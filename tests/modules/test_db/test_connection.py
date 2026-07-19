"""connection.py 단위 테스트.

테스트 그룹:
  - 싱글톤 동작
  - close 후 재연결
  - health check 실패 시 재생성
  - _override_connection 주입
"""

import duckdb

from src.db.connection import (
    _clear_override,
    _is_alive,
    _override_connection,
    close_connection,
    get_connection,
)


class TestSingleton:
    """싱글톤 커넥션 동작."""

    def test_same_object_returned(self, tmp_path):
        """두 번 호출 시 동일 객체 반환."""
        db_path = str(tmp_path / "test.duckdb")
        conn1 = get_connection(db_path)
        conn2 = get_connection(db_path)
        assert conn1 is conn2
        close_connection()

    def test_close_and_reconnect(self, tmp_path):
        """close 후 재호출 시 새 커넥션 생성."""
        db_path = str(tmp_path / "test.duckdb")
        conn1 = get_connection(db_path)
        close_connection()
        conn2 = get_connection(db_path)
        assert conn2 is not conn1
        close_connection()


class TestHealthCheck:
    """커넥션 유효성 확인."""

    def test_alive_connection(self):
        """정상 커넥션은 True 반환."""
        conn = duckdb.connect(":memory:")
        assert _is_alive(conn) is True
        conn.close()

    def test_closed_connection(self):
        """닫힌 커넥션은 False 반환."""
        conn = duckdb.connect(":memory:")
        conn.close()
        assert _is_alive(conn) is False

    def test_auto_reconnect_on_dead(self, tmp_path):
        """닫힌 커넥션 감지 시 자동 재생성."""
        db_path = str(tmp_path / "test.duckdb")
        conn1 = get_connection(db_path)
        conn1.close()  # 외부에서 강제 종료
        conn2 = get_connection(db_path)
        assert _is_alive(conn2) is True
        close_connection()


class TestOverride:
    """테스트용 커넥션 주입."""

    def test_override_returns_injected(self, tmp_path):
        """_override_connection으로 주입한 커넥션 반환."""
        db_path = str(tmp_path / "test.duckdb")
        injected = duckdb.connect(":memory:")
        _override_connection(injected)
        conn = get_connection(db_path)
        assert conn is injected
        _clear_override()
        close_connection()
        injected.close()
