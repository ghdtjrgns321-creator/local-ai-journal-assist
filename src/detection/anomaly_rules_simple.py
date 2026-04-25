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
    """L3-04 기말/기초 대규모: 월말/월초 근접 + 금액 > Q3 또는 수기 전표.

    Why: PCAOB AS 240 §32(b), FSS 결산 수정 조작 패턴.
         기말에 집중되는 고액 전표는 결산 조정 조작 가능성.
         계정그룹별 Q3로 계정 특성(매출 vs 비용 금액 규모) 반영 → 오탐 감소.
    """
    if "is_period_end" not in df.columns:
        return pd.Series(False, index=df.index)
    # Why: max(debit, credit)로 대표 금액 산출 — fraud_rules_groupby 패턴 동일
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)

    # Why: account_group 존재 시 그룹별 Q3 — 계정 특성 반영
    #      미존재 시 전체 단일 Q3 (Phase 1 하위 호환)
    if "account_group" in df.columns:
        threshold = _grouped_quantile(base, df["account_group"], quantile, min_group_size)
    else:
        threshold = base.quantile(quantile)

    period_end = df["is_period_end"].fillna(False)
    high_amount = base > threshold
    manual_entry = (
        df["is_manual_je"].fillna(False).astype(bool)
        if "is_manual_je" in df.columns
        else pd.Series(False, index=df.index)
    )
    flagged = period_end & (high_amount | manual_entry)
    if whitelist_patterns:
        flagged = flagged & ~_matches_period_end_whitelist(df, whitelist_patterns)
    return flagged


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


def c02_weekend_entry(df: pd.DataFrame) -> pd.Series:
    """L3-05 주말 전기: 토/일 또는 공휴일 전기.

    Why: PCAOB AS 240 A49(c) — 비정상 시점 거래는 승인 우회 의심.
    """
    weekend = df.get("is_weekend", pd.Series(False, index=df.index)).fillna(False)
    holiday = df.get("is_holiday", pd.Series(False, index=df.index)).fillna(False)
    return weekend | holiday


def c03_after_hours_entry(df: pd.DataFrame) -> pd.Series:
    """L3-06 심야 전기: 감사인이 설정한 심야 시간대 전기.

    Why: PCAOB AS 240 A49(c) — 심야 전기는 감시 부재 시점 악용 가능.
    L3-05(주말/공휴일)와 L4-05(비정상 시간대 집중)와 중복되지 않도록
    L3-06은 is_after_hours만 사용한다.
    """
    if "is_after_hours" not in df.columns:
        return pd.Series(False, index=df.index)

    return df["is_after_hours"].fillna(False).astype(bool)


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
    return df["days_backdated"].fillna(0).abs() > threshold_days


def c05_fiscal_period_mismatch(df: pd.DataFrame) -> pd.Series:
    """L1-08 기간 불일치: 회계기간 ≠ 전기월.

    Why: PCAOB AS 240 §32(b) — 기간 귀속 오류는 의도적 기간 이동 가능성.
    """
    if "fiscal_period_mismatch" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["fiscal_period_mismatch"].fillna(False)


def c06_missing_or_corrupted_description(df: pd.DataFrame) -> pd.Series:
    """L3-08 적요 결손/파손: 설명 필드가 비었거나 명백히 깨진 경우.

    Why: PCAOB AS 240 A49(c), K-SOX §8①1호 — 적요 미비는 전표 추적 방해.
    """
    if "description_quality" not in df.columns:
        return pd.Series(False, index=df.index)

    # "poor"는 기존 저장 데이터/테스트 fixture 호환용 별칭이다.
    return df["description_quality"].isin(["missing", "corrupted", "poor"])


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

    high_zscore = df["amount_zscore"].fillna(0.0) > zscore_threshold
    return high_zscore & high_amount


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

    suspense = df["is_suspense_account"].astype("boolean").fillna(False)
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
        cleared = df["is_cleared"].astype("boolean")
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
    result.attrs["breakdown"] = {
        "base_threshold_days": int(threshold_days),
        "flagged_rows": int(result.sum()),
    }
    row_annotations: dict[int, dict[str, object]] = {}
    if "gl_account" in df.columns:
        gl_account = df["gl_account"].astype("string").str.strip()
        for idx in result[result].index:
            row_annotations[int(idx)] = {
                "gl_account": None if pd.isna(gl_account.loc[idx]) else str(gl_account.loc[idx]),
                "aging_days": None if pd.isna(aging_days.loc[idx]) else int(aging_days.loc[idx]),
                "threshold_days": int(threshold_days),
            }
    result.attrs["row_annotations"] = row_annotations
    return result


# ── L4-05: 비정상 시간대 입력자 집중 분석 ─────────────────────────

_MIN_USERS_FOR_SIGMA = 3  # σ 통계가 유의미한 최소 사용자 수
_FALLBACK_MIDNIGHT_RATIO = 0.2  # 소수 인원 폴백 시 심야 비율 임계


def c12_abnormal_hours_concentration(
    df: pd.DataFrame,
    sigma_threshold: float = 3.0,
    rapid_approval_minutes: int = 5,
    min_abnormal_ratio: float = 0.1,
    min_midnight_entries: int = 3,
    min_user_entries: int = 10,
    auto_entry_sources: list[str] | None = None,
) -> pd.Series:
    """L4-05 비정상 시간대 입력자 집중: 사용자별 비정상 비율 3σ + 급속 승인.

    Why: KLCA IT 체크리스트 — L3-05/L3-06은 건별 플래그만 수행.
         특정 사용자가 심야/주말에 집중적으로 전표를 입력하는 행동 패턴은
         조직적 부정의 징후일 수 있다.

    하위 로직:
      (a) time_zone_category로 비정상 시간대 판정
      (b) 사용자별 비정상 비율 산출 (groupby)
      (c) 3σ 이상치 판정 (소수 인원 폴백 포함)
      (d) 급속 승인 검증 (자동 승인 필터링)
    """
    # Why: created_by 없으면 사용자별 분석 불가
    if "created_by" not in df.columns:
        return pd.Series(False, index=df.index)
    if "time_zone_category" not in df.columns:
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)

    # ── (a) 비정상 시간대 판정 ──
    is_abnormal = _calc_is_abnormal(df)

    # ── (b) 사용자별 비정상 비율 ──
    user_stats = _calc_user_abnormal_stats(df, is_abnormal)
    if not user_stats.empty:
        # Why: 전표 수가 극소한 사용자(1~2건)는 비율이 급등하여 오탐 유발
        qualified_stats = user_stats[user_stats["total_count"] >= min_user_entries]
        low_volume_midnight_users = user_stats[
            (user_stats["total_count"] < min_user_entries)
            & (user_stats["midnight_count"] >= min_midnight_entries)
        ].index

        # ── (c) 3σ 이상치 판정 ──
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
                result = result | (is_outlier_user & is_abnormal)
        if len(low_volume_midnight_users) > 0:
            is_low_volume_midnight_user = df["created_by"].isin(
                low_volume_midnight_users,
            )
            is_midnight = df["time_zone_category"] == "midnight"
            result = result | (is_low_volume_midnight_user & is_midnight)

    # ── (d) 급속 승인 검증 ──
    rapid_flags = _check_rapid_approval(
        df, rapid_approval_minutes, auto_entry_sources or [],
    )
    result = result | rapid_flags

    return result


def _calc_is_abnormal(df: pd.DataFrame) -> pd.Series:
    """비정상 시간대 여부를 bool Series로 반환."""
    tz_abnormal = df["time_zone_category"].isin(["midnight", "overtime"])
    weekend = df.get("is_weekend", pd.Series(False, index=df.index)).fillna(False)
    holiday = df.get("is_holiday", pd.Series(False, index=df.index)).fillna(False)
    return tz_abnormal | weekend | holiday


def _calc_user_abnormal_stats(
    df: pd.DataFrame, is_abnormal: pd.Series,
) -> pd.DataFrame:
    """사용자별 비정상 비율 + 심야 건수 통계 산출.

    Returns: DataFrame(index=created_by, columns=[abnormal_ratio, midnight_count])
    """
    # Why: NaN created_by는 분석 대상에서 제외
    valid_mask = df["created_by"].notna()
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


def _find_outlier_users(
    user_stats: pd.DataFrame,
    *,
    sigma_threshold: float,
    min_abnormal_ratio: float,
    min_midnight_entries: int,
) -> set[str]:
    """3σ 또는 절대 임계 기준으로 이상치 사용자 식별."""
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
        manual_mask = ~df["source"].isin(auto_entry_sources)

    # Why: automated_system 계정은 ERP 자동 처리 — 인간 검토 대상 아님
    if "user_persona" in df.columns:
        manual_mask = manual_mask & (df["user_persona"] != "automated_system")

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
