"""Recompute the S4 10-feature trivial baseline for Phase 2 evaluation.

The Stage 3 artifact remains a historical reference. This module recomputes
the S4 10-feature shortcut score under the same GroupKFold shape used by the
Phase 2 ensemble evaluation so the anti-shortcut cap compares like-for-like.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.analysis.s4_scenario_detectability import (  # noqa: E402
    EXPECTED_DOC_COUNT,
    LABELS,
    OUT_RECALL,
    SCENARIO_ALIAS,
    TRIVIAL_FEATURES,
    attach_truth,
    load_doc_features,
    trivial_score,
)

DEFAULT_STAGE3_ARTIFACT = ROOT / "artifacts" / "stage3_trivial_shortcut_baseline.json"
DEFAULT_OUT = ROOT / "artifacts" / "phase2_trivial_10feature_baseline.json"


def _read_stage3_macro_ap(path: Path) -> float | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("phase2_ml_floor_macro_ap")
    return None if value is None else float(value)


def _read_s4_recall(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return {
        str(row["scenario"]): {
            key: (None if pd.isna(value) else value)
            for key, value in row.items()
            if key != "scenario"
        }
        for row in df.to_dict(orient="records")
    }


def _macro_ap(df: pd.DataFrame, score_col: str) -> tuple[float, dict[str, float]]:
    per_scenario: dict[str, float] = {}
    for scenario in EXPECTED_DOC_COUNT:
        y = (df["scenario"] == scenario).astype(int).to_numpy()
        score = pd.to_numeric(df[score_col], errors="coerce").fillna(0.0).to_numpy()
        per_scenario[scenario] = float(average_precision_score(y, score))
    return float(np.mean(list(per_scenario.values()))), per_scenario


def _fold_recall(
    df: pd.DataFrame,
    *,
    score_col: str,
    group_cols: tuple[str, ...],
    top_frac: float,
    n_splits: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    work = df.copy()
    work["_phase2_eval_group"] = work[list(group_cols)].astype(str).agg("_".join, axis=1)
    gkf = GroupKFold(n_splits=n_splits)
    fold_rows: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    for fold_idx, (_, test_idx) in enumerate(gkf.split(work, groups=work["_phase2_eval_group"])):
        sub = work.iloc[test_idx].copy()
        k = max(1, int(len(sub) * top_frac))
        threshold = sub[score_col].nlargest(k).iloc[-1]
        sub["_in_topk"] = sub[score_col] >= threshold
        matrix_row: dict[str, Any] = {
            "fold": int(fold_idx),
            "fold_size": int(len(sub)),
            "k": int(k),
        }
        for scenario in EXPECTED_DOC_COUNT:
            truth = sub["scenario"] == scenario
            n_truth = int(truth.sum())
            n_hit = int((truth & sub["_in_topk"]).sum())
            matrix_row[scenario] = n_truth
            fold_rows.append(
                {
                    "fold": int(fold_idx),
                    "scenario": scenario,
                    "n_truth_in_fold": n_truth,
                    "n_hit": n_hit,
                    "recall": (n_hit / n_truth) if n_truth else None,
                    "k": int(k),
                    "fold_size": int(len(sub)),
                }
            )
        matrix_rows.append(matrix_row)
    return fold_rows, matrix_rows


def _point_recall(df: pd.DataFrame, *, score_col: str, top_frac: float) -> dict[str, float]:
    k = max(1, int(len(df) * top_frac))
    threshold = df[score_col].nlargest(k).iloc[-1]
    in_topk = df[score_col] >= threshold
    out: dict[str, float] = {}
    for scenario in EXPECTED_DOC_COUNT:
        truth = df["scenario"] == scenario
        out[scenario] = (
            float((truth & in_topk).sum() / truth.sum())
            if truth.any()
            else float("nan")
        )
    return out


def compute_trivial_baseline(
    *,
    top_frac: float = 0.01,
    n_splits: int = 5,
    group_cols: tuple[str, ...] = ("company_code", "fiscal_year"),
    stage3_artifact: Path = DEFAULT_STAGE3_ARTIFACT,
    s4_recall_csv: Path = OUT_RECALL,
) -> dict[str, Any]:
    """Return a Phase 2 comparable 10-feature trivial baseline.

    The score is the S4 `TRIVIAL_FEATURES` sum. Metrics are document-level and
    use GroupKFold with the same default group shape as S4/S8: company × year.
    """
    truth = pd.read_csv(LABELS)
    doc_df = attach_truth(load_doc_features(), truth)
    doc_df["trivial_10feature_score"] = trivial_score(doc_df)
    found = int((doc_df["scenario"] != "normal").sum())
    expected = int(sum(EXPECTED_DOC_COUNT.values()))
    if found != expected:
        raise ValueError(f"truth join mismatch: found={found}, expected={expected}")

    macro_ap, per_scenario_ap = _macro_ap(doc_df, "trivial_10feature_score")
    fold_recall, fold_truth_count_matrix = _fold_recall(
        doc_df,
        score_col="trivial_10feature_score",
        group_cols=group_cols,
        top_frac=top_frac,
        n_splits=n_splits,
    )
    point_recall = _point_recall(doc_df, score_col="trivial_10feature_score", top_frac=top_frac)

    return {
        "metric_scope": "document_level",
        "score_name": "trivial_10feature_score",
        "trivial_features": list(TRIVIAL_FEATURES),
        "scenario_alias": dict(SCENARIO_ALIAS),
        "groupkfold": {
            "group_cols": list(group_cols),
            "n_splits": int(n_splits),
            "top_frac": float(top_frac),
            "shuffle": False,
        },
        "dataset": {
            "n_docs": int(len(doc_df)),
            "n_truth": found,
            "scenario_counts": {
                scenario: int((doc_df["scenario"] == scenario).sum())
                for scenario in EXPECTED_DOC_COUNT
            },
        },
        "macro_ap": macro_ap,
        "per_scenario_ap": per_scenario_ap,
        "recall_at_top_frac": point_recall,
        "fold_recall": fold_recall,
        "fold_truth_count_matrix": fold_truth_count_matrix,
        "source_references": {
            "stage3_trivial_macro_ap": _read_stage3_macro_ap(stage3_artifact),
            "stage3_artifact": str(stage3_artifact),
            "s4_scenario_recall_csv": str(s4_recall_csv),
            "s4_scenario_recall": _read_s4_recall(s4_recall_csv),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute S4 10-feature trivial baseline.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--top-frac", type=float, default=0.01)
    parser.add_argument("--n-splits", type=int, default=5)
    args = parser.parse_args(argv)

    result = compute_trivial_baseline(top_frac=args.top_frac, n_splits=args.n_splits)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
