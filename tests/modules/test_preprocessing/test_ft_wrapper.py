"""FTTransformerClassifier sklearn 호환 래퍼 테스트."""

from __future__ import annotations

import pickle

import numpy as np
import pytest

from src.preprocessing.ft_wrapper import FTTransformerClassifier


@pytest.fixture()
def small_data() -> tuple[np.ndarray, np.ndarray]:
    """100행 10피처, ~10% 양성."""
    rng = np.random.default_rng(42)
    n, d = 100, 10
    X = rng.normal(0, 1, (n, d)).astype(np.float32)
    y = rng.choice([0, 1], n, p=[0.90, 0.10])
    return X, y


@pytest.fixture()
def fitted_model(small_data) -> FTTransformerClassifier:
    """학습 완료된 FT-Transformer."""
    X, y = small_data
    return FTTransformerClassifier(
        d_token=16, n_layers=1, n_heads=2, d_ff=32,
        epochs=2, batch_size=32, device="cpu",
    ).fit(X, y)


class TestFTTransformerClassifier:
    """FT-Transformer sklearn BaseEstimator 호환 검증."""

    def test_fit_returns_self(self, small_data):
        X, y = small_data
        clf = FTTransformerClassifier(
            d_token=16, n_layers=1, n_heads=2, d_ff=32,
            epochs=2, device="cpu",
        )
        result = clf.fit(X, y)
        assert result is clf

    def test_predict_shape(self, fitted_model, small_data):
        X, _ = small_data
        preds = fitted_model.predict(X)
        assert preds.shape == (len(X),)

    def test_predict_binary(self, fitted_model, small_data):
        X, _ = small_data
        preds = fitted_model.predict(X)
        assert set(np.unique(preds)).issubset({0, 1})

    def test_predict_proba_shape(self, fitted_model, small_data):
        X, _ = small_data
        proba = fitted_model.predict_proba(X)
        assert proba.shape == (len(X), 2)

    def test_predict_proba_sums_to_one(self, fitted_model, small_data):
        X, _ = small_data
        proba = fitted_model.predict_proba(X)
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_classes_attribute(self, fitted_model):
        np.testing.assert_array_equal(fitted_model.classes_, [0, 1])

    def test_score_samples(self, fitted_model, small_data):
        X, _ = small_data
        scores = fitted_model.score_samples(X)
        assert scores.shape == (len(X),)
        assert np.all((scores >= 0) & (scores <= 1))

    def test_n_features_dynamic(self, fitted_model, small_data):
        """n_features_는 입력 차원에서 동적으로 결정되어야 한다."""
        _, _ = small_data
        assert fitted_model.n_features_ == 10

    def test_serialization(self, fitted_model, small_data):
        X, _ = small_data
        data = pickle.dumps(fitted_model)
        loaded = pickle.loads(data)
        assert hasattr(loaded, "model_")
        assert hasattr(loaded, "n_features_")
        preds = loaded.predict(X)
        assert preds.shape == (len(X),)
        assert set(np.unique(preds)).issubset({0, 1})

    # ── Attention Explainability (묶음 1) ────────────────────

    def test_get_attention_weights_shape(self, fitted_model, small_data):
        X, _ = small_data
        weights = fitted_model.get_attention_weights(X)
        # Why: (n_samples, n_features) — [CLS] → 피처 attention
        assert weights.shape == (len(X), fitted_model.n_features_)

    def test_get_attention_weights_non_negative(self, fitted_model, small_data):
        X, _ = small_data
        weights = fitted_model.get_attention_weights(X)
        assert (weights >= 0).all()

    def test_forward_with_attention_returns_per_layer(self, fitted_model, small_data):
        import torch
        X, _ = small_data
        model = fitted_model.model_
        model.eval()
        with torch.no_grad():
            logits, attentions = model.forward_with_attention(
                torch.from_numpy(X).float(),
            )
        assert logits.shape == (len(X), 2)
        # Why: n_layers=1 설정이므로 attentions 리스트 길이는 1
        assert len(attentions) == 1
        # 각 attention shape: (batch, F+1, F+1) (CLS 포함)
        assert attentions[0].shape == (len(X), 11, 11)
