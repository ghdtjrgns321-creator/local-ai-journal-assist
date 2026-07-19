"""PHASE2 unsupervised document review case model invariants."""

from __future__ import annotations

import dataclasses

import pytest

from src.models.phase2_case import UnsupervisedCase, make_row_ref


def _row_ref(row_position: int, document_id: str | None = "DOC-001"):
    return make_row_ref(
        row_position=row_position,
        index_label=row_position,
        document_id=document_id,
        raw_line_number=row_position + 1,
        company_code="C001",
    )


def test_unsupervised_case_requires_document_unit_type() -> None:
    """A1 lock: newly modeled unsupervised review cases are document cases."""
    with pytest.raises(ValueError, match='unit_type="document"'):
        UnsupervisedCase(
            phase2_case_id="p2_unsupervised_row_legacy",
            batch_id="batch-001",
            family="unsupervised",
            unit_type="row",
            row_refs=(_row_ref(0),),
            evidence_tier="ml_quantile",
            case_generation_reason={"gate": "unsupervised_ecdf"},
            family_score=0.91,
            family_ecdf=0.99,
            anomaly_score=0.91,
        )


def test_unsupervised_document_case_holds_multiple_evidence_rows_as_tuple() -> None:
    """One document review case can hold several anomalous row refs as evidence."""
    refs = (_row_ref(0), _row_ref(1))

    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_doc001",
        batch_id="batch-001",
        family="unsupervised",
        unit_type="document",
        row_refs=refs,
        evidence_tier="ml_quantile",
        case_generation_reason={"gate": "unsupervised_ecdf"},
        family_score=0.97,
        family_ecdf=1.0,
        anomaly_score=0.97,
        evidence_row_count=2,
    )

    assert case.row_refs == refs
    assert isinstance(case.row_refs, tuple)
    assert case.evidence_row_count == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.evidence_row_count = 3  # type: ignore[misc]


def test_unsupervised_document_context_and_trace_fields_are_modelled() -> None:
    """Document score context is explicit and display/diagnostic oriented."""
    max_ref = _row_ref(1)
    case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_doc001",
        batch_id="batch-001",
        family="unsupervised",
        unit_type="document",
        row_refs=(_row_ref(0), max_ref),
        evidence_tier="ml_quantile",
        case_generation_reason={"gate": "unsupervised_ecdf"},
        family_score=0.97,
        family_ecdf=1.0,
        anomaly_score=0.97,
        evidence_row_count=2,
        top_score_mean=0.91,
        score_spread=0.12,
        max_score_row_ref=max_ref,
        amount_tail_context=0.98,
        period_end_context=0.75,
        account_rarity_context=0.84,
        process_rarity_context=0.66,
        repeated_normal_pressure=0.2,
        top_features=(
            {
                "feature_id": "amount_tail",
                "contrib": 0.8,
                "tag": "amount_outlier",
                "label_ko": "금액 이상",
                "evidence_type": "amount",
            },
        ),
    )

    assert case.family_score == 0.97
    assert case.anomaly_score == 0.97
    assert case.family_ecdf == 1.0
    assert case.top_score_mean == 0.91
    assert case.score_spread == 0.12
    assert case.max_score_row_ref == max_ref
    assert case.amount_tail_context == 0.98
    assert case.period_end_context == 0.75
    assert case.account_rarity_context == 0.84
    assert case.process_rarity_context == 0.66
    assert case.repeated_normal_pressure == 0.2
    assert case.top_features[0]["tag"] == "amount_outlier"
