"""DuckDB 싱글톤 커넥션 관리.

Why: DB 레이어 진입점. loader·queries 등 여러 모듈이 동일 커넥션을 공유한다.
     threading.Lock으로 Streamlit 멀티스레드 환경에서 커넥션 이중 생성을 방지한다.
     DuckDB 파일 잠금(프로세스 간 충돌)은 DuckDB 자체가 감지하며, IOException으로 안내한다.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import duckdb

from config.settings import get_settings

logger = logging.getLogger(__name__)

# --- 모듈 레벨 싱글톤 ---
# Why: 커넥션은 open/closed 상태가 있어 @lru_cache 부적합.
#      close 후 재연결, 테스트 주입 등 상태 변경이 필요하므로 전역 변수 방식 사용.
_connection: duckdb.DuckDBPyConnection | None = None
_resolved_path: str | None = None  # Why: health check 실패 시 원래 path로 재연결하기 위해 저장
_lock = threading.Lock()


def get_connection(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """싱글톤 DuckDB 커넥션을 반환한다.

    Args:
        path: DB 파일 경로. None이면 settings.duckdb_path 사용.
              ":memory:"로 in-memory DB 생성 가능.

    Returns:
        활성 DuckDB 커넥션.

    Raises:
        duckdb.IOException: DB 파일이 다른 프로세스에 잠겨 있을 때.
    """
    global _connection, _resolved_path

    with _lock:
        # 기존 커넥션이 유효하면 그대로 반환
        if _connection is not None:
            if _is_alive(_connection):
                return _connection
            # Why: closed/손상된 커넥션 감지 → 폐기 후 재생성
            logger.warning("기존 DuckDB 커넥션 무효 — 재생성합니다")
            _connection = None

        # Why: path 미지정 시 이전에 저장된 경로 → settings 순서로 fallback
        #      health check 실패 후 무인수 재호출 시 원래 경로로 재연결 보장
        resolved = path or _resolved_path or get_settings().duckdb_path

        # Why: DuckDB는 DB 파일을 자동 생성하지만 디렉토리는 수동 생성 필요
        if resolved != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)

        try:
            _connection = duckdb.connect(resolved)
        except duckdb.IOException as e:
            logger.error(
                "DB 파일 잠금: 다른 프로세스(또는 다른 Streamlit 인스턴스)가 "
                "이미 %s 파일을 점유하고 있을 수 있습니다. — %s",
                resolved,
                e,
            )
            raise

        _resolved_path = resolved
        logger.info("DuckDB 커넥션 생성: %s", resolved)

        # Why: 순환 import 방지 — schema가 connection을 import할 수 있으므로 지연 import
        from src.db.schema import initialize_schema

        initialize_schema(_connection)

        return _connection


def close_connection() -> None:
    """커넥션을 명시적으로 종료한다.

    Streamlit 세션 종료, 테스트 teardown 등에서 호출.
    close 후 get_connection() 재호출 시 새 커넥션이 생성된다.
    """
    global _connection, _resolved_path

    with _lock:
        if _connection is not None:
            try:
                _connection.close()
            except Exception as e:
                logger.debug("커넥션 종료 중 예외 (이미 닫힘 가능): %s", e)
            _connection = None
            _resolved_path = None
            logger.info("DuckDB 커넥션 종료")


def _override_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """테스트 전용 — 전역 커넥션을 외부 주입 커넥션으로 교체한다.

    Why: loader·queries가 내부에서 get_connection()을 호출하면 path=None으로
         실제 파일 DB에 연결된다. 테스트에서는 :memory: 커넥션을 주입하여 격리.

    Usage (conftest.py):
        conn = duckdb.connect(":memory:")
        _override_connection(conn)
        initialize_schema(conn)
        yield conn
        close_connection()
    """
    global _connection, _resolved_path

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        logger.warning("_override_connection은 테스트 전용입니다")

    with _lock:
        _connection = conn
        _resolved_path = ":memory:"


def _is_alive(conn: duckdb.DuckDBPyConnection) -> bool:
    """커넥션 유효성을 확인한다. SELECT 1 실행 성공 여부로 판정."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False
