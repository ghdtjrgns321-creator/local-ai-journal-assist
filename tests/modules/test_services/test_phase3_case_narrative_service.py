from __future__ import annotations

from types import SimpleNamespace

from src.llm.models import CaseNarrative
from src.services.phase3_case_narrative_service import attach_phase3_case_narratives


class _FakeCaseNarrativeGenerator:
    def __init__(self) -> None:
        self.kwargs = None

    def generate_from_pipeline_result(self, pipeline_result, **kwargs):
        self.kwargs = kwargs
        assert pipeline_result.phase1_case_result == "phase1"
        return [
            CaseNarrative(
                case_id="case_001",
                narrative="검토 필요",
                cited_rules=["L1-05"],
            )
        ]


def test_attach_phase3_case_narratives_sets_pipeline_result_field():
    generator = _FakeCaseNarrativeGenerator()
    pipeline_result = SimpleNamespace(
        phase1_case_result="phase1",
        phase2_case_overlays=[{"phase1_case_id": "case_001"}],
    )

    narratives = attach_phase3_case_narratives(
        pipeline_result,
        generator=generator,
        related_entity_risk_by_case={"case_001": {"summary": "linked"}},
        top_n=3,
        max_documents_per_case=5,
    )

    assert narratives == pipeline_result.phase3_case_narratives
    assert narratives[0].case_id == "case_001"
    assert generator.kwargs == {
        "related_entity_risk_by_case": {"case_001": {"summary": "linked"}},
        "top_n": 3,
        "max_documents_per_case": 5,
    }
