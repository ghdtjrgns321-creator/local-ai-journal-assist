"""Build v84 candidate with rule-agnostic manipulated-entry scenarios.

The scenarios are based on DETECTION_REFERENCE.md pattern proportions, not on a
single detector rule. They are stored as a separate manipulated-entry truth
sidecar so Phase 1 rule-truth contracts remain field based.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v83_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v84_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)

YEAR_SCENARIO_COUNTS: dict[int, dict[str, int]] = {
    2022: {
        "fictitious_entry": 46,
        "period_end_adjustment_manipulation": 25,
        "embezzlement_concealment": 21,
        "circular_related_party_transaction": 9,
        "approval_sod_bypass": 8,
        "unusual_timing_manipulation": 6,
    },
    2023: {
        "fictitious_entry": 58,
        "period_end_adjustment_manipulation": 32,
        "embezzlement_concealment": 26,
        "circular_related_party_transaction": 12,
        "approval_sod_bypass": 10,
        "unusual_timing_manipulation": 7,
    },
    2024: {
        "fictitious_entry": 64,
        "period_end_adjustment_manipulation": 35,
        "embezzlement_concealment": 29,
        "circular_related_party_transaction": 13,
        "approval_sod_bypass": 11,
        "unusual_timing_manipulation": 8,
    },
}

YEAR_CONCEPTS = {
    2022: "conservative_control_environment_low_volume_manipulation",
    2023: "transaction_growth_pressure_and_close_adjustments",
    2024: "new_process_related_party_and_workflow_transition",
}

SCENARIO_META = {
    "fictitious_entry": {
        "reference_pattern": "FSS fictitious journal-entry pattern",
        "base_weight": 0.40,
        "intent": "recognize non-existent revenue, asset, or expense transaction",
        "stealth": ("routine_reference", "normal_description", "manual_accrual"),
    },
    "period_end_adjustment_manipulation": {
        "reference_pattern": "FSS period-end adjustment manipulation pattern",
        "base_weight": 0.22,
        "intent": "move profit or balance sheet estimate near close",
        "stealth": ("closing_adjustment", "estimate_revision", "accrual_cleanup"),
    },
    "embezzlement_concealment": {
        "reference_pattern": "FSS embezzlement concealment pattern",
        "base_weight": 0.18,
        "intent": "hide cash leakage with prepayment, loan, receivable, or suspense-like balance",
        "stealth": ("advance_settlement", "temporary_receivable", "vendor_reclass"),
    },
    "circular_related_party_transaction": {
        "reference_pattern": "FSS circular/related-party transaction pattern",
        "base_weight": 0.08,
        "intent": "create apparent business activity through related-party flow",
        "stealth": ("intercompany_settlement", "roundtrip_reference", "netting_entry"),
    },
    "approval_sod_bypass": {
        "reference_pattern": "FSS approval/SOD bypass pattern",
        "base_weight": 0.07,
        "intent": "process manipulated entry with weak approval or duty concentration",
        "stealth": ("workflow_owner", "delegated_route", "urgent_approval"),
    },
    "unusual_timing_manipulation": {
        "reference_pattern": "FSS unusual-timing manipulation pattern",
        "base_weight": 0.05,
        "intent": "post adjustment at low-review timing around close or non-business time",
        "stealth": ("late_night_close", "weekend_posting", "backlog_release"),
    },
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_exclusion_docs() -> set[str]:
    exclude: set[str] = set()
    for name in ("anomaly_labels.csv", "manipulated_entry_truth.csv"):
        path = LABELS / name
        if path.exists():
            frame = pd.read_csv(path, dtype=str, usecols=["document_id"])
            exclude.update(frame["document_id"].dropna().astype(str))
    return exclude


def _doc_frame(df: pd.DataFrame) -> pd.DataFrame:
    debit = pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0.0)
    tmp = df.copy()
    tmp["_line_amount"] = debit.where(debit.gt(0), credit)
    return tmp.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        document_date=("document_date", "first"),
        fiscal_period=("fiscal_period", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        approved_by=("approved_by", "first"),
        approval_date=("approval_date", "first"),
        user_persona=("user_persona", "first"),
        reference=("reference", "first"),
        trading_partner=("trading_partner", "first"),
        header_text=("header_text", "first"),
        line_amount=("_line_amount", "sum"),
        line_count=("line_number", "count"),
    )


def _is_missing(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"", "none", "nan", "nat", "<na>"})


def _pick(docs: pd.DataFrame, mask: pd.Series, count: int, used: set[str], salt: str) -> pd.DataFrame:
    candidates = docs.loc[mask & ~docs["document_id"].astype(str).isin(used)].copy()
    if candidates.empty:
        return candidates
    candidates["_sort"] = (
        candidates["company_code"].fillna("")
        + "|"
        + candidates["business_process"].fillna("")
        + "|"
        + candidates["source"].fillna("")
        + "|"
        + candidates["document_id"].astype(str)
        + "|"
        + salt
    )
    candidates = candidates.sort_values("_sort").copy()
    candidates["_stratum_rank"] = candidates.groupby(
        ["business_process", "source"],
        dropna=False,
    ).cumcount()
    return (
        candidates.sort_values(["_stratum_rank", "business_process", "source", "_sort"])
        .head(count)
        .drop(columns=["_sort", "_stratum_rank"])
    )


def _scenario_mask(docs: pd.DataFrame, scenario: str) -> pd.Series:
    source = docs["source"].fillna("").astype(str).str.lower().str.strip()
    process = docs["business_process"].fillna("").astype(str).str.upper().str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    approval_date = docs["approval_date"].fillna("").astype(str).str.strip()
    posting = pd.to_datetime(docs["posting_date"], errors="coerce")
    day = posting.dt.day
    weekend = posting.dt.dayofweek >= 5
    has_approval = approved.ne("") & approval_date.ne("")
    human = source.isin({"manual", "adjustment"})
    not_missing_approval = has_approval

    if scenario == "fictitious_entry":
        return not_missing_approval & human & process.isin({"O2C", "R2R", "A2R"})
    if scenario == "period_end_adjustment_manipulation":
        return not_missing_approval & (human | source.eq("recurring")) & (day.ge(25) | day.le(5))
    if scenario == "embezzlement_concealment":
        return not_missing_approval & human & process.isin({"P2P", "TRE", "R2R"})
    if scenario == "circular_related_party_transaction":
        tp = docs["trading_partner"].fillna("").astype(str).str.strip()
        return not_missing_approval & tp.ne("") & process.isin({"R2R", "O2C", "P2P", "TRE"})
    if scenario == "approval_sod_bypass":
        same_user = docs["created_by"].fillna("").astype(str).str.strip().eq(approved)
        missing_approver = _is_missing(docs["approved_by"])
        return same_user | missing_approver
    if scenario == "unusual_timing_manipulation":
        return not_missing_approval & (weekend | day.ge(27) | day.le(3))
    return pd.Series(False, index=docs.index)


def _fallback_mask(docs: pd.DataFrame) -> pd.Series:
    return ~_is_missing(docs["document_id"])


def _patch_text(df: pd.DataFrame, doc_ids: set[str], scenario: str) -> None:
    if not doc_ids:
        return
    doc_mask = df["document_id"].astype(str).isin(doc_ids)
    label = {
        "fictitious_entry": "supporting schedule true-up",
        "period_end_adjustment_manipulation": "period-end estimate revision",
        "embezzlement_concealment": "advance settlement clearing",
        "circular_related_party_transaction": "intercompany netting settlement",
        "approval_sod_bypass": "urgent workflow reroute",
        "unusual_timing_manipulation": "close backlog release",
    }[scenario]
    current_header = df.loc[doc_mask, "header_text"].fillna("").astype(str).str.slice(0, 160)
    current_line = df.loc[doc_mask, "line_text"].fillna("").astype(str).str.slice(0, 160)
    df.loc[doc_mask, "header_text"] = current_header + " | " + label
    df.loc[doc_mask, "line_text"] = current_line + " | " + label
    ref = df.loc[doc_mask, "reference"].fillna("").astype(str).str.strip()
    df.loc[doc_mask, "reference"] = ref.where(ref.ne(""), "MNL-" + df.loc[doc_mask, "document_number"].astype(str))


def _patch_year(year: int, global_exclude: set[str]) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    docs = _doc_frame(df)
    used = set(global_exclude)
    selected_frames: list[pd.DataFrame] = []

    for scenario, count in YEAR_SCENARIO_COUNTS[year].items():
        picked = _pick(docs, _scenario_mask(docs, scenario), count, used, scenario)
        if len(picked) < count:
            remaining = count - len(picked)
            fallback = _pick(docs, _fallback_mask(docs), remaining, used | set(picked["document_id"].astype(str)), f"{scenario}_fallback")
            picked = pd.concat([picked, fallback], ignore_index=True, sort=False)
        picked = picked.head(count).copy()
        picked["manipulation_scenario"] = scenario
        picked["year_concept"] = YEAR_CONCEPTS[year]
        picked["manipulation_intent"] = SCENARIO_META[scenario]["intent"]
        picked["reference_pattern"] = SCENARIO_META[scenario]["reference_pattern"]
        picked["base_reference_weight"] = SCENARIO_META[scenario]["base_weight"]
        picked["stealth_profile"] = [
            SCENARIO_META[scenario]["stealth"][idx % len(SCENARIO_META[scenario]["stealth"])]
            for idx in range(len(picked))
        ]
        picked["not_rule_targeted"] = True
        picked["truth_layer"] = "manipulated_entry_truth"
        picked["evaluation_note"] = "Evaluate whether any L1-L4 signal combination surfaces this manipulated entry; do not treat as rule-specific truth."
        selected_frames.append(picked)
        chosen = set(picked["document_id"].dropna().astype(str))
        used.update(chosen)
        _patch_text(df, chosen, scenario)

    df.to_csv(path, index=False)
    return pd.concat(selected_frames, ignore_index=True, sort=False)


def _rewrite_combined_journal() -> None:
    frames = [
        pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        for year in YEARS
    ]
    pd.concat(frames, ignore_index=True).to_csv(DEST / "journal_entries.csv", index=False)


def main() -> None:
    _copy_candidate_safely()
    exclude = _existing_exclusion_docs()
    truth_frames = [_patch_year(year, exclude) for year in YEARS]
    truth = pd.concat(truth_frames, ignore_index=True, sort=False)
    columns = [
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
    ]
    truth = truth[columns].copy()
    truth.to_csv(LABELS / "manipulated_entry_truth.csv", index=False)
    _write_json_records(LABELS / "manipulated_entry_truth.json", truth)
    for year in YEARS:
        subset = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"manipulated_entry_truth_{year}.csv", index=False)
        _write_json_records(LABELS / f"manipulated_entry_truth_{year}.json", subset)

    summary_df = (
        truth.groupby(["fiscal_year", "manipulation_scenario"], as_index=False)
        .size()
        .rename(columns={"size": "document_count"})
    )
    summary_df.to_csv(LABELS / "manipulated_entry_scenario_summary.csv", index=False)
    _write_json_records(LABELS / "manipulated_entry_scenario_summary.json", summary_df)
    _rewrite_combined_journal()

    summary = {
        "candidate_version": "v84",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "add rule-agnostic manipulated-entry truth based on DETECTION_REFERENCE pattern proportions",
        "total_manipulated_documents": int(len(truth)),
        "year_counts": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "scenario_counts": {str(k): int(v) for k, v in truth["manipulation_scenario"].value_counts().to_dict().items()},
        "anti_fitting_note": "These are not designed for one detector rule. Some manipulated entries may be weakly detected or missed by L1-L4, which is expected.",
        "source_reference": "docs/spec/DETECTION_REFERENCE.md FSS manipulation pattern mix",
    }
    (DEST / "V84_MANIPULATED_ENTRY_TRUTH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V84_CANDIDATE.md").write_text(
        "# DataSynth v84 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: rule-agnostic manipulated-entry truth based on detection reference patterns.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
