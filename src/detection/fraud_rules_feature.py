"""피처 기반 부정 탐지 룰 — L4-01, L2-01, L1-04, L3-02.

피처 엔진(src/feature/)이 미리 생성한 bool/float 컬럼을 조합하는 단순 마스크 연산.
피처 미존재 시 Series(False) 반환 → 오케스트레이터가 warning 기록.
"""

from __future__ import annotations

import pandas as pd


def _check_features(df: pd.DataFrame, required: list[str]) -> list[str]:
    """필요 피처 존재 확인. 누락 컬럼 리스트 반환."""
    return [c for c in required if c not in df.columns]


def b01_revenue_manipulation(
    df: pd.DataFrame,
    zscore_threshold: float = 3.0,
) -> pd.Series:
    """L4-01 매출 이상 변동: 매출 계정 + Z-score 초과.

    Why: PCAOB AS 2401 §32(c) — 매출은 가장 빈번한 부정 대상.
         매출 계정(4xxx)에서 통계적 이상치를 보이는 전표를 탐지.
    """
    missing = _check_features(df, ["is_revenue_account", "amount_zscore"])
    if missing:
        return pd.Series(False, index=df.index)
    return df["is_revenue_account"].fillna(False) & (
        df["amount_zscore"].fillna(0.0) > zscore_threshold
    )


def b02_near_threshold(df: pd.DataFrame) -> pd.Series:
    """L2-01 승인한도 직하: 한도 × 0.9 ≤ 금액 < 한도.

    Why: 감사기준서 240호 A45(e) — 승인 우회 의도를 탐지.
    """
    if "is_near_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["is_near_threshold"].fillna(False)


def b03_exceeds_threshold(df: pd.DataFrame) -> pd.Series:
    """L1-04 승인한도 초과: 금액 ≥ 승인한도.

    Why: K-SOX 승인 통제 — 한도 초과 건이 적절히 승인되었는지 식별.
    """
    if "exceeds_threshold" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["exceeds_threshold"].fillna(False)


def b08_manual_override(df: pd.DataFrame) -> pd.Series:
    """L3-02 수기 전표: 수기 입력 + 승인한도 초과.

    Why: 감사기준서 240호 A45(b) + 외감법 §8② — 자동 프로세스 우회.
         수기 입력 자체는 정상이나, 고액 + 수기 조합은 부정 위험.
    """
    missing = _check_features(df, ["is_manual_je", "exceeds_threshold"])
    if missing:
        return pd.Series(False, index=df.index)
    return df["is_manual_je"].fillna(False) & df["exceeds_threshold"].fillna(False)
