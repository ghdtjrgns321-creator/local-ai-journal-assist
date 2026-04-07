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
    ENGAGEMENT_META_COLUMNS,
    GENERAL_LEDGER_COLUMNS,
    ML_MODEL_METADATA_COLUMNS,
    SCHEMA_DDL,
    initialize_schema,
)


class TestInitializeSchema:
    """DDL 실행 및 테이블 생성."""

    def test_creates_6_tables(self, db_raw_conn):
        """6개 테이블 생성 확인 (engagement_meta 포함)."""
        initialize_schema(db_raw_conn)
        tables = db_raw_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchdf()
        expected = {
            "general_ledger", "anomaly_flags",
            "benford_summary", "benford_digits",
            "ml_model_metadata", "engagement_meta",
        }
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

    def test_schema_ddl_has_9_objects(self):
        """SCHEMA_DDL dict에 9개 오브젝트 정의 (5 table + engagement_meta + sequence + whitelist + view)."""
        assert len(SCHEMA_DDL) == 9

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

    def test_ml_columns_in_gl(self, db_conn):
        """ML 예약 7개 컬럼이 general_ledger DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        ml_cols = [
            "supervised_score", "unsupervised_score", "duplicate_score",
            "supervised_model_id", "unsupervised_model_id", "duplicate_model_id",
            "ml_scored_at",
        ]
        for col in ml_cols:
            assert col in ddl_cols, f"ML 예약 컬럼 '{col}'이 DDL에 없음"

    def test_ml_model_metadata_columns(self, db_conn):
        """ML_MODEL_METADATA_COLUMNS 전부 ml_model_metadata DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ml_model_metadata'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in ML_MODEL_METADATA_COLUMNS:
            assert col in ddl_cols, f"ML_MODEL_METADATA_COLUMNS의 '{col}'이 DDL에 없음"

    def test_ml_model_metadata_pk(self, db_conn):
        """ml_model_metadata.model_id가 PRIMARY KEY."""
        # Why: DuckDB의 table_constraints에서 PK 확인
        result = db_conn.execute(
            "SELECT constraint_type FROM information_schema.table_constraints "
            "WHERE table_name = 'ml_model_metadata' "
            "AND constraint_type = 'PRIMARY KEY'"
        ).fetchdf()
        assert len(result) == 1

    def test_view_empty_query(self, db_conn):
        """anomaly_flag_summary VIEW 빈 상태 정상 조회."""
        result = db_conn.execute("SELECT * FROM anomaly_flag_summary").fetchdf()
        assert len(result) == 0


class TestEngagementMeta:
    """engagement_meta 테이블 (RC-3)."""

    def test_table_created(self, db_conn):
        """engagement_meta 테이블 존재 확인."""
        tables = db_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'engagement_meta'"
        ).fetchdf()
        assert len(tables) == 1

    def test_columns_match(self, db_conn):
        """ENGAGEMENT_META_COLUMNS 전부 DDL에 존재."""
        cols = db_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'engagement_meta'"
        ).fetchdf()
        ddl_cols = set(cols["column_name"])
        for col in ENGAGEMENT_META_COLUMNS:
            assert col in ddl_cols, f"'{col}'이 engagement_meta DDL에 없음"

    def test_insert_and_query(self, db_conn):
        """정상 INSERT + SELECT."""
        db_conn.execute(
            "INSERT INTO engagement_meta (company_id, engagement_id) VALUES ('acme', '2025')"
        )
        row = db_conn.execute("SELECT company_id, engagement_id FROM engagement_meta").fetchone()
        assert row == ("acme", "2025")

    def test_duplicate_guard(self, db_conn):
        """UNIQUE 제약 + ON CONFLICT DO NOTHING으로 중복 INSERT 방지."""
        sql = """
            INSERT INTO engagement_meta (company_id, engagement_id, schema_version)
            VALUES (?, ?, 1)
            ON CONFLICT DO NOTHING
        """
        db_conn.execute(sql, ["acme", "2025"])
        db_conn.execute(sql, ["acme", "2025"])  # 중복 → 무시됨
        count = db_conn.execute("SELECT COUNT(*) FROM engagement_meta").fetchone()[0]
        assert count == 1
