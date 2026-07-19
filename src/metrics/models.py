"""Common models for performance evaluation reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    rule_objective: str = ""
    broad_fraud_type: str = ""
    expected_coverage: str = ""
    overlap_docs: int = 0
    standalone_docs: int = 0
    review_queue_docs: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)
    score_bands: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class PhaseComparisonMetric:
    """Phase-scope comparison summary."""

    phase_scope: str
    flagged_docs: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


@dataclass(slots=True)
class BenfordBenchmarkMetric:
    """Population-level Benford benchmark metric."""

    year: str
    benchmark: str
    truth_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    extra_count: int = 0
    precision: float | None = None
    recall: float | None = None
    note: str = ""


@dataclass(slots=True)
class AnalyticalReviewMetric:
    """Account-level analytical review metric for D01/D02 macro findings."""

    rule_code: str
    year: str
    review_groups: int = 0
    truth_groups: int = 0
    truth_covered: int = 0
    missed_truth_groups: int = 0
    normal_control_groups: int = 0
    normal_control_review_groups: int = 0
    review_population_groups: int = 0
    review_population_covered: int = 0
    overlap_docs: int = 0
    truth_coverage: float | None = None
    normal_control_hit_rate: float | None = None
    review_population_coverage: float | None = None
    note: str = ""


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
    benford_benchmarks: list[BenfordBenchmarkMetric] = field(default_factory=list)
    analytical_review_metrics: list[AnalyticalReviewMetric] = field(default_factory=list)
    hold_out_metrics: dict[str, Any] = field(default_factory=dict)
