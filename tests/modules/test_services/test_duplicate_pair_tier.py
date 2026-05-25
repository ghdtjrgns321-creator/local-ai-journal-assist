"""Duplicate family pair evidence tier classifier 회귀 테스트.

본 모듈은 lane sort 보조키로 쓰이는 categorical tier 분류만 검증한다.
truth recall 보고 threshold 재조정 금지 (D044 fitting-risk check 준수).
"""

from __future__ import annotations

from src.services.duplicate_pair_tier import (
    PAIR_TIER_ORDER,
    best_pair_tier,
    classify_pair_evidence_tier,
    pair_tier_weight,
)


class TestClassifyPairEvidenceTier:
    def test_none_features_return_weak(self):
        assert classify_pair_evidence_tier(None) == "weak"

    def test_empty_features_return_weak(self):
        assert classify_pair_evidence_tier({}) == "weak"

    def test_missing_same_partner_returns_weak(self):
        # same_partner=False 면 reference·text·amount 가 강해도 weak.
        features = {
            "same_partner": False,
            "reference_similarity": 1.0,
            "text_similarity": 1.0,
            "amount_similarity": 1.0,
        }
        assert classify_pair_evidence_tier(features) == "weak"

    def test_strong_via_reference_and_text(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.90,
            "text_similarity": 0.90,
            "amount_similarity": 0.0,
        }
        assert classify_pair_evidence_tier(features) == "strong"

    def test_strong_via_reference_and_amount(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.95,
            "text_similarity": 0.0,
            "amount_similarity": 0.99,
        }
        assert classify_pair_evidence_tier(features) == "strong"

    def test_strong_requires_reference_threshold(self):
        # reference < 0.90 이면 text 또는 amount 가 강해도 strong 진입 불가.
        features = {
            "same_partner": True,
            "reference_similarity": 0.85,
            "text_similarity": 1.0,
            "amount_similarity": 1.0,
        }
        assert classify_pair_evidence_tier(features) == "moderate"

    def test_moderate_via_reference_only(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.70,
            "text_similarity": 0.0,
            "amount_similarity": 0.0,
        }
        assert classify_pair_evidence_tier(features) == "moderate"

    def test_moderate_via_text_only(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.0,
            "text_similarity": 0.80,
            "amount_similarity": 0.0,
        }
        assert classify_pair_evidence_tier(features) == "moderate"

    def test_moderate_via_amount_only(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.0,
            "text_similarity": 0.0,
            "amount_similarity": 0.95,
        }
        assert classify_pair_evidence_tier(features) == "moderate"

    def test_weak_with_same_partner_but_below_thresholds(self):
        features = {
            "same_partner": True,
            "reference_similarity": 0.60,
            "text_similarity": 0.50,
            "amount_similarity": 0.90,
        }
        assert classify_pair_evidence_tier(features) == "weak"

    def test_none_similarity_values_treated_as_zero(self):
        features = {
            "same_partner": True,
            "reference_similarity": None,
            "text_similarity": None,
            "amount_similarity": None,
        }
        assert classify_pair_evidence_tier(features) == "weak"

    def test_nan_similarity_values_treated_as_zero(self):
        features = {
            "same_partner": True,
            "reference_similarity": float("nan"),
            "text_similarity": float("nan"),
            "amount_similarity": 0.96,
        }
        # amount_similarity 0.96 만 moderate 임계 통과 → moderate.
        assert classify_pair_evidence_tier(features) == "moderate"


class TestBestPairTier:
    def test_empty_returns_none_weight_zero(self):
        assert best_pair_tier([]) == (None, 0)

    def test_picks_strongest(self):
        tier, weight = best_pair_tier(["weak", "strong", "moderate"])
        assert tier == "strong"
        assert weight == PAIR_TIER_ORDER["strong"]

    def test_ignores_none_entries(self):
        tier, weight = best_pair_tier([None, "moderate", None])
        assert tier == "moderate"
        assert weight == PAIR_TIER_ORDER["moderate"]

    def test_unknown_tier_treated_as_zero(self):
        tier, weight = best_pair_tier(["unknown_value", "weak"])
        assert tier == "weak"
        assert weight == PAIR_TIER_ORDER["weak"]


class TestPairTierWeight:
    def test_known_tiers(self):
        assert pair_tier_weight("strong") == 3
        assert pair_tier_weight("moderate") == 2
        assert pair_tier_weight("weak") == 1

    def test_none_returns_zero(self):
        assert pair_tier_weight(None) == 0

    def test_unknown_returns_zero(self):
        assert pair_tier_weight("unknown") == 0
