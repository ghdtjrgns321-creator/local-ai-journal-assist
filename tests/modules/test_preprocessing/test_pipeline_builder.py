"""Pipeline 조립 테스트 — XGB / VAE / IF / LightGBM / 지도학습 4종."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.pipeline import Pipeline

from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.pipeline_builder import (
    build_all_pipelines,
    build_if_pipeline,
    build_lgbm_pipeline,
    prepare_training_features,
    build_supervised_pipelines,
    build_xgb_pipeline,
    drop_label_columns,
)


@pytest.fixture()
def simple_groups() -> FeatureGroups:
    """최소 피처 그룹."""
    return FeatureGroups(
        numeric=["f1", "f2", "f3"],
        categorical_low=["cat1"],
        boolean=["flag1"],
    )


@pytest.fixture()
def simple_data() -> tuple[np.ndarray, np.ndarray]:
    """XGB fit/predict용 소규모 데이터."""
    rng = np.random.default_rng(42)
    n = 50
    import pandas as pd

    df = pd.DataFrame({
        "f1": rng.normal(0, 1, n),
        "f2": rng.normal(0, 1, n),
        "f3": rng.normal(0, 1, n),
        "cat1": rng.choice(["A", "B", "C"], n),
        "flag1": rng.choice([0, 1], n),
    })
    y = rng.choice([0, 1], n, p=[0.9, 0.1])
    return df, y


class TestBuildXgbPipeline:
    """XGBoost Pipeline 조립 검증."""

    def test_builds_successfully(self, simple_groups):
        pipe = build_xgb_pipeline(simple_groups)
        assert isinstance(pipe, Pipeline)

    def test_fit_predict(self, simple_groups, simple_data):
        pipe = build_xgb_pipeline(simple_groups)
        X, y = simple_data
        pipe.fit(X, y)
        preds = pipe.predict(X)
        assert set(preds).issubset({0, 1})


class TestBuildIfPipeline:
    """Isolation Forest Pipeline 조립 검증."""

    def test_builds_successfully(self, simple_groups):
        pipe = build_if_pipeline(simple_groups)
        assert isinstance(pipe, Pipeline)

    def test_fit_predict(self, simple_groups, simple_data):
        pipe = build_if_pipeline(simple_groups)
        X, y = simple_data
        pipe.fit(X)
        preds = pipe.predict(X)
        assert len(preds) == len(X)


class TestBuildAllPipelines:
    """3개 Pipeline 일괄 생성 검증."""

    def test_returns_three_pipelines(self, simple_groups):
        result = build_all_pipelines(simple_groups)
        assert len(result) == 3
        assert set(result.keys()) == {"xgb", "vae", "if"}

    def test_all_pipelines_have_preprocessor(self, simple_groups):
        result = build_all_pipelines(simple_groups)
        for name, pipe in result.items():
            assert "preprocessor" in pipe.named_steps, f"{name} has no preprocessor"


class TestBuildLgbmPipeline:
    """LightGBM Pipeline 조립 검증."""

    def test_builds_successfully(self, simple_groups):
        pipe = build_lgbm_pipeline(simple_groups)
        assert isinstance(pipe, Pipeline)

    def test_fit_predict(self, simple_groups, simple_data):
        pipe = build_lgbm_pipeline(simple_groups)
        X, y = simple_data
        pipe.fit(X, y)
        preds = pipe.predict(X)
        assert set(preds).issubset({0, 1})


class TestBuildSupervisedPipelines:
    """지도학습 4개 Pipeline 일괄 생성 검증."""

    def test_returns_four_pipelines(self, simple_groups):
        result = build_supervised_pipelines(simple_groups)
        assert len(result) == 4
        assert {"lr", "rf", "xgb", "lgbm"} == set(result.keys())

    def test_all_have_preprocessor(self, simple_groups):
        result = build_supervised_pipelines(simple_groups)
        for name, pipe in result.items():
            assert "preprocessor" in pipe.named_steps, f"{name} has no preprocessor"

    def test_all_fit_predict(self, simple_groups, simple_data):
        """4개 모델 모두 fit/predict 정상 동작."""
        pipelines = build_supervised_pipelines(simple_groups)
        X, y = simple_data
        for name, pipe in pipelines.items():
            pipe.fit(X, y)
            preds = pipe.predict(X)
            assert set(preds).issubset({0, 1}), f"{name} predict failed"


class TestDropLabelColumns:
    def test_drops_all_datasynth_label_columns(self):
        import pandas as pd

        df = pd.DataFrame({
            "feature_a": [1, 2],
            "is_fraud": [True, False],
            "fraud_type": ["DuplicatePayment", None],
            "is_anomaly": [True, False],
            "anomaly_type": ["TimingAnomaly", None],
            "sod_violation": [False, True],
            "sod_conflict_type": [None, "preparer_approver"],
            "target": [1, 0],
        })

        cleaned = drop_label_columns(df)

        assert list(cleaned.columns) == ["feature_a"]

    def test_normalizes_user_persona_variants(self):
        import pandas as pd

        df = pd.DataFrame({
            "feature_a": [1, 2],
            "user_persona": ["senior_accoutant", "utomated_system"],
        })

        cleaned = drop_label_columns(df)

        assert cleaned["user_persona"].tolist() == [
            "senior_accountant",
            "automated_system",
        ]


class TestPrepareTrainingFeatures:
    def test_excludes_sparse_feature_columns_from_groups(self, simple_groups):
        import pandas as pd

        groups = FeatureGroups(
            numeric=["f1"],
            categorical_low=["user_persona", "cost_center", "tax_code"],
        )
        df = pd.DataFrame({
            "f1": [1.0, 2.0, 3.0, 4.0],
            "user_persona": ["maanger", "controller", "utomated_system", "manager"],
            "cost_center": [None, None, None, "CC100"],
            "tax_code": [None, None, None, None],
        })

        cleaned, adjusted_groups, report = prepare_training_features(df, groups)

        assert adjusted_groups is not None
        assert adjusted_groups.categorical_low == ["user_persona"]
        assert "cost_center" not in cleaned.columns
        assert "tax_code" not in cleaned.columns
        assert report.sparse_dropped_columns == ["cost_center", "tax_code"]
