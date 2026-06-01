"""PHASE3 selected-case narrative generation."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.api_client import ChatClient, get_chat_client
from src.llm.models import CaseNarrative, CaseNarrativeBatch
from src.llm.phase3_case_prompt import (
    build_phase3_selected_case_inputs,
    phase3_fact_grounding_system_prompt,
)

logger = logging.getLogger(__name__)


class CaseNarrativeGenerator:
    """Generate PHASE3 narratives from selected PHASE1 cases and PHASE2 overlays."""

    def __init__(self, client: ChatClient | None = None) -> None:
        self.client = client if client is not None else get_chat_client("reasoning")

    def generate_from_pipeline_result(
        self,
        pipeline_result,
        *,
        related_entity_risk_by_case: dict[str, dict[str, Any]] | None = None,
        top_n: int = 10,
        max_documents_per_case: int = 20,
    ) -> list[CaseNarrative]:
        phase1 = getattr(pipeline_result, "phase1_case_result", None)
        if phase1 is None:
            return []

        payloads = build_phase3_selected_case_inputs(
            phase1,
            phase2_case_overlays=getattr(pipeline_result, "phase2_case_overlays", []),
            related_entity_risk_by_case=related_entity_risk_by_case,
            top_n=top_n,
            max_documents_per_case=max_documents_per_case,
        )
        return self.generate_from_payloads(payloads)

    def generate_from_payloads(
        self,
        payloads: list[dict[str, Any]],
    ) -> list[CaseNarrative]:
        if not payloads:
            return []

        messages = self._build_prompt(payloads)
        raw = self.client.chat(
            messages,
            temperature=0.1,
            format=CaseNarrativeBatch.model_json_schema(),
        )
        try:
            parsed = CaseNarrativeBatch.model_validate_json(raw)
        except Exception:
            logger.warning("PHASE3 case narrative JSON parse failed", exc_info=True)
            return []
        return self._validate_outputs(list(parsed.cases), payloads)

    @staticmethod
    def _build_prompt(payloads: list[dict[str, Any]]) -> list[dict[str, str]]:
        user = (
            "Generate PHASE3 selected-case narratives in Korean.\n"
            "Return one object per requested case_id.\n"
            "Do not add facts outside the provided case payload.\n"
            "Do not reorder cases or assign new priority.\n"
            "Use review-oriented wording; do not conclude fraud, violation, or manipulation.\n"
            "For each case, include summary, narrative, cited_rules, review_focus, "
            "suggested_audit_actions, evidence_limitations, and optional "
            "phase2_family_summary.\n\n"
            f"{json.dumps(payloads, ensure_ascii=False, default=str)}"
        )
        return [
            {"role": "system", "content": phase3_fact_grounding_system_prompt()},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _validate_outputs(
        narratives: list[CaseNarrative],
        payloads: list[dict[str, Any]],
    ) -> list[CaseNarrative]:
        allowed_by_case = {
            str(payload.get("case_id")): _allowed_rule_ids(payload)
            for payload in payloads
            if payload.get("case_id")
        }
        validated: list[CaseNarrative] = []
        for narrative in narratives:
            allowed_rules = allowed_by_case.get(narrative.case_id)
            if allowed_rules is None:
                logger.warning(
                    "Dropping unexpected PHASE3 case narrative: %s",
                    narrative.case_id,
                )
                continue
            cited_rules = [rule for rule in narrative.cited_rules if rule in allowed_rules]
            if len(cited_rules) != len(narrative.cited_rules):
                logger.warning(
                    "Removed unsupported PHASE3 cited rules for case=%s",
                    narrative.case_id,
                )
            validated.append(narrative.model_copy(update={"cited_rules": cited_rules}))
        return validated


def _allowed_rule_ids(payload: dict[str, Any]) -> set[str]:
    allowed = {str(rule) for rule in payload.get("top_rule_ids", []) if rule}
    for doc in payload.get("top_documents", []):
        line_context = doc.get("line_context") or {}
        allowed.update(str(rule) for rule in line_context.get("matched_rules", []) if rule)
    return allowed
