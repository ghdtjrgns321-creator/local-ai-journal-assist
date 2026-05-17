"""SupervisedDetector — 지도학습 이상 탐지 파이프라인 인프라.

Why: 룰 기반 탐지의 복합 패턴 한계를 ML로 보완.
     현 단계는 인프라 구축 목적(TS-3). 합성 데이터 순환 학습 한계로
     향후 고객사 실데이터 유입 시 fine-tuning으로 활성화.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.exceptions import NotFittedError
from sklearn.metrics import f1_score

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
from src.preprocessing.pipeline_builder import (
    build_supervised_pipelines,
    drop_label_columns,
    prepare_training_features,
)
from src.preprocessing.split_strategy import choose_train_validation_split

_RULE_ID = "ML01"
_THRESHOLD_VAL_RATIO = 0.2


@dataclass(frozen=True)
class GateDecision:
    """Structured supervised label gate decision."""

    decision: str
    reason: str | None
    label_source: str
    positive_count: int
    positive_rate: float
    quality_grade: str
    thresholds: dict[str, float | int]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "label_source": self.label_source,
            "positive_count": self.positive_count,
            "positive_rate": self.positive_rate,
            "quality_grade": self.quality_grade,
            "thresholds": dict(self.thresholds),
            "warnings": list(self.warnings),
            "gate_status": _legacy_status_from_decision(self.decision),
            "gate_reason": self.reason,
        }


class SupervisedGateError(ValueError):
    """Raised when supervised training labels do not satisfy the gate policy."""

    def __init__(self, reason: str, snapshot: dict):
        super().__init__(reason)
        self.reason = reason
        self.snapshot = snapshot


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
        split_source = X
        X, groups, feature_quality = prepare_training_features(X, groups)
        gate_snapshot = self._validate_labels(label_result)
        warnings = gate_snapshot["warnings"]
        if feature_quality.sparse_dropped_columns:
            warnings = warnings + [
                "sparse feature columns excluded: "
                + ", ".join(feature_quality.sparse_dropped_columns)
            ]
        y = label_result.y

        # Why: threshold 탐색용 hold-out 분리 — train 데이터로 탐색하면 과적합 누수
        split = choose_train_validation_split(split_source)
        X_tr, X_val = X.iloc[split.train_idx], X.iloc[split.test_idx]
        y_tr, y_val = y[split.train_idx], y[split.test_idx]

        # 후보 Pipeline 생성 (SMOTE는 imblearn Pipeline 내부에서 fold별 적용)
        pipelines = build_supervised_pipelines(groups, use_smote=self._use_smote)

        # XGB scale_pos_weight 동적 설정
        neg, pos = int((y_tr == 0).sum()), max(int((y_tr == 1).sum()), 1)
        if "xgb" in pipelines:
            pipelines["xgb"].set_params(classifier__scale_pos_weight=neg / pos)

        # CV 비교 (train split에서만)
        cv_result = compare_pipelines(
            pipelines,
            X_tr,
            y_tr,
            group_source=split_source.iloc[split.train_idx],
        )
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
        self._split_policy = split.policy
        self._train_years = split.train_years
        self._validation_years = split.test_years
        self._feature_quality_profile = feature_quality.to_dict()
        self._label_gate_snapshot = {
            **gate_snapshot,
            "decision": "eligible",
            "reason": None,
            "gate_status": "eligible",
            "gate_reason": None,
        }

        return {
            "best_model": best_name,
            "mean_f1": cv_result.results[best_name].mean_f1,
            "optimal_threshold": self.optimal_threshold_,
            "train_years": split.train_years,
            "validation_years": split.test_years,
            "split_policy": split.policy,
            "n_train": len(X_tr),
            "n_val": len(X_val),
            "cv_results": cv_result.comparison_table.to_dict(),
            "warnings": warnings,
            "gate_decision": self._label_gate_snapshot["decision"],
            "gate_status": self._label_gate_snapshot["gate_status"],
            "gate_reason": self._label_gate_snapshot["gate_reason"],
            "label_source": self._label_gate_snapshot["label_source"],
            "positive_count": self._label_gate_snapshot["positive_count"],
            "positive_rate": self._label_gate_snapshot["positive_rate"],
            "feature_quality_profile": self._feature_quality_profile,
        }

    # -- 탐지 --

    def detect(self, df: pd.DataFrame) -> DetectionResult:
        """학습된 모델로 이상 탐지 수행."""
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
            evaluation_policy=getattr(self, "_split_policy", "unknown"),
            evaluation_confidence=_evaluation_confidence(getattr(self, "_split_policy", "unknown")),
            train_years=getattr(self, "_train_years", ()),
            test_years=getattr(self, "_validation_years", ()),
            label_source=getattr(self, "_label_gate_snapshot", {}).get("label_source", "unknown"),
            positive_count=getattr(self, "_label_gate_snapshot", {}).get("positive_count", 0),
            positive_rate=getattr(self, "_label_gate_snapshot", {}).get("positive_rate", 0.0),
            gate_decision=getattr(self, "_label_gate_snapshot", {}).get("decision", "unknown"),
            gate_status=getattr(self, "_label_gate_snapshot", {}).get("gate_status", "unknown"),
            gate_reason=getattr(self, "_label_gate_snapshot", {}).get("gate_reason"),
            feature_quality_profile=getattr(self, "_feature_quality_profile", {}),
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
            latest = matched[-1]
            self.optimal_threshold_ = latest.params.get("optimal_threshold", 0.5)
            self._loaded_model_metadata = latest
        else:
            self.optimal_threshold_ = 0.5
            self._loaded_model_metadata = None
        self.classes_ = np.array([0, 1])

    # -- private --

    def _check_fitted(self) -> None:
        """학습 상태 검증. pipeline_/optimal_threshold_ 부재 시 NotFittedError."""
        if not hasattr(self, "pipeline_") or not hasattr(self, "optimal_threshold_"):
            raise NotFittedError(
                f"{type(self).__name__}은 아직 학습되지 않았습니다. train()을 먼저 호출하세요."
            )

    def _validate_labels(self, label_result: LabelResult) -> dict:
        """양성 건수/비율 및 출처 요건을 검증하고 gate snapshot을 반환한다."""
        settings = self._settings
        min_positive = int(getattr(settings, "supervised_min_positive", 50))
        min_positive_rate = float(getattr(settings, "supervised_min_positive_rate", 0.01))
        allowed_sources = set(
            getattr(settings, "supervised_allowed_label_sources", ["ground_truth"])
        )

        pos_count = int(label_result.positive_count or int(label_result.y.sum()))
        positive_rate = float(label_result.positive_rate)
        label_source = str(label_result.label_source)

        quality_grade = str(
            getattr(
                label_result,
                "quality_grade",
                getattr(label_result, "label_quality", "unknown"),
            )
        )
        thresholds = {
            "min_positive_count": min_positive,
            "min_positive_rate": min_positive_rate,
        }

        if label_source not in allowed_sources:
            snapshot = GateDecision(
                decision="low_signal_fallback",
                reason=getattr(label_result, "gate_reason", None)
                or "untrusted_label_source",
                label_source=label_source,
                positive_count=pos_count,
                positive_rate=positive_rate,
                quality_grade=quality_grade,
                thresholds=thresholds,
                warnings=[],
            ).to_dict()
            raise SupervisedGateError(snapshot["gate_reason"], snapshot)
        if (
            not getattr(label_result, "is_supervised_eligible", False)
            and (
                getattr(label_result, "gate_status", "unknown") not in {"unknown", "eligible"}
                or getattr(label_result, "gate_reason", None) is not None
            )
        ):
            snapshot = GateDecision(
                decision=str(
                    getattr(label_result, "gate_decision", "low_signal_fallback")
                    or "low_signal_fallback"
                ),
                reason=getattr(label_result, "gate_reason", None)
                or "ineligible_label_source",
                label_source=label_source,
                positive_count=pos_count,
                positive_rate=positive_rate,
                quality_grade=quality_grade,
                thresholds=thresholds,
                warnings=[],
            ).to_dict()
            raise SupervisedGateError(snapshot["gate_reason"], snapshot)
        if pos_count == 0:
            snapshot = GateDecision(
                decision="hard_fail",
                reason="no_positive_labels",
                label_source=label_source,
                positive_count=pos_count,
                positive_rate=positive_rate,
                quality_grade=quality_grade,
                thresholds=thresholds,
                warnings=[],
            ).to_dict()
            raise SupervisedGateError(snapshot["gate_reason"], snapshot)
        if pos_count < min_positive:
            snapshot = GateDecision(
                decision="low_signal_fallback",
                reason="insufficient_positive_count",
                label_source=label_source,
                positive_count=pos_count,
                positive_rate=positive_rate,
                quality_grade=quality_grade,
                thresholds=thresholds,
                warnings=[],
            ).to_dict()
            raise SupervisedGateError(snapshot["gate_reason"], snapshot)
        if positive_rate < min_positive_rate:
            snapshot = GateDecision(
                decision="low_signal_fallback",
                reason="low_positive_rate",
                label_source=label_source,
                positive_count=pos_count,
                positive_rate=positive_rate,
                quality_grade=quality_grade,
                thresholds=thresholds,
                warnings=[],
            ).to_dict()
            raise SupervisedGateError(snapshot["gate_reason"], snapshot)
        return GateDecision(
            decision="eligible",
            reason=None,
            label_source=label_source,
            positive_count=pos_count,
            positive_rate=positive_rate,
            quality_grade=quality_grade if quality_grade != "unknown" else "trusted",
            thresholds=thresholds,
            warnings=[],
        ).to_dict()

    def get_training_gate_snapshot(self) -> dict:
        """Return saved or loaded gate metadata for UI/pipeline status decisions."""
        if hasattr(self, "_label_gate_snapshot"):
            return dict(self._label_gate_snapshot)
        meta = getattr(self, "_loaded_model_metadata", None)
        if meta is None:
            return {
                "label_source": "unknown",
                "positive_count": 0,
                "positive_rate": 0.0,
                "decision": "unavailable",
                "gate_status": "unknown",
                "gate_reason": "unknown_training_gate",
            }
        decision = getattr(meta, "gate_decision", None) or getattr(
            meta,
            "gate_status",
            "unknown",
        )
        if decision not in {"eligible", "low_signal_fallback", "hard_fail", "unavailable"}:
            decision = _decision_from_legacy_status(str(decision))
        return {
            "label_source": getattr(meta, "label_source", "unknown"),
            "positive_count": int(getattr(meta, "positive_count", 0)),
            "positive_rate": float(getattr(meta, "positive_rate", 0.0)),
            "decision": decision,
            "gate_status": str(getattr(meta, "gate_status", "unknown")),
            "gate_reason": getattr(meta, "gate_reason", None),
            "evaluation_confidence": getattr(meta, "evaluation_confidence", "unknown"),
        }

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


def _evaluation_confidence(split_policy: str) -> str:
    if split_policy == "temporal_holdout":
        return "benchmark"
    if split_policy == "document_group_holdout":
        return "development_only"
    return "unknown"


def _legacy_status_from_decision(decision: str) -> str:
    if decision == "eligible":
        return "eligible"
    if decision == "hard_fail":
        return "blocked"
    if decision in {"low_signal_fallback", "unavailable"}:
        return "fallback_to_unsupervised"
    return "unknown"


def _decision_from_legacy_status(status: str) -> str:
    if status == "eligible":
        return "eligible"
    if status == "blocked":
        return "hard_fail"
    if status == "fallback_to_unsupervised":
        return "low_signal_fallback"
    return "unknown"
