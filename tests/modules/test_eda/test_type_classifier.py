"""type_classifier 단위 테스트 — dtype → 4분류 매핑."""

import pandas as pd
import pytest

from src.eda.type_classifier import classify_column


class TestClassifyColumn:
    """classify_column() 함수 테스트."""

    def test_bool_dtype(self):
        """bool → 'boolean'."""
        s = pd.Series([True, False, True])
        assert classify_column(s) == "boolean"

    def test_nullable_boolean(self):
        """nullable BooleanDtype → 'boolean'."""
        s = pd.Series([True, False, None], dtype="boolean")
        assert classify_column(s) == "boolean"

    def test_datetime64(self):
        """datetime64 → 'datetime'."""
        s = pd.to_datetime(["2025-01-01", "2025-01-02"])
        assert classify_column(s) == "datetime"

    def test_numeric_float(self):
        """float64 → 'numeric'."""
        s = pd.Series([1.0, 2.0, 3.0])
        assert classify_column(s) == "numeric"

    def test_nullable_int(self):
        """Int64 (nullable) → 'numeric'."""
        s = pd.array([1, 2, None], dtype="Int64")
        assert classify_column(pd.Series(s)) == "numeric"

    def test_object_categorical(self):
        """object → 'categorical'."""
        s = pd.Series(["A", "B", "C"])
        assert classify_column(s) == "categorical"

    def test_mixed_df_classification(self, ed_mixed_df):
        """4개 dtype 혼합 DataFrame 분류 검증."""
        expected = {"num": "numeric", "cat": "categorical", "dt": "datetime", "flag": "boolean"}
        for col, expected_group in expected.items():
            assert classify_column(ed_mixed_df[col]) == expected_group
