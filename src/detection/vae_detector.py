"""UnsupervisedDetector — VAE + Isolation Forest 앙상블 비지도 탐지기.

Why: 룰 기반이 잡지 못하는 미지 패턴(zero-day)을 정상 분포 학습으로 탐지.
     VAE 재구성 오차 + IF 고립도를 ECDF 기반 Percentile Ranking으로 결합하여
     배치 크기 무관하게 안정적인 점수를 산출한다.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.exceptions import NotFittedError

from src.detection.base import BaseDetector, DetectionResult
from src.preprocessing.data_stats import (
    compute_class_imbalance,
    compute_feature_schema_version,
    compute_training_stats,
)
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.pipeline_builder import build_if_pipeline, build_vae_pipeline

_RULE_ID = "ML02"
# Why: 감사조서에 첨부할 상위 기여 피처 개수. 너무 많으면 가독성 저하.
_TOP_K_FEATURES = 3


class UnsupervisedDetector(BaseDetector):
    """VAE + Isolation Forest 앙상블 비지도 이상 탐지기.

    train() 시 두 모델을 X 전체로 학습하고 ECDF 분포를 저장.
    detect() 시 학습 분포 기준 백분위수로 정규화하여 앙상블 점수 산출.
    """

    def __init__(
        self,
        settings=None,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        super().__init__(settings)
        self._registry = model_registry

    @property
    def track_name(self) -> str:
        return "ml_unsupervised"

    # -- 학습 --

    def train(
        self,
        X: pd.DataFrame,
        groups: FeatureGroups,
        y: np.ndarray | None = None,
    ) -> dict:
        """두 파이프라인 학습. y는 평가 전용(학습에 사용하지 않음).

        Why: 비지도 학습의 본질 — contamination + 오토인코딩 병목이
             자체적으로 소수의 이상치를 튕겨냄. y로 필터링하면 룰 엔진 편향 답습.
        """
        start = time.perf_counter()

        # VAE Pipeline: X 전체로 학습
        self.vae_pipeline_ = build_vae_pipeline(groups)
        self.vae_pipeline_.set_params(
            detector__latent_dim=self._settings.vae_latent_dim,
            detector__epochs=self._settings.vae_epochs,
            detector__batch_size=self._settings.vae_batch_size,
        )
        self.vae_pipeline_.fit(X)

        # IF Pipeline: X 전체로 학습
        self.if_pipeline_ = build_if_pipeline(groups)
        self.if_pipeline_.set_params(
            detector__contamination=self._settings.if_contamination,
        )
        self.if_pipeline_.fit(X)

        # ECDF용 학습 분포 저장
        vae_raw = self._score_vae(X)
        if_raw = self._score_if(X)
        self.vae_train_scores_ = np.sort(vae_raw)
        # Why: IF decision_function은 음수=이상. 부호 반전 후 정렬하여
        #      ECDF에서 "가장 이상한 값"이 높은 percentile을 받도록 함.
        self.if_train_scores_ = np.sort(-if_raw)

        # Why: train() 시점에서는 학습 데이터 전체에 대해 rankdata 사용.
        #      배치=전체이므로 누수 없음. ECDF는 detect() 시점에서 사용.
        ensemble = self._combine_scores_initial(vae_raw, if_raw)
        contamination = self._settings.if_contamination
        self.threshold_ = float(np.percentile(ensemble, (1 - contamination) * 100))

        elapsed = time.perf_counter() - start
        self._logger.info(
            "학습 완료: %d행 × %d피처, threshold=%.4f (%.1f초)",
            len(X), X.shape[1], self.threshold_, elapsed,
        )

        # Why: 드리프트 감지 베이스라인 — 학습 시점 분포를 메타데이터에 보존
        self._train_stats = compute_training_stats(X)
        self._schema_version = compute_feature_schema_version(X)
        self._class_imbalance = compute_class_imbalance(y)
        self._n_train = int(len(X))

        return {
            "ensemble_threshold": self.threshold_,
            "n_train_samples": len(X),
            "n_features": X.shape[1],
            "elapsed": elapsed,
        }

    # -- 탐지 --

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """ECDF 기반 앙상블 탐지 수행."""
        self._check_fitted()
        start = time.perf_counter()

        vae_raw = self._score_vae(df)
        if_raw = self._score_if(df)
        scores = self._combine_scores(vae_raw, if_raw, df.index)

        # Why: 감사조서 정량 증거용 — 어느 피처에서 재구성 실패가 컸는지 Top-K 분해
        per_feature, feature_names = self._score_vae_per_feature(df)
        topk_columns = self._build_topk_columns(
            per_feature, feature_names, df.index,
        )

        flagged_mask = scores > self.threshold_
        flagged_indices = scores[flagged_mask].index.tolist()

        details = pd.DataFrame({_RULE_ID: scores}, index=df.index)
        details = pd.concat([details, topk_columns], axis=1)

        rule_flags = [
            self._create_rule_flag(
                rule_id=_RULE_ID,
                flagged_count=int(flagged_mask.sum()),
                total_count=len(df),
            ),
        ]
        elapsed = time.perf_counter() - start
        return self._make_result(
            flagged_indices=flagged_indices,
            scores=scores,
            rule_flags=rule_flags,
            details=details,
            metadata={"elapsed": elapsed, "skipped_rules": []},
            warnings=[],
        )

    # -- 모델 영속화 --

    def save_model(self, metric_value: float = 0.0):
        """VAE + IF 두 파이프라인 + ECDF 분포 + 학습 분포 메타를 번들로 저장."""
        self._check_fitted()
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        bundle = {
            "vae_pipeline": self.vae_pipeline_,
            "if_pipeline": self.if_pipeline_,
            "threshold": self.threshold_,
            "vae_train_scores": self.vae_train_scores_,
            "if_train_scores": self.if_train_scores_,
        }
        return self._registry.save(
            bundle, "unsupervised", metric_value,
            params={"threshold": self.threshold_},
            training_data_stats=getattr(self, "_train_stats", {}),
            feature_schema_version=getattr(self, "_schema_version", 1),
            class_imbalance_ratio=getattr(self, "_class_imbalance", 0.0),
            n_train_samples=getattr(self, "_n_train", 0),
        )

    def load_model(
        self, model_name: str = "unsupervised", version: int | None = None,
    ) -> None:
        """ModelRegistry에서 번들 복원."""
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        bundle = self._registry.load(model_name, version)
        self.vae_pipeline_ = bundle["vae_pipeline"]
        self.if_pipeline_ = bundle["if_pipeline"]
        self.threshold_ = bundle["threshold"]
        self.vae_train_scores_ = bundle["vae_train_scores"]
        self.if_train_scores_ = bundle["if_train_scores"]

    # -- private --

    def _check_fitted(self) -> None:
        """학습 상태 검증."""
        required = ("vae_pipeline_", "if_pipeline_", "threshold_",
                     "vae_train_scores_", "if_train_scores_")
        if not all(hasattr(self, attr) for attr in required):
            raise NotFittedError(
                f"{type(self).__name__}은 아직 학습되지 않았습니다. "
                "train()을 먼저 호출하세요.",
            )

    def _score_vae(self, df: pd.DataFrame) -> np.ndarray:
        """VAE 파이프라인의 raw 재구성 오차(MSE) 반환.

        높을수록 이상. ECDF에서 높은 오차 = 높은 percentile.
        """
        preprocessor = self.vae_pipeline_[:-1]
        X_transformed = np.array(preprocessor.transform(df), dtype=np.float32)
        vae = self.vae_pipeline_.named_steps["detector"]
        return vae.score_samples(X_transformed)

    def _score_vae_per_feature(
        self, df: pd.DataFrame,
    ) -> tuple[np.ndarray, list[str]]:
        """피처별 재구성 오차 + 전처리 후 피처명 반환.

        Why: 설명력(Explainability) 핵심 진입점. (N, D) 행렬과 D개 피처명을
             함께 반환하여 Top-K 분해의 입력으로 사용한다.
        """
        preprocessor = self.vae_pipeline_[:-1]
        X_transformed = np.array(preprocessor.transform(df), dtype=np.float32)
        vae = self.vae_pipeline_.named_steps["detector"]
        per_feature = vae.score_samples_per_feature(X_transformed)

        # Why: ColumnTransformer.get_feature_names_out()으로 변환 후 피처명 추출.
        #      실패 시 generic 이름으로 fallback (예: 구버전 sklearn).
        try:
            feature_names = list(preprocessor.get_feature_names_out())
        except (AttributeError, ValueError):
            feature_names = [f"f{i}" for i in range(per_feature.shape[1])]
        return per_feature, feature_names

    @staticmethod
    def _build_topk_columns(
        per_feature: np.ndarray,
        feature_names: list[str],
        index: pd.Index,
        k: int = _TOP_K_FEATURES,
    ) -> pd.DataFrame:
        """행별 상위 K개 피처와 기여도를 컬럼 형태의 DataFrame으로 변환.

        Why: details DataFrame에 첨부 가능한 long → wide 형식으로 정리한다.
             각 행에 대해 np.argpartition으로 상위 K개를 추출(O(N·D))하여
             정렬 비용을 피한다.

        Returns:
            (N, 2K) DataFrame — ML02_top_feature_{i}, ML02_top_feature_{i}_contrib
        """
        n_rows, n_features = per_feature.shape
        if n_rows == 0 or n_features == 0:
            cols = {}
            for i in range(1, k + 1):
                cols[f"{_RULE_ID}_top_feature_{i}"] = pd.Series(dtype="object")
                cols[f"{_RULE_ID}_top_feature_{i}_contrib"] = pd.Series(dtype="float64")
            return pd.DataFrame(cols, index=index)

        effective_k = min(k, n_features)
        # Why: argpartition은 정렬되지 않은 상위 K → argsort로 다시 정렬
        partition_idx = np.argpartition(-per_feature, kth=effective_k - 1, axis=1)[
            :, :effective_k
        ]
        rows = np.arange(n_rows)[:, None]
        topk_values = per_feature[rows, partition_idx]
        order = np.argsort(-topk_values, axis=1)
        sorted_idx = np.take_along_axis(partition_idx, order, axis=1)
        sorted_values = np.take_along_axis(topk_values, order, axis=1)

        feature_name_array = np.asarray(feature_names, dtype=object)
        cols: dict[str, pd.Series] = {}
        for i in range(effective_k):
            cols[f"{_RULE_ID}_top_feature_{i + 1}"] = pd.Series(
                feature_name_array[sorted_idx[:, i]], index=index,
            )
            cols[f"{_RULE_ID}_top_feature_{i + 1}_contrib"] = pd.Series(
                sorted_values[:, i].astype(float), index=index,
            )
        # Why: K가 피처 수보다 큰 경우(거의 발생 안 하나 방어) 빈 컬럼 채움
        for i in range(effective_k, k):
            cols[f"{_RULE_ID}_top_feature_{i + 1}"] = pd.Series(
                [None] * n_rows, index=index,
            )
            cols[f"{_RULE_ID}_top_feature_{i + 1}_contrib"] = pd.Series(
                np.zeros(n_rows, dtype=float), index=index,
            )
        return pd.DataFrame(cols, index=index)

    def _score_if(self, df: pd.DataFrame) -> np.ndarray:
        """IF 파이프라인의 decision_function(raw) 반환.

        음수=이상, 양수=정상. ECDF 전에 부호 반전하여 높을수록 이상으로 변환.
        """
        preprocessor = self.if_pipeline_[:-1]
        X_transformed = preprocessor.transform(df)
        return self.if_pipeline_.named_steps["detector"].decision_function(
            X_transformed,
        )

    @staticmethod
    def _ecdf_transform(
        new_scores: np.ndarray, train_sorted: np.ndarray,
    ) -> np.ndarray:
        """ECDF: 학습 데이터 분포 기준 백분위수 계산.

        Why: 배치 내 rankdata는 배치 크기에 따라 결과 변동.
             학습 데이터 N건의 정렬 배열에 searchsorted하면 배치 크기 무관하게
             "학습 데이터 기준 상위 몇 %"를 안정적으로 계산.
        """
        return np.searchsorted(train_sorted, new_scores) / len(train_sorted)

    def _combine_scores(
        self,
        vae_raw: np.ndarray,
        if_raw: np.ndarray,
        index: pd.Index,
    ) -> pd.Series:
        """ECDF 기반 앙상블. 학습 분포 기준 percentile 후 균등 결합."""
        vae_pct = self._ecdf_transform(vae_raw, self.vae_train_scores_)
        if_pct = self._ecdf_transform(-if_raw, self.if_train_scores_)
        ensemble = np.clip(0.5 * vae_pct + 0.5 * if_pct, 0.0, 1.0)
        return pd.Series(ensemble, index=index, name=_RULE_ID)

    @staticmethod
    def _combine_scores_initial(
        vae_raw: np.ndarray, if_raw: np.ndarray,
    ) -> np.ndarray:
        """train() 전용: ECDF 미구축 상태에서 rankdata로 threshold 결정.

        Why: train() 시점에서는 학습 데이터 전체에 대해 rankdata를 사용하므로
             배치=전체이며 누수 없음. ECDF 배열 저장 후에는 사용하지 않음.
        """
        n = len(vae_raw)
        vae_rank = rankdata(vae_raw) / n
        if_rank = rankdata(-if_raw) / n
        return 0.5 * vae_rank + 0.5 * if_rank
