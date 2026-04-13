"""BiLSTMClassifier — sklearn BaseEstimator 호환 BiLSTM 래퍼.

Why: SequenceDetector가 preprocessor + BiLSTM을 독립적으로 관리하되,
BiLSTM 자체는 sklearn의 get_params/set_params와 joblib 직렬화를 지원해야 한다.

핵심 차이점 (vs FTTransformerClassifier):
- fit(X_3d, y, mask) — 이미 3D로 변환된 시퀀스를 직접 받는다.
- 시퀀스 빌딩은 SequenceDetector가 담당 (이 래퍼는 순수 학습/추론만).
"""

from __future__ import annotations

import io
import logging

import numpy as np
import torch
import torch.nn as nn
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.utils.validation import check_is_fitted

from src.preprocessing.bilstm_model import AuditBiLSTM

logger = logging.getLogger(__name__)


class BiLSTMClassifier(BaseEstimator, ClassifierMixin):
    """sklearn 호환 BiLSTM 시퀀스 분류기."""

    def __init__(
        self,
        hidden_size: int = 64,
        dropout: float = 0.3,
        num_layers: int = 1,
        epochs: int = 50,
        batch_size: int = 256,
        lr: float = 1e-3,
        device: str = "auto",
    ):
        self.hidden_size = hidden_size
        self.dropout = dropout
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.device = device

    def _resolve_device(self) -> str:
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> BiLSTMClassifier:
        """3D 시퀀스 입력으로 BiLSTM 학습.

        Args:
            X: (n_windows, seq_len, n_features) float32
            y: (n_windows,) int64
            mask: (n_windows, seq_len) bool — None이면 전부 유효로 간주
        """
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.int64)

        device = self._resolve_device()
        # Why: input_size는 전처리 후 실제 피처 수 — 하드코딩 금지
        self.input_size_ = X.shape[2]

        self.model_ = AuditBiLSTM(
            input_size=self.input_size_,
            hidden_size=self.hidden_size,
            dropout=self.dropout,
            num_layers=self.num_layers,
        ).to(device)

        optimizer = torch.optim.Adam(self.model_.parameters(), lr=self.lr)
        # Why: 불균형 데이터 대응 — 양성 클래스에 높은 가중치
        counts = np.bincount(y, minlength=2).astype(np.float32)
        weights = torch.tensor([1.0 / max(c, 1) for c in counts], device=device)
        criterion = nn.CrossEntropyLoss(weight=weights)

        X_t = torch.from_numpy(X).to(device)
        y_t = torch.from_numpy(y).to(device)
        mask_t = torch.from_numpy(mask).to(device) if mask is not None else None

        self.model_.train()
        for _ in range(self.epochs):
            # Why: 에폭마다 셔플하여 윈도우 순서 편향 제거
            perm = torch.randperm(len(X_t), device=device)
            for start in range(0, len(X_t), self.batch_size):
                idx = perm[start : start + self.batch_size]
                xb = X_t[idx]
                yb = y_t[idx]
                mb = mask_t[idx] if mask_t is not None else None
                logits = self.model_(xb, mb)
                loss = criterion(logits, yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        self.model_.eval()
        self.classes_ = np.array([0, 1])
        return self

    def predict(self, X: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
        """클래스 예측 (argmax)."""
        check_is_fitted(self, ["model_"])
        proba = self.predict_proba(X, mask)
        return np.argmax(proba, axis=1)

    def predict_proba(
        self, X: np.ndarray, mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """softmax(logits) → [P(정상), P(이상)]."""
        check_is_fitted(self, ["model_"])
        device = self._resolve_device()
        X = np.asarray(X, dtype=np.float32)

        self.model_.eval()
        results = []
        with torch.no_grad():
            for start in range(0, len(X), self.batch_size):
                end = start + self.batch_size
                batch = torch.from_numpy(X[start:end]).to(device)
                mb = None
                if mask is not None:
                    mb = torch.from_numpy(mask[start:end]).to(device)
                logits = self.model_(batch, mb)
                proba = torch.softmax(logits, dim=1)
                results.append(proba.cpu().numpy())
        return np.concatenate(results)

    def score_samples(
        self, X: np.ndarray, mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """이상 확률(클래스 1) 반환 — 앙상블 결합용."""
        return self.predict_proba(X, mask)[:, 1]

    def get_attention_weights(
        self, X: np.ndarray, mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """시퀀스 시점별 Attention 가중치 반환 — Explainability용 public API.

        Why: BiLSTM이 16-step 윈도우의 어느 시점에 주목했는지 설명하여
             "같은 사용자가 수요일 오후 3시에 입력한 3건이 집중 가중됐다"
             같은 감사 증거를 제시한다. Additive Attention weights는
             forward 내부에서 이미 계산되어 `self._attn_weights`에 저장됨.

        Returns:
            (n_windows, seq_len) ndarray. 각 행의 합은 1 (softmax).
            패딩 위치는 mask 적용으로 0.
        """
        check_is_fitted(self, ["model_"])
        device = self._resolve_device()
        X = np.asarray(X, dtype=np.float32)

        self.model_.eval()
        weights_list: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(X), self.batch_size):
                end = start + self.batch_size
                batch = torch.from_numpy(X[start:end]).to(device)
                mb = None
                if mask is not None:
                    mb = torch.from_numpy(mask[start:end]).to(device)
                # Why: forward()가 attention을 self._attn_weights에 저장
                _ = self.model_(batch, mb)
                weights_list.append(
                    self.model_._attn_weights.detach().cpu().numpy(),
                )
        return np.concatenate(weights_list, axis=0)

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
            model = AuditBiLSTM(
                input_size=state["input_size_"],
                hidden_size=state["hidden_size"],
                dropout=state["dropout"],
                num_layers=state["num_layers"],
            )
            buf = io.BytesIO(state["_model_bytes"])
            # Why: CUDA에서 저장한 모델을 CPU 환경에서 불러올 때 map_location 필수
            model.load_state_dict(torch.load(buf, weights_only=True, map_location="cpu"))
            model.eval()
            state["model_"] = model
            del state["_model_bytes"]
        self.__dict__.update(state)
