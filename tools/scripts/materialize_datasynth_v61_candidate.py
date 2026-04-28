"""Materialize DataSynth v61 candidate from the SelfApproval manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v60_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v61_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v61_patch_manifest"
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


def _metadata_col(labels: pd.DataFrame) -> str:
    return "metadata_json" if "metadata_json" in labels.columns else "metadata"


def _next_anomaly_id(labels: pd.DataFrame) -> int:
    current = pd.to_numeric(labels["anomaly_id"].astype(str).str.extract(r"(\d+)")[0], errors="coerce").max()
    return int(current) + 1


def _patch_labels() -> dict[str, int]:
    labels_path = TARGET_DIR / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str)
    manifest = pd.read_csv(MANIFEST_DIR / "self_approval_label_manifest.csv", dtype=str)
    manifest["document_amount"] = pd.to_numeric(manifest["document_amount"], errors="coerce").fillna(0.0)
    meta_col = _metadata_col(labels)

    existing_idx = {
        str(row["document_id"]): idx
        for idx, row in labels.loc[labels["anomaly_type"].eq("SelfApproval")].iterrows()
    }
    next_id = _next_anomaly_id(labels)
    added_rows: list[dict[str, Any]] = []
    updated = 0
    for row in manifest.to_dict(orient="records"):
        doc_id = str(row["document_id"])
        metadata = str(row["metadata_json"])
        description = (
            f"L1-05 SelfApproval truth: {row['created_by']} prepared and approved "
            f"{row['document_number']} ({row['self_approval_role']})"
        )
        related = json.dumps([row["document_number"]], ensure_ascii=False)
        common = {
            "anomaly_category": "Fraud",
            "anomaly_type": "SelfApproval",
            "document_id": doc_id,
            "document_type": row["document_type"],
            "company_code": row["company_code"],
            "anomaly_date": str(row["posting_date"])[:10],
            "detection_timestamp": "2026-04-27 00:00:00",
            "confidence": "0.90",
            "severity": "3" if row["self_approval_role"] == "immediate_violation" else "2",
            "description": description,
            "is_injected": "True",
            "monetary_impact": str(float(row["document_amount"])),
            "related_entities": related,
            "injection_strategy": "SelfApprovalTruthRepair",
            "structured_strategy_type": "SelfApproval",
            "structured_strategy_json": metadata,
            "causal_reason_type": "SelfApprovalFieldContract",
            "causal_reason_json": metadata,
            "child_anomaly_ids": "[]",
            meta_col: metadata,
        }
        if doc_id in existing_idx:
            idx = existing_idx[doc_id]
            for col, value in common.items():
                if col in labels.columns:
                    labels.at[idx, col] = value
            updated += 1
            continue
        new_row = {col: None for col in labels.columns}
        new_row.update(common)
        new_row["anomaly_id"] = f"ANO{next_id:08d}"
        added_rows.append(new_row)
        next_id += 1

    if added_rows:
        labels = pd.concat([labels, pd.DataFrame(added_rows)], ignore_index=True)

    labels.to_csv(labels_path, index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    labels_dir = TARGET_DIR / "labels"
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
    return {"added": len(added_rows), "updated": updated, "total_selfapproval": int(labels["anomaly_type"].eq("SelfApproval").sum())}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("self_approval_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)


def _actual_selfapproval_docs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        df = pd.read_csv(
            TARGET_DIR / f"journal_entries_{year}.csv",
            dtype=str,
            usecols=["document_id", "fiscal_year", "source", "user_persona", "created_by", "approved_by"],
            low_memory=False,
        )
        docs = df.groupby("document_id", as_index=False).agg(
            fiscal_year=("fiscal_year", "first"),
            source=("source", "first"),
            user_persona=("user_persona", "first"),
            created_by=("created_by", "first"),
            approved_by=("approved_by", "first"),
        )
        frames.append(docs)
    docs = pd.concat(frames, ignore_index=True)
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    persona = docs["user_persona"].fillna("").astype(str).str.strip().str.lower()
    source = docs["source"].fillna("").astype(str).str.strip().str.lower()
    return docs.loc[
        created.ne("")
        & approved.ne("")
        & created.eq(approved)
        & ~persona.eq("automated_system")
        & ~source.eq("automated")
    ].copy()


def _validate(label_patch_counts: dict[str, int]) -> dict[str, Any]:
    actual = _actual_selfapproval_docs()
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    self_docs = set(labels.loc[labels["anomaly_type"].eq("SelfApproval"), "document_id"].astype(str))
    actual_docs = set(actual["document_id"].astype(str))
    review = pd.read_csv(TARGET_DIR / "labels" / "self_approval_review_population.csv", dtype=str)
    review_docs = set(review["document_id"].astype(str))
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v60_candidate",
        "actual_l105_docs": len(actual_docs),
        "selfapproval_label_docs": len(self_docs),
        "review_population_docs": len(review_docs),
        "missing_labels_for_actual_l105": len(actual_docs - self_docs),
        "labels_without_actual_l105": len(self_docs - actual_docs),
        "review_population_mismatch": len(actual_docs.symmetric_difference(review_docs)),
        "year_counts": {str(k): int(v) for k, v in actual["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "label_patch_counts": label_patch_counts,
    }
    validation["valid_candidate"] = (
        validation["actual_l105_docs"] == validation["selfapproval_label_docs"]
        and validation["actual_l105_docs"] == validation["review_population_docs"]
        and validation["missing_labels_for_actual_l105"] == 0
        and validation["labels_without_actual_l105"] == 0
        and validation["review_population_mismatch"] == 0
    )
    return validation


def _write_docs(validation: dict[str, Any]) -> None:
    text = f"""# DataSynth v61 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v61
source_baseline: data/journal/primary/datasynth_v60_candidate
included_manifests:
  - patch_manifest/self_approval_label_manifest.csv
  - patch_manifest/self_approval_review_population.csv
  - patch_manifest/self_approval_normal_controls.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Repair L1-05 `SelfApproval` truth that was lost in later DataSynth lineage.
- Do not mutate journal fields.
- Treat non-system `created_by == approved_by` as L1-05 review truth.
- Keep system/automated self-approval contexts in normal controls.

## Anti-Fitting Position

This patch does not sample detector hits. L1-05 is a direct field-contract rule, so the truth population is derived from
ledger fields and explicit allowlist exclusions. The sidecar remains available for Phase 1 population evaluation.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V61_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    label_patch_counts = _patch_labels()
    _copy_sidecars()
    validation = _validate(label_patch_counts)
    (TARGET_DIR / "V61_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
