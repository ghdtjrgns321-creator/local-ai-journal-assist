"""라벨 전략 — 지도학습용 타겟(y) 생성.

Why: ML 모델 학습에는 라벨이 필요하다. 3가지 전략을 제공하여
DataSynth ground truth, Phase 1b 룰 기반 pseudo-label, 또는
양쪽을 결합한 hybrid 방식을 선택할 수 있다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class LabelResult:
    """라벨링 결과 + 메타데이터."""

    y: pd.Series                # 0(정상) / 1(이상)
    label_source: str           # "datasynth" | "pseudo" | "hybrid"
    positive_rate: float        # 양성 비율 (0.0~1.0)
    source_breakdown: dict      # 출처별 양성 수 {"is_fraud": n, ...}


def create_labels(
    df: pd.DataFrame,
    detection_scores: pd.Series | None = None,
    *,
    strategy: str = "hybrid",
    pseudo_threshold: float = 0.5,
    fraud_col: str = "is_fraud",
    anomaly_col: str = "is_anomaly",
) -> LabelResult:
    """DataFrame에서 라벨(y) 생성.

    Parameters
    ----------
    df : 피처 DataFrame (is_fraud/is_anomaly 컬럼 포함 가능)
    detection_scores : Phase 1b score_aggregator의 anomaly_score (0~1)
    strategy : "datasynth" | "pseudo" | "hybrid"
    pseudo_threshold : pseudo-label에서 양성 판정 임계값
    fraud_col, anomaly_col : DataSynth 레이블 컬럼명
    """
    if strategy == "datasynth":
        return _from_datasynth(df, fraud_col, anomaly_col)
    if strategy == "pseudo":
        return _from_pseudo(df, detection_scores, pseudo_threshold)
    if strategy == "hybrid":
        return _hybrid(df, detection_scores, pseudo_threshold, fraud_col, anomaly_col)

    raise ValueError(f"알 수 없는 라벨 전략: {strategy}")


def _from_datasynth(
    df: pd.DataFrame,
    fraud_col: str,
    anomaly_col: str,
) -> LabelResult:
    """DataSynth ground truth 컬럼에서 라벨 생성."""
    breakdown: dict[str, int] = {}
    y = pd.Series(np.zeros(len(df), dtype=int), index=df.index)

    if fraud_col in df.columns:
        fraud_mask = df[fraud_col].fillna(False).astype(bool)
        y = y | fraud_mask.astype(int)
        breakdown[fraud_col] = int(fraud_mask.sum())

    if anomaly_col in df.columns:
        anomaly_mask = df[anomaly_col].fillna(False).astype(bool)
        y = y | anomaly_mask.astype(int)
        breakdown[anomaly_col] = int(anomaly_mask.sum())

    if not breakdown:
        logger.warning("DataSynth 레이블 컬럼(%s, %s) 없음", fraud_col, anomaly_col)

    pos_rate = float(y.mean()) if len(y) > 0 else 0.0
    logger.info("라벨 생성(datasynth): 양성률 %.2f%% (%d건)", pos_rate * 100, y.sum())

    return LabelResult(
        y=y,
        label_source="datasynth",
        positive_rate=pos_rate,
        source_breakdown=breakdown,
    )


def _from_pseudo(
    df: pd.DataFrame,
    detection_scores: pd.Series | None,
    threshold: float,
) -> LabelResult:
    """Phase 1b 룰 기반 pseudo-label 생성."""
    if detection_scores is None:
        raise ValueError("pseudo 전략에는 detection_scores가 필요합니다")

    y = (detection_scores >= threshold).astype(int)
    pos_rate = float(y.mean()) if len(y) > 0 else 0.0

    logger.info(
        "라벨 생성(pseudo): threshold=%.2f, 양성률 %.2f%% (%d건)",
        threshold, pos_rate * 100, y.sum(),
    )
    return LabelResult(
        y=y,
        label_source="pseudo",
        positive_rate=pos_rate,
        source_breakdown={"rule_flagged": int(y.sum())},
    )


def _hybrid(
    df: pd.DataFrame,
    detection_scores: pd.Series | None,
    threshold: float,
    fraud_col: str,
    anomaly_col: str,
) -> LabelResult:
    """DataSynth 우선, 없으면 pseudo 폴백."""
    has_datasynth = fraud_col in df.columns or anomaly_col in df.columns

    if has_datasynth:
        result = _from_datasynth(df, fraud_col, anomaly_col)
        result.label_source = "hybrid"
        if result.positive_rate == 0.0:
            logger.warning(
                "DataSynth 레이블 컬럼이 있지만 양성이 0건입니다. "
                "XGBoost 등 지도학습에서 학습이 불가능할 수 있습니다.",
            )
        return result

    if detection_scores is not None:
        result = _from_pseudo(df, detection_scores, threshold)
        result.label_source = "hybrid"
        return result

    # 양쪽 모두 없으면 전체 정상으로 처리 (비지도 전용)
    logger.warning("DataSynth/detection_scores 모두 없음 → 전체 정상 라벨")
    y = pd.Series(np.zeros(len(df), dtype=int), index=df.index)
    return LabelResult(
        y=y,
        label_source="hybrid",
        positive_rate=0.0,
        source_breakdown={},
    )
