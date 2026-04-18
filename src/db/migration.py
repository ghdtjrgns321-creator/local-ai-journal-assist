"""DuckDB 스키마 마이그레이션 — 기존 DB에 누락 컬럼 추가.

Why: CREATE TABLE IF NOT EXISTS는 기존 테이블에 새 컬럼을 추가하지 않음.
     schema_version 기반 순차 마이그레이션으로 기존 engagement DB를
     최신 DDL과 동기화한다.
     실패 시 ROLLBACK을 시도하되, DuckDB DDL 롤백은 공식 보장 아님.
     _migrate 함수의 멱등성(skip 로직)이 안전망 역할을 한다.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

# Why: 새 마이그레이션 추가 시 이 값을 올리고 _MIGRATIONS에 함수 등록
CURRENT_SCHEMA_VERSION = 4

# Why: v2에서 general_ledger에 추가할 ML 예약 7개 컬럼
#      schema.py의 ML_RESERVED_COLUMNS와 동일 집합이어야 함.
#      schema.py 변경 시 이 딕셔너리도 함께 업데이트할 것.
_V2_COLUMNS: dict[str, str] = {
    "supervised_score": "DOUBLE",
    "unsupervised_score": "DOUBLE",
    "duplicate_score": "DOUBLE",
    "supervised_model_id": "VARCHAR",
    "unsupervised_model_id": "VARCHAR",
    "duplicate_model_id": "VARCHAR",
    "ml_scored_at": "TIMESTAMP",
}

# Why: v3에서 추가할 audit_log 테이블명. _get_schema_version()의 추론 분기에서 사용.
_V3_TABLE = "audit_log"
_V4_TABLE = "feedback_events"
_V4_PERFORMANCE_COLUMNS = {
    "false_positive_docs": "INTEGER DEFAULT 0",
    "confirmed_issue_docs": "INTEGER DEFAULT 0",
}


# ── 공개 API ───────────────────────────────────────────────


# Why: 마이그레이션 레지스트리 — 버전별 함수를 등록하면 자동 순차 실행
#      v3 추가 시 함수만 작성하고 여기 등록하면 됨
_MIGRATIONS: dict[int, str] = {
    2: "_migrate_v1_to_v2",
    3: "_migrate_v2_to_v3",
    4: "_migrate_v3_to_v4",
}


def run_migrations(conn: duckdb.DuckDBPyConnection) -> int:
    """schema_version 기준 순차 마이그레이션 실행.

    실패 시 ROLLBACK을 시도하되 DuckDB DDL 롤백은 공식 보장 아님.
    _migrate 함수의 멱등성(information_schema skip 로직)이 안전망.
    Returns: 최종 schema_version.
    """
    current = _get_schema_version(conn)
    if current >= CURRENT_SCHEMA_VERSION:
        return current

    logger.info("스키마 마이그레이션 시작: v%d → v%d", current, CURRENT_SCHEMA_VERSION)
    try:
        conn.execute("BEGIN TRANSACTION")
        for target_version in sorted(_MIGRATIONS):
            if current < target_version:
                globals()[_MIGRATIONS[target_version]](conn)
        _set_schema_version(conn, CURRENT_SCHEMA_VERSION)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        logger.error("마이그레이션 실패 — ROLLBACK 시도 완료")
        raise

    logger.info("스키마 마이그레이션 완료: v%d", CURRENT_SCHEMA_VERSION)
    return CURRENT_SCHEMA_VERSION


# ── 버전 관리 ──────────────────────────────────────────────


def _get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    """engagement_meta에서 MAX(schema_version) 조회.

    행이 없으면 information_schema로 현재 DDL 상태를 추론:
    - ML 컬럼이 이미 존재 → CURRENT_SCHEMA_VERSION (새 DDL로 생성된 DB)
    - ML 컬럼이 없음 → 1 (레거시 DB)
    """
    row = conn.execute(
        "SELECT MAX(schema_version) FROM engagement_meta"
    ).fetchone()
    if row is not None and row[0] is not None:
        return int(row[0])

    # Why: engagement_meta에 행이 없으면 DDL 상태로 버전 추론.
    #      새 DDL로 생성된 DB는 이미 ML 컬럼 + audit_log 테이블이 있으므로 마이그레이션 불필요.
    existing_cols = set(
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()["column_name"]
    )
    has_v2 = _V2_COLUMNS.keys() <= existing_cols
    if not has_v2:
        return 1

    # Why: v3 판정은 audit_log 테이블 존재 여부로 분기
    has_audit_log = bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = ?",
            [_V3_TABLE],
        ).fetchone()
    )
    if not has_audit_log:
        return 2

    has_feedback_events = bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = ?",
            [_V4_TABLE],
        ).fetchone()
    )
    has_performance_reports = bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'performance_reports'"
        ).fetchone()
    )
    if has_feedback_events and not has_performance_reports:
        return CURRENT_SCHEMA_VERSION

    existing_perf_cols = set(
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'performance_reports'"
        ).fetchdf()["column_name"]
    )
    has_v4_perf = _V4_PERFORMANCE_COLUMNS.keys() <= existing_perf_cols
    if has_feedback_events and has_v4_perf:
        return CURRENT_SCHEMA_VERSION
    return 3


def _set_schema_version(conn: duckdb.DuckDBPyConnection, version: int) -> None:
    """engagement_meta의 schema_version 업데이트.

    Why: engagement별 격리 DB 구조(RC-3) 전제 — WHERE 절 없이 전체 행 갱신.
         행이 없으면(새 DB) UPDATE 영향 0행 → 더미 행 삽입 없이 skip.
         실제 engagement 행이 적재될 때 schema_version DEFAULT로 자동 설정됨.
         비어있는 동안 _get_schema_version()은 information_schema 추론 경로를 탄다.
    """
    conn.execute(
        "UPDATE engagement_meta SET schema_version = ?", [version]
    )
    count = conn.execute("SELECT COUNT(*) FROM engagement_meta").fetchone()[0]
    if count > 0:
        logger.info("engagement_meta schema_version → %d (%d행 업데이트)", version, count)
    else:
        logger.info("engagement_meta 비어있음 — 다음 적재 시 schema_version=%d 적용 예정", version)


# ── 마이그레이션 함수 ──────────────────────────────────────


def _migrate_v1_to_v2(conn: duckdb.DuckDBPyConnection) -> None:
    """ML 예약 7개 컬럼을 general_ledger에 추가.

    information_schema로 기존 컬럼 확인 후 누락분만 ALTER TABLE ADD.
    이미 존재하는 컬럼은 skip (새 DDL로 생성된 DB에서 no-op).
    """
    existing = set(
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'general_ledger'"
        ).fetchdf()["column_name"]
    )

    added = []
    for col, dtype in _V2_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE general_ledger ADD COLUMN {col} {dtype}")
            added.append(col)

    if added:
        logger.info("v1→v2: %d개 컬럼 추가 — %s", len(added), ", ".join(added))
    else:
        logger.info("v1→v2: 모든 ML 컬럼 이미 존재 — skip")


def _migrate_v2_to_v3(conn: duckdb.DuckDBPyConnection) -> None:
    """audit_log 테이블 + 시퀀스 추가 — ISO 27001 / SOC 2 감사증적 대응.

    Why: 기존 engagement DB에는 audit_log 테이블이 없으므로 신규 생성.
         schema.py의 SCHEMA_DDL과 동일한 정의를 사용해야 하므로 그대로 import 후 실행한다.
         CREATE ... IF NOT EXISTS로 멱등성 보장.
    """
    from src.db.schema import SCHEMA_DDL
    conn.execute(SCHEMA_DDL["audit_log_seq"])
    conn.execute(SCHEMA_DDL["audit_log"])
    logger.info("v2→v3: audit_log 테이블 + 시퀀스 생성 완료")


def _migrate_v3_to_v4(conn: duckdb.DuckDBPyConnection) -> None:
    """feedback_events 및 performance_reports HITL 지표 컬럼 추가."""
    from src.db.schema import SCHEMA_DDL

    conn.execute(SCHEMA_DDL["feedback_events_seq"])
    conn.execute(SCHEMA_DDL["feedback_events"])

    has_performance_reports = bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'performance_reports'"
        ).fetchone()
    )
    if not has_performance_reports:
        logger.info("v3→v4: feedback_events 생성, performance_reports 없음 -> 컬럼 추가 skip")
        return

    existing_perf_cols = set(
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'performance_reports'"
        ).fetchdf()["column_name"]
    )
    added = []
    for col, dtype in _V4_PERFORMANCE_COLUMNS.items():
        if col not in existing_perf_cols:
            conn.execute(f"ALTER TABLE performance_reports ADD COLUMN {col} {dtype}")
            added.append(col)
    logger.info(
        "v3→v4: feedback_events 생성, performance_reports 추가 컬럼=%s",
        ", ".join(added) if added else "none",
    )
