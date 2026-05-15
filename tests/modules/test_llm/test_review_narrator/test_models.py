"""ReviewNarrative / ReasoningEvidence / SuggestedAction Pydantic 검증."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.llm.review_narrator.models import (
    EvidenceType,
    ReasoningEvidence,
    ReasoningItem,
    ReviewNarrative,
    SuggestedAction,
    SuggestedActionType,
)

# ── StrEnum ──


class TestEnums:
    def test_evidence_type_values(self):
        assert set(EvidenceType) == {"rule_hit", "ml_feature", "row"}

    def test_suggested_action_type_values(self):
        assert set(SuggestedActionType) == {
            "request_evidence",
            "account_analysis",
            "interview",
            "further_test",
        }

    def test_strenum_is_string(self):
        assert EvidenceType.RULE_HIT == "rule_hit"
        assert SuggestedActionType.INTERVIEW == "interview"


# ── ReasoningEvidence ──


class TestReasoningEvidence:
    def test_rule_hit_minimal(self):
        ev = ReasoningEvidence(type="rule_hit", rule_id="L1-01")
        assert ev.type == EvidenceType.RULE_HIT
        assert ev.rule_id == "L1-01"
        assert ev.feature_id == ""
        assert ev.line_no == 0

    def test_ml_feature_minimal(self):
        ev = ReasoningEvidence(type="ml_feature", model_id="vae_v1", feature_id="amount_zscore")
        assert ev.type == EvidenceType.ML_FEATURE
        assert ev.model_id == "vae_v1"

    def test_row_minimal(self):
        ev = ReasoningEvidence(type="row", journal_id="JE-001", line_no=3)
        assert ev.type == EvidenceType.ROW
        assert ev.line_no == 3

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError, match="type"):
            ReasoningEvidence(type="unknown_type")


# ── ReasoningItem ──


class TestReasoningItem:
    def test_with_evidence(self):
        item = ReasoningItem(
            claim="자정 직후 수기 입력",
            evidence=[ReasoningEvidence(type="rule_hit", rule_id="L1-01")],
        )
        assert item.claim == "자정 직후 수기 입력"
        assert len(item.evidence) == 1

    def test_empty_evidence_allowed_at_model_level(self):
        # Why: Pydantic 레벨에서는 빈 배열 허용. citation_validator가 강등 처리한다.
        item = ReasoningItem(claim="X", evidence=[])
        assert item.evidence == []


# ── SuggestedAction ──


class TestSuggestedAction:
    def test_minimal(self):
        sa = SuggestedAction(action_type="interview", description="작성자 인터뷰", target="USR-001")
        assert sa.action_type == SuggestedActionType.INTERVIEW

    def test_invalid_action_type_raises(self):
        with pytest.raises(ValidationError, match="action_type"):
            SuggestedAction(action_type="explode", description="x")


# ── ReviewNarrative ──


class TestReviewNarrative:
    def test_valid_minimal(self):
        narrative = ReviewNarrative(
            candidate_id="CAND-1",
            priority_rank=1,
            priority_score=0.5,
            summary="요약",
            confidence="medium",
        )
        assert narrative.reasoning == []
        assert narrative.suggested_actions == []
        assert narrative.confidence == "medium"

    def test_priority_score_lower_bound(self):
        with pytest.raises(ValidationError, match="priority_score"):
            ReviewNarrative(
                candidate_id="C",
                priority_rank=1,
                priority_score=-0.1,
                summary="s",
                confidence="low",
            )

    def test_priority_score_upper_bound(self):
        with pytest.raises(ValidationError, match="priority_score"):
            ReviewNarrative(
                candidate_id="C",
                priority_rank=1,
                priority_score=1.5,
                summary="s",
                confidence="low",
            )

    def test_priority_rank_must_be_positive(self):
        with pytest.raises(ValidationError, match="priority_rank"):
            ReviewNarrative(
                candidate_id="C",
                priority_rank=0,
                priority_score=0.1,
                summary="s",
                confidence="low",
            )

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValidationError, match="confidence"):
            ReviewNarrative(
                candidate_id="C",
                priority_rank=1,
                priority_score=0.5,
                summary="s",
                confidence="unknown",
            )

    def test_full_roundtrip(self, rn_valid_narrative):
        json_str = rn_valid_narrative.model_dump_json()
        restored = ReviewNarrative.model_validate_json(json_str)
        assert restored.candidate_id == rn_valid_narrative.candidate_id
        assert len(restored.reasoning) == len(rn_valid_narrative.reasoning)
        assert restored.reasoning[0].evidence[1].feature_id == "amount_zscore"

    def test_json_schema_generation(self):
        """OpenAI Structured Output용 JSON Schema 추출 가능 + 핵심 필드 노출."""
        schema = ReviewNarrative.model_json_schema()
        props = schema["properties"]
        assert "candidate_id" in props
        assert "priority_rank" in props
        assert "priority_score" in props
        assert "reasoning" in props
        assert "suggested_actions" in props
        assert "confidence" in props

    def test_parses_from_llm_style_dict(self, rn_valid_narrative):
        """LLM이 반환할 dict 형태 → ReviewNarrative 파싱."""
        payload = json.loads(rn_valid_narrative.model_dump_json())
        restored = ReviewNarrative(**payload)
        assert restored.priority_rank == 1
