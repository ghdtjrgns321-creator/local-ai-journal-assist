from __future__ import annotations

from src.llm.phase3_case_prompt import (
    build_phase3_selected_case_inputs,
    phase3_fact_grounding_system_prompt,
)
from src.models.phase1_case import CaseDocumentRef
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def test_build_phase3_selected_case_inputs_uses_case_and_overlay_only():
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    overlays = [
        {
            "phase1_case_id": "case_control_failure_00001",
            "phase2_family_scores": {"relational": 0.7},
            "phase2_inference_contract": {"required_models": ["relational"]},
            "phase2_training_report_id": "train_001",
        }
    ]

    payloads = build_phase3_selected_case_inputs(
        phase1,
        phase2_case_overlays=overlays,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"counterparty_recent_case_count": 3}
        },
    )

    payload = payloads[0]
    assert payload["case_id"] == "case_control_failure_00001"
    assert payload["phase2_family_scores"] == {"relational": 0.7}
    assert payload["phase2_training_report_id"] == "train_001"
    assert "top_documents" in payload
    assert payload["related_entity_risk"] == {"counterparty_recent_case_count": 3}


def test_phase3_related_entity_risk_is_conditionally_omitted():
    phase1 = _phase1_result()
    phase1.cases[0].secondary_tags = []
    payloads = build_phase3_selected_case_inputs(
        phase1,
        phase2_case_overlays=[],
        related_entity_risk_by_case={
            "case_control_failure_00001": {"counterparty_recent_case_count": 3}
        },
    )

    assert "related_entity_risk" not in payloads[0]


def test_phase3_limits_and_ranks_case_documents():
    phase1 = _phase1_result()
    phase1.cases[0].documents = [
        CaseDocumentRef(
            document_id=f"D{i:02d}",
            amount=float(i * 1_000),
            matched_rules=["L1-05"] if i % 2 == 0 else [],
            evidence_tags=["control_failure"] if i % 3 == 0 else [],
        )
        for i in range(30)
    ]

    payloads = build_phase3_selected_case_inputs(
        phase1,
        max_documents_per_case=99,
    )

    documents = payloads[0]["top_documents"]
    assert len(documents) == 20
    assert [doc["document_id"] for doc in documents[:3]] == ["D29", "D28", "D27"]


def test_phase3_related_entity_risk_includes_duplicate_statistical_and_degree_context():
    phase1 = _phase1_result()
    phase1.cases[0].primary_theme = "duplicate_or_outflow"
    payloads = build_phase3_selected_case_inputs(
        phase1,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"summary": "multi-process vendor"}
        },
    )
    assert "related_entity_risk" in payloads[0]

    phase1.cases[0].primary_theme = "control_failure"
    phase1.cases[0].secondary_tags = []
    payloads = build_phase3_selected_case_inputs(
        phase1,
        related_entity_risk_by_case={
            "case_control_failure_00001": {"degree": 2, "summary": "degree > 1"}
        },
    )
    assert "related_entity_risk" in payloads[0]


def test_phase3_fact_grounding_system_prompt_contains_constraints():
    prompt = phase3_fact_grounding_system_prompt()

    assert "Use only the selected case input" in prompt
    assert "Do not infer external accounting standards" in prompt
    assert "Do not conclude fraud" in prompt
