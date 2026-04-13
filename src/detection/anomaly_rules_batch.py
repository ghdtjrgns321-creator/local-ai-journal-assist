"""배치 전표 이상 패턴 — C13.

Why: 금융권 IT 감사 가이드라인. 배치 전표는 대량 자동 처리로
     개별 검토가 부재하여 기말 집중·대량 동시 생성·금액 이상 패턴 탐지 필요.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def c13_batch_anomaly(
    df: pd.DataFrame,
    batch_sources: list[str] | None = None,
    period_end_ratio: float = 0.5,
    simultaneous_threshold: int = 50,
    amount_zscore: float = 3.0,
) -> pd.Series:
    """C13 배치 전표 이상: 3가지 하위 패턴 OR 결합.

    Why: 배치 전표는 자동 처리되므로 개별 승인 없이 대량 전기됨.
         기말 집중, 대량 동시 생성, 금액 이상 중 하나라도 해당하면 플래그.
    """
    if "source" not in df.columns:
        return pd.Series(False, index=df.index)

    sources = batch_sources or ["batch", "BATCH"]
    is_batch = df["source"].isin(sources)
    if not is_batch.any():
        return pd.Series(False, index=df.index)

    result = pd.Series(False, index=df.index)
    result = result | _batch_period_end_concentration(df, is_batch, period_end_ratio)
    result = result | _batch_simultaneous_creation(df, is_batch, simultaneous_threshold)
    result = result | _batch_amount_outlier(df, is_batch, amount_zscore)
    return result


def _batch_period_end_concentration(
    df: pd.DataFrame, is_batch: pd.Series, ratio: float,
) -> pd.Series:
    """배치 전표 중 기말 비율이 임계 초과 → 해당 배치 전표 전체 플래그.

    Why: 배치 런(batch run)을 하나의 감사 단위로 취급 (PCAOB AS 240 §32).
         기말 집중 비율이 높으면 해당 기간의 배치 처리 전체가 결산 조정 목적 의심.
         기말이 아닌 배치 행도 같은 자동화 프로세스의 산물이므로 함께 플래그.
    """
    if "is_period_end" not in df.columns:
        return pd.Series(False, index=df.index)
    batch_mask = is_batch.fillna(False)
    period_end = df["is_period_end"].fillna(False)
    batch_count = batch_mask.sum()
    if batch_count == 0:
        return pd.Series(False, index=df.index)
    # Why: 배치 전표 중 기말 비율 → 임계 초과 시 배치 전표 전체 플래그
    batch_period_ratio = (batch_mask & period_end).sum() / batch_count
    if batch_period_ratio > ratio:
        return batch_mask
    return pd.Series(False, index=df.index)


def _batch_simultaneous_creation(
    df: pd.DataFrame, is_batch: pd.Series, threshold: int,
) -> pd.Series:
    """같은 날짜에 배치 전표 N건 이상 → 해당 일자 배치 행 플래그.

    Why: 대량 동시 생성은 자동화 오류 또는 의도적 대량 전기 의심.
    """
    if "posting_date" not in df.columns:
        return pd.Series(False, index=df.index)
    batch_only = df[is_batch.fillna(False)]
    if batch_only.empty:
        return pd.Series(False, index=df.index)
    # Why: 일자별 배치 건수 → 임계 초과 일자의 배치 행 플래그
    daily_counts = batch_only.groupby("posting_date").size()
    flagged_dates = daily_counts[daily_counts >= threshold].index
    return is_batch & df["posting_date"].isin(flagged_dates)


def _batch_amount_outlier(
    df: pd.DataFrame, is_batch: pd.Series, zscore_threshold: float,
) -> pd.Series:
    """배치 전표 내 Z-score 이상치 → 해당 행 플래그.

    Why: 배치 내 금액이 동일 패턴을 벗어나면 수정·오입력 가능성.
    """
    batch_mask = is_batch.fillna(False)
    if not batch_mask.any():
        return pd.Series(False, index=df.index)
    base = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    batch_amounts = base[batch_mask]
    std = batch_amounts.std()
    # Why: 급여·상각 등 동일 금액 배치는 std=0 → 이상치 없음으로 처리
    if std == 0 or np.isnan(std):
        return pd.Series(False, index=df.index)
    mean = batch_amounts.mean()
    zscores = ((base - mean) / std).abs()
    return batch_mask & (zscores > zscore_threshold)
