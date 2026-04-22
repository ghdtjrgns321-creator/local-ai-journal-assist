from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

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
    artifact_root = Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_tests")
    monkeypatch.setattr("src.detection.phase1_case_builder.PROJECT_ROOT", artifact_root)

    artifact_path = save_phase1_case_result(result)
    loaded = load_phase1_case_result(artifact_path)
    reference = build_phase1_case_reference(loaded, artifact_path)

    assert loaded.run_id == result.run_id
    assert reference["phase1_case_run_id"] == result.run_id
    assert reference["phase1_case_path"] == str(artifact_path)
    assert reference["phase1_case_count"] == len(result.cases)
