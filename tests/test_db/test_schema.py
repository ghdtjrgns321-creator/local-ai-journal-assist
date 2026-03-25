"""schema.py 테스트 — DDL 생성, 멱등성, 컬럼 정합성 검증.

Why: DDL이 코드(feature/engine.py, validation/models.py)와 정합하는지
     자동 검증하여 스키마 드리프트를 방지한다.
"""

from __future__ import annotations

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


# ── 헬퍼 ────────────────────────────────────────────────────────

def _get_table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """information_schema에서 테이블 목록을 조회한다."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_view_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """information_schema에서 VIEW 목록을 조회한다."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'VIEW'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_column_names(
    conn: duckdb.DuckDBPyConnection, table_name: str,
) -> list[str]:
    """테이블의 컬럼 이름 목록을 DDL 순서대로 반환한다."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table_name],
    ).fetchall()
    return [r[0] for r in rows]


# ── 테이블/VIEW 존재 확인 ────────────────────────────────────────

EXPECTED_TABLES = {"general_ledger", "anomaly_flags", "benford_summary", "benford_digits"}
EXPECTED_VIEWS = {"anomaly_flag_summary"}


def test_all_tables_created(db_conn):
    """4개 테이블이 모두 생성되었는지 확인한다."""
    tables = _get_table_names(db_conn)
    assert EXPECTED_TABLES.issubset(tables), (
        f"누락 테이블: {EXPECTED_TABLES - tables}"
    )


def test_view_created(db_conn):
    """anomaly_flag_summary VIEW가 생성되었는지 확인한다."""
    views = _get_view_names(db_conn)
    assert EXPECTED_VIEWS.issubset(views), (
        f"누락 VIEW: {EXPECTED_VIEWS - views}"
    )


def test_schema_ddl_contents():
    """SCHEMA_DDL dict의 테이블/VIEW 구성이 기대와 일치하는지 확인한다."""
    tables_in_ddl = {k for k, v in SCHEMA_DDL.items() if "CREATE TABLE" in v}
    views_in_ddl = {k for k, v in SCHEMA_DDL.items() if "CREATE VIEW" in v}
    assert tables_in_ddl == EXPECTED_TABLES, f"DDL 테이블 불일치: {tables_in_ddl}"
    assert views_in_ddl == EXPECTED_VIEWS, f"DDL VIEW 불일치: {views_in_ddl}"


# ── 멱등성 ───────────────────────────────────────────────────────

def test_idempotent_initialization(db_conn):
    """initialize_schema를 두 번 실행해도 에러가 발생하지 않는다."""
    # conftest에서 이미 1회 실행. 추가 1회 실행.
    initialize_schema(db_conn)
    tables = _get_table_names(db_conn)
    assert EXPECTED_TABLES.issubset(tables)


# ── Feature EXPECTED_COLUMNS 정합성 ──────────────────────────────

def test_feature_columns_in_general_ledger(db_conn):
    """feature/engine.py EXPECTED_COLUMNS 18개가 general_ledger DDL에 존재하는지 검증."""
    from src.feature.engine import EXPECTED_COLUMNS

    # Why: EXPECTED_COLUMNS는 dict[FeatureCategory, list[str]] 구조
    all_feature_cols = [
        col for cols in EXPECTED_COLUMNS.values() for col in cols
    ]
    gl_columns = set(_get_column_names(db_conn, "general_ledger"))

    missing = [c for c in all_feature_cols if c not in gl_columns]
    assert not missing, f"general_ledger DDL에 누락된 파생변수: {missing}"
    assert len(all_feature_cols) == 18, (
        f"EXPECTED_COLUMNS 총 개수가 18이 아님: {len(all_feature_cols)}"
    )


# ── BenfordResult 필드 정합성 ────────────────────────────────────

def test_benford_result_fields_in_summary(db_conn):
    """BenfordResult 필드가 benford_summary DDL에 대응하는지 검증."""
    from src.validation.models import BenfordResult

    # Why: BenfordResult는 dataclass — __dataclass_fields__로 필드명 추출
    benford_fields = set(BenfordResult.__dataclass_fields__.keys())
    summary_columns = set(_get_column_names(db_conn, "benford_summary"))

    # observed/expected는 dict 타입이라 DDL에 없음 (benford_digits로 분리)
    non_ddl_fields = {"observed", "expected"}
    # upload_batch_id/created_at은 메타 컬럼이라 BenfordResult에 없음
    meta_columns = {"upload_batch_id", "created_at"}

    mappable_fields = benford_fields - non_ddl_fields
    mappable_columns = summary_columns - meta_columns

    assert mappable_fields == mappable_columns, (
        f"불일치 — BenfordResult에만: {mappable_fields - mappable_columns}, "
        f"DDL에만: {mappable_columns - mappable_fields}"
    )


# ── 컬럼 상수 동기화 검증 ────────────────────────────────────────

def test_general_ledger_columns_match_ddl(db_conn):
    """GENERAL_LEDGER_COLUMNS 상수가 DDL 컬럼과 동기화되었는지 확인."""
    ddl_cols = _get_column_names(db_conn, "general_ledger")
    # created_at은 DEFAULT이므로 상수에서 제외
    ddl_without_meta = [c for c in ddl_cols if c != "created_at"]
    assert GENERAL_LEDGER_COLUMNS == ddl_without_meta


def test_anomaly_flags_columns_match_ddl(db_conn):
    """ANOMALY_FLAGS_COLUMNS 상수가 DDL 컬럼과 동기화되었는지 확인."""
    ddl_cols = _get_column_names(db_conn, "anomaly_flags")
    ddl_without_meta = [c for c in ddl_cols if c != "created_at"]
    assert ANOMALY_FLAGS_COLUMNS == ddl_without_meta


def test_benford_summary_columns_match_ddl(db_conn):
    """BENFORD_SUMMARY_COLUMNS 상수가 DDL 컬럼과 동기화되었는지 확인."""
    ddl_cols = _get_column_names(db_conn, "benford_summary")
    ddl_without_meta = [c for c in ddl_cols if c != "created_at"]
    assert BENFORD_SUMMARY_COLUMNS == ddl_without_meta


def test_benford_digits_columns_match_ddl(db_conn):
    """BENFORD_DIGITS_COLUMNS 상수가 DDL 컬럼과 동기화되었는지 확인."""
    ddl_cols = _get_column_names(db_conn, "benford_digits")
    ddl_without_meta = [c for c in ddl_cols if c != "created_at"]
    assert BENFORD_DIGITS_COLUMNS == ddl_without_meta


# ── VIEW 쿼리 동작 검증 ─────────────────────────────────────────

def test_anomaly_flag_summary_view_queryable(db_conn):
    """anomaly_flag_summary VIEW가 빈 상태에서도 정상 조회되는지 확인."""
    result = db_conn.execute("SELECT * FROM anomaly_flag_summary").fetchall()
    assert result == []
