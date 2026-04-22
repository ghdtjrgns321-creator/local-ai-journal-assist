"""Projection helpers for Phase 1 case queues, summaries, and drill-down views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.detection.phase1_case_builder import load_phase1_case_result
from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)


def resolve_phase1_case_result(pr: "PipelineResult") -> Phase1CaseResult | None:
    """Return an in-memory case result or load it from the saved artifact path."""
    if getattr(pr, "phase1_case_result", None) is not None:
        return pr.phase1_case_result
    artifact_path = getattr(pr, "phase1_case_path", None)
    if not artifact_path:
        return None
    try:
        return load_phase1_case_result(artifact_path)
    except Exception:
        logger.warning("PHASE1 case artifact load failed: %s", artifact_path, exc_info=True)
        return None


def summarize_phase1_case_result(pr: "PipelineResult") -> dict[str, Any]:
    """Build a compact summary contract for UI/report overview surfaces."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {
            "available": False,
            "run_id": getattr(pr, "phase1_case_run_id", None),
            "case_count": int(getattr(pr, "phase1_case_count", 0) or 0),
            "top_theme_ids": list(getattr(pr, "phase1_top_theme_ids", []) or []),
            "top_theme_labels": [],
            "themes": [],
        }

    return {
        "available": True,
        "schema_version": phase1.schema_version,
        "run_id": phase1.run_id,
        "case_count": len(phase1.cases),
        "top_theme_ids": [theme.theme_id for theme in phase1.theme_summaries[:3]],
        "top_theme_labels": [theme.theme_label for theme in phase1.theme_summaries[:3]],
        "themes": [
            {
                "theme_id": theme.theme_id,
                "theme_label": theme.theme_label,
                "case_count": theme.case_count,
                "high_count": theme.high_count,
                "medium_count": theme.medium_count,
                "low_count": theme.low_count,
                "total_amount": theme.total_amount,
                "top_case_ids": list(theme.top_case_ids),
            }
            for theme in phase1.theme_summaries
        ],
    }


def build_phase1_case_queue(
    pr: "PipelineResult",
    *,
    theme_id: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return queue rows for case list views."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []

    items = phase1.cases
    if theme_id:
        items = [case for case in items if case.primary_theme == theme_id]
    if top_n is not None:
        items = items[:top_n]
    return [_case_row(case, phase1) for case in items]


def build_phase1_case_drilldown(pr: "PipelineResult", case_id: str) -> dict[str, Any] | None:
    """Return a drill-down payload for a single case."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return None

    case = next((item for item in phase1.cases if item.case_id == case_id), None)
    if case is None:
        return None

    return {
        "case": _case_row(case, phase1),
        "documents": [
            {
                "document_id": doc.document_id,
                "posting_date": doc.posting_date,
                "created_by": doc.created_by,
                "business_process": doc.business_process,
                "gl_account": doc.gl_account,
                "counterparty": doc.counterparty,
                "amount": doc.amount,
                "matched_rules": list(doc.matched_rules),
                "evidence_tags": list(doc.evidence_tags),
            }
            for doc in case.documents
        ],
        "raw_rule_hits": [
            {
                "rule_id": hit.rule_id,
                "severity": hit.severity,
                "document_id": hit.document_id,
                "row_index": hit.row_index,
                "record_id": hit.record_id,
                "score": hit.score,
                "detail": hit.detail,
                "evidence_type": hit.evidence_type,
            }
            for hit in case.raw_rule_hits
        ],
    }


def _case_row(case: CaseGroupResult, phase1: Phase1CaseResult) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "primary_theme_label": _theme_label(phase1, case.primary_theme),
        "secondary_tags": list(case.secondary_tags),
        "case_key": case.case_key,
        "case_key_parts": dict(case.case_key_parts),
        "priority_score": case.priority_score,
        "priority_band": case.priority_band,
        "exposure_rank": case.exposure_rank,
        "theme_rank": case.theme_rank,
        "document_count": case.document_count,
        "row_count": case.row_count,
        "rule_count": case.rule_count,
        "total_amount": case.total_amount,
        "repeat_months": case.repeat_months,
        "representative_explanation": case.representative_explanation,
        "evidence_tags": list(case.evidence_tags),
        "has_control_failure": case.has_control_failure,
        "has_high_materiality": case.has_high_materiality,
        "has_repeat_pattern": case.has_repeat_pattern,
    }


def _theme_label(phase1: Phase1CaseResult, theme_id: str) -> str:
    for theme in phase1.theme_summaries:
        if theme.theme_id == theme_id:
            return theme.theme_label
    return theme_id
