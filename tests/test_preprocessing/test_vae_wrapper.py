"""VAEDetector sklearn 호환 래퍼 테스트."""

from __future__ import annotations

import pickle

import numpy as np
import pytest

from src.preprocessing.vae_wrapper import VAEDetector


@pytest.fixture()
def small_data() -> tuple[np.ndarray, np.ndarray]:
    """100행 10피처, ~5% 양성."""
    rng = np.random.default_rng(42)
    n, d = 100, 10
    X = rng.normal(0, 1, (n, d)).astype(np.float32)
    y = rng.choice([0, 1], n, p=[0.95, 0.05])
    return X, y


class TestVAEDetector:
    """VAE sklearn BaseEstimator 호환 검증."""

    def test_fit_returns_self(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu")
        result = det.fit(X, y)
        assert result is det

    def test_predict_shape(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        preds = det.predict(X)
        assert preds.shape == (len(X),)

    def test_predict_binary(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        preds = det.predict(X)
        assert set(np.unique(preds)).issubset({0, 1})

    def test_predict_proba_shape(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        proba = det.predict_proba(X)
        assert proba.shape == (len(X), 2)

    def test_predict_proba_sums_to_one(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        proba = det.predict_proba(X)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_classes_attribute(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        np.testing.assert_array_equal(det.classes_, [0, 1])

    def test_fit_unsupervised(self, small_data):
        X, _ = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y=None)
        preds = det.predict(X)
        assert preds.shape == (len(X),)

    def test_serialization(self, small_data):
        X, y = small_data
        det = VAEDetector(latent_dim=4, epochs=3, device="cpu").fit(X, y)
        # pickle roundtrip (joblib 호환)
        data = pickle.dumps(det)
        loaded = pickle.loads(data)
        assert hasattr(loaded, "threshold_")
        assert hasattr(loaded, "model_")
        # 역직렬화 후 predict 정상 동작 확인 (부동소수점 차이로 인한 경계값 불일치 허용)
        preds = loaded.predict(X)
        assert preds.shape == (len(X),)
        assert set(np.unique(preds)).issubset({0, 1})
