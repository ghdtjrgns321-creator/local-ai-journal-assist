"""Persistence helpers for performance evaluation reports."""

from __future__ import annotations

import pandas as pd

from src.metrics.models import PerformanceReport, RuleMetric


def save_report(conn, report: PerformanceReport) -> None:
    """Persist a performance report and its rule metrics."""
    report_df = pd.DataFrame([{
        "report_id": report.report_id,
        "upload_batch_id": report.upload_batch_id,
        "source_kind": report.source_kind,
        "phase_scope": report.phase_scope,
        "metric_confidence": report.metric_confidence,
        "total_docs": report.total_docs,
        "flagged_docs": report.flagged_docs,
        "high_risk_docs": report.high_risk_docs,
        "high_risk_ratio": report.high_risk_ratio,
        "precision": report.precision,
        "recall": report.recall,
        "f1": report.f1,
        "whitelist_removed_docs": report.whitelist_removed_docs,
        "false_positive_docs": report.false_positive_docs,
        "confirmed_issue_docs": report.confirmed_issue_docs,
    }])
    conn.execute("DELETE FROM performance_rule_metrics WHERE report_id = ?", [report.report_id])
    conn.execute("DELETE FROM performance_reports WHERE report_id = ?", [report.report_id])
    conn.execute(
        """
        INSERT INTO performance_reports (
            report_id, upload_batch_id, source_kind, phase_scope,
            metric_confidence, total_docs, flagged_docs, high_risk_docs,
            high_risk_ratio, precision, recall, f1, whitelist_removed_docs,
            false_positive_docs, confirmed_issue_docs
        )
        SELECT * FROM report_df
        """
    )

    if not report.rule_metrics:
        return

    rules_df = pd.DataFrame([{
        "report_id": report.report_id,
        "track_name": metric.track_name,
        "rule_code": metric.rule_code,
        "label_docs": metric.label_docs,
        "flagged_docs": metric.flagged_docs,
        "tp_docs": metric.tp_docs,
        "fp_docs": metric.fp_docs,
        "fn_docs": metric.fn_docs,
        "precision": metric.precision,
        "recall": metric.recall,
        "f1": metric.f1,
    } for metric in report.rule_metrics])
    conn.execute(
        """
        INSERT INTO performance_rule_metrics (
            report_id, track_name, rule_code, label_docs, flagged_docs,
            tp_docs, fp_docs, fn_docs, precision, recall, f1
        )
        SELECT * FROM rules_df
        """
    )


def load_latest_report(conn, upload_batch_id: str) -> PerformanceReport | None:
    """Load the latest stored report for a batch."""
    report_df = conn.execute(
        """
        SELECT report_id, upload_batch_id, source_kind, phase_scope,
               metric_confidence, total_docs, flagged_docs, high_risk_docs,
               high_risk_ratio, precision, recall, f1, whitelist_removed_docs,
               false_positive_docs, confirmed_issue_docs
        FROM performance_reports
        WHERE upload_batch_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [upload_batch_id],
    ).fetchdf()
    if report_df.empty:
        return None

    row = report_df.iloc[0]
    metrics_df = conn.execute(
        """
        SELECT track_name, rule_code, label_docs, flagged_docs,
               tp_docs, fp_docs, fn_docs, precision, recall, f1
        FROM performance_rule_metrics
        WHERE report_id = ?
        ORDER BY track_name, rule_code
        """,
        [row["report_id"]],
    ).fetchdf()
    rule_metrics = [
        RuleMetric(
            track_name=str(metric["track_name"]),
            rule_code=str(metric["rule_code"]),
            label_docs=int(metric["label_docs"]),
            flagged_docs=int(metric["flagged_docs"]),
            tp_docs=int(metric["tp_docs"]),
            fp_docs=int(metric["fp_docs"]),
            fn_docs=int(metric["fn_docs"]),
            precision=_to_optional_float(metric["precision"]),
            recall=_to_optional_float(metric["recall"]),
            f1=_to_optional_float(metric["f1"]),
        )
        for _, metric in metrics_df.iterrows()
    ]
    return PerformanceReport(
        report_id=str(row["report_id"]),
        upload_batch_id=str(row["upload_batch_id"]),
        source_kind=str(row["source_kind"]),
        phase_scope=str(row["phase_scope"]),
        metric_confidence=str(row["metric_confidence"]),
        total_docs=int(row["total_docs"]),
        flagged_docs=int(row["flagged_docs"]),
        high_risk_docs=int(row["high_risk_docs"]),
        high_risk_ratio=_to_optional_float(row["high_risk_ratio"]),
        precision=_to_optional_float(row["precision"]),
        recall=_to_optional_float(row["recall"]),
        f1=_to_optional_float(row["f1"]),
        whitelist_removed_docs=int(row["whitelist_removed_docs"]),
        false_positive_docs=int(row["false_positive_docs"]),
        confirmed_issue_docs=int(row["confirmed_issue_docs"]),
        rule_metrics=rule_metrics,
    )


def list_reports_by_batch(conn, upload_batch_id: str) -> pd.DataFrame:
    """List all stored reports for a batch."""
    return conn.execute(
        """
        SELECT report_id, upload_batch_id, source_kind, phase_scope,
               metric_confidence, total_docs, flagged_docs, high_risk_docs,
               high_risk_ratio, precision, recall, f1,
               whitelist_removed_docs, false_positive_docs,
               confirmed_issue_docs, created_at
        FROM performance_reports
        WHERE upload_batch_id = ?
        ORDER BY created_at DESC
        """,
        [upload_batch_id],
    ).fetchdf()


def _to_optional_float(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)
