from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from src.detection.explanation_schema import RuleExplanation


def test_rule_explanation_is_frozen_and_json_serializable() -> None:
    explanation = RuleExplanation(
        principle="Complete and accurate ledger evidence should support audit review.",
        violation_reason="The rule identifies an entry that lacks required audit context.",
        audit_next_action="Inspect source evidence and confirm whether the exception is valid.",
        reference="PCAOB AS 1105; ISA 240",
    )

    with pytest.raises(FrozenInstanceError):
        explanation.principle = "changed"  # type: ignore[misc]

    payload = explanation.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)

    assert RuleExplanation.from_dict(json.loads(encoded)) == explanation


@pytest.mark.parametrize(
    "missing_field",
    ["principle", "violation_reason", "audit_next_action", "reference"],
)
def test_rule_explanation_from_dict_rejects_missing_required_fields(
    missing_field: str,
) -> None:
    payload = {
        "principle": "Audit principle.",
        "violation_reason": "Rule reason.",
        "audit_next_action": "Next audit action.",
        "reference": "PCAOB AS 1105",
    }
    payload.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        RuleExplanation.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("principle", ""),
        ("violation_reason", "   "),
        ("audit_next_action", None),
        ("reference", 123),
    ],
)
def test_rule_explanation_rejects_blank_or_non_string_fields(
    field_name: str,
    value: object,
) -> None:
    payload = {
        "principle": "Audit principle.",
        "violation_reason": "Rule reason.",
        "audit_next_action": "Next audit action.",
        "reference": "PCAOB AS 1105",
    }
    payload[field_name] = value

    with pytest.raises(ValueError, match=field_name):
        RuleExplanation.from_dict(payload)
