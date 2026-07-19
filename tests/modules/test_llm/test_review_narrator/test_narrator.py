"""narrator — 스펙 §4 호출 전략 + §6.1 narrator 표 케이스.

(1) Mock Structured Output 성공
(2) JSON 파싱 실패 → light 폴백
(3) 2회 실패 → confidence=low
(4) 빈 응답
(5) schema enum 주입 확인
"""

from __future__ import annotations

import json

from src.llm.review_narrator.models import build_review_narrative_schema
from src.llm.review_narrator.narrator import (
    NarratorResult,
    _extract_known_ids,
    narrate,
)

# ── (1) Mock Structured Output 성공 ──


class TestNarrateSuccess:
    def test_reasoning_tier_success(self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls):
        reasoning = rn_chat_client_cls([rn_valid_llm_response])
        light = rn_chat_client_cls([])
        result = narrate(rn_candidate, reasoning, light)
        assert isinstance(result, NarratorResult)
        assert result.call_status == "ok"
        assert result.model_tier == "reasoning"
        assert result.narrative.confidence == "high"
        assert result.citation_result.is_valid is True
        # reasoning만 호출, light는 미호출
        assert len(reasoning.calls) == 1
        assert light.calls == []

    def test_schema_passed_to_chat_client(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        reasoning = rn_chat_client_cls([rn_valid_llm_response])
        light = rn_chat_client_cls([])
        narrate(rn_candidate, reasoning, light)
        format_arg = reasoning.calls[0]["format"]
        assert isinstance(format_arg, dict)
        defs = format_arg.get("$defs", {})
        evidence = defs.get("ReasoningEvidence", {})
        rule_id_enum = evidence["properties"]["rule_id"]["enum"]
        assert "L1-01" in rule_id_enum
        assert "" in rule_id_enum  # 빈 문자열도 포함 (다른 type evidence용)


# ── (2) JSON 파싱 실패 → light 폴백 ──


class TestFallbackToLight:
    def test_invalid_json_triggers_light_fallback(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        reasoning = rn_chat_client_cls(["NOT A JSON {{"])
        light = rn_chat_client_cls([rn_valid_llm_response])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "fallback_used"
        assert result.model_tier == "light"
        assert result.narrative.confidence == "high"
        assert len(reasoning.calls) == 1
        assert len(light.calls) == 1

    def test_provider_exception_triggers_light_fallback(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        reasoning = rn_chat_client_cls([], raise_on_call=True)
        light = rn_chat_client_cls([rn_valid_llm_response])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "fallback_used"
        assert result.model_tier == "light"


# ── (3) 2회 실패 → confidence=low fallback ──


class TestBothFail:
    def test_both_invalid_returns_failure_narrative(self, rn_candidate, rn_chat_client_cls):
        from src.llm.review_narrator.narrator import FAILURE_PRIORITY_RANK

        reasoning = rn_chat_client_cls(["BROKEN"])
        light = rn_chat_client_cls(["ALSO BROKEN"])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "failed"
        assert result.model_tier == "failed"
        assert result.narrative.confidence == "low"
        assert result.narrative.priority_rank == FAILURE_PRIORITY_RANK
        assert result.error is not None
        # 운영 디버깅 가시성 — 사유 분류 토큰 포함
        assert "reasoning=" in result.error
        assert "light=" in result.error

    def test_both_raise_returns_failure_narrative(self, rn_candidate, rn_chat_client_cls):
        reasoning = rn_chat_client_cls([], raise_on_call=True)
        light = rn_chat_client_cls([], raise_on_call=True)
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "failed"
        assert result.narrative.confidence == "low"
        assert "RuntimeError" in result.error

    def test_fallback_preserves_reasoning_error(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        """light 폴백이 성공해도 reasoning 실패 분류는 NarratorResult.error에 보존."""
        reasoning = rn_chat_client_cls([], raise_on_call=True)
        light = rn_chat_client_cls([rn_valid_llm_response])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "fallback_used"
        assert result.error is not None
        assert "RuntimeError" in result.error


# ── (4) 빈 응답 ──


class TestEmptyResponse:
    def test_empty_string_triggers_fallback(
        self, rn_candidate, rn_valid_llm_response, rn_chat_client_cls
    ):
        reasoning = rn_chat_client_cls([""])
        light = rn_chat_client_cls([rn_valid_llm_response])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "fallback_used"
        assert result.model_tier == "light"


# ── (5) schema enum 주입 + helper 함수 ──


class TestSchemaEnum:
    def test_build_schema_injects_enums(self):
        schema = build_review_narrative_schema(
            rule_id_enum=["L1-01", "L2-04"],
            feature_id_enum=["amount_zscore"],
            journal_id_enum=["JE-001"],
        )
        defs = schema.get("$defs", {})
        evidence = defs["ReasoningEvidence"]
        assert set(evidence["properties"]["rule_id"]["enum"]) == {"", "L1-01", "L2-04"}
        assert set(evidence["properties"]["feature_id"]["enum"]) == {"", "amount_zscore"}
        assert set(evidence["properties"]["journal_id"]["enum"]) == {"", "JE-001"}

    def test_build_schema_empty_inputs_safe(self):
        schema = build_review_narrative_schema(
            rule_id_enum=[], feature_id_enum=[], journal_id_enum=[]
        )
        defs = schema.get("$defs", {})
        evidence = defs["ReasoningEvidence"]
        assert evidence["properties"]["rule_id"]["enum"] == [""]


class TestExtractKnownIds:
    def test_extracts_all_three(self, rn_candidate):
        rule_ids, feature_ids, journal_ids = _extract_known_ids(rn_candidate)
        assert rule_ids == {"L1-01"}
        assert feature_ids == {"amount_zscore"}
        assert journal_ids == {"JE-2025-0001"}

    def test_missing_sections_safe(self):
        rule_ids, feature_ids, journal_ids = _extract_known_ids({})
        assert rule_ids == set()
        assert feature_ids == set()
        assert journal_ids == set()


# ── (6) citation 강등 (2차 방어선 회귀) ──


class TestCitationDowngrade:
    def test_unknown_rule_id_downgrades(self, rn_candidate, rn_chat_client_cls):
        # mock이라 strict schema 우회 가능 — citation_validator(2차 방어선) 검증
        bad_payload = {
            "candidate_id": rn_candidate["candidate_id"],
            "priority_rank": 1,
            "priority_score": 0.9,
            "summary": "unknown rule cite",
            "reasoning": [
                {
                    "claim": "x",
                    "evidence": [
                        {
                            "type": "rule_hit",
                            "rule_id": "GHOST-99",
                            "model_id": "",
                            "feature_id": "",
                            "journal_id": "",
                            "line_no": 0,
                        },
                    ],
                },
            ],
            "suggested_actions": [],
            "confidence": "high",
        }
        reasoning = rn_chat_client_cls([json.dumps(bad_payload, ensure_ascii=False)])
        light = rn_chat_client_cls([])
        result = narrate(rn_candidate, reasoning, light)
        assert result.call_status == "ok"
        assert result.citation_result.is_valid is False
        assert result.narrative.confidence == "low"
