"""Materialize DataSynth v67 candidate from the L1-09 approval-date manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v66_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v67_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v67_patch_manifest"
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


def _apply_manifest() -> dict[str, int]:
    manifest = pd.read_csv(MANIFEST_DIR / "approval_date_fill_manifest.csv", dtype=str)
    patch_map = dict(zip(manifest["document_id"].astype(str), manifest["new_approval_date"].astype(str), strict=False))
    combined_frames: list[pd.DataFrame] = []
    patched_rows = 0
    patched_docs: set[str] = set()
    for year in YEARS:
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, dtype=str, low_memory=False)
        mask = df["document_id"].astype(str).isin(patch_map)
        if mask.any():
            df.loc[mask, "approval_date"] = df.loc[mask, "document_id"].astype(str).map(patch_map)
            patched_rows += int(mask.sum())
            patched_docs.update(df.loc[mask, "document_id"].astype(str))
        df.to_csv(path, index=False)
        combined_frames.append(df)
    combined = pd.concat(combined_frames, ignore_index=True)
    combined.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    return {"patched_docs": len(patched_docs), "patched_rows": patched_rows}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("approval_date_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _validate(patch_counts: dict[str, int]) -> dict[str, object]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].dropna().astype(str))
    rows = []
    for year in YEARS:
        df = pd.read_csv(
            TARGET_DIR / f"journal_entries_{year}.csv",
            dtype=str,
            usecols=["document_id", "fiscal_year", "approved_by", "approval_date"],
            low_memory=False,
        )
        rows.append(
            df.groupby("document_id", as_index=False).agg(
                fiscal_year=("fiscal_year", "first"),
                approved_by=("approved_by", "first"),
                approval_date=("approval_date", "first"),
            )
        )
    docs = pd.concat(rows, ignore_index=True)
    has_approver = docs["approved_by"].fillna("").astype(str).str.strip().ne("")
    missing_date = docs["approval_date"].fillna("").astype(str).str.strip().eq("")
    actual_docs = set(docs.loc[has_approver & missing_date, "document_id"].astype(str))
    controls = pd.read_csv(TARGET_DIR / "labels" / "approval_date_present_normal_controls.csv", dtype=str)
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v66_candidate",
        "approval_date_missing_label_docs": len(label_docs),
        "actual_missing_approval_date_docs": len(actual_docs),
        "label_actual_mismatch": len(label_docs.symmetric_difference(actual_docs)),
        "normal_control_docs": int(controls["document_id"].nunique()),
        "wrong_period_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].nunique()),
        "skipped_approval_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].nunique()),
        "patch_counts": patch_counts,
    }
    validation["valid_candidate"] = (
        validation["label_actual_mismatch"] == 0
        and validation["wrong_period_label_docs_preserved"] == 731
        and validation["skipped_approval_label_docs_preserved"] == 15
    )
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v67 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v67
source_baseline: data/journal/primary/datasynth_v66_candidate
included_manifests:
  - v65 patch_manifest/wrong_period_label_manifest.csv
  - v66 patch_manifest/skipped_approval_remove_label_manifest.csv
  - patch_manifest/approval_date_fill_manifest.csv
  - patch_manifest/approval_date_present_normal_controls.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Preserve v65 L1-08 `WrongPeriod` repair.
- Preserve v66 L1-07 `SkippedApproval` cleanup.
- Fill `approval_date` on unlabeled documents where `approved_by` exists.
- Keep confirmed `ApprovalDateMissing` labels as the only documents with approver present and approval date missing.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V67_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _apply_manifest()
    _copy_sidecars()
    validation = _validate(patch_counts)
    (TARGET_DIR / "V67_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
