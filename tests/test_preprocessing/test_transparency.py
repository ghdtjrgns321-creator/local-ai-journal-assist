"""transparency 테스트 — 전처리 메타데이터 생성."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from src.preprocessing.transparency import capture_preprocessing_metadata


class TestCaptureMetadata:
    """capture_preprocessing_metadata 검증."""

    def _make_pipeline(self):
        """테스트용 간단 Pipeline."""
        preprocessor = ColumnTransformer([
            ("num", Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]), ["f1", "f2"]),
        ])
        return Pipeline([
            ("preprocessor", preprocessor),
            ("clf", DecisionTreeClassifier()),
        ])

    def _make_data(self):
        """테스트 데이터."""
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "f1": rng.normal(0, 1, 50),
            "f2": rng.normal(10, 5, 50),
        })
        y = rng.choice([0, 1], 50)
        return df, y

    def test_returns_dict(self):
        """dict 반환."""
        pipe = self._make_pipeline()
        df, y = self._make_data()
        pipe.fit(df, y)
        result = capture_preprocessing_metadata(pipe, df, ["f1", "f2"])
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        """필수 키가 포함되는지."""
        pipe = self._make_pipeline()
        df, y = self._make_data()
        pipe.fit(df, y)
        result = capture_preprocessing_metadata(pipe, df, ["f1", "f2"])
        assert "steps" in result
        assert "before_stats" in result
        assert "after_stats" in result
        assert "n_features_in" in result
        assert "n_features_out" in result

    def test_before_stats_has_columns(self):
        """before_stats에 컬럼별 통계가 있는지."""
        pipe = self._make_pipeline()
        df, y = self._make_data()
        pipe.fit(df, y)
        result = capture_preprocessing_metadata(pipe, df, ["f1", "f2"])
        assert "f1" in result["before_stats"]
        assert "missing_rate" in result["before_stats"]["f1"]

    def test_steps_extraction(self):
        """Pipeline 단계 이름이 추출되는지."""
        pipe = self._make_pipeline()
        df, y = self._make_data()
        pipe.fit(df, y)
        result = capture_preprocessing_metadata(pipe, df, ["f1", "f2"])
        step_names = [s["name"] for s in result["steps"]]
        assert "preprocessor" in step_names
