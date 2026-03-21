"""VAE sklearn BaseEstimator 호환 래퍼.

Why: PyTorch VAE를 sklearn Pipeline에 통합하려면 fit/predict/predict_proba
인터페이스가 필요하다. reconstruction error 기반으로 이상 판정.
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin

logger = logging.getLogger(__name__)


class VAEDetector(BaseEstimator, ClassifierMixin):
    """VAE를 sklearn Pipeline에 통합하는 래퍼.

    fit: 정상 데이터(y==0 or 전체)로 VAE 학습
    predict: reconstruction error 기반 이상 판정 (0=정상, 1=이상)
    predict_proba: reconstruction error를 0~1 확률로 변환
    """

    def __init__(
        self,
        latent_dim: int = 32,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
        contamination: float = 0.01,
        device: str = "auto",
    ):
        self.latent_dim = latent_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.contamination = contamination
        self.device = device

    def _resolve_device(self) -> str:
        """auto → cuda/cpu 자동 판별."""
        import torch

        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def fit(self, X, y=None):
        """VAE 학습. y=None이면 전체 데이터, y 있으면 정상(y==0)만 사용."""
        import torch
        from torch.utils.data import DataLoader, TensorDataset

        from src.preprocessing.vae_model import AuditVAE, vae_loss

        device = self._resolve_device()
        X = np.asarray(X, dtype=np.float32)

        # 반지도: y가 있으면 정상 데이터만 선택
        if y is not None:
            y_arr = np.asarray(y)
            X_train = X[y_arr == 0]
        else:
            X_train = X

        input_dim = X_train.shape[1]
        self.model_ = AuditVAE(input_dim, self.latent_dim).to(device)
        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)

        dataset = TensorDataset(torch.from_numpy(X_train))
        loader = DataLoader(
            dataset, batch_size=self.batch_size, shuffle=True, drop_last=False,
        )

        # 학습 루프
        self.model_.train()
        for epoch in range(self.epochs):
            total_loss = 0.0
            for (batch,) in loader:
                batch = batch.to(device)
                recon, mu, logvar = self.model_(batch)
                loss = vae_loss(recon, batch, mu, logvar)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            if (epoch + 1) % 10 == 0:
                avg = total_loss / len(loader)
                logger.debug("VAE epoch %d/%d, loss=%.4f", epoch + 1, self.epochs, avg)

        # 학습 데이터의 reconstruction error로 threshold 결정
        errors = self._compute_errors(X_train, device)
        self.threshold_ = float(np.percentile(
            errors, 100 * (1 - self.contamination),
        ))

        # VRAM 정리
        if device == "cuda":
            torch.cuda.empty_cache()

        self.classes_ = np.array([0, 1])
        return self

    def _compute_errors(self, X: np.ndarray, device: str) -> np.ndarray:
        """reconstruction error(MSE) 배치 계산."""
        import torch

        self.model_.eval()
        tensor = torch.from_numpy(X.astype(np.float32)).to(device)
        with torch.no_grad():
            recon, _, _ = self.model_(tensor)
            errors = torch.mean((tensor - recon) ** 2, dim=1)
        return errors.cpu().numpy()

    def predict(self, X) -> np.ndarray:
        """이상 판정: 0=정상, 1=이상."""
        errors = self._compute_errors(
            np.asarray(X, dtype=np.float32),
            self._resolve_device(),
        )
        return (errors > self.threshold_).astype(int)

    def predict_proba(self, X) -> np.ndarray:
        """reconstruction error를 0~1 확률로 변환.

        Why: cross_val_score의 scoring='roc_auc'는 predict_proba 필요.
        sigmoid(error - threshold)로 변환.
        """
        errors = self._compute_errors(
            np.asarray(X, dtype=np.float32),
            self._resolve_device(),
        )
        # sigmoid 변환: threshold 기준으로 0.5가 되도록
        scale = max(self.threshold_ * 0.5, 1e-6)
        proba_anomaly = 1.0 / (1.0 + np.exp(-(errors - self.threshold_) / scale))
        proba_normal = 1.0 - proba_anomaly
        return np.column_stack([proba_normal, proba_anomaly])

    def __getstate__(self):
        """joblib 직렬화를 위한 state 추출 — torch 모델은 state_dict로."""
        state = self.__dict__.copy()
        if "model_" in state:
            import torch
            import io
            buf = io.BytesIO()
            torch.save(state["model_"].state_dict(), buf)
            state["_model_state_bytes"] = buf.getvalue()
            del state["model_"]
        return state

    def __setstate__(self, state):
        """joblib 역직렬화 — state_dict에서 torch 모델 복원."""
        model_bytes = state.pop("_model_state_bytes", None)
        self.__dict__.update(state)
        if model_bytes is not None:
            import torch
            import io
            from src.preprocessing.vae_model import AuditVAE

            # input_dim은 threshold_에서 역추정 불가 → state_dict에서 추출
            buf = io.BytesIO(model_bytes)
            sd = torch.load(buf, weights_only=True)
            input_dim = sd["encoder.0.weight"].shape[1]
            model = AuditVAE(input_dim, self.latent_dim)
            model.load_state_dict(sd)
            self.model_ = model
