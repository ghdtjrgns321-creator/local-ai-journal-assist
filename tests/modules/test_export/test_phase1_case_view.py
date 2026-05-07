from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result
from src.export.phase1_case_view import (
    PHASE1_RULE_DOCUMENT_RULES,
    build_phase1_audit_risk_by_queue,
    build_phase1_audit_risk_queue,
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    build_phase1_data_quality_gate,
    build_phase1_macro_finding_queue,
    build_phase1_review_candidate_summary,
    build_phase1_rule_document_detail,
    build_phase1_rule_documents,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)


def _make_pipeline_result() -> SimpleNamespace:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-1", "DOC-2"],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-28"]),
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
    details = pd.DataFrame(
        {
            "L1-05": [0.8, 0.0],
            "L1-07": [0.8, 0.0],
            "L1-08": [0.0, 0.9],
            "L3-04": [0.0, 0.6],
        },
        index=df.index,
    )
    detection_result = DetectionResult(
        track_name="layer_b",
        flagged_indices=[0, 1],
        scores=details.max(axis=1),
        rule_flags=[
            RuleFlag("L1-05", "SelfApproval", 4, 1, len(df)),
            RuleFlag("L1-07", "SkippedApproval", 4, 1, len(df)),
            RuleFlag("L1-08", "PeriodMismatch", 5, 1, len(df)),
            RuleFlag("L3-04", "PeriodEndClosingReview", 3, 1, len(df)),
        ],
        details=details,
        metadata={},
    )
    phase1 = build_phase1_case_result(
        df,
        [detection_result],
        company_id="kr01",
        batch_id="batch42",
        dataset_id=None,
        phase1_case_config={"phase1_case": {"top_n_cases": 50, "top_n_per_theme": 10}},
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
    )
    phase1.metadata["macro_findings"] = [
        {
            "finding_id": "L4-02:0001",
            "rule_id": "L4-02",
            "queue_type": "account_process_macro",
            "company_code": "kr01",
            "gl_account": "410000",
            "review_score": 0.8,
        }
    ]
    phase1.metadata["macro_finding_count"] = 1
    artifact_root = Path(
        "C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_view_tests"
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / "phase1_case.json"
    artifact_path.write_text(phase1.model_dump_json(indent=2), encoding="utf-8")
    low_signal_df = pd.concat(
        [
            df.assign(risk_level="Medium", anomaly_score=0.4, flagged_rules="", review_rules=""),
            pd.DataFrame(
                {
                    "document_id": ["DOC-3"],
                    "posting_date": pd.to_datetime(["2026-04-29"]),
                    "created_by": ["park"],
                    "business_process": ["A2R"],
                    "gl_account": ["510000"],
                    "debit_amount": [3_000_000.0],
                    "credit_amount": [0.0],
                    "auxiliary_account_number": ["V002"],
                    "company_code": ["kr01"],
                    "document_type": ["SA"],
                    "risk_level": ["Normal"],
                    "anomaly_score": [0.09],
                    "flagged_rules": ["L3-02"],
                    "review_rules": ["L3-12"],
                }
            ),
        ],
        ignore_index=True,
    )
    return SimpleNamespace(
        data=low_signal_df,
        featured_data=low_signal_df,
        phase1_case_result=phase1,
        phase1_case_path=str(artifact_path),
        phase1_case_run_id=phase1.run_id,
        phase1_case_count=len(phase1.cases),
        phase1_top_theme_ids=[theme.theme_id for theme in phase1.theme_summaries[:3]],
    )


def test_summarize_phase1_case_result_returns_theme_summary() -> None:
    pipeline_result = _make_pipeline_result()

    summary = summarize_phase1_case_result(pipeline_result)

    assert summary["available"] is True
    assert summary["run_id"] == pipeline_result.phase1_case_run_id
    assert summary["case_count"] == pipeline_result.phase1_case_count
    assert summary["macro_finding_count"] == 1
    assert summary["macro_findings"][0]["rule_id"] == "L4-02"
    assert summary["top_theme_labels"]
    assert summary["themes"]
    assert summary["queues"]
    assert summary["top_queue_labels"]


def test_build_phase1_case_queue_and_drilldown_return_projection_rows() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_case_queue(pipeline_result, top_n=1)
    drilldown = build_phase1_case_drilldown(pipeline_result, queue[0]["case_id"])

    assert len(queue) == 1
    assert queue[0]["primary_theme_label"]
    assert queue[0]["primary_queue"]
    assert queue[0]["primary_queue_label"]
    assert "triage_rank_score" in queue[0]
    assert "triage_rank_reasons" in queue[0]
    assert queue[0]["representative_explanation"]
    assert "base_priority_score" in queue[0]
    assert "topside_bonus" in queue[0]
    assert "batch_combo_bonus" in queue[0]
    assert "weak_evidence_bonus" in queue[0]
    assert "priority_adjustment_reasons" in queue[0]
    assert "direct_risk_count" in queue[0]
    assert "review_context_count" in queue[0]
    assert "integrity_blocker_count" in queue[0]
    assert "macro_finding_count" in queue[0]
    assert queue[0]["case_type"]
    assert queue[0]["main_reason"]
    assert drilldown is not None
    assert drilldown["case"]["case_id"] == queue[0]["case_id"]
    assert drilldown["documents"]
    assert drilldown["raw_rule_hits"]
    assert "signal_sections" in drilldown
    assert "direct_risk" in drilldown["signal_sections"]
    assert drilldown["raw_rule_hits"][0]["signal_type"]
    assert drilldown["raw_rule_hits"][0]["signal_type_label"]


def test_build_phase1_case_queue_filters_by_issue_queue() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_case_queue(
        pipeline_result,
        queue_id="control_approval",
        top_n=10,
    )

    assert queue
    assert all(
        row["primary_queue"] == "control_approval"
        or "control_approval" in row["secondary_queues"]
        for row in queue
    )


def test_build_phase1_case_queue_returns_low_signal_candidates_separately() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_case_queue(
        pipeline_result,
        queue_id="low_signal_candidate",
        top_n=10,
    )
    drilldown = build_phase1_case_drilldown(pipeline_result, queue[0]["case_id"])

    assert len(queue) == 1
    assert queue[0]["case_key"] == "DOC-3"
    assert queue[0]["primary_queue"] == "low_signal_candidate"
    assert queue[0]["priority_band"] == "low"
    assert "not_mixed_into_main_queue" in queue[0]["triage_rank_reasons"]
    assert drilldown is not None
    assert drilldown["case"]["case_id"] == queue[0]["case_id"]


def test_build_phase1_data_quality_gate_returns_work_items() -> None:
    pipeline_result = _make_pipeline_result()

    gate = build_phase1_data_quality_gate(pipeline_result)

    assert gate["available"] is True
    assert gate["items"]
    assert any(item["rule_id"] == "L1-07" for item in gate["items"]) is False


def test_build_phase1_rule_documents_returns_master_detail_payload() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.featured_data.loc[
        pipeline_result.featured_data["document_id"] == "DOC-2",
        "review_rules",
    ] = "L1-08"

    rows = build_phase1_rule_documents(pipeline_result, "L1-08")

    assert rows
    row = rows[0]
    assert row["violation_summary"]
    assert row["violation_details"]
    assert {item["label"] for item in row["violation_details"]} >= {
        "전기일 월",
        "회계기간",
        "기간 차이",
    }
    assert row["evidence_summary"] == row["violation_summary"]
    assert "expected_value" in row
    assert "actual_value" in row
    assert "difference_value" in row


def test_build_phase1_rule_document_detail_returns_raw_lines() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.featured_data.loc[
        pipeline_result.featured_data["document_id"] == "DOC-2",
        "review_rules",
    ] = "L1-08"

    detail = build_phase1_rule_document_detail(pipeline_result, "L1-08", "DOC-2")

    assert detail is not None
    assert detail["document_id"] == "DOC-2"
    assert detail["violation_summary"]
    assert detail["violation_details"]
    assert detail["raw_lines"]
    assert detail["raw_lines"][0]["document_id"] == "DOC-2"


def test_phase1_rule_document_builders_cover_all_current_rules() -> None:
    current_rules = {
        "L1-01",
        "L1-02",
        "L1-03",
        "L1-04",
        "L1-05",
        "L1-06",
        "L1-07",
        "L1-08",
        "L1-09",
        "L2-01",
        "L2-02",
        "L2-03",
        "L2-03a",
        "L2-03b",
        "L2-03c",
        "L2-03d",
        "L2-04",
        "L2-05",
        "L3-01",
        "L3-02",
        "L3-03",
        "L3-04",
        "L3-05",
        "L3-06",
        "L3-07",
        "L3-08",
        "L3-09",
        "L3-10",
        "L3-11",
        "L3-12",
        "L4-01",
        "L4-02",
        "L4-03",
        "L4-04",
        "L4-05",
        "L4-06",
        "D01",
        "D02",
        "IC01",
        "IC02",
        "IC03",
    }

    assert current_rules <= PHASE1_RULE_DOCUMENT_RULES


def test_build_phase1_audit_risk_queue_excludes_data_quality_cases() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_audit_risk_queue(pipeline_result, top_n=10)

    assert queue
    assert all(row["primary_queue"] != "data_integrity" for row in queue)
    assert "queue_tiebreaker_score" in queue[0]
    assert "queue_tiebreaker_reasons" in queue[0]


def test_build_phase1_audit_risk_by_queue_returns_queue_ranked_items() -> None:
    pipeline_result = _make_pipeline_result()

    result = build_phase1_audit_risk_by_queue(pipeline_result, top_n_per_queue=2)

    assert result["available"] is True
    assert result["queues"]
    assert all(len(queue["items"]) <= 2 for queue in result["queues"])
    assert all("queue_tiebreaker_score" in queue["items"][0] for queue in result["queues"])


def test_build_phase1_review_candidate_summary_returns_type_distribution() -> None:
    pipeline_result = _make_pipeline_result()

    summary = build_phase1_review_candidate_summary(pipeline_result)

    assert summary["available"] is True
    assert summary["items"]
    assert all("queue_label" in row for row in summary["items"])


def test_build_phase1_macro_finding_queue_returns_account_process_rows() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_macro_finding_queue(pipeline_result, rule_id="L4-02")

    assert len(queue) == 1
    assert queue[0]["queue_type"] == "account_process_macro"
    assert queue[0]["gl_account"] == "410000"


def test_resolve_phase1_case_result_loads_from_artifact_when_memory_missing() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.phase1_case_result = None

    loaded = resolve_phase1_case_result(pipeline_result)

    assert loaded is not None
    assert loaded.run_id == pipeline_result.phase1_case_run_id
    assert loaded.cases


def test_resolve_phase1_case_result_returns_none_when_artifact_is_missing() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.phase1_case_result = None
    pipeline_result.phase1_case_path = str(
        Path("C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_view_tests/missing.json")
    )

    loaded = resolve_phase1_case_result(pipeline_result)

    assert loaded is None
