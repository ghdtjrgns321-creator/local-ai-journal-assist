"""Local audit decision helpers for review queue rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import duckdb


def update_audit_decision(
    conn: duckdb.DuckDBPyConnection,
    candidate_id: str,
    decision: str | None,
    note: str | None,
    user: str,
) -> dict[str, Any]:
    """Store auditor classification metadata on a review queue row."""
    from src.db.schema import AUDIT_DECISION_VALUES

    if not user:
        raise ValueError("reviewed_by(user) is empty")
    if decision is not None and decision not in AUDIT_DECISION_VALUES:
        raise ValueError(
            f"invalid audit_decision: {decision!r}. allowed: "
            f"{sorted(AUDIT_DECISION_VALUES)} or None"
        )

    exists = conn.execute(
        "SELECT 1 FROM review_narratives WHERE candidate_id = ?",
        [candidate_id],
    ).fetchone()
    if exists is None:
        raise KeyError(f"candidate_id not found in review_narratives: {candidate_id!r}")

    reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    conn.execute(
        """
        UPDATE review_narratives SET
            audit_decision = ?,
            audit_note = ?,
            reviewed_by = ?,
            reviewed_at = ?
        WHERE candidate_id = ?
        """,
        [decision, note, user, reviewed_at, candidate_id],
    )
    return {
        "updated": True,
        "candidate_id": candidate_id,
        "decision": decision,
        "reviewed_at": reviewed_at.isoformat(timespec="seconds"),
    }


def read_audit_decision(
    conn: duckdb.DuckDBPyConnection,
    candidate_id: str,
) -> dict[str, Any] | None:
    """Read stored auditor classification metadata. Return None when absent."""
    row = conn.execute(
        """
        SELECT audit_decision, audit_note, reviewed_by, reviewed_at
        FROM review_narratives
        WHERE candidate_id = ?
        """,
        [candidate_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "audit_decision": row[0],
        "audit_note": row[1],
        "reviewed_by": row[2],
        "reviewed_at": row[3],
    }
