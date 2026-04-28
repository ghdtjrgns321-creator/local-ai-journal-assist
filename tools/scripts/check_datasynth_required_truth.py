"""Check required DataSynth label/sidecar presence before promotion.

This gate intentionally goes beyond "label exists" checks. Several DataSynth
truth types are field-contract truths, so a candidate must fail if labels drift
away from the journal fields that define them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED_LABELS = {
    "ApprovalDateMissing": 1,
    "DuplicatePayment": 1,
    "InvalidAccount": 1,
    "MisclassifiedAccount": 1,
    "ExceededApprovalLimit": 1,
    "JustBelowThreshold": 1,
    "SelfApproval": 1,
    "SegregationOfDutiesViolation": 1,
    "SkippedApproval": 1,
    "WrongPeriod": 1,
    "DuplicateEntry": 1,
    "MissingOrCorruptedDescription": 1,
    "RevenueCutoffMismatch": 1,
    "ExpenseCutoffMismatch": 1,
    "UnusualAccountPair": 1,
    "BatchAnomaly": 1,
}

FIELD_CONTRACT_LABELS = {
    "ApprovalDateMissing",
    "InvalidAccount",
    "ExceededApprovalLimit",
    "SelfApproval",
    "SegregationOfDutiesViolation",
    "SkippedApproval",
    "WrongPeriod",
}

REQUIRED_SIDECARS = {
    "labels/approval_date_missing_cases.csv": 1,
    "labels/approval_date_present_normal_controls.csv": 1,
    "labels/duplicate_payment_pairs.csv": 1,
    "labels/l101_unbalanced_truth.csv": 0,
    "labels/l201_just_below_threshold_truth.csv": 0,
    "labels/duplicate_payment_negative_controls.csv": 1,
    "labels/misclassified_account_coa_fix_cases.csv": 1,
    "labels/intercompany_population_truth.csv": 1,
    "labels/manual_entry_population_truth.csv": 1,
    "labels/weekend_review_population.csv": 1,
    "labels/high_risk_account_review_population.csv": 1,
    "labels/rare_account_pair_review_population.csv": 1,
    "labels/benford_finding_truth.csv": 1,
    "labels/account_activity_variance_truth.csv": 1,
    "labels/monthly_pattern_shift_confirmed_anomalies.csv": 1,
    "labels/wrong_period_confirmed_anomalies.csv": 1,
    "labels/wrong_period_normal_controls.csv": 1,
    "labels/field_contract_truth.csv": 0,
    "labels/l1_audit_issue_truth.csv": 0,
    "labels/l1_field_only_normal_or_review.csv": 0,
}

YEARS = (2022, 2023, 2024)
APPROVAL_THRESHOLDS = (10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000)
SKIPPED_APPROVAL_SYSTEM_SOURCES = {"automated", "batch", "interface", "system"}
SKIPPED_APPROVAL_CONFIRMED_SOURCES = {"manual", "adjustment"}


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def load_label_counts(dataset: Path) -> dict[str, int]:
    labels_path = dataset / "labels" / "anomaly_labels.csv"
    if not labels_path.exists():
        return {}
    labels = pd.read_csv(labels_path, dtype=str, usecols=["anomaly_type"])
    return {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().to_dict().items()}


def load_sidecar_counts(dataset: Path) -> dict[str, int]:
    return {rel: count_csv_rows(dataset / rel) for rel in REQUIRED_SIDECARS}


def load_contract_labels(dataset: Path, anomaly_labels: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    path = dataset / "labels" / "field_contract_truth.csv"
    if not path.exists():
        return anomaly_labels, False
    field_contract = pd.read_csv(path, dtype=str)
    return field_contract, True


def load_journal_docs(dataset: Path, usecols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = dataset / f"journal_entries_{year}.csv"
        if not path.exists():
            continue
        frames.append(pd.read_csv(path, dtype=str, usecols=usecols, low_memory=False))
    if not frames:
        return pd.DataFrame(columns=usecols)
    return pd.concat(frames, ignore_index=True)


def check_file_integrity(dataset: Path) -> list[str]:
    failures: list[str] = []
    combined = dataset / "journal_entries.csv"
    combined_rows = count_csv_rows(combined)
    year_rows = {year: count_csv_rows(dataset / f"journal_entries_{year}.csv") for year in YEARS}
    if combined_rows and sum(year_rows.values()) != combined_rows:
        failures.append(
            f"journal row count mismatch: combined={combined_rows}, year_sum={sum(year_rows.values())}, years={year_rows}"
        )

    for year in YEARS:
        path = dataset / f"journal_entries_{year}.csv"
        if not path.exists():
            failures.append(f"missing journal year split: {path}")
            continue
        df = pd.read_csv(path, dtype=str, usecols=["document_id", "line_number"], low_memory=False)
        duplicated = int(df.duplicated(["document_id", "line_number"]).sum())
        if duplicated:
            failures.append(f"duplicate document_id+line_number in {path.name}: {duplicated}")
    return failures


def check_l101_unbalanced_truth(dataset: Path) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    rows = load_journal_docs(dataset, ["document_id", "fiscal_year", "debit_amount", "credit_amount"])
    if rows.empty:
        return {"actual_unbalanced_docs": 0, "sidecar_docs": 0}, ["L1-01: no journal docs loaded"]
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )
    docs["abs_imbalance_amount"] = (docs["debit_amount"] - docs["credit_amount"]).abs()
    actual = set(docs.loc[docs["abs_imbalance_amount"].gt(1.0), "document_id"].astype(str))
    truth_path = dataset / "labels" / "l101_unbalanced_truth.csv"
    sidecar_docs: set[str] = set()
    if truth_path.exists():
        truth = pd.read_csv(truth_path, dtype=str, usecols=["document_id"])
        sidecar_docs = set(truth["document_id"].dropna().astype(str))
    else:
        failures.append("L1-01 sidecar missing: labels/l101_unbalanced_truth.csv")
    mismatch = actual.symmetric_difference(sidecar_docs) if sidecar_docs else actual
    if mismatch:
        failures.append(f"L1-01 unbalanced truth sidecar mismatch against debit/credit arithmetic: {len(mismatch)}")
    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_unbalanced_docs": len(actual),
            "sidecar_docs": len(sidecar_docs),
            "sidecar_mismatch": len(mismatch),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def load_approval_limits(dataset: Path) -> dict[str, float]:
    path = dataset / "master_data" / "employees.json"
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit") or 0.0)
        for row in records
        if str(row.get("user_id", "")).strip()
    }


def check_l201_near_threshold_truth(dataset: Path) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    limits = load_approval_limits(dataset)
    if not limits:
        return {"actual_l201_docs": 0, "sidecar_docs": 0}, ["L2-01: approval limits missing"]
    rows = load_journal_docs(dataset, ["document_id", "fiscal_year", "approved_by", "debit_amount", "credit_amount"])
    if rows.empty:
        return {"actual_l201_docs": 0, "sidecar_docs": 0}, ["L2-01: no journal docs loaded"]
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        approved_by=("approved_by", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )
    docs["document_amount"] = docs[["debit_amount", "credit_amount"]].max(axis=1)
    docs["approval_limit"] = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
    actual = set(
        docs.loc[
            docs["approval_limit"].notna()
            & docs["approval_limit"].gt(0)
            & docs["document_amount"].ge(docs["approval_limit"] * 0.9)
            & docs["document_amount"].lt(docs["approval_limit"]),
            "document_id",
        ].astype(str)
    )
    truth_path = dataset / "labels" / "l201_just_below_threshold_truth.csv"
    sidecar_docs: set[str] = set()
    if truth_path.exists():
        truth = pd.read_csv(truth_path, dtype=str, usecols=["document_id"])
        sidecar_docs = set(truth["document_id"].dropna().astype(str))
    else:
        failures.append("L2-01 sidecar missing: labels/l201_just_below_threshold_truth.csv")
    mismatch = actual.symmetric_difference(sidecar_docs) if sidecar_docs else actual
    if mismatch:
        failures.append(f"L2-01 near-threshold truth sidecar mismatch against approval-limit arithmetic: {len(mismatch)}")
    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_l201_docs": len(actual),
            "sidecar_docs": len(sidecar_docs),
            "sidecar_mismatch": len(mismatch),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )
def norm_account(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().replace(".0", "")


def load_config_coa() -> set[str]:
    coa_path = Path("config/chart_of_accounts.csv")
    if not coa_path.exists():
        return set()
    coa = pd.read_csv(coa_path, dtype=str)
    if "gl_account" not in coa.columns:
        return set()
    return set(coa["gl_account"].dropna().astype(str).str.strip())


def check_l103_l301_boundary(dataset: Path, labels: pd.DataFrame) -> list[str]:
    valid_accounts = load_config_coa()
    if not valid_accounts:
        return ["config/chart_of_accounts.csv is missing or has no gl_account column"]

    invalid_docs = set(labels.loc[labels["anomaly_type"].eq("InvalidAccount"), "document_id"].dropna().astype(str))
    misclassified_docs = set(
        labels.loc[labels["anomaly_type"].eq("MisclassifiedAccount"), "document_id"].dropna().astype(str)
    )
    failures: list[str] = []
    unlabeled_bad_docs: set[str] = set()
    misclassified_bad_docs: set[str] = set()
    for year in (2022, 2023, 2024):
        path = dataset / f"journal_entries_{year}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, usecols=["document_id", "gl_account"])
        df["_gl_norm"] = df["gl_account"].map(norm_account)
        bad = df.loc[df["_gl_norm"].ne("") & ~df["_gl_norm"].isin(valid_accounts)].copy()
        bad_docs = set(bad["document_id"].astype(str))
        unlabeled_bad_docs.update(bad_docs - invalid_docs)
        misclassified_bad_docs.update(bad_docs & misclassified_docs)
    if unlabeled_bad_docs:
        failures.append(f"unregistered GL docs without InvalidAccount label: {len(unlabeled_bad_docs)}")
    if misclassified_bad_docs:
        failures.append(f"MisclassifiedAccount docs still use unregistered GL: {len(misclassified_bad_docs)}")
    return failures


def check_selfapproval_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    docs = load_journal_docs(
        dataset,
        ["document_id", "fiscal_year", "source", "user_persona", "created_by", "approved_by"],
    )
    if docs.empty:
        return {"actual_l105_docs": 0, "label_docs": 0, "sidecar_docs": 0}, ["SelfApproval: no journal docs loaded"]

    docs = docs.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        source=("source", "first"),
        user_persona=("user_persona", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
    )
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    persona = docs["user_persona"].fillna("").astype(str).str.strip().str.lower()
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    actual = set(
        docs.loc[
            created.ne("")
            & approved.ne("")
            & created.eq(approved)
            & ~persona.eq("automated_system")
            & ~source.eq("automated"),
            "document_id",
        ].astype(str)
    )
    label_docs = set(labels.loc[labels["anomaly_type"].eq("SelfApproval"), "document_id"].dropna().astype(str))
    sidecar_path = dataset / "labels" / "self_approval_review_population.csv"
    sidecar_docs: set[str] = set()
    if sidecar_path.exists():
        sidecar = pd.read_csv(sidecar_path, dtype=str, usecols=["document_id"])
        sidecar_docs = set(sidecar["document_id"].dropna().astype(str))
    else:
        failures.append("SelfApproval sidecar missing: labels/self_approval_review_population.csv")

    missing_labels = actual - label_docs
    extra_labels = label_docs - actual
    sidecar_mismatch = actual.symmetric_difference(sidecar_docs) if sidecar_docs else actual
    if missing_labels:
        failures.append(f"SelfApproval labels missing actual L1-05 docs: {len(missing_labels)}")
    if extra_labels:
        failures.append(f"SelfApproval labels without actual L1-05 field condition: {len(extra_labels)}")
    if sidecar_mismatch:
        failures.append(f"SelfApproval sidecar mismatch against actual L1-05 docs: {len(sidecar_mismatch)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_l105_docs": len(actual),
            "label_docs": len(label_docs),
            "sidecar_docs": len(sidecar_docs),
            "missing_labels": len(missing_labels),
            "extra_labels": len(extra_labels),
            "sidecar_mismatch": len(sidecar_mismatch),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def load_employee_limits(dataset: Path) -> dict[str, float]:
    path = dataset / "master_data" / "employees.json"
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit"))
        for row in records
        if str(row.get("user_id", "")).strip() and row.get("approval_limit") not in (None, "")
    }


def check_approval_limit_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    limits = load_employee_limits(dataset)
    if not limits:
        return {"actual_exceeded_docs": 0, "label_docs": 0, "sidecar_docs": 0}, ["approval limits missing"]

    rows = load_journal_docs(
        dataset,
        ["document_id", "fiscal_year", "approved_by", "debit_amount", "credit_amount"],
    )
    if rows.empty:
        return {"actual_exceeded_docs": 0, "label_docs": 0, "sidecar_docs": 0}, ["L1-04: no journal docs loaded"]
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        approved_by=("approved_by", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )
    docs["document_amount"] = docs[["debit_amount", "credit_amount"]].max(axis=1)
    docs["approval_limit"] = docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
    actual = set(
        docs.loc[
            docs["approval_limit"].notna() & docs["document_amount"].gt(docs["approval_limit"]),
            "document_id",
        ].astype(str)
    )
    label_docs = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].dropna().astype(str))
    sidecar_path = dataset / "labels" / "approval_limit_exceeded_population.csv"
    sidecar_docs: set[str] = set()
    if sidecar_path.exists():
        sidecar = pd.read_csv(sidecar_path, dtype=str, usecols=["document_id"])
        sidecar_docs = set(sidecar["document_id"].dropna().astype(str))
    else:
        failures.append("ExceededApprovalLimit sidecar missing: labels/approval_limit_exceeded_population.csv")

    missing_labels = actual - label_docs
    extra_labels = label_docs - actual
    sidecar_mismatch = actual.symmetric_difference(sidecar_docs) if sidecar_docs else actual
    if missing_labels:
        failures.append(f"ExceededApprovalLimit labels missing actual L1-04 docs: {len(missing_labels)}")
    if extra_labels:
        failures.append(f"ExceededApprovalLimit labels without actual L1-04 field condition: {len(extra_labels)}")
    if sidecar_mismatch:
        failures.append(f"ExceededApprovalLimit sidecar mismatch against actual L1-04 docs: {len(sidecar_mismatch)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_exceeded_docs": len(actual),
            "label_docs": len(label_docs),
            "sidecar_docs": len(sidecar_docs),
            "missing_labels": len(missing_labels),
            "extra_labels": len(extra_labels),
            "sidecar_mismatch": len(sidecar_mismatch),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def check_sod_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    docs = load_journal_docs(dataset, ["document_id", "fiscal_year", "sod_violation"])
    if docs.empty:
        return {"sod_true_docs": 0, "label_docs": 0, "review_population_docs": 0}, ["L1-06: no journal docs loaded"]
    docs = docs.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        sod_violation=("sod_violation", "first"),
    )
    sod_true = set(
        docs.loc[
            docs["sod_violation"].fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes"}),
            "document_id",
        ].astype(str)
    )
    label_docs = set(
        labels.loc[labels["anomaly_type"].eq("SegregationOfDutiesViolation"), "document_id"].dropna().astype(str)
    )
    review_path = dataset / "labels" / "sod_review_population.csv"
    confirmed_path = dataset / "labels" / "sod_confirmed_anomalies.csv"
    review_docs: set[str] = set()
    confirmed_docs: set[str] = set()
    if review_path.exists():
        review = pd.read_csv(review_path, dtype=str, usecols=["document_id"])
        review_docs = set(review["document_id"].dropna().astype(str))
    else:
        failures.append("SoD review sidecar missing: labels/sod_review_population.csv")
    if confirmed_path.exists():
        confirmed = pd.read_csv(confirmed_path, dtype=str, usecols=["document_id"])
        confirmed_docs = set(confirmed["document_id"].dropna().astype(str))
    else:
        failures.append("SoD confirmed sidecar missing: labels/sod_confirmed_anomalies.csv")

    missing_labels = sod_true - label_docs
    label_missing_sod = label_docs - sod_true
    confirmed_mismatch = label_docs.symmetric_difference(confirmed_docs) if confirmed_docs else label_docs
    review_overlap = review_docs & label_docs
    if missing_labels:
        failures.append(f"sod_violation=True without SegregationOfDutiesViolation label: {len(missing_labels)}")
    if label_missing_sod:
        failures.append(f"SegregationOfDutiesViolation labels without sod_violation=True: {len(label_missing_sod)}")
    if confirmed_mismatch:
        failures.append(f"SoD confirmed sidecar mismatch against labels: {len(confirmed_mismatch)}")
    if review_overlap:
        failures.append(f"SoD review sidecar overlaps confirmed labels: {len(review_overlap)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(sod_true), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "sod_true_docs": len(sod_true),
            "label_docs": len(label_docs),
            "review_population_docs": len(review_docs),
            "confirmed_sidecar_docs": len(confirmed_docs),
            "missing_labels": len(missing_labels),
            "label_missing_sod": len(label_missing_sod),
            "confirmed_sidecar_mismatch": len(confirmed_mismatch),
            "review_confirmed_overlap": len(review_overlap),
            "sod_true_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def approval_level(amount: pd.Series) -> pd.Series:
    level = pd.Series(0, index=amount.index, dtype="int64")
    for idx, threshold in enumerate(APPROVAL_THRESHOLDS, 1):
        level = level.where(amount < threshold, idx)
    return level


def check_skipped_approval_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    rows = load_journal_docs(
        dataset,
        ["document_id", "fiscal_year", "source", "approved_by", "debit_amount", "credit_amount"],
    )
    if rows.empty:
        return {"actual_l107_docs": 0, "label_docs": 0, "confirmed_sidecar_docs": 0}, ["L1-07: no journal docs loaded"]
    for col in ("debit_amount", "credit_amount"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        source=("source", "first"),
        approved_by=("approved_by", "first"),
        debit_amount=("debit_amount", "sum"),
        credit_amount=("credit_amount", "sum"),
    )
    docs["document_amount"] = docs["debit_amount"]
    docs["approval_level"] = approval_level(docs["document_amount"])
    missing_approver = docs["approved_by"].fillna("").astype(str).str.strip().eq("")
    source_norm = docs["source"].fillna("").astype(str).str.strip().str.lower()
    actual = set(
        docs.loc[
            missing_approver
            & source_norm.isin(SKIPPED_APPROVAL_CONFIRMED_SOURCES)
            & docs["approval_level"].ge(1),
            "document_id",
        ].astype(str)
    )
    label_docs = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].dropna().astype(str))
    confirmed_path = dataset / "labels" / "skipped_approval_confirmed_anomalies.csv"
    controls_path = dataset / "labels" / "skipped_approval_normal_controls.csv"
    confirmed_docs: set[str] = set()
    control_docs: set[str] = set()
    if confirmed_path.exists():
        confirmed = pd.read_csv(confirmed_path, dtype=str, usecols=["document_id"])
        confirmed_docs = set(confirmed["document_id"].dropna().astype(str))
    else:
        failures.append("SkippedApproval confirmed sidecar missing: labels/skipped_approval_confirmed_anomalies.csv")
    if controls_path.exists():
        controls = pd.read_csv(controls_path, dtype=str, usecols=["document_id"])
        control_docs = set(controls["document_id"].dropna().astype(str))
    else:
        failures.append("SkippedApproval normal controls missing: labels/skipped_approval_normal_controls.csv")

    missing_labels = actual - label_docs
    extra_labels = label_docs - actual
    confirmed_mismatch = label_docs.symmetric_difference(confirmed_docs) if confirmed_docs else label_docs
    control_overlap = control_docs & label_docs
    if missing_labels:
        failures.append(f"SkippedApproval labels missing actual L1-07 docs: {len(missing_labels)}")
    if extra_labels:
        failures.append(f"SkippedApproval labels without actual L1-07 field condition: {len(extra_labels)}")
    if confirmed_mismatch:
        failures.append(f"SkippedApproval confirmed sidecar mismatch against labels: {len(confirmed_mismatch)}")
    if control_overlap:
        failures.append(f"SkippedApproval normal controls overlap labels: {len(control_overlap)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_l107_docs": len(actual),
            "label_docs": len(label_docs),
            "confirmed_sidecar_docs": len(confirmed_docs),
            "normal_control_docs": len(control_docs),
            "missing_labels": len(missing_labels),
            "extra_labels": len(extra_labels),
            "confirmed_sidecar_mismatch": len(confirmed_mismatch),
            "normal_control_label_overlap": len(control_overlap),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def check_approval_date_missing_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    docs = load_journal_docs(dataset, ["document_id", "fiscal_year", "approved_by", "approval_date"])
    if docs.empty:
        return {"actual_l109_docs": 0, "label_docs": 0, "case_sidecar_docs": 0}, ["L1-09: no journal docs loaded"]

    docs = docs.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
    )
    has_approver = docs["approved_by"].fillna("").astype(str).str.strip().ne("")
    missing_date = docs["approval_date"].fillna("").astype(str).str.strip().eq("")
    actual = set(docs.loc[has_approver & missing_date, "document_id"].astype(str))
    label_docs = set(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].dropna().astype(str))
    cases_path = dataset / "labels" / "approval_date_missing_cases.csv"
    controls_path = dataset / "labels" / "approval_date_present_normal_controls.csv"
    case_docs: set[str] = set()
    control_docs: set[str] = set()
    if cases_path.exists():
        cases = pd.read_csv(cases_path, dtype=str, usecols=["document_id"])
        case_docs = set(cases["document_id"].dropna().astype(str))
    else:
        failures.append("ApprovalDateMissing cases sidecar missing: labels/approval_date_missing_cases.csv")
    if controls_path.exists():
        controls = pd.read_csv(controls_path, dtype=str, usecols=["document_id"])
        control_docs = set(controls["document_id"].dropna().astype(str))
    else:
        failures.append("ApprovalDate normal controls missing: labels/approval_date_present_normal_controls.csv")

    missing_labels = actual - label_docs
    extra_labels = label_docs - actual
    case_mismatch = label_docs.symmetric_difference(case_docs) if case_docs else label_docs
    control_overlap = control_docs & label_docs
    if missing_labels:
        failures.append(f"ApprovalDateMissing labels missing actual L1-09 docs: {len(missing_labels)}")
    if extra_labels:
        failures.append(f"ApprovalDateMissing labels without actual L1-09 field condition: {len(extra_labels)}")
    if case_mismatch:
        failures.append(f"ApprovalDateMissing cases sidecar mismatch against labels: {len(case_mismatch)}")
    if control_overlap:
        failures.append(f"ApprovalDate normal controls overlap labels: {len(control_overlap)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_l109_docs": len(actual),
            "label_docs": len(label_docs),
            "case_sidecar_docs": len(case_docs),
            "normal_control_docs": len(control_docs),
            "missing_labels": len(missing_labels),
            "extra_labels": len(extra_labels),
            "case_sidecar_mismatch": len(case_mismatch),
            "normal_control_label_overlap": len(control_overlap),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def check_wrong_period_contract(dataset: Path, labels: pd.DataFrame) -> tuple[dict[str, object], list[str]]:
    failures: list[str] = []
    docs = load_journal_docs(dataset, ["document_id", "fiscal_year", "fiscal_period", "posting_date"])
    if docs.empty:
        return {"actual_l108_docs": 0, "label_docs": 0, "confirmed_sidecar_docs": 0}, ["L1-08: no journal docs loaded"]

    docs = docs.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        fiscal_period=("fiscal_period", "first"),
        posting_date=("posting_date", "first"),
    )
    docs["fiscal_period_num"] = pd.to_numeric(docs["fiscal_period"], errors="coerce")
    docs["posting_month"] = pd.to_datetime(docs["posting_date"], errors="coerce").dt.month
    actual = set(
        docs.loc[
            docs["fiscal_period_num"].notna()
            & docs["posting_month"].notna()
            & docs["fiscal_period_num"].ne(docs["posting_month"]),
            "document_id",
        ].astype(str)
    )
    label_docs = set(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].dropna().astype(str))
    confirmed_path = dataset / "labels" / "wrong_period_confirmed_anomalies.csv"
    controls_path = dataset / "labels" / "wrong_period_normal_controls.csv"
    confirmed_docs: set[str] = set()
    control_docs: set[str] = set()
    if confirmed_path.exists():
        confirmed = pd.read_csv(confirmed_path, dtype=str, usecols=["document_id"])
        confirmed_docs = set(confirmed["document_id"].dropna().astype(str))
    else:
        failures.append("WrongPeriod confirmed sidecar missing: labels/wrong_period_confirmed_anomalies.csv")
    if controls_path.exists():
        controls = pd.read_csv(controls_path, dtype=str, usecols=["document_id"])
        control_docs = set(controls["document_id"].dropna().astype(str))
    else:
        failures.append("WrongPeriod normal controls missing: labels/wrong_period_normal_controls.csv")

    missing_labels = actual - label_docs
    extra_labels = label_docs - actual
    confirmed_mismatch = actual.symmetric_difference(confirmed_docs) if confirmed_docs else actual
    control_overlap = control_docs & label_docs
    if missing_labels:
        failures.append(f"WrongPeriod labels missing actual L1-08 docs: {len(missing_labels)}")
    if extra_labels:
        failures.append(f"WrongPeriod labels without actual L1-08 field condition: {len(extra_labels)}")
    if confirmed_mismatch:
        failures.append(f"WrongPeriod confirmed sidecar mismatch against actual L1-08 docs: {len(confirmed_mismatch)}")
    if control_overlap:
        failures.append(f"WrongPeriod normal controls overlap labels: {len(control_overlap)}")

    by_year = (
        docs.loc[docs["document_id"].astype(str).isin(actual), "fiscal_year"]
        .value_counts()
        .sort_index()
        .to_dict()
    )
    return (
        {
            "actual_l108_docs": len(actual),
            "label_docs": len(label_docs),
            "confirmed_sidecar_docs": len(confirmed_docs),
            "normal_control_docs": len(control_docs),
            "missing_labels": len(missing_labels),
            "extra_labels": len(extra_labels),
            "confirmed_sidecar_mismatch": len(confirmed_mismatch),
            "normal_control_label_overlap": len(control_overlap),
            "actual_by_year": {str(k): int(v) for k, v in by_year.items()},
        },
        failures,
    )


def check_previous_regression(
    dataset: Path,
    previous: Path | None,
    *,
    allow_decrease: set[str],
) -> tuple[dict[str, object], list[str]]:
    if previous is None:
        return {}, []
    failures: list[str] = []
    current_labels = load_label_counts(dataset)
    previous_labels = load_label_counts(previous)
    current_sidecars = load_sidecar_counts(dataset)
    previous_sidecars = load_sidecar_counts(previous)
    label_regressions: dict[str, dict[str, int]] = {}
    sidecar_regressions: dict[str, dict[str, int]] = {}
    for label, previous_count in previous_labels.items():
        current_count = current_labels.get(label, 0)
        if current_count < previous_count and label not in allow_decrease:
            label_regressions[label] = {"previous": previous_count, "current": current_count}
    for rel, previous_count in previous_sidecars.items():
        current_count = current_sidecars.get(rel, 0)
        key = f"sidecar:{rel}"
        if current_count < previous_count and key not in allow_decrease:
            sidecar_regressions[rel] = {"previous": previous_count, "current": current_count}
    if label_regressions:
        failures.append(f"label count regressions vs previous: {label_regressions}")
    if sidecar_regressions:
        failures.append(f"sidecar count regressions vs previous: {sidecar_regressions}")
    return (
        {
            "previous_dataset": str(previous),
            "label_regressions": label_regressions,
            "sidecar_regressions": sidecar_regressions,
        },
        failures,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate required DataSynth truth files.")
    parser.add_argument("dataset", nargs="?", default="data/journal/primary/datasynth")
    parser.add_argument("--previous", help="Previous validated dataset to compare truth counts against.")
    parser.add_argument(
        "--allow-decrease",
        action="append",
        default=[],
        help="Allow an intentional count decrease for a label or sidecar:<relative_path>.",
    )
    args = parser.parse_args()

    dataset = Path(args.dataset)
    previous = Path(args.previous) if args.previous else None
    labels_path = dataset / "labels" / "anomaly_labels.csv"
    failures: list[str] = []
    report: dict[str, object] = {"dataset": str(dataset), "labels": {}, "sidecars": {}, "contracts": {}}

    if not labels_path.exists():
        raise SystemExit(f"missing labels file: {labels_path}")

    labels = pd.read_csv(labels_path)
    contract_labels, audit_issue_mode = load_contract_labels(dataset, labels)
    counts = labels["anomaly_type"].value_counts()
    contract_counts = contract_labels["anomaly_type"].value_counts()
    for label, minimum in REQUIRED_LABELS.items():
        actual = int(contract_counts.get(label, 0)) if audit_issue_mode and label in FIELD_CONTRACT_LABELS else int(counts.get(label, 0))
        report["labels"][label] = actual
        if actual < minimum:
            failures.append(f"{label}: expected >= {minimum}, actual {actual}")
    if audit_issue_mode:
        report["anomaly_labels_truth_semantics"] = "audit_issue_truth"
        report["field_contract_truth_rows"] = int(len(contract_labels))

    for rel, minimum in REQUIRED_SIDECARS.items():
        actual = count_csv_rows(dataset / rel)
        report["sidecars"][rel] = actual
        if actual < minimum:
            failures.append(f"{rel}: expected >= {minimum}, actual {actual}")

    failures.extend(check_file_integrity(dataset))
    l101_report, l101_failures = check_l101_unbalanced_truth(dataset)
    report["contracts"]["L1-01"] = l101_report
    failures.extend(l101_failures)
    l201_report, l201_failures = check_l201_near_threshold_truth(dataset)
    report["contracts"]["L2-01"] = l201_report
    failures.extend(l201_failures)
    failures.extend(check_l103_l301_boundary(dataset, contract_labels))
    selfapproval_report, selfapproval_failures = check_selfapproval_contract(dataset, contract_labels)
    report["contracts"]["SelfApproval"] = selfapproval_report
    failures.extend(selfapproval_failures)
    approval_limit_report, approval_limit_failures = check_approval_limit_contract(dataset, contract_labels)
    report["contracts"]["ExceededApprovalLimit"] = approval_limit_report
    failures.extend(approval_limit_failures)
    sod_report, sod_failures = check_sod_contract(dataset, contract_labels)
    report["contracts"]["SegregationOfDutiesViolation"] = sod_report
    failures.extend(sod_failures)
    skipped_report, skipped_failures = check_skipped_approval_contract(dataset, contract_labels)
    report["contracts"]["SkippedApproval"] = skipped_report
    failures.extend(skipped_failures)
    approval_date_report, approval_date_failures = check_approval_date_missing_contract(dataset, contract_labels)
    report["contracts"]["ApprovalDateMissing"] = approval_date_report
    failures.extend(approval_date_failures)
    wrong_period_report, wrong_period_failures = check_wrong_period_contract(dataset, contract_labels)
    report["contracts"]["WrongPeriod"] = wrong_period_report
    failures.extend(wrong_period_failures)

    previous_report, previous_failures = check_previous_regression(
        dataset,
        previous,
        allow_decrease=set(args.allow_decrease),
    )
    if previous_report:
        report["previous_regression"] = previous_report
    failures.extend(previous_failures)

    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
