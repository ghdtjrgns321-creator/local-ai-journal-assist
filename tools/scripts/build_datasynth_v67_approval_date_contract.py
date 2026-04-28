"""Build v67 manifest for L1-09 ApprovalDateMissing contract cleanup.

v67 is cumulative on top of v66. It preserves confirmed L1-09 labels and fills
approval_date on unlabeled documents where an approver is present.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v66_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v67_patch_manifest"
YEARS = (2022, 2023, 2024)


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _approval_date_for(row: pd.Series) -> str:
    posting = pd.to_datetime(row["posting_date"], errors="coerce")
    if pd.isna(posting):
        posting = pd.to_datetime(row["document_date"], errors="coerce")
    if pd.isna(posting):
        posting = pd.Timestamp(f"{int(row['fiscal_year'])}-01-01")

    source = str(row.get("source", "")).strip().lower()
    seed = _stable_int(str(row["document_id"]))
    if source == "automated":
        offset_days = 0 if seed % 100 < 92 else 1
    elif source == "recurring":
        offset_days = seed % 3
    else:
        offset_days = seed % 2
    return (posting.normalize() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _read_doc_level() -> pd.DataFrame:
    cols = [
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
        "approval_date",
        "user_persona",
    ]
    frames = []
    for year in YEARS:
        frame = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    return rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
        document_type=("document_type", "first"),
        document_number=("document_number", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
    )


def _write_json(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


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

    docs = _read_doc_level()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].dropna().astype(str))

    has_approver = docs["approved_by"].fillna("").astype(str).str.strip().ne("")
    missing_date = docs["approval_date"].fillna("").astype(str).str.strip().eq("")
    actual = docs.loc[has_approver & missing_date].copy()
    patch_docs = actual.loc[~actual["document_id"].astype(str).isin(label_docs)].copy()
    patch_docs["old_approval_date"] = patch_docs["approval_date"]
    patch_docs["new_approval_date"] = patch_docs.apply(_approval_date_for, axis=1)
    patch_docs["patch_action"] = "fill_unlabeled_approval_date"
    patch_docs["truth_layer"] = "normal_control"
    patch_docs["normal_reason"] = patch_docs["source"].fillna("").astype(str).str.lower().map(
        {
            "automated": "automated_approved_timestamp_present",
            "recurring": "recurring_preapproved_timestamp_present",
            "manual": "manual_non_anomalous_approval_timestamp_present",
            "adjustment": "adjustment_non_anomalous_approval_timestamp_present",
        }
    ).fillna("approved_timestamp_present")
    patch_docs[
        [
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
            "old_approval_date",
            "new_approval_date",
            "truth_layer",
            "normal_reason",
            "patch_action",
        ]
    ].to_csv(MANIFEST_DIR / "approval_date_fill_manifest.csv", index=False)

    _write_sidecar(
        patch_docs[
            [
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
                "new_approval_date",
                "truth_layer",
                "normal_reason",
            ]
        ].rename(columns={"new_approval_date": "approval_date"}),
        "approval_date_present_normal_controls",
    )

    summary = {
        "candidate_version": "v67",
        "source_baseline": "data/journal/primary/datasynth_v66_candidate",
        "patch_scope": "L1-09 ApprovalDateMissing contract cleanup",
        "actual_missing_approval_date_docs": int(len(actual)),
        "approval_date_missing_labels": int(len(label_docs)),
        "filled_unlabeled_docs": int(len(patch_docs)),
        "filled_by_year": {str(k): int(v) for k, v in patch_docs["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "filled_by_source": {str(k): int(v) for k, v in patch_docs["source"].value_counts().to_dict().items()},
        "anti_fitting_note": (
            "v67 does not use detector results. It enforces the field contract that only labeled "
            "ApprovalDateMissing documents retain approved_by without approval_date."
        ),
    }
    (MANIFEST_DIR / "approval_date_v67_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v67 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v66_candidate`\n\n"
        "Scope: repair L1-09 `ApprovalDateMissing` field contract without dropping v65/v66 patches.\n\n"
        "- Preserve existing `ApprovalDateMissing` label documents with missing `approval_date`.\n"
        "- Fill `approval_date` for unlabeled documents where `approved_by` is present.\n"
        "- Record filled documents as normal controls, not confirmed anomalies.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
