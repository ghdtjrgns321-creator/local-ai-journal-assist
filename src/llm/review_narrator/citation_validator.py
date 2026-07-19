"""Phase 3 v2 Review Narrator — Citation Validator.

LLM 응답의 모든 evidence가 입력 candidate에 실제 존재하는 식별자(rule_id /
feature_id / journal_id)를 인용하는지 검증한다. 실패 건은 `confidence=low`로
강등하고 invalid 인용 목록을 함께 반환해 후순위 처리 + UI 노출에 활용한다.

스펙 §인용 계약:
- reasoning[].evidence 배열은 비어 있을 수 없다.
- rule_id / feature_id / journal_id는 입력에 실제 존재해야 한다.
- 실패 시 confidence=low + priority_rank 후순위.

단일 출처: docs/archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.llm.review_narrator.models import (
    EvidenceType,
    ReasoningEvidence,
    ReviewNarrative,
)


@dataclass
class CitationValidationResult:
    """검증 결과 — is_valid + 강등 적용된 narrative + 위반 목록."""

    is_valid: bool
    narrative: ReviewNarrative
    invalid_citations: list[str] = field(default_factory=list)


def _check_evidence(
    evidence: ReasoningEvidence,
    known_rule_ids: set[str],
    known_feature_ids: set[str],
    known_journal_ids: set[str],
) -> str | None:
    """단일 evidence 검증 — 위반 시 사람이 읽을 사유 문자열, 통과 시 None."""
    if evidence.type == EvidenceType.RULE_HIT:
        if not evidence.rule_id:
            return "rule_hit evidence with empty rule_id"
        if evidence.rule_id not in known_rule_ids:
            return f"unknown rule_id: {evidence.rule_id}"
        return None

    if evidence.type == EvidenceType.ML_FEATURE:
        # Why: 스펙 §인용 계약은 model_id + feature_id 둘 다 필수.
        #      LLM이 model_id=""로 환각하면 어느 모델에서 나온 feature인지 추적 불가.
        if not evidence.model_id:
            return "ml_feature evidence with empty model_id"
        if not evidence.feature_id:
            return "ml_feature evidence with empty feature_id"
        if evidence.feature_id not in known_feature_ids:
            return f"unknown feature_id: {evidence.feature_id}"
        return None

    if evidence.type == EvidenceType.ROW:
        if not evidence.journal_id:
            return "row evidence with empty journal_id"
        if evidence.journal_id not in known_journal_ids:
            return f"unknown journal_id: {evidence.journal_id}"
        return None

    # Why: StrEnum 신규 값이 들어와도 강등 처리되도록 방어
    return f"unsupported evidence type: {evidence.type}"


def validate_citations(
    narrative: ReviewNarrative,
    known_rule_ids: set[str],
    known_feature_ids: set[str],
    known_journal_ids: set[str],
) -> CitationValidationResult:
    """ReviewNarrative의 모든 인용을 검증하고 실패 시 confidence=low로 강등.

    검증 규칙:
    1. reasoning 배열이 비어있으면 강등 (인용 자체 부재).
    2. 각 reasoning의 evidence 배열이 비어있으면 강등.
    3. evidence별 식별자가 known 집합에 없으면 강등.

    강등은 narrative 원본을 수정하지 않고 model_copy로 신규 객체를 반환한다.
    """
    invalid: list[str] = []

    if not narrative.reasoning:
        invalid.append("reasoning array is empty")
    else:
        for idx, item in enumerate(narrative.reasoning):
            if not item.evidence:
                invalid.append(f"reasoning[{idx}].evidence is empty")
                continue
            for ev_idx, ev in enumerate(item.evidence):
                reason = _check_evidence(ev, known_rule_ids, known_feature_ids, known_journal_ids)
                if reason is not None:
                    invalid.append(f"reasoning[{idx}].evidence[{ev_idx}]: {reason}")

    if not invalid:
        return CitationValidationResult(is_valid=True, narrative=narrative, invalid_citations=[])

    # Why: 강등은 confidence=low 고정. priority_rank는 후순위 처리는 cache/UI 레이어 책임.
    downgraded = narrative.model_copy(update={"confidence": "low"})
    return CitationValidationResult(is_valid=False, narrative=downgraded, invalid_citations=invalid)
