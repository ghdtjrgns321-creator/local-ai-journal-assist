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


def test_l104_bucket_normalization_preserves_phase1_risk_order():
    buckets = {
        "boundary": 0.4,
        "moderate": 0.6,
        "severe": 0.75,
        "critical": 0.9,
        "non_approver": 0.9,
    }

    normalized = {
        bucket: normalize_rule_evidence(
            rule_id="L1-04",
            evidence_type="control_failure",
            severity=3,
            raw_value=raw_score,
            display_label=bucket,
        ).normalized_score
        for bucket, raw_score in buckets.items()
    }

    assert normalized["boundary"] < normalized["moderate"]
    assert normalized["moderate"] < normalized["severe"]
    assert normalized["severe"] < normalized["critical"]
    assert normalized["critical"] == pytest.approx(normalized["non_approver"])


def test_l201_near_threshold_buckets_are_monotonic_after_phase1_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L2-01",
            evidence_type="duplicate_or_outflow",
            severity=3,
            raw_value=raw_score,
            display_label=bucket,
        ).normalized_score
        for bucket, raw_score in [
            ("lower_band", 0.45),
            ("close_band", 0.60),
            ("razor_band", 0.75),
        ]
    ]

    assert normalized == pytest.approx([0.27, 0.36, 0.45])
    assert normalized == sorted(normalized)


def test_l201_routine_razor_scores_below_manual_lower_band():
    routine = normalize_rule_evidence(
        rule_id="L2-01",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.35,
        display_label="razor_band",
    )
    manual_lower = normalize_rule_evidence(
        rule_id="L2-01",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.45,
        display_label="lower_band",
    )

    assert routine.normalized_score == pytest.approx(0.2025)
    assert routine.normalized_score < manual_lower.normalized_score


def test_l103_raw_score_is_not_folded_by_coarse_label():
    normalized = [
        normalize_rule_evidence(
            rule_id="L1-03",
            evidence_type="logic_mismatch",
            severity=3,
            raw_value=score,
            display_label="high",
        ).normalized_score
        for score in [0.60, 0.75, 0.90]
    ]

    assert normalized == pytest.approx([0.45, 0.5625, 0.675])
    assert normalized == sorted(normalized)
    assert len(set(normalized)) == 3


def test_l301_raw_score_order_is_preserved_after_normalization():
    normalized = {
        score: normalize_rule_evidence(
            rule_id="L3-01",
            evidence_type="logic_mismatch",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in [0.65, 0.45, 0.40]
    }

    assert normalized[0.65] == pytest.approx(0.2925)
    assert normalized[0.45] == pytest.approx(0.2025)
    assert normalized[0.40] == pytest.approx(0.18)
    assert normalized[0.65] > normalized[0.45] > normalized[0.40]


def test_l310_signal_bands_preserve_phase1_priority_order():
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-10",
            evidence_type="logic_mismatch",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in [0.20, 0.35, 0.65]
    ]

    assert normalized == pytest.approx([0.0351, 0.061425, 0.114075])
    assert normalized == sorted(normalized)
    assert len(set(normalized)) == 3


def test_l404_rare_pair_bands_preserve_phase1_priority_order():
    normalized = [
        normalize_rule_evidence(
            rule_id="L4-04",
            evidence_type="logic_mismatch",
            severity=2,
            raw_value=score,
        ).normalized_score
        for score in [0.25, 0.35, 0.45]
    ]

    assert normalized == pytest.approx([0.1875, 0.2625, 0.3375])
    assert normalized == sorted(normalized)
    assert len(set(normalized)) == 3


def test_l312_review_score_order_is_preserved_after_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-12",
            evidence_type="access_scope_review",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in [0.20, 0.35, 0.45, 0.55, 0.65]
    ]

    assert normalized == sorted(normalized)
    assert len(set(normalized)) == 5


def test_l107_component_score_is_preserved_for_phase1_priority():
    scores = [0.45, 0.69, 0.70, 0.80, 0.85, 0.95]

    normalized = [
        normalize_rule_evidence(
            rule_id="L1-07",
            evidence_type="control_failure",
            severity=4,
            raw_value=score,
            display_label="immediate",
        ).normalized_score
        for score in scores
    ]

    assert normalized == pytest.approx(scores)
    assert normalized == sorted(normalized)


def test_l305_calendar_scores_preserve_phase1_risk_order():
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-05",
            evidence_type="timing_anomaly",
            severity=2,
            raw_value=score,
            display_label=label,
        ).normalized_score
        for score, label in [
            (0.35, "weekday_holiday"),
            (0.40, "weekend"),
            (0.45, "weekend_holiday"),
        ]
    ]

    assert normalized == pytest.approx([0.135, 0.153, 0.18])
    assert normalized == sorted(normalized)


def test_l307_gap_buckets_are_monotonic_after_phase1_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-07",
            evidence_type="timing_anomaly",
            severity=3,
            raw_value=raw_score,
            display_label=bucket,
        ).normalized_score
        for bucket, raw_score in [
            ("late_moderate_gap", 0.45),
            ("late_large_gap", 0.60),
            ("late_extreme_gap", 0.75),
        ]
    ]

    assert normalized == pytest.approx([0.2475, 0.3375, 0.45])
    assert normalized == sorted(normalized)


def test_l403_zscore_buckets_are_monotonic_after_phase1_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L4-03",
            evidence_type="statistical_outlier",
            severity=3,
            raw_value=raw_score,
            display_label=bucket,
        ).normalized_score
        for bucket, raw_score in [
            ("low_zscore", 0.25),
            ("medium_zscore", 0.45),
            ("high_zscore", 0.70),
        ]
    ]

    assert normalized == pytest.approx([0.2025, 0.315, 0.45])
    assert normalized == sorted(normalized)


def test_l309_aging_score_is_monotonic_in_phase1_priority():
    scores = [0.45, 0.60, 0.75, 0.80]

    normalized = [
        normalize_rule_evidence(
            rule_id="L3-09",
            evidence_type="logic_mismatch",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in scores
    ]

    assert normalized == pytest.approx([0.3375, 0.45, 0.5625, 0.60])
    assert normalized == sorted(normalized)


def test_l309_aging_bucket_labels_preserve_phase1_order():
    normalized = {
        bucket: normalize_rule_evidence(
            rule_id="L3-09",
            evidence_type="logic_mismatch",
            severity=3,
            raw_value=0.60,
            display_label=bucket,
        ).normalized_score
        for bucket in ["aging_30_60", "aging_60_90", "aging_over_90"]
    }

    assert normalized["aging_30_60"] < normalized["aging_60_90"]
    assert normalized["aging_60_90"] < normalized["aging_over_90"]


def test_l306_system_context_scores_below_human_context_in_phase1_normalization():
    system_context = normalize_rule_evidence(
        rule_id="L3-06",
        evidence_type="timing_anomaly",
        severity=2,
        raw_value=0.20,
    )
    human_context = normalize_rule_evidence(
        rule_id="L3-06",
        evidence_type="timing_anomaly",
        severity=2,
        raw_value=0.45,
    )

    assert system_context.signal_strength == pytest.approx(0.20)
    assert human_context.signal_strength == pytest.approx(0.45)
    assert system_context.normalized_score < human_context.normalized_score


def test_l405_behavior_bands_preserve_phase1_priority_order():
    scores = [0.25, 0.45, 0.50, 0.55, 0.65]

    normalized = [
        normalize_rule_evidence(
            rule_id="L4-05",
            evidence_type="timing_anomaly",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in scores
    ]

    assert normalized == pytest.approx([0.0675, 0.1215, 0.135, 0.1485, 0.1755])
    assert normalized == sorted(normalized)


def test_l202_duplicate_payment_confidence_order_is_preserved():
    cases = [
        ("reference_match", 0.90),
        ("mixed_reference_fallback", 0.70),
        ("amount_partner_fallback", 0.65),
        ("blank_reference_fallback", 0.60),
    ]

    normalized = [
        normalize_rule_evidence(
            rule_id="L2-02",
            evidence_type="duplicate_or_outflow",
            severity=3,
            raw_value=raw_value,
            display_label=label,
        ).normalized_score
        for label, raw_value in cases
    ]

    assert normalized == pytest.approx([0.54, 0.42, 0.39, 0.36])
    assert normalized == sorted(normalized, reverse=True)
