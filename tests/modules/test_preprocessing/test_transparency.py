"""전처리 투명성 메타데이터 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.preprocessing.transparency import capture_preprocessing_metadata


class TestCaptureMetadata:
    """전처리 전/후 비교 메타데이터 검증."""

    def _make_pipeline(self) -> Pipeline:
        return Pipeline([
            ("preprocessor", SimpleImputer(strategy="mean")),
            ("scaler", StandardScaler()),
        ])

    def _make_data(self) -> pd.DataFrame:
        return pd.DataFrame({
            "a": [1.0, np.nan, 3.0, 4.0, 5.0],
            "b": [10.0, 20.0, np.nan, 40.0, 50.0],
        })

    def test_returns_dict(self):
        pipe = self._make_pipeline()
        df = self._make_data()
        pipe.fit(df)
        result = capture_preprocessing_metadata(pipe, df, ["a", "b"])
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        pipe = self._make_pipeline()
        df = self._make_data()
        pipe.fit(df)
        result = capture_preprocessing_metadata(pipe, df, ["a", "b"])
        for key in ("steps", "before_stats", "after_stats", "n_features_in", "n_features_out"):
            assert key in result, f"missing key: {key}"

    def test_before_stats_has_columns(self):
        pipe = self._make_pipeline()
        df = self._make_data()
        pipe.fit(df)
        result = capture_preprocessing_metadata(pipe, df, ["a", "b"])
        for col in ("a", "b"):
            assert col in result["before_stats"]
            assert "missing_rate" in result["before_stats"][col]

    def test_steps_extraction(self):
        pipe = self._make_pipeline()
        df = self._make_data()
        pipe.fit(df)
        result = capture_preprocessing_metadata(pipe, df, ["a", "b"])
        step_names = [s["name"] for s in result["steps"]]
        assert "preprocessor" in step_names
