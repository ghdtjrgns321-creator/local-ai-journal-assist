"""커스텀 sklearn Transformer 테스트."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import skew

from src.preprocessing.transformers import NullFlagTransformer, SafePowerTransformer


class TestNullFlagTransformer:
    """NaN 플래그 컬럼 추가 + fill_value 대체 검증."""

    def test_adds_flag_columns(self):
        X = np.array([[1.0, 2.0], [np.nan, 3.0], [4.0, np.nan]])
        tf = NullFlagTransformer().fit(X)
        result = tf.transform(X)
        assert result.shape == (3, 4)  # 원본 2 + 플래그 2

    def test_nan_replaced_with_fill_value(self):
        X = np.array([[np.nan], [5.0]])
        result = NullFlagTransformer(fill_value=-99.0).fit(X).transform(X)
        assert result[0, 0] == -99.0
        assert result[1, 0] == 5.0

    def test_flag_values_correct(self):
        X = np.array([[np.nan], [5.0], [np.nan]])
        result = NullFlagTransformer().fit(X).transform(X)
        flags = result[:, 1]  # 두 번째 컬럼이 플래그
        np.testing.assert_array_equal(flags, [1.0, 0.0, 1.0])

    def test_no_nan_no_flags(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = NullFlagTransformer().fit(X).transform(X)
        flags = result[:, 2:]
        assert np.all(flags == 0.0)


class TestSafePowerTransformer:
    """Yeo-Johnson + 상수 컬럼 방어 검증."""

    def test_transforms_skewed_data(self):
        rng = np.random.default_rng(42)
        X = rng.lognormal(mean=10, sigma=2, size=(200, 1))
        tf = SafePowerTransformer().fit(X)
        result = tf.transform(X)
        assert abs(skew(result[:, 0])) < abs(skew(X[:, 0]))

    def test_handles_constant_column(self):
        X = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
        tf = SafePowerTransformer().fit(X)
        result = tf.transform(X)
        # 상수 컬럼은 원본 유지
        np.testing.assert_array_equal(result[:, 0], [5.0, 5.0, 5.0])

    def test_output_shape_preserved(self):
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        result = SafePowerTransformer().fit(X).transform(X)
        assert result.shape == X.shape

    def test_handles_negative_values(self):
        X = np.array([[-10.0], [-5.0], [0.0], [5.0], [10.0]])
        tf = SafePowerTransformer().fit(X)
        result = tf.transform(X)
        assert result.shape == X.shape  # 에러 없이 변환 완료
