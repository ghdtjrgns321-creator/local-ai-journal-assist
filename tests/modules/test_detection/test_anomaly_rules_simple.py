"""L3-04~L3-08, L4-03, L3-09 피처 기반 이상 징후 룰 단위 테스트."""

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
    """L3/L4 피처가 사전 포함된 테스트 DataFrame (8행)."""
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


# ── L3-04 기말 대규모 ──────────────────────────────────────────


class TestL3-04:
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

    def test_grouped_q3_per_account_group(self) -> None:
        """account_group별 Q3 적용 — 그룹 내 상대적 고액만 플래그."""
        # Why: expense [10, 20, 30, 100] → Q3=47.5, revenue [1000, 2000, 3000, 10000] → Q3=4750
        df = pd.DataFrame({
            "debit_amount":  [10, 20, 30, 100, 1000, 2000, 3000, 10000],
            "credit_amount": [0] * 8,
            "is_period_end": [True] * 8,
            "account_group": ["expense"] * 4 + ["revenue"] * 4,
        })
        result = c01_period_end_large(df, quantile=0.75, min_group_size=3)
        # expense: 100 > Q3(47.5) → True
        assert result[3]
        # expense: 10, 20, 30 ≤ Q3 → False
        assert not result[0] and not result[1] and not result[2]
        # revenue: 10000 > Q3(4750) → True
        assert result[7]
        # revenue: 1000, 2000, 3000 ≤ Q3 → False
        assert not result[4] and not result[5]

    def test_small_group_fallback_to_global(self) -> None:
        """n < min_group_size인 그룹은 전체 Q3로 fallback."""
        df = pd.DataFrame({
            "debit_amount":  [10, 20, 80, 90, 9000],
            "credit_amount": [0] * 5,
            "is_period_end": [True] * 5,
            # Why: 'rare' 그룹은 1건뿐 → 전체 Q3 fallback
            "account_group": ["expense"] * 4 + ["rare"],
        })
        result = c01_period_end_large(df, quantile=0.75, min_group_size=3)
        # rare(idx=4): 9000 > 전체 Q3(≈86.25) → True
        assert result[4]

    def test_no_account_group_uses_global(self, anomaly_feature_df: pd.DataFrame) -> None:
        """account_group 미존재 시 기존 전체 Q3 동작과 동일."""
        result_with_param = c01_period_end_large(anomaly_feature_df, quantile=0.75, min_group_size=30)
        result_without = c01_period_end_large(anomaly_feature_df, quantile=0.75)
        pd.testing.assert_series_equal(result_with_param, result_without)


# ── L3-05 주말 전기 ──────────────────────────────────────────


class TestL3-05:
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


# ── L3-06 심야 전기 ──────────────────────────────────────────


class TestL3-06:
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

    def test_time_zone_category_fallback(self) -> None:
        """is_after_hours 미생성 시 time_zone_category로 대체 동작."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 100.0, 100.0, 100.0],
            "time_zone_category": ["normal", "overtime", "midnight", "unknown"],
        })
        result = c03_after_hours_entry(df)
        # Why: overtime/midnight만 비정상 시간대 — fallback 신호
        assert result.tolist() == [False, True, True, False]

    def test_time_zone_category_or_combined(self) -> None:
        """is_after_hours와 time_zone_category가 모두 있으면 OR 결합."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 100.0, 100.0, 100.0],
            # is_after_hours만 보면 0번만 True
            "is_after_hours": [True, False, False, False],
            # time_zone_category로는 2번이 추가로 midnight
            "time_zone_category": ["normal", "normal", "midnight", "normal"],
        })
        result = c03_after_hours_entry(df)
        # Why: is_after_hours=True (0번) OR time_zone_category in {midnight,overtime} (2번)
        assert result.tolist() == [True, False, True, False]


# ── L3-07 소급 전기 ──────────────────────────────────────────


class TestL3-07:
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


# ── L1-08 기간 불일치 ────────────────────────────────────────


class TestL1-08:
    def test_mismatch_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert result[2]
        assert result[5]

    def test_match_not_flagged(self, anomaly_feature_df: pd.DataFrame) -> None:
        result = c05_fiscal_period_mismatch(anomaly_feature_df)
        assert not result[0]


# ── L3-08 위험 적요 ──────────────────────────────────────────


class TestL3-08:
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


# ── L4-03 이상 고액 ──────────────────────────────────────────


class TestL4-03:
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


# ── L3-09 가수금 장기체류 ──────────────────────────────────────


class TestL3-09:
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
