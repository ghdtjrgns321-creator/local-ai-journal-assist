from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HOTFIX_TS = "2026-04-21T01:40:00+09:00"

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


def main() -> None:
    for rel in [
        Path("data/journal/primary/datasynth"),
        Path("data/journal/primary/datasynth_v20"),
    ]:
        rebuild_dataset(ROOT / rel)


def rebuild_dataset(base_dir: Path) -> None:
    employees_path = base_dir / "master_data" / "employees.json"
    employees = load_employee_list(employees_path)
    employees_df = pd.DataFrame(employees)
    employees_df = employees_df[
        ~employees_df["employee_id"].astype(str).str.startswith("EMP-ALIAS-")
    ].copy()

    summary = build_legacy_summary(base_dir / "journal_entries.csv")
    alias_rows = [
        build_legacy_user_row(row)
        for row in summary.itertuples(index=False)
    ]

    combined = pd.concat([employees_df, pd.DataFrame(alias_rows)], ignore_index=True)
    employees_path.write_text(
        json.dumps(combined.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    refresh_generation_statistics(base_dir, len(combined))
    write_report(base_dir, alias_rows, summary)


def load_employee_list(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
        raise RuntimeError(f"No employee list found in {path}")
    return payload


def build_legacy_summary(je_path: Path) -> pd.DataFrame:
    je = pd.read_csv(
        je_path,
        usecols=[
            "document_id",
            "company_code",
            "created_by",
            "approved_by",
            "user_persona",
            "debit_amount",
            "credit_amount",
        ],
        low_memory=False,
    )
    je["doc_line_amt"] = (
        pd.to_numeric(je["debit_amount"], errors="coerce").fillna(0).abs()
        + pd.to_numeric(je["credit_amount"], errors="coerce").fillna(0).abs()
    )
    doc_meta = (
        je.groupby("document_id")
        .agg(
            {
                "company_code": "first",
                "created_by": "first",
                "approved_by": "first",
                "user_persona": "first",
                "doc_line_amt": "sum",
            }
        )
        .reset_index()
    )
    creator = (
        doc_meta[doc_meta["created_by"].notna()]
        .groupby("created_by")
        .agg(
            company_code=("company_code", lambda s: s.value_counts().index[0]),
            persona=("user_persona", lambda s: s.value_counts().index[0]),
            created_docs=("document_id", "count"),
            max_created_amt=("doc_line_amt", "max"),
        )
        .reset_index()
        .rename(columns={"created_by": "legacy_id"})
    )
    approver = (
        doc_meta[doc_meta["approved_by"].notna()]
        .groupby("approved_by")
        .agg(
            approved_docs=("document_id", "count"),
            max_approved_amt=("doc_line_amt", "max"),
        )
        .reset_index()
        .rename(columns={"approved_by": "legacy_id"})
    )
    return creator.merge(approver, on="legacy_id", how="left").fillna(
        {"approved_docs": 0, "max_approved_amt": 0}
    )


def build_legacy_user_row(row) -> dict:
    persona = str(row.persona)
    job_level, job_title = PERSONA_JOB.get(persona, ("staff", "Staff Accountant"))
    can_approve = bool(row.approved_docs > 0)
    base_limit = PERSONA_LIMIT.get(persona, 10_000_000)
    if can_approve:
        base_limit = max(base_limit, int(float(row.max_approved_amt)))
    else:
        base_limit = max(base_limit, int(float(row.max_created_amt)))

    is_system = persona == "automated_system" or row.legacy_id in {"SYSTEM", "IC_GENERATOR"}
    return {
        "employee_id": f"EMP-ALIAS-{row.company_code}-{row.legacy_id}",
        "user_id": row.legacy_id,
        "display_name": f"Legacy JE User {row.legacy_id}",
        "first_name": "Legacy",
        "last_name": row.legacy_id,
        "email": f"{str(row.legacy_id).lower()}@legacy.company.com",
        "persona": persona,
        "job_level": job_level,
        "job_title": job_title,
        "department_id": "System" if is_system else "Finance",
        "cost_center": None,
        "manager_id": None,
        "direct_reports": [],
        "status": "active",
        "company_code": row.company_code,
        "working_hours": {
            "start_hour": 8,
            "end_hour": 18,
            "peak_hours": [10, 11, 14, 15],
            "weekend_probability": 0.05 if not is_system else 0.0,
            "after_hours_probability": 0.10 if not is_system else 0.50,
        },
        "authorized_company_codes": [row.company_code],
        "authorized_cost_centers": [],
        "approval_limit": str(base_limit),
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


def refresh_generation_statistics(base_dir: Path, employee_count: int) -> None:
    stats_path = base_dir / "generation_statistics.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["employee_count"] = employee_count
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(base_dir: Path, alias_rows: list[dict], summary: pd.DataFrame) -> None:
    report = {
        "hotfixed_at": HOTFIX_TS,
        "alias_count": len(alias_rows),
        "legacy_users_total": int(len(summary)),
        "legacy_approvers_total": int((summary["approved_docs"] > 0).sum()),
        "aliases": [
            {
                "legacy_id": row["user_id"],
                "company_code": row["company_code"],
                "persona": row["persona"],
                "can_approve_je": row["can_approve_je"],
                "approval_limit": row["approval_limit"],
            }
            for row in alias_rows
        ],
    }
    (base_dir / "V20_2_APPROVAL_USER_ALIAS_HOTFIX.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
