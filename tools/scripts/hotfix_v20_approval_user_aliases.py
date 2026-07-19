from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
HOTFIX_TS = "2026-04-21T01:10:00+09:00"


def main() -> None:
    emp_path = DATA_DIR / "master_data" / "employees.json"
    employees = json.loads(emp_path.read_text(encoding="utf-8"))
    if isinstance(employees, dict):
        for value in employees.values():
            if isinstance(value, list):
                employees = value
                break

    emp_df = pd.DataFrame(employees)
    legacy_summary = build_legacy_summary()
    existing_user_ids = set(emp_df["user_id"].dropna().astype(str))
    alias_rows = []

    for row in legacy_summary.itertuples(index=False):
        legacy_id = row.legacy_id
        if legacy_id in existing_user_ids:
            continue
        if row.user_persona == "automated_system" or legacy_id in {"SYSTEM", "IC_GENERATOR"}:
            alias = build_system_alias(row, emp_df)
        else:
            alias = build_human_alias(row, emp_df)
        alias_rows.append(alias)

    if alias_rows:
        employees.extend(alias_rows)
        emp_path.write_text(json.dumps(employees, ensure_ascii=False, indent=2), encoding="utf-8")

    refresh_generation_statistics(len(employees))
    write_hotfix_report(alias_rows, legacy_summary)


def build_legacy_summary() -> pd.DataFrame:
    je = pd.read_csv(
        DATA_DIR / "journal_entries.csv",
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
    creator_summary = (
        doc_meta[doc_meta["created_by"].notna()]
        .groupby("created_by")
        .agg(
            company_code=("company_code", lambda s: s.value_counts().index[0]),
            user_persona=("user_persona", lambda s: s.value_counts().index[0]),
            created_docs=("document_id", "count"),
            max_created_amt=("doc_line_amt", "max"),
        )
        .reset_index()
        .rename(columns={"created_by": "legacy_id"})
    )
    approver_summary = (
        doc_meta[doc_meta["approved_by"].notna()]
        .groupby("approved_by")
        .agg(
            approved_docs=("document_id", "count"),
            max_approved_amt=("doc_line_amt", "max"),
        )
        .reset_index()
        .rename(columns={"approved_by": "legacy_id"})
    )
    return creator_summary.merge(approver_summary, on="legacy_id", how="left").fillna(
        {"approved_docs": 0, "max_approved_amt": 0}
    )


def build_human_alias(row, emp_df: pd.DataFrame) -> dict:
    candidates = emp_df[
        (emp_df["company_code"] == row.company_code)
        & (emp_df["persona"] == row.user_persona)
    ].copy()
    if candidates.empty:
        candidates = emp_df[emp_df["company_code"] == row.company_code].copy()
    if candidates.empty:
        raise RuntimeError(f"No employee template found for {row.legacy_id}")

    if row.approved_docs > 0:
        approver_candidates = candidates[candidates["can_approve_je"] == True].copy()  # noqa: E712
        if approver_candidates.empty:
            approver_candidates = emp_df[
                (emp_df["company_code"] == row.company_code) & (emp_df["can_approve_je"] == True)  # noqa: E712
            ].copy()
        if not approver_candidates.empty:
            approver_candidates["approval_limit_num"] = pd.to_numeric(
                approver_candidates["approval_limit"], errors="coerce"
            ).fillna(0)
            approver_candidates.sort_values(
                ["approval_limit_num", "user_id"], ascending=[False, True], inplace=True
            )
            candidates = approver_candidates

    template = deepcopy(candidates.iloc[0].to_dict())
    template["employee_id"] = f"EMP-ALIAS-{row.company_code}-{row.legacy_id}"
    template["user_id"] = row.legacy_id
    template["display_name"] = f"Legacy Alias {row.legacy_id}"
    template["email"] = f"{row.legacy_id.lower()}@legacy.company.com"
    template["first_name"] = row.legacy_id.split("0")[0][:3] or "Legacy"
    template["last_name"] = row.legacy_id
    template["company_code"] = row.company_code
    template["status"] = "active"

    if row.approved_docs > 0:
        approval_target = max(
            int(float(row.max_approved_amt)),
            int(float(row.max_created_amt)),
            int(pd.to_numeric(template.get("approval_limit", 0), errors="coerce") or 0),
        )
        template["can_approve_je"] = True
        template["can_approve_pr"] = True
        template["can_approve_po"] = True
        template["approval_limit"] = str(approval_target)

    return template


def build_system_alias(row, emp_df: pd.DataFrame) -> dict:
    company_candidates = emp_df[emp_df["company_code"] == row.company_code].copy()
    if company_candidates.empty:
        raise RuntimeError(f"No company template found for system alias {row.legacy_id}")
    template = deepcopy(company_candidates.iloc[0].to_dict())
    template["employee_id"] = f"EMP-ALIAS-{row.company_code}-{row.legacy_id}"
    template["user_id"] = row.legacy_id
    template["display_name"] = f"Legacy System {row.legacy_id}"
    template["first_name"] = "Legacy"
    template["last_name"] = row.legacy_id
    template["email"] = f"{row.legacy_id.lower()}@system.company.com"
    template["persona"] = "automated_system"
    template["job_level"] = "system"
    template["job_title"] = "System User"
    template["department_id"] = "System"
    template["cost_center"] = None
    template["manager_id"] = None
    template["direct_reports"] = []
    template["authorized_company_codes"] = [row.company_code]
    template["authorized_cost_centers"] = []
    template["approval_limit"] = str(max(int(float(row.max_created_amt)), 999_999_999_999))
    template["can_approve_pr"] = False
    template["can_approve_po"] = False
    template["can_approve_invoice"] = False
    template["can_approve_je"] = False
    template["can_release_payment"] = False
    template["system_roles"] = ["system"]
    template["transaction_codes"] = []
    template["is_shared_services"] = False
    template["location"] = None
    template["phone"] = None
    template["status"] = "active"
    template["company_code"] = row.company_code
    return template


def refresh_generation_statistics(employee_count: int) -> None:
    stats_path = DATA_DIR / "generation_statistics.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["employee_count"] = employee_count
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def write_hotfix_report(alias_rows: list[dict], legacy_summary: pd.DataFrame) -> None:
    report = {
        "hotfixed_at": HOTFIX_TS,
        "alias_count": len(alias_rows),
        "legacy_users_total": int(len(legacy_summary)),
        "legacy_approvers_total": int((legacy_summary["approved_docs"] > 0).sum()),
        "aliases": [
            {
                "legacy_id": row["user_id"],
                "employee_id": row["employee_id"],
                "company_code": row["company_code"],
                "persona": row["persona"],
                "can_approve_je": row["can_approve_je"],
                "approval_limit": row["approval_limit"],
            }
            for row in alias_rows
        ],
    }
    (DATA_DIR / "V20_2_APPROVAL_USER_ALIAS_HOTFIX.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
