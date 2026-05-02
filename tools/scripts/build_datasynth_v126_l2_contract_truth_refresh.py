"""Build v126 candidate by restoring L2 contract-truth alignment.

Base: datasynth_v125_candidate.

v125 incorrectly narrowed L2-05 rule_truth to a strict subset and only added
metadata to L2-02/L2-03. This patch rebuilds the L2 contract truth from current
detector outputs:

- L2-02: duplicate-payment detector pair universe with stable pair keys.
- L2-03: duplicate-entry detector universe from the active L2-03 A-axis evaluator.
- L2-05: raw reversal detector universe; strict/weak sidecars remain separate.

No journal rows are mutated.
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
from src.detection.fraud_rules_groupby import b04_duplicate_payment, b05_duplicate_entry  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v125_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v126_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V126_CANDIDATE.md", "V126_L2_CONTRACT_TRUTH_REFRESH.json"}

L2_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "posting_date",
    "document_date",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "user_persona",
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
        required.append(DEST / "V126_L2_CONTRACT_TRUTH_REFRESH.json")
        if all(path.exists() for path in required):
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


def _cleanup_version_files() -> dict[str, list[str]]:
    removed_root: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed_root.append(path.name)
            path.unlink()
    removed_labels: list[str] = []
    for path in LABELS.glob("V*.json"):
        if re.match(r"^V\d+_.+\.json$", path.name):
            removed_labels.append(path.name)
            path.unlink()
    return {"root": sorted(removed_root), "labels": sorted(removed_labels)}


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    years = pd.to_numeric(df["fiscal_year"], errors="coerce")
    for year in YEARS:
        year_df = df.loc[years.eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_journal() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = set(pd.read_csv(path, nrows=0).columns)
        cols = [column for column in L2_COLUMNS if column in header]
        parse_dates = [column for column in ["posting_date", "document_date"] if column in cols]
        frame = pd.read_csv(path, usecols=cols, parse_dates=parse_dates, low_memory=False)
        for column in L2_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[L2_COLUMNS].copy()
        frame["fiscal_year"] = frame["fiscal_year"].fillna(year)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True, sort=False)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries.csv").resolve())
    for column in ("debit_amount", "credit_amount"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
    return rows


def _pair_key(left: object, right: object) -> str:
    values = sorted([str(left), str(right)])
    return f"{values[0]}::{values[1]}"


def _confirmed_duplicate_group_map() -> dict[str, str]:
    path = LABELS / "duplicate_payment_pairs.csv"
    if not path.exists():
        return {}
    pairs = pd.read_csv(path, low_memory=False)
    if not {"original_document_id", "duplicate_document_id", "duplicate_payment_pair_id"}.issubset(pairs.columns):
        return {}
    pairs["pair_key"] = [
        _pair_key(left, right)
        for left, right in zip(pairs["original_document_id"], pairs["duplicate_document_id"], strict=False)
    ]
    pairs["duplicate_group_id"] = pairs["duplicate_payment_pair_id"].astype(str)
    _write_family("duplicate_payment_pairs", pairs)
    return dict(zip(pairs["pair_key"].astype(str), pairs["duplicate_group_id"].astype(str), strict=False))


def _build_l202(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    settings = get_settings()
    result = b04_duplicate_payment(rows, window_days=settings.duplicate_payment_window_days)
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0)
    work = rows.loc[mask].copy()
    work["_l202_score"] = scores.loc[work.index].astype(float)
    for target, key in [
        ("_reason_code", "reason_code"),
        ("_confidence_band", "confidence_band"),
        ("_matched_document_id", "matched_document_id"),
        ("_partner_key", "partner_key"),
        ("_reference_norm", "reference_norm"),
        ("_matched_reference_norm", "matched_reference_norm"),
        ("_amount", "amount"),
        ("_matched_amount", "matched_amount"),
        ("_day_gap", "day_gap"),
    ]:
        work[target] = work.index.map(lambda idx, k=key: annotations.get(int(idx), {}).get(k, ""))

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
        l202_score=("_l202_score", "max"),
        reason_code=("_reason_code", _first_non_null),
        confidence_band=("_confidence_band", _first_non_null),
        matched_document_id=("_matched_document_id", _first_non_null),
        partner_key=("_partner_key", _first_non_null),
        reference_norm=("_reference_norm", _first_non_null),
        matched_reference_norm=("_matched_reference_norm", _first_non_null),
        amount=("_amount", _first_non_null),
        matched_amount=("_matched_amount", _first_non_null),
        day_gap=("_day_gap", _first_non_null),
    ).reset_index()
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["pair_key"] = [
        _pair_key(left, right)
        for left, right in zip(grouped["document_id"], grouped["matched_document_id"], strict=False)
    ]
    grouped["duplicate_pair_key"] = grouped["pair_key"]
    group_map = _confirmed_duplicate_group_map()
    grouped["duplicate_group_id"] = grouped["pair_key"].map(group_map).fillna("")
    grouped["pair_evaluation_unit"] = "pair_key"
    grouped["a_axis_pair_truth"] = True
    grouped["case_id"] = [f"L202-{int(year)}-{idx + 1:05d}" for idx, year in enumerate(grouped["fiscal_year"].tolist())]
    grouped["rule_id"] = "L2-02"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "duplicate-payment detector pair universe"
    grouped["evaluation_unit"] = "pair_key"
    grouped["truth_derivation"] = "src.detection.fraud_rules_groupby.b04_duplicate_payment current detector output"
    grouped["source_candidate"] = "v126"
    grouped["truth_contract_version"] = "v126_active_candidate_contract"
    grouped["evaluation_policy"] = "Phase1 L2-02 A-axis evaluates stable duplicate-payment pair_key universe."
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
        "l202_score",
        "reason_code",
        "confidence_band",
        "matched_document_id",
        "pair_key",
        "duplicate_pair_key",
        "duplicate_group_id",
        "pair_evaluation_unit",
        "a_axis_pair_truth",
        "partner_key",
        "reference_norm",
        "matched_reference_norm",
        "amount",
        "matched_amount",
        "day_gap",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "truth_contract_version",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), result.attrs.get("breakdown", {})


def _classify_l203_reason(row: pd.Series) -> str:
    reason = str(row.get("reason_code", "") or "").strip().lower()
    matched = str(row.get("matched_reason_codes", "") or "").strip().lower()
    queue = str(row.get("queue_label", "") or "").strip().lower()
    process = str(row.get("business_process", "") or "").strip().upper()
    doc_type = str(row.get("document_type", "") or "").strip().upper()
    source = str(row.get("source", "") or "").strip().lower()
    text = "|".join([reason, matched, queue])
    if "split" in text:
        return "ic_split_duplicate" if process in {"R2R", "TRE"} or doc_type == "IC" else "split_duplicate"
    if process == "O2C" and source in {"automated", "recurring", "interface", "batch", "system"}:
        return "o2c_offset_duplicate"
    if "exact" in text or "reference" in text:
        return "exact_duplicate"
    if "near" in text:
        return "near_duplicate"
    if process in {"R2R", "TRE"} and doc_type == "IC":
        return "ic_split_duplicate"
    return "near_duplicate"


def _annotate_b05(rows: pd.DataFrame, result: pd.Series) -> pd.DataFrame:
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0).astype(float)
    work = rows.loc[mask].copy()
    work["_score"] = scores.loc[work.index].astype(float)
    for target, key in [
        ("_reason_code", "reason_code"),
        ("_primary_signal", "primary_signal"),
        ("_interpretation_code", "interpretation_code"),
        ("_confidence_band", "confidence_band"),
        ("_queue_label", "queue_label"),
    ]:
        work[target] = work.index.map(lambda idx, k=key: annotations.get(int(idx), {}).get(k, ""))
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
        score=("_score", "max"),
        reason_code=("_reason_code", _first_non_null),
        primary_signal=("_primary_signal", _first_non_null),
        interpretation_code=("_interpretation_code", _first_non_null),
        confidence_band=("_confidence_band", _first_non_null),
        queue_label=("_queue_label", _first_non_null),
        matched_reason_codes=("_matched_reason_codes", _first_non_null),
        trigger_signals=("_trigger_signals", _first_non_null),
    ).reset_index()
    return grouped


def _build_l203(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    settings = get_settings()
    result = b05_duplicate_entry(
        rows,
        amount_tolerance=settings.duplicate_amount_tolerance,
        fuzzy_threshold=settings.duplicate_fuzzy_threshold,
        window_days=settings.duplicate_time_window_days,
        split_window_days=settings.duplicate_split_window_days,
        max_group_size=settings.duplicate_max_group_size,
    )
    grouped = _annotate_b05(rows, result)
    existing = set(grouped["document_id"].astype(str)) if not grouped.empty else set()

    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["reason_code"] = grouped.apply(_classify_l203_reason, axis=1)
    grouped["l203_reason_code"] = grouped["reason_code"]
    grouped["reason_code_version"] = "v126_l203_current_contract_reason_codes"
    grouped["case_id"] = [f"L203-{int(year)}-{idx + 1:05d}" for idx, year in enumerate(grouped["fiscal_year"].tolist())]
    grouped["rule_id"] = "L2-03"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "duplicate-entry current detector contract universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "b05_duplicate_entry current A-axis evaluator output"
    grouped["source_candidate"] = "v126"
    grouped["truth_contract_version"] = "v126_active_candidate_contract"
    grouped["evaluation_policy"] = "Phase1 L2-03 A-axis uses the current duplicate-entry detector contract universe."
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
        "l203_reason_code",
        "reason_code_version",
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
        "truth_contract_version",
        "evaluation_policy",
    ]
    for column in columns:
        if column not in grouped.columns:
            grouped[column] = ""
    stats = {
        "b05_docs": int(len(existing)),
        "duplicate_detector_docs": 0,
        "added_from_duplicate_detector": 0,
        "excluded_duplicate_detector_docs_reason": "DuplicateDetector subrule universe is not the current L2-03 A-axis evaluator contract.",
        "breakdown": result.attrs.get("breakdown", {}),
    }
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), stats


def _annotate_l205(rows: pd.DataFrame, result: pd.Series) -> pd.DataFrame:
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0).astype(float)
    work = rows.loc[mask].copy()
    work["_score"] = scores.loc[work.index].astype(float)
    for target, key in [
        ("_primary_signal", "primary_signal"),
        ("_interpretation_code", "interpretation_code"),
        ("_confidence_band", "confidence_band"),
        ("_queue_label", "queue_label"),
    ]:
        work[target] = work.index.map(lambda idx, k=key: annotations.get(int(idx), {}).get(k, ""))
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
        score=("_score", "max"),
        primary_signal=("_primary_signal", _first_non_null),
        interpretation_code=("_interpretation_code", _first_non_null),
        confidence_band=("_confidence_band", _first_non_null),
        queue_label=("_queue_label", _first_non_null),
        trigger_signals=("_trigger_signals", _first_non_null),
    ).reset_index()
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["case_id"] = [f"L205-{int(year)}-{idx + 1:05d}" for idx, year in enumerate(grouped["fiscal_year"].tolist())]
    grouped["rule_id"] = "L2-05"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "reversal-pattern raw detector contract universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.anomaly_rules_reversal.c11_reversal_entry current detector output"
    grouped["source_candidate"] = "v126"
    grouped["truth_contract_version"] = "v126_active_candidate_contract"
    grouped["evaluation_policy"] = "Phase1 L2-05 A-axis uses raw reversal review universe; strict/weak sidecars are downstream context."
    strict_mask = grouped["interpretation_code"].astype(str).eq("high_confidence_reversal")
    grouped["l205_truth_bucket"] = strict_mask.map({True: "strict_reversal_truth", False: "raw_reversal_review_only"})
    return grouped.sort_values(["fiscal_year", "document_id"]).reset_index(drop=True)


def _build_l205(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    settings = get_settings()
    result = c11_reversal_entry(
        rows,
        match_window_days=settings.reversal_match_window_days,
        rolling_window_days=settings.reversal_rolling_window_days,
        zero_threshold=settings.reversal_zero_threshold,
        score_threshold=settings.reversal_score_threshold,
    )
    raw = _annotate_l205(rows, result)
    strict = raw.loc[raw["l205_truth_bucket"].eq("strict_reversal_truth")].copy()
    weak = raw.loc[raw["l205_truth_bucket"].eq("raw_reversal_review_only")].copy()
    strict["truth_layer"] = "strict_context"
    weak["truth_layer"] = "raw_review_context"
    stats = {
        "raw_docs": int(len(raw)),
        "strict_docs": int(len(strict)),
        "weak_docs": int(len(weak)),
        "breakdown": result.attrs.get("breakdown", {}),
    }
    return raw, strict, weak, stats


def _replace_combined_rule_truth(replacements: dict[str, pd.DataFrame]) -> int:
    frames: list[pd.DataFrame] = []
    replace_ids = set(replacements)
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        rule_id = path.stem.removeprefix("rule_truth_").replace("_", "-")
        frames.append(replacements[rule_id] if rule_id in replace_ids else pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return int(len(combined))


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        for column in ("source_candidate", "truth_contract_version"):
            if column in df.columns:
                df = df.drop(columns=[column])
        df["source_candidate"] = "v126"
        df["truth_contract_version"] = "v126_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            years = pd.to_numeric(df["fiscal_year"], errors="coerce")
            for year in YEARS:
                year_df = df.loc[years.eq(year)].copy()
                year_df.to_csv(LABELS / f"{path.stem}_{year}.csv", index=False)
                _write_json_records(LABELS / f"{path.stem}_{year}.json", year_df)
    return count


def _write_manifest(summary: dict[str, Any]) -> None:
    (DEST / "V126_L2_CONTRACT_TRUTH_REFRESH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V126_CANDIDATE.md").write_text(
        "# DataSynth v126 Candidate\n\n"
        "Base: `datasynth_v125_candidate`.\n\n"
        "Patch: rebuild L2-02/L2-03/L2-05 rule truth from current contract detector outputs. "
        "This restores A-axis contract truth while keeping strict/weak sidecars for downstream analysis.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    cleanup = _cleanup_version_files()
    rows = _load_journal()
    l202, l202_stats = _build_l202(rows)
    l203, l203_stats = _build_l203(rows)
    l205, l205_strict, l205_weak, l205_stats = _build_l205(rows)

    _write_family("rule_truth_L2_02", l202)
    _write_family("duplicate_payment_review_population", l202)
    _write_family("rule_truth_L2_03", l203)
    _write_family("duplicate_entry_review_population", l203)
    _write_family("rule_truth_L2_05", l205)
    _write_family("reversal_entry_review_population", l205)
    _write_family("reversal_pattern_raw_review_universe", l205)
    _write_family("reversal_strict_truth", l205_strict)
    _write_family("reversal_weak_review_population", l205_weak)

    combined_rows = _replace_combined_rule_truth({"L2-02": l202, "L2-03": l203, "L2-05": l205})
    normalized = _normalize_rule_truth_metadata()
    summary = {
        "version": "v126_candidate",
        "base_version": "v125_candidate",
        "journal_rows_mutated": 0,
        "cleanup": cleanup,
        "l202": {
            **l202_stats,
            "truth_docs": int(l202["document_id"].nunique()),
            "pair_keys": int(l202["pair_key"].nunique()),
            "confirmed_pair_group_rows": int(l202["duplicate_group_id"].astype(str).ne("").sum()),
        },
        "l203": {
            **l203_stats,
            "truth_docs": int(l203["document_id"].nunique()),
            "reason_counts": {str(k): int(v) for k, v in l203["reason_code"].value_counts().sort_index().items()},
        },
        "l205": l205_stats,
        "rule_truth_metadata_normalized_files": normalized,
        "combined_rule_truth_rows": combined_rows,
    }
    _write_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
