from __future__ import annotations

from dashboard import tab_overview
from src.metrics.models import PerformanceReport, RuleMetric


def test_build_datasynth_rule_tables_splits_ground_truth_and_separate_benchmarks():
    report = PerformanceReport(
        report_id="rep_001",
        upload_batch_id="batch_001",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_c",
                rule_code="L3-06",
                evaluation_status="ok",
                label_docs=6,
                flagged_docs=16035,
                tp_docs=6,
                fp_docs=16029,
                fn_docs=0,
                precision=6 / 16035,
                recall=1.0,
                f1=0.0007,
            ),
            RuleMetric(
                track_name="benford",
                rule_code="L4-02",
                evaluation_status="ok",
                label_docs=0,
                flagged_docs=34123,
                tp_docs=0,
                fp_docs=34123,
                fn_docs=0,
                precision=0.0,
                recall=None,
                f1=None,
            ),
            RuleMetric(
                track_name="layer_c",
                rule_code="L4-05",
                evaluation_status="no_label",
                label_docs=0,
                flagged_docs=129,
                tp_docs=0,
                fp_docs=129,
                fn_docs=0,
                precision=None,
                recall=None,
                f1=None,
            ),
        ],
    )

    evaluated_df, separate_df = tab_overview._build_datasynth_rule_tables(report)

    assert list(evaluated_df["Rule ID"]) == ["L3-06"]
    assert list(evaluated_df["Status"]) == ["Evaluated"]
    assert list(evaluated_df["Recall"]) == ["100.0%"]

    assert list(separate_df["Rule ID"]) == ["L4-02", "L4-05"]
    assert list(separate_df["Benchmark Type"]) == ["Separate Benchmark", "Separate Benchmark"]
    assert list(separate_df["Benchmark Scope"]) == ["dataset / segment", "user / user-day"]


def test_build_datasynth_rule_tables_keeps_no_label_non_benchmark_rules_in_ground_truth_table():
    report = PerformanceReport(
        report_id="rep_002",
        upload_batch_id="batch_002",
        source_kind="ground_truth",
        phase_scope="phase1_only",
        rule_metrics=[
            RuleMetric(
                track_name="layer_c",
                rule_code="L3-08",
                evaluation_status="no_label",
                label_docs=0,
                flagged_docs=10,
                tp_docs=0,
                fp_docs=10,
                fn_docs=0,
                precision=None,
                recall=None,
                f1=None,
            ),
        ],
    )

    evaluated_df, separate_df = tab_overview._build_datasynth_rule_tables(report)

    assert list(evaluated_df["Rule ID"]) == ["L3-08"]
    assert list(evaluated_df["Status"]) == ["No Label"]
    assert list(evaluated_df["Precision"]) == ["N/A"]
    assert separate_df.empty
