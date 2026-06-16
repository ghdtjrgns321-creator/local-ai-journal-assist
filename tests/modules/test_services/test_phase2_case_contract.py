from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
)
from src.services.phase2_case_contract import (
    PROVENANCE_ONLY_FIELDS,
    apply_phase2_tie_break,
    build_phase2_case_feature_frame,
    build_phase2_case_overlays,
    build_phase2_case_provenance,
    enforce_phase2_case_feature_firewall,
)


def _phase1_result() -> Phase1CaseResult:
    case = CaseGroupResult(
        case_id="case_control_failure_00001",
        primary_theme="control_failure",
        secondary_tags=["statistical_outlier"],
        evidence_types=["control_failure", "statistical_outlier"],
        case_key="kim / P2P / 2026-04",
        priority_score=0.8,
        base_priority_score=0.65,
        topside_bonus=0.10,
        batch_combo_bonus=0.05,
        priority_adjustment_reasons=["topside_score=0.40", "batch_combo_groups=2"],
        priority_band="high",
        amount_score=0.7,
        control_score=0.9,
        logic_score=0.1,
        timing_score=0.3,
        behavior_score=0.4,
        repeat_score=0.5,
        rule_count=2,
        evidence_count=3,
        document_count=2,
        row_count=3,
        total_amount=30_000_000.0,
        repeat_months=2,
        representative_explanation="승인 통제 위반 검토 필요",
        evidence_tags=["control_failure", "statistical_outlier"],
        documents=[
            CaseDocumentRef(
                document_id="D1",
                created_by="kim",
                business_process="P2P",
                counterparty="V001",
                amount=10_000_000.0,
            ),
            CaseDocumentRef(
                document_id="D2",
                created_by="lee",
                business_process="R2R",
                counterparty="V002",
                amount=20_000_000.0,
            ),
        ],
        raw_rule_hits=[
            RawRuleHitRef(
                rule_id="L1-05",
                severity=3,
                document_id="D1",
                row_index=0,
                score=0.6,
                evidence_type="control_failure",
            ),
            RawRuleHitRef(
                rule_id="L1-07",
                severity=4,
                document_id="D1",
                row_index=1,
                score=0.8,
                evidence_type="control_failure",
            ),
            RawRuleHitRef(
                rule_id="L4-03",
                severity=3,
                document_id="D2",
                row_index=2,
                score=0.6,
                evidence_type="statistical_outlier",
            ),
        ],
        has_control_failure=True,
        has_high_materiality=True,
        has_repeat_pattern=True,
    )
    return Phase1CaseResult(
        run_id="phase1case_test",
        company_id="kr01",
        generated_at=datetime(2026, 4, 25, tzinfo=UTC),
        cases=[case],
    )


def test_phase2_case_feature_frame_excludes_rule_and_theme_identifiers():
    frame = build_phase2_case_feature_frame(_phase1_result())

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["rule_diversity_count"] == 3
    assert row["evidence_type_count"] == 2
    assert bool(row["cross_process_flag"]) is True
    assert bool(row["cross_user_flag"]) is True
    assert frame.index.name == "phase1_case_id"
    assert frame.index[0] == "case_control_failure_00001"

    forbidden = {
        "phase1_case_id",
        "primary_theme",
        "secondary_tags",
        "top_rule_ids",
        "raw_rule_hits",
    }
    assert forbidden.isdisjoint(frame.columns)


def test_phase2_case_feature_firewall_blocks_provenance_columns():
    frame = build_phase2_case_feature_frame(_phase1_result())
    frame["top_rule_ids"] = "L1-05"

    with pytest.raises(ValueError, match="provenance columns"):
        enforce_phase2_case_feature_firewall(frame)


def test_phase2_case_feature_firewall_blocks_string_features():
    frame = pd.DataFrame(
        {
            "rule_diversity_count": ["three"],
            "evidence_type_count": [2],
        }
    )

    with pytest.raises(TypeError, match="numeric/boolean"):
        enforce_phase2_case_feature_firewall(frame)


def test_phase2_case_provenance_contains_display_only_fields():
    provenance = build_phase2_case_provenance(_phase1_result())

    assert set(PROVENANCE_ONLY_FIELDS).issubset(provenance[0])
    assert provenance[0]["primary_theme"] == "control_failure"
    assert provenance[0]["top_rule_ids"] == ["L1-05", "L1-07", "L4-03"]
    assert provenance[0]["phase1_case_priority"] == 0.8
    assert provenance[0]["phase1_base_priority"] == 0.65
    assert provenance[0]["phase1_priority_adjustments"]["topside_bonus"] == 0.10
    assert provenance[0]["phase1_priority_adjustments"]["reasons"] == [
        "topside_score=0.40",
        "batch_combo_groups=2",
    ]


def test_phase2_case_overlays_preserve_phase1_priority():
    overlays = build_phase2_case_overlays(
        _phase1_result(),
        family_scores_by_case={
            "case_control_failure_00001": {"timeseries": 0.6, "relational": 0.4}
        },
        phase2_training_report_id="train_001",
    )

    overlay = overlays[0]
    assert overlay["phase1_case_id"] == "case_control_failure_00001"
    assert overlay["phase2_family_scores"] == {"timeseries": 0.6, "relational": 0.4}
    assert overlay["phase2_adjusted_priority"] == 0.71
    assert overlay["phase2_training_report_id"] == "train_001"


def test_phase2_case_overlay_does_not_mutate_phase1_priority_score():
    """옵션 Z lock HARD: overlay 적용 전후 case.priority_score 가 row-wise 동일.

    PHASE1 priority_score 는 PHASE2 family_scores 가 주어져도 절대 덮어쓰여지지 않는다
    (Stage 7 phase1_phase2_integration_stage7.assert_priority_score_preserved 와 동일 계약).
    """
    phase1 = _phase1_result()
    snapshot = {case.case_id: float(case.priority_score) for case in phase1.cases}

    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={
            "case_control_failure_00001": {
                "ml_unsupervised": 0.95,
                "timeseries": 0.6,
            }
        },
        phase2_training_report_id="train_z_lock",
    )

    # 원본 priority_score 가 모든 case 에서 변경되지 않았다 (diff == 0)
    for case in phase1.cases:
        assert float(case.priority_score) == snapshot[case.case_id], (
            f"case {case.case_id} priority_score 가 overlay 적용 후 변경됨: "
            f"{snapshot[case.case_id]} → {case.priority_score}"
        )

    # overlay 는 phase2_adjusted_priority 컬럼으로만 영향을 전달한다 (별도 필드)
    overlay = overlays[0]
    assert "phase2_adjusted_priority" in overlay
    assert overlay["phase2_adjusted_priority"] is not None
    # adjusted 와 base 가 다른지(=실제로 overlay 가 계산되었는지) 확인
    assert overlay["phase2_adjusted_priority"] != snapshot["case_control_failure_00001"]


def test_phase2_case_overlay_without_family_scores_reports_not_applied():
    """family_scores 가 비어 있으면 adjusted_priority 는 None, reason 은 phase2_not_applied."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(phase1)
    overlay = overlays[0]

    assert overlay["phase2_adjusted_priority"] is None
    assert overlay["precision_adjustment_reason"] == "phase2_not_applied"
    # 원본 priority 는 여전히 보존
    assert float(phase1.cases[0].priority_score) == 0.8


def test_phase2_case_overlay_keys_do_not_include_priority_score():
    """overlay dict 의 키 자체에 priority_score 가 없다 (이름 충돌로 인한 덮어쓰기 방지)."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": {"ml_unsupervised": 0.9}},
    )
    overlay_keys = set(overlays[0].keys())

    # PHASE1 priority_score 와 동일한 키명을 overlay 가 갖지 않아야 다운스트림에서
    # dict merge 시 의도치 않은 덮어쓰기가 발생하지 않음.
    assert "priority_score" not in overlay_keys
    # adjusted 는 명시적으로 phase2_ 접두사로 격리됨
    assert "phase2_adjusted_priority" in overlay_keys


# ──────────────────────────────────────────────────────────────────────────────
# Phase D 신규 필드 + tie-break 가드 회귀
# ──────────────────────────────────────────────────────────────────────────────


def _phase1_two_cases() -> Phase1CaseResult:  # noqa: F841 — 향후 multi-case fixture 용 예약
    """두 case 가 거의 같은 priority_score 를 갖는 fixture."""
    cases = [
        CaseGroupResult(
            case_id="case_A",
            primary_theme="control_failure",
            secondary_tags=[],
            evidence_types=["control_failure"],
            case_key="A",
            priority_score=0.50,
            base_priority_score=0.50,
            topside_bonus=0.0,
            batch_combo_bonus=0.0,
            priority_adjustment_reasons=[],
            priority_band="medium",
            amount_score=0.5,
            control_score=0.5,
            logic_score=0.0,
            timing_score=0.0,
            behavior_score=0.0,
            repeat_score=0.0,
            rule_count=1,
            evidence_count=1,
            document_count=1,
            row_count=1,
            total_amount=50_000_000.0,
            repeat_months=1,
            representative_explanation="A",
            evidence_tags=["control_failure"],
            documents=[],
            raw_rule_hits=[],
            has_control_failure=True,
            has_high_materiality=False,
            has_repeat_pattern=False,
        ),
        CaseGroupResult(
            case_id="case_B",
            primary_theme="control_failure",
            secondary_tags=[],
            evidence_types=["control_failure"],
            case_key="B",
            priority_score=0.50,
            base_priority_score=0.50,
            topside_bonus=0.0,
            batch_combo_bonus=0.0,
            priority_adjustment_reasons=[],
            priority_band="medium",
            amount_score=0.5,
            control_score=0.5,
            logic_score=0.0,
            timing_score=0.0,
            behavior_score=0.0,
            repeat_score=0.0,
            rule_count=1,
            evidence_count=1,
            document_count=1,
            row_count=1,
            total_amount=10_000_000.0,
            repeat_months=1,
            representative_explanation="B",
            evidence_tags=["control_failure"],
            documents=[],
            raw_rule_hits=[],
            has_control_failure=True,
            has_high_materiality=False,
            has_repeat_pattern=False,
        ),
    ]
    return Phase1CaseResult(
        run_id="phase1case_test",
        company_id="kr01",
        generated_at=datetime(2026, 4, 25, tzinfo=UTC),
        cases=cases,
    )


def test_overlay_populates_family_contributions_and_lane_membership():
    """build_phase2_case_overlays 가 신규 필드 7종 모두 채움."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={
            "case_control_failure_00001": {
                "unsupervised": 0.97,
                "duplicate": 0.60,
                "intercompany": 0.0,
            }
        },
        family_ecdf_by_case={
            "case_control_failure_00001": {
                "unsupervised": 0.99,
                "duplicate": 0.95,
                "intercompany": 0.0,
            }
        },
        family_top_subdetectors_by_case={
            "case_control_failure_00001": {
                "duplicate": [("L2-03a", "exact_duplicate_amount")],
                "unsupervised": [("VAE-01", "audit_vae_reconstruction")],
            }
        },
        family_roles={
            "unsupervised": "active-ranker",
            "duplicate": "active-ranker",
            "intercompany": "near-dormant",
        },
        family_q95_thresholds={"unsupervised": 0.97, "duplicate": 0.60, "intercompany": 0.0},
    )

    overlay = overlays[0]
    # 신규 7개 필드 모두 존재
    for key in (
        "family_contributions",
        "top_family",
        "coverage_breadth_q95",
        "max_family_ecdf",
        "max_evidence_tier",
        "lane_membership",
        "coverage_gap_families",
    ):
        assert key in overlay, f"missing field {key}"

    # duplicate L2-03a 는 strong tier → max_evidence_tier=strong
    assert overlay["max_evidence_tier"] == "strong"
    # top_family 는 evidence_tier 우선 정렬이므로 duplicate (strong) 가
    # unsupervised (ml_quantile) 보다 위
    assert overlay["top_family"] == "duplicate"
    # coverage_breadth: unsupervised >= 0.97 (Y), duplicate >= 0.60 (Y),
    # intercompany 는 near-dormant 로 제외 → 2
    assert overlay["coverage_breadth_q95"] == 2
    # max_family_ecdf 는 0.99 (unsupervised)
    assert overlay["max_family_ecdf"] == pytest.approx(0.99)
    # near-dormant 인 intercompany 는 lane_membership 에서 제외 + coverage_gap_families 에 포함
    assert "intercompany" not in overlay["lane_membership"]
    assert "intercompany" in overlay["coverage_gap_families"]
    # active family 는 lane 에 포함
    assert "unsupervised" in overlay["lane_membership"]
    assert "duplicate" in overlay["lane_membership"]


def test_overlay_no_family_signals_keeps_defaults():
    """family signal 미공급 시 신규 필드 default 값 유지 + PHASE1 priority 보존."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(phase1)
    overlay = overlays[0]

    assert overlay["family_contributions"] == []
    assert overlay["top_family"] is None
    assert overlay["coverage_breadth_q95"] == 0
    assert overlay["max_family_ecdf"] is None
    assert overlay["max_evidence_tier"] is None
    assert overlay["lane_membership"] == []
    # PHASE1 priority 보존
    assert float(phase1.cases[0].priority_score) == 0.8


def test_overlay_keeps_intercompany_review_only_without_phase2_score_inflation():
    """IC01 review-only 는 confirmed score 없이 lane/metadata 에만 남긴다."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_review_only_by_case={
            "case_control_failure_00001": {
                "intercompany": {
                    "review_only_count": 2,
                    "review_reasons": ["missing_partner", "mapping_uncertain"],
                }
            }
        },
        family_roles={"intercompany": "near-dormant"},
    )

    overlay = overlays[0]
    assert overlay["phase2_family_scores"] == {}
    assert overlay["phase2_adjusted_priority"] is None
    assert overlay["precision_adjustment_reason"] == "phase2_not_applied"
    assert overlay["top_family"] is None
    assert overlay["phase2_review_band"] == "none"
    assert overlay["lane_membership"] == ["intercompany"]

    contribution = overlay["family_contributions"][0]
    assert contribution["family"] == "intercompany"
    assert contribution["score"] == 0.0
    assert contribution["review_only"] is True
    assert contribution["review_only_count"] == 2
    assert contribution["review_reasons"] == ["missing_partner", "mapping_uncertain"]


def test_overlay_attaches_unsupervised_document_context_display_only():
    """P3: document evidence/context is surfaced on the contribution only.

    The context values must not change adjusted priority, banding, or contribution sort
    because B3 keeps family_score as the raw max score.
    """
    phase1 = _phase1_result()
    base_kwargs = {
        "phase1": phase1,
        "family_scores_by_case": {
            "case_control_failure_00001": {"unsupervised": 0.97, "duplicate": 0.6}
        },
        "family_ecdf_by_case": {
            "case_control_failure_00001": {"unsupervised": 0.99, "duplicate": 0.95}
        },
        "family_top_subdetectors_by_case": {
            "case_control_failure_00001": {
                "unsupervised": [("VAE-01", "audit_vae_reconstruction")],
                "duplicate": [("L2-03a", "exact_duplicate_amount")],
            }
        },
        "family_roles": {"unsupervised": "active-ranker", "duplicate": "active-ranker"},
        "family_q95_thresholds": {"unsupervised": 0.95, "duplicate": 0.5},
    }
    without_context = build_phase2_case_overlays(**base_kwargs)[0]
    with_context = build_phase2_case_overlays(
        **base_kwargs,
        family_explanation_features_by_case={
            "case_control_failure_00001": {
                "unsupervised": [
                    {
                        "feature_id": "num__posting_date_weekend",
                        "feature": "num__posting_date_weekend",
                        "contrib": 0.55,
                        "tag": "unusual_timing",
                        "label_ko": "비정상 거래시점",
                        "evidence_type": "statistical_outlier",
                    }
                ]
            }
        },
        family_document_context_by_case={
            "case_control_failure_00001": {
                "unsupervised": {
                    "unit_type": "document",
                    "document_id": "D1",
                    "evidence_row_count": 2,
                    "top_score_mean": 0.91,
                    "score_spread": 0.12,
                    "amount_tail_context": 1.0,
                    "period_end_context": 1.0,
                    "account_rarity_context": 1.0,
                    "process_rarity_context": 1.0,
                    "repeated_normal_pressure": 0.0,
                    "reason_tags": ["unusual_timing"],
                    "max_score_row_ref": {"row_position": 1, "document_id": "D1"},
                    "max_score_top_features": [{"feature_id": "num__amount_z"}],
                }
            }
        },
    )[0]

    assert with_context["phase2_adjusted_priority"] == without_context["phase2_adjusted_priority"]
    assert with_context["phase2_review_band"] == without_context["phase2_review_band"]
    assert with_context["top_family"] == without_context["top_family"]
    contribution = next(
        item for item in with_context["family_contributions"] if item["family"] == "unsupervised"
    )
    assert contribution["evidence_type"] == "statistical_outlier"
    assert contribution["explanation_features"][0]["feature_id"] == "num__posting_date_weekend"
    assert contribution["unit_type"] == "document"
    assert contribution["evidence_row_count"] == 2
    assert contribution["top_score_mean"] == pytest.approx(0.91)
    assert contribution["score_spread"] == pytest.approx(0.12)
    assert contribution["amount_tail_context"] == pytest.approx(1.0)
    assert contribution["period_end_context"] == pytest.approx(1.0)
    assert contribution["account_rarity_context"] == pytest.approx(1.0)
    assert contribution["process_rarity_context"] == pytest.approx(1.0)
    assert contribution["repeated_normal_pressure"] == pytest.approx(0.0)
    assert contribution["reason_tags"] == ["unusual_timing"]
    assert "document_id" not in contribution
    assert "document_id" not in contribution["document_context"]
    assert "max_score_row_ref" not in contribution
    assert "max_score_row_ref" not in contribution["document_context"]


def test_tie_break_preserves_primary_order_outside_near_tie():
    """primary RRF score 차이가 near_tie_eps 초과 시 primary 순위 유지 (가드)."""
    primary = {"case_A": 0.10, "case_B": 0.05, "case_C": 0.01}
    overlays = {
        # case_C 가 모든 ladder 기준에서 1등이지만 primary score 가 낮으면 1등 못함
        "case_C": {
            "coverage_breadth_q95": 99,
            "max_family_ecdf": 1.0,
            "max_evidence_tier": "strong",
        },
        "case_B": {"coverage_breadth_q95": 0, "max_family_ecdf": 0.1, "max_evidence_tier": "weak"},
        "case_A": {"coverage_breadth_q95": 0, "max_family_ecdf": 0.1, "max_evidence_tier": "weak"},
    }
    result = apply_phase2_tie_break(primary, overlays, near_tie_eps=1e-9)
    # primary order 그대로 유지 — 가드 동작
    assert result == ["case_A", "case_B", "case_C"]


def test_tie_break_applies_ladder_within_near_tie_group():
    """primary score 가 동률 (또는 ≤ eps) 일 때만 ladder 적용."""
    primary = {"case_A": 0.50, "case_B": 0.50, "case_C": 0.50}
    overlays = {
        "case_A": {"coverage_breadth_q95": 1, "max_family_ecdf": 0.5, "max_evidence_tier": "weak"},
        "case_B": {
            "coverage_breadth_q95": 3,
            "max_family_ecdf": 0.7,
            "max_evidence_tier": "strong",
        },
        "case_C": {
            "coverage_breadth_q95": 2,
            "max_family_ecdf": 0.6,
            "max_evidence_tier": "moderate",
        },
    }
    result = apply_phase2_tie_break(primary, overlays)
    # coverage_breadth 순: B(3) > C(2) > A(1)
    assert result == ["case_B", "case_C", "case_A"]


def test_tie_break_ladder_step_3_strong_subdetector_count():
    """coverage_breadth + ecdf 동률 시 strong_subdetector_count 가 다음 분기.

    #4 fix 후 count 는 sub_detectors[].evidence_tier=='strong' 만 카운트한다.
    """
    primary = {"case_A": 0.50, "case_B": 0.50}
    overlays = {
        "case_A": {
            "coverage_breadth_q95": 2,
            "max_family_ecdf": 0.5,
            "max_evidence_tier": "strong",
            "family_contributions": [
                {
                    "family": "duplicate",
                    "evidence_tier": "strong",
                    "sub_detectors": [{"code": "L2-03a", "evidence_tier": "strong"}],
                }
            ],
        },
        "case_B": {
            "coverage_breadth_q95": 2,
            "max_family_ecdf": 0.5,
            "max_evidence_tier": "strong",
            "family_contributions": [
                {
                    "family": "duplicate",
                    "evidence_tier": "strong",
                    "sub_detectors": [
                        {"code": "L2-03a", "evidence_tier": "strong"},
                        {"code": "R01", "evidence_tier": "strong"},
                        {"code": "R02", "evidence_tier": "strong"},
                    ],
                }
            ],
        },
    }
    result = apply_phase2_tie_break(primary, overlays)
    # B 가 strong sub-detector 3개로 더 많음
    assert result == ["case_B", "case_A"]


def test_tie_break_ladder_step_6_total_amount_as_final_resort():
    """모든 ladder 단계 동률 시 총 금액으로 최종 분기."""
    primary = {"case_A": 0.50, "case_B": 0.50}
    overlays = {
        "case_A": {"coverage_breadth_q95": 0, "max_family_ecdf": 0.0, "max_evidence_tier": None},
        "case_B": {"coverage_breadth_q95": 0, "max_family_ecdf": 0.0, "max_evidence_tier": None},
    }
    amounts = {"case_A": 10_000_000.0, "case_B": 50_000_000.0}
    result = apply_phase2_tie_break(primary, overlays, total_amounts_by_case=amounts)
    assert result == ["case_B", "case_A"]


def test_tie_break_empty_overlay_safe():
    """overlay dict 가 비어 있어도 primary score 정렬은 정상 동작."""
    primary = {"x": 0.30, "y": 0.50, "z": 0.10}
    result = apply_phase2_tie_break(primary, {})
    assert result == ["y", "x", "z"]


# ──────────────────────────────────────────────────────────────────────────────
# Post-review bug fix 회귀 (2026-05-19)
# ──────────────────────────────────────────────────────────────────────────────


def test_coverage_breadth_excludes_near_dormant_family():
    """near-dormant family 는 q95=0 이어도 breadth 카운트되지 않는다 (#3)."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={
            "case_control_failure_00001": {
                "unsupervised": 0.99,
                "intercompany": 0.0,
            }
        },
        family_roles={
            "unsupervised": "active-ranker",
            "intercompany": "near-dormant",
        },
        family_q95_thresholds={"unsupervised": 0.97, "intercompany": 0.0},
    )
    # intercompany 는 near-dormant 라 카운트 제외 → unsupervised 만 = 1
    assert overlays[0]["coverage_breadth_q95"] == 1


def test_coverage_breadth_positive_guard_when_threshold_zero():
    """threshold ≤ 0 이면 score > 0 인 case 만 카운트 (positive guard, #3)."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={
            "case_control_failure_00001": {
                "active_low_threshold": 0.0,  # threshold=0 이고 score=0 → 카운트 X
                "active_with_score": 0.3,  # threshold=0 이지만 score>0 → 카운트 O
            }
        },
        family_roles={
            "active_low_threshold": "active-ranker",
            "active_with_score": "active-ranker",
        },
        family_q95_thresholds={"active_low_threshold": 0.0, "active_with_score": 0.0},
    )
    assert overlays[0]["coverage_breadth_q95"] == 1


def test_lane_membership_excludes_low_ecdf_non_tail_cases():
    """ECDF 가 q95(=0.95) 미만이고 score=0 이면 lane 에 진입하지 않는다 (#2)."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={
            "case_control_failure_00001": {
                "active_quiet": 0.0,  # score=0, ecdf=0.5 → lane 진입 X (ecdf<0.95)
                "active_tail": 0.0,  # score=0, ecdf=0.96 → lane 진입 O (ecdf>=0.95)
                "active_hit": 0.4,  # score>0 → lane 진입 O
            }
        },
        family_ecdf_by_case={
            "case_control_failure_00001": {
                "active_quiet": 0.5,
                "active_tail": 0.96,
                "active_hit": 0.7,
            }
        },
        family_roles={
            "active_quiet": "active-ranker",
            "active_tail": "active-ranker",
            "active_hit": "active-ranker",
        },
    )
    lanes = overlays[0]["lane_membership"]
    assert "active_quiet" not in lanes
    assert "active_tail" in lanes
    assert "active_hit" in lanes


def test_strong_subdetector_count_includes_multiple_per_family():
    """같은 family 에 strong sub-detector 가 2개 이상이면 그대로 누적 (#4)."""
    primary = {"case_M": 0.50, "case_S": 0.50}
    # case_M 은 duplicate 안에 strong sub-detector 2개 (L2-03a 두 번 hit 가정)
    # case_S 는 duplicate 안에 strong sub-detector 1개
    overlays = {
        "case_M": {
            "family_contributions": [
                {
                    "family": "duplicate",
                    "evidence_tier": "strong",
                    "sub_detectors": [
                        {"code": "L2-03a", "evidence_tier": "strong"},
                        {"code": "L2-03a", "evidence_tier": "strong"},
                    ],
                }
            ],
            "coverage_breadth_q95": 1,
            "max_family_ecdf": 0.9,
            "max_evidence_tier": "strong",
        },
        "case_S": {
            "family_contributions": [
                {
                    "family": "duplicate",
                    "evidence_tier": "strong",
                    "sub_detectors": [{"code": "L2-03a", "evidence_tier": "strong"}],
                }
            ],
            "coverage_breadth_q95": 1,
            "max_family_ecdf": 0.9,
            "max_evidence_tier": "strong",
        },
    }
    result = apply_phase2_tie_break(primary, overlays)
    # case_M 의 strong sub-detector count=2 > case_S=1
    assert result == ["case_M", "case_S"]


def test_family_contributions_attach_evidence_tier_per_sub_detector():
    """contribution.sub_detectors[]에 evidence_tier/tier_weight 가 부착되어야 한다 (#4)."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": {"duplicate": 0.6, "timeseries": 0.4}},
        family_ecdf_by_case={"case_control_failure_00001": {"duplicate": 0.95, "timeseries": 0.8}},
        family_top_subdetectors_by_case={
            "case_control_failure_00001": {
                "duplicate": [
                    ("L2-03a", "exact_duplicate_amount"),
                    ("L2-03d", "time_shifted_duplicate"),
                ],
                "timeseries": [("TS01", "transaction_burst")],
            }
        },
        family_roles={"duplicate": "active-ranker", "timeseries": "coarse-booster"},
    )
    contributions = overlays[0]["family_contributions"]
    duplicate_entry = next(c for c in contributions if c["family"] == "duplicate")
    subs = {s["code"]: s for s in duplicate_entry["sub_detectors"]}
    # YAML lock 상 L2-03a=strong, L2-03d=weak
    assert subs["L2-03a"]["evidence_tier"] == "strong"
    assert subs["L2-03a"]["evidence_tier_weight"] == 3
    assert subs["L2-03d"]["evidence_tier"] == "weak"
    assert subs["L2-03d"]["evidence_tier_weight"] == 1
    timeseries_entry = next(c for c in contributions if c["family"] == "timeseries")
    ts_subs = {s["code"]: s for s in timeseries_entry["sub_detectors"]}
    # TS01 = moderate
    assert ts_subs["TS01"]["evidence_tier"] == "moderate"


# ──────────────────────────────────────────────────────────────────────────────
# Duplicate lane pair_evidence_tier 부착 회귀 (sort 보조키 한정)
# ──────────────────────────────────────────────────────────────────────────────


def test_overlay_attaches_pair_evidence_tier_to_duplicate_entry_only():
    """duplicate_pair_evidence_by_case 가 전달되면 duplicate entry 에만 부착."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": {"duplicate": 0.6, "timeseries": 0.4}},
        family_top_subdetectors_by_case={
            "case_control_failure_00001": {
                "duplicate": [("L2-03a", "exact_duplicate_amount")],
                "timeseries": [("TS01", "transaction_burst")],
            }
        },
        duplicate_pair_evidence_by_case={"case_control_failure_00001": "strong"},
    )
    contributions = overlays[0]["family_contributions"]
    duplicate_entry = next(c for c in contributions if c["family"] == "duplicate")
    timeseries_entry = next(c for c in contributions if c["family"] == "timeseries")
    assert duplicate_entry["pair_evidence_tier"] == "strong"
    assert duplicate_entry["pair_evidence_tier_weight"] == 3
    # 다른 family entry 에는 pair_evidence_tier 가 부착되지 않음 (영향 0).
    assert "pair_evidence_tier" not in timeseries_entry
    assert "pair_evidence_tier_weight" not in timeseries_entry


def test_overlay_pair_evidence_missing_keeps_duplicate_entry_unchanged():
    """duplicate_pair_evidence_by_case 가 비어 있으면 duplicate entry 도 부착되지 않음."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": {"duplicate": 0.6}},
        family_top_subdetectors_by_case={
            "case_control_failure_00001": {"duplicate": [("L2-03a", "exact_duplicate_amount")]}
        },
        # duplicate_pair_evidence_by_case 미전달 (graceful fallback)
    )
    contributions = overlays[0]["family_contributions"]
    duplicate_entry = next(c for c in contributions if c["family"] == "duplicate")
    assert "pair_evidence_tier" not in duplicate_entry
    assert "pair_evidence_tier_weight" not in duplicate_entry


def test_overlay_pair_evidence_weak_tier_is_attached_with_weight_one():
    """weak tier 도 weight=1 로 부착되어 sort 보조키에서 차등화된다."""
    phase1 = _phase1_result()
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": {"duplicate": 0.6}},
        family_top_subdetectors_by_case={
            "case_control_failure_00001": {"duplicate": [("L2-03a", "exact_duplicate_amount")]}
        },
        duplicate_pair_evidence_by_case={"case_control_failure_00001": "weak"},
    )
    contributions = overlays[0]["family_contributions"]
    duplicate_entry = next(c for c in contributions if c["family"] == "duplicate")
    assert duplicate_entry["pair_evidence_tier"] == "weak"
    assert duplicate_entry["pair_evidence_tier_weight"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# IC internal probability column → review_band 영향 (옵션 2 의도 lock, 2026-05-25)
#
# `phase2_subdetector_tiers.yaml` 에 등록된 IC 4개 internal prob column 은
# `_build_family_contributions` 에서 family entry 의 `evidence_tier` 로 승격되며,
# 결과적으로 `classify_phase2_review_band` 가 max_evidence_tier 기반으로 분류한다.
# 이 chain 은 옵션 2 의 의도된 부수효과 (audit semantic — ISA 550 ¶A20 인용 정합)
# 이며 본 회귀가 계약을 고정한다. docs/spec/PHASE2_INTERFACE_DESIGN.md §4.3.2 참조.
# ──────────────────────────────────────────────────────────────────────────────


def _ic_only_overlay(
    *,
    ic_code: str,
    ic_score: float = 0.7,
    extra_family_scores: dict[str, float] | None = None,
    extra_family_subdetectors: dict[str, list[tuple[str, str]]] | None = None,
    extra_q95: dict[str, float] | None = None,
) -> dict:
    """build_phase2_case_overlays 호출 helper — IC family + optional 다른 family."""
    phase1 = _phase1_result()
    family_scores = {"intercompany": ic_score}
    family_scores.update(extra_family_scores or {})
    family_subdetectors = {"intercompany": [(ic_code, ic_code)]}
    family_subdetectors.update(extra_family_subdetectors or {})
    q95 = {"intercompany": 0.0}
    q95.update(extra_q95 or {})
    overlays = build_phase2_case_overlays(
        phase1,
        family_scores_by_case={"case_control_failure_00001": family_scores},
        family_top_subdetectors_by_case={"case_control_failure_00001": family_subdetectors},
        family_roles={family: "active-ranker" for family in family_scores},
        family_q95_thresholds=q95,
    )
    return overlays[0]


class TestIntercompanyInternalProbReviewBandImpact:
    """IC internal prob column 등록 후 review_band 승격 경로 계약 회귀."""

    def test_reciprocal_flow_alone_strong_tier_yields_review_when_breadth_below_two(self):
        # ic_reciprocal_flow_prob 단독 → family tier=strong → breadth=1 → review.
        overlay = _ic_only_overlay(ic_code="ic_reciprocal_flow_prob")
        assert overlay["max_evidence_tier"] == "strong"
        assert overlay["phase2_review_band"] == "review"

    def test_reciprocal_flow_with_second_family_strong_tier_yields_immediate(self):
        # ic_reciprocal_flow_prob (strong) + duplicate active → breadth>=2 → immediate.
        overlay = _ic_only_overlay(
            ic_code="ic_reciprocal_flow_prob",
            extra_family_scores={"duplicate": 0.6},
            extra_family_subdetectors={"duplicate": [("L2-03a", "exact_duplicate_amount")]},
            extra_q95={"duplicate": 0.5},
        )
        assert overlay["max_evidence_tier"] == "strong"
        assert overlay["coverage_breadth_q95"] >= 2
        assert overlay["phase2_review_band"] == "immediate"

    def test_amount_prob_with_second_family_moderate_tier_yields_review(self):
        # ic_amount_prob (moderate) + duplicate L2-03b moderate active → breadth>=2 → review.
        overlay = _ic_only_overlay(
            ic_code="ic_amount_prob",
            extra_family_scores={"duplicate": 0.6},
            extra_family_subdetectors={"duplicate": [("L2-03b", "fuzzy_duplicate")]},
            extra_q95={"duplicate": 0.5},
        )
        assert overlay["max_evidence_tier"] in {"moderate", "strong"}
        assert overlay["coverage_breadth_q95"] >= 2
        # max_evidence_tier=moderate + breadth>=2 → review.
        # (duplicate L2-03b 도 moderate 이므로 strong 으로 올라가지 않음)
        assert overlay["max_evidence_tier"] == "moderate"
        assert overlay["phase2_review_band"] == "review"

    def test_amount_prob_alone_moderate_tier_below_breadth_yields_candidate(self):
        # ic_amount_prob 단독 → family tier=moderate → breadth=1 → candidate (D060 4번).
        overlay = _ic_only_overlay(ic_code="ic_amount_prob")
        assert overlay["max_evidence_tier"] == "moderate"
        assert overlay["phase2_review_band"] == "candidate"

    def test_unmatched_prob_alone_weak_tier_yields_candidate(self):
        # ic_unmatched_prob 단독 → family tier=weak → candidate (weak 단독 review 진입 금지).
        overlay = _ic_only_overlay(ic_code="ic_unmatched_prob")
        assert overlay["max_evidence_tier"] == "weak"
        assert overlay["phase2_review_band"] == "candidate"

    def test_timing_prob_alone_weak_tier_yields_candidate(self):
        # ic_timing_prob 단독 → family tier=weak → candidate.
        overlay = _ic_only_overlay(ic_code="ic_timing_prob")
        assert overlay["max_evidence_tier"] == "weak"
        assert overlay["phase2_review_band"] == "candidate"
