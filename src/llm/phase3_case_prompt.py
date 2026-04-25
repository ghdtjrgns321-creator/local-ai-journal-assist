"""Selected-case PHASE3 prompt payload builders."""

from __future__ import annotations

from typing import Any

from src.models.phase1_case import CaseDocumentRef, CaseGroupResult, Phase1CaseResult

_DEFAULT_TOP_N = 10
_MAX_TOP_N = 100
_DEFAULT_DOCUMENTS_PER_CASE = 10
_MAX_DOCUMENTS_PER_CASE = 20
_RELATED_ENTITY_THEMES = {
    "duplicate_or_outflow",
    "intercompany_structure",
    "statistical_outlier",
}


def build_phase3_selected_case_inputs(
    phase1: Phase1CaseResult,
    *,
    phase2_case_overlays: list[dict[str, Any]] | None = None,
    related_entity_risk_by_case: dict[str, dict[str, Any]] | None = None,
    top_n: int = _DEFAULT_TOP_N,
    max_documents_per_case: int = _DEFAULT_DOCUMENTS_PER_CASE,
) -> list[dict[str, Any]]:
    """Build PHASE3 inputs from selected PHASE1 cases and PHASE2 overlays."""
    overlays_by_case = {
        str(overlay.get("phase1_case_id")): overlay
        for overlay in (phase2_case_overlays or [])
        if overlay.get("phase1_case_id")
    }
    related_entity_risk_by_case = related_entity_risk_by_case or {}

    selected = _select_cases(phase1, top_n=top_n)
    document_limit = _bounded_limit(
        max_documents_per_case,
        default=_DEFAULT_DOCUMENTS_PER_CASE,
        hard_max=_MAX_DOCUMENTS_PER_CASE,
    )

    return [
        _case_input(
            case,
            overlay=overlays_by_case.get(case.case_id, {}),
            related_entity_risk=related_entity_risk_by_case.get(case.case_id),
            max_documents=document_limit,
        )
        for case in selected
    ]


def _select_cases(phase1: Phase1CaseResult, *, top_n: int) -> list[CaseGroupResult]:
    limit = _bounded_limit(top_n, default=_DEFAULT_TOP_N, hard_max=_MAX_TOP_N)
    if limit <= 0:
        return []
    selected = [case for case in phase1.cases if case.is_top_case]
    if not selected:
        selected = list(phase1.cases)
    selected = sorted(
        selected,
        key=lambda case: (
            float(case.priority_score),
            int(case.document_count),
            float(case.total_amount),
        ),
        reverse=True,
    )
    return selected[:limit]


def phase3_fact_grounding_system_prompt() -> str:
    """Return shared PHASE3 fact-grounding constraints."""
    return (
        "You are an audit narrative assistant. Use only the selected case input, "
        "PHASE1 evidence, PHASE2 overlay/provenance, and supplied related_entity_risk. "
        "Do not infer external accounting standards, legal conclusions, company "
        "policies, or facts that are not present in the input. Do not conclude fraud, "
        "violation, or manipulation. Use review-oriented wording such as 가능성, "
        "검토 필요, 확인 필요. If evidence is insufficient, explicitly say so."
    )


def _case_input(
    case: CaseGroupResult,
    *,
    overlay: dict[str, Any],
    related_entity_risk: dict[str, Any] | None,
    max_documents: int,
) -> dict[str, Any]:
    payload = {
        "case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "representative_explanation": case.representative_explanation,
        "review_focus": list(case.review_focus),
        "risk_narrative": case.risk_narrative,
        "recommended_audit_actions": list(case.recommended_audit_actions),
        "rule_evidence_summary": list(case.rule_evidence_summary),
        "evidence_tags": list(case.evidence_tags),
        "top_rule_ids": _top_rule_ids(case),
        "phase1_case_priority": case.priority_score,
        "phase2_family_scores": dict(overlay.get("phase2_family_scores") or {}),
        "phase2_inference_contract": overlay.get("phase2_inference_contract"),
        "phase2_training_report_id": overlay.get("phase2_training_report_id"),
        "top_documents": [
            {
                "document_id": doc.document_id,
                "line_context": {
                    "posting_date": doc.posting_date,
                    "created_by": doc.created_by,
                    "business_process": doc.business_process,
                    "gl_account": doc.gl_account,
                    "counterparty": doc.counterparty,
                    "amount": doc.amount,
                    "matched_rules": list(doc.matched_rules),
                    "evidence_tags": list(doc.evidence_tags),
                },
            }
            for doc in _rank_documents(case.documents)[:max_documents]
        ],
    }
    if _should_include_related_entity_risk(case, overlay, related_entity_risk):
        payload["related_entity_risk"] = related_entity_risk
    return payload


def _should_include_related_entity_risk(
    case: CaseGroupResult,
    overlay: dict[str, Any],
    related_entity_risk: dict[str, Any] | None,
) -> bool:
    if not related_entity_risk:
        return False
    if case.primary_theme in _RELATED_ENTITY_THEMES:
        return True
    if _RELATED_ENTITY_THEMES.intersection(set(case.secondary_tags)):
        return True
    if _has_graph_degree_context(related_entity_risk):
        return True
    scores = overlay.get("phase2_family_scores") or {}
    graph_score_keys = ("intercompany", "relational", "graph")
    return any(float(scores.get(key, 0.0) or 0.0) > 0 for key in graph_score_keys)


def _rank_documents(documents: list[CaseDocumentRef]) -> list[CaseDocumentRef]:
    by_id = {doc.document_id: doc for doc in documents}
    ranked_ids: list[str] = []

    for doc in sorted(documents, key=lambda item: abs(float(item.amount or 0.0)), reverse=True)[:3]:
        ranked_ids.append(doc.document_id)

    remaining = [doc for doc in documents if doc.document_id not in set(ranked_ids)]
    for doc in sorted(
        remaining,
        key=lambda item: (
            len(item.matched_rules),
            len(item.evidence_tags),
            abs(float(item.amount or 0.0)),
        ),
        reverse=True,
    )[:2]:
        ranked_ids.append(doc.document_id)

    for doc in sorted(
        documents,
        key=lambda item: (
            len(item.matched_rules),
            len(item.evidence_tags),
            abs(float(item.amount or 0.0)),
        ),
        reverse=True,
    ):
        if doc.document_id not in set(ranked_ids):
            ranked_ids.append(doc.document_id)

    return [by_id[doc_id] for doc_id in ranked_ids]


def _has_graph_degree_context(related_entity_risk: dict[str, Any]) -> bool:
    degree_keys = (
        "degree",
        "graph_degree",
        "related_process_count",
        "process_count",
        "department_count",
        "distinct_department_count",
        "distinct_process_count",
    )
    return any(float(related_entity_risk.get(key, 0) or 0) > 1 for key in degree_keys)


def _bounded_limit(value: int, *, default: int, hard_max: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(0, min(limit, hard_max))


def _top_rule_ids(case: CaseGroupResult, limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for hit in case.raw_rule_hits:
        counts[hit.rule_id] = counts.get(hit.rule_id, 0) + 1
    return [
        rule_id
        for rule_id, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :limit
        ]
    ]
