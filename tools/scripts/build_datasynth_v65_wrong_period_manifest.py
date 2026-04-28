"""Build v65 manifest for L1-08 WrongPeriod truth repair."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v64_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v65_patch_manifest"
YEARS = (2022, 2023, 2024)


def _read_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cols = [
        "document_id",
        "fiscal_year",
        "fiscal_period",
        "company_code",
        "posting_date",
        "document_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
    ]
    for year in YEARS:
        df = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        frames.append(df)
    rows = pd.concat(frames, ignore_index=True)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        fiscal_period=("fiscal_period", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "min"),
        document_date=("document_date", "first"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        user_persona=("user_persona", "first"),
    )
    docs["fiscal_period_num"] = pd.to_numeric(docs["fiscal_period"], errors="coerce")
    docs["posting_month"] = pd.to_datetime(docs["posting_date"], errors="coerce").dt.month
    docs["document_month"] = pd.to_datetime(docs["document_date"], errors="coerce").dt.month
    return docs


def _write_json(path: Path, df: pd.DataFrame) -> None:
    path.write_text(json.dumps(df.where(pd.notna(df), None).to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")


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
    docs = _read_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    existing = set(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].astype(str))
    label_map = labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(map(str, s))))).to_dict()

    mismatch = docs.loc[
        docs["fiscal_period_num"].notna()
        & docs["posting_month"].notna()
        & docs["fiscal_period_num"].ne(docs["posting_month"])
    ].copy()
    mismatch["existing_labels"] = mismatch["document_id"].map(lambda doc_id: label_map.get(doc_id, ""))
    mismatch["period_basis_observed"] = mismatch.apply(
        lambda row: "document_date_month"
        if pd.notna(row["document_month"]) and float(row["fiscal_period_num"]) == float(row["document_month"])
        else "other_or_invalid_period",
        axis=1,
    )
    missing = mismatch.loc[~mismatch["document_id"].astype(str).isin(existing)].copy()
    missing["metadata_json"] = missing.apply(
        lambda row: json.dumps(
            {
                "v65_patch": "wrong_period_truth_repair",
                "rule_id": "L1-08",
                "truth_layer": "field_contract_confirmed_issue",
                "fiscal_period": int(float(row["fiscal_period_num"])),
                "posting_month": int(float(row["posting_month"])),
                "document_month": None if pd.isna(row["document_month"]) else int(float(row["document_month"])),
                "period_basis_observed": row["period_basis_observed"],
                "existing_labels": str(row["existing_labels"]).split("|") if row["existing_labels"] else [],
                "anti_fitting_note": "L1-08 truth is derived from fiscal_period versus posting_date under the calendar-year K4 contract.",
            },
            ensure_ascii=False,
        ),
        axis=1,
    )

    manifest_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "approved_by",
        "user_persona",
        "fiscal_period",
        "fiscal_period_num",
        "posting_month",
        "document_month",
        "period_basis_observed",
        "existing_labels",
        "metadata_json",
    ]
    missing[manifest_cols].to_csv(MANIFEST_DIR / "wrong_period_label_manifest.csv", index=False)
    sidecar_cols = [col for col in manifest_cols if col != "metadata_json"]
    mismatch["expected_l108_flag"] = True
    sidecar_cols.append("expected_l108_flag")
    _write_sidecar(mismatch[sidecar_cols], "wrong_period_confirmed_anomalies")

    normal = docs.loc[
        docs["fiscal_period_num"].notna()
        & docs["posting_month"].notna()
        & docs["fiscal_period_num"].eq(docs["posting_month"])
    ].copy()
    normal["expected_l108_flag"] = False
    normal["normal_reason"] = "posting_month_matches_fiscal_period"
    normal_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "fiscal_period",
        "fiscal_period_num",
        "posting_month",
        "document_month",
        "expected_l108_flag",
        "normal_reason",
    ]
    # Keep this sidecar compact but still year-split for contract evaluation.
    normal_sample = normal.sort_values(["fiscal_year", "posting_date", "document_id"]).groupby("fiscal_year").head(250)
    _write_sidecar(normal_sample[normal_cols], "wrong_period_normal_controls")

    summary = {
        "candidate_version": "v65",
        "source_baseline": "data/journal/primary/datasynth_v64_candidate",
        "patch_scope": "L1-08 WrongPeriod missing label repair",
        "actual_wrong_period_docs": int(len(mismatch)),
        "existing_wrong_period_labels": int(len(existing)),
        "missing_wrong_period_labels": int(len(missing)),
        "actual_by_year": {str(k): int(v) for k, v in mismatch["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "missing_by_year": {str(k): int(v) for k, v in missing["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "period_basis_observed": mismatch["period_basis_observed"].value_counts().to_dict(),
        "missing_existing_label_types": missing["existing_labels"].value_counts().head(20).to_dict(),
        "anti_fitting_note": "No journal dates or periods are changed. The patch labels all records violating the posting-date fiscal-period contract.",
    }
    (MANIFEST_DIR / "wrong_period_manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v65 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v64_candidate`\n\n"
        "Scope: repair L1-08 `WrongPeriod` labels where `fiscal_period` does not match `posting_date.month`.\n\n"
        "- Do not mutate journal `fiscal_period` or dates.\n"
        "- Preserve overlapping labels such as `BatchAnomaly`, `DuplicatePayment`, and `SelfApproval`.\n"
        "- Add a confirmed sidecar for all wrong-period documents.\n"
        "- Add a compact normal-control sidecar for matching-period documents.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
