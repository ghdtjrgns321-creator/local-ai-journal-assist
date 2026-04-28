"""Build v71 manifest for L1-01 unbalanced document truth.

L1-01 is a ledger integrity contract: any document with debit/credit imbalance
is positive, regardless of the causal anomaly label.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v70_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v71_patch_manifest"
YEARS = (2022, 2023, 2024)
TOLERANCE = 1.0


def _read_unbalanced_docs() -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "debit_amount",
        "credit_amount",
    ]
    frames = []
    for year in YEARS:
        frame = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        for col in ("debit_amount", "credit_amount"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "first"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        debit_total=("debit_amount", "sum"),
        credit_total=("credit_amount", "sum"),
        line_count=("document_id", "size"),
    )
    docs["imbalance_amount"] = docs["debit_total"] - docs["credit_total"]
    docs["abs_imbalance_amount"] = docs["imbalance_amount"].abs()
    return docs.loc[docs["abs_imbalance_amount"].gt(TOLERANCE)].copy()


def _write_json(path: Path, df: pd.DataFrame) -> None:
    path.write_text(
        json.dumps(df.where(pd.notna(df), None).to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_sidecar(df: pd.DataFrame, stem: str) -> None:
    df.to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df)
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
        _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset)


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    unbalanced = _read_unbalanced_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    cause = (
        labels.loc[labels["document_id"].astype(str).isin(unbalanced["document_id"].astype(str))]
        .groupby("document_id")["anomaly_type"]
        .apply(lambda s: "|".join(sorted(set(s.dropna().astype(str)))))
        .rename("causal_anomaly_types")
        .reset_index()
    )
    truth = unbalanced.merge(cause, on="document_id", how="left")
    truth["rule_id"] = "L1-01"
    truth["truth_layer"] = "field_contract_truth"
    truth["expected_l101_flag"] = True
    truth["truth_basis"] = "abs(sum(debit_amount)-sum(credit_amount)) > 1"
    truth["causal_anomaly_types"] = truth["causal_anomaly_types"].fillna("")
    _write_sidecar(truth, "l101_unbalanced_truth")

    summary = {
        "candidate_version": "v71",
        "source_baseline": "data/journal/primary/datasynth_v70_candidate",
        "patch_scope": "L1-01 field truth uses actual debit/credit imbalance",
        "l101_truth_docs": int(len(truth)),
        "l101_truth_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "causal_label_counts": labels.loc[
            labels["document_id"].astype(str).isin(truth["document_id"].astype(str)), "anomaly_type"
        ].value_counts().to_dict(),
        "anti_fitting_note": "L1-01 truth is derived from ledger arithmetic, not from detector output or a single causal label.",
    }
    (MANIFEST_DIR / "v71_l101_truth_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v71 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v70_candidate`\n\n"
        "Scope: make L1-01 truth equal to actual debit/credit imbalance.\n\n"
        "- Preserve causal labels such as DecimalError, RoundingError, CurrencyError, and ReversedAmount.\n"
        "- Add `labels/l101_unbalanced_truth.csv` as the evaluation truth for L1-01.\n"
        "- Do not force every unbalanced document to have `UnbalancedEntry` as the causal label.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
