"""VAEDetector — sklearn BaseEstimator 호환 VAE 래퍼.

Why: sklearn Pipeline/GridSearchCV에 VAE를 통합하려면
fit/predict/predict_proba 인터페이스가 필요하다.
torch 모델을 joblib 직렬화 가능하도록 state_dict 바이트로 변환한다.
"""

from __future__ import annotations

import io
import logging

import numpy as np
import torch
from sklearn.base import BaseEstimator

from src.preprocessing.vae_model import AuditVAE, vae_loss

logger = logging.getLogger(__name__)


class VAEDetector(BaseEstimator):
    """sklearn 호환 VAE 이상 탐지기."""

    def __init__(
        self,
        latent_dim: int = 8,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
        contamination: float = 0.02,
        device: str = "auto",
    ):
        self.latent_dim = latent_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.contamination = contamination
        self.device = device

    def _resolve_device(self) -> str:
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def fit(self, X, y=None):
        X = np.array(X, dtype=np.float32)
        # 지도 모드: 정상 데이터(y==0)만으로 학습
        if y is not None:
            y = np.asarray(y)
            X = X[y == 0]

        device = self._resolve_device()
        self.model_ = AuditVAE(X.shape[1], self.latent_dim).to(device)
        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        tensor = torch.from_numpy(X).to(device)

        self.model_.train()
        for _ in range(self.epochs):
            for start in range(0, len(tensor), self.batch_size):
                batch = tensor[start : start + self.batch_size]
                recon, mu, logvar = self.model_(batch)
                loss = vae_loss(recon, batch, mu, logvar)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        # threshold 결정: 학습 데이터의 재구성 오차 분포 기준
        errors = self._compute_errors(X, device)
        percentile = (1 - self.contamination) * 100
        self.threshold_ = float(np.percentile(errors, percentile))
        self.classes_ = np.array([0, 1])
        return self

    def _compute_errors(self, X: np.ndarray, device: str) -> np.ndarray:
        """배치 단위 MSE 재구성 오차 계산.

        Why: forward()의 reparameterize는 랜덤 샘플링이므로 추론마다 결과가 달라진다.
        deterministic 추론을 위해 encode → mu → decode 경로를 직접 사용한다.
        """
        self.model_.eval()
        self.model_.to(device)
        errors = []
        tensor = torch.from_numpy(np.array(X, dtype=np.float32)).to(device)
        with torch.no_grad():
            for start in range(0, len(tensor), self.batch_size):
                batch = tensor[start : start + self.batch_size]
                mu, _ = self.model_.encode(batch)
                recon = self.model_.decode(mu)
                mse = ((recon - batch) ** 2).mean(dim=1)
                errors.append(mse.cpu().numpy())
        return np.concatenate(errors)

    def predict(self, X) -> np.ndarray:
        device = self._resolve_device()
        errors = self._compute_errors(np.array(X, dtype=np.float32), device)
        return (errors > self.threshold_).astype(int)

    def predict_proba(self, X) -> np.ndarray:
        """sigmoid((error - threshold) / scale) → [P(정상), P(이상)]."""
        device = self._resolve_device()
        errors = self._compute_errors(np.array(X, dtype=np.float32), device)
        scale = max(self.threshold_ * 0.1, 1e-8)
        prob_anomaly = 1.0 / (1.0 + np.exp(-(errors - self.threshold_) / scale))
        return np.column_stack([1 - prob_anomaly, prob_anomaly])

    def __getstate__(self):
        """joblib 직렬화: torch 모델 → state_dict bytes."""
        state = self.__dict__.copy()
        if "model_" in state:
            buf = io.BytesIO()
            torch.save(state["model_"].state_dict(), buf)
            state["_model_bytes"] = buf.getvalue()
            state["_input_dim"] = state["model_"].input_dim
            del state["model_"]
        return state

    def __setstate__(self, state):
        """joblib 역직렬화: bytes → torch 모델 복원."""
        if "_model_bytes" in state:
            model = AuditVAE(state["_input_dim"], state["latent_dim"])
            buf = io.BytesIO(state["_model_bytes"])
            model.load_state_dict(torch.load(buf, weights_only=True))
            model.eval()
            state["model_"] = model
            del state["_model_bytes"], state["_input_dim"]
        self.__dict__.update(state)
