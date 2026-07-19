from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.llm.case_narrative_generator import CaseNarrativeGenerator
from src.llm.models import CaseNarrative, CaseNarrativeBatch
from tests.modules.test_services.test_phase2_case_contract import _phase1_result


def test_case_narrative_generator_uses_pipeline_case_payloads():
    phase1 = _phase1_result()
    phase1.cases[0].is_top_case = True
    client = MagicMock()
    client.chat.return_value = CaseNarrativeBatch(
        cases=[
            CaseNarrative(
                case_id="case_control_failure_00001",
                summary="PHASE1 근거와 PHASE2 관계 신호를 함께 검토할 항목입니다.",
                narrative="제공된 PHASE1 근거 기준으로 검토가 필요합니다.",
                cited_rules=["L1-05", "L9-99"],
                review_focus=["approval trail"],
                suggested_audit_actions=[
                    {
                        "action_type": "request_evidence",
                        "description": "승인 증빙을 확인합니다.",
                        "target": "approval trail",
                    }
                ],
                evidence_limitations=["no external policy supplied"],
                phase2_family_summary={
                    "families": ["relational"],
                    "summary": "구조적 관계 신호가 보조 근거로 제공되었습니다.",
                },
            )
        ]
    ).model_dump_json()
    pipeline_result = SimpleNamespace(
        phase1_case_result=phase1,
        phase2_case_overlays=[
            {
                "phase1_case_id": "case_control_failure_00001",
                "phase2_family_scores": {"relational": 0.4},
                "phase2_inference_contract": {"source_report_id": "train_001"},
                "phase2_training_report_id": "train_001",
            }
        ],
    )

    result = CaseNarrativeGenerator(client=client).generate_from_pipeline_result(
        pipeline_result
    )

    assert len(result) == 1
    assert result[0].case_id == "case_control_failure_00001"
    assert result[0].summary == "PHASE1 근거와 PHASE2 관계 신호를 함께 검토할 항목입니다."
    assert result[0].cited_rules == ["L1-05"]
    assert result[0].suggested_audit_actions[0]["action_type"] == "request_evidence"
    assert result[0].phase2_family_summary == {
        "families": ["relational"],
        "summary": "구조적 관계 신호가 보조 근거로 제공되었습니다.",
    }
    assert client.chat.called
    call_kwargs = client.chat.call_args.kwargs
    assert call_kwargs["temperature"] == 0.1
    assert "properties" in call_kwargs["format"]
    schema_properties = call_kwargs["format"]["$defs"]["CaseNarrative"]["properties"]
    assert "summary" in schema_properties
    assert "suggested_audit_actions" in schema_properties
    assert "phase2_family_summary" in schema_properties
    user_content = client.chat.call_args.args[0][1]["content"]
    assert "case_control_failure_00001" in user_content
    assert "source_report_id" in user_content
    assert "Do not reorder cases or assign new priority" in user_content
    assert "suggested_audit_actions" in user_content
    assert "phase2_family_summary" in user_content


def test_case_narrative_generator_returns_empty_without_phase1():
    client = MagicMock()

    result = CaseNarrativeGenerator(client=client).generate_from_pipeline_result(
        SimpleNamespace(phase1_case_result=None)
    )

    assert result == []
    assert not client.chat.called


def test_case_narrative_generator_drops_unrequested_cases():
    client = MagicMock()
    client.chat.return_value = CaseNarrativeBatch(
        cases=[
            CaseNarrative(
                case_id="unexpected",
                narrative="ignore",
                cited_rules=[],
            )
        ]
    ).model_dump_json()

    result = CaseNarrativeGenerator(client=client).generate_from_payloads(
        [{"case_id": "expected", "top_rule_ids": ["L1-05"], "top_documents": []}]
    )

    assert result == []
