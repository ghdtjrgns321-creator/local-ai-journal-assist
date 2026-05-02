"""Projection helpers for Phase 1 case queues, summaries, and drill-down views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.detection.phase1_case_builder import load_phase1_case_result
from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)


def resolve_phase1_case_result(pr: PipelineResult) -> Phase1CaseResult | None:
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


def summarize_phase1_case_result(pr: PipelineResult) -> dict[str, Any]:
    """Build a compact summary contract for UI/report overview surfaces."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {
            "available": False,
            "run_id": getattr(pr, "phase1_case_run_id", None),
            "case_count": int(getattr(pr, "phase1_case_count", 0) or 0),
            "macro_finding_count": int(getattr(pr, "phase1_macro_finding_count", 0) or 0),
            "macro_findings": [],
            "top_theme_ids": list(getattr(pr, "phase1_top_theme_ids", []) or []),
            "top_theme_labels": [],
            "themes": [],
        }

    return {
        "available": True,
        "schema_version": phase1.schema_version,
        "run_id": phase1.run_id,
        "case_count": len(phase1.cases),
        "macro_finding_count": int(phase1.metadata.get("macro_finding_count", 0) or 0),
        "macro_findings": list(phase1.metadata.get("macro_findings", []) or [])[:5],
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
    pr: PipelineResult,
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


def build_phase1_macro_finding_queue(
    pr: PipelineResult,
    *,
    rule_id: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return Account/Process Queue rows for macro findings such as L4-02."""

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []

    items = list(phase1.metadata.get("macro_findings", []) or [])
    if rule_id:
        rule = str(rule_id)
        items = [item for item in items if str(item.get("rule_id", "")) == rule]
    if top_n is not None:
        items = items[:top_n]
    return items


def build_phase1_case_drilldown(pr: PipelineResult, case_id: str) -> dict[str, Any] | None:
    """Return a drill-down payload for a single case."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return None

    case = next((item for item in phase1.cases if item.case_id == case_id), None)
    if case is None:
        return None

    raw_rule_hits = [_raw_hit_row(hit) for hit in case.raw_rule_hits]
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
        "raw_rule_hits": raw_rule_hits,
        "signal_sections": {
            signal_type: [row for row in raw_rule_hits if row["signal_type"] == signal_type]
            for signal_type in (
                "direct_risk",
                "review_context",
                "integrity_blocker",
                "macro_finding",
            )
        },
    }


def _case_row(case: CaseGroupResult, phase1: Phase1CaseResult) -> dict[str, Any]:
    signal_counts = _case_signal_counts(case)
    return {
        "case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "primary_theme_label": _theme_label(phase1, case.primary_theme),
        "secondary_tags": list(case.secondary_tags),
        "case_key": case.case_key,
        "case_key_parts": dict(case.case_key_parts),
        "priority_score": case.priority_score,
        "base_priority_score": case.base_priority_score,
        "topside_bonus": case.topside_bonus,
        "batch_combo_bonus": case.batch_combo_bonus,
        "weak_evidence_bonus": case.weak_evidence_bonus,
        "l301_priority_bonus": case.l301_priority_bonus,
        "priority_adjustment_reasons": list(case.priority_adjustment_reasons),
        "priority_band": case.priority_band,
        "exposure_rank": case.exposure_rank,
        "theme_rank": case.theme_rank,
        "document_count": case.document_count,
        "row_count": case.row_count,
        "rule_count": case.rule_count,
        "direct_risk_count": signal_counts["direct_risk"],
        "review_context_count": signal_counts["review_context"],
        "integrity_blocker_count": signal_counts["integrity_blocker"],
        "macro_finding_count": signal_counts["macro_finding"],
        "case_type": _case_type(case, signal_counts),
        "main_reason": _main_reason(case),
        "total_amount": case.total_amount,
        "amount_score": case.amount_score,
        "control_score": case.control_score,
        "duplicate_or_outflow_score": case.duplicate_or_outflow_score,
        "logic_score": case.logic_score,
        "data_integrity_score": case.data_integrity_score,
        "intercompany_score": case.intercompany_score,
        "timing_score": case.timing_score,
        "behavior_score": case.behavior_score,
        "repeat_months": case.repeat_months,
        "representative_explanation": case.representative_explanation,
        "review_focus": list(case.review_focus),
        "risk_narrative": case.risk_narrative,
        "recommended_audit_actions": list(case.recommended_audit_actions),
        "rule_evidence_summary": list(case.rule_evidence_summary),
        "evidence_tags": list(case.evidence_tags),
        "has_control_failure": case.has_control_failure,
        "has_high_materiality": case.has_high_materiality,
        "has_repeat_pattern": case.has_repeat_pattern,
    }


def _raw_hit_row(hit: Any) -> dict[str, Any]:
    signal_type = _signal_type(hit)
    return {
        "rule_id": hit.rule_id,
        "signal_type": signal_type,
        "signal_type_label": _SIGNAL_TYPE_LABELS[signal_type],
        "severity": hit.severity,
        "document_id": hit.document_id,
        "row_index": hit.row_index,
        "record_id": hit.record_id,
        "score": hit.score,
        "signal_strength": hit.signal_strength,
        "normalized_score": hit.normalized_score,
        "evidence_strength": hit.evidence_strength,
        "scoring_role": hit.scoring_role,
        "display_label": hit.display_label,
        "signal_status": hit.signal_status,
        "detail": hit.detail,
        "evidence_type": hit.evidence_type,
    }


_SIGNAL_TYPE_LABELS = {
    "direct_risk": "직접 위험",
    "review_context": "리뷰/맥락",
    "integrity_blocker": "정합성/탐지제약",
    "macro_finding": "계정/모집단",
}

_INTEGRITY_RULES = {"L1-01", "L1-02", "L1-08"}
_MACRO_RULES = {"L4-02", "D01", "D02", "GR01", "GR03"}
_REVIEW_CONTEXT_RULES = {"L3-03", "L3-05", "L3-06", "L3-08", "L3-12", "L4-06"}
_L302_DIRECT_BUCKETS = {"manual_control_bypass"}
_L304_DIRECT_BUCKETS = {"closing_amount_p90", "closing_amount_p95"}


def _case_signal_counts(case: CaseGroupResult) -> dict[str, int]:
    counts = {
        "direct_risk": 0,
        "review_context": 0,
        "integrity_blocker": 0,
        "macro_finding": 0,
    }
    for hit in case.raw_rule_hits:
        counts[_signal_type(hit)] += 1
    return counts


def _signal_type(hit: Any) -> str:
    rule_id = str(hit.rule_id)
    label = str(hit.display_label or "").strip().lower()
    scoring_role = str(hit.scoring_role or "").strip().lower()
    evidence_type = str(hit.evidence_type or "").strip().lower()
    signal_status = str(hit.signal_status or "").strip().lower()

    if rule_id in _MACRO_RULES or scoring_role == "macro_only":
        return "macro_finding"
    if rule_id in _INTEGRITY_RULES or evidence_type == "data_integrity_failure":
        return "integrity_blocker"
    if signal_status == "review_candidate":
        return "review_context"
    if scoring_role in {"booster", "combo_only"}:
        return "review_context"
    if rule_id in _REVIEW_CONTEXT_RULES:
        return "review_context"
    if rule_id == "L3-02" and label not in _L302_DIRECT_BUCKETS:
        return "review_context"
    if rule_id == "L3-04" and label and label not in _L304_DIRECT_BUCKETS:
        return "review_context"
    return "direct_risk"


def _case_type(case: CaseGroupResult, signal_counts: dict[str, int]) -> str:
    if signal_counts["direct_risk"] > 0:
        return "직접 위험 케이스"
    if signal_counts["integrity_blocker"] > 0:
        return "정합성/탐지제약 케이스"
    if signal_counts["macro_finding"] > 0:
        return "계정/모집단 분석 케이스"
    if signal_counts["review_context"] > 0:
        return "리뷰/맥락 케이스"
    return _theme_label_from_id(case.primary_theme)


def _main_reason(case: CaseGroupResult) -> str:
    if case.review_focus:
        return ", ".join(case.review_focus[:3])
    if case.risk_narrative:
        return case.risk_narrative
    return case.representative_explanation


def _theme_label_from_id(theme_id: str) -> str:
    return theme_id.replace("_", " ")


def _theme_label(phase1: Phase1CaseResult, theme_id: str) -> str:
    for theme in phase1.theme_summaries:
        if theme.theme_id == theme_id:
            return theme.theme_label
    return theme_id
