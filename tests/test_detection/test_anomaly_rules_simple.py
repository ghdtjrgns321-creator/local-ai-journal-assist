"""C01~C06, C08, C10 피처 기반 이상 징후 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_simple import (
    c01_period_end_large,
    c02_weekend_entry,
    c03_after_hours_entry,
    c04_backdated_entry,
    c05_fiscal_period_mismatch,
    c06_risky_description,
    c08_amount_outlier,
    c10_suspense_account,
)


@pytest.fixture
def anomaly_feature_df() -> pd.DataFrame:
    """Layer C 피처가 사전 포함된 테스트 DataFrame (8행)."""
    return pd.DataFrame({
        "debit_amount": [100e6, 50e6, 10e6, 80e6, 5e6, 200e6, 30e6, 60e6],
        "credit_amount": [0.0] * 8,
        "is_period_end": [True, False, True, False, True, True, False, False],
        "is_weekend": [True, False, False, True, False, False, True, False],
        "is_holiday": [False, False, True, False, False, False, False, False],
        "is_after_hours": [False, True, False, False, True, False, False, False],
        "days_backdated": [0, 45, -5, 31, 10, 0, -35, 29],
        "fiscal_period_mismatch": [False, False, True, False, False, True, False, False],
        "description_quality": ["normal", "missing", "poor", "normal", "normal", "missing", "normal", "poor"],
        "has_risk_keyword": ["low", "high", "low", "medium", "low", "low", "low", "high"],
        "amount_zscore": [1.0, 2.5, 0.5, 3.5, -4.0, 2.0, 0.3, 1.5],
    })


# ── C01 기말 대규모 ──────────────────────────────────────────


class TestC01:
    def test_period_end_high_amount_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말 + 금액 > Q3 → flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        # 행5: is_period_end=True, amount=200e6 (최고액) → True
        assert result[5]

    def test_period_end_low_amount_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말이지만 금액 ≤ Q3 → not flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        # 행2: is_period_end=True, amount=10e6 (하위) → False
        assert not result[2]

    def test_non_period_end_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """월말 아닌 행은 고액이어도 not flagged."""
        result = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        assert not result[3]  # is_period_end=False, amount=80e6

    def test_missing_feature_returns_false(self) -> None:
        """is_period_end 피처 미존재 시 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not c01_period_end_large(df).any()


# ── C02 주말 전기 ──────────────────────────────────────────


class TestC02:
    def test_weekend_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """토/일 → flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert result[0]  # is_weekend=True
        assert result[3]  # is_weekend=True

    def test_holiday_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """공휴일 → flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert result[2]  # is_holiday=True

    def test_weekday_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """평일 + 비공휴일 → not flagged."""
        result = c02_weekend_entry(anomaly_feature_df)
        assert not result[1]
        assert not result[7]


# ── C03 심야 전기 ──────────────────────────────────────────


class TestC03:
    def test_after_hours_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """업무시간 외 → flagged."""
        result = c03_after_hours_entry(anomaly_feature_df)
        assert result[1]
        assert result[4]

    def test_business_hours_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """업무시간 → not flagged."""
        result = c03_after_hours_entry(anomaly_feature_df)
        assert not result[0]

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c03_after_hours_entry(df).any()


# ── C04 소급 전기 ──────────────────────────────────────────


class TestC04:
    def test_backdated_over_threshold_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(days_backdated) > 30 → flagged."""
        result = c04_backdated_entry(anomaly_feature_df, threshold_days=30)
        assert result[1]  # 45일
        assert result[3]  # 31일
        assert result[6]  # -35일 (abs=35)

    def test_backdated_under_threshold_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(days_backdated) ≤ 30 → not flagged."""
        result = c04_backdated_entry(anomaly_feature_df, threshold_days=30)
        assert not result[0]  # 0일
        assert not result[7]  # 29일

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c04_backdated_entry(df).any()


# ── C05 기간 불일치 ────────────────────────────────────────


class TestC05:
    def test_mismatch_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert result[2]
        assert result[5]

    def test_match_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert not result[0]


# ── C06 위험 적요 ──────────────────────────────────────────


class TestC06:
    def test_missing_quality_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """description_quality=missing → flagged."""
        result = c06_risky_description(anomaly_feature_df)
        assert result[1]  # missing
        assert result[5]  # missing

    def test_poor_quality_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """description_quality=poor → flagged."""
        result = c06_risky_description(anomaly_feature_df)
        assert result[2]  # poor

    def test_high_risk_keyword_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """has_risk_keyword=high/medium → flagged."""
        result = c06_risky_description(anomaly_feature_df)
        assert result[3]  # medium
        assert result[7]  # high

    def test_normal_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """quality=normal + risk=low → not flagged."""
        result = c06_risky_description(anomaly_feature_df)
        assert not result[0]
        assert not result[4]


# ── C08 이상 고액 ──────────────────────────────────────────


class TestC08:
    def test_high_zscore_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(zscore) > 3.0 → flagged."""
        result = c08_amount_outlier(anomaly_feature_df, zscore_threshold=3.0)
        assert result[3]  # 3.5
        assert result[4]  # -4.0 (abs=4.0)

    def test_low_zscore_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        """abs(zscore) ≤ 3.0 → not flagged."""
        result = c08_amount_outlier(anomaly_feature_df, zscore_threshold=3.0)
        assert not result[0]  # 1.0
        assert not result[1]  # 2.5

    def test_missing_feature_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c08_amount_outlier(df).any()


# ── C10 가수금 장기체류 ──────────────────────────────────────


class TestC10:
    def test_suspense_flagged(self) -> None:
        """is_suspense_account=True → flagged."""
        df = pd.DataFrame({
            "debit_amount": [1e6, 2e6, 3e6],
            "credit_amount": [0.0, 0.0, 0.0],
            "is_suspense_account": [True, False, True],
        })
        result = c10_suspense_account(df)
        assert result[0]
        assert not result[1]
        assert result[2]

    def test_all_false_when_no_suspense(self) -> None:
        """가계정 없음 → 전체 False."""
        df = pd.DataFrame({
            "debit_amount": [1e6, 2e6],
            "credit_amount": [0.0, 0.0],
            "is_suspense_account": [False, False],
        })
        assert not c10_suspense_account(df).any()

    def test_nan_treated_as_false(self) -> None:
        """NaN → False (플래그 안 함)."""
        df = pd.DataFrame({
            "debit_amount": [1e6],
            "credit_amount": [0.0],
            "is_suspense_account": [None],
        })
        assert not c10_suspense_account(df).any()

    def test_missing_feature_returns_false(self) -> None:
        """is_suspense_account 컬럼 미존재 → 전체 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not c10_suspense_account(df).any()
