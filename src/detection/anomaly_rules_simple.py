"""피처 기반 이상 징후 룰 — L3-04~L3-07, L4-03, L3-09, L4-05.

피처 엔진(src/feature/)이 미리 생성한 bool/float 컬럼을 조합하는 마스크 연산.
피처 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.detection.boolean_utils import bool_column
from src.detection.source_trust import lone_automated_mask


def c01_period_end_large(
    df: pd.DataFrame,
    period_end_margin_days: int = 5,
) -> pd.Series:
    """L3-04 period-end/start binary review population."""
    if "is_period_end" not in df.columns and "is_period_start" not in df.columns:
        return pd.Series(False, index=df.index)

    period_end = bool_column(df, "is_period_end")
    period_start = bool_column(df, "is_period_start")
    flagged = period_end | period_start
    flagged = flagged.astype(bool)
    score_series = flagged.astype(float)
    period_phase = _period_phase_series(
        df,
        period_start=period_start,
        period_end=period_end,
        margin_days=period_end_margin_days,
    )

    flagged_index = flagged[flagged].index
    row_annotations: dict[int, dict[str, object]] = {}
    optional_columns = [
        column
        for column in (
            "document_id",
            "posting_date",
            "source",
            "created_by",
            "approved_by",
            "business_process",
            "account_group",
            "gl_account",
        )
        if column in df.columns
    ]
    optional_values = (
        df.loc[flagged_index, optional_columns]
        .astype(object)
        .where(pd.notna(df.loc[flagged_index, optional_columns]), None)
        .to_dict(orient="index")
        if optional_columns
        else {}
    )
    annotation_frame = pd.DataFrame(
        {
            "period_phase": period_phase.loc[flagged_index].astype(object),
            "score": score_series.loc[flagged_index].round(4),
        },
        index=flagged_index,
    ).astype(object)
    annotation_frame = annotation_frame.where(pd.notna(annotation_frame), None)

    # Why: 480k 회 .loc[idx].to_dict() (~22s) → 단일 to_dict(orient="index") (~5s)
    annotation_dict = annotation_frame.to_dict(orient="index")
    for idx in flagged_index:
        annotation = annotation_dict[idx]
        annotation["score"] = float(annotation["score"])
        annotation.update(optional_values.get(idx, {}))
        row_annotations[int(idx)] = annotation

    flagged.attrs["score_series"] = score_series
    flagged.attrs["breakdown"] = {
        "flagged_rows": int(flagged.sum()),
        "period_end_rows": int((flagged & period_phase.eq("end")).sum()),
        "period_start_rows": int((flagged & period_phase.eq("start")).sum()),
        "source_counts": (
            df.loc[flagged, "source"].fillna("<missing>").astype(str).value_counts().to_dict()
            if "source" in df.columns
            else {}
        ),
    }
    flagged.attrs["row_annotations"] = row_annotations
    return flagged


def _period_phase_series(
    df: pd.DataFrame,
    *,
    period_start: pd.Series,
    period_end: pd.Series,
    margin_days: int,
) -> pd.Series:
    """Return L3-04 phase labels: start, end, or none."""
    phase = pd.Series("none", index=df.index, dtype="object")
    phase.loc[period_end] = "end"
    phase.loc[period_start] = "start"

    if "posting_date" not in df.columns:
        return phase

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce")
    day = posting_date.dt.day
    days_in_month = posting_date.dt.days_in_month
    margin = max(int(margin_days), 1)
    inferred_start = day.between(1, margin, inclusive="both").fillna(False)
    inferred_end = day.ge(days_in_month - margin + 1).fillna(False)
    inferable = period_end & ~period_start
    phase.loc[inferable & inferred_start] = "start"
    phase.loc[inferable & inferred_end] = "end"
    return phase


def _abnormal_time_mask(df: pd.DataFrame) -> pd.Series:
    abnormal = pd.Series(False, index=df.index)
    for column in ("is_after_hours", "is_weekend", "is_holiday"):
        if column in df.columns:
            abnormal = abnormal | bool_column(df, column)
    if "time_zone_category" in df.columns:
        time_zone = df["time_zone_category"].fillna("").astype(str).str.strip().str.lower()
        abnormal = abnormal | time_zone.isin({"overtime", "midnight"})
    return abnormal


def _approval_control_signal_mask(df: pd.DataFrame) -> pd.Series:
    result = pd.Series(False, index=df.index)
    for mask in _approval_control_reason_masks(df).values():
        result = result | mask
    return result


def _approval_control_reason_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    masks: dict[str, pd.Series] = {}
    if {"created_by", "approved_by"}.issubset(df.columns):
        created = df["created_by"].fillna("").astype(str).str.strip().str.lower()
        approved = df["approved_by"].fillna("").astype(str).str.strip().str.lower()
        masks["self_approval"] = created.ne("") & created.eq(approved)
    if "approved_by" in df.columns and "exceeds_threshold" in df.columns:
        no_approver = df["approved_by"].fillna("").astype(str).str.strip().eq("")
        masks["skipped_approval"] = bool_column(df, "exceeds_threshold") & no_approver
    if {"approved_by", "approval_date"}.issubset(df.columns):
        has_approver = df["approved_by"].fillna("").astype(str).str.strip().ne("")
        no_approval_date = df["approval_date"].fillna("").astype(str).str.strip().eq("")
        masks["approval_date_absent"] = has_approver & no_approval_date
    return masks


def _approval_control_reasons(df: pd.DataFrame, idx: Any) -> list[str]:
    reasons: list[str] = []
    if {"created_by", "approved_by"}.issubset(df.columns):
        created = str(df.at[idx, "created_by"] or "").strip().lower()
        approved = str(df.at[idx, "approved_by"] or "").strip().lower()
        if created and created == approved:
            reasons.append("self_approval")
    if "approved_by" in df.columns and "exceeds_threshold" in df.columns:
        no_approver = str(df.at[idx, "approved_by"] or "").strip() == ""
        if bool_column(df, "exceeds_threshold").at[idx] and no_approver:
            reasons.append("skipped_approval")
    if {"approved_by", "approval_date"}.issubset(df.columns):
        has_approver = str(df.at[idx, "approved_by"] or "").strip() != ""
        no_approval_date = str(df.at[idx, "approval_date"] or "").strip() == ""
        if has_approver and no_approval_date:
            reasons.append("approval_date_absent")
    return reasons


def _coerce_nullable_bool(series: pd.Series) -> pd.Series:
    """Coerce common bool-like accounting exports while preserving unknowns."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype("boolean")
    if pd.api.types.is_numeric_dtype(series.dtype):
        numeric = pd.to_numeric(series, errors="coerce")
        result = pd.Series(pd.NA, index=series.index, dtype="boolean")
        result.loc[numeric.notna()] = numeric.loc[numeric.notna()].ne(0)
        return result

    text = series.astype("string").str.strip().str.lower()
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    true_values = {"true", "t", "1", "yes", "y", "cleared", "closed", "settled", "resolved"}
    false_values = {"false", "f", "0", "no", "n", "open", "uncleared", "unsettled", "unresolved"}
    result.loc[text.isin(true_values)] = True
    result.loc[text.isin(false_values)] = False
    return result


def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    """Return distinct document count for rows selected by mask."""
    if "document_id" not in df.columns:
        return 0
    return int(df.loc[mask.reindex(df.index, fill_value=False), "document_id"].dropna().nunique())


def c02_weekend_entry(df: pd.DataFrame) -> pd.Series:
    """L3-05 주말 전기: 토/일 또는 공휴일 전기.

    Why: PCAOB AS 240 A49(c) — 비정상 시점 거래는 승인 우회 의심.
    """
    weekend = bool_column(df, "is_weekend")
    holiday = bool_column(df, "is_holiday")
    flagged = weekend | holiday
    score_series = flagged.astype(float)

    breakdown = {
        "flagged_rows": int(flagged.sum()),
        "weekend_rows": int(weekend.sum()),
        "holiday_rows": int(holiday.sum()),
        "source_counts": (
            df.loc[flagged, "source"].fillna("<missing>").astype(str).value_counts().to_dict()
            if "source" in df.columns
            else {}
        ),
    }
    if "document_id" in df.columns:
        breakdown.update(
            {
                "flagged_docs": _nunique_documents(df, flagged),
                "weekend_docs": _nunique_documents(df, weekend),
                "holiday_docs": _nunique_documents(df, holiday),
            }
        )

    row_annotations: dict[int, dict[str, object]] = {}
    optional_columns = [
        column for column in ("document_id", "posting_date", "source") if column in df.columns
    ]
    optional_values = (
        df.loc[flagged, optional_columns]
        .astype(object)
        .where(pd.notna(df.loc[flagged, optional_columns]), None)
        .to_dict(orient="index")
        if optional_columns
        else {}
    )
    for idx in df.index[flagged]:
        annotation = {
            "score": 1.0,
            "is_weekend": bool(weekend.loc[idx]),
            "is_holiday": bool(holiday.loc[idx]),
        }
        annotation.update(optional_values.get(idx, {}))
        row_annotations[int(idx)] = annotation

    result = flagged.astype(bool)
    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = breakdown
    result.attrs["row_annotations"] = row_annotations
    return result


def c03_after_hours_entry(df: pd.DataFrame) -> pd.Series:
    """L3-06 심야 전기: 감사인이 설정한 심야 시간대 전기.

    Why: PCAOB AS 240 A49(c) — 심야 전기는 감시 부재 시점 악용 가능.
    L3-05(주말/공휴일)와 L4-05(비정상 시간대 집중)와 중복되지 않도록
    L3-06은 is_after_hours만 사용한다.
    """
    if "is_after_hours" not in df.columns:
        return pd.Series(False, index=df.index)

    result = bool_column(df, "is_after_hours").astype(bool)
    score_series = result.astype(float)
    posting = (
        pd.to_datetime(df["posting_date"], errors="coerce")
        if "posting_date" in df.columns
        else pd.Series(pd.NaT, index=df.index)
    )
    source_values = (
        df["source"].fillna("").astype(str).str.strip()
        if "source" in df.columns
        else pd.Series("", index=df.index)
    )
    time_buckets: dict[str, int] = {}
    row_annotations: dict[int, dict[str, object]] = {}
    for idx in result[result].index:
        posting_value = posting.loc[idx]
        hour = posting_value.hour if pd.notna(posting_value) else None
        if hour is None:
            time_bucket = "unknown_time"
        elif hour < 6:
            time_bucket = "midnight_00_05"
        else:
            time_bucket = "late_evening_22_23"
        time_buckets[time_bucket] = time_buckets.get(time_bucket, 0) + 1
        row_annotations[int(idx)] = {
            "score": 1.0,
            "time_bucket": time_bucket,
            "posting_date": posting_value.isoformat() if pd.notna(posting_value) else "",
            "source": str(df.at[idx, "source"]) if "source" in df.columns else "",
            "created_by": str(df.at[idx, "created_by"]) if "created_by" in df.columns else "",
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "after_hours_rows": int(result.sum()),
        "source_counts": {
            str(key): int(value)
            for key, value in source_values.loc[result].value_counts(dropna=False).items()
            if str(key)
        },
        "time_bucket_counts": time_buckets,
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def c04_backdated_entry(
    df: pd.DataFrame,
    threshold_days: int = 30,
) -> pd.Series:
    """L3-07 전기일-문서일 장기 괴리: 두 날짜 차이의 절댓값이 임계 초과.

    Why: PCAOB AS 240 A49(c), FSS 횡령 은폐 — 과도한 지연/선전기성 날짜
    괴리는 기록 조작 또는 기간귀속 왜곡 검토 신호.
    """
    if "days_backdated" not in df.columns:
        return pd.Series(False, index=df.index)

    days = pd.to_numeric(df["days_backdated"], errors="coerce").fillna(0)
    abs_gap = days.abs()
    result = (abs_gap > threshold_days).astype(bool)
    score_series = result.astype(float)

    row_annotations: dict[object, dict[str, object]] = {}
    optional_columns = (
        "document_id",
        "posting_date",
        "document_date",
        "entry_date",
        "created_at",
        "source",
        "created_by",
        "business_process",
        "document_type",
    )
    for idx in result[result].index:
        annotation: dict[str, object] = {
            "score": 1.0,
            "days_backdated": int(days.loc[idx]),
            "abs_gap_days": int(abs_gap.loc[idx]),
            "threshold_days": int(threshold_days),
        }
        for column in optional_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        row_annotations[annotation_key] = annotation

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "flagged_rows": int(result.sum()),
        "threshold_days": int(threshold_days),
    }
    result.attrs["row_annotations"] = row_annotations
    return result


def _normalized_values(value: object) -> set[str]:
    """Return lower-case string values for config matching."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, (list, tuple, set)):
        return {str(v).lower() for v in value if pd.notna(v)}
    return {str(value).lower()}


def _matches_any(series: pd.Series, allowed: object) -> pd.Series:
    values = _normalized_values(allowed)
    if not values:
        return pd.Series(False, index=series.index)
    return series.astype("string").str.lower().isin(values).fillna(False)


def _expected_period(date_series: pd.Series, fiscal_year_start: int) -> pd.Series:
    month = pd.to_datetime(date_series, errors="coerce").dt.month
    return (month - fiscal_year_start) % 12 + 1


def _period_distance(actual: object, expected: object) -> int | None:
    try:
        actual_int = int(actual)
        expected_int = int(expected)
    except (TypeError, ValueError):
        return None
    if not 1 <= actual_int <= 16 or not 1 <= expected_int <= 12:
        return None
    if actual_int > 12:
        return None
    raw_distance = abs(actual_int - expected_int)
    return min(raw_distance, 12 - raw_distance)


def _l108_context_mask(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    return bool_column(df, column)


def _l108_amount_context(df: pd.DataFrame) -> pd.Series:
    if "exceeds_threshold" in df.columns:
        return _l108_context_mask(df, "exceeds_threshold")
    if "amount_zscore" in df.columns:
        zscore = pd.to_numeric(df["amount_zscore"], errors="coerce").abs()
        return zscore.ge(3.0).fillna(False)
    return pd.Series(False, index=df.index, dtype=bool)


def c05_fiscal_period_mismatch(
    df: pd.DataFrame,
    policy: dict | None = None,
) -> pd.Series:
    """L1-08 기간 불일치: 회계기간 ≠ 전기월.

    Why: PCAOB AS 240 §32(b) — 기간 귀속 오류는 의도적 기간 이동 가능성.
    """
    raw = df.get("fiscal_period_mismatch")
    if raw is None:
        raw = pd.Series(False, index=df.index, dtype="boolean")
    else:
        raw = raw.fillna(False).astype("boolean")

    cfg = policy or {}
    strict_mode = bool(cfg.get("strict_mode", True))
    fiscal_year_start = int(cfg.get("fiscal_year_start", 1))
    exempted = pd.Series(False, index=df.index)

    if not strict_mode and "fiscal_period" in df.columns:
        allow_special = bool(cfg.get("allow_special_periods", False))
        special_periods = set(cfg.get("special_periods") or [])
        if allow_special and special_periods:
            special_allowed = df["fiscal_period"].isin(special_periods).fillna(False)
            if "special_period_allowed_sources" in cfg and "source" in df.columns:
                special_allowed &= _matches_any(
                    df["source"],
                    cfg.get("special_period_allowed_sources"),
                )
            if "special_period_allowed_document_types" in cfg and "document_type" in df.columns:
                special_allowed &= _matches_any(
                    df["document_type"],
                    cfg.get("special_period_allowed_document_types"),
                )
            if (
                "special_period_allowed_business_processes" in cfg
                and "business_process" in df.columns
            ):
                special_allowed &= _matches_any(
                    df["business_process"],
                    cfg.get("special_period_allowed_business_processes"),
                )
            exempted |= special_allowed.fillna(False)

        basis_by_process = cfg.get("period_basis_by_process") or {}
        if basis_by_process and "business_process" in df.columns:
            for process, basis_col in basis_by_process.items():
                if basis_col not in df.columns:
                    continue
                process_mask = _matches_any(df["business_process"], [process])
                has_null = df[basis_col].isna() | df["fiscal_period"].isna()
                basis_match = df["fiscal_period"].eq(
                    _expected_period(df[basis_col], fiscal_year_start),
                )
                exempted |= (process_mask & ~has_null & basis_match).fillna(False)

        basis_by_source = cfg.get("period_basis_by_source") or {}
        if basis_by_source and "source" in df.columns:
            for source, basis_col in basis_by_source.items():
                if basis_col not in df.columns:
                    continue
                source_mask = _matches_any(df["source"], [source])
                has_null = df[basis_col].isna() | df["fiscal_period"].isna()
                basis_match = df["fiscal_period"].eq(
                    _expected_period(df[basis_col], fiscal_year_start),
                )
                exempted |= (source_mask & ~has_null & basis_match).fillna(False)

    final = (raw & ~exempted).astype("boolean").fillna(False)
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[final.astype(bool)] = 1.0
    context_masks = {
        "period_end": _l108_context_mask(df, "is_period_end"),
        "manual_entry": _l108_context_mask(df, "is_manual_je"),
        "high_amount": _l108_amount_context(df),
        "date_gap": _l108_context_mask(df, "has_date_gap")
        | _l108_context_mask(df, "backdated_flag"),
        "approval_issue": _l108_context_mask(df, "has_approval_date_absent")
        | _l108_context_mask(df, "approval_missing")
        | _l108_context_mask(df, "approval_bypass"),
    }
    if "days_backdated" in df.columns:
        days = pd.to_numeric(df["days_backdated"], errors="coerce").abs()
        context_masks["date_gap"] = context_masks["date_gap"] | days.gt(30).fillna(False)
    if "source" in df.columns:
        source = df["source"].fillna("").astype(str).str.strip().str.lower()
        context_masks["manual_entry"] = context_masks["manual_entry"] | source.isin(
            {"manual", "adjustment"}
        )

    context_count = sum(mask.astype(int) for mask in context_masks.values())

    expected_period = (
        _expected_period(df["posting_date"], fiscal_year_start)
        if "posting_date" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    actual_period = (
        pd.to_numeric(df["fiscal_period"], errors="coerce")
        if "fiscal_period" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    row_annotations: dict[object, dict[str, object]] = {}
    for idx in final[final].index:
        active_contexts = [
            name for name, mask in context_masks.items() if bool(mask.reindex(df.index).loc[idx])
        ]
        bucket = "period_mismatch_corroborated" if active_contexts else "period_mismatch_confirmed"
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        expected = expected_period.loc[idx]
        actual = actual_period.loc[idx]
        annotation: dict[str, object] = {
            "bucket": bucket,
            "score": round(float(score_series.loc[idx]), 4),
            "actual_period": None if pd.isna(actual) else int(actual),
            "expected_period": None if pd.isna(expected) else int(expected),
            "period_distance": _period_distance(actual, expected),
            "context_reasons": active_contexts,
            "strict_mode": strict_mode,
            "policy_exempted": bool(exempted.loc[idx]),
        }
        for column in (
            "document_id",
            "posting_date",
            "document_date",
            "source",
            "document_type",
            "business_process",
            "is_period_end",
            "is_manual_je",
            "days_backdated",
        ):
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[annotation_key] = annotation

    raw_count = int(raw.fillna(False).sum())
    exempted_count = int((raw.fillna(False) & exempted).sum())
    final.attrs["raw_fiscal_period_mismatch_count"] = raw_count
    final.attrs["policy_exempted_count"] = exempted_count
    final.attrs["breakdown"] = {
        "raw_fiscal_period_mismatch_rows": raw_count,
        "policy_exempted_rows": exempted_count,
        "final_l108_rows": int(final.sum()),
        "strict_mode": strict_mode,
        "corroborated_rows": int((final & context_count.gt(0)).sum()),
    }
    final.attrs["score_series"] = score_series.where(final, 0.0)
    final.attrs["row_annotations"] = row_annotations
    return final


def _match_subtype_patterns(
    subtype_series: pd.Series,
    patterns: list[str],
) -> pd.Series:
    """대소문자 무시 부분일치로 subtype 패턴을 매칭한다.

    Why: config에서 관리하는 패턴 목록(대문자 기준)을 실제 데이터 subtype에
         대소문자 무시 부분일치로 적용 — 하드코딩 금지 정책 준수.
    """
    if not patterns:
        return pd.Series(False, index=subtype_series.index)
    upper = subtype_series.str.upper().fillna("")
    mask = pd.Series(False, index=subtype_series.index)
    for pat in patterns:
        mask = mask | upper.str.contains(pat.upper(), na=False)
    return mask


def _compute_pbt_thresholds(
    df: pd.DataFrame,
    company_col: str,
    year_col: str,
    debit: pd.Series,
    credit: pd.Series,
    subtype: pd.Series,
    mc: dict[str, Any],
) -> dict[tuple[str, Any], dict[str, float | str | None]]:
    """회사×연도 단위 수행중요성 임계(threshold)와 근거 basis를 산출한다.

    Why: PCAOB AS 2101 / ISA 320 — 수행중요성(PM)은 engagement별로 결정된다.
         이익은 **마감분개(income_statement_close)가 닫은 손익계정 순액 = NI** 로 우선 산출한다
         (키워드 분류 없이 GL이 실제로 확정한 손익이라 정확). 마감분개가 없는(연중) 데이터는
         수익·비용 subtype 키워드 합산으로 fallback 한다.
         법인세는 OPEX_TAX 등에 세금과공과와 섞여 분리가 부정확하므로 떼지 않고 NI 기준을 쓴다.
         저마진·손익분기 근처는 이익 기준 임계가 비현실적으로 낮아지므로 매출 기준을 floor 로 둔다
         (ISA 320: PBT 변동·손익분기 근처는 매출/총자산 벤치마크). materiality_amount > 0 이면 override.
    """
    rev_patterns = mc.get("revenue_subtype_patterns", [])
    exp_patterns = mc.get("expense_subtype_patterns", [])
    excl_patterns = mc.get("exclude_subtype_patterns", [])
    closing_sub = mc.get("closing_subtype", "")
    closing_header_patterns = mc.get("closing_header_patterns", [])
    income_prefixes = [str(p) for p in mc.get("income_account_prefixes", [])]
    pbt_pct = float(mc.get("pbt_pct", 0.05))
    rev_pct = float(mc.get("rev_pct", 0.005))
    pm_ratio = float(mc.get("pm_ratio", 0.75))
    override = float(mc.get("materiality_amount", 0))

    subtype_upper = subtype.str.upper().fillna("")
    is_closing = subtype_upper == closing_sub.upper()
    # Why: DataSynth는 연말 손익 마감 분개를 income_statement_close subtype이 아니라
    #      원래 손익 subtype(REVENUE/COGS/OPEX)으로 태깅하고 header_text에만 마감 표시를
    #      남긴다. 이를 잡지 못하면 마감 차변이 매출 대변을 상쇄해 매출≈0 → 중요성 붕괴.
    #      패턴은 config(closing_header_patterns)로 관리 — 실 ERP는 마감 문서유형/헤더를 매핑.
    if closing_header_patterns and "header_text" in df.columns:
        header_upper = df["header_text"].fillna("").astype(str).str.upper()
        header_close = pd.Series(False, index=df.index)
        for pat in closing_header_patterns:
            header_close = header_close | header_upper.str.contains(
                str(pat).upper(), na=False, regex=False
            )
        is_closing = is_closing | header_close
    not_excluded = ~_match_subtype_patterns(subtype, excl_patterns)
    base_mask = ~is_closing & not_excluded

    is_revenue = base_mask & _match_subtype_patterns(subtype, rev_patterns)
    is_expense = base_mask & _match_subtype_patterns(subtype, exp_patterns)

    # 마감분개 손익계정 라인(NI 역산용): closing AND 손익 prefix
    if income_prefixes and "gl_account" in df.columns:
        gl_first = df["gl_account"].astype(str).str.strip().str[:1]
        is_closing_income = is_closing & gl_first.isin(income_prefixes)
    else:
        is_closing_income = pd.Series(False, index=df.index)

    result: dict[tuple[str, Any], dict[str, float | str | None]] = {}
    groups = df.groupby([company_col, year_col])
    for (cc, yr), idx in groups.groups.items():
        if override > 0:
            result[(cc, yr)] = {
                "threshold": override,
                "threshold_basis": "override",
                "income": None,
                "revenue": None,
            }
            continue

        rev_idx = idx[is_revenue.loc[idx]]
        rev_val = float(credit.loc[rev_idx].sum() - debit.loc[rev_idx].sum())

        # 이익(NI): 마감분개 우선, 없으면 키워드 합산 fallback
        close_idx = idx[is_closing_income.loc[idx]]
        if len(close_idx) > 0:
            # 마감분개가 수익을 차변·비용을 대변으로 닫으므로 (debit-credit)=순이익
            income = float(debit.loc[close_idx].sum() - credit.loc[close_idx].sum())
            income_basis = "closing_ni"
        else:
            exp_idx = idx[is_expense.loc[idx]]
            exp_val = float(debit.loc[exp_idx].sum() - credit.loc[exp_idx].sum())
            income = rev_val - exp_val
            income_basis = "keyword_pbt"

        # 매출 기준 floor (저마진·손익분기 근처는 이익 대신 매출 벤치마크)
        rev_floor = rev_val * rev_pct * pm_ratio if rev_val > 0 else 0.0

        if income > 0:
            income_thr = income * pbt_pct * pm_ratio
            if income_thr >= rev_floor:
                threshold, basis = income_thr, income_basis
            else:
                threshold, basis = rev_floor, "revenue_floor"
        elif rev_val > 0:
            threshold, basis = rev_floor, "revenue"
        else:
            # 매출·이익 모두 산출 불가 — fallback 정책 미결정(추후 결정), 발화 0
            result[(cc, yr)] = {
                "threshold": None,
                "threshold_basis": "unset",
                "income": income,
                "revenue": rev_val,
            }
            continue

        result[(cc, yr)] = {
            "threshold": threshold,
            "threshold_basis": basis,
            "income": income,
            "revenue": rev_val,
        }

    return result


def c08_amount_outlier(
    df: pd.DataFrame,
    materiality_config: dict[str, Any] | None = None,
) -> pd.Series:
    """L4-03 이상 고액: 수행중요성 절대임계(PM) 초과 binary 발화.

    Why: PCAOB AS 2101 / ISA 320 — 수행중요성(PM) 초과 금액 전표는 감사인 리뷰 대상.
         z-score 통계 모집단 대비 PM 기반 절대임계가 감사 기준에 더 직접적으로 대응하며,
         회사×연도별 재무 규모에 비례하여 임계가 결정된다.

    Args:
        df: 전표 DataFrame. 필수 컬럼: debit_amount, credit_amount, company_code,
            fiscal_year, semantic_account_subtype.
        materiality_config: audit_rules.yaml의 patterns.l403_materiality 블록.
                            None이면 빈 dict로 처리(threshold=unset → 발화 0).
    """
    mc: dict[str, Any] = materiality_config or {}

    required = {"debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return pd.Series(False, index=df.index)

    company_col = "company_code" if "company_code" in df.columns else None
    year_col = "fiscal_year" if "fiscal_year" in df.columns else None

    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    base_amount = pd.concat([debit, credit], axis=1).max(axis=1)

    subtype: pd.Series
    if "semantic_account_subtype" in df.columns:
        subtype = df["semantic_account_subtype"].fillna("").astype(str)
    else:
        subtype = pd.Series("", index=df.index, dtype="str")

    # 회사×연도 단위 임계 산출
    thresholds_map: dict[tuple[Any, Any], dict[str, float | str | None]] = {}
    unset_groups: set[tuple[Any, Any]] = set()

    if company_col and year_col:
        thresholds_map = _compute_pbt_thresholds(
            df, company_col, year_col, debit, credit, subtype, mc
        )
        unset_groups = {k for k, v in thresholds_map.items() if v["threshold_basis"] == "unset"}
    else:
        # grouping 컬럼 없으면 threshold=None (unset)
        pass

    # 라인 단위 발화 판정
    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    row_annotations: dict[object, dict[str, object]] = {}

    if company_col and year_col:
        for idx in df.index:
            cc = df.at[idx, company_col]
            yr = df.at[idx, year_col]
            key = (cc, yr)
            info = thresholds_map.get(key, {"threshold": None, "threshold_basis": "unset"})
            thr = info["threshold"]
            basis = info["threshold_basis"]
            ba = float(base_amount.loc[idx])
            if thr is not None and ba >= thr:
                score_series.loc[idx] = 1.0
                annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
                row_annotations[annotation_key] = {
                    "base_amount": ba,
                    "threshold": float(thr),
                    "threshold_basis": str(basis),
                    "exceed_ratio": round(ba / thr, 4) if thr > 0 else None,
                }
            elif thr is None:
                # threshold 산출 불가 — 발화 0, annotation에 "threshold_unset" 표기
                annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
                row_annotations[annotation_key] = {
                    "base_amount": ba,
                    "threshold": None,
                    "threshold_basis": "unset",
                    "exceed_ratio": None,
                }

    result = (score_series > 0).astype(bool)

    # breakdown 집계
    flagged_count = int(result.sum())
    unset_cy_count = len(unset_groups)
    breakdown: dict[str, object] = {
        "high_amount_review_rows": flagged_count,
        "threshold_unset_company_years": unset_cy_count,
    }
    if "document_id" in df.columns:
        breakdown["high_amount_review_docs"] = _nunique_documents(df, result)

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = breakdown
    result.attrs["row_annotations"] = row_annotations
    return result


def c10_suspense_account(
    df: pd.DataFrame,
    threshold_days: int = 30,
    min_open_amount: float = 0.0,
) -> pd.Series:
    """L3-09 가수금 장기체류: 가계정이 장기간 미정리(open) 상태로 남아 있는 전표.

    Why: 외감법 §8①2호, FSS 횡령 은폐 사례 — 가수금·임시계정은 단순 사용 자체보다
         일정 기간 내 정리되지 않고 잔존하는 상태가 더 실질적인 검토 대상이다.
    """
    if "is_suspense_account" not in df.columns or "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)

    suspense = _coerce_nullable_bool(df["is_suspense_account"]).fillna(False)
    if not suspense.any():
        return suspense.astype(bool)

    posting = pd.to_datetime(df["posting_date"], errors="coerce")
    if posting.notna().sum() == 0:
        return pd.Series(False, index=df.index)

    dataset_end = posting.max()
    if pd.isna(dataset_end):
        return pd.Series(False, index=df.index)

    unresolved = pd.Series(False, index=df.index)
    resolution_signal_present = pd.Series(False, index=df.index)

    if "amount_open" in df.columns:
        amount_open = pd.to_numeric(df["amount_open"], errors="coerce")
        amount_present = amount_open.notna()
        resolution_signal_present = resolution_signal_present | amount_present
        unresolved = unresolved | (amount_present & (amount_open.abs() > min_open_amount))

    if "is_cleared" in df.columns:
        cleared = _coerce_nullable_bool(df["is_cleared"])
        cleared_present = cleared.notna()
        resolution_signal_present = resolution_signal_present | cleared_present
        unresolved = unresolved | (cleared_present & ~cleared.fillna(True))

    if "settlement_status" in df.columns:
        status = df["settlement_status"].astype("string").str.strip().str.lower()
        status_present = status.notna() & status.ne("")
        resolution_signal_present = resolution_signal_present | status_present
        closed_status = {"settled", "cleared", "closed", "resolved", "matched"}
        unresolved = unresolved | (status_present & ~status.isin(closed_status))

    if not resolution_signal_present.any():
        if "settlement_date" in df.columns:
            settlement_date = pd.to_datetime(df["settlement_date"], errors="coerce")
            resolution_signal_present = (
                resolution_signal_present | settlement_date.notna() | posting.notna()
            )
            unresolved = unresolved | settlement_date.isna()
        elif "lettrage_date" in df.columns:
            lettrage_date = pd.to_datetime(df["lettrage_date"], errors="coerce")
            resolution_signal_present = (
                resolution_signal_present | lettrage_date.notna() | posting.notna()
            )
            unresolved = unresolved | lettrage_date.isna()
        elif "lettrage" in df.columns:
            lettrage = df["lettrage"].astype("string").str.strip()
            resolution_signal_present = resolution_signal_present | lettrage.notna()
            unresolved = unresolved | lettrage.isna() | lettrage.eq("")
        else:
            return pd.Series(False, index=df.index)

    resolution_date = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    if "settlement_date" in df.columns:
        resolution_date = pd.to_datetime(df["settlement_date"], errors="coerce")
    elif "lettrage_date" in df.columns:
        resolution_date = pd.to_datetime(df["lettrage_date"], errors="coerce")

    aging_end = resolution_date.fillna(dataset_end)
    aging_days = (aging_end - posting).dt.days

    amount_mask = pd.Series(True, index=df.index)
    if "amount_open" in df.columns:
        amount_open = pd.to_numeric(df["amount_open"], errors="coerce")
        amount_mask = amount_open.abs().fillna(0.0) > min_open_amount
    elif min_open_amount > 0:
        debit = pd.to_numeric(df.get("debit_amount", 0.0), errors="coerce").fillna(0.0)
        credit = pd.to_numeric(df.get("credit_amount", 0.0), errors="coerce").fillna(0.0)
        gross = pd.concat([debit.abs(), credit.abs()], axis=1).max(axis=1)
        amount_mask = gross > min_open_amount

    result = (
        suspense
        & resolution_signal_present
        & unresolved
        & aging_days.fillna(-1).ge(threshold_days)
        & amount_mask
    ).astype(bool)

    amount_open_abs = pd.Series(np.nan, index=df.index, dtype="float64")
    if "amount_open" in df.columns:
        amount_open_abs = pd.to_numeric(df["amount_open"], errors="coerce").abs()
    elif {"debit_amount", "credit_amount"}.issubset(df.columns):
        debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0).abs()
        credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0).abs()
        amount_open_abs = pd.concat([debit, credit], axis=1).max(axis=1)

    score_series = result.astype(float)

    result.attrs["breakdown"] = {
        "base_threshold_days": int(threshold_days),
        "flagged_rows": int(result.sum()),
    }
    row_annotations: dict[object, dict[str, object]] = {}
    gl_account = (
        df["gl_account"].astype("string").str.strip()
        if "gl_account" in df.columns
        else pd.Series(pd.NA, index=df.index, dtype="string")
    )
    for idx in result[result].index:
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        row_annotations[annotation_key] = {
            "gl_account": None if pd.isna(gl_account.loc[idx]) else str(gl_account.loc[idx]),
            "aging_days": None if pd.isna(aging_days.loc[idx]) else int(aging_days.loc[idx]),
            "threshold_days": int(threshold_days),
            "open_amount": (
                None if pd.isna(amount_open_abs.loc[idx]) else float(amount_open_abs.loc[idx])
            ),
            "score": 1.0,
        }
        for column in (
            "document_id",
            "posting_date",
            "settlement_date",
            "lettrage_date",
            "amount_open",
            "is_cleared",
            "settlement_status",
        ):
            if column in df.columns:
                value = df.at[idx, column]
                row_annotations[annotation_key][column] = None if pd.isna(value) else value
    result.attrs["score_series"] = score_series
    result.attrs["row_annotations"] = row_annotations
    return result


# ── L4-05: 비정상 시간대 입력자 집중 분석 ─────────────────────────

_MIN_USERS_FOR_SIGMA = 3  # σ 통계가 유의미한 최소 사용자 수
_FALLBACK_MIDNIGHT_RATIO = 0.2  # 소수 인원 폴백 시 심야 비율 임계


def c12_abnormal_hours_concentration(
    df: pd.DataFrame,
    sigma_threshold: float = 2.5,
    rapid_approval_minutes: int = 5,
    min_abnormal_ratio: float = 0.1,
    min_midnight_entries: int = 3,
    min_user_entries: int = 10,
    min_high_context_midnight_entries: int = 100,
    auto_entry_sources: list[str] | None = None,
) -> pd.Series:
    """L4-05 비정상 시간대 입력자 집중: 사용자별 비정상 비율 2.5σ + 급속 승인.

    Why: KLCA IT 체크리스트 — L3-05/L3-06은 건별 플래그만 수행.
         특정 사용자가 심야/주말에 집중적으로 전표를 입력하는 행동 패턴은
         조직적 부정의 징후일 수 있다.

    하위 로직:
      (a) time_zone_category로 비정상 시간대 판정
      (b) 사용자별 비정상 비율 산출 (groupby)
      (c) 2.5σ 이상치 판정 (소수 인원 폴백 포함)
      (d) 급속 승인 검증 (자동 승인 필터링)
    """
    # Why: created_by 없으면 사용자별 분석 불가
    if "created_by" not in df.columns:
        return pd.Series(False, index=df.index)
    if "time_zone_category" not in df.columns:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    sigma_outlier_flags = pd.Series(False, index=df.index)
    low_volume_midnight_flags = pd.Series(False, index=df.index)
    high_context_midnight_flags = pd.Series(False, index=df.index)

    # ── (a) 비정상 시간대 판정 ──
    is_abnormal = _calc_is_abnormal(df)

    # ── (b) 사용자별 비정상 비율 ──
    user_stats = _calc_user_abnormal_stats(
        df,
        is_abnormal,
        auto_entry_sources=auto_entry_sources or [],
    )
    if not user_stats.empty:
        # Why: 전표 수가 극소한 사용자(1~2건)는 비율이 급등하여 오탐 유발
        qualified_stats = user_stats[user_stats["total_count"] >= min_user_entries]
        low_volume_midnight_users = user_stats[
            (user_stats["total_count"] < min_user_entries)
            & (user_stats["midnight_count"] >= min_midnight_entries)
        ].index
        high_context_midnight_users = qualified_stats[
            (qualified_stats["midnight_count"] >= min_high_context_midnight_entries)
            & (qualified_stats["abnormal_ratio"] >= min_abnormal_ratio)
        ].index

        # ── (c) 2.5σ 이상치 판정 ──
        if not qualified_stats.empty:
            outlier_users = _find_outlier_users(
                qualified_stats,
                sigma_threshold=sigma_threshold,
                min_abnormal_ratio=min_abnormal_ratio,
                min_midnight_entries=min_midnight_entries,
            )
            # Why: 이상치 사용자 중 비정상 시간대 행만 플래그
            #       정상 시간 전표까지 낙인하면 Top-side JE 등 복합 판정에서 오탐 유발
            if outlier_users:
                is_outlier_user = df["created_by"].isin(outlier_users)
                sigma_outlier_flags = is_outlier_user & is_abnormal
                result = result | sigma_outlier_flags
        if len(low_volume_midnight_users) > 0:
            is_low_volume_midnight_user = df["created_by"].isin(
                low_volume_midnight_users,
            )
            is_midnight = df["time_zone_category"] == "midnight"
            low_volume_midnight_flags = is_low_volume_midnight_user & is_midnight
            result = result | low_volume_midnight_flags
        if len(high_context_midnight_users) > 0:
            is_high_context_midnight_user = df["created_by"].isin(
                high_context_midnight_users,
            )
            is_midnight = df["time_zone_category"] == "midnight"
            high_context_midnight_flags = is_high_context_midnight_user & is_midnight
            result = result | high_context_midnight_flags

    # ── (d) 급속 승인 검증 ──
    rapid_flags = _check_rapid_approval(
        df,
        rapid_approval_minutes,
        auto_entry_sources or [],
    )
    result = result | rapid_flags
    result = result.astype(bool)

    human_operational_mask = _manual_user_mask(df, auto_entry_sources or [])
    propagated_system_context = (
        result
        & ~rapid_flags
        & ~human_operational_mask
        & (sigma_outlier_flags | low_volume_midnight_flags | high_context_midnight_flags)
    )

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[sigma_outlier_flags] = 0.45
    score_series.loc[low_volume_midnight_flags] = 0.50
    score_series.loc[high_context_midnight_flags] = 0.55
    score_series.loc[propagated_system_context] = 0.25
    score_series.loc[rapid_flags] = score_series.loc[rapid_flags].clip(lower=0.65)

    score_bucket = pd.Series("", index=df.index, dtype="object")
    score_bucket.loc[sigma_outlier_flags] = "sigma_outlier"
    score_bucket.loc[low_volume_midnight_flags] = "low_volume_midnight"
    score_bucket.loc[high_context_midnight_flags] = "high_context_midnight"
    score_bucket.loc[propagated_system_context] = "system_context_review"
    score_bucket.loc[rapid_flags] = "rapid_approval"

    row_annotations: dict[object, dict[str, object]] = {}
    optional_columns = (
        "document_id",
        "created_by",
        "approved_by",
        "posting_date",
        "approval_date",
        "time_zone_category",
        "source",
        "user_persona",
    )
    for idx in result[result].index:
        reason_codes: list[str] = []
        if bool(sigma_outlier_flags.loc[idx]):
            reason_codes.append("sigma_outlier")
        if bool(low_volume_midnight_flags.loc[idx]):
            reason_codes.append("low_volume_midnight")
        if bool(high_context_midnight_flags.loc[idx]):
            reason_codes.append("high_context_midnight")
        if bool(propagated_system_context.loc[idx]):
            reason_codes.append("system_context_review")
        if bool(rapid_flags.loc[idx]):
            reason_codes.append("rapid_approval")
        annotation: dict[str, object] = {
            "reason_codes": reason_codes,
            "primary_reason": reason_codes[-1] if reason_codes else "abnormal_time_review",
            "score": round(float(score_series.loc[idx]), 4),
            "score_bucket": str(score_bucket.loc[idx] or "abnormal_time_review"),
            "is_abnormal_time": bool(is_abnormal.loc[idx]),
        }
        for column in optional_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        row_annotations[annotation_key] = annotation

    breakdown: dict[str, object] = {
        "behavior_review_rows": int(result.sum()),
        "sigma_outlier_rows": int(sigma_outlier_flags.sum()),
        "low_volume_midnight_rows": int(low_volume_midnight_flags.sum()),
        "high_context_midnight_rows": int(high_context_midnight_flags.sum()),
        "system_context_review_rows": int(propagated_system_context.sum()),
        "rapid_approval_rows": int(rapid_flags.sum()),
        "manual_user_count": int(len(user_stats)) if not user_stats.empty else 0,
        "qualified_user_count": (
            int(len(user_stats[user_stats["total_count"] >= min_user_entries]))
            if not user_stats.empty
            else 0
        ),
        "sigma_threshold": float(sigma_threshold),
        "min_abnormal_ratio": float(min_abnormal_ratio),
        "min_midnight_entries": int(min_midnight_entries),
        "min_user_entries": int(min_user_entries),
        "min_high_context_midnight_entries": int(min_high_context_midnight_entries),
    }
    if "document_id" in df.columns:
        breakdown.update(
            {
                "behavior_review_docs": _nunique_documents(df, result),
                "sigma_outlier_docs": _nunique_documents(df, sigma_outlier_flags),
                "low_volume_midnight_docs": _nunique_documents(df, low_volume_midnight_flags),
                "high_context_midnight_docs": _nunique_documents(df, high_context_midnight_flags),
                "system_context_review_docs": _nunique_documents(
                    df,
                    propagated_system_context,
                ),
                "rapid_approval_docs": _nunique_documents(df, rapid_flags),
            }
        )

    breakdown["score_bands"] = {
        "system_context_review": 0.25,
        "sigma_outlier": 0.45,
        "low_volume_midnight": 0.50,
        "high_context_midnight": 0.55,
        "rapid_approval": 0.65,
    }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = breakdown
    result.attrs["row_annotations"] = row_annotations
    return result


def _calc_is_abnormal(df: pd.DataFrame) -> pd.Series:
    """비정상 시간대 여부를 bool Series로 반환."""
    tz_abnormal = df["time_zone_category"].isin(["midnight", "overtime"])
    weekend = df.get("is_weekend", pd.Series(False, index=df.index)).fillna(False)
    holiday = df.get("is_holiday", pd.Series(False, index=df.index)).fillna(False)
    return tz_abnormal | weekend | holiday


def _calc_user_abnormal_stats(
    df: pd.DataFrame,
    is_abnormal: pd.Series,
    auto_entry_sources: list[str] | None = None,
) -> pd.DataFrame:
    """사용자별 비정상 비율 + 심야 건수 통계 산출.

    Returns: DataFrame(index=created_by, columns=[abnormal_ratio, midnight_count])
    """
    # Why: NaN created_by는 분석 대상에서 제외
    valid_mask = _manual_user_mask(df, auto_entry_sources or [])
    if not valid_mask.any():
        return pd.DataFrame()

    grouped = (
        df[valid_mask]
        .assign(
            _is_abnormal=is_abnormal[valid_mask],
            _is_midnight=(df.loc[valid_mask, "time_zone_category"] == "midnight"),
        )
        .groupby("created_by")
    )

    stats = pd.DataFrame(
        {
            "abnormal_ratio": grouped["_is_abnormal"].mean(),
            "midnight_count": grouped["_is_midnight"].sum(),
            "total_count": grouped.size(),
        }
    )
    return stats


def _normalized_string(series: pd.Series) -> pd.Series:
    """Return a normalized string series for case-insensitive comparisons."""
    return series.astype("string").str.strip().str.lower()


def _manual_user_mask(
    df: pd.DataFrame,
    auto_entry_sources: list[str] | None = None,
) -> pd.Series:
    """Return rows that belong to real/manual users for L4-05 behavior stats."""
    mask = df["created_by"].notna()

    if "source" in df.columns and auto_entry_sources:
        auto_sources = {
            str(source).strip().lower() for source in auto_entry_sources if str(source).strip()
        }
        source = _normalized_string(df["source"])
        lone_automated = lone_automated_mask(
            df,
            source_tokens=auto_sources,
        ).reindex(df.index, fill_value=False)
        system_source = source.isin(auto_sources) & ~lone_automated
        mask = mask & ~system_source

    if "user_persona" in df.columns:
        persona = _normalized_string(df["user_persona"]).str.replace(
            " ",
            "_",
            regex=False,
        )
        mask = mask & persona.ne("automated_system")

    created_by = _normalized_string(df["created_by"])
    mask = mask & ~created_by.isin({"system", "ic_generator"})
    return mask.fillna(False)


def _find_outlier_users(
    user_stats: pd.DataFrame,
    *,
    sigma_threshold: float,
    min_abnormal_ratio: float,
    min_midnight_entries: int,
) -> set[str]:
    """Return users above the configured sigma or fallback threshold."""
    ratios = user_stats["abnormal_ratio"]
    n_users = len(ratios)

    if n_users < _MIN_USERS_FOR_SIGMA:
        # Why: 사용자 3명 미만이면 σ 통계 무의미 → 절대 기준 폴백
        #      비율 + 건수 AND 조건으로 우연한 1~2건 필터링
        flagged = user_stats[
            (user_stats["abnormal_ratio"] > _FALLBACK_MIDNIGHT_RATIO)
            & (user_stats["midnight_count"] >= min_midnight_entries)
        ]
        return set(flagged.index)

    mean = ratios.mean()
    std = ratios.std()

    # Why: std=0이면 모든 사용자 비율 동일 → 이상치 없음
    if std == 0 or np.isnan(std):
        return set()

    threshold = mean + sigma_threshold * std
    # Why: σ 이상치여도 절대 비율 미달이면 미플래그 (저비율 과탐 방지)
    flagged = user_stats[(ratios > threshold) & (ratios >= min_abnormal_ratio)]
    return set(flagged.index)


def _check_rapid_approval(
    df: pd.DataFrame,
    rapid_minutes: int,
    auto_entry_sources: list[str] | None = None,
) -> pd.Series:
    """비정상 시간대 + 급속 승인 행 탐지 (자동 승인 과탐 방지).

    Why: 입력자-승인자 간 시간차가 극히 짧으면 부실 검토 의심.
         단, 시스템 자동 승인·자기 승인·소액 자동 처리는 제외.
    """
    result = pd.Series(False, index=df.index)

    # Why: approval_date 없으면 검증 불가 → graceful skip
    if "approval_date" not in df.columns or "posting_date" not in df.columns:
        return result
    if "created_by" not in df.columns or "approved_by" not in df.columns:
        return result

    # Why: 자동 승인 과탐 방지 — 수기 전표만 검증 대상
    #       is_manual_je 부재 시 source 컬럼으로 대체 (ERP 배치/IF 제외)
    manual_mask = pd.Series(True, index=df.index)
    if "is_manual_je" in df.columns:
        manual_mask = df["is_manual_je"].fillna(False)
    elif "source" in df.columns and auto_entry_sources:
        auto_sources = {
            str(source).strip().lower() for source in auto_entry_sources if str(source).strip()
        }
        manual_mask = ~_normalized_string(df["source"]).isin(auto_sources)

    # Why: automated_system 계정은 ERP 자동 처리 — 인간 검토 대상 아님
    if "user_persona" in df.columns:
        persona = _normalized_string(df["user_persona"]).str.replace(
            " ",
            "_",
            regex=False,
        )
        manual_mask = manual_mask & persona.ne("automated_system")

    # Why: 자기 승인은 L1-05에서 이미 탐지 → 여기서 중복 플래그 불필요
    diff_approver = df["created_by"] != df["approved_by"]
    manual_mask = manual_mask & diff_approver

    # Why: 비정상 시간대가 아닌 급속 승인은 정상 업무 흐름
    is_abnormal_time = df.get(
        "time_zone_category",
        pd.Series("unknown", index=df.index),
    ).isin(["midnight", "overtime"])
    manual_mask = manual_mask & is_abnormal_time

    if not manual_mask.any():
        return result

    # Why: 승인은 전기 이후에 발생해야 정상. 음수(승인이 전기 이전)는 데이터 오류이므로 제외
    posting_dt = pd.to_datetime(df["posting_date"], errors="coerce")
    approval_dt = pd.to_datetime(df["approval_date"], errors="coerce")
    time_diff_seconds = (approval_dt - posting_dt).dt.total_seconds()
    time_diff_minutes = time_diff_seconds / 60.0

    rapid = manual_mask & (time_diff_minutes >= 0) & (time_diff_minutes < rapid_minutes)
    return rapid.fillna(False)
