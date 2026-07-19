"""Feature-based fraud rules: L4-01, L2-01, L1-04, L3-02."""

from __future__ import annotations

import pandas as pd

from config.settings import get_audit_rules
from src.detection.boolean_utils import bool_column


def _check_features(df: pd.DataFrame, required: list[str]) -> list[str]:
    """Return missing feature columns."""
    return [c for c in required if c not in df.columns]


def b01_revenue_manipulation(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
) -> pd.Series:
    """L4-01 상대적 고액 매출: 매출계정이고 로그 z-score가 임계 초과면 발화(binary).

    매출은 우편향이라 원금액 z-score(`amount_zscore`)는 극단값이 σ를 부풀려 이상치를
    가린다. 로그변환 z-score(`amount_zscore_log`)를 써서 σ 팽창을 제거한다(피처 근거는
    amount_features.add_amount_zscore_log).
    """
    missing = _check_features(df, ["is_revenue_account", "amount_zscore_log"])
    if missing:
        return pd.Series(False, index=df.index)
    zscore = pd.to_numeric(df["amount_zscore_log"], errors="coerce").fillna(0.0)
    result = df["is_revenue_account"].fillna(False) & (zscore > zscore_threshold)

    # binary flag: 발화=1.0, 미발화=0.0. z-score 폭에 따른 등급 차등(구 bucket)은
    # 폐기 — 강도·정황·조합은 통합점수체계 소관이고 룰은 발화 여부만 결정한다. z-score 값은
    # 사실값으로 row_annotation 에만 남겨 표시·정렬에 통합점수 쪽이 활용한다.
    score_series = result.astype("float64")

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in result[result].index:
        annotation: dict[str, object] = {
            "score": 1.0,
            "amount_zscore_log": round(float(zscore.loc[idx]), 4),
            "zscore_threshold": float(zscore_threshold),
            "interpretation": "relative_high_value_revenue",
        }
        if "gl_account" in df.columns:
            value = df.at[idx, "gl_account"]
            annotation["gl_account"] = None if pd.isna(value) else value
        row_annotations[idx] = annotation

    result.attrs["score_series"] = score_series
    result.attrs["row_annotations"] = row_annotations
    result.attrs["breakdown"] = {
        "interpretation": "relative_high_value_revenue",
        "zscore_threshold": float(zscore_threshold),
        "flagged_rows": int(result.sum()),
    }
    return result


def b02_near_threshold(df: pd.DataFrame) -> pd.Series:
    """L2-01 just below approval threshold."""
    if "is_near_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    result = bool_column(df, "is_near_threshold")

    bucket = (
        df["near_threshold_bucket"].fillna("none").astype(str)
        if "near_threshold_bucket" in df.columns
        else pd.Series("lower_band", index=df.index).where(result, "none")
    )
    score_series = _score_l201_near_threshold(df, result, bucket)

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in result[result].index:
        source = _source_norm_at(df, idx)
        queue_label = _l201_queue_label(score_series.loc[idx])
        annotation: dict[str, object] = {
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "queue_label": queue_label,
            "source": source,
        }
        for column in (
            "near_threshold_amount",
            "near_threshold_limit_amount",
            "near_threshold_ratio_to_limit",
            "near_threshold_gap_amount",
            "near_threshold_gap_ratio",
            "near_threshold_limit_resolved",
        ):
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[idx] = annotation

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "bucket_counts": bucket.loc[result].value_counts().to_dict(),
        "flagged_rows": int(result.sum()),
        "scored_rows": int(score_series.gt(0).sum()),
        "zero_score_rows": int((result & score_series.eq(0)).sum()),
        "queue_counts": pd.Series(
            [_l201_queue_label(score_series.loc[idx]) for idx in result[result].index],
            dtype="object",
        )
        .value_counts()
        .to_dict(),
        "unresolved_limit_rows": int(bucket.eq("unresolved_limit").sum()),
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def _score_l201_near_threshold(
    df: pd.DataFrame,
    result: pd.Series,
    bucket: pd.Series,
) -> pd.Series:
    """Return binary L2-01 flags for resolved near-threshold hits."""

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result & bucket.isin({"lower_band", "close_band", "razor_band"})] = 1.0
    return score_series.where(result, 0.0)


def _source_norm_at(df: pd.DataFrame, idx: object) -> str:
    if "source" not in df.columns:
        return ""
    value = df.at[idx, "source"]
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _l201_queue_label(score: float) -> str:
    if score <= 0:
        return "normal_population"
    if score >= 1.0:
        return "priority_review"
    return "review"


def b03_exceeds_threshold(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-04 approval limit exceeded or approved by a user without authority."""
    if "exceeds_threshold" not in df.columns:
        return pd.Series(False, index=df.index)

    has_approver = (
        df["approved_by"].fillna("").astype(str).str.strip().ne("")
        if "approved_by" in df.columns
        else pd.Series(True, index=df.index)
    )
    limit_resolved = (
        bool_column(df, "approval_limit_resolved")
        if "approval_limit_resolved" in df.columns
        else pd.Series(True, index=df.index)
    )
    can_approve = (
        df["approver_can_approve_je"].astype("boolean").fillna(True).astype(bool)
        if "approver_can_approve_je" in df.columns
        else pd.Series(True, index=df.index)
    )
    approver_in_master = (
        df["approver_in_master"].astype("boolean").fillna(True).astype(bool)
        if "approver_in_master" in df.columns
        else pd.Series(True, index=df.index)
    )
    amount_exceeded = bool_column(df, "exceeds_threshold") & limit_resolved
    no_authority = has_approver & approver_in_master & can_approve.eq(False)
    if "approval_limit_resolved" in df.columns:
        no_authority = no_authority | (has_approver & approver_in_master & ~limit_resolved)
    candidate = has_approver & (amount_exceeded | no_authority)
    if not candidate.any():
        return candidate

    bucket = (
        df["approval_excess_bucket"].fillna("unresolved_limit").astype(str)
        if "approval_excess_bucket" in df.columns
        else pd.Series("unresolved_limit", index=df.index)
    )
    immediate = candidate
    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[candidate] = 1.0
    review_score_series = pd.Series(0.0, index=df.index)

    flagged_index = candidate[candidate].index
    annotation_columns = [
        column
        for column in (
            "document_approval_amount",
            "approver_limit_amount",
            "approval_excess_amount",
            "approval_excess_ratio",
            "approval_limit_resolved",
            "approver_can_approve_je",
            "approval_level",
        )
        if column in df.columns
    ]
    annotation_df = pd.DataFrame(
        {
            "bucket": bucket.loc[flagged_index].astype(str),
            "score": score_series.loc[flagged_index].round(4),
            "review_score": review_score_series.loc[flagged_index].round(4),
            "queue_label": pd.Series("binary_flag", index=flagged_index),
            "reason_code": pd.Series("approval_limit_or_authority", index=flagged_index),
        },
        index=flagged_index,
    )
    if annotation_columns:
        annotation_df = pd.concat(
            [annotation_df, df.loc[flagged_index, annotation_columns]],
            axis=1,
        )
    row_annotations = (
        annotation_df.astype(object)
        .where(pd.notna(annotation_df), None)
        .to_dict(
            orient="index",
        )
    )

    immediate.attrs["score_series"] = score_series
    immediate.attrs["review_score_series"] = review_score_series
    immediate.attrs["breakdown"] = {
        "bucket_counts": bucket.loc[candidate].value_counts().to_dict(),
        "flagged_rows": int(immediate.sum()),
        "candidate_rows": int(candidate.sum()),
        "immediate_rows": int(immediate.sum()),
        "review_rows": 0,
        "amount_exceeded_rows": int((candidate & amount_exceeded).sum()),
        "no_authority_rows": int((candidate & no_authority).sum()),
    }
    immediate.attrs["row_annotations"] = row_annotations
    return immediate


def b08_manual_override(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L3-02 manual entry: source/manual feature only."""
    rules = audit_rules if audit_rules is not None else get_audit_rules()
    manual_sources = {
        str(v).strip().lower()
        for v in rules.get("patterns", {}).get("manual_source_codes", ["manual", "adjustment"])
    }
    source_norm = (
        df["source"].fillna("").astype(str).str.strip().str.lower()
        if "source" in df.columns
        else pd.Series("", index=df.index)
    )

    if "is_manual_je" in df.columns:
        candidate = bool_column(df, "is_manual_je")
    elif "source" in df.columns:
        if not manual_sources:
            candidate = pd.Series(False, index=df.index)
        else:
            candidate = source_norm.isin(manual_sources)
    else:
        candidate = pd.Series(False, index=df.index)

    score_series = candidate.astype(float)

    candidate_index = candidate[candidate].index
    row_annotations: dict[object, dict[str, object]] = {}
    optional_columns = [
        column
        for column in (
            "document_id",
            "source",
            "created_by",
            "approved_by",
            "approval_date",
            "business_process",
            "gl_account",
            "description_quality",
        )
        if column in df.columns
    ]
    optional_values = (
        df.loc[candidate_index, optional_columns]
        .astype(object)
        .where(pd.notna(df.loc[candidate_index, optional_columns]), None)
        .to_dict(orient="index")
        if optional_columns
        else {}
    )

    for idx in candidate_index:
        annotation: dict[str, object] = {"score": 1.0}
        annotation.update(optional_values.get(idx, {}))
        row_annotations[idx] = annotation

    candidate.attrs["score_series"] = score_series
    candidate.attrs["breakdown"] = {
        "flagged_rows": int(candidate.sum()),
        "manual_rows": int((candidate & ~source_norm.eq("adjustment")).sum()),
        "adjustment_rows": int((candidate & source_norm.eq("adjustment")).sum()),
        "source_counts": source_norm.loc[candidate].value_counts().to_dict(),
    }
    candidate.attrs["row_annotations"] = row_annotations
    return candidate
