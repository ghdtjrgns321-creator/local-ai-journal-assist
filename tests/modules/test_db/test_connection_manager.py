"""ConnectionManager 단위 테스트 + 통합 테스트.

테스트 그룹:
  - 멀티 경로 격리
  - 캐시 재사용
  - close 단일/전체
  - dead conn 재연결
  - :memory: 비캐시
  - 스레드 안전성
  - 통합: 2회사×2연도 4개 독립 DB
"""

from __future__ import annotations

import threading

import duckdb
import pytest

from src.db.connection import ConnectionManager
from src.db.schema import initialize_schema


# ── 픽스처 ──────────────────────────────────────────────────


@pytest.fixture()
def manager():
    """테스트용 ConnectionManager 인스턴스."""
    mgr = ConnectionManager()
    yield mgr
    mgr.close_all()


# ── 멀티 경로 격리 ──────────────────────────────────────────


class TestMultiPath:
    """경로별 독립 커넥션 관리."""

    def test_different_paths_return_different_conns(self, manager, tmp_path):
        """서로 다른 경로 → 서로 다른 conn 객체."""
        p1 = str(tmp_path / "a.duckdb")
        p2 = str(tmp_path / "b.duckdb")
        c1 = manager.get(p1)
        c2 = manager.get(p2)
        assert c1 is not c2

    def test_same_path_returns_cached(self, manager, tmp_path):
        """같은 경로 2회 호출 → 동일 conn 객체 (캐시)."""
        p = str(tmp_path / "test.duckdb")
        c1 = manager.get(p)
        c2 = manager.get(p)
        assert c1 is c2

    def test_schema_initialized_on_create(self, manager, tmp_path):
        """새 커넥션 생성 시 스키마 자동 초기화."""
        p = str(tmp_path / "test.duckdb")
        conn = manager.get(p)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchdf()
        assert "general_ledger" in tables["table_name"].values
        assert "engagement_meta" in tables["table_name"].values


# ── Close 동작 ──────────────────────────────────────────────


class TestClose:
    """커넥션 종료 동작."""

    def test_close_single_leaves_others(self, manager, tmp_path):
        """close(path_a) 후 path_b는 살아있음."""
        p1 = str(tmp_path / "a.duckdb")
        p2 = str(tmp_path / "b.duckdb")
        manager.get(p1)
        c2 = manager.get(p2)
        manager.close(p1)
        # p2 커넥션은 여전히 유효
        assert c2.execute("SELECT 1").fetchone() == (1,)

    def test_close_all(self, manager, tmp_path):
        """close_all() 후 모든 커넥션 종료."""
        paths = [str(tmp_path / f"{i}.duckdb") for i in range(3)]
        conns = [manager.get(p) for p in paths]
        manager.close_all()
        # 모든 커넥션이 무효화됨
        for conn in conns:
            with pytest.raises(duckdb.Error):
                conn.execute("SELECT 1")


# ── Dead conn 재연결 ────────────────────────────────────────


class TestAutoReconnect:
    """캐시된 커넥션이 죽었을 때 자동 재생성."""

    def test_dead_conn_auto_reconnect(self, manager, tmp_path):
        """외부에서 close된 커넥션 → get() 시 새로 생성."""
        p = str(tmp_path / "test.duckdb")
        c1 = manager.get(p)
        c1.close()  # 외부 강제 종료
        c2 = manager.get(p)
        assert c2.execute("SELECT 1").fetchone() == (1,)
        assert c2 is not c1


# ── :memory: 비캐시 ─────────────────────────────────────────


class TestMemory:
    """:memory: 커넥션은 캐시하지 않음."""

    def test_memory_not_cached(self, manager):
        """매번 새 :memory: 커넥션 생성."""
        c1 = manager.get(":memory:")
        c2 = manager.get(":memory:")
        assert c1 is not c2
        c1.close()
        c2.close()

    def test_memory_has_schema(self, manager):
        """:memory: 커넥션에도 스키마 초기화."""
        conn = manager.get(":memory:")
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchdf()
        assert "general_ledger" in tables["table_name"].values
        conn.close()


# ── 스레드 안전성 ───────────────────────────────────────────


class TestThreadSafety:
    """멀티스레드에서 동시 get() 호출."""

    def test_concurrent_get_same_path(self, manager, tmp_path):
        """10개 스레드가 동시에 같은 경로 get() → 충돌 없음."""
        p = str(tmp_path / "thread_test.duckdb")
        results: list[duckdb.DuckDBPyConnection] = []
        errors: list[Exception] = []

        def worker():
            try:
                conn = manager.get(p)
                results.append(conn)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 모든 스레드가 동일 캐시 커넥션을 받아야 함
        assert all(r is results[0] for r in results)


# ── 통합: 2회사×2연도 4개 독립 DB ───────────────────────────


class TestFourIndependentDbs:
    """완료 기준: 2회사 × 2연도 → 4개 독립 DB 파일."""

    def test_four_independent_dbs(self, manager, tmp_path):
        """4개 독립 DB 생성 + 데이터 격리 확인."""
        paths = {}
        for company in ["acme", "beta"]:
            for year in ["2024", "2025"]:
                p = tmp_path / company / year / "audit.duckdb"
                conn = manager.get(str(p))
                # Why: 각 DB에 회사/연도 구분 가능한 식별 데이터 INSERT
                conn.execute(
                    "INSERT INTO engagement_meta (company_id, engagement_id) VALUES (?, ?)",
                    [company, year],
                )
                paths[(company, year)] = str(p)

        # 4개 파일 모두 존재
        from pathlib import Path as P
        assert all(P(p).exists() for p in paths.values())

        # 각 DB가 자기 데이터만 보유 (격리 검증)
        for (company, year), p in paths.items():
            conn = manager.get(p)
            row = conn.execute(
                "SELECT company_id, engagement_id FROM engagement_meta"
            ).fetchone()
            assert row == (company, year)

    def test_attach_cross_query(self, manager, tmp_path):
        """ATTACH로 두 engagement DB 간 교차 쿼리 성공."""
        from src.db.queries import attached_engagement

        p_2024 = str(tmp_path / "acme" / "2024" / "audit.duckdb")
        p_2025 = str(tmp_path / "acme" / "2025" / "audit.duckdb")

        # 각 DB에 engagement_meta 데이터 삽입
        c24 = manager.get(p_2024)
        c24.execute(
            "INSERT INTO engagement_meta (company_id, engagement_id) VALUES ('acme', '2024')"
        )
        c25 = manager.get(p_2025)
        c25.execute(
            "INSERT INTO engagement_meta (company_id, engagement_id) VALUES ('acme', '2025')"
        )

        # Why: ATTACH는 대상 DB의 exclusive lock이 필요 → 2024 conn을 먼저 close
        manager.close(p_2024)

        # 2025 DB에서 2024 DB를 ATTACH하여 교차 쿼리
        c25 = manager.get(p_2025)
        with attached_engagement(c25, p_2024, "prior") as alias:
            result = c25.execute(
                f"SELECT company_id, engagement_id FROM {alias}.engagement_meta"
            ).fetchone()
            assert result == ("acme", "2024")

        # DETACH 후 alias 접근 불가 확인
        with pytest.raises(duckdb.Error):
            c25.execute("SELECT * FROM prior.engagement_meta")
