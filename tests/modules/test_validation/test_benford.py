"""Benford's Law 분석 단위 테스트."""

import math

import numpy as np
import pandas as pd
import pytest

from config.settings import AuditSettings
from src.validation.benford import BENFORD_EXPECTED, analyze_benford


@pytest.fixture()
def settings() -> AuditSettings:
    return AuditSettings()


def _benford_digits(n: int, seed: int = 42) -> pd.Series:
    """Benford 분포를 따르는 first_digit 시리즈 생성."""
    rng = np.random.default_rng(seed)
    probs = [BENFORD_EXPECTED[d] for d in range(1, 10)]
    digits = rng.choice(range(1, 10), size=n, p=probs)
    return pd.array(digits, dtype="Int64")


def _uniform_digits(n: int) -> pd.Series:
    """균등 분포(1~9 동빈도) first_digit 시리즈."""
    repeat = n // 9
    digits = list(range(1, 10)) * repeat + list(range(1, n - repeat * 9 + 1))
    return pd.array(digits[:n], dtype="Int64")


class TestAnalyzeBenford:
    """analyze_benford 핵심 테스트."""

    def test_conforming_benford_distribution(self, settings):
        """완벽한 Benford 분포 → is_conforming=True, MAD < 0.006."""
        digits = _benford_digits(5000)
        result, warnings = analyze_benford(digits, settings=settings)

        assert result.is_conforming is True
        assert result.mad is not None
        assert result.mad < 0.006
        assert result.mad_conformity == "close"
        assert result.confidence == "high"
        assert result.chi2_p_value is not None
        assert result.chi2_p_value > 0.05

    def test_uniform_distribution_nonconforming(self, settings):
        """균등 분포 → is_conforming=False, MAD > 0.015."""
        digits = _uniform_digits(1000)
        result, warnings = analyze_benford(digits, settings=settings)

        assert result.is_conforming is False
        assert result.mad is not None
        assert result.mad > 0.015
        assert result.mad_conformity == "nonconforming"

    def test_small_sample_low_confidence(self, settings):
        """n < 100 → confidence=low + 경고."""
        digits = _benford_digits(50)
        result, warnings = analyze_benford(digits, settings=settings)

        assert result.confidence == "low"
        assert any("신뢰도 낮음" in w for w in warnings)
        assert result.sample_size == 50

    def test_moderate_confidence(self, settings):
        """100 ≤ n < 500 → confidence=moderate."""
        digits = _benford_digits(200)
        result, _ = analyze_benford(digits, settings=settings)
        assert result.confidence == "moderate"

    def test_empty_series(self, settings):
        """전체 NaN → 빈 결과 + 경고."""
        digits = pd.array([pd.NA] * 10, dtype="Int64")
        result, warnings = analyze_benford(digits, settings=settings)

        assert result.sample_size == 0
        assert result.is_conforming is False
        assert result.mad is None
        assert any("유효한 첫째자리" in w for w in warnings)

    def test_observed_sums_to_one(self, settings):
        """observed 분포의 합이 1.0."""
        digits = _benford_digits(500)
        result, _ = analyze_benford(digits, settings=settings)
        assert abs(sum(result.observed.values()) - 1.0) < 1e-10

    def test_expected_matches_benford(self, settings):
        """expected가 Benford 이론값과 일치."""
        digits = _benford_digits(100)
        result, _ = analyze_benford(digits, settings=settings)
        for d in range(1, 10):
            assert abs(result.expected[d] - math.log10(1 + 1 / d)) < 1e-10

    def test_ks_populated_for_large_sample(self, settings):
        """n ≥ 50이면 KS 보조 지표가 채워짐."""
        digits = _benford_digits(100)
        result, _ = analyze_benford(digits, settings=settings)
        assert result.ks_statistic is not None
        assert result.ks_p_value is not None

    def test_ks_none_for_small_sample(self, settings):
        """n < 50이면 KS 미산출."""
        digits = _benford_digits(30)
        result, _ = analyze_benford(digits, settings=settings)
        assert result.ks_statistic is None
