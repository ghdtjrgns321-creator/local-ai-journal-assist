"""transformers 테스트 — 커스텀 Transformer fit/transform."""

from __future__ import annotations

import numpy as np
import pytest

from src.preprocessing.transformers import NullFlagTransformer, SafePowerTransformer


class TestNullFlagTransformer:
    """NullFlagTransformer 검증."""

    def test_adds_flag_columns(self):
        """NaN 위치에 플래그 컬럼이 추가되는지."""
        X = np.array([[1.0, np.nan], [3.0, 4.0]])
        t = NullFlagTransformer(fill_value=-1.0)
        result = t.fit_transform(X)

        # 원본 2컬럼 + 플래그 2컬럼 = 4컬럼
        assert result.shape == (2, 4)

    def test_nan_replaced_with_fill_value(self):
        """NaN이 fill_value로 대체되는지."""
        X = np.array([[1.0, np.nan], [3.0, 4.0]])
        t = NullFlagTransformer(fill_value=-99.0)
        result = t.fit_transform(X)

        assert result[0, 1] == -99.0  # NaN → -99
        assert result[1, 1] == 4.0    # 원본 유지

    def test_flag_values_correct(self):
        """플래그가 NaN=1.0, 값있음=0.0인지."""
        X = np.array([[np.nan], [5.0]])
        t = NullFlagTransformer()
        result = t.fit_transform(X)

        assert result[0, 1] == 1.0  # NaN이었으므로 플래그=1
        assert result[1, 1] == 0.0  # 값 있으므로 플래그=0

    def test_no_nan_no_flags(self):
        """NaN이 없으면 플래그가 전부 0인지."""
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        t = NullFlagTransformer()
        result = t.fit_transform(X)
        flags = result[:, 2:]
        assert np.all(flags == 0.0)


class TestSafePowerTransformer:
    """SafePowerTransformer 검증."""

    def test_transforms_skewed_data(self):
        """우측 꼬리 분포가 변환되는지."""
        rng = np.random.default_rng(42)
        X = rng.exponential(1_000_000, size=(200, 1))
        t = SafePowerTransformer()
        result = t.fit_transform(X)

        # 변환 후 분포가 더 정규분포에 가까워야 함
        assert result.shape == X.shape
        # 원본 skewness > 변환 후 skewness (절대값)
        from scipy.stats import skew
        orig_skew = abs(skew(X.ravel()))
        trans_skew = abs(skew(result.ravel()))
        assert trans_skew < orig_skew

    def test_handles_constant_column(self):
        """상수 컬럼(std=0)이 에러 없이 처리되는지."""
        X = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
        t = SafePowerTransformer()
        result = t.fit_transform(X)

        assert result.shape == X.shape
        # 상수 컬럼은 그대로 유지
        assert np.all(result[:, 0] == 5.0)

    def test_output_shape_preserved(self):
        """입출력 shape이 동일한지."""
        X = np.array([[1.0, 100.0], [2.0, 200.0], [3.0, 300.0]])
        t = SafePowerTransformer()
        result = t.fit_transform(X)
        assert result.shape == X.shape

    def test_handles_negative_values(self):
        """음수값(Yeo-Johnson)이 에러 없이 처리되는지."""
        X = np.array([[-100.0], [0.0], [100.0], [1000.0]])
        t = SafePowerTransformer()
        result = t.fit_transform(X)
        assert result.shape == X.shape
        assert not np.any(np.isnan(result))
