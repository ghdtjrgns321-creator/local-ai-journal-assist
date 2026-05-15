"""Phase 3 v2 Review Narrator — Pydantic 응답 스키마.

OpenAI Structured Output(`strict: True`)에서 사용한다. 스펙 §출력 계약과 1:1 매핑.

설계:
- `ReasoningEvidence`는 type 디스크리미네이터 + type별 부가 필드(빈 문자열 기본값).
  strict 모드는 oneOf union보다 단일 객체가 안전하므로 평탄 구조 채택.
- 검증은 citation_validator에서 type별 필수 필드 존재 여부를 확인한다.
- `priority_score`는 [0,1] 범위 강제. `priority_rank`는 1부터 시작 (1=highest).

단일 출처: docs/PHASE3_REVIEW_NARRATOR_SPEC.md §출력 계약.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceType(StrEnum):
    """근거 인용 타입 — 입력 데이터의 신호원과 1:1 대응."""

    RULE_HIT = "rule_hit"  # PHASE1 룰 히트 → rule_id 인용
    ML_FEATURE = "ml_feature"  # PHASE2 ML top-feature → model_id + feature_id
    ROW = "row"  # 전표 라인 직접 인용 → journal_id + line_no


class SuggestedActionType(StrEnum):
    """감사인 다음 행동 유형 — 스펙 §출력 계약 suggested_actions.action_type 열거."""

    REQUEST_EVIDENCE = "request_evidence"
    ACCOUNT_ANALYSIS = "account_analysis"
    INTERVIEW = "interview"
    FURTHER_TEST = "further_test"


ConfidenceLevel = Literal["low", "medium", "high"]


class ReasoningEvidence(BaseModel):
    """근거 인용 1건. type에 따라 필수 필드가 달라진다.

    - type=rule_hit: rule_id 필수
    - type=ml_feature: model_id + feature_id 필수
    - type=row: journal_id + line_no 필수

    strict 스키마 호환을 위해 모든 부가 필드를 기본값으로 평탄화하고,
    실제 정합성 검증은 citation_validator에서 수행한다.
    """

    type: EvidenceType
    rule_id: str = ""
    model_id: str = ""
    feature_id: str = ""
    journal_id: str = ""
    line_no: int = 0


class ReasoningItem(BaseModel):
    """의심 근거 1건 — 주장(claim) + 인용 증거 배열.

    스펙 §인용 계약: evidence 배열은 비어 있을 수 없다 (citation_validator가 강등).
    """

    claim: str
    evidence: list[ReasoningEvidence] = Field(default_factory=list)


class SuggestedAction(BaseModel):
    """감사인 다음 행동 제안."""

    action_type: SuggestedActionType
    description: str
    target: str = ""


class ReviewNarrative(BaseModel):
    """LLM이 candidate 1건에 대해 생성하는 전체 응답.

    스펙 §출력 계약 JSON Schema와 1:1 매핑. OpenAI Structured Output strict 모드에서
    `model_json_schema()`로 스키마 추출 가능.
    """

    candidate_id: str
    priority_rank: int = Field(ge=1, description="1=highest")
    priority_score: float = Field(ge=0.0, le=1.0)
    summary: str
    reasoning: list[ReasoningItem] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    confidence: ConfidenceLevel


def build_review_narrative_schema(
    *,
    rule_id_enum: list[str],
    feature_id_enum: list[str],
    journal_id_enum: list[str],
) -> dict:
    """ReviewNarrative JSON Schema에 candidate별 ID enum을 주입한 사본.

    스펙 §4.2 (PHASE3_REWORK_PLAN) 1차 방어선: OpenAI Structured Output strict
    모드에서 LLM이 입력에 없는 ID를 응답으로 만들지 못하도록 schema enum으로 차단.

    빈 문자열("")은 type 디스크리미네이터에서 해당 ID가 무관한 evidence(예: type=row이면
    rule_id="")에 사용되므로 enum에 항상 포함한다.

    Args:
        rule_id_enum: 입력 candidate의 rule_hits에서 추출한 rule_id 리스트.
        feature_id_enum: ml_scores[*].top_features[*].feature_id 리스트.
        journal_id_enum: journal_ref.journal_id 단일 또는 그룹.

    Returns:
        ReviewNarrative.model_json_schema() 사본 (enum 주입). 원본은 변경하지 않는다.
    """
    from copy import deepcopy

    schema = deepcopy(ReviewNarrative.model_json_schema())
    defs = schema.get("$defs") or schema.get("definitions") or {}
    evidence_schema = defs.get("ReasoningEvidence")
    if evidence_schema is None:
        return schema
    props = evidence_schema.get("properties", {})

    def _inject(field_name: str, values: list[str]) -> None:
        if field_name not in props:
            return
        # Why: 빈 문자열은 다른 type의 evidence에서 기본값으로 사용되므로 항상 enum에 포함
        merged = sorted({""} | {v for v in values if isinstance(v, str)})
        props[field_name]["enum"] = merged

    _inject("rule_id", rule_id_enum)
    _inject("feature_id", feature_id_enum)
    _inject("journal_id", journal_id_enum)
    return schema
