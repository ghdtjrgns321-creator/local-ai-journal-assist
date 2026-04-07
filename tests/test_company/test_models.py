"""RC-0-1/2: CompanyProfile, EngagementProfile 모델 테스트."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from src.company.models import CompanyProfile, EngagementProfile, EngagementStatus


class TestCompanyProfile:
    """CompanyProfile 직렬화/역직렬화 및 유효성 검증."""

    def test_roundtrip(self, cx_company_profile: CompanyProfile):
        """model_dump → YAML → model_validate 라운드트립."""
        dumped = cx_company_profile.model_dump(mode="json")
        yaml_str = yaml.safe_dump(dumped)
        reloaded = CompanyProfile.model_validate(yaml.safe_load(yaml_str))
        assert reloaded.company_id == cx_company_profile.company_id
        assert reloaded.settings_overrides == cx_company_profile.settings_overrides

    def test_company_id_normalization(self):
        """대문자/공백 → 소문자 정규화."""
        p = CompanyProfile(company_id="acme_corp", display_name="Test")
        assert p.company_id == "acme_corp"

    def test_company_id_invalid_slash(self):
        """경로 탈출 문자 → ValidationError."""
        with pytest.raises(Exception):
            CompanyProfile(company_id="acme/corp", display_name="Test")

    def test_company_id_invalid_space(self):
        """공백 포함 → ValidationError."""
        with pytest.raises(Exception):
            CompanyProfile(company_id="acme corp", display_name="Test")

    def test_company_id_empty(self):
        """빈 문자열 → ValidationError."""
        with pytest.raises(Exception):
            CompanyProfile(company_id="", display_name="Test")

    def test_fiscal_year_start_range(self):
        """fiscal_year_start 범위 (1~12)."""
        p = CompanyProfile(company_id="test", display_name="T", fiscal_year_start=3)
        assert p.fiscal_year_start == 3

        with pytest.raises(Exception):
            CompanyProfile(company_id="test", display_name="T", fiscal_year_start=0)

        with pytest.raises(Exception):
            CompanyProfile(company_id="test", display_name="T", fiscal_year_start=13)

    def test_settings_overrides_arbitrary(self):
        """임의 dict 허용."""
        p = CompanyProfile(
            company_id="test",
            display_name="T",
            settings_overrides={"custom_key": [1, 2, 3], "nested": {"a": 1}},
        )
        assert p.settings_overrides["custom_key"] == [1, 2, 3]


class TestEngagementProfile:
    """EngagementProfile 유효성 검증."""

    def test_period_order_valid(self):
        """period_start < period_end → 정상."""
        e = EngagementProfile(
            engagement_id="test_2025",
            company_id="test",
            fiscal_year=2025,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        )
        assert e.period_end == date(2025, 12, 31)

    def test_period_order_invalid(self):
        """period_end < period_start → ValueError."""
        with pytest.raises(Exception, match="앞섭니다"):
            EngagementProfile(
                engagement_id="test_2025",
                company_id="test",
                fiscal_year=2025,
                period_start=date(2025, 12, 31),
                period_end=date(2025, 1, 1),
            )

    def test_fiscal_year_range(self):
        """fiscal_year 범위 (2000~2099)."""
        with pytest.raises(Exception):
            EngagementProfile(
                engagement_id="old", company_id="test", fiscal_year=1999
            )
        with pytest.raises(Exception):
            EngagementProfile(
                engagement_id="far", company_id="test", fiscal_year=2100
            )

    def test_status_enum(self):
        """유효 상태 값."""
        e = EngagementProfile(
            engagement_id="t", company_id="t", fiscal_year=2025,
            status=EngagementStatus.COMPLETED,
        )
        assert e.status == "completed"

    def test_none_periods(self):
        """period_start/end 모두 None 허용."""
        e = EngagementProfile(
            engagement_id="t", company_id="t", fiscal_year=2025
        )
        assert e.period_start is None
        assert e.period_end is None
