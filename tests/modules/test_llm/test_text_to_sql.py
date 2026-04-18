"""text_to_sql 단위 + E2E 테스트.

프리셋 매칭, LLM SQL 생성(mock), 검증, 실행 파이프라인 검증.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pandas as pd
import pytest

from src.llm.sql_validator import TABLE_WHITELIST
from src.llm.text_to_sql import AuditTextToSQL, SQLResult, create_text_to_sql


# ── fixture ──────────────────────────────────────────────────

@pytest.fixture()
def mem_conn():
    """DuckDB :memory: + general_ledger 테이블 + 테스트 데이터."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE general_ledger (
            document_id VARCHAR, upload_batch_id VARCHAR,
            debit_amount DOUBLE DEFAULT 0, credit_amount DOUBLE DEFAULT 0,
            risk_level VARCHAR, anomaly_score DOUBLE DEFAULT 0,
            is_weekend BOOLEAN DEFAULT false,
            is_after_hours BOOLEAN DEFAULT false,
            is_period_end BOOLEAN DEFAULT false,
            is_fraud BOOLEAN DEFAULT false,
            fraud_type VARCHAR, business_process VARCHAR,
            sod_violation BOOLEAN DEFAULT false,
            sod_conflict_type VARCHAR,
            created_by VARCHAR, approved_by VARCHAR,
            gl_account VARCHAR, posting_date TIMESTAMP,
            is_manual_je BOOLEAN DEFAULT false,
            is_intercompany BOOLEAN DEFAULT false,
            is_suspense_account BOOLEAN DEFAULT false,
            lettrage VARCHAR,
            trading_partner VARCHAR, company_code VARCHAR,
            reference VARCHAR, header_text VARCHAR,
            source VARCHAR, posting_time TIME
        )
    """)
    conn.execute("""
        CREATE TABLE anomaly_flags (
            upload_batch_id VARCHAR, document_id VARCHAR,
            line_number INTEGER, track_name VARCHAR,
            rule_code VARCHAR, score DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE benford_digits (
            upload_batch_id VARCHAR, digit INTEGER,
            observed_freq DOUBLE, expected_freq DOUBLE, deviation DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE trial_balance (
            upload_batch_id VARCHAR, gl_account VARCHAR,
            fiscal_period INTEGER, debit_total DOUBLE, credit_total DOUBLE
        )
    """)
    conn.execute("""
        CREATE VIEW anomaly_flag_summary AS
        SELECT upload_batch_id, track_name, rule_code,
               COUNT(*) AS flagged_count, AVG(score) AS avg_score
        FROM anomaly_flags
        GROUP BY upload_batch_id, track_name, rule_code
    """)
    conn.execute("""
        CREATE TABLE benford_summary (
            upload_batch_id VARCHAR, sample_size INTEGER,
            mad DOUBLE, mad_conformity VARCHAR
        )
    """)
    # 테스트 데이터 삽입
    conn.execute("""
        INSERT INTO general_ledger (document_id, upload_batch_id, debit_amount,
            risk_level, anomaly_score, is_weekend, business_process, created_by,
            gl_account, posting_date, is_fraud, fraud_type)
        VALUES
            ('DOC001', 'batch_1', 100000, 'HIGH', 0.9, true, 'P2P', 'user_a',
             '4100', '2025-06-15', true, 'DuplicatePayment'),
            ('DOC002', 'batch_1', 50000, 'MEDIUM', 0.5, false, 'O2C', 'user_b',
             '1200', '2025-06-16', false, NULL),
            ('DOC003', 'batch_1', 200000, 'HIGH', 0.85, false, 'R2R', 'user_a',
             '4100', '2025-12-31', false, NULL)
    """)
    yield conn
    conn.close()


@pytest.fixture()
def mock_ctx(mem_conn):
    """mock CompanyContext — db_path와 settings만 필요."""
    ctx = MagicMock()
    ctx.db_path = Path(":memory:")
    ctx.settings.openai_api_key = ""
    ctx.settings.openai_light_model = "gpt-5.4-mini"
    ctx.settings.openai_temperature = 0.0
    return ctx


@pytest.fixture()
def mock_client():
    """LLM 클라이언트 mock — chat() 응답 제어."""
    client = MagicMock()
    client.is_available.return_value = True
    return client


# ── SQLResult dataclass ──────────────────────────────────────

class TestSQLResult:

    def test_fields(self):
        result = SQLResult(sql="SELECT 1", result_df=None, source="preset")
        assert result.sql == "SELECT 1"
        assert result.source == "preset"
        assert result.error is None

    def test_with_error(self):
        result = SQLResult(sql="", result_df=None, source="failed",
                           error="test error")
        assert result.error == "test error"


# ── 프리셋 매칭 ──────────────────────────────────────────────

class TestPresetMatching:

    def test_preset_match_returns_data(self, mock_ctx, mem_conn):
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        result = engine.ask(
            "고위험으로 분류된 전표의 건수와 금액 분포는?",
            batch_id="batch_1",
        )
        assert result.source == "preset"
        assert result.preset_key == "high_risk_overview"
        assert result.result_df is not None
        assert len(result.result_df) > 0

    def test_preset_weekend(self, mock_ctx, mem_conn):
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        result = engine.ask("주말 전표 보여줘", batch_id="batch_1")
        assert result.source == "preset"
        assert result.preset_key == "weekend_midnight"


# ── LLM SQL 생성 (mock) ─────────────────────────────────────

class TestLLMGeneration:

    def test_llm_generates_valid_sql(self, mock_ctx, mem_conn, mock_client):
        """LLM이 유효한 SQL 생성 → source="llm"."""
        # Why: LLM에 ? 플레이스홀더를 지시하므로 생성 SQL에도 ? 포함
        generated_sql = (
            "SELECT document_id, debit_amount FROM general_ledger "
            "WHERE upload_batch_id = ? LIMIT 100"
        )
        mock_client.chat.return_value = json.dumps({"sql": generated_sql})

        engine = AuditTextToSQL(ctx=mock_ctx, client=mock_client, conn=mem_conn)
        result = engine.ask("가장 큰 금액의 전표는?", batch_id="batch_1")

        assert result.source == "llm"
        assert result.result_df is not None

    def test_llm_generates_dml_blocked(self, mock_ctx, mem_conn, mock_client):
        """LLM이 DML 생성 → 검증 실패 → source="failed"."""
        mock_client.chat.return_value = json.dumps({
            "sql": "DELETE FROM general_ledger WHERE upload_batch_id = 'b1'",
        })

        engine = AuditTextToSQL(ctx=mock_ctx, client=mock_client, conn=mem_conn)
        result = engine.ask("전표 삭제해줘", batch_id="batch_1")

        assert result.source == "failed"
        assert "DML" in result.error

    def test_llm_missing_batch_filter(self, mock_ctx, mem_conn, mock_client):
        """LLM이 upload_batch_id 누락 → 검증 실패."""
        mock_client.chat.return_value = json.dumps({
            "sql": "SELECT * FROM general_ledger LIMIT 100",
        })

        engine = AuditTextToSQL(ctx=mock_ctx, client=mock_client, conn=mem_conn)
        result = engine.ask("전체 전표 보여줘", batch_id="batch_1")

        assert result.source == "failed"
        assert "upload_batch_id" in result.error

    def test_llm_unauthorized_table(self, mock_ctx, mem_conn, mock_client):
        """LLM이 비허용 테이블 참조 → 검증 실패."""
        mock_client.chat.return_value = json.dumps({
            "sql": "SELECT * FROM audit_log WHERE upload_batch_id = 'b1'",
        })

        engine = AuditTextToSQL(ctx=mock_ctx, client=mock_client, conn=mem_conn)
        result = engine.ask("감사 로그 보여줘", batch_id="batch_1")

        assert result.source == "failed"
        assert "비허용 테이블" in result.error


# ── LLM 미가용 ───────────────────────────────────────────────

class TestLLMUnavailable:

    def test_no_client_preset_fallback(self, mock_ctx, mem_conn):
        """client=None → 프리셋 매칭만 시도."""
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        result = engine.ask("고위험 전표 현황", batch_id="batch_1")
        # "고위험" 키워드로 프리셋 매칭 성공
        assert result.source == "preset"

    def test_no_client_no_preset_failed(self, mock_ctx, mem_conn):
        """client=None + 프리셋 미매칭 → failed."""
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        result = engine.ask("오늘 날씨 어때?", batch_id="batch_1")
        assert result.source == "failed"
        assert "미가용" in result.error

    def test_preset_without_batch_id_fails(self, mock_ctx, mem_conn):
        """batch_id=None + 프리셋 매칭 → 명확한 실패 메시지."""
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        result = engine.ask(
            "고위험으로 분류된 전표의 건수와 금액 분포는?",
            batch_id=None,
        )
        assert result.source == "failed"
        assert "batch_id" in result.error


# ── DDL 컨텍스트 ─────────────────────────────────────────────

class TestDDLContext:

    def test_contains_whitelist_tables(self, mock_ctx, mem_conn):
        engine = AuditTextToSQL(ctx=mock_ctx, conn=mem_conn)
        for table in TABLE_WHITELIST:
            assert table in engine._ddl_context.lower(), (
                f"DDL에 {table} 누락"
            )


# ── 팩토리 ───────────────────────────────────────────────────

class TestFactory:

    def test_create_text_to_sql(self, mock_ctx, mem_conn):
        engine = create_text_to_sql(mock_ctx, conn=mem_conn)
        assert isinstance(engine, AuditTextToSQL)

    def test_factory_without_conn(self, mock_ctx):
        """conn=None → lazy 초기화 (db_path 기반)."""
        engine = create_text_to_sql(mock_ctx)
        assert engine._conn is None


# ── E2E ──────────────────────────────────────────────────────

class TestE2E:

    def test_preset_end_to_end(self, mock_ctx, mem_conn):
        """프리셋 질문 → SQL 바인딩 → DuckDB 실행 → DataFrame."""
        engine = create_text_to_sql(mock_ctx, conn=mem_conn)
        result = engine.ask(
            "프로세스별 부정 분포",
            batch_id="batch_1",
        )
        assert result.source == "preset"
        assert result.preset_key == "fraud_by_process"
        assert isinstance(result.result_df, pd.DataFrame)

    def test_llm_end_to_end(self, mock_ctx, mem_conn, mock_client):
        """자연어 → LLM SQL → 검증 → 파라미터 바인딩 실행 → DataFrame."""
        sql = (
            "SELECT gl_account, COUNT(*) AS cnt "
            "FROM general_ledger "
            "WHERE upload_batch_id = ? "
            "GROUP BY gl_account "
            "ORDER BY cnt DESC LIMIT 10"
        )
        mock_client.chat.return_value = json.dumps({"sql": sql})

        engine = create_text_to_sql(mock_ctx, client=mock_client, conn=mem_conn)
        result = engine.ask("계정별 전표 건수", batch_id="batch_1")

        assert result.source == "llm"
        assert result.result_df is not None
        assert "gl_account" in result.result_df.columns
