"""Markdown builder for performance evaluation reports."""

from __future__ import annotations

from datetime import datetime

from src.metrics.models import PerformanceReport


def build_markdown_report(report: PerformanceReport) -> str:
    """Render a performance report as compact Markdown."""
    lines: list[str] = []
    lines.append("# Performance Evaluation Report")
    lines.append(f"\n> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> Batch: `{report.upload_batch_id}`")
    lines.append(
        f"> Source: `{report.source_kind}` / Scope: `{report.phase_scope}` / Confidence: `{report.metric_confidence}`"
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
        lines.append("| Track | Rule | Labels | Flagged | TP | FP | FN | Precision | Recall | F1 |")
        lines.append("|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|")
        for metric in report.rule_metrics:
            lines.append(
                f"| {metric.track_name} | {metric.rule_code} | {metric.label_docs:,} | "
                f"{metric.flagged_docs:,} | {metric.tp_docs:,} | {metric.fp_docs:,} | "
                f"{metric.fn_docs:,} | {_fmt_pct(metric.precision)} | "
                f"{_fmt_pct(metric.recall)} | {_fmt_pct(metric.f1)} |"
            )

    return "\n".join(lines) + "\n"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1%}"
