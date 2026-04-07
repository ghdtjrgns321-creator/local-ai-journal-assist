"""category_profiler 단위 테스트 — 범주형 통계 산출."""

import numpy as np
import pandas as pd
import pytest

from src.eda.category_profiler import profile_categorical


class TestProfileCategorical:
    """profile_categorical() 함수 테스트."""

    def test_top10_values(self):
        """상위 10개 값 추출 + 정렬 검증."""
        values = [f"cat_{i}" for i in range(20)] * 10
        # cat_0이 가장 많도록 추가
        values += ["cat_0"] * 50
        s = pd.Series(values)
        result = profile_categorical(s)

        assert len(result["top_values"]) == 10
        assert result["top_values"][0][0] == "cat_0"

    def test_high_cardinality(self):
        """고카디널리티 (100+ 유니크값)."""
        s = pd.Series([f"val_{i}" for i in range(150)])
        result = profile_categorical(s)

        assert result["cardinality"] == 150

    def test_single_value(self):
        """단일값만 존재."""
        s = pd.Series(["only"] * 10)
        result = profile_categorical(s)

        assert result["cardinality"] == 1
        assert result["top_values"] == [("only", 10)]

    def test_all_nan(self):
        """전체 NaN → 빈 결과."""
        s = pd.Series([np.nan, np.nan, np.nan])
        result = profile_categorical(s)

        assert result["cardinality"] == 0
        assert result["top_values"] == []

    def test_korean_values(self):
        """한글 범주값 처리."""
        s = pd.Series(["가수금", "매출", "가수금", "입금", "매출", "매출"])
        result = profile_categorical(s)

        assert result["cardinality"] == 3
        assert result["top_values"][0][0] == "매출"
        assert result["top_values"][0][1] == 3
