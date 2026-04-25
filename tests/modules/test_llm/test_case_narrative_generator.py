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
                narrative="제공된 PHASE1 근거 기준으로 검토가 필요합니다.",
                cited_rules=["L1-05", "L9-99"],
                review_focus=["approval trail"],
                evidence_limitations=["no external policy supplied"],
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
    assert result[0].cited_rules == ["L1-05"]
    assert client.chat.called
    call_kwargs = client.chat.call_args.kwargs
    assert call_kwargs["temperature"] == 0.1
    assert "properties" in call_kwargs["format"]
    user_content = client.chat.call_args.args[0][1]["content"]
    assert "case_control_failure_00001" in user_content
    assert "source_report_id" in user_content


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
