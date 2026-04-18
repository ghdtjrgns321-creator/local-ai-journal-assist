"""Tests for company and engagement profile models."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from src.company.models import CompanyProfile, EngagementProfile, EngagementStatus


class TestCompanyProfile:
    def test_roundtrip(self, cx_company_profile: CompanyProfile):
        dumped = cx_company_profile.model_dump(mode="json")
        yaml_str = yaml.safe_dump(dumped)
        reloaded = CompanyProfile.model_validate(yaml.safe_load(yaml_str))
        assert reloaded.company_id == cx_company_profile.company_id
        assert reloaded.settings_overrides == cx_company_profile.settings_overrides

    def test_company_id_normalization(self):
        p = CompanyProfile(company_id="acme_corp", display_name="Test")
        assert p.company_id == "acme_corp"

    def test_company_id_invalid_slash(self):
        with pytest.raises(Exception):
            CompanyProfile(company_id="acme/corp", display_name="Test")

    def test_company_id_invalid_space(self):
        with pytest.raises(Exception):
            CompanyProfile(company_id="acme corp", display_name="Test")

    def test_company_id_empty(self):
        with pytest.raises(Exception):
            CompanyProfile(company_id="", display_name="Test")

    def test_fiscal_year_start_range(self):
        p = CompanyProfile(company_id="test", display_name="T", fiscal_year_start=3)
        assert p.fiscal_year_start == 3

        with pytest.raises(Exception):
            CompanyProfile(company_id="test", display_name="T", fiscal_year_start=0)

        with pytest.raises(Exception):
            CompanyProfile(company_id="test", display_name="T", fiscal_year_start=13)

    def test_settings_overrides_legacy_alias_normalized(self):
        p = CompanyProfile(
            company_id="test",
            display_name="T",
            settings_overrides={"approval_amount_threshold": 123},
        )
        assert p.settings_overrides == {"approval_thresholds": [123]}

    def test_settings_overrides_unknown_key_ignored(self):
        p = CompanyProfile(
            company_id="test",
            display_name="T",
            settings_overrides={"custom_key": [1, 2, 3], "zscore_threshold": 2.1},
        )
        assert p.settings_overrides == {"zscore_threshold": 2.1}


class TestEngagementProfile:
    def test_period_order_valid(self):
        e = EngagementProfile(
            engagement_id="test_2025",
            company_id="test",
            fiscal_year=2025,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )
        assert e.period_end == date(2025, 12, 31)

    def test_period_order_invalid(self):
        with pytest.raises(Exception, match="must not be earlier"):
            EngagementProfile(
                engagement_id="test_2025",
                company_id="test",
                fiscal_year=2025,
                period_start=date(2025, 12, 31),
                period_end=date(2025, 1, 1),
            )

    def test_fiscal_year_range(self):
        with pytest.raises(Exception):
            EngagementProfile(
                engagement_id="old",
                company_id="test",
                fiscal_year=1999,
            )
        with pytest.raises(Exception):
            EngagementProfile(
                engagement_id="far",
                company_id="test",
                fiscal_year=2100,
            )

    def test_status_enum(self):
        e = EngagementProfile(
            engagement_id="t",
            company_id="t",
            fiscal_year=2025,
            status=EngagementStatus.COMPLETED,
        )
        assert e.status == "completed"

    def test_none_periods(self):
        e = EngagementProfile(
            engagement_id="t",
            company_id="t",
            fiscal_year=2025,
        )
        assert e.period_start is None
        assert e.period_end is None
