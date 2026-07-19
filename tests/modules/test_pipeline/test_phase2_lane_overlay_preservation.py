"""Phase E primary queue 보존 회귀 — overlay/lane 도입이 PHASE1+VAE 2-way RRF 순위를 변경하지 않음을 검증.

Phase D Phase2CaseOverlay 확장 + Phase E lane UI 도입 후에도 기존 queue_fusion
2-way RRF 결과(`compute_rrf_score({"phase1_composite": ..., "phase2_unsupervised": ...})`)
가 그대로 보존되어야 한다.

docs/spec/PHASE2_GOVERNANCE_DESIGN.md 결정 8 — primary queue 변경 0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.services.queue_fusion import compute_rrf_score


def _phase1_phase2_2way(seed: int = 42, n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    phase1 = pd.Series(rng.beta(2, 5, n), name="phase1_composite", dtype=float)
    phase2 = pd.Series(rng.beta(2, 5, n), name="phase2_unsupervised", dtype=float)
    return compute_rrf_score({"phase1_composite": phase1, "phase2_unsupervised": phase2})


def test_primary_2way_rrf_score_is_stable_across_runs():
    """2-way RRF 결과가 random seed 만 같다면 동일하게 재현됨을 확인."""
    first = _phase1_phase2_2way()
    second = _phase1_phase2_2way()
    pd.testing.assert_series_equal(
        pd.Series(first["rrf_score"]),
        pd.Series(second["rrf_score"]),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        pd.Series(first["rrf_rank"]),
        pd.Series(second["rrf_rank"]),
        check_names=False,
    )


def test_overlay_helper_does_not_touch_primary_rrf():
    """Phase2CaseOverlay 함수 호출이 primary RRF 결과를 변경하지 않음."""
    from src.models.phase1_case import CaseGroupResult, Phase1CaseResult
    from src.services.phase2_case_contract import build_phase2_case_overlays

    baseline = _phase1_phase2_2way()
    baseline_snapshot = baseline.copy(deep=True)

    case = CaseGroupResult(
        case_id="case_A",
        primary_theme="control_failure",
        secondary_tags=[],
        evidence_types=["control_failure"],
        case_key="A",
        priority_score=0.5,
        base_priority_score=0.5,
        topside_bonus=0.0,
        priority_adjustment_reasons=[],
        priority_band="medium",
        amount_score=0.5,
        control_score=0.5,
        logic_score=0.0,
        timing_score=0.0,
        behavior_score=0.0,
        repeat_score=0.0,
        rule_count=1,
        evidence_count=1,
        document_count=1,
        row_count=1,
        total_amount=10_000_000.0,
        repeat_months=1,
        representative_explanation="A",
        evidence_tags=["control_failure"],
        documents=[],
        raw_rule_hits=[],
        has_control_failure=True,
        has_high_materiality=False,
        has_repeat_pattern=False,
    )
    from datetime import UTC, datetime

    phase1_result = Phase1CaseResult(
        run_id="r1",
        company_id="kr01",
        generated_at=datetime(2026, 5, 19, tzinfo=UTC),
        cases=[case],
    )
    _ = build_phase2_case_overlays(
        phase1_result,
        family_scores_by_case={"case_A": {"duplicate": 0.6}},
        family_ecdf_by_case={"case_A": {"duplicate": 0.95}},
        family_top_subdetectors_by_case={
            "case_A": {"duplicate": [("L2-03a", "exact_duplicate_amount")]}
        },
        family_roles={"duplicate": "active-ranker"},
        family_q95_thresholds={"duplicate": 0.5},
    )
    # overlay 생성 호출 후에도 baseline 결과는 그대로
    after = _phase1_phase2_2way()
    pd.testing.assert_frame_equal(baseline_snapshot, after)


def test_lane_sort_does_not_touch_primary_rrf():
    """sort_lane 호출이 primary RRF 결과를 변경하지 않음."""
    from src.services.phase2_lane_sort import sort_lane

    baseline = _phase1_phase2_2way()
    baseline_snapshot = baseline.copy(deep=True)
    overlays = [
        {
            "phase1_case_id": "c1",
            "family_contributions": [
                {
                    "family": "duplicate",
                    "score": 0.5,
                    "ecdf": 0.9,
                    "evidence_tier": "strong",
                    "evidence_tier_weight": 3,
                    "sub_detectors": [],
                }
            ],
        }
    ]
    _ = sort_lane("duplicate", overlays)
    after = _phase1_phase2_2way()
    pd.testing.assert_frame_equal(baseline_snapshot, after)
