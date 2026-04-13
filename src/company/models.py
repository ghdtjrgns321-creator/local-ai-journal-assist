"""Company/Engagement 프로파일 Pydantic 모델.

YAML 직렬화를 위해 BaseModel 사용 (ingest/models.py의 @dataclass와 다름).
company.yaml, engagement.yaml 스키마를 정의한다.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EngagementStatus(StrEnum):
    """감사 진행 상태."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CompanyProfile(BaseModel):
    """회사 프로파일 — company.yaml 스키마.

    company_id는 파일시스템 경로로 사용되므로 영소문자+숫자+밑줄만 허용.
    display_name에서 사람이 읽는 이름을 관리한다.
    """

    company_id: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$"
    )
    display_name: str = Field(..., min_length=1, max_length=128)
    industry: str = ""
    erp_system: str = ""
    fiscal_year_start: int = Field(default=1, ge=1, le=12)
    currency: str = Field(default="KRW", max_length=3)

    # Why: AuditSettings 71개 필드 중 일부만 오버라이드하므로 plain dict 사용.
    # deep_merge 시점에서 AuditSettings.model_validate로 최종 검증.
    settings_overrides: dict[str, Any] = Field(default_factory=dict)

    has_custom_coa: bool = False
    has_custom_keywords: bool = False
    has_custom_rules: bool = False
    has_custom_risk_keywords: bool = False

    @field_validator("company_id")
    @classmethod
    def _normalize_company_id(cls, v: str) -> str:
        return v.strip().lower()


class EngagementProfile(BaseModel):
    """감사 연도 프로파일 — engagement.yaml 스키마.

    fiscal_year와 period_start/end로 감사 기간을 정의한다.
    period_start/end가 None이면 fiscal_year + fiscal_year_start로 기간을 유추.
    """

    engagement_id: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$"
    )
    company_id: str = Field(..., min_length=1)
    fiscal_year: int = Field(..., ge=2000, le=2099)
    materiality_amount: int = Field(default=0, ge=0)
    period_start: date | None = None
    period_end: date | None = None
    settings_overrides: dict[str, Any] = Field(default_factory=dict)
    status: EngagementStatus = EngagementStatus.DRAFT

    @field_validator("period_end")
    @classmethod
    def _check_period_order(cls, v: date | None, info) -> date | None:
        start = info.data.get("period_start")
        if v is not None and start is not None and v < start:
            msg = f"period_end({v})가 period_start({start})보다 앞섭니다"
            raise ValueError(msg)
        return v
