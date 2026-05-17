"""TransformerDetector — FT-Transformer 기반 지도학습 이상 탐지기.

Why: 24개 룰 결과 간 조합 패턴을 self-attention이 자동 학습한다.
현 단계는 인프라 구축 목적(TS-3). 향후 고객사 실데이터 유입 시 fine-tuning으로 활성화.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.metrics import f1_score

from src.detection.base import BaseDetector, DetectionResult
from src.preprocessing.data_stats import (
    compute_class_imbalance,
    compute_feature_schema_version,
    compute_training_stats,
)
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.pipeline_builder import (
    build_ft_pipeline,
    drop_label_columns,
    prepare_training_features,
)
from src.preprocessing.split_strategy import choose_train_validation_split

_RULE_ID = "ML03"
_MIN_POSITIVE_COUNT = 50
_MIN_POSITIVE_RATE = 0.01
_THRESHOLD_VAL_RATIO = 0.2


class TransformerDetector(BaseDetector):
    """FT-Transformer 기반 지도학습 이상 탐지기."""

    def __init__(
        self,
        settings=None,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        super().__init__(settings)
        self._registry = model_registry

    @property
    def track_name(self) -> str:
        return "ml_transformer"

    # -- 학습 --

    def train(
        self,
        X: pd.DataFrame,
        label_result: LabelResult,
        groups: FeatureGroups,
    ) -> dict:
        """FT-Transformer 학습 + 동적 threshold 탐색."""
        split_source = X
        X, groups, feature_quality = prepare_training_features(X, groups)
        warnings = self._validate_labels(label_result)
        if feature_quality.sparse_dropped_columns:
            warnings = warnings + [
                "sparse feature columns excluded: "
                + ", ".join(feature_quality.sparse_dropped_columns)
            ]
        y = label_result.y

        split = choose_train_validation_split(split_source)
        X_tr, X_val = X.iloc[split.train_idx], X.iloc[split.test_idx]
        y_tr, y_val = y[split.train_idx], y[split.test_idx]

        self.pipeline_ = build_ft_pipeline(groups)
        # Why: settings에서 하이퍼파라미터를 주입하여 환경변수 오버라이드 가능
        self.pipeline_.set_params(
            classifier__d_token=self._settings.ft_d_token,
            classifier__n_layers=self._settings.ft_n_layers,
            classifier__n_heads=self._settings.ft_n_heads,
            classifier__d_ff=self._settings.ft_d_ff,
            classifier__dropout=self._settings.ft_dropout,
            classifier__epochs=self._settings.ft_epochs,
            classifier__batch_size=self._settings.ft_batch_size,
            classifier__lr=self._settings.ft_lr,
        )
        self.pipeline_.fit(X_tr, y_tr)

        self.optimal_threshold_ = self._find_optimal_threshold(X_val, y_val)
        self.classes_ = np.array([0, 1])

        # Why: 드리프트 감지 베이스라인 — 학습 시점 분포를 메타데이터에 보존
        self._train_stats = compute_training_stats(X_tr)
        self._schema_version = compute_feature_schema_version(X_tr)
        self._class_imbalance = compute_class_imbalance(y_tr)
        self._n_train = int(len(X_tr))
        self._split_policy = split.policy
        self._train_years = split.train_years
        self._validation_years = split.test_years
        self._feature_quality_profile = feature_quality.to_dict()

        return {
            "optimal_threshold": self.optimal_threshold_,
            "n_train": len(X_tr),
            "n_val": len(X_val),
            "train_years": split.train_years,
            "validation_years": split.test_years,
            "split_policy": split.policy,
            "warnings": warnings,
            "feature_quality_profile": self._feature_quality_profile,
        }

    # -- 탐지 --

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """학습된 FT-Transformer로 이상 탐지 수행."""
        self._check_fitted()
        start = time.perf_counter()

        X = drop_label_columns(df)
        proba = self.pipeline_.predict_proba(X)[:, 1]
        scores = pd.Series(proba, index=df.index, name=_RULE_ID)

        flagged_mask = scores > self.optimal_threshold_
        flagged_indices = scores[flagged_mask].index.tolist()

        details = pd.DataFrame({_RULE_ID: scores}, index=df.index)
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

    def save_model(self, mean_f1: float):
        """ModelRegistry로 파이프라인 + threshold + 학습 분포 메타 저장."""
        self._check_fitted()
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        return self._registry.save(
            self.pipeline_, "ft_transformer", mean_f1,
            params={"optimal_threshold": self.optimal_threshold_},
            training_data_stats=getattr(self, "_train_stats", {}),
            feature_schema_version=getattr(self, "_schema_version", 1),
            class_imbalance_ratio=getattr(self, "_class_imbalance", 0.0),
            n_train_samples=getattr(self, "_n_train", 0),
            evaluation_policy=getattr(self, "_split_policy", "unknown"),
            evaluation_confidence=_evaluation_confidence(getattr(self, "_split_policy", "unknown")),
            train_years=getattr(self, "_train_years", ()),
            test_years=getattr(self, "_validation_years", ()),
            feature_quality_profile=getattr(self, "_feature_quality_profile", {}),
        )

    def load_model(
        self, model_name: str = "ft_transformer", version: int | None = None,
    ) -> None:
        """ModelRegistry에서 파이프라인 로드 + threshold 복원."""
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        self.pipeline_ = self._registry.load(model_name, version)
        meta = self._registry.list_models()
        matched = [m for m in meta if m.model_name == model_name]
        if version is not None:
            matched = [m for m in matched if m.version == version]
        self.optimal_threshold_ = (
            matched[-1].params.get("optimal_threshold", 0.5) if matched else 0.5
        )
        self.classes_ = np.array([0, 1])

    # -- private --

    def _check_fitted(self) -> None:
        if not hasattr(self, "pipeline_") or not hasattr(self, "optimal_threshold_"):
            raise NotFittedError(
                f"{type(self).__name__}은 아직 학습되지 않았습니다. "
                "train()을 먼저 호출하세요.",
            )

    def _validate_labels(self, label_result: LabelResult) -> list[str]:
        """양성 건수/비율 최소 요건 검증."""
        pos_count = int(label_result.y.sum())
        if pos_count == 0:
            raise ValueError("양성 샘플이 0건입니다. 지도학습 불가.")
        warnings = []
        if pos_count < _MIN_POSITIVE_COUNT:
            msg = f"양성 {pos_count}건 < 최소 {_MIN_POSITIVE_COUNT}건. 학습 품질 저하 가능."
            self._logger.warning(msg)
            warnings.append(msg)
        if label_result.positive_rate < _MIN_POSITIVE_RATE:
            msg = f"양성 비율 {label_result.positive_rate:.4f} < {_MIN_POSITIVE_RATE}. 극단 불균형."
            self._logger.warning(msg)
            warnings.append(msg)
        return warnings

    def _find_optimal_threshold(self, X, y: np.ndarray) -> float:
        """F1-macro 최대화 threshold 탐색 (validation 데이터 기반)."""
        proba = self.pipeline_.predict_proba(X)[:, 1]
        thresholds = np.linspace(0.1, 0.9, 81)
        best_t, best_f1 = 0.5, 0.0
        for t in thresholds:
            preds = (proba >= t).astype(int)
            if preds.sum() == 0 or preds.sum() == len(preds):
                continue
            score = f1_score(y, preds, average="macro", zero_division=0)
            if score > best_f1:
                best_f1, best_t = score, float(t)
        self._logger.info("최적 threshold: %.3f (F1-macro=%.4f)", best_t, best_f1)
        return best_t


def _evaluation_confidence(split_policy: str) -> str:
    if split_policy == "temporal_holdout":
        return "benchmark"
    if split_policy == "document_group_holdout":
        return "development_only"
    return "unknown"
