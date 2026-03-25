"""test_db 공통 픽스처.

Why: 모든 DB 테스트에 in-memory 커넥션을 주입하여
     실제 파일 DB에 영향 없이 격리된 테스트 실행.
"""

from __future__ import annotations

import duckdb
import pytest

from src.db.connection import _override_connection, close_connection
from src.db.schema import initialize_schema


@pytest.fixture(autouse=True)
def db_conn():
    """in-memory DuckDB 커넥션을 전역 싱글톤으로 주입한다."""
    conn = duckdb.connect(":memory:")
    _override_connection(conn)
    initialize_schema(conn)
    yield conn
    close_connection()
