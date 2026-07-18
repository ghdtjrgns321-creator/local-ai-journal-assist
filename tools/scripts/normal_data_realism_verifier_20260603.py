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

from src.detection.source_trust import (  # noqa: E402
    AUTOMATED_SOURCE_TOKENS,
    trusted_automated_mask,
)
from tools.scripts.normal_realism_account_checks import run_account_checks  # noqa: E402

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


# 항등식/자기검사 게이트 — 판정 참조 제외 (2026-07-15 판정, docs/0716/PLAN.md §3 S1 게이트 정비).
# M03/M04는 같은 지역변수를 재계산해 비교하므로 어떤 데이터로도 FAIL이 불가하고,
# M01/M07도 동류로 판정됨(계약 e5adea09 §Unit 2). PASS로 세면 hollow-PASS가 되므로
# INFO로 강등한다. BLOCKED는 강등하지 않는다(입력 부재 사실은 그대로 보고).
IDENTITY_EXCLUDED_TESTS = {"M01", "M03", "M04", "M07"}


def verdict(
    gate: str, test_id: str, status: str, metric: dict[str, Any], notes: str
) -> dict[str, Any]:
    if test_id in IDENTITY_EXCLUDED_TESTS and status in ("PASS", "FAIL"):
        notes = f"[판정 제외 — 항등식 검사, 원판정 {status}] {notes}"
        status = "INFO"
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


def _automated_source_identity_metrics(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    required = ["source", "batch_id", "job_id", "posting_date"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        return "BLOCKED", {"missing_required_columns": missing}

    source = df["source"].fillna("").astype(str).str.strip().str.lower()
    automated = source.isin(AUTOMATED_SOURCE_TOKENS)
    human = source.isin({"manual", "adjustment"})
    batch_filled = df["batch_id"].fillna("").astype(str).str.strip().ne("")
    job_filled = df["job_id"].fillna("").astype(str).str.strip().ne("")
    auto_rows = int(automated.sum())
    human_rows = int(human.sum())
    auto_both = int((automated & batch_filled & job_filled).sum())
    auto_missing_either = int((automated & ~(batch_filled & job_filled)).sum())
    human_either = int((human & (batch_filled | job_filled)).sum())
    trusted_auto = trusted_automated_mask(df)
    trusted_auto_rows = int((automated & trusted_auto).sum())
    trusted_auto_rate = float(trusted_auto_rows / auto_rows) if auto_rows else 0.0
    auto_both_rate = float(auto_both / auto_rows) if auto_rows else 0.0
    human_either_rate = float(human_either / human_rows) if human_rows else 0.0
    metric = {
        "automated_source_tokens": sorted(AUTOMATED_SOURCE_TOKENS),
        "auto_rows": auto_rows,
        "auto_both_filled_rows": auto_both,
        "auto_missing_either_rows": auto_missing_either,
        "auto_both_filled_rate": auto_both_rate,
        "human_rows": human_rows,
        "human_either_filled_rows": human_either,
        "human_either_filled_rate": human_either_rate,
        "trusted_automated_rows": trusted_auto_rows,
        "trusted_automated_rate": trusted_auto_rate,
        "trusted_automated_min_rate": 0.90,
    }
    status = (
        "PASS"
        if auto_rows > 0
        and auto_missing_either == 0
        and human_either == 0
        and trusted_auto_rate >= 0.90
        else "FAIL"
    )
    return status, metric


def _load_ic_pair_map() -> dict[str, str]:
    try:
        import yaml

        raw = (
            yaml.safe_load((ROOT / "config" / "audit_rules.yaml").read_text(encoding="utf-8")) or {}
        )
        pairs = raw.get("patterns", {}).get("intercompany", {}).get("pairs", [])
        return {
            str(item["receivable"]): str(item["payable"])
            for item in pairs
            if "receivable" in item and "payable" in item
        }
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
    rec_g = (
        rec.groupby(group_cols, dropna=False)
        .agg(
            rec_amount=("debit_amount", "sum"),
            rec_date=("posting_date", "min"),
            rec_rows=("document_id", "count"),
        )
        .reset_index()
    )
    pay_g = (
        pay.groupby(group_cols, dropna=False)
        .agg(
            pay_amount=("credit_amount", "sum"),
            pay_date=("posting_date", "min"),
            pay_rows=("document_id", "count"),
        )
        .reset_index()
    )

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
    ic = ic[
        ic["_src"].isin(company_codes) & ic["_dst"].isin(company_codes) & ic["_src"].ne(ic["_dst"])
    ]
    if ic.empty:
        return {"networkx_available": True, "edges_built": 0, "cycles_found": 0}
    graph = nx.from_pandas_edgelist(
        ic, source="_src", target="_dst", edge_attr=["document_id"], create_using=nx.MultiDiGraph
    )
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
        return {
            "direction_pair_count": 0,
            "high_asymmetry_pair_count": 0,
            "high_asymmetry_rate": 0.0,
        }
    amount = ic[["debit_amount", "credit_amount"]].max(axis=1)
    is_credit = ic["credit_amount"] > 0
    ic["_src"] = ic["company_code"].where(is_credit, ic["trading_partner"]).astype(str)
    ic["_dst"] = ic["trading_partner"].where(is_credit, ic["company_code"]).astype(str)
    ic["_amount"] = amount
    directed = (
        ic[ic["_src"].ne(ic["_dst"])]
        .groupby(["_src", "_dst"])
        .agg(
            count=("_amount", "size"),
            total_amount=("_amount", "sum"),
            mean_amount=("_amount", "mean"),
        )
        .reset_index()
    )
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
            hits = {
                pattern: text.count(pattern) for pattern in namespace_patterns if pattern in text
            }
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
                    allowed_related_master = (
                        path.name == "related_parties.json"
                        and str(item.get("journal_company_code", "")).strip() == "C001"
                    )
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
        doc_head[doc_head["semantic_scenario_id"].astype(str).eq("R2R_REVERSAL")][
            "document_id"
        ].astype(str)
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
    amount_work["_signed"] = amount_work["debit_amount"].round(0) - amount_work[
        "credit_amount"
    ].round(0)
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

        pair_lines = amount_work[
            amount_work["document_id"].astype(str).isin({original_doc, reversal_doc})
        ]
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


def _debit_minus_credit_from_normal(
    account_code: str, normal_side_balance: int, coa_meta: dict[str, dict[str, Any]]
) -> int:
    return (
        -normal_side_balance if _is_credit_normal(account_code, coa_meta) else normal_side_balance
    )


def _is_contra_account(
    account_code: str, category: str, coa_meta: dict[str, dict[str, Any]]
) -> bool:
    meta = coa_meta.get(str(account_code), {})
    text = " ".join(
        str(meta.get(key, ""))
        for key in [
            "account_name",
            "name",
            "description",
            "account_type",
            "sub_type",
            "semantic_account_subtype",
        ]
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
    if category in {"Cash", "Receivables", "Inventory", "FixedAssets"} and _is_credit_normal(
        account_code, coa_meta
    ):
        return True
    if category in {"Revenue", "OtherIncome"} and not _is_credit_normal(account_code, coa_meta):
        return True
    if category in {
        "Payables",
        "AccruedLiabilities",
        "LongTermDebt",
        "Equity",
    } and not _is_credit_normal(account_code, coa_meta):
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


def _company_year_pnl(
    df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    if df.empty:
        return "BLOCKED", {"rows": 0}
    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    nonclosing = work[
        ~(batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-"))
    ].copy()
    if nonclosing.empty:
        return "BLOCKED", {"nonclosing_rows": 0}

    nonclosing["_debit_i"] = nonclosing["debit_amount"].round(0).astype("int64")
    nonclosing["_credit_i"] = nonclosing["credit_amount"].round(0).astype("int64")
    nonclosing["_prefix"] = nonclosing["gl_account"].fillna("").astype(str).str.strip().str[:1]
    nonclosing["_meta_text"] = (
        nonclosing["gl_account"]
        .astype(str)
        .map(lambda account: _meta_text(coa_meta.get(account, {})))
    )
    nonclosing["_expense_net"] = nonclosing["_debit_i"] - nonclosing["_credit_i"]
    nonclosing["_revenue_net"] = nonclosing["_credit_i"] - nonclosing["_debit_i"]

    bad_periods: list[dict[str, Any]] = []
    ratios: list[dict[str, Any]] = []
    grouped = nonclosing.groupby(["company_code", "fiscal_year"], dropna=False)
    for (company, year), group in grouped:
        revenue = int(group.loc[group["_prefix"].eq("4"), "_revenue_net"].sum())
        cogs = int(group.loc[group["_prefix"].eq("5"), "_expense_net"].sum())
        sga = int(group.loc[group["_prefix"].eq("6"), "_expense_net"].sum())
        interest = int(
            group.loc[
                group["_meta_text"].str.contains("interest|이자", regex=True), "_expense_net"
            ].sum()
        )
        taxes = int(
            group.loc[
                group["_meta_text"].str.contains(
                    "tax|income_tax|corporate_tax|세금|법인세", regex=True
                ),
                "_expense_net",
            ].sum()
        )
        if revenue <= 0:
            bad_periods.append(
                {
                    "company": str(company),
                    "year": str(year),
                    "reason": "nonpositive_revenue",
                    "revenue": revenue,
                }
            )
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
            for key in [
                "cogs_ratio",
                "sga_ratio",
                "interest_ratio",
                "tax_ratio",
                "operating_margin",
            ]
        },
        "sample_bad_periods": bad_periods[:10],
    }
    return ("PASS" if not bad_periods else "FAIL"), metric


def _coa_prefix_semantic_metrics(
    df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
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
        if prefix1 == "4" and any(
            term in text
            for term in [
                "expense",
                "cost",
                "tax",
                "interest",
                "loss",
                "비용",
                "원가",
                "세금",
                "이자",
                "손상",
            ]
        ):
            reason = "revenue_prefix_has_expense_semantics"
        elif prefix1 == "5" and any(
            term in text
            for term in [
                "interest",
                "tax",
                "depreciation",
                "amortization",
                "opex",
                "selling",
                "admin",
                "이자",
                "세금",
                "감가",
                "상각",
                "판관",
            ]
        ):
            reason = "cogs_prefix_has_non_cogs_semantics"
        elif prefix1 == "6" and any(
            term in text for term in ["interest", "income tax", "corporate tax", "이자", "법인세"]
        ):
            reason = "sga_prefix_has_financing_or_tax_semantics"
        elif prefix1 == "7" and any(
            term in text
            for term in [
                "expense",
                "cost",
                "loss",
                "tax",
                "interest",
                "비용",
                "원가",
                "손실",
                "세금",
                "이자",
            ]
        ):
            reason = "other_income_prefix_has_expense_semantics"
        elif (
            prefix1 == "8"
            and "income tax" not in text
            and any(term in text for term in ["revenue", "income", "sales", "매출", "수익"])
        ):
            reason = "other_expense_prefix_has_income_semantics"
        elif prefix1 in {"1", "2", "3"} and any(
            term in account_type for term in ["revenue", "expense", "income"]
        ):
            reason = "balance_sheet_prefix_has_pl_account_type"
        elif prefix1 in {"4", "5", "6", "7", "8"} and any(
            term in account_type for term in ["asset", "liability", "equity"]
        ):
            reason = "pl_prefix_has_balance_sheet_account_type"
        if reason:
            bad.append(
                {
                    "account": account,
                    "reason": reason,
                    "account_type": account_type,
                    "sub_type": str(
                        meta.get("sub_type") or meta.get("semantic_account_subtype") or ""
                    ),
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
    income = [
        rec
        for rec in statements
        if str(rec.get("statement_type", "")).lower() == "income_statement"
    ]
    if not income:
        return "BLOCKED", {
            "financial_statement_records": len(statements),
            "income_statement_records": 0,
        }
    revenue_negative = 0
    cogs_gt_revenue = 0
    empty_mapping = 0
    checked = 0
    sample_bad: list[dict[str, Any]] = []
    for rec in income:
        items = {
            str(item.get("line_code")): item
            for item in rec.get("line_items", [])
            if isinstance(item, dict)
        }
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
    status = (
        "PASS"
        if checked > 0 and revenue_negative == 0 and cogs_gt_revenue == 0 and empty_mapping == 0
        else "FAIL"
    )
    return status, metric


def _depreciation_net_metrics(
    df: pd.DataFrame, coa_meta: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any]]:
    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    work = work[~(batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-"))].copy()
    work["_meta_text"] = (
        work["gl_account"].astype(str).map(lambda account: _meta_text(coa_meta.get(account, {})))
    )
    dep = work[
        work["_meta_text"].str.contains(
            "depreciation expense|amortization expense|감가상각비|상각비", regex=True
        )
    ].copy()
    if dep.empty:
        return "BLOCKED", {"depreciation_expense_rows": 0}
    dep["_debit_i"] = dep["debit_amount"].round(0).astype("int64")
    dep["_credit_i"] = dep["credit_amount"].round(0).astype("int64")
    grouped = (
        dep.groupby(["company_code", "fiscal_year"], dropna=False)
        .agg(
            debit=("_debit_i", "sum"),
            credit=("_credit_i", "sum"),
            rows=("document_id", "size"),
        )
        .reset_index()
    )
    grouped["net_expense"] = grouped["debit"] - grouped["credit"]
    zero_or_negative = grouped[grouped["net_expense"] <= 0]
    metric = {
        "company_years_checked": int(len(grouped)),
        "zero_or_negative_net_expense_count": int(len(zero_or_negative)),
        "net_expense_min": int(grouped["net_expense"].min()) if not grouped.empty else None,
        "net_expense_p50": float(grouped["net_expense"].quantile(0.5))
        if not grouped.empty
        else None,
        "sample_bad": zero_or_negative.head(10).to_dict("records"),
    }
    return ("PASS" if len(grouped) > 0 and zero_or_negative.empty else "FAIL"), metric


def _stable_account_class(account: str, coa_meta: dict[str, dict[str, Any]]) -> str:
    meta = coa_meta.get(str(account), {})
    text = _meta_text(meta)
    if account.startswith("810") or "income_tax_expense" in text or "income tax expense" in text:
        return "income_tax_expense"
    if account.startswith("800") or "interest_expense" in text or "interest expense" in text:
        return "interest_expense"
    if "depreciation" in text or "amortization" in text or "감가" in text or "상각" in text:
        return "depreciation_amortization"
    if "rent" in text or "lease" in text or "임차" in text or "리스" in text:
        return "rent_lease"
    return ""


def _stable_account_yoy_volatility_metrics(
    df: pd.DataFrame,
    coa_meta: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    work = work[~(batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-"))].copy()
    work["_stable_class"] = (
        work["gl_account"].astype(str).map(lambda account: _stable_account_class(account, coa_meta))
    )
    stable = work[work["_stable_class"].ne("")].copy()
    if stable.empty:
        return "BLOCKED", {"stable_account_rows": 0}

    stable["_activity_i"] = (
        stable["debit_amount"].round(0).astype("int64").abs()
        + stable["credit_amount"].round(0).astype("int64").abs()
    )
    grouped = (
        stable.groupby(
            ["company_code", "gl_account", "_stable_class", "fiscal_year"], dropna=False
        )["_activity_i"]
        .sum()
        .reset_index()
    )
    min_activity = 50_000_000
    max_ratio = 8.0
    checked_pairs = 0
    bad_pair_count = 0
    bad_pairs: list[dict[str, Any]] = []
    ratios: list[float] = []
    class_counts: dict[str, int] = {}
    years = sorted(str(year) for year in grouped["fiscal_year"].dropna().astype(str).unique())
    year_pairs = list(zip(years, years[1:]))
    for (company, account, stable_class), sub in grouped.groupby(
        ["company_code", "gl_account", "_stable_class"],
        dropna=False,
        sort=False,
    ):
        values = {str(row["fiscal_year"]): int(row["_activity_i"]) for _, row in sub.iterrows()}
        for prev_year, curr_year in year_pairs:
            prev_amount = values.get(prev_year, 0)
            curr_amount = values.get(curr_year, 0)
            if min(prev_amount, curr_amount) < min_activity:
                continue
            ratio = max(prev_amount, curr_amount) / max(min(prev_amount, curr_amount), 1)
            ratios.append(float(ratio))
            checked_pairs += 1
            if ratio > max_ratio:
                bad_pair_count += 1
                class_counts[str(stable_class)] = class_counts.get(str(stable_class), 0) + 1
                if len(bad_pairs) < 20:
                    bad_pairs.append(
                        {
                            "company_code": str(company),
                            "gl_account": str(account),
                            "stable_class": str(stable_class),
                            "prev_year": prev_year,
                            "curr_year": curr_year,
                            "prev_activity": prev_amount,
                            "curr_activity": curr_amount,
                            "change_ratio": float(ratio),
                        }
                    )
    metric = {
        "stable_account_rows": int(len(stable)),
        "stable_accounts_used": int(stable["gl_account"].nunique()),
        "checked_year_pairs": checked_pairs,
        "year_pairs": [[left, right] for left, right in year_pairs],
        "min_activity_krw": min_activity,
        "max_allowed_change_ratio": max_ratio,
        "bad_year_pairs": bad_pair_count,
        "bad_year_pairs_by_class": class_counts,
        "max_change_ratio": max(ratios) if ratios else None,
        "sample_bad_pairs": bad_pairs,
    }
    return ("PASS" if checked_pairs > 0 and not bad_pairs else "FAIL"), metric


def _rare_account_pair_reuse_metrics(df: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    required = {
        "document_id",
        "company_code",
        "fiscal_year",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "semantic_account_subtype",
        "source",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        return "BLOCKED", {"missing_required_columns": missing}

    work = df.copy()
    batch_type = work.get("batch_type", pd.Series("", index=work.index)).fillna("").astype(str)
    reference = work.get("reference", pd.Series("", index=work.index)).fillna("").astype(str)
    is_closing = batch_type.eq("annual_closing") | reference.str.startswith("CLOSE-")
    gl_for_ic = work["gl_account"].fillna("").astype(str)
    is_ic_account = gl_for_ic.str.startswith(("1150", "2050", "4500", "2700"))
    is_ic = (
        work.get("is_intercompany", pd.Series(False, index=work.index))
        .fillna(False)
        .astype(str)
        .str.lower()
        .eq("true")
        | is_ic_account
    )
    work = work[~(is_closing | is_ic)].copy()
    if work.empty:
        return "BLOCKED", {"eligible_rows": 0}

    work["_amount_i"] = work[["debit_amount", "credit_amount"]].max(axis=1).round(0).astype("int64")
    work = work[work["_amount_i"] > 0].copy()
    work["_side"] = work["debit_amount"].fillna(0).astype(float).gt(0).map({True: "D", False: "C"})
    work["_gl"] = work["gl_account"].fillna("").astype(str)
    work["_subtype"] = work["semantic_account_subtype"].fillna("").astype(str)
    work["_pair_parent"] = [
        _account_pair_parent(subtype, account)
        for subtype, account in zip(work["_subtype"], work["_gl"], strict=False)
    ]
    work["_source"] = work["source"].fillna("").astype(str).str.lower()

    doc_keys = ["company_code", "fiscal_year", "document_id"]
    doc_sources = (
        work.groupby(doc_keys, dropna=False)["_source"]
        .agg(lambda values: "|".join(sorted(set(values))))
        .reset_index()
    )
    debits = (
        work[work["_side"].eq("D")]
        .groupby(doc_keys, dropna=False)
        .agg(
            debit_accounts=("_gl", lambda values: sorted(set(values))),
            debit_subtypes=("_pair_parent", lambda values: sorted(set(values))),
        )
        .reset_index()
    )
    credits = (
        work[work["_side"].eq("C")]
        .groupby(doc_keys, dropna=False)
        .agg(
            credit_accounts=("_gl", lambda values: sorted(set(values))),
            credit_subtypes=("_pair_parent", lambda values: sorted(set(values))),
        )
        .reset_index()
    )
    docs = debits.merge(credits, on=doc_keys, how="inner").merge(
        doc_sources, on=doc_keys, how="left"
    )
    if docs.empty:
        return "BLOCKED", {"eligible_documents": 0}

    concrete_records: list[dict[str, Any]] = []
    subtype_records: list[dict[str, Any]] = []
    for _, row in docs.iterrows():
        key_base = {
            "company_code": str(row["company_code"]),
            "fiscal_year": str(row["fiscal_year"]),
            "document_id": str(row["document_id"]),
            "source": str(row["_source"]),
        }
        for debit in row["debit_accounts"]:
            for credit in row["credit_accounts"]:
                concrete_records.append({**key_base, "debit": debit, "credit": credit})
        for debit in row["debit_subtypes"]:
            for credit in row["credit_subtypes"]:
                subtype_records.append({**key_base, "debit": debit, "credit": credit})

    concrete = pd.DataFrame(concrete_records)
    subtype = pd.DataFrame(subtype_records)
    if concrete.empty or subtype.empty:
        return "BLOCKED", {"eligible_documents": int(len(docs)), "pair_records": int(len(concrete))}

    pair_keys = ["company_code", "fiscal_year", "debit", "credit"]
    concrete_counts = (
        concrete.groupby(pair_keys, dropna=False).size().rename("pair_count").reset_index()
    )
    subtype_counts = (
        subtype.groupby(pair_keys, dropna=False).size().rename("subtype_pair_count").reset_index()
    )
    concrete = concrete.merge(concrete_counts, on=pair_keys, how="left")
    subtype = subtype.merge(subtype_counts, on=pair_keys, how="left")

    rare_docs = concrete[concrete["pair_count"] <= 3]["document_id"].drop_duplicates()
    l404_doc_rate = len(rare_docs) / max(docs["document_id"].nunique(), 1)

    source_by_doc = docs.set_index("document_id")["_source"].to_dict()
    rare_source = rare_docs.map(lambda doc: source_by_doc.get(doc, ""))
    source_doc = docs[["document_id", "_source"]].drop_duplicates()
    source_rates: dict[str, float] = {}
    for token in ["recurring", "automated", "interface"]:
        denom = source_doc[source_doc["_source"].str.contains(token, regex=False)][
            "document_id"
        ].nunique()
        numer = int(rare_source.fillna("").str.contains(token, regex=False).sum())
        source_rates[token] = numer / denom if denom else 0.0

    concrete_pair_meta = concrete_counts.copy()
    concrete_pair_meta["is_rare"] = concrete_pair_meta["pair_count"] <= 3
    subtype_pair_counts = subtype_counts.rename(
        columns={"debit": "debit_subtype", "credit": "credit_subtype"}
    )
    account_to_subtype = (
        work.groupby("_gl", dropna=False)["_pair_parent"]
        .agg(lambda values: values.value_counts().index[0] if len(values) else "")
        .to_dict()
    )
    rare_pair_meta = concrete_pair_meta[concrete_pair_meta["is_rare"]].copy()
    rare_pair_meta["debit_subtype"] = rare_pair_meta["debit"].map(account_to_subtype).fillna("")
    rare_pair_meta["credit_subtype"] = rare_pair_meta["credit"].map(account_to_subtype).fillna("")
    rare_pair_meta = rare_pair_meta.merge(
        subtype_pair_counts,
        on=["company_code", "fiscal_year", "debit_subtype", "credit_subtype"],
        how="left",
    )
    rare_pair_count = int(len(rare_pair_meta))
    fragmented = rare_pair_meta[rare_pair_meta["subtype_pair_count"].fillna(0) > 3]
    fragmentation_rate = len(fragmented) / max(rare_pair_count, 1)

    top_pairs_share = float(
        concrete_counts["pair_count"].sort_values(ascending=False).head(20).sum()
        / max(concrete_counts["pair_count"].sum(), 1)
    )
    metric = {
        "eligible_documents": int(docs["document_id"].nunique()),
        "concrete_pair_count": int(len(concrete_counts)),
        "rare_pair_count": rare_pair_count,
        "l404_like_rare_doc_rate": float(l404_doc_rate),
        "l404_like_rare_doc_max_rate": 0.01,
        "source_rare_doc_rates": source_rates,
        "recurring_rare_doc_max_rate": 0.005,
        "automated_rare_doc_max_rate": 0.01,
        "fragmented_rare_pair_count": int(len(fragmented)),
        "fragmented_rare_pair_rate": float(fragmentation_rate),
        "fragmented_rare_pair_max_rate": 0.20,
        "top20_pair_occurrence_share": top_pairs_share,
        "sample_fragmented_pairs": fragmented.head(10).to_dict("records"),
    }
    passed = (
        l404_doc_rate <= 0.01
        and source_rates.get("recurring", 0.0) <= 0.005
        and source_rates.get("automated", 0.0) <= 0.01
        and fragmentation_rate <= 0.20
    )
    return ("PASS" if passed else "FAIL"), metric


def _account_pair_parent(subtype: str, account: str) -> str:
    subtype_norm = str(subtype or "").strip()
    if subtype_norm.lower() != "standard_account":
        return subtype_norm
    account = str(account or "")
    if account.startswith(("100", "101")):
        bucket = "cash"
    elif account.startswith("11"):
        bucket = "receivable"
    elif account.startswith("12"):
        bucket = "inventory"
    elif account.startswith(("13", "15", "16")):
        bucket = "asset"
    elif account.startswith(("20", "21", "22", "23", "25", "27")):
        bucket = "liability"
    elif account.startswith("3"):
        bucket = "equity"
    elif account.startswith("4"):
        bucket = "revenue"
    elif account.startswith("5"):
        bucket = "cogs"
    elif account.startswith(("6", "7")):
        bucket = "sga"
    elif account.startswith(("8", "9")):
        bucket = "other"
    else:
        bucket = "other"
    return f"standard_account:{bucket}"


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


def _archetype_coverage_metrics(
    df: pd.DataFrame, doc_head: pd.DataFrame, dataset: Path
) -> tuple[str, dict[str, Any]]:
    archetype_col = "semantic_scenario_id"
    if (
        archetype_col not in df.columns
        or df[archetype_col].fillna("").astype(str).str.strip().eq("").all()
    ):
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
        raw_tuple_missing_mask = (
            work[required]
            .fillna("")
            .astype(str)
            .apply(lambda col: col.str.strip().eq(""))
            .any(axis=1)
        )
        raw_tuple_missing_rows = int(raw_tuple_missing_mask.sum())
        coa_meta = _load_coa_meta(dataset)
        account_subtype = work["semantic_account_subtype"].fillna("").astype(str).str.strip()
        account_subtype = account_subtype.mask(
            account_subtype.eq(""),
            work["gl_account"]
            .astype(str)
            .map(lambda code: str(coa_meta.get(code, {}).get("sub_type", ""))),
        )
        account_subtype = account_subtype.mask(
            account_subtype.eq(""), work["gl_account"].map(_account_category)
        )
        line_family = work["line_text_family"].fillna("").astype(str).str.strip()
        line_family = line_family.mask(
            line_family.eq("")
            & work["_archetype_key"].str.contains("IC_|INTERCOMPANY", case=False, regex=True),
            "INTERCOMPANY",
        )
        line_family = line_family.mask(
            line_family.eq("")
            & work["_archetype_key"].str.contains("CLOSING|RECLASS", case=False, regex=True),
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
        tuple_missing_mask = (
            work[derived_required]
            .fillna("")
            .astype(str)
            .apply(lambda col: col.str.strip().eq(""))
            .any(axis=1)
        )
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
        tuple_counts = (
            work[~tuple_missing_mask & work["_archetype_key"].ne("")]
            .groupby("_archetype_key")["_tuple_key"]
            .nunique()
        )
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

    dist = (
        work[work["_archetype_key"].ne("")]
        .groupby("_archetype_key")
        .agg(
            rows=("document_id", "size"),
            docs=("document_id", "nunique"),
        )
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
                "top_gl_accounts": ",".join(
                    group["gl_account"].astype(str).value_counts().head(8).index.tolist()
                ),
                "line_text_sample": " | ".join(
                    group["line_text"].astype(str).drop_duplicates().head(4).tolist()
                ),
            }
        )
    return doc_rows


def _document_reference_structure_metrics(
    df: pd.DataFrame, doc_head: pd.DataFrame
) -> tuple[str, dict[str, Any]]:
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
        docs[doc_num_nonblank & docs.duplicated("document_number", keep=False)][
            "document_id"
        ].nunique()
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
    same_role_duplicate_reference_docs = (
        int(same_role_ref_groups["docs"].sum()) if len(same_role_ref_groups) else 0
    )

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
        from src.detection.duplicate_detector import DuplicateDetector

        from config.settings import AuditSettings

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
            "truncated": bool(artifact.get("truncated", False))
            if isinstance(artifact, dict)
            else False,
        }
        return ("PASS" if not same_doc_pairs else "FAIL"), metric
    except Exception as exc:  # noqa: BLE001
        work = df.copy()
        work["_amount"] = work[["debit_amount", "credit_amount"]].max(axis=1)
        work["_date"] = work["posting_date"].astype(str).str[:10]
        explainable_doc = pd.Series(False, index=work.index)
        for column in ["batch_type", "batch_id", "job_id"]:
            if column in work.columns:
                explainable_doc = explainable_doc | work[column].fillna("").astype(
                    str
                ).str.strip().ne("")
        explained_docs = set(work.loc[explainable_doc, "document_id"].astype(str))
        exact_same_doc = (
            work.groupby(
                ["document_id", "gl_account", "_amount", "_date", "line_text"], dropna=False
            )
            .size()
            .reset_index(name="line_count")
        )
        same_doc_groups = exact_same_doc[exact_same_doc["line_count"] > 1]
        unexplained_groups = same_doc_groups[
            ~same_doc_groups["document_id"].astype(str).isin(explained_docs)
        ]
        pair_count = int(
            ((unexplained_groups["line_count"] * (unexplained_groups["line_count"] - 1)) // 2).sum()
        )
        metric = {
            "detector_import_available": False,
            "detector_import_error": str(exc),
            "fallback_exact_same_document_groups": int(len(same_doc_groups)),
            "fallback_explained_batch_groups": int(len(same_doc_groups) - len(unexplained_groups)),
            "fallback_unexplained_same_document_groups": int(len(unexplained_groups)),
            "fallback_unexplained_same_document_pair_count": pair_count,
            "fallback_key": [
                "document_id",
                "gl_account",
                "amount",
                "posting_date_day",
                "line_text",
            ],
            "explainable_document_fields": ["batch_type", "batch_id", "job_id"],
        }
        return ("PASS" if pair_count == 0 else "FAIL"), metric


def _section9_diagnostics(df: pd.DataFrame) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    reclass = df[
        df.get("batch_type", pd.Series("", index=df.index))
        .fillna("")
        .astype(str)
        .eq("monthly_balance_reclass")
    ].copy()
    if reclass.empty:
        findings.append(
            verdict(
                "Diagnostic",
                "S09_RECLASS",
                "INFO",
                {"reclass_documents": 0, "reclass_rows": 0},
                "monthly balance reclass trigger diagnostics",
            )
        )
    else:
        doc_line_counts = reclass.groupby("document_id").size()
        restore_rows = reclass[
            reclass["line_text"].fillna("").astype(str).str.contains("정상잔액 복원", regex=False)
        ]
        reclass_metric = {
            "reclass_documents": int(reclass["document_id"].nunique()),
            "reclass_rows": int(len(reclass)),
            "company_periods_with_reclass": int(
                reclass[["company_code", "fiscal_year", "fiscal_period"]].drop_duplicates().shape[0]
            ),
            "line_count_per_doc_min": int(doc_line_counts.min()),
            "line_count_per_doc_p50": float(doc_line_counts.quantile(0.5)),
            "line_count_per_doc_max": int(doc_line_counts.max()),
            "restored_account_rows": int(len(restore_rows)),
            "restored_account_top": {
                str(k): int(v)
                for k, v in restore_rows["gl_account"].value_counts().head(20).items()
            },
            "trigger_rule": "issued only when a company-period/account has negative normal-side BS balance after monthly roll-forward; line count varies by triggered accounts, not a fixed blanket row pattern",
        }
        findings.append(
            verdict(
                "Diagnostic",
                "S09_RECLASS",
                "INFO",
                reclass_metric,
                "monthly balance reclass trigger diagnostics",
            )
        )

    work = df.copy()
    work["_category"] = work["gl_account"].map(_account_category)
    pnl = work[
        work["_category"].isin(
            {"Revenue", "OtherIncome", "CostOfSales", "OperatingExpenses", "OtherExpenses"}
        )
    ].copy()
    if pnl.empty:
        pnl_metric = {"income_statement_rows": 0}
    else:
        pnl["_amount_debit_i"] = pnl["debit_amount"].round(0).astype("int64")
        pnl["_amount_credit_i"] = pnl["credit_amount"].round(0).astype("int64")
        by_period_account = (
            pnl.groupby(
                ["company_code", "fiscal_year", "fiscal_period", "gl_account", "_category"],
                dropna=False,
            )
            .agg(
                debit=("_amount_debit_i", "sum"),
                credit=("_amount_credit_i", "sum"),
                docs=("document_id", "nunique"),
                rows=("document_id", "size"),
            )
            .reset_index()
        )
        revenue_like = by_period_account["_category"].isin({"Revenue", "OtherIncome"})
        expense_like = by_period_account["_category"].isin(
            {"CostOfSales", "OperatingExpenses", "OtherExpenses"}
        )
        reverse = by_period_account[
            (revenue_like & (by_period_account["debit"] > by_period_account["credit"]))
            | (expense_like & (by_period_account["credit"] > by_period_account["debit"]))
        ]
        pnl_metric = {
            "period_account_reverse_count": int(len(reverse)),
            "reverse_rate": float(len(reverse) / max(len(by_period_account), 1)),
            "by_category": {str(k): int(v) for k, v in reverse["_category"].value_counts().items()},
            "top_accounts": {
                str(k): int(v) for k, v in reverse["gl_account"].value_counts().head(20).items()
            },
            "basis": "period-level P&L reverse balances are diagnostic: returns/discounts, reallocations, reversals, reclass, tax/closing timing can create debit revenue or credit expense in a month without breaking annual closing",
        }
    findings.append(
        verdict(
            "Diagnostic",
            "S09_M06_IS_REVERSE",
            "INFO",
            pnl_metric,
            "income statement reverse-balance diagnostic",
        )
    )
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
        for test_id in ["M01", "M02", "M03", "M04", "M05", "M06", "M14"]:
            findings.append(
                verdict(
                    "Gate 2",
                    test_id,
                    "BLOCKED",
                    metric,
                    "financial statement balance artifacts required",
                )
            )
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
        work["_period_key"] = list(
            zip(
                work["company_code"],
                work["fiscal_year"].astype(str),
                work["fiscal_period"].astype(str).str.zfill(2),
            )
        )

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
            findings.append(
                verdict(
                    "Gate 2",
                    "M01",
                    "BLOCKED",
                    {"trial_balance_periods": len(tbs), "company_code_missing": True},
                    "TB must carry company_code for multi-company verification",
                )
            )
        else:
            findings.append(
                verdict(
                    "Gate 2",
                    "M01",
                    "PASS" if mismatches == 0 else "FAIL",
                    {
                        "checked_lines": checked_lines,
                        "mismatches": mismatches,
                        "max_abs_diff_krw": max_diff,
                    },
                    "GL aggregate equals exported TB balances",
                )
            )

        # M02/M03/M04/M06 use journal-derived roll-forward ledger state.
        periods = sorted(
            work[["company_code", "fiscal_year", "fiscal_period"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
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
            rows = work[
                (work["company_code"].astype(str) == company)
                & (work["fiscal_year"].astype(int) == fy_i)
                & (work["fiscal_period"].astype(int) == fp_i)
            ]
            carried_accounts = {
                account
                for (prior_company, account), _closing in prior_closing.items()
                if prior_company == company
            }
            accounts = (
                set(opening.get(company, {}))
                | set(rows["gl_account"].astype(str))
                | carried_accounts
            )
            assets = liabilities = equity = revenue = expenses = 0
            for account in accounts:
                cat = _account_category(account)
                opening_value = prior_closing.get(
                    (company, account), opening.get(company, {}).get(account, 0)
                )
                debit = int(
                    rows.loc[rows["gl_account"].astype(str).eq(account), "_amount_debit_i"].sum()
                )
                credit = int(
                    rows.loc[rows["gl_account"].astype(str).eq(account), "_amount_credit_i"].sum()
                )
                if _is_credit_normal(account, coa_meta):
                    closing = opening_value - debit + credit
                else:
                    closing = opening_value + debit - credit
                if (
                    abs(
                        (
                            opening_value
                            + (
                                credit - debit
                                if _is_credit_normal(account, coa_meta)
                                else debit - credit
                            )
                        )
                        - closing
                    )
                    > 1
                ):
                    roll_bad += 1
                if (company, account) in prior_closing and abs(
                    opening_value - prior_closing[(company, account)]
                ) > 1:
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
                    elif cat in {
                        "Revenue",
                        "OtherIncome",
                        "CostOfSales",
                        "OperatingExpenses",
                        "OtherExpenses",
                    }:
                        pnl_negative += 1
                    elif (
                        account == "3200"
                        or str(coa_meta.get(account, {}).get("sub_type", "")).lower()
                        == "retained_earnings"
                    ):
                        retained_deficit += 1
                    elif cat == "Equity":
                        other_equity_negative += 1
                        normal_side_bad_by_account[account] = (
                            normal_side_bad_by_account.get(account, 0) + 1
                        )
                    else:
                        normal_side_bad += 1
                        normal_side_bad_by_account[account] = (
                            normal_side_bad_by_account.get(account, 0) + 1
                        )
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
            findings.append(
                verdict(
                    "Gate 2",
                    "M02",
                    "PASS" if fs_checked > 0 and fs_bad == 0 else "FAIL",
                    {
                        "periods_checked": fs_checked,
                        "equation_bad_periods": fs_bad,
                        "max_equation_diff_krw": fs_max_diff,
                        "equation_formula": "financial_statements BS-TA = BS-TL + BS-TE",
                    },
                    "ending accounting equation",
                )
            )
        else:
            findings.append(
                verdict(
                    "Gate 2",
                    "M02",
                    "PASS" if equation_bad == 0 else "FAIL",
                    {
                        "periods_checked": len(periods),
                        "equation_bad_periods": equation_bad,
                        "max_equation_diff_krw": max_equation_diff,
                        "equation_formula": "assets = liabilities + equity + current_ytd_income",
                    },
                    "ending accounting equation",
                )
            )
        findings.append(
            verdict(
                "Gate 2",
                "M03",
                "PASS" if roll_bad == 0 else "FAIL",
                {"period_accounts_checked": checked_period_accounts, "roll_forward_bad": roll_bad},
                "account roll-forward",
            )
        )
        findings.append(
            verdict(
                "Gate 2",
                "M04",
                "PASS" if continuity_bad == 0 else "FAIL",
                {
                    "period_accounts_checked": checked_period_accounts,
                    "continuity_bad": continuity_bad,
                },
                "prior closing equals current opening",
            )
        )
        top_normal_side_bad = sorted(
            normal_side_bad_by_account.items(), key=lambda item: item[1], reverse=True
        )[:10]
        hard_negative_rate = normal_side_bad / max(checked_period_accounts, 1)
        m06_pass = other_equity_negative == 0 and hard_negative_rate <= 0.02
        findings.append(
            verdict(
                "Gate 2",
                "M06",
                "PASS" if m06_pass else "MONITOR",
                {
                    "period_accounts_checked": checked_period_accounts,
                    "hard_negative_balance_count": normal_side_bad,
                    "hard_negative_balance_rate": hard_negative_rate,
                    "hard_negative_balance_rate_threshold": 0.02,
                    "other_equity_negative_balance_count": other_equity_negative,
                    "contra_negative_balance_count": contra_negative,
                    "retained_earnings_deficit_count": retained_deficit,
                    "income_statement_reverse_balance_count": pnl_negative,
                    "top_hard_negative_accounts": dict(top_normal_side_bad),
                },
                "normal balance direction",
            )
        )

        closing = work[work["_is_closing"]]
        nonclosing = work[~work["_is_closing"]]
        years = nonclosing[["company_code", "fiscal_year"]].drop_duplicates()
        closing_bad = 0
        closing_checked = 0
        for company, fy in years.itertuples(index=False, name=None):
            sub = nonclosing[
                (nonclosing["company_code"].eq(company)) & (nonclosing["fiscal_year"].eq(fy))
            ]
            pnl = 0
            for _, row in sub.iterrows():
                account = str(row["gl_account"])
                if account[:1] in {"4", "5", "6", "7", "8"}:
                    pnl += int(row["_amount_credit_i"] - row["_amount_debit_i"])
            cls = closing[
                (closing["company_code"].eq(company))
                & (closing["fiscal_year"].eq(fy))
                & (closing["gl_account"].astype(str).eq("3200"))
            ]
            re_effect = int(cls["_amount_credit_i"].sum() - cls["_amount_debit_i"].sum())
            closing_checked += 1
            if abs(pnl - re_effect) > 1:
                closing_bad += 1
        findings.append(
            verdict(
                "Gate 2",
                "M05",
                "PASS" if closing_checked > 0 and closing_bad == 0 else "FAIL",
                {"company_years_checked": closing_checked, "closing_bad": closing_bad},
                "P&L closes to retained earnings",
            )
        )

        # M14: annual closing rows must keep closing semantics, not account-native
        # revenue/expense labels. L4-03 materiality thresholds read
        # semantic_account_subtype == income_statement_close to infer P&L scale,
        # so a balanced closing entry can still be unusable if these labels drift.
        m08_years_checked = 0
        m08_pnl_lines = 0
        m08_re_lines = 0
        m08_bad_subtype = 0
        m08_bad_line_family = 0
        m08_bad_re_subtype = 0
        m08_bad_re_line_family = 0
        m08_missing_closing_components = 0
        m08_bad_reconciliation = 0
        m08_max_reconciliation_diff = 0
        m08_examples: list[dict[str, Any]] = []
        for company, fy in years.itertuples(index=False, name=None):
            cls_year = closing[
                (closing["company_code"].eq(company)) & (closing["fiscal_year"].eq(fy))
            ]
            pnl_cls = cls_year[
                cls_year["gl_account"].astype(str).str[:1].isin(["4", "5", "6", "7", "8"])
            ]
            re_cls = cls_year[cls_year["gl_account"].astype(str).eq("3200")]
            m08_years_checked += 1
            if pnl_cls.empty or re_cls.empty:
                m08_missing_closing_components += 1
                if len(m08_examples) < 10:
                    m08_examples.append(
                        {
                            "company_code": str(company),
                            "fiscal_year": int(fy),
                            "issue": "missing_pnl_or_retained_earnings_closing_line",
                            "pnl_closing_lines": int(len(pnl_cls)),
                            "retained_earnings_lines": int(len(re_cls)),
                        }
                    )
                continue

            m08_pnl_lines += int(len(pnl_cls))
            m08_re_lines += int(len(re_cls))
            bad_sub = (
                pnl_cls["semantic_account_subtype"]
                .fillna("")
                .astype(str)
                .ne("income_statement_close")
            )
            bad_fam = pnl_cls["line_text_family"].fillna("").astype(str).ne("annual_closing")
            bad_re_sub = (
                re_cls["semantic_account_subtype"].fillna("").astype(str).ne("retained_earnings")
            )
            bad_re_fam = re_cls["line_text_family"].fillna("").astype(str).ne("annual_closing")
            m08_bad_subtype += int(bad_sub.sum())
            m08_bad_line_family += int(bad_fam.sum())
            m08_bad_re_subtype += int(bad_re_sub.sum())
            m08_bad_re_line_family += int(bad_re_fam.sum())

            pnl_net = int((pnl_cls["_amount_credit_i"] - pnl_cls["_amount_debit_i"]).sum())
            re_effect = int((re_cls["_amount_credit_i"] - re_cls["_amount_debit_i"]).sum())
            diff = abs(pnl_net + re_effect)
            m08_max_reconciliation_diff = max(m08_max_reconciliation_diff, diff)
            if diff > 1:
                m08_bad_reconciliation += 1

            if len(m08_examples) < 10 and (
                bad_sub.any() or bad_fam.any() or bad_re_sub.any() or bad_re_fam.any() or diff > 1
            ):
                m08_examples.append(
                    {
                        "company_code": str(company),
                        "fiscal_year": int(fy),
                        "bad_pnl_subtype_lines": int(bad_sub.sum()),
                        "bad_pnl_line_family_lines": int(bad_fam.sum()),
                        "bad_re_subtype_lines": int(bad_re_sub.sum()),
                        "bad_re_line_family_lines": int(bad_re_fam.sum()),
                        "closing_reconciliation_diff_krw": int(diff),
                    }
                )

        m08_bad_total = (
            m08_bad_subtype
            + m08_bad_line_family
            + m08_bad_re_subtype
            + m08_bad_re_line_family
            + m08_missing_closing_components
            + m08_bad_reconciliation
        )
        findings.append(
            verdict(
                "Gate 2",
                "M14",
                "PASS" if m08_years_checked > 0 and m08_bad_total == 0 else "FAIL",
                {
                    "company_years_checked": m08_years_checked,
                    "pnl_closing_lines_checked": m08_pnl_lines,
                    "retained_earnings_lines_checked": m08_re_lines,
                    "bad_pnl_semantic_subtype_lines": m08_bad_subtype,
                    "bad_pnl_line_text_family_lines": m08_bad_line_family,
                    "bad_retained_earnings_subtype_lines": m08_bad_re_subtype,
                    "bad_retained_earnings_line_text_family_lines": m08_bad_re_line_family,
                    "missing_closing_component_years": m08_missing_closing_components,
                    "bad_reconciliation_years": m08_bad_reconciliation,
                    "max_reconciliation_diff_krw": m08_max_reconciliation_diff,
                    "examples": m08_examples,
                },
                "annual closing semantic labels must support downstream materiality threshold derivation",
            )
        )

    recon_path = dataset / "balance" / "subledger_reconciliation.json"
    if not recon_path.exists():
        findings.append(
            verdict(
                "Gate 2",
                "M07",
                "BLOCKED",
                {"missing": "balance/subledger_reconciliation.json"},
                "subledger reconciliation required",
            )
        )
    else:
        recon = json.loads(recon_path.read_text(encoding="utf-8"))
        diffs = [abs(float(item.get("difference", 0))) for item in recon if isinstance(item, dict)]
        statuses = [str(item.get("status", "")) for item in recon if isinstance(item, dict)]
        bad = sum(1 for diff in diffs if diff > 1.0)
        findings.append(
            verdict(
                "Gate 2",
                "M07",
                "PASS" if bad == 0 and statuses else "FAIL",
                {
                    "reconciliations": len(diffs),
                    "bad_reconciliations": bad,
                    "max_abs_diff_krw": max(diffs) if diffs else None,
                    "statuses": dict(pd.Series(statuses).value_counts()) if statuses else {},
                },
                "AR/AP/Inventory/FA subledger equals GL control",
            )
        )

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
        col: int(df[col].str.strip().ne("").sum()) for col in mutation_cols if col in df.columns
    }
    findings.append(
        verdict(
            "Gate 0",
            "O01",
            "PASS"
            if all(v == 0 for v in normal_flags.values())
            and all(v == 0 for v in mutation_nonblank.values())
            else "FAIL",
            {"normal_flags": normal_flags, "mutation_nonblank": mutation_nonblank},
            "normal-only label/provenance contamination check",
        )
    )

    source_identity_status, source_identity_metric = _automated_source_identity_metrics(df)
    findings.append(
        verdict(
            "Gate 1",
            "E13_AUTOMATED_SOURCE_IDENTITY",
            source_identity_status,
            source_identity_metric,
            "automated/recurring source rows require both batch_id and job_id, human-entered rows must keep them blank, and source_trust must trust automated rows",
        )
    )

    bal = df.groupby("document_id", sort=False).agg(
        debit=("debit_amount", "sum"), credit=("credit_amount", "sum")
    )
    bal_i = (
        df.assign(
            _debit_won=df["debit_amount"].round(0).astype("int64"),
            _credit_won=df["credit_amount"].round(0).astype("int64"),
        )
        .groupby("document_id", sort=False)
        .agg(debit=("_debit_won", "sum"), credit=("_credit_won", "sum"))
    )
    diff = (bal_i["debit"] - bal_i["credit"]).abs()
    imbalance_count = int((diff > 1).sum())
    findings.append(
        verdict(
            "Gate 0",
            "A01",
            "PASS" if imbalance_count == 0 else "FAIL",
            {
                "imbalance_count": imbalance_count,
                "max_abs_diff_krw": int(diff.max() if len(diff) else 0),
            },
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
        sod_conflict_nonblank = (
            doc_head["sod_conflict_type"].fillna("").astype(str).str.strip().ne("")
        )
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
                if sod_true_docs == 0 and conflict_docs == 0 and non_self_sod_docs == 0
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

    rbac_required = {"user_persona", "business_process", "created_by", "source"}
    rbac_missing = sorted(rbac_required - set(doc_head.columns))
    if rbac_missing:
        findings.append(
            verdict(
                "Gate 0",
                "E05B_RBAC_PERSONA_PROCESS_SCOPE",
                "BLOCKED",
                {"missing_required_columns": rbac_missing},
                "normal baseline RBAC/persona scope must be measurable",
            )
        )
    else:
        # ── E05B 재설계 (2026-07-16, 사용자 결정) ──────────────────────────────
        # 구판은 persona 라벨별 허용 프로세스 표(ap_clerk 등 clerk 어휘)를 검사했다.
        # 생성기 UserPersona enum에는 clerk 어휘가 없어(junior/senior/controller/
        # manager/...만 존재) 그 표는 원리상 만족 불가능한 주장이었다 — ACC01과
        # 같은 게이트 오류 계열. 감사 실질(SoD·직무 전문화)은 라벨이 아니라
        # "한 사용자가 몇 개 프로세스를 넘나드는가"로 측정한다 (T3-10 전담 원칙).
        #
        # 검증 주장 (수기·조정 전표의 사람 사용자 단위):
        #   1. junior_accountant 사용자는 프로세스 폭 1 (단일 전담, 겸직 0)
        #   2. 그 외 사람 persona는 폭 <=2 (compatible 겸직 최대 2)
        #   3. 폭 2인 사용자의 두 번째 프로세스는 반드시 R2R —
        #      생성기 compatible_pairs 4쌍(R2R-A2R·R2R-TRE·P2P-R2R·O2C-R2R)은 전부
        #      R2R을 포함하고, 12월 결산 투입(T4-21)도 R2R로만 확장된다. 즉 정상
        #      겸직의 본질은 "결산(R2R)과의 겸직"이며, R2R 없는 쌍(H2R-O2C,
        #      O2C-P2P, TRE-P2P 등 anomalous 계열)은 normal에서 0건
        #      (생성기 config anomalous_assignment_rate 0.0과 정합)
        #   4. junior_accountant × Treasury 문서 0건 (T3-09)
        # automated source 행은 배치 잡 소유라 사용자 전문화 주장에서 제외.
        rbac = doc_head.copy()
        rbac["_persona_norm"] = (
            rbac["user_persona"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
        )
        rbac["_process_norm"] = (
            rbac["business_process"].fillna("").astype(str).str.strip().str.upper()
        )
        rbac["_source_norm"] = rbac["source"].fillna("").astype(str).str.strip().str.lower()
        automated_source = rbac["_source_norm"].isin(
            {"automated", "recurring", "interface", "system"}
        )
        human = rbac.loc[~automated_source & ~rbac["_persona_norm"].isin({"automated_system", ""})]

        # TRE/TREASURY 표기 통일 (생성기는 Treasury, 카탈로그 축약은 TRE)
        process_alias = {"TREASURY": "TRE", "INTERCOMPANY": "IC"}
        human = human.assign(
            _process_norm=human["_process_norm"].map(lambda p: process_alias.get(p, p))
        )

        user_groups = human.groupby("created_by").agg(
            _persona=("_persona_norm", "first"),
            _processes=("_process_norm", lambda s: sorted(set(s))),
            _docs=("_process_norm", "size"),
        )
        junior_multi = {}
        over_breadth = {}
        bad_pairs = {}
        for user, row in user_groups.iterrows():
            persona, procs = row["_persona"], row["_processes"]
            if persona == "junior_accountant" and len(procs) > 1:
                junior_multi[user] = procs
            elif len(procs) > 2:
                over_breadth[f"{user}|{persona}"] = procs
            elif len(procs) == 2 and "R2R" not in procs:
                bad_pairs[f"{user}|{persona}"] = procs

        junior_treasury_docs = int(
            (
                (human["_persona_norm"] == "junior_accountant") & (human["_process_norm"] == "TRE")
            ).sum()
        )
        persona_user_breadth_max = (
            user_groups.assign(_breadth=user_groups["_processes"].map(len))
            .groupby("_persona")["_breadth"]
            .max()
            .to_dict()
        )
        findings.append(
            verdict(
                "Gate 0",
                "E05B_RBAC_PERSONA_PROCESS_SCOPE",
                "PASS"
                if not junior_multi
                and not over_breadth
                and not bad_pairs
                and junior_treasury_docs == 0
                else "FAIL",
                {
                    "human_documents_checked": int(len(human)),
                    "human_users_checked": int(len(user_groups)),
                    "junior_multi_process_users": {
                        str(k): v for k, v in list(junior_multi.items())[:10]
                    },
                    "over_breadth_users": {str(k): v for k, v in list(over_breadth.items())[:10]},
                    "non_compatible_pair_users": {
                        str(k): v for k, v in list(bad_pairs.items())[:10]
                    },
                    "junior_treasury_docs": junior_treasury_docs,
                    "persona_user_breadth_max": {
                        str(k): int(v) for k, v in persona_user_breadth_max.items()
                    },
                },
                "normal RBAC scope (user-level): junior single-process; senior+ at most one "
                "compatible dual assignment; anomalous pairs and junior-Treasury are overlay-only",
            )
        )

    approver_required = {"document_id", "approved_by", "debit_amount"}
    approver_missing = sorted(approver_required - set(df.columns))
    employee_path = dataset / "master_data" / "employees.json"
    if approver_missing or not employee_path.exists():
        findings.append(
            verdict(
                "Gate 0",
                "E05C_APPROVER_MASTER_AUTHORITY",
                "BLOCKED",
                {
                    "missing_required_columns": approver_missing,
                    "missing_employee_master": not employee_path.exists(),
                },
                "normal baseline approvers must be master-backed and authorized",
            )
        )
    else:
        employees = json.loads(employee_path.read_text(encoding="utf-8"))
        emp_rows = []
        for employee in employees if isinstance(employees, list) else []:
            if not isinstance(employee, dict):
                continue
            user_id = str(employee.get("user_id", "") or "").strip()
            if not user_id:
                continue
            emp_rows.append(
                {
                    "approved_by": user_id,
                    "_approver_can_approve_je": employee.get("can_approve_je", False),
                    "_approver_approval_limit": employee.get("approval_limit", 0),
                    "_approver_persona": employee.get("persona", employee.get("user_persona", "")),
                    "_approver_job_title": employee.get("job_title", ""),
                }
            )
        emp = pd.DataFrame(emp_rows)
        if emp.empty:
            approver_metric = {
                "approved_docs_checked": int(
                    doc_head["approved_by"].fillna("").astype(str).str.strip().ne("").sum()
                ),
                "employee_master_rows": 0,
            }
            findings.append(
                verdict(
                    "Gate 0",
                    "E05C_APPROVER_MASTER_AUTHORITY",
                    "FAIL",
                    approver_metric,
                    "normal baseline approvers must be master-backed and authorized",
                )
            )
        else:
            emp["_approver_can_approve_je"] = emp["_approver_can_approve_je"].map(
                lambda value: (
                    value if isinstance(value, bool) else str(value).strip().lower() == "true"
                )
            )
            emp["_approver_approval_limit"] = pd.to_numeric(
                emp["_approver_approval_limit"], errors="coerce"
            ).fillna(0)
            doc_amount = (
                df.assign(_debit_i=pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0))
                .groupby("document_id", sort=False)["_debit_i"]
                .sum()
                .rename("_document_debit_total")
                .reset_index()
            )
            approved_docs = (
                doc_head[["document_id", "approved_by", "business_process", "source"]]
                .copy()
                .assign(
                    approved_by=lambda frame: (
                        frame["approved_by"].fillna("").astype(str).str.strip()
                    )
                )
            )
            approved_docs = approved_docs[approved_docs["approved_by"].ne("")]
            approved_docs = approved_docs.merge(doc_amount, on="document_id", how="left")
            approved_docs = approved_docs.merge(emp, on="approved_by", how="left")
            unresolved = approved_docs["_approver_can_approve_je"].isna()
            unauthorized = approved_docs["_approver_can_approve_je"].eq(False)
            limit_bad = approved_docs["_approver_can_approve_je"].eq(True) & approved_docs[
                "_approver_approval_limit"
            ].fillna(0).lt(approved_docs["_document_debit_total"].fillna(0))
            authority_bad = unresolved | unauthorized
            limit_bad_docs = int(limit_bad.sum())
            approved_doc_count = int(len(approved_docs))
            limit_bad_rate = limit_bad_docs / max(approved_doc_count, 1)
            min_limit_bad_rate = 0.0005
            max_limit_bad_rate = 0.02
            limit_rate_in_range = min_limit_bad_rate <= limit_bad_rate <= max_limit_bad_rate
            bad = authority_bad | (
                limit_bad
                if not limit_rate_in_range
                else pd.Series(False, index=approved_docs.index)
            )
            bad_by_process = (
                approved_docs.loc[authority_bad | limit_bad, "business_process"]
                .fillna("")
                .astype(str)
                .value_counts()
                .head(10)
                .to_dict()
            )
            bad_approvers = (
                approved_docs.loc[
                    authority_bad | limit_bad,
                    ["approved_by", "_approver_persona", "_approver_job_title"],
                ]
                .fillna("")
                .astype(str)
                .drop_duplicates()
                .head(20)
                .to_dict(orient="records")
            )
            findings.append(
                verdict(
                    "Gate 0",
                    "E05C_APPROVER_MASTER_AUTHORITY",
                    "PASS" if int(authority_bad.sum()) == 0 and limit_rate_in_range else "FAIL",
                    {
                        "approved_docs_checked": approved_doc_count,
                        "unresolved_approver_docs": int(unresolved.sum()),
                        "unauthorized_approver_docs": int(unauthorized.sum()),
                        "approval_limit_exceeded_docs": limit_bad_docs,
                        "approval_limit_exceeded_rate": limit_bad_rate,
                        "approval_limit_exceeded_min_rate": min_limit_bad_rate,
                        "approval_limit_exceeded_max_rate": max_limit_bad_rate,
                        "authority_bad_docs": int(authority_bad.sum()),
                        "limit_rate_in_range": bool(limit_rate_in_range),
                        "bad_docs": int(authority_bad.sum())
                        + (0 if limit_rate_in_range else limit_bad_docs),
                        "exception_by_process_top10": {
                            str(k): int(v) for k, v in bad_by_process.items()
                        },
                        "exception_approver_examples": bad_approvers,
                    },
                    "approved_by users must exist and have can_approve_je=true; approval-limit exceedance must be present but bounded as a natural control exception",
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
        "VendorService": (
            "vendor_service_text_off_domain",
            "PROFESSIONAL_FEES",
            re.compile(r"전문|자문|용역|매입세액"),
        ),
        "VendorOfficeSupplies": (
            "vendor_office_text_off_domain",
            "OFFICE_SUPPLIES_PURCHASE",
            re.compile(r"사무|문구|복사|토너|오피스|매입세액"),
        ),
        "VendorRawMaterial": (
            "vendor_rawmaterial_text_off_domain",
            "RAW_MATERIAL_PURCHASE",
            re.compile(r"원자.?재|원재료|원자\s*입고|자재|재료|매입세액"),
        ),
        "VendorUtilities": (
            "vendor_utilities_text_off_domain",
            "UTILITIES",
            re.compile(r"전.?력|력.?전|전.?요금|력.?요금|수.?도|통.?신|전력|수도|통신|매입세액"),
        ),
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
                if str(row.line_text).strip()
                and str(row.semantic_account_subtype) not in tax_subtypes
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
    wrong_pattern = re.compile(
        r"fx revaluation|depreciation|CAPEX|고객|매출|원자재|전력요금|자문수수료", re.I
    )
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
            or not counterparty_types.issubset(
                {"IntercompanyAffiliate", "RELATED_PARTY", "RelatedParty"}
            )
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
        sub["base_amt"] = sub["abs_amount"].where(
            sub["semantic_account_subtype"].isin(base_subtypes), 0
        )
        agg = sub.groupby("document_id", sort=False)[["tax_amt", "base_amt"]].sum()
        tax_docs = agg[agg["tax_amt"] > 0].copy()
        tax_docs["ratio"] = tax_docs["tax_amt"] / tax_docs["base_amt"].replace(0, pd.NA)
        bad = tax_docs[(tax_docs["base_amt"] <= 0) | (tax_docs["ratio"] > 0.15)]
        tax_checks[scenario] = {
            "tax_docs": int(len(tax_docs)),
            "bad_ratio_gt_15pct_or_no_base": int(len(bad)),
            "no_base": int((tax_docs["base_amt"] <= 0).sum()),
            "ratio_p50": None
            if tax_docs.empty
            else float(tax_docs["ratio"].dropna().quantile(0.5)),
            "ratio_p95": None
            if tax_docs.empty
            else float(tax_docs["ratio"].dropna().quantile(0.95)),
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
        required_treatments = {
            "taxable_10",
            "zero_rated_export",
            "exempt",
            "non_taxable",
            "import_vat",
        }
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
            & (
                (doc_tax["supporting"] != "세금계산서")
                | (~doc_tax["has_vat_line"])
                | (doc_tax["tax_amount"] <= 0)
            )
        ]
        bad_import = doc_tax[
            doc_tax["treatment"].map(lambda x: "import_vat" in x)
            & (
                (doc_tax["supporting"] != "수입장")
                | (~doc_tax["has_vat_line"])
                | (doc_tax["tax_amount"] <= 0)
            )
        ]
        bad_zero = doc_tax[
            doc_tax["treatment"].map(lambda x: "zero_rated_export" in x)
            & (
                (doc_tax["supporting"] != "수출신고필증")
                | (doc_tax["has_vat_line"])
                | (doc_tax["tax_amount"] != 0)
            )
        ]
        bad_exempt = doc_tax[
            doc_tax["treatment"].map(lambda x: "exempt" in x)
            & (
                (doc_tax["supporting"] != "계산서")
                | (doc_tax["has_vat_line"])
                | (doc_tax["tax_amount"] != 0)
            )
        ]
        bad_non_taxable = doc_tax[
            doc_tax["treatment"].map(lambda x: "non_taxable" in x)
            & (
                doc_tax["has_vat_line"]
                | (doc_tax["tax_amount"] != 0)
                | doc_tax["tax_codes"].map(bool)
            )
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
        "missing_field_rate_per_row": (
            dq_stats.get("missing_values", {}).get("total_missing", 0) / max(total_rows, 1)
        ),
        "text_format_variation_rate_per_row": (
            dq_stats.get("format_variations", {}).get("text_variations", 0) / max(total_rows, 1)
        ),
        "typo_rate_per_row": (dq_stats.get("typos", {}).get("total_typos", 0) / max(total_rows, 1)),
        "records_with_issues_rate_per_doc": (
            dq_stats.get("records_with_issues", 0)
            / max(dq_stats.get("total_records", total_docs), 1)
        ),
    }
    noise_status = "PASS"
    if (
        true_noise["records_with_issues_rate_per_doc"] > 0.15
        or true_noise["text_format_variation_rate_per_row"] > 0.05
    ):
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
    top_exact_share = (
        float(positive.value_counts(normalize=True).head(1).iloc[0]) if len(positive) else 0.0
    )
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
    c07_status, c07_metric = _stable_account_yoy_volatility_metrics(df, _load_coa_meta(dataset))
    findings.append(
        verdict(
            "Gate 2",
            "C07_STABLE_ACCOUNT_YOY_VOLATILITY",
            c07_status,
            c07_metric,
            "stable accounts such as tax, interest, depreciation/amortization, and rent must not swing by implausible account-level YoY ratios",
        )
    )
    c06_status, c06_metric = _rare_account_pair_reuse_metrics(df)
    findings.append(
        verdict(
            "Gate 2",
            "C06_ACCOUNT_PAIR_REUSE",
            c06_status,
            c06_metric,
            "normal ERP account determination should reuse concrete debit-credit account pairs; L4-04-like rare pairs must not be dominated by subtype fragmentation. NOTE: this check reads the RESULT only, so it can be satisfied by post-hoc rewriting of gl_account -- ACC02 checks the METHOD and is the one that blocks that",
        )
    )

    # 계정 체계 검사. C06가 결과만 보는 탓에 최빈계정 강제치환으로 통과당한 이력이 있어,
    # ACC02가 생성기의 계정결정 표 준수를 직접 본다.
    for test_id, status, metric, notes in run_account_checks(df, dataset):
        findings.append(verdict("Gate 2", test_id, status, metric, notes))

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
        # These are intentionally process-scoped in a normal RBAC model and are
        # checked by E05B instead of treated as generator fingerprints here.
        "user_persona",
        "created_by",
        "approved_by",
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
            company_values = (
                set(df["company_code"].fillna("").astype(str).str.strip())
                if "company_code" in df.columns
                else set()
            )
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
        for scenario, group in df[df["_marker_amount"] > 0].groupby(
            "semantic_scenario_id", sort=False
        ):
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

    marker_findings = sorted(
        marker_findings,
        key=lambda item: item.get("documents", item.get("top_count", 0)),
        reverse=True,
    )
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
                "delegated_structural_rbac_columns": ["user_persona", "created_by", "approved_by"],
            },
            "all-column synthetic marker scan for generator fingerprints",
        )
    )

    company_codes = (
        set(df["company_code"].fillna("").astype(str).str.strip())
        if "company_code" in df.columns
        else set()
    )
    has_ic_required = all(
        col in df.columns
        for col in ["is_intercompany", "company_code", "trading_partner", "gl_account"]
    )
    if not has_ic_required:
        missing = [
            col
            for col in ["is_intercompany", "company_code", "trading_partner", "gl_account"]
            if col not in df.columns
        ]
        for test_id, note in [
            ("K01", "single-company journal scope"),
            ("K02", "normal related-party IC background required"),
            ("K03", "normal IC GL prefix population required"),
            ("K04", "normal IC dates must be plausible"),
            ("K05", "company-code partners allowed only for related-party IC rows"),
            ("K06", "no company-node graph cycle background"),
            ("K07", "normal IC direction population should not be one-sided"),
        ]:
            findings.append(
                verdict(
                    "Gate 1" if test_id <= "K05" else "Gate 2",
                    test_id,
                    "BLOCKED",
                    {"missing_required_columns": missing},
                    note,
                )
            )
    else:
        primary_company = "C001"
        ic_mask = _truthy(df["is_intercompany"])
        ic_df = df[ic_mask].copy()
        ic_doc_count = int(ic_df["document_id"].nunique())
        ic_row_count = int(len(ic_df))
        partner_all = df["trading_partner"].fillna("").astype(str).str.strip()
        company_partner_rows = int(partner_all.isin(company_codes | {"C002", "C003"}).sum())
        related_surface = (
            df["counterparty_type"]
            .fillna("")
            .astype(str)
            .str.contains("Intercompany|RELATED_PARTY|Related", case=False, regex=True)
            | df["semantic_scenario_id"]
            .fillna("")
            .astype(str)
            .str.contains("IC_|INTERCOMPANY|RELATED", case=False, regex=True)
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
        findings.append(
            verdict(
                "Gate 1",
                "K01",
                "PASS" if k01_pass else "FAIL",
                k01_metric,
                "single legal-entity journal scope",
            )
        )

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
        findings.append(
            verdict(
                "Gate 1",
                "K02",
                "PASS" if k02_pass else "FAIL",
                k02_metric,
                "single-company normal must contain low-volume related-party IC traces without adding extra ledger companies",
            )
        )

        recon = _ic_reconciliation_metrics(df, pair_map)
        k03_metric = dict(recon)
        k03_metric.update({"receivable_prefix_rows": rec_rows, "payable_prefix_rows": pay_rows})
        k03_pass = rec_rows > 0 and pay_rows > 0
        findings.append(
            verdict(
                "Gate 1",
                "K03",
                "PASS" if k03_pass else "FAIL",
                k03_metric,
                "normal related-party IC must include both receivable/revenue and payable/cost traces",
            )
        )

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
        k04_pass = (
            ic_row_count > 0 and ic_dates_missing == 0 and recon["close_lag_exceeded_pairs"] == 0
        )
        findings.append(
            verdict(
                "Gate 1",
                "K04",
                "PASS" if k04_pass else "FAIL",
                k04_metric,
                "normal related-party IC timing must have populated dates and no stale close-lag pattern",
            )
        )

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
        findings.append(
            verdict(
                "Gate 1",
                "K05",
                "PASS" if k05_pass else "FAIL",
                k05_metric,
                "company-code partners are allowed only as related-party trading_partner values on IC rows",
            )
        )

        cycle_metrics = _ic_cycle_metrics(df)
        k06_pass = (
            bool(cycle_metrics.get("networkx_available", False))
            and int(cycle_metrics.get("cycle_instance_count", 0)) == 0
        )
        findings.append(
            verdict(
                "Gate 2",
                "K06",
                "PASS" if k06_pass else "FAIL",
                cycle_metrics,
                "single-company normal must not contain company-node graph cycles",
            )
        )

        asym = _ic_direction_asymmetry_metrics(df)
        k07_pass = (
            int(asym["direction_pair_count"]) > 0 and float(asym["high_asymmetry_rate"]) <= 0.75
        )
        findings.append(
            verdict(
                "Gate 2",
                "K07",
                "PASS" if k07_pass else "FAIL",
                asym,
                "normal related-party IC should have a directional population without being entirely one-sided",
            )
        )

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
                "stratification": [
                    "semantic_scenario_id",
                    "business_process",
                    "document_type",
                    "source",
                ],
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
        "# Normal Data Realism Verifier",
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
