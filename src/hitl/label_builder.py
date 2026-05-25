"""Derive document-level labels from feedback events."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from src.hitl.models import DocumentFeedbackLabel


def build_document_feedback_labels(events_df: pd.DataFrame) -> list[DocumentFeedbackLabel]:
    """Reduce feedback events into latest effective document-level labels."""
    if events_df.empty or "document_id" not in events_df.columns:
        return []

    working = events_df.copy()
    working = working[working["document_id"].notna()]
    if "event_type" in working.columns:
        working = working[working["event_type"].eq("document_feedback")]
    if "decision" in working.columns:
        working = working[
            working["decision"].isin(
                {"false_positive", "confirmed_issue", "whitelist_revoked"}
            )
        ]
    if working.empty:
        return []
    if "created_at" in working.columns:
        working = working.sort_values(["created_at", "id"], ascending=[False, False])
    elif "id" in working.columns:
        working = working.sort_values("id", ascending=False)

    labels: list[DocumentFeedbackLabel] = []
    for document_id, group in working.groupby("document_id", sort=False):
        effective = _select_effective_event(group)
        if effective is None:
            continue
        labels.append(
            DocumentFeedbackLabel(
                document_id=str(document_id),
                batch_id=_optional_str(effective.get("batch_id")),
                decision=str(effective["decision"]),
                reason=_optional_str(effective.get("reason")),
                event_type=str(effective.get("event_type") or "document_feedback"),
                event_count=int(len(group)),
                created_at=effective.get("created_at"),
            )
        )
    return labels


def build_document_feedback_frame(events_df: pd.DataFrame) -> pd.DataFrame:
    """Return document feedback labels as a dataframe."""
    labels = build_document_feedback_labels(events_df)
    if not labels:
        return pd.DataFrame(
            columns=[
                "document_id",
                "batch_id",
                "decision",
                "reason",
                "event_type",
                "event_count",
                "created_at",
            ]
        )
    return pd.DataFrame([asdict(label) for label in labels])


def _select_effective_event(group: pd.DataFrame):
    if group.empty:
        return None
    top = group.iloc[0]
    if str(top.get("decision")) == "whitelist_revoked":
        return None
    return top


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
