"""query_helper — WHERE 절 빌더 + 안전 쿼리 실행 테스트."""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from src.db.schema import initialize_schema
from src.export.models import ExportFilter
from src.export.query_helper import build_where_clause, safe_query


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "qh_test.duckdb"
    c = duckdb.connect(str(db_path))
    initialize_schema(c)
    yield c
    c.close()


class TestBuildWhereClause:
    def test_only_batch_id_when_filters_empty(self) -> None:
        sql, params = build_where_clause(ExportFilter(), "BATCH_X")
        assert sql == "AND upload_batch_id = ?"
        assert params == ["BATCH_X"]

    def test_company_codes_uses_in_clause(self) -> None:
        sql, params = build_where_clause(
            ExportFilter(company_codes=["C001", "C002"]), "B"
        )
        assert "AND company_code IN (?,?)" in sql
        assert params == ["B", "C001", "C002"]

    def test_date_range_added(self) -> None:
        f = ExportFilter(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
        sql, params = build_where_clause(f, "B")
        assert "AND posting_date >= ?" in sql
        assert "AND posting_date <= ?" in sql
        assert date(2026, 1, 1) in params
        assert date(2026, 12, 31) in params

    def test_all_filters_combined(self) -> None:
        f = ExportFilter(
            company_codes=["C001"],
            business_processes=["P2P", "O2C"],
            risk_levels=["High"],
            document_types=["SA"],
        )
        sql, params = build_where_clause(f, "B")
        # Why: 모든 조건이 한 쿼리에 추가되었는지 점검 (배치 ID 1 + 5 = 6)
        assert params[0] == "B"
        assert len(params) == 1 + 1 + 2 + 1 + 1


class TestSafeQuery:
    def test_returns_dataframe_on_valid_query(self, conn) -> None:
        df = safe_query(conn, "SELECT 1 AS x", [])
        assert isinstance(df, pd.DataFrame)
        assert df.iloc[0]["x"] == 1

    def test_missing_table_returns_empty_dataframe(self, conn) -> None:
        # Why: CatalogException → graceful 빈 DataFrame
        df = safe_query(conn, "SELECT * FROM nonexistent_table_xyz", [])
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_syntax_error_returns_empty(self, conn) -> None:
        # Why: 일반 예외도 graceful 처리
        df = safe_query(conn, "SELEC * FORM bad_syntax", [])
        assert df.empty

    def test_connection_error_propagates(self, tmp_path) -> None:
        # Why: 커넥션 단절은 빈 보고서 양산을 막기 위해 상위로 전파.
        db_path = tmp_path / "closed.duckdb"
        c = duckdb.connect(str(db_path))
        initialize_schema(c)
        c.close()
        with pytest.raises((RuntimeError, duckdb.ConnectionException)):
            safe_query(c, "SELECT 1", [])
