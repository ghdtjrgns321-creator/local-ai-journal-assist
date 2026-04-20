"""Common models for performance evaluation reports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RuleMetric:
    """Per-rule evaluation metric."""

    track_name: str
    rule_code: str
    action_layer: str = ""
    evaluation_status: str = "ok"
    evaluation_reason: str = ""
    label_docs: int = 0
    flagged_docs: int = 0
    tp_docs: int = 0
    fp_docs: int = 0
    fn_docs: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


@dataclass(slots=True)
class PhaseComparisonMetric:
    """Phase-scope comparison summary."""

    phase_scope: str
    flagged_docs: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


@dataclass(slots=True)
class PerformanceReport:
    """Unified report shape for ground-truth and operational evaluation."""

    report_id: str
    upload_batch_id: str
    source_kind: str
    phase_scope: str
    metric_confidence: str = "complete"
    total_docs: int = 0
    flagged_docs: int = 0
    high_risk_docs: int = 0
    high_risk_ratio: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    whitelist_removed_docs: int = 0
    false_positive_docs: int = 0
    confirmed_issue_docs: int = 0
    phase_comparisons: list[PhaseComparisonMetric] = field(default_factory=list)
    rule_metrics: list[RuleMetric] = field(default_factory=list)
