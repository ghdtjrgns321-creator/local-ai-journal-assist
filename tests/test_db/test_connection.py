"""connection.py 단위 테스트.

테스트 항목:
  1. 싱글톤 동작 — 두 번 호출 시 동일 객체
  2. close 후 재호출 — 새 커넥션 생성
  3. health check 실패 — closed 커넥션 자동 재생성
  4. _override_connection — 주입 커넥션 반환 확인
"""

from __future__ import annotations

import duckdb

from src.db.connection import (
    _override_connection,
    close_connection,
    get_connection,
)


class TestSingleton:
    """싱글톤 동작 검증."""

    def test_same_object_on_double_call(self, db_conn):
        """두 번 호출 시 동일 커넥션 객체를 반환한다."""
        conn1 = get_connection()
        conn2 = get_connection()
        assert conn1 is conn2

    def test_new_connection_after_close(self, db_conn):
        """close 후 재호출 시 새 커넥션이 생성된다."""
        conn_before = get_connection()
        close_connection()

        # close 이후 새 in-memory 커넥션 주입
        new_conn = duckdb.connect(":memory:")
        _override_connection(new_conn)

        conn_after = get_connection()
        assert conn_after is not conn_before
        assert conn_after is new_conn


class TestHealthCheck:
    """커넥션 유효성 검사 검증."""

    def test_auto_recreate_on_closed_connection(self):
        """closed 커넥션 감지 시 get_connection()이 새 커넥션을 생성한다."""
        # 수동으로 closed 커넥션 주입
        dead_conn = duckdb.connect(":memory:")
        dead_conn.close()
        _override_connection(dead_conn)

        # get_connection은 health check 실패 → :memory:로 재생성
        conn = get_connection(":memory:")
        assert conn is not dead_conn

        # 새 커넥션이 유효한지 확인
        result = conn.execute("SELECT 42 AS answer").fetchone()
        assert result[0] == 42

        # cleanup
        close_connection()


class TestOverride:
    """테스트 주입 함수 검증."""

    def test_override_replaces_global(self):
        """_override_connection으로 주입한 커넥션이 get_connection()에서 반환된다."""
        injected = duckdb.connect(":memory:")
        _override_connection(injected)

        assert get_connection() is injected

        # cleanup
        close_connection()
