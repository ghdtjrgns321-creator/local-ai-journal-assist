"""Unit tests for feature-based fraud rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.fraud_rules_feature import (
    b01_revenue_manipulation,
    b02_near_threshold,
    b03_exceeds_threshold,
    b08_manual_override,
)


@pytest.fixture
def feature_df() -> pd.DataFrame:
    return pd.DataFrame({
        "debit_amount": [60e6, 40e6, 10e6, 80e6, 30e6, 55e6],
        "credit_amount": [0.0] * 6,
        "is_revenue_account": [True, True, False, True, False, True],
        "amount_zscore": [4.0, 2.0, 5.0, 3.5, 1.0, 0.5],
        "is_near_threshold": [False, True, False, False, True, False],
        "exceeds_threshold": [True, False, False, True, False, True],
        "is_manual_je": [True, False, False, True, True, False],
    })


class TestL4_01:
    def test_revenue_high_zscore_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert result[0]
        assert result[3]

    def test_revenue_low_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[1]
        assert not result[5]

    def test_non_revenue_high_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[2]

    def test_missing_features_returns_all_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        result = b01_revenue_manipulation(df)
        assert not result.any()


class TestL2_01:
    def test_near_threshold_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert result[1]
        assert result[4]

    def test_not_near_threshold(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert not result[0]

    def test_missing_feature(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b02_near_threshold(df).any()


class TestL1_04:
    def test_exceeds_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert result[0]
        assert result[3]
        assert result[5]

    def test_not_exceeds(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert not result[1]


class TestL3_02:
    def test_manual_entry_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b08_manual_override(feature_df)
        assert result[0]
        assert result[3]
        assert result[4]

    def test_non_manual_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b08_manual_override(feature_df)
        assert not result[1]
        assert not result[2]
        assert not result[5]

    def test_source_fallback_uses_manual_source_codes(self) -> None:
        df = pd.DataFrame({"source": ["Manual", "Adjustment", "automated", None]})
        assert b08_manual_override(df).tolist() == [True, True, False, False]
