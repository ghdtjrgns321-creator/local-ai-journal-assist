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
