"""sklearn Pipeline 전처리 모듈 — 퍼블릭 API.

EDAProfile → 피처 분류 → Pipeline 조립 → CV 비교 → 모델 저장.
"""

from src.preprocessing.cv_selector import (
    CVComparisonResult,
    CVResult,
    SplitStrategySelection,
    build_user_group_kfold,
    compare_pipelines,
    evaluate_stage2_auc_gaps,
    select_split_strategy,
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
from src.preprocessing.transformers import NullFlagTransformer, SafePowerTransformer
from src.preprocessing.transparency import capture_preprocessing_metadata
from src.preprocessing.vae_wrapper import VAEDetector

__all__ = [
    "CVComparisonResult",
    "CVResult",
    "FeatureGroups",
    "LabelResult",
    "ModelMetadata",
    "ModelRegistry",
    "NullFlagTransformer",
    "PipelineExplainer",
    "SafePowerTransformer",
    "SplitStrategySelection",
    "VAEDetector",
    "build_all_pipelines",
    "build_if_pipeline",
    "build_user_group_kfold",
    "build_vae_pipeline",
    "build_xgb_pipeline",
    "capture_preprocessing_metadata",
    "classify_features",
    "compare_pipelines",
    "create_labels",
    "evaluate_stage2_auc_gaps",
    "select_split_strategy",
    "tune_best_pipeline",
]
