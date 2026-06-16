"""Registry for standard detection rule explanations."""

from __future__ import annotations

from src.detection.anomaly_layer import ANOMALY_RULE_EXPLANATIONS
from src.detection.benford_detector import BENFORD_RULE_EXPLANATIONS
from src.detection.evidence_detector import EVIDENCE_RULE_EXPLANATIONS
from src.detection.explanation_schema import RuleExplanation
from src.detection.fraud_layer import FRAUD_RULE_EXPLANATIONS
from src.detection.integrity_layer import INTEGRITY_RULE_EXPLANATIONS
from src.detection.rule_detail_metadata import get_canonical_transaction_rule_ids
from src.detection.variance_layer import VARIANCE_RULE_EXPLANATIONS

ACTIVE_RULE_EXPLANATIONS: dict[str, RuleExplanation] = {
    **INTEGRITY_RULE_EXPLANATIONS,
    **FRAUD_RULE_EXPLANATIONS,
    **ANOMALY_RULE_EXPLANATIONS,
    **EVIDENCE_RULE_EXPLANATIONS,
    **BENFORD_RULE_EXPLANATIONS,
    **VARIANCE_RULE_EXPLANATIONS,
}

# L4-02(Benford)·D01·D02 는 canonical L1~L4 count 밖(macro, PHASE1-2 family 귀속)이지만
# 감사인 설명 텍스트는 유지한다 — active 설명 집합에 명시 포함.
ACTIVE_RULE_IDS: tuple[str, ...] = tuple(
    sorted((*get_canonical_transaction_rule_ids(), "L4-02", "D01", "D02"))
)


def get_rule_explanation(rule_id: str) -> RuleExplanation | None:
    """Return the standard explanation for a rule ID, if registered."""

    return ACTIVE_RULE_EXPLANATIONS.get(rule_id)


def list_rules_without_explanation(rule_ids: tuple[str, ...] | None = None) -> list[str]:
    """Return active or caller-supplied rule IDs without registered explanations."""

    scoped_rule_ids = rule_ids or ACTIVE_RULE_IDS
    return sorted(rule_id for rule_id in scoped_rule_ids if rule_id not in ACTIVE_RULE_EXPLANATIONS)
