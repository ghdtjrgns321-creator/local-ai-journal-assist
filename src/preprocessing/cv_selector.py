"""StratifiedKFold Pipeline 비교 + GridSearchCV 튜닝.

Why: 이상 전표 1% 미만 극단 불균형 → 기본 KFold 시 양성 0건 Fold 발생.
StratifiedKFold를 강제하여 Fold별 양성 비율을 유지한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import reduce

import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score

logger = logging.getLogger(__name__)


@dataclass
class CVResult:
    """단일 Pipeline CV 결과."""

    pipeline_name: str
    mean_f1: float
    std_f1: float
    scores: list[float]


@dataclass
class CVComparisonResult:
    """다수 Pipeline 비교 결과."""

    results: dict[str, CVResult]
    best_pipeline_name: str
    comparison_table: pd.DataFrame


def _ensure_stratified_kfold(cv: int | StratifiedKFold = 5) -> StratifiedKFold:
    """int → StratifiedKFold 변환, 기존 인스턴스는 passthrough."""
    if isinstance(cv, StratifiedKFold):
        return cv
    return StratifiedKFold(n_splits=cv, shuffle=True, random_state=42)


def compare_pipelines(
    pipelines: dict,
    X: np.ndarray,
    y: np.ndarray,
    cv: int | StratifiedKFold = 5,
    scoring: str = "f1_macro",
) -> CVComparisonResult:
    """동일 데이터로 여러 Pipeline의 CV 성능을 비교."""
    skf = _ensure_stratified_kfold(cv)
    results: dict[str, CVResult] = {}

    for name, pipe in pipelines.items():
        # Why: VAE(torch CUDA) + joblib fork → CUDA context 충돌 방지
        n_jobs = 1  # 전체 직렬. 비-VAE 병렬화는 Phase 2c에서 검토
        scores = cross_val_score(pipe, X, y, cv=skf, scoring=scoring, n_jobs=n_jobs)
        results[name] = CVResult(
            pipeline_name=name,
            mean_f1=float(scores.mean()),
            std_f1=float(scores.std()),
            scores=scores.tolist(),
        )
        _cleanup_gpu_if_needed(pipe)

    best_name = max(results, key=lambda k: results[k].mean_f1)
    table = pd.DataFrame([
        {"pipeline": r.pipeline_name, "mean_f1": r.mean_f1, "std_f1": r.std_f1}
        for r in results.values()
    ])

    return CVComparisonResult(
        results=results,
        best_pipeline_name=best_name,
        comparison_table=table,
    )


def tune_best_pipeline(
    pipeline,
    X: np.ndarray,
    y: np.ndarray,
    param_grid: dict,
    cv: int | StratifiedKFold = 5,
) -> tuple:
    """GridSearchCV로 최적 하이퍼파라미터 탐색."""
    skf = _ensure_stratified_kfold(cv)
    n_combos = _count_combinations(param_grid)
    logger.info("GridSearchCV 시작: %d 조합", n_combos)

    gs = GridSearchCV(pipeline, param_grid, cv=skf, scoring="f1_macro", refit=True)
    gs.fit(X, y)
    _cleanup_gpu_if_needed(gs.best_estimator_)
    return gs.best_estimator_, gs.best_params_


def _count_combinations(param_grid: dict) -> int:
    """파라미터 그리드의 전체 조합 수 계산."""
    if not param_grid:
        return 0
    return reduce(lambda a, b: a * b, (len(v) for v in param_grid.values()), 1)


def _has_vae(pipe) -> bool:
    """Pipeline 내부에 VAEDetector 스텝이 있는지 검사.

    Why: VAEDetector는 torch CUDA를 사용하므로 joblib 병렬(fork)시
    CUDA context가 복제되어 충돌한다. 감지 시 n_jobs=1 강제 필요.
    """
    # Why: core-only 환경(torch 미설치)에서 ImportError 방지
    try:
        from src.preprocessing.vae_wrapper import VAEDetector
    except ImportError:
        return False

    if isinstance(pipe, VAEDetector):
        return True
    # sklearn Pipeline: named_steps 순회
    if hasattr(pipe, "named_steps"):
        return any(isinstance(s, VAEDetector) for s in pipe.named_steps.values())
    return False


def _cleanup_gpu_if_needed(pipe) -> None:
    """VAE Pipeline이면 VRAM 정리."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
