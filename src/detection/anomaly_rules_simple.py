"""피처 기반 이상 징후 룰 — C01~C06, C08.

피처 엔진(src/feature/)이 미리 생성한 bool/float 컬럼을 조합하는 마스크 연산.
피처 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

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
