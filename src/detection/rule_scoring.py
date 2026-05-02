"""Rule-level scoring normalization for PHASE1 case aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.detection.constants import SEVERITY_MAP

SIGNAL_STRENGTH_MAP: dict[str, float] = {
    "critical": 1.0,
    "high": 1.0,
    "상": 1.0,
    "위험높음": 1.0,
    "위험 높음": 1.0,
    "medium": 0.6,
    "moderate": 0.6,
    "중": 0.6,
    "review_needed": 0.6,
    "검토필요": 0.6,
    "검토 필요": 0.6,
    "low": 0.3,
    "하": 0.3,
    "info": 0.2,
    "참고": 0.2,
    "normal": 0.0,
    "none": 0.0,
    "false": 0.0,
}

EVIDENCE_STRENGTH_FACTOR: dict[str, float] = {
    "strong": 1.0,
    "medium": 0.75,
    "weak": 0.45,
    "info": 0.25,
}

SCORING_ROLE_FACTOR: dict[str, float] = {
    "primary": 1.0,
    "booster": 0.65,
    "combo_only": 0.35,
    "macro_only": 0.0,
}

L104_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "boundary": 0.35,
    "moderate": 0.65,
    "severe": 0.85,
    "critical": 1.0,
    "non_approver": 1.0,
}

L201_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "lower_band": 0.60,
    "close_band": 0.80,
    "razor_band": 1.00,
    "routine_razor_review": 0.45,
    "normal_population": 0.0,
}

L103_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "unknown_account": 0.75,
    "unknown_account_family": 0.85,
    "malformed_account": 0.92,
    "placeholder_or_reserved": 1.0,
}

L305_CALENDAR_SIGNAL_STRENGTH: dict[str, float] = {
    "weekday_holiday": 0.75,
    "holiday": 0.75,
    "weekend": 0.85,
    "weekend_holiday": 1.0,
}

L307_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "moderate_gap": 0.55,
    "large_gap": 0.75,
    "extreme_gap": 1.0,
}

L403_ZSCORE_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "low_zscore": 0.45,
    "review_zscore": 0.45,
    "medium_zscore": 0.70,
    "strong_zscore": 0.70,
    "high_zscore": 1.0,
    "extreme_zscore": 1.0,
}

L309_AGING_BUCKET_SIGNAL_STRENGTH: dict[str, float] = {
    "aging_30_60": 0.75,
    "aging_60_90": 1.0,
    "aging_over_90": 1.25,
}

L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH: dict[str, float] = {
    "reference_match": 0.90,
    "mixed_reference_fallback": 0.70,
    "amount_partner_fallback": 0.65,
    "blank_reference_fallback": 0.60,
}


@dataclass(frozen=True)
class RuleScoringMetadata:
    """PHASE1 scoring contract for one rule."""

    rule_id: str
    evidence_type: str
    evidence_strength: str
    scoring_role: str = "primary"
    contribution_weight: float = 1.0

    @property
    def severity(self) -> int:
        return int(SEVERITY_MAP.get(self.rule_id, 1))


@dataclass(frozen=True)
class NormalizedRuleEvidence:
    """A raw rule result translated into the common PHASE1 score scale."""

    rule_id: str
    evidence_type: str
    severity: int
    display_label: str
    signal_strength: float
    evidence_strength: str
    scoring_role: str
    normalized_score: float


RULE_SCORING_REGISTRY: dict[str, RuleScoringMetadata] = {
    "L1-01": RuleScoringMetadata("L1-01", "data_integrity_failure", "strong"),
    "L1-02": RuleScoringMetadata("L1-02", "data_integrity_failure", "medium"),
    "L1-03": RuleScoringMetadata("L1-03", "logic_mismatch", "medium"),
    "L1-04": RuleScoringMetadata("L1-04", "control_failure", "strong"),
    "L1-05": RuleScoringMetadata("L1-05", "control_failure", "strong"),
    "L1-06": RuleScoringMetadata("L1-06", "control_failure", "strong"),
    "L1-07": RuleScoringMetadata("L1-07", "control_failure", "strong"),
    "L1-08": RuleScoringMetadata("L1-08", "data_integrity_failure", "medium"),
    "L1-09": RuleScoringMetadata("L1-09", "control_failure", "medium"),
    "L2-01": RuleScoringMetadata("L2-01", "duplicate_or_outflow", "medium"),
    "L2-02": RuleScoringMetadata("L2-02", "duplicate_or_outflow", "strong"),
    "L2-03": RuleScoringMetadata("L2-03", "duplicate_or_outflow", "medium"),
    "L2-03a": RuleScoringMetadata("L2-03a", "duplicate_or_outflow", "strong"),
    "L2-03b": RuleScoringMetadata("L2-03b", "duplicate_or_outflow", "medium"),
    "L2-03c": RuleScoringMetadata("L2-03c", "duplicate_or_outflow", "medium"),
    "L2-03d": RuleScoringMetadata("L2-03d", "duplicate_or_outflow", "medium"),
    "L2-04": RuleScoringMetadata("L2-04", "logic_mismatch", "medium"),
    "L2-05": RuleScoringMetadata("L2-05", "duplicate_or_outflow", "medium"),
    "L3-01": RuleScoringMetadata("L3-01", "logic_mismatch", "medium"),
    "L3-02": RuleScoringMetadata("L3-02", "control_failure", "medium"),
    "L3-03": RuleScoringMetadata("L3-03", "intercompany_structure", "weak"),
    "L3-04": RuleScoringMetadata("L3-04", "timing_anomaly", "medium"),
    "L3-05": RuleScoringMetadata("L3-05", "timing_anomaly", "weak"),
    "L3-06": RuleScoringMetadata("L3-06", "timing_anomaly", "weak"),
    "L3-07": RuleScoringMetadata("L3-07", "timing_anomaly", "medium"),
    "L3-08": RuleScoringMetadata("L3-08", "timing_anomaly", "weak", "booster"),
    "L3-09": RuleScoringMetadata("L3-09", "logic_mismatch", "medium"),
    "L3-10": RuleScoringMetadata("L3-10", "logic_mismatch", "weak", "booster"),
    "L3-11": RuleScoringMetadata("L3-11", "timing_anomaly", "medium"),
    "L3-12": RuleScoringMetadata("L3-12", "access_scope_review", "weak", "booster"),
    "L4-01": RuleScoringMetadata("L4-01", "statistical_outlier", "medium"),
    "L4-02": RuleScoringMetadata("L4-02", "statistical_outlier", "weak", "macro_only"),
    "L4-03": RuleScoringMetadata("L4-03", "statistical_outlier", "medium"),
    "L4-04": RuleScoringMetadata("L4-04", "logic_mismatch", "medium"),
    "L4-05": RuleScoringMetadata("L4-05", "timing_anomaly", "weak"),
    "L4-06": RuleScoringMetadata("L4-06", "statistical_outlier", "weak", "combo_only"),
    "IC01": RuleScoringMetadata("IC01", "intercompany_structure", "medium"),
    "IC02": RuleScoringMetadata("IC02", "intercompany_structure", "medium"),
    "IC03": RuleScoringMetadata("IC03", "intercompany_structure", "medium"),
    "D01": RuleScoringMetadata("D01", "macro_finding", "medium", "macro_only"),
    "D02": RuleScoringMetadata("D02", "macro_finding", "medium", "macro_only"),
    "GR01": RuleScoringMetadata("GR01", "intercompany_structure", "medium", "macro_only"),
    "GR03": RuleScoringMetadata("GR03", "intercompany_structure", "medium", "macro_only"),
}


def normalize_signal_strength(
    value: Any,
    *,
    severity: int,
    display_label: str | None = None,
) -> float:
    """Return 0..1 signal strength independent of severity weighting."""

    label = str(display_label or "").strip().lower()
    if label in SIGNAL_STRENGTH_MAP:
        return SIGNAL_STRENGTH_MAP[label]

    if isinstance(value, bool):
        return 1.0 if value else 0.0

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value or "").strip().lower()
        return SIGNAL_STRENGTH_MAP.get(text, 0.0)

    if numeric <= 0:
        return 0.0

    severity_factor = max(float(severity) / 5.0, 0.01)
    if numeric <= severity_factor + 1e-9:
        return min(numeric / severity_factor, 1.0)
    return min(numeric, 1.0)


def normalize_rule_evidence(
    *,
    rule_id: str,
    evidence_type: str,
    severity: int,
    raw_value: Any,
    display_label: str | None = None,
) -> NormalizedRuleEvidence:
    """Translate one rule hit into the common PHASE1 aggregation contract."""

    metadata = RULE_SCORING_REGISTRY.get(
        rule_id,
        RuleScoringMetadata(
            rule_id=rule_id,
            evidence_type=evidence_type,
            evidence_strength="medium" if severity >= 3 else "weak",
        ),
    )
    signal_strength = _rule_specific_signal_strength(
        rule_id=rule_id,
        raw_value=raw_value,
        severity=severity,
        display_label=display_label,
    )
    severity_factor = max(min(float(severity) / 5.0, 1.0), 0.0)
    evidence_factor = EVIDENCE_STRENGTH_FACTOR.get(metadata.evidence_strength, 0.45)
    role_factor = SCORING_ROLE_FACTOR.get(metadata.scoring_role, 1.0)
    normalized_score = (
        signal_strength
        * severity_factor
        * evidence_factor
        * role_factor
        * metadata.contribution_weight
    )
    return NormalizedRuleEvidence(
        rule_id=rule_id,
        evidence_type=evidence_type,
        severity=severity,
        display_label=display_label or "",
        signal_strength=max(0.0, min(signal_strength, 1.0)),
        evidence_strength=metadata.evidence_strength,
        scoring_role=metadata.scoring_role,
        normalized_score=max(0.0, min(float(normalized_score), 1.0)),
    )


def _rule_specific_signal_strength(
    *,
    rule_id: str,
    raw_value: Any,
    severity: int,
    display_label: str | None,
) -> float:
    label = str(display_label or "").strip().lower()
    if rule_id == "L1-04" and label in L104_BUCKET_SIGNAL_STRENGTH:
        return L104_BUCKET_SIGNAL_STRENGTH[label]
    if rule_id == "L2-02":
        if label in L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH:
            return L202_DUPLICATE_PAYMENT_SIGNAL_STRENGTH[label]
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L2-01":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            numeric = 0.0
        if label == "normal_population" or numeric <= 0:
            return 0.0
        if label == "routine_razor_review" or numeric <= 0.35:
            return L201_BUCKET_SIGNAL_STRENGTH["routine_razor_review"]
        if label in L201_BUCKET_SIGNAL_STRENGTH:
            return L201_BUCKET_SIGNAL_STRENGTH[label]
        return min(numeric, 1.0)
    if rule_id == "L1-03":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            if label in L103_BUCKET_SIGNAL_STRENGTH:
                return L103_BUCKET_SIGNAL_STRENGTH[label]
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    if rule_id == "L1-07":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    if rule_id == "L3-09":
        if label in L309_AGING_BUCKET_SIGNAL_STRENGTH:
            return L309_AGING_BUCKET_SIGNAL_STRENGTH[label]
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    if rule_id == "L3-05":
        if label in L305_CALENDAR_SIGNAL_STRENGTH:
            return L305_CALENDAR_SIGNAL_STRENGTH[label]
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        if numeric >= 0.45:
            return L305_CALENDAR_SIGNAL_STRENGTH["weekend_holiday"]
        if numeric >= 0.40:
            return L305_CALENDAR_SIGNAL_STRENGTH["weekend"]
        if numeric >= 0.35:
            return L305_CALENDAR_SIGNAL_STRENGTH["weekday_holiday"]
        return normalize_signal_strength(
            numeric,
            severity=severity,
            display_label=display_label,
        )
    if rule_id == "L3-01":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L3-10":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L4-04":
        try:
            numeric = max(float(raw_value), 0.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
        severity_factor = max(min(float(severity) / 5.0, 1.0), 0.01)
        return min(numeric, 1.0) / severity_factor
    if rule_id == "L3-12":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L3-06":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L4-05":
        try:
            return min(max(float(raw_value), 0.0), 1.0)
        except (TypeError, ValueError):
            return normalize_signal_strength(
                raw_value,
                severity=severity,
                display_label=display_label,
            )
    if rule_id == "L3-07":
        for suffix, signal_strength in L307_BUCKET_SIGNAL_STRENGTH.items():
            if label.endswith(suffix):
                return signal_strength
    if rule_id == "L4-03":
        if label in L403_ZSCORE_BUCKET_SIGNAL_STRENGTH:
            return L403_ZSCORE_BUCKET_SIGNAL_STRENGTH[label]
    return normalize_signal_strength(
        raw_value,
        severity=severity,
        display_label=display_label,
    )
