"""vae_wrapper 테스트 — VAE sklearn 호환성."""

from __future__ import annotations

import numpy as np
import pytest

from src.preprocessing.vae_wrapper import VAEDetector


@pytest.fixture()
def small_data():
    """VAE 테스트용 소규모 데이터."""
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, size=(60, 5)).astype(np.float32)
    y = np.zeros(60, dtype=int)
    y[:3] = 1  # 이상치 3건
    return X, y


class TestVAEDetector:
    """VAEDetector sklearn 호환성 검증."""

    def test_fit_returns_self(self, small_data):
        """fit이 self를 반환하는지 (sklearn 규약)."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        result = det.fit(X, y)
        assert result is det

    def test_predict_shape(self, small_data):
        """predict 출력 shape."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)
        pred = det.predict(X)
        assert pred.shape == (len(X),)

    def test_predict_binary(self, small_data):
        """predict 출력이 0/1인지."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)
        pred = det.predict(X)
        assert set(np.unique(pred)).issubset({0, 1})

    def test_predict_proba_shape(self, small_data):
        """predict_proba 출력이 (n, 2) shape인지."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)
        proba = det.predict_proba(X)
        assert proba.shape == (len(X), 2)

    def test_predict_proba_sums_to_one(self, small_data):
        """predict_proba 각 행의 합이 1인지."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)
        proba = det.predict_proba(X)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_classes_attribute(self, small_data):
        """fit 후 classes_ 속성이 [0, 1]인지."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)
        assert hasattr(det, "classes_")
        np.testing.assert_array_equal(det.classes_, [0, 1])

    def test_fit_unsupervised(self, small_data):
        """y=None 비지도 모드 동작."""
        X, _ = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X)  # y=None
        pred = det.predict(X)
        assert len(pred) == len(X)

    def test_serialization(self, small_data):
        """__getstate__/__setstate__ 직렬화 라운드트립."""
        X, y = small_data
        det = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det.fit(X, y)

        # 직렬화 → 역직렬화
        state = det.__getstate__()
        det2 = VAEDetector(latent_dim=8, epochs=5, device="cpu")
        det2.__setstate__(state)

        # threshold가 보존되는지 검증 (reconstruction error는 eval 모드에서
        # reparameterize 노이즈 때문에 미세 차이 발생 가능 → threshold 비교)
        assert hasattr(det2, "threshold_")
        assert det2.threshold_ == det.threshold_
        assert hasattr(det2, "model_")

        # predict_proba가 동작하는지 (shape 검증)
        proba = det2.predict_proba(X)
        assert proba.shape == (len(X), 2)
