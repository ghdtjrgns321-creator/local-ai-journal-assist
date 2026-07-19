"""Materialize DataSynth v62 candidate from the approval-limit manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v61_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v62_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v62_patch_manifest"


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


def _metadata_col(labels: pd.DataFrame) -> str:
    return "metadata_json" if "metadata_json" in labels.columns else "metadata"


def _next_anomaly_id(labels: pd.DataFrame) -> int:
    current = pd.to_numeric(labels["anomaly_id"].astype(str).str.extract(r"(\d+)")[0], errors="coerce").max()
    return int(current) + 1


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
    labels_path = TARGET_DIR / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str)
    manifest = pd.read_csv(MANIFEST_DIR / "approval_limit_label_manifest.csv", dtype=str)
    if manifest.empty:
        return {"added": 0, "total_exceeded_approval_limit": int(labels["anomaly_type"].eq("ExceededApprovalLimit").sum())}
    meta_col = _metadata_col(labels)
    existing_eal = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    next_id = _next_anomaly_id(labels)
    new_rows: list[dict[str, Any]] = []
    for row in manifest.to_dict(orient="records"):
        if str(row["document_id"]) in existing_eal:
            continue
        metadata = str(row["metadata_json"])
        new_row = {col: None for col in labels.columns}
        new_row.update(
            {
                "anomaly_id": f"ANO{next_id:08d}",
                "anomaly_category": "Fraud",
                "anomaly_type": "ExceededApprovalLimit",
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["posting_date"])[:10],
                "detection_timestamp": "2026-04-27 00:00:00",
                "confidence": "0.88",
                "severity": "3",
                "description": (
                    f"L1-04 ExceededApprovalLimit truth: {row['document_number']} amount "
                    f"{int(float(row['document_amount']))} exceeds {row['approved_by']} limit "
                    f"{int(float(row['approval_limit']))}"
                ),
                "is_injected": "True",
                "monetary_impact": str(float(row["excess_amount"])),
                "related_entities": json.dumps([row["document_number"]], ensure_ascii=False),
                "injection_strategy": "ApprovalLimitTruthRepair",
                "structured_strategy_type": "ExceededApprovalLimit",
                "structured_strategy_json": metadata,
                "causal_reason_type": "ApprovalLimitFieldContract",
                "causal_reason_json": metadata,
                "child_anomaly_ids": "[]",
                meta_col: metadata,
            }
        )
        new_rows.append(new_row)
        next_id += 1
    if new_rows:
        labels = pd.concat([labels, pd.DataFrame(new_rows)], ignore_index=True)
    _write_label_files(labels)
    return {"added": len(new_rows), "total_exceeded_approval_limit": int(labels["anomaly_type"].eq("ExceededApprovalLimit").sum())}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("approval_limit_exceeded_population*.csv"):
        shutil.copy2(path, labels_dir / path.name)


def _validate(patch_counts: dict[str, int]) -> dict[str, Any]:
    summary = json.loads((MANIFEST_DIR / "approval_limit_manifest_summary.json").read_text(encoding="utf-8"))
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    eal_docs = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    population = pd.read_csv(TARGET_DIR / "labels" / "approval_limit_exceeded_population.csv", dtype=str)
    population_docs = set(population["document_id"].astype(str))
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v61_candidate",
        "actual_exceeded_docs": int(summary["actual_exceeded_docs"]),
        "eal_label_docs": len(eal_docs),
        "population_docs": len(population_docs),
        "missing_labels_for_actual_exceeded": len(population_docs - eal_docs),
        "label_patch_counts": patch_counts,
    }
    validation["valid_candidate"] = (
        validation["actual_exceeded_docs"] == validation["eal_label_docs"]
        and validation["actual_exceeded_docs"] == validation["population_docs"]
        and validation["missing_labels_for_actual_exceeded"] == 0
    )
    return validation


def _write_docs(validation: dict[str, Any]) -> None:
    text = f"""# DataSynth v62 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v62
source_baseline: data/journal/primary/datasynth_v61_candidate
included_manifests:
  - patch_manifest/approval_limit_label_manifest.csv
  - patch_manifest/approval_limit_exceeded_population.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Add missing L1-04 `ExceededApprovalLimit` labels for documents whose amount exceeds the resolved approver limit.
- Preserve existing `UnusuallyHighAmount` and `StatisticalOutlier` labels as overlapping L4-03 truth.
- Do not mutate journal fields.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V62_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _patch_labels()
    _copy_sidecars()
    validation = _validate(patch_counts)
    (TARGET_DIR / "V62_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
