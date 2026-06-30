from __future__ import annotations

import argparse
import json
import numbers
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PHASE2_NEW_ACCOUNTS = {
    "131100": "intangible_assets",
    "681100": "amortization_expense",
    "151900": "construction_in_progress",
    "116100": "contract_assets",
    "231100": "contract_liabilities",
    "123100": "inventory_wip",
    "117100": "loans_receivable",
    "117900": "employee_advances",
    "106100": "short_term_investments",
    "119100": "allowance_for_doubtful_accounts",
    "469100": "allowance_reversal",
    "237100": "provisions",
    "160100": "investments",
    "682100": "impairment_loss",
}

PHASE2_WOVEN_REQUIRED_ACCOUNTS = {
    "131100",
    "681100",
    "151900",
    "117100",
    "117900",
    "119100",
    "469100",
    "237100",
    "106100",
    "160100",
    "682100",
}

PHASE2_ALLOWED_WOVEN_ARCHETYPES = {
    "P2P_VENDOR_INVOICE",
    "P2P_PAYMENT",
    "A2R_ASSET_ACQUISITION",
    "A2R_DEPRECIATION",
    "H2R_PAYROLL_PAYMENT",
    "H2R_PAYROLL_ACCRUAL",
    "R2R_ACCRUAL",
    "R2R_CLOSING_ENTRY",
    "TRE_LOAN_DRAWDOWN",
    "TRE_INTEREST_PAYMENT",
}

PHASE2_NEW_ACCOUNT_BASELINES = {"1000", "1100", "5000", "1230"}



def verdict(gate: str, test_id: str, status: str, metric: dict[str, Any], notes: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "test_id": test_id,
        "verdict": status,
        "metric": metric,
        "notes": notes,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    return value


def load_journal(dataset: Path) -> pd.DataFrame:
    df = pd.read_csv(dataset / "journal_entries.csv", dtype=str, keep_default_na=False)
    for column in ["debit_amount", "credit_amount", "local_amount", "tax_amount"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def _truthy(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _load_ic_pair_map() -> dict[str, str]:
    try:
        import yaml

        raw = yaml.safe_load((ROOT / "config" / "audit_rules.yaml").read_text(encoding="utf-8")) or {}
        pairs = raw.get("patterns", {}).get("intercompany", {}).get("pairs", [])
        return {str(item["receivable"]): str(item["payable"]) for item in pairs if "receivable" in item and "payable" in item}
    except Exception:
        return {"1150": "2050", "4500": "2700"}


def _starts_with_any(series: pd.Series, prefixes: set[str]) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    if not prefixes:
        return pd.Series(False, index=series.index)
    return values.map(lambda value: any(value.startswith(prefix) for prefix in prefixes))


def _ic_reconciliation_metrics(df: pd.DataFrame, pair_map: dict[str, str]) -> dict[str, Any]:
    rec_prefixes = set(pair_map)
    pay_prefixes = set(pair_map.values())
    ic = df[_truthy(df["is_intercompany"])].copy()
    ic["_is_rec"] = _starts_with_any(ic["gl_account"], rec_prefixes)
    ic["_is_pay"] = _starts_with_any(ic["gl_account"], pay_prefixes)
    rec = ic[ic["_is_rec"] & (ic["debit_amount"] > 0)].copy()
    pay = ic[ic["_is_pay"] & (ic["credit_amount"] > 0)].copy()
    if rec.empty or pay.empty:
        return {
            "candidate_pair_count": 0,
            "matched_pair_count": 0,
            "matched_rate": 0.0,
            "diff_ratio_p95": None,
            "diff_ratio_max": None,
            "tolerance_exceeded_pairs": 0,
            "date_diff_p95": None,
            "date_diff_max": None,
            "close_lag_exceeded_pairs": 0,
        }

    group_cols = ["reference", "company_code", "trading_partner"]
    rec_g = rec.groupby(group_cols, dropna=False).agg(
        rec_amount=("debit_amount", "sum"),
        rec_date=("posting_date", "min"),
        rec_rows=("document_id", "count"),
    ).reset_index()
    pay_g = pay.groupby(group_cols, dropna=False).agg(
        pay_amount=("credit_amount", "sum"),
        pay_date=("posting_date", "min"),
        pay_rows=("document_id", "count"),
    ).reset_index()

    merged = rec_g.merge(
        pay_g,
        left_on=["reference", "company_code", "trading_partner"],
        right_on=["reference", "trading_partner", "company_code"],
        how="left",
        suffixes=("_rec", "_pay"),
    )
    has_match = merged["pay_amount"].notna()
    matched = merged[has_match].copy()
    candidate_count = int(len(merged))
    matched_count = int(len(matched))
    if matched.empty:
        return {
            "candidate_pair_count": candidate_count,
            "matched_pair_count": 0,
            "matched_rate": 0.0,
            "diff_ratio_p95": None,
            "diff_ratio_max": None,
            "tolerance_exceeded_pairs": 0,
            "date_diff_p95": None,
            "date_diff_max": None,
            "close_lag_exceeded_pairs": 0,
        }
    denom = matched[["rec_amount", "pay_amount"]].max(axis=1).replace(0, pd.NA)
    diff_ratio = ((matched["rec_amount"] - matched["pay_amount"]).abs() / denom).fillna(0.0)
    rec_dates = pd.to_datetime(matched["rec_date"], errors="coerce")
    pay_dates = pd.to_datetime(matched["pay_date"], errors="coerce")
    date_diff = (rec_dates - pay_dates).abs().dt.days.fillna(9999)
    return {
        "candidate_pair_count": candidate_count,
        "matched_pair_count": matched_count,
        "matched_rate": float(matched_count / max(candidate_count, 1)),
        "diff_ratio_p95": float(diff_ratio.quantile(0.95)) if len(diff_ratio) else None,
        "diff_ratio_max": float(diff_ratio.max()) if len(diff_ratio) else None,
        "tolerance_exceeded_pairs": int((diff_ratio > 0.05).sum()),
        "date_diff_p95": float(date_diff.quantile(0.95)) if len(date_diff) else None,
        "date_diff_max": int(date_diff.max()) if len(date_diff) else None,
        "close_lag_exceeded_pairs": int((date_diff > 10).sum()),
    }


def _ic_cycle_metrics(df: pd.DataFrame) -> dict[str, Any]:
    try:
        import networkx as nx
    except ImportError:
        return {"networkx_available": False}

    company_codes = set(df["company_code"].fillna("").astype(str).str.strip())
    ic = df[_truthy(df["is_intercompany"])].copy()
    if ic.empty or "trading_partner" not in ic.columns:
        return {"networkx_available": True, "edges_built": 0, "cycles_found": 0}
    amount = ic[["debit_amount", "credit_amount"]].max(axis=1)
    ic = ic[amount >= 10_000_000].copy()
    if ic.empty:
        return {"networkx_available": True, "edges_built": 0, "cycles_found": 0}
    is_credit = ic["credit_amount"] > 0
    ic["_src"] = ic["company_code"].where(is_credit, ic["trading_partner"]).astype(str)
    ic["_dst"] = ic["trading_partner"].where(is_credit, ic["company_code"]).astype(str)
    ic = ic[ic["_src"].isin(company_codes) & ic["_dst"].isin(company_codes) & ic["_src"].ne(ic["_dst"])]
    if ic.empty:
        return {"networkx_available": True, "edges_built": 0, "cycles_found": 0}
    graph = nx.from_pandas_edgelist(ic, source="_src", target="_dst", edge_attr=["document_id"], create_using=nx.MultiDiGraph)
    cycles = [cycle for cycle in nx.simple_cycles(graph, length_bound=5) if len(cycle) >= 3]
    length_counts: dict[str, int] = {}
    for cycle in cycles:
        length_counts[str(len(cycle))] = length_counts.get(str(len(cycle)), 0) + 1
    directed_counts = ic.groupby(["_src", "_dst"]).size().to_dict()
    cycle_instance_count = 0
    for cycle in cycles:
        edge_counts = []
        for idx, src in enumerate(cycle):
            dst = cycle[(idx + 1) % len(cycle)]
            edge_counts.append(int(directed_counts.get((src, dst), 0)))
        if edge_counts:
            cycle_instance_count += min(edge_counts)
    return {
        "networkx_available": True,
        "edges_built": int(graph.number_of_edges()),
        "company_nodes": int(graph.number_of_nodes()),
        "cycles_found": int(len(cycles)),
        "cycle_instance_count": int(cycle_instance_count),
        "cycle_length_counts": length_counts,
    }


def _ic_direction_asymmetry_metrics(df: pd.DataFrame) -> dict[str, Any]:
    ic = df[_truthy(df["is_intercompany"])].copy()
    if ic.empty:
        return {"direction_pair_count": 0, "high_asymmetry_pair_count": 0, "high_asymmetry_rate": 0.0}
    amount = ic[["debit_amount", "credit_amount"]].max(axis=1)
    is_credit = ic["credit_amount"] > 0
    ic["_src"] = ic["company_code"].where(is_credit, ic["trading_partner"]).astype(str)
    ic["_dst"] = ic["trading_partner"].where(is_credit, ic["company_code"]).astype(str)
    ic["_amount"] = amount
    directed = ic[ic["_src"].ne(ic["_dst"])].groupby(["_src", "_dst"]).agg(
        count=("_amount", "size"),
        total_amount=("_amount", "sum"),
        mean_amount=("_amount", "mean"),
    ).reset_index()
    checked = 0
    high = 0
    for _, row in directed.iterrows():
        reverse = directed[(directed["_src"] == row["_dst"]) & (directed["_dst"] == row["_src"])]
        if reverse.empty:
            continue
        checked += 1
        other_total = float(reverse["total_amount"].iloc[0])
        row_total = float(row["total_amount"])
        other_count = float(reverse["count"].iloc[0])
        row_count = float(row["count"])
        amount_denom = max(row_total, other_total, 1.0)
        count_denom = max(row_count, other_count, 1.0)
        amount_asymmetry = abs(row_total - other_total) / amount_denom
        count_asymmetry = abs(row_count - other_count) / count_denom
        if amount_asymmetry > 0.35 or count_asymmetry > 0.35:
            high += 1
    return {
        "direction_pair_count": int(checked),
        "high_asymmetry_pair_count": int(high),
        "high_asymmetry_rate": float(high / max(checked, 1)),
        "amount_or_count_asymmetry_threshold": 0.35,
    }


def _single_company_sidecar_metrics(dataset: Path) -> tuple[str, dict[str, Any]]:
    roots = [
        dataset / "master_data",
        dataset / "document_flows",
        dataset / "relationships",
        dataset / "subledger",
        dataset / "balance",
        dataset / "financial_reporting",
        dataset / "intercompany",
    ]
    namespace_patterns = ["IC-C", "IC_INTERCOMPANY"]
    forbidden_company_field_hits: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    files_checked = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            files_checked += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = {pattern: text.count(pattern) for pattern in namespace_patterns if pattern in text}
            if hits:
                findings.append(
                    {
                        "path": str(path.relative_to(dataset)),
                        "hits": hits,
                    }
                )
            try:
                raw = json.loads(text)
            except Exception:
                raw = []
            stack = raw if isinstance(raw, list) else [raw]
            for item in stack:
                if not isinstance(item, dict):
                    continue
                company = str(item.get("company_code", item.get("company", ""))).strip()
                if company in {"C002", "C003"}:
                    allowed_related_master = path.name == "related_parties.json" and str(
                        item.get("journal_company_code", "")
                    ).strip() == "C001"
                    if not allowed_related_master:
                        forbidden_company_field_hits.append(
                            {"path": str(path.relative_to(dataset)), "company_code": company}
                        )
    metric = {
        "files_checked": files_checked,
        "forbidden_sidecar_file_count": len(findings) + len(forbidden_company_field_hits),
        "sample_findings": findings[:20],
        "sample_forbidden_company_field_hits": forbidden_company_field_hits[:20],
        "forbidden_patterns": namespace_patterns,
        "allowed_related_party_partner_codes": ["C002", "C003"],
    }
    return ("PASS" if not findings and not forbidden_company_field_hits else "FAIL"), metric


def _reversal_link_metrics(df: pd.DataFrame, doc_head: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    required = [
        "original_document_id",
        "reversal_document_id",
        "reversal_type",
        "reversal_reason",
        "reversal_reason_code",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return "BLOCKED", {"missing_required_columns": missing}

    reversal_scenario_docs = set(
        doc_head[doc_head["semantic_scenario_id"].astype(str).eq("R2R_REVERSAL")]["document_id"].astype(str)
    )
    linked_reversal_heads = doc_head[
        doc_head["original_document_id"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    linked_reversal_docs = set(linked_reversal_heads["document_id"].astype(str))
    unlinked_reversal_docs = sorted(reversal_scenario_docs - linked_reversal_docs)

    doc_index = doc_head.set_index("document_id", drop=False)
    missing_originals = 0
    bad_time_order = 0
    bad_pair_net = 0
    bad_reason = 0
    checked_pairs = 0
    max_abs_pair_net_krw = 0.0

    amount_work = df.copy()
    amount_work["_signed"] = amount_work["debit_amount"].round(0) - amount_work["credit_amount"].round(0)
    for row in linked_reversal_heads.itertuples(index=False):
        reversal_doc = str(row.document_id)
        original_doc = str(row.original_document_id).strip()
        if not original_doc or original_doc not in doc_index.index:
            missing_originals += 1
            continue
        checked_pairs += 1
        original_date = pd.to_datetime(doc_index.loc[original_doc, "posting_date"], errors="coerce")
        reversal_date = pd.to_datetime(getattr(row, "posting_date"), errors="coerce")
        if pd.isna(original_date) or pd.isna(reversal_date) or reversal_date <= original_date:
            bad_time_order += 1

        reason_code = str(getattr(row, "reversal_reason_code", "")).strip()
        reversal_type = str(getattr(row, "reversal_type", "")).strip()
        if reason_code != "NORMAL_ACCRUAL_REVERSAL" or reversal_type != "normal_accrual_reversal":
            bad_reason += 1

        pair_lines = amount_work[amount_work["document_id"].astype(str).isin({original_doc, reversal_doc})]
        by_account = pair_lines.groupby("gl_account", dropna=False)["_signed"].sum().abs()
        pair_max = float(by_account.max()) if len(by_account) else 0.0
        max_abs_pair_net_krw = max(max_abs_pair_net_krw, pair_max)
        if pair_max > 1.0:
            bad_pair_net += 1

    metric = {
        "reversal_scenario_docs": int(len(reversal_scenario_docs)),
        "linked_reversal_docs": int(len(linked_reversal_docs)),
        "checked_pairs": int(checked_pairs),
        "unlinked_reversal_docs": int(len(unlinked_reversal_docs)),
        "sample_unlinked_reversal_docs": unlinked_reversal_docs[:10],
        "missing_originals": int(missing_originals),
        "bad_time_order": int(bad_time_order),
        "bad_pair_net": int(bad_pair_net),
        "bad_reason_or_type": int(bad_reason),
        "max_abs_pair_net_krw": max_abs_pair_net_krw,
    }
    status = (
        "PASS"
        if checked_pairs > 0
        and not unlinked_reversal_docs
        and missing_originals == 0
        and bad_time_order == 0
        and bad_pair_net == 0
        and bad_reason == 0
        else "FAIL"
    )
    return status, metric


def _account_category(account_code: str) -> str:
    prefix = str(account_code).strip()[:2]
    if prefix == "10":
        return "Cash"
    if prefix in {"11", "45"}:
        return "Receivables"
    if prefix in {"12", "13", "14"}:
        return "Inventory"
    if prefix in {"15", "16", "17", "18", "19"}:
        return "FixedAssets"
    if prefix == "20":
        return "Payables"
    if prefix in {"21", "22", "23", "24"}:
        return "AccruedLiabilities"
    if prefix in {"25", "26", "27", "28", "29"}:
        return "LongTermDebt"
    if prefix in {"30", "31", "32", "33", "34", "35", "36", "37", "38", "39"}:
        return "Equity"
    if prefix in {"40", "41", "42", "43", "44"}:
        return "Revenue"
    if prefix in {"50", "51", "52", "53"}:
        return "CostOfSales"
    if prefix in {"60", "61", "62", "63", "64", "65", "66", "67", "68", "69"}:
        return "OperatingExpenses"
    if prefix in {"70", "71", "72", "73", "74"}:
        return "OtherIncome"
    if prefix in {"80", "81", "82", "83", "84", "85", "86", "87", "88", "89"}:
        return "OtherExpenses"
    return "OperatingExpenses"


def _is_bs_category(category: str) -> bool:
    return category in {
        "Cash",
        "Receivables",
        "Inventory",
        "FixedAssets",
        "Payables",
        "AccruedLiabilities",
        "LongTermDebt",
        "Equity",
    }


def _is_credit_normal(account_code: str, coa_meta: dict[str, dict[str, Any]]) -> bool:
    meta = coa_meta.get(str(account_code), {})
    if "normal_debit_balance" in meta:
        return not bool(meta["normal_debit_balance"])
    return str(account_code).strip()[:1] in {"2", "3", "4"}


def _debit_minus_credit_from_normal(account_code: str, normal_side_balance: int, coa_meta: dict[str, dict[str, Any]]) -> int:
    return -normal_side_balance if _is_credit_normal(account_code, coa_meta) else normal_side_balance


def _is_contra_account(account_code: str, category: str, coa_meta: dict[str, dict[str, Any]]) -> bool:
    meta = coa_meta.get(str(account_code), {})
    text = " ".join(
        str(meta.get(key, ""))
        for key in ["account_name", "name", "description", "account_type", "sub_type", "semantic_account_subtype"]
    ).lower()
    contra_terms = {
        "accumulated depreciation",
        "allowance",
        "contra",
        "return",
        "discount",
        "valuation",
        "depreciation",
        "충당",
        "감가상각누계",
        "환입",
        "할인",
    }
    if any(term in text for term in contra_terms):
        return True
    if category in {"Cash", "Receivables", "Inventory", "FixedAssets"} and _is_credit_normal(account_code, coa_meta):
        return True
    if category in {"Revenue", "OtherIncome"} and not _is_credit_normal(account_code, coa_meta):
        return True
    if category in {"Payables", "AccruedLiabilities", "LongTermDebt", "Equity"} and not _is_credit_normal(account_code, coa_meta):
        return True
    return False


def _load_coa_meta(dataset: Path) -> dict[str, dict[str, Any]]:
    path = dataset / "chart_of_accounts.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", raw if isinstance(raw, list) else [])
    meta: dict[str, dict[str, Any]] = {}
    for account in accounts:
        code = str(account.get("account_number") or account.get("account_code") or "")
        if code:
            meta[code] = account
    return meta


def _meta_text(meta: dict[str, Any]) -> str:
    return " ".join(
        str(meta.get(key, ""))
        for key in [
            "account_name",
            "name",
            "description",
            "account_type",
            "category",
            "sub_type",
            "semantic_account_subtype",
            "normal_use",
        ]
    ).lower()


def _account_meta_type(meta: dict[str, Any]) -> str:
    return str(meta.get("account_type") or meta.get("category") or "").strip().lower()


def _company_year_pnl(df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if df.empty:
        return "BLOCKED", {"rows": 0}
    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    nonclosing = work[~(batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-"))].copy()
    if nonclosing.empty:
        return "BLOCKED", {"nonclosing_rows": 0}

    nonclosing["_debit_i"] = nonclosing["debit_amount"].round(0).astype("int64")
    nonclosing["_credit_i"] = nonclosing["credit_amount"].round(0).astype("int64")
    nonclosing["_prefix"] = nonclosing["gl_account"].fillna("").astype(str).str.strip().str[:1]
    nonclosing["_meta_text"] = nonclosing["gl_account"].astype(str).map(lambda account: _meta_text(coa_meta.get(account, {})))
    nonclosing["_expense_net"] = nonclosing["_debit_i"] - nonclosing["_credit_i"]
    nonclosing["_revenue_net"] = nonclosing["_credit_i"] - nonclosing["_debit_i"]

    bad_periods: list[dict[str, Any]] = []
    ratios: list[dict[str, Any]] = []
    grouped = nonclosing.groupby(["company_code", "fiscal_year"], dropna=False)
    for (company, year), group in grouped:
        revenue = int(group.loc[group["_prefix"].eq("4"), "_revenue_net"].sum())
        cogs = int(group.loc[group["_prefix"].eq("5"), "_expense_net"].sum())
        sga = int(group.loc[group["_prefix"].eq("6"), "_expense_net"].sum())
        interest = int(group.loc[group["_meta_text"].str.contains("interest|이자", regex=True), "_expense_net"].sum())
        taxes = int(group.loc[group["_meta_text"].str.contains("tax|income_tax|corporate_tax|세금|법인세", regex=True), "_expense_net"].sum())
        if revenue <= 0:
            bad_periods.append({"company": str(company), "year": str(year), "reason": "nonpositive_revenue", "revenue": revenue})
            continue
        cogs_ratio = cogs / revenue
        sga_ratio = sga / revenue
        interest_ratio = interest / revenue
        tax_ratio = taxes / revenue
        operating_margin = (revenue - cogs - sga) / revenue
        item = {
            "company": str(company),
            "year": str(year),
            "revenue": revenue,
            "cogs_ratio": cogs_ratio,
            "sga_ratio": sga_ratio,
            "interest_ratio": interest_ratio,
            "tax_ratio": tax_ratio,
            "operating_margin": operating_margin,
        }
        ratios.append(item)
        period_bad = (
            not (0.55 <= cogs_ratio <= 0.92)
            or not (0.03 <= sga_ratio <= 0.45)
            or interest_ratio > 0.15
            or tax_ratio > 0.40
            or operating_margin < -0.20
        )
        if period_bad:
            bad_periods.append(item)

    if not ratios:
        return "BLOCKED", {"company_years_checked": 0, "bad_periods": bad_periods[:10]}
    metric = {
        "company_years_checked": len(ratios),
        "bad_company_years": len(bad_periods),
        "thresholds": {
            "cogs_ratio": "0.55..0.92",
            "sga_ratio": "0.03..0.45",
            "interest_ratio_max": 0.15,
            "tax_ratio_max": 0.40,
            "operating_margin_min": -0.20,
        },
        "ratio_summary": {
            key: {
                "min": float(pd.Series([r[key] for r in ratios]).min()),
                "p50": float(pd.Series([r[key] for r in ratios]).quantile(0.5)),
                "max": float(pd.Series([r[key] for r in ratios]).max()),
            }
            for key in ["cogs_ratio", "sga_ratio", "interest_ratio", "tax_ratio", "operating_margin"]
        },
        "sample_bad_periods": bad_periods[:10],
    }
    return ("PASS" if not bad_periods else "FAIL"), metric


def _coa_prefix_semantic_metrics(df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    used_accounts = set(df["gl_account"].fillna("").astype(str).str.strip())
    checked = 0
    bad: list[dict[str, Any]] = []
    for account in sorted(used_accounts):
        if not account:
            continue
        meta = coa_meta.get(account, {})
        text = _meta_text(meta)
        account_type = _account_meta_type(meta)
        prefix1 = account[:1]
        checked += 1
        reason = ""
        if prefix1 == "4" and any(term in text for term in ["expense", "cost", "tax", "interest", "loss", "비용", "원가", "세금", "이자", "손상"]):
            reason = "revenue_prefix_has_expense_semantics"
        elif prefix1 == "5" and any(term in text for term in ["interest", "tax", "depreciation", "amortization", "opex", "selling", "admin", "이자", "세금", "감가", "상각", "판관"]):
            reason = "cogs_prefix_has_non_cogs_semantics"
        elif prefix1 == "6" and any(term in text for term in ["interest", "income tax", "corporate tax", "이자", "법인세"]):
            reason = "sga_prefix_has_financing_or_tax_semantics"
        elif prefix1 == "7" and any(term in text for term in ["expense", "cost", "loss", "tax", "interest", "비용", "원가", "손실", "세금", "이자"]):
            reason = "other_income_prefix_has_expense_semantics"
        elif prefix1 == "8" and "income tax" not in text and any(term in text for term in ["revenue", "income", "sales", "매출", "수익"]):
            reason = "other_expense_prefix_has_income_semantics"
        elif prefix1 in {"1", "2", "3"} and any(term in account_type for term in ["revenue", "expense", "income"]):
            reason = "balance_sheet_prefix_has_pl_account_type"
        elif prefix1 in {"4", "5", "6", "7", "8"} and any(term in account_type for term in ["asset", "liability", "equity"]):
            reason = "pl_prefix_has_balance_sheet_account_type"
        if reason:
            bad.append(
                {
                    "account": account,
                    "reason": reason,
                    "account_type": account_type,
                    "sub_type": str(meta.get("sub_type") or meta.get("semantic_account_subtype") or ""),
                    "name": str(meta.get("account_name") or meta.get("name") or ""),
                }
            )
    metric = {
        "used_accounts_checked": checked,
        "bad_account_count": len(bad),
        "sample_bad_accounts": bad[:30],
    }
    return ("PASS" if checked > 0 and not bad else "FAIL"), metric


def _financial_statement_export_metrics(dataset: Path) -> tuple[str, dict[str, Any]]:
    fs_path = dataset / "financial_reporting" / "financial_statements.json"
    if not fs_path.exists():
        fs_path = dataset / "financial_statements.json"
    if not fs_path.exists():
        return "BLOCKED", {"missing": "financial_statements.json"}
    raw = json.loads(fs_path.read_text(encoding="utf-8"))
    statements = raw if isinstance(raw, list) else []
    income = [rec for rec in statements if str(rec.get("statement_type", "")).lower() == "income_statement"]
    if not income:
        return "BLOCKED", {"financial_statement_records": len(statements), "income_statement_records": 0}
    revenue_negative = 0
    cogs_gt_revenue = 0
    empty_mapping = 0
    checked = 0
    sample_bad: list[dict[str, Any]] = []
    for rec in income:
        items = {str(item.get("line_code")): item for item in rec.get("line_items", []) if isinstance(item, dict)}
        rev = int(round(float(items.get("IS-REV", {}).get("amount", 0) or 0)))
        cogs = int(round(float(items.get("IS-COGS", {}).get("amount", 0) or 0)))
        checked += 1
        bad_reasons = []
        if rev <= 0:
            revenue_negative += 1
            bad_reasons.append("nonpositive_revenue")
        if rev > 0 and cogs > rev:
            cogs_gt_revenue += 1
            bad_reasons.append("cogs_gt_revenue")
        for code in ["IS-REV", "IS-COGS", "IS-OPEX", "IS-TAX"]:
            item = items.get(code)
            if item is not None and not item.get("gl_accounts"):
                empty_mapping += 1
                bad_reasons.append(f"{code}_empty_gl_accounts")
        if bad_reasons and len(sample_bad) < 10:
            sample_bad.append(
                {
                    "company": rec.get("company_code"),
                    "year": rec.get("fiscal_year"),
                    "period": rec.get("fiscal_period"),
                    "revenue": rev,
                    "cogs": cogs,
                    "reasons": sorted(set(bad_reasons)),
                }
            )
    metric = {
        "income_statement_records": checked,
        "nonpositive_revenue_records": revenue_negative,
        "cogs_gt_revenue_records": cogs_gt_revenue,
        "empty_gl_account_mapping_items": empty_mapping,
        "sample_bad_records": sample_bad,
    }
    status = "PASS" if checked > 0 and revenue_negative == 0 and cogs_gt_revenue == 0 and empty_mapping == 0 else "FAIL"
    return status, metric


def _depreciation_net_metrics(df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    work = work[~(batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-"))].copy()
    work["_meta_text"] = work["gl_account"].astype(str).map(lambda account: _meta_text(coa_meta.get(account, {})))
    dep = work[work["_meta_text"].str.contains("depreciation expense|amortization expense|감가상각비|상각비", regex=True)].copy()
    if dep.empty:
        return "BLOCKED", {"depreciation_expense_rows": 0}
    dep["_debit_i"] = dep["debit_amount"].round(0).astype("int64")
    dep["_credit_i"] = dep["credit_amount"].round(0).astype("int64")
    grouped = dep.groupby(["company_code", "fiscal_year"], dropna=False).agg(
        debit=("_debit_i", "sum"),
        credit=("_credit_i", "sum"),
        rows=("document_id", "size"),
    ).reset_index()
    grouped["net_expense"] = grouped["debit"] - grouped["credit"]
    zero_or_negative = grouped[grouped["net_expense"] <= 0]
    metric = {
        "company_years_checked": int(len(grouped)),
        "zero_or_negative_net_expense_count": int(len(zero_or_negative)),
        "net_expense_min": int(grouped["net_expense"].min()) if not grouped.empty else None,
        "net_expense_p50": float(grouped["net_expense"].quantile(0.5)) if not grouped.empty else None,
        "sample_bad": zero_or_negative.head(10).to_dict("records"),
    }
    return ("PASS" if len(grouped) > 0 and zero_or_negative.empty else "FAIL"), metric


def _load_opening_balances(dataset: Path) -> dict[str, dict[str, int]]:
    path = dataset / "balance" / "opening_balances.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, int]] = {}
    for item in raw if isinstance(raw, list) else []:
        company = str(item.get("company_code", ""))
        balances = item.get("balances", {}) or {}
        result[company] = {str(k): int(round(float(v))) for k, v in balances.items()}
    return result


def _load_period_tbs(dataset: Path) -> list[dict[str, Any]]:
    path = dataset / "period_close" / "trial_balances.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def _archetype_coverage_metrics(df: pd.DataFrame, doc_head: pd.DataFrame, dataset: Path) -> tuple[str, dict[str, Any]]:
    archetype_col = "semantic_scenario_id"
    if archetype_col not in df.columns or df[archetype_col].fillna("").astype(str).str.strip().eq("").all():
        archetype_col = "scenario_id" if "scenario_id" in df.columns else "event_type"
    archetype = df[archetype_col].fillna("").astype(str).str.strip()
    missing_rows = int(archetype.eq("").sum())
    doc_archetype = doc_head[archetype_col].fillna("").astype(str).str.strip()
    missing_docs = int(doc_archetype.eq("").sum())
    total_docs = int(doc_head["document_id"].nunique())
    required = [
        "semantic_account_subtype",
        "business_process",
        "counterparty_type",
        "document_type",
        "line_text_family",
    ]
    missing_required_cols = [col for col in required if col not in df.columns]
    work = df.copy()
    work["_archetype_key"] = archetype
    if missing_required_cols:
        tuple_missing_rows = len(work)
        raw_tuple_missing_rows = tuple_missing_rows
        tuple_counts = pd.Series(dtype="int64")
        tuple_summary: dict[str, Any] = {}
    else:
        raw_tuple_missing_mask = work[required].fillna("").astype(str).apply(lambda col: col.str.strip().eq("")).any(axis=1)
        raw_tuple_missing_rows = int(raw_tuple_missing_mask.sum())
        coa_meta = _load_coa_meta(dataset)
        account_subtype = work["semantic_account_subtype"].fillna("").astype(str).str.strip()
        account_subtype = account_subtype.mask(
            account_subtype.eq(""),
            work["gl_account"].astype(str).map(lambda code: str(coa_meta.get(code, {}).get("sub_type", ""))),
        )
        account_subtype = account_subtype.mask(account_subtype.eq(""), work["gl_account"].map(_account_category))
        line_family = work["line_text_family"].fillna("").astype(str).str.strip()
        line_family = line_family.mask(
            line_family.eq("") & work["_archetype_key"].str.contains("IC_|INTERCOMPANY", case=False, regex=True),
            "INTERCOMPANY",
        )
        line_family = line_family.mask(
            line_family.eq("") & work["_archetype_key"].str.contains("CLOSING|RECLASS", case=False, regex=True),
            "ACCRUAL",
        )
        work["_derived_account_subtype"] = account_subtype
        work["_derived_line_text_family"] = line_family
        derived_required = [
            "_derived_account_subtype",
            "business_process",
            "counterparty_type",
            "document_type",
            "_derived_line_text_family",
        ]
        tuple_missing_mask = work[derived_required].fillna("").astype(str).apply(lambda col: col.str.strip().eq("")).any(axis=1)
        tuple_missing_rows = int(tuple_missing_mask.sum())
        work["_tuple_key"] = (
            work["_derived_account_subtype"].astype(str)
            + "|"
            + work["business_process"].astype(str)
            + "|"
            + work["counterparty_type"].astype(str)
            + "|"
            + work["document_type"].astype(str)
            + "|"
            + work["_derived_line_text_family"].astype(str)
        )
        tuple_counts = work[~tuple_missing_mask & work["_archetype_key"].ne("")].groupby("_archetype_key")["_tuple_key"].nunique()
        tuple_summary = {
            key: {
                "rows": int(group_rows),
                "docs": int(group_docs),
                "tuple_count": int(tuple_counts.get(key, 0)),
                "top_tuples": {
                    str(tuple_key): int(count)
                    for tuple_key, count in work[work["_archetype_key"].eq(key)]["_tuple_key"]
                    .value_counts()
                    .head(5)
                    .items()
                },
            }
            for key, group_rows, group_docs in work[work["_archetype_key"].ne("")]
            .groupby("_archetype_key")
            .agg(rows=("document_id", "size"), docs=("document_id", "nunique"))
            .sort_values("rows", ascending=False)
            .head(20)
            .itertuples()
        }

    dist = work[work["_archetype_key"].ne("")].groupby("_archetype_key").agg(
        rows=("document_id", "size"),
        docs=("document_id", "nunique"),
    )
    dist_top = {
        str(idx): {"docs": int(row.docs), "rows": int(row.rows)}
        for idx, row in dist.sort_values("rows", ascending=False).head(30).iterrows()
    }
    missing_doc_rate = missing_docs / max(total_docs, 1)
    status = (
        "PASS"
        if missing_docs == 0
        and missing_rows == 0
        and raw_tuple_missing_rows == 0
        and tuple_missing_rows == 0
        and not missing_required_cols
        else "FAIL"
    )
    metric = {
        "archetype_column": archetype_col,
        "archetype_count": int(dist.shape[0]),
        "total_documents": total_docs,
        "missing_archetype_docs": missing_docs,
        "missing_archetype_doc_rate": missing_doc_rate,
        "missing_archetype_rows": missing_rows,
        "required_tuple_fields": required,
        "missing_required_columns": missing_required_cols,
        "raw_tuple_missing_rows": raw_tuple_missing_rows,
        "derived_tuple_missing_rows": tuple_missing_rows,
        "derivation_policy": "diagnostic only: derived tuple still reports CoA/scenario fallback, but PASS requires raw semantic tuple fields to be populated",
        "max_tuple_count_per_archetype": int(tuple_counts.max()) if len(tuple_counts) else 0,
        "top_archetypes": dist_top,
        "top_archetype_tuple_profiles": tuple_summary,
    }
    return status, metric


def _p01_sample_rows(df: pd.DataFrame, max_rows: int = 200) -> list[dict[str, Any]]:
    doc_rows = []
    group_cols = ["semantic_scenario_id", "business_process", "document_type", "source"]
    doc_head = df.drop_duplicates("document_id").copy()
    missing_cols = [col for col in group_cols if col not in doc_head.columns]
    if missing_cols:
        return []
    sampled = (
        doc_head.sort_values("document_id")
        .groupby(group_cols, dropna=False, sort=True, group_keys=False)
        .sample(n=1, random_state=20260605)
        .sort_values(group_cols + ["document_id"])
        .head(max_rows)
    )
    for doc in sampled["document_id"].astype(str):
        group = df[df["document_id"].astype(str).eq(doc)]
        head = group.iloc[0]
        debit_total = float(group["debit_amount"].sum())
        credit_total = float(group["credit_amount"].sum())
        doc_rows.append(
            {
                "document_id": doc,
                "company_code": str(head.get("company_code", "")),
                "fiscal_year": str(head.get("fiscal_year", "")),
                "fiscal_period": str(head.get("fiscal_period", "")),
                "posting_date": str(head.get("posting_date", "")),
                "semantic_scenario_id": str(head.get("semantic_scenario_id", "")),
                "business_process": str(head.get("business_process", "")),
                "document_type": str(head.get("document_type", "")),
                "source": str(head.get("source", "")),
                "counterparty_type": str(head.get("counterparty_type", "")),
                "reference": str(head.get("reference", "")),
                "line_count": int(len(group)),
                "debit_total": debit_total,
                "credit_total": credit_total,
                "top_gl_accounts": ",".join(group["gl_account"].astype(str).value_counts().head(8).index.tolist()),
                "line_text_sample": " | ".join(group["line_text"].astype(str).drop_duplicates().head(4).tolist()),
            }
        )
    return doc_rows


def _document_reference_structure_metrics(df: pd.DataFrame, doc_head: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    required = [
        "document_id",
        "company_code",
        "fiscal_year",
        "document_type",
        "business_process",
        "semantic_scenario_id",
        "document_number",
        "reference",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        return "BLOCKED", {"missing_required_columns": missing}

    docs = doc_head[required].copy()
    for col in required:
        docs[col] = docs[col].fillna("").astype(str).str.strip()

    doc_id_conflict = int(
        df.groupby("document_id", dropna=False)[["company_code", "fiscal_year", "document_type"]]
        .nunique(dropna=False)
        .gt(1)
        .any(axis=1)
        .sum()
    )
    doc_num_nonblank = docs["document_number"].ne("")
    duplicate_doc_number_docs = int(
        docs[doc_num_nonblank & docs.duplicated("document_number", keep=False)]["document_id"].nunique()
    )
    number_parts = docs["document_number"].str.extract(
        r"^(?P<company>[^-]+)-(?P<year>\d{4})-(?P<document_type>[^-]+)-(?P<seq>\d{6})$"
    )
    bad_number_format_docs = int(
        (
            ~doc_num_nonblank
            | number_parts["company"].isna()
            | number_parts["company"].ne(docs["company_code"])
            | number_parts["year"].ne(docs["fiscal_year"])
            | number_parts["document_type"].ne(docs["document_type"])
        ).sum()
    )

    role_ref_cols = [
        "company_code",
        "fiscal_year",
        "document_type",
        "business_process",
        "semantic_scenario_id",
        "reference",
    ]
    ref_docs = docs[docs["reference"].ne("")].copy()
    same_role_ref_groups = (
        ref_docs.groupby(role_ref_cols, dropna=False)
        .agg(docs=("document_id", "nunique"))
        .reset_index()
    )
    same_role_ref_groups = same_role_ref_groups[same_role_ref_groups["docs"].gt(1)]
    same_role_duplicate_reference_groups = int(len(same_role_ref_groups))
    same_role_duplicate_reference_docs = int(same_role_ref_groups["docs"].sum()) if len(same_role_ref_groups) else 0

    cross_role_shared_reference_groups = 0
    if not ref_docs.empty:
        by_ref = (
            ref_docs.groupby(["company_code", "fiscal_year", "reference"], dropna=False)
            .agg(
                docs=("document_id", "nunique"),
                document_types=("document_type", "nunique"),
                scenarios=("semantic_scenario_id", "nunique"),
                processes=("business_process", "nunique"),
            )
            .reset_index()
        )
        cross_role_shared_reference_groups = int(
            by_ref[
                by_ref["docs"].gt(1)
                & (
                    by_ref["document_types"].gt(1)
                    | by_ref["scenarios"].gt(1)
                    | by_ref["processes"].gt(1)
                )
            ].shape[0]
        )

    metric = {
        "document_id_company_year_type_conflict_docs": doc_id_conflict,
        "duplicate_document_number_docs": duplicate_doc_number_docs,
        "bad_document_number_format_docs": bad_number_format_docs,
        "same_role_duplicate_reference_groups": same_role_duplicate_reference_groups,
        "same_role_duplicate_reference_docs": same_role_duplicate_reference_docs,
        "cross_role_shared_reference_groups": cross_role_shared_reference_groups,
        "document_number_pattern": "company-year-document_type-000001 by company/year/document_type range",
        "reference_policy": "same-role reference reuse must be 0; cross-role shared references are flow-link diagnostics",
    }
    status = (
        "PASS"
        if doc_id_conflict == 0
        and duplicate_doc_number_docs == 0
        and bad_number_format_docs == 0
        and same_role_duplicate_reference_groups == 0
        else "FAIL"
    )
    return status, metric


def _duplicate_detector_same_document_pair_metrics(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    required = {
        "document_id",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "posting_date",
        "line_text",
    }
    missing = [column for column in sorted(required) if column not in df.columns]
    if missing:
        return "BLOCKED", {"missing_required_columns": missing}
    try:
        from config.settings import AuditSettings
        from src.detection.duplicate_detector import DuplicateDetector

        result = DuplicateDetector(AuditSettings()).detect(df)
        artifact = (result.metadata or {}).get("pair_artifact", {})
        top_pairs = artifact.get("top_pairs", []) if isinstance(artifact, dict) else []
        same_doc_pairs = [
            pair
            for pair in top_pairs
            if isinstance(pair, dict)
            and str(pair.get("left_document_id") or "").strip()
            and str(pair.get("left_document_id") or "").strip()
            == str(pair.get("right_document_id") or "").strip()
        ]
        metric = {
            "retained_pair_count": int(len(top_pairs)),
            "same_document_retained_pair_count": int(len(same_doc_pairs)),
            "truncated": bool(artifact.get("truncated", False)) if isinstance(artifact, dict) else False,
        }
        return ("PASS" if not same_doc_pairs else "FAIL"), metric
    except Exception as exc:  # noqa: BLE001
        return "BLOCKED", {"error": str(exc)}


def _section9_diagnostics(df: pd.DataFrame) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    reclass = df[df.get("batch_type", pd.Series("", index=df.index)).fillna("").astype(str).eq("monthly_balance_reclass")].copy()
    if reclass.empty:
        findings.append(verdict("Diagnostic", "S09_RECLASS", "INFO", {"reclass_documents": 0, "reclass_rows": 0}, "monthly balance reclass trigger diagnostics"))
    else:
        doc_line_counts = reclass.groupby("document_id").size()
        restore_rows = reclass[reclass["line_text"].fillna("").astype(str).str.contains("정상잔액 복원", regex=False)]
        reclass_metric = {
            "reclass_documents": int(reclass["document_id"].nunique()),
            "reclass_rows": int(len(reclass)),
            "company_periods_with_reclass": int(reclass[["company_code", "fiscal_year", "fiscal_period"]].drop_duplicates().shape[0]),
            "line_count_per_doc_min": int(doc_line_counts.min()),
            "line_count_per_doc_p50": float(doc_line_counts.quantile(0.5)),
            "line_count_per_doc_max": int(doc_line_counts.max()),
            "restored_account_rows": int(len(restore_rows)),
            "restored_account_top": {str(k): int(v) for k, v in restore_rows["gl_account"].value_counts().head(20).items()},
            "trigger_rule": "issued only when a company-period/account has negative normal-side BS balance after monthly roll-forward; line count varies by triggered accounts, not a fixed blanket row pattern",
        }
        findings.append(verdict("Diagnostic", "S09_RECLASS", "INFO", reclass_metric, "monthly balance reclass trigger diagnostics"))

    work = df.copy()
    work["_category"] = work["gl_account"].map(_account_category)
    pnl = work[work["_category"].isin({"Revenue", "OtherIncome", "CostOfSales", "OperatingExpenses", "OtherExpenses"})].copy()
    if pnl.empty:
        pnl_metric = {"income_statement_rows": 0}
    else:
        pnl["_amount_debit_i"] = pnl["debit_amount"].round(0).astype("int64")
        pnl["_amount_credit_i"] = pnl["credit_amount"].round(0).astype("int64")
        by_period_account = pnl.groupby(["company_code", "fiscal_year", "fiscal_period", "gl_account", "_category"], dropna=False).agg(
            debit=("_amount_debit_i", "sum"),
            credit=("_amount_credit_i", "sum"),
            docs=("document_id", "nunique"),
            rows=("document_id", "size"),
        ).reset_index()
        revenue_like = by_period_account["_category"].isin({"Revenue", "OtherIncome"})
        expense_like = by_period_account["_category"].isin({"CostOfSales", "OperatingExpenses", "OtherExpenses"})
        reverse = by_period_account[(revenue_like & (by_period_account["debit"] > by_period_account["credit"])) | (expense_like & (by_period_account["credit"] > by_period_account["debit"]))]
        pnl_metric = {
            "period_account_reverse_count": int(len(reverse)),
            "reverse_rate": float(len(reverse) / max(len(by_period_account), 1)),
            "by_category": {str(k): int(v) for k, v in reverse["_category"].value_counts().items()},
            "top_accounts": {str(k): int(v) for k, v in reverse["gl_account"].value_counts().head(20).items()},
            "basis": "period-level P&L reverse balances are diagnostic: returns/discounts, reallocations, reversals, reclass, tax/closing timing can create debit revenue or credit expense in a month without breaking annual closing",
        }
    findings.append(verdict("Diagnostic", "S09_M06_IS_REVERSE", "INFO", pnl_metric, "income statement reverse-balance diagnostic"))
    return findings


def _balance_metrics(df: pd.DataFrame, dataset: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    coa_meta = _load_coa_meta(dataset)
    opening = _load_opening_balances(dataset)
    tbs = _load_period_tbs(dataset)
    if not opening or not tbs:
        metric = {
            "opening_balance_companies": len(opening),
            "trial_balance_periods": len(tbs),
            "missing": [
                name
                for name, present in {
                    "balance/opening_balances.json": bool(opening),
                    "period_close/trial_balances.json": bool(tbs),
                }.items()
                if not present
            ],
        }
        for test_id in ["M01", "M02", "M03", "M04", "M05", "M06"]:
            findings.append(verdict("Gate 2", test_id, "BLOCKED", metric, "financial statement balance artifacts required"))
    else:
        work = df.copy()
        work["_amount_debit_i"] = work["debit_amount"].round(0).astype("int64")
        work["_amount_credit_i"] = work["credit_amount"].round(0).astype("int64")
        work["_category"] = work["gl_account"].map(_account_category)
        work["_posting_dt"] = pd.to_datetime(work["posting_date"], errors="coerce")
        if "batch_type" in work.columns:
            batch_type = work["batch_type"].fillna("").astype(str)
        else:
            batch_type = pd.Series("", index=work.index)
        if "reference" in work.columns:
            reference = work["reference"].fillna("").astype(str)
        else:
            reference = pd.Series("", index=work.index)
        work["_is_closing"] = batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-")
        work["_period_key"] = list(zip(work["company_code"], work["fiscal_year"].astype(str), work["fiscal_period"].astype(str).str.zfill(2)))

        # M01: exported TB must match journal-derived balances by company/period/account.
        mismatches = 0
        checked_lines = 0
        max_diff = 0
        for tb in tbs:
            company = str(tb.get("company_code") or tb.get("company") or "")
            if not company:
                # Older PeriodTrialBalance omitted company_code; infer from trial_balance_id not available.
                # Treat as blocked later if no company-bearing TB exists.
                continue
            fy = int(tb["fiscal_year"])
            fp = int(tb["fiscal_period"])
            period_end = pd.to_datetime(tb["period_end"])
            expected: dict[str, tuple[int, int]] = {}
            company_opening = opening.get(company, {})
            for account, amount in company_opening.items():
                cat = _account_category(account)
                if _is_bs_category(cat):
                    expected[account] = (amount, 0) if amount >= 0 else (0, -amount)
            company_rows = work[work["company_code"].astype(str).eq(company)]
            for account, group in company_rows.groupby("gl_account", sort=False):
                cat = _account_category(account)
                if _is_bs_category(cat):
                    group_year = group["fiscal_year"].astype(int)
                    group_period = group["fiscal_period"].astype(int)
                    sub = group[(group_year < fy) | ((group_year == fy) & (group_period <= fp))]
                else:
                    sub = group[
                        (group["fiscal_year"].astype(int) == fy)
                        & (group["fiscal_period"].astype(int) <= fp)
                    ]
                debit = int(sub["_amount_debit_i"].sum())
                credit = int(sub["_amount_credit_i"].sum())
                od, oc = expected.get(str(account), (0, 0))
                net = od - oc + debit - credit
                expected[str(account)] = (net, 0) if net >= 0 else (0, -net)
            actual = {
                str(line["account_code"]): (
                    int(round(float(line.get("debit_balance", 0)))),
                    int(round(float(line.get("credit_balance", 0)))),
                )
                for line in tb.get("entries", [])
            }
            for account, exp in expected.items():
                act = actual.get(account, (0, 0))
                diff = abs(exp[0] - act[0]) + abs(exp[1] - act[1])
                max_diff = max(max_diff, diff)
                checked_lines += 1
                if diff > 1:
                    mismatches += 1
        if checked_lines == 0:
            findings.append(verdict("Gate 2", "M01", "BLOCKED", {"trial_balance_periods": len(tbs), "company_code_missing": True}, "TB must carry company_code for multi-company verification"))
        else:
            findings.append(verdict("Gate 2", "M01", "PASS" if mismatches == 0 else "FAIL", {"checked_lines": checked_lines, "mismatches": mismatches, "max_abs_diff_krw": max_diff}, "GL aggregate equals exported TB balances"))

        # M02/M03/M04/M06 use journal-derived roll-forward ledger state.
        periods = sorted(work[["company_code", "fiscal_year", "fiscal_period"]].drop_duplicates().itertuples(index=False, name=None))
        equation_bad = 0
        max_equation_diff = 0
        roll_bad = 0
        continuity_bad = 0
        normal_side_bad = 0
        contra_negative = 0
        pnl_negative = 0
        retained_deficit = 0
        other_equity_negative = 0
        normal_side_bad_by_account: dict[str, int] = {}
        checked_period_accounts = 0
        prior_closing: dict[tuple[str, str], int] = {}
        for company, fy, fp in periods:
            company = str(company)
            fy_i = int(fy)
            fp_i = int(fp)
            rows = work[(work["company_code"].astype(str) == company) & (work["fiscal_year"].astype(int) == fy_i) & (work["fiscal_period"].astype(int) == fp_i)]
            carried_accounts = {
                account
                for (prior_company, account), _closing in prior_closing.items()
                if prior_company == company
            }
            accounts = set(opening.get(company, {})) | set(rows["gl_account"].astype(str)) | carried_accounts
            assets = liabilities = equity = revenue = expenses = 0
            for account in accounts:
                cat = _account_category(account)
                opening_value = prior_closing.get((company, account), opening.get(company, {}).get(account, 0))
                debit = int(rows.loc[rows["gl_account"].astype(str).eq(account), "_amount_debit_i"].sum())
                credit = int(rows.loc[rows["gl_account"].astype(str).eq(account), "_amount_credit_i"].sum())
                if _is_credit_normal(account, coa_meta):
                    closing = opening_value - debit + credit
                else:
                    closing = opening_value + debit - credit
                if abs((opening_value + (credit - debit if _is_credit_normal(account, coa_meta) else debit - credit)) - closing) > 1:
                    roll_bad += 1
                if (company, account) in prior_closing and abs(opening_value - prior_closing[(company, account)]) > 1:
                    continuity_bad += 1
                prior_closing[(company, account)] = closing
                checked_period_accounts += 1
                debit_minus_credit = _debit_minus_credit_from_normal(account, closing, coa_meta)
                if cat in {"Cash", "Receivables", "Inventory", "FixedAssets"}:
                    assets += debit_minus_credit
                elif cat in {"Payables", "AccruedLiabilities", "LongTermDebt"}:
                    liabilities += -debit_minus_credit
                elif cat == "Equity":
                    equity += -debit_minus_credit
                elif cat in {"Revenue", "OtherIncome"}:
                    revenue += -debit_minus_credit
                elif cat in {"CostOfSales", "OperatingExpenses", "OtherExpenses"}:
                    expenses += debit_minus_credit
                if closing < -1:
                    if _is_contra_account(account, cat, coa_meta):
                        contra_negative += 1
                    elif cat in {"Revenue", "OtherIncome", "CostOfSales", "OperatingExpenses", "OtherExpenses"}:
                        pnl_negative += 1
                    elif account == "3200" or str(coa_meta.get(account, {}).get("sub_type", "")).lower() == "retained_earnings":
                        retained_deficit += 1
                    elif cat == "Equity":
                        other_equity_negative += 1
                        normal_side_bad_by_account[account] = normal_side_bad_by_account.get(account, 0) + 1
                    else:
                        normal_side_bad += 1
                        normal_side_bad_by_account[account] = normal_side_bad_by_account.get(account, 0) + 1
            equation_diff = assets - liabilities - equity - (revenue - expenses)
            max_equation_diff = max(max_equation_diff, abs(equation_diff))
            if abs(equation_diff) > 1:
                equation_bad += 1

        fs_path = dataset / "financial_reporting" / "financial_statements.json"
        if fs_path.exists():
            fs_data = json.loads(fs_path.read_text(encoding="utf-8"))
            bs_records = [rec for rec in fs_data if rec.get("statement_type") == "balance_sheet"]
            fs_bad = 0
            fs_max_diff = 0
            fs_checked = 0
            for rec in bs_records:
                items = {
                    str(item.get("line_code")): int(round(float(item.get("amount", 0) or 0)))
                    for item in rec.get("line_items", [])
                    if isinstance(item, dict)
                }
                if not {"BS-TA", "BS-TL", "BS-TE"}.issubset(items):
                    continue
                fs_checked += 1
                diff = abs(items["BS-TA"] - (items["BS-TL"] + items["BS-TE"]))
                fs_max_diff = max(fs_max_diff, diff)
                if diff > 1:
                    fs_bad += 1
            findings.append(verdict("Gate 2", "M02", "PASS" if fs_checked > 0 and fs_bad == 0 else "FAIL", {"periods_checked": fs_checked, "equation_bad_periods": fs_bad, "max_equation_diff_krw": fs_max_diff, "equation_formula": "financial_statements BS-TA = BS-TL + BS-TE"}, "ending accounting equation"))
        else:
            findings.append(verdict("Gate 2", "M02", "PASS" if equation_bad == 0 else "FAIL", {"periods_checked": len(periods), "equation_bad_periods": equation_bad, "max_equation_diff_krw": max_equation_diff, "equation_formula": "assets = liabilities + equity + current_ytd_income"}, "ending accounting equation"))
        findings.append(verdict("Gate 2", "M03", "PASS" if roll_bad == 0 else "FAIL", {"period_accounts_checked": checked_period_accounts, "roll_forward_bad": roll_bad}, "account roll-forward"))
        findings.append(verdict("Gate 2", "M04", "PASS" if continuity_bad == 0 else "FAIL", {"period_accounts_checked": checked_period_accounts, "continuity_bad": continuity_bad}, "prior closing equals current opening"))
        top_normal_side_bad = sorted(normal_side_bad_by_account.items(), key=lambda item: item[1], reverse=True)[:10]
        hard_negative_rate = normal_side_bad / max(checked_period_accounts, 1)
        m06_pass = other_equity_negative == 0 and hard_negative_rate <= 0.02
        findings.append(verdict("Gate 2", "M06", "PASS" if m06_pass else "MONITOR", {"period_accounts_checked": checked_period_accounts, "hard_negative_balance_count": normal_side_bad, "hard_negative_balance_rate": hard_negative_rate, "hard_negative_balance_rate_threshold": 0.02, "other_equity_negative_balance_count": other_equity_negative, "contra_negative_balance_count": contra_negative, "retained_earnings_deficit_count": retained_deficit, "income_statement_reverse_balance_count": pnl_negative, "top_hard_negative_accounts": dict(top_normal_side_bad)}, "normal balance direction"))

        closing = work[work["_is_closing"]]
        nonclosing = work[~work["_is_closing"]]
        years = nonclosing[["company_code", "fiscal_year"]].drop_duplicates()
        closing_bad = 0
        closing_checked = 0
        for company, fy in years.itertuples(index=False, name=None):
            sub = nonclosing[(nonclosing["company_code"].eq(company)) & (nonclosing["fiscal_year"].eq(fy))]
            pnl = 0
            for _, row in sub.iterrows():
                account = str(row["gl_account"])
                if account[:1] in {"4", "5", "6", "7", "8"}:
                    pnl += int(row["_amount_credit_i"] - row["_amount_debit_i"])
            cls = closing[(closing["company_code"].eq(company)) & (closing["fiscal_year"].eq(fy)) & (closing["gl_account"].astype(str).eq("3200"))]
            re_effect = int(cls["_amount_credit_i"].sum() - cls["_amount_debit_i"].sum())
            closing_checked += 1
            if abs(pnl - re_effect) > 1:
                closing_bad += 1
        findings.append(verdict("Gate 2", "M05", "PASS" if closing_checked > 0 and closing_bad == 0 else "FAIL", {"company_years_checked": closing_checked, "closing_bad": closing_bad}, "P&L closes to retained earnings"))

    recon_path = dataset / "balance" / "subledger_reconciliation.json"
    if not recon_path.exists():
        findings.append(verdict("Gate 2", "M07", "BLOCKED", {"missing": "balance/subledger_reconciliation.json"}, "subledger reconciliation required"))
    else:
        recon = json.loads(recon_path.read_text(encoding="utf-8"))
        diffs = [abs(float(item.get("difference", 0))) for item in recon if isinstance(item, dict)]
        statuses = [str(item.get("status", "")) for item in recon if isinstance(item, dict)]
        bad = sum(1 for diff in diffs if diff > 1.0)
        findings.append(verdict("Gate 2", "M07", "PASS" if bad == 0 and statuses else "FAIL", {"reconciliations": len(diffs), "bad_reconciliations": bad, "max_abs_diff_krw": max(diffs) if diffs else None, "statuses": dict(pd.Series(statuses).value_counts()) if statuses else {}}, "AR/AP/Inventory/FA subledger equals GL control"))

    return findings


def audit(dataset: Path) -> dict[str, Any]:
    df = load_journal(dataset)
    doc_head = df.drop_duplicates("document_id").copy()
    findings: list[dict[str, Any]] = []

    mutation_cols = [
        "mutation_base_event_type",
        "mutation_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "detection_surface_hints",
    ]
    normal_flags = {
        "is_fraud_true": int(df["is_fraud"].str.lower().eq("true").sum()),
        "is_anomaly_true": int(df["is_anomaly"].str.lower().eq("true").sum()),
        "fraud_type_nonblank": int(df["fraud_type"].str.strip().ne("").sum()),
        "anomaly_type_nonblank": int(df["anomaly_type"].str.strip().ne("").sum()),
    }
    mutation_nonblank = {
        col: int(df[col].str.strip().ne("").sum())
        for col in mutation_cols
        if col in df.columns
    }
    findings.append(
        verdict(
            "Gate 0",
            "O01",
            "PASS" if all(v == 0 for v in normal_flags.values()) and all(v == 0 for v in mutation_nonblank.values()) else "FAIL",
            {"normal_flags": normal_flags, "mutation_nonblank": mutation_nonblank},
            "normal-only label/provenance contamination check",
        )
    )

    bal = df.groupby("document_id", sort=False).agg(debit=("debit_amount", "sum"), credit=("credit_amount", "sum"))
    bal_i = df.assign(
        _debit_won=df["debit_amount"].round(0).astype("int64"),
        _credit_won=df["credit_amount"].round(0).astype("int64"),
    ).groupby("document_id", sort=False).agg(debit=("_debit_won", "sum"), credit=("_credit_won", "sum"))
    diff = (bal_i["debit"] - bal_i["credit"]).abs()
    imbalance_count = int((diff > 1).sum())
    findings.append(
        verdict(
            "Gate 0",
            "A01",
            "PASS" if imbalance_count == 0 else "FAIL",
            {"imbalance_count": imbalance_count, "max_abs_diff_krw": int(diff.max() if len(diff) else 0)},
            "document-level debit/credit balance in integer KRW",
        )
    )

    both = int(((df["debit_amount"] > 0) & (df["credit_amount"] > 0)).sum())
    zero = int(((df["debit_amount"] <= 0) & (df["credit_amount"] <= 0)).sum())
    findings.append(
        verdict(
            "Gate 0",
            "A02",
            "PASS" if both == 0 and zero == 0 else "FAIL",
            {"both_side_rows": both, "zero_side_rows": zero},
            "line side validity",
        )
    )

    sod_required = {"sod_violation", "sod_conflict_type"}
    sod_missing = sorted(sod_required - set(doc_head.columns))
    if sod_missing:
        findings.append(
            verdict(
                "Gate 0",
                "E05_SOD_DIRECT_MARKER",
                "BLOCKED",
                {"missing_required_columns": sod_missing},
                "normal baseline direct SoD markers must be measurable",
            )
        )
    else:
        sod_true = _truthy(doc_head["sod_violation"])
        sod_conflict_nonblank = doc_head["sod_conflict_type"].fillna("").astype(str).str.strip().ne("")
        self_approval = doc_head["approved_by"].fillna("").astype(str).str.strip().ne("") & (
            doc_head["created_by"].fillna("").astype(str).str.strip()
            == doc_head["approved_by"].fillna("").astype(str).str.strip()
        )
        non_self_sod_docs = int((sod_true & ~self_approval).sum())
        self_approval_without_marker_docs = int((self_approval & ~sod_true).sum())
        conflict_counts = (
            doc_head.loc[sod_conflict_nonblank, "sod_conflict_type"]
            .astype(str)
            .str.strip()
            .value_counts()
            .head(10)
            .to_dict()
        )
        sod_true_docs = int(sod_true.sum())
        conflict_docs = int(sod_conflict_nonblank.sum())
        total_docs = int(len(doc_head))
        findings.append(
            verdict(
                "Gate 0",
                "E05_SOD_DIRECT_MARKER",
                "PASS"
                if sod_true_docs == 0
                and conflict_docs == 0
                and non_self_sod_docs == 0
                else "FAIL",
                {
                    "documents_checked": total_docs,
                    "sod_violation_true_docs": sod_true_docs,
                    "sod_violation_true_rate": (sod_true_docs / total_docs) if total_docs else 0.0,
                    "sod_conflict_type_nonblank_docs": conflict_docs,
                    "non_self_sod_docs": non_self_sod_docs,
                    "self_approval_without_direct_marker_docs": self_approval_without_marker_docs,
                    "top_sod_conflict_type": conflict_counts,
                },
                "normal baseline may contain self-approval context, but direct SoD violation markers are reserved for abnormal overlays",
            )
        )

    i_status, i_metric = _document_reference_structure_metrics(df, doc_head)
    findings.append(
        verdict(
            "Gate 1",
            "I01_I03_I04",
            i_status,
            i_metric,
            "document number uniqueness/number range and same-role reference reuse",
        )
    )
    dup_status, dup_metric = _duplicate_detector_same_document_pair_metrics(df)
    findings.append(
        verdict(
            "Gate 1",
            "I05_DUPLICATE_ARTIFACT_DOCUMENT_SCOPE",
            dup_status,
            dup_metric,
            "DuplicateDetector retained pair artifact must not contain same-document line pairs",
        )
    )

    p2p = df[df["semantic_scenario_id"].eq("P2P_VENDOR_INVOICE")]
    text_flags: dict[str, int] = {}
    text_metrics: dict[str, Any] = {
        "p2p_checked_docs": {},
        "p2p_bad_docs": {},
        "h2r_payment_checked_docs": 0,
        "h2r_payment_bad_docs": 0,
        "ic_checked_docs": 0,
        "ic_bad_docs": 0,
    }
    p2p_families = {
        "VendorService": ("vendor_service_text_off_domain", "PROFESSIONAL_FEES", re.compile(r"전문|자문|용역|매입세액")),
        "VendorOfficeSupplies": ("vendor_office_text_off_domain", "OFFICE_SUPPLIES_PURCHASE", re.compile(r"사무|문구|복사|토너|오피스|매입세액")),
        "VendorRawMaterial": ("vendor_rawmaterial_text_off_domain", "RAW_MATERIAL_PURCHASE", re.compile(r"원자.?재|원재료|원자\s*입고|자재|재료|매입세액")),
        "VendorUtilities": ("vendor_utilities_text_off_domain", "UTILITIES", re.compile(r"전.?력|력.?전|전.?요금|력.?요금|수.?도|통.?신|전력|수도|통신|매입세액")),
    }
    tax_subtypes = {"INPUT_TAX_RECEIVABLE", "OUTPUT_TAX_PAYABLE"}
    for cp, (flag, expected_family, pattern) in p2p_families.items():
        bad_docs: set[str] = set()
        sub = p2p[p2p["counterparty_type"].eq(cp)]
        checked_docs = int(sub["document_id"].nunique())
        text_metrics["p2p_checked_docs"][cp] = checked_docs
        for doc, group in sub.groupby("document_id", sort=False):
            texts = [
                str(row.line_text)
                for row in group.itertuples()
                if str(row.line_text).strip() and str(row.semantic_account_subtype) not in tax_subtypes
            ]
            families = {
                str(row.line_text_family)
                for row in group.itertuples()
                if str(row.semantic_account_subtype) not in tax_subtypes
            }
            joined = " ".join(texts)
            if expected_family not in families and joined and not pattern.search(joined):
                bad_docs.add(doc)
        if bad_docs:
            text_flags[flag] = len(bad_docs)
        text_metrics["p2p_bad_docs"][cp] = len(bad_docs)

    h2r_payment_bad = 0
    pay_pattern = re.compile(
        r"이체|이\s*체|급여\s*체|급여|원천세|반제|납부|지급|payment|payroll payment|clearing|tax payment",
        re.I,
    )
    wrong_pattern = re.compile(r"fx revaluation|depreciation|CAPEX|고객|매출|원자재|전력요금|자문수수료", re.I)
    h2r_payment_docs = df[df["semantic_scenario_id"].eq("H2R_PAYROLL_PAYMENT")]
    text_metrics["h2r_payment_checked_docs"] = int(h2r_payment_docs["document_id"].nunique())
    for _, group in h2r_payment_docs.groupby("document_id", sort=False):
        joined = " ".join(str(x) for x in group["line_text"] if str(x).strip())
        if joined and (not pay_pattern.search(joined) or wrong_pattern.search(joined)):
            h2r_payment_bad += 1
    if h2r_payment_bad:
        text_flags["h2r_payment_text_off_domain"] = h2r_payment_bad
    text_metrics["h2r_payment_bad_docs"] = h2r_payment_bad

    ic_bad_docs: set[str] = set()
    ic_docs = df[df["semantic_scenario_id"].eq("IC_INTERCOMPANY_SALE")]
    allowed_ic_subtypes = {
        "COGS_MATERIAL",
        "IC_PAYABLE",
        "IC_RECEIVABLE",
        "IC_REVENUE",
        "IC_SERVICE_EXPENSE",
        "INTERCOMPANY_REVENUE",
        "INTEREST_EXPENSE",
        "OPEX_INTERCOMPANY_SERVICE",
        "PRODUCT_REVENUE",
        "RETAINED_EARNINGS",
        "SERVICE_REVENUE",
        "TAX_RECEIVABLE",
    }
    text_metrics["ic_checked_docs"] = int(ic_docs["document_id"].nunique())
    for doc, group in ic_docs.groupby("document_id", sort=False):
        document_types = set(group["document_type"].fillna("").astype(str).str.strip())
        processes = set(group["business_process"].fillna("").astype(str).str.strip())
        counterparty_types = set(group["counterparty_type"].fillna("").astype(str).str.strip())
        line_families = set(group["line_text_family"].fillna("").astype(str).str.strip())
        subtypes = set(group["semantic_account_subtype"].fillna("").astype(str).str.strip())
        has_blank_semantic = "" in line_families or "" in subtypes
        has_off_domain_subtype = bool(subtypes - allowed_ic_subtypes)
        if (
            document_types != {"IC"}
            or processes != {"Intercompany"}
            or not counterparty_types.issubset({"IntercompanyAffiliate", "RELATED_PARTY", "RelatedParty"})
            or not line_families.issubset(
                {
                    "INTERCOMPANY_SALE",
                    "related_party_service_revenue",
                    "related_party_service_charge",
                }
            )
            or has_blank_semantic
            or has_off_domain_subtype
        ):
            ic_bad_docs.add(str(doc))
    if ic_bad_docs:
        text_flags["ic_line_semantic_off_domain"] = len(ic_bad_docs)
    text_metrics["ic_bad_docs"] = len(ic_bad_docs)
    text_metrics["violation_flags"] = text_flags
    findings.append(
        verdict(
            "Gate 1",
            "B15_B16_H04",
            "PASS" if not text_flags else "FAIL",
            text_metrics,
            "counterparty/account/text/document coherence",
        )
    )

    tax_checks: dict[str, Any] = {}
    tax_fail = False
    df["abs_amount"] = df["debit_amount"] + df["credit_amount"]
    checks = [
        (
            "P2P_VENDOR_INVOICE",
            "INPUT_TAX_RECEIVABLE",
            {
                "OPEX_PROFESSIONAL_FEES",
                "OPEX_OFFICE_SUPPLIES",
                "OPEX_UTILITIES",
                "COGS_MATERIAL",
                "INVENTORY",
                "RAW_MATERIALS",
                "FIXED_ASSET",
            },
        ),
        ("O2C_CUSTOMER_INVOICE", "OUTPUT_TAX_PAYABLE", {"PRODUCT_REVENUE", "SERVICE_REVENUE"}),
    ]
    for scenario, tax_subtype, base_subtypes in checks:
        sub = df[df["semantic_scenario_id"].eq(scenario)].copy()
        sub["tax_amt"] = sub["abs_amount"].where(sub["semantic_account_subtype"].eq(tax_subtype), 0)
        sub["base_amt"] = sub["abs_amount"].where(sub["semantic_account_subtype"].isin(base_subtypes), 0)
        agg = sub.groupby("document_id", sort=False)[["tax_amt", "base_amt"]].sum()
        tax_docs = agg[agg["tax_amt"] > 0].copy()
        tax_docs["ratio"] = tax_docs["tax_amt"] / tax_docs["base_amt"].replace(0, pd.NA)
        bad = tax_docs[(tax_docs["base_amt"] <= 0) | (tax_docs["ratio"] > 0.15)]
        tax_checks[scenario] = {
            "tax_docs": int(len(tax_docs)),
            "bad_ratio_gt_15pct_or_no_base": int(len(bad)),
            "no_base": int((tax_docs["base_amt"] <= 0).sum()),
            "ratio_p50": None if tax_docs.empty else float(tax_docs["ratio"].dropna().quantile(0.5)),
            "ratio_p95": None if tax_docs.empty else float(tax_docs["ratio"].dropna().quantile(0.95)),
        }
        if len(tax_docs) == 0 or len(bad) > 0:
            tax_fail = True
    findings.append(
        verdict(
            "Gate 1",
            "A07_L02_L03",
            "PASS" if not tax_fail else "FAIL",
            tax_checks,
            "VAT GL line existence and base/tax ratio; empty tax population is not PASS",
        )
    )

    l06_metrics: dict[str, Any] = {}
    if "tax_treatment" not in df.columns:
        l06_status = "BLOCKED"
        l06_metrics["missing_required_column"] = "tax_treatment"
    else:
        treatment_counts = df["tax_treatment"].value_counts().to_dict()
        l06_metrics["treatment_counts"] = {str(k): int(v) for k, v in treatment_counts.items()}
        required_treatments = {"taxable_10", "zero_rated_export", "exempt", "non_taxable", "import_vat"}
        missing_treatments = sorted(required_treatments - set(treatment_counts))

        vat_subtypes = {"INPUT_TAX_RECEIVABLE", "OUTPUT_TAX_PAYABLE"}
        vat_line_docs = set(df[df["semantic_account_subtype"].isin(vat_subtypes)]["document_id"])
        doc_tax = df.groupby("document_id", sort=False).agg(
            treatment=("tax_treatment", lambda s: sorted(set(x for x in s if str(x).strip()))),
            supporting=("supporting_doc_type", "first"),
            tax_codes=("tax_code", lambda s: sorted(set(x for x in s if str(x).strip()))),
            tax_amount=("tax_amount", "sum"),
        )
        doc_tax["has_vat_line"] = doc_tax.index.isin(vat_line_docs)

        bad_taxable = doc_tax[
            doc_tax["treatment"].map(lambda x: "taxable_10" in x)
            & ((doc_tax["supporting"] != "세금계산서") | (~doc_tax["has_vat_line"]) | (doc_tax["tax_amount"] <= 0))
        ]
        bad_import = doc_tax[
            doc_tax["treatment"].map(lambda x: "import_vat" in x)
            & ((doc_tax["supporting"] != "수입장") | (~doc_tax["has_vat_line"]) | (doc_tax["tax_amount"] <= 0))
        ]
        bad_zero = doc_tax[
            doc_tax["treatment"].map(lambda x: "zero_rated_export" in x)
            & ((doc_tax["supporting"] != "수출신고필증") | (doc_tax["has_vat_line"]) | (doc_tax["tax_amount"] != 0))
        ]
        bad_exempt = doc_tax[
            doc_tax["treatment"].map(lambda x: "exempt" in x)
            & ((doc_tax["supporting"] != "계산서") | (doc_tax["has_vat_line"]) | (doc_tax["tax_amount"] != 0))
        ]
        bad_non_taxable = doc_tax[
            doc_tax["treatment"].map(lambda x: "non_taxable" in x)
            & (doc_tax["has_vat_line"] | (doc_tax["tax_amount"] != 0) | doc_tax["tax_codes"].map(bool))
        ]
        mixed_treatment_docs = int(doc_tax["treatment"].map(len).gt(1).sum())
        l06_metrics.update(
            {
                "missing_treatments": missing_treatments,
                "bad_taxable_docs": int(len(bad_taxable)),
                "bad_import_vat_docs": int(len(bad_import)),
                "bad_zero_rated_docs": int(len(bad_zero)),
                "bad_exempt_docs": int(len(bad_exempt)),
                "bad_non_taxable_docs": int(len(bad_non_taxable)),
                "mixed_treatment_docs": mixed_treatment_docs,
            }
        )
        l06_status = (
            "PASS"
            if not missing_treatments
            and not len(bad_taxable)
            and not len(bad_import)
            and not len(bad_zero)
            and not len(bad_exempt)
            and not len(bad_non_taxable)
            and mixed_treatment_docs == 0
            else "FAIL"
        )
    findings.append(
        verdict(
            "Gate 1",
            "L06",
            l06_status,
            l06_metrics,
            "tax treatment must follow transaction archetype/evidence, not random/reference markers",
        )
    )

    stats_path = dataset / "data_quality_stats.json"
    dq_stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}
    total_rows = len(df)
    total_docs = len(doc_head)
    true_noise = {
        "missing_field_rate_per_row": (dq_stats.get("missing_values", {}).get("total_missing", 0) / max(total_rows, 1)),
        "text_format_variation_rate_per_row": (dq_stats.get("format_variations", {}).get("text_variations", 0) / max(total_rows, 1)),
        "typo_rate_per_row": (dq_stats.get("typos", {}).get("total_typos", 0) / max(total_rows, 1)),
        "records_with_issues_rate_per_doc": (dq_stats.get("records_with_issues", 0) / max(dq_stats.get("total_records", total_docs), 1)),
    }
    noise_status = "PASS"
    if true_noise["records_with_issues_rate_per_doc"] > 0.15 or true_noise["text_format_variation_rate_per_row"] > 0.05:
        noise_status = "FAIL"
    findings.append(
        verdict(
            "Gate 1",
            "G08_G09",
            noise_status,
            true_noise,
            "true noise rate from generator stats; lexical Latin scans are diagnostic only",
        )
    )

    amount = df[["debit_amount", "credit_amount"]].max(axis=1)
    positive = amount[amount > 0]
    round_10k_rate = float(((positive % 10_000) == 0).mean()) if len(positive) else 0.0
    top_exact_share = float(positive.value_counts(normalize=True).head(1).iloc[0]) if len(positive) else 0.0
    amount_status = "PASS" if round_10k_rate <= 0.25 and top_exact_share <= 0.02 else "FAIL"
    findings.append(
        verdict(
            "Gate 2",
            "C03_C09_C10",
            amount_status,
            {"round_10k_rate": round_10k_rate, "top_exact_share": top_exact_share},
            "amount round-grid dominance and exact amount concentration",
        )
    )

    marker_findings: list[dict[str, Any]] = []
    allowed_single_scenario_columns = {
        "semantic_scenario_id",
        "scenario_id",
        "event_type",
        "business_process",
        "document_type",
        "ledger",
        "currency",
        "exchange_rate",
        "gl_account",
        "counterparty_type",
        "semantic_account_subtype",
        "debit_account_subtype",
        "credit_account_subtype",
        "line_text_family",
        "supporting_doc_type",
        "tax_treatment",
        "line_number",
        "source",
        "is_synthetic",
        "is_mutated",
        "is_fraud",
        "is_anomaly",
        "is_intercompany",
    }
    excluded_marker_columns = {
        "document_id",
        "document_number",
        "reference",
        "header_text",
        "line_text",
        "posting_date",
        "document_date",
        "approval_date",
        "delivery_date",
        "ip_address",
        "batch_id",
        "job_id",
        "batch_type",
        "original_document_id",
        "reversal_document_id",
        "reversal_type",
        "reversal_reason",
        "reversal_reason_code",
    }

    scenario_by_doc = doc_head.set_index("document_id")["semantic_scenario_id"].to_dict()
    for column in df.columns:
        if column in allowed_single_scenario_columns or column in excluded_marker_columns:
            continue
        if df[column].dtype != object:
            continue
        work = df[["document_id", column]].drop_duplicates()
        work = work[work[column].astype(str).str.strip().ne("")]
        if column == "trading_partner":
            company_values = set(df["company_code"].fillna("").astype(str).str.strip()) if "company_code" in df.columns else set()
            structural_related_parties = {"C002", "C003"}
            work = work[
                ~work[column]
                .astype(str)
                .str.strip()
                .isin(company_values | structural_related_parties)
            ]
        if work.empty:
            continue
        work["scenario"] = work["document_id"].map(scenario_by_doc).fillna("")
        for value, group in work.groupby(column, sort=False):
            n_docs = int(group["document_id"].nunique())
            if n_docs < 100:
                continue
            scenario_counts = group["scenario"].value_counts()
            top_scenario_share = float(scenario_counts.iloc[0] / max(n_docs, 1))
            if top_scenario_share >= 0.98:
                marker_findings.append(
                    {
                        "type": "single_value_single_scenario",
                        "column": column,
                        "value": str(value)[:80],
                        "documents": n_docs,
                        "top_scenario": str(scenario_counts.index[0]),
                        "top_scenario_share": top_scenario_share,
                    }
                )

    if "posting_date" in df.columns:
        exact_ts = doc_head["posting_date"].astype(str).value_counts()
        for value, count in exact_ts.head(10).items():
            if int(count) >= 50:
                marker_findings.append(
                    {
                        "type": "exact_timestamp_cluster",
                        "column": "posting_date",
                        "value": str(value),
                        "documents": int(count),
                    }
                )

    if {"semantic_scenario_id", "debit_amount", "credit_amount"}.issubset(df.columns):
        df["_marker_amount"] = df[["debit_amount", "credit_amount"]].max(axis=1)
        for scenario, group in df[df["_marker_amount"] > 0].groupby("semantic_scenario_id", sort=False):
            n_rows = int(len(group))
            if n_rows < 500:
                continue
            top_counts = group["_marker_amount"].value_counts()
            top_count = int(top_counts.iloc[0])
            top_share = float(top_count / n_rows)
            if top_count >= 200 and top_share >= 0.20:
                marker_findings.append(
                    {
                        "type": "scenario_amount_dominance",
                        "column": "debit_amount/credit_amount",
                        "value": float(top_counts.index[0]),
                        "scenario": str(scenario),
                        "rows": n_rows,
                        "top_count": top_count,
                        "top_share": top_share,
                    }
                )
        df.drop(columns=["_marker_amount"], inplace=True)

    marker_findings = sorted(marker_findings, key=lambda item: item.get("documents", item.get("top_count", 0)), reverse=True)
    findings.append(
        verdict(
            "Diagnostic",
            "O02",
            "PASS" if not marker_findings else "FAIL",
            {
                "high_risk_marker_count": len(marker_findings),
                "sample_findings": marker_findings[:20],
                "rules": {
                    "single_value_single_scenario": "non-structural value appears in >=100 documents and >=98% one scenario",
                    "exact_timestamp_cluster": "exact posting timestamp appears in >=50 documents",
                    "scenario_amount_dominance": "one exact amount is >=20% of rows in a scenario with >=500 rows",
                },
            },
            "all-column synthetic marker scan for generator fingerprints",
        )
    )

    company_codes = set(df["company_code"].fillna("").astype(str).str.strip()) if "company_code" in df.columns else set()
    has_ic_required = all(col in df.columns for col in ["is_intercompany", "company_code", "trading_partner", "gl_account"])
    if not has_ic_required:
        missing = [col for col in ["is_intercompany", "company_code", "trading_partner", "gl_account"] if col not in df.columns]
        for test_id, note in [
            ("K01", "single-company journal scope"),
            ("K02", "normal related-party IC background required"),
            ("K03", "normal IC GL prefix population required"),
            ("K04", "normal IC dates must be plausible"),
            ("K05", "company-code partners allowed only for related-party IC rows"),
            ("K06", "no company-node graph cycle background"),
            ("K07", "normal IC direction population should not be one-sided"),
        ]:
            findings.append(verdict("Gate 1" if test_id <= "K05" else "Gate 2", test_id, "BLOCKED", {"missing_required_columns": missing}, note))
    else:
        primary_company = "C001"
        ic_mask = _truthy(df["is_intercompany"])
        ic_df = df[ic_mask].copy()
        ic_doc_count = int(ic_df["document_id"].nunique())
        ic_row_count = int(len(ic_df))
        partner_all = df["trading_partner"].fillna("").astype(str).str.strip()
        company_partner_rows = int(partner_all.isin(company_codes | {"C002", "C003"}).sum())
        related_surface = (
            df["counterparty_type"].fillna("").astype(str).str.contains("Intercompany|RELATED_PARTY|Related", case=False, regex=True)
            | df["semantic_scenario_id"].fillna("").astype(str).str.contains("IC_|INTERCOMPANY|RELATED", case=False, regex=True)
            | df["business_process"].fillna("").astype(str).str.upper().eq("IC")
            | df["document_type"].fillna("").astype(str).str.upper().eq("IC")
        )
        related_surface_docs = int(df[related_surface]["document_id"].nunique())
        k01_metric = {
            "company_codes": sorted(company_codes),
            "expected_company_codes": [primary_company],
            "company_code_count": len(company_codes),
            "total_documents": int(df["document_id"].nunique()),
            "total_rows": int(len(df)),
        }
        k01_pass = company_codes == {primary_company}
        findings.append(verdict("Gate 1", "K01", "PASS" if k01_pass else "FAIL", k01_metric, "single legal-entity journal scope"))

        pair_map = _load_ic_pair_map()
        rec_prefixes = set(pair_map)
        pay_prefixes = set(pair_map.values())
        rec_rows = int((_starts_with_any(ic_df["gl_account"], rec_prefixes)).sum())
        pay_rows = int((_starts_with_any(ic_df["gl_account"], pay_prefixes)).sum())
        pairmap_rows = rec_rows + pay_rows
        k02_metric = {
            "ic_row_count": ic_row_count,
            "ic_doc_count": ic_doc_count,
            "related_surface_docs": related_surface_docs,
            "receivable_prefix_rows_in_ic": rec_rows,
            "payable_prefix_rows_in_ic": pay_rows,
            "pair_map_rows_in_ic": pairmap_rows,
        }
        ic_row_share = ic_row_count / max(len(df), 1)
        k02_metric["ic_row_share"] = ic_row_share
        k02_metric["expected_ic_row_share_range"] = [0.0005, 0.02]
        k02_pass = (
            ic_doc_count >= 50
            and 0.0005 <= ic_row_share <= 0.02
            and related_surface_docs >= ic_doc_count
            and pairmap_rows > 0
        )
        findings.append(verdict("Gate 1", "K02", "PASS" if k02_pass else "FAIL", k02_metric, "single-company normal must contain low-volume related-party IC traces without adding extra ledger companies"))

        recon = _ic_reconciliation_metrics(df, pair_map)
        k03_metric = dict(recon)
        k03_metric.update({"receivable_prefix_rows": rec_rows, "payable_prefix_rows": pay_rows})
        k03_pass = rec_rows > 0 and pay_rows > 0
        findings.append(verdict("Gate 1", "K03", "PASS" if k03_pass else "FAIL", k03_metric, "normal related-party IC must include both receivable/revenue and payable/cost traces"))

        ic_dates_missing = 0
        if not ic_df.empty:
            ic_dates_missing = int(
                ic_df[["posting_date", "document_date"]]
                .fillna("")
                .astype(str)
                .apply(lambda col: col.str.strip().eq(""))
                .any(axis=1)
                .sum()
            )
        k04_metric = dict(recon)
        k04_metric["ic_date_missing_rows"] = ic_dates_missing
        k04_pass = ic_row_count > 0 and ic_dates_missing == 0 and recon["close_lag_exceeded_pairs"] == 0
        findings.append(verdict("Gate 1", "K04", "PASS" if k04_pass else "FAIL", k04_metric, "normal related-party IC timing must have populated dates and no stale close-lag pattern"))

        partner_values = df["trading_partner"].fillna("").astype(str).str.strip()
        company_partner_mask = partner_values.isin(company_codes | {"C002", "C003"})
        company_partner_non_ic_rows = int((company_partner_mask & ~ic_mask).sum())
        k05_metric = {
            "company_codes": sorted(company_codes),
            "company_code_partner_rows": company_partner_rows,
            "ic_prefixed_partner_rows": int(partner_values.str.match(r"^IC-").sum()),
            "self_company_partner_rows": int(partner_values.eq(primary_company).sum()),
            "company_code_partner_non_ic_rows": company_partner_non_ic_rows,
            "allowed_related_party_partners": ["C002", "C003"],
        }
        k05_pass = (
            company_partner_rows > 0
            and company_partner_non_ic_rows == 0
            and k05_metric["self_company_partner_rows"] == 0
            and k05_metric["ic_prefixed_partner_rows"] == 0
        )
        findings.append(verdict("Gate 1", "K05", "PASS" if k05_pass else "FAIL", k05_metric, "company-code partners are allowed only as related-party trading_partner values on IC rows"))

        cycle_metrics = _ic_cycle_metrics(df)
        k06_pass = bool(cycle_metrics.get("networkx_available", False)) and int(cycle_metrics.get("cycle_instance_count", 0)) == 0
        findings.append(verdict("Gate 2", "K06", "PASS" if k06_pass else "FAIL", cycle_metrics, "single-company normal must not contain company-node graph cycles"))

        asym = _ic_direction_asymmetry_metrics(df)
        k07_pass = int(asym["direction_pair_count"]) > 0 and float(asym["high_asymmetry_rate"]) <= 0.75
        findings.append(verdict("Gate 2", "K07", "PASS" if k07_pass else "FAIL", asym, "normal related-party IC should have a directional population without being entirely one-sided"))

    k08_status, k08_metric = _single_company_sidecar_metrics(dataset)
    findings.append(
        verdict(
            "Gate 1",
            "K08",
            k08_status,
            k08_metric,
            "single-company scope must also hold in master/flow/subledger/balance sidecars",
        )
    )

    line_counts = df.groupby("document_id").size()
    high_line_docs = int((line_counts >= 100).sum())
    has_batch_fields = all(col in df.columns for col in ["batch_id", "job_id", "batch_type"])
    batch_metrics: dict[str, Any] = {
        "max_line_count": int(line_counts.max()),
        "high_line_docs_ge_100": high_line_docs,
        "min_expected_high_line_docs_ge_100": 60,
        "has_batch_fields": has_batch_fields,
    }
    if has_batch_fields:
        high_doc_ids = set(line_counts[line_counts >= 100].index.astype(str))
        high_rows = doc_head[doc_head["document_id"].isin(high_doc_ids)]
        missing_batch_meta = int(
            high_rows[["batch_id", "job_id", "batch_type"]]
            .apply(lambda col: col.astype(str).str.strip().eq(""))
            .any(axis=1)
            .sum()
        )
        batch_metrics["missing_batch_metadata_docs"] = missing_batch_meta
        batch_metrics["batch_type_counts"] = high_rows["batch_type"].value_counts().to_dict()
    if not has_batch_fields:
        j08_status = "BLOCKED"
    elif high_line_docs < batch_metrics["min_expected_high_line_docs_ge_100"]:
        j08_status = "FAIL"
    elif batch_metrics.get("missing_batch_metadata_docs", 0) > 0:
        j08_status = "FAIL"
    else:
        j08_status = "PASS"
    findings.append(
        verdict(
            "Gate 1",
            "J08",
            j08_status,
            batch_metrics,
            "high-line-count batch explainability; missing batch metadata is BLOCKED",
        )
    )
    j04_j07_status, j04_j07_metric = _reversal_link_metrics(df, doc_head)
    findings.append(
        verdict(
            "Gate 1",
            "J04_J07",
            j04_j07_status,
            j04_j07_metric,
            "normal reversal entries must carry original-document links and net to zero by GL account",
        )
    )

    findings.extend(_balance_metrics(df, dataset))
    coa_meta = _load_coa_meta(dataset)
    p01_status, p01_metric = _company_year_pnl(df, coa_meta)
    findings.append(
        verdict(
            "Gate 2",
            "M11",
            p01_status,
            p01_metric,
            "company-year P&L ratio realism: revenue, COGS, SGA, interest, tax must be economically plausible",
        )
    )
    coa_status, coa_metric = _coa_prefix_semantic_metrics(df, coa_meta)
    findings.append(
        verdict(
            "Gate 1",
            "B18",
            coa_status,
            coa_metric,
            "account code prefix must match account type and semantic subtype",
        )
    )
    fs_status, fs_metric = _financial_statement_export_metrics(dataset)
    findings.append(
        verdict(
            "Gate 2",
            "M12",
            fs_status,
            fs_metric,
            "exported financial statements must have positive revenue, COGS below revenue, and GL rollup mappings",
        )
    )
    dep_status, dep_metric = _depreciation_net_metrics(df, coa_meta)
    findings.append(
        verdict(
            "Gate 2",
            "M13",
            dep_status,
            dep_metric,
            "depreciation and amortization expense must have positive net P&L impact by company-year",
        )
    )
    b17_status, b17_metric = _archetype_coverage_metrics(df, doc_head, dataset)
    findings.append(
        verdict(
            "Gate 1",
            "B17",
            b17_status,
            b17_metric,
            "transaction archetype coverage and joint tuple coherence",
        )
    )
    p01_rows = _p01_sample_rows(df)
    findings.append(
        verdict(
            "Diagnostic",
            "P01",
            "INFO",
            {
                "fixed_seed": 20260605,
                "stratification": ["semantic_scenario_id", "business_process", "document_type", "source"],
                "sample_documents": len(p01_rows),
                "sample_scope": "diagnostic only; no pass/fail authority",
            },
            "expert/LLM fixed-seed stratified sample review artifact",
        )
    )
    findings.extend(_section9_diagnostics(df))
    from tools.scripts.normal_new_account_realism_gate_20260610 import new_account_findings

    findings.extend(new_account_findings(df))

    summary: dict[str, int] = {}
    for item in findings:
        summary[item["verdict"]] = summary.get(item["verdict"], 0) + 1

    return {
        "dataset": dataset.name,
        "documents": int(doc_head["document_id"].nunique()),
        "rows": int(len(df)),
        "summary": summary,
        "findings": findings,
        "p01_samples": p01_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--md-out", type=Path, required=True)
    args = parser.parse_args()

    result = _json_safe(audit(args.dataset))
    p01_samples = result.pop("p01_samples", [])
    sample_json = args.json_out.with_name(args.json_out.stem + "_p01_samples.json")
    sample_csv = args.json_out.with_name(args.json_out.stem + "_p01_samples.csv")
    sample_json.write_text(json.dumps(p01_samples, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(p01_samples).to_csv(sample_csv, index=False, encoding="utf-8-sig")
    for finding in result["findings"]:
        if finding["test_id"] == "P01":
            finding["metric"]["sample_json"] = str(sample_json)
            finding["metric"]["sample_csv"] = str(sample_csv)
    args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Normal Data Realism Verifier",
        f"- dataset: `{result['dataset']}`",
        f"- documents: {result['documents']:,}",
        f"- rows: {result['rows']:,}",
        f"- summary: {result['summary']}",
        "",
        "| gate | test_id | verdict | metric | notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for finding in result["findings"]:
        metric = json.dumps(finding["metric"], ensure_ascii=False)
        lines.append(
            f"| {finding['gate']} | {finding['test_id']} | {finding['verdict']} | `{metric}` | {finding['notes']} |"
        )
    args.md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
