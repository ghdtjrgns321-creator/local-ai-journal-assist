from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

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
    build_phase1_review_candidate_summary,
    build_phase1_rule_document_counts,
    build_phase1_rule_document_detail,
    build_phase1_rule_documents,
    build_phase1_topic_top_n,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
)

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
    pipeline_result = _phase1([
        _case(topic_id, primary_topic=topic_id, priority_score=0.5)
        for topic_id in TOPIC_REGISTRY
    ])

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
    pipeline_result = _phase1([
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
    ])

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
        queue_id="control_approval",
        top_n=10,
    )

    assert queue
    assert all(
        row["primary_queue"] == "control_approval"
        or "control_approval" in row["secondary_queues"]
        for row in queue
    )


def test_legacy_artifact_primary_queue_falls_back_to_locked_topic() -> None:
    pipeline_result = _phase1([
        _case(
            "legacy-control",
            primary_topic="",
            primary_queue="control_approval",
            primary_queue_label="Audit Risk",
            topic_scores={},
            priority_score=0.67,
        )
    ])

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
    pipeline_result = _phase1([
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
    ])

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
    pipeline_result = _phase1([
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
    ])

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
