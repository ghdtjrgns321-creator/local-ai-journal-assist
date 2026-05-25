"""PHASE2 family diagnostics 3 metric 회귀 테스트.

V7 fixed3 실측값(artifacts/phase2_family_correlation_matrix_20260519.json)과
edge case 모두 검증한다. fitting 가드: 본 metric 은 truth label 미사용.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.services.phase2_family_diagnostics import (
    METADATA_KEY,
    FamilyDiagnostics,
    attach_family_diagnostics_to_metadata,
    classify_all_family_roles,
    classify_family_role,
    compute_all_family_diagnostics,
    compute_family_diagnostics,
    compute_rank_resolution,
    compute_row_nonzero_rate,
    compute_top_tail_resolution,
    diagnostics_from_payload,
    read_family_diagnostics_from_metadata,
    serialize_diagnostics,
)


def _make_series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


class TestRowNonzeroRate:
    def test_all_zero(self):
        rate, count = compute_row_nonzero_rate(_make_series([0.0] * 100))
        assert rate == 0.0
        assert count == 0

    def test_all_positive(self):
        rate, count = compute_row_nonzero_rate(_make_series([0.5] * 100))
        assert rate == 1.0
        assert count == 100

    def test_half_positive(self):
        rate, count = compute_row_nonzero_rate(_make_series([0.0, 0.5] * 50))
        assert rate == 0.5
        assert count == 50

    def test_nan_treated_as_zero(self):
        rate, count = compute_row_nonzero_rate(pd.Series([0.0, np.nan, 0.5, 0.3], dtype=float))
        assert rate == 0.5
        assert count == 2

    def test_empty(self):
        rate, count = compute_row_nonzero_rate(_make_series([]))
        assert rate == 0.0
        assert count == 0


class TestRankResolution:
    def test_all_distinct(self):
        # 100 distinct values → rank_resolution = 1.0
        assert compute_rank_resolution(_make_series(list(np.linspace(0, 1, 100)))) == 1.0

    def test_two_value_discrete(self):
        # 50% 0.4 + 50% 0.8 → 2 unique ranks / 100 = 0.02
        scores = _make_series([0.4] * 50 + [0.8] * 50)
        assert compute_rank_resolution(scores) == pytest.approx(0.02)

    def test_v7_timeseries_pattern(self):
        # V7 fixed3 timeseries 유사: 13% zero + 60% 0.4 + 27% 0.8 → 3 unique ranks
        scores = _make_series([0.0] * 130 + [0.4] * 600 + [0.8] * 270)
        assert compute_rank_resolution(scores) == pytest.approx(0.003)

    def test_empty(self):
        assert compute_rank_resolution(_make_series([])) == 0.0


class TestTopTailResolution:
    def test_all_distinct_tail(self):
        # 100 distinct, q95 tail = top 5% (5 values) all distinct → resolution = 0.8
        # (largest tie block = 1 / tail_count = 5 → 1 - 1/5 = 0.8)
        scores = _make_series(list(np.linspace(0, 1, 100)))
        result = compute_top_tail_resolution(scores, q=0.95)
        assert result == pytest.approx(0.8, abs=0.05)

    def test_tail_completely_tied(self):
        # tail이 한 값으로만 묶임 → 1 - tail_count/tail_count = 0.0
        scores = _make_series([0.1] * 950 + [0.9] * 50)
        result = compute_top_tail_resolution(scores, q=0.95)
        assert result == 0.0

    def test_sparse_family_zero_threshold(self):
        # 99% zero + 1% positive → q95 threshold = 0, positive tail로 fallback
        scores = _make_series([0.0] * 990 + [0.3, 0.5, 0.7, 0.9, 0.1] * 2)
        result = compute_top_tail_resolution(scores, q=0.95)
        assert result > 0.5  # positive tail은 분해능 있음

    def test_all_zero_returns_zero(self):
        assert compute_top_tail_resolution(_make_series([0.0] * 100)) == 0.0

    def test_empty(self):
        assert compute_top_tail_resolution(_make_series([])) == 0.0


class TestFamilyDiagnostics:
    def test_dataclass_to_dict(self):
        diag = FamilyDiagnostics(
            row_nonzero_rate=0.5,
            rank_resolution=0.1,
            top_tail_resolution=0.8,
            row_count=1000,
            nonzero_count=500,
        )
        payload = diag.to_dict()
        assert payload["row_nonzero_rate"] == 0.5
        assert payload["row_count"] == 1000

    def test_compute_family_diagnostics_pipeline(self):
        scores = _make_series([0.0] * 950 + list(np.linspace(0.1, 1.0, 50)))
        diag = compute_family_diagnostics(scores)
        assert 0.0 < diag.row_nonzero_rate < 0.1
        assert diag.row_count == 1000
        assert diag.nonzero_count == 50
        assert diag.top_tail_resolution > 0.0

    def test_compute_all(self):
        scores_map = {
            "f1": _make_series(list(np.linspace(0, 1, 100))),
            "f2": _make_series([0.4] * 100),
        }
        result = compute_all_family_diagnostics(scores_map)
        assert set(result.keys()) == {"f1", "f2"}
        assert result["f2"].rank_resolution == pytest.approx(0.01)


class TestClassifyFamilyRole:
    def test_near_dormant_when_no_hits(self):
        diag = FamilyDiagnostics(0.0001, 0.5, 0.8, 1000, 0)
        assert classify_family_role(diag) == "near-dormant"

    def test_active_ranker_when_continuous(self):
        # V7 fixed3 unsupervised 유사
        diag = FamilyDiagnostics(0.9999, 0.5, 0.9, 1000000, 999999)
        assert classify_family_role(diag) == "active-ranker"

    def test_coarse_booster_on_low_rank_resolution(self):
        # V7 fixed3 timeseries 유사
        diag = FamilyDiagnostics(0.87, 0.003, 0.3, 1000000, 870000)
        assert classify_family_role(diag) == "coarse-booster"

    def test_coarse_booster_on_low_top_tail(self):
        diag = FamilyDiagnostics(0.5, 0.8, 0.3, 1000, 500)
        assert classify_family_role(diag) == "coarse-booster"

    def test_tail_only_fallback_on_very_low_top_tail(self):
        diag = FamilyDiagnostics(0.5, 0.8, 0.1, 1000, 500)
        assert classify_family_role(diag) == "tail-only-fallback"

    def test_classify_all(self):
        diags = {
            "unsup": FamilyDiagnostics(0.9999, 0.5, 0.9, 1000000, 999999),
            "timeseries": FamilyDiagnostics(0.87, 0.003, 0.3, 1000000, 870000),
            "ic": FamilyDiagnostics(0.0001, 0.5, 0.0, 1000000, 100),
        }
        roles = classify_all_family_roles(diags)
        assert roles == {
            "unsup": "active-ranker",
            "timeseries": "coarse-booster",
            "ic": "near-dormant",
        }


class TestSerialization:
    def test_round_trip(self):
        original = {
            "f1": FamilyDiagnostics(0.5, 0.1, 0.8, 1000, 500),
            "f2": FamilyDiagnostics(0.001, 0.5, 0.0, 1000, 1),
        }
        payload = serialize_diagnostics(original)
        restored = diagnostics_from_payload(payload)
        assert restored == original


class TestV7Fixed3IntegrationPattern:
    """V7 fixed3 실측 분포 패턴(artifacts/phase2_family_correlation_matrix_20260519.json) 정합."""

    def test_unsupervised_classified_as_active_ranker(self):
        # row_nonzero=99.9999%, q95=0.9712 → continuous distribution
        scores = pd.Series(
            np.concatenate([np.linspace(0.01, 0.5, 500000), np.linspace(0.5, 0.99, 500000)]),
            dtype=float,
        )
        diag = compute_family_diagnostics(scores)
        assert classify_family_role(diag) == "active-ranker"

    def test_timeseries_classified_as_coarse_booster(self):
        # 13% zero + 60% 0.4 + 27% 0.8 (이산값)
        scores = _make_series([0.0] * 13000 + [0.4] * 60000 + [0.8] * 27000)
        diag = compute_family_diagnostics(scores)
        role = classify_family_role(diag)
        assert role in {"coarse-booster", "tail-only-fallback"}

    def test_intercompany_classified_as_near_dormant(self):
        # row_nonzero=0.003% (34/1,032,864)
        scores = _make_series([0.0] * 999966 + [0.5] * 34)
        diag = compute_family_diagnostics(scores)
        assert classify_family_role(diag) == "near-dormant"


class TestTrainingReportIntegration:
    """training_report.metadata 에 family_diagnostics 를 pin / read back."""

    def test_attach_writes_payload_into_metadata(self):
        metadata: dict[str, object] = {}
        family_scores = {
            "unsup": _make_series(list(np.linspace(0.01, 0.99, 1000))),
            "ts": _make_series([0.0] * 500 + [0.4] * 300 + [0.8] * 200),
            "ic": _make_series([0.0] * 999 + [0.5]),
        }
        payload = attach_family_diagnostics_to_metadata(metadata, family_scores)
        assert METADATA_KEY in metadata
        pinned = metadata[METADATA_KEY]
        assert isinstance(pinned, dict)
        assert pinned["schema_version"] == 1
        assert pinned["q"] == 0.95
        assert set(pinned["diagnostics"].keys()) == {"unsup", "ts", "ic"}
        assert set(pinned["roles"].keys()) == {"unsup", "ts", "ic"}
        assert payload == pinned["diagnostics"]

    def test_read_back_returns_dataclass_and_roles(self):
        metadata: dict[str, object] = {}
        # near-dormant 분류를 분명히 트리거하려면 row_nonzero_rate < 0.001 필요
        family_scores = {
            "unsup": _make_series(list(np.linspace(0.01, 0.99, 10000))),
            "ic": _make_series([0.0] * 9999 + [0.5]),  # rate = 0.0001 < 0.001
        }
        attach_family_diagnostics_to_metadata(metadata, family_scores)
        result = read_family_diagnostics_from_metadata(metadata)
        assert result is not None
        diagnostics, roles = result
        assert set(diagnostics.keys()) == {"unsup", "ic"}
        assert isinstance(diagnostics["unsup"], FamilyDiagnostics)
        assert roles["ic"] == "near-dormant"

    def test_read_back_returns_none_when_unpinned(self):
        assert read_family_diagnostics_from_metadata({}) is None
        assert read_family_diagnostics_from_metadata({METADATA_KEY: "not-a-dict"}) is None
        assert (
            read_family_diagnostics_from_metadata({METADATA_KEY: {}}) is not None
        )  # 빈 dict 는 (빈 dict, 빈 dict) 반환

    def test_read_back_filters_invalid_roles(self):
        metadata = {
            METADATA_KEY: {
                "schema_version": 1,
                "q": 0.95,
                "diagnostics": {
                    "f1": {
                        "row_nonzero_rate": 0.5,
                        "rank_resolution": 0.5,
                        "top_tail_resolution": 0.8,
                        "row_count": 1000,
                        "nonzero_count": 500,
                    },
                },
                "roles": {"f1": "bogus-role"},
            }
        }
        result = read_family_diagnostics_from_metadata(metadata)
        assert result is not None
        _, roles = result
        assert "f1" not in roles  # invalid role 은 필터링
