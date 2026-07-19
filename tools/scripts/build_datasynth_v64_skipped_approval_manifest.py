"""Build v64 manifest for L1-07 SkippedApproval truth repair."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v63_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v64_patch_manifest"
YEARS = (2022, 2023, 2024)
THRESHOLDS = (10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000)
SYSTEM_SOURCES = {"automated", "batch", "interface", "system"}


def _read_docs() -> pd.DataFrame:
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
        "approval_date",
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
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )


def _approval_level(amount: pd.Series) -> pd.Series:
    level = pd.Series(0, index=amount.index, dtype="int64")
    for idx, threshold in enumerate(THRESHOLDS, 1):
        level = level.where(amount < threshold, idx)
    return level


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
    label_docs = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].astype(str))

    docs["document_amount"] = docs[["debit_amount", "credit_amount"]].max(axis=1)
    docs["approval_level"] = _approval_level(docs["document_amount"])
    docs["source_normalized"] = docs["source"].fillna("").astype(str).str.strip().str.lower()
    docs["missing_approved_by"] = docs["approved_by"].fillna("").astype(str).str.strip().eq("")
    docs["system_source"] = docs["source_normalized"].isin(SYSTEM_SOURCES)
    docs["expected_l107_flag"] = docs["missing_approved_by"] & ~docs["system_source"] & docs["approval_level"].ge(1)
    docs["truth_layer"] = docs["expected_l107_flag"].map({True: "confirmed_anomaly", False: "normal_or_allowed_missing_approval"})

    confirmed = docs.loc[docs["expected_l107_flag"]].copy()
    missing = confirmed.loc[~confirmed["document_id"].astype(str).isin(label_docs)].copy()
    normal_controls = docs.loc[docs["missing_approved_by"] & ~docs["expected_l107_flag"]].copy()
    normal_controls["normal_reason"] = normal_controls.apply(
        lambda row: "system_source_missing_approver" if bool(row["system_source"]) else "below_approval_threshold",
        axis=1,
    )

    missing["metadata_json"] = missing.apply(
        lambda row: json.dumps(
            {
                "v64_patch": "skipped_approval_truth_repair",
                "rule_id": "L1-07",
                "truth_layer": "confirmed_anomaly",
                "document_amount": int(float(row["document_amount"])),
                "approval_level": int(row["approval_level"]),
                "source": row["source"],
                "business_process": row["business_process"],
                "missing_approved_by": True,
                "system_source": False,
                "anti_fitting_note": "L1-07 truth is derived from missing approver plus approval-required amount and source contract.",
            },
            ensure_ascii=False,
        ),
        axis=1,
    )
    label_cols = [
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
        "approval_date",
        "user_persona",
        "document_amount",
        "approval_level",
        "metadata_json",
    ]
    missing[label_cols].to_csv(MANIFEST_DIR / "skipped_approval_label_manifest.csv", index=False)

    sidecar_cols = [
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
        "approval_date",
        "user_persona",
        "document_amount",
        "approval_level",
        "expected_l107_flag",
        "truth_layer",
    ]
    _write_sidecar(confirmed[sidecar_cols], "skipped_approval_confirmed_anomalies")
    control_cols = sidecar_cols + ["normal_reason"]
    _write_sidecar(normal_controls[control_cols], "skipped_approval_normal_controls")

    summary = {
        "candidate_version": "v64",
        "source_baseline": "data/journal/primary/datasynth_v63_candidate",
        "patch_scope": "L1-07 SkippedApproval missing label repair",
        "blank_approved_by_docs": int(docs["missing_approved_by"].sum()),
        "confirmed_l107_docs": int(len(confirmed)),
        "existing_skipped_labels": int(len(label_docs)),
        "missing_skipped_labels": int(len(missing)),
        "confirmed_by_year": {str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "missing_by_year": {str(k): int(v) for k, v in missing["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "normal_control_docs": int(len(normal_controls)),
        "normal_control_reasons": normal_controls["normal_reason"].value_counts().to_dict(),
        "anti_fitting_note": "No 2023 positives are added because v63 has no 2023 document satisfying the L1-07 field contract.",
    }
    (MANIFEST_DIR / "skipped_approval_manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v64 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v63_candidate`\n\n"
        "Scope: repair L1-07 `SkippedApproval` labels where approval is required, source is non-system, and `approved_by` is missing.\n\n"
        "- Do not label every missing approver document.\n"
        "- Preserve system/recurring missing approver records as normal controls.\n"
        "- Do not force a 2023 positive because no 2023 document meets the current field contract.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
