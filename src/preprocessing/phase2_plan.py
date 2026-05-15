"""Phase 2 preprocessing decision plan.

This module only records column decisions. Matrix transformation stays in the
training pipeline and is intentionally not implemented here.
"""

from __future__ import annotations

import re
from collections import Counter

from src.eda.models import ColumnProfile, EDAProfile
from src.preprocessing.constants import LABEL_COLUMNS
from src.services.phase2_training_models import (
    Phase2ColumnDecision,
    Phase2PreprocessingPlan,
)

_ID_NAMES = {"document_id", "doc_id", "row_id", "id", "transaction_id", "journal_id"}
_LOW_CARD_DOMAIN_COLUMNS = {"user_persona"}
_HIGH_MISSING_THRESHOLD = 0.90

_LEAKAGE_PATTERNS = (
    ("label", "leakage_label"),
    ("target", "leakage_label"),
    ("fraud", "leakage_label"),
    ("anomaly", "leakage_label"),
    ("risk", "leakage_risk"),
    ("rule", "leakage_rule"),
    ("score", "leakage_score"),
    ("model", "leakage_model"),
    ("prediction", "leakage_model"),
    ("probability", "leakage_model"),
    ("export", "leakage_export"),
    ("dashboard", "leakage_dashboard"),
)


def build_phase2_preprocessing_plan(
    profile: EDAProfile,
    *,
    high_card_threshold: int = 50,
) -> Phase2PreprocessingPlan:
    """Build a serializable Phase 2 column decision plan from capped EDA."""
    decisions = [
        _decide_column(name, column, high_card_threshold=high_card_threshold)
        for name, column in profile.columns.items()
    ]
    reason_counts = Counter(decision.reason_code for decision in decisions)
    action_counts = Counter(decision.action for decision in decisions)
    return Phase2PreprocessingPlan(
        row_count=profile.total_rows,
        profile_sampled=profile.sampled,
        profile_sample_size=profile.sample_size,
        duplicate_rows=profile.duplicate_rows,
        duplicate_rows_estimated=profile.duplicate_rows_estimated,
        duplicate_sample_size=profile.duplicate_sample_size,
        duplicate_rate_estimate=profile.duplicate_rate_estimate,
        decisions=decisions,
        metadata={
            "decision_count": len(decisions),
            "action_counts": dict(sorted(action_counts.items())),
            "reason_code_counts": dict(sorted(reason_counts.items())),
        },
    )


def _decide_column(
    name: str,
    column: ColumnProfile,
    *,
    high_card_threshold: int,
) -> Phase2ColumnDecision:
    normalized_name = _normalize_name(name)
    leakage_reason = _leakage_reason(normalized_name)

    if normalized_name in LABEL_COLUMNS:
        return _decision(name, column, "label", "exclude", "leakage_label")
    if leakage_reason is not None:
        return _decision(name, column, "leakage", "exclude", leakage_reason)
    if normalized_name in _ID_NAMES or normalized_name.endswith("_id"):
        return _decision(name, column, "identifier", "exclude", "identifier")
    if column.dtype_group == "datetime":
        return _decision(name, column, "datetime", "exclude", "datetime_raw")
    if column.missing_rate >= _HIGH_MISSING_THRESHOLD:
        return _decision(name, column, "feature", "exclude", "high_missing")
    if name in _LOW_CARD_DOMAIN_COLUMNS:
        return _decision(name, column, "categorical_low", "include", "domain_low_card")
    if column.dtype_group == "boolean":
        return _decision(name, column, "boolean", "include", "boolean")
    if column.dtype_group == "numeric":
        return _decision(name, column, "numeric", "include", "numeric")
    if column.dtype_group == "categorical":
        if column.unique_count >= high_card_threshold:
            return _decision(
                name,
                column,
                "categorical_high",
                "include",
                "high_cardinality",
            )
        return _decision(name, column, "categorical_low", "include", "low_cardinality")
    return _decision(name, column, "feature", "include", "dtype_fallback")


def _decision(
    name: str,
    column: ColumnProfile,
    role: str,
    action: str,
    reason_code: str,
) -> Phase2ColumnDecision:
    return Phase2ColumnDecision(
        column=name,
        role=role,
        action=action,
        reason_code=reason_code,
        dtype_group=column.dtype_group,
        missing_rate=column.missing_rate,
        unique_count=column.unique_count,
    )


def _leakage_reason(normalized_name: str) -> str | None:
    tokens = set(normalized_name.split("_"))
    for token, reason_code in _LEAKAGE_PATTERNS:
        if token in tokens or normalized_name.endswith(f"_{token}"):
            return reason_code
    return None


def _normalize_name(name: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")
