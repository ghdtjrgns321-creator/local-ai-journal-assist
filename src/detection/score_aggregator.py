"""종합 anomaly_score 산출 — 다중 DetectionResult 가중합.

Why: 탐지 트랙(Layer A/B/C, Benford, Phase 2 ML)별 점수를
     하나의 anomaly_score로 합산하여 risk_level 분류.
     BaseDetector를 상속하지 않는 순수 함수 모듈.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.detection.base import DetectionResult
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    Layer,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# ── public API ─────────────────────────────────────────────


def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    Returns:
        DataFrame(anomaly_score, risk_level, flagged_rules), index=df.index.
    """
    # Why: Layer enum 값(.value)과 track_name 문자열 통일
    w = {k.value if isinstance(k, Layer) else k: v
         for k, v in (weights or LAYER_WEIGHTS).items()}

    result_map = {r.track_name: r for r in results}

    # Why: 각 레이어별 scores × weight 가중합. 에러 격리로 한 레이어 실패해도 계속 진행.
    score_acc = pd.Series(0.0, index=df.index)
    for track_name, weight in w.items():
        if track_name not in result_map:
            logger.warning("트랙 '%s' 결과 없음 — 0점 처리", track_name)
            continue
        try:
            layer_scores = result_map[track_name].scores.reindex(df.index, fill_value=0.0)
            score_acc = score_acc + layer_scores * weight
        except Exception:
            logger.warning("트랙 '%s' 점수 합산 실패 — 0점 처리", track_name, exc_info=True)

    anomaly_score = score_acc.clip(0.0, 1.0)

    agg_df = pd.DataFrame({
        "anomaly_score": anomaly_score,
        "risk_level": classify_risk_level(anomaly_score),
        "flagged_rules": _collect_flagged_rules(results, df.index),
    }, index=df.index)

    return _apply_auto_escalation(agg_df, results)


def classify_risk_level(scores: pd.Series) -> pd.Series:
    """anomaly_score → risk_level 변환 (4등급).

    Normal→Low→Medium→High 순서로 덮어쓰기하여 최종 등급 결정.
    """
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[scores > RISK_THRESHOLDS[RiskLevel.LOW]] = RiskLevel.LOW
    levels[scores > RISK_THRESHOLDS[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[scores > RISK_THRESHOLDS[RiskLevel.HIGH]] = RiskLevel.HIGH
    return levels


# ── private helpers ────────────────────────────────────────


def _apply_auto_escalation(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Layer A ≥ 1 위반 AND Layer B ≥ 2 위반 → risk_level = High 강제.

    Why: 무결성 위반 + 부정 의심 중복은 가중합 점수와 무관하게 고위험.
    """
    result_map = {r.track_name: r for r in results}
    layer_a = result_map.get(Layer.LAYER_A.value)
    layer_b = result_map.get(Layer.LAYER_B.value)
    if layer_a is None or layer_b is None:
        return agg_df

    # Why: details > 0인 컬럼 수 = 해당 행에서 위반된 룰 수
    a_flagged = (layer_a.details.reindex(agg_df.index, fill_value=0.0) > 0).sum(axis=1) >= 1
    b_flagged = (layer_b.details.reindex(agg_df.index, fill_value=0.0) > 0).sum(axis=1) >= 2
    escalate_mask = a_flagged & b_flagged

    if escalate_mask.any():
        agg_df.loc[escalate_mask, "risk_level"] = RiskLevel.HIGH
    return agg_df


def _collect_flagged_rules(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.Series:
    """행별 위반 룰 ID를 comma-separated 문자열로 반환.

    Why: mask.dot(cols + ",") 벡터화로 100만 행도 1초 미만 처리.
         apply(axis=1)은 내부 Python for 루프라 대규모 데이터에서 병목.
    """
    details_list = [r.details for r in results if not r.details.empty]
    if not details_list:
        return pd.Series("", index=index)

    # Why: 동일 rule_id가 여러 트랙에 존재할 수 있음 (예: C07이 layer_c와 benford 양쪽).
    #      중복 컬럼을 max로 합쳐서 "C07,C07" 이중 출력 방지.
    combined = pd.concat(details_list, axis=1).reindex(index).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    mask = combined > 0
    cols_with_comma = mask.columns + ","
    flagged_str = mask.dot(cols_with_comma)
    return flagged_str.str.rstrip(",")
