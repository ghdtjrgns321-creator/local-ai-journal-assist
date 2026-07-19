from __future__ import annotations

import duckdb

from src.db.schema import initialize_schema
from src.hitl.feedback_store import (
    build_feedback_event,
    list_feedback_events,
    record_feedback_event,
)
from src.hitl.label_builder import build_document_feedback_frame


def test_record_and_list_feedback_events() -> None:
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)

    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="document_feedback",
            decision="false_positive",
            company_id="acme",
            engagement_id="2026",
            batch_id="batch_001",
            document_id="DOC001",
            rule_code="L1-01",
            reason="expected posting",
            payload={"source": "whitelist_add"},
        ),
    )

    df = list_feedback_events(conn, batch_id="batch_001", document_id="DOC001")

    assert len(df) == 1
    assert df.iloc[0]["decision"] == "false_positive"
    assert df.iloc[0]["payload_json"]["source"] == "whitelist_add"
    conn.close()


def test_document_feedback_frame_uses_latest_effective_event() -> None:
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)

    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="document_feedback",
            decision="false_positive",
            batch_id="batch_001",
            document_id="DOC001",
            rule_code="L1-01",
        ),
    )
    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="document_feedback",
            decision="whitelist_revoked",
            batch_id="batch_001",
            document_id="DOC001",
            rule_code="L1-01",
        ),
    )
    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="document_feedback",
            decision="confirmed_issue",
            batch_id="batch_001",
            document_id="DOC002",
            rule_code="L2-01",
        ),
    )

    labels_df = build_document_feedback_frame(list_feedback_events(conn, batch_id="batch_001"))

    assert list(labels_df["document_id"]) == ["DOC002"]
    assert labels_df.iloc[0]["decision"] == "confirmed_issue"
    conn.close()


def test_document_feedback_frame_ignores_rule_feedback_events() -> None:
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)

    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="document_feedback",
            decision="false_positive",
            batch_id="batch_001",
            document_id="DOC001",
            rule_code="L1-01",
        ),
    )
    record_feedback_event(
        conn,
        build_feedback_event(
            event_type="rule_feedback",
            decision="approved",
            batch_id="batch_001",
            document_id="DOC001",
            rule_code="L1-01",
        ),
    )

    labels_df = build_document_feedback_frame(list_feedback_events(conn, batch_id="batch_001"))

    assert len(labels_df) == 1
    assert labels_df.iloc[0]["document_id"] == "DOC001"
    assert labels_df.iloc[0]["decision"] == "false_positive"
    conn.close()
