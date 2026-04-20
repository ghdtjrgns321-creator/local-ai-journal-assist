from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from src.db.performance_store import list_reports_by_batch, load_latest_report, save_report
from src.db.schema import initialize_schema
from src.metrics.models import PerformanceReport, RuleMetric
from src.metrics.operational_evaluator import (
    evaluate_operational_report,
    evaluate_operational_report_from_db,
)


@pytest.fixture()
def db_conn():
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


class TestOperationalEvaluator:
    def test_evaluate_operational_report_counts_docs_and_whitelist(self):
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D3"],
                "anomaly_score": [0.8, 0.1, 0.0, 0.6],
                "risk_level": ["High", "High", "Normal", "Medium"],
            }
        )
        whitelist_df = pd.DataFrame(
            {"document_id": ["D2", "D2", "D3"], "rule_code": ["L1-01", "L4-01", "L3-04"]}
        )
        feedback_events_df = pd.DataFrame(
            [
                {"document_id": "D2", "decision": "false_positive", "created_at": "2026-01-01", "id": 1},
                {"document_id": "D3", "decision": "confirmed_issue", "created_at": "2026-01-02", "id": 2},
            ]
        )

        report = evaluate_operational_report(
            df,
            upload_batch_id="batch_001",
            whitelist_df=whitelist_df,
            feedback_events_df=feedback_events_df,
        )

        assert report.source_kind == "operational_proxy"
        assert report.total_docs == 3
        assert report.flagged_docs == 2
        assert report.high_risk_docs == 1
        assert report.high_risk_ratio == 1 / 3
        assert report.whitelist_removed_docs == 2
        assert report.false_positive_docs == 1
        assert report.confirmed_issue_docs == 1

    def test_evaluate_operational_report_from_db(self, db_conn):
        db_conn.execute(
            """
            INSERT INTO general_ledger (
                document_id, fiscal_period, posting_date, debit_amount, credit_amount,
                approval_level, upload_batch_id, anomaly_score, risk_level
            ) VALUES
                ('D1', 1, TIMESTAMP '2025-01-01 00:00:00', 100, 0, 1, 'batch_001', 0.8, 'High'),
                ('D2', 1, TIMESTAMP '2025-01-01 00:00:00', 100, 0, 1, 'batch_001', 0.0, 'Normal')
            """
        )
        db_conn.execute(
            """
            INSERT INTO whitelist (batch_id, document_id, rule_code, reason, created_by)
            VALUES ('batch_001', 'D2', 'L1-01', 'expected false positive', 'auditor')
            """
        )
        db_conn.execute(
            """
            INSERT INTO feedback_events (
                company_id, engagement_id, batch_id, document_id,
                track_name, rule_code, event_type, decision,
                reason, payload_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?)
            """,
            ["acme", "2026", "batch_001", "D2", None, "L1-01", "document_feedback", "false_positive", "expected", "{}", "auditor"],
        )
        db_conn.execute(
            """
            INSERT INTO feedback_events (
                company_id, engagement_id, batch_id, document_id,
                track_name, rule_code, event_type, decision,
                reason, payload_json, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?)
            """,
            ["acme", "2026", "batch_001", "D1", None, "L1-01", "document_feedback", "confirmed_issue", "confirmed", "{}", "auditor"],
        )

        report = evaluate_operational_report_from_db(db_conn, upload_batch_id="batch_001")

        assert report.total_docs == 2
        assert report.flagged_docs == 1
        assert report.high_risk_docs == 1
        assert report.whitelist_removed_docs == 1
        assert report.false_positive_docs == 1
        assert report.confirmed_issue_docs == 1
        assert report.metric_confidence == "partial"


class TestPerformanceStore:
    def test_save_and_load_latest_report(self, db_conn):
        report = PerformanceReport(
            report_id="rep_001",
            upload_batch_id="batch_001",
            source_kind="ground_truth",
            phase_scope="phase1_only",
            total_docs=10,
            flagged_docs=4,
            high_risk_docs=2,
            high_risk_ratio=0.2,
            precision=0.5,
            recall=0.4,
            f1=0.444,
            whitelist_removed_docs=1,
            false_positive_docs=1,
            confirmed_issue_docs=2,
            rule_metrics=[
                RuleMetric(
                    track_name="layer_a",
                    rule_code="L1-01",
                    label_docs=3,
                    flagged_docs=2,
                    tp_docs=1,
                    fp_docs=1,
                    fn_docs=2,
                    precision=0.5,
                    recall=1 / 3,
                    f1=0.4,
                )
            ],
        )

        save_report(db_conn, report)
        loaded = load_latest_report(db_conn, "batch_001")

        assert loaded is not None
        assert loaded.report_id == "rep_001"
        assert loaded.total_docs == 10
        assert loaded.false_positive_docs == 1
        assert loaded.confirmed_issue_docs == 2
        assert loaded.rule_metrics[0].rule_code == "L1-01"

    def test_list_reports_by_batch_returns_rows(self, db_conn):
        report = PerformanceReport(
            report_id="rep_002",
            upload_batch_id="batch_002",
            source_kind="operational_proxy",
            phase_scope="phase2_included",
            total_docs=5,
            flagged_docs=1,
        )

        save_report(db_conn, report)
        result = list_reports_by_batch(db_conn, "batch_002")

        assert len(result) == 1
        assert result.iloc[0]["report_id"] == "rep_002"
