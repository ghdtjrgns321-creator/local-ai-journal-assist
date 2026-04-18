"""Persistence helpers for normalized HITL feedback events."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.db.queries import execute_preset, execute_write
from src.hitl.models import FeedbackEvent


def record_feedback_event(conn, event: FeedbackEvent) -> None:
    """Persist a normalized feedback event."""
    payload = json.dumps(event.payload or {}, ensure_ascii=False, default=str)
    execute_write(
        conn,
        "insert_feedback_event",
        (
            event.company_id,
            event.engagement_id,
            event.batch_id,
            event.document_id,
            event.track_name,
            event.rule_code,
            event.event_type,
            event.decision,
            event.reason,
            payload,
            event.created_by,
        ),
    )


def list_feedback_events(
    conn,
    *,
    batch_id: str | None = None,
    document_id: str | None = None,
    company_id: str | None = None,
    engagement_id: str | None = None,
) -> pd.DataFrame:
    """Load normalized feedback events as a dataframe."""
    if batch_id and document_id:
        df = execute_preset(
            conn,
            "feedback_events_by_document",
            params=(batch_id, document_id),
        )
    elif batch_id:
        df = execute_preset(conn, "feedback_events_by_batch", params=(batch_id,))
    elif company_id and engagement_id:
        df = execute_preset(
            conn,
            "feedback_events_by_engagement",
            params=(company_id, engagement_id),
        )
    else:
        raise ValueError("batch_id 또는 company_id/engagement_id가 필요합니다.")
    return _normalize_payload_column(df)


def build_feedback_event(
    *,
    event_type: str,
    decision: str,
    company_id: str | None = None,
    engagement_id: str | None = None,
    batch_id: str | None = None,
    document_id: str | None = None,
    track_name: str | None = None,
    rule_code: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
    created_by: str = "auditor",
) -> FeedbackEvent:
    """Convenience factory for feedback events."""
    return FeedbackEvent(
        event_type=event_type,
        decision=decision,
        company_id=company_id,
        engagement_id=engagement_id,
        batch_id=batch_id,
        document_id=document_id,
        track_name=track_name,
        rule_code=rule_code,
        reason=reason,
        payload=payload or {},
        created_by=created_by,
    )


def _normalize_payload_column(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "payload_json" not in df.columns:
        return df
    normalized = df.copy()
    normalized["payload_json"] = normalized["payload_json"].apply(_parse_payload)
    return normalized


def _parse_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {}
