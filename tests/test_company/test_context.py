"""RC-0-5/6: CompanyContext + ContextFactory 테스트."""

from __future__ import annotations

import pytest

from config.settings import AuditSettings, get_settings
from src.company.repository import CompanyRepository
from src.context import ContextFactory


class TestContextFactory:
    """ContextFactory.create() 기본 동작."""

    def test_create_basic(self, cx_populated_repo: CompanyRepository):
        """create() → CompanyContext 필드 확인."""
        factory = ContextFactory(cx_populated_repo)
        ctx = factory.create("acme_corp", "acme_corp_2025")
        assert ctx.company_id == "acme_corp"
        assert ctx.engagement_id == "acme_corp_2025"
        assert isinstance(ctx.settings, AuditSettings)
        assert isinstance(ctx.keywords, dict)
        assert isinstance(ctx.schema, dict)

    def test_create_settings_merged(self, cx_populated_repo: CompanyRepository):
        """3계층 머지 결과 settings 값 확인."""
        factory = ContextFactory(cx_populated_repo)
        ctx = factory.create("acme_corp", "acme_corp_2025")
        # Why: company_overrides에 zscore_threshold=2.5 설정됨
        assert ctx.settings.zscore_threshold == 2.5
        # Why: engagement_overrides에 period_end_margin_days=10 설정됨
        assert ctx.settings.period_end_margin_days == 10

    def test_create_with_preset(self, cx_populated_repo: CompanyRepository):
        """preset_overrides 적용."""
        factory = ContextFactory(cx_populated_repo)
        ctx = factory.create(
            "acme_corp", "acme_corp_2025",
            preset_overrides={"fuzzy_threshold": 90},
        )
        assert ctx.settings.fuzzy_threshold == 90

    def test_create_company_not_found(self, cx_repo: CompanyRepository):
        """미존재 회사 → FileNotFoundError."""
        factory = ContextFactory(cx_repo)
        with pytest.raises(FileNotFoundError):
            factory.create("ghost", "ghost_2025")

    def test_paths_correct(self, cx_populated_repo: CompanyRepository):
        """경로 필드 정확성."""
        factory = ContextFactory(cx_populated_repo)
        ctx = factory.create("acme_corp", "acme_corp_2025")
        assert ctx.profile_dir == cx_populated_repo.profile_dir("acme_corp")
        assert ctx.db_path == cx_populated_repo.db_path("acme_corp", "acme_corp_2025")
        assert ctx.model_dir == cx_populated_repo.model_dir("acme_corp", "acme_corp_2025")


class TestContextCache:
    """ContextFactory 메모리 캐시."""

    def test_cache_hit(self, cx_populated_repo: CompanyRepository):
        """동일 키로 두 번 호출 → 동일 객체."""
        factory = ContextFactory(cx_populated_repo)
        ctx1 = factory.create("acme_corp", "acme_corp_2025")
        ctx2 = factory.create("acme_corp", "acme_corp_2025")
        assert ctx1 is ctx2

    def test_cache_bypass_with_runtime(self, cx_populated_repo: CompanyRepository):
        """runtime_overrides 있으면 캐시 우회."""
        factory = ContextFactory(cx_populated_repo)
        ctx1 = factory.create("acme_corp", "acme_corp_2025")
        ctx2 = factory.create(
            "acme_corp", "acme_corp_2025",
            runtime_overrides={"fuzzy_threshold": 95},
        )
        assert ctx1 is not ctx2
        assert ctx2.settings.fuzzy_threshold == 95

    def test_invalidate_specific(self, cx_populated_repo: CompanyRepository):
        """특정 캐시 무효화."""
        factory = ContextFactory(cx_populated_repo)
        factory.create("acme_corp", "acme_corp_2025")
        factory.invalidate("acme_corp", "acme_corp_2025")
        # 캐시 미스 → 새로 빌드
        ctx = factory.create("acme_corp", "acme_corp_2025")
        assert ctx.company_id == "acme_corp"

    def test_invalidate_all(self, cx_populated_repo: CompanyRepository):
        """전체 캐시 클리어."""
        factory = ContextFactory(cx_populated_repo)
        factory.create("acme_corp", "acme_corp_2025")
        factory.invalidate()
        assert len(factory._cache) == 0


class TestAnonymousAndLegacy:
    """create_anonymous() / from_settings()."""

    def test_create_anonymous(self):
        """글로벌 기본값 + _anonymous ID."""
        ctx = ContextFactory.create_anonymous()
        assert ctx.company_id == "_anonymous"
        assert ctx.engagement_id == "_anonymous"
        assert isinstance(ctx.settings, AuditSettings)

    def test_anonymous_settings_match(self):
        """get_settings() 기본값과 동일."""
        ctx = ContextFactory.create_anonymous()
        default = get_settings()
        assert ctx.settings.fuzzy_threshold == default.fuzzy_threshold
        assert ctx.settings.zscore_threshold == default.zscore_threshold

    def test_from_settings(self):
        """커스텀 AuditSettings → CompanyContext 래핑."""
        custom = AuditSettings(fuzzy_threshold=95)
        ctx = ContextFactory.from_settings(custom)
        assert ctx.company_id == "_legacy"
        assert ctx.settings.fuzzy_threshold == 95


class TestCompanyContextFrozen:
    """CompanyContext 불변성."""

    def test_frozen(self):
        """필드 변경 시 FrozenInstanceError."""
        ctx = ContextFactory.create_anonymous()
        with pytest.raises(Exception):
            ctx.company_id = "hacked"  # type: ignore[misc]

    def test_clone_with_settings(self):
        """clone_with_settings → 새 인스턴스, settings만 변경."""
        ctx = ContextFactory.create_anonymous()
        new_settings = ctx.settings.model_copy(update={"fuzzy_threshold": 99})
        cloned = ctx.clone_with_settings(new_settings)
        assert cloned is not ctx
        assert cloned.settings.fuzzy_threshold == 99
        assert cloned.company_id == ctx.company_id
        assert cloned.keywords is ctx.keywords  # 얕은 복사 (같은 참조)

    def test_coa_fallback_to_global(self):
        """회사별 CoA 없음 → 글로벌 CoA 로드."""
        ctx = ContextFactory.create_anonymous()
        # Why: config/chart_of_accounts.csv가 존재하면 set, 없으면 None
        assert ctx.chart_of_accounts is None or isinstance(
            ctx.chart_of_accounts, set
        )
