"""Typed models for the Phase 2 training pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Phase2TrainingStatus(StrEnum):
    """Execution status for Phase 2 AutoML steps and trials."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Phase2ColumnDecision:
    """Preprocessing decision for one source column before matrix building."""

    column: str
    role: str
    action: str
    reason_code: str
    dtype_group: str | None = None
    missing_rate: float | None = None
    unique_count: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Phase2PreprocessingPlan:
    """Serializable Phase 2 preprocessing plan metadata."""

    row_count: int
    profile_sampled: bool
    profile_sample_size: int | None
    duplicate_rows: int
    duplicate_rows_estimated: bool
    duplicate_sample_size: int | None
    duplicate_rate_estimate: float | None
    decisions: list[Phase2ColumnDecision] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decisions"] = [decision.to_dict() for decision in self.decisions]
        return payload


@dataclass
class Phase2LabelSummary:
    """Label readiness summary captured before candidate training starts."""

    strategy: str
    label_source: str
    gate_status: str
    gate_reason: str | None
    is_supervised_eligible: bool
    positive_count: int
    positive_rate: float
    gate_decision: str = "unknown"

    def __post_init__(self) -> None:
        if self.gate_decision == "unknown":
            if self.gate_status == "eligible":
                self.gate_decision = "eligible"
            elif self.gate_status == "blocked":
                self.gate_decision = "hard_fail"
            elif self.gate_status == "fallback_to_unsupervised":
                self.gate_decision = "low_signal_fallback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Phase2TrialResult:
    """Single training/evaluation attempt for one model family and variant."""

    model_family: str
    variant: str
    status: Phase2TrainingStatus
    metric_name: str = "f1_macro"
    metric_value: float | None = None
    elapsed_sec: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    gate_reason: str | None = None
    artifact_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    feature_quality_profile: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class Phase2PromotedModel:
    """Promoted best model metadata for inference-time registry usage."""

    model_name: str
    source_trial_variant: str
    metric_name: str
    metric_value: float
    registry_version: int | None = None
    registry_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Phase2TrainingReport:
    """Serializable summary returned by the future Phase 2 training service."""

    report_id: str
    company_id: str | None
    engagement_id: str | None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    status: Phase2TrainingStatus = Phase2TrainingStatus.PENDING
    label_summary: Phase2LabelSummary | None = None
    supervised_gate: dict[str, Any] = field(default_factory=dict)
    leaderboard: list[Phase2TrialResult] = field(default_factory=list)
    promoted_models: list[Phase2PromotedModel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "company_id": self.company_id,
            "engagement_id": self.engagement_id,
            "created_at": self.created_at,
            "status": self.status.value,
            "label_summary": (None if self.label_summary is None else self.label_summary.to_dict()),
            "supervised_gate": (
                dict(self.supervised_gate)
                if self.supervised_gate
                else _supervised_gate_from_label_summary(self.label_summary)
            ),
            "leaderboard": [trial.to_dict() for trial in self.leaderboard],
            "promoted_models": [model.to_dict() for model in self.promoted_models],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


def _supervised_gate_from_label_summary(
    label_summary: Phase2LabelSummary | None,
) -> dict[str, Any]:
    if label_summary is None:
        return {
            "decision": "unavailable",
            "reason": "missing_label_summary",
            "label_source": "unknown",
            "positive_count": 0,
            "positive_rate": 0.0,
            "thresholds": {
                "min_positive_count": 50,
                "min_positive_rate": 0.01,
            },
            "eligible": False,
        }
    return {
        "decision": label_summary.gate_decision,
        "reason": label_summary.gate_reason,
        "label_source": label_summary.label_source,
        "positive_count": label_summary.positive_count,
        "positive_rate": label_summary.positive_rate,
        "thresholds": {
            "min_positive_count": 50,
            "min_positive_rate": 0.01,
        },
        "eligible": label_summary.is_supervised_eligible,
    }
