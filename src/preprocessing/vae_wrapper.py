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
from sklearn.utils.validation import check_is_fitted

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
        # Why: 비지도 학습기는 y에 눈을 가려야 한다.
        #      contamination + 오토인코딩 병목이 자체적으로 이상치를 튕겨냄.
        #      y는 외부(UnsupervisedDetector)에서 평가 전용으로만 사용.
        X = np.array(X, dtype=np.float32)

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

    def _compute_errors_per_feature(self, X: np.ndarray, device: str) -> np.ndarray:
        """배치 단위 피처별 MSE 재구성 오차 계산. 결과 shape=(N, D).

        Why: 감사 도메인에서 "이 전표가 왜 비정상인가"를 설명하려면
             전체 MSE만으로는 부족하고, 어느 피처에서 오차가 컸는지가 필요하다.
             VAE forward에서 이미 recon과 x 모두 가지고 있으므로 mean 직전 단계에서
             분기하여 (N, D) 행렬로 반환한다.
        """
        self.model_.eval()
        self.model_.to(device)
        per_feature: list[np.ndarray] = []
        tensor = torch.from_numpy(np.array(X, dtype=np.float32)).to(device)
        with torch.no_grad():
            for start in range(0, len(tensor), self.batch_size):
                batch = tensor[start : start + self.batch_size]
                mu, _ = self.model_.encode(batch)
                recon = self.model_.decode(mu)
                # Why: mean(dim=1)을 적용하지 않고 (batch, D) 그대로 보관
                sq = (recon - batch) ** 2
                per_feature.append(sq.cpu().numpy())
        return np.concatenate(per_feature, axis=0)

    def _compute_errors(self, X: np.ndarray, device: str) -> np.ndarray:
        """배치 단위 MSE 재구성 오차 계산 (행 평균).

        Why: 기존 호출자(threshold/score_samples)와의 호환을 위해 유지.
             내부적으로는 _compute_errors_per_feature를 행 평균하여 위임.
        """
        return self._compute_errors_per_feature(X, device).mean(axis=1)

    def predict(self, X) -> np.ndarray:
        # Why: fit() 전 호출 시 model_/threshold_ 없어 cryptic 에러 → 명확한 안내
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        errors = self._compute_errors(np.array(X, dtype=np.float32), device)
        return (errors > self.threshold_).astype(int)

    def score_samples(self, X) -> np.ndarray:
        """재구성 오차(MSE) 배열 반환 — 앙상블 결합용 public API.

        Why: UnsupervisedDetector가 raw 오차로 ECDF 정규화하므로
             predict_proba(sigmoid 적용)가 아닌 원시 MSE가 필요.
        """
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        return self._compute_errors(np.array(X, dtype=np.float32), device)

    def score_samples_per_feature(self, X) -> np.ndarray:
        """피처별 재구성 오차 행렬 반환 — 설명력(Explainability) 용 public API.

        Why: 감사 도메인에서 "왜 이 전표가 비정상인지"를 정량적 증거로 제시하려면
             전체 MSE 스칼라가 아닌 피처별 기여도가 필요하다.
             score_samples()는 본 함수의 row-wise mean과 동일하다.

        Returns:
            (N, D) ndarray. N=입력 행 수, D=전처리 후 피처 수.
        """
        check_is_fitted(self, ["model_", "threshold_"])
        device = self._resolve_device()
        return self._compute_errors_per_feature(
            np.array(X, dtype=np.float32), device,
        )

    def predict_proba(self, X) -> np.ndarray:
        """sigmoid((error - threshold) / scale) → [P(정상), P(이상)]."""
        check_is_fitted(self, ["model_", "threshold_"])
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
