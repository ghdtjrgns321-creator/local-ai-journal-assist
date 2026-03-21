"""전처리 전/후 비교 메타데이터 — White Box 투명성.

Why: 사용자가 대시보드 EDA 탭에서 "결측치: 수치→중앙값 [변경]" 같은 UI를
통해 전처리 과정을 확인·변경할 수 있으려면, Pipeline의 각 단계를
메타데이터로 추출해야 한다.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)


def capture_preprocessing_metadata(
    pipeline: Pipeline,
    X_before: pd.DataFrame,
    feature_columns: list[str],
) -> dict:
    """전처리 전/후 비교 메타데이터 생성.

    Parameters
    ----------
    pipeline : fit 완료된 Pipeline
    X_before : 전처리 전 원본 DataFrame
    feature_columns : Pipeline에 투입된 피처 목록

    Returns
    -------
    대시보드 렌더링용 dict:
    {
        "steps": [...],
        "before_stats": {컬럼: {mean, std, missing_rate}},
        "after_stats": {feature_idx: {mean, std}},
        "n_features_in": int,
        "n_features_out": int,
    }
    """
    # 전처리 전 통계
    before_stats = _compute_before_stats(X_before, feature_columns)

    # Pipeline 단계 추출
    steps = _extract_steps(pipeline)

    # 전처리 후 통계 (preprocessor 단계만 transform)
    after_stats = _compute_after_stats(pipeline, X_before)

    return {
        "steps": steps,
        "before_stats": before_stats,
        "after_stats": after_stats,
        "n_features_in": len(feature_columns),
        "n_features_out": after_stats.get("n_features", 0),
    }


def _compute_before_stats(
    df: pd.DataFrame, columns: list[str],
) -> dict[str, dict]:
    """전처리 전 컬럼별 기초 통계."""
    stats = {}
    for col in columns:
        if col not in df.columns:
            continue
        s = df[col]
        entry: dict = {"missing_rate": round(float(s.isna().mean()), 4)}
        if pd.api.types.is_numeric_dtype(s):
            entry["mean"] = round(float(s.mean()), 4) if not s.isna().all() else None
            entry["std"] = round(float(s.std()), 4) if not s.isna().all() else None
        stats[col] = entry
    return stats


def _extract_steps(pipeline: Pipeline) -> list[dict]:
    """Pipeline의 각 단계(imputer, scaler 등) 메타데이터 추출."""
    steps = []
    for name, estimator in pipeline.named_steps.items():
        step_info = {"name": name, "type": type(estimator).__name__}

        # ColumnTransformer 내부 세부 정보
        if hasattr(estimator, "transformers_"):
            step_info["transformers"] = [
                {
                    "name": t_name,
                    "type": type(t_est).__name__ if not isinstance(t_est, str) else t_est,
                    "columns": list(t_cols) if hasattr(t_cols, "__iter__") else str(t_cols),
                }
                for t_name, t_est, t_cols in estimator.transformers_
            ]
        steps.append(step_info)
    return steps


def _compute_after_stats(pipeline: Pipeline, X: pd.DataFrame) -> dict:
    """전처리 후 기초 통계. preprocessor 단계만 transform."""
    result: dict = {}
    preprocessor = pipeline.named_steps.get("preprocessor")
    if preprocessor is None:
        return result

    try:
        X_transformed = preprocessor.transform(X)
        if hasattr(X_transformed, "toarray"):
            X_transformed = X_transformed.toarray()
        X_arr = np.asarray(X_transformed, dtype=float)

        result["n_features"] = X_arr.shape[1]
        result["global_mean"] = round(float(np.nanmean(X_arr)), 4)
        result["global_std"] = round(float(np.nanstd(X_arr)), 4)
    except Exception:
        logger.warning("전처리 후 통계 계산 실패", exc_info=True)
        result["n_features"] = 0

    return result
