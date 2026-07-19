"""Reusable scenario detectability metrics for Phase 2 evaluation."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

CI_WIDTH_INSIGNIFICANT = 0.15


def _scenario_names(
    df: pd.DataFrame,
    expected_doc_count: Mapping[str, int] | None,
) -> list[str]:
    if expected_doc_count is not None:
        return list(expected_doc_count)
    if "scenario" not in df.columns:
        raise ValueError("df must contain a 'scenario' column")
    return sorted(str(s) for s in df["scenario"].dropna().unique() if str(s) != "normal")


def groupkfold_recall_at_k(
    df: pd.DataFrame,
    score_col: str,
    top_frac: float = 0.01,
    n_splits: int = 5,
    expected_doc_count: Mapping[str, int] | None = None,
    group_cols: tuple[str, str] = ("company_code", "fiscal_year"),
) -> pd.DataFrame:
    """Compute scenario recall@K on GroupKFold validation folds."""
    missing_cols = [col for col in [*group_cols, "scenario", score_col] if col not in df.columns]
    if missing_cols:
        raise ValueError(f"df missing required columns: {missing_cols}")

    df = df.copy()
    df["_evaluation_group"] = df[group_cols[0]].astype(str) + "_" + df[group_cols[1]].astype(str)
    gkf = GroupKFold(n_splits=n_splits)
    fold_records = []
    scenarios = _scenario_names(df, expected_doc_count)

    for fold_idx, (_, test_idx) in enumerate(gkf.split(df, groups=df["_evaluation_group"])):
        sub = df.iloc[test_idx].copy()
        k = max(1, int(len(sub) * top_frac))
        threshold = sub[score_col].nlargest(k).iloc[-1]
        sub["in_topk"] = sub[score_col] >= threshold
        for scenario in scenarios:
            sc_truth = sub[sub["scenario"] == scenario]
            n_truth_fold = len(sc_truth)
            n_hit = int(sc_truth["in_topk"].sum())
            fold_records.append(
                {
                    "fold": fold_idx,
                    "scenario": scenario,
                    "n_truth_in_fold": n_truth_fold,
                    "n_hit": n_hit,
                    "recall": (n_hit / n_truth_fold) if n_truth_fold else np.nan,
                    "k": k,
                    "fold_size": len(sub),
                }
            )
    return pd.DataFrame(fold_records)


def bootstrap_ci(
    df: pd.DataFrame,
    score_col: str,
    n_boot: int = 1000,
    top_frac: float = 0.01,
    expected_doc_count: Mapping[str, int] | None = None,
    random_state: int = 2026,
    ci_width_insignificant: float = CI_WIDTH_INSIGNIFICANT,
) -> pd.DataFrame:
    """Bootstrap scenario recall@K confidence intervals."""
    if "scenario" not in df.columns or score_col not in df.columns:
        raise ValueError("df must contain 'scenario' and score columns")

    rng = np.random.default_rng(random_state)
    k = max(1, int(len(df) * top_frac))
    threshold = df[score_col].nlargest(k).iloc[-1]
    df = df.copy()
    df["in_topk"] = df[score_col] >= threshold
    rows = []
    for scenario in _scenario_names(df, expected_doc_count):
        sc_truth = df[df["scenario"] == scenario]
        n = len(sc_truth)
        if n == 0:
            continue
        hit_mask = sc_truth["in_topk"].astype(int).to_numpy()
        boot = rng.choice(hit_mask, size=(n_boot, n), replace=True).mean(axis=1)
        lo, hi = np.quantile(boot, [0.025, 0.975])
        width = hi - lo
        rows.append(
            {
                "scenario": scenario,
                "n_truth": n,
                "point_recall": float(hit_mask.mean()),
                "ci_lo": float(lo),
                "ci_hi": float(hi),
                "ci_width": float(width),
                "statistically_insignificant": bool(width > ci_width_insignificant),
            }
        )
    return pd.DataFrame(rows)
