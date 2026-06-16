from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import (
    _build_audit_evidence_context,
    _build_macro_context_index,
    _case_audit_evidence_scores,
    _collect_raw_hits,
    _macro_only_evidences,
    _priority_band,
    _unit_audit_evidence_scores,
    build_phase1_case_reference,
    build_phase1_case_result,
    build_phase1_case_run_id,
    load_phase1_case_result,
    save_phase1_case_result,
)
from src.detection.rule_scoring import RULE_SCORING_REGISTRY, normalize_rule_evidence


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


def _single_row_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "posting_date": pd.to_datetime(["2026-04-30"]),
            "created_by": ["kim"],
            "business_process": ["R2R"],
            "gl_account": ["410000"],
            "debit_amount": [10_000_000.0],
            "credit_amount": [0.0],
            "company_code": ["kr01"],
            "trading_partner": ["kr02"],
            "document_type": ["SA"],
        }
    )


def _single_rule_detection_result(
    df: pd.DataFrame,
    rule_id: str,
    *,
    score: float = 0.8,
    severity: int = 3,
    row_annotations: dict | None = None,
) -> DetectionResult:
    details = pd.DataFrame({rule_id: [score]}, index=df.index)
    return DetectionResult(
        track_name="metadata_policy",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[RuleFlag(rule_id, rule_id, severity, 1, len(df))],
        details=details,
        metadata={"row_annotations": row_annotations or {}},
    )


def test_unit_audit_evidence_fast_context_matches_case_reference() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-05-02", "2026-06-30"]),
            "document_date": pd.to_datetime(["2026-04-20", "2026-04-20", "2026-06-25"]),
            "created_by": ["kim", "SYSTEM_BATCH", "lee"],
            "approved_by": ["", "SYSTEM_BATCH", "lee"],
            "source": ["manual", "system", "manual"],
            "user_persona": ["accountant", "system", "manager"],
            "business_process": ["P2P", "Intercompany", "R2R"],
            "reference": ["INV-1", "IC-77", "REV-1"],
            "trading_partner": ["", "C002", ""],
            "auxiliary_account_number": ["V001", "", ""],
            "master_counterparty_inactive": [True, False, False],
            "master_counterparty_known": [False, True, False],
            "document_flow_orphan": [False, True, False],
            "ic_matched_pair_found": [False, True, False],
            "ic_unmatched_reference": [False, False, False],
            "approval_matrix_gap": [False, False, False],
            "approval_limit_exceeded_independent": [True, False, False],
            "has_attachment": [False, True, True],
            "supporting_doc_type": ["", "invoice", "invoice"],
            "settlement_status": ["", "", "reversed"],
            "gl_account": ["410000", "510000", "620000"],
            "debit_amount": [100.0, 200.0, 300.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["kr01"] * 3,
            "document_type": ["SA"] * 3,
        }
    )
    details = pd.DataFrame(
        {
            "L2-05": [0.8, 0.0, 0.8],
            "L3-04": [0.0, 0.6, 0.0],
            "L4-03": [0.6, 0.0, 0.0],
        },
        index=df.index,
    )
    result = DetectionResult(
        track_name="audit_context",
        flagged_indices=[0, 1, 2],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L2-05", "Reversal", 4, 2, len(df)),
            RuleFlag("L3-04", "PeriodEnd", 3, 1, len(df)),
            RuleFlag("L4-03", "Large", 4, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    hits = _collect_raw_hits(df, [result])
    context = _build_audit_evidence_context(df)

    for positions in ([0], [1], [0, 1], [2], [0, 1, 2]):
        case_hits = [hit for hit in hits if hit.row_index in positions]
        rows = df.iloc[positions]
        expected = _case_audit_evidence_scores(
            rows=rows,
            case_hits=case_hits,
            amount_score=0.75,
            repeat_score=0.50,
        )
        actual = _unit_audit_evidence_scores(
            row_positions=list(positions),
            case_hits=case_hits,
            amount_score=0.75,
            repeat_score=0.50,
            context=context,
        )
        assert actual == expected


def _build_single_rule_case_result(
    rule_id: str,
    *,
    score: float = 0.8,
    severity: int = 3,
    row_annotations: dict | None = None,
):
    df = _single_row_df()
    return build_phase1_case_result(
        df,
        [
            _single_rule_detection_result(
                df,
                rule_id,
                score=score,
                severity=severity,
                row_annotations=row_annotations,
            )
        ],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )


def test_priority_band_does_not_promote_low_score_repeated_case() -> None:
    config = {"priority_band": {"high": 0.90, "medium": 0.75}}

    assert _priority_band(0.50, config) == "low"


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


def test_l101_separated_into_data_integrity_track():
    # 2026-06-15: L1-01(차대불일치)은 부정 위험이 아니라 데이터 품질 문제 → 위험 큐에서 분리.
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

    # 위험 큐(case) 미생성 — L1-01은 위험 점수/등급에 기여하지 않는다.
    assert result.cases == []
    di = {f["rule_id"]: f for f in result.metadata["data_integrity_findings"]}
    assert di["L1-01"]["flagged_row_count"] == 2
    assert di["L1-01"]["track"] == "data_integrity"


def test_l103_separated_into_data_integrity_track():
    # 2026-06-15: L1-03(무효 계정)도 데이터 정합성 트랙 → 위험 큐 미생성.
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

    assert result.cases == []
    di = {f["rule_id"]: f for f in result.metadata["data_integrity_findings"]}
    assert di["L1-03"]["flagged_row_count"] == 2
    assert di["L1-03"]["track"] == "data_integrity"


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
    assert "l108_context=high_amount,manual_entry,period_end" in (case.priority_adjustment_reasons)


def test_l103_data_integrity_track_counts_all_flagged_rows():
    # 2026-06-15: L1-03은 위험 큐가 아니라 데이터 정합성 트랙에서 발화 건수로만 집계.
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

    assert result.cases == []
    di = {f["rule_id"]: f for f in result.metadata["data_integrity_findings"]}
    assert di["L1-03"]["flagged_row_count"] == 3


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


@pytest.mark.parametrize(
    "rule_id",
    ("L3-05", "L3-06", "L3-08", "L3-10", "L3-12", "L4-05", "L4-06"),
)
def test_metadata_standalone_false_rules_do_not_seed_cases(rule_id: str):
    result = _build_single_rule_case_result(rule_id)

    assert result.cases == []


def test_benford_alias_is_canonicalized_to_l402_but_does_not_seed_transaction_case():
    result = _build_single_rule_case_result("Benford")

    assert result.cases == []


def test_l203_internal_reason_codes_canonicalize_without_extra_case_or_rule_count():
    df = _single_row_df()
    details = pd.DataFrame({"L2-03": [0.8], "L2-03a": [0.8], "L2-03d": [0.7]}, index=df.index)
    detection_result = DetectionResult(
        track_name="duplicate_reason_codes",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L2-03", "DuplicateDocument", 3, 1, len(df)),
            RuleFlag("L2-03a", "ExactDuplicateReason", 3, 1, len(df)),
            RuleFlag("L2-03d", "SequentialDuplicateReason", 3, 1, len(df)),
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

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.rule_count == 1
    assert {hit.rule_id for hit in case.raw_rule_hits} == {"L2-03"}
    assert {doc.matched_rules[0] for doc in case.documents} == {"L2-03"}
    assert case.rule_evidence_summary[0]["canonical_rule_id"] == "L2-03"
    assert case.rule_evidence_summary[0]["requested_rule_id"] in {"L2-03", "L2-03a", "L2-03d"}


@pytest.mark.skip(
    reason="intercompany_cycle 주제 제거(IC/GR PHASE1 제외, 2026-06-14) — 검증 대상 폐지."
)
def test_intercompany_sidecar_rule_keeps_topic_seed_without_l1_l4_transaction_count():
    result = _build_single_rule_case_result("IC01")

    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.primary_theme == "intercompany_structure"
    assert case.primary_topic == "intercompany_cycle"
    assert case.raw_rule_hits[0].rule_id == "IC01"
    assert case.rule_evidence_summary[0]["canonical_rule_id"] == "IC01"


def test_primary_transaction_detail_rule_still_seeds_case():
    result = _build_single_rule_case_result("L1-05", score=0.8, severity=4)

    assert len(result.cases) == 1
    assert result.cases[0].raw_rule_hits[0].rule_id == "L1-05"


def test_metadata_policy_overrides_legacy_stale_scoring_role(monkeypatch):
    stale = replace(
        RULE_SCORING_REGISTRY["L3-05"],
        scoring_role="primary",
        standalone_rankable=True,
    )
    monkeypatch.setitem(RULE_SCORING_REGISTRY, "L3-05", stale)

    result = _build_single_rule_case_result(
        "L3-05",
        row_annotations={"L3-05": {0: {"score": 0.9}}},
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


def test_l109_alone_does_not_seed_case_queue():
    # §9.1 light_seeder audit (2026-05-14): L1-09는 case seeder 권한이 회수되었으므로
    # 단독 hit는 더 이상 case를 생성하지 않는다. corroborating evidence 로만 합류한다.
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

    assert result.cases == []


def test_l107_alone_does_not_seed_case_queue():
    # §9.1 light_seeder audit (2026-05-14): L1-07도 동일하게 case seeder 권한 회수.
    result = _build_single_rule_case_result("L1-07", score=0.8, severity=4)

    assert result.cases == []


def test_light_seeder_l107_l109_pair_does_not_seed_case_queue():
    # §9.1: light_seeder 정의 — ruleset ⊆ {L1-07, L1-09, L3-04} 이고 L3-04 가 없으면
    # 어떤 룰도 seeder가 아니므로 case가 생성되지 않는다.
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
    details = pd.DataFrame({"L1-07": [0.7], "L1-09": [0.6]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-07", "Approval Bypass", 4, 1, len(df)),
            RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df)),
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


def test_light_seeder_l107_l109_join_case_seeded_by_l304_as_corroborating():
    # §9.1: light_seeder ruleset {L1-07, L1-09, L3-04} 에서 L3-04 만 seeder.
    # L1-07/L1-09는 corroborating evidence로 같은 case에 합류한다 (theme/topic는 L3-04 기준).
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
            "fiscal_period": ["12"],
        }
    )
    details = pd.DataFrame(
        {"L1-07": [0.7], "L1-09": [0.6], "L3-04": [0.4]},
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-07", "Approval Bypass", 4, 1, len(df)),
            RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df)),
            RuleFlag("L3-04", "PeriodEndClosingReview", 2, 1, len(df)),
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

    # L3-04만 seeder이므로 case가 한 개만 생성되고, 그 안에 L1-07/L1-09가 corroborating으로 합류.
    assert len(result.cases) == 1
    case = result.cases[0]
    hit_rule_ids = {hit.rule_id for hit in case.raw_rule_hits}
    assert hit_rule_ids == {"L1-07", "L1-09", "L3-04"}
    # primary_theme은 L3-04 기반이어야 하고 approval_control이 아님.
    assert case.primary_theme != "control_failure"


def test_l109_material_missing_date_gets_case_priority_floor():
    # §9.1 light_seeder audit: L1-09는 더 이상 단독 seeder가 아니므로 co-seeder L1-04를 추가해
    # case를 생성한 뒤 L1-09 priority_floor가 corroborating evidence 매칭으로 동작하는지 검증한다.
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
    details = pd.DataFrame({"L1-04": [0.5], "L1-09": [0.70]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-04", "Approval Limit Exceeded", 3, 1, len(df)),
            RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df)),
        ],
        details=details,
        metadata={
            "row_annotations": {"L1-09": {0: {"bucket": "material_control_gap", "score": 0.70}}}
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
    assert case.priority_band == "low"
    assert "missing_approval_date_material" in case.priority_adjustment_reasons


def test_l109_corroborated_missing_date_gets_stronger_case_priority_floor():
    # §9.1 light_seeder audit: L1-04 co-seeder + L1-09 corroborating evidence 조합에서
    # L1-09 priority_floor 강한 등급(0.55)이 그대로 적용되는지 검증.
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
    details = pd.DataFrame({"L1-04": [0.5], "L1-09": [0.80]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-04", "Approval Limit Exceeded", 3, 1, len(df)),
            RuleFlag("L1-09", "Approval Date Missing", 3, 1, len(df)),
        ],
        details=details,
        metadata={
            "row_annotations": {"L1-09": {0: {"bucket": "corroborated_material", "score": 0.80}}}
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
    assert case.priority_band == "low"
    assert "missing_approval_date_corroborated_material" in (case.priority_adjustment_reasons)


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
    assert case.priority_band == "low"
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
    assert combo_case.priority_band == "low"
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
    assert case.priority_band == "low"
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
    assert timing_case.priority_band == "medium"
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
    assert timing_case.priority_band == "medium"
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


def test_l402_benford_not_attached_to_transaction_cases():
    # #20② 재판정 — L4-02(Benford)는 모집단 신호로 거래 case 부착 제외(by_account 미포함).
    # Benford detector 가 위반 문서 목록을 안 만들어 broad 부착 시 OOM 유발 → macro 큐에만 표면화.
    findings = [
        {"rule_id": "L4-02", "gl_account": "8010", "finding_id": "L4-02:0001"},
        {
            "rule_id": "D01",
            "gl_account": "1190",
            "finding_id": "D01:0001",
            "queue_bucket": "confirmed_account_shift",
        },
    ]
    index = _build_macro_context_index(findings)
    assert "8010" not in index["by_account"], "L4-02 Benford 가 거래 case 에 부착되면 안 됨"
    assert "1190" in index["by_account"], "D01 은 타깃 단위라 부착 유지"


def test_macro_only_evidences_score_by_scoring_effect():
    # #20① — scoring_effect 별 normalized_score 환산 (confirmed=1.0, corroborated=0.67, context_only=0)
    contexts = [
        {"rule_id": "D01", "scoring_effect": "priority_booster"},
        {"rule_id": "GR01", "scoring_effect": "weak_priority_booster"},
        {"rule_id": "L4-02", "scoring_effect": "context_only"},
    ]
    evidences = {ev["rule_id"]: ev for ev in _macro_only_evidences(contexts)}
    assert all(ev["scoring_role"] == "macro_only" for ev in evidences.values())
    assert evidences["D01"]["normalized_score"] == pytest.approx(1.0)
    assert evidences["GR01"]["normalized_score"] == pytest.approx(0.67)
    assert evidences["L4-02"]["normalized_score"] == pytest.approx(0.0)


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
    assert "macro_context=D01:confirmed_account_shift+0.06" in (case.priority_adjustment_reasons)
    assert not any(
        "normal_business_review" in reason or "normal_pattern_review" in reason
        for reason in case.priority_adjustment_reasons
    )
    assert "d01_macro_context" in case.evidence_tags
    assert "d02_macro_context" in case.evidence_tags


@pytest.mark.skip(reason="GR macro 제거(IC/GR PHASE1 제외, 2026-06-14) — 검증 대상 폐지.")
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


@pytest.mark.skip(reason="intercompany axis 제거(IC/GR PHASE1 제외, 2026-06-14) — 검증 대상 폐지.")
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
    assert "weak_evidence=missing_or_corrupted_description" in case.priority_adjustment_reasons


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

    # period_end_adjustment_high combo → closing_timing tier HIGH. topic_scores 는 이제 tier
    # 대표값(가중합 .score 아님): HIGH=0.90. band 도 high.
    assert case.topic_scores["closing_timing"] == pytest.approx(0.90)
    assert case.priority_band == "high"
    assert "period_end_adjustment_risk" in case.fraud_scenario_tags
    assert "period_end_adjustment_risk" in breakdown["fraud_combo_tags"]
    assert (
        "period_end_or_late_posting + high_amount + weak_description_or_sensitive_account"
        in (breakdown["fraud_combo_policy_ids"])
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
        metadata={"row_annotations": {"L1-05": {0: {"bucket": "escalated_materiality"}}}},
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
                        "min_priority_score": 0.90,
                        "reason": "critical_self_approval",
                    }
                ],
            }
        },
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    case = next(case for case in result.cases if case.primary_theme == "control_failure")
    assert case.priority_score == pytest.approx(0.90)
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
    # §9.1 light_seeder audit: L1-07는 더 이상 단독 seeder가 아니므로 co-seeder L1-04를 추가해
    # case를 생성한 뒤 L1-07 priority_floor가 corroborating evidence 매칭으로 동작하는지 검증한다.
    details = pd.DataFrame({"L1-04": [0.5], "L1-07": [0.86]}, index=df.index)
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-04", "Approval Limit Exceeded", 3, 1, len(df)),
            RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df)),
        ],
        details=details,
        metadata={"row_annotations": {"L1-07": {0: {"queue_label": "immediate"}}}},
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
                        "min_priority_score": 0.90,
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
    assert case.priority_score == pytest.approx(0.90)
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
                        "min_priority_score": 0.90,
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
    assert by_doc["DOC-2"].priority_band == "low"
    assert by_doc["DOC-3"].priority_score == pytest.approx(0.75)
    assert by_doc["DOC-3"].priority_band == "medium"
    assert by_doc["DOC-4"].priority_score == pytest.approx(0.90)
    assert by_doc["DOC-4"].priority_band == "high"


def test_l102_separated_into_data_integrity_track():
    # 2026-06-15: L1-02(필수필드 누락)도 데이터 정합성 트랙 → 위험 큐/floor 미적용.
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
            "row_annotations": {"L1-02": {0: {"missing_fields": ["gl_account"], "score": 0.74}}}
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

    assert result.cases == []
    di = {f["rule_id"]: f for f in result.metadata["data_integrity_findings"]}
    assert di["L1-02"]["flagged_row_count"] == 1
    assert di["L1-02"]["track"] == "data_integrity"


def test_l102_multiple_missing_separated_into_data_integrity_track():
    # 2026-06-15: 여러 필수필드 누락도 위험 큐가 아니라 데이터 정합성 트랙에서만 집계.
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

    assert result.cases == []
    di = {f["rule_id"]: f for f in result.metadata["data_integrity_findings"]}
    assert di["L1-02"]["flagged_row_count"] == 1


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


# ---------------------------------------------------------------------------
# §9.3 composite_sort_score 회귀 가드
# ---------------------------------------------------------------------------


def _topic_scoring_config() -> dict:
    return {
        "phase1_case": {
            "top_n_cases": 50,
            "top_n_per_theme": 10,
            "topic_scoring": {
                "topic_caps": {},
                "topic_floors": {},
                "combo_floors": {},
            },
        }
    }


def test_tier_sort_score_components_are_ordinal_keys():
    # PHASE1_TIER_SCORING_SPEC §4: tier sort = 순서형 (tier_rank, 독립 primary 수, rule_count,
    # materiality). 가중합/composite 공식 폐기. components 는 이 4개 순서형 키.
    df = _single_row_df()
    detection_result = _single_rule_detection_result(df, "L1-05", score=0.8, severity=4)
    result = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config=_topic_scoring_config(),
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert len(result.cases) == 1
    case = result.cases[0]
    comps = case.composite_sort_score_components
    assert set(comps) == {
        "tier_rank",
        "independent_primary_count",
        "rule_count",
        "materiality_score",
    }
    assert comps["independent_primary_count"] >= 1
    assert comps["tier_rank"] >= 1  # L1-05 primary → 최소 LOW tier


def test_composite_sort_score_falls_back_to_priority_score_without_topic_scoring():
    # use_topic_scoring=False (legacy 모드) 에서는 fallback 으로 priority_score 사용.
    df = _single_row_df()
    detection_result = _single_rule_detection_result(df, "L1-05", score=0.8, severity=4)
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
    assert case.composite_sort_score == pytest.approx(case.priority_score, abs=1e-9)
    assert case.composite_sort_score_components == {"fallback_score": case.priority_score}


def test_tier_sort_orders_more_signals_above_high_amount():
    # PHASE1_TIER_SCORING_SPEC §4: 같은 tier 안에서 서로 다른 신호(독립 primary 룰)가 더 많은
    # case 가 위. 금액(materiality)은 최후 tiebreak 이므로, 신호 적지만 고액인 case 를
    # 신호 많은 case 가 누른다(§9.3 anti-burying lock 호환).
    df = pd.DataFrame(
        {
            "document_id": ["DOC-MANY", "DOC-AMOUNT"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-29"]),
            "created_by": ["kim", "lee"],
            "business_process": ["P2P", "P2P"],
            "gl_account": ["111000", "111100"],
            "debit_amount": [10_000_000.0, 5_000_000_000.0],
            "credit_amount": [0.0, 0.0],
            "company_code": ["kr01", "kr02"],
            "trading_partner": ["V01", "V02"],
            "document_type": ["KR", "KR"],
        }
    )
    # DOC-MANY: 독립 primary 2개(L1-05+L1-06), 소액. DOC-AMOUNT: 1개(L1-05), 고액.
    details = pd.DataFrame(
        {"L1-05": [0.8, 0.8], "L1-06": [0.8, 0.0]},
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 2, len(df)),
            RuleFlag("L1-06", "SegregationOfDuties", 4, 1, len(df)),
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
        phase1_case_config=_topic_scoring_config(),
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )

    assert len(result.cases) >= 2
    many_case = next(
        case
        for case in result.cases
        if any(hit.document_id == "DOC-MANY" for hit in case.raw_rule_hits)
    )
    amount_case = next(
        case
        for case in result.cases
        if any(hit.document_id == "DOC-AMOUNT" for hit in case.raw_rule_hits)
    )
    # 신호 많은 case 가 고액 case 보다 위 (금액은 최후 tiebreak).
    assert many_case.composite_sort_score > amount_case.composite_sort_score
    assert (many_case.exposure_rank or 0) < (amount_case.exposure_rank or 0)


_COMPOSITE_GUARD_ARTIFACT = Path(
    "artifacts/phase1_cases/_anonymous/"
    "phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T092313Z.json"
)
_COMPOSITE_GUARD_TRUTH = Path(
    "data/journal/archive/primary_legacy_20260514/datasynth/labels/manipulated_entry_truth.csv"
)


@pytest.mark.skipif(
    not _COMPOSITE_GUARD_ARTIFACT.exists() or not _COMPOSITE_GUARD_TRUTH.exists(),
    reason="v126 composite case artifact or truth CSV not present in this checkout",
)
def test_composite_sort_score_v126_truth_capture_thresholds():
    """§9.3 audit 수용 기준 — 7개 주제 합계/도메인별 Top200 truth_doc."""
    import csv
    import json as _json

    artifact_path = _COMPOSITE_GUARD_ARTIFACT
    truth_path = _COMPOSITE_GUARD_TRUTH
    data = _json.loads(artifact_path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    with truth_path.open(encoding="utf-8") as fp:
        truth_docs = {
            str(row["document_id"]).strip() for row in csv.DictReader(fp) if row.get("document_id")
        }

    def _case_docs(case: dict) -> set[str]:
        out: set[str] = set()
        for hit in case.get("raw_rule_hits") or []:
            doc = hit.get("document_id")
            if doc:
                out.add(str(doc))
        return out

    def _composite_score(case: dict, topic_id: str | None = None) -> float:
        composite = case.get("composite_sort_score")
        if composite is not None:
            return float(composite)
        if topic_id:
            return float((case.get("topic_scores") or {}).get(topic_id, 0.0))
        return float(case.get("priority_score") or 0.0)

    def _topic_top_n_truth(topic_id: str, top_n: int, *, high_only: bool) -> int:
        rows = []
        for case in cases:
            scores = case.get("topic_scores") or {}
            ts = float(scores.get(topic_id, 0.0))
            if ts <= 0:
                continue
            if high_only and ts < 0.75:
                continue
            rows.append(case)
        rows.sort(
            key=lambda case: (
                -_composite_score(case, topic_id),
                -float(case.get("triage_rank_score") or 0.0),
                -float(case.get("total_amount") or 0.0),
                -int(case.get("rule_count") or 0),
            )
        )
        seen: set[str] = set()
        for case in rows[:top_n]:
            seen |= _case_docs(case)
        return len(seen & truth_docs)

    topics = (
        "ledger_integrity",
        "approval_control",
        "closing_timing",
        "account_logic",
        "duplicate_outflow",
        "intercompany_cycle",
        "revenue_statistical",
    )
    all_band_sum = sum(_topic_top_n_truth(topic_id, 200, high_only=False) for topic_id in topics)
    approval_high = _topic_top_n_truth("approval_control", 200, high_only=True)
    closing_all = _topic_top_n_truth("closing_timing", 200, high_only=False)
    revenue_all = _topic_top_n_truth("revenue_statistical", 200, high_only=False)

    # approval_control:high 가드를 비율 기반으로 환산 (T4 multi-dataset lock).
    # 절대치 12 는 v126_profiled 단일 측정 (high_cases=489) 기준이라 high_band 모집단이 바뀌면
    # 임계가 의미를 잃는다. high_cases 대비 Top200 truth_doc 비율 ≥ 2.0% 로 재정의 한다.
    # 본 가드는 Layer C SOFT WARN (baseline 회귀 방지선) 이며 가중치 조정의 근거로 사용 금지.
    approval_high_cases = sum(
        1
        for case in cases
        if float((case.get("topic_scores") or {}).get("approval_control", 0.0)) >= 0.75
    )
    approval_high_ratio = (approval_high / approval_high_cases) if approval_high_cases else 0.0

    # 수용 기준 (post A1+A3, 14342 cases, multi-dataset 검증 후)
    # baseline (post-A1, baseline sort) vs composite (post-A1+A3, composite sort) 비교:
    #   sum Top200             96 -> 138
    #   approval_control:high  ratio: 9/489=1.84% -> 12/489=2.45%
    #   closing_timing all     16 -> 20
    #   revenue_statistical all 21 -> 20
    # multi-dataset 검증 (v126_profiled / v133_archive / manipulation_v2) 결과 v126_profiled 측정
    # 2.45% 를 통과시키되 0% 회귀를 차단할 안전 임계 ≥ 2.0% 채택. v133_archive (46.30%) /
    # manipulation_v2 (61.77%) 는 모집단 자체가 다른 데이터셋이므로 별도 audit 산출물 참조
    # (`artifacts/phase1_sort_composite_multi_dataset_lock.md`).
    assert all_band_sum >= 100, (
        f"7개 주제 합계 Top200 truth_doc = {all_band_sum} < 100 (§9.3 audit C3 권고)"
    )
    assert approval_high_ratio >= 0.02, (
        f"approval_control:high Top200 truth_doc / high_cases = "
        f"{approval_high}/{approval_high_cases} = {approval_high_ratio:.2%} < 2.0% "
        f"(v126_profiled 측정 = 2.45%, multi-dataset lock 임계 2.0%)"
    )
    assert closing_all >= 18, (
        f"closing_timing all-band Top200 truth_doc = {closing_all} < 18 "
        f"(post A1+A3 measured = 20, baseline = 16)"
    )
    # revenue_statistical 도메인 충돌 가드 — post-A1+A3 실측 20, baseline 21 (-1).
    # audit §4.2 손실 ≤5 한도 적용 시 ≥16 안전 임계.
    assert revenue_all >= 16, (
        f"revenue_statistical all-band Top200 truth_doc = {revenue_all} < 16 "
        f"(post A1+A3 measured = 20, baseline = 21, 도메인 충돌 가드 위반)"
    )
