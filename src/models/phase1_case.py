"""Phase 1 case-centric result schema models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawRuleHitRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: int
    document_id: str
    row_index: int
    record_id: str | None = None
    score: float = 0.0
    detail: str | None = None
    evidence_type: str


class CaseDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    posting_date: str | None = None
    created_by: str | None = None
    business_process: str | None = None
    gl_account: str | None = None
    counterparty: str | None = None
    amount: float = 0.0
    matched_rules: list[str] = Field(default_factory=list)
    evidence_tags: list[str] = Field(default_factory=list)


class CaseGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    primary_theme: str
    secondary_tags: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    case_key: str
    case_key_parts: dict[str, Any] = Field(default_factory=dict)
    priority_score: float = 0.0
    priority_band: str = "low"
    amount_score: float = 0.0
    control_score: float = 0.0
    logic_score: float = 0.0
    behavior_score: float = 0.0
    repeat_score: float = 0.0
    rule_count: int = 0
    evidence_count: int = 0
    document_count: int = 0
    row_count: int = 0
    total_amount: float = 0.0
    first_posting_date: str | None = None
    last_posting_date: str | None = None
    repeat_months: int = 0
    representative_explanation: str = ""
    evidence_tags: list[str] = Field(default_factory=list)
    documents: list[CaseDocumentRef] = Field(default_factory=list)
    raw_rule_hits: list[RawRuleHitRef] = Field(default_factory=list)
    exposure_rank: int | None = None
    theme_rank: int | None = None
    is_top_case: bool = False
    has_control_failure: bool = False
    has_high_materiality: bool = False
    has_repeat_pattern: bool = False


class ThemeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str
    theme_label: str
    case_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    total_amount: float = 0.0
    top_case_ids: list[str] = Field(default_factory=list)
    secondary_tag_case_count: int = 0


class Phase1CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    run_id: str
    company_id: str
    dataset_id: str | None = None
    batch_id: str | None = None
    generated_at: datetime
    top_n_cases: int = 0
    top_n_per_theme: int = 0
    theme_summaries: list[ThemeSummary] = Field(default_factory=list)
    cases: list[CaseGroupResult] = Field(default_factory=list)
    raw_rule_reference: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

