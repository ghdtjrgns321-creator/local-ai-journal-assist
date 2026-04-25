"""종합 anomaly_score 산출 — 다중 DetectionResult 가중합 + Top-side JE 복합 탐지.

Why: 탐지 트랙(Layer A/B/C, Benford, Phase 2 ML)별 점수를
     하나의 anomaly_score로 합산하여 risk_level 분류.
     Top-side JE score는 기존 룰 플래그를 조합하는 후처리로 여기서 산출.
     BaseDetector를 상속하지 않는 순수 함수 모듈.
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.constants import (
    BATCH_CORROBORATION_RULES,
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    TOPSIDE_BONUS_RULES,
    Layer,
    RiskLevel,
)

# Why: Top-side JE 가점 조건 수 (정규화 분모). ���이트키퍼(수기)는 제���.
_TOPSIDE_CONDITIONS = len(TOPSIDE_BONUS_RULES)
_BATCH_CORROBORATION_CONDITIONS = len(BATCH_CORROBORATION_RULES)

logger = logging.getLogger(__name__)


# ── public API ─────────────────────────────────────────────


def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    settings: object | None = None,
    *,
    stacking_scores: pd.Series | None = None,
) -> pd.DataFrame:
    """여러 트랙의 DetectionResult를 종합하여 최종 anomaly_score 산출.

    Args:
        settings: AuditSettings 인스턴스. None이면 get_settings() 싱글톤 사용.
        stacking_scores: Stacking meta-learner가 산출한 최종 점수.
            제공되면 기존 가중합을 건너뛰고 이 점수를 anomaly_score로 사용.

    Returns:
        DataFrame(anomaly_score, risk_level, flagged_rules), index=df.index.
    """
    if settings is None:
        settings = get_settings()

    # Why: stacking_scores가 있으면 meta-learner 점수를 직접 사용.
    #      없으면 기존 레이어별 가중합 로직 유지 (하위 호환).
    if stacking_scores is not None:
        anomaly_score = stacking_scores.reindex(df.index, fill_value=0.0).clip(0.0, 1.0)
    else:
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

    # Why: settings의 classification mode를 해석하여 quantile/absolute 분기
    mode = getattr(settings, "risk_classification_mode", "absolute")
    quantiles = None
    if mode == "quantile":
        quantiles = {
            RiskLevel.HIGH: getattr(settings, "risk_quantile_high", 0.90),
            RiskLevel.MEDIUM: getattr(settings, "risk_quantile_medium", 0.75),
            RiskLevel.LOW: getattr(settings, "risk_quantile_low", 0.50),
        }

    agg_df = pd.DataFrame({
        "anomaly_score": anomaly_score,
        "risk_level": classify_risk_level(
            anomaly_score, thresholds, mode=mode, quantiles=quantiles,
        ),
        "flagged_rules": _collect_flagged_rules(results, df.index),
    }, index=df.index)

    # Why: ML 개별 트랙 점수를 전용 컬럼으로 주입 → 대시보드/DB에서 분리 표시 가능.
    #      트랙 미존재(Cold Start) 시 컬럼 자체를 생성하지 않아 하위 호환 유지.
    _inject_ml_track_scores(agg_df, results)

    agg_df = _apply_auto_escalation(agg_df, results)
    agg_df = _apply_batch_corroboration(agg_df, results)
    return _inject_topside_score(agg_df, df, results)


def _inject_ml_track_scores(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> None:
    """ml_supervised/ml_unsupervised 트랙 점수를 DB 적재용 컬럼에 주입.

    Why: DB schema에 예약된 supervised_score, unsupervised_score 컬럼을 채운다.
         대시보드 Explorer Grid가 두 점수를 별도 바 렌더러로 표시하기 위함.
    """
    track_to_col = {
        "ml_supervised": "supervised_score",
        "ml_unsupervised": "unsupervised_score",
    }
    for r in results:
        col = track_to_col.get(r.track_name)
        if col is None:
            continue
        agg_df[col] = r.scores.reindex(agg_df.index)


def classify_risk_level(
    scores: pd.Series,
    thresholds: dict[str, float] | None = None,
    mode: str = "absolute",
    quantiles: dict[str, float] | None = None,
) -> pd.Series:
    """anomaly_score → risk_level 변환 (4등급).

    Normal→Low→Medium→High 순서로 덮어쓰기하여 최종 등급 결정.

    Args:
        scores: anomaly_score 시리즈
        thresholds: 절대값 임계값 (mode="absolute"). None이면 RISK_THRESHOLDS 사용
        mode: "absolute" (고정 임계값) 또는 "quantile" (분위수 기반)
        quantiles: 분위수 딕셔너리 (mode="quantile"). 예: {high:0.9, medium:0.75, low:0.5}

    Why (quantile 모드): Stacking Ridge 출력은 진짜 확률이 아니므로 절대값 기준은
    오해 유발. 분위수 기반은 "상위 10%를 HIGH"로 분류하여 감사 실무 워크플로우
    (Top-N 조사)에 정렬된다.
    """
    if mode == "quantile":
        return _classify_by_quantile(scores, quantiles)

    t = thresholds or RISK_THRESHOLDS
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[scores > t[RiskLevel.LOW]] = RiskLevel.LOW
    levels[scores > t[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[scores > t[RiskLevel.HIGH]] = RiskLevel.HIGH
    return levels


def _classify_by_quantile(
    scores: pd.Series,
    quantiles: dict[str, float] | None,
) -> pd.Series:
    """분위수 기반 risk_level 분류.

    Why: 절대 확률 가정이 깨져도 "상위 N%"는 항상 의미 있다.
         동일 score가 여러 행에 있을 때 stable ordering을 위해 rank(method='max') 사용.
    """
    q = quantiles or {
        RiskLevel.HIGH: 0.90,
        RiskLevel.MEDIUM: 0.75,
        RiskLevel.LOW: 0.50,
    }
    # Why: 모든 score가 0.0인 경우(결과 없음) quantile 계산 의미 없음 → NORMAL
    if scores.empty or scores.max() <= 0:
        return pd.Series(RiskLevel.NORMAL, index=scores.index)

    # Why: 동일 값의 묶음 처리를 위해 percentile rank 사용 (0~1)
    pct_rank = scores.rank(method="max", pct=True)
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[pct_rank > q[RiskLevel.LOW]] = RiskLevel.LOW
    levels[pct_rank > q[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[pct_rank > q[RiskLevel.HIGH]] = RiskLevel.HIGH
    # Why: score=0인 행은 언제나 NORMAL 보존 (rank가 높아도 실제 위험 없음)
    levels[scores <= 0] = RiskLevel.NORMAL
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

    # Why: 동일 rule_id가 여러 트랙에 존재할 수 있음 (예: L4-02이 layer_c와 benford 양쪽).
    #      중복 컬럼을 max로 합쳐서 "L4-02,L4-02" 이중 출력 방지.
    combined = pd.concat(details_list, axis=1).reindex(index).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    mask = combined > 0
    cols_with_comma = mask.columns + ","
    flagged_str = mask.dot(cols_with_comma)
    return flagged_str.str.rstrip(",")


# ── Top-side JE 복합 점수 ────────────────────────────


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
    """Top-side JE 가중 점수 산출.

    Why: 수기 전표(is_manual_je)가 게이트키퍼. 자동 전표는 가점이 만점이어도 0점.
         게이트 통과 시 5개 가점 조건(L3-04, L1-05/L1-07, L1-03/L4-04, L4-03, L3-08) 합산.
    """
    result_map = {r.track_name: r for r in results}
    idx = df.index
    score = pd.Series(0, index=idx, dtype=int)

    # Why: TOPSIDE_BONUS_RULES를 순회하여 하드코딩 제거.
    #      각 그룹 내 룰은 OR 결합 (하나라도 True면 가점 1).
    for _label, rule_pairs in TOPSIDE_BONUS_RULES:
        group_flag = pd.Series(False, index=idx)
        for rule_id, layer_name in rule_pairs:
            group_flag = group_flag | _get_rule_flag(result_map, rule_id, layer_name, idx)
        score += group_flag.astype(int)

    # Why: 게이트키퍼 — 수기 전표가 아니면 가점 전체를 0으로 초기화.
    #      자동 배치 전표가 우연히 다른 조건에 걸려도 Top-side JE로 과탐되지 않음.
    if "is_manual_je" in df.columns:
        is_manual = df["is_manual_je"].fillna(False)
    else:
        is_manual = pd.Series(False, index=idx)
    score = score * is_manual.astype(int)

    return score


def _inject_topside_score(
    agg_df: pd.DataFrame,
    df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Top-side JE score를 내부 case-priority feature로 추가한다."""
    raw_score = _compute_topside_score(df, results)

    # Why: topside_score 컬럼은 항상 추가 (하류 코드 컬럼 보장)
    agg_df["topside_score"] = raw_score / _TOPSIDE_CONDITIONS
    return agg_df


def _apply_batch_corroboration(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """L4-06 단독은 보조 신호로 두고, 결합 신호가 있을 때만 우선순위를 올린다.

    Why: 자동 배치 전표는 정상 대량 처리도 많다. 따라서 L4-06만으로 High를 만들지 않고,
         결산/cutoff, 통제 실패, 고액/계정 이상, 부실 적요, 역분개/중복 중
         복수 신호가 함께 있을 때 감사 검토 우선순위를 높인다.
    """
    result_map = {r.track_name: r for r in results}
    idx = agg_df.index
    batch_flag = _get_rule_flag(result_map, "L4-06", Layer.LAYER_C.value, idx)

    raw_score = pd.Series(0, index=idx, dtype=int)
    reason_parts = pd.Series("", index=idx, dtype="string")
    for label, rule_pairs in BATCH_CORROBORATION_RULES:
        group_flag = pd.Series(False, index=idx)
        for rule_id, layer_name in rule_pairs:
            group_flag = group_flag | _get_rule_flag(result_map, rule_id, layer_name, idx)
        group_flag = group_flag & batch_flag
        raw_score += group_flag.astype(int)
        reason_parts = reason_parts.mask(
            group_flag,
            reason_parts.where(reason_parts == "", reason_parts + ",") + label,
        )

    if _BATCH_CORROBORATION_CONDITIONS == 0:
        agg_df["batch_combo_score"] = 0.0
    else:
        agg_df["batch_combo_score"] = raw_score / _BATCH_CORROBORATION_CONDITIONS
    agg_df["batch_combo_reasons"] = reason_parts.fillna("")

    high_mask = batch_flag & (raw_score >= 3)
    medium_mask = batch_flag & (raw_score >= 2) & ~high_mask
    if high_mask.any():
        agg_df.loc[high_mask, "risk_level"] = RiskLevel.HIGH
    if medium_mask.any():
        current_high = agg_df["risk_level"].eq(RiskLevel.HIGH)
        agg_df.loc[medium_mask & ~current_high, "risk_level"] = RiskLevel.MEDIUM

    return agg_df
