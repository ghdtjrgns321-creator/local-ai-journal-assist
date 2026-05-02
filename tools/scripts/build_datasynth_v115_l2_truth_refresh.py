"""Build v115 candidate by deleting stale L2 truth and rebuilding it.

This patch is intentionally stricter than earlier cumulative patches:

1. Start from v114.
2. Delete copied L2-03/L2-04/L2-05 rule-truth families from the new candidate.
3. Rebuild those files from the current Phase 1 detector output.

The confirmed anomaly labels remain as injection evidence. The `rule_truth_*`
files are the Phase 1 candidate universe, not the injected-fraud subset.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_reversal import c11_reversal_entry  # noqa: E402
from src.detection.fraud_rules_groupby import b05_duplicate_entry, b11_expense_capitalization  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v114_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v115_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
REFRESH_RULES = ("L2-03", "L2-04", "L2-05")
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")

RULE_INPUT_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "user_persona",
    "posting_date",
    "document_date",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "trading_partner",
    "auxiliary_account_number",
    "auxiliary_account_label",
    "vendor_name",
    "customer_name",
    "counterparty_code",
    "counterparty_name",
    "original_document_id",
    "reversal_document_id",
    "reference_document_id",
    "reversed_document_id",
    "reverse_document_id",
    "reversal_reason",
    "reversal_reason_code",
]


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "V115_L2_TRUTH_REFRESH.json")
        if all(path.exists() for path in required):
            return
        if all(path.exists() for path in required[:-1]):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _read_year(year: int) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [column for column in RULE_INPUT_COLUMNS if column in header]
    frame = pd.read_csv(path, usecols=cols, parse_dates=["posting_date", "document_date"], low_memory=False)
    for column in RULE_INPUT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame[RULE_INPUT_COLUMNS].copy()
    frame["fiscal_year"] = frame["fiscal_year"].fillna(year)
    return frame


def _load_journal() -> pd.DataFrame:
    frames = [_read_year(year) for year in YEARS]
    rows = pd.concat(frames, ignore_index=True)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    for column in ("debit_amount", "credit_amount"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
    return rows


def _purge_stale_l2_truth() -> list[str]:
    removed: list[str] = []
    stale_stems = [
        "rule_truth_L2_03",
        "rule_truth_L2_04",
        "rule_truth_L2_05",
        "duplicate_entry_review_population",
        "expense_capitalization_review_population",
        "reversal_entry_review_population",
    ]
    for stem in stale_stems:
        for path in LABELS.glob(f"{stem}*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
                removed.append(path.name)
                path.unlink()
    return sorted(removed)


def _annotate_from_result(df: pd.DataFrame, result: pd.Series, prefix: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=df.index).fillna(0.0).astype(float)
    work = df.loc[mask].copy()
    if work.empty:
        return pd.DataFrame(), result.attrs.get("breakdown", {})

    work[f"_{prefix}_score"] = scores.loc[work.index].astype(float)
    work["_reason_code"] = work.index.map(
        lambda idx: str(annotations.get(int(idx), {}).get("reason_code", ""))
    )
    work["_primary_signal"] = work.index.map(
        lambda idx: str(annotations.get(int(idx), {}).get("primary_signal", ""))
    )
    work["_interpretation_code"] = work.index.map(
        lambda idx: str(annotations.get(int(idx), {}).get("interpretation_code", ""))
    )
    work["_confidence_band"] = work.index.map(
        lambda idx: str(annotations.get(int(idx), {}).get("confidence_band", ""))
    )
    work["_queue_label"] = work.index.map(
        lambda idx: str(annotations.get(int(idx), {}).get("queue_label", ""))
    )
    work["_matched_reason_codes"] = work.index.map(
        lambda idx: "|".join(str(v) for v in annotations.get(int(idx), {}).get("matched_reason_codes", []))
    )
    work["_trigger_signals"] = work.index.map(
        lambda idx: "|".join(str(v) for v in annotations.get(int(idx), {}).get("trigger_signals", []))
    )

    grouped = work.groupby("document_id", dropna=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
        approved_by=("approved_by", _first_non_null),
        user_persona=("user_persona", _first_non_null),
        line_count=("document_id", "size"),
        flagged_row_count=("document_id", "size"),
        score=(f"_{prefix}_score", "max"),
        reason_code=("_reason_code", _first_non_null),
        primary_signal=("_primary_signal", _first_non_null),
        interpretation_code=("_interpretation_code", _first_non_null),
        confidence_band=("_confidence_band", _first_non_null),
        queue_label=("_queue_label", _first_non_null),
        matched_reason_codes=("_matched_reason_codes", _first_non_null),
        trigger_signals=("_trigger_signals", _first_non_null),
    )
    return grouped.reset_index(), result.attrs.get("breakdown", {})


def _finalize_truth(rule_id: str, truth: pd.DataFrame, basis: str, derivation: str) -> pd.DataFrame:
    out = truth.copy()
    if out.empty:
        out = pd.DataFrame(columns=["document_id"])
    out["fiscal_year"] = pd.to_numeric(out["fiscal_year"], errors="coerce").astype("Int64")
    out["posting_date"] = out["posting_date"].astype(str)
    out["case_id"] = [
        f"{rule_id.replace('-', '')}-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(out["fiscal_year"].fillna(0).tolist())
    ]
    out["rule_id"] = rule_id
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = basis
    out["evaluation_unit"] = "document_id"
    out["truth_derivation"] = derivation
    out["source_candidate"] = "v115"
    out["evaluation_policy"] = (
        "Phase1 raw candidate universe generated from current detector output; "
        "confirmed injected labels and normal controls are separate evidence."
    )
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "line_count",
        "flagged_row_count",
        "score",
        "reason_code",
        "primary_signal",
        "interpretation_code",
        "confidence_band",
        "queue_label",
        "matched_reason_codes",
        "trigger_signals",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_policy",
    ]
    for column in columns:
        if column not in out.columns:
            out[column] = ""
    return out[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True)


def _build_truths(rows: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    settings = get_settings()
    audit_rules = get_audit_rules()

    l203 = b05_duplicate_entry(
        rows,
        amount_tolerance=settings.duplicate_amount_tolerance,
        fuzzy_threshold=settings.duplicate_fuzzy_threshold,
        window_days=settings.duplicate_time_window_days,
        split_window_days=settings.duplicate_split_window_days,
        max_group_size=settings.duplicate_max_group_size,
    )
    l203_docs, l203_breakdown = _annotate_from_result(rows, l203, "l203")

    l204 = b11_expense_capitalization(
        rows,
        audit_rules=audit_rules,
        amount_tolerance=settings.expense_capitalization_amount_tolerance,
        min_amount=settings.expense_capitalization_min_amount,
        review_threshold=settings.expense_capitalization_review_threshold,
        immediate_threshold=settings.expense_capitalization_immediate_threshold,
    )
    l204_docs, l204_breakdown = _annotate_from_result(rows, l204, "l204")

    l205 = c11_reversal_entry(
        rows,
        match_window_days=settings.reversal_match_window_days,
        rolling_window_days=settings.reversal_rolling_window_days,
        zero_threshold=settings.reversal_zero_threshold,
        score_threshold=settings.reversal_score_threshold,
    )
    l205_docs, l205_breakdown = _annotate_from_result(rows, l205, "l205")

    truths = {
        "L2-03": _finalize_truth(
            "L2-03",
            l203_docs,
            "duplicate-entry raw review universe",
            "src.detection.fraud_rules_groupby.b05_duplicate_entry current detector output",
        ),
        "L2-04": _finalize_truth(
            "L2-04",
            l204_docs,
            "expense-capitalization raw review universe",
            "src.detection.fraud_rules_groupby.b11_expense_capitalization current detector output",
        ),
        "L2-05": _finalize_truth(
            "L2-05",
            l205_docs,
            "reversal-pattern raw review universe",
            "src.detection.anomaly_rules_reversal.c11_reversal_entry current detector output",
        ),
    }
    breakdowns = {
        "L2-03": l203_breakdown,
        "L2-04": l204_breakdown,
        "L2-05": l205_breakdown,
    }
    return truths, breakdowns


def _write_truth_family(rule_id: str, truth: pd.DataFrame, review_stem: str) -> None:
    rule_stem = f"rule_truth_{rule_id.replace('-', '_')}"
    for stem in (rule_stem, review_stem):
        truth.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[pd.to_numeric(truth["fiscal_year"], errors="coerce").eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _replace_combined_rule_truth(truths: dict[str, pd.DataFrame]) -> dict[str, int]:
    path = LABELS / "rule_truth.csv"
    if path.exists():
        combined = pd.read_csv(path, low_memory=False)
        combined = combined.loc[~combined["rule_id"].astype(str).isin(REFRESH_RULES)].copy()
    else:
        combined = pd.DataFrame()
    rebuilt = pd.concat([combined, *truths.values()], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)
    return {
        str(rule): int(count)
        for rule, count in rebuilt["rule_id"].value_counts().sort_index().to_dict().items()
    }


def _stale_l2_files() -> dict[str, list[str]]:
    stale: dict[str, list[str]] = {}
    for rule_id in REFRESH_RULES:
        path = LABELS / f"rule_truth_{rule_id.replace('-', '_')}.csv"
        if not path.exists():
            stale[rule_id] = ["missing"]
            continue
        df = pd.read_csv(path, low_memory=False)
        values = sorted(df.get("source_candidate", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
        stale_values = [value for value in values if value != "v115"]
        if stale_values:
            stale[rule_id] = stale_values
    return stale


def main() -> int:
    _copy_candidate_fast()
    removed_files = _purge_stale_l2_truth()
    rows = _load_journal()
    truths, breakdowns = _build_truths(rows)

    review_stems = {
        "L2-03": "duplicate_entry_review_population",
        "L2-04": "expense_capitalization_review_population",
        "L2-05": "reversal_entry_review_population",
    }
    for rule_id, truth in truths.items():
        _write_truth_family(rule_id, truth, review_stems[rule_id])
    rule_counts = _replace_combined_rule_truth(truths)
    stale = _stale_l2_files()
    if stale:
        raise SystemExit(f"stale L2 truth remains after rebuild: {stale}")

    summary = {
        "candidate_version": "v115",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "delete stale L2-03/L2-04/L2-05 truth families and rebuild from current detector output",
        "removed_stale_files": removed_files,
        "replaced_rule_counts": {rule: int(len(df)) for rule, df in truths.items()},
        "detector_breakdowns": breakdowns,
        "all_rule_counts": rule_counts,
        "stale_l2_source_candidates": stale,
        "anti_fitting_note": (
            "This is detector-contract truth for Phase1 raw candidates. It does not claim "
            "that every candidate is injected fraud; risk separation remains in score and sidecars."
        ),
    }
    (DEST / "V115_L2_TRUTH_REFRESH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V115_CANDIDATE.md").write_text(
        "# DataSynth v115 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: stale L2 truth purge and current-detector rebuild.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
