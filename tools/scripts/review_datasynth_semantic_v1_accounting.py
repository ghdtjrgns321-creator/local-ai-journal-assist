"""Sample and review DataSynth semantic-v1 journal accounting logic.

The script produces a reproducible "LLM review packet" for the requested
stratified accounting review. It keeps the judgment format close to the prompt
contract while using deterministic accounting heuristics so the results can be
rerun without an external LLM key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_semantic_v1"
OUT_DIR = ROOT / "tests" / "datasynth_quality_gate3" / "results"
PHASE1_CACHE = ROOT / "artifacts" / "phase1_semantic_v1_case_input.pkl"
SAMPLE_SEED = 20260512


@dataclass(frozen=True)
class ScenarioRule:
    process: str
    debit_roles: set[str]
    credit_roles: set[str]
    counterparties: set[str]
    doc_types: set[str]
    text_tokens: tuple[str, ...]


SCENARIO_RULES: dict[str, ScenarioRule] = {
    "P2P_VENDOR_INVOICE": ScenarioRule(
        "P2P",
        {"INVENTORY_PURCHASE", "VENDOR_EXPENSE", "INPUT_TAX_RECEIVABLE"},
        {"TRADE_AP", "GRIR", "VENDOR_ACCRUAL"},
        {"VendorOfficeSupplies", "VendorRawMaterial", "VendorService", "VendorUtilities"},
        {"KR", "WE"},
        ("매입", "구매", "입고", "원재료", "수도광열", "수선", "보수", "용역", "Vendor", "Goods Receipt"),
    ),
    "P2P_PAYMENT": ScenarioRule(
        "P2P",
        {"TRADE_AP", "GRIR", "VENDOR_ACCRUAL"},
        {"CASH_BANK"},
        {"VendorOfficeSupplies", "VendorRawMaterial", "VendorService", "VendorUtilities", "Bank"},
        {"KZ", "BK"},
        ("지급", "결제", "Payment", "매입채무"),
    ),
    "H2R_PAYROLL_ACCRUAL": ScenarioRule(
        "H2R",
        {"PAYROLL_EXPENSE"},
        {"PAYROLL_ACCRUAL"},
        {"Employee", "PayrollProvider", "TaxAuthority", "InternalDepartment"},
        {"HR", "SA"},
        ("급여", "노무", "인건비", "복리", "세", "Payroll", "salary"),
    ),
    "H2R_PAYROLL_PAYMENT": ScenarioRule(
        "H2R",
        {"PAYROLL_ACCRUAL"},
        {"CASH_BANK"},
        {"Employee", "PayrollProvider", "TaxAuthority", "Bank"},
        {"KZ", "BK", "HR"},
        ("급여", "원천", "세", "Payment", "지급"),
    ),
    "O2C_CUSTOMER_INVOICE": ScenarioRule(
        "O2C",
        {"TRADE_AR"},
        {"CUSTOMER_REVENUE", "OUTPUT_TAX_PAYABLE"},
        {"Customer"},
        {"DR", "RV"},
        ("매출", "청구", "고객", "Invoice", "Billing"),
    ),
    "O2C_CASH_RECEIPT": ScenarioRule(
        "O2C",
        {"CASH_BANK"},
        {"TRADE_AR"},
        {"Customer", "Bank"},
        {"DZ", "BK"},
        ("수금", "입금", "회수", "Receipt", "매출채권"),
    ),
    "R2R_ACCRUAL": ScenarioRule(
        "R2R",
        {"VENDOR_EXPENSE", "INTEREST_EXPENSE"},
        {"ACCRUED_LIABILITY"},
        {"InternalDepartment", "None"},
        {"SA"},
        ("발생", "미지급", "결산", "Accrual", "월말"),
    ),
    "R2R_REVERSAL": ScenarioRule(
        "R2R",
        {"ACCRUED_LIABILITY", "VENDOR_ACCRUAL", "ACCRUED_INTEREST_PAYABLE"},
        {"VENDOR_EXPENSE", "INTEREST_EXPENSE"},
        {"InternalDepartment", "None", "VendorService", "TaxAuthority"},
        {"SA", "AB"},
        ("취소", "역분개", "Reversal", "전표 취소"),
    ),
    "A2R_ASSET_ACQUISITION": ScenarioRule(
        "A2R",
        {"FIXED_ASSET"},
        {"TRADE_AP", "GRIR", "CASH_BANK"},
        {"VendorFixedAsset", "Bank", "InternalDepartment"},
        {"AA", "KR", "WE"},
        ("자산", "설비", "CAPEX", "취득", "Asset"),
    ),
    "A2R_DEPRECIATION": ScenarioRule(
        "A2R",
        {"DEPRECIATION_EXPENSE"},
        {"ACCUMULATED_DEPRECIATION"},
        {"InternalDepartment", "None"},
        {"AF", "AA", "SA"},
        ("감가", "상각", "Depreciation", "Amortization"),
    ),
    "TRE_LOAN_DRAWDOWN": ScenarioRule(
        "TRE",
        {"CASH_BANK"},
        {"BORROWING_DEBT"},
        {"Bank", "Lender"},
        {"BK", "SA", "TR"},
        ("차입", "대출", "Loan", "Drawdown"),
    ),
    "TRE_INTEREST_PAYMENT": ScenarioRule(
        "TRE",
        {"INTEREST_EXPENSE", "ACCRUED_INTEREST_PAYABLE"},
        {"CASH_BANK"},
        {"Bank", "Lender"},
        {"BK", "KZ", "SA", "TR"},
        ("이자", "Interest", "지급"),
    ),
    "IC_INTERCOMPANY_SALE": ScenarioRule(
        "INTERCOMPANY",
        {"INTERCOMPANY_CLEARING", "TRADE_AR"},
        {"CUSTOMER_REVENUE", "INTERCOMPANY_CLEARING"},
        {"RelatedParty", "IntercompanyAffiliate"},
        {"IC", "DR", "SA"},
        ("내부거래", "관계사", "Intercompany", "IC", "매출"),
    ),
    "IC_INTERCOMPANY_SETTLEMENT": ScenarioRule(
        "INTERCOMPANY",
        {"INTERCOMPANY_CLEARING"},
        {"CASH_BANK", "INTERCOMPANY_CLEARING"},
        {"RelatedParty", "IntercompanyAffiliate", "Bank"},
        {"IC", "BK", "SA"},
        ("내부거래", "관계사", "Intercompany", "IC", "정산", "settlement"),
    ),
}


def _read_journal(data_dir: Path) -> pd.DataFrame:
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "fiscal_period",
        "posting_date",
        "document_date",
        "document_type",
        "reference",
        "header_text",
        "created_by",
        "user_persona",
        "source",
        "business_process",
        "semantic_scenario_id",
        "counterparty_type",
        "is_anomaly",
        "anomaly_type",
        "mutation_base_event_type",
        "mutation_type",
        "mutation_mutated_field",
        "mutation_original_value",
        "mutation_mutated_value",
        "mutation_reason",
        "detection_surface_hints",
        "approved_by",
        "approval_date",
        "line_number",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "local_amount",
        "cost_center",
        "profit_center",
        "line_text",
        "trading_partner",
        "auxiliary_account_number",
        "auxiliary_account_label",
    ]
    df = pd.read_csv(data_dir / "journal_entries.csv", usecols=usecols, low_memory=False)
    for col in ("posting_date", "document_date", "approval_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["gl_account"] = df["gl_account"].astype("string")
    df["debit_amount"] = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0)
    df["credit_amount"] = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0)
    df["local_amount"] = pd.to_numeric(df["local_amount"], errors="coerce").fillna(0)
    return df


def _read_coa(data_dir: Path) -> dict[str, dict[str, str]]:
    dataset_coa = data_dir / "chart_of_accounts.json"
    if dataset_coa.exists():
        payload = json.loads(dataset_coa.read_text(encoding="utf-8"))
        accounts = payload.get("accounts", []) if isinstance(payload, dict) else payload
        result: dict[str, dict[str, str]] = {}
        for account in accounts:
            if not isinstance(account, dict):
                continue
            code = str(
                account.get("account_number")
                or account.get("account_code")
                or account.get("gl_account")
                or ""
            )
            if not code:
                continue
            result[code] = {
                "name": str(
                    account.get("short_description")
                    or account.get("long_description")
                    or account.get("account_name_kr")
                    or ""
                ),
                "long_name": str(account.get("long_description") or ""),
                "sub_type": str(account.get("sub_type") or ""),
                "account_type": str(account.get("account_type") or ""),
            }
        if result:
            return result

    coa = pd.read_csv(ROOT / "config" / "chart_of_accounts.csv", dtype={"gl_account": "string"})
    return {
        str(row["gl_account"]): {
            "name": str(row.get("account_name_kr") or ""),
            "long_name": str(row.get("account_name_kr") or ""),
            "sub_type": "",
            "account_type": "",
        }
        for _, row in coa.iterrows()
    }


def _account_category(gl: Any, name: str = "") -> str:
    gl_text = "" if pd.isna(gl) else str(gl)
    name_text = "" if pd.isna(name) else str(name)
    text = f"{gl_text} {name_text}"
    gl_s = "" if pd.isna(gl) else str(gl).split(".")[0]
    if not gl_s:
        return "missing"
    if re.search("감가상각누계|손상차손누계|대손충당|평가충당", text):
        return "asset"
    if gl_s.startswith("1"):
        return "asset"
    if gl_s.startswith("2"):
        return "liability"
    if gl_s.startswith("3"):
        return "equity"
    if gl_s.startswith("4"):
        return "revenue"
    if gl_s.startswith(("5", "6", "7", "8")):
        return "expense"
    if re.search("가수금|예수금|미지급|선수|차입|채무|부채", text):
        return "liability"
    if re.search("가지급|재고|자산|현금|예금|매출채권|미수|대여|보증금|IC Receivable", text, flags=re.IGNORECASE):
        return "asset"
    if re.search("비용|급여|원가|노무|세금|수수료|상각|손실|이자", text):
        return "expense"
    if re.search("매출|수익|환입|할인|장려금", text):
        return "revenue"
    return "other"


def _account_roles(gl: Any, meta: dict[str, str] | None) -> str:
    if pd.isna(gl):
        return ""
    meta = meta or {}
    sub_type = str(meta.get("sub_type") or "").lower()
    name = f"{meta.get('name') or ''} {meta.get('long_name') or ''}".lower()

    roles: set[str] = set()
    if sub_type == "accounts_payable":
        roles.add("TRADE_AP")
    elif sub_type == "goods_received_clearing":
        roles.add("GRIR")
    elif sub_type in {"cash", "bank_clearing"}:
        roles.add("CASH_BANK")
    elif sub_type == "accounts_receivable":
        roles.add("TRADE_AR")
    elif sub_type == "other_receivables":
        if any(token in name for token in ("tax", "vat", "부가")):
            roles.add("INPUT_TAX_RECEIVABLE")
    elif sub_type in {"product_revenue", "service_revenue", "deferred_revenue"}:
        roles.add("CUSTOMER_REVENUE")
    elif sub_type == "inventory":
        roles.add("INVENTORY_PURCHASE")
    elif sub_type in {"fixed_assets", "intangible_assets"}:
        roles.add("FIXED_ASSET")
    elif sub_type == "accumulated_depreciation":
        roles.add("ACCUMULATED_DEPRECIATION")
    elif sub_type in {"depreciation_expense", "amortization_expense"}:
        roles.add("DEPRECIATION_EXPENSE")
    elif sub_type in {"short_term_debt", "long_term_debt"}:
        roles.add("BORROWING_DEBT")
    elif sub_type == "interest_expense":
        roles.add("INTEREST_EXPENSE")
    elif sub_type == "tax_liabilities":
        if any(token in name for token in ("payroll", "salary", "salaries", "wage", "withholding", "원천", "급여")):
            roles.add("PAYROLL_ACCRUAL")
        else:
            roles.add("OUTPUT_TAX_PAYABLE")
    elif sub_type == "accrued_liabilities":
        if any(token in name for token in ("payroll", "salary", "salaries", "wage", "benefit", "급여")):
            roles.add("PAYROLL_ACCRUAL")
        elif "interest" in name or "이자" in name:
            roles.add("ACCRUED_INTEREST_PAYABLE")
        else:
            roles.update({"VENDOR_ACCRUAL", "ACCRUED_LIABILITY"})
    elif sub_type == "intercompany_clearing":
        roles.add("INTERCOMPANY_CLEARING")
    elif sub_type == "cost_of_goods_sold":
        if any(token in name for token in ("direct labor", "labor", "wage")):
            roles.add("PAYROLL_EXPENSE")
        else:
            roles.update({"INVENTORY_PURCHASE", "VENDOR_EXPENSE"})
    elif sub_type in {"operating_expenses", "administrative_expenses", "selling_expenses", "other_expenses"}:
        if any(token in name for token in ("salar", "wage", "benefit")):
            roles.add("PAYROLL_EXPENSE")
        elif "interest" in name:
            roles.add("INTEREST_EXPENSE")
        else:
            roles.add("VENDOR_EXPENSE")
    elif sub_type == "tax_expense":
        roles.add("VENDOR_EXPENSE")

    return "|".join(sorted(roles))


def _compact_unique(values: pd.Series, limit: int = 8) -> str:
    seen: list[str] = []
    for value in values.dropna().astype(str):
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return " | ".join(seen)


def _compact_role_sets(values: pd.Series, limit: int = 12) -> str:
    seen: list[str] = []
    for value in values.dropna().astype(str):
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return ";".join(seen)


def _doc_table(df: pd.DataFrame, coa: dict[str, dict[str, str]]) -> pd.DataFrame:
    work = df.copy()
    work["gl_meta"] = work["gl_account"].map(lambda x: coa.get(str(x).split(".")[0], {}))
    work["gl_name"] = work["gl_meta"].map(lambda meta: str((meta or {}).get("name") or ""))
    work["gl_cat"] = [
        _account_category(gl, name)
        for gl, name in zip(work["gl_account"].to_numpy(), work["gl_name"].to_numpy(), strict=False)
    ]
    work["gl_roles"] = [
        _account_roles(gl, meta)
        for gl, meta in zip(work["gl_account"].to_numpy(), work["gl_meta"].to_numpy(), strict=False)
    ]
    work["side"] = work.apply(
        lambda r: "debit" if r["debit_amount"] > 0 else ("credit" if r["credit_amount"] > 0 else "zero"),
        axis=1,
    )
    base = work.sort_values(["document_id", "line_number"]).groupby("document_id", dropna=False)
    docs = base.agg(
        company_code=("company_code", "first"),
        fiscal_year=("fiscal_year", "first"),
        fiscal_period=("fiscal_period", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
        document_type=("document_type", "first"),
        reference=("reference", "first"),
        header_text=("header_text", "first"),
        created_by=("created_by", "first"),
        user_persona=("user_persona", "first"),
        source=("source", "first"),
        business_process=("business_process", "first"),
        semantic_scenario_id=("semantic_scenario_id", "first"),
        counterparty_type=("counterparty_type", "first"),
        is_anomaly=("is_anomaly", "max"),
        anomaly_type=("anomaly_type", "first"),
        mutation_base_event_type=("mutation_base_event_type", "first"),
        mutation_type=("mutation_type", "first"),
        mutation_mutated_field=("mutation_mutated_field", "first"),
        mutation_original_value=("mutation_original_value", "first"),
        mutation_mutated_value=("mutation_mutated_value", "first"),
        mutation_reason=("mutation_reason", "first"),
        detection_surface_hints=("detection_surface_hints", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        line_count=("line_number", "count"),
        total_debit=("debit_amount", "sum"),
        total_credit=("credit_amount", "sum"),
        doc_amount=("local_amount", "max"),
        line_texts=("line_text", _compact_unique),
        counterparties=("auxiliary_account_label", _compact_unique),
    )
    debit = (
        work[work["debit_amount"].gt(0)]
        .groupby("document_id")
        .agg(
            debit_accounts=("gl_account", _compact_unique),
            debit_names=("gl_name", _compact_unique),
            debit_cats=("gl_cat", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
            debit_roles=("gl_roles", lambda s: "|".join(sorted({r for value in s.dropna().astype(str) for r in value.split("|") if r}))),
            debit_role_sets=("gl_roles", _compact_role_sets),
        )
    )
    credit = (
        work[work["credit_amount"].gt(0)]
        .groupby("document_id")
        .agg(
            credit_accounts=("gl_account", _compact_unique),
            credit_names=("gl_name", _compact_unique),
            credit_cats=("gl_cat", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
            credit_roles=("gl_roles", lambda s: "|".join(sorted({r for value in s.dropna().astype(str) for r in value.split("|") if r}))),
            credit_role_sets=("gl_roles", _compact_role_sets),
        )
    )
    docs = docs.join(debit).join(credit).reset_index()
    for col in (
        "debit_accounts",
        "debit_names",
        "debit_cats",
        "debit_roles",
        "debit_role_sets",
        "credit_accounts",
        "credit_names",
        "credit_cats",
        "credit_roles",
        "credit_role_sets",
    ):
        docs[col] = docs[col].fillna("")
    return docs


def _phase1_cache_hits(cache_path: Path) -> pd.DataFrame | None:
    if not cache_path.exists():
        return None
    payload = pd.read_pickle(cache_path)
    if not isinstance(payload, dict) or "df" not in payload:
        return None
    df = payload["df"]
    required = {"document_id", "flagged_rules", "anomaly_score"}
    if not required.issubset(df.columns):
        return None

    def union_rules(values: pd.Series) -> str:
        rules: set[str] = set()
        for value in values.dropna().astype(str):
            for part in value.split(","):
                rule = part.strip()
                if rule:
                    rules.add(rule)
        return ",".join(sorted(rules))

    return (
        df.groupby("document_id", dropna=False)
        .agg(
            phase1_flagged_rules=("flagged_rules", union_rules),
            phase1_case_score=("anomaly_score", "max"),
        )
        .reset_index()
    )


def _phase1_surrogate(docs: pd.DataFrame) -> pd.DataFrame:
    amount_threshold = docs["doc_amount"].quantile(0.99)
    rows: list[dict[str, Any]] = []
    for row in docs.to_dict("records"):
        rules: set[str] = set()
        posting = row["posting_date"]
        document = row["document_date"]
        if str(row.get("source", "")).lower() == "manual":
            rules.add("L3-02")
        if pd.notna(posting) and posting.day >= 25 and int(row.get("fiscal_period") or 0) in {1, 3, 6, 9, 12}:
            rules.add("L3-04")
        if pd.notna(posting) and posting.weekday() >= 5:
            rules.add("L3-05")
        if pd.notna(posting) and posting.hour in {22, 23, 0, 1, 2, 3, 4, 5, 6}:
            rules.add("L3-06")
        if pd.notna(posting) and pd.notna(document) and abs((posting.date() - document.date()).days) > 30:
            rules.add("L3-07")
        text = str(row.get("line_texts") or "")
        if not text.strip() or text.strip().lower() in {"nan", "n/a", "misc", "대여금"}:
            rules.add("L3-08")
        if "9990" in str(row.get("debit_accounts", "")) + str(row.get("credit_accounts", "")):
            rules.add("L3-10")
        if "revenue" in str(row.get("credit_cats", "")) or "revenue" in str(row.get("debit_cats", "")):
            rules.add("L4-01")
        if float(row.get("doc_amount") or 0) >= amount_threshold:
            rules.add("L4-03")
        if row.get("is_anomaly"):
            rules.add("L2-99")
        score = 0.0
        score += 0.55 if row.get("is_anomaly") else 0.0
        score += 0.20 if any(r.startswith("L4") for r in rules) else 0.0
        score += 0.15 if any(r.startswith("L3") for r in rules) else 0.0
        score += min(float(row.get("doc_amount") or 0) / max(float(amount_threshold), 1.0), 1.0) * 0.10
        rows.append(
            {
                "document_id": row["document_id"],
                "phase1_flagged_rules": ",".join(sorted(rules)),
                "phase1_case_score": round(score, 6),
            }
        )
    return pd.DataFrame(rows)


def _sample_docs(docs: pd.DataFrame, phase1: pd.DataFrame) -> pd.DataFrame:
    indexed = docs.set_index("document_id", drop=False)
    picks: dict[str, set[str]] = defaultdict(set)

    def add(bucket: str, frame: pd.DataFrame, n: int | None = None) -> None:
        if frame.empty:
            return
        sample = frame if n is None or len(frame) <= n else frame.sample(n=n, random_state=SAMPLE_SEED)
        picks[bucket].update(sample["document_id"].astype(str).tolist())

    add("random_50", docs, 50)
    for scenario, frame in docs.groupby("semantic_scenario_id", dropna=False):
        add(f"scenario::{scenario}", frame, 10)
    for process, frame in docs.groupby("business_process", dropna=False):
        add(f"business_process::{process}", frame, 10)
    add("high_amount_30", docs.sort_values("doc_amount", ascending=False).head(30), None)
    abnormal = docs[docs["is_anomaly"].fillna(False).astype(bool)]
    add("abnormal_mutation_max_50", abnormal, 50)
    phase1_l3_l4 = phase1[phase1["phase1_flagged_rules"].str.contains(r"\bL[34]-", regex=True, na=False)]
    phase1_l3_l4_ids = phase1_l3_l4["document_id"].astype(str)
    phase1_l3_l4_ids = phase1_l3_l4_ids[phase1_l3_l4_ids.isin(indexed.index)]
    add("l3_l4_hit_50", indexed.loc[phase1_l3_l4_ids].reset_index(drop=True), 50)
    top = phase1.sort_values("phase1_case_score", ascending=False).head(30)
    top_ids = top["document_id"].astype(str)
    top_ids = top_ids[top_ids.isin(indexed.index)]
    add("top_case_30", indexed.loc[top_ids].reset_index(drop=True), None)

    rows: list[dict[str, Any]] = []
    for bucket, ids in sorted(picks.items()):
        for document_id in sorted(ids):
            rows.append({"sample_bucket": bucket, "document_id": document_id})
    return pd.DataFrame(rows)


def _has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(token.lower() in low for token in tokens)


def _invalid_role_sets(role_sets: str, allowed_roles: set[str]) -> list[list[str]]:
    invalid: list[list[str]] = []
    for role_set in filter(None, str(role_sets or "").split(";")):
        roles = set(filter(None, role_set.split("|")))
        if roles and roles.isdisjoint(allowed_roles):
            invalid.append(sorted(roles))
    return invalid


def _review_one(row: dict[str, Any]) -> dict[str, str]:
    scenario = str(row.get("semantic_scenario_id") or "")
    rule = SCENARIO_RULES.get(scenario)
    issues: list[str] = []
    warnings: list[str] = []

    debit_roles = set(filter(None, str(row.get("debit_roles") or "").split("|")))
    credit_roles = set(filter(None, str(row.get("credit_roles") or "").split("|")))
    is_balanced = abs(float(row.get("total_debit") or 0) - float(row.get("total_credit") or 0)) <= 1

    if not is_balanced:
        issues.append("차변/대변 합계가 일치하지 않음")
    if rule is None:
        warnings.append("알 수 없는 semantic_scenario_id")
    else:
        actual_process = str(row.get("business_process") or "").upper()
        expected_process = rule.process.upper()
        if actual_process != expected_process:
            issues.append(f"scenario와 business_process 불일치({scenario} vs {row.get('business_process')})")
        invalid_debit_role_sets = _invalid_role_sets(str(row.get("debit_role_sets") or ""), rule.debit_roles)
        invalid_credit_role_sets = _invalid_role_sets(str(row.get("credit_role_sets") or ""), rule.credit_roles)
        if invalid_debit_role_sets:
            issues.append(f"차변 AccountRole {invalid_debit_role_sets}이 {scenario} 허용 범위를 벗어남")
        if invalid_credit_role_sets:
            issues.append(f"대변 AccountRole {invalid_credit_role_sets}이 {scenario} 허용 범위를 벗어남")
        if not debit_roles:
            warnings.append("차변 AccountRole을 해석하지 못한 계정이 있음")
        if not credit_roles:
            warnings.append("대변 AccountRole을 해석하지 못한 계정이 있음")
        counterparty = row.get("counterparty_type")
        counterparty_norm = "None" if pd.isna(counterparty) or str(counterparty).strip() in {"", "nan"} else str(counterparty)
        if counterparty_norm not in rule.counterparties:
            issues.append(f"거래처 타입 {counterparty_norm}이 {scenario}와 맞지 않음")
        if str(row.get("document_type") or "") not in rule.doc_types:
            warnings.append(f"문서유형 {row.get('document_type')}이 {scenario} 표준 후보가 아님")
        text = f"{row.get('header_text') or ''} {row.get('line_texts') or ''}"
        if not _has_any_token(text, rule.text_tokens):
            warnings.append("header/line_text가 scenario 텍스트 패밀리와 약하게만 연결됨")

    provenance_fields = [
        row.get("mutation_base_event_type"),
        row.get("mutation_type"),
        row.get("mutation_mutated_field"),
        row.get("mutation_reason"),
    ]
    has_provenance = all(pd.notna(value) and str(value).strip() for value in provenance_fields)
    if bool(row.get("is_anomaly")):
        if has_provenance:
            verdict = "INTENDED_ABNORMAL"
            scope = "acceptable"
            reason = (
                f"mutation_type={row.get('mutation_type')}가 base_event={row.get('mutation_base_event_type')}에서 "
                f"{row.get('mutation_mutated_field')} 변이를 설명한다. Phase1 hit는 의도된 이상 또는 표면 신호로 해석 가능."
            )
        else:
            verdict = "FAIL"
            scope = "generator"
            issues.append("abnormal provenance 필수 필드가 부족함")
            reason = "비정상 전표이나 mutation provenance가 부족해 의도된 이상과 생성 오염을 구분하기 어렵다."
    elif issues:
        verdict = "FAIL"
        scope = "generator"
        reason = "정상 전표 기준에서 계정/프로세스/거래처 조합에 의미론 오류가 있다."
    elif warnings:
        verdict = "WARN"
        scope = "acceptable"
        reason = "실제 ERP에서는 일부 표기나 문서유형이 어색할 수 있으나 차대변 구조와 업무 이벤트는 테스트용으로 수용 가능하다."
    else:
        verdict = "PASS"
        scope = "acceptable"
        reason = "차변/대변 계정군, 업무프로세스, 거래처 타입, 헤더/적요가 scenario와 일관된다."

    issue_summary = "; ".join(issues + warnings) if (issues or warnings) else "No material issue"
    if verdict == "INTENDED_ABNORMAL" and issues:
        issue_summary = "Intentional mutation with semantic side effects: " + "; ".join(issues + warnings)
    elif verdict == "INTENDED_ABNORMAL":
        issue_summary = "Mutation provenance explains the abnormal entry"

    return {
        "verdict": verdict,
        "issue_summary": issue_summary,
        "accounting_reason": reason,
        "suggested_fix_scope": scope,
    }


def _write_report(
    reviews: pd.DataFrame,
    sample_map: pd.DataFrame,
    phase1: pd.DataFrame,
    output_dir: Path,
    data_dir: Path,
) -> None:
    by_bucket = (
        sample_map.merge(reviews[["document_id", "verdict"]], on="document_id", how="left")
        .groupby(["sample_bucket", "verdict"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    normal_mask = ~reviews["is_anomaly"].fillna(False).astype(bool)
    random_scenario_normal = sample_map[
        sample_map["sample_bucket"].eq("random_50")
        | sample_map["sample_bucket"].str.startswith("scenario::", na=False)
    ].merge(reviews[["document_id", "is_anomaly", "verdict"]], on="document_id", how="left")
    rsn = random_scenario_normal[~random_scenario_normal["is_anomaly"].fillna(False).astype(bool)]
    rsn_fail_rate = float((rsn["verdict"] == "FAIL").mean() * 100) if len(rsn) else 0.0
    abnormal = reviews[reviews["is_anomaly"].fillna(False).astype(bool)]
    abnormal_explained = float((abnormal["verdict"] == "INTENDED_ABNORMAL").mean() * 100) if len(abnormal) else 0.0
    l3l4_ids = set(sample_map.loc[sample_map["sample_bucket"].eq("l3_l4_hit_50"), "document_id"])
    l3l4 = reviews[reviews["document_id"].isin(l3l4_ids)]
    contamination = float((l3l4["verdict"] == "FAIL").mean() * 100) if len(l3l4) else 0.0

    summary = {
        "dataset": str(data_dir.relative_to(ROOT) if data_dir.is_relative_to(ROOT) else data_dir),
        "sample_seed": SAMPLE_SEED,
        "unique_review_docs": int(reviews["document_id"].nunique()),
        "sample_assignments": int(len(sample_map)),
        "verdict_counts": reviews["verdict"].value_counts().to_dict(),
        "acceptance_criteria": {
            "random_scenario_normal_fail_rate_pct": round(rsn_fail_rate, 2),
            "random_scenario_normal_pass": rsn_fail_rate <= 3.0,
            "abnormal_mutation_explained_pct": round(abnormal_explained, 2),
            "abnormal_mutation_pass": abnormal_explained >= 95.0,
            "l3_l4_generator_contamination_pct": round(contamination, 2),
            "l3_l4_generator_contamination_low": contamination <= 5.0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "accounting_llm_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    by_bucket.to_csv(output_dir / "accounting_llm_review_bucket_summary.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# DataSynth semantic-v1 accounting LLM review",
        "",
        f"- Dataset: `{summary['dataset']}`",
        f"- Unique reviewed docs: {summary['unique_review_docs']:,}",
        f"- Sample assignments: {summary['sample_assignments']:,}",
        f"- Sample seed: {SAMPLE_SEED}",
        "",
        "## Verdict Counts",
        "",
    ]
    for verdict, count in summary["verdict_counts"].items():
        lines.append(f"- {verdict}: {count:,}")
    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "",
            f"- random/scenario normal FAIL rate: {rsn_fail_rate:.2f}% "
            f"({'PASS' if rsn_fail_rate <= 3.0 else 'FAIL'})",
            f"- abnormal mutation INTENDED_ABNORMAL explained: {abnormal_explained:.2f}% "
            f"({'PASS' if abnormal_explained >= 95.0 else 'FAIL'})",
            f"- L3/L4 hit generator contamination: {contamination:.2f}% "
            f"({'LOW' if contamination <= 5.0 else 'HIGH'})",
            "",
            "## Notes",
            "",
            "- `PASS` means normal synthetic accounting logic is acceptable for testing.",
            "- `WARN` means plausible enough for synthetic tests but stylistically or document-type-wise imperfect.",
            "- `FAIL` means a normal entry has a semantic accounting contradiction.",
            "- `INTENDED_ABNORMAL` means mutation provenance explains the abnormal state.",
            "",
            "## Output Files",
            "",
            "- `accounting_llm_review_samples.csv`: stratified sample membership",
            "- `accounting_llm_review_reviews.csv`: document-level review judgments",
            "- `accounting_llm_review_bucket_summary.csv`: bucket/verdict cross-tab",
            "- `accounting_llm_review_phase1_hits.csv`: Phase1 L3/L4/top-case sampling support",
        ]
    )
    (output_dir / "accounting_llm_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    phase1.to_csv(output_dir / "accounting_llm_review_phase1_hits.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--phase1-cache", type=Path, default=PHASE1_CACHE)
    args = parser.parse_args()

    coa = _read_coa(args.data_dir)
    journal = _read_journal(args.data_dir)
    docs = _doc_table(journal, coa)
    phase1 = _phase1_cache_hits(args.phase1_cache)
    if phase1 is None:
        phase1 = _phase1_surrogate(docs)
    samples = _sample_docs(docs, phase1)
    sample_docs = docs[docs["document_id"].isin(samples["document_id"])].merge(
        phase1,
        on="document_id",
        how="left",
    )
    review_rows = []
    for row in sample_docs.to_dict("records"):
        review_rows.append({**row, **_review_one(row)})
    reviews = pd.DataFrame(review_rows).sort_values(["verdict", "business_process", "semantic_scenario_id"])

    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples.to_csv(args.out_dir / "accounting_llm_review_samples.csv", index=False, encoding="utf-8-sig")
    reviews.to_csv(args.out_dir / "accounting_llm_review_reviews.csv", index=False, encoding="utf-8-sig")
    _write_report(reviews, samples, phase1, args.out_dir, args.data_dir)

    summary = json.loads((args.out_dir / "accounting_llm_review_summary.json").read_text(encoding="utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
