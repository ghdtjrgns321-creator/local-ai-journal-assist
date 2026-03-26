"""schema.py 단위 테스트.

테스트 그룹:
  - DDL 오브젝트 생성 확인
  - 멱등성
  - 컬럼 상수 ↔ DDL 동기화
  - DataSynth PREVIEW 39개 컬럼 대응
"""

import duckdb
import pytest

from src.db.schema import (
    ANOMALY_FLAGS_COLUMNS,
    BENFORD_DIGITS_COLUMNS,
    BENFORD_SUMMARY_COLUMNS,
    GENERAL_LEDGER_COLUMNS,
    SCHEMA_DDL,
    initialize_schema,
)


class TestInitializeSchema:
    """DDL 실행 및 테이블 생성."""

    def test_creates_4_tables(self, db_raw_conn):
        """4개 테이블 생성 확인."""
        initialize_schema(db_raw_conn)
        tables = db_raw_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchdf()
        expected = {"general_ledger", "anomaly_flags", "benford_summary", "benford_digits"}
        # Why: DuckDB에서 VIEW도 information_schema.tables에 포함될 수 있음
        assert expected <= set(tables["table_name"])

    def test_creates_1_view(self, db_raw_conn):
        """1 VIEW 생성 확인."""
        initialize_schema(db_raw_conn)
        # Why: DuckDB information_schema에서 VIEW는 duckdb_views()로 조회
        views = db_raw_conn.execute(
            "SELECT view_name FROM duckdb_views() WHERE schema_name = 'main'"
        ).fetchdf()
        assert "anomaly_flag_summary" in set(views["view_name"])

    def test_schema_ddl_has_5_objects(self):
        """SCHEMA_DDL dict에 5개 오브젝트 정의."""
        assert len(SCHEMA_DDL) == 5

    def test_idempotent(self, db_raw_conn):
        """2회 실행해도 에러 없음 (멱등성)."""
        initialize_schema(db_raw_conn)
        initialize_schema(db_raw_conn)  # 두 번째 호출
        tables = db_raw_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchdf()
        # Why: VIEW 포함 시 5개
        assert len(tables) >= 4


class TestColumnConstants:
    """컬럼 상수 ↔ DDL 동기화."""

    def test_gl_columns_in_ddl(self, db_conn):
        """GENERAL_LEDGER_COLUMNS 전부 general_ledger DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in GENERAL_LEDGER_COLUMNS:
            assert col in ddl_cols, f"GENERAL_LEDGER_COLUMNS의 '{col}'이 DDL에 없음"

    def test_af_columns_in_ddl(self, db_conn):
        """ANOMALY_FLAGS_COLUMNS 전부 anomaly_flags DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'anomaly_flags'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in ANOMALY_FLAGS_COLUMNS:
            assert col in ddl_cols

    def test_bs_columns_in_ddl(self, db_conn):
        """BENFORD_SUMMARY_COLUMNS 전부 benford_summary DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'benford_summary'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in BENFORD_SUMMARY_COLUMNS:
            assert col in ddl_cols

    def test_bd_columns_in_ddl(self, db_conn):
        """BENFORD_DIGITS_COLUMNS 전부 benford_digits DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'benford_digits'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in BENFORD_DIGITS_COLUMNS:
            assert col in ddl_cols

    def test_feature_columns_in_gl(self, db_conn):
        """Feature EXPECTED_COLUMNS 18개 전부 general_ledger DDL에 존재."""
        from src.feature.engine import EXPECTED_COLUMNS

        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for category_cols in EXPECTED_COLUMNS.values():
            for col in category_cols:
                assert col in ddl_cols, f"피처 '{col}'이 DDL에 없음"

    def test_approval_level_in_gl(self, db_conn):
        """approval_level 파생 컬럼 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()
        assert "approval_level" in set(cols["column_name"])

    def test_view_empty_query(self, db_conn):
        """anomaly_flag_summary VIEW 빈 상태 정상 조회."""
        result = db_conn.execute("SELECT * FROM anomaly_flag_summary").fetchdf()
        assert len(result) == 0
