"""PHASE1 P2-2 document unit adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result


def _config() -> dict:
    return {
        "phase1_case": {
            "top_n_cases": 50,
            "top_n_per_theme": 10,
            "priority_band": {"high": 0.90, "medium": 0.75},
            "topic_scoring": {},
        }
    }


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-1", "DOC-2", "DOC-3", "DOC-4", "DOC-5"],
            "posting_date": pd.to_datetime(
                [
                    "2026-04-30",
                    "2026-04-30",
                    "2026-04-30",
                    "2026-04-30",
                    "2026-04-30",
                    "2026-04-30",
                ]
            ),
            "created_by": ["kim", "kim", "lee", "park", "choi", "han"],
            "business_process": ["R2R", "R2R", "P2P", "P2P", "R2R", "R2R"],
            "gl_account": ["410000", "510000", "110000", "210000", "610000", "710000"],
            "debit_amount": [100.0, 0.0, 200.0, 300.0, 400.0, 500.0],
            "credit_amount": [0.0, 100.0, 0.0, 0.0, 0.0, 0.0],
            "company_code": ["kr01"] * 6,
            "document_type": ["SA"] * 6,
        }
    )


def _result(rule_ids: list[str], detail_scores: dict[str, list[float]]) -> DetectionResult:
    details = pd.DataFrame(detail_scores, index=_df().index)
    return DetectionResult(
        track_name="p2_document_unit_test",
        flagged_indices=list(range(len(details))),
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag(
                rule_id=rule_id,
                rule_name=rule_id,
                severity=4,
                flagged_count=sum(float(value) > 0 for value in detail_scores[rule_id]),
                total_count=len(details),
            )
            for rule_id in rule_ids
        ],
        details=details,
        metadata={},
    )


def _build(result: DetectionResult):
    return build_phase1_case_result(
        _df(),
        [result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_config(),
        generated_at=datetime(2026, 6, 4, 0, 0, 0, tzinfo=UTC),
    )


def test_document_rule_hits_on_same_document_are_grouped_into_one_document_unit() -> None:
    result = _result(
        ["L1-05", "L3-05"],
        {
            "L1-05": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L3-05": [0.0, 0.8, 0.0, 0.0, 0.0, 0.0],
        },
    )

    phase1 = _build(result)

    assert [unit.unit_id for unit in phase1.units] == ["DOC-1"]
    unit = phase1.units[0]
    assert unit.unit_type == "document"
    assert {hit.rule_id for hit in unit.evidence_rows} == {"L1-05", "L3-05"}
    assert [hit.row_index for hit in unit.evidence_rows] == [0, 1]
    assert all(hit.document_id == "DOC-1" for hit in unit.evidence_rows)
    assert unit.priority_score > 0.0
    assert unit.composite_sort_score > 0.0
    assert unit.topic_scores


def test_case_priority_is_derived_from_document_unit_score() -> None:
    result = _result(
        ["L1-05", "L3-05"],
        {
            "L1-05": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L3-05": [0.0, 0.8, 0.0, 0.0, 0.0, 0.0],
        },
    )

    phase1 = _build(result)

    unit = phase1.units[0]
    case = phase1.cases[0]
    assert case.priority_score == unit.priority_score
    assert case.composite_sort_score == unit.composite_sort_score
    assert case.topic_scores == unit.topic_scores


def test_document_units_are_document_denominator_not_row_denominator() -> None:
    result = _result(
        ["L1-05"],
        {"L1-05": [0.9, 0.8, 0.7, 0.0, 0.0, 0.0]},
    )

    phase1 = _build(result)

    assert [unit.unit_id for unit in phase1.units] == ["DOC-1", "DOC-2"]
    assert sum(len(unit.evidence_rows) for unit in phase1.units) == 3
    assert len(phase1.units) == 2
    assert all(unit.unit_type == "document" for unit in phase1.units)


def test_document_units_exclude_review_score_only_annotations() -> None:
    details = pd.DataFrame(
        {
            "L1-05": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L1-07": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=_df().index,
    )
    result = DetectionResult(
        track_name="p2_document_unit_test",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag(
                rule_id="L1-05",
                rule_name="L1-05",
                severity=4,
                flagged_count=1,
                total_count=len(details),
            ),
            RuleFlag(
                rule_id="L1-07",
                rule_name="L1-07",
                severity=4,
                flagged_count=0,
                total_count=len(details),
            ),
        ],
        details=details,
        metadata={
            "row_annotations": {
                "L1-07": {
                    2: {
                        "score": 0.0,
                        "review_score": 0.55,
                        "queue_label": "review",
                    },
                },
            },
        },
    )

    phase1 = _build(result)

    document_units = [unit for unit in phase1.units if unit.unit_type == "document"]
    assert [unit.unit_id for unit in document_units] == ["DOC-1"]
    assert {hit.rule_id for hit in document_units[0].evidence_rows} == {"L1-05"}


def test_flow_and_review_population_rules_do_not_create_document_units() -> None:
    """Flow rules and review-population signals are not document denominator units."""

    result = _result(
        [
            "L2-02",
            "L2-03",
            "L2-05",
            "IC01",
            "IC02",
            "IC03",
            "GR01",
            "L4-02",
            "D01",
            "D02",
            "L3-12",
            "L4-05",
            "L4-06",
        ],
        {
            "L2-02": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L2-03": [0.0, 0.9, 0.0, 0.0, 0.0, 0.0],
            "L2-05": [0.0, 0.0, 0.9, 0.0, 0.0, 0.0],
            "IC01": [0.0, 0.0, 0.0, 0.9, 0.0, 0.0],
            "IC02": [0.0, 0.0, 0.0, 0.0, 0.9, 0.0],
            "IC03": [0.0, 0.0, 0.0, 0.0, 0.0, 0.9],
            "GR01": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L4-02": [0.0, 0.9, 0.0, 0.0, 0.0, 0.0],
            "D01": [0.0, 0.0, 0.9, 0.0, 0.0, 0.0],
            "D02": [0.0, 0.0, 0.0, 0.9, 0.0, 0.0],
            "L3-12": [0.0, 0.0, 0.0, 0.0, 0.9, 0.0],
            "L4-05": [0.0, 0.0, 0.0, 0.0, 0.0, 0.9],
            "L4-06": [0.0, 0.0, 0.0, 0.0, 0.9, 0.0],
        },
    )

    phase1 = _build(result)

    assert [unit for unit in phase1.units if unit.unit_type == "document"] == []


def test_document_unit_addition_does_not_change_existing_cases() -> None:
    result = _result(
        ["L1-05", "L3-05"],
        {
            "L1-05": [0.9, 0.0, 0.0, 0.0, 0.0, 0.0],
            "L3-05": [0.0, 0.8, 0.0, 0.0, 0.0, 0.0],
        },
    )

    phase1 = _build(result)
    legacy_view = phase1.model_copy(update={"units": []})
    restored_legacy = type(phase1).model_validate(legacy_view.model_dump(mode="json"))

    assert [case.model_dump(mode="json") for case in restored_legacy.cases] == [
        case.model_dump(mode="json") for case in phase1.cases
    ]
    assert restored_legacy.units == []
