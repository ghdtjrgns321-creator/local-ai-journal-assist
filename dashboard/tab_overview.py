"""Overview helpers for Phase 1 metric tables.

This module intentionally keeps a small import surface so tests and report
generation can use the table builders without loading the full Streamlit UI.
"""

from __future__ import annotations

import pandas as pd

from src.metrics.models import PerformanceReport, RuleMetric

_SEPARATE_BENCHMARK_RULES: dict[str, str] = {
    "L4-02": "dataset / segment",
    "L4-03": "entry / population",
    "L4-04": "pair / population",
    "L3-09": "account / aging-bucket",
    "L4-05": "user / user-day",
}

_STATUS_LABELS: dict[str, str] = {
    "ok": "Evaluated",
    "no_label": "No Label",
    "skipped": "Skipped",
}


def _format_percent(value: float | None, *, allow_blank: bool = False) -> str:
    """Format a percentage value for display."""

    if value is None:
        return "" if allow_blank else "N/A"
    return f"{value * 100:.1f}%"


def _build_metric_row(metric: RuleMetric) -> dict[str, object]:
    """Convert a RuleMetric into a table row."""

    return {
        "Rule ID": metric.rule_code,
        "Status": _STATUS_LABELS.get(metric.evaluation_status, metric.evaluation_status),
        "Labels": metric.label_docs,
        "Flagged": metric.flagged_docs,
        "TP": metric.tp_docs,
        "FP": metric.fp_docs,
        "FN": metric.fn_docs,
        "Precision": _format_percent(metric.precision),
        "Recall": _format_percent(metric.recall),
        "F1": _format_percent(metric.f1),
    }


def _build_datasynth_rule_tables(
    report: PerformanceReport,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rule metrics into regular and separate-benchmark tables."""

    evaluated_rows: list[dict[str, object]] = []
    separate_rows: list[dict[str, object]] = []

    for metric in report.rule_metrics:
        row = _build_metric_row(metric)
        if metric.rule_code in _SEPARATE_BENCHMARK_RULES:
            row["Benchmark Type"] = "Separate Benchmark"
            row["Benchmark Scope"] = _SEPARATE_BENCHMARK_RULES[metric.rule_code]
            separate_rows.append(row)
        else:
            evaluated_rows.append(row)

    evaluated_df = pd.DataFrame(
        evaluated_rows,
        columns=["Rule ID", "Status", "Labels", "Flagged", "TP", "FP", "FN", "Precision", "Recall", "F1"],
    )
    separate_df = pd.DataFrame(
        separate_rows,
        columns=[
            "Rule ID",
            "Status",
            "Labels",
            "Flagged",
            "TP",
            "FP",
            "FN",
            "Precision",
            "Recall",
            "F1",
            "Benchmark Type",
            "Benchmark Scope",
        ],
    )
    return evaluated_df, separate_df
