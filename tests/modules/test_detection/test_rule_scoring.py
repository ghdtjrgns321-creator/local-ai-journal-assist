from __future__ import annotations

import pytest

from src.detection.phase1_case_builder import _RULE_THEME_MAP
from src.detection.rule_scoring import (
    RULE_SCORING_REGISTRY,
    TOPIC_REGISTRY,
    normalize_rule_evidence,
    normalize_signal_strength,
)
from src.detection.topic_scoring import (
    compute_fraud_scenario_tags,
    compute_topic_scores,
    pick_primary_topic,
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

    assert normalized == pytest.approx([0.08775, 0.09945, 0.117])
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

    assert normalized == pytest.approx([0.043875, 0.078975, 0.08775, 0.096525, 0.114075])
    assert normalized == sorted(normalized)


def test_topic_registry_has_locked_seven_topics():
    assert list(TOPIC_REGISTRY) == [
        "ledger_integrity",
        "approval_control",
        "closing_timing",
        "account_logic",
        "duplicate_outflow",
        "intercompany_cycle",
        "revenue_statistical",
    ]
    assert TOPIC_REGISTRY["ledger_integrity"].label == "원장기록·데이터정합성"


def test_locked_rule_topic_corrections_are_registered():
    l201 = RULE_SCORING_REGISTRY["L2-01"]
    l108 = RULE_SCORING_REGISTRY["L1-08"]

    assert l201.final_topic == "duplicate_outflow"
    assert l201.secondary_topics == ("approval_control",)
    assert l108.final_topic == "closing_timing"
    assert l108.secondary_topics == ("ledger_integrity",)


def test_all_registered_rules_have_one_locked_final_topic():
    missing = sorted(
        rule_id
        for rule_id, metadata in RULE_SCORING_REGISTRY.items()
        if metadata.final_topic not in TOPIC_REGISTRY
    )

    assert missing == []


@pytest.mark.parametrize("rule_id", ["L3-05", "L3-06"])
def test_l305_l306_are_boosters_not_standalone_rankable(rule_id: str):
    metadata = RULE_SCORING_REGISTRY[rule_id]

    assert metadata.scoring_role == "booster"
    assert metadata.standalone_rankable is False


@pytest.mark.parametrize("rule_id", ["L4-02", "Benford", "D01", "D02"])
def test_locked_macro_only_rules_have_zero_standalone_contribution(rule_id: str):
    evidence = normalize_rule_evidence(
        rule_id=rule_id,
        evidence_type=RULE_SCORING_REGISTRY[rule_id].evidence_type,
        severity=3,
        raw_value=1.0,
    )

    assert evidence.scoring_role == "macro_only"
    assert evidence.standalone_rankable is False
    assert evidence.normalized_score == 0.0


@pytest.mark.parametrize("rule_id", ["L4-06", "L3-12"])
def test_locked_combo_only_rules_do_not_seed_topic_score(rule_id: str):
    evidence = normalize_rule_evidence(
        rule_id=rule_id,
        evidence_type=RULE_SCORING_REGISTRY[rule_id].evidence_type,
        severity=3,
        raw_value=1.0,
    )

    scores = compute_topic_scores([evidence])

    assert evidence.scoring_role == "combo_only"
    assert evidence.standalone_rankable is False
    assert max(scores.values()) == 0.0


def test_topic_scoring_uses_primary_secondary_and_tags():
    primary = normalize_rule_evidence(
        rule_id="L2-01",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.75,
        display_label="razor_band",
    )
    secondary = normalize_rule_evidence(
        rule_id="L1-05",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.1,
    )

    scores = compute_topic_scores([primary, secondary])

    assert pick_primary_topic(scores) == "duplicate_outflow"
    assert scores["duplicate_outflow"] > scores["approval_control"]
    assert compute_fraud_scenario_tags([primary, secondary]) == (
        "threshold_splitting",
        "approval_bypass",
        "embezzlement_concealment_risk",
    )


def test_audit_evidence_score_boosts_but_does_not_seed_topic_score():
    no_rule_scores = compute_topic_scores(
        [],
        audit_evidence_score={"approval_control": 1.0},
    )
    primary = normalize_rule_evidence(
        rule_id="L1-05",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.6,
    )
    without_context = compute_topic_scores([primary])
    with_context = compute_topic_scores(
        [primary],
        audit_evidence_score={"approval_control": 1.0},
    )

    assert max(no_rule_scores.values()) == 0.0
    assert with_context["approval_control"] > without_context["approval_control"]
    assert with_context["approval_control"] < 0.75


def _topic_evidences(rule_specs):
    return [
        normalize_rule_evidence(
            rule_id=rule_id,
            evidence_type=evidence_type,
            severity=severity,
            raw_value=raw_value,
            display_label=display_label,
        )
        for rule_id, evidence_type, severity, raw_value, display_label in rule_specs
    ]


@pytest.mark.parametrize(
    ("topic_id", "expected_tag", "expected_floor", "expected_reason", "rule_specs"),
    [
        (
            "closing_timing",
            "period_end_adjustment_risk",
            0.75,
            "period_end_or_late_posting + high_amount + weak_description_or_sensitive_account",
            [
                ("L3-04", "timing_anomaly", 3, 0.6, ""),
                ("L4-03", "statistical_outlier", 3, 0.7, "high_zscore"),
                ("L3-08", "timing_anomaly", 1, 0.6, ""),
            ],
        ),
        (
            "duplicate_outflow",
            "embezzlement_concealment_risk",
            0.75,
            "outflow_or_duplicate + approval_bypass",
            [
                ("L2-05", "duplicate_or_outflow", 3, 0.8, ""),
                ("L1-05", "control_failure", 4, 0.8, ""),
            ],
        ),
        (
            "intercompany_cycle",
            "circular_transaction_risk",
            0.45,
            "related_party_or_ic + amount_or_timing_anomaly",
            [
                ("L3-03", "intercompany_structure", 3, 0.6, ""),
                ("L4-03", "statistical_outlier", 3, 0.7, "high_zscore"),
            ],
        ),
        (
            "revenue_statistical",
            "fictitious_entry_risk",
            0.75,
            "revenue_or_amount_outlier + manual_adjustment + rare_or_duplicate_pattern",
            [
                ("L4-01", "statistical_outlier", 3, 0.8, ""),
                ("L3-02", "control_failure", 3, 0.8, ""),
                ("L4-04", "logic_mismatch", 2, 0.45, ""),
            ],
        ),
        (
            "approval_control",
            "approval_bypass_risk",
            0.75,
            "approval_bypass + high_amount_or_cutoff_or_strong_abnormal_timing",
            [
                ("L1-07", "control_failure", 4, 0.8, ""),
                ("L4-03", "statistical_outlier", 3, 0.8, "high_zscore"),
            ],
        ),
    ],
)
def test_fraud_combo_floor_raises_expected_topic_score(
    topic_id,
    expected_tag,
    expected_floor,
    expected_reason,
    rule_specs,
):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    assert expected_tag in compute_fraud_scenario_tags(evidences)
    assert breakdowns[topic_id].score >= expected_floor
    assert expected_reason in breakdowns[topic_id].fraud_combo_policy_ids
    assert expected_tag in breakdowns[topic_id].fraud_combo_tags
    assert "manipulation_candidate" not in TOPIC_REGISTRY


def test_circular_transaction_combo_gets_high_floor_when_repeat_or_cycle_context_exists():
    evidences = _topic_evidences([
        ("IC01", "intercompany_structure", 3, 0.8, ""),
        ("L3-11", "timing_anomaly", 3, 0.8, ""),
    ])

    breakdowns = compute_topic_scores(
        evidences,
        repeat_score={"intercompany_cycle": 1.0},
        return_breakdown=True,
    )

    assert breakdowns["intercompany_cycle"].score == pytest.approx(0.75)
    assert "related_party_or_ic + amount_or_timing_anomaly + repeat_or_counterparty_cycle" in (
        breakdowns["intercompany_cycle"].fraud_combo_policy_ids
    )


def test_manual_scope_closing_does_not_create_fictitious_or_period_end_floor():
    evidences = _topic_evidences([
        ("L3-02", "control_failure", 3, 0.8, ""),
        ("L3-04", "timing_anomaly", 3, 0.6, ""),
        ("L3-12", "access_scope_review", 3, 0.8, ""),
    ])

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    tags = compute_fraud_scenario_tags(evidences)

    assert "fictitious_entry_risk" not in tags
    assert "period_end_adjustment_risk" not in tags
    assert breakdowns["revenue_statistical"].fraud_combo_policy_ids == ()
    assert breakdowns["closing_timing"].fraud_combo_policy_ids == ()


@pytest.mark.parametrize(
    "rule_specs",
    [
        [
            ("L3-03", "intercompany_structure", 3, 0.6, ""),
            ("L3-05", "timing_anomaly", 3, 0.6, ""),
            ("L3-02", "control_failure", 3, 0.8, ""),
        ],
        [
            ("L3-03", "intercompany_structure", 3, 0.6, ""),
            ("L3-05", "timing_anomaly", 3, 0.6, ""),
            ("L3-12", "access_scope_review", 3, 0.8, ""),
        ],
    ],
)
def test_related_party_weekend_manual_or_scope_does_not_create_circular_high_floor(
    rule_specs,
):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    assert breakdowns["intercompany_cycle"].score < 0.75
    assert "related_party + manual_or_scope_context + non_business_day_timing" not in (
        breakdowns["intercompany_cycle"].fraud_combo_policy_ids
    )


def test_approval_manual_scope_does_not_create_embezzlement_floor():
    evidences = _topic_evidences([
        ("L1-05", "control_failure", 4, 0.8, ""),
        ("L3-02", "control_failure", 3, 0.8, ""),
        ("L3-12", "access_scope_review", 3, 0.8, ""),
    ])

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    tags = compute_fraud_scenario_tags(evidences)

    assert "embezzlement_concealment_risk" not in tags
    assert breakdowns["duplicate_outflow"].fraud_combo_policy_ids == ()


@pytest.mark.parametrize(
    ("rule_specs", "blocked_reason", "expected_medium_reason"),
    [
        (
            [
                ("L1-07", "control_failure", 4, 0.8, ""),
                ("L3-02", "control_failure", 3, 0.8, ""),
            ],
            "approval_bypass + manual_adjustment",
            "approval_bypass + manual_adjustment_context",
        ),
        (
            [
                ("L1-07", "control_failure", 4, 0.8, ""),
                ("L3-05", "timing_anomaly", 3, 0.6, ""),
            ],
            "approval_bypass + non_business_day_timing",
            "approval_bypass + non_business_day_context",
        ),
        (
            [
                ("L1-07", "control_failure", 4, 0.8, ""),
                ("L3-06", "timing_anomaly", 3, 0.6, ""),
            ],
            "approval_bypass + abnormal_time",
            "approval_bypass + after_hours_context",
        ),
    ],
)
def test_approval_bypass_with_weak_timing_or_manual_context_is_medium_not_high(
    rule_specs,
    blocked_reason,
    expected_medium_reason,
):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    assert breakdowns["approval_control"].score >= 0.60
    assert breakdowns["approval_control"].score < 0.75
    assert blocked_reason not in breakdowns["approval_control"].fraud_combo_policy_ids
    assert expected_medium_reason in breakdowns["approval_control"].fraud_combo_policy_ids


@pytest.mark.parametrize(
    ("topic_id", "rule_specs", "blocked_reason"),
    [
        (
            "closing_timing",
            [
                ("L3-04", "timing_anomaly", 3, 0.6, ""),
                ("L3-02", "control_failure", 3, 0.8, ""),
                ("L3-08", "timing_anomaly", 1, 0.6, ""),
            ],
            "period_end + manual_adjustment + weak_description",
        ),
        (
            "duplicate_outflow",
            [
                ("L2-05", "duplicate_or_outflow", 3, 0.8, ""),
                ("L3-12", "access_scope_review", 3, 0.8, ""),
                ("L3-02", "control_failure", 3, 0.8, ""),
            ],
            "reversal_or_offset + work_scope_concentration + manual_adjustment",
        ),
    ],
)
def test_weak_context_combinations_do_not_create_medium_floor(
    topic_id,
    rule_specs,
    blocked_reason,
):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    tags = compute_fraud_scenario_tags(evidences)

    assert breakdowns[topic_id].score < 0.60
    assert blocked_reason not in breakdowns[topic_id].fraud_combo_policy_ids
    assert not any(tag.endswith("_risk") for tag in tags)


@pytest.mark.parametrize(
    "rule_specs",
    [
        [("L4-03", "statistical_outlier", 3, 0.7, "high_zscore")],
        [("L3-04", "timing_anomaly", 3, 0.6, "")],
        [("L3-03", "intercompany_structure", 3, 0.6, "")],
    ],
)
def test_single_rules_do_not_apply_fraud_combo_floor(rule_specs):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    assert not any(breakdown.fraud_combo_tags for breakdown in breakdowns.values())
    assert not any(breakdown.fraud_combo_policy_ids for breakdown in breakdowns.values())
    assert not any(
        tag.endswith("_risk") for tag in compute_fraud_scenario_tags(evidences)
    )


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
