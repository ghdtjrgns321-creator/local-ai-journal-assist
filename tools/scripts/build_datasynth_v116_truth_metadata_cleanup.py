"""Build v116 candidate by removing legacy source-candidate metadata.

v115 fixed L2-03/L2-04/L2-05 stale truth. This patch removes old
`source_candidate=vXX` values from active rule-truth files so the active
candidate no longer carries previous patch-version criteria as truth metadata.

This does not change journal rows or truth membership. It is a metadata cleanup
for the active candidate contract.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v115_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v116_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V116_TRUTH_METADATA_CLEANUP.json")
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


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_truth_file(path: Path) -> dict[str, object]:
    df = pd.read_csv(path, low_memory=False)
    before = sorted(df.get("source_candidate", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
    if "source_candidate" in df.columns:
        df = df.drop(columns=["source_candidate"])
    if "legacy_source_candidate" in df.columns:
        df = df.drop(columns=["legacy_source_candidate"])
    df["source_candidate"] = "v116"
    df["truth_contract_version"] = "v116_active_candidate_contract"
    df.to_csv(path, index=False)
    _write_json_records(path.with_suffix(".json"), df)
    return {
        "file": path.name,
        "rows": int(len(df)),
        "previous_source_candidate": before,
        "new_source_candidate": ["v116"],
    }


def _normalize_all_rule_truth() -> list[dict[str, object]]:
    changes = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if YEAR_SUFFIX_RE.search(stem):
            continue
        changes.append(_normalize_truth_file(path))

        rule_stem = stem
        yearless = pd.read_csv(path, low_memory=False)
        if "fiscal_year" not in yearless.columns:
            continue
        for year in YEARS:
            year_path = LABELS / f"{rule_stem}_{year}.csv"
            if not year_path.exists():
                continue
            year_df = yearless.loc[pd.to_numeric(yearless["fiscal_year"], errors="coerce").eq(year)].copy()
            year_df.to_csv(year_path, index=False)
            _write_json_records(year_path.with_suffix(".json"), year_df)
    return changes


def _rebuild_combined_rule_truth() -> dict[str, int]:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if YEAR_SUFFIX_RE.search(stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    if "rule_id" not in combined.columns:
        return {}
    return {
        str(rule): int(count)
        for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
    }


def _remaining_legacy_sources() -> dict[str, list[str]]:
    remaining = {}
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if YEAR_SUFFIX_RE.search(stem):
            continue
        df = pd.read_csv(path, usecols=lambda column: column == "source_candidate", low_memory=False)
        if "source_candidate" not in df.columns:
            remaining[path.name] = ["missing"]
            continue
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        legacy = [value for value in values if value != "v116"]
        if legacy:
            remaining[path.name] = legacy
    return remaining


def main() -> int:
    _copy_candidate_fast()
    changes = _normalize_all_rule_truth()
    counts = _rebuild_combined_rule_truth()
    remaining = _remaining_legacy_sources()
    if remaining:
        raise SystemExit(f"legacy source_candidate remains: {remaining}")

    summary = {
        "candidate_version": "v116",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "remove old source_candidate values from active rule_truth files",
        "normalized_files": changes,
        "rule_counts": counts,
        "remaining_legacy_source_candidates": remaining,
        "note": (
            "Truth membership is unchanged from v115. This patch removes active "
            "truth metadata that pointed at old patch versions."
        ),
    }
    (DEST / "V116_TRUTH_METADATA_CLEANUP.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V116_CANDIDATE.md").write_text(
        "# DataSynth v116 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: active rule-truth metadata cleanup. No journal rows changed.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
