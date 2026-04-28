from __future__ import annotations

import pytest

from src.detection.phase1_case_builder import _RULE_THEME_MAP
from src.detection.rule_scoring import (
    RULE_SCORING_REGISTRY,
    normalize_rule_evidence,
    normalize_signal_strength,
)


def test_rule_scoring_registry_covers_phase1_transaction_rules():
    missing = sorted(set(_RULE_THEME_MAP) - set(RULE_SCORING_REGISTRY))

    assert missing == []


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("High", 1.0),
        ("상", 1.0),
        ("검토 필요", 0.6),
        ("Low", 0.3),
        ("참고", 0.2),
    ],
)
def test_normalize_signal_strength_maps_rule_labels(label: str, expected: float):
    assert normalize_signal_strength(label, severity=3) == expected


def test_normalize_signal_strength_recovers_signal_from_severity_weighted_score():
    assert normalize_signal_strength(0.6, severity=3) == 1.0
    assert normalize_signal_strength(0.3, severity=3) == 0.5


def test_normalize_rule_evidence_keeps_display_label_separate_from_score():
    evidence = normalize_rule_evidence(
        rule_id="L1-05",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.6,
        display_label="위험 높음",
    )

    assert evidence.signal_strength == 1.0
    assert evidence.evidence_strength == "strong"
    assert evidence.scoring_role == "primary"
    assert evidence.normalized_score == pytest.approx(0.6)
    assert evidence.display_label == "위험 높음"


def test_booster_rule_has_lower_direct_contribution_than_primary_rule():
    l304 = normalize_rule_evidence(
        rule_id="L3-04",
        evidence_type="timing_anomaly",
        severity=3,
        raw_value=0.6,
    )
    l308 = normalize_rule_evidence(
        rule_id="L3-08",
        evidence_type="timing_anomaly",
        severity=3,
        raw_value=0.6,
    )

    assert l308.scoring_role == "booster"
    assert l308.normalized_score < l304.normalized_score


def test_macro_rule_does_not_contribute_to_transaction_score():
    evidence = normalize_rule_evidence(
        rule_id="D01",
        evidence_type="macro_finding",
        severity=4,
        raw_value=0.8,
    )

    assert evidence.scoring_role == "macro_only"
    assert evidence.normalized_score == 0.0


def test_rule_score_uses_rule_signal_not_severity_only():
    weak_signal = normalize_rule_evidence(
        rule_id="L1-05",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.3,
    )
    strong_signal = normalize_rule_evidence(
        rule_id="L1-05",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.6,
    )

    assert weak_signal.signal_strength == pytest.approx(0.5)
    assert strong_signal.signal_strength == pytest.approx(1.0)
    assert weak_signal.normalized_score < strong_signal.normalized_score


def test_l101_normalized_score_preserves_imbalance_signal():
    evidence = normalize_rule_evidence(
        rule_id="L1-01",
        evidence_type="data_integrity_failure",
        severity=5,
        raw_value=0.15,
        display_label="rounding_scale",
    )

    assert evidence.signal_strength == pytest.approx(0.15)
    assert evidence.normalized_score == pytest.approx(0.15)
