"""FTTransformerClassifier — sklearn BaseEstimator 호환 FT-Transformer 래퍼.

Why: sklearn Pipeline/GridSearchCV에 FT-Transformer를 통합하려면
fit/predict/predict_proba 인터페이스가 필요하다.
torch 모델을 joblib 직렬화 가능하도록 state_dict 바이트로 변환한다.
"""

from __future__ import annotations

import io
import logging

import numpy as np
import torch
import torch.nn as nn
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.utils.validation import check_is_fitted

from src.preprocessing.ft_model import AuditFTTransformer

logger = logging.getLogger(__name__)


class FTTransformerClassifier(BaseEstimator, ClassifierMixin):
    """sklearn 호환 FT-Transformer 지도학습 분류기."""

    def __init__(
        self,
        d_token: int = 64,
        n_layers: int = 2,
        n_heads: int = 4,
        d_ff: int = 128,
        dropout: float = 0.1,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
        device: str = "auto",
    ):
        self.d_token = d_token
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.device = device

    def _resolve_device(self) -> str:
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def fit(self, X, y):
        """CrossEntropyLoss로 지도학습. y는 0/1 이진 라벨."""
        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.int64)

        device = self._resolve_device()
        # Why: n_features는 전처리 후 실제 차원 — 하드코딩 금지
        self.n_features_ = X.shape[1]
        self.model_ = AuditFTTransformer(
            n_features=self.n_features_,
            d_token=self.d_token,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            d_ff=self.d_ff,
            dropout=self.dropout,
        ).to(device)

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        # Why: 불균형 데이터 대응 — 양성 클래스에 높은 가중치
        counts = np.bincount(y, minlength=2).astype(np.float32)
        weights = torch.tensor([1.0 / max(c, 1) for c in counts], device=device)
        criterion = nn.CrossEntropyLoss(weight=weights)

        X_t = torch.from_numpy(X).to(device)
        y_t = torch.from_numpy(y).to(device)

        self.model_.train()
        for _ in range(self.epochs):
            # Why: 에폭마다 셔플하여 시계열 정렬 데이터의 배치 순서 편향 제거
            perm = torch.randperm(len(X_t), device=device)
            X_shuffled = X_t[perm]
            y_shuffled = y_t[perm]
            for start in range(0, len(X_shuffled), self.batch_size):
                xb = X_shuffled[start : start + self.batch_size]
                yb = y_shuffled[start : start + self.batch_size]
                logits = self.model_(xb)
                loss = criterion(logits, yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        self.model_.eval()  # Why: Dropout 비활성화 — 추론 시 결정적 결과 보장
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, X) -> np.ndarray:
        check_is_fitted(self, ["model_"])
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    def predict_proba(self, X) -> np.ndarray:
        """softmax(logits) → [P(정상), P(이상)]."""
        check_is_fitted(self, ["model_"])
        device = self._resolve_device()
        X = np.array(X, dtype=np.float32)
        self.model_.eval()
        results = []
        with torch.no_grad():
            for start in range(0, len(X), self.batch_size):
                batch = torch.from_numpy(X[start : start + self.batch_size]).to(device)
                logits = self.model_(batch)
                proba = torch.softmax(logits, dim=1)
                results.append(proba.cpu().numpy())
        return np.concatenate(results)

    def score_samples(self, X) -> np.ndarray:
        """이상 확률(클래스 1) 반환 — 앙상블 결합용."""
        return self.predict_proba(X)[:, 1]

    def get_attention_weights(self, X) -> np.ndarray:
        """[CLS] 토큰이 각 피처에 준 attention 가중치 반환 — Explainability용.

        Why: self-attention이 "어느 피처 조합을 중요하게 봤는지"를 드러낸다.
             전체 layer의 [CLS]→피처 attention을 평균하여 피처별 기여도로 변환한다.
             (B, F+1, F+1) 중 [CLS]=0번 행의 [1:] 슬라이스가 피처 기여도.

        Returns:
            (n_samples, n_features) ndarray. 각 행 합은 1에 가까움 (softmax 후).
        """
        check_is_fitted(self, ["model_"])
        device = self._resolve_device()
        X = np.array(X, dtype=np.float32)
        self.model_.eval()
        results: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(X), self.batch_size):
                batch = torch.from_numpy(
                    X[start : start + self.batch_size],
                ).to(device)
                _, attentions = self.model_.forward_with_attention(batch)
                # Why: layer 평균 → (B, F+1, F+1). [CLS] 행의 피처 토큰(1:) 추출
                stacked = torch.stack(attentions, dim=0).mean(dim=0)
                cls_to_features = stacked[:, 0, 1:]  # (B, F)
                results.append(cls_to_features.cpu().numpy())
        return np.concatenate(results, axis=0)

    def __getstate__(self):
        """joblib 직렬화: torch 모델 → state_dict bytes."""
        state = self.__dict__.copy()
        if "model_" in state:
            buf = io.BytesIO()
            torch.save(state["model_"].state_dict(), buf)
            state["_model_bytes"] = buf.getvalue()
            del state["model_"]
        return state

    def __setstate__(self, state):
        """joblib 역직렬화: bytes → torch 모델 복원."""
        if "_model_bytes" in state:
            model = AuditFTTransformer(
                n_features=state["n_features_"],
                d_token=state["d_token"],
                n_layers=state["n_layers"],
                n_heads=state["n_heads"],
                d_ff=state["d_ff"],
                dropout=state["dropout"],
            )
            buf = io.BytesIO(state["_model_bytes"])
            model.load_state_dict(torch.load(buf, weights_only=True))
            model.eval()
            state["model_"] = model
            del state["_model_bytes"]
        self.__dict__.update(state)
