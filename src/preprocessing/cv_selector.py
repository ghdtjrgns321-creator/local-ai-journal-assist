"""Pipeline 비교 + GridSearchCV — StratifiedKFold 필수.

Why: 횡령/이상 전표는 전체의 1% 미만이므로, 기본 KFold를 쓰면
특정 Fold에 양성이 0건 배정되어 F1=0이 되는 대참사가 발생한다.
StratifiedKFold로 매 Fold에서 타겟 클래스 비율을 일정하게 유지한다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.model_selection import (
    GridSearchCV,
    StratifiedKFold,
    cross_val_score,
)
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)


@dataclass
class CVResult:
    """Pipeline별 cross-validation 결과."""

    pipeline_name: str
    mean_f1: float
    std_f1: float
    fit_time: float             # 평균 fit 시간(초)
    scores: list[float]         # fold별 F1
    best_params: dict | None = None


@dataclass
class CVComparisonResult:
    """전체 비교 결과."""

    results: dict[str, CVResult] = field(default_factory=dict)
    best_pipeline_name: str = ""
    best_pipeline: Pipeline | None = None
    comparison_table: pd.DataFrame | None = None


def _ensure_stratified_kfold(cv) -> StratifiedKFold:
    """cv 인자가 int이면 StratifiedKFold로 자동 변환."""
    if isinstance(cv, int):
        return StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)
    return cv


def compare_pipelines(
    pipelines: dict[str, Pipeline],
    X: pd.DataFrame | np.ndarray,
    y: pd.Series | np.ndarray,
    *,
    cv: StratifiedKFold | int = 5,
    scoring: str = "f1_macro",
    n_jobs: int = 1,
) -> CVComparisonResult:
    """3개 Pipeline cross_val_score 비교 → 최적 선택.

    Parameters
    ----------
    pipelines : {"xgb": Pipeline, "vae": Pipeline, "if": Pipeline}
    X, y : 피처와 라벨
    cv : int면 StratifiedKFold 자동 생성
    scoring : sklearn scoring 메트릭
    n_jobs : VRAM 공유 시 1 (순차 실행)
    """
    skf = _ensure_stratified_kfold(cv)
    results: dict[str, CVResult] = {}

    for name, pipe in pipelines.items():
        logger.info("Pipeline '%s' 교차 검증 시작 (cv=%d)", name, skf.n_splits)
        t0 = time.monotonic()

        scores = cross_val_score(
            pipe, X, y, cv=skf, scoring=scoring, n_jobs=n_jobs,
        )

        elapsed = time.monotonic() - t0
        result = CVResult(
            pipeline_name=name,
            mean_f1=float(np.mean(scores)),
            std_f1=float(np.std(scores)),
            fit_time=round(elapsed / skf.n_splits, 2),
            scores=scores.tolist(),
        )
        results[name] = result

        logger.info(
            "Pipeline '%s': F1=%.4f (±%.4f), %.1fs",
            name, result.mean_f1, result.std_f1, elapsed,
        )

        # VAE GPU 후 VRAM 정리
        _cleanup_gpu_if_needed(pipe)

    # 최적 Pipeline 선택
    best_name = max(results, key=lambda k: results[k].mean_f1)

    # 대시보드용 비교 테이블
    table = pd.DataFrame([
        {
            "pipeline": r.pipeline_name,
            "mean_f1": round(r.mean_f1, 4),
            "std_f1": round(r.std_f1, 4),
            "fit_time_sec": r.fit_time,
        }
        for r in results.values()
    ]).sort_values("mean_f1", ascending=False)

    logger.info("최적 Pipeline: '%s' (F1=%.4f)", best_name, results[best_name].mean_f1)

    return CVComparisonResult(
        results=results,
        best_pipeline_name=best_name,
        best_pipeline=pipelines[best_name],
        comparison_table=table,
    )


def tune_best_pipeline(
    pipeline: Pipeline,
    X: pd.DataFrame | np.ndarray,
    y: pd.Series | np.ndarray,
    param_grid: dict,
    *,
    cv: StratifiedKFold | int = 5,
    scoring: str = "f1_macro",
    n_jobs: int = 1,
) -> tuple[Pipeline, dict]:
    """최적 Pipeline에 대해 GridSearchCV로 하이퍼파라미터 튜닝.

    Returns
    -------
    (best_estimator, best_params) 튜플
    """
    skf = _ensure_stratified_kfold(cv)

    logger.info("GridSearchCV 시작: %d 파라미터 조합", _count_combinations(param_grid))

    gs = GridSearchCV(
        pipeline,
        param_grid,
        cv=skf,
        scoring=scoring,
        n_jobs=n_jobs,
        refit=True,
    )
    gs.fit(X, y)

    logger.info(
        "GridSearchCV 완료: best_score=%.4f, best_params=%s",
        gs.best_score_, gs.best_params_,
    )
    return gs.best_estimator_, gs.best_params_


def _count_combinations(param_grid: dict) -> int:
    """파라미터 조합 수 계산."""
    count = 1
    for values in param_grid.values():
        if isinstance(values, list):
            count *= len(values)
    return count


def _cleanup_gpu_if_needed(pipe: Pipeline) -> None:
    """Pipeline 내 VAE가 있으면 GPU 메모리 정리."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
