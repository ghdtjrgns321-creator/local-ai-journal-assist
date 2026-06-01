"""PHASE1 selected-case review memo generation.

This module is intentionally narrower than ``review_narrator``: it accepts one
PHASE1 case drilldown payload only and permits citations to PHASE1 rule hits or
case rows. PHASE2 overlays and ML feature evidence are not part of this input
contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.llm.api_client import ChatClient, get_chat_client

logger = logging.getLogger(__name__)

EvidenceType = Literal["rule_hit", "row"]
ActionType = Literal[
    "request_evidence",
    "account_analysis",
    "interview",
    "further_test",
    "data_quality_check",
]

SYSTEM_PROMPT = (
    "당신은 한국 감사인을 보조하는 PHASE1 case review memo assistant다. "
    "입력으로 제공된 단일 PHASE1 case의 rule hit, 문서 메타, row context만 사용해 "
    "감사인 검토 메모 초안을 JSON으로 작성한다. PHASE2, ML score, ml_feature, "
    "통합 priority, 새로운 탐지 가설은 절대 언급하지 않는다. fraud/violation/"
    "manipulation 확정 표현을 쓰지 말고 검토 후보, 확인 필요, 분석 제한으로 표현한다."
)


class Phase1BriefEvidence(BaseModel):
    """Evidence citation limited to PHASE1 rule hits or rows."""

    type: EvidenceType
    rule_id: str = ""
    document_id: str = ""
    line_no: int = 0


class Phase1BriefReasoning(BaseModel):
    """One claim and its supporting evidence."""

    claim: str
    evidence: list[Phase1BriefEvidence] = Field(default_factory=list)


class Phase1BriefAction(BaseModel):
    """Suggested auditor follow-up action."""

    action_type: ActionType
    description: str


class Phase1CaseBrief(BaseModel):
    """LLM output for one PHASE1 selected case."""

    summary: str
    reasoning: list[Phase1BriefReasoning] = Field(default_factory=list)
    suggested_actions: list[Phase1BriefAction] = Field(default_factory=list)
    limitations: str


@dataclass(frozen=True)
class Phase1CaseBriefResult:
    """Generated brief plus citation validation metadata."""

    brief: Phase1CaseBrief
    invalid_citations: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.invalid_citations


def build_phase1_case_brief_payload(drilldown: dict[str, Any]) -> dict[str, Any]:
    """Build the PHASE1-only payload sent to the LLM."""
    case = dict(drilldown.get("case") or {})
    documents = [dict(doc) for doc in list(drilldown.get("documents") or [])[:20]]
    raw_rule_hits = [dict(hit) for hit in list(drilldown.get("raw_rule_hits") or [])[:50]]
    return {
        "case_id": str(case.get("case_id") or ""),
        "selected_phase1_case": {
            "topic_label": case.get("topic_label") or case.get("primary_topic_label") or "",
            "priority_band": case.get("priority_band") or "",
            "risk_narrative": case.get("risk_narrative") or "",
            "representative_explanation": case.get("representative_explanation") or "",
            "review_focus": list(case.get("review_focus") or []),
            "recommended_audit_actions": list(case.get("recommended_audit_actions") or []),
        },
        "phase1_rule_evidence": raw_rule_hits,
        "documents": [_document_context(doc) for doc in documents],
    }


def build_phase1_case_brief_schema(rule_ids: set[str], document_ids: set[str]) -> dict[str, Any]:
    """Return JSON schema with case-local rule/document enums injected."""
    from copy import deepcopy

    schema = deepcopy(Phase1CaseBrief.model_json_schema())
    defs = schema.get("$defs") or schema.get("definitions") or {}
    evidence_schema = defs.get("Phase1BriefEvidence")
    if evidence_schema is None:
        return schema
    props = evidence_schema.get("properties", {})
    if "rule_id" in props:
        props["rule_id"]["enum"] = sorted({""} | set(rule_ids))
    if "document_id" in props:
        props["document_id"]["enum"] = sorted({""} | set(document_ids))
    return schema


def generate_phase1_case_brief(
    drilldown: dict[str, Any],
    *,
    reasoning_client: ChatClient | None = None,
    light_client: ChatClient | None = None,
) -> Phase1CaseBriefResult:
    """Generate and validate a PHASE1-only case brief."""
    payload = build_phase1_case_brief_payload(drilldown)
    rule_ids, document_ids = _known_ids(payload)
    schema = build_phase1_case_brief_schema(rule_ids, document_ids)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "다음 PHASE1 case evidence만 근거로 한국어 검토 메모 초안을 작성하라. "
                "reasoning.evidence.type은 rule_hit 또는 row만 허용된다.\n\n"
                f"{json.dumps(payload, ensure_ascii=False, default=str)}"
            ),
        },
    ]

    errors: list[str] = []
    clients: tuple[tuple[str, ChatClient | None], ...] = (
        ("reasoning", reasoning_client),
        ("light", light_client),
    )
    for tier, injected_client in clients:
        client = injected_client or get_chat_client(tier)  # type: ignore[arg-type]
        brief, error = _try_generate(client, messages, schema)
        if brief is not None:
            return validate_phase1_case_brief(brief, rule_ids, document_ids)
        errors.append(f"{tier}={error}")
    raise RuntimeError("; ".join(errors))


def validate_phase1_case_brief(
    brief: Phase1CaseBrief,
    known_rule_ids: set[str],
    known_document_ids: set[str],
) -> Phase1CaseBriefResult:
    """Validate citations and downgrade unsupported evidence through limitations."""
    invalid: list[str] = []
    for idx, item in enumerate(brief.reasoning):
        if not item.evidence:
            invalid.append(f"reasoning[{idx}].evidence is empty")
            continue
        for ev_idx, evidence in enumerate(item.evidence):
            reason = _invalid_evidence_reason(evidence, known_rule_ids, known_document_ids)
            if reason:
                invalid.append(f"reasoning[{idx}].evidence[{ev_idx}]: {reason}")
    if not invalid:
        return Phase1CaseBriefResult(brief=brief, invalid_citations=[])
    limitation = (
        brief.limitations.rstrip()
        + " 일부 근거 인용은 case evidence와 맞지 않아 검토 신뢰도가 낮습니다."
    )
    return Phase1CaseBriefResult(
        brief=brief.model_copy(update={"limitations": limitation}),
        invalid_citations=invalid,
    )


def _try_generate(
    client: ChatClient,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
) -> tuple[Phase1CaseBrief | None, str | None]:
    try:
        raw = client.chat(messages, temperature=0.1, format=schema)
    except Exception as exc:  # noqa: BLE001 - external API exceptions are shown in UI
        logger.warning("PHASE1 case brief LLM call failed: %s", exc, exc_info=True)
        return None, f"{type(exc).__name__}: {exc}"
    try:
        return Phase1CaseBrief.model_validate_json(raw), None
    except (ValidationError, ValueError) as exc:
        logger.warning("PHASE1 case brief parse failed: %s", exc)
        return None, "ParseError"


def _known_ids(payload: dict[str, Any]) -> tuple[set[str], set[str]]:
    rule_ids: set[str] = set()
    for hit in payload.get("phase1_rule_evidence", []):
        rule_id = str(hit.get("rule_id") or "").strip()
        if rule_id:
            rule_ids.add(rule_id)
    document_ids: set[str] = set()
    for doc in payload.get("documents", []):
        doc_id = str(doc.get("document_id") or "").strip()
        if doc_id:
            document_ids.add(doc_id)
        rule_ids.update(str(rule) for rule in doc.get("matched_rules", []) if rule)
    return rule_ids, document_ids


def _invalid_evidence_reason(
    evidence: Phase1BriefEvidence,
    known_rule_ids: set[str],
    known_document_ids: set[str],
) -> str | None:
    if evidence.type == "rule_hit":
        if not evidence.rule_id:
            return "rule_hit evidence with empty rule_id"
        if evidence.rule_id not in known_rule_ids:
            return f"unknown rule_id: {evidence.rule_id}"
        return None
    if not evidence.document_id:
        return "row evidence with empty document_id"
    if evidence.document_id not in known_document_ids:
        return f"unknown document_id: {evidence.document_id}"
    return None


def _document_context(document: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "document_id",
        "posting_date",
        "created_by",
        "approved_by",
        "business_process",
        "gl_account",
        "counterparty",
        "amount",
        "matched_rules",
        "evidence_tags",
    )
    return {key: document.get(key) for key in keep if key in document}
