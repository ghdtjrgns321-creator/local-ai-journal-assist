"""Run a Tritscher ERP-Fraud external shadow benchmark.

This is a diagnostic external benchmark, not a promotion path. It trains an
unsupervised model only on NonFraud rows from non-holdout runs, then evaluates
row-level and document-level ranking on each held-out run.

Usage:
    uv run python tools/scripts/benchmark_tritscher_shadow.py \
        --input-dir data/external/tritscher_erp_fraud \
        --output-dir artifacts/external_validation/tritscher_erp_fraud_20260519
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TRANSACTION_FILES = ("fraud_1.csv", "fraud_2.csv", "fraud_3.csv", "normal_1.csv", "normal_2.csv")

CANONICAL_COLUMNS = {
    "document_id": "Belegnummer",
    "line_id": "Position",
    "gl_account": "Sachkonto",
    "amount": "Betrag Hauswaehr",
    "debit_credit_indicator": "Soll/Haben-Kennz_",
    "event_time": "Erfassungsuhrzeit",
    "vendor": "Kreditor",
    "transaction_type": "Transaktionsart",
    "label": "Label",
}

NUMERIC_FEATURES = [
    "abs_amount",
    "log_abs_amount",
    "signed_amount",
    "line_position",
    "event_hour",
    "is_debit",
    "amount_is_zero",
    "gl_account_missing",
    "vendor_missing",
    "material_missing",
]

CATEGORICAL_FEATURES = [
    "Soll/Haben-Kennz_",
    "Sachkonto",
    "Buchungsschluessel",
    "Kontoart",
    "Kreditor",
    "Material",
    "Transaktionsart",
    "Vorgangsart GL",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_transactions(input_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(input_dir.rglob("*.csv")):
        if path.name not in TRANSACTION_FILES:
            continue
        frame = pd.read_csv(path, low_memory=False)
        frame["source_file"] = path.name
        frame["run_id"] = path.stem
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No Tritscher transaction CSVs found under {input_dir}")
    return pd.concat(frames, ignore_index=True)


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _event_hour(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series.astype(str), format="%H:%M:%S", errors="coerce")
    return parsed.dt.hour.astype("float64")


def _prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    amount = _to_numeric(prepared[CANONICAL_COLUMNS["amount"]]).fillna(0.0)
    dc = prepared[CANONICAL_COLUMNS["debit_credit_indicator"]].astype(str).str.upper()
    sign = np.where(dc.eq("H"), -1.0, 1.0)
    abs_amount = amount.abs()

    prepared["document_id"] = prepared[CANONICAL_COLUMNS["document_id"]].astype(str)
    prepared["line_position"] = _to_numeric(prepared[CANONICAL_COLUMNS["line_id"]])
    prepared["abs_amount"] = abs_amount
    prepared["log_abs_amount"] = np.log1p(abs_amount)
    prepared["signed_amount"] = amount * sign
    prepared["event_hour"] = _event_hour(prepared[CANONICAL_COLUMNS["event_time"]])
    prepared["is_debit"] = dc.eq("S").astype("int8")
    prepared["amount_is_zero"] = amount.eq(0).astype("int8")
    prepared["gl_account_missing"] = prepared[CANONICAL_COLUMNS["gl_account"]].isna().astype("int8")
    prepared["vendor_missing"] = prepared[CANONICAL_COLUMNS["vendor"]].isna().astype("int8")
    if "Material" in prepared:
        prepared["material_missing"] = prepared["Material"].isna().astype("int8")
    else:
        prepared["material_missing"] = 1
    prepared["is_labeled_fraud"] = (
        prepared[CANONICAL_COLUMNS["label"]].astype(str).str.lower().ne("nonfraud")
    )

    for column in CATEGORICAL_FEATURES:
        if column not in prepared.columns:
            prepared[column] = "__MISSING__"
        prepared[column] = (
            prepared[column]
            .where(prepared[column].notna(), "__MISSING__")
            .astype(str)
        )

    return prepared


def _make_preprocessor(max_categories: int) -> ColumnTransformer:
    numeric_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler(with_mean=False)),
        ]
    )
    categorical_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="__MISSING__")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    max_categories=max_categories,
                    sparse_output=True,
                ),
            ),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC_FEATURES),
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
        ],
        sparse_threshold=1.0,
    )


def _safe_auc(y_true: pd.Series, scores: np.ndarray) -> float | None:
    if y_true.nunique(dropna=False) < 2:
        return None
    return float(roc_auc_score(y_true.astype(int), scores))


def _safe_ap(y_true: pd.Series, scores: np.ndarray) -> float | None:
    if int(y_true.sum()) == 0:
        return None
    return float(average_precision_score(y_true.astype(int), scores))


def _precision_recall_at_k(y_true: pd.Series, scores: np.ndarray, k: int) -> dict[str, Any]:
    if len(y_true) == 0:
        return {"k": k, "precision": None, "recall": None, "hits": 0}
    actual_k = min(k, len(y_true))
    order = np.argsort(scores)[::-1][:actual_k]
    positives = int(y_true.sum())
    hits = int(y_true.iloc[order].sum())
    return {
        "k": actual_k,
        "precision": float(hits / actual_k) if actual_k else None,
        "recall": float(hits / positives) if positives else None,
        "hits": hits,
    }


def _metrics_for_scores(
    y_true: pd.Series,
    scores: np.ndarray,
    k_values: tuple[int, ...] = (100, 500, 1000),
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "rows": int(len(y_true)),
        "positive_rows": int(y_true.sum()),
        "prevalence": float(y_true.mean()) if len(y_true) else None,
        "auroc": _safe_auc(y_true, scores),
        "average_precision": _safe_ap(y_true, scores),
    }
    for k in k_values:
        item = _precision_recall_at_k(y_true, scores, k)
        metrics[f"precision_at_{k}"] = item["precision"]
        metrics[f"recall_at_{k}"] = item["recall"]
        metrics[f"hits_at_{k}"] = item["hits"]
    top_one_pct_k = max(1, int(np.ceil(len(y_true) * 0.01)))
    item = _precision_recall_at_k(y_true, scores, top_one_pct_k)
    metrics["precision_at_top_1pct"] = item["precision"]
    metrics["recall_at_top_1pct"] = item["recall"]
    metrics["hits_at_top_1pct"] = item["hits"]
    metrics["top_1pct_k"] = item["k"]
    return metrics


def _document_metrics(scored: pd.DataFrame) -> dict[str, Any]:
    docs = (
        scored.groupby("document_id", dropna=False)
        .agg(is_labeled_fraud=("is_labeled_fraud", "max"), anomaly_score=("anomaly_score", "max"))
        .reset_index()
    )
    metrics = _metrics_for_scores(
        docs["is_labeled_fraud"].astype(bool),
        docs["anomaly_score"].to_numpy(),
    )
    metrics["documents"] = metrics.pop("rows")
    metrics["positive_documents"] = metrics.pop("positive_rows")
    return metrics


def _run_holdout(
    df: pd.DataFrame,
    holdout_run: str,
    *,
    max_categories: int,
    max_samples: int,
    n_estimators: int,
    random_state: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    train = df[(df["run_id"].ne(holdout_run)) & (~df["is_labeled_fraud"])].copy()
    test = df[df["run_id"].eq(holdout_run)].copy()
    preprocessor = _make_preprocessor(max_categories=max_categories)
    model = IsolationForest(
        n_estimators=n_estimators,
        max_samples=min(max_samples, len(train)),
        contamination="auto",
        random_state=random_state,
        n_jobs=-1,
    )
    x_train = preprocessor.fit_transform(train)
    model.fit(x_train)
    x_test = preprocessor.transform(test)
    scores = -model.score_samples(x_test)

    scored = test[
        [
            "document_id",
            "run_id",
            "source_file",
            CANONICAL_COLUMNS["label"],
            "is_labeled_fraud",
            CANONICAL_COLUMNS["amount"],
            CANONICAL_COLUMNS["gl_account"],
            CANONICAL_COLUMNS["vendor"],
            CANONICAL_COLUMNS["transaction_type"],
        ]
    ].copy()
    scored["anomaly_score"] = scores
    scored = scored.sort_values("anomaly_score", ascending=False)

    row_metrics = _metrics_for_scores(scored["is_labeled_fraud"].astype(bool), scores)
    doc_metrics = _document_metrics(scored)
    result = {
        "holdout_run": holdout_run,
        "train_rows": int(len(train)),
        "train_runs": sorted(train["run_id"].unique().tolist()),
        "test_rows": int(len(test)),
        "test_documents": int(test["document_id"].nunique()),
        "feature_policy": "Label/source_file/run_id denied; run_id used only for holdout",
        "model": "diagnostic_unsupervised_isolation_forest",
        "row_level": row_metrics,
        "document_level": doc_metrics,
    }
    return result, scored.head(200)


def _flatten_run_results(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        row: dict[str, Any] = {
            "holdout_run": result["holdout_run"],
            "train_rows": result["train_rows"],
            "test_rows": result["test_rows"],
            "test_documents": result["test_documents"],
        }
        for prefix in ("row_level", "document_level"):
            for key, value in result[prefix].items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _write_markdown(output_path: Path, summary: dict[str, Any], run_table: pd.DataFrame) -> None:
    lines = [
        "# Tritscher ERP-Fraud Shadow Benchmark",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Status: **{summary['status']}**",
        f"- Rows: {summary['rows']:,}",
        f"- Fraud rows: {summary['fraud_rows']:,}",
        f"- Model: `{summary['model']}`",
        "",
        "This is an external simulation shadow benchmark. It does not activate supervised, "
        "transformer, sequence, or stacking families.",
        "",
        "## Run-Holdout Results",
        "",
    ]
    display_cols = [
        "holdout_run",
        "row_level_positive_rows",
        "row_level_auroc",
        "row_level_average_precision",
        "row_level_recall_at_100",
        "row_level_recall_at_top_1pct",
        "document_level_positive_documents",
        "document_level_auroc",
        "document_level_average_precision",
        "document_level_recall_at_100",
        "document_level_recall_at_top_1pct",
    ]
    existing_cols = [col for col in display_cols if col in run_table.columns]
    markdown_table = run_table[existing_cols].copy()
    markdown_table = markdown_table.where(pd.notna(markdown_table), "")
    lines.append(markdown_table.to_markdown(index=False))
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- `Label`, `source_file`, and `run_id` are denied as features.",
            "- `run_id` is used only as the holdout boundary.",
            "- This dataset is synthetic ERP simulation, not real Korean manufacturing GL.",
            "- Good external ranking here supports robustness checks only; "
            "it is not a dormant-family activation trigger.",
            "- Weak ranking here is useful evidence about cross-simulation limits, "
            "not a reason to fit DataSynth.",
            "",
            "## Output Files",
            "",
            "- `tritscher_shadow_benchmark_summary.json`",
            "- `tritscher_shadow_benchmark_runs.csv`",
            "- `tritscher_shadow_top_scores.csv`",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-categories", type=int, default=50)
    parser.add_argument("--max-samples", type=int, default=10_000)
    parser.add_argument("--n-estimators", type=int, default=100)
    parser.add_argument("--random-state", type=int, default=20260519)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _prepare_features(_read_transactions(input_dir))
    run_ids = sorted(df["run_id"].unique().tolist())
    results: list[dict[str, Any]] = []
    top_scores: list[pd.DataFrame] = []
    for holdout_run in run_ids:
        result, top_scored = _run_holdout(
            df,
            holdout_run,
            max_categories=args.max_categories,
            max_samples=args.max_samples,
            n_estimators=args.n_estimators,
            random_state=args.random_state,
        )
        results.append(result)
        top_scores.append(top_scored)

    run_table = _flatten_run_results(results)
    top_score_table = pd.concat(top_scores, ignore_index=True) if top_scores else pd.DataFrame()
    positive_runs = run_table[run_table["row_level_positive_rows"].gt(0)]
    status = "GO_WITH_CAVEAT" if not positive_runs.empty else "NO_LABELED_HOLDOUT"
    summary = {
        "created_at": _now_iso(),
        "status": status,
        "rows": int(len(df)),
        "documents": int(df["document_id"].nunique()),
        "fraud_rows": int(df["is_labeled_fraud"].sum()),
        "run_ids": run_ids,
        "model": "diagnostic_unsupervised_isolation_forest",
        "feature_deny_columns": ["Label", "source_file", "run_id"],
        "results": results,
    }

    (output_dir / "tritscher_shadow_benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    run_table.to_csv(
        output_dir / "tritscher_shadow_benchmark_runs.csv",
        index=False,
        encoding="utf-8-sig",
    )
    top_score_table.to_csv(
        output_dir / "tritscher_shadow_top_scores.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _write_markdown(output_dir / "tritscher_shadow_benchmark.md", summary, run_table)
    print(
        json.dumps(
            {"status": status, "runs": run_table.to_dict(orient="records")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
