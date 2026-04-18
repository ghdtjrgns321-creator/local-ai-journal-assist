"""queries.py 단위 테스트.

테스트 그룹:
  - batch_ledger: 적재 건수 == 조회 건수
  - batch_flags: 룰별 조회
  - benford_summary/digits: 고정 분석
  - rule_violation_stats: VIEW 집계
  - document_rule_detail: 드릴다운
  - 에러 처리: QueryNotFoundError, ValueError
"""

import pytest

from src.db.loader import load_all, load_anomaly_flags, load_general_ledger
from src.db.queries import (
    PRESET_QUERIES,
    QueryNotFoundError,
    execute_preset,
)


class TestBatchLedger:
    """batch_ledger 쿼리."""

    def test_row_count_match(self, db_conn, db_sample_df):
        """적재 건수 == 조회 건수."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_ledger", batch_id="batch_001")
        assert len(result) == 3

    def test_required_columns(self, db_conn, db_sample_df):
        """필수 컬럼 존재 확인."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_ledger", batch_id="batch_001")
        required = {"document_id", "anomaly_score", "risk_level", "flagged_rules"}
        assert required <= set(result.columns)

    def test_sorted_by_score_desc(self, db_conn, db_sample_df):
        """anomaly_score DESC 정렬."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_ledger", batch_id="batch_001")
        scores = result["anomaly_score"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_new_columns_present(self, db_conn, db_sample_df):
        """v3 추가 컬럼(user_persona, approval_level 등) 존재."""
        load_general_ledger(db_conn, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_ledger", batch_id="batch_001")
        new_cols = {"business_process", "user_persona", "approved_by", "approval_level"}
        assert new_cols <= set(result.columns)


class TestBatchFlags:
    """batch_flags 쿼리."""

    def test_flags_returned(self, db_conn, db_sample_df, db_detection_results):
        """적재된 플래그 전수 조회."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_flags", batch_id="batch_001")
        assert len(result) > 0

    def test_score_values(self, db_conn, db_sample_df, db_detection_results):
        """score 값 정합."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "batch_flags", batch_id="batch_001")
        assert set(result["score"]) == {0.6, 0.8}


class TestBenford:
    """benford_summary / benford_digits 쿼리."""

    def test_summary_1_row(self, db_conn, db_benford_results):
        """배치당 1행."""
        from src.db.loader import load_benford

        load_benford(db_conn, db_benford_results, "batch_001")
        result = execute_preset(db_conn, "benford_summary", batch_id="batch_001")
        assert len(result) == 1

    def test_digits_9_rows(self, db_conn, db_benford_results):
        """자릿수별 9행."""
        from src.db.loader import load_benford

        load_benford(db_conn, db_benford_results, "batch_001")
        result = execute_preset(db_conn, "benford_digits", batch_id="batch_001")
        assert len(result) == 9


class TestRuleViolationStats:
    """rule_violation_stats VIEW 쿼리."""

    def test_view_aggregation(self, db_conn, db_sample_df, db_detection_results):
        """VIEW 집계 정합."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = execute_preset(db_conn, "rule_violation_stats", batch_id="batch_001")
        assert len(result) > 0
        assert "flagged_count" in result.columns


class TestDocumentRuleDetail:
    """document_rule_detail 드릴다운."""

    def test_specific_document(self, db_conn, db_sample_df, db_detection_results):
        """특정 document_id 필터링."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = execute_preset(
            db_conn, "document_rule_detail",
            params=("batch_001", "JE-001"),
        )
        assert len(result) > 0

    def test_nonexistent_document(self, db_conn, db_sample_df, db_detection_results):
        """존재하지 않는 document_id → 빈 DataFrame."""
        load_anomaly_flags(db_conn, db_detection_results, db_sample_df, "batch_001")
        result = execute_preset(
            db_conn, "document_rule_detail",
            params=("batch_001", "NONEXISTENT"),
        )
        assert len(result) == 0


class TestErrorHandling:
    """에러 처리."""

    def test_unknown_query_name(self, db_conn):
        """존재하지 않는 쿼리명 → QueryNotFoundError."""
        with pytest.raises(QueryNotFoundError):
            execute_preset(db_conn, "nonexistent_query", batch_id="x")

    def test_no_params_no_batch_id(self, db_conn):
        """params와 batch_id 모두 None → ValueError."""
        with pytest.raises(ValueError):
            execute_preset(db_conn, "batch_ledger")

    def test_empty_table_returns_empty_df(self, db_conn):
        """빈 테이블 → 빈 DataFrame."""
        result = execute_preset(db_conn, "batch_ledger", batch_id="empty")
        assert len(result) == 0

    def test_preset_queries_count(self):
        """PRESET_QUERIES 22종 정의 (코어 11 + 보조 7 + audit_log 4)."""
        assert len(PRESET_QUERIES) == 29

    def test_all_queries_have_batch_filter(self):
        """모든 쿼리에 batch_id 관련 필터 포함 (PK 삭제 제외)."""
        # Why: delete_whitelist는 PK(id)로 삭제, list_batches는 전체 조회
        skip = {
            "delete_whitelist",
            "list_batches",
            "performance_rule_metrics_by_report",
            "list_audit_log",
            "audit_log_by_engagement",
            "feedback_events_by_engagement",
        }
        for name, sql in PRESET_QUERIES.items():
            if name in skip:
                continue
            assert "batch_id" in sql or "upload_batch_id" in sql, (
                f"{name}에 batch_id 필터 없음"
            )

    def test_batch_isolation(self, db_conn, db_sample_df):
        """2개 배치 적재 → 교차 조회 없음."""
        load_general_ledger(db_conn, db_sample_df, "batch_A")
        load_general_ledger(db_conn, db_sample_df, "batch_B")
        a = execute_preset(db_conn, "batch_ledger", batch_id="batch_A")
        b = execute_preset(db_conn, "batch_ledger", batch_id="batch_B")
        assert len(a) == 3
        assert len(b) == 3
