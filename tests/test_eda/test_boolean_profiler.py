"""boolean_profiler 단위 테스트 — boolean 통계 산출."""

import numpy as np
import pandas as pd
import pytest

from src.eda.boolean_profiler import profile_boolean


class TestProfileBoolean:
    """profile_boolean() 함수 테스트."""

    def test_true_rate(self):
        """기본 true_rate 산출."""
        s = pd.Series([True, True, False, False, True])
        result = profile_boolean(s)

        assert result["true_rate"] == pytest.approx(0.6)

    def test_all_true(self):
        """전체 True → true_rate=1.0."""
        s = pd.Series([True, True, True])
        result = profile_boolean(s)

        assert result["true_rate"] == pytest.approx(1.0)

    def test_all_nan(self):
        """전체 NaN → true_rate=None."""
        s = pd.Series([np.nan, np.nan, np.nan], dtype="boolean")
        result = profile_boolean(s)

        assert result["true_rate"] is None

    def test_nullable_boolean(self):
        """nullable BooleanDtype + NA 혼합."""
        s = pd.Series([True, False, None, True], dtype="boolean")
        result = profile_boolean(s)

        # NaN 제외: 3건 중 True 2건
        assert result["true_rate"] == pytest.approx(2 / 3, rel=1e-4)
