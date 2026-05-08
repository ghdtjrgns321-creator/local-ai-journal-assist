"""Rule-level scoring normalization for PHASE1 case aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class TopicMetadata:
    """Auditor-facing PHASE1 ranking topic."""

    topic_id: str
    label: str


TOPIC_REGISTRY: dict[str, TopicMetadata] = {
    "ledger_integrity": TopicMetadata("ledger_integrity", "원장기록·데이터정합성"),
    "approval_control": TopicMetadata("approval_control", "승인·권한·업무분장 통제"),
    "closing_timing": TopicMetadata("closing_timing", "결산·기간귀속·입력시점"),
    "account_logic": TopicMetadata("account_logic", "계정분류·거래실질 불일치"),
    "duplicate_outflow": TopicMetadata("duplicate_outflow", "중복·상계·자금유출"),
    "intercompany_cycle": TopicMetadata("intercompany_cycle", "관계사·내부거래·순환구조"),
    "revenue_statistical": TopicMetadata("revenue_statistical", "수익·금액·모집단 통계 이상"),
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
    final_topic: str | None = None
    secondary_topics: tuple[str, ...] = field(default_factory=tuple)
    standalone_rankable: bool = True
    floor_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    combo_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    fraud_scenario_tags: tuple[str, ...] = field(default_factory=tuple)

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
    final_topic: str | None = None
    secondary_topics: tuple[str, ...] = field(default_factory=tuple)
    standalone_rankable: bool = True
    floor_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    combo_policy_ids: tuple[str, ...] = field(default_factory=tuple)
    fraud_scenario_tags: tuple[str, ...] = field(default_factory=tuple)


RULE_SCORING_REGISTRY: dict[str, RuleScoringMetadata] = {
    "L1-01": RuleScoringMetadata(
        "L1-01",
        "data_integrity_failure",
        "strong",
        final_topic="ledger_integrity",
        fraud_scenario_tags=("ledger_integrity_failure",),
    ),
    "L1-02": RuleScoringMetadata(
        "L1-02",
        "data_integrity_failure",
        "medium",
        final_topic="ledger_integrity",
        fraud_scenario_tags=("missing_or_incomplete_data",),
    ),
    "L1-03": RuleScoringMetadata(
        "L1-03",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("account_classification_mismatch",),
    ),
    "L1-04": RuleScoringMetadata(
        "L1-04",
        "control_failure",
        "strong",
        final_topic="approval_control",
        floor_policy_ids=("approval_control_high",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-05": RuleScoringMetadata(
        "L1-05",
        "control_failure",
        "strong",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-06": RuleScoringMetadata(
        "L1-06",
        "control_failure",
        "strong",
        final_topic="approval_control",
        fraud_scenario_tags=("segregation_of_duties",),
    ),
    "L1-07": RuleScoringMetadata(
        "L1-07",
        "control_failure",
        "strong",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        fraud_scenario_tags=("approval_bypass",),
    ),
    "L1-08": RuleScoringMetadata(
        "L1-08",
        "data_integrity_failure",
        "medium",
        final_topic="closing_timing",
        secondary_topics=("ledger_integrity",),
        fraud_scenario_tags=("cutoff_or_period_mismatch",),
    ),
    "L1-09": RuleScoringMetadata(
        "L1-09",
        "control_failure",
        "medium",
        final_topic="approval_control",
        fraud_scenario_tags=("missing_approval_trace",),
    ),
    "L2-01": RuleScoringMetadata(
        "L2-01",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        secondary_topics=("approval_control",),
        fraud_scenario_tags=("threshold_splitting",),
    ),
    "L2-02": RuleScoringMetadata(
        "L2-02",
        "duplicate_or_outflow",
        "strong",
        final_topic="duplicate_outflow",
        floor_policy_ids=("duplicate_outflow_high",),
        fraud_scenario_tags=("duplicate_payment",),
    ),
    "L2-03": RuleScoringMetadata(
        "L2-03",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03a": RuleScoringMetadata(
        "L2-03a",
        "duplicate_or_outflow",
        "strong",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03b": RuleScoringMetadata(
        "L2-03b",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03c": RuleScoringMetadata(
        "L2-03c",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-03d": RuleScoringMetadata(
        "L2-03d",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("reversal_or_offset_pattern",),
    ),
    "L2-04": RuleScoringMetadata(
        "L2-04",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("transaction_substance_mismatch",),
    ),
    "L2-05": RuleScoringMetadata(
        "L2-05",
        "duplicate_or_outflow",
        "medium",
        final_topic="duplicate_outflow",
        fraud_scenario_tags=("topside_or_outflow_pattern",),
    ),
    "L3-01": RuleScoringMetadata(
        "L3-01",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("sensitive_account_pattern",),
    ),
    "L3-02": RuleScoringMetadata(
        "L3-02",
        "control_failure",
        "medium",
        final_topic="approval_control",
        fraud_scenario_tags=("manual_entry_concentration",),
    ),
    "L3-03": RuleScoringMetadata(
        "L3-03",
        "intercompany_structure",
        "weak",
        "booster",
        final_topic="intercompany_cycle",
        secondary_topics=("account_logic",),
        standalone_rankable=False,
        fraud_scenario_tags=("intercompany_population_context",),
    ),
    "L3-04": RuleScoringMetadata(
        "L3-04",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("cutoff_or_late_posting",),
    ),
    "L3-05": RuleScoringMetadata(
        "L3-05",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("non_business_day_activity",),
    ),
    "L3-06": RuleScoringMetadata(
        "L3-06",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("after_hours_activity",),
    ),
    "L3-07": RuleScoringMetadata(
        "L3-07",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("posting_document_date_gap",),
    ),
    "L3-08": RuleScoringMetadata(
        "L3-08",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="ledger_integrity",
        secondary_topics=("closing_timing",),
        standalone_rankable=False,
        fraud_scenario_tags=("sequence_gap_or_backdated_context",),
    ),
    "L3-09": RuleScoringMetadata(
        "L3-09",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        fraud_scenario_tags=("aging_or_settlement_mismatch",),
    ),
    "L3-10": RuleScoringMetadata(
        "L3-10",
        "logic_mismatch",
        "weak",
        "booster",
        final_topic="account_logic",
        secondary_topics=("approval_control", "revenue_statistical"),
        standalone_rankable=False,
        fraud_scenario_tags=("sensitive_amount_or_account_context",),
    ),
    "L3-11": RuleScoringMetadata(
        "L3-11",
        "timing_anomaly",
        "medium",
        final_topic="closing_timing",
        fraud_scenario_tags=("period_end_concentration",),
    ),
    "L3-12": RuleScoringMetadata(
        "L3-12",
        "access_scope_review",
        "weak",
        "combo_only",
        final_topic="approval_control",
        secondary_topics=("duplicate_outflow",),
        standalone_rankable=False,
        combo_policy_ids=("work_scope_combo",),
        fraud_scenario_tags=("work_scope_concentration",),
    ),
    "L4-01": RuleScoringMetadata(
        "L4-01",
        "statistical_outlier",
        "medium",
        final_topic="revenue_statistical",
        fraud_scenario_tags=("amount_outlier",),
    ),
    "L4-02": RuleScoringMetadata(
        "L4-02",
        "statistical_outlier",
        "weak",
        "macro_only",
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("benford_distribution_anomaly",),
    ),
    "Benford": RuleScoringMetadata(
        "Benford",
        "statistical_outlier",
        "weak",
        "macro_only",
        final_topic="ledger_integrity",
        secondary_topics=("revenue_statistical",),
        standalone_rankable=False,
        fraud_scenario_tags=("benford_distribution_anomaly",),
    ),
    "L4-03": RuleScoringMetadata(
        "L4-03",
        "statistical_outlier",
        "medium",
        final_topic="revenue_statistical",
        fraud_scenario_tags=("zscore_amount_outlier",),
    ),
    "L4-04": RuleScoringMetadata(
        "L4-04",
        "logic_mismatch",
        "medium",
        final_topic="account_logic",
        secondary_topics=("intercompany_cycle",),
        fraud_scenario_tags=("rare_account_partner_pair",),
    ),
    "L4-05": RuleScoringMetadata(
        "L4-05",
        "timing_anomaly",
        "weak",
        "booster",
        final_topic="closing_timing",
        secondary_topics=("approval_control",),
        standalone_rankable=False,
        fraud_scenario_tags=("behavioral_timing_context",),
    ),
    "L4-06": RuleScoringMetadata(
        "L4-06",
        "statistical_outlier",
        "weak",
        "combo_only",
        final_topic="revenue_statistical",
        standalone_rankable=False,
        combo_policy_ids=("batch_combo",),
        fraud_scenario_tags=("batch_population_anomaly",),
    ),
    "IC01": RuleScoringMetadata(
        "IC01",
        "intercompany_structure",
        "medium",
        final_topic="intercompany_cycle",
        floor_policy_ids=("intercompany_exception",),
        fraud_scenario_tags=("intercompany_reconciliation_exception",),
    ),
    "IC02": RuleScoringMetadata(
        "IC02",
        "intercompany_structure",
        "medium",
        final_topic="intercompany_cycle",
        floor_policy_ids=("intercompany_exception",),
        fraud_scenario_tags=("intercompany_amount_difference",),
    ),
    "IC03": RuleScoringMetadata(
        "IC03",
        "intercompany_structure",
        "medium",
        final_topic="intercompany_cycle",
        floor_policy_ids=("intercompany_exception",),
        fraud_scenario_tags=("intercompany_cycle_exception",),
    ),
    "D01": RuleScoringMetadata(
        "D01",
        "macro_finding",
        "medium",
        "macro_only",
        final_topic="account_logic",
        secondary_topics=("intercompany_cycle", "revenue_statistical"),
        standalone_rankable=False,
        fraud_scenario_tags=("macro_account_logic_anomaly",),
    ),
    "D02": RuleScoringMetadata(
        "D02",
        "macro_finding",
        "medium",
        "macro_only",
        final_topic="closing_timing",
        secondary_topics=("intercompany_cycle", "revenue_statistical"),
        standalone_rankable=False,
        fraud_scenario_tags=("macro_timing_anomaly",),
    ),
    "GR01": RuleScoringMetadata(
        "GR01",
        "intercompany_structure",
        "medium",
        "macro_only",
        final_topic="intercompany_cycle",
        standalone_rankable=False,
        fraud_scenario_tags=("group_relationship_context",),
    ),
    "GR03": RuleScoringMetadata(
        "GR03",
        "intercompany_structure",
        "medium",
        "macro_only",
        final_topic="intercompany_cycle",
        standalone_rankable=False,
        fraud_scenario_tags=("group_relationship_context",),
    ),
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
        final_topic=metadata.final_topic,
        secondary_topics=metadata.secondary_topics,
        standalone_rankable=metadata.standalone_rankable,
        floor_policy_ids=metadata.floor_policy_ids,
        combo_policy_ids=metadata.combo_policy_ids,
        fraud_scenario_tags=metadata.fraud_scenario_tags,
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
