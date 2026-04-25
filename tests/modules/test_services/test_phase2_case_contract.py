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
