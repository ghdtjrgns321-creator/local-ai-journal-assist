"""싱글톤 DuckDB 커넥션 관리.

Why: 여러 모듈(loader, queries)이 동일 커넥션을 공유하되,
     Streamlit 멀티스레드 환경에서 이중 생성을 방지한다.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import duckdb

from config.settings import get_settings

logger = logging.getLogger(__name__)

_connection: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()


def get_connection(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """싱글톤 DuckDB 커넥션 반환.

    1. Lock 획득
    2. 기존 커넥션이 살아있으면 반환
    3. 없거나 무효 → 새 커넥션 생성 + 스키마 초기화
    """
    global _connection  # noqa: PLW0603

    with _lock:
        if _connection is not None and _is_alive(_connection):
            return _connection

        db_path = path or get_settings().duckdb_path
        # Why: DuckDB는 DB 파일을 자동 생성하지만 디렉토리는 수동 생성 필요
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            _connection = duckdb.connect(db_path)
        except duckdb.IOException as exc:
            logger.error("DuckDB 파일 잠금 — 다른 프로세스가 %s를 사용 중", db_path)
            raise RuntimeError(f"DuckDB 파일 잠금: {db_path}") from exc

        # Why: 순환 import 방지 — schema 모듈이 connection을 참조하지 않도록 지연 import
        from src.db.schema import initialize_schema

        initialize_schema(_connection)
        logger.info("DuckDB 커넥션 생성: %s", db_path)
        return _connection


def close_connection() -> None:
    """커넥션 명시적 종료. Lock 보호 하에 close + None 리셋."""
    global _connection  # noqa: PLW0603

    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None
            logger.info("DuckDB 커넥션 종료")


def _override_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """테스트 전용 — 전역 커넥션을 외부 주입으로 교체."""
    global _connection  # noqa: PLW0603

    with _lock:
        # Why: 기존 커넥션이 파일 핸들을 잡고 있으면 누수 발생
        if _connection is not None and _is_alive(_connection):
            _connection.close()
        _connection = conn


def _is_alive(conn: duckdb.DuckDBPyConnection) -> bool:
    """SELECT 1 실행으로 커넥션 유효성 확인."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False
