"""Add v128 manipulation refinements on top of v127.

Scope:
- strengthen circular related-party manipulation as verifiable IC cycles
- mark shared related-party vendor/customer masters as intercompany
- add IC sidecar entries linked to manipulated circular documents
- add weak SoD/self-approval and over-limit signals to selected manipulation scenarios
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")
YEARS = (2022, 2023, 2024)

RP_MAP = {
    "C001": {"partner_company": "C002", "vendor_id": "V-000002", "customer_id": "C-000002"},
    "C002": {"partner_company": "C003", "vendor_id": "V-000003", "customer_id": "C-000003"},
    "C003": {"partner_company": "C001", "vendor_id": "V-000001", "customer_id": "C-000001"},
}
RP_VENDOR_TO_COMPANY = {"V-000001": "C001", "V-000002": "C002", "V-000003": "C003"}
RP_CUSTOMER_TO_COMPANY = {"C-000001": "C001", "C-000002": "C002", "C-000003": "C003"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _employee_maps(base: Path) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    raw = _read_json(base / "master_data" / "employees.json")
    employees = raw.get("employees") if isinstance(raw, dict) else raw
    by_user = {str(e["user_id"]): e for e in employees}
    approvers = sorted([u for u, e in by_user.items() if _as_bool(e.get("can_approve_je"))])
    weak = sorted([u for u, e in by_user.items() if e.get("persona") in {"junior_accountant", "senior_accountant"}])
    return by_user, approvers, weak


def update_master_parties(base: Path) -> None:
    vendors_path = base / "master_data" / "vendors.json"
    vendors = _read_json(vendors_path)
    for vendor in vendors:
        vid = str(vendor.get("vendor_id"))
        if vid in RP_VENDOR_TO_COMPANY:
            company = RP_VENDOR_TO_COMPANY[vid]
            vendor["is_intercompany"] = True
            vendor["intercompany_code"] = company
            vendor["vendor_type"] = "intercompany"
            vendor["name"] = f"{company} 관계사 매입처"
            vendor["reconciliation_account"] = vendor.get("reconciliation_account") or "2050"
            vendor["payment_terms"] = "net30"
            vendor["payment_terms_days"] = 30
            vendor["currency"] = "KRW"
    _write_json(vendors_path, vendors)

    customers_path = base / "master_data" / "customers.json"
    customers = _read_json(customers_path)
    for customer in customers:
        cid = str(customer.get("customer_id"))
        if cid in RP_CUSTOMER_TO_COMPANY:
            company = RP_CUSTOMER_TO_COMPANY[cid]
            customer["is_intercompany"] = True
            customer["intercompany_code"] = company
            customer["customer_type"] = "intercompany"
            customer["name"] = f"{company} 관계사 매출처"
            customer["reconciliation_account"] = customer.get("reconciliation_account") or "1150"
            customer["payment_terms"] = "net30"
            customer["payment_terms_days"] = 30
            customer["currency"] = "KRW"
    _write_json(customers_path, customers)


def _set_amount_pair(df: pd.DataFrame, mask: pd.Series, amount: float, debit_accounts: list[str], credit_accounts: list[str], idx: int) -> None:
    rows = df.loc[mask].sort_values("line_number").index.tolist()
    if not rows:
        return
    debit_rows = [r for r in rows if float(df.at[r, "debit_amount"] or 0) >= float(df.at[r, "credit_amount"] or 0)]
    credit_rows = [r for r in rows if r not in debit_rows]
    if not debit_rows or not credit_rows:
        half = max(1, len(rows) // 2)
        debit_rows = rows[:half]
        credit_rows = rows[half:] or rows[:1]
    debit_share = round(amount / len(debit_rows), 2)
    credit_share = round(amount / len(credit_rows), 2)
    for i, r in enumerate(debit_rows):
        df.at[r, "debit_amount"] = debit_share
        df.at[r, "credit_amount"] = 0.0
        df.at[r, "local_amount"] = debit_share
        df.at[r, "gl_account"] = debit_accounts[(idx + i) % len(debit_accounts)]
    for i, r in enumerate(credit_rows):
        df.at[r, "debit_amount"] = 0.0
        df.at[r, "credit_amount"] = credit_share
        df.at[r, "local_amount"] = -credit_share
        df.at[r, "gl_account"] = credit_accounts[(idx + i) % len(credit_accounts)]


def _update_doc_common(df: pd.DataFrame, mask: pd.Series, dt: datetime, ref: str, text: str) -> None:
    df.loc[mask, "posting_date"] = _fmt_dt(dt)
    df.loc[mask, "document_date"] = _fmt_date(dt)
    df.loc[mask, "fiscal_period"] = dt.month
    df.loc[mask, "reference"] = ref
    df.loc[mask, "header_text"] = text
    df.loc[mask, "line_text"] = text
    df.loc[mask, "source"] = "manual"
    df.loc[mask, "approval_date"] = _fmt_date(dt + timedelta(days=1))
    if "has_attachment" in df.columns:
        df.loc[mask, "has_attachment"] = True


def strengthen_circular(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].copy()
    circ = circ.sort_values(["fiscal_year", "document_id"]).reset_index(drop=True)
    if circ.empty:
        return truth

    updates: dict[str, dict[str, Any]] = {}
    for year, gy in circ.groupby("fiscal_year"):
        df = df_by_year[int(year)]
        docs = gy["document_id"].astype(str).tolist()
        for group_idx in range(0, len(docs), 3):
            trio = docs[group_idx : group_idx + 3]
            base_amount = float(7_500_000 + int(year) % 100 * 100_000 + group_idx * 350_000)
            base_dt = datetime(int(year), [2, 5, 8, 11][(group_idx // 3) % 4], 10 + (group_idx // 3) % 5, 10, 0, 0)
            cycle = [("C001", "O2C"), ("C002", "P2P"), ("C003", "O2C")]
            for offset, doc_id in enumerate(trio):
                company, process = cycle[offset]
                partner_company = RP_MAP[company]["partner_company"]
                partner = RP_MAP[company]["customer_id"] if process == "O2C" else RP_MAP[company]["vendor_id"]
                amount = round(base_amount * (1 + [0.0, 0.012, -0.008][offset]), 2)
                dt = base_dt + timedelta(days=offset * 2)
                ref = f"IC-CYCLE-{int(year)}-{group_idx // 3 + 1:03d}"
                text = f"관계사 순환 정산 {company}-{partner_company}"
                mask = df["document_id"].astype(str).eq(doc_id)
                if not mask.any():
                    continue
                _update_doc_common(df, mask, dt, ref, text)
                df.loc[mask, "company_code"] = company
                df.loc[mask, "business_process"] = process
                df.loc[mask, "trading_partner"] = partner
                if process == "O2C":
                    _set_amount_pair(df, mask, amount, ["1150", "1100"], ["4500", "4000"], offset)
                else:
                    _set_amount_pair(df, mask, amount, ["5000", "1150"], ["2050", "2000"], offset)
                updates[doc_id] = {
                    "company_code": company,
                    "business_process": process,
                    "posting_date": _fmt_dt(dt),
                    "reference_pattern": "circular_related_party_transaction:shared_rp_three_company_cycle",
                    "manipulation_subtype": "shared_rp_three_company_cycle",
                }
    for doc_id, upd in updates.items():
        mask = truth["document_id"].astype(str).eq(doc_id)
        for k, v in upd.items():
            if k in truth.columns:
                truth.loc[mask, k] = v
    return truth


def add_weak_signals(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    by_user, approvers, weak_users = _employee_maps(base)
    for scenario, share in [("fictitious_entry", 0.15), ("embezzlement_concealment", 0.08)]:
        rows = truth[truth["manipulation_scenario"].eq(scenario)].sort_values(["fiscal_year", "document_id"])
        target_count = max(1, int(round(len(rows) * share)))
        selected = rows.head(target_count)
        for i, row in enumerate(selected.itertuples(index=False)):
            year = int(row.fiscal_year)
            df = df_by_year[year]
            mask = df["document_id"].astype(str).eq(str(row.document_id))
            if not mask.any():
                continue
            created = str(df.loc[mask, "created_by"].iloc[0])
            if scenario == "fictitious_entry":
                if i % 2 == 0:
                    df.loc[mask, "approved_by"] = created
                    df.loc[mask, "sod_violation"] = True
                    df.loc[mask, "sod_conflict_type"] = "preparer_approver"
                    truth.loc[truth["document_id"].astype(str).eq(str(row.document_id)), "reference_pattern"] = "fictitious_entry:weak_self_approval_signal"
                else:
                    weak = weak_users[i % len(weak_users)]
                    df.loc[mask, "approved_by"] = weak
                    df.loc[mask, "sod_violation"] = True
                    df.loc[mask, "sod_conflict_type"] = "unauthorized_approver"
                    truth.loc[truth["document_id"].astype(str).eq(str(row.document_id)), "reference_pattern"] = "fictitious_entry:weak_unauthorized_approval_signal"
            else:
                # over-limit embezzlement: keep balanced lines but push amount slightly above selected approver limit.
                approver = approvers[i % len(approvers)]
                limit = float(by_user[approver].get("approval_limit") or 100_000_000)
                amount = round(limit * (1.03 + (i % 3) * 0.01), 2)
                df.loc[mask, "approved_by"] = approver
                _set_amount_pair(df, mask, amount, ["1200", "6500", "6600"], ["1000", "2000"], i)
                truth.loc[truth["document_id"].astype(str).eq(str(row.document_id)), "reference_pattern"] = "embezzlement_concealment:over_limit_weak_signal"
    return truth


def refresh_truth_family(labels_dir: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    docs = []
    for df in df_by_year.values():
        docs.append(df.sort_values("line_number").drop_duplicates("document_id"))
    doc = pd.concat(docs, ignore_index=True).set_index("document_id")
    for idx, row in truth.iterrows():
        doc_id = str(row["document_id"])
        if doc_id not in doc.index:
            continue
        src = doc.loc[doc_id]
        for col in ["company_code", "document_number", "document_type", "posting_date", "business_process", "source", "created_by", "approved_by", "approval_date", "user_persona"]:
            if col in truth.columns and col in src.index:
                truth.at[idx, col] = src[col]
        mask_year = df_by_year[int(row["fiscal_year"])]["document_id"].astype(str).eq(doc_id)
        truth.at[idx, "line_count"] = int(mask_year.sum())
        truth.at[idx, "line_amount"] = float(df_by_year[int(row["fiscal_year"])].loc[mask_year, "debit_amount"].sum())

    write_label_family(labels_dir, truth, "manipulated_entry_truth")
    summary = truth.groupby(["fiscal_year", "manipulation_scenario"]).size().reset_index(name="document_count")
    summary.to_csv(labels_dir / "manipulated_entry_scenario_summary.csv", index=False)
    _write_json_records(labels_dir / "manipulated_entry_scenario_summary.json", summary)
    return truth


def write_label_family(labels_dir: Path, df: pd.DataFrame, stem: str) -> None:
    df.to_csv(labels_dir / f"{stem}.csv", index=False)
    _write_json_records(labels_dir / f"{stem}.json", df)
    for year, sub in df.groupby("fiscal_year"):
        year = int(year)
        sub.to_csv(labels_dir / f"{stem}_{year}.csv", index=False)
        _write_json_records(labels_dir / f"{stem}_{year}.json", sub)


def refresh_intercompany_sidecars(base: Path, truth: pd.DataFrame, df_by_year: dict[int, pd.DataFrame]) -> None:
    inter_dir = base / "intercompany"
    pairs = _read_json(inter_dir / "ic_matched_pairs.json")
    sellers = _read_json(inter_dir / "ic_seller_journal_entries.json")
    buyers = _read_json(inter_dir / "ic_buyer_journal_entries.json")
    pairs = [p for p in pairs if not str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    sellers = [x for x in sellers if not str(x.get("header", {}).get("reference", "")).startswith("IC-CYCLE-")]
    buyers = [x for x in buyers if not str(x.get("header", {}).get("reference", "")).startswith("IC-CYCLE-")]

    circ = truth[truth["manipulation_scenario"].eq("circular_related_party_transaction")].sort_values(["fiscal_year", "posting_date"])
    for i, row in enumerate(circ.itertuples(index=False), start=1):
        year = int(row.fiscal_year)
        df = df_by_year[year]
        doc = df[df["document_id"].astype(str).eq(str(row.document_id))]
        if doc.empty:
            continue
        first = doc.iloc[0]
        seller_company = str(first["company_code"])
        partner = str(first["trading_partner"])
        buyer_company = RP_VENDOR_TO_COMPANY.get(partner) or RP_CUSTOMER_TO_COMPANY.get(partner) or RP_MAP.get(seller_company, {}).get("partner_company")
        amount = float(doc["debit_amount"].sum())
        ref = str(first["reference"])
        posting_date = str(first["posting_date"]).split(" ")[0]
        pair = {
            "ic_reference": ref,
            "transaction_type": "manipulated_shared_rp_cycle",
            "seller_company": seller_company,
            "buyer_company": buyer_company,
            "amount": str(round(amount, 2)),
            "currency": "KRW",
            "transaction_date": posting_date,
            "posting_date": posting_date,
            "seller_document": str(first["document_number"]),
            "buyer_document": f"M-ICB-{year}-{i:04d}",
            "description": f"Manipulated shared RP cycle {seller_company}->{buyer_company}",
            "transfer_pricing_policy": "outside_normal_range_or_missing_support",
            "withholding_tax": None,
            "settlement_status": "open",
            "settlement_date": None,
            "netting_reference": ref,
            "source_truth": "manipulated_entry_truth",
            "document_id": str(row.document_id),
        }
        pairs.append(pair)
        sellers.append(_journal_sidecar_record(first, doc, ref, seller_company, buyer_company, seller=True))
        buyers.append(_journal_sidecar_record(first, doc, ref, buyer_company, seller_company, seller=False))

    _write_json(inter_dir / "ic_matched_pairs.json", pairs)
    _write_json(inter_dir / "ic_seller_journal_entries.json", sellers)
    _write_json(inter_dir / "ic_buyer_journal_entries.json", buyers)


def _journal_sidecar_record(first: pd.Series, doc: pd.DataFrame, ref: str, company: str, partner_company: str, *, seller: bool) -> dict[str, Any]:
    header = {
        "document_id": str(first["document_id"]),
        "company_code": company,
        "fiscal_year": int(first["fiscal_year"]),
        "fiscal_period": int(first["fiscal_period"]),
        "posting_date": str(first["posting_date"]).split(" ")[0],
        "document_date": str(first["document_date"]).split(" ")[0],
        "document_type": "IC",
        "currency": "KRW",
        "exchange_rate": "1",
        "reference": ref,
        "header_text": f"조작 관계사 {'매출' if seller else '매입'} - {partner_company}",
        "created_by": str(first["created_by"]),
        "user_persona": str(first["user_persona"]),
        "source": str(first["source"]),
        "business_process": "R2R",
        "ledger": "0L",
        "sod_violation": bool(_as_bool(first.get("sod_violation"))),
        "sod_conflict_type": first.get("sod_conflict_type") if pd.notna(first.get("sod_conflict_type")) else None,
        "approved_by": first.get("approved_by") if pd.notna(first.get("approved_by")) else None,
        "approval_date": first.get("approval_date") if pd.notna(first.get("approval_date")) else None,
        "has_attachment": bool(_as_bool(first.get("has_attachment"))),
        "document_number": str(first["document_number"]),
    }
    lines = []
    for _, line in doc.iterrows():
        lines.append(
            {
                "document_id": str(line["document_id"]),
                "line_number": int(line["line_number"]),
                "gl_account": str(line["gl_account"]),
                "debit_amount": str(line["debit_amount"]),
                "credit_amount": str(line["credit_amount"]),
                "local_amount": str(line["local_amount"]),
                "cost_center": line.get("cost_center") if pd.notna(line.get("cost_center")) else None,
                "profit_center": line.get("profit_center") if pd.notna(line.get("profit_center")) else None,
                "line_text": str(line["line_text"]),
                "text": str(line["line_text"]),
                "reference": ref,
                "assignment": ref,
                "trading_partner": partner_company,
            }
        )
    return {"header": header, "lines": lines}


def refresh_metadata(base: Path, journal: pd.DataFrame, truth: pd.DataFrame, checks: dict[str, Any]) -> None:
    meta_path = base / "validated_metadata.json"
    metadata = _read_json(meta_path) if meta_path.exists() else {}
    metadata.update(
        {
            "status": "pass" if not checks["failures"] else "fail",
            "version": "v128_manipulation_rp_and_weak_signals",
            "total_entries": int(journal["document_id"].nunique()),
            "total_line_items": int(len(journal)),
            "scenario_truth_documents": int(truth["document_id"].nunique()),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "checks": checks,
        }
    )
    _write_json(meta_path, metadata)


def validate(base: Path, truth: pd.DataFrame, journal: pd.DataFrame) -> dict[str, Any]:
    failures: list[str] = []
    circ_ids = set(truth.loc[truth["manipulation_scenario"].eq("circular_related_party_transaction"), "document_id"].astype(str))
    circ = journal[journal["document_id"].astype(str).isin(circ_ids)].sort_values("line_number").drop_duplicates("document_id").copy()
    vendor_master = {v["vendor_id"]: v for v in _read_json(base / "master_data" / "vendors.json")}
    customer_master = {c["customer_id"]: c for c in _read_json(base / "master_data" / "customers.json")}
    partner_bad = []
    for _, row in circ.iterrows():
        partner = str(row["trading_partner"])
        master = vendor_master.get(partner) or customer_master.get(partner)
        if not master or not master.get("is_intercompany") or not master.get("intercompany_code"):
            partner_bad.append(partner)
    if partner_bad:
        failures.append(f"circular RP partners not intercompany in master: {sorted(set(partner_bad))}")

    pairs = _read_json(base / "intercompany" / "ic_matched_pairs.json")
    manipulated_pairs = [p for p in pairs if str(p.get("ic_reference", "")).startswith("IC-CYCLE-")]
    pair_docs = {str(p.get("document_id")) for p in manipulated_pairs}
    missing_pair_docs = sorted(circ_ids - pair_docs)
    if missing_pair_docs:
        failures.append(f"circular docs missing from ic_matched_pairs: {len(missing_pair_docs)}")

    balance = journal[journal["document_id"].astype(str).isin(set(truth["document_id"].astype(str)))].groupby("document_id")[["debit_amount", "credit_amount"]].sum()
    unbalanced = int(((balance["debit_amount"] - balance["credit_amount"]).abs() > 1).sum())
    if unbalanced:
        failures.append(f"unbalanced manipulated truth docs: {unbalanced}")

    doc = journal[journal["document_id"].astype(str).isin(set(truth["document_id"].astype(str)))].sort_values("line_number").drop_duplicates("document_id")
    doc = doc.merge(truth[["document_id", "manipulation_scenario", "manipulation_subtype"]], on="document_id")
    metrics = {}
    for scenario, g in doc.groupby("manipulation_scenario"):
        metrics[scenario] = {
            "documents": int(len(g)),
            "sod_true_pct": round(float(g["sod_violation"].astype(str).str.lower().isin(["true", "1"]).mean() * 100), 2),
            "subtypes": g["manipulation_subtype"].value_counts().to_dict(),
        }
    return {
        "failures": failures,
        "circular_ic_pair_docs": len(pair_docs),
        "circular_partner_master_bad_count": len(partner_bad),
        "scenario_metrics": metrics,
    }


def write_preview(base: Path, checks: dict[str, Any], journal: pd.DataFrame, truth: pd.DataFrame) -> None:
    lines = [
        "# DataSynth Manipulation v128",
        "",
        "This split contains normal journal rows plus actual manipulation scenario truth only.",
        "",
        f"- Rows: {len(journal):,}",
        f"- Documents: {journal['document_id'].nunique():,}",
        f"- Manipulated-entry truth documents: {truth['document_id'].nunique():,}",
        f"- Circular IC sidecar linked docs: {checks['circular_ic_pair_docs']}",
        f"- Validation status: {'pass' if not checks['failures'] else 'fail'}",
        "",
        "## Scenario Metrics",
        "",
        "| Scenario | Docs | SoD True | Subtypes |",
        "|---|---:|---:|---|",
    ]
    for scenario, m in checks["scenario_metrics"].items():
        lines.append(f"| {scenario} | {m['documents']} | {m['sod_true_pct']}% | `{m['subtypes']}` |")
    if checks["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {f}" for f in checks["failures"])
    (base / "PREVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    base = args.data_dir
    labels_dir = base / "labels"

    update_master_parties(base)
    truth = pd.read_csv(labels_dir / "manipulated_entry_truth.csv")
    df_by_year: dict[int, pd.DataFrame] = {}
    for year in YEARS:
        df = pd.read_csv(base / f"journal_entries_{year}.csv", low_memory=False)
        df["gl_account"] = df["gl_account"].astype("object")
        df_by_year[year] = df

    truth = strengthen_circular(base, truth, df_by_year)
    truth = add_weak_signals(base, truth, df_by_year)
    truth = refresh_truth_family(labels_dir, truth, df_by_year)
    refresh_intercompany_sidecars(base, truth, df_by_year)

    combined = pd.concat([df_by_year[y] for y in YEARS], ignore_index=True)
    for year, df in df_by_year.items():
        df.to_csv(base / f"journal_entries_{year}.csv", index=False)
        _write_json_records(base / f"journal_entries_{year}.json", df)
    combined.to_csv(base / "journal_entries.csv", index=False)
    _write_json_records(base / "journal_entries.json", combined)

    checks = validate(base, truth, combined)
    refresh_metadata(base, combined, truth, checks)
    write_preview(base, checks, combined, truth)
    manifest = {
        "version": "v128_manipulation_rp_and_weak_signals",
        "base_version": "v127_manipulation_realism",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "row_count": int(len(combined)),
        "document_count": int(combined["document_id"].nunique()),
        "manipulated_entry_truth_count": int(truth["document_id"].nunique()),
        "checks": checks,
    }
    _write_json(base / "V128_MANIPULATION_RP_AND_WEAK_SIGNALS_PATCH.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
