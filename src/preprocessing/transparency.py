"""전처리 투명성 메타데이터 — White Box 전처리.

Why: 사용자가 전처리 전/후를 대시보드에서 확인할 수 있도록
각 단계의 변환 내용과 통계를 메타데이터로 캡처한다.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def capture_preprocessing_metadata(
    pipeline,
    X_before: pd.DataFrame,
    feature_columns: list[str],
) -> dict:
    """Pipeline 전/후 비교 메타데이터 생성."""
    before_stats = _compute_before_stats(X_before, feature_columns)
    steps = _extract_steps(pipeline)
    after_stats = _compute_after_stats(pipeline, X_before)

    n_out = after_stats.get("n_features", len(feature_columns))
    return {
        "steps": steps,
        "before_stats": before_stats,
        "after_stats": after_stats,
        "n_features_in": len(feature_columns),
        "n_features_out": n_out,
    }


def _compute_before_stats(df: pd.DataFrame, columns: list[str]) -> dict:
    """전처리 전 컬럼별 통계."""
    stats = {}
    for col in columns:
        if col not in df.columns:
            continue
        series = df[col]
        stats[col] = {
            "missing_rate": float(series.isna().mean()),
            "dtype": str(series.dtype),
            "unique_count": int(series.nunique()),
        }
    return stats


def _extract_steps(pipeline) -> list[dict]:
    """Pipeline의 각 단계 메타데이터 추출."""
    steps = []
    for name, step in pipeline.steps:
        step_info = {"name": name, "type": type(step).__name__}
        if hasattr(step, "get_params"):
            try:
                params = step.get_params(deep=False)
                # 직렬화 가능한 값만 유지
                step_info["params"] = {
                    k: v for k, v in params.items()
                    if isinstance(v, (int, float, str, bool, type(None)))
                }
            except Exception:
                step_info["params"] = {}
        steps.append(step_info)
    return steps


def _compute_after_stats(pipeline, X: pd.DataFrame) -> dict:
    """전처리 단계(preprocessor)만 적용한 후 통계."""
    result: dict = {}
    try:
        # Pipeline의 첫 번째 단계(preprocessor)만 transform
        preprocessor = pipeline.named_steps.get("preprocessor")
        if preprocessor is not None:
            X_transformed = preprocessor.transform(X)
            if hasattr(X_transformed, "shape"):
                result["n_features"] = X_transformed.shape[1]
                result["n_samples"] = X_transformed.shape[0]
    except Exception as e:
        logger.warning("after_stats 계산 실패: %s", e)
    return result
