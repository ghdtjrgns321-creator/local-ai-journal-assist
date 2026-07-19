"""PHASE2 hierarchical RRF helper 회귀 테스트 — EXPERIMENTAL.

본 모듈은 `compute_phase2_internal_rrf` 의 active-only / booster-only / mixed /
eligibility 분기를 검증한다. truth label 미사용.

[EXPERIMENTAL — V7 FIXED3 PRODUCTION REJECT (2026-05-19)]
hierarchical RRF 는 V7 fixed3 measurement-only 비교에서 2-way baseline 대비
TOP 100~5000 평균 -6.45pp 손실로 production reject 됨. 본 tests 는 미래
재평가(supervised/transformer 활성화 시)를 위해 보존되며 marker
`experimental_phase2_internal_rrf` 로 격리된다.

skip 방법: `uv run pytest -m "not experimental_phase2_internal_rrf" ...`
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.services.queue_fusion import K_DEFAULT, compute_phase2_internal_rrf

pytestmark = pytest.mark.experimental_phase2_internal_rrf


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


class TestActiveOnly:
    def test_two_active_rankers_score_decreasing(self):
        scores = {
            "f1": _series([0.9, 0.5, 0.1, 0.0]),
            "f2": _series([0.1, 0.5, 0.9, 0.0]),
        }
        result = compute_phase2_internal_rrf(scores, active_rankers=["f1", "f2"])
        rrf_score = result["phase2_internal_rrf_score"]
        # 두 family 의 (rank=1 + rank=3) = (rank=3 + rank=1) → row 0/2 동률
        assert rrf_score.iloc[0] == pytest.approx(rrf_score.iloc[2])
        assert rrf_score.iloc[1] > rrf_score.iloc[3]

    def test_single_active_ranker_matches_rrf_formula(self):
        scores = {"f1": _series([0.9, 0.5, 0.1])}
        result = compute_phase2_internal_rrf(scores, active_rankers=["f1"])
        expected = 1.0 / (K_DEFAULT + 1)
        assert result["phase2_internal_rrf_score"].iloc[0] == pytest.approx(expected)


class TestCoverageBreadth:
    def test_breadth_counts_q95_entries(self):
        # 100 rows. f1 마지막 5 행만 q95+, f2 마지막 5 행이 다른 위치
        f1 = list(np.linspace(0.0, 0.5, 95)) + [0.95] * 5
        f2 = [0.95] * 5 + list(np.linspace(0.0, 0.5, 95))
        scores = {"f1": _series(f1), "f2": _series(f2)}
        result = compute_phase2_internal_rrf(scores, active_rankers=["f1", "f2"])
        # row 0~4: f2 q95+ → breadth=1; row 95~99: f1 q95+ → breadth=1
        assert result["coverage_breadth_q95"].iloc[0] == 1
        assert result["coverage_breadth_q95"].iloc[99] == 1


class TestBoosterEligibility:
    def test_booster_does_not_contribute_when_ineligible(self):
        # f1 active, f2 booster. doc 0 만 f1 q95+ 진입.
        f1 = [0.0] * 99 + [0.99]
        f2 = list(np.linspace(0.1, 1.0, 100))  # 모든 행에 booster 값 존재
        scores = {"f1": _series(f1), "f2": _series(f2)}
        result = compute_phase2_internal_rrf(
            scores,
            active_rankers=["f1"],
            coarse_boosters=["f2"],
        )
        # active-only 비교
        active_only = compute_phase2_internal_rrf(scores, active_rankers=["f1"])
        # eligible 한 doc 만 booster 기여 추가
        # row 99 는 f1 q95+ 진입 → booster 가산, 다른 row 는 가산 0
        assert (
            result["phase2_internal_rrf_score"].iloc[99]
            > active_only["phase2_internal_rrf_score"].iloc[99]
        )
        # 비-eligible row 는 booster 기여 0 (단, 동률 rank 차이로 active_only 와 동일하지 않을 수 있음)
        non_eligible_idx = 50
        assert result["phase2_internal_rrf_score"].iloc[non_eligible_idx] == pytest.approx(
            active_only["phase2_internal_rrf_score"].iloc[non_eligible_idx],
            abs=1e-9,
        )

    def test_phase1_q95_entry_also_eligible(self):
        f1 = [0.0] * 99 + [0.99]
        f2 = [0.5] + [0.0] * 99  # row 0 만 booster tail 진입
        phase1 = [0.99] + [0.0] * 99  # row 0 만 PHASE1 q95+ 진입
        scores = {"f1": _series(f1), "f2": _series(f2)}
        result = compute_phase2_internal_rrf(
            scores,
            active_rankers=["f1"],
            coarse_boosters=["f2"],
            phase1_scores=_series(phase1),
        )
        # row 0 은 PHASE1 q95+ 이므로 eligible → booster 가산. f2 rank_tail 존재.
        assert result["booster_f2"].iloc[0] is not pd.NA
        # row 99 는 f1 q95+ 진입 → eligible 하지만 f2 booster 가 q95+ 아님 (f2[99]=0)
        # booster_f2 NaN.
        assert pd.isna(result["booster_f2"].iloc[99])


class TestValidation:
    def test_empty_active_rankers_rejected(self):
        scores = {"f1": _series([0.1, 0.2])}
        with pytest.raises(ValueError, match="active_rankers"):
            compute_phase2_internal_rrf(scores, active_rankers=[])

    def test_unknown_family_in_active_rejected(self):
        scores = {"f1": _series([0.1, 0.2])}
        with pytest.raises(ValueError, match="unknown families"):
            compute_phase2_internal_rrf(scores, active_rankers=["f2"])

    def test_overlap_active_booster_rejected(self):
        scores = {"f1": _series([0.1, 0.2])}
        with pytest.raises(ValueError, match="both active and booster"):
            compute_phase2_internal_rrf(scores, active_rankers=["f1"], coarse_boosters=["f1"])

    def test_index_mismatch_rejected(self):
        scores = {
            "f1": pd.Series([0.1, 0.2], index=[0, 1], dtype=float),
            "f2": pd.Series([0.3, 0.4], index=[2, 3], dtype=float),
        }
        with pytest.raises(ValueError, match="family index mismatch"):
            compute_phase2_internal_rrf(scores, active_rankers=["f1", "f2"])


class TestV7Fixed3Pattern:
    def test_five_family_mixed_active_booster(self):
        # V7 fixed3 유사 패턴: unsup/relational/duplicate active, timeseries booster,
        # intercompany 제외 (near-dormant).
        np.random.seed(42)
        n = 1000
        scores = {
            "unsupervised": _series(list(np.random.beta(2, 5, n))),  # 연속 분포
            "timeseries": _series([0.4] * 600 + [0.8] * 200 + [0.0] * 200),  # 이산
            "relational": _series([0.0] * 970 + list(np.random.uniform(0.5, 1.0, 30))),  # 희소
            "duplicate": _series([0.0] * 850 + list(np.random.uniform(0.5, 0.6, 150))),  # 이산-희소
        }
        result = compute_phase2_internal_rrf(
            scores,
            active_rankers=["unsupervised", "relational", "duplicate"],
            coarse_boosters=["timeseries"],
        )
        assert "phase2_internal_rrf_score" in result.columns
        assert "phase2_internal_rrf_rank" in result.columns
        assert "rank_unsupervised" in result.columns
        assert "rank_relational" in result.columns
        assert "booster_timeseries" in result.columns
        # rank 1 은 active-ranker q95+ 진입 + (가능시) booster 합산이 가장 큰 doc
        top_doc = result["phase2_internal_rrf_rank"].idxmin()
        assert result["phase2_internal_rrf_score"].loc[top_doc] > 0


class TestRankCorrectness:
    def test_rrf_score_matches_manual_calculation(self):
        # 단순 두 family, 알려진 rank → 직접 계산과 매칭
        scores = {
            "f1": _series([0.9, 0.5, 0.1]),
            "f2": _series([0.3, 0.7, 0.2]),
        }
        result = compute_phase2_internal_rrf(scores, active_rankers=["f1", "f2"])
        # f1 rank: 1, 2, 3 / f2 rank: 2, 1, 3
        # row 0: 1/61 + 1/62
        # row 1: 1/62 + 1/61
        # row 2: 1/63 + 1/63
        expected_0 = 1 / (60 + 1) + 1 / (60 + 2)
        expected_1 = 1 / (60 + 2) + 1 / (60 + 1)
        expected_2 = 1 / (60 + 3) + 1 / (60 + 3)
        assert result["phase2_internal_rrf_score"].iloc[0] == pytest.approx(expected_0)
        assert result["phase2_internal_rrf_score"].iloc[1] == pytest.approx(expected_1)
        assert result["phase2_internal_rrf_score"].iloc[2] == pytest.approx(expected_2)
