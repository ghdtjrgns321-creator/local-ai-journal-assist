"""amount_features 단위 테스트.

계층: base_amount → 개별 피처 → orchestrator 순서로 검증.
"""

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.feature.amount_features import (
    _compute_base_amount,
    _zscore_with_fallback,
    add_all_amount_features,
    add_amount_magnitude,
    add_amount_zscore,
    add_exceeds_threshold,
    add_is_near_threshold,
    add_is_round_number,
)


# ── TestBaseAmount ───────────────────────────────────────────────


class TestBaseAmount:
    """_compute_base_amount: 차/대 중 큰 값 선택, NaN 방어."""

    def test_debit_only(self):
        df = pd.DataFrame({"debit_amount": [100], "credit_amount": [0]})
        assert _compute_base_amount(df).iloc[0] == 100

    def test_credit_only(self):
        df = pd.DataFrame({"debit_amount": [0], "credit_amount": [200]})
        assert _compute_base_amount(df).iloc[0] == 200

    def test_both_zero(self):
        df = pd.DataFrame({"debit_amount": [0], "credit_amount": [0]})
        assert _compute_base_amount(df).iloc[0] == 0

    def test_both_nan(self):
        """둘 다 NaN → fillna(0) → 0."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [np.nan]})
        assert _compute_base_amount(df).iloc[0] == 0

    def test_one_nan(self):
        """한쪽 NaN → 유효값 사용."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [500]})
        assert _compute_base_amount(df).iloc[0] == 500


# ── TestIsNearThreshold ──────────────────────────────────────────


class TestIsNearThreshold:
    """B02: 다단계 승인한도 직하. 각 레벨별 threshold*ratio ≤ base < threshold."""

    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]
    RATIO = 0.90

    def test_exact_lower_bound(self):
        """첫 번째 레벨(10M)의 lower bound(9M) 정확히 → True."""
        base = pd.Series([self.THRESHOLDS[0] * self.RATIO])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == True

    def test_below_lower_bound(self):
        """모든 레벨의 near 구간 밖 → False."""
        base = pd.Series([self.THRESHOLDS[0] * self.RATIO - 1])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == False

    def test_at_threshold_is_false(self):
        """threshold 정확히 → False (그 레벨의 near 구간 상한)."""
        base = pd.Series([self.THRESHOLDS[0]])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == False

    def test_multi_level_near(self):
        """두 번째 레벨(100M)의 near 구간(90M~100M) → True."""
        base = pd.Series([95_000_000])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == True

    def test_between_levels_not_near(self):
        """레벨 사이 (20M) — 어떤 near 구간에도 미해당 → False."""
        base = pd.Series([20_000_000])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, self.RATIO)
        assert df["is_near_threshold"].iloc[0] == False


# ── TestExceedsThreshold ─────────────────────────────────────────


class TestExceedsThreshold:
    """B03: 다단계 승인한도 초과. base >= min(thresholds)."""

    THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000]

    def test_exact_threshold(self):
        """최고 한도(1B) 정확히 → True, level=3."""
        base = pd.Series([self.THRESHOLDS[-1]])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == True
        assert df["approval_level"].iloc[0] == 3

    def test_below_all_thresholds(self):
        """최저 한도(10M) 미만 → False, level=0."""
        base = pd.Series([self.THRESHOLDS[0] - 1])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == False
        assert df["approval_level"].iloc[0] == 0

    def test_mid_level_exceeds(self):
        """최저 한도(10M) 초과, 중간 한도(100M) 미만 → True, level=1."""
        base = pd.Series([50_000_000])
        df = pd.DataFrame({"x": [0]})
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["exceeds_threshold"].iloc[0] == True
        assert df["approval_level"].iloc[0] == 1

    def test_no_gap_with_near(self):
        """최고 한도 정확히 → near=False, exceeds=True (gap 없음)."""
        ratio = 0.90
        base = pd.Series([self.THRESHOLDS[-1]])
        df = pd.DataFrame({"x": [0]})
        add_is_near_threshold(df, base, self.THRESHOLDS, ratio)
        add_exceeds_threshold(df, base, self.THRESHOLDS)
        assert df["is_near_threshold"].iloc[0] == False
        assert df["exceeds_threshold"].iloc[0] == True


# ── TestAmountZscore ─────────────────────────────────────────────


class TestAmountZscore:
    """C08: 그룹별 Z-score + fallback."""

    def test_large_group_has_values(self, af_zscore_df):
        """30건+ 그룹은 Z-score 값이 존재해야 한다."""
        base = _compute_base_amount(af_zscore_df)
        df = af_zscore_df.copy()
        add_amount_zscore(df, base)
        # 큰 그룹 "A"의 zscore는 NaN이 아님
        large = df[df["gl_account"] == "A"]["amount_zscore"]
        assert large.notna().all()

    def test_small_group_fallback(self, af_zscore_df):
        """30건 미만 그룹은 전체 기준 Z-score로 fallback."""
        base = _compute_base_amount(af_zscore_df)
        df = af_zscore_df.copy()
        add_amount_zscore(df, base)
        small = df[df["gl_account"] == "B"]["amount_zscore"]
        assert small.notna().all()

    def test_std_zero_returns_zero(self, af_uniform_df):
        """모든 금액 동일(std=0) → Z-score 0.0, 에러 없음."""
        base = _compute_base_amount(af_uniform_df)
        df = af_uniform_df.copy()
        add_amount_zscore(df, base)
        assert (df["amount_zscore"] == 0.0).all()

    def test_too_few_rows_returns_nan(self):
        """전체 10건 미만 → Z-score 전부 NaN."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000] * 5,
            "credit_amount": [0] * 5,
            "gl_account": ["X"] * 5,
        })
        base = _compute_base_amount(df)
        add_amount_zscore(df, base)
        assert df["amount_zscore"].isna().all()

    def test_missing_gl_account(self):
        """gl_account 컬럼 누락 → NaN + warning."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000],
            "credit_amount": [0],
        })
        base = _compute_base_amount(df)
        add_amount_zscore(df, base)
        assert df["amount_zscore"].isna().all()


# ── TestAmountMagnitude ──────────────────────────────────────────


class TestAmountMagnitude:
    """log10(abs(base) + 1) 스케일."""

    def test_million(self):
        base = pd.Series([1_000_000])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert pytest.approx(df["amount_magnitude"].iloc[0], abs=0.01) == np.log10(1_000_001)

    def test_zero(self):
        base = pd.Series([0])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert df["amount_magnitude"].iloc[0] == 0.0

    def test_nan(self):
        base = pd.Series([np.nan])
        df = pd.DataFrame({"x": [0]})
        add_amount_magnitude(df, base)
        assert pd.isna(df["amount_magnitude"].iloc[0])


# ── TestIsRoundNumber ────────────────────────────────────────────


class TestIsRoundNumber:
    """B04: 라운드넘버 판정."""

    UNIT = 1_000_000

    def test_round(self):
        base = pd.Series([10_000_000])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == True

    def test_not_round(self):
        base = pd.Series([10_500_000])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_zero_excluded(self):
        """0원 → False (라운드넘버에서 제외)."""
        base = pd.Series([0])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_nan_is_false(self):
        """NaN → False."""
        base = pd.Series([np.nan])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False

    def test_float_tail_tolerance(self):
        """float 소수점 꼬리(미세)가 있어도 round 후 배수 판정."""
        base = pd.Series([10_000_000.000001, 5_000_000.4])
        df = pd.DataFrame({"x": [0, 0]})
        add_is_round_number(df, base, self.UNIT)
        # .000001 → round → 10M (배수), .4 → round → 5M (배수)
        assert df["is_round_number"].tolist() == [True, True]

    def test_near_but_not_round(self):
        """반올림해도 배수가 아닌 경우 → False."""
        base = pd.Series([10_500_000.3])
        df = pd.DataFrame({"x": [0]})
        add_is_round_number(df, base, self.UNIT)
        assert df["is_round_number"].iloc[0] == False


# ── TestAddAllAmountFeatures ─────────────────────────────────────


class TestAddAllAmountFeatures:
    """오케스트레이터: 5개 컬럼 생성, base_amount 미포함."""

    EXPECTED_COLS = {
        "is_near_threshold",
        "exceeds_threshold",
        "amount_zscore",
        "amount_magnitude",
        "is_round_number",
    }

    def test_all_columns_present(self, af_basic_df):
        result = add_all_amount_features(af_basic_df.copy())
        assert self.EXPECTED_COLS.issubset(result.columns)

    def test_base_amount_not_in_output(self, af_basic_df):
        result = add_all_amount_features(af_basic_df.copy())
        assert "base_amount" not in result.columns

    def test_custom_settings(self, af_basic_df):
        """approval_thresholds 커스텀 주입이 피처에 반영되는지 확인."""
        custom = AuditSettings(
            approval_thresholds=[10_000_000],
            near_threshold_ratio=0.80,
            round_unit=500_000,
        )
        result = add_all_amount_features(af_basic_df.copy(), settings=custom)
        assert self.EXPECTED_COLS.issubset(result.columns)
        # 10M 초과 금액은 exceeds=True 여야 함
        assert result["exceeds_threshold"].any()

    def test_edge_cases(self, af_edge_df):
        """NaN/0 포함 데이터에서 에러 없이 완료."""
        result = add_all_amount_features(af_edge_df.copy())
        assert self.EXPECTED_COLS.issubset(result.columns)
