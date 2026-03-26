"""CV Pipeline 비교 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    _ensure_stratified_kfold,
    compare_pipelines,
)


@pytest.fixture()
def dummy_pipelines() -> dict[str, Pipeline]:
    """비교용 간단한 Pipeline 2개."""
    return {
        "shallow": Pipeline([
            ("imputer", SimpleImputer(strategy="mean")),
            ("clf", LogisticRegression(max_iter=200, random_state=42)),
        ]),
        "deep": Pipeline([
            ("imputer", SimpleImputer(strategy="mean")),
            ("clf", DecisionTreeClassifier(random_state=42)),
        ]),
    }


@pytest.fixture()
def classification_data() -> tuple[np.ndarray, np.ndarray]:
    """200행, 5% 양성, 수치형 5컬럼."""
    rng = np.random.default_rng(42)
    n = 200
    X = rng.normal(0, 1, (n, 5))
    y = rng.choice([0, 1], n, p=[0.95, 0.05])
    return X, y


class TestEnsureStratifiedKFold:
    """int → StratifiedKFold 변환 검증."""

    def test_int_converted(self):
        result = _ensure_stratified_kfold(5)
        assert isinstance(result, StratifiedKFold)
        assert result.n_splits == 5

    def test_skf_passthrough(self):
        skf = StratifiedKFold(n_splits=3)
        assert _ensure_stratified_kfold(skf) is skf


class TestComparePipelines:
    """Pipeline CV 비교 검증."""

    def test_returns_comparison_result(self, dummy_pipelines, classification_data):
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert isinstance(result, CVComparisonResult)

    def test_all_pipelines_evaluated(self, dummy_pipelines, classification_data):
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert set(result.results.keys()) == {"shallow", "deep"}

    def test_best_pipeline_selected(self, dummy_pipelines, classification_data):
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert result.best_pipeline_name in {"shallow", "deep"}

    def test_comparison_table_structure(self, dummy_pipelines, classification_data):
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert "pipeline" in result.comparison_table.columns
        assert "mean_f1" in result.comparison_table.columns

    def test_scores_list_length(self, dummy_pipelines, classification_data):
        X, y = classification_data
        cv = 3
        result = compare_pipelines(dummy_pipelines, X, y, cv=cv)
        for cv_result in result.results.values():
            assert len(cv_result.scores) == cv
