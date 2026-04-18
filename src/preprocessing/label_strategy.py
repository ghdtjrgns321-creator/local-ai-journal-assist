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

from src.ingest.datasynth_labels import ensure_datasynth_ground_truth
from src.preprocessing.constants import DEFAULT_GROUND_TRUTH_LABEL_COLUMNS

logger = logging.getLogger(__name__)


@dataclass
class LabelResult:
    """라벨 생성 결과."""

    y: np.ndarray
    strategy: str
    label_source: str
    positive_rate: float
    positive_count: int = 0
    label_quality: str = "unknown"
    gate_status: str = "unknown"
    gate_reason: str | None = None
    is_supervised_eligible: bool = False
    source_breakdown: dict | None = field(default=None)


def create_labels(
    df: pd.DataFrame,
    detection_scores: np.ndarray | None = None,
    strategy: str = "hybrid",
    fraud_col: str = "is_fraud",
    anomaly_col: str = "is_anomaly",
    label_columns: tuple[str, ...] | list[str] | None = None,
    threshold: float = 0.5,
) -> LabelResult:
    """전략별 라벨 생성 진입점."""
    gt_label_columns = tuple(label_columns or DEFAULT_GROUND_TRUTH_LABEL_COLUMNS)
    if strategy == "datasynth":
        return _from_datasynth(df, fraud_col, anomaly_col, gt_label_columns)
    if strategy == "pseudo":
        return _from_pseudo(df, detection_scores, threshold)
    return _hybrid(
        df, detection_scores, threshold, fraud_col, anomaly_col, gt_label_columns,
    )


def create_labels_from_feedback(
    df: pd.DataFrame,
    feedback_labels: pd.DataFrame | None,
) -> LabelResult | None:
    """Build supervised labels from normalized HITL document labels when available."""
    if feedback_labels is None or feedback_labels.empty or "document_id" not in df.columns:
        return None

    label_map = {
        str(row["document_id"]): int(str(row.get("decision")) == "confirmed_issue")
        for _, row in feedback_labels.iterrows()
        if row.get("decision") in {"confirmed_issue", "false_positive"}
    }
    if not label_map:
        return None

    y = np.asarray([label_map.get(str(doc_id), 0) for doc_id in df["document_id"]], dtype=int)
    pos_rate = float(y.mean()) if len(y) > 0 else 0.0
    return _build_label_result(
        y=y,
        strategy="feedback",
        label_source="ground_truth",
        positive_rate=pos_rate,
        source_breakdown={
            "confirmed_issue_docs": int(sum(value == 1 for value in label_map.values())),
            "false_positive_docs": int(sum(value == 0 for value in label_map.values())),
        },
    )


def _from_datasynth(
    df: pd.DataFrame,
    fraud_col: str,
    anomaly_col: str,
    label_columns: tuple[str, ...],
) -> LabelResult:
    """DataSynth GT 라벨: is_fraud or is_anomaly → 양성."""
    df = ensure_datasynth_ground_truth(df)
    n = len(df)
    y = np.zeros(n, dtype=int)
    breakdown = {}

    columns_to_use = tuple(dict.fromkeys(label_columns or (fraud_col, anomaly_col)))

    for col in columns_to_use:
        if col in df.columns:
            mask = df[col].fillna(0).astype(bool)
            y = y | mask.values.astype(int)
            breakdown[col] = int(mask.sum())

    pos_rate = float(y.mean()) if n > 0 else 0.0
    return _build_label_result(
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
    return _build_label_result(
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
    label_columns: tuple[str, ...],
) -> LabelResult:
    """DataSynth 우선 → pseudo 폴백 → 비지도(전체 0)."""
    # 1) DataSynth 시도
    ds_result = _from_datasynth(df, fraud_col, anomaly_col, label_columns)
    if ds_result.positive_rate > 0:
        ds_result.strategy = "hybrid"
        return ds_result

    # 2) pseudo 폴백
    if detection_scores is not None:
        pseudo_result = _from_pseudo(df, detection_scores, threshold)
        pseudo_result.strategy = "hybrid"
        pseudo_result.label_source = "pseudo_fallback"
        # Why: pseudo도 양성 0이면 사실상 비지도 강제 — 사용자/로그에 알려야 함
        if pseudo_result.positive_rate == 0:
            logger.warning(
                "pseudo 폴백도 양성 0건 (threshold=%.2f). "
                "비지도 모드와 동일하게 동작합니다. threshold 하향 검토 필요.",
                threshold,
            )
        return pseudo_result

    # 3) 양쪽 모두 불가 → 비지도 모드
    logger.info("라벨 소스 없음 → 전체 정상(0) 반환 (비지도 전용)")
    return _build_label_result(
        y=np.zeros(len(df), dtype=int),
        strategy="hybrid",
        label_source="unsupervised",
        positive_rate=0.0,
    )


def _build_label_result(
    *,
    y: np.ndarray,
    strategy: str,
    label_source: str,
    positive_rate: float,
    source_breakdown: dict | None = None,
) -> LabelResult:
    positive_count = int(np.asarray(y).sum())
    label_quality, gate_status, gate_reason, is_supervised_eligible = _qualify_label_source(
        label_source=label_source,
        positive_count=positive_count,
        positive_rate=positive_rate,
    )
    return LabelResult(
        y=np.asarray(y, dtype=int),
        strategy=strategy,
        label_source=label_source,
        positive_rate=positive_rate,
        positive_count=positive_count,
        label_quality=label_quality,
        gate_status=gate_status,
        gate_reason=gate_reason,
        is_supervised_eligible=is_supervised_eligible,
        source_breakdown=source_breakdown,
    )


def _qualify_label_source(
    *,
    label_source: str,
    positive_count: int,
    positive_rate: float,
) -> tuple[str, str, str | None, bool]:
    trusted_sources = {"ground_truth", "synthetic", "holdout_test", "train_oof", "oof_fold"}
    circular_sources = {"detection_scores", "pseudo_fallback"}
    absent_sources = {"unsupervised"}

    if label_source in circular_sources:
        return "circular_risk", "fallback_to_unsupervised", "circular_label_risk", False
    if label_source in absent_sources:
        return "absent", "fallback_to_unsupervised", "missing_ground_truth_labels", False
    if label_source not in trusted_sources:
        return "unknown", "fallback_to_unsupervised", "untrusted_label_source", False
    if positive_count == 0:
        return "trusted", "blocked", "no_positive_labels", False
    if positive_rate <= 0.0:
        return "trusted", "blocked", "no_positive_labels", False
    return "trusted", "eligible", None, True
