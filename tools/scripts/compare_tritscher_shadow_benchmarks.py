"""Compare Tritscher IsolationForest and VAE shadow benchmark outputs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read(path: Path, prefix: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.add_prefix(f"{prefix}_")
    return df.rename(columns={f"{prefix}_holdout_run": "holdout_run"})


def _mean_positive_holdouts(df: pd.DataFrame, columns: list[str]) -> dict[str, float | None]:
    positive = df[df["vae_row_level_positive_rows"].fillna(0).gt(0)].copy()
    out: dict[str, float | None] = {}
    for col in columns:
        if col in positive and positive[col].notna().any():
            out[col] = float(positive[col].mean())
        else:
            out[col] = None
    return out


def _write_markdown(path: Path, comparison: pd.DataFrame, summary: dict[str, Any]) -> None:
    cols = [
        "holdout_run",
        "iso_row_level_auroc",
        "vae_row_level_auroc",
        "delta_row_auroc_vae_minus_iso",
        "iso_document_level_auroc",
        "vae_document_level_auroc",
        "delta_doc_auroc_vae_minus_iso",
        "iso_document_level_recall_at_100",
        "vae_document_level_recall_at_100",
    ]
    display = comparison[[col for col in cols if col in comparison.columns]].copy()
    display = display.where(pd.notna(display), "")
    lines = [
        "# Tritscher Shadow Benchmark Comparison",
        "",
        f"- Created at: {summary['created_at']}",
        "- Models: `diagnostic_unsupervised_isolation_forest` vs "
        "`project_audit_vae_external_shadow`",
        "- Scope: external synthetic ERP shadow evidence only",
        "",
        "## Result Table",
        "",
        display.to_markdown(index=False),
        "",
        "## Summary",
        "",
        f"- Positive holdouts: {summary['positive_holdout_count']}",
        f"- Mean row AUROC, IsolationForest: {summary['means'].get('iso_row_level_auroc')}",
        f"- Mean row AUROC, VAE: {summary['means'].get('vae_row_level_auroc')}",
        f"- Mean document AUROC, IsolationForest: "
        f"{summary['means'].get('iso_document_level_auroc')}",
        f"- Mean document AUROC, VAE: {summary['means'].get('vae_document_level_auroc')}",
        "",
        "## Decision",
        "",
        "The VAE shadow benchmark is stronger than the quick IsolationForest diagnostic "
        "on document-level fraud runs, but row-level ranking remains uneven. This supports "
        "keeping PHASE2 active as unsupervised/document-prioritized shadow evidence. It "
        "does not justify activating supervised, transformer, sequence, or stacking.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    iso = _read(output_dir / "tritscher_shadow_benchmark_runs.csv", "iso")
    vae = _read(output_dir / "tritscher_vae_shadow_benchmark_runs.csv", "vae")
    comparison = iso.merge(vae, on="holdout_run", how="outer")
    comparison["delta_row_auroc_vae_minus_iso"] = (
        comparison["vae_row_level_auroc"] - comparison["iso_row_level_auroc"]
    )
    comparison["delta_doc_auroc_vae_minus_iso"] = (
        comparison["vae_document_level_auroc"] - comparison["iso_document_level_auroc"]
    )
    metric_cols = [
        "iso_row_level_auroc",
        "vae_row_level_auroc",
        "iso_document_level_auroc",
        "vae_document_level_auroc",
        "iso_document_level_recall_at_100",
        "vae_document_level_recall_at_100",
    ]
    summary = {
        "created_at": _now_iso(),
        "positive_holdout_count": int(
            comparison["vae_row_level_positive_rows"].fillna(0).gt(0).sum()
        ),
        "means": _mean_positive_holdouts(comparison, metric_cols),
    }
    comparison.to_csv(
        output_dir / "tritscher_shadow_benchmark_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output_dir / "tritscher_shadow_benchmark_comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(output_dir / "tritscher_shadow_benchmark_comparison.md", comparison, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
