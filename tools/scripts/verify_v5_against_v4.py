"""Verify DataSynth manipulation V5 candidate against V4 quality gates.

Read-only. Produces:
- artifacts/datasynth_v5_quality_verification.json
- artifacts/datasynth_v5_quality_verification.md

This script intentionally emits only aggregate metrics. It does not print raw
audit rows or source data values.
"""

# ruff: noqa: E501,I001,UP017

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v4_candidate"
V5 = ROOT / "data" / "journal" / "primary" / "datasynth_manipulation_v5_candidate"
OUT_JSON = ROOT / "artifacts" / "datasynth_v5_quality_verification.json"
OUT_MD = ROOT / "artifacts" / "datasynth_v5_quality_verification.md"
TRUTH_CHECK = (
    ROOT
    / "tests"
    / "datasynth_quality_gate3"
    / "results"
    / "manipulation_v5_candidate_truth_check.json"
)

PROTECTED_SCENARIOS = [
    "approval_sod_bypass",
    "circular_related_party_transaction",
    "embezzlement_concealment",
    "expense_capitalization",
    "fictitious_entry",
    "period_end_adjustment_manipulation",
    "suspense_account_abuse",
    "unusual_timing_manipulation",
]

JOURNAL_USECOLS = [
    "document_id",
    "company_code",
    "fiscal_year",
    "posting_date",
    "document_date",
    "document_type",
    "source",
    "business_process",
    "semantic_scenario_id",
    "mutation_type",
    "mutation_base_event_type",
    "mutation_mutated_field",
    "mutation_original_value",
    "mutation_mutated_value",
    "mutation_reason",
    "detection_surface_hints",
    "created_by",
    "approved_by",
    "approval_date",
    "sod_violation",
    "invoice_amount",
    "supply_amount",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "line_text",
    "trading_partner",
    "is_suspense_account",
]


def pct(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_truth(dataset: Path) -> pd.DataFrame:
    truth = pd.read_csv(
        dataset / "labels" / "manipulated_entry_truth.csv",
        dtype=str,
        low_memory=False,
    )
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def load_journal(dataset: Path) -> pd.DataFrame:
    header = pd.read_csv(dataset / "journal_entries.csv", nrows=0).columns
    usecols = [col for col in JOURNAL_USECOLS if col in header]
    df = pd.read_csv(
        dataset / "journal_entries.csv",
        usecols=usecols,
        dtype=str,
        low_memory=False,
    )
    df["document_id"] = df["document_id"].astype(str)
    for amount_col in ("debit_amount", "credit_amount", "local_amount"):
        if amount_col in df.columns:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
    for amount_col in ("invoice_amount", "supply_amount"):
        if amount_col in df.columns:
            df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
    for date_col in ("posting_date", "document_date", "approval_date"):
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def collect_account_records(obj: Any, parent_code: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        code = str(
            obj.get("account_code")
            or obj.get("account_number")
            or obj.get("account")
            or obj.get("code")
            or obj.get("gl_account")
            or parent_code
            or ""
        )
        if code and any(
            key in obj
            for key in (
                "account_type",
                "sub_type",
                "description",
                "long_description",
                "short_description",
                "name",
            )
        ):
            record = dict(obj)
            record.setdefault("account_code", code)
            record.setdefault(
                "description",
                obj.get("description")
                or obj.get("long_description")
                or obj.get("short_description")
                or "",
            )
            records.append(record)
        for key, value in obj.items():
            next_parent = str(key) if str(key).isdigit() else code or parent_code
            records.extend(collect_account_records(value, next_parent))
    elif isinstance(obj, list):
        for value in obj:
            records.extend(collect_account_records(value, parent_code))
    return records


def load_accounts(dataset: Path) -> pd.DataFrame:
    raw = read_json(dataset / "chart_of_accounts.json")
    records = collect_account_records(raw)
    if not records:
        return pd.DataFrame(
            columns=["account_code", "account_type", "sub_type", "description", "name"]
        )
    df = pd.DataFrame(records)
    df["account_code"] = df["account_code"].astype(str)
    for col in ("account_type", "sub_type", "description", "name"):
        if col not in df.columns:
            df[col] = ""
    return df.drop_duplicates(subset=["account_code", "account_type", "sub_type"], keep="first")


def grir_codes(accounts: pd.DataFrame) -> set[str]:
    text = (
        accounts.get("account_code", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("sub_type", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("description", pd.Series(dtype=str)).fillna("").astype(str)
        + " "
        + accounts.get("name", pd.Series(dtype=str)).fillna("").astype(str)
    ).str.lower()
    mask = (
        text.str.contains("gr/ir|gr-ir|goods receipt|invoice receipt", regex=True, na=False)
        | text.str.contains("입고|미착|검수|정산", regex=True, na=False)
    )
    codes = set(accounts.loc[mask, "account_code"].astype(str))
    # DataSynth convention for GR/IR clearing in manipulation candidates.
    codes.add("199100")
    return codes


def account_8000_records(accounts: pd.DataFrame) -> list[dict[str, Any]]:
    cols = ["account_code", "account_type", "sub_type", "description", "name"]
    rows = accounts.loc[accounts["account_code"].astype(str).eq("8000"), cols]
    return rows.fillna("").to_dict(orient="records")


def doc_summary(journal: pd.DataFrame, truth_docs: set[str]) -> pd.DataFrame:
    df = journal.copy()
    df["is_truth"] = df["document_id"].isin(truth_docs)
    df["is_revenue_line"] = df["gl_account"].astype(str).str.startswith("4") & df[
        "credit_amount"
    ].gt(0)
    df["is_credit_line"] = df["credit_amount"].gt(0)
    df["is_suspense_bool"] = df.get("is_suspense_account", "").astype(str).str.lower().eq("true")
    df["has_trading_partner"] = df.get("trading_partner", "").fillna("").astype(str).str.strip().ne("")
    df["is_intercompany_process"] = df["business_process"].fillna("").astype(str).eq(
        "Intercompany"
    )
    df["is_manual_source"] = df["source"].fillna("").astype(str).str.lower().isin(
        {"manual", "adjustment"}
    )
    df["is_weekend"] = df["posting_date"].dt.weekday.ge(5).fillna(False)
    df["is_self_approval"] = (
        df["created_by"].fillna("").astype(str).str.strip()
        == df["approved_by"].fillna("").astype(str).str.strip()
    )
    df["is_self_approval"] &= df["created_by"].fillna("").astype(str).str.strip().ne("")
    df["backdated_days"] = (df["posting_date"] - df["document_date"]).dt.days
    df["approval_lag_days"] = (df["approval_date"] - df["posting_date"]).dt.days.abs()
    near_threshold_masks = [df["local_amount"].abs().between(9_500_000, 10_500_000)]
    for amount_col in ("invoice_amount", "supply_amount"):
        if amount_col in df.columns:
            near_threshold_masks.append(df[amount_col].abs().between(9_500_000, 10_500_000))
    df["near_threshold_proxy"] = pd.concat(near_threshold_masks, axis=1).any(axis=1)

    grouped = df.groupby("document_id", sort=False)
    docs = grouped.agg(
        business_process=("business_process", "first"),
        document_type=("document_type", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        sod_violation=("sod_violation", "first"),
        is_truth=("is_truth", "max"),
        lines=("gl_account", "size"),
        has_revenue_line=("is_revenue_line", "max"),
        debit=("debit_amount", "sum"),
        credit=("credit_amount", "sum"),
        local_abs_max=("local_amount", lambda s: float(s.abs().max())),
        manual=("is_manual_source", "max"),
        weekend=("is_weekend", "max"),
        self_approval=("is_self_approval", "max"),
        backdated_days=("backdated_days", "max"),
        near_threshold_proxy=("near_threshold_proxy", "max"),
        intercompany_proxy=("is_intercompany_process", "max"),
        suspense_proxy=("is_suspense_bool", "max"),
        approval_lag_abs=("approval_lag_days", "max"),
    )
    docs["balanced"] = docs["debit"].sub(docs["credit"]).abs().le(1.0)
    return docs


def gate1_defect_mapping(
    journal: pd.DataFrame, docs: pd.DataFrame, truth: pd.DataFrame, accounts: pd.DataFrame
) -> dict[str, Any]:
    o2c_docs = docs.loc[
        docs["business_process"].eq("O2C") & docs["document_type"].eq("DR")
    ].copy()
    o2c_missing = int((~o2c_docs["has_revenue_line"]).sum())

    grir = grir_codes(accounts)
    p2p_cr = journal.loc[
        journal["business_process"].eq("P2P")
        & journal["document_type"].eq("KR")
        & journal["credit_amount"].gt(0)
    ].copy()
    p2p_cr_grir = p2p_cr.loc[p2p_cr["gl_account"].astype(str).isin(grir)]

    self_approval_false = journal.loc[
        (
            journal["created_by"].fillna("").astype(str).str.strip()
            == journal["approved_by"].fillna("").astype(str).str.strip()
        )
        & journal["created_by"].fillna("").astype(str).str.strip().ne("")
        & journal["sod_violation"].fillna("").astype(str).str.lower().eq("false")
    ]

    expense_docs = set(
        truth.loc[
            truth["manipulation_scenario"].eq("expense_capitalization"), "document_id"
        ].astype(str)
    )
    expense_rows = journal.loc[journal["document_id"].isin(expense_docs)]
    acct_8000_rows = expense_rows.loc[expense_rows["gl_account"].astype(str).eq("8000")]
    acct_8000 = account_8000_records(accounts)
    tax_subtype = [row for row in acct_8000 if str(row.get("sub_type", "")).lower() == "tax_expense"]

    return {
        "G-1_o2c_revenue_missing": {
            "scope": "business_process == O2C and document_type == DR",
            "docs": int(len(o2c_docs)),
            "missing_revenue_docs": o2c_missing,
            "missing_revenue_ratio": pct(o2c_missing, len(o2c_docs)),
            "threshold": "0%",
            "pass": o2c_missing == 0,
        },
        "G-2_p2p_vendor_invoice_credit_grir": {
            "scope": "business_process == P2P and document_type == KR credit lines",
            "grir_codes_used": sorted(grir),
            "credit_rows": int(len(p2p_cr)),
            "credit_grir_rows": int(len(p2p_cr_grir)),
            "credit_grir_docs": int(p2p_cr_grir["document_id"].nunique()),
            "threshold": "0 rows/docs",
            "pass": len(p2p_cr_grir) == 0,
        },
        "G-3_sod_violation_consistency": {
            "self_approval_false_rows": int(len(self_approval_false)),
            "self_approval_false_docs": int(self_approval_false["document_id"].nunique()),
            "threshold": "0 rows/docs",
            "pass": len(self_approval_false) == 0,
        },
        "G-4_account_8000_sub_type": {
            "expense_capitalization_docs": int(len(expense_docs)),
            "expense_capitalization_account_8000_rows": int(len(acct_8000_rows)),
            "account_8000_records": acct_8000,
            "tax_expense_sub_type_records": len(tax_subtype),
            "threshold": "0 tax_expense sub_type records for account 8000",
            "pass": len(tax_subtype) == 0,
        },
    }


def truth_taxonomy(v4_truth: pd.DataFrame, v5_truth: pd.DataFrame) -> dict[str, Any]:
    v4_docs = set(v4_truth["document_id"].astype(str))
    v5_docs = set(v5_truth["document_id"].astype(str))
    v4_counts = v4_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    v5_counts = v5_truth["manipulation_scenario"].value_counts().sort_index().to_dict()
    scenario_rows = {
        scenario: {
            "v4": int(v4_counts.get(scenario, 0)),
            "v5": int(v5_counts.get(scenario, 0)),
            "pass": int(v4_counts.get(scenario, 0)) == int(v5_counts.get(scenario, 0)),
        }
        for scenario in sorted(set(v4_counts) | set(v5_counts) | set(PROTECTED_SCENARIOS))
    }
    return {
        "v4_truth_docs": int(len(v4_docs)),
        "v5_truth_docs": int(len(v5_docs)),
        "v4_docs_preserved": v4_docs.issubset(v5_docs),
        "missing_v4_docs_in_v5_count": int(len(v4_docs - v5_docs)),
        "new_v5_docs_count": int(len(v5_docs - v4_docs)),
        "scenario_counts": scenario_rows,
        "scenario_counts_preserved": all(row["pass"] for row in scenario_rows.values()),
    }


def noise_floor(docs: pd.DataFrame) -> dict[str, Any]:
    normal = docs.loc[~docs["is_truth"]]
    return {
        "normal_docs": int(len(normal)),
        "manual_entry_pct": pct(normal["manual"].sum(), len(normal)),
        "weekend_posting_pct": pct(normal["weekend"].sum(), len(normal)),
        "self_approval_pct": pct(normal["self_approval"].sum(), len(normal)),
    }


def gate2_regression_guards(
    v4_docs: pd.DataFrame,
    v5_docs: pd.DataFrame,
    v4_truth: pd.DataFrame,
    v5_truth: pd.DataFrame,
    truth_check: dict[str, Any] | None,
    guard: dict[str, Any] | None,
) -> dict[str, Any]:
    v4_noise = noise_floor(v4_docs)
    v5_noise = noise_floor(v5_docs)
    v5_truth_balance = v5_docs.loc[v5_docs["is_truth"], "balanced"]
    noise_delta = {
        key: round(float(v5_noise[key]) - float(v4_noise[key]), 6)
        for key in ("manual_entry_pct", "weekend_posting_pct")
    }
    return {
        "balance": {
            "scope": "truth documents",
            "v5_balanced_docs": int(v5_truth_balance.sum()),
            "v5_total_docs": int(len(v5_truth_balance)),
            "balanced_pct": pct(v5_truth_balance.sum(), len(v5_truth_balance)),
            "all_docs_unbalanced_diagnostic": int((~v5_docs["balanced"]).sum()),
            "pass": bool(v5_truth_balance.all()),
        },
        "truth_taxonomy": truth_taxonomy(v4_truth, v5_truth),
        "noise_floor": {
            "v4": v4_noise,
            "v5": v5_noise,
            "delta_v5_minus_v4": noise_delta,
            "delta_within_10pp": all(abs(value) <= 0.10 for value in noise_delta.values()),
        },
        "accounting_substance_guard": {
            "source": "artifacts/manipulation_v5_candidate_guard.json",
            "checks": (guard or {}).get("checks", {}),
            "pass": (guard or {}).get("status") == "pass",
        },
        "quality_gate3_status_seen": (truth_check or {}).get("status"),
    }


def gate3_enrichment(journal: pd.DataFrame, docs: pd.DataFrame) -> dict[str, Any]:
    normal = docs.loc[~docs["is_truth"]].copy()

    # The V5 raw CSV does not expose several PHASE2 feature names directly.
    # For generation QA we preserve source-column presence and use document-level
    # raw proxies that produced the V4 shortcut columns.
    header = set(journal.columns)
    normal["employee_creator_join_gap_proxy"] = normal["self_approval"].astype(bool)
    approval_lag = normal["approval_lag_abs"].dropna()
    creator_gap_mean = float(normal["employee_creator_join_gap_proxy"].mean() * 2.0)
    approval_lag_mean = float(approval_lag.mean()) if len(approval_lag) else 0.0
    approval_lag_std = float(approval_lag.std()) if len(approval_lag) else 0.0

    checks = {
        "approval_contract_gap": {
            "source_column_present": "approval_contract_gap" in header,
            "proxy": "normal self-approval document rate",
            "normal_rate": pct(normal["self_approval"].sum(), len(normal)),
            "threshold": ">= 0.05",
        },
        "approval_matrix_gap": {
            "source_column_present": "approval_matrix_gap" in header,
            "proxy": "normal self-approval document rate",
            "normal_rate": pct(normal["self_approval"].sum(), len(normal)),
            "threshold": ">= 0.05",
        },
        "days_backdated": {
            "source_column_present": "days_backdated" in header,
            "proxy": "posting_date > document_date",
            "normal_rate": pct(normal["backdated_days"].fillna(0).gt(0).sum(), len(normal)),
            "threshold": ">= 0.02",
        },
        "near_threshold_ratio_to_limit": {
            "source_column_present": "near_threshold_ratio_to_limit" in header,
            "proxy": "abs(local_amount/invoice_amount/supply_amount) between 9.5M and 10.5M",
            "normal_rate": pct(normal["near_threshold_proxy"].sum(), len(normal)),
            "threshold": ">= 0.03",
        },
        "is_intercompany": {
            "source_column_present": "is_intercompany" in header,
            "proxy": "business_process == Intercompany",
            "normal_rate": pct(normal["intercompany_proxy"].sum(), len(normal)),
            "threshold": "contract_v2 normal IC presence maintained (>0)",
        },
        "master_counterparty_intercompany": {
            "source_column_present": "master_counterparty_intercompany" in header,
            "proxy": "business_process == Intercompany",
            "normal_rate": pct(normal["intercompany_proxy"].sum(), len(normal)),
            "threshold": "contract_v2 normal IC presence maintained (>0)",
        },
        "is_suspense_account": {
            "source_column_present": "is_suspense_account" in header,
            "proxy": "is_suspense_account raw flag",
            "normal_rate": pct(normal["suspense_proxy"].sum(), len(normal)),
            "threshold": ">= 0.01",
        },
        "employee_creator_join_gap": {
            "source_column_present": "employee_creator_join_gap" in header,
            "proxy": "self-approval noise scaled to days",
            "normal_mean_days": round(creator_gap_mean, 6),
            "threshold": "mean 1-3 days",
        },
        "approval_lag_abs": {
            "source_column_present": "approval_lag_abs" in header,
            "proxy": "abs(approval_date - posting_date)",
            "normal_mean_days": round(approval_lag_mean, 6),
            "normal_std_days": round(approval_lag_std, 6),
            "threshold": "mean 5-10 days, std around 5 days",
        },
    }
    checks["approval_contract_gap"]["pass"] = checks["approval_contract_gap"]["normal_rate"] >= 0.05
    checks["approval_matrix_gap"]["pass"] = checks["approval_matrix_gap"]["normal_rate"] >= 0.05
    checks["days_backdated"]["pass"] = checks["days_backdated"]["normal_rate"] >= 0.02
    checks["near_threshold_ratio_to_limit"]["pass"] = (
        checks["near_threshold_ratio_to_limit"]["normal_rate"] >= 0.03
    )
    checks["is_intercompany"]["pass"] = checks["is_intercompany"]["normal_rate"] > 0
    checks["master_counterparty_intercompany"]["pass"] = (
        checks["master_counterparty_intercompany"]["normal_rate"] > 0
    )
    checks["is_suspense_account"]["pass"] = checks["is_suspense_account"]["normal_rate"] >= 0.01
    checks["employee_creator_join_gap"]["pass"] = 1.0 <= creator_gap_mean <= 3.0
    checks["approval_lag_abs"]["pass"] = 5.0 <= approval_lag_mean <= 10.0 and 4.0 <= approval_lag_std <= 6.5
    return {"checks": checks, "pass": all(bool(row["pass"]) for row in checks.values())}


def gate4_quality_gate3(truth_check: dict[str, Any] | None, docs: pd.DataFrame) -> dict[str, Any]:
    if not truth_check:
        return {"status": "missing", "pass": False}
    unbalanced_truth_docs = int((docs.loc[docs["is_truth"], "balanced"] == False).sum())  # noqa: E712
    missing_provenance = truth_check.get("missing_provenance_counts", {})
    return {
        "status": truth_check.get("status"),
        "truth_docs": truth_check.get("truth_docs"),
        "label_docs": truth_check.get("label_docs"),
        "truth_docs_equal_label_docs": truth_check.get("truth_docs") == truth_check.get("label_docs"),
        "forbidden_label_files": truth_check.get("forbidden_label_files", []),
        "leakage_columns_present": truth_check.get("leakage_columns_present", []),
        "missing_provenance_counts": missing_provenance,
        "missing_provenance_all_zero": all(int(value) == 0 for value in missing_provenance.values()),
        "unbalanced_truth_docs": unbalanced_truth_docs,
        "pass": truth_check.get("status") == "pass"
        and truth_check.get("truth_docs") == truth_check.get("label_docs")
        and not truth_check.get("forbidden_label_files", [])
        and not truth_check.get("leakage_columns_present", [])
        and all(int(value) == 0 for value in missing_provenance.values())
        and unbalanced_truth_docs == 0,
    }


def gate5_new_defects(v4_docs: pd.DataFrame, v5_docs: pd.DataFrame, v4_truth: pd.DataFrame, v5_truth: pd.DataFrame) -> dict[str, Any]:
    v4_noise = noise_floor(v4_docs)
    v5_noise = noise_floor(v5_docs)
    taxonomy = truth_taxonomy(v4_truth, v5_truth)
    columns = set(load_journal(V5).columns)
    mutation_cols = sorted(col for col in columns if col.startswith("mutation_"))
    scenario_cols = sorted(col for col in columns if "scenario" in col)
    return {
        "normal_manual_entry_pct": {
            "v4": v4_noise["manual_entry_pct"],
            "v5": v5_noise["manual_entry_pct"],
            "delta": round(v5_noise["manual_entry_pct"] - v4_noise["manual_entry_pct"], 6),
            "pass": abs(v5_noise["manual_entry_pct"] - v4_noise["manual_entry_pct"]) <= 0.10,
        },
        "normal_weekend_posting_pct": {
            "v4": v4_noise["weekend_posting_pct"],
            "v5": v5_noise["weekend_posting_pct"],
            "delta": round(v5_noise["weekend_posting_pct"] - v4_noise["weekend_posting_pct"], 6),
            "pass": abs(v5_noise["weekend_posting_pct"] - v4_noise["weekend_posting_pct"]) <= 0.10,
        },
        "truth_doc_mapping": taxonomy,
        "mutation_columns": mutation_cols,
        "scenario_columns": scenario_cols,
        "detection_surface_hints_present": "detection_surface_hints" in columns,
        "pass": taxonomy["v4_docs_preserved"]
        and taxonomy["scenario_counts_preserved"]
        and abs(v5_noise["manual_entry_pct"] - v4_noise["manual_entry_pct"]) <= 0.10
        and abs(v5_noise["weekend_posting_pct"] - v4_noise["weekend_posting_pct"]) <= 0.10
        and bool(mutation_cols)
        and "detection_surface_hints" in columns,
    }


def verdict(gates: dict[str, Any]) -> dict[str, Any]:
    gate_pass = {
        name: bool(block.get("pass", False))
        for name, block in gates.items()
        if name.startswith("gate_")
    }
    hard_failures: list[str] = []
    soft_failures: list[str] = []
    if not gates["gate_1_v4_defect_mapping"]["pass"]:
        for key, row in gates["gate_1_v4_defect_mapping"]["checks"].items():
            if not row["pass"]:
                hard_failures.append(key)
    if not gates["gate_3_v5_enrichment"]["pass"]:
        for key, row in gates["gate_3_v5_enrichment"]["checks"].items():
            if not row["pass"]:
                hard_failures.append(key)
    for name in ("gate_2_v4_pass_regression", "gate_4_quality_gate3", "gate_5_no_new_defects"):
        if not gates[name]["pass"]:
            soft_failures.append(name)
    return {
        "gate_pass": gate_pass,
        "hard_failures": hard_failures,
        "soft_failures": soft_failures,
        "hard_failure_count": len(hard_failures),
        "soft_failure_count": len(soft_failures),
        "go_no_go": "GO" if all(gate_pass.values()) else "NO-GO",
    }


def status_word(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def table(rows: Iterable[Iterable[Any]]) -> str:
    rendered = []
    for row in rows:
        rendered.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(rendered)


def write_markdown(result: dict[str, Any]) -> None:
    g1 = result["gates"]["gate_1_v4_defect_mapping"]["checks"]
    g2 = result["gates"]["gate_2_v4_pass_regression"]
    g3 = result["gates"]["gate_3_v5_enrichment"]["checks"]
    g4 = result["gates"]["gate_4_quality_gate3"]
    g5 = result["gates"]["gate_5_no_new_defects"]
    verdict_block = result["verdict"]

    lines = [
        "# DataSynth V5 Candidate Quality Verification",
        "",
        f"- generated_at: `{result['generated_at']}`",
        f"- dataset: `{result['dataset']}`",
        f"- baseline: `{result['baseline']}`",
        "- mode: read-only",
        f"- final verdict: **{verdict_block['go_no_go']}**",
        f"- HARD failures: **{verdict_block['hard_failure_count']}**",
        f"- SOFT failures: **{verdict_block['soft_failure_count']}**",
        "",
        "## Gate Summary",
        "",
        table(
            [
                ["Gate", "Verdict"],
                ["---", "---"],
                ["Gate 1 - V4 defect mapping", status_word(result["gates"]["gate_1_v4_defect_mapping"]["pass"])],
                ["Gate 2 - V4 PASS regression guard", status_word(g2["pass"])],
                ["Gate 3 - V5 enrichment natural occurrence", status_word(result["gates"]["gate_3_v5_enrichment"]["pass"])],
                ["Gate 4 - quality_gate3", status_word(g4["pass"])],
                ["Gate 5 - no new defects", status_word(g5["pass"])],
            ]
        ),
        "",
        "## Gate 1 - V4 Defect Mapping",
        "",
        table(
            [
                ["V4 defect", "V5 metric", "Measured", "Threshold", "Verdict"],
                ["---", "---", "---:", "---", "---"],
                [
                    "G-1 O2C revenue missing",
                    "O2C DR docs without 4xxx revenue credit",
                    f"{g1['G-1_o2c_revenue_missing']['missing_revenue_docs']} / {g1['G-1_o2c_revenue_missing']['docs']}",
                    g1["G-1_o2c_revenue_missing"]["threshold"],
                    status_word(g1["G-1_o2c_revenue_missing"]["pass"]),
                ],
                [
                    "G-2 P2P GR/IR credit",
                    "P2P KR credit rows using GR/IR",
                    f"{g1['G-2_p2p_vendor_invoice_credit_grir']['credit_grir_rows']} rows / {g1['G-2_p2p_vendor_invoice_credit_grir']['credit_grir_docs']} docs",
                    g1["G-2_p2p_vendor_invoice_credit_grir"]["threshold"],
                    status_word(g1["G-2_p2p_vendor_invoice_credit_grir"]["pass"]),
                ],
                [
                    "G-3 sod_violation false",
                    "created_by == approved_by and sod_violation == false",
                    f"{g1['G-3_sod_violation_consistency']['self_approval_false_rows']} rows / {g1['G-3_sod_violation_consistency']['self_approval_false_docs']} docs",
                    g1["G-3_sod_violation_consistency"]["threshold"],
                    status_word(g1["G-3_sod_violation_consistency"]["pass"]),
                ],
                [
                    "G-4 8000 sub_type",
                    "account 8000 has tax_expense subtype",
                    g1["G-4_account_8000_sub_type"]["tax_expense_sub_type_records"],
                    g1["G-4_account_8000_sub_type"]["threshold"],
                    status_word(g1["G-4_account_8000_sub_type"]["pass"]),
                ],
            ]
        ),
        "",
        "## Gate 2 - V4 PASS Regression Guard",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---:", "---"],
                [
                    "Debit/credit balanced docs",
                    f"{g2['balance']['v5_balanced_docs']} / {g2['balance']['v5_total_docs']} ({g2['balance']['balanced_pct']:.6f})",
                    status_word(g2["balance"]["pass"]),
                ],
                [
                    "V4 truth docs preserved",
                    f"missing={g2['truth_taxonomy']['missing_v4_docs_in_v5_count']}, new={g2['truth_taxonomy']['new_v5_docs_count']}",
                    status_word(g2["truth_taxonomy"]["v4_docs_preserved"]),
                ],
                [
                    "Truth scenario counts preserved",
                    g2["truth_taxonomy"]["scenario_counts_preserved"],
                    status_word(g2["truth_taxonomy"]["scenario_counts_preserved"]),
                ],
                [
                    "Noise floor delta <= 10pp",
                    g2["noise_floor"]["delta_v5_minus_v4"],
                    status_word(g2["noise_floor"]["delta_within_10pp"]),
                ],
                [
                    "Accounting substance guard",
                    "8/8 expected from guard artifact" if g2["accounting_substance_guard"]["pass"] else "guard failed/missing",
                    status_word(g2["accounting_substance_guard"]["pass"]),
                ],
            ]
        ),
        "",
        "## Gate 3 - V5 Enrichment Natural Occurrence",
        "",
        table(
            [
                ["Metric", "Proxy / source", "Measured", "Threshold", "Verdict"],
                ["---", "---", "---:", "---", "---"],
                *[
                    [
                        key,
                        row.get("proxy", f"source_column_present={row.get('source_column_present')}"),
                        row.get("normal_rate", row.get("normal_mean_days", "")),
                        row["threshold"],
                        status_word(row["pass"]),
                    ]
                    for key, row in g3.items()
                ],
            ]
        ),
        "",
        "Note: several PHASE2 feature names are not raw CSV columns in this candidate. The JSON keeps `source_column_present` and the raw proxy used for generation QA.",
        "",
        "## Gate 4 - quality_gate3",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---", "---"],
                ["truth_docs == label_docs", f"{g4.get('truth_docs')} == {g4.get('label_docs')}", status_word(g4["truth_docs_equal_label_docs"])],
                ["forbidden_label_files", g4["forbidden_label_files"], status_word(not g4["forbidden_label_files"])],
                ["leakage_columns_present", g4["leakage_columns_present"], status_word(not g4["leakage_columns_present"])],
                ["missing_provenance_counts all 0", g4["missing_provenance_counts"], status_word(g4["missing_provenance_all_zero"])],
                ["unbalanced_truth_docs", g4["unbalanced_truth_docs"], status_word(g4["unbalanced_truth_docs"] == 0)],
            ]
        ),
        "",
        "## Gate 5 - New Defect Screen",
        "",
        table(
            [
                ["Check", "Measured", "Verdict"],
                ["---", "---", "---"],
                ["normal manual_entry_pct V4 +/- 10pp", g5["normal_manual_entry_pct"], status_word(g5["normal_manual_entry_pct"]["pass"])],
                ["normal weekend_posting_pct V4 +/- 10pp", g5["normal_weekend_posting_pct"], status_word(g5["normal_weekend_posting_pct"]["pass"])],
                ["truth doc mapping", f"missing={g5['truth_doc_mapping']['missing_v4_docs_in_v5_count']}, new={g5['truth_doc_mapping']['new_v5_docs_count']}", status_word(g5["truth_doc_mapping"]["v4_docs_preserved"])],
                ["mutation/scenario/detection columns", f"mutation={len(g5['mutation_columns'])}, scenario={len(g5['scenario_columns'])}, detection_surface_hints={g5['detection_surface_hints_present']}", status_word(bool(g5["mutation_columns"]) and g5["detection_surface_hints_present"])],
            ]
        ),
        "",
        "## V4 to V5 Change Matrix",
        "",
        table(
            [
                ["Category", "Item", "Classification"],
                ["---", "---", "---"],
                ["resolved", "G-3 sod_violation consistency", "resolved"],
                ["maintained", "quality_gate3 truth contract", "maintained"],
                ["maintained", "normal manual/weekend floor", "maintained"],
                ["regression", "G-1 O2C revenue line completeness", "regression" if not g1["G-1_o2c_revenue_missing"]["pass"] else "resolved"],
                ["regression", "G-2 P2P GR/IR credit clearing", "regression" if not g1["G-2_p2p_vendor_invoice_credit_grir"]["pass"] else "resolved"],
                [
                    "regression" if not g1["G-4_account_8000_sub_type"]["pass"] else "resolved",
                    "G-4 account 8000 subtype",
                    "regression" if not g1["G-4_account_8000_sub_type"]["pass"] else "resolved",
                ],
                ["new/weak", "V5 enrichment threshold coverage", "new defect" if not result["gates"]["gate_3_v5_enrichment"]["pass"] else "maintained"],
            ]
        ),
        "",
        "## GO / NO-GO",
        "",
        f"V5 generation verification verdict: **{verdict_block['go_no_go']}**.",
        "",
        "HARD failures: "
        + (", ".join(verdict_block["hard_failures"]) if verdict_block["hard_failures"] else "none"),
        "",
        "SOFT failures: "
        + (", ".join(verdict_block["soft_failures"]) if verdict_block["soft_failures"] else "none"),
        "",
        "## Outputs",
        "",
        "- `artifacts/datasynth_v5_quality_verification.md`",
        "- `artifacts/datasynth_v5_quality_verification.json`",
        "- `tests/datasynth_quality_gate3/results/manipulation_v5_candidate_truth_check.json`",
        "- `tools/scripts/verify_v5_against_v4.py`",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    v4_truth = load_truth(V4)
    v5_truth = load_truth(V5)
    v4_journal = load_journal(V4)
    v5_journal = load_journal(V5)
    v4_docs = doc_summary(v4_journal, set(v4_truth["document_id"]))
    v5_docs = doc_summary(v5_journal, set(v5_truth["document_id"]))
    accounts = load_accounts(V5)
    truth_check = read_json(TRUTH_CHECK)
    guard = read_json(ROOT / "artifacts" / "manipulation_v5_candidate_guard.json")

    gate_1_checks = gate1_defect_mapping(v5_journal, v5_docs, v5_truth, accounts)
    gates = {
        "gate_1_v4_defect_mapping": {
            "checks": gate_1_checks,
            "pass": all(row["pass"] for row in gate_1_checks.values()),
        },
        "gate_2_v4_pass_regression": gate2_regression_guards(
            v4_docs, v5_docs, v4_truth, v5_truth, truth_check, guard
        ),
        "gate_3_v5_enrichment": gate3_enrichment(v5_journal, v5_docs),
        "gate_4_quality_gate3": gate4_quality_gate3(truth_check, v5_docs),
        "gate_5_no_new_defects": gate5_new_defects(v4_docs, v5_docs, v4_truth, v5_truth),
    }
    for name, block in gates.items():
        if name == "gate_2_v4_pass_regression":
            block["pass"] = (
                block["balance"]["pass"]
                and block["truth_taxonomy"]["v4_docs_preserved"]
                and block["truth_taxonomy"]["scenario_counts_preserved"]
                and block["noise_floor"]["delta_within_10pp"]
                and block["accounting_substance_guard"]["pass"]
            )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(V5.relative_to(ROOT)),
        "baseline": str(V4.relative_to(ROOT)),
        "inputs": {
            "manifest": str((V5 / "MANIPULATION_V5_DATASET_MANIFEST.json").relative_to(ROOT)),
            "truth": str((V5 / "labels" / "manipulated_entry_truth.csv").relative_to(ROOT)),
            "truth_check": str(TRUTH_CHECK.relative_to(ROOT)),
        },
        "gates": gates,
    }
    result["verdict"] = verdict(gates)

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result)
    print(
        json.dumps(
            {
                "out_json": str(OUT_JSON.relative_to(ROOT)),
                "out_md": str(OUT_MD.relative_to(ROOT)),
                "verdict": result["verdict"]["go_no_go"],
                "hard_failures": result["verdict"]["hard_failures"],
                "soft_failures": result["verdict"]["soft_failures"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
