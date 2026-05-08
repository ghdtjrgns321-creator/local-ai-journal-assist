from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import (
    build_phase1_case_reference,
    build_phase1_case_result,
    build_phase1_case_run_id,
    load_phase1_case_result,
    save_phase1_case_result,
)
from src.detection.rule_scoring import normalize_rule_evidence


def _make_detection_result(df: pd.DataFrame) -> DetectionResult:
    details = pd.DataFrame(
        {
            "L1-05": [0.8, 0.0],
            "L1-07": [0.8, 0.0],
            "L3-04": [0.0, 0.4],
        },
        index=df.index,
    )
    return DetectionResult(
        track_name="layer_b",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df)),
            RuleFlag("L3-04", "PeriodEndClosingReview", 2, 1, len(df)),
        ],
        details=details,
        metadata={"elapsed": 0.01},
    )


def test_run_id_prefers_company_and_batch():
    run_id = build_phase1_case_run_id(
        company_id="KR01",
        batch_id="batch42",
        dataset_id=None,
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )
    assert run_id == "phase1case_KR01_batch42_20260422T031522Z"


def test_build_phase1_case_result_groups_hits():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-20", "2026-04-30"]),
            "created_by": ["kim", "lee"],
            "business_process": ["P2P", "R2R"],
            "gl_account": ["111000", "410000"],
            "debit_amount": [20_000_000.0, 5_000_000.0],
            "credit_amount": [0.0, 0.0],
            "auxiliary_account_number": ["V001", None],
            "company_code": ["kr01", "kr01"],
            "document_type": ["KR", "SA"],
        }
    )
    result = build_phase1_case_result(
        df,
        [_make_detection_result(df)],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "secondary_tag_min_score": 0.40,
                "near_period_days": 7,
                "period_end_window_days": 5,
                "priority_band": {"high": 0.75, "medium": 0.45},
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.schema_version == "1.0.0"
    assert result.run_id == "phase1case_kr01_batch42_20260422T031522Z"
    assert len(result.theme_summaries) >= 1
    assert len(result.cases) >= 2
    first_case = result.cases[0]
    assert first_case.case_id.startswith("case_")
    assert first_case.document_count >= 1
    assert first_case.raw_rule_hits
    assert first_case.documents


def test_l201_duplicate_or_outflow_score_contributes_to_case_priority():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-L201"],
            "posting_date": pd.to_datetime(["2026-04-20"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [95_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L2-01": [0.75]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-01", "JustBelowThreshold", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L2-01": {
                    0: {"bucket": "razor_band", "score": 0.75},
                }
            }
        },
    )

    result_with_outflow = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_weights": {
                    "amount": 0.25,
                    "outflow": 0.15,
                    "behavior": 0.10,
                }
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )
    result_without_outflow = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_weights": {
                    "amount": 0.25,
                    "outflow": 0.0,
                    "behavior": 0.10,
                }
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    with_outflow = result_with_outflow.cases[0]
    without_outflow = result_without_outflow.cases[0]
    expected_outflow_score = normalize_rule_evidence(
        rule_id="L2-01",
        evidence_type="duplicate_or_outflow",
        severity=3,
        raw_value=0.75,
        display_label="razor_band",
    ).normalized_score

    assert with_outflow.duplicate_or_outflow_score == pytest.approx(expected_outflow_score)
    assert with_outflow.priority_score - without_outflow.priority_score == pytest.approx(
        expected_outflow_score * 0.15,
    )


def test_build_phase1_case_result_accepts_string_index_and_document_total_amount():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-20", "2026-04-20"]),
            "created_by": ["kim", "kim"],
            "business_process": ["R2R", "R2R"],
            "gl_account": ["410000", "410000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 200.0],
            "auxiliary_account_number": ["V001", "V001"],
            "company_code": ["kr01", "kr01"],
            "document_type": ["SA", "AB"],
        },
        index=["row-a", "row-b"],
    )
    details = pd.DataFrame({"L2-05": [0.8, 0.0]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-05", "Reversal", 3, 1, len(df))],
        details=details,
        metadata={
            "elapsed": 0.01,
            "row_annotations": {
                "L2-05": {
                    "row-a": {
                        "interpretation_label": "High-confidence reversal",
                        "primary_signal": "S0",
                        "reason_text": "ERP reversal",
                    }
                }
            },
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {}},
    )

    case = result.cases[0]
    assert case.raw_rule_hits[0].row_index == 0
    assert "S0" in (case.raw_rule_hits[0].detail or "")
    assert case.documents[0].amount == 300.0


def test_build_phase1_case_result_feeds_l205_into_outflow_priority_axis():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-L205"],
            "posting_date": pd.to_datetime(["2026-04-20"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L2-05": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-05", "Reversal", 4, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_weights": {
                    "control": 0.25,
                    "amount": 0.25,
                    "outflow": 0.15,
                    "logic": 0.15,
                    "timing": 0.10,
                    "behavior": 0.10,
                },
            }
        },
    )

    case = result.cases[0]
    assert case.primary_theme == "duplicate_or_outflow"
    assert case.duplicate_or_outflow_score == pytest.approx(0.45)
    assert case.priority_score == pytest.approx(0.3275)


def test_build_phase1_case_result_collects_secondary_tags_from_same_rows():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [20_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame(
        {
            "L1-05": [0.8],
            "L4-03": [0.7],
        },
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L4-03", "UnusualLargeAmount", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "secondary_tag_min_score": 0.40,
                "top_n_cases": 50,
                "top_n_per_theme": 10,
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    control_case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert "statistical_outlier" in control_case.secondary_tags


def test_build_phase1_case_result_uses_l101_split_score_in_logic_score():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-LOW", "DOC-HIGH"],
            "posting_date": pd.to_datetime(["2026-04-20", "2026-04-20"]),
            "created_by": ["kim", "kim"],
            "business_process": ["R2R", "R2R"],
            "gl_account": ["111000", "111000"],
            "debit_amount": [100_000.0, 100_000.0],
            "credit_amount": [99_950.0, 50_000.0],
            "company_code": ["kr01", "kr01"],
            "document_type": ["SA", "AB"],
        }
    )
    details = pd.DataFrame({"L1-01": [0.15, 0.90]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-01", "UnbalancedEntry", 5, 2, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-01": {
                    0: {"bucket": "rounding_scale", "score": 0.15},
                    1: {"bucket": "severe", "score": 0.90},
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    cases = {case.documents[0].document_id: case for case in result.cases}
    assert cases["DOC-LOW"].logic_score == pytest.approx(0.15)
    assert cases["DOC-HIGH"].logic_score == pytest.approx(0.90)
    assert (
        cases["DOC-HIGH"].raw_rule_hits[0].normalized_score
        > cases["DOC-LOW"].raw_rule_hits[0].normalized_score
    )


def test_build_phase1_case_result_uses_l103_bucket_score_in_logic_score():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-UNKNOWN", "DOC-PLACEHOLDER"],
            "posting_date": pd.to_datetime(["2026-04-20", "2026-04-20"]),
            "created_by": ["kim", "kim"],
            "business_process": ["R2R", "R2R"],
            "gl_account": ["1999", "9999"],
            "debit_amount": [100_000.0, 100_000.0],
            "credit_amount": [0.0, 0.0],
            "company_code": ["kr01", "kr01"],
            "document_type": ["SA", "SA"],
        }
    )
    details = pd.DataFrame({"L1-03": [0.60, 0.80]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-03", "InvalidAccount", 3, 2, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-03": {
                    0: {"bucket": "unknown_account", "score": 0.60},
                    1: {"bucket": "placeholder_or_reserved", "score": 0.80},
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    cases = {case.documents[0].document_id: case for case in result.cases}
    unknown = cases["DOC-UNKNOWN"]
    placeholder = cases["DOC-PLACEHOLDER"]
    assert placeholder.logic_score > unknown.logic_score
    assert placeholder.raw_rule_hits[0].normalized_score > unknown.raw_rule_hits[0].normalized_score


def test_build_phase1_case_result_uses_l108_annotation_score_for_priority():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-BASE", "DOC-CONTEXT"],
            "company_code": ["KR01", "KR01"],
            "document_type": ["SA", "AB"],
            "posting_date": pd.to_datetime(["2026-03-31", "2026-03-31"]),
            "created_by": ["kim", "kim"],
            "business_process": ["R2R", "R2R"],
            "debit_amount": [1000.0, 1000.0],
            "credit_amount": [0.0, 0.0],
        }
    )
    details = pd.DataFrame({"L1-08": [0.80, 0.80]})
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-08", "WrongPeriod", 4, 2, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-08": {
                    0: {"bucket": "period_mismatch_confirmed", "score": 0.80},
                    1: {
                        "bucket": "period_mismatch_corroborated",
                        "score": 0.95,
                        "context_reasons": ["period_end", "manual_entry", "high_amount"],
                    },
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_weights": {
                    "control": 0.35,
                    "amount": 0.30,
                    "logic": 0.20,
                    "behavior": 0.15,
                },
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_topic == "closing_timing")
    by_row = {hit.row_index: hit for hit in case.raw_rule_hits}

    assert {doc.document_id for doc in case.documents} == {"DOC-BASE", "DOC-CONTEXT"}
    assert by_row[0].score == pytest.approx(0.80)
    assert by_row[1].score == pytest.approx(0.95)
    assert case.primary_theme == "timing_anomaly"
    assert case.primary_queue == "timing_close"
    assert case.priority_score > 0
    assert "l108_context=high_amount,manual_entry,period_end" in (
        case.priority_adjustment_reasons
    )


def test_l103_case_normalized_score_preserves_raw_score_when_label_is_coarse():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-LOW", "DOC-MID", "DOC-HIGH"],
            "posting_date": pd.to_datetime(["2026-04-20"] * 3),
            "created_by": ["kim", "kim", "kim"],
            "business_process": ["R2R", "R2R", "R2R"],
            "gl_account": ["1999", "ABCD", "9999"],
            "debit_amount": [100_000.0, 100_000.0, 100_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["kr01", "kr01", "kr01"],
            "document_type": ["SA", "SA", "SA"],
        }
    )
    details = pd.DataFrame({"L1-03": [0.60, 0.75, 0.90]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0, 1, 2],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-03", "InvalidAccount", 3, 3, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-03": {
                    0: {"risk_level": "high", "score": 0.60},
                    1: {"risk_level": "high", "score": 0.75},
                    2: {"risk_level": "high", "score": 0.90},
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    by_doc = {case.documents[0].document_id: case for case in result.cases}
    normalized = [
        by_doc["DOC-LOW"].raw_rule_hits[0].normalized_score,
        by_doc["DOC-MID"].raw_rule_hits[0].normalized_score,
        by_doc["DOC-HIGH"].raw_rule_hits[0].normalized_score,
    ]
    assert normalized == pytest.approx([0.45, 0.5625, 0.675])
    assert by_doc["DOC-HIGH"].priority_score > by_doc["DOC-LOW"].priority_score


def test_l310_alone_does_not_seed_case_queue():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-10": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-10", "High-risk Account Use", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L3-10": {
                    0: {
                        "match_type": "prefix",
                        "matched_value": "111",
                        "matched_group": "cash_equivalent",
                        "signal_category": "priority_case",
                        "category_reason": "manual_or_adjustment",
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_band": {"high": 0.75, "medium": 0.45},
                "priority_floors": [
                    {
                        "rule_id": "L3-10",
                        "labels": ["priority_case"],
                        "min_priority_score": 0.45,
                        "reason": "sensitive_account_priority_context",
                    }
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []


def test_l303_alone_does_not_seed_case_queue():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-03": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-03", "RelatedParty", 3, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []


def test_build_phase1_case_result_maps_l1_09_into_control_failure():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-09": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.evidence_types == ["control_failure"]
    assert case.raw_rule_hits[0].rule_id == "L1-09"


def test_l109_material_missing_date_gets_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-09": [0.70]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-09": {0: {"bucket": "material_control_gap", "score": 0.70}}
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-09",
                        "min_raw_score": 0.70,
                        "min_priority_score": 0.45,
                        "reason": "missing_approval_date_material",
                    }
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.priority_score == pytest.approx(0.45)
    assert case.priority_band == "medium"
    assert "missing_approval_date_material" in case.priority_adjustment_reasons


def test_l109_corroborated_missing_date_gets_stronger_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-09": [0.80]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-09": {0: {"bucket": "corroborated_material", "score": 0.80}}
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-09",
                        "min_raw_score": 0.80,
                        "min_priority_score": 0.55,
                        "reason": "missing_approval_date_corroborated_material",
                    }
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.priority_score == pytest.approx(0.55)
    assert case.priority_band == "medium"
    assert "missing_approval_date_corroborated_material" in (
        case.priority_adjustment_reasons
    )


def test_build_phase1_case_result_keeps_review_only_l1_annotation_score():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-04": [0.0]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-04", "Approval Limit Exceeded", 3, 0, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-04": {
                    0: {
                        "bucket": "boundary",
                        "queue_label": "review",
                        "review_score": 0.4,
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.raw_rule_hits[0].rule_id == "L1-04"
    assert case.raw_rule_hits[0].score == pytest.approx(0.4)
    assert case.raw_rule_hits[0].display_label == "boundary"
    assert case.raw_rule_hits[0].signal_status == "review_candidate"


def test_build_phase1_case_result_does_not_seed_case_from_booster_review_only():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L3-12": [0.0]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-12", "Work Scope Excess Review", 3, 0, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L3-12": {
                    0: {
                        "bucket": "compound_scope_concentration",
                        "queue_label": "review",
                        "review_score": 0.65,
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []


def test_build_phase1_case_result_uses_configured_fallback_columns():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-28"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["452100"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "custom_counterparty": ["ALT-CP"],
            "company_code": ["kr01"],
            "trading_partner": ["tp01"],
            "document_type": ["KR"],
            "upload_batch_id": ["B-001"],
        }
    )
    details = pd.DataFrame({"L2-02": [0.9]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-02", "DuplicatePayment", 4, 1, len(df))],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "counterparty_columns": ["custom_counterparty", "auxiliary_account_number"],
                "counterparty_fallback": "UNKNOWN_COUNTERPARTY",
                "near_period_days": 7,
                "top_n_cases": 50,
                "top_n_per_theme": 10,
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "duplicate_or_outflow")
    assert case.case_key_parts["counterparty"] == "ALT-CP"
    assert case.documents[0].counterparty == "ALT-CP"


def test_l202_reference_match_gets_medium_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-28"]),
            "business_process": ["P2P"],
            "gl_account": ["452100"],
            "debit_amount": [15_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L2-02": [0.9]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-02", "DuplicatePayment", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L2-02": {
                    0: {
                        "reason_code": "reference_match",
                        "confidence": 0.9,
                    },
                },
            },
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_floors": [
                    {
                        "rule_id": "L2-02",
                        "labels": ["reference_match"],
                        "min_priority_score": 0.45,
                        "reason": "duplicate_payment_reference_match",
                    },
                ],
            },
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "duplicate_or_outflow")
    assert case.priority_score == pytest.approx(0.45)
    assert "duplicate_payment_reference_match" in case.priority_adjustment_reasons
    assert case.raw_rule_hits[0].display_label == "reference_match"


def test_l203_high_confidence_alone_stays_low_priority():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-28"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["510000"],
            "debit_amount": [5_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L2-03": [0.9]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L2-03", "DuplicateEntry", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L2-03": {
                    0: {
                        "confidence": 0.9,
                        "confidence_band": "high",
                        "queue_label": "priority_duplicate_review",
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "duplicate_or_outflow")
    assert case.priority_score < 0.45
    assert case.priority_band == "low"


def test_l203_high_confidence_with_independent_signal_gets_medium_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["510000"],
            "debit_amount": [5_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L2-03": [0.9], "L3-04": [0.4]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L2-03", "DuplicateEntry", 3, 1, len(df)),
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
        ],
        details=details,
        metadata={
            "row_annotations": {
                "L2-03": {
                    0: {
                        "confidence": 0.9,
                        "confidence_band": "high",
                        "queue_label": "priority_duplicate_review",
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "duplicate_or_outflow")
    assert case.priority_score == pytest.approx(0.45)
    assert case.priority_band == "medium"
    assert "l203_high_confidence_corroborated" in case.priority_adjustment_reasons


def test_representative_explanation_prioritizes_control_failure_over_amount():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [2_000_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-05": [0.8], "L4-03": [0.9]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L4-03", "UnusualLargeAmount", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert "자기승인" in case.representative_explanation
    assert "승인·권한 통제" in case.representative_explanation


def test_representative_explanation_uses_timing_template_when_only_timing_exists():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [5_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.7], "L3-08": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "PeriodEndClosingReview", 3, 1, len(df)),
            RuleFlag("L3-08", "VagueDescription", 3, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")
    assert "기말 집중" in case.representative_explanation
    assert "결산 시점" in case.representative_explanation


def test_l304_only_case_is_downgraded_but_combo_case_is_promoted():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-30"]),
            "created_by": ["kim", "lee"],
            "business_process": ["R2R", "R2R"],
            "gl_account": ["610000", "410000"],
            "debit_amount": [100_000.0, 50_000_000.0],
            "credit_amount": [0.0, 0.0],
            "company_code": ["kr01", "kr01"],
            "document_type": ["SA", "SA"],
            "source": ["manual", "manual"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.6, 0.75], "L3-07": [0.0, 0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "Period-start/end Closing Review Candidate", 3, 2, len(df)),
            RuleFlag("L3-07", "BackdatedEntry", 3, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    timing_cases = [case for case in result.cases if case.primary_theme == "timing_anomaly"]
    plain_case = next(case for case in timing_cases if case.documents[0].document_id == "DOC-1")
    combo_case = next(case for case in timing_cases if case.documents[0].document_id == "DOC-2")

    assert plain_case.priority_band == "low"
    assert combo_case.priority_band in {"medium", "high"}
    assert combo_case.priority_score > plain_case.priority_score


def test_l311_severe_cutoff_gets_medium_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-CUTOFF"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["O2C"],
            "gl_account": ["410000"],
            "debit_amount": [100_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["RV"],
        }
    )
    details = pd.DataFrame({"L3-11": [0.36]}, index=df.index)
    detection_result = DetectionResult(
        track_name="evidence",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-11", "RevenueCutoffMismatch", 3, 1, len(df))],
        details=details,
        metadata={"row_annotations": {"L3-11": {0: {"score": 0.60}}}},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_floors": [
                    {
                        "rule_id": "L3-11",
                        "min_raw_score": 0.60,
                        "min_priority_score": 0.45,
                        "reason": "l311_severe_cutoff_gap",
                    }
                ]
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = result.cases[0]
    assert case.timing_score > 0
    assert case.priority_score == pytest.approx(0.45)
    assert case.priority_band == "medium"
    assert "l311_severe_cutoff_gap" in case.priority_adjustment_reasons


def test_l311_high_amount_cutoff_gets_high_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-CUTOFF"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["O2C"],
            "gl_account": ["410000"],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["RV"],
        }
    )
    details = pd.DataFrame({"L3-11": [0.18], "L4-01": [0.55]}, index=df.index)
    detection_result = DetectionResult(
        track_name="evidence",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-11", "RevenueCutoffMismatch", 3, 1, len(df)),
            RuleFlag("L4-01", "RevenueManipulation", 3, 1, len(df)),
        ],
        details=details,
        metadata={"row_annotations": {"L3-11": {0: {"score": 0.30}}}},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_floors": [
                    {
                        "rule_id": "L3-11",
                        "min_raw_score": 0.30,
                        "required_rules": ["L4-01"],
                        "min_priority_score": 0.75,
                        "reason": "l311_high_amount_cutoff",
                    }
                ]
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    timing_case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")
    assert timing_case.priority_score == pytest.approx(0.75)
    assert timing_case.priority_band == "high"
    assert "l311_high_amount_cutoff" in timing_case.priority_adjustment_reasons


def test_l401_period_end_combo_gets_high_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-REV"],
            "posting_date": pd.to_datetime(["2026-12-31"]),
            "created_by": ["kim"],
            "business_process": ["O2C"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["RV"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.45], "L4-01": [0.60]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "PeriodEndClosingReview", 3, 1, len(df)),
            RuleFlag("L4-01", "RevenueManipulation", 5, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "priority_floors": [
                    {
                        "rule_id": "L3-04",
                        "min_raw_score": 0.45,
                        "required_rules": ["L4-01"],
                        "min_priority_score": 0.75,
                        "reason": "l401_period_end_revenue_outlier",
                    }
                ]
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    timing_case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")
    assert timing_case.priority_score == pytest.approx(0.75)
    assert timing_case.priority_band == "high"
    assert "l401_period_end_revenue_outlier" in timing_case.priority_adjustment_reasons


def test_l304_repeat_pattern_case_caps_repeat_promotion():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2", "DOC-3"],
            "posting_date": pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]),
            "created_by": ["kim", "kim", "kim"],
            "business_process": ["R2R", "R2R", "R2R"],
            "gl_account": ["610000", "610000", "610000"],
            "debit_amount": [1_000_000.0, 1_020_000.0, 980_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["kr01", "kr01", "kr01"],
            "document_type": ["SA", "SA", "SA"],
            "source": ["manual", "manual", "manual"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.6, 0.6, 0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0, 1, 2],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-04", "Period-start/end Closing Review Candidate", 3, 3, len(df))],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")

    assert case.has_repeat_pattern is True
    assert case.repeat_score <= 0.30
    assert case.priority_band == "low"


def test_l301_raw_hit_stays_low_but_context_promotes_review_priority():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-RAW", "DOC-MANUAL", "DOC-APPROVAL"],
            "posting_date": pd.to_datetime(["2026-01-15", "2026-02-15", "2026-03-31"]),
            "created_by": ["kim", "lee", "park"],
            "business_process": ["P2P", "P2P", "P2P"],
            "gl_account": ["410000", "420000", "430000"],
            "debit_amount": [10_000_000.0, 10_000_000.0, 200_000_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["kr01", "kr01", "kr01"],
            "document_type": ["SA", "SA", "SA"],
            "source": ["automated", "manual", "manual"],
            "is_period_end": [False, False, True],
        }
    )
    details = pd.DataFrame(
        {
            "L3-01": [0.65, 0.65, 0.65],
            "L1-07": [0.0, 0.0, 0.8],
        },
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0, 1, 2],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-01", "MisclassifiedAccount", 3, 3, len(df)),
            RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    logic_cases = [case for case in result.cases if case.primary_theme == "logic_mismatch"]
    raw_case = next(case for case in logic_cases if case.documents[0].document_id == "DOC-RAW")
    manual_case = next(
        case for case in logic_cases if case.documents[0].document_id == "DOC-MANUAL"
    )
    approval_case = next(
        case for case in logic_cases if case.documents[0].document_id == "DOC-APPROVAL"
    )

    assert raw_case.priority_band == "low"
    assert raw_case.l301_priority_bonus == 0.0
    assert manual_case.priority_score >= 0.75
    assert "l301_context=manual_entry" in manual_case.priority_adjustment_reasons
    assert approval_case.priority_score >= 0.95
    assert (
        "l301_context=approval_issue,high_amount,manual_entry,period_end"
        in approval_case.priority_adjustment_reasons
    )


def test_topside_bonus_increases_case_priority():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [100_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
            "is_manual_je": [True],
        }
    )
    details = pd.DataFrame(
        {"L3-04": [0.7], "L1-05": [0.8], "L4-03": [0.8]},
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L4-03", "LargeAmount", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.topside_bonus == 0.20
    assert "topside_score=0.60" in case.priority_adjustment_reasons
    assert case.priority_score > case.base_priority_score


def test_batch_combo_bonus_requires_l406_and_corroboration():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame(
        {"L4-06": [0.6], "L3-04": [0.6], "L1-05": [0.8], "L4-03": [0.8]},
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L4-06", "BatchAnomaly", 3, 1, len(df)),
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L4-03", "LargeAmount", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "statistical_outlier")
    assert case.batch_combo_bonus == 0.15
    assert case.behavior_score == 1.0
    assert "batch_combo_groups=3" in case.priority_adjustment_reasons


def test_l406_alone_does_not_create_high_priority_case():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["batch_user"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L4-06": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L4-06", "BatchAnomaly", 3, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []


def test_l404_only_recurring_case_gets_priority_penalty():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["batch_user"],
            "business_process": ["P2P"],
            "gl_account": ["500360"],
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
            "source": ["recurring"],
        }
    )
    details = pd.DataFrame({"L4-04": [0.4]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L4-04", "Rare Debit-Credit Account Pair", 2, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "logic_mismatch")
    assert case.priority_score < case.base_priority_score
    assert "l404_only_penalty=-0.10" in case.priority_adjustment_reasons
    assert "l404_recurring_source_penalty=-0.08" in case.priority_adjustment_reasons
    assert case.priority_band == "low"


def test_macro_findings_do_not_enter_transaction_queue():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L4-02": [0.8], "D01": [0.9], "D02": [0.7]}, index=df.index)
    detection_result = DetectionResult(
        track_name="benford",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L4-02", "Benford", 2, 1, len(df)),
            RuleFlag("D01", "AccountActivityShift", 4, 1, len(df)),
            RuleFlag("D02", "MonthlyPatternShift", 3, 1, len(df)),
        ],
        details=details,
        metadata={
            "benford_findings": [
                {
                    "scope": "company_gl_account",
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "sample_size": 900,
                    "mad": 0.016,
                    "chi2_p_value": 0.001,
                    "finding_severity": "strong",
                    "flagged_digits": [9],
                    "max_deviation": 0.04,
                    "candidate_score": 0.8,
                    "candidate_rows": 1,
                    "candidate_documents": 1,
                }
            ],
            "account_activity_variance": [
                {
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "review_row_count": 1,
                    "reason": "activity_variance",
                    "weighted_variance": 0.9,
                }
            ],
            "d02_account_diagnostics": [
                {
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "d02_group_key": "kr01::410000",
                    "flagged": True,
                    "jsd": 0.7,
                }
            ],
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []
    assert result.metadata["macro_finding_count"] == 3
    assert {item["rule_id"] for item in result.metadata["macro_findings"]} == {
        "L4-02",
        "D01",
        "D02",
    }
    assert result.metadata["macro_findings"][0]["queue_type"] == "account_process_macro"


def test_d01_macro_findings_use_calibrated_priority_not_raw_variance():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    detection_result = DetectionResult(
        track_name="layer_d",
        flagged_indices=[],
        scores=pd.Series([0.0], index=df.index),
        rule_flags=[RuleFlag("D01", "AccountActivityShift", 4, 0, len(df))],
        details=pd.DataFrame({"D01": [0.0]}, index=df.index),
        metadata={
            "account_activity_variance": [
                {
                    "company_code": "kr01",
                    "gl_account": "500100",
                    "review_row_count": 20,
                    "weighted_variance": 20.0,
                    "evaluation_bucket": "normal_business_control",
                    "business_event_type": "price_increase",
                    "precision_policy": "expected_raw_flag_but_exclude_from_confirmed_truth",
                    "d01_target_document_count": 0,
                },
                {
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "review_row_count": 3,
                    "weighted_variance": 0.8,
                    "evaluation_bucket": "confirmed_truth",
                    "precision_policy": "count_as_d01_truth",
                    "d01_target_document_count": 2,
                },
            ],
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    findings = result.metadata["macro_findings"]
    assert findings[0]["gl_account"] == "410000"
    assert findings[0]["queue_bucket"] == "confirmed_account_shift"
    assert findings[0]["macro_priority_score"] >= 0.75
    normal = next(item for item in findings if item["gl_account"] == "500100")
    assert normal["queue_bucket"] == "normal_business_review"
    assert normal["macro_priority_score"] <= 0.35
    assert normal["normal_likelihood"] == 0.85


def test_d02_macro_findings_downrank_normal_recurring_patterns():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    detection_result = DetectionResult(
        track_name="layer_d",
        flagged_indices=[],
        scores=pd.Series([0.0], index=df.index),
        rule_flags=[RuleFlag("D02", "MonthlyPatternShift", 3, 0, len(df))],
        details=pd.DataFrame({"D02": [0.0]}, index=df.index),
        metadata={
            "d02_account_diagnostics": [
                {
                    "company_code": "kr01",
                    "gl_account": "100060",
                    "d02_group_key": "kr01::100060",
                    "flagged": True,
                    "jsd": 0.72,
                    "top_month_delta": 0.65,
                    "scenario_type": "normal_recurring_or_interface_batch",
                    "sources": "automated|recurring",
                    "d02_target_document_count": 0,
                },
                {
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "d02_group_key": "kr01::410000",
                    "flagged": True,
                    "jsd": 0.45,
                    "top_month_delta": 0.30,
                    "scenario_type": "target_anomaly_monthly_shift",
                    "d02_target_document_count": 1,
                },
            ],
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    findings = result.metadata["macro_findings"]
    assert findings[0]["gl_account"] == "410000"
    assert findings[0]["queue_bucket"] == "confirmed_monthly_shift"
    normal = next(item for item in findings if item["gl_account"] == "100060")
    assert normal["queue_bucket"] == "normal_pattern_review"
    assert normal["macro_priority_score"] <= 0.35
    assert normal["normal_likelihood"] == 0.85


def test_d01_d02_macro_contexts_flow_into_matching_transaction_cases():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2024-12-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "fiscal_year": [2024],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.60]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df))],
        details=details,
        metadata={
            "account_activity_variance": [
                {
                    "fiscal_year": 2024,
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "review_row_count": 10,
                    "weighted_variance": 0.8,
                    "evaluation_bucket": "confirmed_truth",
                    "precision_policy": "count_as_d01_truth",
                    "d01_target_document_count": 1,
                },
                {
                    "fiscal_year": 2024,
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "review_row_count": 10,
                    "weighted_variance": 9.0,
                    "evaluation_bucket": "normal_business_control",
                    "business_event_type": "price_increase",
                    "precision_policy": "expected_raw_flag_but_exclude_from_confirmed_truth",
                    "d01_target_document_count": 0,
                },
            ],
            "d02_account_diagnostics": [
                {
                    "fiscal_year": 2024,
                    "company_code": "kr01",
                    "gl_account": "410000",
                    "d02_group_key": "kr01::410000",
                    "flagged": True,
                    "jsd": 0.55,
                    "top_month_delta": 0.35,
                    "scenario_type": "normal_recurring_or_interface_batch",
                    "sources": "automated|recurring",
                    "d02_target_document_count": 0,
                }
            ],
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")
    assert {context["queue_bucket"] for context in case.macro_contexts} == {
        "confirmed_account_shift",
        "normal_business_review",
        "normal_pattern_review",
    }
    assert "macro_context=D01:confirmed_account_shift+0.06" in (
        case.priority_adjustment_reasons
    )
    assert not any(
        "normal_business_review" in reason or "normal_pattern_review" in reason
        for reason in case.priority_adjustment_reasons
    )
    assert "d01_macro_context" in case.evidence_tags
    assert "d02_macro_context" in case.evidence_tags


def test_graph_macro_findings_remain_context_without_rankable_transaction_seed():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2024-12-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [80_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "fiscal_year": [2024],
            "document_type": ["SA"],
        }
    )
    transaction_details = pd.DataFrame({"L3-03": [0.60]}, index=df.index)
    graph_details = pd.DataFrame({"GR01": [0.80], "GR03": [0.70]}, index=df.index)
    transaction_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=transaction_details.max(axis=1),
        rule_flags=[RuleFlag("L3-03", "RelatedParty", 3, 1, len(df))],
        details=transaction_details,
        metadata={},
    )
    graph_result = DetectionResult(
        track_name="graph",
        flagged_indices=[0],
        scores=graph_details.max(axis=1),
        rule_flags=[
            RuleFlag("GR01", "GraphCircular", 4, 1, len(df)),
            RuleFlag("GR03", "GraphTransferPricing", 4, 1, len(df)),
        ],
        details=graph_details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [transaction_result, graph_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert {item["rule_id"] for item in result.metadata["macro_findings"]} == {
        "GR01",
        "GR03",
    }
    assert result.cases == []


def test_case_scores_expose_integrity_and_intercompany_axes():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-30"]),
            "created_by": ["kim", "lee"],
            "business_process": ["R2R", "R2R"],
            "gl_account": ["410000", "420000"],
            "debit_amount": [80_000_000.0, 60_000_000.0],
            "credit_amount": [0.0, 0.0],
            "company_code": ["kr01", "kr01"],
            "trading_partner": ["", "kr02"],
            "document_type": ["SA", "SA"],
        }
    )
    details = pd.DataFrame({"L1-01": [0.90, 0.0], "IC01": [0.0, 0.80]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-01", "UnbalancedEntry", 5, 1, len(df)),
            RuleFlag("IC01", "IntercompanyReconciliationGap", 3, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    integrity_case = next(
        case for case in result.cases if case.primary_theme == "data_integrity_failure"
    )
    intercompany_case = next(
        case for case in result.cases if case.primary_theme == "intercompany_structure"
    )
    assert integrity_case.data_integrity_score > 0
    assert integrity_case.intercompany_score == 0
    assert intercompany_case.intercompany_score > 0
    assert intercompany_case.data_integrity_score == 0


def test_weak_evidence_bonus_requires_strong_evidence():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
            "is_round_number": [True],
        }
    )
    details = pd.DataFrame({"L1-05": [0.8]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-05", "SelfApproval", 4, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.weak_evidence_bonus == 0.03
    assert "weak_evidence=is_round_number" in case.priority_adjustment_reasons


def test_l308_alone_does_not_seed_case_queue():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-08": [0.55]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L3-08", "MissingDescription", 1, 1, len(df))],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert result.cases == []


def test_l308_gets_weak_description_bonus_with_corroborating_rule():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame({"L3-04": [0.60], "L3-08": [0.55]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_c",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
            RuleFlag("L3-08", "MissingDescription", 1, 1, len(df)),
        ],
        details=details,
        metadata={},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "timing_anomaly")
    assert case.weak_evidence_bonus == 0.03
    assert (
        "weak_evidence=missing_or_corrupted_description"
        in case.priority_adjustment_reasons
    )


def test_fraud_combo_floor_is_written_to_case_topic_breakdown():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-CLOSING"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [150_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["SA"],
        }
    )
    details = pd.DataFrame(
        {"L3-04": [0.60], "L4-03": [0.70], "L3-08": [0.60]},
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="combo",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
            RuleFlag("L4-03", "HighAmount", 3, 1, len(df)),
            RuleFlag("L3-08", "MissingDescription", 1, 1, len(df)),
        ],
        details=details,
        metadata={"row_annotations": {"L4-03": {0: {"bucket": "high_zscore"}}}},
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "topic_scoring": {
                    "combo_floors": {
                        "period_end_adjustment_high": 0.75,
                    },
                },
                "top_n_cases": 50,
                "top_n_per_theme": 10,
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_topic == "closing_timing")
    breakdown = case.topic_score_breakdown["closing_timing"]

    assert case.topic_scores["closing_timing"] == pytest.approx(0.75)
    assert "period_end_adjustment_risk" in case.fraud_scenario_tags
    assert "period_end_adjustment_risk" in breakdown["fraud_combo_tags"]
    assert "period_end_or_late_posting + high_amount + weak_description_or_sensitive_account" in (
        breakdown["fraud_combo_policy_ids"]
    )


def test_l105_escalated_materiality_gets_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["111000"],
            "debit_amount": [1_500_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-05": [0.8]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-05", "SelfApproval", 3, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-05": {0: {"bucket": "escalated_materiality"}}
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-05",
                        "labels": ["escalated_materiality"],
                        "min_priority_score": 0.80,
                        "reason": "critical_self_approval",
                    }
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.priority_score == pytest.approx(0.80)
    assert case.priority_band == "high"
    assert "critical_self_approval" in case.priority_adjustment_reasons


def test_l107_uses_score_sensitive_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["TRE"],
            "gl_account": ["111000"],
            "debit_amount": [1_500_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-07": [0.86]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-07": {0: {"queue_label": "immediate"}}
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-07",
                        "labels": ["immediate"],
                        "min_raw_score": 0.85,
                        "min_priority_score": 0.85,
                        "reason": "skipped_approval_critical",
                    },
                    {
                        "rule_id": "L1-07",
                        "labels": ["immediate"],
                        "min_raw_score": 0.70,
                        "min_priority_score": 0.75,
                        "reason": "skipped_approval_high",
                    },
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.priority_score == pytest.approx(0.85)
    assert case.priority_band == "high"
    assert "skipped_approval_critical" in case.priority_adjustment_reasons


def test_l106_score_bands_get_distinct_case_priority_floors():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2", "DOC-3", "DOC-4"],
            "posting_date": pd.to_datetime(["2026-04-30"] * 4),
            "created_by": ["a", "b", "c", "d"],
            "business_process": ["A2R", "P2P", "TRE", "TRE"],
            "gl_account": ["111000"] * 4,
            "debit_amount": [0.0, 10_000.0, 10_000.0, 10_000.0],
            "credit_amount": [0.0] * 4,
            "company_code": ["kr01"] * 4,
            "document_type": ["KR"] * 4,
        }
    )
    details = pd.DataFrame({"L1-06": [0.50, 0.70, 0.80, 0.95]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0, 1, 2, 3],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-06", "SegregationOfDutiesViolation", 4, 4, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-06": {
                    0: {"bucket": "direct_low", "score": 0.50},
                    1: {"bucket": "direct_medium", "score": 0.70},
                    2: {"bucket": "direct_high", "score": 0.80},
                    3: {"bucket": "direct_critical", "score": 0.95},
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-06",
                        "min_raw_score": 0.70,
                        "min_priority_score": 0.45,
                        "reason": "sod_direct_medium",
                    },
                    {
                        "rule_id": "L1-06",
                        "min_raw_score": 0.80,
                        "min_priority_score": 0.75,
                        "reason": "sod_direct_high",
                    },
                    {
                        "rule_id": "L1-06",
                        "min_raw_score": 0.95,
                        "min_priority_score": 0.85,
                        "reason": "sod_direct_critical",
                    },
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    by_doc = {case.documents[0].document_id: case for case in result.cases}
    assert by_doc["DOC-1"].priority_score < 0.45
    assert by_doc["DOC-1"].priority_band == "low"
    assert 0.45 <= by_doc["DOC-2"].priority_score < 0.75
    assert by_doc["DOC-2"].priority_band == "medium"
    assert by_doc["DOC-3"].priority_score == pytest.approx(0.75)
    assert by_doc["DOC-3"].priority_band == "high"
    assert by_doc["DOC-4"].priority_score == pytest.approx(0.85)
    assert by_doc["DOC-4"].priority_band == "high"


def test_l102_core_missing_field_gets_medium_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": [None],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-02": [0.74]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-02", "MissingField", 2, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-02": {0: {"missing_fields": ["gl_account"], "score": 0.74}}
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-02",
                        "missing_fields": [
                            "gl_account",
                            "posting_date",
                            "debit_amount",
                            "credit_amount",
                        ],
                        "min_priority_score": 0.55,
                        "reason": "missing_core_required_field_blocker",
                    }
                ],
                "priority_band": {"high": 0.75, "medium": 0.45},
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "data_integrity_failure")
    assert case.priority_score == pytest.approx(0.55)
    assert case.priority_band == "medium"
    assert "missing_core_required_field_blocker" in case.priority_adjustment_reasons


def test_l102_multiple_core_missing_fields_gets_high_case_priority_floor():
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": [pd.NaT],
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": [None],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-02": [0.80]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_a",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-02", "MissingField", 2, 1, len(df))],
        details=details,
        metadata={
            "row_annotations": {
                "L1-02": {
                    0: {
                        "missing_fields": ["gl_account", "posting_date"],
                        "score": 0.80,
                    }
                }
            }
        },
    )

    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={
            "phase1_case": {
                "top_n_cases": 50,
                "top_n_per_theme": 10,
                "priority_floors": [
                    {
                        "rule_id": "L1-02",
                        "missing_fields": [
                            "document_id",
                            "gl_account",
                            "posting_date",
                            "debit_amount",
                            "credit_amount",
                        ],
                        "min_matching_missing_fields": 2,
                        "min_priority_score": 0.75,
                        "reason": "multiple_core_required_fields_missing",
                    }
                ],
                "priority_band": {"high": 0.75, "medium": 0.45},
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "data_integrity_failure")
    assert case.priority_score == pytest.approx(0.75)
    assert case.priority_band == "high"
    assert "multiple_core_required_fields_missing" in case.priority_adjustment_reasons


def test_save_and_load_phase1_case_result_roundtrip(monkeypatch):
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["P2P"],
            "gl_account": ["111000"],
            "debit_amount": [20_000_000.0],
            "credit_amount": [0.0],
            "auxiliary_account_number": ["V001"],
            "company_code": ["kr01"],
            "document_type": ["KR"],
        }
    )
    details = pd.DataFrame({"L1-05": [0.8]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag("L1-05", "SelfApproval", 4, 1, len(df))],
        details=details,
        metadata={},
    )
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )
    artifact_root = Path(
        "C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_tests"
    )
    monkeypatch.setattr("src.detection.phase1_case_builder.PROJECT_ROOT", artifact_root)

    artifact_path = save_phase1_case_result(result)
    loaded = load_phase1_case_result(artifact_path)
    reference = build_phase1_case_reference(loaded, artifact_path)

    assert loaded.run_id == result.run_id
    assert reference["phase1_case_run_id"] == result.run_id
    assert reference["phase1_case_path"] == str(artifact_path)
    assert reference["phase1_case_count"] == len(result.cases)
