"""Document-safe GroupKFold pipeline comparison + GridSearchCV tuning."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import reduce

import pandas as pd
from sklearn.model_selection import GridSearchCV, GroupKFold, cross_val_score

from src.preprocessing.split_strategy import build_document_group_kfold

logger = logging.getLogger(__name__)


@dataclass
class CVResult:
    pipeline_name: str
    mean_f1: float
    std_f1: float
    scores: list[float]


@dataclass
class CVComparisonResult:
    results: dict[str, CVResult]
    best_pipeline_name: str
    comparison_table: pd.DataFrame


def _ensure_group_kfold(cv: int | GroupKFold = 5) -> GroupKFold:
    """Convert an integer into GroupKFold, passthrough existing instances."""
    if isinstance(cv, GroupKFold):
        return cv
    return GroupKFold(n_splits=cv)


def compare_pipelines(
    pipelines: dict,
    X: pd.DataFrame,
    y,
    cv: int | GroupKFold = 5,
    scoring: str = "f1_macro",
) -> CVComparisonResult:
    """Compare candidate pipelines with document-level GroupKFold."""
    gkf = _ensure_group_kfold(cv)
    _, groups = build_document_group_kfold(X, n_splits=gkf.n_splits)
    model_X = _drop_split_columns(X)
    results: dict[str, CVResult] = {}

    for name, pipe in pipelines.items():
        scores = cross_val_score(
            pipe,
            model_X,
            y,
            cv=gkf,
            groups=groups,
            scoring=scoring,
            n_jobs=1,
        )
        results[name] = CVResult(
            pipeline_name=name,
            mean_f1=float(scores.mean()),
            std_f1=float(scores.std()),
            scores=scores.tolist(),
        )
        _cleanup_gpu_if_needed(pipe)

    best_name = max(results, key=lambda key: results[key].mean_f1)
    table = pd.DataFrame([
        {"pipeline": item.pipeline_name, "mean_f1": item.mean_f1, "std_f1": item.std_f1}
        for item in results.values()
    ])

    return CVComparisonResult(
        results=results,
        best_pipeline_name=best_name,
        comparison_table=table,
    )


def tune_best_pipeline(
    pipeline,
    X: pd.DataFrame,
    y,
    param_grid: dict,
    cv: int | GroupKFold = 5,
) -> tuple:
    """Tune a pipeline with document-level GroupKFold."""
    gkf = _ensure_group_kfold(cv)
    _, groups = build_document_group_kfold(X, n_splits=gkf.n_splits)
    model_X = _drop_split_columns(X)
    logger.info("GridSearchCV 시작: %d 조합", _count_combinations(param_grid))

    gs = GridSearchCV(pipeline, param_grid, cv=gkf, scoring="f1_macro", refit=True)
    gs.fit(model_X, y, groups=groups)
    _cleanup_gpu_if_needed(gs.best_estimator_)
    return gs.best_estimator_, gs.best_params_


def _count_combinations(param_grid: dict) -> int:
    if not param_grid:
        return 0
    return reduce(lambda left, right: left * right, (len(values) for values in param_grid.values()), 1)


def _cleanup_gpu_if_needed(pipe) -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _drop_split_columns(X: pd.DataFrame) -> pd.DataFrame:
    return X.drop(columns=["document_id", "fiscal_year", "posting_date"], errors="ignore")
