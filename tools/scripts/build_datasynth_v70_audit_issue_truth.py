"""Build v70 manifest that separates L1 audit issue truth from field contracts.

v70 is cumulative on v69. The main label file becomes audit-issue truth, while
L1 field-contract truth is preserved in sidecars for implementation checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v69_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v70_patch_manifest"
YEARS = (2022, 2023, 2024)

L1_FIELD_LABELS = {
    "UnbalancedEntry",
    "MissingField",
    "InvalidAccount",
    "ExceededApprovalLimit",
    "SelfApproval",
    "SegregationOfDutiesViolation",
    "SkippedApproval",
    "WrongPeriod",
    "ApprovalDateMissing",
}


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
        "debit_amount",
        "credit_amount",
        "sod_violation",
        "sod_conflict_type",
        "fiscal_period",
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
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
        sod_violation=("sod_violation", "first"),
        sod_conflict_type=("sod_conflict_type", "first"),
        fiscal_period=("fiscal_period", "first"),
    )
    docs["document_amount"] = docs["debit_amount"]
    return docs


def _write_json(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sidecar(df: pd.DataFrame, stem: str) -> None:
    df.to_csv(MANIFEST_DIR / f"{stem}.csv", index=False)
    _write_json(MANIFEST_DIR / f"{stem}.json", df)
    if "fiscal_year" in df.columns:
        for year in YEARS:
            subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
            subset.to_csv(MANIFEST_DIR / f"{stem}_{year}.csv", index=False)
            _write_json(MANIFEST_DIR / f"{stem}_{year}.json", subset)


def _audit_keep_reason(label: pd.Series, doc: pd.Series | None) -> tuple[bool, str]:
    label_type = str(label["anomaly_type"])
    severity = int(float(label.get("severity") or 0))
    amount = 0.0 if doc is None else float(doc.get("document_amount") or 0.0)
    source = "" if doc is None else str(doc.get("source") or "").strip().lower()
    process = "" if doc is None else str(doc.get("business_process") or "").strip().upper()

    if label_type == "UnbalancedEntry":
        return amount >= 25_000_000 or severity >= 4, "material_unbalanced_entry"
    if label_type == "MissingField":
        return severity >= 4 or process in {"P2P", "O2C", "TRE"}, "key_field_missing_in_core_process"
    if label_type == "InvalidAccount":
        return True, "invalid_account_is_audit_issue"
    if label_type == "ExceededApprovalLimit":
        return source in {"manual", "adjustment"} or amount >= 1_000_000_000, "material_or_manual_approval_limit_breach"
    if label_type == "SelfApproval":
        return source in {"manual", "adjustment"} and (
            amount >= 50_000_000 or (process in {"R2R", "A2R", "TRE"} and amount >= 10_000_000)
        ), "risky_manual_self_approval"
    if label_type == "SegregationOfDutiesViolation":
        return True, "confirmed_sod_conflict"
    if label_type == "SkippedApproval":
        return amount >= 25_000_000 or process in {"TRE", "P2P", "O2C"}, "material_skipped_approval"
    if label_type == "WrongPeriod":
        return amount >= 250_000_000 or (
            process in {"O2C", "P2P"} and amount >= 50_000_000
        ), "material_or_revenue_purchase_period_error"
    if label_type == "ApprovalDateMissing":
        return source in {"manual", "adjustment"} and (amount >= 10_000_000 or process in {"TRE", "O2C"}), "manual_approval_trace_gap"
    return False, "not_l1_field_contract"


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    docs = _read_docs().set_index("document_id")
    l1_labels = labels.loc[labels["anomaly_type"].isin(L1_FIELD_LABELS)].copy()
    non_l1_labels = labels.loc[~labels["anomaly_type"].isin(L1_FIELD_LABELS)].copy()

    enriched = l1_labels.merge(
        docs.reset_index()[
            [
                "document_id",
                "fiscal_year",
                "source",
                "business_process",
                "document_amount",
                "document_number",
                "posting_date",
            ]
        ],
        on="document_id",
        how="left",
        suffixes=("", "_doc"),
    )
    keep_flags: list[bool] = []
    reasons: list[str] = []
    for _, row in enriched.iterrows():
        doc = docs.loc[row["document_id"]] if row["document_id"] in docs.index else None
        keep, reason = _audit_keep_reason(row, doc)
        keep_flags.append(keep)
        reasons.append(reason)
    enriched["audit_issue_keep"] = keep_flags
    enriched["audit_issue_reason"] = reasons
    enriched["truth_layer"] = "field_contract_truth"
    enriched["moved_from_anomaly_labels"] = ~enriched["audit_issue_keep"]

    audit_l1 = enriched.loc[enriched["audit_issue_keep"], labels.columns].copy()
    audit_labels = pd.concat([non_l1_labels, audit_l1], ignore_index=True)
    audit_labels = audit_labels.sort_values(["anomaly_date", "anomaly_id"], na_position="last").reset_index(drop=True)

    field_contract = enriched.copy()
    _write_sidecar(field_contract, "field_contract_truth")
    _write_sidecar(enriched.loc[enriched["audit_issue_keep"]].copy(), "l1_audit_issue_truth")
    _write_sidecar(enriched.loc[~enriched["audit_issue_keep"]].copy(), "l1_field_only_normal_or_review")

    audit_labels.to_csv(MANIFEST_DIR / "anomaly_labels_audit_issue.csv", index=False)
    _write_json(MANIFEST_DIR / "anomaly_labels_audit_issue.json", audit_labels)

    summary = {
        "candidate_version": "v70",
        "source_baseline": "data/journal/primary/datasynth_v69_candidate",
        "patch_scope": "Use audit issue truth as anomaly_labels; move L1 field contracts to sidecars",
        "source_total_labels": int(len(labels)),
        "source_l1_field_labels": int(len(l1_labels)),
        "kept_l1_audit_issue_labels": int(len(audit_l1)),
        "moved_l1_field_only_labels": int((~enriched["audit_issue_keep"]).sum()),
        "target_total_labels": int(len(audit_labels)),
        "kept_l1_by_type": audit_l1["anomaly_type"].value_counts().to_dict(),
        "moved_l1_by_type": enriched.loc[~enriched["audit_issue_keep"], "anomaly_type"].value_counts().to_dict(),
        "anti_fitting_note": (
            "v70 changes evaluation truth semantics: anomaly_labels is audit-issue truth, while exact L1 field contracts are sidecars."
        ),
    }
    (MANIFEST_DIR / "v70_audit_issue_truth_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(
        "# DataSynth v70 Patch Manifest\n\n"
        "Source: `data/journal/primary/datasynth_v69_candidate`\n\n"
        "Scope: make `anomaly_labels.csv` represent audit issue truth rather than raw L1 field-contract truth.\n\n"
        "- Preserve every removed L1 label in `field_contract_truth*`.\n"
        "- Keep material/risky L1 cases in `anomaly_labels.csv` as audit issues.\n"
        "- Move non-material field-only cases to `l1_field_only_normal_or_review*`.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
