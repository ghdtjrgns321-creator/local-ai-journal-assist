"""Normalized HITL feedback models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class FeedbackEvent:
    """A normalized human-in-the-loop feedback event."""

    event_type: str
    decision: str
    company_id: str | None = None
    engagement_id: str | None = None
    batch_id: str | None = None
    document_id: str | None = None
    track_name: str | None = None
    rule_code: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_by: str = "auditor"


@dataclass(slots=True)
class DocumentFeedbackLabel:
    """The latest effective feedback label for a document."""

    document_id: str
    batch_id: str | None
    decision: str
    reason: str | None = None
    event_type: str = "document_feedback"
    event_count: int = 0
    created_at: datetime | None = None
