"""Run a Tritscher ERP-Fraud VAE shadow benchmark.

This script uses the project `AuditVAE` model class, but builds a Tritscher-
specific canonical feature matrix because the external SAP simulation schema is
not the project journal-entry schema. Results are diagnostic only.

Usage:
    uv run python tools/scripts/benchmark_tritscher_vae_shadow.py \
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
import torch
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.preprocessing.vae_model import AuditVAE, vae_loss  # noqa: E402
from tools.scripts.benchmark_tritscher_shadow import (  # noqa: E402
    _document_metrics,
    _make_preprocessor,
    _metrics_for_scores,
    _prepare_features,
    _read_transactions,
)

DEFAULT_EPOCHS = 20
DEFAULT_BATCH_SIZE = 512
DEFAULT_HIDDEN_DIM = 64
DEFAULT_LATENT_DIM = 16
DEFAULT_LR = 1e-3
DEFAULT_BETA = 1.0
DEFAULT_TRAIN_CAP = 80_000
DEFAULT_PATIENCE = 4


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _finite_or_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _finite_or_none(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_or_none(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _to_dense_float32(matrix: Any) -> np.ndarray:
    if hasattr(matrix, "toarray"):
        matrix = matrix.toarray()
    return np.asarray(matrix, dtype=np.float32)


def _cap_train_rows(df: pd.DataFrame, *, cap_rows: int, random_state: int) -> pd.DataFrame:
    if len(df) <= cap_rows:
        return df.copy()
    return df.sample(n=cap_rows, random_state=random_state).sort_index().copy()


def _train_vae(
    x_train: np.ndarray,
    x_val: np.ndarray,
    *,
    hidden_dim: int,
    latent_dim: int,
    epochs: int,
    batch_size: int,
    lr: float,
    beta: float,
    patience: int,
    random_state: int,
) -> tuple[AuditVAE, list[dict[str, float]], str]:
    torch.manual_seed(random_state)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(random_state)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AuditVAE(x_train.shape[1], latent_dim=latent_dim, hidden_dim=hidden_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    train_tensor = torch.from_numpy(x_train)
    val_tensor = torch.from_numpy(x_val)
    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(train_tensor),
        batch_size=batch_size,
        shuffle=True,
    )

    best_state: dict[str, torch.Tensor] | None = None
    best_val = float("inf")
    patience_left = patience
    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []
        for (batch_cpu,) in loader:
            batch = batch_cpu.to(device)
            recon, mu, logvar = model(batch)
            loss = vae_loss(recon, batch, mu, logvar, beta=beta)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        val_scores = _reconstruction_errors(
            model,
            val_tensor.numpy(),
            batch_size=batch_size,
            device=device,
        )
        val_loss = float(np.mean(val_scores))
        train_loss = float(np.mean(train_losses))
        history.append({"epoch": float(epoch), "train_loss": train_loss, "val_recon": val_loss})
        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()
            }
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, history, device


def _reconstruction_errors(
    model: AuditVAE,
    x: np.ndarray,
    *,
    batch_size: int,
    device: str,
) -> np.ndarray:
    model.eval()
    result: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(x), batch_size):
            batch = torch.from_numpy(x[start : start + batch_size]).to(device)
            recon, _, _ = model(batch)
            result.append(((recon - batch) ** 2).mean(dim=1).detach().cpu().numpy())
    return np.concatenate(result, axis=0)


def _ecdf_from_train(train_scores: np.ndarray, scores: np.ndarray) -> np.ndarray:
    sorted_train = np.sort(train_scores)
    return np.searchsorted(sorted_train, scores, side="right") / max(len(sorted_train), 1)


def _run_holdout(
    df: pd.DataFrame,
    holdout_run: str,
    *,
    max_categories: int,
    train_cap_rows: int,
    epochs: int,
    batch_size: int,
    hidden_dim: int,
    latent_dim: int,
    lr: float,
    beta: float,
    patience: int,
    random_state: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    train_pool = df[(df["run_id"].ne(holdout_run)) & (~df["is_labeled_fraud"])].copy()
    train_pool = _cap_train_rows(train_pool, cap_rows=train_cap_rows, random_state=random_state)
    train_df, val_df = train_test_split(
        train_pool,
        test_size=0.2,
        random_state=random_state,
        shuffle=True,
    )
    test_df = df[df["run_id"].eq(holdout_run)].copy()

    preprocessor = _make_preprocessor(max_categories=max_categories)
    x_train = _to_dense_float32(preprocessor.fit_transform(train_df))
    x_val = _to_dense_float32(preprocessor.transform(val_df))
    x_test = _to_dense_float32(preprocessor.transform(test_df))

    model, history, device = _train_vae(
        x_train,
        x_val,
        hidden_dim=hidden_dim,
        latent_dim=latent_dim,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        beta=beta,
        patience=patience,
        random_state=random_state,
    )
    train_raw = _reconstruction_errors(model, x_train, batch_size=batch_size, device=device)
    test_raw = _reconstruction_errors(model, x_test, batch_size=batch_size, device=device)
    test_ecdf = _ecdf_from_train(train_raw, test_raw)

    scored = test_df[
        [
            "document_id",
            "run_id",
            "source_file",
            "Label",
            "is_labeled_fraud",
            "Betrag Hauswaehr",
            "Sachkonto",
            "Kreditor",
            "Transaktionsart",
        ]
    ].copy()
    scored["vae_recon_error"] = test_raw
    scored["vae_ecdf_score"] = test_ecdf
    scored["anomaly_score"] = test_ecdf
    scored = scored.sort_values("vae_ecdf_score", ascending=False)

    row_metrics = _metrics_for_scores(scored["is_labeled_fraud"].astype(bool), test_ecdf)
    doc_metrics = _document_metrics(scored)
    result = {
        "holdout_run": holdout_run,
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
        "test_rows": int(len(test_df)),
        "test_documents": int(test_df["document_id"].nunique()),
        "model": "project_audit_vae_external_shadow",
        "device": device,
        "epochs_completed": len(history),
        "best_val_recon": min((item["val_recon"] for item in history), default=None),
        "row_level": row_metrics,
        "document_level": doc_metrics,
    }
    return result, scored.head(200)


def _flatten(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        row: dict[str, Any] = {
            "holdout_run": result["holdout_run"],
            "train_rows": result["train_rows"],
            "val_rows": result["val_rows"],
            "test_rows": result["test_rows"],
            "epochs_completed": result["epochs_completed"],
            "best_val_recon": result["best_val_recon"],
        }
        for prefix in ("row_level", "document_level"):
            for key, value in result[prefix].items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _write_markdown(path: Path, summary: dict[str, Any], run_table: pd.DataFrame) -> None:
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
    display = run_table[[col for col in display_cols if col in run_table.columns]].copy()
    display = display.where(pd.notna(display), "")
    lines = [
        "# Tritscher ERP-Fraud VAE Shadow Benchmark",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Status: **{summary['status']}**",
        f"- Rows: {summary['rows']:,}",
        f"- Fraud rows: {summary['fraud_rows']:,}",
        f"- Model: `{summary['model']}`",
        "",
        "This benchmark uses the project `AuditVAE` architecture on a Tritscher-specific "
        "canonical matrix. It is external simulation evidence only.",
        "",
        "## Run-Holdout Results",
        "",
        display.to_markdown(index=False),
        "",
        "## Interpretation",
        "",
        "- `Label`, `source_file`, and `run_id` are denied as features.",
        "- Training uses only `Label == NonFraud` rows from non-holdout runs.",
        "- The score is reconstruction-error ECDF against the training distribution.",
        "- This does not activate supervised, transformer, sequence, or stacking families.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-categories", type=int, default=50)
    parser.add_argument("--train-cap-rows", type=int, default=DEFAULT_TRAIN_CAP)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--hidden-dim", type=int, default=DEFAULT_HIDDEN_DIM)
    parser.add_argument("--latent-dim", type=int, default=DEFAULT_LATENT_DIM)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--beta", type=float, default=DEFAULT_BETA)
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    parser.add_argument("--random-state", type=int, default=20260519)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = _prepare_features(_read_transactions(input_dir))
    results: list[dict[str, Any]] = []
    top_scores: list[pd.DataFrame] = []
    for holdout_run in sorted(df["run_id"].unique().tolist()):
        result, scored = _run_holdout(
            df,
            holdout_run,
            max_categories=args.max_categories,
            train_cap_rows=args.train_cap_rows,
            epochs=args.epochs,
            batch_size=args.batch_size,
            hidden_dim=args.hidden_dim,
            latent_dim=args.latent_dim,
            lr=args.lr,
            beta=args.beta,
            patience=args.patience,
            random_state=args.random_state,
        )
        results.append(result)
        top_scores.append(scored)

    run_table = _flatten(results)
    top_score_table = pd.concat(top_scores, ignore_index=True) if top_scores else pd.DataFrame()
    summary = {
        "created_at": _now_iso(),
        "status": "GO_WITH_CAVEAT",
        "rows": int(len(df)),
        "documents": int(df["document_id"].nunique()),
        "fraud_rows": int(df["is_labeled_fraud"].sum()),
        "model": "project_audit_vae_external_shadow",
        "feature_deny_columns": ["Label", "source_file", "run_id"],
        "results": results,
    }
    summary = _finite_or_none(summary)
    (output_dir / "tritscher_vae_shadow_benchmark_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    run_table.to_csv(
        output_dir / "tritscher_vae_shadow_benchmark_runs.csv",
        index=False,
        encoding="utf-8-sig",
    )
    top_score_table.to_csv(
        output_dir / "tritscher_vae_shadow_top_scores.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _write_markdown(output_dir / "tritscher_vae_shadow_benchmark.md", summary, run_table)
    print(
        json.dumps(
            {"status": summary["status"], "runs": run_table.to_dict(orient="records")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
