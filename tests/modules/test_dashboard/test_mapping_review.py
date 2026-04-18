from __future__ import annotations

from dashboard.components.mapping_review import _split_visible_and_hidden_mappings
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
