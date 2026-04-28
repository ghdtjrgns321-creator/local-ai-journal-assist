"""Build v66 manifest for L1-07 SkippedApproval contract cleanup.

v66 is cumulative on top of v65. It keeps the v65 WrongPeriod repair and only
reclassifies L1-07 confirmed truth to the immediate-violation contract:

- approved_by is missing,
- source is manual or adjustment,
- debit-side document amount requires approval.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v65_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v66_patch_manifest"
YEARS = (2022, 2023, 2024)
THRESHOLDS = (10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000)
CONFIRMED_SOURCES = {"manual", "adjustment"}
SYSTEM_SOURCES = {"automated", "batch", "interface", "system"}


def _read_docs() -> pd.DataFrame:
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
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        frame = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=cols, low_memory=False)
        for col in ("debit_amount", "credit_amount"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        frames.append(frame)
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
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sidecar(df: pd.DataFrame, stem: str) -> None:
    df.to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df)
    for year in YEARS:
        subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
        _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset)


def _normal_reason(row: pd.Series) -> str:
    if bool(row["system_source"]):
        return "system_source_missing_approver"
    if str(row["source_normalized"]) not in CONFIRMED_SOURCES:
        return "non_immediate_source_review_only"
    if int(row["approval_level"]) < 1:
        return "below_debit_approval_threshold"
    return "not_l107_immediate_contract"


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    docs = _read_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    skipped_labels = labels.loc[labels["anomaly_type"].eq("SkippedApproval")].copy()
    label_docs = set(skipped_labels["document_id"].dropna().astype(str))

    docs["document_amount"] = docs["debit_amount"]
    docs["credit_side_amount"] = docs["credit_amount"]
    docs["approval_level"] = _approval_level(docs["document_amount"])
    docs["source_normalized"] = docs["source"].fillna("").astype(str).str.strip().str.lower()
    docs["missing_approved_by"] = docs["approved_by"].fillna("").astype(str).str.strip().eq("")
    docs["system_source"] = docs["source_normalized"].isin(SYSTEM_SOURCES)
    docs["expected_l107_flag"] = (
        docs["missing_approved_by"]
        & docs["source_normalized"].isin(CONFIRMED_SOURCES)
        & docs["approval_level"].ge(1)
    )
    docs["truth_layer"] = docs["expected_l107_flag"].map({True: "confirmed_anomaly", False: "normal_or_review_control"})

    confirmed = docs.loc[docs["expected_l107_flag"]].copy()
    actual_docs = set(confirmed["document_id"].astype(str))
    extra_label_docs = sorted(label_docs - actual_docs)
    missing_label_docs = sorted(actual_docs - label_docs)

    remove_labels = skipped_labels.loc[skipped_labels["document_id"].astype(str).isin(extra_label_docs)].copy()
    remove_labels = remove_labels.merge(
        docs[
            [
                "document_id",
                "fiscal_year",
                "document_number",
                "source",
                "business_process",
                "document_amount",
                "credit_side_amount",
                "approval_level",
            ]
        ],
        on="document_id",
        how="left",
        suffixes=("", "_actual"),
    )
    remove_labels["patch_action"] = "remove_skipped_approval_label"
    remove_labels["reason"] = remove_labels.apply(
        lambda row: (
            "L1-07 confirmed truth requires manual/adjustment source and debit-side approval level; "
            f"actual source={row.get('source_actual') or row.get('source')}, "
            f"debit_amount={row.get('document_amount')}, credit_amount={row.get('credit_side_amount')}, "
            f"approval_level={row.get('approval_level')}"
        ),
        axis=1,
    )
    remove_labels.to_csv(MANIFEST_DIR / "skipped_approval_remove_label_manifest.csv", index=False)

    missing = confirmed.loc[confirmed["document_id"].astype(str).isin(missing_label_docs)].copy()
    missing.to_csv(MANIFEST_DIR / "skipped_approval_add_label_manifest.csv", index=False)

    normal_controls = docs.loc[docs["missing_approved_by"] & ~docs["expected_l107_flag"]].copy()
    normal_controls["normal_reason"] = normal_controls.apply(_normal_reason, axis=1)

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
        "credit_side_amount",
        "approval_level",
        "expected_l107_flag",
        "truth_layer",
    ]
    _write_sidecar(confirmed[sidecar_cols], "skipped_approval_confirmed_anomalies")
    _write_sidecar(normal_controls[sidecar_cols + ["normal_reason"]], "skipped_approval_normal_controls")

    summary = {
        "candidate_version": "v66",
        "source_baseline": "data/journal/primary/datasynth_v65_candidate",
        "patch_scope": "L1-07 SkippedApproval contract cleanup",
        "source_label_docs": int(len(label_docs)),
        "confirmed_l107_docs": int(len(confirmed)),
        "remove_label_docs": int(len(extra_label_docs)),
        "add_label_docs": int(len(missing_label_docs)),
        "confirmed_by_year": {str(k): int(v) for k, v in confirmed["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "removed_documents": extra_label_docs,
        "normal_control_docs": int(len(normal_controls)),
        "normal_control_reasons": normal_controls["normal_reason"].value_counts().to_dict(),
        "anti_fitting_note": (
            "v66 uses the documented immediate L1-07 contract, not detector results: missing approver, "
            "manual/adjustment source, and debit-side approval-required amount."
        ),
    }
    (MANIFEST_DIR / "skipped_approval_v66_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v66 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v65_candidate`\n\n"
        "Scope: clean up L1-07 `SkippedApproval` confirmed truth without dropping v65 L1-08 `WrongPeriod` repair.\n\n"
        "- Confirmed L1-07 uses debit-side document amount, not `max(debit, credit)`.\n"
        "- Confirmed L1-07 is limited to `manual` and `adjustment` sources.\n"
        "- `recurring` missing-approver cases remain controls/review population, not confirmed truth.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
