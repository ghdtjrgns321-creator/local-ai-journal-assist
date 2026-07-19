"""Materialize DataSynth v66 candidate from the L1-07 cleanup manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v65_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v66_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v66_patch_manifest"


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


def _write_label_files(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": int(len(labels)),
        "by_anomaly_type": labels["anomaly_type"].value_counts().to_dict(),
        "by_category": labels["anomaly_category"].value_counts().to_dict() if "anomaly_category" in labels else {},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _patch_labels() -> dict[str, int]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    remove_manifest = pd.read_csv(MANIFEST_DIR / "skipped_approval_remove_label_manifest.csv", dtype=str)
    remove_docs = set(remove_manifest["document_id"].dropna().astype(str)) if not remove_manifest.empty else set()
    before = int(labels["anomaly_type"].eq("SkippedApproval").sum())
    if remove_docs:
        labels = labels.loc[
            ~(labels["anomaly_type"].eq("SkippedApproval") & labels["document_id"].astype(str).isin(remove_docs))
        ].copy()
    _write_label_files(labels)
    after = int(labels["anomaly_type"].eq("SkippedApproval").sum())
    return {"removed": before - after, "added": 0, "total_skipped_approval": after}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("skipped_approval_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _validate(patch_counts: dict[str, int]) -> dict[str, object]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].dropna().astype(str))
    confirmed = pd.read_csv(TARGET_DIR / "labels" / "skipped_approval_confirmed_anomalies.csv", dtype=str)
    confirmed_docs = set(confirmed["document_id"].dropna().astype(str))
    wrong_period = labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].nunique()
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v65_candidate",
        "included_prior_candidate": "data/journal/primary/datasynth_v65_candidate",
        "skipped_label_docs": len(label_docs),
        "confirmed_sidecar_docs": len(confirmed_docs),
        "label_sidecar_mismatch": len(label_docs.symmetric_difference(confirmed_docs)),
        "wrong_period_label_docs_preserved": int(wrong_period),
        "label_patch_counts": patch_counts,
    }
    validation["valid_candidate"] = (
        validation["label_sidecar_mismatch"] == 0 and validation["wrong_period_label_docs_preserved"] == 731
    )
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v66 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v66
source_baseline: data/journal/primary/datasynth_v65_candidate
included_manifests:
  - v65 patch_manifest/wrong_period_label_manifest.csv
  - v65 patch_manifest/wrong_period_confirmed_anomalies.csv
  - v65 patch_manifest/wrong_period_normal_controls.csv
  - patch_manifest/skipped_approval_remove_label_manifest.csv
  - patch_manifest/skipped_approval_confirmed_anomalies.csv
  - patch_manifest/skipped_approval_normal_controls.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Preserve v65 L1-08 `WrongPeriod` repair.
- Clean up L1-07 `SkippedApproval` confirmed truth.
- Use debit-side document amount for approval-level truth.
- Keep `recurring` missing-approver cases as controls/review context, not confirmed violations.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V66_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _patch_labels()
    _copy_sidecars()
    validation = _validate(patch_counts)
    (TARGET_DIR / "V66_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
