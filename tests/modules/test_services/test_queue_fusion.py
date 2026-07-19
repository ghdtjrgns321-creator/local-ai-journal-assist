"""RRF 통합 큐 정렬 단위 테스트."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from src.services.queue_fusion import (
    K_DEFAULT,
    compute_phase2_internal_noisy_or,
    compute_rrf_score,
    to_ecdf,
)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=np.float64)


# ── 식 정확성 ────────────────────────────────────────────────


def test_rrf_score_formula_simple() -> None:
    """k=60, 3 case 단순 입력에서 식이 정확히 계산된다."""
    p1 = _series([3.0, 2.0, 1.0])  # rank: 1, 2, 3
    p2 = _series([1.0, 2.0, 3.0])  # rank: 3, 2, 1

    result = compute_rrf_score(p1, p2, k=60)

    expected = np.array(
        [
            1 / (60 + 1) + 1 / (60 + 3),
            1 / (60 + 2) + 1 / (60 + 2),
            1 / (60 + 3) + 1 / (60 + 1),
        ]
    )
    np.testing.assert_allclose(result["rrf_score"].to_numpy(), expected, rtol=1e-12)
    assert result["rank_phase1"].tolist() == [1, 2, 3]
    assert result["rank_phase2"].tolist() == [3, 2, 1]


def test_rrf_score_formula_dict_rankers() -> None:
    """dict API 는 rank_<name> 컬럼과 N-way score 를 반환한다."""
    rankers = {
        "phase1_composite": _series([3.0, 2.0, 1.0]),
        "phase2_unsupervised": _series([1.0, 2.0, 3.0]),
    }
    result = compute_rrf_score(rankers, k=60)
    assert result["rank_phase1_composite"].tolist() == [1, 2, 3]
    assert result["rank_phase2_unsupervised"].tolist() == [3, 2, 1]


def test_rrf_rank_descending_by_score() -> None:
    """양 ranker 에서 상위인 case 가 rrf_rank 1 을 받는다."""
    # case 0 양쪽 상위, case 1 양쪽 중위, case 2 한쪽만 상위.
    p1 = _series([5.0, 3.0, 4.0])
    p2 = _series([5.0, 3.0, 1.0])
    result = compute_rrf_score(p1, p2)
    # case 0: 1/61 + 1/61, case 2: 1/62 + 1/63, case 1: 1/63 + 1/62.
    # case 0 > case 2 ≈ case 1.
    assert int(result["rrf_rank"].iloc[0]) == 1
    assert int(result["rrf_rank"].iloc[2]) < int(result["rrf_rank"].iloc[1]) or (
        int(result["rrf_rank"].iloc[2]) == int(result["rrf_rank"].iloc[1])
    )


# ── 동률 처리 ────────────────────────────────────────────────


def test_rank_tie_uses_method_min() -> None:
    """method='min' 이면 동률 그룹은 같은(최소) rank 를 받는다."""
    p1 = _series([5.0, 5.0, 3.0, 1.0])
    p2 = _series([1.0, 1.0, 1.0, 1.0])
    result = compute_rrf_score(p1, p2)
    # 두 동률은 rank 1 둘 다, 다음은 rank 3 (2 가 아님).
    assert result["rank_phase1"].tolist() == [1, 1, 3, 4]
    # PHASE2 동률 4 → 모두 rank 1.
    assert result["rank_phase2"].tolist() == [1, 1, 1, 1]


# ── PHASE2 NaN 처리 ──────────────────────────────────────────


def test_phase2_nan_gets_worst_rank() -> None:
    """phase2_score NaN 은 worst rank(동률) 로 처리된다."""
    p1 = _series([10.0, 9.0, 8.0, 7.0])
    p2 = _series([0.5, np.nan, 0.8, np.nan])
    result = compute_rrf_score(p1, p2)
    # NaN 둘은 같은 worst rank, 둘 다 가장 큰 숫자여야 한다.
    nan_ranks = result["rank_phase2"].iloc[[1, 3]].tolist()
    non_nan_ranks = result["rank_phase2"].iloc[[0, 2]].tolist()
    assert nan_ranks[0] == nan_ranks[1]
    assert min(nan_ranks) > max(non_nan_ranks)


def test_all_phase2_nan_still_valid() -> None:
    """PHASE2 가 전부 NaN 이어도 PHASE1 단독 정렬과 동일하게 동작한다."""
    p1 = _series([3.0, 1.0, 2.0])
    p2 = _series([np.nan, np.nan, np.nan])
    result = compute_rrf_score(p1, p2)
    # PHASE2 가 모두 worst tie → RRF rank 는 PHASE1 rank 와 동일.
    assert result["rrf_rank"].tolist() == result["rank_phase1"].tolist()


# ── PHASE1 NaN → ValueError ─────────────────────────────────


def test_phase1_nan_raises() -> None:
    p1 = pd.Series([1.0, np.nan, 3.0], dtype=np.float64)
    p2 = _series([1.0, 2.0, 3.0])
    with pytest.raises(ValueError, match="phase1_score contains NaN"):
        compute_rrf_score(p1, p2)


def test_phase1_composite_nan_raises() -> None:
    rankers = {
        "phase1_composite": pd.Series([1.0, np.nan, 3.0], dtype=np.float64),
        "phase2_unsupervised": _series([1.0, 2.0, 3.0]),
    }
    with pytest.raises(ValueError, match="phase1_composite contains NaN"):
        compute_rrf_score(rankers)


# ── 입력 검증 ────────────────────────────────────────────────


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        compute_rrf_score(_series([1.0, 2.0]), _series([1.0, 2.0, 3.0]))


def test_index_mismatch_raises() -> None:
    rankers = {
        "phase1_composite": pd.Series([1.0, 2.0], index=["a", "b"], dtype=np.float64),
        "phase2_unsupervised": pd.Series([1.0, 2.0], index=["a", "c"], dtype=np.float64),
    }
    with pytest.raises(ValueError, match="ranker index mismatch"):
        compute_rrf_score(rankers)


def test_dtype_validation_rejects_int() -> None:
    p1 = pd.Series([1, 2, 3], dtype=np.int64)
    p2 = _series([1.0, 2.0, 3.0])
    with pytest.raises(TypeError, match="phase1_score must be float64"):
        compute_rrf_score(p1, p2)


def test_dtype_validation_phase2() -> None:
    p1 = _series([1.0, 2.0, 3.0])
    p2 = pd.Series([1, 2, 3], dtype=np.int64)
    with pytest.raises(TypeError, match="phase2_score must be float64"):
        compute_rrf_score(p1, p2)


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        compute_rrf_score(_series([1.0, 2.0]), _series([1.0, 2.0]), k=0)


def test_k_default_is_60() -> None:
    assert K_DEFAULT == 60


# ── k 변경 허용 (단 정책상 호출처는 60 고정) ────────────────


def test_k_parameter_accepted() -> None:
    """k 인자 자체는 호출 가능. 정책상 60 유지는 호출처 책임."""
    p1 = _series([3.0, 2.0, 1.0])
    p2 = _series([1.0, 2.0, 3.0])
    res_60 = compute_rrf_score(p1, p2, k=60)
    res_30 = compute_rrf_score(p1, p2, k=30)
    # 동일 입력에서 k 만 바꿔도 rrf_rank 순서 자체는 동일.
    assert res_60["rrf_rank"].tolist() == res_30["rrf_rank"].tolist()
    # 점수 값은 다름.
    assert not np.allclose(res_60["rrf_score"], res_30["rrf_score"])


# ── 출력 dtype / index ───────────────────────────────────────


def test_output_dtypes() -> None:
    p1 = _series([3.0, 2.0, 1.0])
    p2 = _series([1.0, 2.0, 3.0])
    result = compute_rrf_score(p1, p2)
    assert result["rank_phase1"].dtype == np.int64
    assert result["rank_phase2"].dtype == np.int64
    assert result["rrf_score"].dtype == np.float64
    assert result["rrf_rank"].dtype == np.int64


def test_output_preserves_index() -> None:
    p1 = pd.Series([3.0, 2.0, 1.0], index=["a", "b", "c"], dtype=np.float64)
    p2 = pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"], dtype=np.float64)
    result = compute_rrf_score(p1, p2)
    assert result.index.tolist() == ["a", "b", "c"]


# ── 성능 ─────────────────────────────────────────────────────


def test_large_input_under_one_second() -> None:
    """10k case 입력에서 1초 미만으로 완료."""
    rng = np.random.default_rng(42)
    n = 10_000
    p1 = pd.Series(rng.random(n).astype(np.float64), dtype=np.float64)
    p2 = pd.Series(rng.random(n).astype(np.float64), dtype=np.float64)
    t0 = time.perf_counter()
    result = compute_rrf_score(p1, p2)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"slow: {elapsed:.3f}s"
    assert len(result) == n


# ── 5-way RRF ────────────────────────────────────────────────


def test_five_way_identical_scores_have_identical_rrf_score() -> None:
    values = _series([1.0, 1.0, 1.0, 1.0])
    rankers = {
        "phase1_composite": values.copy(),
        "phase2_unsupervised": values.copy(),
        "phase2_timeseries": values.copy(),
        "phase2_relational": values.copy(),
        "phase2_duplicate": values.copy(),
    }
    result = compute_rrf_score(rankers)
    assert result["rrf_score"].nunique() == 1
    assert result["rrf_rank"].tolist() == [1, 1, 1, 1]


def test_all_nan_ranker_contributes_constant_only() -> None:
    four_way = {
        "phase1_composite": _series([4.0, 3.0, 2.0, 1.0]),
        "phase2_unsupervised": _series([1.0, 2.0, 3.0, 4.0]),
        "phase2_timeseries": _series([0.1, 0.3, 0.2, 0.4]),
        "phase2_relational": _series([7.0, 6.0, 8.0, 5.0]),
    }
    five_way = {
        **four_way,
        "phase2_intercompany": pd.Series([np.nan, np.nan, np.nan, np.nan], dtype=np.float64),
    }
    res_four = compute_rrf_score(four_way)
    res_five = compute_rrf_score(five_way)
    np.testing.assert_allclose(
        res_five["rrf_score"].to_numpy() - res_four["rrf_score"].to_numpy(),
        np.repeat(1 / (K_DEFAULT + 1), 4),
        rtol=1e-12,
    )
    assert res_five["rrf_rank"].tolist() == res_four["rrf_rank"].tolist()


def test_negative_correlation_rankers_sum_directly() -> None:
    rankers = {
        "phase1_composite": _series([4.0, 3.0, 2.0, 1.0]),
        "phase2_timeseries": _series([1.0, 2.0, 3.0, 4.0]),
    }
    result = compute_rrf_score(rankers)
    expected = np.array(
        [
            1 / (60 + 1) + 1 / (60 + 4),
            1 / (60 + 2) + 1 / (60 + 3),
            1 / (60 + 3) + 1 / (60 + 2),
            1 / (60 + 4) + 1 / (60 + 1),
        ]
    )
    np.testing.assert_allclose(result["rrf_score"].to_numpy(), expected, rtol=1e-12)


# ── PHASE2 Noisy-OR (채택된 family 결합식, 2026-05-19) ─────────────


class TestToEcdf:
    def test_ecdf_uniform_distribution(self):
        scores = _series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        ecdf = to_ecdf(scores)
        assert ecdf.min() == pytest.approx(0.1)
        assert ecdf.max() == pytest.approx(1.0)
        assert ecdf.is_monotonic_increasing

    def test_ecdf_nan_treated_as_zero(self):
        scores = pd.Series([np.nan, 0.5, 0.0, 1.0], dtype=float)
        ecdf = to_ecdf(scores)
        assert ecdf.iloc[3] == pytest.approx(1.0)
        # NaN 과 0 은 무신호로 보존한다.
        assert ecdf.iloc[0] == pytest.approx(0.0)
        assert ecdf.iloc[2] == pytest.approx(0.0)

    def test_ecdf_all_same_value(self):
        scores = _series([0.5, 0.5, 0.5, 0.5])
        ecdf = to_ecdf(scores)
        np.testing.assert_allclose(ecdf.to_numpy(), [0.625, 0.625, 0.625, 0.625], rtol=1e-9)

    def test_ecdf_all_zero_stays_zero(self):
        scores = _series([0.0, 0.0, 0.0, 0.0])
        ecdf = to_ecdf(scores)
        np.testing.assert_allclose(ecdf.to_numpy(), [0.0, 0.0, 0.0, 0.0], rtol=1e-9)

    def test_sparse_binary_zero_rows_do_not_contribute(self):
        scores = _series([0.0, 0.0, 0.0, 1.0])
        ecdf = to_ecdf(scores)
        np.testing.assert_allclose(ecdf.to_numpy(), [0.0, 0.0, 0.0, 1.0], rtol=1e-9)


class TestNoisyOrFormula:
    def test_single_family_equals_ecdf(self):
        scores = _series([0.0, 0.25, 0.5, 0.75, 1.0])
        result = compute_phase2_internal_noisy_or({"f1": scores})
        ecdf = to_ecdf(scores)
        np.testing.assert_allclose(result.to_numpy(), ecdf.to_numpy(), rtol=1e-9)

    def test_two_independent_families_or_formula(self):
        """식: 1 - (1 - ecdf_f1)(1 - ecdf_f2)."""
        f1 = _series([0.0, 0.5, 1.0])
        f2 = _series([1.0, 0.5, 0.0])
        result = compute_phase2_internal_noisy_or({"f1": f1, "f2": f2})
        ecdf1 = to_ecdf(f1).to_numpy()
        ecdf2 = to_ecdf(f2).to_numpy()
        expected = 1.0 - (1.0 - np.clip(ecdf1, 0, 1 - 1e-12)) * (1.0 - np.clip(ecdf2, 0, 1 - 1e-12))
        np.testing.assert_allclose(result.to_numpy(), expected, rtol=1e-9)

    def test_result_bounded_in_unit_interval(self):
        rng = np.random.default_rng(42)
        f1 = pd.Series(rng.beta(2, 5, 1000), dtype=float)
        f2 = pd.Series(rng.beta(2, 5, 1000), dtype=float)
        f3 = pd.Series(rng.beta(2, 5, 1000), dtype=float)
        result = compute_phase2_internal_noisy_or({"f1": f1, "f2": f2, "f3": f3})
        assert result.min() >= 0.0
        assert result.max() < 1.0

    def test_or_aggregation_monotonic(self):
        """한 family 라도 강해지면 결합 점수도 강해진다.

        ECDF 는 rank-based 이므로 같은 batch 내에서 비교하려면 4개 case 를 같이 둠.
        """
        # 4-case batch: case_high 에서 f1 이 더 강하게 신호 보냄
        result_high = compute_phase2_internal_noisy_or(
            {"f1": _series([0.1, 0.2, 0.3, 0.99]), "f2": _series([0.0, 0.0, 0.0, 0.0])}
        )
        result_low = compute_phase2_internal_noisy_or(
            {"f1": _series([0.1, 0.2, 0.3, 0.5]), "f2": _series([0.0, 0.0, 0.0, 0.0])}
        )
        # 두 batch 동일 — 마지막 row 가 4 case 중 최고 → ecdf=1.0 → 둘 다 1-epsilon 으로 cap
        # 하지만 더 낮은 row 들은 다른 정도로 (f1 의 ranking 안정성)
        # 마지막 row 의 결합값은 epsilon 차이 → 비교 의미 약함. 대신 row 0 ~ 2 의
        # 값 모두 양수 (Noisy-OR 가 0 family 와 결합 시 단일 family ecdf 와 동일).
        assert result_high.iloc[3] >= result_low.iloc[3]
        # 더 의미 있는 monotonic check: f2 가 신호 가지면 결합값이 항상 큼
        result_with_f2 = compute_phase2_internal_noisy_or(
            {"f1": _series([0.0, 0.5, 0.0, 0.0]), "f2": _series([0.0, 0.5, 0.0, 0.0])}
        )
        result_without_f2 = compute_phase2_internal_noisy_or(
            {"f1": _series([0.0, 0.5, 0.0, 0.0]), "f2": _series([0.0, 0.0, 0.0, 0.0])}
        )
        # f2 가 신호 가진 row 1 의 결합값은 f2 가 없을 때보다 큼
        assert result_with_f2.iloc[1] > result_without_f2.iloc[1]


class TestNoisyOrValidation:
    def test_empty_family_scores_rejected(self):
        with pytest.raises(ValueError, match="family_scores must not be empty"):
            compute_phase2_internal_noisy_or({})

    def test_non_series_family_rejected(self):
        with pytest.raises(TypeError, match="must be pandas Series"):
            compute_phase2_internal_noisy_or(
                {"f1": _series([0.1, 0.2]), "f2": [0.1, 0.2]}  # type: ignore[dict-item]
            )

    def test_index_mismatch_rejected(self):
        scores = {
            "f1": pd.Series([0.1, 0.2], index=[0, 1], dtype=float),
            "f2": pd.Series([0.3, 0.4], index=[2, 3], dtype=float),
        }
        with pytest.raises(ValueError, match="family index mismatch"):
            compute_phase2_internal_noisy_or(scores)


class TestNoisyOrAlreadyEcdf:
    def test_skip_ecdf_conversion_when_flagged(self):
        ecdf_input = _series([0.0, 0.5, 0.95, 1.0])
        result = compute_phase2_internal_noisy_or({"f1": ecdf_input}, already_ecdf=True)
        expected = np.clip(ecdf_input.to_numpy(), 0, 1 - 1e-12)
        np.testing.assert_allclose(result.to_numpy(), expected, rtol=1e-9)

    def test_already_ecdf_nan_is_zero_signal(self):
        ecdf_input = pd.Series([0.1, np.nan, 0.9], dtype=float)
        result = compute_phase2_internal_noisy_or({"f1": ecdf_input}, already_ecdf=True)
        np.testing.assert_allclose(result.to_numpy(), [0.1, 0.0, 0.9], rtol=1e-9)


class TestNoisyOrPhase1Phase2Integration:
    """PHASE1 ↔ PHASE2 Noisy-OR final RRF 결합 회귀 — 채택된 운영 식."""

    def test_final_rrf_with_noisy_or_voter(self):
        family_scores = {
            "unsupervised": _series([0.9, 0.5, 0.1]),
            "timeseries": _series([0.4, 0.4, 0.0]),
            "relational": _series([0.0, 0.0, 0.8]),
            "duplicate": _series([0.0, 0.6, 0.0]),
            "intercompany": _series([0.0, 0.0, 0.0]),
        }
        phase2_voter = compute_phase2_internal_noisy_or(family_scores)
        phase1_composite = _series([0.5, 0.7, 0.3])
        rrf = compute_rrf_score(
            {
                "phase1_composite": phase1_composite,
                "phase2_internal": phase2_voter,
            }
        )
        assert "rrf_score" in rrf.columns
        assert "rrf_rank" in rrf.columns
        assert set(rrf["rrf_rank"].to_numpy()) == {1, 2, 3}
