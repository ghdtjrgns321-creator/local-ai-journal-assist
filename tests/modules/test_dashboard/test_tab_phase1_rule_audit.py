from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dashboard.tab_phase1 import _phase1_rule_audit
from src.export.phase1_case_view import resolve_phase1_case_result, summarize_phase1_case_result
from src.models.phase1_case import (
    CaseDocumentRef,
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
    ThemeSummary,
)


def test_layer_d_detector_status_marks_d_rules_skipped() -> None:
    result = SimpleNamespace(
        results=[],
        detector_statuses=[
            {
                "track_name": "layer_d",
                "run_status": "skipped",
                "reason": "missing_historical_data",
            }
        ],
    )

    audit = _phase1_rule_audit(result)
    statuses = {row["rule_id"]: row["status"] for row in audit["rules"]}

    assert statuses["D01"] == "skipped"
    assert statuses["D02"] == "skipped"


def test_zero_flag_rule_flag_is_not_reported_as_generated() -> None:
    result = SimpleNamespace(
        results=[
            SimpleNamespace(
                rule_flags=[
                    SimpleNamespace(rule_id="D01", flagged_count=0),
                    SimpleNamespace(rule_id="L1-01", flagged_count=3),
                ],
                metadata={"skipped_rules": []},
            )
        ],
        detector_statuses=[],
    )

    audit = _phase1_rule_audit(result)
    statuses = {row["rule_id"]: row["status"] for row in audit["rules"]}
    counts = {row["rule_id"]: row["flag_count"] for row in audit["rules"]}

    assert statuses["D01"] == "no_match"
    assert statuses["L1-01"] == "generated"
    assert counts["L1-01"] == 3


def test_phase1_artifact_load_replaces_empty_placeholder() -> None:
    empty = Phase1CaseResult(
        run_id="empty",
        company_id="test",
        generated_at=datetime.now(UTC),
    )
    loaded = Phase1CaseResult(
        run_id="loaded",
        company_id="test",
        batch_id="batch_001",
        generated_at=datetime.now(UTC),
        theme_summaries=[
            ThemeSummary(
                theme_id="control_failure",
                theme_label="Control",
                case_count=1,
                high_count=1,
            )
        ],
        cases=[
            CaseGroupResult(
                case_id="case_001",
                primary_theme="control_failure",
                primary_queue="control_approval",
                case_key="user|process|month",
                priority_band="high",
                document_count=1,
                rule_count=1,
                documents=[
                    CaseDocumentRef(
                        document_id="D1",
                        matched_rules=["L1-05"],
                    )
                ],
                raw_rule_hits=[
                    RawRuleHitRef(
                        rule_id="L1-05",
                        severity=3,
                        document_id="D1",
                        row_index=0,
                        score=0.8,
                        normalized_score=0.8,
                        evidence_type="control_failure",
                    )
                ],
            )
        ],
    )
    artifact = Path(".tmp_phase1case_rule_audit_test.json")
    try:
        artifact.write_text(loaded.model_dump_json(), encoding="utf-8")
        result = SimpleNamespace(
            phase1_case_result=empty,
            phase1_case_path=str(artifact),
            phase1_case_count=1,
        )

        resolved = resolve_phase1_case_result(result)
        summary = summarize_phase1_case_result(result)

        assert resolved is result.phase1_case_result
        assert resolved.run_id == "loaded"
        assert summary["metadata_only"] is False
        assert summary["case_count"] == 1
    finally:
        if artifact.exists():
            artifact.unlink()


def test_rule_audit_counts_only_phase1_cases_when_cases_exist() -> None:
    phase1 = Phase1CaseResult(
        run_id="loaded",
        company_id="test",
        generated_at=datetime.now(UTC),
        cases=[
            CaseGroupResult(
                case_id=case_id,
                primary_theme="data_integrity_failure",
                primary_queue="data_integrity",
                case_key="company|type|batch",
                priority_band="high",
                document_count=1,
                rule_count=1,
                documents=[
                    CaseDocumentRef(document_id=document_id, matched_rules=["L1-01"])
                ],
                raw_rule_hits=[
                    RawRuleHitRef(
                        rule_id="L1-01",
                        severity=4,
                        document_id=document_id,
                        row_index=0,
                        score=0.8,
                        normalized_score=0.8,
                        evidence_type="data_integrity_failure",
                    )
                ],
            )
            for case_id, document_id in (("case_001", "D1"), ("case_002", "D1"))
        ],
    )
    result = SimpleNamespace(
        phase1_case_result=phase1,
        results=[
            SimpleNamespace(
                rule_flags=[
                    SimpleNamespace(rule_id="L1-01", flagged_count=10),
                    SimpleNamespace(rule_id="L3-12", flagged_count=87422),
                ],
                metadata={"skipped_rules": []},
            )
        ],
        detector_statuses=[],
    )

    audit = _phase1_rule_audit(result)
    counts = {row["rule_id"]: row["flag_count"] for row in audit["rules"]}
    statuses = {row["rule_id"]: row["status"] for row in audit["rules"]}

    assert counts["L1-01"] == 2
    assert counts["L3-12"] == 0
    assert statuses["L3-12"] == "no_match"
