"""Document-safe GroupKFold pipeline comparison + GridSearchCV tuning."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import reduce
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV, GroupKFold, cross_val_score

from src.preprocessing.split_strategy import (
    TemporalHoldoutSplit,
    build_document_group_kfold,
    split_user_year_holdout,
)

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


@dataclass(frozen=True)
class SplitStrategySelection:
    name: str
    cv: GroupKFold | None = None
    groups: np.ndarray | None = None
    holdout: TemporalHoldoutSplit | None = None


STAGE2_RANDOM_MINUS_GROUP_AUC_GAP_THRESHOLD = 0.05
STAGE2_GROUP_MINUS_TIME_AUC_GAP_THRESHOLD = 0.03


def _ensure_group_kfold(cv: int | GroupKFold = 5) -> GroupKFold:
    """Convert an integer into GroupKFold, passthrough existing instances."""
    if isinstance(cv, GroupKFold):
        return cv
    if not isinstance(cv, int):
        raise ValueError(
            "row-level KFold is not allowed for Phase 2 evaluation; "
            "use GroupKFold with document_id or created_by groups",
        )
    return GroupKFold(n_splits=cv)


def build_user_group_kfold(
    df: pd.DataFrame,
    n_splits: int = 5,
    fallback_to_doc: bool = True,
) -> tuple[GroupKFold, np.ndarray]:
    """Build user-level GroupKFold inputs, falling back to document groups if needed."""
    if "created_by" not in df.columns:
        raise ValueError("created_by column is required for user GroupKFold evaluation")

    groups = df["created_by"].astype(str).to_numpy()
    unique_users = np.unique(groups)
    if len(unique_users) < n_splits:
        if not fallback_to_doc:
            raise ValueError(
                f"not enough unique created_by values for GroupKFold: "
                f"{len(unique_users)} < {n_splits}",
            )
        logger.warning(
            "created_by unique count %d is below n_splits=%d; "
            "falling back to document_id GroupKFold",
            len(unique_users),
            n_splits,
        )
        return build_document_group_kfold(df, n_splits=n_splits)
    return GroupKFold(n_splits=n_splits), groups


def select_split_strategy(
    df: pd.DataFrame,
    feature_metadata: Any,
    *,
    n_splits: int = 5,
) -> SplitStrategySelection:
    """Select the leak-safe split strategy implied by feature metadata."""
    if bool(getattr(feature_metadata, "uses_user_features", False)):
        cv, groups = build_user_group_kfold(df, n_splits=n_splits)
        return SplitStrategySelection(name="user_group_kfold", cv=cv, groups=groups)

    if bool(getattr(feature_metadata, "requires_temporal_holdout", False)):
        holdout = split_user_year_holdout(df)
        return SplitStrategySelection(name="split_user_year_holdout", holdout=holdout)

    cv, groups = build_document_group_kfold(df, n_splits=n_splits)
    return SplitStrategySelection(name="document_group_kfold", cv=cv, groups=groups)


def evaluate_stage2_auc_gaps(
    *,
    random_auc: float,
    group_auc: float,
    time_auc: float,
) -> dict[str, float | bool]:
    """Apply Stage 2 split-leakage AUC gap thresholds."""
    random_minus_group = float(random_auc - group_auc)
    group_minus_time = float(group_auc - time_auc)
    return {
        "random_minus_group": random_minus_group,
        "group_minus_time": group_minus_time,
        "user_level_leakage_confirmed": (
            random_minus_group > STAGE2_RANDOM_MINUS_GROUP_AUC_GAP_THRESHOLD
        ),
        "temporal_leakage_confirmed": (
            group_minus_time > STAGE2_GROUP_MINUS_TIME_AUC_GAP_THRESHOLD
        ),
    }


def compare_pipelines(
    pipelines: dict,
    X: pd.DataFrame,
    y,
    cv: int | GroupKFold = 5,
    scoring: str = "f1_macro",
    group_source: pd.DataFrame | None = None,
) -> CVComparisonResult:
    """Compare candidate pipelines with document-level GroupKFold."""
    gkf = _ensure_group_kfold(cv)
    _, groups = build_document_group_kfold(
        X if group_source is None else group_source,
        n_splits=gkf.n_splits,
    )
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
    return reduce(
        lambda left, right: left * right,
        (len(values) for values in param_grid.values()),
        1,
    )


def _cleanup_gpu_if_needed(pipe) -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _drop_split_columns(X: pd.DataFrame) -> pd.DataFrame:
    return X.drop(columns=["document_id", "fiscal_year", "posting_date"], errors="ignore")
