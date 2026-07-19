"""CompanyContext (불변 런타임 번들) + ContextFactory (생성 팩토리).

Usage:
    repo = CompanyRepository(Path("data/companies"))
    factory = ContextFactory(repo)
    ctx = factory.create("acme_corp", "acme_corp_2025")
    pipeline = AuditPipeline(context=ctx)   # RC-1에서 연동
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import (
    CONFIG_DIR,
    AuditSettings,
    get_audit_rules,
    get_cleaning_config,
    get_keywords,
    get_phase1_case,
    get_risk_keywords,
    get_schema,
    get_settings,
)
from src.company.merger import resolve_settings, resolve_yaml_config
from src.company.repository import CompanyRepository, parse_coa_csv

logger = logging.getLogger(__name__)

# Why: "_anonymous", "_legacy" 등 회사 프로파일 없는 폴백 식별자.
#      pipeline.py 등에서 분기 시 매직 스트링 대신 이 상수 또는 is_anonymous 사용.
ANONYMOUS_ID = "_anonymous"
LEGACY_ID = "_legacy"


@dataclass(frozen=True)
class CompanyContext:
    """회사별 불변 런타임 컨텍스트.

    파이프라인 전 구간에서 단일 참조점으로 사용.
    frozen=True: 생성 후 필드 변경 불가.
    """

    company_id: str
    engagement_id: str
    settings: AuditSettings
    schema: dict
    keywords: dict
    audit_rules: dict
    phase1_case: dict
    risk_keywords: dict
    cleaning_config: dict
    chart_of_accounts: set[str] | None
    profile_dir: Path
    db_path: Path
    model_dir: Path
    # Why: Layer D(전기 대비 변동 탐지)에서 fiscal_year-1 engagement를 찾기 위해 필요
    fiscal_year: int | None = None
    # Why: WU-13 TB 교차검증에서 대사 허용 차이 기준 (EngagementProfile.materiality_amount)
    materiality_amount: float = 0.0

    @property
    def is_anonymous(self) -> bool:
        """회사 프로파일 없는 폴백 context인지 판별."""
        return self.company_id in (ANONYMOUS_ID, LEGACY_ID)

    def clone_with_settings(self, new_settings: AuditSettings) -> CompanyContext:
        """UI 슬라이더용 초고속 복제 — 디스크 I/O 없이 메모리에서 즉시 교체."""
        return dataclasses.replace(self, settings=new_settings)


class ContextFactory:
    """CompanyContext 생성 팩토리.

    Repository + merger를 조합하여 3계층 해소 완료된 CompanyContext를 생성한다.
    메모리 캐시로 Streamlit re-run 시 디스크 재읽기를 방지한다.
    """

    def __init__(self, repo: CompanyRepository) -> None:
        self._repo = repo
        # Why: (company_id, engagement_id) → CompanyContext 캐시.
        # Streamlit은 매 re-run마다 스크립트를 처음부터 실행하므로,
        # 디스크 I/O를 최소화하기 위해 메모리 캐시 사용.
        self._cache: dict[tuple[str, str], CompanyContext] = {}

    def create(
        self,
        company_id: str,
        engagement_id: str,
        *,
        preset_overrides: dict[str, Any] | None = None,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> CompanyContext:
        """회사 + 연도 프로파일 로드 → 3계층 머지 → CompanyContext.

        preset/runtime_overrides가 없는 경우 캐시를 사용한다.
        preset/runtime이 있으면 캐시를 우회한다 (비영속 오버라이드).

        Raises:
            FileNotFoundError: company/engagement 미존재
        """
        cache_key = (company_id, engagement_id)
        has_runtime = bool(preset_overrides or runtime_overrides)

        if not has_runtime and cache_key in self._cache:
            return self._cache[cache_key]

        ctx = self._build_context(company_id, engagement_id, preset_overrides, runtime_overrides)

        # Why: runtime 오버라이드가 있으면 캐시에 저장하지 않음 (비영속).
        if not has_runtime:
            self._cache[cache_key] = ctx
        return ctx

    def invalidate(
        self,
        company_id: str | None = None,
        engagement_id: str | None = None,
    ) -> None:
        """캐시 무효화. Repository.update_* 후 호출.

        - company_id만 지정: 해당 회사의 모든 engagement 캐시 제거
        - 둘 다 지정: 특정 engagement만 제거
        - 둘 다 None: 전체 캐시 클리어
        """
        if company_id is None:
            self._cache.clear()
            return

        keys_to_remove = [
            k
            for k in self._cache
            if k[0] == company_id and (engagement_id is None or k[1] == engagement_id)
        ]
        for k in keys_to_remove:
            del self._cache[k]

    @staticmethod
    def create_anonymous() -> CompanyContext:
        """글로벌 기본값으로 CompanyContext 생성 (하위 호환).

        기존 AuditPipeline(settings=None) 동작을 CompanyContext 인터페이스로 래핑.
        """
        settings = get_settings()
        return CompanyContext(
            company_id=ANONYMOUS_ID,
            engagement_id=ANONYMOUS_ID,
            settings=settings,
            schema=get_schema(),
            keywords=get_keywords(),
            audit_rules=get_audit_rules(),
            phase1_case=get_phase1_case(),
            risk_keywords=get_risk_keywords(),
            cleaning_config=get_cleaning_config(),
            chart_of_accounts=_load_global_coa(),
            profile_dir=Path(settings.profile_dir),
            db_path=Path(settings.duckdb_path),
            model_dir=Path("data/models"),
        )

    @staticmethod
    def from_settings(settings: AuditSettings) -> CompanyContext:
        """레거시 AuditSettings → CompanyContext 래핑.

        기존 테스트에서 AuditSettings를 직접 주입하던 코드의 전환용.
        """
        return CompanyContext(
            company_id=LEGACY_ID,
            engagement_id=LEGACY_ID,
            settings=settings,
            schema=get_schema(),
            keywords=get_keywords(),
            audit_rules=get_audit_rules(),
            phase1_case=get_phase1_case(),
            risk_keywords=get_risk_keywords(),
            cleaning_config=get_cleaning_config(),
            chart_of_accounts=_load_global_coa(),
            profile_dir=Path(settings.profile_dir),
            db_path=Path(settings.duckdb_path),
            model_dir=Path("data/models"),
        )

    # ── Private ──────────────────────────────────────

    def _build_context(
        self,
        company_id: str,
        engagement_id: str,
        preset_overrides: dict[str, Any] | None,
        runtime_overrides: dict[str, Any] | None,
    ) -> CompanyContext:
        """디스크에서 프로파일을 읽고 3계층 머지를 수행."""
        company = self._repo.get_company(company_id)
        engagement = self._repo.get_engagement(company_id, engagement_id)

        settings = resolve_settings(
            company_overrides=company.settings_overrides,
            engagement_overrides=engagement.settings_overrides,
            preset_overrides=preset_overrides,
            runtime_overrides=runtime_overrides,
        )

        company_kw = self._repo.load_company_keywords(company_id)
        company_rules = self._repo.load_company_audit_rules(company_id)
        company_phase1_case = self._repo.load_company_phase1_case(company_id)
        company_risk = self._repo.load_company_risk_keywords(company_id)

        keywords = resolve_yaml_config(get_keywords(), company_kw)
        audit_rules = resolve_yaml_config(get_audit_rules(), company_rules)
        phase1_case = resolve_yaml_config(get_phase1_case(), company_phase1_case)
        risk_keywords = resolve_yaml_config(get_risk_keywords(), company_risk)

        coa = self._repo.load_company_coa(company_id)
        if coa is None:
            coa = _load_global_coa()

        return CompanyContext(
            company_id=company_id,
            engagement_id=engagement_id,
            settings=settings,
            schema=get_schema(),
            keywords=keywords,
            audit_rules=audit_rules,
            phase1_case=phase1_case,
            risk_keywords=risk_keywords,
            cleaning_config=get_cleaning_config(),
            chart_of_accounts=coa,
            profile_dir=self._repo.profile_dir(company_id),
            db_path=self._repo.db_path(company_id, engagement_id),
            model_dir=self._repo.model_dir(company_id, engagement_id),
            fiscal_year=engagement.fiscal_year,
            materiality_amount=getattr(engagement, "materiality_amount", 0.0) or 0.0,
        )


def _load_global_coa() -> set[str] | None:
    """글로벌 chart_of_accounts.csv → set[str]."""
    return parse_coa_csv(CONFIG_DIR / "chart_of_accounts.csv")
