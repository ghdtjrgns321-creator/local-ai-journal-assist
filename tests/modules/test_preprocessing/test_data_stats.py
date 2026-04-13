"""data_stats — 학습 데이터 분포 메타데이터 산출 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing.data_stats import (
    compute_class_imbalance,
    compute_feature_schema_version,
    compute_training_stats,
)


@pytest.fixture()
def mixed_df() -> pd.DataFrame:
    """수치형 + 범주형 + 결측을 포함한 표준 DataFrame."""
    return pd.DataFrame({
        "amount": [100.0, 200.0, 300.0, np.nan, 500.0],
        "currency": ["KRW", "KRW", "USD", "USD", None],
        "qty": [1, 2, 3, 4, 5],
    })


class TestComputeTrainingStats:
    def test_empty_returns_zero(self):
        result = compute_training_stats(pd.DataFrame())
        assert result["n_samples"] == 0
        assert result["columns"] == {}

    def test_n_samples(self, mixed_df):
        result = compute_training_stats(mixed_df)
        assert result["n_samples"] == 5

    def test_numeric_stats(self, mixed_df):
        stats = compute_training_stats(mixed_df)["columns"]["amount"]
        assert stats["type"] == "numeric"
        # Why: NaN 제외 후 평균 (100+200+300+500)/4 = 275
        assert stats["mean"] == pytest.approx(275.0)
        assert stats["min"] == 100.0
        assert stats["max"] == 500.0
        assert stats["null_rate"] == pytest.approx(0.2)
        assert stats["nunique"] == 4

    def test_categorical_stats(self, mixed_df):
        stats = compute_training_stats(mixed_df)["columns"]["currency"]
        assert stats["type"] == "categorical"
        assert stats["nunique"] == 2
        assert stats["null_rate"] == pytest.approx(0.2)
        # Why: 빈도수가 가장 높은 카테고리는 KRW(2건)
        assert stats["top_categories"]["KRW"] == 2
        assert stats["top_categories"]["USD"] == 2

    def test_integer_treated_as_numeric(self, mixed_df):
        stats = compute_training_stats(mixed_df)["columns"]["qty"]
        assert stats["type"] == "numeric"
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0


class TestComputeClassImbalance:
    def test_none_returns_zero(self):
        assert compute_class_imbalance(None) == 0.0

    def test_empty_returns_zero(self):
        assert compute_class_imbalance(np.array([])) == 0.0

    def test_balanced(self):
        assert compute_class_imbalance(np.array([0, 1, 0, 1])) == 0.5

    def test_imbalanced(self):
        # Why: 양성 1개 / 전체 100개 = 1%
        y = np.zeros(100, dtype=int)
        y[0] = 1
        assert compute_class_imbalance(y) == pytest.approx(0.01)

    def test_pandas_series_input(self):
        s = pd.Series([0, 1, 1, 1, 0])
        assert compute_class_imbalance(s) == pytest.approx(0.6)


class TestComputeFeatureSchemaVersion:
    def test_empty_returns_zero(self):
        assert compute_feature_schema_version(pd.DataFrame()) == 0

    def test_deterministic(self):
        df1 = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        df2 = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        assert compute_feature_schema_version(df1) == compute_feature_schema_version(df2)

    def test_order_independent(self):
        # Why: 컬럼 순서가 달라도 동일 set이면 동일 해시
        df1 = pd.DataFrame({"a": [1], "b": [2]})
        df2 = pd.DataFrame({"b": [1], "a": [2]})
        assert compute_feature_schema_version(df1) == compute_feature_schema_version(df2)

    def test_different_columns_differ(self):
        df1 = pd.DataFrame({"a": [1], "b": [2]})
        df2 = pd.DataFrame({"a": [1], "c": [2]})
        assert compute_feature_schema_version(df1) != compute_feature_schema_version(df2)
