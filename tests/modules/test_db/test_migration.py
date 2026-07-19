"""DuckDB 스키마 마이그레이션 테스트.

Why: 기존 engagement DB에 ML 예약 컬럼이 없을 때
     ALTER TABLE로 안전하게 추가되는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import patch

import duckdb
import pytest

from src.db.migration import CURRENT_SCHEMA_VERSION, _get_schema_version, run_migrations

# Why: 마이그레이션 후 존재해야 할 ML 예약 7개 컬럼
_EXPECTED_ML_COLUMNS = {
    "supervised_score",
    "unsupervised_score",
    "duplicate_score",
    "supervised_model_id",
    "unsupervised_model_id",
    "duplicate_model_id",
    "ml_scored_at",
}
_EXPECTED_REVIEW_COLUMNS = {"review_rules"}


def _get_gl_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """general_ledger 테이블의 컬럼명 집합 반환."""
    df = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'general_ledger'"
    ).fetchdf()
    return set(df["column_name"])


class TestMigrateV1ToV2:
    """v1 → v2 마이그레이션 (ML 7개 컬럼 추가)."""

    def test_adds_missing_columns(self, db_v1_conn):
        """v1 DB에 ML 7개 컬럼이 추가된다."""
        # Why: v1 DB에는 ML 컬럼이 없으므로 ALTER TABLE이 실행되어야 함
        before = _get_gl_columns(db_v1_conn)
        assert not _EXPECTED_ML_COLUMNS.issubset(before), "v1에 ML 컬럼이 이미 존재"

        run_migrations(db_v1_conn)

        after = _get_gl_columns(db_v1_conn)
        assert _EXPECTED_ML_COLUMNS.issubset(after), f"누락: {_EXPECTED_ML_COLUMNS - after}"

    def test_idempotent(self, db_v1_conn):
        """2회 실행해도 에러 없이 동일 결과."""
        run_migrations(db_v1_conn)
        run_migrations(db_v1_conn)  # 2회차 — 에러 없어야 함

        after = _get_gl_columns(db_v1_conn)
        assert _EXPECTED_ML_COLUMNS.issubset(after)

    def test_schema_version_updated(self, db_v1_conn):
        """마이그레이션 후 schema_version = CURRENT_SCHEMA_VERSION."""
        run_migrations(db_v1_conn)

        version = _get_schema_version(db_v1_conn)
        assert version == CURRENT_SCHEMA_VERSION

    def test_new_db_skips_alter(self, db_conn):
        """최신 DDL DB는 ALTER 없이 version만 업데이트."""
        # Why: db_conn은 이미 ML 컬럼 포함 DDL로 생성됨
        result = run_migrations(db_conn)
        assert result == CURRENT_SCHEMA_VERSION

    def test_returns_final_version(self, db_v1_conn):
        """반환값이 CURRENT_SCHEMA_VERSION."""
        result = run_migrations(db_v1_conn)
        assert result == CURRENT_SCHEMA_VERSION

    def test_empty_meta_defaults_v1(self, db_v1_conn):
        """engagement_meta 비어있으면 버전 1로 시작."""
        version = _get_schema_version(db_v1_conn)
        assert version == 1

    def test_partial_failure_raises(self, db_v1_conn):
        """마이그레이션 중 에러 시 예외가 전파된다.

        Why: DuckDB는 DDL 롤백을 공식 보장하지 않으므로 예외 전파만 검증.
             컬럼 추가 여부는 DuckDB 버전 의존 — 멱등성(skip 로직)이 안전망.
        """
        with patch(
            "src.db.migration._set_schema_version",
            side_effect=RuntimeError("강제 에러"),
        ):
            with pytest.raises(RuntimeError, match="강제 에러"):
                run_migrations(db_v1_conn)
