"""Materialize semantic DataSynth manipulation-v2 split.

The input is the semantic-clean contract-v2 journal. The output is a separate
``datasynth_manipulation_v2`` dataset with the same journal schema and master
data, but with manipulation-only truth labels:

- ``labels/manipulated_entry_truth*``
- ``labels/anomaly_labels*``
- ``labels/manipulated_entry_scenario_summary*``

Contract rule truth and contract sidecars are intentionally not copied.
"""

# ruff: noqa: E501,I001

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


YEARS = (2022, 2023, 2024)
DEFAULT_SOURCE = Path("data/journal/primary/datasynth_contract_v2")
DEFAULT_TARGET = Path("data/journal/primary/datasynth_manipulation_v2")

SCENARIO_TARGETS = {
    2022: {
        "approval_sod_bypass": 8,
        "circular_related_party_transaction": 9,
        "embezzlement_concealment": 21,
        "fictitious_entry": 46,
        "period_end_adjustment_manipulation": 25,
        "unusual_timing_manipulation": 6,
    },
    2023: {
        "approval_sod_bypass": 10,
        "circular_related_party_transaction": 12,
        "embezzlement_concealment": 26,
        "fictitious_entry": 58,
        "period_end_adjustment_manipulation": 32,
        "unusual_timing_manipulation": 7,
    },
    2024: {
        "approval_sod_bypass": 11,
        "circular_related_party_transaction": 13,
        "embezzlement_concealment": 29,
        "fictitious_entry": 64,
        "period_end_adjustment_manipulation": 35,
        "unusual_timing_manipulation": 8,
    },
}

SCENARIO_INTENTS = {
    "approval_sod_bypass": "override or bypass normal approval route while preserving accounting form",
    "circular_related_party_transaction": "move value through related-party or intercompany-looking flows",
    "embezzlement_concealment": "conceal employee or cash leakage in plausible operating expense/payment entries",
    "fictitious_entry": "record non-existent revenue, asset, or expense activity",
    "period_end_adjustment_manipulation": "bias period-end estimates or accruals",
    "unusual_timing_manipulation": "post legitimate-looking entries at unusual timing to avoid normal review",
}

SCENARIO_SUBTYPES = {
    "approval_sod_bypass": ["self_approval_sod", "approval_limit_override", "emergency_route_bypass"],
    "circular_related_party_transaction": ["round_trip_intercompany", "related_party_pass_through"],
    "embezzlement_concealment": [
        "corporate_card_private_use",
        "employee_advance_concealment",
        "false_welfare_or_travel_claim",
    ],
    "fictitious_entry": ["fictitious_revenue", "fictitious_asset", "fictitious_expense"],
    "period_end_adjustment_manipulation": ["manual_accrual_bias", "reserve_estimate_bias"],
    "unusual_timing_manipulation": ["after_hours_posting", "weekend_posting"],
}
CONTRACT_APPROVAL_FIXTURE_APPROVERS = {
    "LIMIT_REVIEWER",
    "NEAR_LIMIT_REVIEWER",
}
IC_GL_ACCOUNTS = ("1150", "2050", "4500", "2700")
FICTITIOUS_REVENUE_DEBIT_ACCOUNTS = ("1100", "1160")
FICTITIOUS_REVENUE_CREDIT_ACCOUNTS = ("4000", "4010", "4900")
EMBEZZLEMENT_DEBIT_ACCOUNTS = ("1200", "1250")
EMBEZZLEMENT_CREDIT_ACCOUNTS = ("1000",)
NEAR_LIMIT_APPROVER = "NEAR_LIMIT_REVIEWER"
NEAR_LIMIT_AMOUNT = 9_500_000_000
NEAR_LIMIT_APPROVAL_LIMIT = 10_000_000_000

ANOMALY_COLUMNS = [
    "anomaly_id",
    "anomaly_category",
    "anomaly_type",
    "document_id",
    "document_type",
    "company_code",
    "anomaly_date",
    "detection_timestamp",
    "confidence",
    "severity",
    "description",
    "is_injected",
    "monetary_impact",
    "related_entities",
    "cluster_id",
    "original_document_hash",
    "injection_strategy",
    "structured_strategy_type",
    "structured_strategy_json",
    "causal_reason_type",
    "causal_reason_json",
    "parent_anomaly_id",
    "child_anomaly_ids",
    "scenario_id",
    "run_id",
    "generation_seed",
    "metadata_json",
]


def stable_bucket(value: object, modulo: int = 100) -> int:
    return sum(ord(ch) for ch in str(value)) % modulo


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def amount_text(value: float | int) -> str:
    return str(int(round(float(value))))


def prepare_target(source: Path, target: Path, force: bool) -> None:
    source = source.resolve()
    target = target.resolve()
    workspace = Path.cwd().resolve()
    if not str(target).startswith(str(workspace)):
        raise ValueError(f"Refusing to write outside workspace: {target}")
    if target.exists():
        if not force:
            raise FileExistsError(f"{target} already exists; pass --force to replace it")
        if target.name != "datasynth_manipulation_v2":
            raise ValueError(f"Refusing to remove unexpected target: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for child in source.iterdir():
        if child.name == "labels":
            continue
        if child.name.startswith("_archive"):
            continue
        if child.name.startswith("journal_entries"):
            continue
        if child.name.startswith("CONTRACT"):
            continue
        dest = target / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        elif child.is_file():
            shutil.copy2(child, dest)


def ensure_manipulation_employee_limits(target: Path) -> None:
    path = target / "master_data" / "employees.json"
    if not path.exists():
        return
    records = json.loads(path.read_text(encoding="utf-8"))
    for row in records:
        if str(row.get("user_id") or "").strip().upper() == NEAR_LIMIT_APPROVER:
            row["approval_limit"] = str(NEAR_LIMIT_APPROVAL_LIMIT)
            row["can_approve_je"] = True
            break
    write_json(path, records)


def load_journal(source: Path) -> pd.DataFrame:
    return pd.read_csv(source / "journal_entries.csv", dtype=str, low_memory=False)


def doc_frame(rows: pd.DataFrame) -> pd.DataFrame:
    amount = pd.to_numeric(rows["local_amount"], errors="coerce").abs().fillna(0.0)
    work = rows.assign(_abs_amount=amount)
    docs = (
        work.sort_values(["document_id", "line_number"])
        .groupby("document_id", as_index=False)
        .agg(
            fiscal_year=("fiscal_year", "first"),
            company_code=("company_code", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            posting_date=("posting_date", "first"),
            document_date=("document_date", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            created_by=("created_by", "first"),
            approved_by=("approved_by", "first"),
            approval_date=("approval_date", "first"),
            user_persona=("user_persona", "first"),
            semantic_scenario_id=("semantic_scenario_id", "first"),
            counterparty_type=("counterparty_type", "first"),
            line_amount=("_abs_amount", "max"),
            line_count=("document_id", "size"),
        )
    )
    docs["fiscal_year"] = pd.to_numeric(docs["fiscal_year"], errors="coerce").astype("Int64")
    return docs


def select_docs(docs: pd.DataFrame) -> dict[str, str]:
    selected: dict[str, str] = {}
    used: set[str] = set()
    scenario_filters = {
        "approval_sod_bypass": lambda d: d["source"].str.lower().isin({"manual", "adjustment"})
        & d["approved_by"].fillna("").astype(str).str.strip().ne(""),
        "circular_related_party_transaction": lambda d: d["business_process"].isin(["Intercompany", "R2R", "O2C"]),
        "embezzlement_concealment": lambda d: d["business_process"].isin(["P2P", "R2R"])
        & d["line_amount"].ge(100_000),
        "fictitious_entry": lambda d: d["business_process"].isin(["O2C", "A2R", "R2R"])
        & d["line_amount"].ge(100_000),
        "period_end_adjustment_manipulation": lambda d: d["business_process"].isin(["R2R", "A2R"]),
        "unusual_timing_manipulation": lambda d: d["source"].str.lower().isin({"manual", "adjustment", "automated", "recurring"}),
    }
    for year in YEARS:
        year_docs = docs.loc[docs["fiscal_year"].eq(year)].copy()
        year_docs["_bucket"] = year_docs["document_id"].map(stable_bucket)
        for scenario, target in SCENARIO_TARGETS[year].items():
            mask = scenario_filters[scenario](year_docs)
            candidates = year_docs.loc[mask & ~year_docs["document_id"].astype(str).isin(used)].copy()
            candidates = candidates.sort_values(["_bucket", "line_amount", "document_id"], ascending=[True, False, True])
            if len(candidates) < target:
                fallback = year_docs.loc[~year_docs["document_id"].astype(str).isin(used)].copy()
                fallback = fallback.sort_values(["_bucket", "line_amount", "document_id"], ascending=[True, False, True])
                candidates = pd.concat([candidates, fallback], ignore_index=True).drop_duplicates("document_id")
            chosen = candidates.head(target)
            if len(chosen) < target:
                raise RuntimeError(f"Not enough candidates for {year} {scenario}: {len(chosen)} < {target}")
            for doc_id in chosen["document_id"].astype(str):
                selected[doc_id] = scenario
                used.add(doc_id)
    return selected


def scenario_datetime(year: int, scenario: str, bucket: int) -> pd.Timestamp:
    if scenario == "period_end_adjustment_manipulation":
        month = [3, 6, 9, 12][bucket % 4]
        day = 31 if month == 12 else 30
        hour = [18, 19, 20, 21, 22][bucket % 5]
        return pd.Timestamp(year=year, month=month, day=day, hour=hour, minute=(bucket * 7) % 60)
    if scenario == "unusual_timing_manipulation":
        month = [3, 6, 9, 12][bucket % 4]
        day = 23 + (bucket % 5)
        dt = pd.Timestamp(year=year, month=month, day=min(day, 28), hour=[0, 1, 5, 21, 23][bucket % 5], minute=15)
        while dt.dayofweek < 5 and bucket % 2 == 0:
            dt += pd.Timedelta(days=1)
        return dt
    if scenario == "approval_sod_bypass":
        month = [3, 6, 9, 12][bucket % 4]
        return pd.Timestamp(year=year, month=month, day=28, hour=18, minute=(bucket * 5) % 60)
    if scenario == "circular_related_party_transaction":
        month = [2, 5, 8, 11][bucket % 4]
        return pd.Timestamp(year=year, month=month, day=10 + bucket % 8, hour=14, minute=(bucket * 3) % 60)
    if scenario == "embezzlement_concealment":
        month = [1, 2, 3, 6, 9, 12][bucket % 6]
        return pd.Timestamp(year=year, month=month, day=20 + bucket % 7, hour=[9, 10, 15, 17, 21][bucket % 5], minute=5)
    month = [1, 3, 5, 6, 9, 10, 12][bucket % 7]
    return pd.Timestamp(year=year, month=month, day=min(28 + bucket % 4, 31), hour=[9, 14, 16, 18, 21][bucket % 5], minute=3)


def neutralize_nontruth_contract_approval_fixtures(rows: pd.DataFrame, selected: dict[str, str]) -> dict[str, Any]:
    """Remove contract-only approval fixtures from manipulation background rows."""
    doc_ids = rows["document_id"].astype(str)
    selected_docs = set(selected)
    nontruth = ~doc_ids.isin(selected_docs)
    created = rows["created_by"].fillna("").astype(str).str.strip().str.upper()
    approved = rows["approved_by"].fillna("").astype(str).str.strip().str.upper()
    missing = approved.eq("") | approved.isin({"NAN", "NONE", "NULL"})
    self_approved = created.ne("") & created.eq(approved)
    contract_limit_fixture = approved.isin(CONTRACT_APPROVAL_FIXTURE_APPROVERS)
    repair_row_mask = nontruth & (missing | self_approved | contract_limit_fixture)
    repair_docs = set(rows.loc[repair_row_mask, "document_id"].astype(str))
    if not repair_docs:
        return {"neutralized_documents": 0, "neutralized_rows": 0}

    repair_doc_mask = doc_ids.isin(repair_docs)
    company = rows.loc[repair_doc_mask, "company_code"].fillna("").astype(str).str.strip().str.upper()
    rows.loc[repair_doc_mask, "approved_by"] = company.map(
        lambda value: f"JE_APPROVER_{value}" if value else "JE_APPROVER_C001"
    ).to_numpy()
    if "approval_date" in rows.columns:
        fallback_date = rows.loc[repair_doc_mask, "posting_date"].fillna("").astype(str).str[:10]
        rows.loc[repair_doc_mask, "approval_date"] = fallback_date.mask(
            fallback_date.eq(""), "2024-12-31"
        )
    return {
        "neutralized_documents": len(repair_docs),
        "neutralized_rows": int(repair_doc_mask.sum()),
    }


def sorted_doc_indices(rows: pd.DataFrame, mask: pd.Series) -> list[int]:
    subset = rows.loc[mask].copy()
    if "line_number" in subset.columns:
        subset["_line_sort"] = pd.to_numeric(subset["line_number"], errors="coerce").fillna(999999)
        subset = subset.sort_values(["_line_sort"])
    return list(subset.index)


def force_two_sided_entry(
    rows: pd.DataFrame,
    mask: pd.Series,
    *,
    debit_gl: str,
    credit_gl: str,
    amount: float | int,
) -> None:
    indices = sorted_doc_indices(rows, mask)
    if len(indices) < 2:
        return
    debit_idx = next(
        (
            idx
            for idx in indices
            if float(pd.to_numeric(pd.Series([rows.at[idx, "debit_amount"]]), errors="coerce").fillna(0).iloc[0])
            > 0
        ),
        indices[0],
    )
    credit_idx = next(
        (
            idx
            for idx in indices
            if idx != debit_idx
            and float(pd.to_numeric(pd.Series([rows.at[idx, "credit_amount"]]), errors="coerce").fillna(0).iloc[0])
            > 0
        ),
        indices[1] if indices[0] == debit_idx else indices[0],
    )
    rows.loc[indices, ["debit_amount", "credit_amount", "local_amount"]] = "0"
    amount = amount_text(amount)
    rows.at[debit_idx, "gl_account"] = debit_gl
    rows.at[debit_idx, "debit_amount"] = amount
    rows.at[debit_idx, "credit_amount"] = "0"
    rows.at[debit_idx, "local_amount"] = amount
    rows.at[credit_idx, "gl_account"] = credit_gl
    rows.at[credit_idx, "debit_amount"] = "0"
    rows.at[credit_idx, "credit_amount"] = amount
    rows.at[credit_idx, "local_amount"] = amount


def doc_base_amount(rows: pd.DataFrame, mask: pd.Series) -> float:
    debit = pd.to_numeric(rows.loc[mask, "debit_amount"], errors="coerce").fillna(0.0).sum()
    credit = pd.to_numeric(rows.loc[mask, "credit_amount"], errors="coerce").fillna(0.0).sum()
    local = pd.to_numeric(rows.loc[mask, "local_amount"], errors="coerce").fillna(0.0).abs().max()
    return max(float(debit), float(credit), float(local), 1_000_000.0)


def apply_substantive_manipulation_patterns(rows: pd.DataFrame, selected: dict[str, str]) -> dict[str, Any]:
    doc_ids = rows["document_id"].astype(str)
    stats = {
        "circular_ic_docs": 0,
        "circular_unmatched_reference_docs": 0,
        "circular_period_end_docs": 0,
        "fictitious_revenue_docs": 0,
        "fictitious_batch_docs": 0,
        "embezzlement_cash_advance_docs": 0,
        "embezzlement_duplicate_pair_docs": 0,
        "embezzlement_near_limit_docs": 0,
    }

    selected_by_scenario: dict[str, list[str]] = {}
    for doc_id, scenario in selected.items():
        selected_by_scenario.setdefault(scenario, []).append(doc_id)

    for offset, doc_id in enumerate(sorted(selected_by_scenario.get("circular_related_party_transaction", []))):
        mask = doc_ids.eq(doc_id)
        if not mask.any():
            continue
        bucket = stable_bucket(doc_id)
        amount = max(doc_base_amount(rows, mask), 250_000_000)
        force_two_sided_entry(
            rows,
            mask,
            debit_gl=IC_GL_ACCOUNTS[bucket % len(IC_GL_ACCOUNTS)],
            credit_gl=IC_GL_ACCOUNTS[(bucket + 1) % len(IC_GL_ACCOUNTS)],
            amount=amount,
        )
        year = str(rows.loc[mask, "fiscal_year"].iloc[0])
        rows.loc[mask, "reference"] = f"IC{year}{offset:05d}" if offset % 2 == 0 else f"ICS-{year}-{offset:05d}"
        period_end_dt = pd.Timestamp(
            year=int(year),
            month=12,
            day=30 if offset % 2 == 0 else 31,
            hour=21 + (offset % 3),
            minute=offset % 60,
        )
        rows.loc[mask, "posting_date"] = period_end_dt.strftime("%Y-%m-%d %H:%M:%S")
        rows.loc[mask, "document_date"] = period_end_dt.date().isoformat()
        rows.loc[mask, "source"] = "adjustment"
        rows.loc[mask, "mutation_mutated_field"] = "substantive_intercompany_gl_and_period_end"
        rows.loc[mask, "mutation_mutated_value"] = "intercompany_gl_prefix_with_period_end_adjustment"
        stats["circular_ic_docs"] += 1
        stats["circular_period_end_docs"] += 1
        if offset % 2 == 0:
            stats["circular_unmatched_reference_docs"] += 1

    fictitious_docs = sorted(selected_by_scenario.get("fictitious_entry", []))
    for offset, doc_id in enumerate(fictitious_docs):
        mask = doc_ids.eq(doc_id)
        if not mask.any():
            continue
        bucket = stable_bucket(doc_id)
        base = max(doc_base_amount(rows, mask), 500_000_000)
        amount = max(base, 25_000_000_000) if offset % 3 == 0 else max(base, 1_500_000_000)
        force_two_sided_entry(
            rows,
            mask,
            debit_gl=FICTITIOUS_REVENUE_DEBIT_ACCOUNTS[bucket % len(FICTITIOUS_REVENUE_DEBIT_ACCOUNTS)],
            credit_gl=FICTITIOUS_REVENUE_CREDIT_ACCOUNTS[
                bucket % len(FICTITIOUS_REVENUE_CREDIT_ACCOUNTS)
            ],
            amount=amount,
        )
        rows.loc[mask, "business_process"] = "O2C"
        rows.loc[mask, "counterparty_type"] = "Customer"
        rows.loc[mask, "document_type"] = "SA"
        rows.loc[mask, "mutation_mutated_field"] = "substantive_fictitious_revenue"
        rows.loc[mask, "mutation_mutated_value"] = "ar_or_cash_to_revenue_with_outlier_amount"
        stats["fictitious_revenue_docs"] += 1

        if offset % 4 == 0:
            year = int(rows.loc[mask, "fiscal_year"].iloc[0])
            batch_dt = pd.Timestamp(year=year, month=12, day=30, hour=22, minute=offset % 60)
            rows.loc[mask, "posting_date"] = batch_dt.strftime("%Y-%m-%d %H:%M:%S")
            rows.loc[mask, "document_date"] = batch_dt.date().isoformat()
            rows.loc[mask, "created_by"] = "BATCH_FICT_USER"
            rows.loc[mask, "source"] = "adjustment"
            stats["fictitious_batch_docs"] += 1

    embezzlement_docs = sorted(selected_by_scenario.get("embezzlement_concealment", []))
    for offset, doc_id in enumerate(embezzlement_docs):
        mask = doc_ids.eq(doc_id)
        if not mask.any():
            continue
        bucket = stable_bucket(doc_id)
        amount = NEAR_LIMIT_AMOUNT if offset % 3 == 0 else max(doc_base_amount(rows, mask), 250_000_000)
        force_two_sided_entry(
            rows,
            mask,
            debit_gl=EMBEZZLEMENT_DEBIT_ACCOUNTS[bucket % len(EMBEZZLEMENT_DEBIT_ACCOUNTS)],
            credit_gl=EMBEZZLEMENT_CREDIT_ACCOUNTS[0],
            amount=amount,
        )
        rows.loc[mask, "business_process"] = "P2P"
        rows.loc[mask, "document_type"] = "KZ"
        rows.loc[mask, "counterparty_type"] = "Employee"
        rows.loc[mask, "trading_partner"] = "EMP-ADVANCE"
        rows.loc[mask, "auxiliary_account_number"] = "EMP-ADVANCE"
        rows.loc[mask, "auxiliary_account_label"] = "임직원 정산"
        rows.loc[mask, "mutation_mutated_field"] = "substantive_cash_leakage"
        rows.loc[mask, "mutation_mutated_value"] = "employee_advance_to_cash"
        stats["embezzlement_cash_advance_docs"] += 1

        if offset % 3 == 0:
            rows.loc[mask, "approved_by"] = NEAR_LIMIT_APPROVER
            rows.loc[mask, "approval_date"] = rows.loc[mask, "posting_date"].fillna("").astype(str).str[:10]
            stats["embezzlement_near_limit_docs"] += 1

        pair_id = offset // 2
        if offset % 2 in {0, 1}:
            year = int(rows.loc[mask, "fiscal_year"].iloc[0])
            pair_dt = pd.Timestamp(year=year, month=6, day=15 + min(pair_id % 7, 7), hour=10)
            if offset % 2 == 1:
                pair_dt += pd.Timedelta(days=2)
            duplicate_amount = 850_000_000 + pair_id * 1000
            force_two_sided_entry(
                rows,
                mask,
                debit_gl=EMBEZZLEMENT_DEBIT_ACCOUNTS[bucket % len(EMBEZZLEMENT_DEBIT_ACCOUNTS)],
                credit_gl=EMBEZZLEMENT_CREDIT_ACCOUNTS[0],
                amount=duplicate_amount,
            )
            rows.loc[mask, "posting_date"] = pair_dt.strftime("%Y-%m-%d %H:%M:%S")
            rows.loc[mask, "document_date"] = pair_dt.date().isoformat()
            rows.loc[mask, "reference"] = f"EMP-CARD-DUP-{pair_id:04d}"
            rows.loc[mask, "trading_partner"] = f"EMP-CARD-{pair_id:04d}"
            rows.loc[mask, "auxiliary_account_number"] = rows.loc[mask, "trading_partner"]
            stats["embezzlement_duplicate_pair_docs"] += 1

    return stats


def apply_manipulation_surface(rows: pd.DataFrame, selected: dict[str, str]) -> None:
    doc_ids = rows["document_id"].astype(str)
    for doc_id, scenario in selected.items():
        mask = doc_ids.eq(doc_id)
        first = rows.loc[mask].iloc[0]
        year = int(first["fiscal_year"])
        bucket = stable_bucket(doc_id)
        subtype = SCENARIO_SUBTYPES[scenario][bucket % len(SCENARIO_SUBTYPES[scenario])]
        dt = scenario_datetime(year, scenario, bucket)
        date = dt.date().isoformat()
        rows.loc[mask, "posting_date"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        rows.loc[mask, "document_date"] = date
        rows.loc[mask, "fiscal_period"] = str(dt.month)
        rows.loc[mask, "mutation_base_event_type"] = rows.loc[mask, "semantic_scenario_id"].fillna("").astype(str)
        rows.loc[mask, "mutation_type"] = scenario
        rows.loc[mask, "mutation_mutated_field"] = "manipulation_surface"
        rows.loc[mask, "mutation_original_value"] = "semantic_clean_baseline"
        rows.loc[mask, "mutation_mutated_value"] = subtype
        rows.loc[mask, "mutation_reason"] = SCENARIO_INTENTS[scenario]
        rows.loc[mask, "detection_surface_hints"] = scenario

        if scenario in {"approval_sod_bypass", "period_end_adjustment_manipulation", "unusual_timing_manipulation"}:
            rows.loc[mask, "source"] = "manual" if scenario != "period_end_adjustment_manipulation" else "adjustment"
            created_by = str(first.get("created_by") or "").strip()
            rows.loc[mask, "approved_by"] = created_by
            rows.loc[mask, "approval_date"] = "" if scenario == "approval_sod_bypass" and bucket % 2 == 0 else date
            rows.loc[mask, "user_persona"] = "senior_accountant"
        if scenario == "circular_related_party_transaction":
            rows.loc[mask, "business_process"] = "Intercompany"
            rows.loc[mask, "counterparty_type"] = "IntercompanyAffiliate"
            rows.loc[mask, "trading_partner"] = "IC-C002" if str(first.get("company_code")) != "C002" else "IC-C001"
            rows.loc[mask, "auxiliary_account_number"] = rows.loc[mask, "trading_partner"]
            rows.loc[mask, "auxiliary_account_label"] = "관계사 정산"
        if scenario == "embezzlement_concealment":
            rows.loc[mask, "source"] = "manual"
            rows.loc[mask, "counterparty_type"] = "Employee"
            rows.loc[mask, "trading_partner"] = "EMP-ADVANCE"
            rows.loc[mask, "auxiliary_account_number"] = "EMP-ADVANCE"
            rows.loc[mask, "auxiliary_account_label"] = "임직원 정산"
        if scenario == "fictitious_entry":
            rows.loc[mask, "source"] = "adjustment"
        text = {
            "approval_sod_bypass": "긴급 승인 경로 조정",
            "circular_related_party_transaction": "관계사 정산",
            "embezzlement_concealment": "임직원 비용 정산",
            "fictitious_entry": "거래 정산 반영",
            "period_end_adjustment_manipulation": "결산 추정 조정",
            "unusual_timing_manipulation": "마감 전표 처리",
        }[scenario]
        rows.loc[mask, "header_text"] = text
        rows.loc[mask, "line_text"] = rows.loc[mask, "line_text"].fillna("").astype(str).where(
            rows.loc[mask, "line_text"].fillna("").astype(str).str.strip().ne(""),
            text,
        )


def build_truth(rows: pd.DataFrame, selected: dict[str, str]) -> pd.DataFrame:
    docs = doc_frame(rows)
    docs = docs.loc[docs["document_id"].astype(str).isin(selected)].copy()
    docs["manipulation_scenario"] = docs["document_id"].astype(str).map(selected)
    docs["manipulation_subtype"] = docs.apply(
        lambda row: SCENARIO_SUBTYPES[row["manipulation_scenario"]][
            stable_bucket(row["document_id"]) % len(SCENARIO_SUBTYPES[row["manipulation_scenario"]])
        ],
        axis=1,
    )
    docs["year_concept"] = docs["fiscal_year"].map(
        {
            2022: "conservative_control_environment_low_volume_manipulation",
            2023: "mixed_control_environment_manipulation",
            2024: "heightened_close_pressure_manipulation",
        }
    )
    docs["manipulation_intent"] = docs["manipulation_scenario"].map(SCENARIO_INTENTS)
    docs["reference_pattern"] = docs["manipulation_scenario"] + ":" + docs["manipulation_subtype"]
    docs["base_reference_weight"] = "0.4"
    docs["stealth_profile"] = docs["manipulation_subtype"].map(
        lambda value: "workflow_owner" if "approval" in str(value) or "sod" in str(value) else "routine_reference"
    )
    docs["not_rule_targeted"] = True
    docs["truth_layer"] = "manipulated_entry_truth"
    docs["evaluation_note"] = (
        "Evaluate whether L1-L4 signal combinations surface this manipulated entry; not rule-specific truth."
    )
    cols = [
        "document_id",
        "fiscal_year",
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
        "line_amount",
        "line_count",
        "manipulation_scenario",
        "year_concept",
        "manipulation_intent",
        "reference_pattern",
        "base_reference_weight",
        "stealth_profile",
        "not_rule_targeted",
        "truth_layer",
        "evaluation_note",
        "manipulation_subtype",
    ]
    return docs[cols].sort_values(["fiscal_year", "manipulation_scenario", "document_id"]).reset_index(drop=True)


def build_anomaly_labels(truth: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for idx, row in enumerate(truth.itertuples(index=False), start=1):
        metadata = {
            "dataset_role": "manipulation",
            "truth_source": "manipulated_entry_truth",
            "fiscal_year": int(row.fiscal_year),
            "manipulation_scenario": row.manipulation_scenario,
            "manipulation_subtype": row.manipulation_subtype,
            "year_concept": row.year_concept,
            "stealth_profile": row.stealth_profile,
            "not_rule_targeted": bool(row.not_rule_targeted),
        }
        structured = {
            "manipulation_scenario": row.manipulation_scenario,
            "manipulation_subtype": row.manipulation_subtype,
            "reference_pattern": row.reference_pattern,
        }
        rows.append(
            {
                "anomaly_id": f"MANIPV2{idx:06d}",
                "anomaly_category": "ManipulationTruth",
                "anomaly_type": row.manipulation_scenario,
                "document_id": row.document_id,
                "document_type": row.document_type,
                "company_code": row.company_code,
                "anomaly_date": str(row.posting_date).split(" ")[0],
                "detection_timestamp": now,
                "confidence": 1.0,
                "severity": 4,
                "description": f"Manipulation truth scenario: {row.manipulation_scenario}",
                "is_injected": True,
                "monetary_impact": float(row.line_amount) if pd.notna(row.line_amount) else None,
                "related_entities": json.dumps([row.document_id], ensure_ascii=False),
                "cluster_id": row.reference_pattern,
                "original_document_hash": "",
                "injection_strategy": row.manipulation_scenario,
                "structured_strategy_type": row.manipulation_subtype,
                "structured_strategy_json": json.dumps(structured, ensure_ascii=False),
                "causal_reason_type": "ManipulationScenario",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": row.manipulation_scenario,
                "run_id": "datasynth_manipulation_v2",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows, columns=ANOMALY_COLUMNS)


def compute_operational_noise_floor(target: Path, rows: pd.DataFrame) -> dict[str, Any]:
    total_rows = max(len(rows), 1)
    approved_by = rows["approved_by"].fillna("").astype(str).str.strip().str.upper()
    source = rows["source"].fillna("").astype(str).str.strip().str.lower()
    posting = pd.to_datetime(rows["posting_date"], errors="coerce")
    approved_missing = approved_by.eq("") | approved_by.isin({"NAN", "NONE", "NULL"})
    manual = source.isin({"manual", "adjustment"})
    weekend = posting.dt.weekday.ge(5).fillna(False)

    employees_path = target / "master_data" / "employees.json"
    approval_gap = pd.Series(False, index=rows.index)
    if employees_path.exists():
        records = json.loads(employees_path.read_text(encoding="utf-8"))
        employees = {
            str(row.get("user_id") or "").strip().upper(): row
            for row in records
            if str(row.get("user_id") or "").strip()
        }
        ids = set(employees)
        can_approve = {
            user_id: bool(row.get("can_approve_je", False))
            for user_id, row in employees.items()
        }
        authorized = {
            user_id: {
                str(value).strip().upper()
                for value in row.get("authorized_company_codes") or []
                if str(value).strip()
            }
            for user_id, row in employees.items()
        }
        creator = rows["created_by"].fillna("").astype(str).str.strip().str.upper()
        company = rows["company_code"].fillna("").astype(str).str.strip().str.upper()
        known = approved_by.isin(ids)
        can = approved_by.map(can_approve).fillna(False).astype(bool)
        company_authorized = pd.Series(
            [
                bool(comp) and comp in authorized.get(approver, set())
                for comp, approver in zip(company, approved_by, strict=False)
            ],
            index=rows.index,
        )
        self_approved = creator.ne("") & creator.eq(approved_by)
        approval_gap = manual & (
            approved_missing
            | self_approved
            | (~known & ~approved_missing)
            | (~can & ~approved_missing)
            | (~company_authorized & ~approved_missing)
        )

    def pct(mask: pd.Series) -> float:
        return round(float(mask.sum()) / total_rows, 6)

    return {
        "approved_by_null_rows": int(approved_missing.sum()),
        "approved_by_null_pct": pct(approved_missing),
        "manual_entry_rows": int(manual.sum()),
        "manual_entry_pct": pct(manual),
        "approval_matrix_gap_rows": int(approval_gap.sum()),
        "approval_matrix_gap_pct": pct(approval_gap),
        "weekend_posting_rows": int(weekend.sum()),
        "weekend_posting_pct": pct(weekend),
    }


def write_journal(target: Path, rows: pd.DataFrame) -> dict[str, Any]:
    rows.to_csv(target / "journal_entries.csv", index=False, encoding="utf-8")
    stats: dict[str, Any] = {
        "journal_entries_all": {
            "rows": int(len(rows)),
            "docs": int(rows["document_id"].nunique()),
            "columns": int(len(rows.columns)),
        }
    }
    for year in YEARS:
        subset = rows.loc[rows["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(target / f"journal_entries_{year}.csv", index=False, encoding="utf-8")
        stats[f"journal_entries_{year}"] = {
            "rows": int(len(subset)),
            "docs": int(subset["document_id"].nunique()),
            "columns": int(len(subset.columns)),
        }
    return stats


def write_labels(target: Path, truth: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    labels_dir = target / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    truth.to_csv(labels_dir / "manipulated_entry_truth.csv", index=False, encoding="utf-8")
    write_json_records(labels_dir / "manipulated_entry_truth.json", truth)
    for year in YEARS:
        subset = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(labels_dir / f"manipulated_entry_truth_{year}.csv", index=False, encoding="utf-8")
        write_json_records(labels_dir / f"manipulated_entry_truth_{year}.json", subset)

    summary = (
        truth.groupby(["fiscal_year", "manipulation_scenario"], as_index=False)
        .agg(document_count=("document_id", "nunique"))
        .sort_values(["fiscal_year", "manipulation_scenario"])
    )
    summary.to_csv(labels_dir / "manipulated_entry_scenario_summary.csv", index=False, encoding="utf-8")
    write_json_records(labels_dir / "manipulated_entry_scenario_summary.json", summary)

    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False, encoding="utf-8")
    write_json_records(labels_dir / "anomaly_labels.json", labels)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for record in labels.to_dict(orient="records"):
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    label_summary = {
        "dataset_role": "manipulation",
        "truth_source": "manipulated_entry_truth",
        "rows": int(len(labels)),
        "documents": int(labels["document_id"].nunique()),
        "anomaly_type_counts": {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().sort_index().to_dict().items()},
    }
    write_json(labels_dir / "anomaly_labels_summary.json", label_summary)
    (labels_dir / "README_MANIPULATION_LABELS.md").write_text(
        """# DataSynth Manipulation V2 Labels

Active truth files:

- `manipulated_entry_truth*`: scenario-level manipulation truth.
- `anomaly_labels*`: compatibility label family rebuilt from `manipulated_entry_truth`.
- `manipulated_entry_scenario_summary*`: scenario count summary.

Excluded from this split:

- `rule_truth*`
- contract-only sidecars and taxonomies

Phase1 may flag non-truth documents as review candidates. That is expected background behavior, not manipulation truth.
""",
        encoding="utf-8",
    )
    return label_summary


def validate(target: Path, rows: pd.DataFrame, truth: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    failures: list[str] = []
    truth_docs = set(truth["document_id"].astype(str))
    label_docs = set(labels["document_id"].astype(str))
    journal_docs = set(rows["document_id"].astype(str))
    if truth_docs != label_docs:
        failures.append(f"truth/label doc mismatch: missing={len(truth_docs-label_docs)} extra={len(label_docs-truth_docs)}")
    if not truth_docs <= journal_docs:
        failures.append(f"truth docs missing from journal: {len(truth_docs-journal_docs)}")
    for year, targets in SCENARIO_TARGETS.items():
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))]
        counts = year_truth["manipulation_scenario"].value_counts().to_dict()
        for scenario, expected in targets.items():
            actual = int(counts.get(scenario, 0))
            if actual != expected:
                failures.append(f"{year} {scenario}: expected={expected}, actual={actual}")
    forbidden = sorted(
        path.name
        for path in (target / "labels").glob("*")
        if path.name.startswith("rule_truth") or path.name.startswith("contract_") or "sidecar" in path.name
    )
    if forbidden:
        failures.append(f"contract label files present in manipulation split: {forbidden[:10]}")
    mutation_type_missing = rows.loc[
        rows["document_id"].astype(str).isin(truth_docs)
        & rows["mutation_type"].fillna("").astype(str).str.strip().eq("")
    ]
    if not mutation_type_missing.empty:
        failures.append(f"truth journal rows missing mutation_type: {len(mutation_type_missing)}")
    leakage_cols = [col for col in ["is_fraud", "fraud_type", "is_anomaly", "anomaly_type"] if col in rows.columns]
    if leakage_cols:
        failures.append(f"direct label leakage columns present: {leakage_cols}")
    return {
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "truth_documents": len(truth_docs),
        "label_documents": len(label_docs),
        "truth_rows": int(len(truth)),
        "scenario_counts": {
            str(k): int(v) for k, v in truth["manipulation_scenario"].value_counts().sort_index().to_dict().items()
        },
        "forbidden_contract_label_files": forbidden,
        "leakage_columns_present": leakage_cols,
    }


def write_manifests(
    target: Path,
    source: Path,
    stats: dict[str, Any],
    label_summary: dict[str, Any],
    checks: dict[str, Any],
    operational_noise_floor: dict[str, Any],
) -> None:
    manifest = {
        "dataset": "datasynth_manipulation_v2",
        "source_dataset": str(source),
        "base_policy": "semantic contract-v2 journal schema and generation options",
        "purpose": "Semantic-clean journal background plus scenario-level manipulation truth.",
        "journal_policy": "No direct is_fraud/is_anomaly labels; manipulation truth is represented through labels and mutation provenance.",
        "labels_policy": "Manipulation-only labels; contract rule truth and sidecars are excluded.",
        "stats": stats,
        "label_summary": label_summary,
        "checks": checks,
        "operational_noise_floor": operational_noise_floor,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(target / "MANIPULATION_V2_DATASET_MANIFEST.json", manifest)
    write_json(target / "validated_metadata.json", {"version": "datasynth_manipulation_v2", "status": checks["status"], "checks": checks})
    (target / "PREVIEW.md").write_text(
        "\n".join(
            [
                "# DataSynth Manipulation V2",
                "",
                "Semantic-clean background dataset with manipulation-only truth labels.",
                "",
                f"- source: `{source}`",
                f"- truth documents: `{checks['truth_documents']}`",
                f"- status: `{checks['status']}`",
                "",
                "Contract rule truth files are intentionally excluded.",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    prepare_target(args.source, args.target, args.force)
    ensure_manipulation_employee_limits(args.target)
    rows = load_journal(args.source)
    docs = doc_frame(rows)
    selected = select_docs(docs)
    approval_cleanup = neutralize_nontruth_contract_approval_fixtures(rows, selected)
    apply_manipulation_surface(rows, selected)
    substantive_stats = apply_substantive_manipulation_patterns(rows, selected)
    truth = build_truth(rows, selected)
    labels = build_anomaly_labels(truth)
    stats = write_journal(args.target, rows)
    label_summary = write_labels(args.target, truth, labels)
    checks = validate(args.target, rows, truth, labels)
    checks["approval_cleanup"] = approval_cleanup
    checks["substantive_mutation_stats"] = substantive_stats
    operational_noise_floor = compute_operational_noise_floor(args.target, rows)
    write_manifests(args.target, args.source, stats, label_summary, checks, operational_noise_floor)
    print(json.dumps({"target": str(args.target), "checks": checks}, ensure_ascii=False, indent=2))
    if checks["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
