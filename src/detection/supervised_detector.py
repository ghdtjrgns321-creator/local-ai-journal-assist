"""SupervisedDetector — 지도학습 이상 탐지 파이프라인 인프라.

Why: 룰 기반 탐지의 복합 패턴 한계를 ML로 보완.
     현 단계는 인프라 구축 목적(TS-3). 합성 데이터 순환 학습 한계로
     향후 고객사 실데이터 유입 시 fine-tuning으로 활성화.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split

from src.detection.base import BaseDetector, DetectionResult
from src.preprocessing.cv_selector import compare_pipelines
from src.preprocessing.data_stats import (
    compute_class_imbalance,
    compute_feature_schema_version,
    compute_training_stats,
)
from src.preprocessing.feature_groups import FeatureGroups
from src.preprocessing.label_strategy import LabelResult
from src.preprocessing.model_registry import ModelRegistry
from src.preprocessing.pipeline_builder import build_supervised_pipelines

_RULE_ID = "ML01"
_MIN_POSITIVE_COUNT = 50
_MIN_POSITIVE_RATE = 0.01
_THRESHOLD_VAL_RATIO = 0.2


class SupervisedDetector(BaseDetector):
    """지도학습 기반 이상 탐지기.

    4개 모델(LR, RF, XGB, LightGBM)을 cv_selector로 자동 비교/선택.
    """

    def __init__(
        self,
        settings=None,
        model_registry: ModelRegistry | None = None,
        use_smote: bool = False,
    ) -> None:
        super().__init__(settings)
        self._registry = model_registry
        self._use_smote = use_smote

    @property
    def track_name(self) -> str:
        return "ml_supervised"

    # -- 학습 --

    def train(
        self,
        X: pd.DataFrame,
        label_result: LabelResult,
        groups: FeatureGroups,
    ) -> dict:
        """모델 학습 + CV 비교 + 최적 모델 선택 + 동적 threshold."""
        warnings = self._validate_labels(label_result)
        y = label_result.y

        # Why: threshold 탐색용 hold-out 분리 — train 데이터로 탐색하면 과적합 누수
        X_tr, X_val, y_tr, y_val = train_test_split(
            X, y, test_size=_THRESHOLD_VAL_RATIO, random_state=42, stratify=y,
        )

        # 후보 Pipeline 생성 (SMOTE는 imblearn Pipeline 내부에서 fold별 적용)
        pipelines = build_supervised_pipelines(groups, use_smote=self._use_smote)

        # XGB scale_pos_weight 동적 설정
        neg, pos = int((y_tr == 0).sum()), max(int((y_tr == 1).sum()), 1)
        if "xgb" in pipelines:
            pipelines["xgb"].set_params(classifier__scale_pos_weight=neg / pos)

        # CV 비교 (train split에서만)
        cv_result = compare_pipelines(pipelines, X_tr, y_tr)
        best_name = cv_result.best_pipeline_name
        self._logger.info(
            "최적 모델: %s (F1=%.4f)", best_name, cv_result.results[best_name].mean_f1,
        )

        # train split으로 최종 학습
        self.pipeline_ = pipelines[best_name]
        self.pipeline_.fit(X_tr, y_tr)

        # Why: validation split으로 threshold 탐색 — 학습 데이터와 분리하여 과적합 방지
        self.optimal_threshold_ = self._find_optimal_threshold(X_val, y_val)
        self.classes_ = np.array([0, 1])

        # Why: 드리프트 감지 베이스라인 — 학습 시점 분포를 메타데이터에 보존
        self._train_stats = compute_training_stats(X_tr)
        self._schema_version = compute_feature_schema_version(X_tr)
        self._class_imbalance = compute_class_imbalance(y_tr)
        self._n_train = int(len(X_tr))

        return {
            "best_model": best_name,
            "mean_f1": cv_result.results[best_name].mean_f1,
            "optimal_threshold": self.optimal_threshold_,
            "cv_results": cv_result.comparison_table.to_dict(),
            "warnings": warnings,
        }

    # -- 탐지 --

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """학습된 모델로 이상 탐지 수행."""
        self._check_fitted()
        start = time.perf_counter()

        proba = self.pipeline_.predict_proba(df)[:, 1]
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
        """ModelRegistry를 통해 파이프라인 + threshold + 학습 분포 메타 저장."""
        self._check_fitted()
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        return self._registry.save(
            self.pipeline_, "supervised", mean_f1,
            params={"optimal_threshold": self.optimal_threshold_},
            training_data_stats=getattr(self, "_train_stats", {}),
            feature_schema_version=getattr(self, "_schema_version", 1),
            class_imbalance_ratio=getattr(self, "_class_imbalance", 0.0),
            n_train_samples=getattr(self, "_n_train", 0),
        )

    def load_model(self, model_name: str = "supervised", version: int | None = None) -> None:
        """ModelRegistry에서 파이프라인 로드 + threshold 복원."""
        if self._registry is None:
            raise ValueError("model_registry가 설정되지 않았습니다.")
        self.pipeline_ = self._registry.load(model_name, version)
        # Why: 로드 대상 버전의 params에서 threshold 조회
        meta = self._registry.list_models()
        target_ver = version
        matched = [m for m in meta if m.model_name == model_name]
        if target_ver is not None:
            matched = [m for m in matched if m.version == target_ver]
        if matched:
            self.optimal_threshold_ = matched[-1].params.get("optimal_threshold", 0.5)
        else:
            self.optimal_threshold_ = 0.5
        self.classes_ = np.array([0, 1])

    # -- private --

    def _check_fitted(self) -> None:
        """학습 상태 검증. pipeline_/optimal_threshold_ 부재 시 NotFittedError."""
        if not hasattr(self, "pipeline_") or not hasattr(self, "optimal_threshold_"):
            raise NotFittedError(
                f"{type(self).__name__}은 아직 학습되지 않았습니다. train()을 먼저 호출하세요."
            )

    def _validate_labels(self, label_result: LabelResult) -> list[str]:
        """양성 건수/비율 최소 요건 검증. 양성 0건이면 ValueError."""
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
            # Why: 예측이 전부 양성 또는 전부 음성이면 F1 의미 없음
            if preds.sum() == 0 or preds.sum() == len(preds):
                continue
            score = f1_score(y, preds, average="macro", zero_division=0)
            if score > best_f1:
                best_f1, best_t = score, float(t)
        self._logger.info("최적 threshold: %.3f (F1-macro=%.4f)", best_t, best_f1)
        return best_t
