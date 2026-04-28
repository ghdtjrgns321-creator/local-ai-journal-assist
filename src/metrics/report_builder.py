"""Markdown builder for performance evaluation reports."""

from __future__ import annotations

from datetime import datetime

from src.detection.constants import get_track_display_label
from src.metrics.models import PerformanceReport


def build_markdown_report(report: PerformanceReport) -> str:
    """Render a performance report as compact Markdown."""
    lines: list[str] = []
    lines.append("# Performance Evaluation Report")
    lines.append(f"\n> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> Batch: `{report.upload_batch_id}`")
    lines.append(
        f"> Source: `{report.source_kind}` / Scope: `{report.phase_scope}` / "
        f"Confidence: `{report.metric_confidence}`"
    )

    lines.append("\n## Summary\n")
    lines.append("| Metric | Value |")
    lines.append("|:--|--:|")
    lines.append(f"| Total docs | {report.total_docs:,} |")
    lines.append(f"| Flagged docs | {report.flagged_docs:,} |")
    lines.append(f"| High-risk docs | {report.high_risk_docs:,} |")
    lines.append(f"| High-risk ratio | {_fmt_pct(report.high_risk_ratio)} |")
    lines.append(f"| Precision | {_fmt_pct(report.precision)} |")
    lines.append(f"| Recall | {_fmt_pct(report.recall)} |")
    lines.append(f"| F1 | {_fmt_pct(report.f1)} |")
    lines.append(f"| Whitelist removed docs | {report.whitelist_removed_docs:,} |")
    lines.append(f"| False positive docs | {report.false_positive_docs:,} |")
    lines.append(f"| Confirmed issue docs | {report.confirmed_issue_docs:,} |")

    if report.phase_comparisons:
        lines.append("\n## Phase Comparison\n")
        lines.append("| Scope | Flagged docs | Precision | Recall | F1 |")
        lines.append("|:--|--:|--:|--:|--:|")
        for item in report.phase_comparisons:
            lines.append(
                f"| {item.phase_scope} | {item.flagged_docs:,} | "
                f"{_fmt_pct(item.precision)} | {_fmt_pct(item.recall)} | {_fmt_pct(item.f1)} |"
            )

    if report.rule_metrics:
        lines.append("\n## Rule Metrics\n")
        lines.append(
            "| Action Layer | Rule Group | Rule | Status | Labels | Flagged | TP | FP | FN | "
            "Precision | Recall | F1 |"
        )
        lines.append("|:--|:--|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|")
        for metric in report.rule_metrics:
            status = _status_label(metric.evaluation_status)
            lines.append(
                f"| {metric.action_layer or '-'} | "
                f"{get_track_display_label(metric.track_name, metric.rule_code)} | "
                f"{metric.rule_code} | {status} | {metric.label_docs:,} | "
                f"{metric.flagged_docs:,} | {metric.tp_docs:,} | {metric.fp_docs:,} | "
                f"{metric.fn_docs:,} | {_fmt_pct(metric.precision)} | "
                f"{_fmt_pct(metric.recall)} | {_fmt_pct(metric.f1)} |"
            )

        coverage_metrics = [metric for metric in report.rule_metrics if metric.rule_objective]
        if coverage_metrics:
            lines.append("\n## Coverage-Oriented Rule Context\n")
            lines.append(
                "| Rule | Objective | Broad fraud type | Expected coverage | "
                "Overlap docs | Standalone docs | Review queue docs | Note |"
            )
            lines.append("|:--|:--|:--|:--|--:|--:|--:|:--|")
            for metric in coverage_metrics:
                lines.append(
                    f"| {metric.rule_code} | {metric.rule_objective} | "
                    f"{metric.broad_fraud_type or '-'} | {metric.expected_coverage or '-'} | "
                    f"{metric.overlap_docs:,} | {metric.standalone_docs:,} | "
                    f"{metric.review_queue_docs:,} | {metric.evaluation_reason or '-'} |"
                )

        banded_metrics = [
            metric for metric in report.rule_metrics if metric.breakdown or metric.score_bands
        ]
        if banded_metrics:
            lines.append("\n## Range-Oriented Rule Bands\n")
            lines.append("| Rule | Score bands | Detector breakdown |")
            lines.append("|:--|:--|:--|")
            for metric in banded_metrics:
                lines.append(
                    f"| {metric.rule_code} | {_fmt_dict(metric.score_bands)} | "
                    f"{_fmt_dict(metric.breakdown)} |"
                )

    if report.benford_benchmarks:
        lines.append("\n## Benford Population Benchmark\n")
        lines.append(
            "| Year | Benchmark | Truth/control | Hits | Misses | Extra | "
            "Precision | Recall | Note |"
        )
        lines.append("|:--|:--|--:|--:|--:|--:|--:|--:|:--|")
        for metric in report.benford_benchmarks:
            lines.append(
                f"| {metric.year} | {metric.benchmark} | {metric.truth_count:,} | "
                f"{metric.hit_count:,} | {metric.miss_count:,} | {metric.extra_count:,} | "
                f"{_fmt_pct(metric.precision)} | {_fmt_pct(metric.recall)} | "
                f"{metric.note or '-'} |"
            )

    if report.analytical_review_metrics:
        lines.append("\n## Analytical Review Signals\n")
        lines.append(
            "| Year | Rule | Review groups | Truth groups | Truth covered | Missed truth | "
            "Normal-control review | Review population covered | Overlap docs | "
            "Truth coverage | Normal-control hit rate | Review coverage | Note |"
        )
        lines.append("|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|")
        for metric in report.analytical_review_metrics:
            lines.append(
                f"| {metric.year} | {metric.rule_code} | {metric.review_groups:,} | "
                f"{metric.truth_groups:,} | {metric.truth_covered:,} | "
                f"{metric.missed_truth_groups:,} | "
                f"{metric.normal_control_review_groups:,} / "
                f"{metric.normal_control_groups:,} | "
                f"{metric.review_population_covered:,} / "
                f"{metric.review_population_groups:,} | "
                f"{metric.overlap_docs:,} | {_fmt_pct(metric.truth_coverage)} | "
                f"{_fmt_pct(metric.normal_control_hit_rate)} | "
                f"{_fmt_pct(metric.review_population_coverage)} | "
                f"{metric.note or '-'} |"
            )

    return "\n".join(lines) + "\n"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}"


def _status_label(status: str) -> str:
    if status == "no_label":
        return "N/A"
    if status == "coverage_anchor":
        return "Coverage Anchor"
    if status == "population":
        return "Population"
    return "OK"


def _fmt_dict(value: dict) -> str:
    if not value:
        return "-"
    parts = [f"{key}={item}" for key, item in value.items()]
    return ", ".join(parts)
