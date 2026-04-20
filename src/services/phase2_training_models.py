"""Typed models for the Phase 2 training pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
class Phase2LabelSummary:
    """Label readiness summary captured before candidate training starts."""

    strategy: str
    label_source: str
    gate_status: str
    gate_reason: str | None
    is_supervised_eligible: bool
    positive_count: int
    positive_rate: float

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
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    status: Phase2TrainingStatus = Phase2TrainingStatus.PENDING
    label_summary: Phase2LabelSummary | None = None
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
            "label_summary": (
                None if self.label_summary is None else self.label_summary.to_dict()
            ),
            "leaderboard": [trial.to_dict() for trial in self.leaderboard],
            "promoted_models": [model.to_dict() for model in self.promoted_models],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }
