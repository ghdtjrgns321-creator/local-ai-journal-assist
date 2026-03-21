"""SHAP 기반 XAI — 피처별 기여도 설명.

Why: "모델이 왜 이 전표를 이상하다고 판단했는가?"에 대해
피처별 기여도(Shapley values)를 제공한다.
- XGBoost → TreeExplainer (빠름, 정확)
- VAE/IF → KernelExplainer (느림, 플래그 전표에만 on-demand)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

# KernelExplainer 최대 설명 건수 (계산 비용 제한)
_MAX_KERNEL_SAMPLES = 100


class PipelineExplainer:
    """최적 Pipeline의 예측을 SHAP으로 설명."""

    def __init__(
        self,
        pipeline: Pipeline,
        feature_names: list[str],
        model_type: str = "auto",
    ):
        """
        Parameters
        ----------
        pipeline : fit 완료된 Pipeline
        feature_names : 원본 피처명 목록
        model_type : "tree" | "kernel" | "auto"
            auto: classifier/detector 타입에서 자동 판별
        """
        self.pipeline = pipeline
        self.feature_names = feature_names
        self.model_type = model_type
        self._explainer = None

    def _resolve_model_type(self) -> str:
        """Pipeline 내 모델 타입 자동 판별."""
        if self.model_type != "auto":
            return self.model_type

        # Pipeline의 마지막 단계가 트리 기반인지 확인
        last_step = self.pipeline.steps[-1][1]
        tree_types = ("XGBClassifier", "RandomForestClassifier", "GradientBoostingClassifier")
        if type(last_step).__name__ in tree_types:
            return "tree"
        return "kernel"

    def _get_preprocessor(self):
        """Pipeline에서 preprocessor 단계 추출."""
        return self.pipeline.named_steps.get("preprocessor")

    def _get_model(self):
        """Pipeline에서 모델 단계 추출."""
        last_name, last_step = self.pipeline.steps[-1]
        return last_step

    def explain_batch(
        self,
        X: pd.DataFrame,
        top_k: int = 5,
    ) -> list[dict]:
        """전표 배치에 대해 상위 k개 피처 기여도 반환.

        Returns
        -------
        [{"index": 42, "contributions": [("전표일자", 0.30), ...]}]
        """
        import shap

        model_type = self._resolve_model_type()
        preprocessor = self._get_preprocessor()
        model = self._get_model()

        # 전처리 적용
        if preprocessor is not None:
            X_transformed = preprocessor.transform(X)
        else:
            X_transformed = np.asarray(X)

        if hasattr(X_transformed, "toarray"):
            X_transformed = X_transformed.toarray()
        X_arr = np.asarray(X_transformed, dtype=float)

        # Explainer 생성
        if model_type == "tree":
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_arr)
        else:
            # KernelExplainer: 비용 제한
            n_samples = min(len(X_arr), _MAX_KERNEL_SAMPLES)
            if len(X_arr) > n_samples:
                logger.warning(
                    "KernelExplainer 비용 제한: %d → %d건만 설명",
                    len(X_arr), n_samples,
                )
                X_arr = X_arr[:n_samples]

            background = shap.kmeans(X_arr, min(10, len(X_arr)))
            explainer = shap.KernelExplainer(model.predict, background)
            shap_values = explainer.shap_values(X_arr)

        # 이진 분류: shap_values가 리스트면 양성 클래스 선택
        if isinstance(shap_values, list):
            shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]

        # 피처명 매핑 (전처리 후 피처 수와 원본이 다를 수 있음)
        feature_labels = self._resolve_feature_labels(shap_values.shape[1])

        # 결과 조립
        results = []
        for i in range(len(X_arr)):
            sv = shap_values[i]
            # 절대값 기준 상위 k개
            top_indices = np.argsort(np.abs(sv))[::-1][:top_k]
            contributions = [
                (feature_labels[idx], round(float(sv[idx]), 4))
                for idx in top_indices
            ]
            results.append({
                "index": i,
                "contributions": contributions,
            })

        return results

    def explain_single(self, X_row: pd.DataFrame, top_k: int = 5) -> dict:
        """단일 전표 상세 설명."""
        if isinstance(X_row, pd.Series):
            X_row = X_row.to_frame().T
        batch = self.explain_batch(X_row, top_k=top_k)
        return batch[0] if batch else {}

    def _resolve_feature_labels(self, n_features_out: int) -> list[str]:
        """전처리 후 피처 수에 맞는 레이블 생성."""
        preprocessor = self._get_preprocessor()

        # ColumnTransformer의 get_feature_names_out 시도
        if preprocessor is not None and hasattr(preprocessor, "get_feature_names_out"):
            try:
                names = preprocessor.get_feature_names_out()
                if len(names) == n_features_out:
                    return [str(n) for n in names]
            except Exception:
                logger.debug("get_feature_names_out 실패 → 폴백", exc_info=True)

        # 폴백: 원본 피처명 + 인덱스
        if len(self.feature_names) == n_features_out:
            return self.feature_names

        return [f"feature_{i}" for i in range(n_features_out)]
