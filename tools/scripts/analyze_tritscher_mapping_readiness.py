"""Analyze Tritscher ERP-Fraud mapping and shadow-benchmark readiness."""

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

TRANSACTION_FILES = ("fraud_1.csv", "fraud_2.csv", "fraud_3.csv", "normal_1.csv", "normal_2.csv")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dataset_name(path: Path) -> str:
    return path.stem


def _read_transactions(input_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(input_dir.rglob("*.csv")):
        if path.name not in TRANSACTION_FILES:
            continue
        df = pd.read_csv(path, low_memory=False)
        df["source_file"] = path.name
        df["run_id"] = _dataset_name(path)
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _summarize(df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    if df.empty:
        return {"status": "NO_DATA", "reason": "No transaction CSV files found."}, pd.DataFrame()

    required = {
        "Label",
        "Belegnummer",
        "Position",
        "Betrag Hauswaehr",
        "Soll/Haben-Kennz_",
        "Sachkonto",
        "Erfassungsuhrzeit",
    }
    missing = sorted(required - set(df.columns))
    label_counts = df["Label"].value_counts(dropna=False).sort_index().to_dict()
    run_label_counts = (
        df.groupby(["run_id", "Label"], dropna=False).size().reset_index(name="rows")
    )
    doc_summary = (
        df.groupby("run_id", dropna=False)
        .agg(
            rows=("Label", "size"),
            documents=("Belegnummer", "nunique"),
            labels=("Label", "nunique"),
            fraud_rows=(
                "Label",
                lambda value: int(value.astype(str).str.lower().ne("nonfraud").sum()),
            ),
            amount_non_null=("Betrag Hauswaehr", lambda value: int(value.notna().sum())),
            account_non_null=("Sachkonto", lambda value: int(value.notna().sum())),
            vendor_non_null=("Kreditor", lambda value: int(value.notna().sum()))
            if "Kreditor" in df.columns
            else ("Label", "size"),
        )
        .reset_index()
    )
    # Pandas agg cannot conditionally use a different column cleanly for missing Kreditor.
    if "Kreditor" not in df.columns:
        doc_summary["vendor_non_null"] = 0

    fraud_rows = int(df["Label"].astype(str).str.lower().ne("nonfraud").sum())
    status = "GO_WITH_CAVEAT" if not missing and fraud_rows > 0 else "NO_GO"
    summary = {
        "created_at": _now_iso(),
        "status": status,
        "rows": int(len(df)),
        "documents": int(df["Belegnummer"].nunique()) if "Belegnummer" in df.columns else 0,
        "missing_required_columns": missing,
        "label_counts": {str(k): int(v) for k, v in label_counts.items()},
        "fraud_rows": fraud_rows,
        "run_ids": sorted(df["run_id"].unique().tolist()),
        "canonical_mapping": {
            "document_id": "Belegnummer",
            "line_id": "Position",
            "gl_account": "Sachkonto",
            "amount": "Betrag Hauswaehr",
            "debit_credit_indicator": "Soll/Haben-Kennz_",
            "event_time": "Erfassungsuhrzeit",
            "vendor": "Kreditor",
            "transaction_type": "Transaktionsart",
            "label": "Label",
        },
        "feature_deny_columns": [
            "Label",
            "source_file",
            "run_id",
        ],
        "split_policy": "run_id holdout preferred; document-level split only for diagnostics",
    }
    return summary, run_label_counts.merge(doc_summary, on="run_id", how="left")


def _write_markdown(output_path: Path, summary: dict[str, Any], run_summary: pd.DataFrame) -> None:
    lines = [
        "# Tritscher Mapping Readiness",
        "",
        f"- Status: **{summary['status']}**",
        f"- Rows: {summary.get('rows', 0)}",
        f"- Documents: {summary.get('documents', 0)}",
        f"- Fraud rows: {summary.get('fraud_rows', 0)}",
        "",
        "## Canonical Mapping",
        "",
        "| Canonical | Tritscher column |",
        "|---|---|",
    ]
    for key, value in summary.get("canonical_mapping", {}).items():
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(["", "## Label Counts", "", "| Label | Rows |", "|---|---:|"])
    for key, value in summary.get("label_counts", {}).items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Run Summary", ""])
    if run_summary.empty:
        lines.append("(none)")
    else:
        lines.append(run_summary.to_markdown(index=False))
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "Use this dataset for labeled external shadow benchmarking only. "
            "Use `run_id` as the primary holdout boundary. Do not feed `Label`, "
            "`source_file`, or `run_id` as model features.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    df = _read_transactions(input_dir)
    summary, run_summary = _summarize(df)
    (output_dir / "tritscher_mapping_readiness.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    run_summary.to_csv(
        output_dir / "tritscher_run_label_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _write_markdown(output_dir / "tritscher_mapping_readiness.md", summary, run_summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
