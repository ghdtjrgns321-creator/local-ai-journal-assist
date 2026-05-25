"""PHASE2 family lane dashboard 컴포넌트 회귀 테스트.

Phase E lane UI 의 데이터 변환 helper (build_lane_summary_frame /
build_lane_content_frame) 검증. streamlit render 자체는 import 만 확인.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from dashboard.components.phase2_family_lanes import (
    LANE_LABELS,
    build_lane_content_frame,
    build_lane_summary_frame,
)


def _overlay(
    case_id: str, family: str, *, score: float, ecdf: float, tier: str | None, sub_codes: list[str]
) -> dict:
    weight_map = {"strong": 3, "moderate": 2, "weak": 1, "ml_quantile": 0}
    return {
        "phase1_case_id": case_id,
        "coverage_breadth_q95": 2,
        "top_family": family,
        "family_contributions": [
            {
                "family": family,
                "score": score,
                "ecdf": ecdf,
                "role": "active-ranker",
                "evidence_tier": tier,
                "evidence_tier_weight": weight_map.get(tier or "", 0),
                "sub_detectors": [{"code": c, "label": c} for c in sub_codes],
            }
        ],
    }


def _review_only_overlay(case_id: str) -> dict:
    return {
        "phase1_case_id": case_id,
        "coverage_breadth_q95": 0,
        "top_family": None,
        "family_contributions": [
            {
                "family": "intercompany",
                "score": 0.0,
                "ecdf": 0.0,
                "role": "near-dormant",
                "evidence_tier": None,
                "evidence_tier_weight": 0,
                "review_only": True,
                "review_only_count": 1,
                "review_reasons": ["missing_partner"],
                "sub_detectors": [{"code": "IC01", "label": "IC01 review-only"}],
            }
        ],
    }


class TestLaneSummaryFrame:
    def test_summary_has_one_row_per_active_lane(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.6, ecdf=0.9, tier="strong", sub_codes=["L2-03a"]),
            _overlay("c2", "relational", score=0.5, ecdf=0.7, tier="strong", sub_codes=["R01"]),
        ]
        roles = {
            "unsupervised": "active-ranker",
            "duplicate": "active-ranker",
            "relational": "active-ranker",
            "timeseries": "coarse-booster",
            "intercompany": "near-dormant",
        }
        frame = build_lane_summary_frame(overlays, roles)
        # unsupervised 는 lane 에서 제외
        assert "unsupervised" not in frame["family"].tolist()
        # duplicate, relational, timeseries, intercompany 4 lane
        assert set(frame["family"].tolist()) == {
            "duplicate",
            "relational",
            "timeseries",
            "intercompany",
        }
        # near-dormant intercompany 는 데이터 미보유 배지
        intercompany_row = frame[frame["family"] == "intercompany"].iloc[0]
        assert intercompany_row["badge"] == "데이터 미보유"
        assert intercompany_row["case_count"] == 0

    def test_lane_labels_used(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.6, ecdf=0.9, tier="strong", sub_codes=["L2-03a"])
        ]
        roles = {"duplicate": "active-ranker", "intercompany": "near-dormant"}
        frame = build_lane_summary_frame(overlays, roles)
        assert LANE_LABELS["duplicate"] in frame["lane"].tolist()

    def test_review_only_near_dormant_lane_is_counted(self):
        frame = build_lane_summary_frame(
            [_review_only_overlay("c1")],
            {"intercompany": "near-dormant"},
        )
        row = frame.iloc[0]
        assert row["case_count"] == 1
        assert row["review_only"] == 1
        assert row["badge"] == "검토-only 1건"


class TestLaneContentFrame:
    def test_content_sorted_by_tier_and_ecdf(self):
        overlays = [
            _overlay("c1", "duplicate", score=0.5, ecdf=0.6, tier="moderate", sub_codes=["L2-03b"]),
            _overlay("c2", "duplicate", score=0.5, ecdf=0.9, tier="strong", sub_codes=["L2-03a"]),
            _overlay("c3", "duplicate", score=0.5, ecdf=0.3, tier="weak", sub_codes=["L2-03d"]),
        ]
        frame = build_lane_content_frame("duplicate", overlays)
        assert frame["case_id"].tolist() == ["c2", "c1", "c3"]
        # strong tier 가 맨 위
        assert frame.iloc[0]["evidence_tier"] == "strong"
        assert "L2-03a" in frame.iloc[0]["sub_detectors"]

    def test_content_respects_max_rows(self):
        overlays = [
            _overlay(
                f"c{i}", "duplicate", score=0.5, ecdf=0.9 - i * 0.01, tier="strong", sub_codes=[]
            )
            for i in range(10)
        ]
        frame = build_lane_content_frame("duplicate", overlays, max_rows=3)
        assert len(frame) == 3

    def test_content_empty_when_no_overlay_for_family(self):
        overlays = [
            _overlay("c1", "relational", score=0.5, ecdf=0.7, tier="strong", sub_codes=["R01"])
        ]
        frame = build_lane_content_frame("duplicate", overlays)
        assert frame.empty

    def test_content_includes_review_only_metadata(self):
        frame = build_lane_content_frame("intercompany", [_review_only_overlay("c1")])
        assert frame.iloc[0]["case_id"] == "c1"
        assert frame.iloc[0]["review_only_count"] == 1
        assert frame.iloc[0]["review_reasons"] == "missing_partner"
        assert frame.iloc[0]["score"] == 0.0


class TestStreamlitImportSmoke:
    def test_module_imports(self):
        import dashboard.components.phase2_family_lanes as module

        assert hasattr(module, "render_lane_view")
        assert hasattr(module, "LANE_LABELS")
