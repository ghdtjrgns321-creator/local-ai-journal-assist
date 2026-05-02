"""Feature-based fraud rules: L4-01, L2-01, L1-04, L3-02."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import get_audit_rules


def _check_features(df: pd.DataFrame, required: list[str]) -> list[str]:
    """Return missing feature columns."""
    return [c for c in required if c not in df.columns]


def _get_l104_review_policy(audit_rules: dict | None = None) -> dict[str, tuple[str, ...]]:
    """Return L1-04 contexts treated as review-only by default."""

    rules = audit_rules if audit_rules is not None else get_audit_rules()
    cfg = rules.get("patterns", {}).get("approval_limit_exceeded_review", {})
    return {
        "buckets": tuple(
            str(value).strip().lower()
            for value in cfg.get("review_buckets", ["boundary"])
            if str(value).strip()
        ),
        "sources": tuple(
            str(value).strip().lower()
            for value in cfg.get(
                "review_sources",
                ["automated", "batch", "interface", "system", "recurring"],
            )
            if str(value).strip()
        ),
        "user_personas": tuple(
            str(value).strip().lower().replace(" ", "_")
            for value in cfg.get("review_user_personas", ["automated_system"])
            if str(value).strip()
        ),
    }


def b01_revenue_manipulation(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
) -> pd.Series:
    """L4-01 revenue account outlier: revenue account and high amount z-score."""
    missing = _check_features(df, ["is_revenue_account", "amount_zscore"])
    if missing:
        return pd.Series(False, index=df.index)
    zscore = pd.to_numeric(df["amount_zscore"], errors="coerce").fillna(0.0)
    result = df["is_revenue_account"].fillna(False) & (zscore > zscore_threshold)

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result & zscore.lt(4.0)] = 0.45
    score_series.loc[result & zscore.ge(4.0) & zscore.lt(6.0)] = 0.60
    score_series.loc[result & zscore.ge(6.0)] = 0.75

    bucket = pd.Series("none", index=df.index, dtype="object")
    bucket.loc[result & zscore.lt(4.0)] = "review_zscore"
    bucket.loc[result & zscore.ge(4.0) & zscore.lt(6.0)] = "strong_zscore"
    bucket.loc[result & zscore.ge(6.0)] = "extreme_zscore"

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in result[result].index:
        annotation: dict[str, object] = {
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "amount_zscore": round(float(zscore.loc[idx]), 4),
            "zscore_threshold": float(zscore_threshold),
            "interpretation": "high_value_revenue_outlier_anchor",
        }
        if "gl_account" in df.columns:
            value = df.at[idx, "gl_account"]
            annotation["gl_account"] = None if pd.isna(value) else value
        row_annotations[idx] = annotation

    result.attrs["score_series"] = score_series
    result.attrs["row_annotations"] = row_annotations
    result.attrs["breakdown"] = {
        "interpretation": "high_value_revenue_outlier_anchor",
        "zscore_threshold": float(zscore_threshold),
        "flagged_rows": int(result.sum()),
        "score_bands": {
            "review_zscore": 0.45,
            "strong_zscore": 0.60,
            "extreme_zscore": 0.75,
        },
        "bucket_counts": bucket.loc[result].value_counts().to_dict(),
    }
    return result


def b02_near_threshold(df: pd.DataFrame) -> pd.Series:
    """L2-01 just below approval threshold."""
    if "is_near_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    result = df["is_near_threshold"].fillna(False).astype(bool)

    bucket = (
        df["near_threshold_bucket"].fillna("none").astype(str)
        if "near_threshold_bucket" in df.columns
        else pd.Series("lower_band", index=df.index).where(result, "none")
    )
    score_series = _score_l201_near_threshold(df, result, bucket)

    row_annotations: dict[object, dict[str, object]] = {}
    for idx in result[result].index:
        source = _source_norm_at(df, idx)
        queue_label = _l201_queue_label(score_series.loc[idx], source)
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
            [
                _l201_queue_label(score_series.loc[idx], _source_norm_at(df, idx))
                for idx in result[result].index
            ],
            dtype="object",
        ).value_counts().to_dict(),
        "unresolved_limit_rows": int(bucket.eq("unresolved_limit").sum()),
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def _score_l201_near_threshold(
    df: pd.DataFrame,
    result: pd.Series,
    bucket: pd.Series,
) -> pd.Series:
    """Score L2-01 after separating population capture from risk priority.

    L2-01 should capture every resolved near-threshold document. Risk score is
    only assigned when the context makes the near-threshold amount suspicious.
    Automated and recurring lower/close-band entries are treated as normal
    population hits and therefore receive zero score.
    """

    base_score_map = {
        "lower_band": 0.45,
        "close_band": 0.60,
        "razor_band": 0.75,
    }
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    for bucket_name, score in base_score_map.items():
        score_series.loc[result & bucket.eq(bucket_name)] = score
    score_series.loc[result & score_series.eq(0.0)] = 0.45

    if "source" not in df.columns:
        return score_series.where(result, 0.0)

    source = df["source"].where(df["source"].notna(), "").astype(str).str.strip().str.lower()
    routine_source = source.isin({"automated", "recurring", "batch", "interface", "system"})
    routine_normal = result & routine_source & bucket.isin({"lower_band", "close_band"})
    score_series.loc[routine_normal] = 0.0

    routine_razor = result & routine_source & bucket.eq("razor_band")
    score_series.loc[routine_razor] = score_series.loc[routine_razor].clip(upper=0.35)
    return score_series.where(result, 0.0)


def _source_norm_at(df: pd.DataFrame, idx: object) -> str:
    if "source" not in df.columns:
        return ""
    value = df.at[idx, "source"]
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _l201_queue_label(score: float, source: str) -> str:
    if score <= 0:
        return "normal_population"
    if source in {"automated", "recurring", "batch", "interface", "system"}:
        return "routine_razor_review"
    if score >= 0.75:
        return "priority_review"
    return "review"


def b03_exceeds_threshold(
    df: pd.DataFrame,
    audit_rules: dict | None = None,
) -> pd.Series:
    """L1-04 approval limit exceeded."""
    if "exceeds_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    candidate = df["exceeds_threshold"].fillna(False).astype(bool)
    if "approval_limit_resolved" in df.columns:
        candidate = candidate & df["approval_limit_resolved"].fillna(False).astype(bool)
    if not candidate.any():
        return candidate

    bucket = (
        df["approval_excess_bucket"].fillna("unresolved_limit").astype(str)
        if "approval_excess_bucket" in df.columns
        else pd.Series("unresolved_limit", index=df.index)
    )
    bucket_norm = bucket.str.strip().str.lower()
    review_policy = _get_l104_review_policy(audit_rules)
    review = candidate & bucket_norm.isin(review_policy["buckets"])
    if "source" in df.columns and review_policy["sources"]:
        source_norm = (
            df["source"].where(df["source"].notna(), "").astype(str).str.strip().str.lower()
        )
        review = review | (candidate & source_norm.isin(review_policy["sources"]))
    if "user_persona" in df.columns and review_policy["user_personas"]:
        persona_norm = (
            df["user_persona"]
            .where(df["user_persona"].notna(), "")
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
        )
        review = review | (candidate & persona_norm.isin(review_policy["user_personas"]))
    immediate = candidate & ~review
    score_map = {
        "boundary": 0.45,
        "moderate": 0.60,
        "severe": 0.75,
        "critical": 0.90,
        "non_approver": 0.90,
        "unresolved_limit": 0.60,
    }
    score_series = pd.Series(0.0, index=df.index)
    for bucket_name, score in score_map.items():
        score_series.loc[immediate & bucket_norm.eq(bucket_name)] = score
    score_series.loc[immediate & score_series.eq(0.0)] = 0.60
    review_score_series = pd.Series(0.0, index=df.index)
    review_score_series.loc[review] = 0.4

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
    annotation_df = pd.DataFrame({
        "bucket": bucket.loc[flagged_index].astype(str),
        "score": score_series.loc[flagged_index].round(4),
        "review_score": review_score_series.loc[flagged_index].round(4),
        "queue_label": pd.Series("review", index=flagged_index).where(
            review.loc[flagged_index],
            "immediate",
        ),
    }, index=flagged_index)
    if annotation_columns:
        annotation_df = pd.concat(
            [annotation_df, df.loc[flagged_index, annotation_columns]],
            axis=1,
        )
    row_annotations = annotation_df.astype(object).where(pd.notna(annotation_df), None).to_dict(
        orient="index",
    )

    immediate.attrs["score_series"] = score_series
    immediate.attrs["review_score_series"] = review_score_series
    immediate.attrs["breakdown"] = {
        "bucket_counts": bucket.loc[candidate].value_counts().to_dict(),
        "flagged_rows": int(immediate.sum()),
        "candidate_rows": int(candidate.sum()),
        "immediate_rows": int(immediate.sum()),
        "review_rows": int(review.sum()),
        "review_buckets": list(review_policy["buckets"]),
        "review_sources": list(review_policy["sources"]),
        "review_user_personas": list(review_policy["user_personas"]),
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
        candidate = df["is_manual_je"].fillna(False).astype(bool)
    elif "source" in df.columns:
        if not manual_sources:
            candidate = pd.Series(False, index=df.index)
        else:
            candidate = source_norm.isin(manual_sources)
    else:
        return pd.Series(False, index=df.index)

    if not candidate.any():
        return candidate

    no_approver = (
        df["approved_by"].fillna("").astype(str).str.strip().eq("")
        if "approved_by" in df.columns
        else pd.Series(False, index=df.index)
    )
    has_approver = ~no_approver if "approved_by" in df.columns else pd.Series(False, index=df.index)
    no_approval_date = (
        df["approval_date"].fillna("").astype(str).str.strip().eq("")
        if "approval_date" in df.columns
        else pd.Series(False, index=df.index)
    )
    created = (
        df["created_by"].fillna("").astype(str).str.strip().str.lower()
        if "created_by" in df.columns
        else pd.Series("", index=df.index)
    )
    approved = (
        df["approved_by"].fillna("").astype(str).str.strip().str.lower()
        if "approved_by" in df.columns
        else pd.Series("", index=df.index)
    )
    self_approval = created.ne("") & created.eq(approved)
    exceeds_threshold = (
        df["exceeds_threshold"].fillna(False).astype(bool)
        if "exceeds_threshold" in df.columns
        else pd.Series(False, index=df.index)
    )
    skipped_approval = exceeds_threshold & no_approver
    missing_approval_date = has_approver & no_approval_date

    abnormal_time = pd.Series(False, index=df.index)
    for column in ("is_after_hours", "is_weekend", "is_holiday"):
        if column in df.columns:
            abnormal_time = abnormal_time | df[column].fillna(False).astype(bool)
    if "time_zone_category" in df.columns:
        abnormal_time = abnormal_time | df["time_zone_category"].fillna("").astype(
            str
        ).str.strip().str.lower().isin({"overtime", "midnight"})

    period_end = (
        df["is_period_end"].fillna(False).astype(bool)
        if "is_period_end" in df.columns
        else pd.Series(False, index=df.index)
    )
    weak_description = (
        df["description_quality"].fillna("").astype(str).str.strip().str.lower().isin(
            {"missing", "corrupted", "poor"}
        )
        if "description_quality" in df.columns
        else pd.Series(False, index=df.index)
    )

    high_risk_cfg = rules.get("patterns", {}).get("high_risk_account_use", {})
    legacy_cfg = rules.get("patterns", {}).get("self_approval_immediate_override", {})
    high_risk_accounts = {
        str(v).strip().lower()
        for v in high_risk_cfg.get("accounts", legacy_cfg.get("high_risk_accounts", []))
    }
    high_risk_prefixes = tuple(
        str(v).strip().lower()
        for v in high_risk_cfg.get(
            "account_prefixes",
            legacy_cfg.get("high_risk_account_prefixes", []),
        )
    )
    gl = (
        df["gl_account"].fillna("").astype(str).str.strip().str.lower().str.replace(
            r"\.0+$",
            "",
            regex=True,
        )
        if "gl_account" in df.columns
        else pd.Series("", index=df.index)
    )
    high_risk_account = gl.isin(high_risk_accounts)
    if high_risk_prefixes:
        high_risk_account = high_risk_account | gl.str.startswith(high_risk_prefixes)

    control_bypass = candidate & (self_approval | skipped_approval | missing_approval_date)
    priority = candidate & (
        exceeds_threshold
        | abnormal_time
        | period_end
        | weak_description
        | high_risk_account
    )
    immediate = priority | control_bypass

    bucket = pd.Series("none", index=df.index, dtype="object")
    bucket.loc[candidate & source_norm.eq("adjustment")] = "adjustment_population"
    bucket.loc[candidate & bucket.eq("none")] = "manual_population"
    bucket.loc[priority] = "manual_priority"
    bucket.loc[control_bypass] = "manual_control_bypass"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    review_score_series = pd.Series(0.0, index=df.index, dtype="float64")
    review_score_series.loc[candidate & ~immediate] = 0.35
    score_series.loc[priority] = 0.60
    score_series.loc[control_bypass] = 0.75

    reason_masks = {
        "self_approval": self_approval,
        "skipped_approval": skipped_approval,
        "missing_approval_date": missing_approval_date,
        "high_amount": exceeds_threshold,
        "abnormal_time": abnormal_time,
        "period_end": period_end,
        "weak_description": weak_description,
        "high_risk_account": high_risk_account,
    }
    priority_reason_counts: dict[str, int] = {}
    for reason, mask in reason_masks.items():
        count = int((candidate & mask).sum())
        if count:
            priority_reason_counts[reason] = count

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
    reason_values = {
        reason: mask.loc[candidate_index].to_numpy(dtype=bool)
        for reason, mask in reason_masks.items()
    }
    bucket_values = bucket.loc[candidate_index].astype(str).to_numpy()
    score_values = (
        score_series.combine(review_score_series, max)
        .loc[candidate_index]
        .round(4)
        .to_numpy()
    )
    source_bucket_values = np.where(
        source_norm.loc[candidate_index].eq("adjustment").to_numpy(),
        "adjustment",
        "manual",
    )

    for pos, idx in enumerate(candidate_index):
        annotation: dict[str, object] = {
            "bucket": bucket_values[pos],
            "score": float(score_values[pos]),
            "source_bucket": source_bucket_values[pos],
            "priority_reasons": [
                reason
                for reason, values in reason_values.items()
                if bool(values[pos])
            ],
        }
        annotation.update(optional_values.get(idx, {}))
        row_annotations[idx] = annotation

    immediate.attrs["score_series"] = score_series
    immediate.attrs["review_score_series"] = review_score_series
    immediate.attrs["breakdown"] = {
        "flagged_rows": int(immediate.sum()),
        "candidate_rows": int(candidate.sum()),
        "review_rows": int((candidate & ~immediate).sum()),
        "manual_rows": int((candidate & ~source_norm.eq("adjustment")).sum()),
        "adjustment_rows": int((candidate & source_norm.eq("adjustment")).sum()),
        "priority_rows": int(priority.sum()),
        "control_bypass_rows": int(control_bypass.sum()),
        "source_counts": source_norm.loc[candidate].value_counts().to_dict(),
        "bucket_counts": bucket.loc[candidate].value_counts().to_dict(),
        "priority_reason_counts": priority_reason_counts,
    }
    immediate.attrs["row_annotations"] = row_annotations
    return immediate
