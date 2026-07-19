"""Build v68 manifest for L1 distribution realism.

v68 is cumulative on top of v67. It reduces excessive L1-05 confirmed
SelfApproval documents by changing non-confirmed self approvals to a different
valid approver, and adds a small 2023 L1-07 coverage fixture.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v67_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v68_patch_manifest"
YEARS = (2022, 2023, 2024)
SELF_APPROVAL_TARGETS = {2022: 73, 2023: 58, 2024: 86}
SKIPPED_APPROVAL_2023_TARGET = 2
APPROVAL_THRESHOLDS = (10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000)
CONFIRMED_SKIPPED_SOURCES = {"manual", "adjustment"}


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _approval_level(amount: pd.Series) -> pd.Series:
    level = pd.Series(0, index=amount.index, dtype="int64")
    for idx, threshold in enumerate(APPROVAL_THRESHOLDS, 1):
        level = level.where(amount < threshold, idx)
    return level


def _approval_date_for(row: pd.Series) -> str:
    posting = pd.to_datetime(row["posting_date"], errors="coerce")
    if pd.isna(posting):
        posting = pd.Timestamp(f"{int(row['fiscal_year'])}-01-01")
    offset = _stable_int(str(row["document_id"])) % 3
    return (posting.normalize() + timedelta(days=offset)).strftime("%Y-%m-%d")


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
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
        row_count=("document_id", "size"),
    )
    docs["document_amount"] = docs["debit_amount"]
    docs["approval_level"] = _approval_level(docs["document_amount"])
    return docs


def _load_high_limit_approver() -> str:
    employees = json.loads((SOURCE_DIR / "master_data" / "employees.json").read_text(encoding="utf-8"))
    candidates = [
        row
        for row in employees
        if str(row.get("user_id", "")).strip()
        and bool(row.get("can_approve_je", True))
        and float(row.get("approval_limit") or 0) >= 50_000_000_000
    ]
    if not candidates:
        candidates = [row for row in employees if str(row.get("user_id", "")).strip()]
    candidates = sorted(candidates, key=lambda row: str(row.get("user_id")))
    return str(candidates[0]["user_id"])


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


def _select_selfapproval_keep(docs: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    non_self_labels = labels.loc[~labels["anomaly_type"].eq("SelfApproval")]
    protected_docs = set(non_self_labels["document_id"].dropna().astype(str))
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    source = docs["source"].fillna("").astype(str).str.lower()
    actual = docs.loc[
        created.ne("")
        & created.eq(approved)
        & ~source.eq("automated")
    ].copy()
    actual["protected_by_other_label"] = actual["document_id"].astype(str).isin(protected_docs)
    actual["priority"] = 0
    actual.loc[actual["source"].astype(str).str.lower().isin(["manual", "adjustment"]), "priority"] += 4
    actual.loc[actual["approval_level"].ge(1), "priority"] += 3
    actual.loc[actual["business_process"].isin(["R2R", "A2R", "TRE"]), "priority"] += 2
    actual.loc[actual["protected_by_other_label"], "priority"] += 5
    actual["_sort"] = actual["document_id"].map(_stable_int)

    keep_parts = []
    for year, target in SELF_APPROVAL_TARGETS.items():
        year_pool = actual.loc[actual["fiscal_year"].astype(str).eq(str(year))].sort_values(
            ["protected_by_other_label", "priority", "_sort"],
            ascending=[False, False, True],
        )
        keep_parts.append(year_pool.head(target))
    keep = pd.concat(keep_parts, ignore_index=True)
    keep_docs = set(keep["document_id"].astype(str))
    repair = actual.loc[~actual["document_id"].astype(str).isin(keep_docs)].copy()
    return keep, repair


def _select_skipped_2023(docs: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    labeled_docs = set(labels["document_id"].dropna().astype(str))
    source = docs["source"].fillna("").astype(str).str.lower()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    candidates = docs.loc[
        docs["fiscal_year"].astype(str).eq("2023")
        & source.isin(CONFIRMED_SKIPPED_SOURCES)
        & approved.ne("")
        & docs["approval_level"].ge(1)
        & ~docs["document_id"].astype(str).isin(labeled_docs)
    ].copy()
    candidates["priority"] = 0
    candidates.loc[candidates["business_process"].isin(["P2P", "O2C", "TRE"]), "priority"] += 2
    candidates.loc[candidates["row_count"].between(2, 6), "priority"] += 1
    candidates["_sort"] = candidates["document_id"].map(_stable_int)
    return candidates.sort_values(["priority", "_sort"], ascending=[False, True]).head(SKIPPED_APPROVAL_2023_TARGET)


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    docs = _read_docs()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    replacement_approver = _load_high_limit_approver()

    self_keep, self_repair = _select_selfapproval_keep(docs, labels)
    self_repair["old_approved_by"] = self_repair["approved_by"]
    self_repair["new_approved_by"] = self_repair["created_by"].apply(
        lambda user: replacement_approver if str(user) != replacement_approver else "SSCOTT018"
    )
    self_repair["old_approval_date"] = self_repair["approval_date"]
    self_repair["new_approval_date"] = self_repair.apply(_approval_date_for, axis=1)
    self_repair["patch_action"] = "replace_nonconfirmed_self_approver"
    self_repair["normal_reason"] = "self_approval_review_reclassified_to_independent_approval"

    skipped_add = _select_skipped_2023(docs, labels)
    skipped_add["old_approved_by"] = skipped_add["approved_by"]
    skipped_add["new_approved_by"] = ""
    skipped_add["old_approval_date"] = skipped_add["approval_date"]
    skipped_add["new_approval_date"] = ""
    skipped_add["patch_action"] = "inject_2023_skipped_approval_coverage"

    self_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "old_approved_by",
        "new_approved_by",
        "old_approval_date",
        "new_approval_date",
        "document_amount",
        "approval_level",
        "patch_action",
        "normal_reason",
    ]
    self_repair[self_cols].to_csv(MANIFEST_DIR / "self_approval_repair_manifest.csv", index=False)

    self_keep["truth_layer"] = "confirmed_anomaly"
    self_keep[
        [
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
            "truth_layer",
        ]
    ].to_csv(MANIFEST_DIR / "self_approval_confirmed_anomalies.csv", index=False)
    _write_sidecar(self_keep.assign(truth_layer="confirmed_anomaly"), "self_approval_review_population")

    control_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_type",
        "document_number",
        "source",
        "business_process",
        "created_by",
        "old_approved_by",
        "new_approved_by",
        "new_approval_date",
        "document_amount",
        "approval_level",
        "normal_reason",
    ]
    _write_sidecar(self_repair[control_cols], "self_approval_normal_controls")

    skipped_add[
        [
            "document_id",
            "fiscal_year",
            "company_code",
            "posting_date",
            "document_type",
            "document_number",
            "source",
            "business_process",
            "created_by",
            "old_approved_by",
            "new_approved_by",
            "old_approval_date",
            "new_approval_date",
            "document_amount",
            "approval_level",
            "patch_action",
        ]
    ].to_csv(MANIFEST_DIR / "skipped_approval_2023_add_manifest.csv", index=False)

    summary = {
        "candidate_version": "v68",
        "source_baseline": "data/journal/primary/datasynth_v67_candidate",
        "patch_scope": "L1-05 distribution realism and L1-07 2023 coverage",
        "self_approval_source_docs": int(len(self_keep) + len(self_repair)),
        "self_approval_confirmed_docs": int(len(self_keep)),
        "self_approval_repaired_docs": int(len(self_repair)),
        "self_approval_confirmed_by_year": {
            str(k): int(v) for k, v in self_keep["fiscal_year"].value_counts().sort_index().to_dict().items()
        },
        "skipped_approval_2023_added_docs": int(len(skipped_add)),
        "skipped_approval_2023_added_ids": skipped_add["document_id"].astype(str).tolist(),
        "anti_fitting_note": (
            "v68 changes source fields according to business contracts. It does not use detector TP/FP output as a target."
        ),
    }
    (MANIFEST_DIR / "v68_l1_distribution_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v68 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v67_candidate`\n\n"
        "Scope: reduce excessive L1-05 self-approval confirmed truth and add small L1-07 2023 coverage.\n\n"
        "- Non-confirmed self approvals are changed to independent approvals with valid approval dates.\n"
        "- Confirmed self approvals remain non-uniform by year.\n"
        "- 2023 receives a small manual/adjustment skipped-approval coverage fixture.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
