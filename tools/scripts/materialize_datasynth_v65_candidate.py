"""Materialize DataSynth v65 candidate from the WrongPeriod manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v64_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v65_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v65_patch_manifest"


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
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    manifest = pd.read_csv(MANIFEST_DIR / "wrong_period_label_manifest.csv", dtype=str)
    if manifest.empty:
        return {"added": 0, "total_wrong_period": int(labels["anomaly_type"].eq("WrongPeriod").sum())}
    meta_col = _metadata_col(labels)
    existing = set(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].astype(str))
    next_id = _next_anomaly_id(labels)
    new_rows: list[dict[str, Any]] = []
    for row in manifest.to_dict(orient="records"):
        if str(row["document_id"]) in existing:
            continue
        metadata = str(row["metadata_json"])
        new_row = {col: None for col in labels.columns}
        new_row.update(
            {
                "anomaly_id": f"ANO{next_id:08d}",
                "anomaly_category": "Error",
                "anomaly_type": "WrongPeriod",
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["posting_date"])[:10],
                "detection_timestamp": "2026-04-27 00:00:00",
                "confidence": "0.93",
                "severity": "4",
                "description": (
                    f"L1-08 WrongPeriod truth: fiscal_period={int(float(row['fiscal_period_num']))} "
                    f"but posting month={int(float(row['posting_month']))}"
                ),
                "is_injected": "True",
                "monetary_impact": None,
                "related_entities": json.dumps([row["document_number"]], ensure_ascii=False),
                "injection_strategy": "WrongPeriodTruthRepair",
                "structured_strategy_type": "WrongPeriod",
                "structured_strategy_json": metadata,
                "causal_reason_type": "FiscalPeriodFieldContract",
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
    return {"added": len(new_rows), "total_wrong_period": int(labels["anomaly_type"].eq("WrongPeriod").sum())}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("wrong_period_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _validate(patch_counts: dict[str, int]) -> dict[str, Any]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    label_docs = set(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].astype(str))
    confirmed = pd.read_csv(TARGET_DIR / "labels" / "wrong_period_confirmed_anomalies.csv", dtype=str)
    confirmed_docs = set(confirmed["document_id"].astype(str))
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v64_candidate",
        "wrong_period_label_docs": len(label_docs),
        "confirmed_sidecar_docs": len(confirmed_docs),
        "label_sidecar_mismatch": len(label_docs.symmetric_difference(confirmed_docs)),
        "label_patch_counts": patch_counts,
    }
    validation["valid_candidate"] = validation["label_sidecar_mismatch"] == 0
    return validation


def _write_docs(validation: dict[str, Any]) -> None:
    text = f"""# DataSynth v65 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v65
source_baseline: data/journal/primary/datasynth_v64_candidate
included_manifests:
  - patch_manifest/wrong_period_label_manifest.csv
  - patch_manifest/wrong_period_confirmed_anomalies.csv
  - patch_manifest/wrong_period_normal_controls.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Add missing strict L1-08 `WrongPeriod` labels.
- Preserve original `fiscal_period` values as the data-integrity issue under test.
- Preserve overlapping labels and add sidecars for confirmed mismatches and normal controls.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V65_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _patch_labels()
    _copy_sidecars()
    validation = _validate(patch_counts)
    (TARGET_DIR / "V65_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
