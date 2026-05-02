from __future__ import annotations

from dashboard.components.mapping_review import (
    _is_auto_hidden_source_column,
    _split_visible_and_hidden_mappings,
)
from src.ingest.models import MappingResult


def test_split_visible_and_hidden_mappings_separates_label_targets() -> None:
    mapping_result = MappingResult(
        mapping={
            "document_id": "document_id",
            "is_fraud": "is_fraud",
            "anomaly_type": "anomaly_type",
        },
        suggestions={"created_by": "created_by"},
        confidence={},
        unmapped=[],
        missing_required=[],
        needs_review=False,
    )

    visible, hidden = _split_visible_and_hidden_mappings(
        ["document_id", "is_fraud", "anomaly_type", "created_by"],
        mapping_result,
    )

    assert visible == {
        "document_id": "document_id",
        "created_by": "created_by",
    }
    assert hidden == {
        "is_fraud": "is_fraud",
        "anomaly_type": "anomaly_type",
    }


def test_split_visible_and_hidden_mappings_ignores_unmapped_columns() -> None:
    mapping_result = MappingResult(
        mapping={"document_id": "document_id"},
        suggestions={},
        confidence={},
        unmapped=["fraud_type"],
        missing_required=[],
        needs_review=True,
    )

    visible, hidden = _split_visible_and_hidden_mappings(
        ["document_id", "fraud_type"],
        mapping_result,
    )

    assert visible == {"document_id": "document_id"}
    assert hidden == {}


def test_auto_hidden_source_columns_include_derived_and_internal_columns() -> None:
    assert _is_auto_hidden_source_column("amount_open")
    assert _is_auto_hidden_source_column("is_cleared")
    assert _is_auto_hidden_source_column("settlement_status")
    assert _is_auto_hidden_source_column("settlement_date")
    assert _is_auto_hidden_source_column("description_quality")
    assert _is_auto_hidden_source_column("exceeds_threshold")
    assert _is_auto_hidden_source_column("_doc_id_str")
    assert _is_auto_hidden_source_column("is_fraud")


def test_auto_hidden_source_columns_do_not_hide_source_schema_columns() -> None:
    assert not _is_auto_hidden_source_column("document_id")
    assert not _is_auto_hidden_source_column("posting_date")
    assert not _is_auto_hidden_source_column("debit_amount")
