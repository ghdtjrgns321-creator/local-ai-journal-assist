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
    compute_topic_tiers,
    pick_primary_topic,
)


def _ev(rule_id: str, score: float = 0.6) -> dict[str, object]:
    """레드플래그 on 한 룰 evidence (나머지 메타는 RULE_SCORING_REGISTRY 폴백)."""
    return {"rule_id": rule_id, "normalized_score": score}


def test_old_related_party_reversal_combo_no_longer_promotes():
    # tier 폐지(PHASE1_COMBO_BUILDER_SPEC §6): 구 related_party_reversal_medium 조합은
    # 등급을 만들지 않는다 — L2-05 standalone 게이트(LOW)만 남는다.
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-03")])
    assert tiers["duplicate_outflow"].tier == "LOW"


def test_old_expense_capitalization_high_combo_no_longer_promotes():
    tiers = compute_topic_tiers([_ev("L2-04"), _ev("L3-02"), _ev("L3-04")])
    assert tiers["account_logic"].tier == "LOW"


def test_old_period_end_high_combo_no_longer_promotes():
    tiers = compute_topic_tiers([_ev("L3-04"), _ev("L3-10")])
    assert tiers["closing_timing"].tier == "LOW"


def test_old_embezzlement_high_combo_no_longer_promotes():
    tiers = compute_topic_tiers([_ev("L2-05"), _ev("L3-02"), _ev("L4-03")])
    assert tiers["duplicate_outflow"].tier == "LOW"


def test_old_approval_bypass_high_combo_no_longer_promotes():
    tiers = compute_topic_tiers([_ev("L1-05"), _ev("L4-03")])
    assert tiers["approval_control"].tier == "LOW"


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
    l305 = normalize_rule_evidence(
        rule_id="L3-05",
        evidence_type="timing_anomaly",
        severity=3,
        raw_value=0.6,
    )

    assert l305.scoring_role == "booster"
    assert l305.normalized_score < l304.normalized_score


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


def test_binary_unified_rules_ignore_legacy_bucket_labels():
    # L1-04·L3-07·L3-09 는 binary 통일(2026-06-20, 기다/아니다만). 옛 bucket label 을 줘도
    # 등급 없이 일관된 binary 강도를 내야 한다(grading 죽은 코드 제거 검증, hollow 방지).
    cases = [
        ("L1-04", "control_failure", ["boundary", "severe", "critical"]),
        ("L3-07", "timing_anomaly", ["moderate_gap", "large_gap", "extreme_gap"]),
        ("L3-09", "logic_mismatch", ["aging_30_60", "aging_60_90", "aging_over_90"]),
    ]
    for rule_id, evidence_type, labels in cases:
        strengths = [
            normalize_rule_evidence(
                rule_id=rule_id,
                evidence_type=evidence_type,
                severity=3,
                raw_value=1.0,
                display_label=label,
            ).signal_strength
            for label in [None, *labels]
        ]
        # 모든 label(없음 포함)에서 동일(binary) + 발화 시 1.0
        assert len({round(s, 6) for s in strengths}) == 1
        assert strengths[0] == pytest.approx(1.0)


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


def test_l404_rare_pair_contributes_binary_after_phase1_normalization():
    # binary 전환: 발화(raw>0)면 옛 bucket 크기(0.25/0.35/0.45)와 무관하게 동일 기여.
    # 강도(쌍 개수)·정황·조합은 통합점수·case priority 소관이므로 룰 기여는 binary.
    fired = [
        normalize_rule_evidence(
            rule_id="L4-04",
            evidence_type="logic_mismatch",
            severity=2,
            raw_value=score,
        ).normalized_score
        for score in [0.25, 0.35, 0.45]
    ]
    # 세 bucket 모두 동일값 = bucket 차등 폐기
    assert len(set(fired)) == 1
    assert fired[0] > 0.0

    # 미발화(raw=0)는 0 기여
    none = normalize_rule_evidence(
        rule_id="L4-04",
        evidence_type="logic_mismatch",
        severity=2,
        raw_value=0.0,
    ).normalized_score
    assert none == 0.0

    # signal_strength 도 binary(발화=1.0)
    sig = normalize_rule_evidence(
        rule_id="L4-04",
        evidence_type="logic_mismatch",
        severity=2,
        raw_value=0.45,
    ).signal_strength
    assert sig == pytest.approx(1.0)


def test_l312_is_macro_only_zero_contribution():
    """L3-12(업무범위)는 PHASE1-2 family 귀속 — macro_only 로 row anomaly_score 0 기여(2026-06-21).

    과거 combo_only 로 raw band 순서를 보존했으나, PHASE1-1 통합점수 완전 제거로 0 고정.
    """
    normalized = [
        normalize_rule_evidence(
            rule_id="L3-12",
            evidence_type="access_scope_review",
            severity=3,
            raw_value=score,
        ).normalized_score
        for score in [0.20, 0.35, 0.45, 0.55, 0.65]
    ]

    assert all(score == 0.0 for score in normalized)


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


def test_l403_binary_score_normalizes_via_generic_fallback():
    """L4-03 binary(0/1) 발화 — generic fallback이 일관된 normalized score를 반환한다."""
    # binary hit: score=1.0
    hit = normalize_rule_evidence(
        rule_id="L4-03",
        evidence_type="statistical_outlier",
        severity=3,
        raw_value=1.0,
        display_label="",
    ).normalized_score
    # no hit: score=0.0
    miss = normalize_rule_evidence(
        rule_id="L4-03",
        evidence_type="statistical_outlier",
        severity=3,
        raw_value=0.0,
        display_label="",
    ).normalized_score
    # hit > miss, 둘 다 [0,1] 범위
    assert 0.0 <= miss < hit <= 1.0
    # 구 bucket score(0.25/0.45/0.70) 값은 더 이상 특별 처리되지 않음 — generic 정규화 통과
    bucket_score = normalize_rule_evidence(
        rule_id="L4-03",
        evidence_type="statistical_outlier",
        severity=3,
        raw_value=0.25,
        display_label="low_zscore",
    ).normalized_score
    # generic fallback은 raw_value를 그대로 정규화하므로 0~hit 사이 값
    assert 0.0 <= bucket_score <= hit


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
def test_phase1_2_family_rules_do_not_contribute_to_topic_score(rule_id: str):
    """L4-06(배치)·L3-12(업무범위)는 PHASE1-2 family — macro_only 로 topic seed/score 0 기여(2026-06-21)."""
    evidence = normalize_rule_evidence(
        rule_id=rule_id,
        evidence_type=RULE_SCORING_REGISTRY[rule_id].evidence_type,
        severity=3,
        raw_value=1.0,
    )

    scores = compute_topic_scores([evidence])

    assert evidence.scoring_role == "macro_only"
    assert evidence.normalized_score == 0.0
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

    # 점수 폐지: topic 점수는 전부 0 — 우선순위 선택은 게이트/빌더 몫.
    assert max(scores.values()) == 0.0
    assert pick_primary_topic(scores) is None
    # 태그는 룰 메타데이터 기원만 남는다(구 combo 기원 embezzlement_concealment_risk 제거).
    assert compute_fraud_scenario_tags([primary, secondary]) == (
        "threshold_splitting",
        "approval_bypass",
    )


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

    scores = compute_topic_scores([evidence])

    assert evidence.floor_policy_ids == ()
    assert scores["duplicate_outflow"] == pytest.approx(0.0)
