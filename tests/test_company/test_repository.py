"""Repository tests for company and engagement persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.company.models import CompanyProfile, EngagementProfile, EngagementStatus
from src.company.repository import CompanyRepository


class TestCompanyCRUD:
    def test_create_company(
        self,
        cx_repo: CompanyRepository,
        cx_company_profile: CompanyProfile,
    ):
        path = cx_repo.create_company(cx_company_profile)
        assert path.exists()
        assert (cx_repo.company_dir("acme_corp") / "company.yaml").exists()
        assert cx_repo.profile_dir("acme_corp").exists()

    def test_create_company_duplicate(
        self,
        cx_repo: CompanyRepository,
        cx_company_profile: CompanyProfile,
    ):
        cx_repo.create_company(cx_company_profile)
        with pytest.raises(FileExistsError):
            cx_repo.create_company(cx_company_profile)

    def test_get_company(self, cx_populated_repo: CompanyRepository):
        p = cx_populated_repo.get_company("acme_corp")
        assert p.company_id == "acme_corp"
        assert p.display_name == "ACME Corporation"
        assert p.settings_overrides["zscore_threshold"] == 2.5

    def test_get_company_not_found(self, cx_repo: CompanyRepository):
        with pytest.raises(FileNotFoundError):
            cx_repo.get_company("nonexistent")

    def test_list_companies_empty(self, cx_repo: CompanyRepository):
        assert cx_repo.list_companies() == []

    def test_list_companies_multiple(self, cx_repo: CompanyRepository):
        cx_repo.create_company(CompanyProfile(company_id="alpha", display_name="Alpha"))
        cx_repo.create_company(CompanyProfile(company_id="beta", display_name="Beta"))
        result = cx_repo.list_companies()
        ids = [c.company_id for c in result]
        assert "alpha" in ids
        assert "beta" in ids

    def test_update_company(self, cx_populated_repo: CompanyRepository):
        p = cx_populated_repo.get_company("acme_corp")
        updated = p.model_copy(update={"display_name": "ACME Updated"})
        cx_populated_repo.update_company(updated)
        reloaded = cx_populated_repo.get_company("acme_corp")
        assert reloaded.display_name == "ACME Updated"

    def test_update_company_normalizes_legacy_settings_key(
        self,
        cx_populated_repo: CompanyRepository,
    ):
        p = cx_populated_repo.get_company("acme_corp")
        updated = p.model_copy(
            update={"settings_overrides": {"approval_amount_threshold": 12345}},
        )
        cx_populated_repo.update_company(updated)
        reloaded = cx_populated_repo.get_company("acme_corp")
        assert reloaded.settings_overrides == {"approval_thresholds": [12345]}

    def test_update_company_not_found(self, cx_repo: CompanyRepository):
        p = CompanyProfile(company_id="ghost", display_name="Ghost")
        with pytest.raises(FileNotFoundError):
            cx_repo.update_company(p)

    def test_delete_company(self, cx_populated_repo: CompanyRepository):
        assert cx_populated_repo.delete_company("acme_corp") is True
        assert not cx_populated_repo.company_dir("acme_corp").exists()

    def test_delete_company_not_found(self, cx_repo: CompanyRepository):
        assert cx_repo.delete_company("ghost") is False


class TestEngagementCRUD:
    def test_create_engagement(self, cx_populated_repo: CompanyRepository):
        edir = cx_populated_repo.engagement_dir("acme_corp", "acme_corp_2025")
        assert edir.exists()
        assert (edir / "engagement.yaml").exists()
        assert (edir / "models").exists()
        assert (edir / "exports").exists()

    def test_create_engagement_no_company(
        self,
        cx_repo: CompanyRepository,
        cx_engagement_profile: EngagementProfile,
    ):
        with pytest.raises(FileNotFoundError):
            cx_repo.create_engagement("ghost", cx_engagement_profile)

    def test_create_engagement_duplicate(
        self,
        cx_populated_repo: CompanyRepository,
        cx_engagement_profile: EngagementProfile,
    ):
        with pytest.raises(FileExistsError):
            cx_populated_repo.create_engagement("acme_corp", cx_engagement_profile)

    def test_get_engagement(self, cx_populated_repo: CompanyRepository):
        e = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        assert e.fiscal_year == 2025
        assert e.status == EngagementStatus.DRAFT

    def test_list_engagements(self, cx_populated_repo: CompanyRepository):
        lst = cx_populated_repo.list_engagements("acme_corp")
        assert len(lst) == 1
        assert lst[0].engagement_id == "acme_corp_2025"

    def test_update_engagement(self, cx_populated_repo: CompanyRepository):
        e = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        updated = e.model_copy(update={"status": EngagementStatus.IN_PROGRESS})
        cx_populated_repo.update_engagement("acme_corp", updated)
        reloaded = cx_populated_repo.get_engagement("acme_corp", "acme_corp_2025")
        assert reloaded.status == EngagementStatus.IN_PROGRESS


class TestResourceLoaders:
    def test_load_coa_exists(self, cx_populated_repo: CompanyRepository):
        coa_path = cx_populated_repo.company_dir("acme_corp") / "chart_of_accounts.csv"
        coa_path.write_text("gl_account\n1000\n2000\n3000\n", encoding="utf-8")
        result = cx_populated_repo.load_company_coa("acme_corp")
        assert result == {"1000", "2000", "3000"}

    def test_load_coa_missing(self, cx_populated_repo: CompanyRepository):
        assert cx_populated_repo.load_company_coa("acme_corp") is None

    def test_load_keywords(self, cx_populated_repo: CompanyRepository):
        kw_path = cx_populated_repo.company_dir("acme_corp") / "keywords.yaml"
        kw_path.write_text(
            yaml.safe_dump({"document_id": ["전표번호", "증빙번호"]}),
            encoding="utf-8",
        )
        result = cx_populated_repo.load_company_keywords("acme_corp")
        assert result["document_id"] == ["전표번호", "증빙번호"]

    def test_load_keywords_missing(self, cx_populated_repo: CompanyRepository):
        assert cx_populated_repo.load_company_keywords("acme_corp") is None

    def test_load_phase1_case(self, cx_populated_repo: CompanyRepository):
        phase1_path = cx_populated_repo.company_dir("acme_corp") / "phase1_case.yaml"
        phase1_path.write_text(
            yaml.safe_dump({"phase1_case": {"top_n_cases": 7}}, allow_unicode=True),
            encoding="utf-8",
        )
        result = cx_populated_repo.load_company_phase1_case("acme_corp")
        assert result["phase1_case"]["top_n_cases"] == 7

    def test_save_company_yaml_sets_custom_flags(
        self,
        cx_populated_repo: CompanyRepository,
    ):
        cx_populated_repo.save_company_yaml(
            "acme_corp",
            "audit_rules.yaml",
            {"patterns": {"manual_source_codes": ["Manual"]}},
        )
        profile = cx_populated_repo.get_company("acme_corp")
        assert profile.has_custom_rules is True


class TestPathHelpers:
    def test_paths(self, cx_repo: CompanyRepository, cx_base_dir: Path):
        assert cx_repo.company_dir("x") == cx_base_dir / "x"
        assert (
            cx_repo.engagement_dir("x", "y")
            == cx_base_dir / "x" / "engagements" / "y"
        )
        assert cx_repo.profile_dir("x") == cx_base_dir / "x" / "profiles"
        assert (
            cx_repo.db_path("x", "y")
            == cx_base_dir / "x" / "engagements" / "y" / "audit.duckdb"
        )
        assert (
            cx_repo.model_dir("x", "y")
            == cx_base_dir / "x" / "engagements" / "y" / "models"
        )
