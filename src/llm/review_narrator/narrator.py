"""Phase 3 v2 Review Narrator — LLM 호출 + 응답 파싱.

스펙 §흐름 (docs/archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md):
    Candidate → Sanitizer(이미 처리됨) → LLM (Structured Output) → Citation Validator

호출 전략 (스펙 §4 + §4.2):
1. reasoning 티어(`gpt-5.4`)로 1차 호출, OpenAI Structured Output strict + 동적 enum.
2. JSON 파싱 실패 또는 ValidationError 시 light 티어(`gpt-5.4-mini`)로 1회 fallback.
3. 2회 모두 실패 시 `confidence=low` + 후순위(priority_rank=999) fallback narrative 반환.
4. 성공한 응답은 citation_validator를 통과시켜 환각 ID를 자동 강등.

본 모듈은 ChatClient 인스턴스를 외부에서 주입받는다 (`narrate(...,
reasoning_client, light_client)`). 실제 OpenAI 호출은 호출부에서 `get_chat_client`로
주입하고, 테스트는 mock ChatClient를 주입한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from src.llm.api_client import ChatClient
from src.llm.review_narrator.citation_validator import (
    CitationValidationResult,
    validate_citations,
)
from src.llm.review_narrator.models import (
    ReviewNarrative,
    build_review_narrative_schema,
)

logger = logging.getLogger(__name__)

# Why: 한국어 감사 도메인 + 인용 강제 + 1~2줄 한국어 요약 제약 명시.
DEFAULT_SYSTEM_PROMPT = (
    "당신은 한국 감사인을 보조하는 분석 에이전트다. 주어진 review candidate를 읽고 "
    "다음 JSON Schema에 정확히 부합하는 응답을 생성하라. 반드시 한국어로 작성하고, "
    "모든 reasoning.evidence는 입력의 rule_hits / ml_scores.top_features / journal_ref 에 "
    "실제 존재하는 ID만 인용한다. 자유 가설을 생성하지 말고, 입력에 있는 신호만 해석한다."
)

# Why: LLM 응답 실패 시 fallback narrative의 후순위 강제용. priority_rank 자연 정렬에서
#      review queue 가장 뒤로 밀린다. 변경 시 본 상수 1지점만 수정.
FAILURE_PRIORITY_RANK: int = 999


@dataclass
class NarratorResult:
    """단일 candidate에 대한 narrate 결과."""

    narrative: ReviewNarrative
    citation_result: CitationValidationResult
    model_tier: str  # "reasoning" | "light" | "failed"
    call_status: str  # "ok" | "fallback_used" | "failed"
    error: str | None = None


def _extract_known_ids(candidate: dict) -> tuple[set[str], set[str], set[str]]:
    """candidate에서 rule/feature/journal ID set 추출 — citation 검증 + enum 채움 공용."""
    rule_ids = {
        hit.get("rule_id", "") for hit in candidate.get("rule_hits", []) if hit.get("rule_id")
    }
    feature_ids = {
        feat.get("feature_id", "")
        for ml in candidate.get("ml_scores", [])
        for feat in ml.get("top_features", [])
        if feat.get("feature_id")
    }
    journal_id = candidate.get("journal_ref", {}).get("journal_id", "")
    journal_ids = {journal_id} if journal_id else set()
    return rule_ids, feature_ids, journal_ids


def _try_call(
    client: ChatClient,
    messages: list[dict[str, str]],
    schema: dict,
) -> tuple[ReviewNarrative | None, str | None]:
    """1회 LLM 호출 → JSON 파싱 → Pydantic 검증.

    Returns:
        (narrative, error_class) — 성공 시 (ReviewNarrative, None),
        실패 시 (None, 예외 클래스명 또는 사유 토큰).
        영구 장애(AuthenticationError 등)와 일시 장애(RateLimitError)는 호출자에서
        error_class 문자열로 구분해 NarratorResult.error에 분류 정보를 보존한다.
    """
    try:
        raw = client.chat(messages, temperature=0.1, format=schema)
    except Exception as exc:  # noqa: BLE001 — 외부 API 모든 예외 흡수 후 분류 노출
        error_class = type(exc).__name__
        logger.warning("LLM chat 호출 실패 [%s]: %s", error_class, exc)
        return None, error_class
    if not raw:
        logger.warning("LLM 빈 응답")
        return None, "EmptyResponse"
    try:
        return ReviewNarrative.model_validate_json(raw), None
    except (ValidationError, ValueError) as exc:
        logger.warning("LLM 응답 파싱 실패: %s — raw=%r", exc, raw[:200])
        return None, "ParseError"


def _make_failure_narrative(candidate: dict, reason: str) -> ReviewNarrative:
    """2회 모두 실패 시 후순위 fallback narrative.

    Why: 호출 실패도 review queue에 남겨 감사인이 LLM 미생성 candidate임을 인지할 수
        있도록 한다. `FAILURE_PRIORITY_RANK`로 강제 후순위, confidence=low.
    """
    return ReviewNarrative(
        candidate_id=candidate.get("candidate_id", "UNKNOWN"),
        priority_rank=FAILURE_PRIORITY_RANK,
        priority_score=0.0,
        summary=f"LLM 응답 실패 — 감사인 수동 검토 필요 ({reason})",
        reasoning=[],
        suggested_actions=[],
        confidence="low",
    )


def narrate(
    candidate: dict,
    reasoning_client: ChatClient,
    light_client: ChatClient,
    *,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> NarratorResult:
    """단일 candidate에 대해 LLM 호출 + 인용 검증.

    Args:
        candidate: candidate_builder가 생성한 LLM 입력 dict.
        reasoning_client: 1차 호출용 reasoning 티어 ChatClient.
        light_client: fallback 호출용 light 티어 ChatClient.
        system_prompt: 시스템 프롬프트 override 가능.

    Returns:
        NarratorResult — narrative + citation 결과 + 호출 메타.
    """
    rule_ids, feature_ids, journal_ids = _extract_known_ids(candidate)
    schema = build_review_narrative_schema(
        rule_id_enum=sorted(rule_ids),
        feature_id_enum=sorted(feature_ids),
        journal_id_enum=sorted(journal_ids),
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(candidate, ensure_ascii=False)},
    ]

    # 1차: reasoning tier
    narrative, reasoning_error = _try_call(reasoning_client, messages, schema)
    if narrative is not None:
        citation = validate_citations(narrative, rule_ids, feature_ids, journal_ids)
        return NarratorResult(
            narrative=citation.narrative,
            citation_result=citation,
            model_tier="reasoning",
            call_status="ok",
        )

    # 2차: light tier fallback
    narrative, light_error = _try_call(light_client, messages, schema)
    if narrative is not None:
        citation = validate_citations(narrative, rule_ids, feature_ids, journal_ids)
        return NarratorResult(
            narrative=citation.narrative,
            citation_result=citation,
            model_tier="light",
            call_status="fallback_used",
            error=f"reasoning={reasoning_error}",
        )

    # 3차: 두 티어 모두 실패 — confidence=low fallback narrative
    error_summary = f"reasoning={reasoning_error}; light={light_error}"
    fallback = _make_failure_narrative(candidate, error_summary)
    citation = validate_citations(fallback, rule_ids, feature_ids, journal_ids)
    return NarratorResult(
        narrative=citation.narrative,
        citation_result=citation,
        model_tier="failed",
        call_status="failed",
        error=error_summary,
    )


# ── 호출부 편의용 ──


def serialize_candidate_for_llm(candidate: dict) -> str:
    """candidate dict를 LLM에 보낼 JSON 문자열로 직렬화 (디버깅·테스트 용도)."""
    return json.dumps(candidate, ensure_ascii=False, sort_keys=True)


def deserialize_response(raw: str) -> Any:
    """LLM 원시 응답을 dict로 파싱. 디버깅·테스트 용도."""
    return json.loads(raw)
