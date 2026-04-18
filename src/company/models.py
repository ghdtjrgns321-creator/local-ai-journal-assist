"""Pydantic models for company and engagement profiles."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.company.merger import normalize_settings_overrides


class EngagementStatus(StrEnum):
    """Audit engagement lifecycle status."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CompanyProfile(BaseModel):
    """Company profile persisted in `company.yaml`."""

    company_id: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$"
    )
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
        return v.strip().lower()

    @field_validator("settings_overrides", mode="before")
    @classmethod
    def _normalize_settings_overrides(cls, value: Any) -> dict[str, Any]:
        raw = value or {}
        if not isinstance(raw, dict):
            raise TypeError("settings_overrides must be a dict")
        return normalize_settings_overrides(raw, scope="company")


class EngagementProfile(BaseModel):
    """Engagement profile persisted in `engagement.yaml`."""

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
            raise ValueError(f"period_end({v}) must not be earlier than {start}")
        return v

    @field_validator("settings_overrides", mode="before")
    @classmethod
    def _normalize_settings_overrides(cls, value: Any) -> dict[str, Any]:
        raw = value or {}
        if not isinstance(raw, dict):
            raise TypeError("settings_overrides must be a dict")
        return normalize_settings_overrides(raw, scope="engagement")
