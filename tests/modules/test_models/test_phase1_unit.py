"""PHASE1 document/flow unit additive schema tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.phase1_case import CaseGroupResult, Phase1CaseResult, RawRuleHitRef
from src.models.phase1_unit import DocumentUnit, FlowUnit


def _raw_hit(document_id: str = "DOC-1", row_index: int = 0) -> RawRuleHitRef:
    return RawRuleHitRef(
        rule_id="L1-05",
        severity=4,
        document_id=document_id,
        row_index=row_index,
        score=0.72,
        evidence_type="control_failure",
    )


def _case() -> CaseGroupResult:
    return CaseGroupResult(
        case_id="case_user_month_0001",
        primary_theme="control_failure",
        case_key="user=kim|month=2026-04",
        priority_score=0.8,
        composite_sort_score=0.9,
        raw_rule_hits=[_raw_hit()],
    )


def test_phase1_case_result_units_round_trip() -> None:
    document_unit = DocumentUnit(
        unit_id="DOC-1",
        evidence_rows=[_raw_hit()],
    )
    flow_unit = FlowUnit(
        unit_id="FLOW-1",
        flow_id="FLOW-1",
        flow_type="duplicate_payment",
        link_key={"counterparty": "V001", "amount_minor": 100000},
        member_document_ids=["DOC-1", "DOC-2"],
        evidence_rows=[_raw_hit("DOC-2", 1)],
        measurement_owner_unit_id="FLOW-1",
        absorbed_document_ids=["DOC-1"],
        absorbed_rule_hits=[_raw_hit()],
        cross_ref_flow_ids=["FLOW-2"],
        artifact_completeness="complete",
        source_artifact_schema="duplicate_pair_artifact.v1",
        candidate_count=2,
        retained_count=2,
        member_count=2,
        measurement_eligible=True,
    )
    original = Phase1CaseResult(
        run_id="run-p2-1",
        company_id="kr01",
        generated_at=datetime(2026, 6, 4, tzinfo=UTC),
        cases=[_case()],
        units=[document_unit, flow_unit],
    )

    restored = Phase1CaseResult.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.units[0].unit_type == "document"
    assert restored.units[1].unit_type == "flow"


def test_phase1_case_result_legacy_payload_without_units_loads_with_empty_units() -> None:
    legacy_payload = {
        "schema_version": "1.0.0",
        "run_id": "legacy-run",
        "company_id": "kr01",
        "generated_at": "2026-06-04T00:00:00Z",
        "cases": [_case().model_dump(mode="json")],
    }

    restored = Phase1CaseResult.model_validate(legacy_payload)

    assert restored.units == []


def test_case_group_result_contract_shape_is_unchanged() -> None:
    field_names = set(CaseGroupResult.model_fields)

    assert "case_id" in field_names
    assert "case_key" in field_names
    assert "priority_score" in field_names
    assert "composite_sort_score" in field_names
    assert "raw_rule_hits" in field_names
    assert "documents" in field_names
    assert "units" not in field_names


def test_document_unit_required_fields_and_unit_type_validation() -> None:
    unit = DocumentUnit(unit_id="DOC-1", evidence_rows=[_raw_hit()])

    assert unit.unit_type == "document"
    assert unit.unit_id == "DOC-1"
    assert unit.evidence_rows[0].document_id == "DOC-1"
    assert unit.priority_score == 0.0
    assert unit.topic_scores == {}

    with pytest.raises(ValidationError):
        DocumentUnit(unit_type="row", unit_id="DOC-1", evidence_rows=[])  # type: ignore[arg-type]


def test_flow_unit_required_fields_and_completeness_validation() -> None:
    unit = FlowUnit(
        unit_id="FLOW-1",
        flow_id="FLOW-1",
        flow_type="duplicate_payment",
        link_key={"counterparty": "V001"},
        member_document_ids=["DOC-1", "DOC-2"],
        evidence_rows=[_raw_hit()],
        artifact_completeness="bounded",
        truncated=True,
        cap_reason="duplicate_pair_artifact_top_n",
        candidate_count=5,
        retained_count=2,
        member_count=2,
        measurement_eligible=False,
    )

    assert unit.unit_type == "flow"
    assert unit.flow_id == "FLOW-1"
    assert unit.truncated is True
    assert unit.measurement_eligible is False
    assert unit.priority_score == 0.0
    assert unit.topic_scores == {}

    with pytest.raises(ValidationError):
        FlowUnit(
            unit_id="FLOW-1",
            flow_id="FLOW-1",
            flow_type="duplicate_payment",
            link_key={},
            member_document_ids=["DOC-1"],
            evidence_rows=[],
            artifact_completeness="partial",
        )
