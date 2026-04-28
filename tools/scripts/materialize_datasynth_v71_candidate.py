"""Materialize DataSynth v71 candidate from L1-01 truth manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v70_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v71_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v71_patch_manifest"


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


def _copy_truth_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("l101_unbalanced_truth*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _validate() -> dict[str, object]:
    truth = pd.read_csv(TARGET_DIR / "labels" / "l101_unbalanced_truth.csv", dtype=str)
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v70_candidate",
        "anomaly_labels_truth_semantics": "audit_issue_truth",
        "l101_unbalanced_truth_docs": int(truth["document_id"].nunique()),
        "unbalanced_entry_causal_labels": int(labels["anomaly_type"].eq("UnbalancedEntry").sum()),
        "truth_by_year": truth["fiscal_year"].value_counts().sort_index().to_dict(),
        "target_total_labels_preserved": int(len(labels)),
    }
    validation["valid_candidate"] = validation["l101_unbalanced_truth_docs"] > 0
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v71 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v71
source_baseline: data/journal/primary/datasynth_v70_candidate
included_manifests:
  - v70 audit issue truth split
  - patch_manifest/l101_unbalanced_truth.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- L1-01 truth is now `labels/l101_unbalanced_truth.csv`.
- Causal labels such as `DecimalError`, `RoundingError`, `CurrencyError`, `TransposedDigits`, and `ReversedAmount` remain in `anomaly_labels.csv`.
- `UnbalancedEntry` remains a causal scenario label, not the exhaustive L1-01 truth.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V71_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    _copy_truth_sidecars()
    validation = _validate()
    (TARGET_DIR / "V71_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
