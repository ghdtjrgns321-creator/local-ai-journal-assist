"""sql_validator 단위 테스트.

5단계 검증 파이프라인: DML차단 + 테이블화이트리스트 + 서브쿼리깊이
+ 배치격리키 + 자동LIMIT + EXPLAIN.
"""

from __future__ import annotations

import duckdb
import pytest

from src.llm.sql_validator import (
    DEFAULT_LIMIT,
    MAX_SUBQUERY_DEPTH,
    TABLE_WHITELIST,
    ValidationResult,
    validate_sql,
)


# ── fixture ──────────────────────────────────────────────────

@pytest.fixture()
def mem_conn():
    """테스트용 DuckDB :memory: 커넥션 + general_ledger 테이블."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE general_ledger (
            document_id VARCHAR, upload_batch_id VARCHAR,
            debit_amount DOUBLE DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE anomaly_flags (
            upload_batch_id VARCHAR, document_id VARCHAR,
            rule_code VARCHAR, score DOUBLE
        )
    """)
    yield conn
    conn.close()


# ── Step 1: DML 차단 ────────────────────────────────────────

class TestDmlBlocking:
    """DML/DDL 구문 차단 테스트."""

    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    ])
    def test_dml_blocked(self, keyword: str):
        sql = f"{keyword} INTO general_ledger VALUES ('x', 'b1', 0)"
        result = validate_sql(sql, require_batch_filter=False)
        assert not result.is_valid
        assert any("DML" in e for e in result.errors)

    def test_case_insensitive(self):
        result = validate_sql(
            "insert into general_ledger values ('x')",
            require_batch_filter=False,
        )
        assert not result.is_valid

    def test_select_allowed(self):
        sql = "SELECT * FROM general_ledger WHERE upload_batch_id = 'b1'"
        result = validate_sql(sql)
        assert result.is_valid

    def test_string_constant_no_false_positive(self):
        """문자열 상수 내 DML 단어는 오탐하지 않아야 함."""
        sql = (
            "SELECT document_id, 'UPDATE_REQUIRED' AS status "
            "FROM general_ledger WHERE upload_batch_id = 'b1'"
        )
        result = validate_sql(sql)
        assert result.is_valid

    def test_string_constant_delete_flag(self):
        sql = (
            "SELECT 'DELETE_FLAG' AS flag, document_id "
            "FROM general_ledger WHERE upload_batch_id = 'b1'"
        )
        result = validate_sql(sql)
        assert result.is_valid


# ── Step 2: 테이블 화이트리스트 ──────────────────────────────

class TestTableWhitelist:

    def test_whitelist_pass(self):
        sql = (
            "SELECT * FROM general_ledger gl "
            "JOIN anomaly_flags af ON gl.document_id = af.document_id "
            "WHERE gl.upload_batch_id = 'b1'"
        )
        result = validate_sql(sql)
        assert result.is_valid

    def test_whitelist_fail(self):
        sql = (
            "SELECT * FROM users "
            "WHERE upload_batch_id = 'b1'"
        )
        result = validate_sql(sql)
        assert not result.is_valid
        assert any("비허용 테이블" in e for e in result.errors)

    def test_all_whitelisted_tables(self):
        """화이트리스트 6개 테이블 모두 통과 확인."""
        for table in TABLE_WHITELIST:
            sql = f"SELECT * FROM {table} WHERE upload_batch_id = 'b1'"
            result = validate_sql(sql)
            assert result.is_valid, f"{table} 테이블이 거부됨"


# ── Step 3: 서브쿼리 깊이 ────────────────────────────────────

class TestSubqueryDepth:

    def test_within_limit(self):
        # 깊이 2: 허용
        sql = """
            SELECT * FROM (
                SELECT * FROM (
                    SELECT document_id FROM general_ledger
                    WHERE upload_batch_id = 'b1'
                ) sub1
            ) sub2
            WHERE upload_batch_id = 'b1'
        """
        result = validate_sql(sql)
        assert result.is_valid

    def test_exceeded(self):
        # 깊이 4: 거부
        sql = """
            SELECT * FROM (
                SELECT * FROM (
                    SELECT * FROM (
                        SELECT * FROM (
                            SELECT document_id FROM general_ledger
                        ) s1
                    ) s2
                ) s3
            ) s4
            WHERE upload_batch_id = 'b1'
        """
        result = validate_sql(sql)
        assert not result.is_valid
        assert any("서브쿼리 깊이" in e for e in result.errors)


# ── Step 4: 배치 격리 키 ─────────────────────────────────────

class TestBatchIsolation:

    def test_missing_batch_filter_blocked(self):
        sql = "SELECT * FROM general_ledger"
        result = validate_sql(sql, require_batch_filter=True)
        assert not result.is_valid
        assert any("upload_batch_id" in e for e in result.errors)

    def test_batch_filter_present_pass(self):
        sql = "SELECT * FROM general_ledger WHERE upload_batch_id = 'b1'"
        result = validate_sql(sql, require_batch_filter=True)
        assert result.is_valid

    def test_batch_filter_disabled(self):
        sql = "SELECT * FROM general_ledger"
        result = validate_sql(sql, require_batch_filter=False)
        assert result.is_valid


# ── Step 5: LIMIT 자동 추가 ──────────────────────────────────

class TestLimitAutoAdd:

    def test_auto_added(self):
        sql = "SELECT * FROM general_ledger WHERE upload_batch_id = 'b1'"
        result = validate_sql(sql)
        assert f"LIMIT {DEFAULT_LIMIT}" in result.sql
        assert any("자동 추가" in w for w in result.warnings)

    def test_existing_preserved(self):
        sql = "SELECT * FROM general_ledger WHERE upload_batch_id = 'b1' LIMIT 500"
        result = validate_sql(sql)
        assert "LIMIT 500" in result.sql
        assert not any("자동 추가" in w for w in result.warnings)


# ── Step 6: EXPLAIN 검증 ────────────────────────────────────

class TestExplainValidation:

    def test_valid_sql(self, mem_conn):
        sql = "SELECT * FROM general_ledger WHERE upload_batch_id = 'b1'"
        result = validate_sql(sql, conn=mem_conn)
        assert result.is_valid

    def test_invalid_syntax(self, mem_conn):
        sql = "SELECTX * FROM general_ledger WHERE upload_batch_id = 'b1'"
        result = validate_sql(sql, conn=mem_conn)
        assert not result.is_valid
        assert any("문법 오류" in e for e in result.errors)


# ── CTE / UNION ──────────────────────────────────────────────

class TestComplexQueries:

    def test_cte_allowed(self):
        sql = """
            WITH cte AS (
                SELECT document_id, debit_amount
                FROM general_ledger
                WHERE upload_batch_id = 'b1'
            )
            SELECT * FROM cte
        """
        result = validate_sql(sql)
        assert result.is_valid

    def test_union_allowed(self):
        sql = """
            SELECT document_id FROM general_ledger WHERE upload_batch_id = 'b1'
            UNION ALL
            SELECT document_id FROM anomaly_flags WHERE upload_batch_id = 'b1'
        """
        result = validate_sql(sql)
        assert result.is_valid
