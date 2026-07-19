"""prior_data_loader 단위 테스트 — find_prior_engagement + load_prior_summary.

find_prior_engagement: Mock 기반 (CompanyRepository.list_engagements)
load_prior_summary: 임시 DuckDB 파일로 실제 ATTACH 동작 검증
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from src.company.models import EngagementProfile, EngagementStatus
from src.detection.prior_data_loader import (
    PriorSummary,
    find_prior_engagement,
    load_prior_summary,
)

# ── find_prior_engagement 테스트 ────────────────────────────


def _make_engagement(
    fiscal_year: int,
    status: EngagementStatus = EngagementStatus.DRAFT,
    engagement_id: str | None = None,
) -> EngagementProfile:
    """테스트용 EngagementProfile 생성 헬퍼."""
    eid = engagement_id or f"fy{fiscal_year}"
    return EngagementProfile(
        engagement_id=eid,
        company_id="test_co",
        fiscal_year=fiscal_year,
        status=status,
    )


class TestFindPriorEngagement:
    """find_prior_engagement 5개 케이스."""

    def test_completed_prior(self) -> None:
        """전기 COMPLETED engagement 반환."""
        repo = MagicMock()
        repo.list_engagements.return_value = [
            _make_engagement(2024, EngagementStatus.COMPLETED),
        ]
        result = find_prior_engagement(repo, "test_co", 2025)
        assert result is not None
        assert result.fiscal_year == 2024
        assert result.status == EngagementStatus.COMPLETED

    def test_in_progress_prior(self) -> None:
        """전기 IN_PROGRESS engagement 반환."""
        repo = MagicMock()
        repo.list_engagements.return_value = [
            _make_engagement(2024, EngagementStatus.IN_PROGRESS),
        ]
        result = find_prior_engagement(repo, "test_co", 2025)
        assert result is not None
        assert result.status == EngagementStatus.IN_PROGRESS

    def test_completed_over_in_progress(self) -> None:
        """COMPLETED + IN_PROGRESS 동시 존재 → COMPLETED 우선."""
        repo = MagicMock()
        repo.list_engagements.return_value = [
            _make_engagement(2024, EngagementStatus.IN_PROGRESS, "ip"),
            _make_engagement(2024, EngagementStatus.COMPLETED, "comp"),
        ]
        result = find_prior_engagement(repo, "test_co", 2025)
        assert result is not None
        assert result.engagement_id == "comp"

    def test_no_prior_year(self) -> None:
        """전기(fiscal_year-1) 미존재 → None."""
        repo = MagicMock()
        repo.list_engagements.return_value = [
            _make_engagement(2023, EngagementStatus.COMPLETED),
        ]
        result = find_prior_engagement(repo, "test_co", 2025)
        assert result is None

    def test_empty_engagements(self) -> None:
        """engagement 없음 → None."""
        repo = MagicMock()
        repo.list_engagements.return_value = []
        result = find_prior_engagement(repo, "test_co", 2025)
        assert result is None


# ── load_prior_summary 테스트 ───────────────────────────────


def _create_prior_db(db_path: Path) -> None:
    """테스트용 전기 DuckDB 생성 — general_ledger 테이블 + 샘플 데이터."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE general_ledger (
            gl_account   VARCHAR,
            debit_amount DOUBLE,
            credit_amount DOUBLE,
            fiscal_period INTEGER
        )
    """)
    # 계정 4110: 1~3월 데이터
    conn.execute("""
        INSERT INTO general_ledger VALUES
            ('4110', 100000, 0, 1),
            ('4110', 200000, 0, 2),
            ('4110', 150000, 0, 3),
            ('8220', 50000, 0, 1),
            ('8220', 30000, 0, 6)
    """)
    conn.close()


def _create_empty_prior_db(db_path: Path) -> None:
    """빈 general_ledger 테이블만 있는 DuckDB 생성."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE general_ledger (
            gl_account   VARCHAR,
            debit_amount DOUBLE,
            credit_amount DOUBLE,
            fiscal_period INTEGER
        )
    """)
    conn.close()


def _create_company_prior_db(db_path: Path) -> None:
    """Create a prior DB with company_code for company-aware D01 aggregates."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE general_ledger (
            company_code  VARCHAR,
            gl_account    VARCHAR,
            debit_amount  DOUBLE,
            credit_amount DOUBLE,
            fiscal_period INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO general_ledger VALUES
            ('C001', '4110', 100000, 0, 1),
            ('C001', '4110', 200000, 0, 2),
            ('C002', '4110', 50000, 0, 1)
    """)
    conn.close()


def _create_numeric_company_prior_db(db_path: Path) -> None:
    """Create prior data with numeric account codes as DuckDB may return from CSV load."""
    conn = duckdb.connect(str(db_path))
    conn.execute("""
        CREATE TABLE general_ledger (
            company_code  VARCHAR,
            gl_account    DOUBLE,
            debit_amount  DOUBLE,
            credit_amount DOUBLE,
            fiscal_period INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO general_ledger VALUES
            ('C001', 1000.0, 100000, 0, 1),
            ('C001', 1000.0, 200000, 0, 2)
    """)
    conn.close()


class TestLoadPriorSummary:
    """load_prior_summary 4개 케이스."""

    def test_normal_load(self, tmp_path: Path) -> None:
        """정상 로드 — account_aggregates + monthly_patterns 검증."""
        prior_db = tmp_path / "prior.duckdb"
        _create_prior_db(prior_db)

        conn = duckdb.connect()
        result = load_prior_summary(conn, prior_db, 2024)
        conn.close()

        assert result is not None
        assert isinstance(result, PriorSummary)
        assert result.prior_fiscal_year == 2024
        assert result.prior_total_rows == 5

        # D01: account_aggregates 검증
        assert "4110" in result.account_aggregates
        agg_4110 = result.account_aggregates["4110"]
        assert agg_4110["count"] == 3
        # total_amount = (100000+0) + (200000+0) + (150000+0) = 450000
        assert agg_4110["total_amount"] == pytest.approx(450000.0)

        assert "8220" in result.account_aggregates
        agg_8220 = result.account_aggregates["8220"]
        assert agg_8220["count"] == 2
        assert agg_8220["total_amount"] == pytest.approx(80000.0)

        # D02: monthly_patterns 검증 — 비율 합 ≈ 1.0
        assert "4110" in result.monthly_patterns
        pattern_4110 = result.monthly_patterns["4110"]
        assert sum(pattern_4110.values()) == pytest.approx(1.0, abs=1e-6)

    def test_company_code_loads_company_account_aggregates(self, tmp_path: Path) -> None:
        """company_code가 있으면 D01 prior 집계는 회사별 계정 키로 저장된다."""
        prior_db = tmp_path / "prior_company.duckdb"
        _create_company_prior_db(prior_db)

        conn = duckdb.connect()
        result = load_prior_summary(conn, prior_db, 2024)
        conn.close()

        assert result is not None
        assert result.account_aggregates["C001::4110"]["total_amount"] == pytest.approx(
            300000.0
        )
        assert result.account_aggregates["C001::4110"]["count"] == 2
        assert result.account_aggregates["C002::4110"]["total_amount"] == pytest.approx(
            50000.0
        )
        assert "C001::4110" in result.monthly_patterns
        assert sum(result.monthly_patterns["C001::4110"].values()) == pytest.approx(
            1.0,
            abs=1e-6,
        )
        assert "C002::4110" in result.monthly_patterns

    def test_numeric_account_keys_are_normalised(self, tmp_path: Path) -> None:
        """1000.0 prior keys must match current-period Layer D key C001::1000."""
        prior_db = tmp_path / "prior_numeric_company.duckdb"
        _create_numeric_company_prior_db(prior_db)

        conn = duckdb.connect()
        result = load_prior_summary(conn, prior_db, 2024)
        conn.close()

        assert result is not None
        assert "C001::1000" in result.account_aggregates
        assert "C001::1000.0" not in result.account_aggregates
        assert "C001::1000" in result.monthly_patterns
        assert "C001::1000.0" not in result.monthly_patterns

    def test_db_not_exists(self, tmp_path: Path) -> None:
        """DB 파일 미존재 → None."""
        fake_path = tmp_path / "nonexistent.duckdb"
        conn = duckdb.connect()
        result = load_prior_summary(conn, fake_path, 2024)
        conn.close()
        assert result is None

    def test_empty_table(self, tmp_path: Path) -> None:
        """general_ledger 빈 테이블 → None."""
        prior_db = tmp_path / "empty.duckdb"
        _create_empty_prior_db(prior_db)

        conn = duckdb.connect()
        result = load_prior_summary(conn, prior_db, 2024)
        conn.close()
        assert result is None

    def test_invalid_file(self, tmp_path: Path) -> None:
        """잘못된 파일 → None (graceful fallback)."""
        bad_file = tmp_path / "bad.duckdb"
        bad_file.write_text("not a database")

        conn = duckdb.connect()
        result = load_prior_summary(conn, bad_file, 2024)
        conn.close()
        assert result is None
