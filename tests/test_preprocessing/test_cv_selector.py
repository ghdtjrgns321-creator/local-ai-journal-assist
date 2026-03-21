"""cv_selector 테스트 — StratifiedKFold Pipeline 비교."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    _ensure_stratified_kfold,
    compare_pipelines,
)


@pytest.fixture()
def dummy_pipelines():
    """비교용 더미 Pipeline 2개."""
    pipe_a = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", DecisionTreeClassifier(max_depth=2, random_state=42)),
    ])
    pipe_b = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", DecisionTreeClassifier(max_depth=5, random_state=42)),
    ])
    return {"shallow": pipe_a, "deep": pipe_b}


@pytest.fixture()
def classification_data():
    """이진 분류 테스트 데이터 (불균형)."""
    rng = np.random.default_rng(42)
    n = 100
    X = pd.DataFrame({
        "f1": rng.normal(0, 1, n),
        "f2": rng.normal(0, 1, n),
    })
    y = pd.Series(np.concatenate([np.zeros(90), np.ones(10)]))
    return X, y


class TestEnsureStratifiedKFold:
    """_ensure_stratified_kfold 검증."""

    def test_int_converted(self):
        """int → StratifiedKFold 변환."""
        skf = _ensure_stratified_kfold(5)
        assert isinstance(skf, StratifiedKFold)
        assert skf.n_splits == 5

    def test_skf_passthrough(self):
        """StratifiedKFold 인스턴스는 그대로 반환."""
        original = StratifiedKFold(n_splits=3)
        result = _ensure_stratified_kfold(original)
        assert result is original


class TestComparePipelines:
    """compare_pipelines 검증."""

    def test_returns_comparison_result(self, dummy_pipelines, classification_data):
        """CVComparisonResult 반환."""
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert isinstance(result, CVComparisonResult)

    def test_all_pipelines_evaluated(self, dummy_pipelines, classification_data):
        """모든 Pipeline이 평가되는지."""
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert set(result.results.keys()) == {"shallow", "deep"}

    def test_best_pipeline_selected(self, dummy_pipelines, classification_data):
        """best_pipeline_name이 설정되는지."""
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        assert result.best_pipeline_name in {"shallow", "deep"}
        assert result.best_pipeline is not None

    def test_comparison_table_structure(self, dummy_pipelines, classification_data):
        """대시보드용 비교 테이블 구조."""
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        table = result.comparison_table
        assert "pipeline" in table.columns
        assert "mean_f1" in table.columns
        assert len(table) == 2

    def test_scores_list_length(self, dummy_pipelines, classification_data):
        """fold별 점수 리스트 길이가 cv와 일치하는지."""
        X, y = classification_data
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        for cv_result in result.results.values():
            assert len(cv_result.scores) == 3
