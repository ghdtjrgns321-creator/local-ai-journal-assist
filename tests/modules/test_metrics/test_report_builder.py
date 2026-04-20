from __future__ import annotations

from src.metrics.models import PerformanceReport, RuleMetric
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
    assert "| - | layer_a | L1-01 | OK | 3 | 2 | 1 | 1 | 2 | 50.0% | 33.3% | 40.0% |" in rendered
