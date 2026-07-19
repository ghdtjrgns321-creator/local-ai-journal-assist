"""SHAP 기반 피처 중요도 — Pipeline 해석 가능성 확보.

Why: 탐지 결과의 "왜 이상인가?"를 설명하려면
각 피처의 기여도를 SHAP으로 분해해야 한다.
"""

from __future__ import annotations

import logging

import numpy as np
import shap

logger = logging.getLogger(__name__)


class PipelineExplainer:
    """sklearn Pipeline의 SHAP 기여도 산출."""

    def __init__(self, pipeline, feature_names: list[str], model_type: str | None = None):
        self.pipeline = pipeline
        self.feature_names = feature_names
        self.model_type = model_type or self._resolve_model_type()

    def _resolve_model_type(self) -> str:
        """Pipeline 내 모델 타입 자동 감지."""
        model = self._get_model()
        cls_name = type(model).__name__.lower()
        if "xgb" in cls_name:
            return "tree"
        if "forest" in cls_name:
            return "tree"
        return "kernel"

    def _get_preprocessor(self):
        """Pipeline에서 preprocessor 단계 추출."""
        return self.pipeline.named_steps.get("preprocessor")

    def _get_model(self):
        """Pipeline에서 모델 단계 추출 (classifier 또는 detector)."""
        for name in ("classifier", "detector"):
            if name in self.pipeline.named_steps:
                return self.pipeline.named_steps[name]
        # 마지막 단계를 모델로 간주
        return self.pipeline.steps[-1][1]

    def explain_batch(self, X, top_k: int = 5) -> tuple[list[dict], float]:
        """배치 데이터에 대한 SHAP 기여도 산출.

        Returns:
            (contributions, base_value) 튜플.
            contributions: 각 행의 top-k 피처 기여도 dict 리스트.
            base_value: 모델의 평균 예측값(expected_value). Waterfall 차트 시작점.

        Why: Waterfall 시각화는 base_value에서 시작해 피처 기여도를 누적하여
             최종 예측값까지 계단으로 표현 → base_value 없으면 의미 없는 차트.
        """
        preprocessor = self._get_preprocessor()
        model = self._get_model()

        X_transformed = preprocessor.transform(X) if preprocessor else X
        n_features_out = X_transformed.shape[1]
        labels = self._resolve_feature_labels(n_features_out)

        if self.model_type == "tree":
            explainer = shap.TreeExplainer(model)
        else:
            explainer = shap.KernelExplainer(
                model.predict, X_transformed[: min(100, len(X_transformed))]
            )

        shap_values = explainer.shap_values(X_transformed)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # 양성 클래스

        # Why: expected_value는 scalar 또는 [neg, pos] array → 양성 클래스 값 추출
        expected = explainer.expected_value
        if hasattr(expected, "__len__") and len(expected) > 1:
            base_value = float(expected[1])
        else:
            base_value = float(expected)

        results = []
        for i in range(len(X_transformed)):
            row_vals = shap_values[i]
            top_idx = np.argsort(np.abs(row_vals))[-top_k:][::-1]
            contributions = {labels[j]: float(row_vals[j]) for j in top_idx}
            results.append(contributions)
        return results, base_value

    def explain_single(self, X_row, top_k: int = 5) -> tuple[dict, float]:
        """단일 행에 대한 SHAP 기여도.

        Returns:
            (contributions, base_value) 튜플.
        """
        X_row = np.atleast_2d(X_row)
        results, base_value = self.explain_batch(X_row, top_k=top_k)
        return results[0], base_value

    def _resolve_feature_labels(self, n_features_out: int) -> list[str]:
        """전처리 후 피처명 결정. 매핑 불가 시 인덱스 라벨."""
        preprocessor = self._get_preprocessor()
        if preprocessor is not None and hasattr(preprocessor, "get_feature_names_out"):
            try:
                return list(preprocessor.get_feature_names_out())
            except Exception:
                pass
        if len(self.feature_names) == n_features_out:
            return list(self.feature_names)
        return [f"feature_{i}" for i in range(n_features_out)]
