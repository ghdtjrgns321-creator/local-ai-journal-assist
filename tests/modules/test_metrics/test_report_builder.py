from __future__ import annotations

from src.metrics.models import (
    AnalyticalReviewMetric,
    BenfordBenchmarkMetric,
    PerformanceReport,
    RuleMetric,
)
from src.metrics.report_builder import build_markdown_report


def test_build_markdown_report_contains_summary_and_rule_metrics():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        total_docs=10,
        flagged_docs=4,
        high_risk_docs=2,
        high_risk_ratio=0.2,
        precision=0.5,
        recall=0.4,
        f1=0.444,
        whitelist_removed_docs=1,
        rule_metrics=[
            RuleMetric(
                track_name="layer_a",
                rule_code="L1-01",
                label_docs=3,
                flagged_docs=2,
                tp_docs=1,
                fp_docs=1,
                fn_docs=2,
                precision=0.5,
                recall=1 / 3,
                f1=0.4,
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "# Performance Evaluation Report" in rendered
    assert "| Total docs | 10 |" in rendered
    assert "| - | L1 | L1-01 | OK | 3 | 2 | 1 | 1 | 2 | 50.0% | 33.3% | 40.0% |" in rendered


def test_build_markdown_report_contains_coverage_context():
    report = PerformanceReport(
        report_id="rep_002",
        upload_batch_id="batch_002",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_b",
                action_layer="stat_outlier",
                rule_code="L4-01",
                evaluation_status="coverage_anchor",
                evaluation_reason="Broad-label recall is coverage only.",
                label_docs=10,
                flagged_docs=6,
                tp_docs=2,
                fp_docs=4,
                fn_docs=8,
                precision=2 / 6,
                recall=0.2,
                rule_objective="High-value revenue z-score outlier",
                broad_fraud_type="RevenueManipulation",
                expected_coverage="partial / anchor",
                overlap_docs=3,
                standalone_docs=3,
                review_queue_docs=4,
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "| stat_outlier | L4 | L4-01 | Coverage Anchor |" in rendered
    assert "## Coverage-Oriented Rule Context" in rendered
    assert "High-value revenue z-score outlier" in rendered
    assert (
        "| L4-01 | High-value revenue z-score outlier | RevenueManipulation | "
        "partial / anchor | 3 | 3 | 4 |"
    ) in rendered


def test_build_markdown_report_contains_range_oriented_bands():
    report = PerformanceReport(
        report_id="rep_003",
        upload_batch_id="batch_003",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_b",
                action_layer="layer_b",
                rule_code="L1-06",
                breakdown={"immediate_rows": 2, "review_rows": 3},
                score_bands={"immediate_docs": 1, "review_docs": 2},
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "## Range-Oriented Rule Bands" in rendered
    assert "immediate_docs=1, review_docs=2" in rendered
    assert "immediate_rows=2, review_rows=3" in rendered


def test_build_markdown_report_contains_benford_population_benchmark():
    report = PerformanceReport(
        report_id="rep_004",
        upload_batch_id="batch_004",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        benford_benchmarks=[
            BenfordBenchmarkMetric(
                year="2024",
                benchmark="contract_findings",
                truth_count=32,
                hit_count=32,
                miss_count=0,
                extra_count=0,
                precision=1.0,
                recall=1.0,
                note="strict contract truth",
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "## Benford Population Benchmark" in rendered
    assert "| 2024 | contract_findings | 32 | 32 | 0 | 0 | 100.0% | 100.0% |" in rendered


def test_build_markdown_report_contains_missing_benford_sidecar_status():
    report = PerformanceReport(
        report_id="rep_004b",
        upload_batch_id="batch_004b",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        benford_benchmarks=[
            BenfordBenchmarkMetric(
                year="2024",
                benchmark="sidecars_missing",
                note="Benford population benchmark unavailable",
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "sidecars_missing" in rendered
    assert "Benford population benchmark unavailable" in rendered


def test_build_markdown_report_contains_analytical_review_signals():
    report = PerformanceReport(
        report_id="rep_005",
        upload_batch_id="batch_005",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        analytical_review_metrics=[
            AnalyticalReviewMetric(
                rule_code="D01",
                year="2024",
                review_groups=10,
                truth_groups=4,
                truth_covered=4,
                missed_truth_groups=0,
                normal_control_groups=6,
                normal_control_review_groups=6,
                review_population_groups=10,
                review_population_covered=10,
                overlap_docs=3,
                truth_coverage=1.0,
                normal_control_hit_rate=1.0,
                review_population_coverage=1.0,
                note="account review population",
            )
        ],
    )

    rendered = build_markdown_report(report)

    assert "## Analytical Review Signals" in rendered
    assert "| 2024 | D01 | 10 | 4 | 4 | 0 | 6 / 6 | 10 / 10 | 3 | 100.0% |" in rendered
