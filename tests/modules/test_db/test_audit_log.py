"""audit_log 테이블 + record_event() 헬퍼 테스트.

검증 항목:
1. 스키마 초기화 후 audit_log 테이블 + 시퀀스 존재
2. record_event() 호출 → INSERT 성공
3. DuckDB 락 충돌 시 execute_write 재시도 경유
4. 영구 실패 시 호출측에 예외 전파되지 않음 (graceful)
5. 마이그레이션 v2→v3에서 audit_log 신규 생성
"""

from __future__ import annotations

import json
from unittest.mock import patch

import duckdb
import pytest

from src.db.audit_log import record_event
from src.db.migration import CURRENT_SCHEMA_VERSION, run_migrations
from src.db.queries import execute_write
from src.db.schema import SCHEMA_DDL


# ── 스키마 존재 검증 ─────────────────────────────────────────


class TestAuditLogSchema:
    """audit_log DDL 등록 + 초기화 검증."""

    def test_table_exists_after_init(self, db_conn):
        """initialize_schema() 후 audit_log 테이블이 존재한다."""
        row = db_conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log'"
        ).fetchone()
        assert row is not None

    def test_required_columns(self, db_conn):
        """audit_log 컬럼 7개 + id + created_at가 존재한다."""
        cols = set(
            db_conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'audit_log'"
            ).fetchdf()["column_name"]
        )
        expected = {
            "id", "action", "actor", "company_id", "engagement_id",
            "batch_id", "target_id", "details", "created_at",
        }
        assert expected.issubset(cols), f"누락: {expected - cols}"

    def test_sequence_exists(self, db_conn):
        """audit_log_id_seq 시퀀스가 등록되어 있다."""
        # Why: DuckDB는 nextval()을 직접 호출하면 검증 가능
        result = db_conn.execute("SELECT nextval('audit_log_id_seq')").fetchone()
        assert result is not None and result[0] >= 1


# ── record_event 기본 동작 ──────────────────────────────────


class TestRecordEvent:
    """record_event() INSERT 정상 동작."""

    def test_inserts_row(self, db_conn):
        """record_event() 호출 → audit_log에 1행 INSERT."""
        record_event(
            db_conn,
            action="detection_run",
            company_id="C001",
            engagement_id="ENG-2024",
            batch_id="batch_abc",
            target_id="journal.csv",
            details={"row_count": 1000, "anomaly_count": 5},
        )

        row = db_conn.execute(
            "SELECT action, company_id, engagement_id, batch_id, target_id, details "
            "FROM audit_log"
        ).fetchone()
        assert row is not None
        action, company_id, engagement_id, batch_id, target_id, details = row
        assert action == "detection_run"
        assert company_id == "C001"
        assert engagement_id == "ENG-2024"
        assert batch_id == "batch_abc"
        assert target_id == "journal.csv"
        # Why: details는 JSON 직렬화된 문자열로 저장됨
        parsed = json.loads(details)
        assert parsed == {"row_count": 1000, "anomaly_count": 5}

    def test_optional_fields_default_to_null(self, db_conn):
        """company_id 등 옵션 인자 미지정 시 NULL 저장."""
        record_event(db_conn, action="whitelist_remove", target_id="42")

        row = db_conn.execute(
            "SELECT action, company_id, engagement_id, batch_id, target_id "
            "FROM audit_log"
        ).fetchone()
        assert row == ("whitelist_remove", None, None, None, "42")

    def test_actor_defaults_to_auditor(self, db_conn):
        """actor 미지정 시 'auditor' 기본값."""
        record_event(db_conn, action="detection_run")
        actor = db_conn.execute("SELECT actor FROM audit_log").fetchone()[0]
        assert actor == "auditor"

    def test_details_handles_numpy_types(self, db_conn):
        """details에 numpy/pandas 타입이 들어와도 default=str로 직렬화 성공."""
        import numpy as np
        record_event(
            db_conn,
            action="detection_run",
            details={"score": np.float64(0.85), "count": np.int64(100)},
        )
        details = db_conn.execute("SELECT details FROM audit_log").fetchone()[0]
        parsed = json.loads(details)
        # Why: default=str 경유 시 문자열로 변환되어 저장될 수 있으므로 존재만 확인
        assert "score" in parsed and "count" in parsed


# ── 락 충돌 재시도 시나리오 ─────────────────────────────────


class TestRetryOnLockConflict:
    """execute_write() 재시도 경유 검증 — DuckDB single-writer 락 충돌 대응.

    Why: DuckDB 커넥션 객체의 execute 속성은 read-only라 직접 patch 불가.
         대신 src.db.audit_log 모듈이 import한 execute_write를 patch하여
         "record_event가 retry-aware 래퍼를 경유하는가"를 검증한다.
         execute_write 내부의 실제 재시도 동작은 test_queries.py가 별도 커버.
    """

    def test_uses_execute_write_wrapper(self, db_conn):
        """record_event는 raw conn.execute가 아닌 execute_write를 호출한다."""
        with patch("src.db.audit_log.execute_write") as mock_write:
            record_event(
                db_conn,
                action="whitelist_add",
                target_id="JE-001",
                details={"rule_codes": ["L4-01"]},
            )
            mock_write.assert_called_once()
            # Why: 첫 인자는 conn, 두 번째는 'insert_audit_log' 프리셋명
            args = mock_write.call_args.args
            assert args[1] == "insert_audit_log"
            # Why: 파라미터 튜플에 action='whitelist_add' 포함
            params = args[2]
            assert params[0] == "whitelist_add"

    def test_permanent_failure_is_graceful(self, db_conn):
        """execute_write가 IOException 영구 실패해도 호출측에 전파되지 않음."""
        def always_fail(*args, **kwargs):
            raise duckdb.IOException("permanent lock")

        with patch("src.db.audit_log.execute_write", side_effect=always_fail):
            # Why: 예외 전파 없이 정상 반환되어야 함 (graceful)
            record_event(db_conn, action="detection_run", batch_id="b1")
        # Why: 본 흐름이 차단되지 않았으므로 후속 작업 가능 — 별도 INSERT 검증
        record_event(db_conn, action="detection_run", batch_id="b2")
        cnt = db_conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        # Why: patch 해제 후의 두 번째 호출만 성공
        assert cnt == 1

    def test_generic_exception_is_graceful(self, db_conn):
        """execute_write가 임의 예외를 던져도 graceful."""
        with patch(
            "src.db.audit_log.execute_write",
            side_effect=RuntimeError("unexpected"),
        ):
            # Why: 어떤 예외든 호출측에 전파되면 안 됨
            record_event(db_conn, action="detection_run")


# ── 마이그레이션 v2 → v3 ────────────────────────────────────


def _create_v2_db() -> duckdb.DuckDBPyConnection:
    """audit_log가 없는 v2 상태 DB 생성 — 마이그레이션 대상."""
    conn = duckdb.connect(":memory:")
    # Why: schema_supplementary는 audit_log와 무관하므로 일단 core만 생성
    for name, ddl in SCHEMA_DDL.items():
        if name in ("audit_log", "audit_log_seq", "feedback_events", "feedback_events_seq"):
            continue
        conn.execute(ddl)
    return conn


class TestMigrateV2ToV3:
    """v2 → v3: audit_log 테이블 신규 생성."""

    def test_creates_audit_log(self):
        conn = _create_v2_db()
        # Why: v2 상태에서는 audit_log가 없어야 함
        before = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log'"
        ).fetchone()
        assert before is None

        run_migrations(conn)

        after = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log'"
        ).fetchone()
        assert after is not None
        conn.close()

    def test_idempotent(self):
        conn = _create_v2_db()
        run_migrations(conn)
        run_migrations(conn)  # 2회차 — 멱등성

        # Why: record_event 정상 동작 확인 (테이블 손상 없음)
        record_event(conn, action="detection_run")
        cnt = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert cnt == 1
        conn.close()

    def test_full_schema_returns_current_version(self, db_conn):
        """최신 DDL DB는 마이그레이션 후 CURRENT_SCHEMA_VERSION 반환."""
        result = run_migrations(db_conn)
        assert result == CURRENT_SCHEMA_VERSION
