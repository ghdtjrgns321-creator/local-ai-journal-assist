"""numeric_profiler 단위 테스트 — 수치형 통계 산출."""

import numpy as np
import pandas as pd
import pytest

from src.eda.numeric_profiler import profile_numeric


class TestProfileNumeric:
    """profile_numeric() 함수 테스트."""

    def test_basic_stats(self):
        """기본 통계값 정확도 검증."""
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = profile_numeric(s)

        assert result["mean"] == pytest.approx(3.0)
        assert result["median"] == pytest.approx(3.0)
        assert result["min_val"] == pytest.approx(1.0)
        assert result["max_val"] == pytest.approx(5.0)
        assert result["std"] is not None

    def test_iqr_outlier_detection(self):
        """IQR × 1.5 기반 이상치 탐지."""
        # 1~10 정상값 + 100 이상치
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100])
        result = profile_numeric(s)

        assert result["outlier_count"] >= 1
        assert result["iqr"] is not None
        assert result["q1"] is not None
        assert result["q3"] is not None

    def test_std_zero_no_outliers(self):
        """모든 값 동일 (std=0) → outlier_count=0."""
        s = pd.Series([5.0, 5.0, 5.0, 5.0, 5.0])
        result = profile_numeric(s)

        assert result["std"] == pytest.approx(0.0)
        assert result["outlier_count"] == 0

    def test_all_nan_returns_none(self):
        """전체 NaN → 모든 값 None."""
        s = pd.Series([np.nan, np.nan, np.nan])
        result = profile_numeric(s)

        for key in ("mean", "median", "std", "min_val", "max_val"):
            assert result[key] is None

    def test_numpy_to_native_conversion(self):
        """반환값이 Python 네이티브 타입인지 검증."""
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = profile_numeric(s)

        for key in ("mean", "median", "std", "q1", "q3"):
            if result[key] is not None:
                assert isinstance(result[key], (int, float)), f"{key}: {type(result[key])}"

        assert isinstance(result["outlier_count"], int)

    def test_skewness_kurtosis(self):
        """skewness/kurtosis 산출 확인."""
        s = pd.Series([1, 2, 3, 4, 5, 100])  # 우편향
        result = profile_numeric(s)

        assert result["skewness"] is not None
        assert result["skewness"] > 0  # 양의 왜도
        assert result["kurtosis"] is not None

    def test_nullable_int(self):
        """Int64 (nullable integer) 처리."""
        s = pd.array([1, 2, 3, None, 5], dtype="Int64")
        result = profile_numeric(pd.Series(s))

        assert result["mean"] is not None
        assert result["min_val"] == pytest.approx(1.0)

    def test_single_value(self):
        """단일값 Series 처리."""
        s = pd.Series([42.0])
        result = profile_numeric(s)

        assert result["mean"] == pytest.approx(42.0)
        assert result["outlier_count"] == 0
