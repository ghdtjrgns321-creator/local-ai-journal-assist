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
            RuleFlag("L3-04", "PeriodEndLarge", 2, 1, len(df)),
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


def test_build_phase1_case_result_maps_l3_10_into_logic_mismatch():
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
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "logic_mismatch")
    assert case.evidence_types == ["logic_mismatch"]
    assert case.raw_rule_hits[0].rule_id == "L3-10"
    assert case.raw_rule_hits[0].detail == (
        "prefix=111; group=cash_equivalent; "
        "result=priority_case; reason=manual_or_adjustment"
    )
    assert case.rule_evidence_summary[0]["summary"].endswith(
        "result=priority_case; reason=manual_or_adjustment"
    )


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
            RuleFlag("L3-04", "PeriodEndLarge", 3, 1, len(df)),
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
            RuleFlag("L3-04", "Period-start/end Large or Manual Posting", 3, 2, len(df)),
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
        rule_flags=[RuleFlag("L3-04", "Period-start/end Large or Manual Posting", 3, 3, len(df))],
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

    case = result.cases[0]
    assert case.primary_theme == "statistical_outlier"
    assert case.priority_band != "high"
    assert case.batch_combo_bonus == 0.0


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
