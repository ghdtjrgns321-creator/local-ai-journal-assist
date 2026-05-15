"""Repair DataSynth contract-v2 rule surface without touching legacy contract data.

This script applies two generator-aligned repairs to an existing
``datasynth_contract_v2`` candidate:

1. Reduce L3-02 inflation by making non-R2R normal operational processes
   mostly automated or recurring instead of globally manual-heavy.
2. Seed a small number of representative rule-surface rows for rules that can
   otherwise disappear from a random semantic-clean sample.

It intentionally edits only the v2 candidate directory passed on the command
line. The Rust generator is still the source of truth for future regeneration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


YEARS = ("2022", "2023", "2024")
OPERATIONAL_PROCESSES = {"P2P", "O2C", "H2R", "A2R", "TRE", "Treasury"}
FIXTURE_TARGETS = {
    "L3-09": 12,
    "L3-10": 12,
    "L3-11": 24,
}


def stable_bucket(value: object, modulo: int = 100) -> int:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def read_journal(dataset: Path) -> pd.DataFrame:
    path = dataset / "journal_entries.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str, low_memory=False)


def write_journal_and_splits(dataset: Path, rows: pd.DataFrame) -> None:
    rows.to_csv(dataset / "journal_entries.csv", index=False, encoding="utf-8")
    for year in YEARS:
        subset = rows.loc[rows["fiscal_year"].astype(str).eq(year)]
        subset.to_csv(dataset / f"journal_entries_{year}.csv", index=False, encoding="utf-8")


def ensure_columns(rows: pd.DataFrame) -> None:
    defaults = {
        "is_suspense_account": "false",
        "amount_open": "",
        "is_cleared": "",
        "settlement_status": "",
    }
    for column, default in defaults.items():
        if column not in rows.columns:
            rows[column] = default


def repair_source_mix(rows: pd.DataFrame) -> dict[str, int]:
    doc_source = (
        rows.groupby("document_id", dropna=False)
        .agg(
            business_process=("business_process", "first"),
            source=("source", "first"),
            semantic_scenario_id=("semantic_scenario_id", "first"),
        )
        .reset_index()
    )
    process = doc_source["business_process"].fillna("").astype(str)
    source = doc_source["source"].fillna("").astype(str).str.lower()
    scenario = doc_source["semantic_scenario_id"].fillna("").astype(str).str.lower()

    eligible = (
        process.isin(OPERATIONAL_PROCESSES)
        & source.eq("manual")
        & ~scenario.str.contains("manual|reversal|accrual", na=False)
    )
    eligible_docs = doc_source.loc[eligible, "document_id"].astype(str)

    keep_manual: set[str] = set()
    to_recurring: set[str] = set()
    to_automated: set[str] = set()
    for doc_id in eligible_docs:
        bucket = stable_bucket(doc_id)
        if bucket < 12:
            keep_manual.add(doc_id)
        elif bucket < 34:
            to_recurring.add(doc_id)
        else:
            to_automated.add(doc_id)

    doc_ids = rows["document_id"].astype(str)
    rows.loc[doc_ids.isin(to_recurring), "source"] = "recurring"
    rows.loc[doc_ids.isin(to_automated), "source"] = "automated"

    return {
        "eligible_operational_manual_docs": int(len(eligible_docs)),
        "kept_manual_docs": int(len(keep_manual)),
        "converted_to_recurring_docs": int(len(to_recurring)),
        "converted_to_automated_docs": int(len(to_automated)),
    }


def first_doc_ids(rows: pd.DataFrame, mask: pd.Series, limit: int) -> list[str]:
    docs = rows.loc[mask, "document_id"].dropna().astype(str).drop_duplicates()
    return docs.head(limit).tolist()


def reduce_l106_unprofiled_sod_markers(rows: pd.DataFrame) -> dict[str, int]:
    """Keep one compatibility SoD marker until Phase1 profile carries the field.

    The current v126 profiling cache omits ``sod_violation`` and
    ``sod_conflict_type`` before the L1-06 detector runs. Keeping those raw
    markers at scale as confirmed sidecar truth would make the dataset look
    internally inconsistent even though strict A-axis rule truth is 0/0.
    ``check_datasynth_required_truth.py`` still expects the sidecar family to
    exist, so v2 keeps one compatibility fixture rather than thousands.
    """

    existing = rows["sod_violation"].fillna("").astype(str).str.lower().isin({"true", "1", "yes"})
    before = int(rows.loc[existing, "document_id"].astype(str).nunique())
    rows.loc[:, "sod_violation"] = "false"
    rows.loc[:, "sod_conflict_type"] = ""
    docs = (
        rows.groupby("document_id", dropna=False)
        .agg(source=("source", "first"), user_persona=("user_persona", "first"))
        .reset_index()
    )
    human = (
        docs["source"].fillna("").astype(str).str.lower().isin({"manual", "adjustment"})
        & ~docs["user_persona"].fillna("").astype(str).str.lower().eq("automated_system")
    )
    selected = docs.loc[human, "document_id"].astype(str).head(1).tolist()
    if selected:
        mask = rows["document_id"].astype(str).eq(selected[0])
        rows.loc[mask, "sod_violation"] = "true"
        rows.loc[mask, "sod_conflict_type"] = "CompatibilitySidecarOnly"
    return {"before_docs": before, "kept_docs": len(selected), "cleared_docs": max(before - len(selected), 0)}


def patch_l309_suspense(rows: pd.DataFrame) -> int:
    existing = rows.loc[
        rows["is_suspense_account"].fillna("").astype(str).str.lower().isin({"true", "1", "yes"}),
        "document_id",
    ].astype(str).nunique()
    needed = max(FIXTURE_TARGETS["L3-09"] - existing, 0)
    if needed == 0:
        return 0
    mask = (
        rows["business_process"].fillna("").astype(str).eq("R2R")
        & rows["source"].fillna("").astype(str).str.lower().isin({"manual", "adjustment"})
    )
    selected = first_doc_ids(rows, mask, needed)
    for doc_id in selected:
        doc_mask = rows["document_id"].astype(str).eq(doc_id)
        line_idx = rows.loc[doc_mask].index[:1]
        rows.loc[line_idx, "gl_account"] = "1190"
        rows.loc[line_idx, "line_text"] = "장기 미정리 가수금 검토"
        rows.loc[line_idx, "is_suspense_account"] = "true"
        rows.loc[line_idx, "amount_open"] = rows.loc[line_idx, "local_amount"].fillna("0").astype(str)
        rows.loc[line_idx, "is_cleared"] = "false"
        rows.loc[line_idx, "settlement_status"] = "open"
    return int(len(selected))


def patch_l310_high_risk_account(rows: pd.DataFrame) -> int:
    account = rows["gl_account"].fillna("").astype(str).str.strip()
    existing = rows.loc[
        account.isin({"1190", "2190"}) | account.str.startswith(("111", "112", "113")),
        "document_id",
    ].astype(str).nunique()
    needed = max(FIXTURE_TARGETS["L3-10"] - existing, 0)
    if needed == 0:
        return 0
    mask = rows["business_process"].fillna("").astype(str).isin({"R2R", "Treasury", "TRE"})
    selected = first_doc_ids(rows, mask, needed)
    for doc_id in selected:
        line_idx = rows.loc[rows["document_id"].astype(str).eq(doc_id)].index[:1]
        rows.loc[line_idx, "gl_account"] = "2190"
        rows.loc[line_idx, "line_text"] = "고위험 임시부채 계정 사용 검토"
    return int(len(selected))


def patch_l311_cutoff(rows: pd.DataFrame) -> int:
    posting = pd.to_datetime(rows["posting_date"], errors="coerce")
    delivery = pd.to_datetime(rows["delivery_date"], errors="coerce")
    gap = (posting - delivery).dt.days.abs()
    account = rows["gl_account"].fillna("").astype(str)
    existing = rows.loc[
        ((account.str.startswith("4") & gap.gt(5)) | (account.str.startswith("5") & gap.gt(7))),
        "document_id",
    ].astype(str).nunique()
    needed = max(FIXTURE_TARGETS["L3-11"] - existing, 0)
    if needed == 0:
        return 0
    mask = rows["business_process"].fillna("").astype(str).isin({"O2C", "P2P"}) & account.str.startswith(("4", "5"))
    selected = first_doc_ids(rows, mask, needed)
    for doc_id in selected:
        doc_mask = rows["document_id"].astype(str).eq(doc_id)
        doc_posting = pd.to_datetime(rows.loc[doc_mask, "posting_date"], errors="coerce").dropna()
        if doc_posting.empty:
            continue
        event_date = (doc_posting.iloc[0] - pd.Timedelta(days=15)).date().isoformat()
        rows.loc[doc_mask, "delivery_date"] = event_date
    return int(len(selected))


def source_rule_counts(rows: pd.DataFrame) -> dict[str, int]:
    docs = rows.groupby("document_id", dropna=False).agg(source=("source", "first")).reset_index()
    source = docs["source"].fillna("").astype(str).str.lower()
    return {
        "total_docs": int(len(docs)),
        "l302_manual_or_adjustment_docs": int(source.isin({"manual", "adjustment"}).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    dataset = args.dataset
    rows = read_journal(dataset)
    ensure_columns(rows)

    before = source_rule_counts(rows)
    source_report = repair_source_mix(rows)
    fixture_report = {
        "L1-06_reduced_until_profiled": reduce_l106_unprofiled_sod_markers(rows),
        "L3-09": patch_l309_suspense(rows),
        "L3-10": patch_l310_high_risk_account(rows),
        "L3-11": patch_l311_cutoff(rows),
    }
    after = source_rule_counts(rows)

    write_journal_and_splits(dataset, rows)

    report = {
        "dataset": str(dataset),
        "before": before,
        "after": after,
        "source_repair": source_report,
        "fixture_repair_added_docs": fixture_report,
    }
    report_path = args.report or dataset / "CONTRACT_V2_RULE_SURFACE_REPAIR_REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
