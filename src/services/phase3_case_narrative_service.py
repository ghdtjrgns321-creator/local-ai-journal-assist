"""Attach PHASE3 selected-case narratives to pipeline results."""

from __future__ import annotations

from typing import Any

from src.llm.case_narrative_generator import CaseNarrativeGenerator
from src.llm.models import CaseNarrative


def attach_phase3_case_narratives(
    pipeline_result,
    *,
    generator: CaseNarrativeGenerator | None = None,
    related_entity_risk_by_case: dict[str, dict[str, Any]] | None = None,
    top_n: int = 10,
    max_documents_per_case: int = 20,
) -> list[CaseNarrative]:
    """Generate PHASE3 case narratives and attach them to `pipeline_result`."""
    generator = generator or CaseNarrativeGenerator()
    narratives = generator.generate_from_pipeline_result(
        pipeline_result,
        related_entity_risk_by_case=related_entity_risk_by_case,
        top_n=top_n,
        max_documents_per_case=max_documents_per_case,
    )
    setattr(pipeline_result, "phase3_case_narratives", narratives)
    return narratives
