"""RC-0-4: CompanyRepository CRUD 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.company.models import CompanyProfile, EngagementProfile, EngagementStatus
from src.company.repository import CompanyRepository


class TestCompanyCRUD:
    """Company 생성/조회/수정/삭제."""

    def test_create_company(
        self, cx_repo: CompanyRepository, cx_company_profile: CompanyProfile
    ):
        """디렉토리 + company.yaml 생성 확인."""
        path = cx_repo.create_company(cx_company_profile)
        assert path.exists()
        assert (cx_repo.company_dir("acme_corp") / "company.yaml").exists()
        assert cx_repo.profile_dir("acme_corp").exists()

    def test_create_company_duplicate(
        self, cx_repo: CompanyRepository, cx_company_profile: CompanyProfile
    ):
        """동일 ID 재생성 → FileExistsError."""
        cx_repo.create_company(cx_company_profile)
        with pytest.raises(FileExistsError):
            cx_repo.create_company(cx_company_profile)

    def test_get_company(self, cx_populated_repo: CompanyRepository):
        """YAML 역직렬화 + 필드 일치."""
        p = cx_populated_repo.get_company("acme_corp")
        assert p.company_id == "acme_corp"
        assert p.display_name == "ACME Corporation"
        assert p.settings_overrides["zscore_threshold"] == 2.5

    def test_get_company_not_found(self, cx_repo: CompanyRepository):
        """미존재 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            cx_repo.get_company("nonexistent")

    def test_list_companies_empty(self, cx_repo: CompanyRepository):
        """빈 디렉토리 → 빈 리스트."""
        assert cx_repo.list_companies() == []

    def test_list_companies_multiple(self, cx_repo: CompanyRepository):
        """복수 회사 목록."""
        cx_repo.create_company(
            CompanyProfile(company_id="alpha", display_name="Alpha")
        )
        cx_repo.create_company(
            CompanyProfile(company_id="beta", display_name="Beta")
        )
        result = cx_repo.list_companies()
        ids = [c.company_id for c in result]
        assert "alpha" in ids
        assert "beta" in ids

    def test_update_company(self, cx_populated_repo: CompanyRepository):
        """settings_overrides 변경 확인."""
        p = cx_populated_repo.get_company("acme_corp")
        updated = p.model_copy(update={"display_name": "ACME Updated"})
        cx_populated_repo.update_company(updated)
        reloaded = cx_populated_repo.get_company("acme_corp")
        assert reloaded.display_name == "ACME Updated"

    def test_update_company_not_found(self, cx_repo: CompanyRepository):
        """미존재 회사 업데이트 → FileNotFoundError."""
        p = CompanyProfile(company_id="ghost", display_name="Ghost")
        with pytest.raises(FileNotFoundError):
            cx_repo.update_company(p)

    def test_delete_company(self, cx_populated_repo: CompanyRepository):
        """디렉토리 완전 삭제."""
        assert cx_populated_repo.delete_company("acme_corp") is True
        assert not cx_populated_repo.company_dir("acme_corp").exists()

    def test_delete_company_not_found(self, cx_repo: CompanyRepository):
        """미존재 삭제 → False."""
        assert cx_repo.delete_company("ghost") is False


class TestEngagementCRUD:
    """Engagement 생성/조회/수정."""

    def test_create_engagement(self, cx_populated_repo: CompanyRepository):
        """engagements/{id}/ 구조 확인."""
        edir = cx_populated_repo.engagement_dir("acme_corp", "acme_corp_2025")
        assert edir.exists()
        assert (edir / "engagement.yaml").exists()
        assert (edir / "models").exists()
        assert (edir / "exports").exists()

    def test_create_engagement_no_company(
        self, cx_repo: CompanyRepository, cx_engagement_profile: EngagementProfile
    ):
        """회사 미존재 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            cx_repo.create_engagement("ghost", cx_engagement_profile)

    def test_create_engagement_duplicate(
        self,
        cx_populated_repo: CompanyRepository,
        cx_engagement_profile: EngagementProfile,
    ):
        """동일 engagement 재생성 → FileExistsError."""
        with pytest.raises(FileExistsError):
            cx_populated_repo.create_engagement("acme_corp", cx_engagement_profile)

    def test_get_engagement(self, cx_populated_repo: CompanyRepository):
        """역직렬화 + 필드 일치."""
        e = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        assert e.fiscal_year == 2025
        assert e.status == EngagementStatus.DRAFT

    def test_list_engagements(self, cx_populated_repo: CompanyRepository):
        """목록 반환."""
        lst = cx_populated_repo.list_engagements("acme_corp")
        assert len(lst) == 1
        assert lst[0].engagement_id == "acme_corp_2025"

    def test_update_engagement(self, cx_populated_repo: CompanyRepository):
        """상태 변경."""
        e = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        updated = e.model_copy(update={"status": EngagementStatus.IN_PROGRESS})
        cx_populated_repo.update_engagement("acme_corp", updated)
        reloaded = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        assert reloaded.status == EngagementStatus.IN_PROGRESS


class TestResourceLoaders:
    """회사별 커스텀 리소스 로드."""

    def test_load_coa_exists(self, cx_populated_repo: CompanyRepository):
        """CSV → set[str] 변환."""
        coa_path = cx_populated_repo.company_dir("acme_corp") / "chart_of_accounts.csv"
        coa_path.write_text("gl_account\n1000\n2000\n3000\n", encoding="utf-8")
        result = cx_populated_repo.load_company_coa("acme_corp")
        assert result == {"1000", "2000", "3000"}

    def test_load_coa_missing(self, cx_populated_repo: CompanyRepository):
        """파일 미존재 → None."""
        assert cx_populated_repo.load_company_coa("acme_corp") is None

    def test_load_keywords(self, cx_populated_repo: CompanyRepository):
        """YAML dict 반환."""
        kw_path = cx_populated_repo.company_dir("acme_corp") / "keywords.yaml"
        kw_path.write_text(
            yaml.safe_dump({"document_id": ["전표번호", "증번호"]}),
            encoding="utf-8",
        )
        result = cx_populated_repo.load_company_keywords("acme_corp")
        assert result["document_id"] == ["전표번호", "증번호"]

    def test_load_keywords_missing(self, cx_populated_repo: CompanyRepository):
        """미존재 → None."""
        assert cx_populated_repo.load_company_keywords("acme_corp") is None


class TestPathHelpers:
    """경로 헬퍼 정확성."""

    def test_paths(self, cx_repo: CompanyRepository, cx_base_dir: Path):
        """모든 경로 헬퍼가 올바른 경로를 반환."""
        assert cx_repo.company_dir("x") == cx_base_dir / "x"
        assert cx_repo.engagement_dir("x", "y") == cx_base_dir / "x" / "engagements" / "y"
        assert cx_repo.profile_dir("x") == cx_base_dir / "x" / "profiles"
        assert cx_repo.db_path("x", "y") == cx_base_dir / "x" / "engagements" / "y" / "audit.duckdb"
        assert cx_repo.model_dir("x", "y") == cx_base_dir / "x" / "engagements" / "y" / "models"
