"""Pydantic models for company and engagement profiles."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.company.merger import normalize_settings_overrides

# Why: company_id / engagement_id 는 폴더명으로 쓰이므로 Windows·Linux 모두에서
#      금지하는 path-unsafe 문자(< > : " / \ | ? *)와 공백/제어문자를 거부하지 않고
#      밑줄(_)로 치환한다. 사용자가 "normal test" 처럼 공백을 넣어도 등록이 막히지
#      않고 "normal_test" 로 정규화된다. 나머지 문자(한글·대문자·하이픈 등)는 유지.
_PATH_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\s\x00-\x1f]')


def _validate_identifier(value: str, *, field_name: str) -> str:
    # path-unsafe 문자를 밑줄로 치환 → 연속 밑줄 축약 → 양끝 밑줄 제거
    normalized = _PATH_UNSAFE_RE.sub("_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise ValueError(f"{field_name} 는 비어 있을 수 없습니다.")
    return normalized


class EngagementStatus(StrEnum):
    """Audit engagement lifecycle status."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CompanyProfile(BaseModel):
    """Company profile persisted in `company.yaml`."""

    company_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    industry: str = ""
    erp_system: str = ""
    fiscal_year_start: int = Field(default=1, ge=1, le=12)
    currency: str = Field(default="KRW", max_length=3)
    settings_overrides: dict[str, Any] = Field(default_factory=dict)
    has_custom_coa: bool = False
    has_custom_keywords: bool = False
    has_custom_rules: bool = False
    has_custom_risk_keywords: bool = False

    @field_validator("company_id")
    @classmethod
    def _normalize_company_id(cls, v: str) -> str:
        return _validate_identifier(v, field_name="company_id")

    @field_validator("settings_overrides", mode="before")
    @classmethod
    def _normalize_settings_overrides(cls, value: Any) -> dict[str, Any]:
        raw = value or {}
        if not isinstance(raw, dict):
            raise TypeError("settings_overrides must be a dict")
        return normalize_settings_overrides(raw, scope="company")


class EngagementProfile(BaseModel):
    """Engagement profile persisted in `engagement.yaml`."""

    engagement_id: str = Field(..., min_length=1, max_length=64)
    company_id: str = Field(..., min_length=1)
    fiscal_year: int = Field(..., ge=2000, le=2099)
    materiality_amount: int = Field(default=0, ge=0)
    period_start: date | None = None
    period_end: date | None = None
    settings_overrides: dict[str, Any] = Field(default_factory=dict)
    status: EngagementStatus = EngagementStatus.DRAFT

    @field_validator("engagement_id")
    @classmethod
    def _normalize_engagement_id(cls, v: str) -> str:
        return _validate_identifier(v, field_name="engagement_id")

    @field_validator("company_id")
    @classmethod
    def _normalize_company_id_ref(cls, v: str) -> str:
        return _validate_identifier(v, field_name="company_id")

    @field_validator("period_end")
    @classmethod
    def _check_period_order(cls, v: date | None, info) -> date | None:
        start = info.data.get("period_start")
        if v is not None and start is not None and v < start:
            raise ValueError(f"period_end({v}) must not be earlier than {start}")
        return v

    @field_validator("settings_overrides", mode="before")
    @classmethod
    def _normalize_settings_overrides(cls, value: Any) -> dict[str, Any]:
        raw = value or {}
        if not isinstance(raw, dict):
            raise TypeError("settings_overrides must be a dict")
        return normalize_settings_overrides(raw, scope="engagement")
