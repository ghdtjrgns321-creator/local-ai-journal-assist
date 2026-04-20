"""L4-01, L2-01, L1-04, L3-02 피처 기반 룰 단위 테스트."""

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
    """피처 엔진 출력을 모사한 DataFrame (6행)."""
    return pd.DataFrame({
        "debit_amount": [60e6, 40e6, 10e6, 80e6, 30e6, 55e6],
        "credit_amount": [0.0] * 6,
        "is_revenue_account": [True, True, False, True, False, True],
        "amount_zscore": [4.0, 2.0, 5.0, 3.5, 1.0, 0.5],
        "is_near_threshold": [False, True, False, False, True, False],
        "exceeds_threshold": [True, False, False, True, False, True],
        "is_manual_je": [True, False, False, True, True, False],
    })


# ── L4-01 매출 이상 변동 ────────────────────────────────────


class TestL4-01:
    def test_revenue_high_zscore_flagged(self, feature_df: pd.DataFrame) -> None:
        """매출 계정 + zscore > 3.0 → flagged."""
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        # 행0: revenue=True, zscore=4.0 → True
        # 행3: revenue=True, zscore=3.5 → True
        assert result[0]
        assert result[3]

    def test_revenue_low_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        """매출 계정이지만 zscore < 3.0 → not flagged."""
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[1]  # zscore=2.0
        assert not result[5]  # zscore=0.5

    def test_non_revenue_high_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        """비매출 계정은 zscore가 높아도 not flagged."""
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[2]  # revenue=False, zscore=5.0

    def test_missing_features_returns_all_false(self) -> None:
        """피처 미존재 시 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        result = b01_revenue_manipulation(df)
        assert not result.any()


# ── L2-01 승인한도 직하 ─────────────────────────────────────


class TestL2-01:
    def test_near_threshold_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert result[1]  # is_near_threshold=True
        assert result[4]

    def test_not_near_threshold(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert not result[0]

    def test_missing_feature(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b02_near_threshold(df).any()


# ── L1-04 승인한도 초과 ─────────────────────────────────────


class TestL1-04:
    def test_exceeds_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert result[0]
        assert result[3]
        assert result[5]

    def test_not_exceeds(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert not result[1]


# ── L3-02 수기 전표 ─────────────────────────────────────────


class TestL3-02:
    def test_manual_and_exceeds_flagged(self, feature_df: pd.DataFrame) -> None:
        """수기 + 한도 초과 → flagged."""
        result = b08_manual_override(feature_df)
        assert result[0]   # manual=True, exceeds=True
        assert result[3]   # manual=True, exceeds=True

    def test_manual_but_not_exceeds(self, feature_df: pd.DataFrame) -> None:
        """수기지만 한도 미초과 → not flagged."""
        result = b08_manual_override(feature_df)
        assert not result[4]  # manual=True, exceeds=False

    def test_exceeds_but_not_manual(self, feature_df: pd.DataFrame) -> None:
        """한도 초과지만 비수기 → not flagged."""
        result = b08_manual_override(feature_df)
        assert not result[5]  # manual=False, exceeds=True
