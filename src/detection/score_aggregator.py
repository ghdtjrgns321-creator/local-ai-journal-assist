"""Aggregate detector results into row-level risk scores.

The execution tracks still use legacy names such as ``layer_a`` and ``layer_b``
for compatibility, but the default score aggregation is now based on the
current audit rule code families: L1, L2, L3, and L4.
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.constants import (
    BATCH_CORROBORATION_RULES,
    RISK_THRESHOLDS,
    RULE_LEVEL_WEIGHTS,
    SEVERITY_MAP,
    TOPSIDE_BONUS_RULES,
    WORK_SCOPE_CORROBORATION_RULES,
    Layer,
    RiskLevel,
)
from src.detection.rule_scoring import RULE_SCORING_REGISTRY, normalize_rule_evidence

_TOPSIDE_CONDITIONS = len(TOPSIDE_BONUS_RULES)
_BATCH_CORROBORATION_CONDITIONS = len(BATCH_CORROBORATION_RULES)
_WORK_SCOPE_CORROBORATION_CONDITIONS = len(WORK_SCOPE_CORROBORATION_RULES)

_POLICY_HIGH_RULES = {"L1-04", "L1-06"}
_POLICY_HIGH_LABELS = {
    "immediate",
    "escalated_materiality",
    "escalated_abnormal_time",
    "escalated_high_risk_account",
}

logger = logging.getLogger(__name__)


def aggregate_scores(
    df: pd.DataFrame,
    results: list[DetectionResult],
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    settings: object | None = None,
    *,
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
        if _uses_rule_level_weights(normalized_weights):
            score_acc = _aggregate_rule_level_scores(df.index, results, normalized_weights)
        else:
            score_acc = _aggregate_legacy_track_scores(df.index, results, normalized_weights)
        anomaly_score = score_acc.clip(0.0, 1.0)

    mode = getattr(settings, "risk_classification_mode", "absolute")
    quantiles = None
    if mode == "quantile":
        quantiles = {
            RiskLevel.HIGH: getattr(settings, "risk_quantile_high", 0.90),
            RiskLevel.MEDIUM: getattr(settings, "risk_quantile_medium", 0.75),
            RiskLevel.LOW: getattr(settings, "risk_quantile_low", 0.50),
        }

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
    agg_df = _apply_policy_risk_floors(agg_df, results)
    agg_df = _apply_auto_escalation(agg_df, results)
    agg_df = _apply_batch_corroboration(agg_df, results)
    agg_df = _apply_work_scope_corroboration(agg_df, results)
    return _inject_topside_score(agg_df, df, results)


def _uses_rule_level_weights(weights: dict[str, float]) -> bool:
    return bool({str(key).upper() for key in weights}.intersection(RULE_LEVEL_WEIGHTS))


def _combined_rule_details(results: list[DetectionResult], index: pd.Index) -> pd.DataFrame:
    details_list = [r.details for r in results if r.details is not None and not r.details.empty]
    if not details_list:
        return pd.DataFrame(index=index)
    combined = pd.concat(details_list, axis=1).reindex(index).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    return combined


def _combined_rule_signal_details(
    results: list[DetectionResult],
    index: pd.Index,
) -> pd.DataFrame:
    """Return raw rule signals, including review-only annotation scores."""
    combined = _combined_rule_details(results, index)
    annotation_columns: list[pd.Series] = []
    for result in results:
        if result.details is None or result.details.empty:
            continue
        for rule_id in result.details.columns:
            rule_code = str(rule_id)
            annotation_scores = _row_annotation_scores_for_rule(result, rule_code, index)
            if annotation_scores.gt(0).any():
                base = (
                    pd.to_numeric(result.details[rule_code].reindex(index), errors="coerce")
                    .fillna(0.0)
                    .astype(float)
                )
                annotation_columns.append(base.combine(annotation_scores, max).rename(rule_code))

    if not annotation_columns:
        return combined
    annotated = pd.concat(annotation_columns, axis=1).reindex(index).fillna(0.0)
    if combined.empty:
        combined = annotated
    else:
        combined = pd.concat([combined, annotated], axis=1).reindex(index).fillna(0.0)
    if combined.columns.duplicated().any():
        combined = combined.T.groupby(level=0).max().T
    return combined


def _aggregate_rule_level_scores(
    index: pd.Index,
    results: list[DetectionResult],
    weights: dict[str, float],
) -> pd.Series:
    """Aggregate by L1/L2/L3/L4 using the max rule score inside each family."""
    combined = _combined_normalized_rule_details(results, index)
    result_map = {r.track_name: r for r in results}
    score_acc = pd.Series(0.0, index=index)
    for level, weight in weights.items():
        level_key = str(level).upper()
        if level_key in RULE_LEVEL_WEIGHTS:
            if combined.empty:
                continue
            columns = [
                col for col in combined.columns if str(col).upper().startswith(f"{level_key}-")
            ]
            if columns:
                score_acc = score_acc + combined[columns].max(axis=1) * float(weight)
            continue

        track = result_map.get(str(level))
        if track is not None:
            score_acc = score_acc + track.scores.reindex(index, fill_value=0.0) * float(weight)
    return score_acc


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
        severities = {
            flag.rule_id: int(flag.severity)
            for flag in result.rule_flags
        }
        for rule_id in details.columns:
            rule_code = str(rule_id)
            if not _is_rule_level_code(rule_code):
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
                pd.to_numeric(details[rule_code], errors="coerce")
                .fillna(0.0)
                .combine(annotation_scores, max)
            )
            normalized = pd.Series(
                [
                    normalize_rule_evidence(
                        rule_id=rule_code,
                        evidence_type=evidence_type,
                        severity=severity,
                        raw_value=raw_value,
                        display_label=display_label or None,
                    ).normalized_score
                    if float(raw_value) > 0
                    else 0.0
                    for raw_value, display_label in zip(raw_values, labels, strict=False)
                ],
                index=index,
                name=rule_code,
                dtype="float64",
            )
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
) -> pd.Series:
    """Keep explicit legacy track weighting available for callers/tests."""
    result_map = {r.track_name: r for r in results}
    score_acc = pd.Series(0.0, index=index)
    for track_name, weight in weights.items():
        if track_name not in result_map:
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

    for rule_id in ("L1-05", "L1-07"):
        label_by_index = _row_labels_for_rule(results, rule_id, agg_df.index)
        for label in _POLICY_HIGH_LABELS:
            mask = label_by_index.eq(label)
            high_mask = high_mask | mask
            reasons = _append_reason(reasons, mask, f"{rule_id}:{label}")

    if high_mask.any():
        agg_df.loc[high_mask, "anomaly_score"] = agg_df.loc[
            high_mask, "anomaly_score"
        ].clip(lower=RISK_THRESHOLDS[RiskLevel.HIGH])
        agg_df.loc[high_mask, "risk_level"] = RiskLevel.HIGH

    agg_df["risk_floor_reasons"] = reasons.fillna("")
    return agg_df


def _row_labels_for_rule(
    results: list[DetectionResult],
    rule_id: str,
    index: pd.Index,
) -> pd.Series:
    labels = pd.Series("", index=index, dtype="string")
    for result in results:
        annotations = (result.metadata or {}).get("row_annotations", {}).get(rule_id, {})
        if not isinstance(annotations, dict):
            continue
        for raw_idx, annotation in annotations.items():
            if not isinstance(annotation, dict):
                continue
            label = (
                annotation.get("bucket")
                or annotation.get("queue_label")
                or annotation.get("risk_level")
                or annotation.get("severity_label")
                or annotation.get("label")
            )
            if label is None:
                continue
            idx = raw_idx if raw_idx in labels.index else _coerce_index_label(index, raw_idx)
            if idx in labels.index:
                labels.loc[idx] = str(label).strip().lower()
    return labels


def _row_annotation_scores_for_rule(
    result: DetectionResult,
    rule_id: str,
    index: pd.Index,
) -> pd.Series:
    scores = pd.Series(0.0, index=index, dtype="float64")
    annotations = (result.metadata or {}).get("row_annotations", {}).get(rule_id, {})
    if not isinstance(annotations, dict):
        return scores
    for raw_idx, annotation in annotations.items():
        if not isinstance(annotation, dict):
            continue
        idx = raw_idx if raw_idx in scores.index else _coerce_index_label(index, raw_idx)
        if idx not in scores.index:
            continue
        scores.loc[idx] = max(scores.loc[idx], _annotation_score(annotation))
    return scores


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
    b_cols = [col for col in combined.columns if str(col) not in {"L1-01", "L1-02", "L1-03"}]
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
    return layer.details[rule_id].reindex(index, fill_value=0.0) > 0


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


def _apply_batch_corroboration(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Promote L4-06 only when corroborating rule groups are also present."""
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


def _apply_work_scope_corroboration(
    agg_df: pd.DataFrame,
    results: list[DetectionResult],
) -> pd.DataFrame:
    """Promote L3-12 only when independent corroborating rule groups exist."""

    result_map = {r.track_name: r for r in results}
    idx = agg_df.index
    scope_flag = _get_rule_flag(result_map, "L3-12", Layer.LAYER_B.value, idx)

    raw_score = pd.Series(0, index=idx, dtype=int)
    reason_parts = pd.Series("", index=idx, dtype="string")
    for label, rule_pairs in WORK_SCOPE_CORROBORATION_RULES:
        group_flag = pd.Series(False, index=idx)
        for rule_id, layer_name in rule_pairs:
            group_flag = group_flag | _get_rule_flag(result_map, rule_id, layer_name, idx)
        group_flag = group_flag & scope_flag
        raw_score += group_flag.astype(int)
        reason_parts = reason_parts.mask(
            group_flag,
            reason_parts.where(reason_parts == "", reason_parts + ",") + label,
        )

    if _WORK_SCOPE_CORROBORATION_CONDITIONS == 0:
        agg_df["work_scope_combo_score"] = 0.0
    else:
        agg_df["work_scope_combo_score"] = raw_score / _WORK_SCOPE_CORROBORATION_CONDITIONS
    agg_df["work_scope_combo_reasons"] = reason_parts.fillna("")

    high_mask = scope_flag & (raw_score >= 3)
    medium_mask = scope_flag & (raw_score >= 2) & ~high_mask
    if high_mask.any():
        agg_df.loc[high_mask, "anomaly_score"] = agg_df.loc[
            high_mask,
            "anomaly_score",
        ].clip(lower=RISK_THRESHOLDS[RiskLevel.HIGH])
        agg_df.loc[high_mask, "risk_level"] = RiskLevel.HIGH
    if medium_mask.any():
        agg_df.loc[medium_mask, "anomaly_score"] = agg_df.loc[
            medium_mask,
            "anomaly_score",
        ].clip(lower=RISK_THRESHOLDS[RiskLevel.MEDIUM])
        current_high = agg_df["risk_level"].eq(RiskLevel.HIGH)
        agg_df.loc[medium_mask & ~current_high, "risk_level"] = RiskLevel.MEDIUM
    return agg_df
