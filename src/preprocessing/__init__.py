"""sklearn Pipeline 전처리 모듈 — 퍼블릭 API.

Phase 2: 전처리+모델 번들링으로 최적 Pipeline 자동 선택.
"""

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    CVResult,
    compare_pipelines,
    tune_best_pipeline,
)
from src.preprocessing.explainer import PipelineExplainer
from src.preprocessing.feature_groups import FeatureGroups, classify_features
from src.preprocessing.label_strategy import LabelResult, create_labels
from src.preprocessing.model_registry import ModelMetadata, ModelRegistry
from src.preprocessing.pipeline_builder import (
    build_all_pipelines,
    build_if_pipeline,
    build_vae_pipeline,
    build_xgb_pipeline,
)
from src.preprocessing.transparency import capture_preprocessing_metadata

__all__ = [
    # feature_groups
    "FeatureGroups",
    "classify_features",
    # pipeline_builder
    "build_xgb_pipeline",
    "build_vae_pipeline",
    "build_if_pipeline",
    "build_all_pipelines",
    # cv_selector
    "CVResult",
    "CVComparisonResult",
    "compare_pipelines",
    "tune_best_pipeline",
    # label_strategy
    "LabelResult",
    "create_labels",
    # transparency
    "capture_preprocessing_metadata",
    # explainer
    "PipelineExplainer",
    # model_registry
    "ModelMetadata",
    "ModelRegistry",
]
