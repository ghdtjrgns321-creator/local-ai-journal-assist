"""StackingEnsemble unit tests for the Ridge(positive=True) meta-learner."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.utils.validation import check_is_fitted

from src.detection.constants import STACKING_BASE_MODELS
from src.preprocessing.stacking import StackingEnsemble


@pytest.fixture()
def score_matrix() -> np.ndarray:
    """(100, len(STACKING_BASE_MODELS)) synthetic score matrix in [0, 1]."""
    rng = np.random.default_rng(42)
    return rng.uniform(0, 1, size=(100, len(STACKING_BASE_MODELS)))


@pytest.fixture()
def labels() -> np.ndarray:
    """100 binary labels with 20 positive samples."""
    rng = np.random.default_rng(42)
    y = np.zeros(100, dtype=int)
    y[rng.choice(100, 20, replace=False)] = 1
    return y


@pytest.fixture()
def fitted_ensemble(score_matrix, labels) -> StackingEnsemble:
    """A fitted StackingEnsemble instance."""
    ens = StackingEnsemble(alpha=1.0, random_state=42)
    ens.fit(score_matrix, labels)
    return ens


class TestFit:
    def test_returns_self(self, score_matrix, labels):
        ens = StackingEnsemble()
        result = ens.fit(score_matrix, labels)
        assert result is ens

    def test_is_fitted(self, fitted_ensemble):
        check_is_fitted(fitted_ensemble, "meta_")

    def test_n_features_in(self, fitted_ensemble):
        assert fitted_ensemble.n_features_in_ == len(STACKING_BASE_MODELS)


class TestPredictProba:
    def test_shape(self, fitted_ensemble, score_matrix):
        proba = fitted_ensemble.predict_proba(score_matrix)
        assert proba.shape == (100, 2)

    def test_range_0_1(self, fitted_ensemble, score_matrix):
        proba = fitted_ensemble.predict_proba(score_matrix)
        assert np.all(proba >= 0.0)
        assert np.all(proba <= 1.0)

    def test_columns_sum_to_1(self, fitted_ensemble, score_matrix):
        proba = fitted_ensemble.predict_proba(score_matrix)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0)

    def test_not_fitted_raises(self, score_matrix):
        from sklearn.exceptions import NotFittedError

        ens = StackingEnsemble()
        with pytest.raises(NotFittedError):
            ens.predict_proba(score_matrix)

    def test_wrong_column_count_raises(self, labels):
        ens = StackingEnsemble()
        wrong_x = np.random.default_rng(42).uniform(0, 1, size=(100, 5))
        with pytest.raises(ValueError, match="불일치"):
            ens.fit(wrong_x, labels)


class TestPredict:
    def test_binary_output(self, fitted_ensemble, score_matrix):
        pred = fitted_ensemble.predict(score_matrix)
        assert set(np.unique(pred)).issubset({0, 1})

    def test_shape(self, fitted_ensemble, score_matrix):
        pred = fitted_ensemble.predict(score_matrix)
        assert pred.shape == (100,)


class TestFeatureWeights:
    def test_all_non_negative(self, fitted_ensemble):
        weights = fitted_ensemble.feature_weights
        for name, weight in weights.items():
            assert weight >= 0.0, f"{name} weight was negative: {weight}"

    def test_length_matches_base_models(self, fitted_ensemble):
        weights = fitted_ensemble.feature_weights
        assert len(weights) == len(STACKING_BASE_MODELS)

    def test_keys_are_track_names(self, fitted_ensemble):
        weights = fitted_ensemble.feature_weights
        assert list(weights.keys()) == list(STACKING_BASE_MODELS)


class TestSerialization:
    def test_joblib_roundtrip(self, fitted_ensemble, score_matrix, tmp_path):
        import joblib

        path = tmp_path / "stacking.pkl"
        joblib.dump(fitted_ensemble, path)
        loaded = joblib.load(path)
        original = fitted_ensemble.predict_proba(score_matrix)
        restored = loaded.predict_proba(score_matrix)
        np.testing.assert_array_equal(original, restored)
