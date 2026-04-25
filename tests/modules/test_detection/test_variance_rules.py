"""D01, D02 룰 함수 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.variance_rules import (
    d01_account_activity_variance,
    d02_monthly_pattern_variance,
)

# ── 공용 fixture ───────────────────────────────────────────


@pytest.fixture
def base_df() -> pd.DataFrame:
    """12건 — 계정 1000(8건), 계정 2000(4건)."""
    return pd.DataFrame({
        "gl_account": ["1000"] * 8 + ["2000"] * 4,
        "debit_amount": [100.0] * 12,
        "credit_amount": [0.0] * 12,
        "fiscal_period": [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4],
    })


# ── D01: 계정과목별 집계 급변 ──────────────────────────────


class TestD01AccountActivityVariance:
    """D01 룰 함수 — 변동률 기반 플래그."""

    def test_high_variance_flagged(self, base_df: pd.DataFrame):
        """변동률 50% 초과 → 해당 계정 행 전체 True."""
        # 전기: 1000 계정 총액 200, 당기: 800 → 변동률 3.0
        prior = {"1000": {"total_amount": 200.0, "count": 2, "avg_amount": 100.0}}
        result = d01_account_activity_variance(base_df, prior, variance_threshold=0.5)

        # 1000 계정 8건 모두 플래그
        assert result[base_df["gl_account"] == "1000"].all()

    def test_low_variance_not_flagged(self, base_df: pd.DataFrame):
        """변동률 50% 이하 → 미플래그."""
        # 전기와 당기가 거의 동일
        prior = {
            "1000": {"total_amount": 800.0, "count": 8, "avg_amount": 100.0},
            "2000": {"total_amount": 400.0, "count": 4, "avg_amount": 100.0},
        }
        result = d01_account_activity_variance(base_df, prior, variance_threshold=0.5)
        assert not result.any()

    def test_new_account_auto_flagged(self, base_df: pd.DataFrame):
        """전기에 없던 계정 → 자동 플래그."""
        # 전기에 1000만 있고, 2000은 신규
        prior = {"1000": {"total_amount": 800.0, "count": 8, "avg_amount": 100.0}}
        result = d01_account_activity_variance(base_df, prior, variance_threshold=0.5)

        # 2000 계정 4건만 플래그
        assert result[base_df["gl_account"] == "2000"].all()
        assert not result[base_df["gl_account"] == "1000"].any()

    def test_identical_data_not_flagged(self, base_df: pd.DataFrame):
        """전기 == 당기 → 변동률 0 → 미플래그."""
        prior = {
            "1000": {"total_amount": 800.0, "count": 8, "avg_amount": 100.0},
            "2000": {"total_amount": 400.0, "count": 4, "avg_amount": 100.0},
        }
        result = d01_account_activity_variance(base_df, prior, variance_threshold=0.5)
        assert not result.any()

    def test_missing_gl_account_column(self):
        """gl_account 컬럼 없으면 전체 False."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        prior = {"1000": {"total_amount": 100.0, "count": 1, "avg_amount": 100.0}}
        result = d01_account_activity_variance(df, prior)
        assert not result.any()

    def test_empty_prior_returns_false(self, base_df: pd.DataFrame):
        """prior_aggregates가 빈 dict → 전체 False."""
        result = d01_account_activity_variance(base_df, {})
        assert not result.any()

    def test_prior_zero_values_no_division_error(self):
        """전기 값이 0이어도 epsilon으로 division-by-zero 방지."""
        df = pd.DataFrame({
            "gl_account": ["1000"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        })
        prior = {"1000": {"total_amount": 0.0, "count": 0, "avg_amount": 0.0}}
        # 에러 없이 실행되어야 함
        result = d01_account_activity_variance(df, prior, variance_threshold=0.5)
        assert isinstance(result, pd.Series)


# ── D02: 월별 분포 패턴 변화 ──────────────────────────────


class TestD02MonthlyPatternVariance:
    """D02 룰 함수 — JSD 기반 분포 비교."""

    def test_concentrated_pattern_flagged(self, base_df: pd.DataFrame):
        """12월 집중 패턴 → JSD > 0.3 → 플래그."""
        # 전기: 균등 분포
        prior = {"1000": {m: 1 / 12 for m in range(1, 13)}}

        # 당기: 12월에 금액 집중
        df = pd.DataFrame({
            "gl_account": ["1000"] * 12,
            "debit_amount": [10.0] * 11 + [500.0],
            "credit_amount": [0.0] * 12,
            "fiscal_period": list(range(1, 13)),
        })
        result = d02_monthly_pattern_variance(df, prior, jsd_threshold=0.3)
        assert result.all()

    def test_identical_distribution_not_flagged(self, base_df: pd.DataFrame):
        """동일 분포 → JSD ≈ 0 → 미플래그."""
        # 전기: 1~8월 균등
        prior = {"1000": {m: 1 / 8 for m in range(1, 9)}}
        result = d02_monthly_pattern_variance(base_df, prior, jsd_threshold=0.3)
        assert not result[base_df["gl_account"] == "1000"].any()

    def test_less_than_3_months_skipped(self):
        """당기 데이터 2개월만 → 비교 불가 → 미플래그."""
        df = pd.DataFrame({
            "gl_account": ["1000", "1000"],
            "debit_amount": [100.0, 100.0],
            "credit_amount": [0.0, 0.0],
            "fiscal_period": [1, 2],
        })
        prior = {"1000": {m: 1 / 12 for m in range(1, 13)}}
        result = d02_monthly_pattern_variance(df, prior, jsd_threshold=0.3)
        assert not result.any()

    def test_prior_less_than_3_months_skipped(self):
        """전기 데이터 2개월만 → 비교 불가 → 미플래그."""
        df = pd.DataFrame({
            "gl_account": ["1000"] * 6,
            "debit_amount": [100.0] * 6,
            "credit_amount": [0.0] * 6,
            "fiscal_period": [1, 2, 3, 4, 5, 6],
        })
        prior = {"1000": {1: 0.5, 2: 0.5}}  # 2개월만
        result = d02_monthly_pattern_variance(df, prior, jsd_threshold=0.3)
        assert not result.any()

    def test_min_months_parameter_allows_stricter_skip(self):
        """min_months 인자를 높이면 3개월 데이터도 비교하지 않는다."""
        df = pd.DataFrame({
            "gl_account": ["1000"] * 3,
            "debit_amount": [10.0, 10.0, 500.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "fiscal_period": [1, 2, 3],
        })
        prior = {"1000": {m: 1 / 12 for m in range(1, 13)}}

        result = d02_monthly_pattern_variance(
            df,
            prior,
            jsd_threshold=0.3,
            min_months=4,
        )

        assert not result.any()

    def test_missing_fiscal_period_column(self):
        """fiscal_period 없으면 전체 False."""
        df = pd.DataFrame({
            "gl_account": ["1000"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        })
        prior = {"1000": {m: 1 / 12 for m in range(1, 13)}}
        result = d02_monthly_pattern_variance(df, prior)
        assert not result.any()

    def test_empty_prior_returns_false(self, base_df: pd.DataFrame):
        """prior_patterns가 빈 dict → 전체 False."""
        result = d02_monthly_pattern_variance(base_df, {})
        assert not result.any()

    def test_account_not_in_prior_skipped(self, base_df: pd.DataFrame):
        """전기에 해당 계정 없으면 스킵 (미플래그)."""
        prior = {"9999": {m: 1 / 12 for m in range(1, 13)}}
        result = d02_monthly_pattern_variance(base_df, prior, jsd_threshold=0.3)
        assert not result.any()
