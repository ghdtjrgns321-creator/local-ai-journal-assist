"""종합 anomaly_score 산출 — 다중 DetectionResult 가중합 + Top-side JE 복합 탐지.

Why: 탐지 트랙(Layer A/B/C, Benford, Phase 2 ML)별 점수를
     하나의 anomaly_score로 합산하여 risk_level 분류.
     B19 Top-side JE는 기존 룰 플래그를 조합하는 후처리로 여기서 산출.
     BaseDetector를 상속하지 않는 순수 함수 모듈.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.detection.base import DetectionResult
from config.settings import get_settings
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    Layer,
    RiskLevel,
)

# Why: Top-side JE 가점 조건 수 (정규화 분모). 게이트키퍼(수기)는 제외.
_TOPSIDE_CONDITIONS = 5

logger = logging.getLogger(__name__)


# ── public API ─────────────────────────────────────────────


def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    settings: object | None = None,
) -> pd.DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    Args:
        settings: AuditSettings 인스턴스. None이면 get_settings() 싱글톤 사용.

    Returns:
        DataFrame(anomaly_score, risk_level, flagged_rules), index=df.index.
    """
    if settings is None:
        settings = get_settings()
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
        "risk_level": classify_risk_level(anomaly_score, thresholds),
        "flagged_rules": _collect_flagged_rules(results, df.index),
    }, index=df.index)

    agg_df = _apply_auto_escalation(agg_df, results)
    return _apply_topside_escalation(agg_df, df, results, settings=settings)


def classify_risk_level(
    scores: pd.Series,
    thresholds: dict[str, float] | None = None,
) -> pd.Series:
    """anomaly_score → risk_level 변환 (4등급).

    Normal→Low→Medium→High 순서로 덮어쓰기하여 최종 등급 결정.
    thresholds가 None이면 모듈 상수 RISK_THRESHOLDS 사용.
    """
    t = thresholds or RISK_THRESHOLDS
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[scores > t[RiskLevel.LOW]] = RiskLevel.LOW
    levels[scores > t[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[scores > t[RiskLevel.HIGH]] = RiskLevel.HIGH
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


# ── B19 Top-side JE 복합 탐지 ────────────────────────────


def _get_rule_flag(
    result_map: dict[str, DetectionResult],
    rule_id: str,
    layer_name: str,
    index: pd.Index,
) -> pd.Series:
    """특정 레이어 details에서 룰 플래그 여부를 bool Series로 반환.

    Why: 레이어 누락이나 룰 미실행(skipped) 시에도 에러 없이 False 반환.
    """
    layer = result_map.get(layer_name)
    if layer is None or rule_id not in layer.details.columns:
        return pd.Series(False, index=index)
    return layer.details[rule_id].reindex(index, fill_value=0.0) > 0


def _compute_topside_score(
    df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.Series:
    """B19 Top-side JE 가중 점수 산출.

    Why: 수기 전표(is_manual_je)가 게이트키퍼. 자동 전표는 가점이 만점이어도 0점.
         게이트 통과 시 5개 가점 조건(C01, B06/B09, A03/C09, C08, C06) 합산.
    """
    result_map = {r.track_name: r for r in results}
    idx = df.index
    la, lb, lc = Layer.LAYER_A.value, Layer.LAYER_B.value, Layer.LAYER_C.value
    score = pd.Series(0, index=idx, dtype=int)

    # 가점 1: 기말 시점 (C01)
    score += _get_rule_flag(result_map, "C01", lc, idx).astype(int)

    # 가점 2: 자기승인(B06) 또는 승인 생략(B09)
    cond_b06 = _get_rule_flag(result_map, "B06", lb, idx)
    cond_b09 = _get_rule_flag(result_map, "B09", lb, idx)
    score += (cond_b06 | cond_b09).astype(int)

    # 가점 3: 비정상 계정 — 무효(A03) 또는 희소 쌍(C09)
    cond_a03 = _get_rule_flag(result_map, "A03", la, idx)
    cond_c09 = _get_rule_flag(result_map, "C09", lc, idx)
    score += (cond_a03 | cond_c09).astype(int)

    # 가점 4: 이상 고액 (C08)
    score += _get_rule_flag(result_map, "C08", lc, idx).astype(int)

    # 가점 5: 위험 적요 (C06)
    score += _get_rule_flag(result_map, "C06", lc, idx).astype(int)

    # Why: 게이트키퍼 — 수기 전표가 아니면 가점 전체를 0으로 초기화.
    #      자동 배치 전표가 우연히 다른 조건에 걸려도 Top-side JE로 과탐되지 않음.
    if "is_manual_je" in df.columns:
        is_manual = df["is_manual_je"].fillna(False)
    else:
        is_manual = pd.Series(False, index=idx)
    score = score * is_manual.astype(int)

    return score


def _apply_topside_escalation(
    agg_df: pd.DataFrame,
    df: pd.DataFrame,
    results: list[DetectionResult],
    settings: object | None = None,
) -> pd.DataFrame:
    """B19 Top-side JE 탐지 결과를 agg_df에 반영.

    Why: 수기 전표이면서 가점 ≥ threshold인 행을 High로 승격하고
         flagged_rules에 B19을 추가. topside_score 컬럼도 항상 생성.
    """
    if settings is None:
        settings = get_settings()
    raw_score = _compute_topside_score(df, results)

    # Why: topside_score 컬럼은 항상 추가 (하류 코드 컬럼 보장)
    agg_df["topside_score"] = raw_score / _TOPSIDE_CONDITIONS

    topside_mask = raw_score >= settings.topside_threshold
    if not topside_mask.any():
        return agg_df

    # risk_level 승격
    agg_df.loc[topside_mask, "risk_level"] = RiskLevel.HIGH

    # Why: _collect_flagged_rules의 벡터화(mask.dot) 패턴과 일관되게 apply 회피.
    existing = agg_df.loc[topside_mask, "flagged_rules"]
    non_empty = existing != ""
    agg_df.loc[topside_mask & non_empty.reindex(topside_mask.index, fill_value=False), "flagged_rules"] = existing[non_empty] + ",B19"
    agg_df.loc[topside_mask & ~non_empty.reindex(topside_mask.index, fill_value=True), "flagged_rules"] = "B19"

    logger.info(
        "B19 Top-side JE: %d/%d건 플래그 (임계값 %d/%d)",
        topside_mask.sum(), len(df), settings.topside_threshold, _TOPSIDE_CONDITIONS,
    )

    return agg_df
