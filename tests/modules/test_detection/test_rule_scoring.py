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
    apply_topic_floors,
    compute_fraud_scenario_tags,
    compute_topic_scores,
    compute_topic_tiers,
    pick_primary_topic,
)


def _ev(rule_id: str, score: float = 0.6) -> dict[str, object]:
    """레드플래그 on 한 룰 evidence (나머지 메타는 RULE_SCORING_REGISTRY 폴백)."""
    return {"rule_id": rule_id, "normalized_score": score}


def test_related_party_reversal_is_medium_after_high7_handoff():
    # §3.0 / §8(4) HIGH-7 → MEDIUM 이관: 역분개(L2-05) & 관계사(L3-03) → duplicate_outflow MEDIUM
    # (related_party_reversal_medium). 기말 L3-04 필수 제외 — L2-05/L3-03 단독으로 승격되어야 한다.
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-03")])
    assert tiers["duplicate_outflow"].tier == "MEDIUM"


def test_expense_capitalization_fires_account_logic_high_via_period_end_leg():
    # §3.0 HIGH-9: L2-04 비용자산화 & L3-02 수기 & (L4-03|L3-04|L1-06) 셋째다리. 여기선 L3-04.
    tiers = compute_topic_tiers([_ev("L2-04"), _ev("L3-02"), _ev("L3-04")])
    assert tiers["account_logic"].tier == "HIGH"


def test_period_end_high_fires_via_corroborant_leg():
    # §3.0 HIGH-4: (L3-04|L3-11) & (L3-10|L4-04|L4-03). timing_seed(L3-04) + corroborant(L4-04).
    # §8(5) 적요부실 L3-08(0/22)은 corroborant 풀에서 삭제됨.
    tiers = compute_topic_tiers([_ev("L3-04"), _ev("L4-04")])
    assert tiers["closing_timing"].tier == "HIGH"


def test_period_end_not_high_via_removed_weak_description_leg():
    # §8(5) HIGH-4 적요부실 L3-08 헛다리 삭제: L3-04 + L3-08 만으로는 HIGH 불가.
    tiers = compute_topic_tiers([_ev("L3-04"), _ev("L3-08")])
    assert tiers["closing_timing"].tier != "HIGH"


def test_embezzlement_reversal_is_not_high_without_bypass_or_high_amount():
    # §3.0 HIGH-2 / §8(1) 고액 복원: 역분개(L2-05)+수기(L3-02)는 bypass 도 고액(L4-03)도 없으면
    # HIGH 불가(둘째 분기가 L4-03 을 AND 로 요구).
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-02")])
    assert tiers["duplicate_outflow"].tier != "HIGH"


def test_embezzlement_reversal_fires_high_with_manual_and_high_amount():
    # §3.0 HIGH-2 둘째 분기: (L2-02|L2-03|L2-05) & L3-02 & L4-03 → HIGH.
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-02"), _ev("L4-03")])
    assert tiers["duplicate_outflow"].tier == "HIGH"


def test_unknown_approver_with_cutoff_is_not_approval_high():
    # §3.0 HIGH-5: bypass & (L4-03|L2-02|L2-03). cutoff(L3-11)은 corroborant 가 아니므로
    # 유령승인자(L1-07-02)+cutoff 만으로는 approval HIGH 불가(§8(5) 강맥락 L3-11 삭제).
    tiers = compute_topic_tiers([_ev("L1-07-02"), _ev("L3-11")])
    assert tiers["approval_control"].tier != "HIGH"


def test_high_amount_corroborant_lifts_approval_bypass_to_high():
    # §3.0 HIGH-5 / §8(1) 고액 복원: 승인우회(L1-05) & 고액(L4-03) → approval HIGH.
    tiers = compute_topic_tiers([_ev("L1-05"), _ev("L4-03")])
    assert tiers["approval_control"].tier == "HIGH"


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
    # macro(D01/D02/L4-02)는 PHASE1-2 귀속이나 registry 에 macro_only 로 유지 — role_factor=0 으로
    # PHASE1-1 점수에 0 기여하도록 중화(항목을 지우면 폴백 점수가 붙음).
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


def test_l101_normalized_score_accepts_uniform_data_integrity_signal():
    evidence = normalize_rule_evidence(
        rule_id="L1-01",
        evidence_type="data_integrity_failure",
        severity=5,
        raw_value=1.0,
    )

    assert evidence.signal_strength == pytest.approx(1.0)
    assert evidence.normalized_score == pytest.approx(1.0)


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


def test_l104_boundary_bucket_does_not_receive_topic_floor():
    evidence = normalize_rule_evidence(
        rule_id="L1-04",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.4,
        display_label="boundary",
    )

    scores = compute_topic_scores([evidence])

    assert evidence.floor_policy_ids == ()
    assert scores["approval_control"] < 0.75


def test_l104_critical_bucket_does_not_receive_topic_floor():
    evidence = normalize_rule_evidence(
        rule_id="L1-04",
        evidence_type="control_failure",
        severity=3,
        raw_value=0.9,
        display_label="critical",
    )

    assert RULE_SCORING_REGISTRY["L1-04"].floor_policy_ids == ()
    assert RULE_SCORING_REGISTRY["L1-04"].floor_eligible_labels is None
    assert evidence.floor_policy_ids == ()


def test_l201_near_threshold_buckets_are_uniform_after_phase1_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L2-01",
            evidence_type="duplicate_or_outflow",
            severity=3,
            raw_value=1.0,
            display_label=bucket,
        ).normalized_score
        for bucket in ("lower_band", "close_band", "razor_band")
    ]

    assert normalized == pytest.approx([0.45, 0.45, 0.45])


def test_l201_routine_hit_has_zero_signal():
    routine = normalize_rule_evidence(
        rule_id="L2-01",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.0,
        display_label="razor_band",
    )

    assert routine.signal_strength == 0.0
    assert routine.normalized_score == 0.0


def test_l103_uniform_signal_has_no_bucket_override():
    evidence = normalize_rule_evidence(
        rule_id="L1-03",
        evidence_type="logic_mismatch",
        severity=3,
        raw_value=1.0,
        display_label="placeholder_or_reserved",
    )

    assert evidence.signal_strength == pytest.approx(1.0)
    assert evidence.normalized_score == pytest.approx(0.75)


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


def test_l305_calendar_scores_are_binary_after_phase1_normalization():
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-05",
            evidence_type="timing_anomaly",
            severity=2,
            raw_value=score,
            display_label=label,
        ).normalized_score
        for score, label in [
            (0.0, ""),
            (1.0, "weekend"),
            (1.0, "holiday"),
        ]
    ]

    assert normalized == pytest.approx([0.0, 0.117, 0.117])


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


def test_topic_registry_has_locked_six_topics():
    # IC/GR 제거(2026-06-14)로 intercompany_cycle 폐지 → 6주제
    assert list(TOPIC_REGISTRY) == [
        "ledger_integrity",
        "approval_control",
        "closing_timing",
        "account_logic",
        "duplicate_outflow",
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
    # macro 는 PHASE1-2 귀속이나 registry 에 macro_only 유지(PHASE1-1 점수 0 중화).
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
            "period_end_or_late_posting + weak_description_or_sensitive_account",
            [
                # §3.0 HIGH-4 corroborant 풀 (L3-10|L4-04|L4-03).
                # L3-08 은 §8(5) 삭제됨 → L4-04 사용.
                ("L3-04", "timing_anomaly", 3, 0.6, ""),
                ("L4-04", "logic_mismatch", 2, 0.6, ""),
            ],
        ),
        (
            "duplicate_outflow",
            "embezzlement_concealment_risk",
            0.75,
            "outflow_or_duplicate + (approval_bypass or manual_with_high_amount)",
            [
                ("L2-05", "duplicate_or_outflow", 3, 0.8, ""),
                ("L1-05", "control_failure", 4, 0.8, ""),
            ],
        ),
        (
            "revenue_statistical",
            "fictitious_entry_risk",
            0.75,
            "revenue_or_amount_outlier + manual_adjustment + secondary_red_flag",
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
            "approval_bypass + high_amount_or_duplicate",
            [
                # §3.0 HIGH-5 corroborant 풀 (L4-03|L2-02|L2-03).
                # cutoff(L3-11) 은 §8(5) 삭제됨 → L4-03 사용.
                ("L1-07", "control_failure", 4, 0.8, ""),
                ("L4-03", "statistical_outlier", 3, 0.7, ""),
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


def test_manual_scope_closing_does_not_create_fictitious_or_period_end_floor():
    evidences = _topic_evidences(
        [
            ("L3-02", "control_failure", 3, 0.8, ""),
            ("L3-04", "timing_anomaly", 3, 0.6, ""),
            ("L3-12", "access_scope_review", 3, 0.8, ""),
        ]
    )

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    tags = compute_fraud_scenario_tags(evidences)

    assert "fictitious_entry_risk" not in tags
    assert "period_end_adjustment_risk" not in tags
    assert breakdowns["revenue_statistical"].fraud_combo_policy_ids == ()
    assert breakdowns["closing_timing"].fraud_combo_policy_ids == ()


def test_approval_manual_scope_does_not_create_embezzlement_floor():
    evidences = _topic_evidences(
        [
            ("L1-05", "control_failure", 4, 0.8, ""),
            ("L3-02", "control_failure", 3, 0.8, ""),
            ("L3-12", "access_scope_review", 3, 0.8, ""),
        ]
    )

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    tags = compute_fraud_scenario_tags(evidences)

    assert "embezzlement_concealment_risk" not in tags
    assert breakdowns["duplicate_outflow"].fraud_combo_policy_ids == ()


# §3.0 / §8(5): approval_bypass_medium 전 분기 폐기. 승인우회 + 약맥락(수기·비영업일·야간)은
#   더 이상 어떤 approval combo floor 도 발화하지 않는다(HIGH-5 corroborant = L4-03|L2-02|L2-03 만).
@pytest.mark.parametrize(
    "rule_specs",
    [
        [
            ("L1-07", "control_failure", 4, 0.8, ""),
            ("L3-02", "control_failure", 3, 0.8, ""),
        ],
        [
            ("L1-07", "control_failure", 4, 0.8, ""),
            ("L3-05", "timing_anomaly", 3, 0.6, ""),
        ],
        [
            ("L1-07", "control_failure", 4, 0.8, ""),
            ("L3-06", "timing_anomaly", 3, 0.6, ""),
        ],
    ],
)
def test_approval_bypass_with_weak_context_fires_no_approval_combo_floor(rule_specs):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    # combo floor 미발화 → score 가 HIGH(0.75) 미만이고 fraud_combo policy 가 비어 있다.
    assert breakdowns["approval_control"].score < 0.75
    assert breakdowns["approval_control"].fraud_combo_policy_ids == ()


# §3.0 / §8(1) 고액 복원·§8(6) 조합 정합 이후, 근거 충족 HIGH 조합은 복원된 leg 로 발화한다.
#   - closing_timing: (L3-04|L3-11) & (L3-10|L4-04|L4-03)   ※L3-08 corroborant 삭제됨
#   - duplicate_outflow: (L2-02|L2-03|L2-05) & L3-02 & L4-03 (고액 AND)  ※bypass 없는 분기
@pytest.mark.parametrize(
    ("topic_id", "rule_specs", "expected_reason"),
    [
        (
            "closing_timing",
            [
                ("L3-04", "timing_anomaly", 3, 0.6, ""),
                ("L4-03", "statistical_outlier", 3, 0.7, ""),
            ],
            "period_end_or_late_posting + weak_description_or_sensitive_account",
        ),
        (
            "duplicate_outflow",
            [
                ("L2-05", "duplicate_or_outflow", 3, 0.8, ""),
                ("L3-02", "control_failure", 3, 0.8, ""),
                ("L4-03", "statistical_outlier", 3, 0.7, ""),
            ],
            "outflow_or_duplicate + (approval_bypass or manual_with_high_amount)",
        ),
    ],
)
def test_grounded_combos_fire_high_with_restored_legs(
    topic_id,
    rule_specs,
    expected_reason,
):
    evidences = _topic_evidences(rule_specs)

    breakdowns = compute_topic_scores(evidences, return_breakdown=True)

    assert breakdowns[topic_id].score >= 0.75
    assert expected_reason in breakdowns[topic_id].fraud_combo_policy_ids


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
    assert not any(tag.endswith("_risk") for tag in compute_fraud_scenario_tags(evidences))


def test_l202_duplicate_payment_reasons_are_uniform_binary():
    cases = [
        ("reference_match", 1.0),
        ("mixed_reference_fallback", 1.0),
        ("amount_partner_fallback", 1.0),
        ("blank_reference_fallback", 1.0),
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

    assert normalized == pytest.approx([0.60, 0.60, 0.60, 0.60])


def test_l202_near_extra_reason_does_not_receive_topic_floor():
    evidence = normalize_rule_evidence(
        rule_id="L2-02",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.70,
        display_label="near_extra",
    )

    assert evidence.floor_policy_ids == ()


def test_l202_reference_match_has_no_topic_floor():
    evidence = normalize_rule_evidence(
        rule_id="L2-02",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=1.0,
        display_label="reference_match",
    )

    scores = apply_topic_floors(
        {"duplicate_outflow": 0.0},
        [evidence],
    )

    assert evidence.floor_policy_ids == ()
    assert scores["duplicate_outflow"] == pytest.approx(0.0)


def test_fraud_combo_rule_scope_gates_automated_only_hits():
    """신뢰 자동 전표에서만 발화한 룰은 fraud combo 트리거에서 제외 (이슈 #14).

    Why: 자동 결산 배치 전표는 승인 부재·결산기 집중이 정상이므로, 그 행들에서만
    발화한 룰 조합은 사람 행위를 전제로 한 fraud combo floor를 받으면 안 된다.
    """
    evidences = _topic_evidences(
        [
            ("L3-04", "timing_anomaly", 3, 0.8, ""),
            ("L4-03", "statistical_outlier", 3, 0.8, "high_zscore"),
            ("L4-04", "logic_mismatch", 2, 0.45, ""),
        ]
    )

    open_breakdowns = compute_topic_scores(evidences, return_breakdown=True)
    gated_breakdowns = compute_topic_scores(
        evidences,
        return_breakdown=True,
        fraud_combo_rule_scope={"L4-04"},  # L3-04/L4-03은 신뢰 자동 행 발화 → 제외
    )

    assert open_breakdowns["closing_timing"].fraud_combo_policy_ids != ()
    assert gated_breakdowns["closing_timing"].fraud_combo_policy_ids == ()
    # Why: 메타데이터만이 아니라 점수 인상 경로(apply_combo_floors)도 게이트돼야 한다 —
    #      1차 구현이 기록 경로만 막고 점수는 그대로 0.75로 올린 회귀의 잠금.
    assert open_breakdowns["closing_timing"].score >= 0.75
    assert gated_breakdowns["closing_timing"].score < 0.75
