"""StackingEnsemble — sklearn BaseEstimator 호환 Stacking Meta-Learner.

Why: len(STACKING_BASE_MODELS)개 base model 점수를 Ridge(positive=True)로 결합하여 최종 anomaly_score 산출.
     Ridge 비음수 제약으로 다중공선성에 의한 음수 가중치 문제를 원천 차단.
     (Layer B ↔ ML Supervised 상관관계가 높아 일반 LR은 음수 계수 생성 가능
      → "ML이 부정이라 확신할수록 점수가 깎이는" 역설 방지)
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.base import BaseEstimator
from sklearn.linear_model import Ridge
from sklearn.utils.validation import check_is_fitted

from src.detection.constants import STACKING_BASE_MODELS

logger = logging.getLogger(__name__)


class StackingEnsemble(BaseEstimator):
    """Level 1 Meta-Learner — Ridge(positive=True) 비음수 제약.

    입력: (N, len(STACKING_BASE_MODELS)) base model 점수 행렬 (STACKING_BASE_MODELS 열 순서)
    출력: predict_proba() → (N, 2) [clip으로 0~1 보정]
    """

    def __init__(
        self,
        alpha: float = 1.0,
        random_state: int = 42,
    ):
        self.alpha = alpha
        self.random_state = random_state

    def fit(self, X: np.ndarray, y: np.ndarray) -> StackingEnsemble:
        """OOF 점수 행렬로 meta-learner 학습.

        Args:
            X: (N, len(STACKING_BASE_MODELS)) base model 점수 행렬. 각 열은 STACKING_BASE_MODELS 순서.
            y: (N,) 이진 라벨 (0=정상, 1=이상).
        """
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        expected_cols = len(STACKING_BASE_MODELS)
        if X.ndim != 2 or X.shape[1] != expected_cols:
            raise ValueError(
                f"열 수 불일치: 기대 {expected_cols}, 수신 {X.shape[1] if X.ndim == 2 else '1D'}"
            )

        # Why: positive=True로 모든 계수 ≥ 0 강제.
        #      감사 도메인에서 개별 모델의 이상 점수가 높을수록
        #      최종 점수도 높아져야 한다는 단조성(monotonicity) 보장.
        self.meta_ = Ridge(
            alpha=self.alpha,
            positive=True,
            fit_intercept=True,
        )
        self.meta_.fit(X, y)
        self.n_features_in_ = X.shape[1]

        logger.info(
            "StackingEnsemble 학습 완료 — coef=%s, intercept=%.4f",
            np.round(self.meta_.coef_, 4),
            self.meta_.intercept_,
        )
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """(N, len(STACKING_BASE_MODELS)) → (N,) 이진 예측 (threshold=0.5)."""
        proba = self.predict_proba(X)[:, 1]
        return (proba >= 0.5).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """(N, len(STACKING_BASE_MODELS)) → (N, 2) 확률 배열 [P(정상), P(이상)].

        Why: Ridge 출력은 연속값이므로 clip(0, 1)로 확률 범위 보정.
        """
        check_is_fitted(self, "meta_")
        X = np.asarray(X, dtype=np.float64)
        raw = self.meta_.predict(X)
        score = np.clip(raw, 0.0, 1.0)
        return np.column_stack([1 - score, score])

    @property
    def feature_weights(self) -> dict[str, float]:
        """meta-learner coef_ → 모델별 가중치 딕셔너리 (모두 ≥ 0 보장).

        Returns:
            {track_name: weight} 매핑. 합계는 1이 아닐 수 있음 (Ridge 특성).
        """
        check_is_fitted(self, "meta_")
        return dict(zip(STACKING_BASE_MODELS, self.meta_.coef_))
