"""Repair contract-v2 master and document-flow coverage.

This keeps the semantic-clean journal intact as much as possible, but ensures
Phase1's independent evidence joins are backed by sidecar records:

- every journal reference with a document-flow prefix has a flow header record;
- normal approvers exist in employee master with JE approval authorization;
- a small deterministic approval-limit fixture set remains for contract rules.

The script is intentionally scoped to ``datasynth_contract_v2`` candidates.
Legacy ``datasynth_contract`` is not modified.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

YEARS = (2022, 2023, 2024)
FLOW_FILES = {
    "PO": ("purchase_orders.json", "purchase_order"),
    "GR": ("goods_receipts.json", "goods_receipt"),
    "VI": ("vendor_invoices.json", "vendor_invoice"),
    "PAY": ("payments.json", "payment"),
    "SO": ("sales_orders.json", "sales_order"),
    "DLV": ("deliveries.json", "delivery"),
    "CI": ("customer_invoices.json", "customer_invoice"),
}
FLOW_ID_RE = re.compile(r"^(PO|GR|VI|PAY|SO|CI|DLV)-")
PLACEHOLDER_MARKER = "contract_v2_master_flow_coverage_repair"
LIMIT_FIXTURE_APPROVER = "LIMIT_REVIEWER"
NEAR_LIMIT_FIXTURE_APPROVER = "NEAR_LIMIT_REVIEWER"
LIMIT_FIXTURE_DOCS = 50
SKIPPED_APPROVAL_FIXTURE_DOCS = 50
SELF_APPROVAL_FIXTURE_DOCS = 50


def read_csv(path: Path, *, usecols: set[str] | None = None) -> pd.DataFrame:
    if usecols is None:
        return pd.read_csv(path, dtype=str, low_memory=False)
    return pd.read_csv(path, dtype=str, usecols=lambda col: col in usecols, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list: {path}")
    return payload


def normalized_reference(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().upper()
    return re.sub(r"^[A-Z0-9_]+:", "", text).strip()


def first_nonblank(row: pd.Series, names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = row.get(name, "")
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    return default


def document_amounts(journal: pd.DataFrame) -> pd.Series:
    amount = pd.to_numeric(
        journal.get("local_amount", pd.Series(0, index=journal.index)), errors="coerce"
    )
    amount = amount.fillna(0.0).abs()
    return amount.groupby(journal["document_id"].astype(str)).transform("sum")


def load_flow_ids(flow_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in flow_dir.glob("*.json"):
        for row in load_json_list(path):
            header = row.get("header") if isinstance(row.get("header"), dict) else {}
            doc_id = str(header.get("document_id") or "").strip().upper()
            if doc_id:
                ids.add(doc_id)
            for ref in header.get("document_references") or []:
                if not isinstance(ref, dict):
                    continue
                for key in ("source_doc_id", "target_doc_id"):
                    ref_id = str(ref.get(key) or "").strip().upper()
                    if ref_id:
                        ids.add(ref_id)
    return ids


def flow_orphan_rows(journal: pd.DataFrame, flow_ids: set[str]) -> int:
    refs = journal.get("reference", pd.Series("", index=journal.index)).map(normalized_reference)
    has_prefix = refs.str.match(FLOW_ID_RE, na=False)
    return int((has_prefix & ~refs.isin(flow_ids)).sum())


def placeholder_flow_record(ref_id: str, document_type: str, sample: pd.Series) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    company_code = first_nonblank(sample, ("company_code",), "C001")
    fiscal_year = first_nonblank(sample, ("fiscal_year",), "2024")
    fiscal_period = first_nonblank(sample, ("fiscal_period",), "1")
    posting_date = first_nonblank(
        sample, ("posting_date", "document_date", "entry_date"), "2024-01-01"
    )
    creator = first_nonblank(sample, ("created_by",), "SYSTEM")
    currency = first_nonblank(sample, ("currency",), "KRW")
    journal_doc = first_nonblank(sample, ("document_id",), "")
    try:
        fiscal_year_value: int | str = int(float(fiscal_year))
    except ValueError:
        fiscal_year_value = fiscal_year
    try:
        fiscal_period_value: int | str = int(float(fiscal_period))
    except ValueError:
        fiscal_period_value = fiscal_period

    return {
        "header": {
            "document_id": ref_id,
            "document_type": document_type,
            "company_code": company_code,
            "fiscal_year": fiscal_year_value,
            "fiscal_period": fiscal_period_value,
            "document_date": posting_date[:10],
            "posting_date": posting_date[:10],
            "entry_date": posting_date[:10],
            "entry_timestamp": now,
            "status": "posted",
            "created_by": creator,
            "changed_by": creator,
            "changed_at": now,
            "currency": currency,
            "reference": journal_doc or None,
            "header_text": "DataSynth contract v2 document-flow sidecar",
            "journal_entry_id": journal_doc or None,
            "document_references": [],
        },
        "generated_by": PLACEHOLDER_MARKER,
    }


def repair_document_flows(dataset: Path, journal: pd.DataFrame) -> dict[str, Any]:
    flow_dir = dataset / "document_flows"
    before_ids = load_flow_ids(flow_dir)
    before_orphans = flow_orphan_rows(journal, before_ids)

    references = journal.get("reference", pd.Series("", index=journal.index)).map(
        normalized_reference
    )
    candidates = journal.loc[references.str.match(FLOW_ID_RE, na=False)].copy()
    candidates["_flow_ref"] = references.loc[candidates.index]
    samples = candidates.drop_duplicates("_flow_ref").set_index("_flow_ref", drop=False)

    additions_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref_id, sample in samples.iterrows():
        if ref_id in before_ids:
            continue
        match = FLOW_ID_RE.match(ref_id)
        if not match:
            continue
        filename, document_type = FLOW_FILES[match.group(1)]
        additions_by_file[filename].append(placeholder_flow_record(ref_id, document_type, sample))

    for filename, additions in sorted(additions_by_file.items()):
        path = flow_dir / filename
        rows = load_json_list(path)
        rows.extend(additions)
        write_json(path, rows)

    after_ids = load_flow_ids(flow_dir)
    after_orphans = flow_orphan_rows(journal, after_ids)
    return {
        "before_orphan_rows": before_orphans,
        "after_orphan_rows": after_orphans,
        "flow_ids_before": len(before_ids),
        "flow_ids_after": len(after_ids),
        "added_flow_records": sum(len(rows) for rows in additions_by_file.values()),
        "added_by_file": {name: len(rows) for name, rows in sorted(additions_by_file.items())},
    }


def employee_master_maps(employees: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("user_id") or "").strip().upper(): row
        for row in employees
        if str(row.get("user_id") or "").strip()
    }


def ensure_employee(
    employees: list[dict[str, Any]],
    user_id: str,
    *,
    companies: set[str],
    approval_limit: float,
    can_approve_je: bool = True,
) -> dict[str, Any]:
    maps = employee_master_maps(employees)
    row = maps.get(user_id)
    if row is None:
        company = sorted(companies)[0] if companies else "C001"
        row = {
            "employee_id": f"EMP-REPAIR-{user_id}",
            "user_id": user_id,
            "display_name": user_id.replace("_", " ").title(),
            "first_name": user_id,
            "last_name": "",
            "email": f"{user_id.lower()}@company.com",
            "persona": "manager",
            "job_level": "manager",
            "job_title": "Journal Entry Approver",
            "department_id": "Finance",
            "cost_center": f"CC-{company}-FIN",
            "manager_id": None,
            "direct_reports": [],
            "status": "active",
            "company_code": company,
            "working_hours": {"start_hour": 8, "end_hour": 18, "peak_hours": [10, 11, 14, 15]},
            "authorized_company_codes": sorted(companies) or [company],
            "authorized_cost_centers": [],
            "approval_limit": str(int(max(approval_limit, 0))),
            "can_approve_pr": False,
            "can_approve_po": False,
            "can_approve_invoice": False,
            "can_approve_je": can_approve_je,
            "can_release_payment": False,
            "system_roles": ["journal_approver"],
            "transaction_codes": [],
            "hire_date": "2022-01-01",
            "termination_date": None,
            "location": None,
            "is_shared_services": False,
            "phone": None,
        }
        employees.append(row)
    existing_companies = {
        str(value).strip().upper()
        for value in row.get("authorized_company_codes") or []
        if str(value).strip()
    }
    row["authorized_company_codes"] = sorted(existing_companies | companies)
    row["can_approve_je"] = bool(can_approve_je)
    try:
        current_limit = float(row.get("approval_limit") or 0.0)
    except (TypeError, ValueError):
        current_limit = 0.0
    row["approval_limit"] = str(int(max(current_limit, math.ceil(approval_limit))))
    row["status"] = "active"
    return row


def approval_gap_rows(journal: pd.DataFrame, employees: list[dict[str, Any]]) -> dict[str, Any]:
    maps = employee_master_maps(employees)
    ids = set(maps)
    approver = (
        journal.get("approved_by", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    creator = (
        journal.get("created_by", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    company = (
        journal.get("company_code", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    doc_amount = document_amounts(journal)
    manual_creator = ~creator.str.startswith("SYSTEM", na=False)
    missing_approver = approver.eq("") | approver.isin({"NAN", "NONE", "NULL"})
    approver_known = approver.isin(ids)
    can_approve = (
        approver.map({uid: bool(row.get("can_approve_je", False)) for uid, row in maps.items()})
        .fillna(False)
        .astype(bool)
    )
    limits = pd.to_numeric(
        approver.map({uid: row.get("approval_limit", 0) for uid, row in maps.items()}),
        errors="coerce",
    ).fillna(0.0)
    authorized = {
        uid: {
            str(value).strip().upper()
            for value in row.get("authorized_company_codes") or []
            if str(value).strip()
        }
        for uid, row in maps.items()
    }
    company_authorized = pd.Series(
        [
            bool(comp) and comp in authorized.get(app, set())
            for comp, app in zip(company, approver, strict=False)
        ],
        index=journal.index,
    )
    self_approval = creator.ne("") & creator.eq(approver)
    raw_gap = manual_creator & (
        missing_approver
        | self_approval
        | (~approver_known & ~missing_approver)
        | (~can_approve & ~missing_approver)
        | (~company_authorized & ~missing_approver)
    )
    limit_exceeded = manual_creator & ~missing_approver & limits.gt(0) & doc_amount.gt(limits)
    return {
        "approval_contract_gap_rows": int(raw_gap.sum()),
        "approval_limit_exceeded_rows": int(limit_exceeded.sum()),
        "approver_join_gap_rows": int((~missing_approver & ~approver_known).sum()),
    }


def write_journal_and_splits(dataset: Path, journal: pd.DataFrame) -> None:
    journal.to_csv(dataset / "journal_entries.csv", index=False, encoding="utf-8")
    if "fiscal_year" not in journal.columns:
        return
    for year in YEARS:
        year_rows = journal.loc[journal["fiscal_year"].astype(str).eq(str(year))]
        year_rows.to_csv(dataset / f"journal_entries_{year}.csv", index=False, encoding="utf-8")


def repair_approval_master(dataset: Path, journal: pd.DataFrame) -> dict[str, Any]:
    employees_path = dataset / "master_data" / "employees.json"
    employees = load_json_list(employees_path)
    before = approval_gap_rows(journal, employees)

    journal = journal.copy()
    doc_amount = document_amounts(journal)
    journal["_doc_amount"] = doc_amount
    approver = (
        journal.get("approved_by", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    company = (
        journal.get("company_code", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    for user_id in sorted(
        uid for uid in approver.unique() if uid and uid not in {"NAN", "NONE", "NULL"}
    ):
        rows = journal.loc[approver.eq(user_id)]
        companies = {
            str(value).strip().upper()
            for value in company.loc[rows.index].unique()
            if str(value).strip()
        }
        max_amount = float(pd.to_numeric(rows["_doc_amount"], errors="coerce").fillna(0.0).max())
        ensure_employee(
            employees, user_id, companies=companies, approval_limit=max_amount * 1.2 + 1.0
        )

    all_companies = {str(value).strip().upper() for value in company.unique() if str(value).strip()}
    company_approvers: dict[str, str] = {}
    for comp in sorted(all_companies):
        user_id = f"JE_APPROVER_{comp}"
        company_approvers[comp] = user_id
        ensure_employee(
            employees,
            user_id,
            companies={comp},
            approval_limit=max(
                float(pd.to_numeric(journal["_doc_amount"], errors="coerce").fillna(0.0).max())
                * 1.2,
                1.0,
            ),
            can_approve_je=True,
        )
    ensure_employee(
        employees,
        LIMIT_FIXTURE_APPROVER,
        companies=all_companies,
        approval_limit=1.0,
        can_approve_je=True,
    )
    employee_master_maps(employees)[LIMIT_FIXTURE_APPROVER]["approval_limit"] = "1"
    ensure_employee(
        employees,
        NEAR_LIMIT_FIXTURE_APPROVER,
        companies=all_companies,
        approval_limit=1.0,
        can_approve_je=True,
    )

    source = (
        journal.get("source", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    missing_approver = approver.eq("") | approver.isin({"NAN", "NONE", "NULL"})
    creator = (
        journal.get("created_by", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    self_approval = creator.ne("") & creator.eq(approver)
    skipped_fixture_docs = set(
        journal.loc[missing_approver & source.isin({"manual", "adjustment"})]
        .sort_values(["_doc_amount", "document_id"], ascending=[False, True])
        .drop_duplicates("document_id")
        .head(SKIPPED_APPROVAL_FIXTURE_DOCS)["document_id"]
        .astype(str)
    )
    self_fixture_docs = set(
        journal.loc[self_approval & ~journal["document_id"].astype(str).isin(skipped_fixture_docs)]
        .sort_values(["_doc_amount", "document_id"], ascending=[False, True])
        .drop_duplicates("document_id")
        .head(SELF_APPROVAL_FIXTURE_DOCS)["document_id"]
        .astype(str)
    )

    fixture_preserve_docs = skipped_fixture_docs | self_fixture_docs
    normalize_gap_mask = (missing_approver | self_approval) & ~journal["document_id"].astype(
        str
    ).isin(fixture_preserve_docs)
    if normalize_gap_mask.any():
        normalized_approvers = (
            company.loc[normalize_gap_mask].map(company_approvers).fillna("JE_APPROVER_C001")
        )
        journal.loc[normalize_gap_mask, "approved_by"] = normalized_approvers.to_numpy()
        if "approval_date" in journal.columns:
            fallback_date = (
                journal.loc[normalize_gap_mask, "posting_date"].fillna("").astype(str).str[:10]
            )
            journal.loc[normalize_gap_mask, "approval_date"] = fallback_date.mask(
                fallback_date.eq(""), "2024-12-31"
            )

    if skipped_fixture_docs:
        skipped_mask = journal["document_id"].astype(str).isin(skipped_fixture_docs)
        journal.loc[skipped_mask, "approved_by"] = ""
        if "approval_date" in journal.columns:
            journal.loc[skipped_mask, "approval_date"] = ""
    if self_fixture_docs:
        self_mask = journal["document_id"].astype(str).isin(self_fixture_docs)
        journal.loc[self_mask, "approved_by"] = journal.loc[self_mask, "created_by"]
        if "approval_date" in journal.columns:
            fallback_date = journal.loc[self_mask, "posting_date"].fillna("").astype(str).str[:10]
            journal.loc[self_mask, "approval_date"] = fallback_date.mask(
                fallback_date.eq(""), "2024-12-31"
            )

    approver_after_normalization = (
        journal.get("approved_by", pd.Series("", index=journal.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    doc_level = (
        journal.loc[
            approver_after_normalization.ne("")
            & ~approver_after_normalization.isin({"NAN", "NONE", "NULL"})
            & ~journal["document_id"].astype(str).isin(fixture_preserve_docs)
        ]
        .sort_values(["_doc_amount", "document_id"], ascending=[False, True])
        .drop_duplicates("document_id")
    )
    fixture_docs = set(doc_level.head(LIMIT_FIXTURE_DOCS)["document_id"].astype(str))
    fixture_mask = journal["document_id"].astype(str).isin(fixture_docs)
    journal.loc[fixture_mask, "approved_by"] = LIMIT_FIXTURE_APPROVER
    if "approval_date" in journal.columns:
        fallback_date = journal.loc[fixture_mask, "posting_date"].fillna("").astype(str).str[:10]
        journal.loc[fixture_mask, "approval_date"] = fallback_date.mask(
            fallback_date.eq(""), "2024-12-31"
        )

    near_candidates = (
        journal.loc[
            ~journal["document_id"].astype(str).isin(fixture_preserve_docs | fixture_docs)
            & pd.to_numeric(journal["_doc_amount"], errors="coerce").fillna(0.0).gt(1000)
        ]
        .sort_values(["_doc_amount", "document_id"], ascending=[False, True])
        .drop_duplicates("document_id")
    )
    near_fixture_doc = ""
    near_fixture_rows = 0
    if not near_candidates.empty:
        near_fixture_doc = str(near_candidates.iloc[0]["document_id"])
        near_mask = journal["document_id"].astype(str).eq(near_fixture_doc)
        near_amount = float(
            max(
                pd.to_numeric(journal.loc[near_mask, "debit_amount"], errors="coerce")
                .fillna(0.0)
                .sum(),
                pd.to_numeric(journal.loc[near_mask, "credit_amount"], errors="coerce")
                .fillna(0.0)
                .sum(),
            )
        )
        journal.loc[near_mask, "approved_by"] = NEAR_LIMIT_FIXTURE_APPROVER
        if "approval_date" in journal.columns:
            fallback_date = journal.loc[near_mask, "posting_date"].fillna("").astype(str).str[:10]
            journal.loc[near_mask, "approval_date"] = fallback_date.mask(
                fallback_date.eq(""), "2024-12-31"
            )
        employee_master_maps(employees)[NEAR_LIMIT_FIXTURE_APPROVER]["approval_limit"] = str(
            int(math.ceil(near_amount / 0.95))
        )
        near_fixture_rows = int(near_mask.sum())
    journal = journal.drop(columns=["_doc_amount"])

    write_json(employees_path, employees)
    write_journal_and_splits(dataset, journal)
    after = approval_gap_rows(journal, employees)
    return {
        "before": before,
        "after": after,
        "employees_after": len(employees),
        "fixture_approver": LIMIT_FIXTURE_APPROVER,
        "limit_fixture_documents": len(fixture_docs),
        "limit_fixture_rows": int(fixture_mask.sum()),
        "skipped_approval_fixture_documents": len(skipped_fixture_docs),
        "self_approval_fixture_documents": len(self_fixture_docs),
        "near_limit_fixture_document": near_fixture_doc,
        "near_limit_fixture_rows": near_fixture_rows,
        "normalized_approval_gap_rows": int(normalize_gap_mask.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", nargs="?", default="data/journal/primary/datasynth_contract_v2")
    parser.add_argument(
        "--report",
        default="data/journal/primary/datasynth_contract_v2/CONTRACT_V2_MASTER_FLOW_COVERAGE_REPAIR_REPORT.json",
    )
    args = parser.parse_args()

    dataset = Path(args.dataset)
    if dataset.name != "datasynth_contract_v2":
        raise SystemExit(f"refusing to patch non-v2 contract dataset: {dataset}")
    journal_path = dataset / "journal_entries.csv"
    if not journal_path.exists():
        raise SystemExit(f"missing journal: {journal_path}")

    journal = read_csv(journal_path)
    flow_report = repair_document_flows(dataset, journal)
    journal = read_csv(journal_path)
    approval_report = repair_approval_master(dataset, journal)
    repaired_journal = read_csv(journal_path, usecols={"reference"})
    final_flow_report = {
        "final_orphan_rows": flow_orphan_rows(
            repaired_journal, load_flow_ids(dataset / "document_flows")
        )
    }
    report = {
        "dataset": str(dataset),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "document_flow": flow_report | final_flow_report,
        "approval_master": approval_report,
    }
    report_path = Path(args.report)
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
