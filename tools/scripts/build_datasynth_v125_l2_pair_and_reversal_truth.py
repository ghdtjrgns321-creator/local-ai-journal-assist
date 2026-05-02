"""Build v125 candidate by tightening selected L2 truth semantics.

Base: datasynth_v124_candidate.

Changes:

- L2-02: add stable duplicate pair keys to rule truth and review population.
- L2-03: keep current sidecar direction but add clearer duplicate reason codes.
- L2-05: split strict reversal truth from the raw reversal review universe.

No journal rows are mutated.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v124_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v125_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V125_CANDIDATE.md", "V125_L2_PAIR_AND_REVERSAL_TRUTH.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V125_L2_PAIR_AND_REVERSAL_TRUTH.json")
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


def _pair_key(left: object, right: object) -> str:
    values = sorted([str(left), str(right)])
    return f"{values[0]}::{values[1]}"


def _add_l202_pair_keys() -> dict[str, Any]:
    stats: dict[str, Any] = {}
    pair_map: dict[str, str] = {}
    pair_path = LABELS / "duplicate_payment_pairs.csv"
    if pair_path.exists():
        pairs = pd.read_csv(pair_path, low_memory=False)
        if {"original_document_id", "duplicate_document_id", "duplicate_payment_pair_id"}.issubset(pairs.columns):
            pairs["pair_key"] = [
                _pair_key(left, right)
                for left, right in zip(pairs["original_document_id"], pairs["duplicate_document_id"], strict=False)
            ]
            pairs["duplicate_group_id"] = pairs["duplicate_payment_pair_id"].astype(str)
            pair_map = dict(zip(pairs["pair_key"].astype(str), pairs["duplicate_group_id"].astype(str), strict=False))
            _write_family("duplicate_payment_pairs", pairs)
            stats["duplicate_payment_pairs"] = {
                "rows": int(len(pairs)),
                "pair_key_count": int(pairs["pair_key"].nunique()),
            }

    for stem in ["rule_truth_L2_02", "duplicate_payment_review_population"]:
        path = LABELS / f"{stem}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, low_memory=False)
        if {"document_id", "matched_document_id"}.issubset(df.columns):
            df["pair_key"] = [
                _pair_key(left, right)
                for left, right in zip(df["document_id"], df["matched_document_id"], strict=False)
            ]
            df["duplicate_pair_key"] = df["pair_key"]
            df["duplicate_group_id"] = df["pair_key"].map(pair_map).fillna("")
            df["pair_evaluation_unit"] = "pair_key"
            df["a_axis_pair_truth"] = True
        df["source_candidate"] = "v125"
        df["truth_contract_version"] = "v125_active_candidate_contract"
        _write_family(stem, df)
        stats[stem] = {
            "rows": int(len(df)),
            "pair_keys": int(df["pair_key"].nunique()) if "pair_key" in df.columns else 0,
            "confirmed_pair_keys": int(df["duplicate_group_id"].astype(str).ne("").sum())
            if "duplicate_group_id" in df.columns
            else 0,
        }
    return stats


def _classify_l203_reason(row: pd.Series) -> str:
    reason = str(row.get("reason_code", "") or "").strip().lower()
    matched = str(row.get("matched_reason_codes", "") or "").strip().lower()
    queue = str(row.get("queue_label", "") or "").strip().lower()
    process = str(row.get("business_process", "") or "").strip().upper()
    doc_type = str(row.get("document_type", "") or "").strip().upper()
    source = str(row.get("source", "") or "").strip().lower()
    text = "|".join([reason, matched, queue])

    if "split" in text:
        if process in {"R2R", "TRE"} or doc_type == "IC":
            return "ic_split_duplicate"
        return "split_duplicate"
    if process == "O2C" and source in {"automated", "recurring", "interface", "batch", "system"}:
        return "o2c_offset_duplicate"
    if "exact" in text or "reference" in text:
        return "exact_duplicate"
    if "near" in text:
        return "near_duplicate"
    if process in {"R2R", "TRE"} and doc_type == "IC":
        return "ic_split_duplicate"
    return "near_duplicate"


def _patch_l203_reason_codes() -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for stem in [
        "rule_truth_L2_03",
        "duplicate_entry_review_population",
        "duplicate_entry_confirmed_scenarios",
        "duplicate_entry_negative_controls",
    ]:
        path = LABELS / f"{stem}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, low_memory=False)
        df["l203_reason_code"] = df.apply(_classify_l203_reason, axis=1)
        if stem.startswith("rule_truth") or stem.endswith("review_population"):
            df["reason_code"] = df["l203_reason_code"]
            df["reason_code_version"] = "v125_l203_clear_reason_codes"
        df["source_candidate"] = "v125"
        if stem.startswith("rule_truth"):
            df["truth_contract_version"] = "v125_active_candidate_contract"
        _write_family(stem, df)
        stats[stem] = {
            "rows": int(len(df)),
            "reason_counts": {
                str(k): int(v) for k, v in df["l203_reason_code"].value_counts().sort_index().items()
            },
        }
    return stats


def _is_strict_l205(row: pd.Series) -> bool:
    interpretation = str(row.get("interpretation_code", "") or "").strip()
    primary = str(row.get("primary_signal", "") or "").strip()
    triggers = str(row.get("trigger_signals", "") or "")
    score = pd.to_numeric(pd.Series([row.get("score")]), errors="coerce").iloc[0]
    high_confidence = interpretation == "high_confidence_reversal"
    structural_signal = primary in {"S0", "S1", "S2b"} or any(signal in triggers.split("|") for signal in ["S0", "S1", "S2b"])
    return bool(high_confidence or (structural_signal and pd.notna(score) and float(score) >= 0.30))


def _split_l205_truth() -> dict[str, Any]:
    path = LABELS / "rule_truth_L2_05.csv"
    raw = pd.read_csv(path, low_memory=False)
    raw["source_candidate"] = "v125"
    raw["truth_contract_version"] = "v125_active_candidate_contract"
    raw["truth_layer"] = "raw_review_universe"
    raw["truth_basis"] = "reversal-pattern raw review universe"
    raw["sidecar_role"] = "review_population"
    raw["sidecar_purpose"] = "raw_reversal_review_universe"
    raw["expected_detector_positive"] = "true"
    raw["allowed_for_independent_sidecar_eval"] = False
    raw["a_axis_truth"] = raw.apply(_is_strict_l205, axis=1)
    raw["l205_truth_bucket"] = raw["a_axis_truth"].map({True: "strict_reversal_truth", False: "raw_reversal_review_only"})
    _write_family("reversal_entry_review_population", raw)
    _write_family("reversal_pattern_raw_review_universe", raw)

    strict = raw.loc[raw["a_axis_truth"].astype(bool)].copy()
    strict["truth_layer"] = "rule_truth"
    strict["truth_basis"] = "strict reversal match: ERP link, one-to-one opposite-sign pair, or line-swap reversal signature"
    strict["sidecar_role"] = "strict_truth_alias"
    strict["sidecar_purpose"] = "detector_contract_strict_reversal_truth"
    strict["evaluation_policy"] = (
        "Phase1 A-axis strict reversal truth. Weak reversal-like clearing/reclass candidates "
        "remain in reversal_entry_review_population for B-axis review."
    )
    _write_family("rule_truth_L2_05", strict)
    _write_family("reversal_strict_truth", strict)

    weak = raw.loc[~raw["a_axis_truth"].astype(bool)].copy()
    _write_family("reversal_weak_review_population", weak)

    return {
        "previous_rule_truth_docs": int(len(raw)),
        "strict_rule_truth_docs": int(len(strict)),
        "raw_review_universe_docs": int(len(raw)),
        "weak_review_only_docs": int(len(weak)),
        "strict_by_year": {
            str(int(k)): int(v)
            for k, v in pd.to_numeric(strict["fiscal_year"], errors="coerce")
            .dropna()
            .astype(int)
            .value_counts()
            .sort_index()
            .items()
        },
        "raw_queue_counts": {
            str(k): int(v) for k, v in raw.get("queue_label", pd.Series(dtype=str)).fillna("").astype(str).value_counts().sort_index().items()
        },
        "strict_signal_counts": {
            str(k): int(v) for k, v in strict.get("primary_signal", pd.Series(dtype=str)).fillna("").astype(str).value_counts().sort_index().items()
        },
    }


def _replace_combined_rule_truth() -> int:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
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
        df["source_candidate"] = "v125"
        df["truth_contract_version"] = "v125_active_candidate_contract"
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


def _update_sidecar_manifest() -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    if not path.exists():
        return {"manifest_rows": 0}
    manifest = pd.read_csv(path, low_memory=False)
    manifest["source_candidate"] = "v125"
    additions = [
        {
            "sidecar_name": "reversal_strict_truth",
            "owner_rule": "L2-05",
            "sidecar_role": "strict_truth_alias",
            "sidecar_purpose": "detector_contract_strict_reversal_truth",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": False,
            "source_candidate": "v125",
        },
        {
            "sidecar_name": "reversal_entry_review_population",
            "owner_rule": "L2-05",
            "sidecar_role": "review_population",
            "sidecar_purpose": "raw_reversal_review_universe",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": False,
            "source_candidate": "v125",
        },
        {
            "sidecar_name": "reversal_weak_review_population",
            "owner_rule": "L2-05",
            "sidecar_role": "review_population",
            "sidecar_purpose": "weak_reversal_review_only",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": False,
            "source_candidate": "v125",
        },
    ]
    if "sidecar_name" in manifest.columns:
        manifest = manifest.loc[
            ~manifest["sidecar_name"].astype(str).isin({item["sidecar_name"] for item in additions})
        ].copy()
    manifest = pd.concat([manifest, pd.DataFrame(additions)], ignore_index=True, sort=False)
    manifest.to_csv(path, index=False)
    _write_json_records(path.with_suffix(".json"), manifest)
    return {"manifest_rows": int(len(manifest))}


def _write_manifest(summary: dict[str, Any]) -> None:
    (DEST / "V125_L2_PAIR_AND_REVERSAL_TRUTH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V125_CANDIDATE.md").write_text(
        "# DataSynth v125 Candidate\n\n"
        "Base: `datasynth_v124_candidate`.\n\n"
        "Patch: add L2-02 pair keys, clarify L2-03 reason codes, and split L2-05 "
        "strict A-axis reversal truth from raw reversal review universe.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    cleanup = _cleanup_version_files()
    l202 = _add_l202_pair_keys()
    l203 = _patch_l203_reason_codes()
    l205 = _split_l205_truth()
    normalized = _normalize_rule_truth_metadata()
    combined_rows = _replace_combined_rule_truth()
    sidecar_manifest = _update_sidecar_manifest()
    summary: dict[str, Any] = {
        "version": "v125_candidate",
        "base_version": "v124_candidate",
        "journal_rows_mutated": 0,
        "cleanup": cleanup,
        "l202_pair_keys": l202,
        "l203_reason_codes": l203,
        "l205_split": l205,
        "rule_truth_metadata_normalized_files": normalized,
        "combined_rule_truth_rows": combined_rows,
        "sidecar_manifest": sidecar_manifest,
    }
    _write_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
