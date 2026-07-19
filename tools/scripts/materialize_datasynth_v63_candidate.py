"""Materialize DataSynth v63 candidate from the SoD contract manifest."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v62_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v63_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v63_patch_manifest"
YEARS = (2022, 2023, 2024)


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _copy_manifests() -> None:
    target = TARGET_DIR / "patch_manifest"
    target.mkdir(exist_ok=True)
    for path in MANIFEST_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, target / path.name)


def _read_patch_docs() -> set[str]:
    path = MANIFEST_DIR / "journal_sod_patch_manifest.csv"
    if not path.exists() or path.stat().st_size == 0:
        return set()
    return set(pd.read_csv(path, dtype=str)["document_id"].astype(str))


def _patch_year_file(year: int, patch_docs: set[str]) -> None:
    path = TARGET_DIR / f"journal_entries_{year}.csv"
    tmp = TARGET_DIR / f"journal_entries_{year}.tmp"
    with path.open("r", newline="", encoding="utf-8") as source, tmp.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            if row["document_id"] in patch_docs:
                row["sod_violation"] = "false"
                row["sod_conflict_type"] = ""
            writer.writerow(row)
    tmp.replace(path)


def _rebuild_combined() -> None:
    combined = TARGET_DIR / "journal_entries.csv"
    tmp = TARGET_DIR / "journal_entries.tmp"
    wrote_header = False
    with tmp.open("w", newline="", encoding="utf-8") as out:
        writer = None
        for year in YEARS:
            with (TARGET_DIR / f"journal_entries_{year}.csv").open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if not wrote_header:
                    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\n")
                    writer.writeheader()
                    wrote_header = True
                assert writer is not None
                for row in reader:
                    writer.writerow(row)
    tmp.replace(combined)


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("sod_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _true_mask(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _validate(patch_docs: set[str]) -> dict[str, Any]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("SegregationOfDutiesViolation"), "document_id"].astype(str))
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        df = pd.read_csv(TARGET_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=["document_id", "fiscal_year", "sod_violation"], low_memory=False)
        frames.append(df.groupby("document_id", as_index=False).agg(fiscal_year=("fiscal_year", "first"), sod_violation=("sod_violation", "first")))
    docs = pd.concat(frames, ignore_index=True)
    sod_docs = set(docs.loc[_true_mask(docs["sod_violation"]), "document_id"].astype(str))
    review = pd.read_csv(TARGET_DIR / "labels" / "sod_review_population.csv", dtype=str)
    confirmed = pd.read_csv(TARGET_DIR / "labels" / "sod_confirmed_anomalies.csv", dtype=str)
    review_docs = set(review["document_id"].astype(str))
    confirmed_docs = set(confirmed["document_id"].astype(str))
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v62_candidate",
        "patched_documents": len(patch_docs),
        "sod_true_docs": len(sod_docs),
        "segregation_label_docs": len(label_docs),
        "sod_missing_label_docs": len(sod_docs - label_docs),
        "label_missing_sod_docs": len(label_docs - sod_docs),
        "review_population_docs": len(review_docs),
        "confirmed_sidecar_docs": len(confirmed_docs),
        "review_confirmed_overlap": len(review_docs & confirmed_docs),
    }
    validation["valid_candidate"] = (
        validation["sod_true_docs"] == validation["segregation_label_docs"]
        and validation["sod_missing_label_docs"] == 0
        and validation["label_missing_sod_docs"] == 0
        and validation["confirmed_sidecar_docs"] == validation["segregation_label_docs"]
        and validation["review_confirmed_overlap"] == 0
    )
    return validation


def _write_docs(validation: dict[str, Any]) -> None:
    text = f"""# DataSynth v63 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v63
source_baseline: data/journal/primary/datasynth_v62_candidate
included_manifests:
  - patch_manifest/journal_sod_patch_manifest.csv
  - patch_manifest/sod_review_population.csv
  - patch_manifest/sod_confirmed_anomalies.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Reserve `sod_violation=True` for strict `SegregationOfDutiesViolation` truth.
- Preserve broad SoD signals in `labels/sod_review_population*`.
- Preserve confirmed SoD positives in `labels/sod_confirmed_anomalies*`.

## Anti-Fitting Position

This patch does not use detector outputs. It separates truth layers so strict L1-06 labels and broad SoD review
population are not evaluated as the same thing.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V63_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_docs = _read_patch_docs()
    for year in YEARS:
        _patch_year_file(year, patch_docs)
    _rebuild_combined()
    _copy_sidecars()
    validation = _validate(patch_docs)
    (TARGET_DIR / "V63_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
