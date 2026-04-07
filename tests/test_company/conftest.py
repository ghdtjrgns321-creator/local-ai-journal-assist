"""Company 테스트 공용 fixture. prefix: cx_"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.company.models import CompanyProfile, EngagementProfile, EngagementStatus
from src.company.repository import CompanyRepository
from src.context import CompanyContext, ContextFactory


@pytest.fixture()
def cx_base_dir(tmp_path: Path) -> Path:
    """임시 companies 루트 디렉토리."""
    d = tmp_path / "companies"
    d.mkdir()
    return d


@pytest.fixture()
def cx_repo(cx_base_dir: Path) -> CompanyRepository:
    """임시 디렉토리 기반 Repository."""
    return CompanyRepository(cx_base_dir)


@pytest.fixture()
def cx_company_profile() -> CompanyProfile:
    """테스트용 회사 프로파일."""
    return CompanyProfile(
        company_id="acme_corp",
        display_name="ACME Corporation",
        industry="manufacturing",
        erp_system="SAP",
        fiscal_year_start=1,
        currency="KRW",
        settings_overrides={
            "approval_thresholds": [50_000_000, 500_000_000],
            "zscore_threshold": 2.5,
        },
    )


@pytest.fixture()
def cx_engagement_profile() -> EngagementProfile:
    """테스트용 감사 연도 프로파일."""
    return EngagementProfile(
        engagement_id="acme_corp_2025",
        company_id="acme_corp",
        fiscal_year=2025,
        settings_overrides={"period_end_margin_days": 10},
        status=EngagementStatus.DRAFT,
    )


@pytest.fixture()
def cx_populated_repo(
    cx_repo: CompanyRepository,
    cx_company_profile: CompanyProfile,
    cx_engagement_profile: EngagementProfile,
) -> CompanyRepository:
    """회사 + 연도가 생성된 상태의 Repository."""
    cx_repo.create_company(cx_company_profile)
    cx_repo.create_engagement("acme_corp", cx_engagement_profile)
    return cx_repo


@pytest.fixture()
def cx_factory(cx_populated_repo: CompanyRepository) -> ContextFactory:
    """테스트용 ContextFactory."""
    return ContextFactory(cx_populated_repo)


@pytest.fixture()
def cx_context(cx_factory: ContextFactory) -> CompanyContext:
    """기본 CompanyContext (acme_corp, acme_corp_2025)."""
    return cx_factory.create("acme_corp", "acme_corp_2025")


@pytest.fixture()
def cx_anonymous() -> CompanyContext:
    """Anonymous CompanyContext — 글로벌 기본값."""
    return ContextFactory.create_anonymous()
