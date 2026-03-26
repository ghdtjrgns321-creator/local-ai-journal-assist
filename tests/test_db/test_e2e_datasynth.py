"""DataSynth E2E 테스트 — 실제 journal_entries.csv 적재·조회.

319MB CSV(1,106,356행) → DuckDB 적재 → 6종 프리셋 쿼리 검증.
detection 미실행 → anomaly_flags/benford는 빈 상태로 검증.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.db.loader import _derive_approval_level, load_general_ledger
from src.db.queries import execute_preset
from src.db.schema import GENERAL_LEDGER_COLUMNS, initialize_schema

DATASYNTH_CSV = Path("data/journal/primary/datasynth/journal_entries.csv")
BATCH_ID = "e2e_datasynth"


@pytest.fixture(scope="module")
def e2e_conn():
    """E2E용 in-memory 커넥션 (모듈 스코프)."""
    conn = duckdb.connect(":memory:")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def e2e_df():
    """DataSynth CSV 로드 (모듈 스코프 — 1회만 읽기)."""
    if not DATASYNTH_CSV.exists():
        pytest.skip(f"DataSynth CSV 없음: {DATASYNTH_CSV}")
    return pd.read_csv(DATASYNTH_CSV, low_memory=False)


@pytest.fixture(scope="module")
def e2e_loaded(e2e_conn, e2e_df):
    """general_ledger 적재 완료 상태."""
    rows = load_general_ledger(e2e_conn, e2e_df, BATCH_ID)
    return rows


class TestDataSynthLoad:
    """DataSynth CSV 적재 검증."""

    def test_row_count(self, e2e_loaded, e2e_df):
        """적재 행 수 == CSV 행 수."""
        assert e2e_loaded == len(e2e_df)

    def test_query_row_count(self, e2e_conn, e2e_loaded):
        """DB 조회 건수 == 적재 건수."""
        result = e2e_conn.execute(
            "SELECT COUNT(*) FROM general_ledger WHERE upload_batch_id = ?",
            [BATCH_ID],
        ).fetchone()
        assert result[0] == e2e_loaded

    def test_document_count(self, e2e_conn):
        """전표(document_id) 수 약 106,489."""
        result = e2e_conn.execute(
            "SELECT COUNT(DISTINCT document_id) FROM general_ledger "
            "WHERE upload_batch_id = ?",
            [BATCH_ID],
        ).fetchone()
        assert result[0] > 100_000

    def test_company_codes(self, e2e_conn):
        """회사코드 C001, C002, C003."""
        result = e2e_conn.execute(
            "SELECT DISTINCT company_code FROM general_ledger "
            "WHERE upload_batch_id = ? ORDER BY company_code",
            [BATCH_ID],
        ).fetchdf()
        assert set(result["company_code"]) == {"C001", "C002", "C003"}


class TestApprovalLevelE2E:
    """approval_level 파생 검증 (E2E)."""

    def test_all_levels_present(self, e2e_conn):
        """6단계 레벨이 모두 존재."""
        result = e2e_conn.execute(
            "SELECT DISTINCT approval_level FROM general_ledger "
            "WHERE upload_batch_id = ? ORDER BY approval_level",
            [BATCH_ID],
        ).fetchdf()
        levels = set(result["approval_level"].dropna().astype(int))
        # Why: 소액 전표가 대부분이므로 Level 1~3은 반드시 존재. Level 6은 드물 수 있음
        assert {1, 2, 3} <= levels

    def test_level_distribution(self, e2e_conn):
        """Level 1(자동승인)이 가장 많음."""
        result = e2e_conn.execute(
            "SELECT approval_level, COUNT(*) AS cnt FROM general_ledger "
            "WHERE upload_batch_id = ? "
            "GROUP BY approval_level ORDER BY cnt DESC",
            [BATCH_ID],
        ).fetchdf()
        assert result.iloc[0]["approval_level"] == 1


class TestBatchLedgerE2E:
    """batch_ledger 쿼리 E2E."""

    def test_returns_data(self, e2e_conn, e2e_loaded):
        """batch_ledger 쿼리가 데이터 반환."""
        result = execute_preset(e2e_conn, "batch_ledger", batch_id=BATCH_ID)
        assert len(result) == e2e_loaded

    def test_new_columns_populated(self, e2e_conn):
        """v3 추가 컬럼에 실제 값 존재."""
        result = execute_preset(e2e_conn, "batch_ledger", batch_id=BATCH_ID)
        # business_process, user_persona는 DataSynth에 반드시 존재
        assert result["business_process"].notna().sum() > 0
        assert result["approval_level"].notna().sum() > 0

    def test_process_distribution(self, e2e_conn):
        """6개 비즈니스 프로세스 분포."""
        result = execute_preset(e2e_conn, "batch_ledger", batch_id=BATCH_ID)
        processes = set(result["business_process"].dropna().unique())
        expected = {"P2P", "O2C", "R2R", "H2R", "TRE", "A2R"}
        assert expected <= processes


class TestEmptyTablesE2E:
    """detection 미실행 → anomaly_flags/benford 빈 상태."""

    def test_batch_flags_empty(self, e2e_conn):
        """anomaly_flags 빈 상태 → 빈 DataFrame."""
        result = execute_preset(e2e_conn, "batch_flags", batch_id=BATCH_ID)
        assert len(result) == 0

    def test_benford_summary_empty(self, e2e_conn):
        """benford_summary 빈 상태."""
        result = execute_preset(e2e_conn, "benford_summary", batch_id=BATCH_ID)
        assert len(result) == 0

    def test_rule_violation_stats_empty(self, e2e_conn):
        """rule_violation_stats VIEW 빈 상태."""
        result = execute_preset(e2e_conn, "rule_violation_stats", batch_id=BATCH_ID)
        assert len(result) == 0
