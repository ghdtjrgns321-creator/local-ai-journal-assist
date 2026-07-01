"""Aggregate detector results into row-level risk scores.

The execution tracks still use legacy names such as ``layer_a`` and ``layer_b``
for compatibility, but the default score aggregation is now based on the
current audit rule code families: L1, L2, L3, and L4.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.constants import (
    LAYER_WEIGHTS,
    RISK_THRESHOLDS,
    RULE_LEVEL_WEIGHTS,
    SEVERITY_MAP,
    TOPSIDE_BONUS_RULES,
    Layer,
    RiskLevel,
)
from src.detection.rule_scoring import (
    EVIDENCE_STRENGTH_FACTOR,
    OFF_TIME_SET,
    RULE_SCORING_REGISTRY,
    SCORING_ROLE_FACTOR,
    SIGNAL_STRENGTH_MAP,
    normalize_rule_evidence,
)
from src.services._phase_timing import log_timing, now_str


class _Phase2Timer:
    """phase2_only scope 일 때만 stage timing 출력하는 컨텍스트 매니저."""

    def __init__(self, scope: str, tag: str) -> None:
        self.scope = scope
        self.tag = tag
        self._start = 0.0
        self._ts = ""

    def __enter__(self) -> _Phase2Timer:
        if self.scope == "phase2_only":
            self._start = time.perf_counter()
            self._ts = now_str()
        return self

    def __exit__(self, *_exc) -> None:
        if self.scope == "phase2_only":
            log_timing(self.tag, time.perf_counter() - self._start, start_ts=self._ts)


_TOPSIDE_CONDITIONS = len(TOPSIDE_BONUS_RULES)
_DATA_INTEGRITY_TRACK_RULES = {"L1-01", "L1-02", "L1-03"}

_POLICY_HIGH_RULES = {"L1-04"}
_POLICY_HIGH_LABELS = {
    "immediate",
    "escalated_materiality",
    "escalated_abnormal_time",
    "escalated_high_risk_account",
}
_POLICY_LABEL_FLOORS = {
    "immediate": RISK_THRESHOLDS[RiskLevel.HIGH],
    "escalated_abnormal_time": 0.75,
    "escalated_materiality": 0.80,
    "escalated_high_risk_account": 0.80,
}

logger = logging.getLogger(__name__)


def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    settings: object | None = None,
    *,
    detection_scope: str = "default",
    stacking_scores: pd.Series | None = None,
) -> pd.DataFrame:
    """Return anomaly_score, risk_level, and rule references for each row."""
    if settings is None:
        settings = get_settings()

    if stacking_scores is not None:
        anomaly_score = stacking_scores.reindex(df.index, fill_value=0.0).clip(0.0, 1.0)
    else:
        normalized_weights = {
            k.value if isinstance(k, Layer) else str(k): float(v)
            for k, v in (weights or RULE_LEVEL_WEIGHTS).items()
        }
        expected_missing_tracks = _expected_missing_tracks_for_scope(detection_scope)
        with _Phase2Timer(detection_scope, "phase2.aggregate.score_acc"):
            if _uses_rule_level_weights(normalized_weights):
                score_acc = _aggregate_rule_level_scores(
                    df.index,
                    results,
                    normalized_weights,
                    expected_missing_tracks=expected_missing_tracks,
                )
            else:
                score_acc = _aggregate_legacy_track_scores(
                    df.index,
                    results,
                    normalized_weights,
                    expected_missing_tracks=expected_missing_tracks,
                )
        anomaly_score = score_acc.clip(0.0, 1.0)

    mode = getattr(settings, "risk_classification_mode", "absolute")
    quantiles = None
    if mode == "quantile":
        quantiles = {
            RiskLevel.HIGH: getattr(settings, "risk_quantile_high", 0.90),
            RiskLevel.MEDIUM: getattr(settings, "risk_quantile_medium", 0.75),
            RiskLevel.LOW: getattr(settings, "risk_quantile_low", 0.50),
        }

    with _Phase2Timer(detection_scope, "phase2.aggregate.agg_df_init"):
        agg_df = pd.DataFrame(
            {
                "anomaly_score": anomaly_score,
                "risk_level": classify_risk_level(
                    anomaly_score,
                    thresholds,
                    mode=mode,
                    quantiles=quantiles,
                ),
                "flagged_rules": _collect_flagged_rules(results, df.index),
                "review_rules": _collect_review_rules(results, df.index),
            },
            index=df.index,
        )

    _inject_ml_track_scores(agg_df, results)
    with _Phase2Timer(detection_scope, "phase2.aggregate.policy_floors"):
        agg_df = _apply_policy_risk_floors(agg_df, results)
    with _Phase2Timer(detection_scope, "phase2.aggregate.corroboration"):
        # batch(L4-06)·work_scope(L3-12)·intercompany(IC01-03) corroboration 제거(2026-06-21):
        # PHASE1-2 family 귀속 룰이라 PHASE1-1 row anomaly_score/risk_level 에 기여하지 않는다.
        agg_df = _apply_auto_escalation(agg_df, results)
    with _Phase2Timer(detection_scope, "phase2.aggregate.topside"):
        return _inject_topside_score(agg_df, df, results)


def _uses_rule_level_weights(weights: dict[str, float]) -> bool:
    return bool({str(key).upper() for key in weights}.intersection(RULE_LEVEL_WEIGHTS))


def _combined_rule_details(results: list[DetectionResult], index: pd.Index) -> pd.DataFrame:
    details_list = [r.details for r in results if r.details is not None and not r.details.empty]
    if not details_list:
        return pd.DataFrame(index=index)
    combined = pd.concat(details_list, axis=1).reindex(index)
    # Why: ML/외부 detector가 details에 model_id/string column을 섞을 수 있어
    #      모든 다운스트림 비교(`combined > 0` 등)에서 'str > int' TypeError를 유발.
    #      numeric 강제 변환으로 근본 차단 — non-numeric은 NaN→0.0 처리.
    combined = combined.apply(lambda c: pd.to_numeric(c, errors="coerce")).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    return combined


def _aggregate_rule_level_scores(
    index: pd.Index,
    results: list[DetectionResult],
    weights: dict[str, float],
    *,
    expected_missing_tracks: set[str] | None = None,
) -> pd.Series:
    """Aggregate by L1/L2/L3/L4 using the max rule score inside each family."""
    combined = _combined_normalized_rule_details(results, index)
    if combined.empty:
        return _aggregate_legacy_track_scores(
            index,
            results,
            _string_keyed_weights(LAYER_WEIGHTS),
            expected_missing_tracks=expected_missing_tracks,
        )
    result_map = {r.track_name: r for r in results}
    score_acc = pd.Series(0.0, index=index)
    matched_rule_family = False
    for level, weight in weights.items():
        level_key = str(level).upper()
        if level_key in RULE_LEVEL_WEIGHTS:
            columns = [
                col for col in combined.columns if str(col).upper().startswith(f"{level_key}-")
            ]
            if columns:
                matched_rule_family = True
                score_acc = score_acc + combined[columns].max(axis=1) * float(weight)
            continue

        track = result_map.get(str(level))
        if track is not None:
            score_acc = score_acc + track.scores.reindex(index, fill_value=0.0) * float(weight)
    if not matched_rule_family and not score_acc.gt(0).any():
        return _aggregate_legacy_track_scores(
            index,
            results,
            _string_keyed_weights(LAYER_WEIGHTS),
            expected_missing_tracks=expected_missing_tracks,
        )
    return score_acc


def _expected_missing_tracks_for_scope(detection_scope: str) -> set[str]:
    if detection_scope != "phase2_only":
        return set()
    return {"layer_a", "layer_b", "layer_c", "benford", "ml_supervised"}


def _string_keyed_weights(weights: dict[object, float]) -> dict[str, float]:
    return {
        key.value if isinstance(key, Layer) else str(key): float(value)
        for key, value in weights.items()
    }


def _combined_normalized_rule_details(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.DataFrame:
    """Return rule detail columns after applying the PHASE1 rule scoring contract."""
    normalized_columns: list[pd.Series] = []
    for result in results:
        if result.details is None or result.details.empty:
            continue
        details = result.details.reindex(index).fillna(0.0)
        severities = {flag.rule_id: int(flag.severity) for flag in result.rule_flags}
        for rule_id in details.columns:
            rule_code = str(rule_id)
            if not _is_rule_level_code(rule_code):
                continue
            if rule_code in _DATA_INTEGRITY_TRACK_RULES:
                normalized_columns.append(pd.Series(0.0, index=index, name=rule_code))
                continue
            # OFF-TIME(L3-05·L3-06·L4-05)은 within-tier 정렬·UI 전용이라 row anomaly_score 에
            # 0 기여한다(HIGH_COMBO_GROUNDING §2(5)). 정렬은 case_builder time_severity 가 룰ID
            # 발화 여부로 별도 산출하므로 점수 0 강제가 정렬을 깨지 않는다.
            if rule_code in OFF_TIME_SET:
                normalized_columns.append(pd.Series(0.0, index=index, name=rule_code))
                continue
            metadata = RULE_SCORING_REGISTRY.get(rule_code)
            if metadata is not None and metadata.scoring_role == "macro_only":
                normalized_columns.append(pd.Series(0.0, index=index, name=rule_code))
                continue

            severity = severities.get(rule_code, int(SEVERITY_MAP.get(rule_code, 1)))
            evidence_type = (
                metadata.evidence_type
                if metadata is not None
                else _default_evidence_type(rule_code)
            )
            labels = _row_labels_for_rule(results=[result], rule_id=rule_code, index=index)
            annotation_scores = _row_annotation_scores_for_rule(result, rule_code, index)
            raw_values = (
                pd.to_numeric(details[rule_code], errors="coerce").fillna(0.0).astype(float)
            )
            raw_values = pd.Series(
                np.maximum(
                    raw_values.to_numpy(dtype="float64"),
                    annotation_scores.to_numpy(dtype="float64"),
                ),
                index=index,
                name=rule_code,
            )
            normalized = _normalize_rule_values(
                rule_id=rule_code,
                evidence_type=evidence_type,
                severity=severity,
                raw_values=raw_values,
                labels=labels,
            ).rename(rule_code)
            normalized_columns.append(normalized)

    if not normalized_columns:
        return pd.DataFrame(index=index)
    combined = pd.concat(normalized_columns, axis=1).reindex(index).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    return combined


def _is_rule_level_code(rule_id: str) -> bool:
    return str(rule_id).upper().startswith(("L1-", "L2-", "L3-", "L4-"))


def _default_evidence_type(rule_id: str) -> str:
    level = str(rule_id).upper().split("-", maxsplit=1)[0]
    return {
        "L1": "data_integrity_failure",
        "L2": "duplicate_or_outflow",
        "L3": "timing_anomaly",
        "L4": "statistical_outlier",
    }.get(level, "statistical_outlier")


def _aggregate_legacy_track_scores(
    index: pd.Index,
    results: list[DetectionResult],
    weights: dict[str, float],
    *,
    expected_missing_tracks: set[str] | None = None,
) -> pd.Series:
    """Keep explicit legacy track weighting available for callers/tests."""
    result_map = {r.track_name: r for r in results}
    score_acc = pd.Series(0.0, index=index)
    expected_missing_tracks = expected_missing_tracks or set()
    for track_name, weight in weights.items():
        if track_name not in result_map:
            if track_name in expected_missing_tracks:
                logger.debug("track '%s' missing; treating as zero", track_name)
            else:
                logger.warning("track '%s' missing; treating as zero", track_name)
            continue
        try:
            track_scores = result_map[track_name].scores.reindex(index, fill_value=0.0)
            score_acc = score_acc + track_scores * float(weight)
        except Exception:
            logger.warning("failed to aggregate track '%s'", track_name, exc_info=True)
    return score_acc


def _inject_ml_track_scores(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> None:
    """Inject optional ML track scores as separate display/storage columns."""
    track_to_col = {
        "ml_supervised": "supervised_score",
        "ml_unsupervised": "unsupervised_score",
    }
    for result in results:
        col = track_to_col.get(result.track_name)
        if col is not None:
            agg_df[col] = result.scores.reindex(agg_df.index)


def classify_risk_level(
    scores: pd.Series,
    thresholds: dict[str, float] | None = None,
    mode: str = "absolute",
    quantiles: dict[str, float] | None = None,
) -> pd.Series:
    """Classify scores into Normal/Low/Medium/High."""
    if mode == "quantile":
        return _classify_by_quantile(scores, quantiles)

    t = thresholds or RISK_THRESHOLDS
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[scores >= t[RiskLevel.LOW]] = RiskLevel.LOW
    levels[scores >= t[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[scores >= t[RiskLevel.HIGH]] = RiskLevel.HIGH
    return levels


def _classify_by_quantile(
    scores: pd.Series,
    quantiles: dict[str, float] | None,
) -> pd.Series:
    q = quantiles or {
        RiskLevel.HIGH: 0.90,
        RiskLevel.MEDIUM: 0.75,
        RiskLevel.LOW: 0.50,
    }
    if scores.empty or scores.max() <= 0:
        return pd.Series(RiskLevel.NORMAL, index=scores.index)

    pct_rank = scores.rank(method="max", pct=True)
    levels = pd.Series(RiskLevel.NORMAL, index=scores.index)
    levels[pct_rank > q[RiskLevel.LOW]] = RiskLevel.LOW
    levels[pct_rank > q[RiskLevel.MEDIUM]] = RiskLevel.MEDIUM
    levels[pct_rank > q[RiskLevel.HIGH]] = RiskLevel.HIGH
    levels[scores <= 0] = RiskLevel.NORMAL
    return levels


def _collect_flagged_rules(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.Series:
    """Return comma-separated confirmed rule IDs per row."""
    combined = _combined_rule_details(results, index)
    if combined.empty:
        return pd.Series("", index=index)
    mask = combined > 0
    cols_with_comma = mask.columns + ","
    flagged_str = mask.dot(cols_with_comma)
    return flagged_str.str.rstrip(",")


def _collect_review_rules(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.Series:
    """Return comma-separated review-only rule IDs per row."""
    combined = _combined_rule_details(results, index)
    review_masks: list[pd.Series] = []

    for result in results:
        if result.details is None or result.details.empty:
            continue
        for rule_id in result.details.columns:
            rule_code = str(rule_id)
            annotation_scores = _row_annotation_scores_for_rule(result, rule_code, index)
            if not annotation_scores.gt(0).any():
                continue
            detail_scores = (
                pd.to_numeric(result.details[rule_code].reindex(index), errors="coerce")
                .fillna(0.0)
                .astype(float)
            )
            review_mask = annotation_scores.gt(0) & detail_scores.le(0)
            if review_mask.any():
                review_masks.append(review_mask.rename(rule_code))

    if not review_masks:
        return pd.Series("", index=index)
    mask = pd.concat(review_masks, axis=1).reindex(index).fillna(False).astype(bool)
    if mask.columns.duplicated().any():
        mask = mask.T.groupby(level=0).max().T.astype(bool)
    if not combined.empty:
        confirmed = combined.reindex(index).fillna(0.0).gt(0)
        for rule_id in mask.columns:
            if rule_id in confirmed.columns:
                mask[rule_id] = mask[rule_id] & ~confirmed[rule_id]
    cols_with_comma = mask.columns + ","
    review_str = mask.dot(cols_with_comma)
    return review_str.str.rstrip(",")


def _apply_policy_risk_floors(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Promote severe control failures that should not be diluted by weighting."""
    combined = _combined_rule_details(results, agg_df.index)
    if combined.empty:
        agg_df["risk_floor_reasons"] = ""
        return agg_df

    high_mask = pd.Series(False, index=agg_df.index)
    reasons = pd.Series("", index=agg_df.index, dtype="string")

    for rule_id in _POLICY_HIGH_RULES:
        if rule_id in combined.columns:
            mask = combined[rule_id].ge(0.8)
            high_mask = high_mask | mask
            reasons = _append_reason(reasons, mask, f"{rule_id}:immediate")

    for rule_id in ("L1-05",):
        label_by_index = _row_labels_for_rule(results, rule_id, agg_df.index)
        for label in _POLICY_HIGH_LABELS:
            mask = label_by_index.eq(label)
            high_mask = high_mask | mask
            reasons = _append_reason(reasons, mask, f"{rule_id}:{label}")
            if mask.any():
                agg_df.loc[mask, "anomaly_score"] = agg_df.loc[
                    mask,
                    "anomaly_score",
                ].clip(lower=_POLICY_LABEL_FLOORS.get(label, RISK_THRESHOLDS[RiskLevel.HIGH]))

    # L1-06(직무분리) 강제 risk floor 제거(2026-06-30): SOD_TOXIC_COMBINATIONS_GROUNDING §3 —
    # RED 직무분리는 단독이면 LOW, 행위신호와 조합될 때만 HIGH(겸직만으로 부정 단정 불가).
    # 구 direct_low/medium/high/critical floor 가 L1-06 단독을 강제 승격해 문서 위반이었다.
    # 이제 L1-06 은 정규 룰 점수경로(_combined_normalized_rule_details)로만 흐르고, tier 승격은
    # approval_bypass·embezzlement 등 콤보 leg 로만 일어난다.

    if high_mask.any():
        agg_df.loc[high_mask, "anomaly_score"] = agg_df.loc[high_mask, "anomaly_score"].clip(
            lower=RISK_THRESHOLDS[RiskLevel.HIGH]
        )
        agg_df.loc[high_mask, "risk_level"] = RiskLevel.HIGH

    agg_df["risk_floor_reasons"] = reasons.fillna("")
    return agg_df


def _row_labels_for_rule(
    results: list[DetectionResult],
    rule_id: str,
    index: pd.Index,
) -> pd.Series:
    values: dict[object, str] = {}
    for result in results:
        annotations = (result.metadata or {}).get("row_annotations", {}).get(rule_id, {})
        if not isinstance(annotations, dict):
            continue
        for raw_idx, annotation in annotations.items():
            if not isinstance(annotation, dict):
                continue
            label = (
                annotation.get("reason_code")
                or annotation.get("bucket")
                or annotation.get("queue_label")
                or annotation.get("risk_level")
                or annotation.get("severity_label")
                or annotation.get("label")
            )
            if label is None:
                continue
            idx = raw_idx if raw_idx in index else _coerce_index_label(index, raw_idx)
            values[idx] = str(label).strip().lower()
    if not values:
        return pd.Series("", index=index, dtype="string")
    return pd.Series(values, dtype="string").reindex(index, fill_value="")


def _row_annotation_scores_for_rule(
    result: DetectionResult,
    rule_id: str,
    index: pd.Index,
) -> pd.Series:
    annotations = (result.metadata or {}).get("row_annotations", {}).get(rule_id, {})
    if not isinstance(annotations, dict):
        return pd.Series(0.0, index=index, dtype="float64")
    values: dict[object, float] = {}
    for raw_idx, annotation in annotations.items():
        if not isinstance(annotation, dict):
            continue
        idx = raw_idx if raw_idx in index else _coerce_index_label(index, raw_idx)
        score = _annotation_score(annotation)
        if score <= 0:
            continue
        values[idx] = max(values.get(idx, 0.0), score)
    if not values:
        return pd.Series(0.0, index=index, dtype="float64")
    return pd.Series(values, dtype="float64").reindex(index, fill_value=0.0)


def _normalize_rule_values(
    *,
    rule_id: str,
    evidence_type: str,
    severity: int,
    raw_values: pd.Series,
    labels: pd.Series,
) -> pd.Series:
    """Vectorized equivalent of normalize_rule_evidence for PHASE1 aggregation."""

    metadata = RULE_SCORING_REGISTRY.get(rule_id)
    if metadata is None:
        return raw_values.map(
            lambda raw_value: (
                normalize_rule_evidence(
                    rule_id=rule_id,
                    evidence_type=evidence_type,
                    severity=severity,
                    raw_value=raw_value,
                ).normalized_score
                if float(raw_value) > 0
                else 0.0
            ),
        ).astype("float64")

    numeric = pd.to_numeric(raw_values, errors="coerce").fillna(0.0).clip(lower=0.0)
    labels = labels.fillna("").astype("string").str.strip().str.lower()
    signal = _vector_signal_strength(rule_id, numeric, labels, severity)
    severity_factor = max(min(float(severity) / 5.0, 1.0), 0.0)
    evidence_factor = EVIDENCE_STRENGTH_FACTOR.get(metadata.evidence_strength, 0.45)
    role_factor = SCORING_ROLE_FACTOR.get(metadata.scoring_role, 1.0)
    normalized = (
        signal * severity_factor * evidence_factor * role_factor * metadata.contribution_weight
    )
    return normalized.where(numeric.gt(0), 0.0).clip(0.0, 1.0).astype("float64")


def _vector_signal_strength(
    rule_id: str,
    numeric: pd.Series,
    labels: pd.Series,
    severity: int,
) -> pd.Series:
    severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
    default = _default_signal_strength(numeric, labels, severity_factor)

    # L1-04·L3-07·L3-09 binary 통일(2026-06-20) — 옛 bucket 등급 제거, generic(default) 로 일관.
    if rule_id in {"L1-03", "L1-07", "L4-04"}:
        signal = numeric.clip(upper=1.0) / severity_factor
        return signal.astype("float64")
    # OFF-TIME(L3-05·L3-06·L4-05)·macro_only(L3-12 등)는 _combined_normalized_rule_details 에서
    # 선행 차단(0강제)되어 이 경로에 도달하지 않는다 — 차단 단일 출처를 그쪽으로 고정(회귀방어).
    if rule_id == "L3-10":
        return numeric.clip(upper=1.0).astype("float64")
    # L4-03: binary 통일 — 수행중요성 절대임계 초과. generic default 로 일관된 binary 강도.
    return default.astype("float64")


def _default_signal_strength(
    numeric: pd.Series,
    labels: pd.Series,
    severity_factor: float,
) -> pd.Series:
    mapped = labels.map(SIGNAL_STRENGTH_MAP)
    from_numeric = numeric.where(numeric.gt(severity_factor), numeric / severity_factor)
    from_numeric = from_numeric.clip(0.0, 1.0)
    return mapped.fillna(from_numeric).astype("float64")


def _annotation_score(annotation: dict[str, object]) -> float:
    for key in ("score", "review_score", "normalized_score"):
        value = annotation.get(key)
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if score > 0:
            return score
    return 0.0


def _coerce_index_label(index: pd.Index, value: object) -> object:
    try:
        pos = int(value)
    except (TypeError, ValueError):
        return value
    if 0 <= pos < len(index):
        return index[pos]
    return value


def _append_reason(reasons: pd.Series, mask: pd.Series, reason: str) -> pd.Series:
    return reasons.mask(mask, reasons.where(reasons == "", reasons + ",") + reason)


def _apply_auto_escalation(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Escalate data-integrity plus multiple control/fraud findings."""
    combined = _combined_rule_details(results, agg_df.index)
    if combined.empty:
        return agg_df
    a_cols = [col for col in combined.columns if str(col) in {"L1-01", "L1-02", "L1-03"}]
    # 등급 승격에 기여하면 안 되는 룰은 escalation 카운트에서 제외:
    # OFF-TIME(L3-05·L3-06·L4-05) + PHASE1-2 family(L4-06·L3-12).
    b_exclude = {"L1-01", "L1-02", "L1-03"} | OFF_TIME_SET | {"L4-06", "L3-12"}
    b_cols = [col for col in combined.columns if str(col) not in b_exclude]
    if not a_cols or not b_cols:
        return agg_df

    a_flagged = (combined[a_cols] > 0).sum(axis=1) >= 1
    b_flagged = (combined[b_cols] > 0).sum(axis=1) >= 2
    escalate_mask = a_flagged & b_flagged
    if escalate_mask.any():
        agg_df.loc[escalate_mask, "risk_level"] = RiskLevel.HIGH
    return agg_df


def _get_rule_flag(
    result_map: dict[str, DetectionResult],
    rule_id: str,
    layer_name: str,
    index: pd.Index,
) -> pd.Series:
    """Return whether a rule is flagged, accepting legacy track locations."""
    layer = result_map.get(layer_name)
    if layer is None or rule_id not in layer.details.columns:
        combined = _combined_rule_details(list(result_map.values()), index)
        if rule_id not in combined.columns:
            return pd.Series(False, index=index)
        return combined[rule_id].reindex(index, fill_value=0.0) > 0
    # Why: 일부 detector가 details에 string column을 넣는 경우 'str > int' 차단.
    raw = pd.to_numeric(
        layer.details[rule_id].reindex(index, fill_value=0.0), errors="coerce"
    ).fillna(0.0)
    return raw > 0


def _compute_topside_score(
    df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.Series:
    """Compute top-side JE corroboration score."""
    result_map = {r.track_name: r for r in results}
    idx = df.index
    score = pd.Series(0, index=idx, dtype=int)

    for _label, rule_pairs in TOPSIDE_BONUS_RULES:
        group_flag = pd.Series(False, index=idx)
        for rule_id, layer_name in rule_pairs:
            group_flag = group_flag | _get_rule_flag(result_map, rule_id, layer_name, idx)
        score += group_flag.astype(int)

    if "is_manual_je" in df.columns:
        is_manual = df["is_manual_je"].fillna(False)
    else:
        is_manual = pd.Series(False, index=idx)
    return score * is_manual.astype(int)


def _inject_topside_score(
    agg_df: pd.DataFrame,
    df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Add top-side score as a supporting feature."""
    raw_score = _compute_topside_score(df, results)
    agg_df["topside_score"] = raw_score / _TOPSIDE_CONDITIONS
    return agg_df
