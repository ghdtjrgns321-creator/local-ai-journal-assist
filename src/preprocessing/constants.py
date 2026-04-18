"""Preprocessing constants shared across training paths."""

from __future__ import annotations

LABEL_COLUMNS = frozenset({
    "is_fraud",
    "fraud_type",
    "is_anomaly",
    "anomaly_type",
    "sod_violation",
    "sod_conflict_type",
    "label",
    "target",
})

DEFAULT_GROUND_TRUTH_LABEL_COLUMNS = (
    "is_fraud",
    "is_anomaly",
)
