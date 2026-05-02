"""피처 기반 이상 징후 룰 — L3-04~L3-08, L4-03, L3-09, L4-05.

피처 엔진(src/feature/)이 미리 생성한 bool/float 컬럼을 조합하는 마스크 연산.
피처 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def c01_period_end_large(
    df: pd.DataFrame,
    quantile: float = 0.75,
    min_group_size: int = 30,
    whitelist_patterns: list[dict[str, Any]] | None = None,
) -> pd.Series:
    """L3-04 period-end/start review population.

    The raw hit is the configured period-end/start window (`is_period_end`).
    Amount bands, manual source, approval issues, and other context signals
    only affect row score, bucket, and downstream priority.
    """
    if "is_period_end" not in df.columns:
        return pd.Series(False, index=df.index)
    # Why: max(debit, credit)로 대표 금액 산출 — fraud_rules_groupby 패턴 동일
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)

    # Why: account_group 존재 시 그룹별 Q3 — 계정 특성 반영
    #      미존재 시 전체 단일 Q3 (Phase 1 하위 호환)
    q50 = _amount_threshold(base, df, 0.50, min_group_size)
    q75 = _amount_threshold(base, df, quantile, min_group_size)
    q90 = _amount_threshold(base, df, 0.90, min_group_size)
    q95 = _amount_threshold(base, df, 0.95, min_group_size)

    period_end = df["is_period_end"].fillna(False)
    high_amount = base > q75
    manual_entry = (
        df["is_manual_je"].fillna(False).astype(bool)
        if "is_manual_je" in df.columns
        else pd.Series(False, index=df.index)
    )
    flagged = period_end.astype(bool)
    whitelist_matched = (
        flagged & _matches_period_end_whitelist(df, whitelist_patterns)
        if whitelist_patterns
        else pd.Series(False, index=df.index)
    )
    flagged = flagged.astype(bool)

    abnormal_time = _abnormal_time_mask(df)
    weak_description = (
        df["description_quality"].fillna("").astype(str).str.strip().str.lower().isin(
            {"missing", "corrupted", "poor"}
        )
        if "description_quality" in df.columns
        else pd.Series(False, index=df.index)
    )
    day_gap = (
        pd.to_numeric(df["days_backdated"], errors="coerce").fillna(0).abs()
        if "days_backdated" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    long_day_gap = day_gap.gt(30)
    control_signal = _approval_control_signal_mask(df)
    priority_signal = abnormal_time | weak_description | long_day_gap | control_signal

    amount_p50 = flagged & base.gt(q50)
    amount_p75 = flagged & base.gt(q75)
    amount_p90 = flagged & base.gt(q90)
    amount_p95 = flagged & base.gt(q95)

    bucket = pd.Series("none", index=df.index, dtype="object")
    bucket.loc[flagged] = "closing_base"
    bucket.loc[amount_p50] = "closing_amount_p50"
    bucket.loc[amount_p75] = "closing_amount_p75"
    bucket.loc[amount_p90] = "closing_amount_p90"
    bucket.loc[amount_p95] = "closing_amount_p95"
    bucket.loc[whitelist_matched] = "closing_recurring_low_priority"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[amount_p50] = 0.20
    score_series.loc[amount_p75] = 0.35
    score_series.loc[amount_p90] = 0.55
    score_series.loc[amount_p95] = 0.70
    score_series.loc[whitelist_matched] = score_series.loc[whitelist_matched].clip(upper=0.20)

    control_reason_masks = _approval_control_reason_masks(df)
    reason_masks = {
        "amount_p50": amount_p50,
        "amount_p75": amount_p75,
        "amount_p90": amount_p90,
        "amount_p95": amount_p95,
        "manual_entry": manual_entry,
        "abnormal_time": abnormal_time,
        "weak_description": weak_description,
        "long_day_gap": long_day_gap,
        **control_reason_masks,
    }
    priority_reason_counts: dict[str, int] = {}
    for reason, mask in reason_masks.items():
        count = int((flagged & mask).sum())
        if count:
            priority_reason_counts[reason] = count

    flagged_index = flagged[flagged].index
    row_annotations: dict[int, dict[str, object]] = {}
    optional_columns = [
        column
        for column in (
            "document_id",
            "posting_date",
            "source",
            "is_manual_je",
            "created_by",
            "approved_by",
            "approval_date",
            "business_process",
            "account_group",
            "gl_account",
            "description_quality",
            "days_backdated",
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
    reason_values = {
        reason: mask.loc[flagged_index].to_numpy(dtype=bool)
        for reason, mask in reason_masks.items()
    }
    q50_values = _threshold_values(q50, flagged_index)
    q75_values = _threshold_values(q75, flagged_index)
    q90_values = _threshold_values(q90, flagged_index)
    q95_values = _threshold_values(q95, flagged_index)
    annotation_frame = pd.DataFrame(
        {
            "bucket": bucket.loc[flagged_index].astype(str),
            "score": score_series.loc[flagged_index].round(4),
            "whitelist_matched": whitelist_matched.loc[flagged_index].astype(bool),
            "amount": base.loc[flagged_index],
            "threshold_amount": q75_values,
            "amount_q50": q50_values,
            "amount_q75": q75_values,
            "amount_q90": q90_values,
            "amount_q95": q95_values,
        },
        index=flagged_index,
    ).astype(object)
    annotation_frame = annotation_frame.where(pd.notna(annotation_frame), None)

    for pos, idx in enumerate(flagged_index):
        annotation = annotation_frame.loc[idx].to_dict()
        annotation["score"] = float(annotation["score"])
        annotation["whitelist_matched"] = bool(annotation["whitelist_matched"])
        if annotation["amount"] is not None:
            annotation["amount"] = float(annotation["amount"])
        if annotation["threshold_amount"] is not None:
            annotation["threshold_amount"] = float(annotation["threshold_amount"])
        annotation["priority_reasons"] = [
            reason
            for reason, values in reason_values.items()
            if bool(values[pos])
        ]
        annotation.update(optional_values.get(idx, {}))
        row_annotations[int(idx)] = annotation

    flagged.attrs["score_series"] = score_series
    flagged.attrs["breakdown"] = {
        "flagged_rows": int(flagged.sum()),
        "high_amount_rows": int((flagged & high_amount).sum()),
        "manual_rows": int((flagged & manual_entry).sum()),
        "priority_rows": int((flagged & priority_signal & ~whitelist_matched).sum()),
        "whitelisted_recurring_rows": int(whitelist_matched.sum()),
        "bucket_counts": bucket.loc[flagged].value_counts().to_dict(),
        "amount_band_counts": {
            "base_zero_score_rows": int((flagged & score_series.eq(0.0)).sum()),
            "amount_p50_rows": int(amount_p50.sum()),
            "amount_p75_rows": int(amount_p75.sum()),
            "amount_p90_rows": int(amount_p90.sum()),
            "amount_p95_rows": int(amount_p95.sum()),
        },
        "priority_reason_counts": priority_reason_counts,
        "quantile": float(quantile),
        "min_group_size": int(min_group_size),
    }
    if "document_id" in df.columns:
        flagged.attrs["breakdown"]["whitelisted_recurring_docs"] = _nunique_documents(
            df,
            whitelist_matched,
        )
    flagged.attrs["row_annotations"] = row_annotations
    return flagged


def _abnormal_time_mask(df: pd.DataFrame) -> pd.Series:
    abnormal = pd.Series(False, index=df.index)
    for column in ("is_after_hours", "is_weekend", "is_holiday"):
        if column in df.columns:
            abnormal = abnormal | df[column].fillna(False).astype(bool)
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
        masks["skipped_approval"] = (
            df["exceeds_threshold"].fillna(False).astype(bool) & no_approver
        )
    if {"approved_by", "approval_date"}.issubset(df.columns):
        has_approver = df["approved_by"].fillna("").astype(str).str.strip().ne("")
        no_approval_date = df["approval_date"].fillna("").astype(str).str.strip().eq("")
        masks["missing_approval_date"] = has_approver & no_approval_date
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
        if bool(df.at[idx, "exceeds_threshold"]) and no_approver:
            reasons.append("skipped_approval")
    if {"approved_by", "approval_date"}.issubset(df.columns):
        has_approver = str(df.at[idx, "approved_by"] or "").strip() != ""
        no_approval_date = str(df.at[idx, "approval_date"] or "").strip() == ""
        if has_approver and no_approval_date:
            reasons.append("missing_approval_date")
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


def c01_period_end_sensitive_account(
    df: pd.DataFrame,
    sensitive_config: dict[str, Any] | None = None,
) -> pd.Series:
    """Return rows touching L3-04-sensitive closing accounts.

    Why: sensitive accounts should raise review priority only after L3-04 triggers.
    This helper intentionally does not create additional L3-04 flags.
    """
    if not sensitive_config:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)

    groups = _normalize_list(sensitive_config.get("account_groups"))
    if groups and "account_group" in df.columns:
        result = result | df["account_group"].astype(str).str.strip().str.lower().isin(groups)

    accounts = _normalize_list(sensitive_config.get("accounts"))
    prefixes = _normalize_list(sensitive_config.get("account_prefixes"))
    if (accounts or prefixes) and "gl_account" in df.columns:
        gl = df["gl_account"].astype(str).str.strip().str.lower()
        if accounts:
            result = result | gl.isin(accounts)
        if prefixes:
            result = result | gl.str.startswith(tuple(prefixes), na=False)

    return result.fillna(False)


def _matches_period_end_whitelist(
    df: pd.DataFrame,
    patterns: list[dict[str, Any]],
) -> pd.Series:
    """Match auditor-approved recurring closing-entry whitelist patterns."""
    result = pd.Series(False, index=df.index)
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        mask = pd.Series(True, index=df.index)
        has_condition = False

        for key in ("source", "created_by", "document_type", "account_group"):
            values = _normalize_list(pattern.get(key))
            if not values:
                continue
            has_condition = True
            if key not in df.columns:
                mask = mask & False
            else:
                series = df[key].astype(str).str.strip().str.lower()
                mask = mask & series.isin(values)

        desc_values = _normalize_list(pattern.get("description_contains"))
        if desc_values:
            has_condition = True
            mask = mask & _description_contains_any(df, desc_values)

        if has_condition:
            result = result | mask
    return result.fillna(False)


def _description_contains_any(df: pd.DataFrame, needles: list[str]) -> pd.Series:
    text = pd.Series("", index=df.index, dtype="object")
    for col in ("line_text", "header_text", "description"):
        if col in df.columns:
            text = text.str.cat(df[col].fillna("").astype(str), sep=" ")
    normalized = text.str.lower()
    mask = pd.Series(False, index=df.index)
    for needle in needles:
        mask = mask | normalized.str.contains(needle, regex=False, na=False)
    return mask


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return [str(item).strip().lower() for item in values if str(item).strip()]


def _nunique_documents(df: pd.DataFrame, mask: pd.Series) -> int:
    """Return distinct document count for rows selected by mask."""
    if "document_id" not in df.columns:
        return 0
    return int(df.loc[mask.reindex(df.index, fill_value=False), "document_id"].dropna().nunique())


def _grouped_quantile(
    base: pd.Series,
    groups: pd.Series,
    quantile: float,
    min_size: int,
) -> pd.Series:
    """그룹별 quantile 계산. 소그룹(n < min_size)은 전체 Q3 fallback.

    Why: n이 너무 작으면 분위수 추정이 불안정 → 전체 Q3가 더 신뢰성 있음.
         groupby().quantile() + map() 패턴으로 transform보다 빠르게 처리.
    """
    global_q = base.quantile(quantile)
    # Why: transform("quantile")은 Python 루프 → groupby().quantile()+map()이 빠름
    group_q_map = base.groupby(groups).quantile(quantile)
    group_size_map = base.groupby(groups).size()
    mapped_q = groups.map(group_q_map)
    mapped_size = groups.map(group_size_map)
    return mapped_q.where(mapped_size >= min_size, global_q)


def _amount_threshold(
    base: pd.Series,
    df: pd.DataFrame,
    quantile: float,
    min_group_size: int,
) -> pd.Series | float:
    """Return global or account-group quantile threshold for L3-04 amount scoring."""

    if "account_group" in df.columns:
        return _grouped_quantile(base, df["account_group"], quantile, min_group_size)
    return float(base.quantile(quantile))


def _threshold_values(threshold: pd.Series | float, index: pd.Index) -> pd.Series:
    """Align scalar or series threshold values to an annotation index."""

    if isinstance(threshold, pd.Series):
        return threshold.loc[index]
    return pd.Series(threshold, index=index)


def c02_weekend_entry(df: pd.DataFrame) -> pd.Series:
    """L3-05 주말 전기: 토/일 또는 공휴일 전기.

    Why: PCAOB AS 240 A49(c) — 비정상 시점 거래는 승인 우회 의심.
    """
    weekend = df.get("is_weekend", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    holiday = df.get("is_holiday", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    flagged = weekend | holiday
    weekend_holiday = weekend & holiday
    weekend_only = weekend & ~holiday
    weekday_holiday = holiday & ~weekend

    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[weekday_holiday] = 0.35
    score_series.loc[weekend_only] = 0.40
    score_series.loc[weekend_holiday] = 0.45

    breakdown = {
        "calendar_review_rows": int(flagged.sum()),
        "weekend_rows": int(weekend.sum()),
        "holiday_rows": int(holiday.sum()),
        "weekend_only_rows": int(weekend_only.sum()),
        "weekday_holiday_rows": int(weekday_holiday.sum()),
        "weekend_holiday_rows": int(weekend_holiday.sum()),
    }
    if "document_id" in df.columns:
        breakdown.update({
            "calendar_review_docs": _nunique_documents(df, flagged),
            "weekend_docs": _nunique_documents(df, weekend),
            "holiday_docs": _nunique_documents(df, holiday),
            "weekend_only_docs": _nunique_documents(df, weekend_only),
            "weekday_holiday_docs": _nunique_documents(df, weekday_holiday),
            "weekend_holiday_docs": _nunique_documents(df, weekend_holiday),
        })

    row_annotations: dict[int, dict[str, object]] = {}
    for idx in df.index[flagged]:
        if bool(weekend_holiday.loc[idx]):
            reason_code = "weekend_holiday"
        elif bool(weekend.loc[idx]):
            reason_code = "weekend"
        elif bool(weekday_holiday.loc[idx]):
            reason_code = "weekday_holiday"
        else:
            reason_code = "holiday"
        row_annotations[int(idx)] = {
            "reason_code": reason_code,
            "score": float(score_series.loc[idx]),
            "is_weekend": bool(weekend.loc[idx]),
            "is_holiday": bool(holiday.loc[idx]),
        }

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

    result = df["is_after_hours"].fillna(False).astype(bool)
    if not result.any():
        return result

    source_norm = (
        df["source"].fillna("").astype(str).str.strip().str.lower()
        if "source" in df.columns
        else pd.Series("", index=df.index)
    )
    persona_norm = (
        df["user_persona"].fillna("").astype(str).str.strip().str.lower()
        if "user_persona" in df.columns
        else pd.Series("", index=df.index)
    )
    actor_norm = (
        df["created_by"].fillna("").astype(str).str.strip().str.lower()
        if "created_by" in df.columns
        else pd.Series("", index=df.index)
    )
    system_source = source_norm.isin({"automated", "batch", "interface", "system"})
    system_persona = persona_norm.eq("automated_system")
    system_actor = pd.Series(False, index=df.index)
    for token in ("batch", "system", "auto", "if_", "svc_"):
        system_actor = system_actor | actor_norm.str.contains(token, regex=False)
    normal_system_context = result & (system_source | system_persona | system_actor)
    confirmed_after_hours = result & ~normal_system_context

    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[normal_system_context] = 0.20
    score_series.loc[confirmed_after_hours] = 0.45

    posting = (
        pd.to_datetime(df["posting_date"], errors="coerce")
        if "posting_date" in df.columns
        else pd.Series(pd.NaT, index=df.index)
    )
    time_buckets: dict[str, int] = {}
    row_annotations: dict[int, dict[str, object]] = {}
    for idx in result[result].index:
        hour = posting.loc[idx].hour if pd.notna(posting.loc[idx]) else None
        if hour is None:
            time_bucket = "unknown_time"
        elif hour < 6:
            time_bucket = "midnight_00_05"
        else:
            time_bucket = "late_evening_22_23"
        time_buckets[time_bucket] = time_buckets.get(time_bucket, 0) + 1
        row_annotations[int(idx)] = {
            "bucket": (
                "normal_system_context"
                if bool(normal_system_context.loc[idx])
                else "confirmed_after_hours"
            ),
            "score": round(float(score_series.loc[idx]), 4),
            "source_category": (
                "system_or_batch" if bool(normal_system_context.loc[idx]) else "human_or_unknown"
            ),
            "time_bucket": time_bucket,
            "source": str(df.at[idx, "source"]) if "source" in df.columns else "",
            "created_by": str(df.at[idx, "created_by"]) if "created_by" in df.columns else "",
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "confirmed_after_hours_rows": int(confirmed_after_hours.sum()),
        "normal_system_context_rows": int(normal_system_context.sum()),
        "source_counts": {
            str(key): int(value)
            for key, value in source_norm.loc[result].value_counts(dropna=False).items()
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
    if not result.any():
        score_series = pd.Series(0.0, index=df.index, dtype="float64")
        result.attrs["score_series"] = score_series
        result.attrs["breakdown"] = {
            "flagged_rows": 0,
            "late_rows": 0,
            "forward_rows": 0,
            "bucket_counts": {},
            "direction_counts": {},
            "threshold_days": int(threshold_days),
        }
        result.attrs["row_annotations"] = {}
        return result

    direction = pd.Series("none", index=df.index, dtype="object")
    direction.loc[result & days.gt(0)] = "late_posting"
    direction.loc[result & days.lt(0)] = "forward_date_gap"

    bucket = pd.Series("none", index=df.index, dtype="object")
    moderate = result & abs_gap.le(60)
    large = result & abs_gap.gt(60) & abs_gap.le(90)
    extreme = result & abs_gap.gt(90)
    bucket.loc[moderate & days.gt(0)] = "late_moderate_gap"
    bucket.loc[large & days.gt(0)] = "late_large_gap"
    bucket.loc[extreme & days.gt(0)] = "late_extreme_gap"
    bucket.loc[moderate & days.lt(0)] = "forward_moderate_gap"
    bucket.loc[large & days.lt(0)] = "forward_large_gap"
    bucket.loc[extreme & days.lt(0)] = "forward_extreme_gap"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[moderate] = 0.45
    score_series.loc[large] = 0.60
    score_series.loc[extreme] = 0.75

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
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "direction": str(direction.loc[idx]),
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
        "late_rows": int((result & days.gt(0)).sum()),
        "forward_rows": int((result & days.lt(0)).sum()),
        "bucket_counts": bucket.loc[result].value_counts().to_dict(),
        "direction_counts": direction.loc[result].value_counts().to_dict(),
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
    return df[column].fillna(False).astype(bool)


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
    score_series = pd.Series(0.80, index=df.index, dtype="float64")
    context_masks = {
        "period_end": _l108_context_mask(df, "is_period_end"),
        "manual_entry": _l108_context_mask(df, "is_manual_je"),
        "high_amount": _l108_amount_context(df),
        "date_gap": _l108_context_mask(df, "has_date_gap")
        | _l108_context_mask(df, "backdated_flag"),
        "approval_issue": _l108_context_mask(df, "has_missing_approval_date")
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
    score_series = (score_series + (context_count * 0.05)).clip(upper=0.95)

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
        bucket = (
            "period_mismatch_corroborated"
            if active_contexts
            else "period_mismatch_confirmed"
        )
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


def c06_missing_or_corrupted_description(df: pd.DataFrame) -> pd.Series:
    """L3-08 적요 결손/파손: 설명 필드가 비었거나 명백히 깨진 경우.

    Why: PCAOB AS 240 A49(c), K-SOX §8①1호 — 적요 미비는 전표 추적 방해.
    """
    if "description_quality" not in df.columns:
        return pd.Series(False, index=df.index)

    quality = df["description_quality"].fillna("").astype(str).str.strip().str.lower()
    # "poor"는 기존 저장 데이터/테스트 fixture 호환용 별칭이다.
    missing = quality.eq("missing")
    corrupted = quality.eq("corrupted")
    poor = quality.eq("poor")
    result = missing | corrupted | poor
    if not result.any():
        return result

    score_series = pd.Series(0.0, index=df.index)
    score_series.loc[missing] = 0.45
    score_series.loc[corrupted] = 0.55
    score_series.loc[poor] = 0.50

    row_annotations: dict[int, dict[str, object]] = {}
    for idx in result[result].index:
        bucket = str(quality.loc[idx])
        normalized_bucket = "corrupted_legacy_poor" if bucket == "poor" else bucket
        row_annotations[int(idx)] = {
            "description_quality": bucket,
            "bucket": normalized_bucket,
            "score": round(float(score_series.loc[idx]), 4),
            "line_missing": (
                bool(df.at[idx, "description_line_missing"])
                if "description_line_missing" in df.columns
                else None
            ),
            "header_missing": (
                bool(df.at[idx, "description_header_missing"])
                if "description_header_missing" in df.columns
                else None
            ),
            "both_missing": (
                bool(df.at[idx, "description_both_missing"])
                if "description_both_missing" in df.columns
                else None
            ),
        }

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "missing_rows": int(missing.sum()),
        "corrupted_rows": int(corrupted.sum()),
        "poor_legacy_rows": int(poor.sum()),
        "quality_counts": {
            str(key): int(value)
            for key, value in quality.loc[result].value_counts(dropna=False).items()
            if str(key)
        },
    }
    result.attrs["row_annotations"] = row_annotations
    return result


# Backward-compatible alias for older imports/tests.
c06_risky_description = c06_missing_or_corrupted_description


def c08_amount_outlier(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
    min_amount_quantile: float = 0.90,
) -> pd.Series:
    """L4-03 이상 고액: 양의 Z-score + 전역 상위 금액 분위수.

    Why: PCAOB AS 240 §33(b), ISA 315 — 3σ 초과 금액은 조작 가능성.
         Phase1에서는 무거운 계정별 whitelist 대신 최소 금액 분위수 가드만 적용해
         저액 방향 이상치와 낮은 금액의 통계적 흔들림을 줄인다.
    """
    required = {"amount_zscore", "debit_amount", "credit_amount"}
    if not required.issubset(df.columns):
        return pd.Series(False, index=df.index)

    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    base_amount = pd.concat([debit, credit], axis=1).max(axis=1)

    if 0.0 < min_amount_quantile <= 1.0:
        amount_threshold = base_amount.quantile(min_amount_quantile)
        high_amount = base_amount >= amount_threshold
    else:
        high_amount = pd.Series(True, index=df.index)

    zscore = pd.to_numeric(df["amount_zscore"], errors="coerce").fillna(0.0)
    high_zscore = zscore > zscore_threshold
    result = (high_zscore & high_amount).astype(bool)

    bucket = pd.Series("none", index=df.index, dtype="object")
    bucket.loc[result] = "low_zscore"
    bucket.loc[result & zscore.ge(5.0)] = "medium_zscore"
    bucket.loc[result & zscore.ge(10.0)] = "high_zscore"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result & bucket.eq("low_zscore")] = 0.25
    score_series.loc[result & bucket.eq("medium_zscore")] = 0.45
    score_series.loc[result & bucket.eq("high_zscore")] = 0.70

    row_annotations: dict[object, dict[str, object]] = {}
    optional_columns = (
        "document_id",
        "gl_account",
        "account_group",
        "posting_date",
        "debit_amount",
        "credit_amount",
    )
    for idx in result[result].index:
        annotation_key = int(idx) if isinstance(idx, (int, np.integer)) else idx
        annotation: dict[str, object] = {
            "bucket": str(bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
            "amount_zscore": round(float(zscore.loc[idx]), 4),
            "base_amount": float(base_amount.loc[idx]),
            "amount_threshold": (
                float(amount_threshold) if 0.0 < min_amount_quantile <= 1.0 else None
            ),
            "min_amount_quantile": float(min_amount_quantile),
            "zscore_threshold": float(zscore_threshold),
        }
        for column in optional_columns:
            if column in df.columns:
                value = df.at[idx, column]
                annotation[column] = None if pd.isna(value) else value
        row_annotations[annotation_key] = annotation

    result.attrs["score_series"] = score_series
    result.attrs["breakdown"] = {
        "high_amount_review_rows": int(result.sum()),
        "low_zscore_rows": int((result & bucket.eq("low_zscore")).sum()),
        "medium_zscore_rows": int((result & bucket.eq("medium_zscore")).sum()),
        "high_zscore_rows": int((result & bucket.eq("high_zscore")).sum()),
        "review_zscore_rows": int((result & bucket.eq("low_zscore")).sum()),
        "strong_zscore_rows": int((result & bucket.eq("medium_zscore")).sum()),
        "extreme_zscore_rows": int((result & bucket.eq("high_zscore")).sum()),
        "amount_guard_rows": int(high_amount.sum()),
        "zscore_candidate_rows": int(high_zscore.sum()),
        "amount_threshold": float(amount_threshold) if 0.0 < min_amount_quantile <= 1.0 else None,
        "min_amount_quantile": float(min_amount_quantile),
        "zscore_threshold": float(zscore_threshold),
    }
    if "document_id" in df.columns:
        result.attrs["breakdown"].update({
            "high_amount_review_docs": _nunique_documents(df, result),
            "low_zscore_docs": _nunique_documents(df, result & bucket.eq("low_zscore")),
            "medium_zscore_docs": _nunique_documents(df, result & bucket.eq("medium_zscore")),
            "high_zscore_docs": _nunique_documents(df, result & bucket.eq("high_zscore")),
            "review_zscore_docs": _nunique_documents(df, result & bucket.eq("low_zscore")),
            "strong_zscore_docs": _nunique_documents(df, result & bucket.eq("medium_zscore")),
            "extreme_zscore_docs": _nunique_documents(df, result & bucket.eq("high_zscore")),
        })
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

    aging_bucket = pd.Series("none", index=df.index, dtype="object")
    aging_bucket.loc[result & aging_days.lt(threshold_days * 2)] = "aging_30_60"
    aging_bucket.loc[
        result & aging_days.ge(threshold_days * 2) & aging_days.lt(threshold_days * 3)
    ] = "aging_60_90"
    aging_bucket.loc[result & aging_days.ge(threshold_days * 3)] = "aging_over_90"

    amount_bucket = pd.Series("unknown_amount", index=df.index, dtype="object")
    flagged_amounts = amount_open_abs[result & amount_open_abs.notna()]
    if not flagged_amounts.empty:
        q50 = flagged_amounts.quantile(0.50)
        q75 = flagged_amounts.quantile(0.75)
        amount_bucket.loc[result & amount_open_abs.lt(q50)] = "open_amount_low"
        amount_bucket.loc[
            result & amount_open_abs.ge(q50) & amount_open_abs.lt(q75)
        ] = "open_amount_medium"
        amount_bucket.loc[result & amount_open_abs.ge(q75)] = "open_amount_high"

    score_series = pd.Series(0.0, index=df.index, dtype="float64")
    score_series.loc[result & aging_bucket.eq("aging_30_60")] = 0.45
    score_series.loc[result & aging_bucket.eq("aging_60_90")] = 0.60
    score_series.loc[result & aging_bucket.eq("aging_over_90")] = 0.75
    high_open_amount = result & amount_bucket.eq("open_amount_high") & score_series.gt(0)
    score_series.loc[high_open_amount] = (
        score_series.loc[high_open_amount] + 0.05
    ).clip(upper=0.80)

    result.attrs["breakdown"] = {
        "base_threshold_days": int(threshold_days),
        "flagged_rows": int(result.sum()),
        "aging_bucket_counts": aging_bucket.loc[result].value_counts().to_dict(),
        "open_amount_bucket_counts": amount_bucket.loc[result].value_counts().to_dict(),
        "high_open_amount_rows": int((result & amount_bucket.eq("open_amount_high")).sum()),
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
            "aging_bucket": str(aging_bucket.loc[idx]),
            "open_amount": (
                None if pd.isna(amount_open_abs.loc[idx]) else float(amount_open_abs.loc[idx])
            ),
            "open_amount_bucket": str(amount_bucket.loc[idx]),
            "score": round(float(score_series.loc[idx]), 4),
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
        df, rapid_approval_minutes, auto_entry_sources or [],
    )
    result = result | rapid_flags
    result = result.astype(bool)

    human_operational_mask = _manual_user_mask(df, auto_entry_sources or [])
    propagated_system_context = (
        result
        & ~rapid_flags
        & ~human_operational_mask
        & (
            sigma_outlier_flags
            | low_volume_midnight_flags
            | high_context_midnight_flags
        )
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
        breakdown.update({
            "behavior_review_docs": _nunique_documents(df, result),
            "sigma_outlier_docs": _nunique_documents(df, sigma_outlier_flags),
            "low_volume_midnight_docs": _nunique_documents(df, low_volume_midnight_flags),
            "high_context_midnight_docs": _nunique_documents(df, high_context_midnight_flags),
            "system_context_review_docs": _nunique_documents(
                df,
                propagated_system_context,
            ),
            "rapid_approval_docs": _nunique_documents(df, rapid_flags),
        })

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

    grouped = df[valid_mask].assign(
        _is_abnormal=is_abnormal[valid_mask],
        _is_midnight=(df.loc[valid_mask, "time_zone_category"] == "midnight"),
    ).groupby("created_by")

    stats = pd.DataFrame({
        "abnormal_ratio": grouped["_is_abnormal"].mean(),
        "midnight_count": grouped["_is_midnight"].sum(),
        "total_count": grouped.size(),
    })
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
            str(source).strip().lower()
            for source in auto_entry_sources
            if str(source).strip()
        }
        source = _normalized_string(df["source"])
        mask = mask & ~source.isin(auto_sources)

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
    flagged = user_stats[
        (ratios > threshold) & (ratios >= min_abnormal_ratio)
    ]
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
            str(source).strip().lower()
            for source in auto_entry_sources
            if str(source).strip()
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
        "time_zone_category", pd.Series("unknown", index=df.index),
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
