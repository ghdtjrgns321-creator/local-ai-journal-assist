from __future__ import annotations

import inspect
from pathlib import Path

from src.detection.explanation_registry import (
    ACTIVE_RULE_EXPLANATIONS,
    ACTIVE_RULE_IDS,
    get_rule_explanation,
    list_rules_without_explanation,
)
from src.detection.explanation_schema import RuleExplanation
from src.detection.rule_detail_metadata import (
    RULE_DETAIL_METADATA_REGISTRY,
    get_canonical_transaction_rule_ids,
)


def test_active_rules_all_have_rule_explanations() -> None:
    # canonical(29) + macro 3종(L4-02/D01/D02, PHASE1-2 귀속이나 설명 텍스트 유지)
    expected_rule_ids = tuple(
        sorted((*get_canonical_transaction_rule_ids(), "L4-02", "D01", "D02"))
    )

    assert ACTIVE_RULE_IDS == expected_rule_ids
    assert list_rules_without_explanation() == []
    assert set(ACTIVE_RULE_EXPLANATIONS) == set(expected_rule_ids)

    for rule_id in expected_rule_ids:
        explanation = get_rule_explanation(rule_id)
        assert isinstance(explanation, RuleExplanation)
        assert explanation.to_dict() == {
            "principle": explanation.principle,
            "violation_reason": explanation.violation_reason,
            "audit_next_action": explanation.audit_next_action,
            "reference": explanation.reference,
        }
        assert rule_id in RULE_DETAIL_METADATA_REGISTRY


def test_rule_explanation_lookup_api_handles_known_and_unknown_rules() -> None:
    l101 = get_rule_explanation("L1-01")

    assert l101 is not None
    assert "balance" in l101.principle.lower()
    assert get_rule_explanation("not-a-rule") is None


def test_list_rules_without_explanation_accepts_custom_scope() -> None:
    assert list_rules_without_explanation(("L1-01", "missing-rule")) == ["missing-rule"]


def test_registry_has_no_dashboard_or_rule_panel_dependency() -> None:
    registry_source = inspect.getsource(__import__("src.detection.explanation_registry"))
    schema_source = inspect.getsource(__import__("src.detection.explanation_schema"))
    detection_sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "src/detection/explanation_registry.py",
            "src/detection/explanation_schema.py",
        ]
    )

    combined = f"{registry_source}\n{schema_source}\n{detection_sources}"
    assert "dashboard" not in combined
    assert "rule_panel" not in combined
