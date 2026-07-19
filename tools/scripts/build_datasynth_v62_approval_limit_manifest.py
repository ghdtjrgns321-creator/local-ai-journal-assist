"""Build v62 manifest for L1-04 ExceededApprovalLimit truth repair."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v61_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v62_patch_manifest"
YEARS = (2022, 2023, 2024)


def _load_limits() -> dict[str, float]:
    employees = json.loads((SOURCE_DIR / "master_data" / "employees.json").read_text(encoding="utf-8"))
    return {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit"))
        for row in employees
        if str(row.get("user_id", "")).strip() and row.get("approval_limit") not in (None, "")
    }


def _load_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "debit_amount",
        "credit_amount",
    ]
    for year in YEARS:
        df = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        for col in ("debit_amount", "credit_amount"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        frames.append(df)
    rows = pd.concat(frames, ignore_index=True)
    return rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "min"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        user_persona=("user_persona", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )


def _load_labels() -> pd.DataFrame:
    return pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    docs = _load_docs()
    labels = _load_labels()
    limits = _load_limits()
    docs["document_amount"] = docs[["debit_amount", "credit_amount"]].max(axis=1)
    docs["approval_limit"] = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
    actual = docs.loc[docs["approval_limit"].notna() & docs["document_amount"].gt(docs["approval_limit"])].copy()

    existing_eal = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    label_map = labels.groupby("document_id")["anomaly_type"].apply(lambda s: sorted(set(map(str, s)))).to_dict()
    missing = actual.loc[~actual["document_id"].astype(str).isin(existing_eal)].copy()
    missing["existing_labels"] = missing["document_id"].map(lambda doc_id: "|".join(label_map.get(doc_id, [])))
    missing["excess_amount"] = missing["document_amount"] - missing["approval_limit"]
    missing["excess_ratio"] = missing["document_amount"] / missing["approval_limit"]
    missing["metadata_json"] = missing.apply(
        lambda row: json.dumps(
            {
                "v62_patch": "approval_limit_truth_repair",
                "rule_id": "L1-04",
                "truth_layer": "field_contract_confirmed_issue",
                "approved_by": row["approved_by"],
                "approval_limit": int(float(row["approval_limit"])),
                "document_amount": int(float(row["document_amount"])),
                "excess_amount": int(float(row["excess_amount"])),
                "excess_ratio": round(float(row["excess_ratio"]), 6),
                "existing_labels": str(row["existing_labels"]).split("|") if row["existing_labels"] else [],
                "anti_fitting_note": "L1-04 truth is derived from approved_by approval_limit, not detector output.",
            },
            ensure_ascii=False,
        ),
        axis=1,
    )
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "document_amount",
        "approval_limit",
        "excess_amount",
        "excess_ratio",
        "existing_labels",
        "metadata_json",
    ]
    missing[cols].to_csv(MANIFEST_DIR / "approval_limit_label_manifest.csv", index=False)
    actual_cols = cols[:-2] + ["existing_labels"]
    actual["existing_labels"] = actual["document_id"].map(lambda doc_id: "|".join(label_map.get(doc_id, [])))
    actual["excess_amount"] = actual["document_amount"] - actual["approval_limit"]
    actual["excess_ratio"] = actual["document_amount"] / actual["approval_limit"]
    actual[actual_cols].to_csv(MANIFEST_DIR / "approval_limit_exceeded_population.csv", index=False)
    for year in YEARS:
        actual.loc[actual["fiscal_year"].astype(str).eq(str(year)), actual_cols].to_csv(
            MANIFEST_DIR / f"approval_limit_exceeded_population_{year}.csv",
            index=False,
        )
    summary = {
        "candidate_version": "v62",
        "source_baseline": "data/journal/primary/datasynth_v61_candidate",
        "patch_scope": "L1-04 ExceededApprovalLimit missing label repair",
        "actual_exceeded_docs": int(len(actual)),
        "existing_exceeded_labels": int(len(existing_eal)),
        "missing_exceeded_labels": int(len(missing)),
        "missing_by_year": {str(k): int(v) for k, v in missing["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "missing_existing_label_types": missing["existing_labels"].value_counts().to_dict(),
        "anti_fitting_note": "The manifest adds labels only where journal amount exceeds the resolved approver limit.",
    }
    (MANIFEST_DIR / "approval_limit_manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v62 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v61_candidate`\n\n"
        "Scope: add missing L1-04 `ExceededApprovalLimit` labels where the journal already exceeds "
        "`approved_by.approval_limit` but the document only had L4-03-style amount labels.\n\n"
        "- Do not mutate journal fields.\n"
        "- Preserve `UnusuallyHighAmount` / `StatisticalOutlier` labels.\n"
        "- Add `ExceededApprovalLimit` as an additional label for overlapping control failure truth.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
