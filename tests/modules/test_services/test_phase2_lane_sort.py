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
    pair_tier: str | None = None,
    relational_continuity_depth: float | None = None,
) -> dict:
    weight_map = {"strong": 3, "moderate": 2, "weak": 1, "ml_quantile": 0}
    pair_weight_map = {"strong": 3, "moderate": 2, "weak": 1}
    entry: dict = {
        "family": family,
        "score": score,
        "ecdf": ecdf,
        "role": "active-ranker",
        "evidence_tier": tier,
        "evidence_tier_weight": weight_map.get(tier or "", 0),
        "sub_detectors": [],
    }
    if pair_tier is not None:
        entry["pair_evidence_tier"] = pair_tier
        entry["pair_evidence_tier_weight"] = pair_weight_map.get(pair_tier, 0)
    if relational_continuity_depth is not None:
        entry["relational_continuity_depth"] = relational_continuity_depth
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


def _ic_overlay(
    case_id: str,
    *,
    score: float,
    ecdf: float,
    codes: list[str],
    family: str = "intercompany",
    tier: str | None = None,
) -> dict:
    weight_map = {"strong": 3, "moderate": 2, "weak": 1, "ml_quantile": 0}
    if tier is None:
        tiers_present = [_IC_CODE_TIER[c] for c in codes if c in _IC_CODE_TIER]
        # 가장 강한 tier 가 entry tier — codes 비어 있으면 None (tier_weight=0).
        tier = max(tiers_present, key=lambda t: weight_map[t]) if tiers_present else None
    sub_detectors = [
        {
            "code": code,
            "label": code,
            "evidence_tier": _IC_CODE_TIER.get(code),
            "evidence_tier_weight": weight_map.get(_IC_CODE_TIER.get(code) or "", 0),
        }
        for code in codes
    ]
    entry: dict = {
        "family": family,
        "score": score,
        "ecdf": ecdf,
        "role": "active-ranker",
        "evidence_tier": tier,
        "evidence_tier_weight": weight_map.get(tier or "", 0),
        "sub_detectors": sub_detectors,
    }
    return {
        "phase1_case_id": case_id,
        "family_contributions": [entry],
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

    def test_relational_tie_break_by_continuity_depth(self):
        # tier 동일·ecdf 동일·score 동일 → depth 가 큰 case 가 위.
        overlays = [
            _overlay(
                "c1",
                "relational",
                score=0.6,
                ecdf=0.7,
                tier="moderate",
                relational_continuity_depth=0.2,
            ),
            _overlay(
                "c2",
                "relational",
                score=0.6,
                ecdf=0.7,
                tier="moderate",
                relational_continuity_depth=0.85,
            ),
            _overlay(
                "c3",
                "relational",
                score=0.6,
                ecdf=0.7,
                tier="moderate",
                relational_continuity_depth=None,  # depth 미존재 → 0 fallback
            ),
        ]
        result = sort_lane("relational", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c2", "c1", "c3"]

    def test_relational_depth_does_not_override_tier(self):
        # depth 가 더 크더라도 tier 가 낮으면 위로 못 올라간다.
        overlays = [
            _overlay(
                "c_strong_low_depth",
                "relational",
                score=0.6,
                ecdf=0.5,
                tier="strong",
                relational_continuity_depth=0.1,
            ),
            _overlay(
                "c_moderate_high_depth",
                "relational",
                score=0.6,
                ecdf=0.9,
                tier="moderate",
                relational_continuity_depth=0.95,
            ),
        ]
        result = sort_lane("relational", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_strong_low_depth", "c_moderate_high_depth"]

    def test_duplicate_lane_pair_tier_tiebreak_within_same_evidence_tier(self):
        # 같은 evidence_tier_weight + 같은 ecdf + 같은 score 일 때,
        # pair_evidence_tier 가 strong > moderate > weak > 미부착(=0) 순으로 정렬.
        overlays = [
            _overlay("c_pw", "duplicate", score=0.5, ecdf=0.6, tier="moderate", pair_tier="weak"),
            _overlay(
                "c_pm", "duplicate", score=0.5, ecdf=0.6, tier="moderate", pair_tier="moderate"
            ),
            _overlay("c_ps", "duplicate", score=0.5, ecdf=0.6, tier="moderate", pair_tier="strong"),
            _overlay("c_none", "duplicate", score=0.5, ecdf=0.6, tier="moderate"),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_ps", "c_pm", "c_pw", "c_none"]

    def test_duplicate_pair_tier_does_not_override_evidence_tier(self):
        # evidence_tier_weight (strong sub-detector) 가 pair_tier 보다 우선.
        # strong sub + 미부착 pair 가 moderate sub + strong pair 보다 먼저.
        overlays = [
            _overlay(
                "c_mod_strongpair",
                "duplicate",
                score=0.5,
                ecdf=0.9,
                tier="moderate",
                pair_tier="strong",
            ),
            _overlay("c_strong_nopair", "duplicate", score=0.5, ecdf=0.6, tier="strong"),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_strong_nopair", "c_mod_strongpair"]

    def test_other_family_lane_ignores_pair_tier_field(self):
        # relational lane 에서는 pair_evidence_tier_weight 가 sort_key 에 들어가지 않음.
        # 같은 tier·score·ecdf 면 pair_tier 가 strong 이어도 순서는 비결정적이지 않게
        # 고정되어야 함 — 즉 pair_tier 영향 0.
        overlays = [
            _overlay(
                "c_with_pair",
                "relational",
                score=0.5,
                ecdf=0.6,
                tier="moderate",
                pair_tier="strong",
            ),
            _overlay("c_without_pair", "relational", score=0.5, ecdf=0.9, tier="moderate"),
        ]
        result = sort_lane("relational", overlays)
        ids = [o["phase1_case_id"] for o in result]
        # ecdf 0.9 가 0.6 보다 위 — pair_tier 무관.
        assert ids == ["c_without_pair", "c_with_pair"]

    def test_duplicate_pair_tier_missing_field_treated_as_zero(self):
        # pair_evidence_tier_weight 가 entry 에 없으면 0 (graceful fallback).
        overlays = [
            _overlay("c_no_pair", "duplicate", score=0.5, ecdf=0.6, tier="moderate"),
            _overlay(
                "c_weak_pair",
                "duplicate",
                score=0.5,
                ecdf=0.6,
                tier="moderate",
                pair_tier="weak",
            ),
        ]
        result = sort_lane("duplicate", overlays)
        ids = [o["phase1_case_id"] for o in result]
        # weak pair (weight=1) > 미부착 (weight=0).
        assert ids == ["c_weak_pair", "c_no_pair"]


class TestIntercompanyRolePriority:
    """IC lane 한정 ic_role_priority 차원 회귀 테스트 (2026-05-25 옵션 2).

    sort 우선순위: evidence_tier_weight > ic_role_priority > ecdf > score.
    ic_role_priority: reciprocal_flow=5 > amount_mismatch=4 > no_candidate=3
    > timing_gap=2 > weak_contract(=fallback 0).
    """

    def test_strong_tier_reciprocal_outranks_ic01_unmatched(self):
        # 같은 strong tier — ic_reciprocal_flow_prob(role=5) > IC01(role=3, no_candidate).
        overlays = [
            _ic_overlay("c_ic01", score=1.0, ecdf=0.6, codes=["IC01"]),
            _ic_overlay(
                "c_reciprocal",
                score=1.0,
                ecdf=0.6,
                codes=["ic_reciprocal_flow_prob"],
            ),
        ]
        result = sort_lane("intercompany", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_reciprocal", "c_ic01"]

    def test_weak_tier_no_candidate_outranks_timing(self):
        # 같은 weak tier — ic_unmatched_prob(role=3, no_candidate)
        # > ic_timing_prob(role=2, timing_gap).
        overlays = [
            _ic_overlay("c_timing", score=1.0, ecdf=0.6, codes=["ic_timing_prob"]),
            _ic_overlay("c_no_cand", score=1.0, ecdf=0.6, codes=["ic_unmatched_prob"]),
            _ic_overlay("c_ic03", score=1.0, ecdf=0.6, codes=["IC03"]),
        ]
        result = sort_lane("intercompany", overlays)
        ids = [o["phase1_case_id"] for o in result]
        # IC03(weak, role=2) 와 ic_timing_prob(weak, role=2) 는 동률
        # — ecdf·score tie 면 입력 순서 보존.
        assert ids[0] == "c_no_cand"
        assert set(ids[1:]) == {"c_timing", "c_ic03"}

    def test_role_priority_does_not_override_evidence_tier(self):
        # ic_amount_prob(moderate, role=4) 가 IC01(strong, role=3) 보다 위로 가서는 안 됨.
        # evidence_tier_weight 가 1차 sort dim.
        overlays = [
            _ic_overlay("c_amount_mod", score=1.0, ecdf=0.9, codes=["ic_amount_prob"]),
            _ic_overlay("c_ic01_strong", score=1.0, ecdf=0.6, codes=["IC01"]),
        ]
        result = sort_lane("intercompany", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_ic01_strong", "c_amount_mod"]

    def test_role_priority_dim_falls_back_to_ecdf(self):
        # 같은 tier + 같은 role priority — ecdf 가 다음 tiebreaker.
        overlays = [
            _ic_overlay(
                "c_amount_low_ecdf",
                score=1.0,
                ecdf=0.5,
                codes=["ic_amount_prob"],
            ),
            _ic_overlay(
                "c_amount_high_ecdf",
                score=1.0,
                ecdf=0.9,
                codes=["ic_amount_prob"],
            ),
        ]
        result = sort_lane("intercompany", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_amount_high_ecdf", "c_amount_low_ecdf"]

    def test_other_family_unaffected_by_ic_role_priority(self):
        # relational lane 에서 IC 코드가 들어가도 ic_role_priority 가 작동하지 않음
        # (lane sort 의 family 분기가 intercompany 외에는 secondary_dim=0 유지).
        overlays = [
            _ic_overlay(
                "c_high_ecdf",
                score=0.5,
                ecdf=0.9,
                codes=["ic_reciprocal_flow_prob"],
                family="relational",
            ),
            _ic_overlay(
                "c_low_ecdf",
                score=0.5,
                ecdf=0.6,
                codes=["IC01"],
                family="relational",
            ),
        ]
        result = sort_lane("relational", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_high_ecdf", "c_low_ecdf"]

    def test_weak_contract_only_falls_to_role_priority_zero(self):
        # weak_contract 는 sub_detector 코드로 표현되지 않음 — role priority=0 fallback.
        # tier·ecdf·score 가 같으면 weak_contract 만 있는 case 는 다른 role 보다 뒤.
        overlays = [
            _ic_overlay("c_weak_contract", score=1.0, ecdf=0.6, codes=[]),
            _ic_overlay("c_timing", score=1.0, ecdf=0.6, codes=["ic_timing_prob"]),
        ]
        # 둘 다 tier=None → tier_weight=0 동률.
        result = sort_lane("intercompany", overlays)
        ids = [o["phase1_case_id"] for o in result]
        assert ids == ["c_timing", "c_weak_contract"]


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
            "duplicate": "active-ranker",
            "relational": "active-ranker",
            "timeseries": "coarse-booster",
            "intercompany": "near-dormant",
        }
        lanes = list_active_lanes(roles)
        assert "unsupervised" not in lanes
        # near-dormant 도 기본 포함 (coverage gap 표시)
        assert "intercompany" in lanes
        assert set(lanes) == {"duplicate", "relational", "timeseries", "intercompany"}

    def test_excludes_near_dormant_when_requested(self):
        roles = {
            "duplicate": "active-ranker",
            "intercompany": "near-dormant",
        }
        lanes = list_active_lanes(roles, include_near_dormant=False)
        assert "intercompany" not in lanes
        assert lanes == ["duplicate"]


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
