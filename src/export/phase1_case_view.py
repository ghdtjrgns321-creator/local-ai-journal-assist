"""Projection helpers for Phase 1 case queues, summaries, and drill-down views."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from src.detection.phase1_case_builder import (
    _rule_actions,
    _rule_focus,
    _rule_label,
    load_phase1_case_result,
)
from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

if TYPE_CHECKING:
    from src.pipeline import PipelineResult

logger = logging.getLogger(__name__)

_LOW_SIGNAL_QUEUE_ID = "low_signal_candidate"
_LOW_SIGNAL_QUEUE_LABEL = "Low-signal 후보"
_LOW_SIGNAL_MAX_DOCS = 5_000
_LOW_SIGNAL_RELEVANT_RULES = {
    "L1-07",
    "L1-09",
    "L2-01",
    "L2-02",
    "L2-03",
    "L3-01",
    "L3-02",
    "L3-03",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-12",
    "L4-03",
}


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
            "queues": [],
        }

    queue_summaries = _queue_summaries(phase1)
    low_signal_summary = _low_signal_summary(pr, phase1)
    if low_signal_summary is not None:
        queue_summaries.append(low_signal_summary)
    return {
        "available": True,
        "schema_version": phase1.schema_version,
        "run_id": phase1.run_id,
        "case_count": len(phase1.cases),
        "macro_finding_count": int(phase1.metadata.get("macro_finding_count", 0) or 0),
        "macro_findings": list(phase1.metadata.get("macro_findings", []) or [])[:5],
        "top_theme_ids": [theme.theme_id for theme in phase1.theme_summaries[:3]],
        "top_theme_labels": [theme.theme_label for theme in phase1.theme_summaries[:3]],
        "queues": queue_summaries,
        "top_queue_ids": [queue["queue_id"] for queue in queue_summaries[:3]],
        "top_queue_labels": [queue["queue_label"] for queue in queue_summaries[:3]],
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
    queue_id: str | None = None,
    theme_id: str | None = None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Return queue rows for case list views."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []

    items = phase1.cases
    if queue_id == _LOW_SIGNAL_QUEUE_ID:
        items = _low_signal_rows(pr, phase1)
        if theme_id:
            items = []
        if top_n is not None:
            items = items[:top_n]
        return items

    if queue_id:
        queue = str(queue_id)
        items = [
            case
            for case in items
            if case.primary_queue == queue or queue in case.secondary_queues
        ]
    if theme_id:
        items = [case for case in items if case.primary_theme == theme_id]
    items = sorted(
        items,
        key=lambda case: (
            -int(case.exposure_rank or 1_000_000_000),
            case.priority_score,
            case.triage_rank_score,
            case.repeat_months,
            case.total_amount,
            case.rule_count,
        ),
        reverse=True,
    )
    if top_n is not None:
        items = items[:top_n]
    return [_case_row(case, phase1) for case in items]


def build_phase1_data_quality_gate(pr: PipelineResult) -> dict[str, Any]:
    """Return data-quality/contract issues as work items, not global Top-N risk cases."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "items": [], "cases": []}

    cases = [
        case
        for case in phase1.cases
        if case.primary_queue == "data_integrity"
        or case.data_integrity_score > 0
        or any(hit.evidence_type == "data_integrity_failure" for hit in case.raw_rule_hits)
    ]
    rule_items: dict[str, dict[str, Any]] = {}
    for case in cases:
        for hit in case.raw_rule_hits:
            if hit.evidence_type != "data_integrity_failure":
                continue
            item = rule_items.setdefault(
                hit.rule_id,
                {
                    "rule_id": hit.rule_id,
                    "rule_label": _rule_label(hit.rule_id),
                    "document_ids": set(),
                    "case_ids": set(),
                    "score_only_document_ids": set(),
                    "normal_score_only_document_ids": set(),
                    "high_case_ids": set(),
                    "medium_case_ids": set(),
                    "actions": [],
                    "review_focus": _rule_focus(hit.rule_id),
                    "strongest_signal": 0.0,
                },
            )
            item["document_ids"].add(hit.document_id)
            item["case_ids"].add(case.case_id)
            item["strongest_signal"] = max(
                item["strongest_signal"],
                float(hit.normalized_score or hit.score or 0.0),
            )
            if case.priority_band == "high":
                item["high_case_ids"].add(case.case_id)
            elif case.priority_band == "medium":
                item["medium_case_ids"].add(case.case_id)
            for action in _rule_actions(hit.rule_id):
                if action not in item["actions"]:
                    item["actions"].append(action)

    _add_data_quality_score_rows(pr, rule_items)

    items = []
    for item in rule_items.values():
        items.append(
            {
                "rule_id": item["rule_id"],
                "rule_label": item["rule_label"],
                "documents": len(item["document_ids"]),
                "cases": len(item["case_ids"]),
                "score_only_documents": len(item["score_only_document_ids"]),
                "normal_score_only_documents": len(item["normal_score_only_document_ids"]),
                "high_cases": len(item["high_case_ids"]),
                "medium_cases": len(item["medium_case_ids"]),
                "review_focus": item["review_focus"],
                "actions": item["actions"],
                "strongest_signal": item["strongest_signal"],
            }
        )
    items.sort(
        key=lambda row: (
            row["documents"],
            row["high_cases"],
            row["strongest_signal"],
            row["rule_id"],
        ),
        reverse=True,
    )
    return {
        "available": True,
        "items": items,
        "cases": [_case_row(case, phase1) for case in cases],
        "document_count": len(
            {doc for item in rule_items.values() for doc in item["document_ids"]}
        ),
        "case_count": len(cases),
    }


def build_phase1_audit_risk_queue(
    pr: PipelineResult,
    *,
    top_n: int | None = 10,
    queue_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the actual audit-risk Top-N, excluding data-quality gate items."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    excluded = {"data_integrity", _LOW_SIGNAL_QUEUE_ID}
    items = [
        case
        for case in phase1.cases
        if case.primary_queue not in excluded
        and case.primary_theme != "data_integrity_failure"
        and _case_signal_counts(case)["direct_risk"] > 0
    ]
    if queue_id:
        items = [
            case
            for case in items
            if case.primary_queue == queue_id or queue_id in case.secondary_queues
        ]
    items = sorted(
        items,
        key=lambda case: (
            _band_rank(case.priority_band),
            case.priority_score,
            _queue_tiebreaker(case, queue_id or case.primary_queue)["score"],
            case.triage_rank_score,
            case.total_amount,
            case.rule_count,
            -case.document_count,
        ),
        reverse=True,
    )
    if top_n is not None:
        items = items[:top_n]
    return [_case_row(case, phase1, tie_queue_id=queue_id) for case in items]


def build_phase1_audit_risk_by_queue(
    pr: PipelineResult,
    *,
    top_n_per_queue: int = 5,
) -> dict[str, Any]:
    """Return audit-risk candidates grouped by audit work queue."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "queues": []}

    queue_order = [
        "control_approval",
        "timing_close",
        "amount_statistical",
        "account_logic",
        "duplicate_outflow",
        "intercompany_cycle",
        "manipulation_candidate",
    ]
    queue_labels = _audit_queue_labels(phase1)
    excluded = {"data_integrity", _LOW_SIGNAL_QUEUE_ID}
    source_cases = [
        case
        for case in phase1.cases
        if case.primary_queue not in excluded
        and case.primary_theme != "data_integrity_failure"
        and _case_signal_counts(case)["direct_risk"] > 0
    ]

    queues = []
    for queue_id in queue_order:
        members = [
            case
            for case in source_cases
            if case.primary_queue == queue_id or queue_id in case.secondary_queues
        ]
        if not members:
            continue
        members = sorted(
            members,
            key=lambda case: (
                _band_rank(case.priority_band),
                case.priority_score,
                _queue_tiebreaker(case, queue_id)["score"],
                case.triage_rank_score,
                case.total_amount,
                case.rule_count,
                -case.document_count,
            ),
            reverse=True,
        )
        queues.append(
            {
                "queue_id": queue_id,
                "queue_label": queue_labels.get(queue_id, queue_id.replace("_", " ")),
                "total_cases": len(members),
                "items": [
                    _case_row(case, phase1, tie_queue_id=queue_id)
                    for case in members[:top_n_per_queue]
                ],
            }
        )
    return {"available": True, "queues": queues}


def build_phase1_review_candidate_summary(pr: PipelineResult) -> dict[str, Any]:
    """Return review/sidecar candidates as type counts, not a Top-N ranking."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {"available": False, "items": []}

    rows: dict[str, dict[str, Any]] = {}
    for case in phase1.cases:
        signal_counts = _case_signal_counts(case)
        is_review = (
            signal_counts["review_context"] > 0
            or signal_counts["macro_finding"] > 0
            or case.primary_queue == _LOW_SIGNAL_QUEUE_ID
            or case.priority_band == "low"
        )
        if not is_review or case.primary_queue == "data_integrity":
            continue
        key = case.primary_queue or case.primary_theme
        row = rows.setdefault(
            key,
            {
                "queue_id": key,
                "queue_label": case.primary_queue_label or key.replace("_", " "),
                "cases": 0,
                "documents": set(),
                "review_hits": 0,
                "direct_hits": 0,
                "high_cases": 0,
                "medium_cases": 0,
                "low_cases": 0,
                "sample_case_ids": [],
                "review_focus": [],
                "actions": [],
            },
        )
        row["cases"] += 1
        row["review_hits"] += signal_counts["review_context"] + signal_counts["macro_finding"]
        row["direct_hits"] += signal_counts["direct_risk"]
        for doc in case.documents:
            row["documents"].add(doc.document_id)
        if case.priority_band == "high":
            row["high_cases"] += 1
        elif case.priority_band == "medium":
            row["medium_cases"] += 1
        else:
            row["low_cases"] += 1
        if len(row["sample_case_ids"]) < 5:
            row["sample_case_ids"].append(case.case_id)
        for focus in case.review_focus:
            if focus not in row["review_focus"]:
                row["review_focus"].append(focus)
        for action in case.recommended_audit_actions:
            if action not in row["actions"]:
                row["actions"].append(action)

    items = []
    for row in rows.values():
        items.append(
            {
                "queue_id": row["queue_id"],
                "queue_label": row["queue_label"],
                "cases": row["cases"],
                "documents": len(row["documents"]),
                "review_hits": row["review_hits"],
                "direct_hits": row["direct_hits"],
                "high_cases": row["high_cases"],
                "medium_cases": row["medium_cases"],
                "low_cases": row["low_cases"],
                "sample_case_ids": row["sample_case_ids"],
                "review_focus": row["review_focus"][:5],
                "actions": row["actions"][:5],
            }
        )
    items.sort(key=lambda row: (row["cases"], row["documents"], row["review_hits"]), reverse=True)
    return {"available": True, "items": items}


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


def _add_data_quality_score_rows(
    pr: PipelineResult,
    rule_items: dict[str, dict[str, Any]],
) -> None:
    data = _feature_frame(pr)
    if data is None or data.empty or "document_id" not in data.columns:
        return
    rule_text = _rule_text_series(data)
    data_quality_rules = rule_text.map(lambda value: _rule_tokens(value) & _INTEGRITY_RULES)
    mask = data["document_id"].notna() & data_quality_rules.map(bool)
    if not bool(mask.any()):
        return

    score = _to_numeric(data["anomaly_score"]) if "anomaly_score" in data.columns else None
    risk = (
        data["risk_level"].fillna("").astype(str).str.lower()
        if "risk_level" in data.columns
        else None
    )
    rows = data.loc[mask, ["document_id"]].copy()
    rows["_rules"] = data_quality_rules[mask]
    rows["_score"] = score[mask] if score is not None else 0.0
    rows["_risk"] = risk[mask] if risk is not None else ""

    seen: set[tuple[str, str]] = set()
    for _, row in rows.iterrows():
        document_id = str(row["document_id"])
        if not document_id or document_id.lower() == "nan":
            continue
        for rule_id in row["_rules"]:
            key = (rule_id, document_id)
            if key in seen:
                continue
            seen.add(key)
            item = rule_items.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "rule_label": _rule_label(rule_id),
                    "document_ids": set(),
                    "case_ids": set(),
                    "score_only_document_ids": set(),
                    "normal_score_only_document_ids": set(),
                    "high_case_ids": set(),
                    "medium_case_ids": set(),
                    "actions": list(_rule_actions(rule_id)),
                    "review_focus": _rule_focus(rule_id),
                    "strongest_signal": 0.0,
                },
            )
            in_case = document_id in item["document_ids"]
            item["document_ids"].add(document_id)
            item["strongest_signal"] = max(
                item["strongest_signal"],
                float(row["_score"] or 0.0),
            )
            if not in_case:
                item["score_only_document_ids"].add(document_id)
                if str(row["_risk"]).lower() == "normal":
                    item["normal_score_only_document_ids"].add(document_id)
            for action in _rule_actions(rule_id):
                if action not in item["actions"]:
                    item["actions"].append(action)


def build_phase1_case_drilldown(pr: PipelineResult, case_id: str) -> dict[str, Any] | None:
    """Return a drill-down payload for a single case."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return None

    case = next((item for item in phase1.cases if item.case_id == case_id), None)
    if case is None:
        if str(case_id).startswith(f"{_LOW_SIGNAL_QUEUE_ID}:"):
            return _low_signal_drilldown(pr, phase1, case_id)
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


def _case_row(
    case: CaseGroupResult,
    phase1: Phase1CaseResult,
    *,
    tie_queue_id: str | None = None,
) -> dict[str, Any]:
    signal_counts = _case_signal_counts(case)
    tie = _queue_tiebreaker(case, tie_queue_id or case.primary_queue)
    return {
        "case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "primary_theme_label": _theme_label(phase1, case.primary_theme),
        "primary_queue": case.primary_queue,
        "primary_queue_label": case.primary_queue_label,
        "secondary_queues": list(case.secondary_queues),
        "secondary_queue_labels": list(case.secondary_queue_labels),
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
        "triage_rank_score": case.triage_rank_score,
        "triage_rank_reasons": list(case.triage_rank_reasons),
        "queue_tiebreaker_score": tie["score"],
        "queue_tiebreaker_reasons": tie["reasons"],
        "queue_tiebreaker_queue": tie["queue_id"],
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


def _low_signal_summary(pr: PipelineResult, phase1: Phase1CaseResult) -> dict[str, Any] | None:
    rows = _low_signal_rows(pr, phase1, top_n=None)
    if not rows:
        return None
    return {
        "queue_id": _LOW_SIGNAL_QUEUE_ID,
        "queue_label": _LOW_SIGNAL_QUEUE_LABEL,
        "case_count": len(rows),
        "high_count": 0,
        "medium_count": 0,
        "low_count": len(rows),
        "total_amount": sum(float(row.get("total_amount") or 0.0) for row in rows),
        "top_case_ids": [row["case_id"] for row in rows[:10]],
    }


def _low_signal_rows(
    pr: PipelineResult,
    phase1: Phase1CaseResult,
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    data = _feature_frame(pr)
    if data is None or data.empty:
        return []
    cache_key = (id(data), phase1.run_id, _LOW_SIGNAL_MAX_DOCS)
    cache = getattr(pr, "_phase1_low_signal_projection_cache", None)
    if isinstance(cache, dict) and cache.get("key") == cache_key:
        rows = list(cache.get("rows", []))
        return rows[:top_n] if top_n is not None else rows

    required = {"document_id", "risk_level", "anomaly_score"}
    if not required.issubset(data.columns):
        return []

    docs_in_cases = _case_document_ids(phase1)
    doc_ids = data["document_id"].fillna("").astype(str).str.strip()
    score = _to_numeric(data["anomaly_score"])
    risk = data["risk_level"].astype(str).str.lower()
    rule_text = _rule_text_series(data)
    relevant_rules = rule_text.map(_relevant_rule_tokens)
    mask = (
        doc_ids.ne("")
        & ~doc_ids.isin(docs_in_cases)
        & risk.eq("normal")
        & score.gt(0)
        & relevant_rules.map(bool)
    )
    if not bool(mask.any()):
        return []

    rows = data.loc[mask].copy()
    rows["_document_id"] = doc_ids[mask]
    rows["_anomaly_score"] = score[mask]
    rows["_relevant_rules"] = relevant_rules[mask]
    rows["_line_amount"] = _amount_series(rows)

    grouped_scores = (
        rows.groupby("_document_id", sort=False)
        .agg(
            priority_score=("_anomaly_score", "max"),
            row_count=("_document_id", "size"),
            total_amount=("_line_amount", lambda values: float(values.abs().sum())),
        )
        .reset_index()
        .sort_values(
            ["priority_score", "row_count", "total_amount", "_document_id"],
            ascending=[False, False, False, False],
        )
    )
    candidate_docs = set(grouped_scores.head(_LOW_SIGNAL_MAX_DOCS)["_document_id"].astype(str))
    rows = rows[rows["_document_id"].isin(candidate_docs)]
    score_lookup = {
        str(row["_document_id"]): row
        for row in grouped_scores[grouped_scores["_document_id"].isin(candidate_docs)].to_dict(
            "records"
        )
    }

    grouped: dict[str, dict[str, Any]] = {}
    for _, row in rows.iterrows():
        document_id = str(row["_document_id"])
        score_row = score_lookup[document_id]
        item = grouped.setdefault(
            document_id,
            {
                "document_id": document_id,
                "row_count": 0,
                "priority_score": 0.0,
                "total_amount": 0.0,
                "rules": set(),
                "posting_dates": [],
                "created_by": "",
                "business_process": "",
                "gl_account": "",
                "counterparty": "",
            },
        )
        item["row_count"] += 1
        item["priority_score"] = float(score_row["priority_score"] or 0.0)
        item["total_amount"] = float(score_row["total_amount"] or 0.0)
        item["rules"].update(row["_relevant_rules"])
        if not item["created_by"] and "created_by" in rows.columns:
            item["created_by"] = str(row.get("created_by") or "")
        if not item["business_process"] and "business_process" in rows.columns:
            item["business_process"] = str(row.get("business_process") or "")
        if not item["gl_account"] and "gl_account" in rows.columns:
            item["gl_account"] = str(row.get("gl_account") or "")
        if not item["counterparty"] and "counterparty" in rows.columns:
            item["counterparty"] = str(row.get("counterparty") or "")
        if "posting_date" in rows.columns and row.get("posting_date") is not None:
            item["posting_dates"].append(row.get("posting_date"))

    projected = [_low_signal_case_row(item) for item in grouped.values()]
    projected.sort(
        key=lambda row: (
            row["priority_score"],
            row["rule_count"],
            row["row_count"],
            row["total_amount"],
            row["case_key"],
        ),
        reverse=True,
    )
    try:
        setattr(
            pr,
            "_phase1_low_signal_projection_cache",
            {"key": cache_key, "rows": projected},
        )
    except Exception:
        pass
    return projected[:top_n] if top_n is not None else projected


def _low_signal_case_row(item: dict[str, Any]) -> dict[str, Any]:
    rules = sorted(item["rules"])
    score = float(item["priority_score"] or 0.0)
    document_id = str(item["document_id"])
    return {
        "case_id": f"{_LOW_SIGNAL_QUEUE_ID}:{document_id}",
        "primary_theme": "low_signal_candidate",
        "primary_theme_label": _LOW_SIGNAL_QUEUE_LABEL,
        "primary_queue": _LOW_SIGNAL_QUEUE_ID,
        "primary_queue_label": _LOW_SIGNAL_QUEUE_LABEL,
        "secondary_queues": [],
        "secondary_queue_labels": [],
        "secondary_tags": ["normal_risk_low_signal"],
        "case_key": document_id,
        "case_key_parts": {"document_id": document_id},
        "priority_score": score,
        "base_priority_score": score,
        "topside_bonus": 0.0,
        "batch_combo_bonus": 0.0,
        "weak_evidence_bonus": 0.0,
        "l301_priority_bonus": 0.0,
        "priority_adjustment_reasons": [],
        "priority_band": "low",
        "triage_rank_score": min(score + min(len(rules), 5) * 0.03, 1.0),
        "triage_rank_reasons": [
            "risk_level=Normal",
            f"weak_signal_rules={len(rules)}",
            "not_mixed_into_main_queue",
        ],
        "exposure_rank": None,
        "theme_rank": None,
        "document_count": 1,
        "row_count": int(item["row_count"]),
        "rule_count": len(rules),
        "direct_risk_count": len([rule for rule in rules if rule not in _REVIEW_CONTEXT_RULES]),
        "review_context_count": len([rule for rule in rules if rule in _REVIEW_CONTEXT_RULES]),
        "integrity_blocker_count": 0,
        "macro_finding_count": 0,
        "case_type": _LOW_SIGNAL_QUEUE_LABEL,
        "main_reason": "Normal risk row with weak PHASE1 signal",
        "total_amount": float(item["total_amount"] or 0.0),
        "amount_score": 0.0,
        "control_score": 0.0,
        "duplicate_or_outflow_score": 0.0,
        "logic_score": 0.0,
        "data_integrity_score": 0.0,
        "intercompany_score": 0.0,
        "timing_score": 0.0,
        "behavior_score": 0.0,
        "repeat_months": 0,
        "representative_explanation": "Normal로 남아 본 queue에는 섞지 않는 약신호 후보입니다.",
        "review_focus": ["약신호 규칙 조합", "전표 단위 근거 확인"],
        "risk_narrative": (
            "위험등급은 Normal이지만 PHASE1 관련 규칙 또는 review 신호가 있어 "
            "별도 후보 queue에 표시됩니다."
        ),
        "recommended_audit_actions": ["필요 시 보조 queue에서 샘플 검토"],
        "rule_evidence_summary": [{"rule_id": rule, "count": 1} for rule in rules],
        "evidence_tags": rules,
        "has_control_failure": False,
        "has_high_materiality": False,
        "has_repeat_pattern": False,
    }


def _low_signal_drilldown(
    pr: PipelineResult,
    phase1: Phase1CaseResult,
    case_id: str,
) -> dict[str, Any] | None:
    rows = _low_signal_rows(pr, phase1, top_n=None)
    case = next((row for row in rows if row["case_id"] == case_id), None)
    if case is None:
        return None
    document_id = str(case["case_key"])
    return {
        "case": case,
        "documents": [
            {
                "document_id": document_id,
                "posting_date": None,
                "created_by": "",
                "business_process": "",
                "gl_account": "",
                "counterparty": "",
                "amount": case["total_amount"],
                "matched_rules": list(case["evidence_tags"]),
                "evidence_tags": list(case["evidence_tags"]),
            }
        ],
        "raw_rule_hits": [],
        "signal_sections": {
            "direct_risk": [],
            "review_context": [],
            "integrity_blocker": [],
            "macro_finding": [],
        },
    }


def _feature_frame(pr: PipelineResult) -> Any:
    featured = getattr(pr, "featured_data", None)
    if featured is not None:
        return featured
    return getattr(pr, "data", None)


def _case_document_ids(phase1: Phase1CaseResult) -> set[str]:
    docs: set[str] = set()
    for case in phase1.cases:
        for doc in case.documents:
            if doc.document_id:
                docs.add(str(doc.document_id))
        for hit in case.raw_rule_hits:
            if hit.document_id:
                docs.add(str(hit.document_id))
    return docs


def _rule_text_series(data: Any) -> Any:
    parts = []
    for column in ("flagged_rules", "review_rules"):
        if column in data.columns:
            parts.append(data[column].fillna("").astype(str))
    if not parts:
        return data["document_id"].fillna("").astype(str).map(lambda _: "")
    result = parts[0]
    for part in parts[1:]:
        result = result + "," + part
    return result


def _relevant_rule_tokens(value: Any) -> set[str]:
    return _rule_tokens(value) & _LOW_SIGNAL_RELEVANT_RULES


def _rule_tokens(value: Any) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[,|;]", str(value or ""))
        if token.strip() and token.strip().lower() != "nan"
    }


def _to_numeric(series: Any) -> Any:
    import pandas as pd

    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _amount_series(data: Any) -> Any:
    import pandas as pd

    if "line_amount" in data.columns:
        return pd.to_numeric(data["line_amount"], errors="coerce").fillna(0.0)
    debit = (
        pd.to_numeric(data["debit_amount"], errors="coerce").fillna(0.0)
        if "debit_amount" in data.columns
        else 0.0
    )
    credit = (
        pd.to_numeric(data["credit_amount"], errors="coerce").fillna(0.0)
        if "credit_amount" in data.columns
        else 0.0
    )
    return debit - credit


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


def _queue_summaries(phase1: Phase1CaseResult) -> list[dict[str, Any]]:
    by_queue: dict[str, dict[str, Any]] = {}
    for case in phase1.cases:
        queues = [case.primary_queue, *case.secondary_queues]
        for queue_id in queues:
            if not queue_id:
                continue
            row = by_queue.setdefault(
                queue_id,
                {
                    "queue_id": queue_id,
                    "queue_label": _queue_label(case, queue_id),
                    "case_count": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "total_amount": 0.0,
                    "top_case_ids": [],
                },
            )
            row["case_count"] += 1
            band = str(case.priority_band).lower()
            if band == "high":
                row["high_count"] += 1
            elif band == "medium":
                row["medium_count"] += 1
            else:
                row["low_count"] += 1
            row["total_amount"] += float(case.total_amount or 0.0)
            if len(row["top_case_ids"]) < 10:
                row["top_case_ids"].append(case.case_id)
    return sorted(
        by_queue.values(),
        key=lambda row: (
            row["queue_id"] != "manipulation_candidate",
            -int(row["high_count"]),
            -int(row["case_count"]),
            str(row["queue_label"]),
        ),
    )


def _queue_label(case: CaseGroupResult, queue_id: str) -> str:
    if queue_id == case.primary_queue and case.primary_queue_label:
        return case.primary_queue_label
    if queue_id in case.secondary_queues:
        index = case.secondary_queues.index(queue_id)
        if index < len(case.secondary_queue_labels):
            return case.secondary_queue_labels[index]
    return queue_id.replace("_", " ")


def _audit_queue_labels(phase1: Phase1CaseResult) -> dict[str, str]:
    labels: dict[str, str] = {}
    for case in phase1.cases:
        if case.primary_queue and case.primary_queue_label:
            labels.setdefault(case.primary_queue, case.primary_queue_label)
        for queue_id, label in zip(
            case.secondary_queues,
            case.secondary_queue_labels,
            strict=False,
        ):
            if queue_id and label:
                labels.setdefault(queue_id, label)
    return labels


def _band_rank(priority_band: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(priority_band).lower(), 0)


def _queue_tiebreaker(case: CaseGroupResult, queue_id: str | None) -> dict[str, Any]:
    queue = str(queue_id or case.primary_queue or "")
    rule_ids = {str(hit.rule_id) for hit in case.raw_rule_hits}
    signal_counts = _case_signal_counts(case)
    small_case_score = 1.0 / max(int(case.document_count or 1), 1)
    rule_score = min(float(case.rule_count or len(rule_ids)) / 8.0, 1.0)
    direct_score = min(float(signal_counts["direct_risk"]) / 12.0, 1.0)
    amount_score = max(
        float(case.amount_score or 0.0),
        1.0 if case.total_amount >= 100_000_000 else 0.0,
    )
    amount_score = min(amount_score, 1.0)
    overlap_score = min(
        float(len([queue for queue in [case.primary_queue, *case.secondary_queues] if queue]))
        / 7.0,
        1.0,
    )
    repeat_score = min(float(case.repeat_months or 0) / 3.0, 1.0)

    components: list[tuple[str, float, float]] = [
        ("direct risk evidence", direct_score, 0.15),
        ("material amount", amount_score, 0.15),
        ("small review set", small_case_score, 0.10),
        ("rule corroboration", rule_score, 0.10),
    ]
    if queue == "control_approval":
        components.extend(
            [
                ("control rule strength", min(float(case.control_score or 0.0), 1.0), 0.30),
                (
                    "L1 control rules",
                    _rule_presence(rule_ids, {"L1-04", "L1-05", "L1-06", "L1-07", "L1-09"}),
                    0.20,
                ),
            ]
        )
    elif queue == "timing_close":
        components.extend(
            [
                ("timing rule strength", min(float(case.timing_score or 0.0), 1.0), 0.30),
                (
                    "close/cutoff rules",
                    _rule_presence(rule_ids, {"L3-04", "L3-07", "L3-09", "L3-11"}),
                    0.15,
                ),
                ("repeat timing pattern", repeat_score, 0.05),
            ]
        )
    elif queue == "amount_statistical":
        components.extend(
            [
                ("amount/stat score", min(float(case.amount_score or 0.0), 1.0), 0.30),
                (
                    "statistical rules",
                    _rule_presence(
                        rule_ids,
                        {"L3-01", "L4-01", "L4-03", "L4-04", "L4-05", "L4-06"},
                    ),
                    0.20,
                ),
            ]
        )
    elif queue == "account_logic":
        components.extend(
            [
                ("account logic score", min(float(case.logic_score or 0.0), 1.0), 0.30),
                (
                    "logic/account rules",
                    _rule_presence(rule_ids, {"L2-05", "L3-02", "L3-05", "L3-06"}),
                    0.20,
                ),
            ]
        )
    elif queue == "duplicate_outflow":
        components.extend(
            [
                (
                    "duplicate/outflow score",
                    min(float(case.duplicate_or_outflow_score or 0.0), 1.0),
                    0.30,
                ),
                (
                    "duplicate/outflow rules",
                    _rule_presence(rule_ids, {"L2-02", "L2-03", "L2-04"}),
                    0.20,
                ),
            ]
        )
    elif queue == "intercompany_cycle":
        components.extend(
            [
                ("intercompany score", min(float(case.intercompany_score or 0.0), 1.0), 0.30),
                ("IC/cycle rules", _rule_presence(rule_ids, {"L3-03", "L3-12"}), 0.15),
                ("repeat IC pattern", repeat_score, 0.05),
            ]
        )
    elif queue == "manipulation_candidate":
        components.extend(
            [
                ("queue overlap", overlap_score, 0.25),
                ("small composite case", small_case_score, 0.15),
                ("corroborating rules", rule_score, 0.10),
            ]
        )
    else:
        components.extend(
            [
                ("queue overlap", overlap_score, 0.20),
                ("repeat pattern", repeat_score, 0.10),
            ]
        )

    total_weight = sum(weight for _, _, weight in components) or 1.0
    score = sum(value * weight for _, value, weight in components) / total_weight
    reasons = [
        label
        for label, value, _ in sorted(components, key=lambda item: item[1] * item[2], reverse=True)
        if value > 0
    ][:5]
    return {
        "queue_id": queue,
        "score": round(min(max(score, 0.0), 1.0), 4),
        "reasons": reasons,
    }


def _rule_presence(rule_ids: set[str], target_rules: set[str]) -> float:
    return min(len(rule_ids & target_rules) / max(len(target_rules), 1), 1.0)


_SIGNAL_TYPE_LABELS = {
    "direct_risk": "직접 위험",
    "review_context": "리뷰/맥락",
    "integrity_blocker": "정합성/탐지제약",
    "macro_finding": "계정/모집단",
}

_INTEGRITY_RULES = {"L1-01", "L1-02", "L1-03", "L1-08"}
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
