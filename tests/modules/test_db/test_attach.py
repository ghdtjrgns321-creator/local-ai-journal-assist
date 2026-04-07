"""ATTACH 헬퍼 단위 테스트.

테스트 그룹:
  - 라이프사이클 (ATTACH → 쿼리 → DETACH)
  - 예외 시 DETACH 보장
  - READ_ONLY 검증
  - alias sanitize
"""

from __future__ import annotations

import duckdb
import pytest

from src.db.queries import attached_engagement
from src.db.schema import initialize_schema


# ── 픽스처 ──────────────────────────────────────────────────


@pytest.fixture()
def two_dbs(tmp_path):
    """두 개의 파일 기반 DuckDB — ATTACH 테스트용.

    Why: ATTACH는 대상 DB 파일의 exclusive lock이 필요하므로
         prior DB는 데이터 삽입 후 close하여 파일 핸들을 해제한다.
    """
    # current DB — 테스트 동안 열어둠
    current_path = str(tmp_path / "current.duckdb")
    current_conn = duckdb.connect(current_path)
    initialize_schema(current_conn)
    current_conn.execute(
        "INSERT INTO engagement_meta (company_id, engagement_id) VALUES (?, ?)",
        ["test_co", "current"],
    )

    # prior DB — 데이터 삽입 후 close (ATTACH를 위해 파일 핸들 해제)
    prior_path = str(tmp_path / "prior.duckdb")
    prior_conn = duckdb.connect(prior_path)
    initialize_schema(prior_conn)
    prior_conn.execute(
        "INSERT INTO engagement_meta (company_id, engagement_id) VALUES (?, ?)",
        ["test_co", "prior"],
    )
    prior_conn.close()

    yield current_conn, None, current_path, prior_path
    current_conn.close()


# ── 라이프사이클 ────────────────────────────────────────────


class TestLifecycle:
    """ATTACH → 쿼리 → DETACH 정상 흐름."""

    def test_attach_and_query(self, two_dbs):
        """ATTACH된 DB에서 데이터 조회 가능."""
        current_conn, _, _, prior_path = two_dbs
        with attached_engagement(current_conn, prior_path, "prior_year") as alias:
            row = current_conn.execute(
                f"SELECT engagement_id FROM {alias}.engagement_meta"
            ).fetchone()
            assert row == ("prior",)

    def test_detach_after_context(self, two_dbs):
        """with 블록 종료 후 alias 접근 불가."""
        current_conn, _, _, prior_path = two_dbs
        with attached_engagement(current_conn, prior_path, "prior_year"):
            pass  # 정상 종료
        with pytest.raises(duckdb.Error):
            current_conn.execute("SELECT * FROM prior_year.engagement_meta")


# ── 예외 시 DETACH 보장 ─────────────────────────────────────


class TestDetachOnException:
    """예외 발생 시에도 DETACH 실행."""

    def test_detach_on_error(self, two_dbs):
        """with 블록 내 예외 → DETACH 후 예외 재전파."""
        current_conn, _, _, prior_path = two_dbs
        with pytest.raises(ValueError, match="test error"):
            with attached_engagement(current_conn, prior_path, "prior_year"):
                raise ValueError("test error")
        # DETACH 확인: alias 접근 불가
        with pytest.raises(duckdb.Error):
            current_conn.execute("SELECT * FROM prior_year.engagement_meta")


# ── READ_ONLY 검증 ──────────────────────────────────────────


class TestReadOnly:
    """ATTACH된 DB는 READ_ONLY — 쓰기 시도 시 에러."""

    def test_write_to_attached_fails(self, two_dbs):
        """ATTACH(READ_ONLY) DB에 INSERT 시도 → 에러."""
        current_conn, _, _, prior_path = two_dbs
        with attached_engagement(current_conn, prior_path, "prior_year") as alias:
            with pytest.raises(duckdb.Error):
                current_conn.execute(
                    f"INSERT INTO {alias}.engagement_meta "
                    "(company_id, engagement_id) VALUES ('hack', 'attempt')"
                )


# ── alias sanitize ──────────────────────────────────────────


class TestAliasSanitize:
    """특수문자 포함 alias → 안전한 문자열로 치환."""

    def test_special_chars_sanitized(self, two_dbs):
        """alias에 특수문자가 있어도 정상 ATTACH."""
        current_conn, _, _, prior_path = two_dbs
        # 특수문자 포함 alias → underscore로 치환됨
        with attached_engagement(current_conn, prior_path, "prior-year.2024!") as alias:
            assert alias == "prior_year_2024_"
            row = current_conn.execute(
                f"SELECT engagement_id FROM {alias}.engagement_meta"
            ).fetchone()
            assert row == ("prior",)
