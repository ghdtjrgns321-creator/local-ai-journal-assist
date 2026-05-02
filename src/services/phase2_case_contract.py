"""PHASE1 case contracts for PHASE2 precision overlays and PHASE3 prompts."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from math import log2
from typing import Any

import pandas as pd

from src.models.phase1_case import CaseGroupResult, Phase1CaseResult

PROVENANCE_ONLY_FIELDS = (
    "phase1_case_id",
    "primary_theme",
    "secondary_tags",
    "top_rule_ids",
    "raw_rule_hits",
    "representative_explanation",
    "review_focus",
    "risk_narrative",
    "recommended_audit_actions",
    "rule_evidence_summary",
    "phase1_case_priority",
    "phase1_base_priority",
    "phase1_priority_adjustments",
)

PHASE2_CASE_FEATURE_COLUMNS = (
    "rule_diversity_count",
    "evidence_type_count",
    "theme_entropy",
    "cross_process_flag",
    "cross_user_flag",
    "cross_counterparty_flag",
    "repeat_months",
    "repeat_score",
    "document_count",
    "row_count",
    "total_amount",
    "amount_score",
    "control_score",
    "logic_score",
    "timing_score",
    "behavior_score",
    "has_control_failure",
    "has_high_materiality",
    "has_repeat_pattern",
)

_FORBIDDEN_FEATURE_COLUMNS = frozenset(PROVENANCE_ONLY_FIELDS)
_ALLOWED_FEATURE_DTYPES = frozenset("biufc?")


@dataclass(frozen=True)
class Phase2CaseOverlay:
    """Case-level PHASE2 overlay that preserves the original PHASE1 priority."""

    phase1_case_id: str
    phase2_family_scores: dict[str, float] = field(default_factory=dict)
    phase2_adjusted_priority: float | None = None
    precision_adjustment_reason: str = "phase2_not_applied"
    detector_statuses: list[dict[str, Any]] = field(default_factory=list)
    phase2_inference_contract: dict[str, Any] | None = None
    phase2_training_report_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_phase2_case_feature_frame(phase1: Phase1CaseResult) -> pd.DataFrame:
    """Return ML-safe case features without direct rule/theme identifier leakage."""
    rows = [_case_feature_row(case) for case in phase1.cases]
    if not rows:
        return enforce_phase2_case_feature_firewall(
            pd.DataFrame(columns=PHASE2_CASE_FEATURE_COLUMNS)
        )
    frame = pd.DataFrame(rows)
    frame = frame.set_index("phase1_case_id", drop=True)
    frame.index.name = "phase1_case_id"
    return enforce_phase2_case_feature_firewall(frame)


def enforce_phase2_case_feature_firewall(df: pd.DataFrame) -> pd.DataFrame:
    """Return PHASE2 case ML features after enforcing the allowlist contract."""
    forbidden = sorted(set(df.columns) & _FORBIDDEN_FEATURE_COLUMNS)
    if forbidden:
        raise ValueError(
            "PHASE2 case feature firewall blocked provenance columns: "
            + ", ".join(forbidden)
        )

    frame = df.reindex(columns=PHASE2_CASE_FEATURE_COLUMNS).copy()
    invalid_types = [
        col
        for col in frame.columns
        if not frame.empty and frame[col].dtype.kind not in _ALLOWED_FEATURE_DTYPES
    ]
    if invalid_types:
        raise TypeError(
            "PHASE2 case feature firewall allows only numeric/boolean features: "
            + ", ".join(invalid_types)
        )
    return frame


def build_phase2_case_provenance(phase1: Phase1CaseResult) -> list[dict[str, Any]]:
    """Return display/debug provenance that must not be used as ML features."""
    return [_case_provenance_row(case) for case in phase1.cases]


def build_phase2_case_overlays(
    phase1: Phase1CaseResult | None,
    *,
    family_scores_by_case: dict[str, dict[str, float]] | None = None,
    detector_statuses: list[dict[str, Any]] | None = None,
    phase2_inference_contract: dict[str, Any] | None = None,
    phase2_training_report_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build neutral overlays keyed by PHASE1 case id.

    This function intentionally does not overwrite PHASE1 `priority_score`.
    Callers may provide family scores later; until then the overlay records that
    PHASE2 case scoring has not been applied.
    """
    if phase1 is None:
        return []

    family_scores_by_case = family_scores_by_case or {}
    detector_statuses = detector_statuses or []
    overlays: list[dict[str, Any]] = []
    for case in phase1.cases:
        family_scores = family_scores_by_case.get(case.case_id, {})
        adjusted = _adjusted_priority(case.priority_score, family_scores)
        reason = (
            "family_score_overlay"
            if family_scores
            else "phase2_not_applied"
        )
        overlays.append(
            Phase2CaseOverlay(
                phase1_case_id=case.case_id,
                phase2_family_scores=family_scores,
                phase2_adjusted_priority=adjusted,
                precision_adjustment_reason=reason,
                detector_statuses=detector_statuses,
                phase2_inference_contract=phase2_inference_contract,
                phase2_training_report_id=phase2_training_report_id,
            ).to_dict()
        )
    return overlays


def _case_feature_row(case: CaseGroupResult) -> dict[str, Any]:
    evidence_counter = Counter(hit.evidence_type for hit in case.raw_rule_hits)
    business_processes = {
        str(doc.business_process).strip()
        for doc in case.documents
        if doc.business_process
    }
    users = {str(doc.created_by).strip() for doc in case.documents if doc.created_by}
    counterparties = {
        str(doc.counterparty).strip()
        for doc in case.documents
        if doc.counterparty
    }
    return {
        "phase1_case_id": case.case_id,
        "rule_diversity_count": len({hit.rule_id for hit in case.raw_rule_hits}),
        "evidence_type_count": len(set(case.evidence_types)),
        "theme_entropy": _entropy(evidence_counter),
        "cross_process_flag": len(business_processes) > 1,
        "cross_user_flag": len(users) > 1,
        "cross_counterparty_flag": len(counterparties) > 1,
        "repeat_months": int(case.repeat_months),
        "repeat_score": float(case.repeat_score),
        "document_count": int(case.document_count),
        "row_count": int(case.row_count),
        "total_amount": float(case.total_amount),
        "amount_score": float(case.amount_score),
        "control_score": float(case.control_score),
        "logic_score": float(case.logic_score),
        "timing_score": float(case.timing_score),
        "behavior_score": float(case.behavior_score),
        "has_control_failure": bool(case.has_control_failure),
        "has_high_materiality": bool(case.has_high_materiality),
        "has_repeat_pattern": bool(case.has_repeat_pattern),
    }


def _case_provenance_row(case: CaseGroupResult) -> dict[str, Any]:
    return {
        "phase1_case_id": case.case_id,
        "primary_theme": case.primary_theme,
        "secondary_tags": list(case.secondary_tags),
        "top_rule_ids": _top_rule_ids(case),
        "raw_rule_hits": [hit.model_dump() for hit in case.raw_rule_hits],
        "representative_explanation": case.representative_explanation,
        "review_focus": list(case.review_focus),
        "risk_narrative": case.risk_narrative,
        "recommended_audit_actions": list(case.recommended_audit_actions),
        "rule_evidence_summary": list(case.rule_evidence_summary),
        "phase1_case_priority": case.priority_score,
        "phase1_base_priority": case.base_priority_score,
        "phase1_priority_adjustments": {
            "topside_bonus": case.topside_bonus,
            "batch_combo_bonus": case.batch_combo_bonus,
            "weak_evidence_bonus": case.weak_evidence_bonus,
            "l301_priority_bonus": case.l301_priority_bonus,
            "reasons": list(case.priority_adjustment_reasons),
        },
    }


def _top_rule_ids(case: CaseGroupResult, limit: int = 5) -> list[str]:
    counts = Counter(hit.rule_id for hit in case.raw_rule_hits)
    return [rule_id for rule_id, _ in counts.most_common(limit)]


def _entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return float(
        -sum((count / total) * log2(count / total) for count in counter.values())
    )


def _adjusted_priority(base_priority: float, family_scores: dict[str, float]) -> float | None:
    if not family_scores:
        return None
    mean_score = sum(float(score) for score in family_scores.values()) / len(family_scores)
    return max(0.0, min((float(base_priority) * 0.7) + (mean_score * 0.3), 1.0))


def _feature_columns() -> list[str]:
    return list(PHASE2_CASE_FEATURE_COLUMNS)
