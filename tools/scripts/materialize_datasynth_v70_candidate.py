"""Materialize DataSynth v70 candidate from audit issue truth manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v69_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v70_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v70_patch_manifest"


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
        "truth_semantics": "audit_issue_truth",
        "field_contract_truth_location": "labels/field_contract_truth.csv",
        "by_anomaly_type": labels["anomaly_type"].value_counts().to_dict(),
        "by_category": labels["anomaly_category"].value_counts().to_dict() if "anomaly_category" in labels else {},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_truth_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for stem in ["field_contract_truth", "l1_audit_issue_truth", "l1_field_only_normal_or_review"]:
        for path in MANIFEST_DIR.glob(f"{stem}*"):
            if path.suffix.lower() in {".csv", ".json"}:
                shutil.copy2(path, labels_dir / path.name)


def _validate() -> dict[str, object]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    field = pd.read_csv(TARGET_DIR / "labels" / "field_contract_truth.csv", dtype=str)
    audit = pd.read_csv(TARGET_DIR / "labels" / "l1_audit_issue_truth.csv", dtype=str)
    moved = pd.read_csv(TARGET_DIR / "labels" / "l1_field_only_normal_or_review.csv", dtype=str)
    field_ids = set((field["document_id"].astype(str) + "|" + field["anomaly_type"].astype(str)).dropna())
    split_ids = set((audit["document_id"].astype(str) + "|" + audit["anomaly_type"].astype(str)).dropna()) | set(
        (moved["document_id"].astype(str) + "|" + moved["anomaly_type"].astype(str)).dropna()
    )
    audit_l1_ids = set((audit["document_id"].astype(str) + "|" + audit["anomaly_type"].astype(str)).dropna())
    label_ids = set((labels["document_id"].astype(str) + "|" + labels["anomaly_type"].astype(str)).dropna())
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v69_candidate",
        "anomaly_labels_truth_semantics": "audit_issue_truth",
        "target_total_labels": int(len(labels)),
        "field_contract_truth_rows": int(len(field)),
        "l1_audit_issue_truth_rows": int(len(audit)),
        "l1_field_only_moved_rows": int(len(moved)),
        "field_split_mismatch": len(field_ids.symmetric_difference(split_ids)),
        "audit_l1_missing_from_labels": len(audit_l1_ids - label_ids),
        "moved_l1_still_in_labels": len(
            set((moved["document_id"].astype(str) + "|" + moved["anomaly_type"].astype(str)).dropna()) & label_ids
        ),
        "audit_l1_by_type": audit["anomaly_type"].value_counts().to_dict(),
        "moved_l1_by_type": moved["anomaly_type"].value_counts().to_dict(),
    }
    validation["valid_candidate"] = (
        validation["field_contract_truth_rows"] > 0
        and validation["field_split_mismatch"] == 0
        and validation["audit_l1_missing_from_labels"] == 0
        and validation["moved_l1_still_in_labels"] == 0
    )
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v70 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v70
source_baseline: data/journal/primary/datasynth_v69_candidate
included_manifests:
  - v65 WrongPeriod repair
  - v66 SkippedApproval cleanup
  - v67 ApprovalDateMissing cleanup
  - v68 L1 distribution realism
  - v69 L1 realism controls
  - patch_manifest/anomaly_labels_audit_issue.csv
  - patch_manifest/field_contract_truth.csv
  - patch_manifest/l1_audit_issue_truth.csv
  - patch_manifest/l1_field_only_normal_or_review.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- `labels/anomaly_labels.csv` now represents audit issue truth.
- Exact L1 field-contract truth is preserved in `labels/field_contract_truth.csv`.
- L1 field-only records not considered audit issues are moved to `labels/l1_field_only_normal_or_review.csv`.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V70_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    labels = pd.read_csv(MANIFEST_DIR / "anomaly_labels_audit_issue.csv", dtype=str)
    _write_label_files(labels)
    _copy_truth_sidecars()
    validation = _validate()
    (TARGET_DIR / "V70_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
