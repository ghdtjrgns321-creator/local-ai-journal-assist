"""pipeline_builder 테스트 — Pipeline build + fit/predict."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.pipeline_builder import (
    build_all_pipelines,
    build_if_pipeline,
    build_xgb_pipeline,
)


@pytest.fixture()
def simple_groups() -> FeatureGroups:
    """최소 피처 그룹."""
    return FeatureGroups(
        numeric=["debit_amount", "credit_amount"],
        categorical_high=[],
        categorical_low=["source"],
        boolean=["is_weekend"],
        ordinal=["description_quality"],
        excluded=["document_id"],
    )


@pytest.fixture()
def simple_data():
    """최소 테스트 데이터."""
    rng = np.random.default_rng(42)
    n = 80
    df = pd.DataFrame({
        "debit_amount": rng.exponential(100_000, size=n),
        "credit_amount": rng.exponential(50_000, size=n),
        "source": rng.choice(["SAP", "ORACLE", "MANUAL"], size=n),
        "is_weekend": rng.choice([True, False], size=n),
        "description_quality": rng.choice(["missing", "poor", "normal"], size=n),
    })
    y = pd.Series(rng.choice([0, 1], size=n, p=[0.9, 0.1]))
    return df, y


class TestBuildXgbPipeline:
    """XGBoost Pipeline 빌드 검증."""

    def test_builds_successfully(self, simple_groups):
        """Pipeline 객체가 생성되는지."""
        pipe = build_xgb_pipeline(simple_groups)
        assert pipe is not None
        assert len(pipe.steps) == 2  # preprocessor + classifier

    def test_fit_predict(self, simple_groups, simple_data):
        """fit → predict 동작하는지."""
        df, y = simple_data
        pipe = build_xgb_pipeline(simple_groups)
        pipe.fit(df, y)
        pred = pipe.predict(df)
        assert len(pred) == len(df)
        assert set(pred).issubset({0, 1})


class TestBuildIfPipeline:
    """Isolation Forest Pipeline 빌드 검증."""

    def test_builds_successfully(self, simple_groups):
        """Pipeline 객체가 생성되는지."""
        pipe = build_if_pipeline(simple_groups)
        assert pipe is not None

    def test_fit_predict(self, simple_groups, simple_data):
        """fit → predict 동작하는지."""
        df, y = simple_data
        pipe = build_if_pipeline(simple_groups)
        pipe.fit(df)
        pred = pipe.predict(df)
        assert len(pred) == len(df)


class TestBuildAllPipelines:
    """build_all_pipelines 검증."""

    def test_returns_three_pipelines(self, simple_groups):
        """3개 Pipeline dict 반환."""
        pipes = build_all_pipelines(simple_groups)
        assert set(pipes.keys()) == {"xgb", "vae", "if"}

    def test_all_pipelines_have_preprocessor(self, simple_groups):
        """모든 Pipeline에 preprocessor 단계가 있는지."""
        pipes = build_all_pipelines(simple_groups)
        for name, pipe in pipes.items():
            assert "preprocessor" in pipe.named_steps, f"{name}에 preprocessor 없음"
