"""Build v122 candidate by regenerating year journal files from combined journal.

Problem:

The v121 candidate contains two journal representations:

- journal_entries.csv
- journal_entries_2022.csv / journal_entries_2023.csv / journal_entries_2024.csv

They have identical row keys but some field values differ. Phase 1 evaluators
often read the year files, so stale year files can disagree with rule-truth
sidecars produced from the combined journal.

This patch makes the year CSV/JSON files deterministic partitions of the
combined journal. Labels and rule-truth membership are not changed.
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
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v121_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v122_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V122_CANDIDATE.md", "V122_YEAR_FILE_CONSISTENCY.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V122_YEAR_FILE_CONSISTENCY.json")
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


def _compare_year_file(year: int, combined_year: pd.DataFrame, year_df: pd.DataFrame) -> dict[str, Any]:
    key_cols = ["document_id", "line_number"] if "line_number" in combined_year.columns else [
        "document_id",
        "gl_account",
        "debit_amount",
        "credit_amount",
    ]
    fields = [
        col
        for col in [
            "fiscal_period",
            "posting_date",
            "document_date",
            "company_code",
            "gl_account",
            "debit_amount",
            "credit_amount",
            "approved_by",
            "approval_date",
            "source",
        ]
        if col in combined_year.columns and col in year_df.columns
    ]
    merged = combined_year[key_cols + fields].merge(
        year_df[key_cols + fields],
        on=key_cols,
        how="outer",
        suffixes=("_combined", "_year"),
        indicator=True,
    )
    mismatches: dict[str, int] = {}
    both = merged["_merge"].eq("both")
    for field in fields:
        left = merged[f"{field}_combined"].fillna("__NA__").astype(str)
        right = merged[f"{field}_year"].fillna("__NA__").astype(str)
        count = int((both & left.ne(right)).sum())
        if count:
            mismatches[field] = count
    return {
        "rows_combined_partition": int(len(combined_year)),
        "rows_year_file_before": int(len(year_df)),
        "docs_combined_partition": int(combined_year["document_id"].nunique()),
        "docs_year_file_before": int(year_df["document_id"].nunique()),
        "merge_status_before": {str(k): int(v) for k, v in merged["_merge"].value_counts().to_dict().items()},
        "field_mismatches_before": mismatches,
    }


def _regenerate_year_files() -> dict[str, Any]:
    combined = pd.read_csv(DEST / "journal_entries.csv", low_memory=False)
    stats: dict[str, Any] = {}
    for year in YEARS:
        year_file = DEST / f"journal_entries_{year}.csv"
        old_year = pd.read_csv(year_file, low_memory=False)
        year_df = combined.loc[pd.to_numeric(combined["fiscal_year"], errors="coerce").eq(year)].copy()
        stats[str(year)] = _compare_year_file(year, year_df, old_year)
        year_df.to_csv(year_file, index=False)
        _write_json_records(DEST / f"journal_entries_{year}.json", year_df)
        reread = pd.read_csv(year_file, low_memory=False)
        after = _compare_year_file(year, year_df, reread)
        stats[str(year)]["field_mismatches_after"] = after["field_mismatches_before"]
        stats[str(year)]["rows_year_file_after"] = int(len(reread))
        stats[str(year)]["docs_year_file_after"] = int(reread["document_id"].nunique())
    return stats


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        df = df.drop(columns=[col for col in ["source_candidate", "truth_contract_version"] if col in df.columns])
        df["source_candidate"] = "v122"
        df["truth_contract_version"] = "v122_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            for year in YEARS:
                year_path = LABELS / f"{path.stem}_{year}.csv"
                if year_path.exists():
                    year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
                    year_df.to_csv(year_path, index=False)
                    _write_json_records(year_path.with_suffix(".json"), year_df)
    return count


def _rebuild_combined_rule_truth() -> dict[str, int]:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return {str(rule): int(count) for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()}


def _update_manifest_source() -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    if not path.exists():
        return {"manifest_rows": 0}
    manifest = pd.read_csv(path, low_memory=False)
    manifest["source_candidate"] = "v122"
    manifest.to_csv(path, index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)
    return {"manifest_rows": int(len(manifest))}


def _legacy_source_count() -> int:
    bad = {}
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda c: c == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v122"]:
            bad[path.name] = values
    if bad:
        raise SystemExit(f"legacy rule_truth source metadata remains: {bad}")
    return 0


def main() -> int:
    _copy_candidate_fast()
    removed_before = _cleanup_version_files()
    year_stats = _regenerate_year_files()
    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    manifest_stats = _update_manifest_source()
    legacy_sources = _legacy_source_count()
    removed_after = _cleanup_version_files()

    summary = {
        "candidate_version": "v122",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "regenerate journal_entries_YYYY files from journal_entries.csv; no label membership changed",
        "year_file_consistency": year_stats,
        "sidecar_manifest": manifest_stats,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_sources,
        "removed_copied_version_manifests": removed_before,
        "removed_copied_version_manifests_after_write": removed_after,
        "rule_counts": rule_counts,
    }
    (DEST / "V122_YEAR_FILE_CONSISTENCY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V122_CANDIDATE.md").write_text(
        "# DataSynth v122 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: year journal file consistency cleanup. Year CSV/JSON files are regenerated as partitions of the combined journal.\n\n"
        "No journal combined file, anomaly-label membership, or rule-truth membership changed.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
