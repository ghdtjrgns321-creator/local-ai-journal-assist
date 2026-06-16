"""Phase 1 document/flow unit schema models."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from src.models.phase1_evidence import RawRuleHitRef


class BasePhase1Unit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_type: Literal["document", "flow"]
    unit_id: str
    evidence_rows: list[RawRuleHitRef] = Field(default_factory=list)

    priority_score: float = 0.0
    base_priority_score: float = 0.0
    composite_sort_score: float = 0.0
    composite_sort_score_components: dict[str, float] = Field(default_factory=dict)
    topic_scores: dict[str, float] = Field(default_factory=dict)
    topic_score_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    priority_band: str = "low"
    triage_rank_score: float = 0.0
    triage_rank_reasons: list[str] = Field(default_factory=list)


class DocumentUnit(BasePhase1Unit):
    model_config = ConfigDict(extra="forbid")

    unit_type: Literal["document"] = "document"


class FlowUnit(BasePhase1Unit):
    model_config = ConfigDict(extra="forbid")

    unit_type: Literal["flow"] = "flow"
    flow_id: str
    flow_type: str
    link_key: dict[str, Any] = Field(default_factory=dict)
    member_document_ids: list[str] = Field(default_factory=list)

    measurement_owner_unit_id: str | None = None
    absorbed_document_ids: list[str] = Field(default_factory=list)
    absorbed_rule_hits: list[RawRuleHitRef] = Field(default_factory=list)
    cross_ref_flow_ids: list[str] = Field(default_factory=list)

    artifact_completeness: Literal["complete", "bounded", "absent", "skipped"]
    truncated: bool = False
    cap_reason: str | None = None
    source_artifact_schema: str | None = None
    candidate_count: int = 0
    retained_count: int = 0
    member_count: int = 0
    measurement_eligible: bool = False


Phase1Unit: TypeAlias = DocumentUnit | FlowUnit
