"""경로별 DuckDB 커넥션 관리 — ConnectionManager.

Why: Company-Centric 아키텍처에서 여러 회사 × 여러 연도의 DB를
     동시에 다루려면 경로별 커넥션 캐시가 필요하다.
     Streamlit 멀티스레드 환경에서 이중 생성을 방지한다.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import duckdb

from config.settings import get_settings

logger = logging.getLogger(__name__)


# ── 유틸리티 ────────────────────────────────────────────────


def _is_alive(conn: duckdb.DuckDBPyConnection) -> bool:
    """SELECT 1 실행으로 커넥션 유효성 확인."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


# ── ConnectionManager ───────────────────────────────────────


class ConnectionManager:
    """경로별 DuckDB 커넥션 캐시.

    - get(db_path): 캐시 hit → 반환, miss → 생성 + 스키마 초기화
    - close(db_path): 특정 경로 커넥션 종료
    - close_all(): 전체 캐시 종료
    - :memory: 커넥션은 캐시하지 않음 (매번 새로 생성, 테스트 격리)
    """

    def __init__(self) -> None:
        self._connections: dict[str, duckdb.DuckDBPyConnection] = {}
        self._lock = threading.Lock()

    def get(self, db_path: str | Path) -> duckdb.DuckDBPyConnection:
        """경로별 커넥션 반환. 없거나 무효하면 생성 + 스키마 초기화."""
        key = str(db_path)

        # Why: :memory: 는 매번 독립 커넥션이 필요 (테스트 격리, 익명 파이프라인)
        if key == ":memory:":
            conn = duckdb.connect(":memory:")
            from src.db.schema import initialize_schema

            initialize_schema(conn)
            from src.db.migration import run_migrations

            run_migrations(conn)
            return conn

        with self._lock:
            cached = self._connections.get(key)
            if cached is not None and _is_alive(cached):
                return cached

            # Why: DuckDB는 DB 파일을 자동 생성하지만 디렉토리는 수동 생성 필요
            Path(key).parent.mkdir(parents=True, exist_ok=True)

            try:
                conn = duckdb.connect(key)
            except duckdb.IOException:
                # Why: 이전 프로세스가 비정상 종료하면 WAL 파일이 잠금을 잡고 있음.
                #      WAL 삭제 후 1회 재시도. 프로세스가 살아있으면 재시도도 실패 → raise.
                wal = Path(f"{key}.wal")
                if wal.exists():
                    logger.warning("DuckDB WAL 잠금 감지 — %s 삭제 후 재시도", wal)
                    try:
                        wal.unlink()
                    except OSError:
                        pass
                try:
                    conn = duckdb.connect(key)
                except duckdb.IOException as exc2:
                    logger.error("DuckDB 파일 잠금 재시도 실패: %s", key)
                    raise RuntimeError(f"DuckDB 파일 잠금: {key}") from exc2

            # Why: 순환 import 방지 — schema 모듈이 connection을 참조하지 않도록 지연 import
            from src.db.schema import initialize_schema

            initialize_schema(conn)

            from src.db.migration import run_migrations

            run_migrations(conn)

            self._connections[key] = conn
            logger.info("DuckDB 커넥션 생성: %s", key)
            return conn

    def close(self, db_path: str | Path) -> None:
        """특정 경로 커넥션 종료."""
        key = str(db_path)
        with self._lock:
            conn = self._connections.pop(key, None)
            if conn is not None:
                conn.close()
                logger.info("DuckDB 커넥션 종료: %s", key)

    def close_all(self) -> None:
        """모든 캐시 커넥션 종료."""
        with self._lock:
            for key, conn in self._connections.items():
                try:
                    conn.close()
                    logger.info("DuckDB 커넥션 종료: %s", key)
                except Exception:
                    logger.warning("커넥션 종료 실패: %s", key, exc_info=True)
            self._connections.clear()


# ── 모듈 레벨 싱글톤 ────────────────────────────────────────

_manager = ConnectionManager()

# Why: _override_connection()에서 테스트용 커넥션 주입 시 사용
_override_conn: duckdb.DuckDBPyConnection | None = None
_override_lock = threading.Lock()


# ── 하위 호환 래퍼 (기존 시그니처 유지) ─────────────────────


def get_connection(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """하위 호환 래퍼 — 기존 `get_connection(path=None)` 시그니처 유지.

    _override_conn이 설정되어 있으면 우선 반환 (테스트 전용).
    """
    global _override_conn  # noqa: PLW0602

    with _override_lock:
        if _override_conn is not None and _is_alive(_override_conn):
            return _override_conn

    db_path = path or get_settings().duckdb_path
    return _manager.get(db_path)


def close_connection(path: str | Path | None = None) -> None:
    """하위 호환 래퍼 — 특정 경로 또는 모든 캐시 커넥션 종료."""
    if path is None:
        _manager.close_all()
    else:
        _manager.close(path)


def get_connection_manager() -> ConnectionManager:
    """Return the process-wide connection manager singleton."""
    return _manager


def _override_connection(conn: duckdb.DuckDBPyConnection) -> None:
    """테스트 전용 — 전역 커넥션을 외부 주입으로 교체."""
    global _override_conn  # noqa: PLW0603

    with _override_lock:
        # Why: 기존 override 커넥션이 파일 핸들을 잡고 있으면 누수 발생
        if _override_conn is not None and _is_alive(_override_conn):
            _override_conn.close()
        _override_conn = conn


def _clear_override() -> None:
    """테스트 전용 — override 상태 해제."""
    global _override_conn  # noqa: PLW0603

    with _override_lock:
        _override_conn = None
