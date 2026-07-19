"""월별 변동성 + 분포 분석 + 계정별 통계 단위 테스트."""

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.validation.volatility import (
    analyze_accounts,
    analyze_distribution,
    analyze_monthly_volatility,
)


@pytest.fixture()
def settings() -> AuditSettings:
    return AuditSettings()


def _monthly_df(months: int = 12, base: float = 1_000_000.0, spike_month: int | None = None):
    """월별 데이터 생성. spike_month 지정 시 해당 월 5배."""
    dates, amounts, accounts = [], [], []
    for m in range(1, months + 1):
        n = 10
        for _ in range(n):
            dates.append(f"2024-{m:02d}-15")
            amt = base * 5 if m == spike_month else base
            amounts.append(amt)
            accounts.append(1110 if m % 2 == 0 else 2110)

    df = pd.DataFrame({
        "posting_date": pd.to_datetime(dates),
        "debit_amount": amounts,
        "credit_amount": [0.0] * len(amounts),
        "gl_account": pd.array(accounts, dtype="Int64"),
    })
    base_amount = df["debit_amount"].fillna(0)
    return df, base_amount


class TestMonthlyVolatility:

    def test_spike_month_detected(self, settings):
        """12월 5배 → outlier_months에 포함."""
        df, base = _monthly_df(12, spike_month=12)
        result, warnings = analyze_monthly_volatility(df, base, settings=settings)

        assert any("2024-12" in m for m in result.outlier_months)
        assert len(result.monthly_totals) == 12

    def test_uniform_no_outliers(self, settings):
        """모든 월 동일 → outlier_months 비어있음."""
        df, base = _monthly_df(12)
        result, warnings = analyze_monthly_volatility(df, base, settings=settings)

        assert result.outlier_months == []

    def test_single_month_warning(self, settings):
        """단일 월 → MoM 불가 경고."""
        df, base = _monthly_df(1)
        result, warnings = analyze_monthly_volatility(df, base, settings=settings)

        assert len(result.mom_change_rates) == 0
        assert any("2개월 미만" in w for w in warnings)

    def test_no_posting_date(self, settings):
        """posting_date 없음 → 빈 결과 + 경고."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        base = df["debit_amount"]
        result, warnings = analyze_monthly_volatility(df, base, settings=settings)

        assert result.monthly_totals == {}
        assert any("posting_date" in w for w in warnings)

    def test_seasonality_index(self, settings):
        """3개월+ → seasonality_index 생성."""
        df, base = _monthly_df(6)
        result, _ = analyze_monthly_volatility(df, base, settings=settings)

        assert result.seasonality_index is not None
        assert len(result.seasonality_index) > 0


class TestDistribution:

    def test_normal_distribution(self, settings):
        """정규분포 → is_normal=True."""
        rng = np.random.default_rng(42)
        amounts = pd.Series(rng.normal(100_000, 10_000, size=500))
        result, _ = analyze_distribution(amounts, settings=settings)

        assert result.is_normal is True
        assert result.shapiro_p_value is not None
        assert result.shapiro_p_value > 0.05

    def test_lognormal_right_skewed(self, settings):
        """로그정규 → is_normal=False, right_skewed."""
        rng = np.random.default_rng(42)
        amounts = pd.Series(rng.lognormal(10, 2, size=500))
        result, _ = analyze_distribution(amounts, settings=settings)

        assert result.is_normal is False
        assert result.skewness_label == "right_skewed"

    def test_small_sample_shapiro_skip(self, settings):
        """n < 20 → Shapiro 스킵, is_normal=None."""
        amounts = pd.Series([1.0, 2.0, 3.0])
        result, warnings = analyze_distribution(amounts, settings=settings)

        assert result.is_normal is None
        assert any("Shapiro-Wilk 스킵" in w for w in warnings)

    def test_empty_series(self, settings):
        """빈 시리즈 → 전부 None."""
        amounts = pd.Series([], dtype="float64")
        result, warnings = analyze_distribution(amounts, settings=settings)

        assert result.shapiro_statistic is None
        assert result.is_normal is None

    def test_large_sample_uses_sampling(self, settings):
        """n > 5000 → 샘플링 후 Shapiro (에러 없이 실행)."""
        rng = np.random.default_rng(42)
        amounts = pd.Series(rng.normal(100, 10, size=10_000))
        result, _ = analyze_distribution(amounts, settings=settings)

        assert result.shapiro_statistic is not None

    def test_outlier_concentration(self, settings):
        """이상치 집중도 계산."""
        amounts = pd.Series([10.0] * 100 + [10_000.0] * 5)
        result, _ = analyze_distribution(amounts, settings=settings)

        assert result.outlier_concentration is not None
        assert result.outlier_concentration > 0


class TestAccountStats:

    def test_concentrated_single_account(self, settings):
        """1계정에 90% 집중 → HHI > 0.25, concentrated."""
        df = pd.DataFrame({
            "gl_account": pd.array([1110] * 90 + [2110] * 10, dtype="Int64"),
        })
        base = pd.Series([100.0] * 90 + [10.0] * 10)
        result, _ = analyze_accounts(df, base, settings=settings)

        assert result.hhi >= 0.25
        assert result.hhi_label == "concentrated"

    def test_diversified_many_accounts(self, settings):
        """100계정 균등 → HHI 낮음, diversified."""
        accounts = [i for i in range(1000, 1100) for _ in range(10)]
        df = pd.DataFrame({
            "gl_account": pd.array(accounts, dtype="Int64"),
        })
        base = pd.Series([100.0] * 1000)
        result, _ = analyze_accounts(df, base, settings=settings)

        assert result.hhi < 0.15
        assert result.hhi_label == "diversified"

    def test_no_gl_account(self, settings):
        """gl_account 없음 → graceful degradation."""
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2024-01-01"])})
        base = pd.Series([100.0])
        result, warnings = analyze_accounts(df, base, settings=settings)

        assert result.account_count == 0
        assert any("gl_account" in w for w in warnings)

    def test_cv_zero_mean_defense(self, settings):
        """mean ≈ 0 계정 → CV = 0.0 (inf 방지)."""
        df = pd.DataFrame({
            "gl_account": pd.array([1110, 1110, 2110], dtype="Int64"),
        })
        # 1110: 금액 합이 0에 가까움 (상계)
        base = pd.Series([100.0, -99.99, 500.0])
        result, _ = analyze_accounts(df, base, settings=settings)

        # inf가 아님을 확인
        for cv in result.cv_by_account.values():
            assert np.isfinite(cv)

    def test_high_cv_accounts(self, settings):
        """CV > 1.0 계정 식별."""
        df = pd.DataFrame({
            "gl_account": pd.array([1110] * 10 + [2110] * 10, dtype="Int64"),
        })
        # 1110: 안정적, 2110: 변동 큼
        base = pd.Series(
            [100.0] * 10 + [10.0, 20.0, 30.0, 500.0, 1.0, 800.0, 5.0, 200.0, 3.0, 700.0]
        )
        result, _ = analyze_accounts(df, base, settings=settings)

        # 2110이 high_cv_accounts에 포함되어야 함
        assert "2110" in result.high_cv_accounts
