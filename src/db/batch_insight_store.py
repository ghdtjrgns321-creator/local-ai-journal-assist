"""Persistence helpers for batch-level phase 3 insight snapshots."""

from __future__ import annotations

from src.db.queries import execute_write
from src.llm.models import BatchInsight


def save_phase3_insight(conn, batch_id: str, insight: BatchInsight) -> None:
    """Persist the latest phase 3 insight JSON on the upload batch row."""
    execute_write(
        conn,
        "update_batch_phase3_insight",
        (insight.model_dump_json(), batch_id),
    )
