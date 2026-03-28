"""피처 기반 이상 징후 룰 — C01~C06, C08, C10, C12.

피처 엔진(src/feature/)이 미리 생성한 bool/float 컬럼을 조합하는 마스크 연산.
피처 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def c01_period_end_large(df: pd.DataFrame, quantile: float = 0.75) -> pd.Series:
    """C01 기말 대규모: 월말 근접 + 금액 > Q3.

    Why: PCAOB AS 240 §32(b), FSS 결산 수정 조작 패턴.
         기말에 집중되는 고액 전표는 결산 조정 조작 가능성.
    """
    if "is_period_end" not in df.columns:
        return pd.Series(False, index=df.index)
    # Why: max(debit, credit)로 대표 금액 산출 — fraud_rules_groupby 패턴 동일
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    # Why: 전체 모집단 Q3 기준 — 기말 행이 '전체 대비 고액'인지 판단.
    #      기말 내부 분포 기준으로 바꾸려면 base[period_end_mask].quantile() 사용.
    #      Phase 2에서 계정그룹별 Q3로 확장 예정.
    threshold = base.quantile(quantile)
    return df["is_period_end"].fillna(False) & (base > threshold)


def c02_weekend_entry(df: pd.DataFrame) -> pd.Series:
    """C02 주말 전기: 토/일 또는 공휴일 전기.

    Why: PCAOB AS 240 A49(c) — 비정상 시점 거래는 승인 우회 의심.
    """
    weekend = df.get("is_weekend", pd.Series(False, index=df.index)).fillna(False)
    holiday = df.get("is_holiday", pd.Series(False, index=df.index)).fillna(False)
    return weekend | holiday


def c03_after_hours_entry(df: pd.DataFrame) -> pd.Series:
    """C03 심야 전기: 업무시간(09~18시) 외 전기.

    Why: PCAOB AS 240 A49(c) — 심야 전기는 감시 부재 시점 악용 가능.
    """
    if "is_after_hours" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_after_hours"].fillna(False)


def c04_backdated_entry(
    df: pd.DataFrame,
    threshold_days: int = 30,
) -> pd.Series:
    """C04 소급 전기: 전기일-전표일 차이가 임계 초과.

    Why: PCAOB AS 240 A49(c), FSS 횡령 은폐 — 과도한 소급은 기록 조작 의심.
    """
    if "days_backdated" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["days_backdated"].fillna(0).abs() > threshold_days


def c05_fiscal_period_mismatch(df: pd.DataFrame) -> pd.Series:
    """C05 기간 불일치: 회계기간 ≠ 전기월.

    Why: PCAOB AS 240 §32(b) — 기간 귀속 오류는 의도적 기간 이동 가능성.
    """
    if "fiscal_period_mismatch" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["fiscal_period_mismatch"].fillna(False)


def c06_risky_description(df: pd.DataFrame) -> pd.Series:
    """C06 위험 적요: 적요 품질 불량 또는 위험 키워드 포함.

    Why: PCAOB AS 240 A49(c), K-SOX §8①1호 — 적요 미비는 전표 추적 방해.
    """
    # Why: OR 조건 — 적요가 부실하거나 위험 키워드가 있으면 플래그
    if "description_quality" not in df.columns and "has_risk_keyword" not in df.columns:
        return pd.Series(False, index=df.index)

    poor_quality = (
        df["description_quality"].isin(["missing", "poor"])
        if "description_quality" in df.columns
        else pd.Series(False, index=df.index)
    )
    high_risk = (
        df["has_risk_keyword"].isin(["high", "medium"])
        if "has_risk_keyword" in df.columns
        else pd.Series(False, index=df.index)
    )
    return poor_quality | high_risk


def c08_amount_outlier(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
) -> pd.Series:
    """C08 이상 고액: Z-score 기준 통계적 이상치.

    Why: PCAOB AS 240 §33(b), ISA 315 — 3σ 초과 금액은 조작 가능성.
    """
    if "amount_zscore" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["amount_zscore"].fillna(0.0).abs() > zscore_threshold


def c10_suspense_account(df: pd.DataFrame) -> pd.Series:
    """C10 가수금 장기체류: 가수금·가지급 등 가계정 사용 전표.

    Why: 외감법 §8①2호, FSS 횡령 은폐 사례 — 가계정 장기 체류는
         자금 유용을 숨기는 수단으로 사용될 수 있다.
    """
    if "is_suspense_account" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_suspense_account"].fillna(False)


# ── C12: 비정상 시간대 입력자 집중 분석 ─────────────────────────

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
    """C12 비정상 시간대 입력자 집중: 사용자별 비정상 비율 3σ + 급속 승인.

    Why: KLCA IT 체크리스트 — C02/C03은 건별 플래그만 수행.
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

    # Why: 자기 승인은 B06에서 이미 탐지 → 여기서 중복 플래그 불필요
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
