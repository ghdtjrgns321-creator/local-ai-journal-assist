from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    _ensure_group_kfold,
    compare_pipelines,
)


@pytest.fixture()
def dummy_pipelines() -> dict[str, Pipeline]:
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
def classification_data() -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(42)
    docs_per_year = 6
    rows_per_doc = 4
    years = [2022, 2023, 2024]
    records: list[dict] = []
    labels: list[int] = []

    for year in years:
        for doc_idx in range(docs_per_year):
            doc_id = f"D{year}_{doc_idx}"
            label = int(doc_idx % 4 == 0)
            for line_idx in range(rows_per_doc):
                records.append({
                    "document_id": doc_id,
                    "fiscal_year": year,
                    "f1": rng.normal(),
                    "f2": rng.normal(),
                    "f3": rng.normal(),
                })
                labels.append(label)

    return pd.DataFrame(records), np.asarray(labels)


class TestEnsureGroupKFold:
    def test_int_converted(self):
        result = _ensure_group_kfold(5)
        assert isinstance(result, GroupKFold)
        assert result.n_splits == 5

    def test_groupkfold_passthrough(self):
        gkf = GroupKFold(n_splits=3)
        assert _ensure_group_kfold(gkf) is gkf


class TestComparePipelines:
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
        result = compare_pipelines(dummy_pipelines, X, y, cv=3)
        for cv_result in result.results.values():
            assert len(cv_result.scores) == 3
