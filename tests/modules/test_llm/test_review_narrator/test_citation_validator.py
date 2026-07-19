"""citation_validator — 스펙 §인용 계약 5 케이스 + 추가 회귀.

(1) 모든 인용 valid → pass
(2) rule_id 미존재 → 강등
(3) feature_id 미존재 → 강등
(4) journal_id 미존재 → 강등
(5) reasoning 배열 비어있음 → 강등
"""

from __future__ import annotations

from src.llm.review_narrator.citation_validator import (
    CitationValidationResult,
    validate_citations,
)
from src.llm.review_narrator.models import (
    EvidenceType,
    ReasoningEvidence,
    ReasoningItem,
    ReviewNarrative,
)

# ── (1) 모든 인용 valid ──


class TestAllValid:
    def test_passes_without_downgrade(
        self,
        rn_valid_narrative,
        rn_known_rule_ids,
        rn_known_feature_ids,
        rn_known_journal_ids,
    ):
        result = validate_citations(
            rn_valid_narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert isinstance(result, CitationValidationResult)
        assert result.is_valid is True
        assert result.invalid_citations == []
        assert result.narrative.confidence == "high"


# ── (2) rule_id 미존재 ──


class TestUnknownRuleId:
    def test_downgraded_to_low(
        self,
        rn_known_rule_ids,
        rn_known_feature_ids,
        rn_known_journal_ids,
    ):
        narrative = ReviewNarrative(
            candidate_id="C2",
            priority_rank=1,
            priority_score=0.7,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="존재하지 않는 룰 인용",
                    evidence=[
                        ReasoningEvidence(type=EvidenceType.RULE_HIT, rule_id="L999-999"),
                    ],
                ),
            ],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert any("L999-999" in m for m in result.invalid_citations)

    def test_empty_rule_id_flagged(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        narrative = ReviewNarrative(
            candidate_id="C2b",
            priority_rank=1,
            priority_score=0.7,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="빈 rule_id",
                    evidence=[ReasoningEvidence(type=EvidenceType.RULE_HIT)],
                ),
            ],
            confidence="medium",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"


# ── (3) feature_id 미존재 ──


class TestUnknownFeatureId:
    def test_downgraded_to_low(self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids):
        narrative = ReviewNarrative(
            candidate_id="C3",
            priority_rank=2,
            priority_score=0.6,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="존재하지 않는 feature",
                    evidence=[
                        ReasoningEvidence(
                            type=EvidenceType.ML_FEATURE,
                            model_id="vae_v1",
                            feature_id="ghost_feature",
                        ),
                    ],
                ),
            ],
            confidence="medium",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert any("ghost_feature" in m for m in result.invalid_citations)

    def test_empty_model_id_flagged(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        """ml_feature evidence에서 model_id가 비어있으면 강등 (스펙 §인용 계약)."""
        narrative = ReviewNarrative(
            candidate_id="C3b",
            priority_rank=1,
            priority_score=0.6,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="model_id 누락",
                    evidence=[
                        ReasoningEvidence(
                            type=EvidenceType.ML_FEATURE,
                            feature_id="amount_zscore",
                        ),
                    ],
                ),
            ],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert any("model_id" in m for m in result.invalid_citations)

    def test_empty_feature_id_flagged(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        """ml_feature evidence에서 feature_id가 비어있으면 강등."""
        narrative = ReviewNarrative(
            candidate_id="C3c",
            priority_rank=1,
            priority_score=0.6,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="feature_id 누락",
                    evidence=[
                        ReasoningEvidence(
                            type=EvidenceType.ML_FEATURE,
                            model_id="vae_v1",
                        ),
                    ],
                ),
            ],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert any("feature_id" in m for m in result.invalid_citations)


# ── (4) journal_id 미존재 ──


class TestUnknownJournalId:
    def test_downgraded_to_low(self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids):
        narrative = ReviewNarrative(
            candidate_id="C4",
            priority_rank=3,
            priority_score=0.4,
            summary="x",
            reasoning=[
                ReasoningItem(
                    claim="존재하지 않는 전표 인용",
                    evidence=[
                        ReasoningEvidence(
                            type=EvidenceType.ROW,
                            journal_id="JE-9999-9999",
                            line_no=1,
                        ),
                    ],
                ),
            ],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert any("JE-9999-9999" in m for m in result.invalid_citations)


# ── (5) reasoning 배열 비어있음 ──


class TestEmptyReasoning:
    def test_empty_reasoning_downgraded(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        narrative = ReviewNarrative(
            candidate_id="C5",
            priority_rank=1,
            priority_score=0.5,
            summary="reasoning 없음",
            reasoning=[],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert "reasoning array is empty" in result.invalid_citations

    def test_empty_evidence_downgraded(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        narrative = ReviewNarrative(
            candidate_id="C5b",
            priority_rank=1,
            priority_score=0.5,
            summary="evidence 비어있음",
            reasoning=[ReasoningItem(claim="claim only", evidence=[])],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"


# ── 추가: 부분 위반 + 원본 보존 ──


class TestPartialInvalid:
    def test_one_invalid_among_many_still_downgrades(
        self, rn_known_rule_ids, rn_known_feature_ids, rn_known_journal_ids
    ):
        """valid + invalid 혼합 → 강등. 모든 위반 사유가 수집되어야 함."""
        narrative = ReviewNarrative(
            candidate_id="C6",
            priority_rank=1,
            priority_score=0.8,
            summary="혼합",
            reasoning=[
                ReasoningItem(
                    claim="valid + invalid",
                    evidence=[
                        ReasoningEvidence(type="rule_hit", rule_id="L1-01"),
                        ReasoningEvidence(type="rule_hit", rule_id="L999"),
                    ],
                ),
            ],
            confidence="high",
        )
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.is_valid is False
        assert result.narrative.confidence == "low"
        assert len(result.invalid_citations) == 1
        assert "L999" in result.invalid_citations[0]

    def test_does_not_mutate_input_narrative(
        self,
        rn_valid_narrative,
        rn_known_rule_ids,
        rn_known_feature_ids,
        rn_known_journal_ids,
    ):
        """강등 시 원본 narrative.confidence는 보존되어야 함."""
        # invalid 시나리오 만들기
        narrative = rn_valid_narrative.model_copy(
            update={
                "reasoning": [
                    ReasoningItem(
                        claim="bad",
                        evidence=[ReasoningEvidence(type="rule_hit", rule_id="UNKNOWN")],
                    )
                ]
            }
        )
        original_confidence = narrative.confidence
        result = validate_citations(
            narrative,
            rn_known_rule_ids,
            rn_known_feature_ids,
            rn_known_journal_ids,
        )
        assert result.narrative.confidence == "low"
        assert narrative.confidence == original_confidence
