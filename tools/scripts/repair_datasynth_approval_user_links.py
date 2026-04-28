"""Repair DataSynth JE user foreign keys against employees.json.

The active DataSynth fixtures can contain legacy JE actor ids in
``created_by``/``approved_by`` while ``employees.json`` only contains the newer
generated employee ids.  That makes approval-limit features fall back to the
global minimum threshold.  This script adds explicit employee aliases for the
legacy actors and rewires ExceededApprovalLimit truth documents to approvers
whose limits match the label contract.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASETS = [
    ROOT / "data" / "journal" / "primary" / "datasynth",
    ROOT / "data" / "journal" / "primary" / "datasynth_v59_candidate",
]
YEARS = (2022, 2023, 2024)
TARGET_ANOMALY = "ExceededApprovalLimit"
REPORT_NAME = "V60_APPROVAL_USER_LINK_REPAIR.json"

PERSONA_JOB = {
    "automated_system": ("system", "System User"),
    "junior_accountant": ("staff", "Staff Accountant"),
    "senior_accountant": ("senior", "Senior Accountant"),
    "manager": ("manager", "Approval Manager"),
    "controller": ("executive", "Financial Controller"),
}

PERSONA_LIMIT = {
    "automated_system": 999_999_999_999,
    "junior_accountant": 10_000_000,
    "senior_accountant": 100_000_000,
    "manager": 5_000_000_000,
    "controller": 50_000_000_000,
}


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _load_employee_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
    raise RuntimeError(f"No employee list found in {path}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _records_for_json(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        out: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, float) and pd.isna(value):
                out[key] = None
            else:
                out[key] = value
        records.append(out)
    return records


def _document_summary(je: pd.DataFrame) -> pd.DataFrame:
    work = je.copy()
    work["debit_amount_num"] = pd.to_numeric(work["debit_amount"], errors="coerce").fillna(0.0)
    work["line_abs_amount"] = (
        pd.to_numeric(work["debit_amount"], errors="coerce").fillna(0.0).abs()
        + pd.to_numeric(work["credit_amount"], errors="coerce").fillna(0.0).abs()
    )
    return (
        work.groupby("document_id", as_index=False)
        .agg(
            fiscal_year=("fiscal_year", "first"),
            company_code=("company_code", "first"),
            created_by=("created_by", "first"),
            approved_by=("approved_by", "first"),
            user_persona=("user_persona", "first"),
            document_amount=("debit_amount_num", "sum"),
            document_abs_amount=("line_abs_amount", "sum"),
        )
        .copy()
    )


def _legacy_actor_summary(doc: pd.DataFrame) -> pd.DataFrame:
    creator = (
        doc.loc[doc["created_by"].map(_clean).ne("")]
        .groupby("created_by", as_index=False)
        .agg(
            company_code=("company_code", lambda s: s.value_counts().index[0]),
            persona=("user_persona", lambda s: s.value_counts().index[0]),
            created_docs=("document_id", "count"),
            max_created_amount=("document_abs_amount", "max"),
        )
        .rename(columns={"created_by": "legacy_id"})
    )
    approver = (
        doc.loc[doc["approved_by"].map(_clean).ne("")]
        .groupby("approved_by", as_index=False)
        .agg(
            approved_docs=("document_id", "count"),
            max_approved_amount=("document_abs_amount", "max"),
        )
        .rename(columns={"approved_by": "legacy_id"})
    )
    return creator.merge(approver, on="legacy_id", how="outer").fillna(
        {
            "company_code": "",
            "persona": "junior_accountant",
            "created_docs": 0,
            "max_created_amount": 0,
            "approved_docs": 0,
            "max_approved_amount": 0,
        }
    )


def _template_for_company(employees: pd.DataFrame, company_code: str) -> dict[str, Any]:
    company_rows = employees.loc[employees["company_code"].astype(str).eq(company_code)]
    if not company_rows.empty:
        return deepcopy(company_rows.iloc[0].to_dict())
    return deepcopy(employees.iloc[0].to_dict())


def _legacy_alias_row(row: Any, employees: pd.DataFrame) -> dict[str, Any]:
    legacy_id = _clean(row.legacy_id)
    company_code = _clean(row.company_code)
    persona = _clean(row.persona) or "junior_accountant"
    is_system = persona == "automated_system" or legacy_id in {"SYSTEM", "IC_GENERATOR"}
    job_level, job_title = PERSONA_JOB.get(persona, ("staff", "Staff Accountant"))
    can_approve = bool(float(row.approved_docs) > 0)
    base_limit = PERSONA_LIMIT.get(persona, 10_000_000)
    max_amount = max(float(row.max_created_amount), float(row.max_approved_amount))
    # Legacy aliases are for FK resolution, not truth injection.  Keep their
    # limits high enough to avoid converting ordinary legacy approvals into
    # L1-04 hits just because the alias was restored.
    limit = max(base_limit, int(max_amount))

    template = _template_for_company(employees, company_code)
    template.update(
        {
            "employee_id": f"EMP-ALIAS-{company_code}-{legacy_id}",
            "user_id": legacy_id,
            "display_name": f"Legacy JE User {legacy_id}",
            "first_name": "Legacy",
            "last_name": legacy_id,
            "email": f"{legacy_id.lower()}@legacy.company.com",
            "persona": persona,
            "job_level": job_level,
            "job_title": job_title,
            "department_id": "System" if is_system else "Finance",
            "cost_center": None,
            "manager_id": None,
            "direct_reports": [],
            "status": "active",
            "company_code": company_code,
            "authorized_company_codes": [company_code],
            "authorized_cost_centers": [],
            "approval_limit": str(limit),
            "can_approve_pr": can_approve,
            "can_approve_po": can_approve,
            "can_approve_invoice": False,
            "can_approve_je": can_approve,
            "can_release_payment": False,
            "system_roles": ["system"] if is_system else ["general_accountant"],
            "transaction_codes": [],
            "hire_date": "2022-01-01",
            "termination_date": None,
            "location": None,
            "is_shared_services": False,
            "phone": None,
        }
    )
    return template


def _approval_alias_id(company_code: str, limit: int) -> str:
    if limit >= 1_000_000_000:
        suffix = f"{limit // 1_000_000_000}B"
    else:
        suffix = f"{limit // 1_000_000}M"
    return f"L104-{company_code}-{suffix}"


def _approval_alias_row(company_code: str, limit: int, employees: pd.DataFrame) -> dict[str, Any]:
    user_id = _approval_alias_id(company_code, limit)
    template = _template_for_company(employees, company_code)
    template.update(
        {
            "employee_id": f"EMP-L104-{company_code}-{limit}",
            "user_id": user_id,
            "display_name": f"L1-04 Approver {company_code} {limit}",
            "first_name": "L104",
            "last_name": f"{company_code}{limit}",
            "email": f"{user_id.lower()}@approval.company.com",
            "persona": "manager",
            "job_level": "manager",
            "job_title": "Approval Limit Owner",
            "department_id": "Finance",
            "cost_center": None,
            "manager_id": None,
            "direct_reports": [],
            "status": "active",
            "company_code": company_code,
            "authorized_company_codes": [company_code],
            "authorized_cost_centers": [],
            "approval_limit": str(limit),
            "can_approve_pr": True,
            "can_approve_po": True,
            "can_approve_invoice": False,
            "can_approve_je": True,
            "can_release_payment": False,
            "system_roles": ["approval_manager"],
            "transaction_codes": [],
            "hire_date": "2022-01-01",
            "termination_date": None,
            "location": None,
            "is_shared_services": False,
            "phone": None,
        }
    )
    return template


def _patch_l104_approvers(
    je: pd.DataFrame,
    labels: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]], set[tuple[str, int]]]:
    label_docs = set(
        labels.loc[labels["anomaly_type"].eq(TARGET_ANOMALY), "document_id"]
        .dropna()
        .astype(str)
    )
    if not label_docs:
        return je, [], set()

    doc = _document_summary(je)
    target = doc.loc[doc["document_id"].astype(str).isin(label_docs)].copy()
    patches: list[dict[str, Any]] = []
    required_aliases: set[tuple[str, int]] = set()

    for row in target.itertuples(index=False):
        amount = float(row.document_amount)
        if amount <= 0:
            continue
        # DataSynth L1-04 truth documents are generated at 110% of the target
        # approval limit.
        limit = int(round(amount / 1.1))
        company_code = _clean(row.company_code)
        approver_id = _approval_alias_id(company_code, limit)
        mask = je["document_id"].astype(str).eq(str(row.document_id))
        previous = _clean(row.approved_by)
        je.loc[mask, "approved_by"] = approver_id
        required_aliases.add((company_code, limit))
        patches.append(
            {
                "document_id": row.document_id,
                "fiscal_year": int(row.fiscal_year),
                "company_code": company_code,
                "document_amount": amount,
                "previous_approved_by": previous or None,
                "approved_by": approver_id,
                "approval_limit": limit,
                "excess_ratio": round((amount - limit) / limit, 6) if limit else None,
            }
        )
    return je, patches, required_aliases


def _write_journal_files(dataset_dir: Path, je: pd.DataFrame) -> None:
    je.to_csv(dataset_dir / "journal_entries.csv", index=False)
    for year in YEARS:
        year_df = je.loc[pd.to_numeric(je["fiscal_year"], errors="coerce").eq(year)].copy()
        year_df.to_csv(dataset_dir / f"journal_entries_{year}.csv", index=False)


def _refresh_generation_statistics(dataset_dir: Path, employee_count: int) -> None:
    path = dataset_dir / "generation_statistics.json"
    if not path.exists():
        return
    stats = json.loads(path.read_text(encoding="utf-8"))
    stats["employee_count"] = employee_count
    _write_json(path, stats)


def _validate(dataset_dir: Path) -> dict[str, Any]:
    employees = pd.DataFrame(_load_employee_rows(dataset_dir / "master_data" / "employees.json"))
    users = set(employees["user_id"].dropna().astype(str).str.strip())
    limits = pd.to_numeric(employees["approval_limit"], errors="coerce")
    limit_by_user = dict(zip(employees["user_id"].astype(str).str.strip(), limits))
    je = pd.read_csv(dataset_dir / "journal_entries.csv", low_memory=False)
    labels = pd.read_csv(dataset_dir / "labels" / "anomaly_labels.csv")

    result: dict[str, Any] = {}
    for column in ("created_by", "approved_by"):
        values = je[column].fillna("").astype(str).str.strip()
        nonblank = values.ne("")
        result[f"{column}_nonblank_rows"] = int(nonblank.sum())
        result[f"{column}_matched_rows"] = int(values.loc[nonblank].isin(users).sum())
        result[f"{column}_unmatched_distinct"] = sorted(set(values.loc[nonblank]) - users)

    doc = _document_summary(je)
    l104_docs = set(
        labels.loc[labels["anomaly_type"].eq(TARGET_ANOMALY), "document_id"]
        .dropna()
        .astype(str)
    )
    l104 = doc.loc[doc["document_id"].astype(str).isin(l104_docs)].copy()
    l104["approval_limit"] = l104["approved_by"].fillna("").astype(str).str.strip().map(limit_by_user)
    l104["resolved"] = l104["approval_limit"].notna()
    l104["exceeded"] = l104["document_amount"] > l104["approval_limit"]
    result["l104_docs"] = int(len(l104))
    result["l104_resolved_docs"] = int(l104["resolved"].sum())
    result["l104_exceeded_docs"] = int((l104["resolved"] & l104["exceeded"]).sum())
    result["l104_unresolved_docs"] = sorted(
        l104.loc[~l104["resolved"], "document_id"].astype(str).tolist()
    )
    return result


def repair_dataset(dataset_dir: Path) -> dict[str, Any]:
    employees_path = dataset_dir / "master_data" / "employees.json"
    labels_path = dataset_dir / "labels" / "anomaly_labels.csv"
    je_path = dataset_dir / "journal_entries.csv"
    if not (employees_path.exists() and labels_path.exists() and je_path.exists()):
        raise FileNotFoundError(f"Missing DataSynth files under {dataset_dir}")

    employees = pd.DataFrame(_load_employee_rows(employees_path))
    existing_user_ids = set(employees["user_id"].dropna().astype(str).str.strip())
    je = pd.read_csv(je_path, low_memory=False)
    labels = pd.read_csv(labels_path)

    doc_before = _document_summary(je)
    summary = _legacy_actor_summary(doc_before)
    alias_rows = []
    for row in summary.itertuples(index=False):
        legacy_id = _clean(row.legacy_id)
        if legacy_id and legacy_id not in existing_user_ids:
            alias = _legacy_alias_row(row, employees)
            alias_rows.append(alias)
            existing_user_ids.add(alias["user_id"])

    je, l104_patches, required_l104_aliases = _patch_l104_approvers(je, labels)
    l104_alias_rows = []
    for company_code, limit in sorted(required_l104_aliases):
        user_id = _approval_alias_id(company_code, limit)
        if user_id not in existing_user_ids:
            alias = _approval_alias_row(company_code, limit, employees)
            l104_alias_rows.append(alias)
            existing_user_ids.add(alias["user_id"])

    if alias_rows or l104_alias_rows:
        combined = pd.concat(
            [employees, pd.DataFrame(alias_rows + l104_alias_rows)],
            ignore_index=True,
        )
    else:
        combined = employees

    _write_json(employees_path, _records_for_json(combined))
    _write_journal_files(dataset_dir, je)
    _refresh_generation_statistics(dataset_dir, len(combined))

    validation = _validate(dataset_dir)
    report = {
        "dataset": str(dataset_dir.relative_to(ROOT)),
        "legacy_alias_count": len(alias_rows),
        "l104_alias_count": len(l104_alias_rows),
        "l104_patched_docs": len(l104_patches),
        "l104_patches": l104_patches,
        "validation": validation,
    }
    _write_json(dataset_dir / REPORT_NAME, report)
    return report


def main() -> None:
    reports = []
    for dataset_dir in DEFAULT_DATASETS:
        if dataset_dir.exists():
            reports.append(repair_dataset(dataset_dir))
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
