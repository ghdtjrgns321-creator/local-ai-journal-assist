"""Phase 1 case-centric result schema models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.phase1_evidence import CaseDocumentRef, RawRuleHitRef
from src.models.phase1_unit import Phase1Unit


class CaseGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    primary_topic: str = ""
    primary_topic_label: str = ""
    topic_scores: dict[str, float] = Field(default_factory=dict)
    topic_score_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    secondary_topics: list[str] = Field(default_factory=list)
    fraud_scenario_tags: list[str] = Field(default_factory=list)
    primary_theme: str
    primary_queue: str = ""
    primary_queue_label: str = ""
    secondary_queues: list[str] = Field(default_factory=list)
    secondary_queue_labels: list[str] = Field(default_factory=list)
    secondary_tags: list[str] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    case_key: str
    case_key_parts: dict[str, Any] = Field(default_factory=dict)
    priority_score: float = 0.0
    base_priority_score: float = 0.0
    composite_sort_score: float = 0.0
    composite_sort_score_components: dict[str, float] = Field(default_factory=dict)
    topside_bonus: float = 0.0
    batch_combo_bonus: float = 0.0
    weak_evidence_bonus: float = 0.0
    priority_adjustment_reasons: list[str] = Field(default_factory=list)
    priority_band: str = "low"
    triage_rank_score: float = 0.0
    triage_rank_reasons: list[str] = Field(default_factory=list)
    amount_score: float = 0.0
    control_score: float = 0.0
    duplicate_or_outflow_score: float = 0.0
    logic_score: float = 0.0
    data_integrity_score: float = 0.0
    intercompany_score: float = 0.0
    timing_score: float = 0.0
    behavior_score: float = 0.0
    repeat_score: float = 0.0
    # OFF-TIME 보조축(주말·심야·작성자 집중) 합산. tier 게이트 미참여, within-tier 정렬·UI 전용.
    time_severity_score: int = 0
    rule_count: int = 0
    evidence_count: int = 0
    document_count: int = 0
    row_count: int = 0
    total_amount: float = 0.0
    first_posting_date: str | None = None
    last_posting_date: str | None = None
    repeat_months: int = 0
    representative_explanation: str = ""
    review_focus: list[str] = Field(default_factory=list)
    risk_narrative: str = ""
    recommended_audit_actions: list[str] = Field(default_factory=list)
    rule_evidence_summary: list[dict[str, Any]] = Field(default_factory=list)
    evidence_tags: list[str] = Field(default_factory=list)
    macro_contexts: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[CaseDocumentRef] = Field(default_factory=list)
    raw_rule_hits: list[RawRuleHitRef] = Field(default_factory=list)
    exposure_rank: int | None = None
    theme_rank: int | None = None
    is_top_case: bool = False
    has_control_failure: bool = False
    has_high_materiality: bool = False
    has_repeat_pattern: bool = False

    @model_validator(mode="after")
    def _fill_topic_compatibility(self) -> CaseGroupResult:
        if not self.primary_topic:
            self.primary_topic = self.primary_theme
        if not self.primary_theme:
            self.primary_theme = self.primary_topic
        if not self.primary_queue:
            self.primary_queue = self.primary_topic
        if not self.primary_topic_label:
            self.primary_topic_label = self.primary_queue_label
        if not self.topic_scores and self.primary_topic:
            self.topic_scores = {self.primary_topic: float(self.priority_score or 0.0)}
        if not self.secondary_topics:
            self.secondary_topics = list(self.secondary_queues)
        return self


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
    units: list[Phase1Unit] = Field(default_factory=list)
    raw_rule_reference: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
