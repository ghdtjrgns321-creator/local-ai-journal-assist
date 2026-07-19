"""Refresh datasynth_manipulation with realistic manipulation scenario signals.

This patch updates only the physical manipulation split. It keeps the row set and
amounts stable, but aligns manipulated-entry truth with actual journal fields:
text leakage removal, SoD fields, timing/date patterns, account category patterns,
employee persona governance, and post-split metadata.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)

SCENARIO_TEXTS = {
    "embezzlement_concealment": [
        "선급금 정산",
        "가지급금 정리",
        "복리후생비 정산",
        "출장비 정산",
        "법인카드 사용분 정리",
        "임직원 대여금 정리",
    ],
    "approval_sod_bypass": [
        "긴급 결재 경로 변경",
        "위임 승인 처리",
        "마감 전표 승인 보완",
        "업무 담당자 결재 재지정",
    ],
    "period_end_adjustment_manipulation": [
        "결산 추정 조정",
        "월말 손익 조정",
        "충당금 재계산 반영",
        "이연수익 조정",
        "재고평가 조정",
    ],
    "circular_related_party_transaction": [
        "관계사 정산",
        "내부거래 대체",
        "관계사 매출매입 상계",
        "그룹사 비용 배부",
    ],
    "fictitious_entry": [
        "매출 정산 반영",
        "자산 취득 정산",
        "비용 발생분 반영",
        "수기 발생 전표",
        "거래처 정산 반영",
    ],
    "unusual_timing_manipulation": [
        "마감 전표 처리",
        "긴급 정산 반영",
        "승인 마감 전 보완",
        "휴일 업무 처리",
    ],
}

EMBEZZLEMENT_SUBTYPES = [
    "corporate_card_private_use",
    "long_outstanding_employee_advance",
    "employee_loan_recovery_delay",
    "false_travel_or_welfare_claim",
    "repeated_small_payment",
]
APPROVAL_SUBTYPES = [
    "self_approval_sod",
    "lower_authority_approval",
    "approval_limit_override",
    "emergency_route_bypass",
]
FICTITIOUS_SUBTYPES = [
    "fictitious_revenue",
    "fictitious_asset",
    "fictitious_expense",
]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def _clean_str(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _weekday_on_or_before(year: int, month: int, day: int) -> datetime:
    dt = datetime(year, month, day)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt


def _weekend_date(year: int, month: int, start_day: int) -> datetime:
    dt = datetime(year, month, start_day)
    for _ in range(14):
        if dt.weekday() >= 5:
            return dt
        dt += timedelta(days=1)
    return datetime(year, month, start_day)


def _scenario_datetime(year: int, scenario: str, idx: int) -> datetime:
    if scenario == "period_end_adjustment_manipulation":
        if idx % 10 < 5:
            day = 20 + (idx % 12)
            base = datetime(year, 12, min(day, 31))
        else:
            month = [3, 6, 9, 12][idx % 4]
            base = _weekday_on_or_before(year, month, 31 if month == 12 else 30)
        hour = [21, 22, 23, 18, 19, 20, 16, 17][idx % 8]
        return base.replace(hour=hour, minute=(13 + idx * 7) % 60, second=(idx * 11) % 60)
    if scenario == "unusual_timing_manipulation":
        month = [3, 6, 9, 12, 12, 12][idx % 6]
        if idx % 3 == 0:
            base = _weekend_date(year, month, 20)
        else:
            base = _weekday_on_or_before(year, month, 30 if month != 12 else 31)
        hour = [20, 21, 22, 23, 0, 1, 5][idx % 7]
        return base.replace(hour=hour, minute=(idx * 9 + 5) % 60, second=(idx * 13) % 60)
    if scenario == "approval_sod_bypass":
        month = [3, 6, 9, 12][idx % 4]
        base = _weekday_on_or_before(year, month, 30 if month != 12 else 31)
        return base.replace(hour=[16, 17, 18, 19][idx % 4], minute=(idx * 5 + 12) % 60, second=0)
    if scenario == "circular_related_party_transaction":
        month = [2, 5, 8, 11][idx % 4]
        base = datetime(year, month, 10 + (idx % 5))
        return base.replace(hour=[10, 11, 14, 15][idx % 4], minute=(idx * 4) % 60, second=0)
    if scenario == "embezzlement_concealment":
        month = [1, 2, 3, 6, 9, 12][idx % 6]
        base = _weekday_on_or_before(year, month, [25, 26, 27, 28, 29, 30][idx % 6])
        hour = [9, 10, 11, 15, 17, 21][idx % 6]
        return base.replace(hour=hour, minute=(idx * 3 + 7) % 60, second=0)
    # fictitious_entry
    month = [1, 3, 5, 6, 9, 10, 12][idx % 7]
    base = _weekday_on_or_before(year, month, [28, 29, 30, 15, 20, 25, 31][idx % 7])
    return base.replace(hour=[8, 9, 14, 16, 18, 21][idx % 6], minute=(idx * 7 + 3) % 60, second=0)


def _canonical_persona(row: pd.Series) -> str:
    job = _clean_str(row.get("job_level")).lower()
    persona = _clean_str(row.get("persona")).lower().replace(" ", "_")
    can_approve = _as_bool(row.get("can_approve_je"))
    try:
        limit = float(row.get("approval_limit") or 0)
    except (TypeError, ValueError):
        limit = 0.0
    if job == "system" or persona == "automated_system":
        return "automated_system"
    if can_approve:
        if limit >= 10_000_000_000 or job in {"director", "executive", "vice_president"}:
            return "controller"
        return "manager"
    if limit >= 100_000_000 or job == "senior":
        return "senior_accountant"
    return "junior_accountant"


def update_employees(base: Path) -> dict[str, dict[str, Any]]:
    path = base / "master_data" / "employees.json"
    raw = _read_json(path)
    employees = raw.get("employees") if isinstance(raw, dict) else raw
    if not isinstance(employees, list):
        raise ValueError(f"Unsupported employees format: {path}")

    for emp in employees:
        persona = _canonical_persona(pd.Series(emp))
        emp["persona"] = persona
        if persona == "automated_system":
            emp["job_level"] = "system"
            emp["job_title"] = "ERP System Actor"
            emp["can_approve_je"] = False
            emp["approval_limit"] = min(float(emp.get("approval_limit") or 100_000_000), 100_000_000)
        elif persona == "junior_accountant":
            emp["job_level"] = "staff"
            emp["job_title"] = "JE Preparer"
            emp["can_approve_je"] = False
            emp["approval_limit"] = min(float(emp.get("approval_limit") or 10_000_000), 10_000_000)
        elif persona == "senior_accountant":
            emp["job_level"] = "senior"
            emp["job_title"] = "JE Reviewer"
            emp["can_approve_je"] = False
            emp["approval_limit"] = min(max(float(emp.get("approval_limit") or 100_000_000), 100_000_000), 100_000_000)
        elif persona == "manager":
            emp["job_level"] = "manager"
            emp["job_title"] = "JE Approver"
            emp["can_approve_je"] = True
            emp["approval_limit"] = min(max(float(emp.get("approval_limit") or 1_000_000_000), 1_000_000_000), 5_000_000_000)
        elif persona == "controller":
            emp["job_level"] = "director"
            emp["job_title"] = "Controller"
            emp["can_approve_je"] = True
            emp["approval_limit"] = min(max(float(emp.get("approval_limit") or 10_000_000_000), 10_000_000_000), 50_000_000_000)

    _write_json(path, raw)
    return {str(emp["user_id"]): emp for emp in employees if "user_id" in emp}


def _safe_approvers(employee_by_user: dict[str, dict[str, Any]]) -> list[str]:
    users = [
        user
        for user, emp in employee_by_user.items()
        if _as_bool(emp.get("can_approve_je")) and emp.get("persona") in {"manager", "controller"}
    ]
    return sorted(users)


def _non_system_people(employee_by_user: dict[str, dict[str, Any]]) -> list[str]:
    return sorted([u for u, e in employee_by_user.items() if e.get("persona") != "automated_system"])


def _apply_doc_updates(
    df: pd.DataFrame,
    doc_id: str,
    truth_row: pd.Series,
    idx: int,
    employee_by_user: dict[str, dict[str, Any]],
    approvers: list[str],
    people: list[str],
) -> dict[str, Any]:
    mask = df["document_id"].astype(str).eq(doc_id)
    if not mask.any():
        return {}

    scenario = truth_row["manipulation_scenario"]
    year = int(truth_row["fiscal_year"])
    dt = _scenario_datetime(year, scenario, idx)
    subtype = ""
    text = SCENARIO_TEXTS[scenario][idx % len(SCENARIO_TEXTS[scenario])]
    ref = f"{truth_row['company_code']}-{year}-ADJ-{idx + 1:04d}"

    df.loc[mask, "posting_date"] = _format_dt(dt)
    df.loc[mask, "document_date"] = _format_date(dt - timedelta(days=0 if scenario != "cutoff_mismatch" else 6))
    df.loc[mask, "fiscal_period"] = dt.month
    if "has_attachment" in df.columns:
        df.loc[mask, "has_attachment"] = True
    if "supporting_doc_type" in df.columns:
        df.loc[mask, "supporting_doc_type"] = "JE_SUPPORT"
    df.loc[mask, "approval_date"] = _format_date(dt + timedelta(days=idx % 3))
    if "header_text" in df.columns:
        df.loc[mask, "header_text"] = text
    if "line_text" in df.columns:
        df.loc[mask, "line_text"] = text
    if "reference" in df.columns:
        df.loc[mask, "reference"] = ref
    if "sod_violation" in df.columns:
        df.loc[mask, "sod_violation"] = False
    if "sod_conflict_type" in df.columns:
        df.loc[mask, "sod_conflict_type"] = pd.NA

    created = _clean_str(df.loc[mask, "created_by"].iloc[0])
    approver = _clean_str(df.loc[mask, "approved_by"].iloc[0])
    if created not in employee_by_user or employee_by_user[created].get("persona") == "automated_system":
        created = people[idx % len(people)]
        df.loc[mask, "created_by"] = created
    if not approver or approver not in employee_by_user or not _as_bool(employee_by_user[approver].get("can_approve_je")):
        approver = approvers[idx % len(approvers)]
        df.loc[mask, "approved_by"] = approver

    if scenario == "embezzlement_concealment":
        subtype = EMBEZZLEMENT_SUBTYPES[idx % len(EMBEZZLEMENT_SUBTYPES)]
        df.loc[mask, "source"] = "manual"
        df.loc[mask, "business_process"] = "P2P"
        if "has_attachment" in df.columns:
            df.loc[mask, "has_attachment"] = idx % 10 < 3
        if idx % 5 in {0, 1}:
            df.loc[mask, "approved_by"] = created
            df.loc[mask, "sod_violation"] = True
            df.loc[mask, "sod_conflict_type"] = "preparer_approver"
        _set_doc_accounts(df, mask, debit_accounts=["1200", "6500", "6600", "6900"], credit_accounts=["1000", "2000"], idx=idx)
    elif scenario == "approval_sod_bypass":
        subtype = APPROVAL_SUBTYPES[idx % len(APPROVAL_SUBTYPES)]
        df.loc[mask, "source"] = "manual"
        df.loc[mask, "business_process"] = "R2R"
        df.loc[mask, "sod_violation"] = True
        if subtype == "self_approval_sod":
            df.loc[mask, "approved_by"] = created
            df.loc[mask, "sod_conflict_type"] = "preparer_approver"
        elif subtype == "lower_authority_approval":
            lower = people[(idx + 3) % len(people)]
            df.loc[mask, "approved_by"] = lower
            df.loc[mask, "sod_conflict_type"] = "unauthorized_approver"
        elif subtype == "approval_limit_override":
            df.loc[mask, "approved_by"] = approvers[idx % len(approvers)]
            df.loc[mask, "sod_conflict_type"] = "approval_limit_override"
        else:
            df.loc[mask, "approved_by"] = approvers[idx % len(approvers)]
            df.loc[mask, "sod_conflict_type"] = "emergency_route_bypass"
        df.loc[mask, "approval_date"] = _format_date(dt + timedelta(days=idx % 3))
    elif scenario == "period_end_adjustment_manipulation":
        subtype = "period_end_estimate_or_cutoff_adjustment"
        df.loc[mask, "source"] = "adjustment"
        df.loc[mask, "business_process"] = "A2R"
        df.loc[mask, "approval_date"] = _format_date(dt + timedelta(days=8 + (idx % 14) if idx % 10 < 4 else idx % 3))
        _set_doc_accounts(df, mask, debit_accounts=["1100", "1200", "1500", "5000", "6000"], credit_accounts=["2000", "2400", "4000", "4900"], idx=idx)
    elif scenario == "circular_related_party_transaction":
        subtype = "three_company_intercompany_cycle"
        cycle = [("C001", "V-000002"), ("C002", "V-000003"), ("C003", "V-000001")]
        company, partner = cycle[idx % 3]
        df.loc[mask, "company_code"] = company
        df.loc[mask, "trading_partner"] = partner
        df.loc[mask, "business_process"] = "O2C" if idx % 2 == 0 else "P2P"
        df.loc[mask, "source"] = "manual"
        _set_doc_accounts(df, mask, debit_accounts=["1150", "1100"], credit_accounts=["2050", "4500"], idx=idx)
    elif scenario == "fictitious_entry":
        subtype = FICTITIOUS_SUBTYPES[idx % len(FICTITIOUS_SUBTYPES)]
        df.loc[mask, "source"] = "adjustment"
        df.loc[mask, "business_process"] = "O2C" if subtype == "fictitious_revenue" else "A2R"
        if "has_attachment" in df.columns:
            df.loc[mask, "has_attachment"] = idx % 10 >= 6
        if subtype == "fictitious_revenue":
            _set_doc_accounts(df, mask, debit_accounts=["1100", "1160"], credit_accounts=["4000", "4010", "4900"], idx=idx)
        elif subtype == "fictitious_asset":
            _set_doc_accounts(df, mask, debit_accounts=["1500", "1510", "1200"], credit_accounts=["2000", "2100"], idx=idx)
        else:
            _set_doc_accounts(df, mask, debit_accounts=["6000", "6500", "6600"], credit_accounts=["2000", "2100"], idx=idx)
    elif scenario == "unusual_timing_manipulation":
        subtype = "off_hours_or_holiday_manual_posting"
        df.loc[mask, "source"] = "manual"
        df.loc[mask, "business_process"] = "R2R"
        df.loc[mask, "approval_date"] = _format_date(dt + timedelta(days=1 + idx % 4))

    # Normalize user persona from the final creator.
    final_created = _clean_str(df.loc[mask, "created_by"].iloc[0])
    persona = employee_by_user.get(final_created, {}).get("persona", "junior_accountant")
    df.loc[mask, "user_persona"] = persona

    return {
        "document_id": doc_id,
        "posting_date": _format_dt(dt),
        "document_date": _format_date(dt),
        "source": _clean_str(df.loc[mask, "source"].iloc[0]),
        "business_process": _clean_str(df.loc[mask, "business_process"].iloc[0]),
        "created_by": _clean_str(df.loc[mask, "created_by"].iloc[0]),
        "approved_by": _clean_str(df.loc[mask, "approved_by"].iloc[0]),
        "approval_date": _clean_str(df.loc[mask, "approval_date"].iloc[0]),
        "user_persona": persona,
        "company_code": _clean_str(df.loc[mask, "company_code"].iloc[0]),
        "document_number": _clean_str(df.loc[mask, "document_number"].iloc[0]),
        "document_type": _clean_str(df.loc[mask, "document_type"].iloc[0]),
        "manipulation_subtype": subtype,
        "line_count": int(mask.sum()),
    }


def _set_doc_accounts(df: pd.DataFrame, mask: pd.Series, debit_accounts: list[str], credit_accounts: list[str], idx: int) -> None:
    rows = df.loc[mask].sort_values("line_number" if "line_number" in df.columns else "document_id").index.tolist()
    d_i = c_i = 0
    for pos, row_idx in enumerate(rows):
        debit = float(df.at[row_idx, "debit_amount"] or 0) if "debit_amount" in df.columns and pd.notna(df.at[row_idx, "debit_amount"]) else 0.0
        credit = float(df.at[row_idx, "credit_amount"] or 0) if "credit_amount" in df.columns and pd.notna(df.at[row_idx, "credit_amount"]) else 0.0
        if debit >= credit:
            df.at[row_idx, "gl_account"] = debit_accounts[(idx + d_i) % len(debit_accounts)]
            d_i += 1
        else:
            df.at[row_idx, "gl_account"] = credit_accounts[(idx + c_i) % len(credit_accounts)]
            c_i += 1


def update_revenue_sidecars(df_by_year: dict[int, pd.DataFrame], labels_dir: Path) -> None:
    path = labels_dir / "revenue_manipulation_subtypes.csv"
    if not path.exists():
        return
    rev = pd.read_csv(path)
    if rev.empty:
        return
    for idx, row in rev.iterrows():
        year = int(row["fiscal_year"])
        df = df_by_year[year]
        mask = df["document_id"].astype(str).eq(str(row["document_id"]))
        if not mask.any():
            continue
        subtype = row["revenue_subtype"]
        dt = pd.to_datetime(df.loc[mask, "posting_date"].iloc[0], errors="coerce")
        if pd.isna(dt):
            dt = datetime(year, 12, 30, 16, 0, 0)
        dt = dt.to_pydatetime()
        if subtype in {"cutoff_mismatch", "period_end_push"}:
            dt = _weekday_on_or_before(year, 12, 31).replace(hour=18 + idx % 5, minute=(idx * 7) % 60, second=0)
            df.loc[mask, "posting_date"] = _format_dt(dt)
            df.loc[mask, "document_date"] = _format_date(dt - timedelta(days=6 + idx % 5))
            if "delivery_date" in df.columns:
                df.loc[mask, "delivery_date"] = _format_date(dt - timedelta(days=7 + idx % 6))
            df.loc[mask, "approval_date"] = _format_date(dt + timedelta(days=2 + idx % 5))
        if subtype == "manual_revenue_entry":
            df.loc[mask, "source"] = "manual"
            if "has_attachment" in df.columns:
                df.loc[mask, "has_attachment"] = idx % 3 == 0
        if subtype == "composite_low_amount_dispersion" and int(mask.sum()) > 40:
            # Leave rows intact, but mark the document as split/dispersed rather than a single huge composite.
            df.loc[mask, "header_text"] = "분산 매출 조정"
        _set_doc_accounts(df, mask, debit_accounts=["1100", "1160"], credit_accounts=["4000", "4010", "4900"], idx=idx)

    # Refresh sidecar snapshots from journal fields.
    refresh_cols = ["company_code", "document_number", "document_type", "posting_date", "business_process", "source", "created_by", "approved_by"]
    for idx, row in rev.iterrows():
        year = int(row["fiscal_year"])
        df = df_by_year[year]
        hit = df[df["document_id"].astype(str).eq(str(row["document_id"]))]
        if hit.empty:
            continue
        first = hit.iloc[0]
        for col in refresh_cols:
            if col in rev.columns and col in first.index:
                rev.at[idx, col] = first[col]
    write_label_family(labels_dir, rev, "revenue_manipulation_subtypes", "fiscal_year")


def write_label_family(labels_dir: Path, df: pd.DataFrame, stem: str, year_col: str = "fiscal_year") -> None:
    df.to_csv(labels_dir / f"{stem}.csv", index=False)
    _write_json_records(labels_dir / f"{stem}.json", df)
    if year_col in df.columns:
        for year, sub in df.groupby(year_col):
            year_int = int(year)
            sub.to_csv(labels_dir / f"{stem}_{year_int}.csv", index=False)
            _write_json_records(labels_dir / f"{stem}_{year_int}.json", sub)


def refresh_truth_labels(labels_dir: Path, updates: dict[str, dict[str, Any]]) -> pd.DataFrame:
    truth = pd.read_csv(labels_dir / "manipulated_entry_truth.csv")
    if "manipulation_subtype" not in truth.columns:
        truth["manipulation_subtype"] = ""
    for idx, row in truth.iterrows():
        doc_id = str(row["document_id"])
        upd = updates.get(doc_id)
        if not upd:
            continue
        for col in [
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "created_by",
            "approved_by",
            "approval_date",
            "user_persona",
            "line_count",
            "manipulation_subtype",
        ]:
            if col in upd:
                truth.at[idx, col] = upd[col]
        scenario = row["manipulation_scenario"]
        truth.at[idx, "reference_pattern"] = f"{scenario}:{upd.get('manipulation_subtype', 'mixed')}"
        truth.at[idx, "evaluation_note"] = "Evaluate whether L1-L4 signal combinations surface this manipulated entry; not rule-specific truth."
    write_label_family(labels_dir, truth, "manipulated_entry_truth", "fiscal_year")

    summary = truth.groupby(["fiscal_year", "manipulation_scenario"]).size().reset_index(name="document_count")
    summary.to_csv(labels_dir / "manipulated_entry_scenario_summary.csv", index=False)
    _write_json_records(labels_dir / "manipulated_entry_scenario_summary.json", summary)
    return truth


def refresh_anomaly_labels(labels_dir: Path, journal_docs: pd.DataFrame) -> None:
    path = labels_dir / "anomaly_labels.csv"
    if not path.exists():
        return
    labels = pd.read_csv(path)
    if labels.empty or "document_id" not in labels.columns:
        return
    docs = journal_docs.set_index("document_id")
    for idx, row in labels.iterrows():
        doc_id = str(row["document_id"])
        if doc_id not in docs.index:
            continue
        doc = docs.loc[doc_id]
        for col in ["fiscal_year", "company_code", "document_number", "document_type", "posting_date"]:
            if col in labels.columns and col in doc.index:
                labels.at[idx, col] = doc[col]
    write_label_family(labels_dir, labels, "anomaly_labels", "fiscal_year")
    summary_cols = ["fiscal_year", "anomaly_type"]
    if all(c in labels.columns for c in summary_cols):
        summary = labels.groupby(summary_cols).size().reset_index(name="document_count")
        _write_json(labels_dir / "anomaly_labels_summary.json", summary.to_dict(orient="records"))


def refresh_metadata(base: Path, journal: pd.DataFrame, labels_dir: Path, checks: dict[str, Any]) -> None:
    doc_count = int(journal["document_id"].nunique())
    row_count = int(len(journal))
    label_union: set[str] = set()
    for pattern in ["anomaly_labels.csv", "manipulated_entry_truth.csv", "revenue_manipulation_subtypes.csv"]:
        p = labels_dir / pattern
        if p.exists():
            df = pd.read_csv(p, usecols=["document_id"])
            label_union.update(df["document_id"].dropna().astype(str))
    metadata = {
        "status": "pass" if not checks.get("failures") else "fail",
        "version": "v127_manipulation_realism",
        "dataset_role": "manipulation",
        "total_entries": doc_count,
        "total_line_items": row_count,
        "manipulation_truth_documents": int(len(label_union)),
        "scenario_truth_documents": int(pd.read_csv(labels_dir / "manipulated_entry_truth.csv")["document_id"].nunique()),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
    }
    _write_json(base / "validated_metadata.json", metadata)
    stats_path = base / "generation_statistics.json"
    stats = _read_json(stats_path) if stats_path.exists() else {}
    stats.update(
        {
            "total_entries": doc_count,
            "total_line_items": row_count,
            "anomalies_injected": int(len(label_union)),
            "manipulated_entry_truth_count": int(pd.read_csv(labels_dir / "manipulated_entry_truth.csv")["document_id"].nunique()),
            "metadata_refreshed_by": "build_datasynth_v127_manipulation_realism.py",
        }
    )
    _write_json(stats_path, stats)


def validate(base: Path, truth: pd.DataFrame, journal: pd.DataFrame, employee_by_user: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    truth_ids = set(truth["document_id"].astype(str))
    journal_ids = set(journal["document_id"].astype(str))
    missing = sorted(truth_ids - journal_ids)
    if missing:
        failures.append(f"truth documents missing from journal: {len(missing)}")

    grouped = journal[journal["document_id"].astype(str).isin(truth_ids)].groupby("document_id")
    balance = grouped[["debit_amount", "credit_amount"]].sum(numeric_only=True)
    unbalanced = balance[(balance["debit_amount"] - balance["credit_amount"]).abs() > 1]
    if not unbalanced.empty:
        failures.append(f"unbalanced manipulated documents: {len(unbalanced)}")

    text_cols = [c for c in ["line_text", "header_text", "reference"] if c in journal.columns]
    text = journal[journal["document_id"].astype(str).isin(truth_ids)][text_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    leakage_tokens = ["advance settlement clearing", "fss fictitious", "recognize non-existent", "manipulation_scenario"]
    leakage = {tok: int(text.str.contains(tok, regex=False).sum()) for tok in leakage_tokens}
    if any(leakage.values()):
        failures.append(f"label leakage tokens remain: {leakage}")

    docs = journal[journal["document_id"].astype(str).isin(truth_ids)].sort_values("line_number").drop_duplicates("document_id")
    docs = docs.merge(truth[["document_id", "manipulation_scenario"]], on="document_id", how="left")
    docs["posting_dt"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["hour"] = docs["posting_dt"].dt.hour
    docs["night"] = docs["hour"].ge(20) | docs["hour"].lt(6)
    docs["weekend"] = docs["posting_dt"].dt.dayofweek.ge(5)
    docs["dec20_31"] = docs["posting_dt"].dt.month.eq(12) & docs["posting_dt"].dt.day.between(20, 31)
    docs["quarter_month"] = docs["posting_dt"].dt.month.isin([3, 6, 9, 12])
    metrics = {}
    for scenario, g in docs.groupby("manipulation_scenario"):
        metrics[scenario] = {
            "documents": int(len(g)),
            "night_20_06_pct": round(float(g["night"].mean() * 100), 2),
            "weekend_pct": round(float(g["weekend"].mean() * 100), 2),
            "dec20_31_pct": round(float(g["dec20_31"].mean() * 100), 2),
            "quarter_month_pct": round(float(g["quarter_month"].mean() * 100), 2),
            "sod_true_pct": round(float(g["sod_violation"].fillna(False).astype(str).str.lower().isin(["true", "1"]).mean() * 100), 2),
            "attachment_missing_pct": round(float((~g["has_attachment"].fillna(False).astype(str).str.lower().isin(["true", "1"])).mean() * 100), 2) if "has_attachment" in g.columns else None,
        }
    if metrics.get("unusual_timing_manipulation", {}).get("night_20_06_pct", 0) < 60:
        failures.append("unusual_timing_manipulation night share below 60%")
    if metrics.get("period_end_adjustment_manipulation", {}).get("dec20_31_pct", 0) < 35:
        failures.append("period_end_adjustment_manipulation Dec20-31 share below 35%")
    if metrics.get("approval_sod_bypass", {}).get("sod_true_pct", 0) < 90:
        failures.append("approval_sod_bypass sod_violation share below 90%")

    persona_mismatch = 0
    for _, row in docs.iterrows():
        emp = employee_by_user.get(_clean_str(row.get("created_by")))
        if emp and row.get("user_persona") != emp.get("persona"):
            persona_mismatch += 1
    if persona_mismatch:
        failures.append(f"created_by master persona mismatch: {persona_mismatch}")

    return {"failures": failures, "scenario_metrics": metrics, "leakage": leakage}


def write_preview(base: Path, checks: dict[str, Any], journal: pd.DataFrame, truth: pd.DataFrame) -> None:
    lines = [
        "# DataSynth Manipulation v127",
        "",
        "This split contains normal journal rows plus actual manipulation scenario truth only.",
        "",
        f"- Rows: {len(journal):,}",
        f"- Documents: {journal['document_id'].nunique():,}",
        f"- Manipulated-entry truth documents: {truth['document_id'].nunique():,}",
        f"- Validation status: {'pass' if not checks.get('failures') else 'fail'}",
        "",
        "## Scenario Metrics",
        "",
        "| Scenario | Docs | Night 20-06 | Weekend | Dec 20-31 | Quarter Months | SoD True | Missing Attachment |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, m in checks["scenario_metrics"].items():
        lines.append(
            f"| {scenario} | {m['documents']} | {m['night_20_06_pct']}% | {m['weekend_pct']}% | "
            f"{m['dec20_31_pct']}% | {m['quarter_month_pct']}% | {m['sod_true_pct']}% | {m['attachment_missing_pct']}% |"
        )
    if checks.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in checks["failures"])
    (base / "PREVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    base = args.data_dir
    labels_dir = base / "labels"

    employee_by_user = update_employees(base)
    approvers = _safe_approvers(employee_by_user)
    people = _non_system_people(employee_by_user)
    if not approvers or not people:
        raise RuntimeError("Employee master does not contain enough approvers/non-system users")

    truth = pd.read_csv(labels_dir / "manipulated_entry_truth.csv")
    scenario_counter: dict[str, int] = defaultdict(int)
    updates: dict[str, dict[str, Any]] = {}
    df_by_year: dict[int, pd.DataFrame] = {}

    for year in YEARS:
        df = pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False)
        df["gl_account"] = df["gl_account"].astype("object")
        # Normalize all personas from created_by so train/test features do not carry mixed spellings.
        df["user_persona"] = df["created_by"].map(lambda u: employee_by_user.get(_clean_str(u), {}).get("persona", "junior_accountant"))
        year_truth = truth[truth["fiscal_year"].astype(int).eq(year)].copy()
        for _, row in year_truth.iterrows():
            scenario = row["manipulation_scenario"]
            idx = scenario_counter[scenario]
            scenario_counter[scenario] += 1
            upd = _apply_doc_updates(df, str(row["document_id"]), row, idx, employee_by_user, approvers, people)
            if upd:
                updates[str(row["document_id"])] = upd
        df_by_year[year] = df

    update_revenue_sidecars(df_by_year, labels_dir)

    combined = pd.concat([df_by_year[y] for y in YEARS], ignore_index=True)
    for year, df in df_by_year.items():
        df.to_csv(base / f"journal_entries_{year}.csv", index=False)
        _write_json_records(base / f"journal_entries_{year}.json", df)
    combined.to_csv(base / "journal_entries.csv", index=False)
    _write_json_records(base / "journal_entries.json", combined)

    truth = refresh_truth_labels(labels_dir, updates)
    doc_snapshot = combined.sort_values("line_number").drop_duplicates("document_id")
    refresh_anomaly_labels(labels_dir, doc_snapshot)

    checks = validate(base, truth, combined, employee_by_user)
    refresh_metadata(base, combined, labels_dir, checks)
    write_preview(base, checks, combined, truth)

    manifest = {
        "version": "v127_manipulation_realism",
        "base_version": "v126_production_manipulation_split",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
        "notes": [
            "Removed direct label leakage strings from journal text/reference fields.",
            "Aligned employee persona/job_level/approval_limit/can_approve_je governance inside manipulation split.",
            "Updated scenario timing, SoD, account, attachment, and revenue subtype fields in journal and labels.",
            "Refreshed CSV and JSON journal/label families plus metadata.",
        ],
    }
    _write_json(base / "V127_MANIPULATION_REALISM_PATCH.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
