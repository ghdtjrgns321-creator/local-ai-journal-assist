from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.detection.base import DetectionResult, RuleFlag
from src.detection.phase1_case_builder import build_phase1_case_result
from src.detection.rule_scoring import TOPIC_REGISTRY
from src.export.phase1_case_view import (
    PHASE1_RULE_DOCUMENT_RULES,
    build_phase1_audit_risk_by_queue,
    build_phase1_audit_risk_queue,
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    build_phase1_data_quality_gate,
    build_phase1_macro_finding_queue,
    build_phase1_raw_rule_truth_index,
    build_phase1_review_candidate_summary,
    build_phase1_rule_coverage,
    build_phase1_rule_document_counts,
    build_phase1_rule_document_detail,
    build_phase1_rule_documents,
    build_phase1_topic_top_n,
    build_phase1_transaction_queue,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
)
from src.models.phase1_unit import DocumentUnit

BANNED_LEGACY_LABELS = {
    "Audit Risk",
    "AUDIT RISK",
    "조작 후보",
    "맥락 검토대상",
    "추가검토사항",
    "우선 위험신호",
    "저우선 위험신호",
}


def _case(
    case_id: str,
    *,
    primary_topic: str = "duplicate_outflow",
    primary_queue: str | None = None,
    primary_queue_label: str = "",
    topic_scores: dict[str, float] | None = None,
    secondary_topics: list[str] | None = None,
    secondary_queues: list[str] | None = None,
    secondary_queue_labels: list[str] | None = None,
    fraud_scenario_tags: list[str] | None = None,
    priority_score: float = 0.5,
    triage_rank_score: float = 0.5,
    priority_band: str = "medium",
) -> CaseGroupResult:
    return CaseGroupResult(
        case_id=case_id,
        primary_topic=primary_topic,
        primary_theme=primary_topic,
        primary_queue=primary_queue if primary_queue is not None else primary_topic,
        primary_queue_label=primary_queue_label,
        topic_scores=topic_scores or {primary_topic: priority_score},
        secondary_topics=secondary_topics or [],
        secondary_queues=secondary_queues or [],
        secondary_queue_labels=secondary_queue_labels or [],
        fraud_scenario_tags=fraud_scenario_tags or [],
        case_key=case_id,
        priority_score=priority_score,
        priority_band=priority_band,
        triage_rank_score=triage_rank_score,
        document_count=1,
        row_count=1,
        rule_count=1,
        total_amount=1000.0,
        representative_explanation="case explanation",
        documents=[CaseDocumentRef(document_id=f"DOC-{case_id}", matched_rules=["L2-01"])],
        raw_rule_hits=[
            RawRuleHitRef(
                rule_id="L2-01",
                severity=4,
                document_id=f"DOC-{case_id}",
                row_index=0,
                score=priority_score,
                normalized_score=priority_score,
                evidence_type="duplicate_or_outflow",
            )
        ],
    )


def _phase1(cases: list[CaseGroupResult]) -> SimpleNamespace:
    result = Phase1CaseResult(
        run_id="topic-test",
        company_id="kr01",
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
        cases=cases,
    )
    return SimpleNamespace(phase1_case_result=result)


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


def test_summarize_phase1_case_result_exposes_only_seven_topic_labels() -> None:
    pipeline_result = _phase1(
        [_case(topic_id, primary_topic=topic_id, priority_score=0.5) for topic_id in TOPIC_REGISTRY]
    )

    summary = summarize_phase1_case_result(pipeline_result)

    expected_labels = [topic.label for topic in TOPIC_REGISTRY.values()]
    assert [row["topic_label"] for row in summary["topics"]] == expected_labels
    assert [row["queue_label"] for row in summary["queues"]] == expected_labels
    assert [row["theme_label"] for row in summary["themes"]] == expected_labels
    assert not (set(summary["top_queue_labels"]) & BANNED_LEGACY_LABELS)
    assert not (set(summary["top_theme_labels"]) & BANNED_LEGACY_LABELS)


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


def test_case_queue_and_topic_ranking_do_not_emit_banned_legacy_labels() -> None:
    pipeline_result = _phase1(
        [
            _case(
                "legacy",
                primary_topic="duplicate_outflow",
                primary_queue="manipulation_candidate",
                primary_queue_label="조작 후보",
                secondary_topics=["approval_control"],
                secondary_queues=["low_signal_candidate"],
                secondary_queue_labels=["저우선 위험신호"],
                topic_scores={"duplicate_outflow": 0.72, "approval_control": 0.31},
            )
        ]
    )

    queue_rows = build_phase1_case_queue(
        pipeline_result,
        queue_id="manipulation_candidate",
        top_n=10,
    )
    topic_rows = build_phase1_topic_top_n(
        pipeline_result,
        topic_id="duplicate_outflow",
        top_n=10,
    )
    grouped = build_phase1_audit_risk_by_queue(pipeline_result, top_n_per_queue=10)
    review = build_phase1_review_candidate_summary(pipeline_result)

    labels: set[str] = set()
    for row in [*queue_rows, *topic_rows]:
        labels.add(str(row["topic_label"]))
        labels.add(str(row["primary_topic_label"]))
        labels.add(str(row["primary_queue_label"]))
        labels.update(str(label) for label in row["secondary_queue_labels"])
    labels.update(str(queue["queue_label"]) for queue in grouped["queues"])
    labels.update(str(item["queue_label"]) for item in review["items"])

    assert not (labels & BANNED_LEGACY_LABELS)
    assert labels <= {topic.label for topic in TOPIC_REGISTRY.values()}


def test_build_phase1_case_queue_filters_by_issue_queue() -> None:
    pipeline_result = _make_pipeline_result()

    queue = build_phase1_case_queue(
        pipeline_result,
        queue_id="approval_control",
        top_n=10,
    )

    assert queue
    assert all(
        row["primary_queue"] == "approval_control" or "approval_control" in row["secondary_queues"]
        for row in queue
    )


def test_legacy_artifact_primary_queue_falls_back_to_locked_topic() -> None:
    pipeline_result = _phase1(
        [
            _case(
                "legacy-control",
                primary_topic="",
                primary_queue="control_approval",
                primary_queue_label="Audit Risk",
                topic_scores={},
                priority_score=0.67,
            )
        ]
    )

    queue = build_phase1_case_queue(
        pipeline_result,
        queue_id="control_approval",
        top_n=10,
    )
    summary = summarize_phase1_case_result(pipeline_result)

    assert queue[0]["topic_id"] == "approval_control"
    assert queue[0]["topic_score"] == 0.67
    assert queue[0]["primary_queue_label"] == TOPIC_REGISTRY["approval_control"].label
    assert summary["queues"][1]["queue_id"] == "approval_control"
    assert summary["queues"][1]["case_count"] == 1


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


def test_fraud_scenario_tags_are_badges_not_queue_labels() -> None:
    pipeline_result = _phase1(
        [
            _case(
                "fraud-tags",
                primary_topic="duplicate_outflow",
                topic_scores={"duplicate_outflow": 0.8},
                fraud_scenario_tags=[
                    "threshold_splitting",
                    "duplicate_payment",
                    "embezzlement_concealment_risk",
                ],
            )
        ]
    )

    queue = build_phase1_case_queue(pipeline_result, top_n=10)
    drilldown = build_phase1_case_drilldown(pipeline_result, "fraud-tags")
    summary = summarize_phase1_case_result(pipeline_result)

    assert queue[0]["fraud_scenario_tags"] == [
        "threshold_splitting",
        "duplicate_payment",
        "embezzlement_concealment_risk",
    ]
    assert drilldown is not None
    assert drilldown["case"]["fraud_scenario_tags"] == [
        "threshold_splitting",
        "duplicate_payment",
        "embezzlement_concealment_risk",
    ]
    queue_label_values = {row["queue_label"] for row in summary["queues"]}
    queue_label_values.add(queue[0]["primary_queue_label"])
    queue_label_values.update(queue[0]["secondary_queue_labels"])
    assert "threshold_splitting" not in queue_label_values
    assert "duplicate_payment" not in queue_label_values
    assert "embezzlement_concealment_risk" not in queue_label_values
    assert {row["queue_id"] for row in summary["queues"]} <= set(TOPIC_REGISTRY)
    assert len(summary["queues"]) <= 7


def test_topic_top_n_sorts_by_topic_score_not_priority_score() -> None:
    pipeline_result = _phase1(
        [
            _case(
                "higher-priority-lower-topic",
                primary_topic="duplicate_outflow",
                topic_scores={"duplicate_outflow": 0.4},
                priority_score=0.99,
                triage_rank_score=0.99,
            ),
            _case(
                "lower-priority-higher-topic",
                primary_topic="duplicate_outflow",
                topic_scores={"duplicate_outflow": 0.8},
                priority_score=0.2,
                triage_rank_score=0.2,
            ),
        ]
    )

    rows = build_phase1_topic_top_n(
        pipeline_result,
        topic_id="duplicate_outflow",
        top_n=10,
    )

    assert [row["case_id"] for row in rows] == [
        "lower-priority-higher-topic",
        "higher-priority-lower-topic",
    ]
    assert [row["topic_score"] for row in rows] == [0.8, 0.4]


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


def test_export_skips_row_violation_detail_for_non_transaction_surfaces() -> None:
    pipeline_result = _make_pipeline_result()
    blocked_rules = ("L4-02", "Benford", "D01", "D02", "GR01", "GR03")

    for rule_id in blocked_rules:
        pipeline_result.featured_data.loc[
            pipeline_result.featured_data["document_id"] == "DOC-1",
            "review_rules",
        ] = rule_id

        assert build_phase1_rule_documents(pipeline_result, rule_id) == []


def test_l308_context_badge_rule_still_renders_hit_documents() -> None:
    pipeline_result = _make_row_level_row_index_result("L3-08")

    rows = build_phase1_rule_documents(pipeline_result, "L3-08")

    assert len(rows) == 1
    assert rows[0]["document_id"] == "DOC-HIT-L3-08"
    assert rows[0]["line_number"] == 3
    assert rows[0]["violation_summary"] == "적요 누락 또는 손상"
    assert rows[0]["line_text"] == "L3-08 violation line"


def test_export_canonicalizes_l203_reason_codes_without_separate_detail_heading() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.featured_data.loc[
        pipeline_result.featured_data["document_id"] == "DOC-1",
        "review_rules",
    ] = "L2-03a"

    rows = build_phase1_rule_documents(pipeline_result, "L2-03a")
    detail = build_phase1_rule_document_detail(pipeline_result, "L2-03a", "DOC-1")

    assert rows
    assert detail is not None
    assert detail["rule_id"] == "L2-03"
    assert detail["requested_rule_id"] == "L2-03a"
    assert build_phase1_rule_documents(pipeline_result, "L2-03") == rows


def test_export_counts_l402_canonically_but_excludes_row_detail() -> None:
    case = _case("benford", primary_topic="ledger_integrity", priority_score=0.6)
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="Benford",
            severity=3,
            document_id="DOC-benford",
            row_index=0,
            score=0.6,
            normalized_score=0.6,
            evidence_type="statistical",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = pd.DataFrame(
        {
            "document_id": ["DOC-benford"],
            "review_rules": ["Benford"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        }
    )

    assert build_phase1_rule_document_counts(pipeline_result) == {"L4-02": 1}
    assert build_phase1_rule_documents(pipeline_result, "L4-02") == []
    assert build_phase1_rule_documents(pipeline_result, "Benford") == []


def test_export_keeps_transaction_detail_for_allowed_rules() -> None:
    pipeline_result = _make_pipeline_result()
    pipeline_result.featured_data.loc[
        pipeline_result.featured_data["document_id"] == "DOC-2",
        "review_rules",
    ] = "L4-03"

    rows = build_phase1_rule_documents(pipeline_result, "L4-03")

    assert rows
    assert rows[0]["violation_summary"]
    assert rows[0]["violation_details"]


def test_metadata_surface_overrides_stale_scoring_role_in_legacy_artifact() -> None:
    case = _case("stale-role", primary_topic="ledger_integrity", priority_score=0.6)
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="L4-02",
            severity=3,
            document_id="DOC-stale-role",
            row_index=0,
            score=0.6,
            normalized_score=0.6,
            scoring_role="primary",
            evidence_type="statistical",
        )
    ]
    pipeline_result = _phase1([case])

    drilldown = build_phase1_case_drilldown(pipeline_result, "stale-role")

    assert drilldown is not None
    assert drilldown["raw_rule_hits"][0]["signal_type"] == "macro_finding"


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


def _make_row_level_row_index_result(rule_id: str) -> SimpleNamespace:
    hit_doc_id = f"DOC-HIT-{rule_id}"
    stale_doc_id = f"DOC-STALE-{rule_id}"
    df = pd.DataFrame(
        {
            "document_id": [hit_doc_id, hit_doc_id, hit_doc_id, stale_doc_id],
            "line_number": [1, 2, 3, 1],
            "posting_date": pd.to_datetime(["2026-04-30"] * 4),
            "document_date": pd.to_datetime(
                ["2026-04-30", "2026-04-30", "2026-04-27", "2026-04-30"]
            ),
            "approval_date": [None, None, None, None],
            "fiscal_period": [4, 4, 4, 4],
            "created_by": ["kim", "kim", "kim", "lee"],
            "business_process": ["R2R", "R2R", "R2R", "P2P"],
            "gl_account": ["100000", "200000", "999999", "777777"],
            "debit_amount": [100.0, 0.0, 777.0, 900.0],
            "credit_amount": [0.0, 100.0, 0.0, 0.0],
            "local_amount": [100.0, 100.0, 777.0, 900.0],
            "amount": [100.0, 100.0, 777.0, 900.0],
            "company_code": ["kr01", "kr01", "kr01", "kr01"],
            "document_type": ["SA", "SA", "SA", "SA"],
            "line_text": [
                "normal debit",
                "normal credit",
                f"{rule_id} violation line",
                "stale flagged line",
            ],
            "description": [
                "normal debit",
                "normal credit",
                f"{rule_id} violation line",
                "stale flagged line",
            ],
            "anomaly_score": [0.0, 0.0, 0.91, 0.99],
            "flagged_rules": ["", "", "", rule_id],
            "review_rules": ["", "", "", ""],
        }
    )
    case = _case(f"row-hit-{rule_id}", primary_topic="account_logic", priority_score=0.8)
    case.documents = [
        CaseDocumentRef(document_id=hit_doc_id, matched_rules=[rule_id], amount=777.0)
    ]
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id=rule_id,
            severity=5,
            document_id=hit_doc_id,
            row_index=2,
            score=0.9,
            normalized_score=0.9,
            evidence_type="account_logic",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = df
    return pipeline_result


@pytest.mark.parametrize(
    "rule_id",
    [
        "L1-02",
        "L1-03",
        "L2-04",
        "L3-03",
        "L3-05",
        "L3-06",
        "L3-08",
        "L3-07",
        "L3-09",
        "L3-10",
        "L3-12",
        "L4-01",
        "L4-03",
        "L4-04",
        "L4-05",
        "L4-06",
    ],
)
def test_row_level_rule_documents_use_raw_hit_row_index_for_representative_record(
    rule_id: str,
) -> None:
    pipeline_result = _make_row_level_row_index_result(rule_id)

    rows = build_phase1_rule_documents(pipeline_result, rule_id)

    assert len(rows) == 1
    assert rows[0]["document_id"] == f"DOC-HIT-{rule_id}"
    assert rows[0]["line_number"] == 3
    assert rows[0]["gl_account"] == "999999"
    assert rows[0]["amount"] == 777.0
    assert rows[0]["debit_amount"] == 777.0
    assert rows[0]["credit_amount"] == 0.0
    assert rows[0]["line_text"] == f"{rule_id} violation line"
    assert rows[0]["description"] == f"{rule_id} violation line"


def test_rule_documents_ignore_stale_flagged_rules_when_raw_truth_exists() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-TRUTH", "DOC-TRUTH", "DOC-STALE"],
            "line_number": [1, 2, 1],
            "posting_date": pd.to_datetime(["2026-04-30"] * 3),
            "document_date": pd.to_datetime(["2026-04-30"] * 3),
            "fiscal_period": [4, 4, 4],
            "created_by": ["kim", "kim", "lee"],
            "business_process": ["R2R", "R2R", "P2P"],
            "gl_account": ["100000", "888888", "777777"],
            "debit_amount": [100.0, 250.0, 900.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "local_amount": [100.0, 250.0, 900.0],
            "company_code": ["kr01", "kr01", "kr01"],
            "document_type": ["SA", "SA", "SA"],
            "line_text": ["normal", "truth hit", "stale flag"],
            "flagged_rules": ["", "", "L1-03"],
            "review_rules": ["", "", ""],
        }
    )
    case = _case("truth-only", primary_topic="account_logic", priority_score=0.8)
    case.documents = [
        CaseDocumentRef(document_id="DOC-TRUTH", matched_rules=["L1-03"], amount=250.0)
    ]
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="L1-03",
            severity=5,
            document_id="DOC-TRUTH",
            row_index=1,
            score=0.9,
            normalized_score=0.9,
            evidence_type="account_logic",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = df

    rows = build_phase1_rule_documents(pipeline_result, "L1-03")

    assert [row["document_id"] for row in rows] == ["DOC-TRUTH"]
    assert rows[0]["gl_account"] == "888888"


def test_raw_rule_truth_index_excludes_stale_flags_and_includes_truth_only_hits() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-TRUTH", "DOC-TRUTH", "DOC-STALE"],
            "line_number": [1, 2, 1],
            "flagged_rules": ["", "", "L1-03"],
            "review_rules": ["", "", ""],
        }
    )
    case = _case("truth-index", primary_topic="account_logic", priority_score=0.8)
    case.documents = [
        CaseDocumentRef(document_id="DOC-TRUTH", matched_rules=["L1-03"], amount=250.0)
    ]
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="L1-03",
            severity=5,
            document_id="DOC-TRUTH",
            row_index=1,
            score=0.9,
            normalized_score=0.9,
            evidence_type="account_logic",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = df

    truth = build_phase1_raw_rule_truth_index(pipeline_result)

    assert truth["available"] is True
    assert truth["rules"] == ["L1-03"]
    assert truth["rule_document_ids"] == {"L1-03": {"DOC-TRUTH"}}
    assert truth["rule_row_indices"] == {"L1-03": {1}}
    assert truth["document_rule_ids"] == {"DOC-TRUTH": {"L1-03"}}


def test_document_level_rule_documents_keep_document_totals() -> None:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-L101", "DOC-L101", "DOC-L108", "DOC-L108"],
            "line_number": [1, 2, 1, 2],
            "posting_date": pd.to_datetime(
                ["2026-04-30", "2026-04-30", "2026-04-30", "2026-04-30"]
            ),
            "document_date": pd.to_datetime(
                ["2026-04-30", "2026-04-30", "2026-04-30", "2026-04-30"]
            ),
            "fiscal_period": [4, 4, 3, 3],
            "created_by": ["kim"] * 4,
            "business_process": ["R2R"] * 4,
            "gl_account": ["100000", "200000", "300000", "400000"],
            "debit_amount": [100.0, 0.0, 10.0, 20.0],
            "credit_amount": [0.0, 90.0, 0.0, 0.0],
            "local_amount": [100.0, 90.0, 10.0, 20.0],
            "company_code": ["kr01"] * 4,
            "document_type": ["SA"] * 4,
            "flagged_rules": ["", "", "", ""],
            "review_rules": ["", "", "", ""],
        }
    )
    case_l101 = _case("doc-l101", primary_topic="ledger_integrity", priority_score=0.8)
    case_l101.documents = [
        CaseDocumentRef(document_id="DOC-L101", matched_rules=["L1-01"], amount=100.0)
    ]
    case_l101.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="L1-01",
            severity=5,
            document_id="DOC-L101",
            row_index=0,
            score=0.9,
            normalized_score=0.9,
            evidence_type="data_integrity_failure",
        )
    ]
    case_l108 = _case("doc-l108", primary_topic="closing_timing", priority_score=0.8)
    case_l108.documents = [
        CaseDocumentRef(document_id="DOC-L108", matched_rules=["L1-08"], amount=30.0)
    ]
    case_l108.raw_rule_hits = [
        RawRuleHitRef(
            rule_id="L1-08",
            severity=5,
            document_id="DOC-L108",
            row_index=2,
            score=0.9,
            normalized_score=0.9,
            evidence_type="data_integrity_failure",
        )
    ]
    pipeline_result = _phase1([case_l101, case_l108])
    pipeline_result.featured_data = df

    l101 = build_phase1_rule_documents(pipeline_result, "L1-01")[0]
    l108 = build_phase1_rule_documents(pipeline_result, "L1-08")[0]

    assert l101["amount"] == 100.0
    assert l101["debit_amount"] == 100.0
    assert l101["credit_amount"] == 90.0
    assert l108["amount"] == 30.0


def _make_document_amount_policy_result(rule_id: str) -> SimpleNamespace:
    df = pd.DataFrame(
        {
            "document_id": ["DOC-AMOUNT", "DOC-AMOUNT"],
            "line_number": [1, 2],
            "posting_date": pd.to_datetime(["2026-04-30", "2026-04-30"]),
            "document_date": pd.to_datetime(["2026-04-30", "2026-04-30"]),
            "approval_date": [None, None],
            "fiscal_period": [4, 4],
            "created_by": ["kim", "kim"],
            "approved_by": ["kim" if rule_id == "L1-05" else None] * 2,
            "business_process": ["R2R", "R2R"],
            "gl_account": ["100000", "200000"],
            "debit_amount": [10.0, 40.0],
            "credit_amount": [0.0, 0.0],
            "local_amount": [10.0, 40.0],
            "approval_limit": [30.0, 30.0],
            "company_code": ["kr01", "kr01"],
            "document_type": ["SA", "SA"],
            "flagged_rules": ["", ""],
            "review_rules": ["", ""],
        }
    )
    case = _case(f"doc-amount-{rule_id}", primary_topic="approval_control", priority_score=0.8)
    case.documents = [
        CaseDocumentRef(document_id="DOC-AMOUNT", matched_rules=[rule_id], amount=50.0)
    ]
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id=rule_id,
            severity=5,
            document_id="DOC-AMOUNT",
            row_index=0,
            score=0.9,
            normalized_score=0.9,
            evidence_type="control_failure",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = df
    return pipeline_result


def test_approval_document_level_rules_use_document_amount_policy() -> None:
    for rule_id in ("L1-04", "L1-05", "L1-07", "L2-01"):
        rows = build_phase1_rule_documents(
            _make_document_amount_policy_result(rule_id),
            rule_id,
        )

        assert len(rows) == 1
        assert rows[0]["amount"] == 50.0, rule_id
        assert rows[0]["evidence_amount"] == 50.0, rule_id
        assert rows[0]["debit_amount"] == 50.0, rule_id
        assert rows[0]["credit_amount"] == 0.0, rule_id


def test_document_level_difference_values_use_document_amount_policy() -> None:
    l104 = build_phase1_rule_documents(
        _make_document_amount_policy_result("L1-04"),
        "L1-04",
    )[0]
    l201 = build_phase1_rule_documents(
        _make_document_amount_policy_result("L2-01"),
        "L2-01",
    )[0]

    assert l104["difference_value"] == 20.0
    assert l201["difference_value"] == 50.0 / 30.0


def _detail_map(row: dict) -> dict[str, object]:
    return {str(item["label"]): item.get("value") for item in row.get("violation_details", [])}


def _make_pair_group_result(rule_id: str, fields: dict[str, object]) -> SimpleNamespace:
    row = {
        "document_id": "DOC-PAIR-A",
        "line_number": 1,
        "posting_date": pd.Timestamp("2026-04-30"),
        "document_date": pd.Timestamp("2026-04-29"),
        "fiscal_period": 4,
        "created_by": "kim",
        "business_process": "R2R",
        "gl_account": "210000",
        "debit_amount": 120.0,
        "credit_amount": 0.0,
        "local_amount": 120.0,
        "company_code": "kr01",
        "document_type": "SA",
        "counterparty": "Vendor A",
        "reference": "INV-100",
        "flagged_rules": "",
        "review_rules": "",
    }
    row.update(fields)
    df = pd.DataFrame([row])
    case = _case(f"pair-{rule_id}", primary_topic="duplicate_outflow", priority_score=0.8)
    case.documents = [
        CaseDocumentRef(document_id="DOC-PAIR-A", matched_rules=[rule_id], amount=120.0)
    ]
    case.raw_rule_hits = [
        RawRuleHitRef(
            rule_id=rule_id,
            severity=5,
            document_id="DOC-PAIR-A",
            row_index=0,
            score=0.9,
            normalized_score=0.9,
            evidence_type="duplicate_or_outflow",
        )
    ]
    pipeline_result = _phase1([case])
    pipeline_result.featured_data = df
    return pipeline_result


def test_l202_pair_group_evidence_exposes_matched_document() -> None:
    row = build_phase1_rule_documents(
        _make_pair_group_result(
            "L2-02",
            {
                "matched_document_id": "DOC-PAIR-B",
                "duplicate_group_id": "PAY-GRP-1",
                "matched_amount": 120.0,
                "day_gap": 2,
            },
        ),
        "L2-02",
    )[0]

    details = _detail_map(row)
    assert details["Matched document"] == "DOC-PAIR-B"
    assert details["Duplicate group"] == "PAY-GRP-1"
    assert details["Matched amount"] == 120.0
    assert details["Date gap"] == 2


def test_l203_pair_group_evidence_exposes_signature_group_and_reason() -> None:
    row = build_phase1_rule_documents(
        _make_pair_group_result(
            "L2-03a",
            {
                "duplicate_group_id": "JRN-GRP-1",
                "duplicate_signature": "kr01|2026-04-30|210000|120",
                "internal_reason_code": "L2-03a",
                "matched_reason_codes": "exact_duplicate,reference_duplicate",
            },
        ),
        "L2-03a",
    )[0]

    details = _detail_map(row)
    assert details["Duplicate group"] == "JRN-GRP-1"
    assert details["Duplicate signature"] == "kr01|2026-04-30|210000|120"
    assert details["Reason code"] == "L2-03a"
    assert details["Matched reasons"] == "exact_duplicate,reference_duplicate"


def test_l205_pair_group_evidence_exposes_reversal_pair_fields() -> None:
    row = build_phase1_rule_documents(
        _make_pair_group_result(
            "L2-05",
            {
                "reversal_pair_id": "REV-1",
                "matched_document_id": "DOC-REV-B",
                "date_gap_days": 1,
                "amount_match": True,
                "matched_amount": 120.0,
            },
        ),
        "L2-05",
    )[0]

    details = _detail_map(row)
    assert details["Reversal pair"] == "REV-1"
    assert details["Matched document"] == "DOC-REV-B"
    assert details["Date gap"] == 1
    assert details["Amount match"] is True
    assert details["Matched amount"] == 120.0


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
        "L2-01",
        "L2-02",
        "L2-03",
        "L2-03a",
        "L2-03b",
        "L2-03c",
        "L2-03d",
        "L2-04",
        "L2-05",
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
        Path(
            "C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.tmp_phase1_case_view_tests/missing.json"
        )
    )

    loaded = resolve_phase1_case_result(pipeline_result)

    assert loaded is None


# ── P3: Phase 1 case basis classifier 단위 테스트 ───────────────


from src.export.phase1_case_view import (  # noqa: E402
    Phase1CaseBasisStatus,
    classify_phase1_case_basis,
)


def _phase1_with_cases() -> Phase1CaseResult:
    """기존 _make_pipeline_result() 가 만드는 phase1 case result 와 동등."""
    return _make_pipeline_result().phase1_case_result


def test_classify_returns_canonical_in_memory_when_cases_present() -> None:
    phase1_result = SimpleNamespace(phase1_case_result=_phase1_with_cases())
    basis = classify_phase1_case_basis(phase1_result)
    assert basis.status == Phase1CaseBasisStatus.CANONICAL_IN_MEMORY
    assert basis.case_result is phase1_result.phase1_case_result
    assert basis.metadata.get("case_count") == len(phase1_result.phase1_case_result.cases)


def test_classify_returns_canonical_artifact_when_lazy_load_succeeds(tmp_path) -> None:
    phase1 = _phase1_with_cases()
    artifact_path = tmp_path / "phase1_case.json"
    artifact_path.write_text(
        phase1.__pydantic_serializer__.to_json(phase1).decode("utf-8"),
        encoding="utf-8",
    )
    phase1_result = SimpleNamespace(
        phase1_case_path=str(artifact_path),
        phase1_case_count=len(phase1.cases),
    )
    basis = classify_phase1_case_basis(phase1_result)
    assert basis.status == Phase1CaseBasisStatus.CANONICAL_ARTIFACT
    assert basis.case_result is not None
    assert len(basis.case_result.cases) == len(phase1.cases)
    assert basis.metadata.get("artifact_path") == str(artifact_path)


def test_classify_returns_fallback_redetect_when_artifact_missing_but_redetect_has_cases(
    tmp_path,
) -> None:
    redetect = SimpleNamespace(phase1_case_result=_phase1_with_cases())
    phase1_result = SimpleNamespace(
        phase1_case_path=str(tmp_path / "missing.json"),
        phase1_case_count=3,
    )
    basis = classify_phase1_case_basis(phase1_result, redetect_result=redetect)
    # missing artifact → load 시도하면 exception 발생 → fallback (redetect cases 있음)
    # OR missing path 인 경우 load_phase1_case_result 가 raise → ARTIFACT_ERROR 분기에서
    # redetect 가 있으면 FALLBACK_REDETECT 로 분류
    assert basis.status == Phase1CaseBasisStatus.FALLBACK_REDETECT
    assert basis.case_result is redetect.phase1_case_result


def test_classify_returns_artifact_error_when_load_fails_and_no_fallback(tmp_path) -> None:
    phase1_result = SimpleNamespace(
        phase1_case_path=str(tmp_path / "missing.json"),
        phase1_case_count=2,
    )
    basis = classify_phase1_case_basis(phase1_result, redetect_result=None)
    assert basis.status == Phase1CaseBasisStatus.ARTIFACT_ERROR
    assert basis.case_result is None
    assert "missing.json" in basis.metadata.get("artifact_path", "")


def test_classify_returns_metadata_only_when_no_artifact_and_no_fallback() -> None:
    phase1_result = SimpleNamespace(phase1_case_count=5)
    basis = classify_phase1_case_basis(phase1_result, redetect_result=None)
    assert basis.status == Phase1CaseBasisStatus.METADATA_ONLY
    assert basis.case_result is None
    assert basis.metadata.get("phase1_case_count") == 5


def test_classify_returns_unavailable_when_phase1_result_is_none() -> None:
    basis = classify_phase1_case_basis(None, redetect_result=None)
    assert basis.status == Phase1CaseBasisStatus.UNAVAILABLE
    assert basis.case_result is None


def test_classify_returns_fallback_when_phase1_none_but_redetect_has_cases() -> None:
    redetect = SimpleNamespace(phase1_case_result=_phase1_with_cases())
    basis = classify_phase1_case_basis(None, redetect_result=redetect)
    assert basis.status == Phase1CaseBasisStatus.FALLBACK_REDETECT
    assert basis.case_result is redetect.phase1_case_result


# ── unit 단위 검토 큐 + 룰별 커버리지 (UNIT_MEASUREMENT_POLICY §1 Layer 1) ──


def _unit_evidence(rule_id: str, document_id: str, row_index: int) -> RawRuleHitRef:
    return RawRuleHitRef(
        rule_id=rule_id,
        severity=4,
        document_id=document_id,
        row_index=row_index,
        evidence_type="duplicate_or_outflow",
    )


def _document_unit(
    unit_id: str,
    *,
    priority_band: str,
    rule_ids: list[str],
    total_amount: float = 1000.0,
    time_severity_score: int = 0,
    triage_rank_score: float = 0.5,
    topic_scores: dict[str, float] | None = None,
) -> DocumentUnit:
    return DocumentUnit(
        unit_id=unit_id,
        priority_band=priority_band,
        triage_rank_score=triage_rank_score,
        total_amount=total_amount,
        time_severity_score=time_severity_score,
        topic_scores=topic_scores or {"duplicate_outflow": 0.9},
        evidence_rows=[
            _unit_evidence(rule_id, unit_id, idx) for idx, rule_id in enumerate(rule_ids)
        ],
    )


def _phase1_with_units(units: list[object]) -> SimpleNamespace:
    # resolve_phase1_case_result 는 cases 가 비면 placeholder 로 보고 None 을 반환하므로
    # 최소 1개 placeholder case 를 둔다. 큐·커버리지의 축은 units 다(case 는 미사용).
    result = Phase1CaseResult(
        run_id="unit-test",
        company_id="kr01",
        generated_at=datetime(2026, 4, 22, 3, 15, 22, tzinfo=UTC),
        cases=[_case("placeholder")],
        units=units,
    )
    return SimpleNamespace(phase1_case_result=result)


def test_transaction_queue_excludes_low_units_keeps_high_and_medium() -> None:
    # 정책: HIGH/MEDIUM tier unit 만 큐에 1줄씩. LOW 는 제외(커버리지 표로만 surface).
    pr = _phase1_with_units(
        [
            _document_unit("DOC-HIGH", priority_band="high", rule_ids=["L2-02"]),
            _document_unit("DOC-MED", priority_band="medium", rule_ids=["L2-02"]),
            _document_unit("DOC-LOW", priority_band="low", rule_ids=["L2-02"]),
        ]
    )

    rows = build_phase1_transaction_queue(pr)

    unit_ids = {row["unit_id"] for row in rows}
    # 빈 큐 PASS 금지 — HIGH/MEDIUM 최소 2줄 기대.
    assert len(rows) == 2
    assert "DOC-HIGH" in unit_ids
    assert "DOC-MED" in unit_ids
    assert "DOC-LOW" not in unit_ids
    bands = {row["unit_id"]: row["priority_band"] for row in rows}
    assert bands["DOC-HIGH"] == "high"
    assert bands["DOC-MED"] == "medium"


def test_transaction_queue_orders_high_before_medium() -> None:
    # band 컷·정렬은 _band_rank 경유. HIGH 가 MEDIUM 보다 먼저.
    pr = _phase1_with_units(
        [
            _document_unit("DOC-MED", priority_band="medium", rule_ids=["L2-02"]),
            _document_unit("DOC-HIGH", priority_band="high", rule_ids=["L2-02"]),
        ]
    )

    rows = build_phase1_transaction_queue(pr)

    assert [row["unit_id"] for row in rows] == ["DOC-HIGH", "DOC-MED"]


def test_transaction_queue_time_severity_outranks_amount_within_band() -> None:
    # 정책: 동일 band·triage 에서 time_severity 가 금액보다 위(anti-burying).
    pr = _phase1_with_units(
        [
            _document_unit(
                "DOC-BIG-AMOUNT",
                priority_band="high",
                rule_ids=["L2-02"],
                total_amount=9_999_999.0,
                time_severity_score=0,
                triage_rank_score=0.5,
            ),
            _document_unit(
                "DOC-OFFTIME",
                priority_band="high",
                rule_ids=["L2-02"],
                total_amount=1.0,
                time_severity_score=2,
                triage_rank_score=0.5,
            ),
        ]
    )

    rows = build_phase1_transaction_queue(pr)

    assert [row["unit_id"] for row in rows] == ["DOC-OFFTIME", "DOC-BIG-AMOUNT"]


def test_rule_coverage_counts_all_units_and_only_standalone_primary() -> None:
    # 정책: 모든 unit(HIGH/MEDIUM/LOW) 의 evidence_rows 를 룰별 전수 집계.
    # 행 대상 = standalone primary 룰만. booster(L3-05) 는 제외.
    pr = _phase1_with_units(
        [
            _document_unit("DOC-A", priority_band="high", rule_ids=["L2-02", "L3-05"]),
            _document_unit("DOC-B", priority_band="medium", rule_ids=["L2-02"]),
            _document_unit("DOC-C", priority_band="low", rule_ids=["L2-02"]),
        ]
    )

    coverage = build_phase1_rule_coverage(pr)

    assert coverage["available"] is True
    items = {item["rule_id"]: item for item in coverage["items"]}
    # 빈 커버리지 PASS 금지 — standalone primary 룰 L2-02 최소 1행.
    assert "L2-02" in items
    # booster L3-05 는 커버리지 행 대상이 아님(standalone_rankable=False).
    assert "L3-05" not in items
    l202 = items["L2-02"]
    # 3개 document 모두에서 L2-02 발화 → distinct document 3.
    assert l202["documents"] == 3
    # tier 분해: HIGH unit 1, MEDIUM unit 1, LOW unit 1.
    assert l202["high"] == 1
    assert l202["medium"] == 1
    assert l202["low"] == 1


def test_rule_coverage_includes_high_unit_rule_firing_in_document_count() -> None:
    # 정책: HIGH unit 의 룰 발화도 documents 카운트에 포함(tier 무관 전수).
    pr = _phase1_with_units(
        [
            _document_unit("DOC-HIGH", priority_band="high", rule_ids=["L2-02"]),
        ]
    )

    coverage = build_phase1_rule_coverage(pr)

    items = {item["rule_id"]: item for item in coverage["items"]}
    assert items["L2-02"]["documents"] == 1
    assert items["L2-02"]["high"] == 1
