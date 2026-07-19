from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, KFold
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    _ensure_group_kfold,
    build_user_group_kfold,
    compare_pipelines,
    evaluate_stage2_auc_gaps,
    select_split_strategy,
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

    def test_random_split_rejects_row_level(self):
        with pytest.raises(ValueError, match="row-level KFold is not allowed"):
            _ensure_group_kfold(KFold(n_splits=3))


class TestStage2SplitStrategy:
    def test_groupkfold_zero_user_overlap(self):
        rows: list[dict] = []
        for user_idx in range(6):
            for row_idx in range(3):
                rows.append({
                    "document_id": f"D{user_idx}_{row_idx}",
                    "created_by": f"U{user_idx}",
                    "amount": float(user_idx + row_idx),
                })
        df = pd.DataFrame(rows)
        gkf, groups = build_user_group_kfold(df, n_splits=3)

        for train_idx, val_idx in gkf.split(df, groups=groups):
            train_users = set(df.iloc[train_idx]["created_by"])
            val_users = set(df.iloc[val_idx]["created_by"])
            assert train_users.isdisjoint(val_users)

    def test_user_group_kfold_falls_back_to_document_when_users_too_few(self, caplog):
        df = pd.DataFrame({
            "document_id": [f"D{i}" for i in range(6)],
            "created_by": ["U1", "U1", "U2", "U2", "U2", "U1"],
        })

        gkf, groups = build_user_group_kfold(df, n_splits=3)

        assert gkf.n_splits == 3
        assert groups.tolist() == df["document_id"].astype(str).tolist()
        assert "falling back to document_id GroupKFold" in caplog.text

    def test_select_split_strategy_uses_user_features_first(self):
        df = pd.DataFrame({
            "document_id": [f"D{i}" for i in range(6)],
            "created_by": [f"U{i}" for i in range(6)],
            "fiscal_year": [2022, 2022, 2023, 2023, 2024, 2024],
        })
        metadata = type(
            "FeatureMetadata",
            (),
            {"uses_user_features": True, "requires_temporal_holdout": True},
        )()

        selection = select_split_strategy(df, metadata, n_splits=3)

        assert selection.name == "user_group_kfold"
        assert selection.cv is not None
        assert selection.groups is not None
        assert set(selection.groups) == set(df["created_by"])

    def test_select_split_strategy_uses_temporal_holdout(self):
        df = pd.DataFrame({
            "document_id": [f"D{i}" for i in range(8)],
            "created_by": ["U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"],
            "fiscal_year": [2022, 2022, 2023, 2023, 2024, 2024, 2024, 2024],
        })
        metadata = type(
            "FeatureMetadata",
            (),
            {"uses_user_features": False, "requires_temporal_holdout": True},
        )()

        selection = select_split_strategy(df, metadata, n_splits=3)

        assert selection.name == "split_user_year_holdout"
        assert selection.holdout is not None
        assert selection.holdout.policy == "user_year_holdout"

    def test_stage2_thresholds_holds(self):
        below = evaluate_stage2_auc_gaps(random_auc=0.9999, group_auc=0.9893, time_auc=0.98)
        assert below["user_level_leakage_confirmed"] is False
        assert below["temporal_leakage_confirmed"] is False

        above = evaluate_stage2_auc_gaps(random_auc=0.96, group_auc=0.90, time_auc=0.86)
        assert above["user_level_leakage_confirmed"] is True
        assert above["temporal_leakage_confirmed"] is True


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
