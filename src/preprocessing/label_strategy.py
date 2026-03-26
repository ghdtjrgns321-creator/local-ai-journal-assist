"""라벨 생성 전략 — datasynth / pseudo / hybrid 3계층.

Why: 감사 데이터는 라벨 확보가 어렵다.
DataSynth(시뮬레이션 GT) → pseudo(룰 기반 점수) → hybrid(우선순위 폴백)
3단계로 라벨 생성을 시도하여 지도/비지도 모델 모두 대응한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class LabelResult:
    """라벨 생성 결과."""

    y: np.ndarray
    strategy: str
    label_source: str
    positive_rate: float
    source_breakdown: dict | None = field(default=None)


def create_labels(
    df: pd.DataFrame,
    detection_scores: np.ndarray | None = None,
    strategy: str = "hybrid",
    fraud_col: str = "is_fraud",
    anomaly_col: str = "is_anomaly",
    threshold: float = 0.5,
) -> LabelResult:
    """전략별 라벨 생성 진입점."""
    if strategy == "datasynth":
        return _from_datasynth(df, fraud_col, anomaly_col)
    if strategy == "pseudo":
        return _from_pseudo(df, detection_scores, threshold)
    return _hybrid(df, detection_scores, threshold, fraud_col, anomaly_col)


def _from_datasynth(
    df: pd.DataFrame,
    fraud_col: str,
    anomaly_col: str,
) -> LabelResult:
    """DataSynth GT 라벨: is_fraud or is_anomaly → 양성."""
    n = len(df)
    y = np.zeros(n, dtype=int)
    breakdown = {}

    for col in [fraud_col, anomaly_col]:
        if col in df.columns:
            mask = df[col].fillna(0).astype(bool)
            y = y | mask.values.astype(int)
            breakdown[col] = int(mask.sum())

    pos_rate = float(y.mean()) if n > 0 else 0.0
    return LabelResult(
        y=y,
        strategy="datasynth",
        label_source="ground_truth",
        positive_rate=pos_rate,
        source_breakdown=breakdown if breakdown else None,
    )


def _from_pseudo(
    df: pd.DataFrame,
    detection_scores: np.ndarray | None,
    threshold: float,
) -> LabelResult:
    """룰 기반 탐지 점수 → 의사 라벨."""
    if detection_scores is None:
        raise ValueError("pseudo 전략에는 detection_scores가 필요합니다.")

    scores = np.asarray(detection_scores)
    y = (scores >= threshold).astype(int)
    pos_rate = float(y.mean()) if len(y) > 0 else 0.0
    return LabelResult(
        y=y,
        strategy="pseudo",
        label_source="detection_scores",
        positive_rate=pos_rate,
    )


def _hybrid(
    df: pd.DataFrame,
    detection_scores: np.ndarray | None,
    threshold: float,
    fraud_col: str,
    anomaly_col: str,
) -> LabelResult:
    """DataSynth 우선 → pseudo 폴백 → 비지도(전체 0)."""
    # 1) DataSynth 시도
    ds_result = _from_datasynth(df, fraud_col, anomaly_col)
    if ds_result.positive_rate > 0:
        ds_result.strategy = "hybrid"
        return ds_result

    # 2) pseudo 폴백
    if detection_scores is not None:
        pseudo_result = _from_pseudo(df, detection_scores, threshold)
        pseudo_result.strategy = "hybrid"
        pseudo_result.label_source = "pseudo_fallback"
        return pseudo_result

    # 3) 양쪽 모두 불가 → 비지도 모드
    logger.info("라벨 소스 없음 → 전체 정상(0) 반환 (비지도 전용)")
    return LabelResult(
        y=np.zeros(len(df), dtype=int),
        strategy="hybrid",
        label_source="unsupervised",
        positive_rate=0.0,
    )
