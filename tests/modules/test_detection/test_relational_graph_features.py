"""Relational graph/entity helper 단위 테스트.

src.detection.relational_graph_features 의 build_pair_key /
compute_pair_rarity_score / compute_first_seen_recency_mask /
compute_user_period_degree_zscore / compute_partner_inactivity_reactivation
graceful·small-sample·high-cardinality 동작 검증.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.detection.relational_graph_features import (
    build_pair_key,
    compute_first_seen_recency_mask,
    compute_first_seen_recency_strength,
    compute_pair_rarity_score,
    compute_partner_inactivity_reactivation,
    compute_user_period_degree_zscore,
)

# ── build_pair_key ─────────────────────────────────────────────


class TestBuildPairKey:
    def test_missing_column_returns_nan_series(self):
        df = pd.DataFrame({"a": [1, 2]})
        key = build_pair_key(df, "a", "b")
        assert key.isna().all()
        assert key.index.equals(df.index)

    def test_blank_or_nan_rows_excluded(self):
        df = pd.DataFrame(
            {
                "a": ["x", "", None, "y"],
                "b": ["1", "2", "3", ""],
            }
        )
        key = build_pair_key(df, "a", "b")
        # Why: 한쪽이라도 비면 NaN
        assert key.notna().tolist() == [True, False, False, False]
        assert key.iloc[0] == "x||1"

    def test_strip_whitespace(self):
        df = pd.DataFrame({"a": ["  x  "], "b": ["  1  "]})
        key = build_pair_key(df, "a", "b")
        assert key.iloc[0] == "x||1"


# ── compute_pair_rarity_score ──────────────────────────────────


class TestPairRarity:
    def test_below_min_pair_population_returns_zero(self):
        # unique pairs = 3, min_pair_population = 50 → 전부 0
        key = pd.Series(["a||1", "a||1", "b||2", "c||3"])
        score = compute_pair_rarity_score(key, min_pair_population=50, min_freq=2)
        assert (score == 0.0).all()

    def test_rare_pair_gets_high_score(self):
        # 146개 valid row: 95 common (freq=95) + 1 rare + 50 unique (freq=1 각).
        keys = ["common||x"] * 95 + ["rare||y"] + [f"other_{i}||z" for i in range(50)]
        key = pd.Series(keys)
        score = compute_pair_rarity_score(key, min_pair_population=50, min_freq=2)
        # Why: 1-ECDF(freq) 로 연속화. freq=1 행 51개 → rank_pct ≈ 26/146 ≈ 0.178
        #      → rarity_ecdf ≈ 0.822. common freq=95 행은 mask (freq>min_freq) 로 0.
        rare_idx = keys.index("rare||y")
        assert score.iloc[rare_idx] > 0.7  # rare-tier 행은 상위 ECDF
        assert score.iloc[0] == 0.0  # common 은 rare-tier mask 미통과

    def test_high_freq_pair_below_min_freq_threshold_zero(self):
        # freq > min_freq → 0
        keys = ["a||1"] * 60 + [f"u_{i}||v_{i}" for i in range(50)]
        key = pd.Series(keys)
        score = compute_pair_rarity_score(key, min_pair_population=50, min_freq=2)
        assert score.iloc[0] == 0.0  # a||1 freq=60

    def test_nan_keys_handled(self):
        keys = ["a||1", None, "a||1", "b||2"] + [f"x_{i}||y_{i}" for i in range(50)]
        key = pd.Series(keys, dtype=object)
        score = compute_pair_rarity_score(key, min_pair_population=50, min_freq=2)
        # NaN key 행은 0
        assert score.iloc[1] == 0.0


# ── compute_first_seen_recency_mask ────────────────────────────


def _dates(values: list) -> pd.Series:
    return pd.Series(pd.to_datetime(values))


class TestFirstSeenRecency:
    def test_first_occurrences_flagged(self):
        key = pd.Series(["a||1", "a||1", "b||2", "b||2"])
        dates = _dates(["2024-01-01", "2024-06-15", "2024-01-05", "2024-12-31"])
        mask = compute_first_seen_recency_mask(key, dates, lookback_days=30)
        # a||1: first=Jan1, days 0/166 → True, False
        # b||2: first=Jan5, days 0/361 → True, False
        assert mask.tolist() == [True, False, True, False]

    def test_zero_lookback_returns_all_false(self):
        key = pd.Series(["a||1"])
        dates = _dates(["2024-01-01"])
        mask = compute_first_seen_recency_mask(key, dates, lookback_days=0)
        assert not mask.any()

    def test_nan_date_excluded(self):
        key = pd.Series(["a||1", "a||1"])
        dates = _dates(["2024-01-01", None])
        mask = compute_first_seen_recency_mask(key, dates, lookback_days=30)
        assert mask.tolist() == [True, False]


# ── compute_first_seen_recency_strength ────────────────────────


class TestFirstSeenRecencyStrength:
    def test_linear_decay_from_first_seen(self):
        # a||1: first=Jan1, days 0/15/30 → strength 1.0 / 0.5 / 0.0
        key = pd.Series(["a||1", "a||1", "a||1"])
        dates = _dates(["2024-01-01", "2024-01-16", "2024-01-31"])
        strength = compute_first_seen_recency_strength(key, dates, lookback_days=30)
        # Why: 선형 감쇠 — days_since_first / lookback_days 비율
        assert strength.iloc[0] == 1.0
        assert 0.4 <= strength.iloc[1] <= 0.6
        assert strength.iloc[2] == 0.0

    def test_beyond_lookback_clips_to_zero(self):
        key = pd.Series(["a||1", "a||1"])
        dates = _dates(["2024-01-01", "2024-06-01"])
        strength = compute_first_seen_recency_strength(key, dates, lookback_days=30)
        # 152일 경과 → 0.0 clip
        assert strength.iloc[1] == 0.0

    def test_zero_lookback_returns_all_zero(self):
        key = pd.Series(["a||1"])
        dates = _dates(["2024-01-01"])
        strength = compute_first_seen_recency_strength(key, dates, lookback_days=0)
        assert (strength == 0.0).all()

    def test_nan_excluded(self):
        key = pd.Series(["a||1", None, "a||1"], dtype=object)
        dates = _dates(["2024-01-01", "2024-01-10", None])
        strength = compute_first_seen_recency_strength(key, dates, lookback_days=30)
        # NaN key / NaN date 행은 0.0
        assert strength.iloc[1] == 0.0
        assert strength.iloc[2] == 0.0


# ── compute_user_period_degree_zscore ──────────────────────────


def _build_user_period_df(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """(user, account, date) tuple list → df."""
    return pd.DataFrame(
        rows,
        columns=["created_by", "gl_account", "posting_date"],
    )


class TestUserPeriodDegreeZscore:
    def test_missing_columns_returns_zero(self):
        df = pd.DataFrame({"only_col": [1, 2, 3]})
        z = compute_user_period_degree_zscore(
            df,
            user_col="created_by",
            target_col="gl_account",
            date_col="posting_date",
            period="M",
            min_user_obs=3,
            min_users=10,
        )
        assert (z == 0.0).all()

    def test_below_min_users_returns_zero(self):
        # 5 users < min_users=10
        rows = [(f"u{i}", "acc1", "2024-01-15") for i in range(5)]
        df = _build_user_period_df(rows)
        z = compute_user_period_degree_zscore(
            df,
            user_col="created_by",
            target_col="gl_account",
            date_col="posting_date",
            period="M",
            min_user_obs=3,
            min_users=10,
        )
        assert (z == 0.0).all()

    def test_below_min_user_obs_returns_zero(self):
        # 15 users, 각 user 1 period 관측 → min_user_obs=3 미만
        rows = [(f"u{i}", "acc1", "2024-01-15") for i in range(15)]
        df = _build_user_period_df(rows)
        z = compute_user_period_degree_zscore(
            df,
            user_col="created_by",
            target_col="gl_account",
            date_col="posting_date",
            period="M",
            min_user_obs=3,
            min_users=10,
        )
        assert (z == 0.0).all()

    def test_spike_user_gets_positive_z(self):
        # 12 users, 각 5개월 평소 degree=2, 1 user는 spike month에 degree=20
        rows: list[tuple[str, str, str]] = []
        months = ["2024-01-15", "2024-02-15", "2024-03-15", "2024-04-15", "2024-05-15"]
        for i in range(12):
            for m in months:
                rows.append((f"u{i}", "acc_a", m))
                rows.append((f"u{i}", "acc_b", m))
        # spike user u0 — 2024-06 에 20개 unique account
        for j in range(20):
            rows.append(("u0", f"acc_spike_{j}", "2024-06-15"))
        df = _build_user_period_df(rows)
        z = compute_user_period_degree_zscore(
            df,
            user_col="created_by",
            target_col="gl_account",
            date_col="posting_date",
            period="M",
            min_user_obs=3,
            min_users=10,
        )
        # spike 행에 양의 z
        spike_mask = (df["created_by"] == "u0") & (df["posting_date"] == "2024-06-15")
        assert z[spike_mask].max() > 2.0
        # 정상 user 행은 z ~ 0
        normal_mask = df["created_by"] == "u1"
        assert (z[normal_mask].abs() <= 1.0).all()


# ── compute_partner_inactivity_reactivation ────────────────────


class TestPartnerInactivity:
    def test_missing_columns_returns_zero(self):
        df = pd.DataFrame({"x": [1]})
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=0.0,
        )
        assert (scores == 0.0).all()

    def test_blank_partner_excluded(self):
        # blank partner만 있는 경우 → 0
        df = pd.DataFrame(
            {
                "trading_partner": ["", "  ", None],
                "posting_date": ["2024-01-01", "2024-08-01", "2024-09-01"],
            }
        )
        df["posting_date"] = pd.to_datetime(df["posting_date"])
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=0.0,
        )
        assert (scores == 0.0).all()

    def test_reactivation_window_propagates_score(self):
        # P1: 2023-01-01, 그 후 200일 휴면, 재활성 2023-08-01
        # window 7일 내 2건이 더 있음
        df = pd.DataFrame(
            {
                "trading_partner": ["P1", "P1", "P1", "P2"],
                "posting_date": [
                    "2023-01-01",
                    "2023-08-01",
                    "2023-08-05",
                    "2023-08-01",
                ],
                "debit_amount": [1000, 1000, 1000, 1000],
                "credit_amount": [0, 0, 0, 0],
            }
        )
        df["posting_date"] = pd.to_datetime(df["posting_date"])
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=0.0,
        )
        # P1 재활성 2건 (8-01, 8-05) 점수 부여
        assert scores.iloc[1] > 0
        assert scores.iloc[2] > 0
        # 첫 거래 + P2는 0
        assert scores.iloc[0] == 0.0
        assert scores.iloc[3] == 0.0

    def test_min_amount_filter_skips_small_reactivation(self):
        df = pd.DataFrame(
            {
                "trading_partner": ["P1", "P1"],
                "posting_date": ["2023-01-01", "2023-08-01"],
                "debit_amount": [100, 100],  # 둘 다 100원
                "credit_amount": [0, 0],
            }
        )
        df["posting_date"] = pd.to_datetime(df["posting_date"])
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=1_000_000.0,
        )
        # 재활성 window 내 최대 금액(100) < 1M → 0
        assert (scores == 0.0).all()

    def test_long_dormancy_higher_score(self):
        # gap이 inactive_days*3 이상이면 score=1.0
        df = pd.DataFrame(
            {
                "trading_partner": ["P1", "P1"],
                "posting_date": ["2022-01-01", "2024-01-01"],  # ~730일 gap
                "debit_amount": [1000, 1000],
                "credit_amount": [0, 0],
            }
        )
        df["posting_date"] = pd.to_datetime(df["posting_date"])
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=0.0,
        )
        # gap=730, inactive_days*3=540 → score = min(730/540, 1.0) = 1.0
        assert scores.iloc[1] == 1.0


# ── High-cardinality 성능 sanity ────────────────────────────────


class TestPerformance:
    def test_high_cardinality_partner_completes(self):
        # 10k 고유 partner, 50k 행
        rng = np.random.default_rng(0)
        n = 50_000
        partners = [f"P{i}" for i in rng.integers(0, 10_000, size=n)]
        dates = pd.date_range("2023-01-01", periods=n, freq="h")
        df = pd.DataFrame(
            {
                "trading_partner": partners,
                "posting_date": dates,
                "debit_amount": rng.integers(1, 1_000_000, size=n),
                "credit_amount": 0,
            }
        )
        scores = compute_partner_inactivity_reactivation(
            df,
            partner_col="trading_partner",
            date_col="posting_date",
            inactive_days=180,
            reactivation_window_days=7,
            min_amount=0.0,
        )
        # 출력 길이만 검증 (성능 회귀 가드는 pytest-timeout 별도)
        assert len(scores) == n
        assert scores.between(0.0, 1.0).all()
