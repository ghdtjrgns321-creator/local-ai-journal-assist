"""PHASE2 family lane 정렬 helper 회귀 테스트.

Phase E lane UI 의 입력이 되는 lane_sort / lane_summary / list_active_lanes 검증.
"""

from __future__ import annotations

from src.services.phase2_lane_sort import (
    best_subdetector_tier,
    lane_summary,
    list_active_lanes,
    sort_lane,
)


def _overlay(
    case_id: str,
    family: str,
    *,
    score: float,
    ecdf: float,
    tier: str | None,
) -> dict:
    weight_map = {"strong": 3, "moderate": 2, "weak": 1, "ml_quantile": 0}
    entry: dict = {
        "family": family,
        "score": score,
        "ecdf": ecdf,
        "role": "active-ranker",
        "evidence_tier": tier,
        "evidence_tier_weight": weight_map.get(tier or "", 0),
        "sub_detectors": [],
    }
    return {
        "phase1_case_id": case_id,
        "family_contributions": [entry],
    }


# IC role priority 차원 테스트용 헬퍼 — sub_detectors 코드와 tier 를 함께 부착.
# tier 미지정 시 가장 강한 IC 코드 tier 로 자동 도출.
_IC_CODE_TIER: dict[str, str] = {
    "ic_reciprocal_flow_prob": "strong",
    "IC01": "strong",
    "IC02": "moderate",
    "ic_amount_prob": "moderate",
    "IC03": "weak",
    "ic_timing_prob": "weak",
    "ic_unmatched_prob": "weak",
}


def _review_only_overlay(case_id: str) -> dict:
    return {
        "phase1_case_id": case_id,
        "family_contributions": [
            {
                "family": "intercompany",
                "score": 0.0,
                "ecdf": 0.0,
                "role": "near-dormant",
                "evidence_tier": None,
                "evidence_tier_weight": 0,
                "review_only": True,
                "review_only_count": 2,
                "review_reasons": ["missing_partner"],
                "sub_detectors": [],
            }
        ],
    }


class TestSortLane:
    def test_orders_by_tier_then_ecdf(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.5, ecdf=0.7, tier="moderate"),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.9, tier="strong"),
            _overlay("c3", "duplicate", score=0.5, ecdf=0.6, tier="weak"),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        # strong > moderate > weak
        assert ids == ["c2", "c1", "c3"]

    def test_excludes_zero_score_by_default(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.0, ecdf=0.0, tier=None),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.7, tier="strong"),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c2"]

    def test_includes_review_only_zero_score_by_default(self):
        result = sort_lane("intercompany", [_review_only_overlay("c1")])
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c1"]

    def test_includes_zero_when_requested(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.0, ecdf=0.0, tier=None),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.7, tier="strong"),
        ]
        result = sort_lane("duplicate", overlays, include_zero_score=True)
        assert len(result) == 2

    def test_skips_overlay_missing_family(self):
        overlays = [
            _overlay("c1", "relational", score=0.5, ecdf=0.5, tier="strong"),
        ]
        result = sort_lane("duplicate", overlays)
        assert result == []

    def test_ecdf_break_when_tier_equal(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.5, ecdf=0.6, tier="strong"),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.9, tier="strong"),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c2", "c1"]


class TestLaneSummary:
    def test_near_dormant_returns_no_data_badge(self):
        summary = lane_summary("intercompany", [], family_role="near-dormant")
        assert summary["badge"] == "데이터 미보유"
        assert summary["case_count"] == 0

    def test_near_dormant_review_only_reports_count(self):
        summary = lane_summary(
            "intercompany",
            [_review_only_overlay("c1")],
            family_role="near-dormant",
        )
        assert summary["badge"] == "검토-only 2건"
        assert summary["case_count"] == 1
        assert summary["review_only_count"] == 2

    def test_active_lane_counts_tiers(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.5, ecdf=0.9, tier="strong"),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.7, tier="strong"),
            _overlay("c3", "duplicate", score=0.5, ecdf=0.5, tier="moderate"),
            _overlay("c4", "duplicate", score=0.5, ecdf=0.3, tier="weak"),
        ]
        summary = lane_summary("duplicate", overlays, family_role="active-ranker")
        assert summary["case_count"] == 4
        assert summary["tier_counts"]["strong"] == 2
        assert summary["tier_counts"]["moderate"] == 1
        assert summary["tier_counts"]["weak"] == 1
        assert "strong 2건" in summary["badge"]

    def test_coarse_booster_badge(self):
        overlays = [
            _overlay("c1", "timeseries", score=0.8, ecdf=0.8, tier="moderate"),
        ]
        summary = lane_summary("timeseries", overlays, family_role="coarse-booster")
        assert "보조" in summary["badge"]


class TestListActiveLanes:
    def test_excludes_unsupervised_from_lanes(self):
        roles = {
            "unsupervised": "active-ranker",
            "relational": "active-ranker",
            "timeseries": "coarse-booster",
            "intercompany": "near-dormant",
        }
        lanes = list_active_lanes(roles)
        assert "unsupervised" not in lanes
        # near-dormant 도 기본 포함 (coverage gap 표시)
        assert "intercompany" in lanes
        assert set(lanes) == {"relational", "timeseries", "intercompany"}

    def test_excludes_near_dormant_when_requested(self):
        roles = {
            "relational": "active-ranker",
            "intercompany": "near-dormant",
        }
        lanes = list_active_lanes(roles, include_near_dormant=False)
        assert "intercompany" not in lanes
        assert lanes == ["relational"]


class TestBestSubdetectorTier:
    def test_picks_strongest_tier(self):
        # duplicate 에 L2-03a(strong) + L2-03d(weak)
        tier, weight = best_subdetector_tier("duplicate", ["L2-03a", "L2-03d"])
        assert tier == "strong"
        assert weight == 3

    def test_returns_none_for_unknown_codes(self):
        tier, weight = best_subdetector_tier("duplicate", ["L2-99x"])
        assert tier is None
        assert weight == 0
