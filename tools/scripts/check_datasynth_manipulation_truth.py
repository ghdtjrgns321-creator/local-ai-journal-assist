"""Validate DataSynth manipulation-only truth contract."""

# ruff: noqa: E501,I001

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


YEARS = (2022, 2023, 2024)
REQUIRED_LABEL_FILES = [
    "labels/manipulated_entry_truth.csv",
    "labels/anomaly_labels.csv",
    "labels/manipulated_entry_scenario_summary.csv",
]


def count_csv(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, default=Path("tests/datasynth_quality_gate3/results/manipulation_v2_truth_check.json"))
    args = parser.parse_args()

    dataset = args.dataset
    failures: list[str] = []
    missing = [rel for rel in REQUIRED_LABEL_FILES if not (dataset / rel).exists()]
    if missing:
        failures.append(f"missing required label files: {missing}")

    combined_rows = count_csv(dataset / "journal_entries.csv")
    year_rows = {year: count_csv(dataset / f"journal_entries_{year}.csv") for year in YEARS}
    if combined_rows != sum(year_rows.values()):
        failures.append(f"year split row sum mismatch: combined={combined_rows}, years={sum(year_rows.values())}")

    truth = pd.read_csv(dataset / "labels" / "manipulated_entry_truth.csv", dtype=str, low_memory=False)
    labels = pd.read_csv(dataset / "labels" / "anomaly_labels.csv", dtype=str, low_memory=False)
    journal = pd.read_csv(
        dataset / "journal_entries.csv",
        dtype=str,
        usecols=lambda col: col
        in {
            "document_id",
            "fiscal_year",
            "mutation_type",
            "mutation_reason",
            "mutation_base_event_type",
            "mutation_mutated_field",
            "mutation_original_value",
            "mutation_mutated_value",
            "is_fraud",
            "fraud_type",
            "is_anomaly",
            "anomaly_type",
            "debit_amount",
            "credit_amount",
        },
        low_memory=False,
    )
    truth_docs = set(truth["document_id"].astype(str))
    label_docs = set(labels["document_id"].astype(str))
    journal_docs = set(journal["document_id"].astype(str))
    if truth_docs != label_docs:
        failures.append(f"truth/labels mismatch: missing={len(truth_docs-label_docs)}, extra={len(label_docs-truth_docs)}")
    if not truth_docs <= journal_docs:
        failures.append(f"truth docs missing from journal: {len(truth_docs-journal_docs)}")

    forbidden_label_files = sorted(
        str(path.relative_to(dataset))
        for path in (dataset / "labels").glob("*")
        if path.name.startswith("rule_truth") or path.name.startswith("contract_") or "sidecar" in path.name
    )
    if forbidden_label_files:
        failures.append(f"contract label files present: {forbidden_label_files[:10]}")

    leakage_cols = [col for col in ["is_fraud", "fraud_type", "is_anomaly", "anomaly_type"] if col in journal.columns]
    if leakage_cols:
        failures.append(f"direct leakage columns present: {leakage_cols}")

    truth_rows = journal.loc[journal["document_id"].astype(str).isin(truth_docs)]
    provenance_cols = [
        "mutation_type",
        "mutation_reason",
        "mutation_base_event_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
    ]
    missing_provenance = {
        col: int(truth_rows[col].fillna("").astype(str).str.strip().eq("").sum())
        for col in provenance_cols
        if col in truth_rows.columns
    }
    bad_provenance = {col: count for col, count in missing_provenance.items() if count > 0}
    if bad_provenance:
        failures.append(f"truth rows missing mutation provenance: {bad_provenance}")

    debit = pd.to_numeric(journal["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(journal["credit_amount"], errors="coerce").fillna(0.0)
    balance = (
        pd.DataFrame({"document_id": journal["document_id"], "debit": debit, "credit": credit})
        .groupby("document_id", as_index=False)
        .agg(debit=("debit", "sum"), credit=("credit", "sum"))
    )
    unbalanced_truth_docs = set(
        balance.loc[
            balance["document_id"].astype(str).isin(truth_docs)
            & balance["debit"].sub(balance["credit"]).abs().gt(1.0),
            "document_id",
        ].astype(str)
    )
    if unbalanced_truth_docs:
        failures.append(f"unbalanced truth docs: {len(unbalanced_truth_docs)}")

    summary = {
        "dataset": str(dataset),
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "journal_rows": combined_rows,
        "year_rows": year_rows,
        "truth_docs": len(truth_docs),
        "label_docs": len(label_docs),
        "scenario_counts": {str(k): int(v) for k, v in truth["manipulation_scenario"].value_counts().sort_index().to_dict().items()},
        "truth_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "forbidden_label_files": forbidden_label_files,
        "leakage_columns_present": leakage_cols,
        "missing_provenance_counts": missing_provenance,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
