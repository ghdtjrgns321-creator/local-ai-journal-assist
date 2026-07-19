"""Operational proxy metrics for performance evaluation reports."""

from __future__ import annotations

import uuid

import pandas as pd

from src.hitl.label_builder import build_document_feedback_frame
from src.metrics.models import PerformanceReport


def evaluate_operational_report(
    df: pd.DataFrame,
    *,
    upload_batch_id: str,
    whitelist_df: pd.DataFrame | None = None,
    feedback_events_df: pd.DataFrame | None = None,
    metric_confidence: str = "complete",
) -> PerformanceReport:
    """Build an operational proxy report from a batch dataframe."""
    total_docs = int(df["document_id"].nunique()) if "document_id" in df.columns else int(len(df))
    flagged_docs = _count_flagged_docs(df)
    high_risk_docs = _count_high_risk_docs(df)
    high_risk_ratio = high_risk_docs / total_docs if total_docs > 0 else 0.0
    whitelist_removed_docs = 0
    if (
        whitelist_df is not None
        and not whitelist_df.empty
        and "document_id" in whitelist_df.columns
    ):
        whitelist_removed_docs = int(whitelist_df["document_id"].nunique())
    feedback_labels = build_document_feedback_frame(
        feedback_events_df if feedback_events_df is not None else pd.DataFrame()
    )
    false_positive_docs = _count_feedback_docs(feedback_labels, "false_positive")
    confirmed_issue_docs = _count_feedback_docs(feedback_labels, "confirmed_issue")

    return PerformanceReport(
        report_id=f"opr_{uuid.uuid4().hex[:12]}",
        upload_batch_id=upload_batch_id,
        source_kind="operational_proxy",
        phase_scope="phase2_included",
        metric_confidence=metric_confidence,
        total_docs=total_docs,
        flagged_docs=flagged_docs,
        high_risk_docs=high_risk_docs,
        high_risk_ratio=high_risk_ratio,
        whitelist_removed_docs=whitelist_removed_docs,
        false_positive_docs=false_positive_docs,
        confirmed_issue_docs=confirmed_issue_docs,
    )


def evaluate_operational_report_from_db(
    conn,
    *,
    upload_batch_id: str,
    metric_confidence: str = "partial",
) -> PerformanceReport:
    """Build an operational proxy report from engagement DB tables."""
    df = conn.execute(
        """
        SELECT document_id, anomaly_score, risk_level
        FROM general_ledger
        WHERE upload_batch_id = ?
        """,
        [upload_batch_id],
    ).fetchdf()
    whitelist_df = conn.execute(
        """
        SELECT document_id, rule_code
        FROM whitelist
        WHERE batch_id = ?
        """,
        [upload_batch_id],
    ).fetchdf()
    feedback_events_df = conn.execute(
        """
        SELECT document_id, decision, event_type, reason, created_at, id, batch_id
        FROM feedback_events
        WHERE batch_id = ?
        """,
        [upload_batch_id],
    ).fetchdf()
    return evaluate_operational_report(
        df,
        upload_batch_id=upload_batch_id,
        whitelist_df=whitelist_df,
        feedback_events_df=feedback_events_df,
        metric_confidence=metric_confidence,
    )


def _count_flagged_docs(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    if "document_id" not in df.columns:
        if "anomaly_score" in df.columns:
            return int(df["anomaly_score"].fillna(0).gt(0).sum())
        return 0
    if "anomaly_score" in df.columns:
        mask = df["anomaly_score"].fillna(0).gt(0)
    elif "risk_level" in df.columns:
        mask = df["risk_level"].fillna("Normal").ne("Normal")
    else:
        return 0
    return int(df.loc[mask, "document_id"].nunique())


def _count_high_risk_docs(df: pd.DataFrame) -> int:
    if df.empty or "document_id" not in df.columns or "risk_level" not in df.columns:
        return 0
    return int(df.loc[df["risk_level"].fillna("Normal").eq("High"), "document_id"].nunique())


def _count_feedback_docs(df: pd.DataFrame, decision: str) -> int:
    if df.empty or "decision" not in df.columns:
        return 0
    return int(df.loc[df["decision"].eq(decision), "document_id"].nunique())
