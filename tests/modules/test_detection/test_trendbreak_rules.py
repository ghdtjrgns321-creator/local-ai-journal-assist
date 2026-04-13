"""TB01(부호 편향), TB02(범위 극단) 룰 함수 단위 테스트."""

from __future__ import annotations

import pytest

from src.detection.trendbreak_rules import tb01_sign_bias, tb02_range_extremity


# ── TB01: 부호 편향 ────────────────────────────────────────


class TestTb01SignBias:
    """estimation error 부호 일관성 판정."""

    def test_all_positive_errors(self):
        """모든 error가 양수 → 플래그 (과대추정 편향)."""
        errors = {"1020": [100.0, 200.0, 150.0, 300.0]}
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is True
        assert result["1020"]["sign_ratio"] == 1.0
        assert result["1020"]["dominant_sign"] == "positive"

    def test_all_negative_errors(self):
        """모든 error가 음수 → 플래그 (이익 편향 과소추정)."""
        errors = {"1020": [-50.0, -80.0, -30.0, -100.0]}
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is True
        assert result["1020"]["dominant_sign"] == "negative"

    def test_mixed_errors_no_bias(self):
        """양수/음수 혼재 → 편향 없음."""
        errors = {"1020": [100.0, -50.0, 80.0, -30.0]}
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is False
        assert result["1020"]["sign_ratio"] == 0.5

    def test_below_threshold(self):
        """2/3 = 0.67 < 0.8 → 미플래그."""
        errors = {"1020": [100.0, 200.0, -50.0]}
        result = tb01_sign_bias(errors, min_periods=2, bias_ratio_threshold=0.8)
        assert result["1020"]["flagged"] is False

    def test_at_threshold(self):
        """3/4 = 0.75 < 0.8 → 미플래그."""
        errors = {"1020": [100.0, 200.0, 150.0, -50.0]}
        result = tb01_sign_bias(errors, min_periods=2, bias_ratio_threshold=0.8)
        assert result["1020"]["flagged"] is False

    def test_above_threshold(self):
        """4/5 = 0.8 >= 0.8 → 플래그."""
        errors = {"1020": [100.0, 200.0, 150.0, 300.0, -50.0]}
        result = tb01_sign_bias(errors, min_periods=2, bias_ratio_threshold=0.8)
        assert result["1020"]["flagged"] is True

    def test_all_zeros(self):
        """모든 error = 0 → insufficient_data."""
        errors = {"1020": [0.0, 0.0, 0.0, 0.0]}
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is False
        assert result["1020"]["reason"] == "insufficient_data"

    def test_insufficient_data(self):
        """error 1개 < min_periods=2 → insufficient_data."""
        errors = {"1020": [100.0]}
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is False

    def test_custom_threshold(self):
        """threshold=0.5, 2/3=0.67 > 0.5 → 플래그."""
        errors = {"1020": [100.0, -50.0, 80.0]}
        result = tb01_sign_bias(errors, min_periods=2, bias_ratio_threshold=0.5)
        assert result["1020"]["flagged"] is True

    def test_multiple_accounts(self):
        """여러 계정 동시 판정."""
        errors = {
            "1020": [100.0, 200.0, 150.0],  # 3/3 = 1.0 → 플래그
            "1599": [50.0, -60.0, 30.0],    # 2/3 = 0.67 → 미플래그
        }
        result = tb01_sign_bias(errors, min_periods=2)
        assert result["1020"]["flagged"] is True
        assert result["1599"]["flagged"] is False


# ── TB02: 범위 극단 ────────────────────────────────────────


class TestTb02RangeExtremity:
    """provision amounts(설정액) 단조 추세 판정."""

    def test_consistently_decreasing(self):
        """설정액이 매년 감소 → 이익 편향 플래그 (direction=lower)."""
        amounts = {"1020": [100.0, 90.0, 80.0, 70.0, 60.0]}
        result = tb02_range_extremity(amounts, min_periods=3, extremity_quantile=0.1)
        info = result["1020"]
        assert info["flagged"] is True
        assert info["direction"] == "lower"
        assert info["trend_ratio"] == 1.0  # 4/4 모두 감소

    def test_consistently_increasing(self):
        """설정액이 매년 증가 → 보수적 과다 설정 플래그 (direction=upper)."""
        amounts = {"1020": [50.0, 70.0, 90.0, 110.0, 130.0]}
        result = tb02_range_extremity(amounts, min_periods=3, extremity_quantile=0.1)
        info = result["1020"]
        assert info["flagged"] is True
        assert info["direction"] == "upper"

    def test_normal_variation(self):
        """증감 혼재 → 미플래그."""
        amounts = {"1020": [100.0, 110.0, 95.0, 108.0, 92.0]}
        result = tb02_range_extremity(amounts, min_periods=3)
        assert result["1020"]["flagged"] is False

    def test_no_variation(self):
        """설정액 동일 → no_variation 스킵."""
        amounts = {"1020": [100.0, 100.0, 100.0]}
        result = tb02_range_extremity(amounts, min_periods=3)
        assert result["1020"]["flagged"] is False
        assert result["1020"]["reason"] == "no_variation"

    def test_insufficient_periods(self):
        """기간 2개 < min_periods=3 → insufficient_data."""
        amounts = {"1020": [100.0, 200.0]}
        result = tb02_range_extremity(amounts, min_periods=3)
        assert result["1020"]["flagged"] is False

    def test_large_writeoff_no_false_positive(self):
        """TB02는 provision(설정액)만 보므로 상각(debit)과 무관.

        Why: provision_amounts는 total_credit 시계열이므로
             total_debit(상각) 급증은 이 데이터에 포함되지 않는다.
        """
        # 설정액은 안정적 증감 혼재 — 상각 급증은 여기 반영 안 됨
        amounts = {"1020": [100.0, 105.0, 98.0, 102.0, 100.0]}
        result = tb02_range_extremity(amounts, min_periods=3)
        assert result["1020"]["flagged"] is False

    def test_multiple_accounts(self):
        """여러 계정 동시 판정."""
        amounts = {
            "1020": [100.0, 100.0, 100.0],  # no_variation
            "1599": [100.0, 90.0, 80.0],    # 단조 감소 → 플래그
        }
        result = tb02_range_extremity(amounts, min_periods=3)
        assert result["1020"]["flagged"] is False
        assert result["1599"]["flagged"] is True
        assert result["1599"]["direction"] == "lower"
