"""Materialize DataSynth v68 candidate from the L1 distribution manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v67_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v68_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v68_patch_manifest"
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


def _write_json(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _next_anomaly_id(labels: pd.DataFrame) -> int:
    current = pd.to_numeric(labels["anomaly_id"].astype(str).str.extract(r"(\d+)")[0], errors="coerce").max()
    return int(current) + 1


def _metadata_col(labels: pd.DataFrame) -> str:
    return "metadata_json" if "metadata_json" in labels.columns else "metadata"


def _apply_journal_manifest() -> dict[str, int]:
    self_manifest = pd.read_csv(MANIFEST_DIR / "self_approval_repair_manifest.csv", dtype=str)
    skipped_manifest = pd.read_csv(MANIFEST_DIR / "skipped_approval_2023_add_manifest.csv", dtype=str)
    self_map = self_manifest.set_index("document_id")[["new_approved_by", "new_approval_date"]].to_dict(orient="index")
    skipped_docs = set(skipped_manifest["document_id"].dropna().astype(str))

    combined_frames: list[pd.DataFrame] = []
    self_rows = 0
    skipped_rows = 0
    for year in YEARS:
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, dtype=str, low_memory=False)
        ids = df["document_id"].astype(str)
        self_mask = ids.isin(self_map)
        if self_mask.any():
            df.loc[self_mask, "approved_by"] = ids[self_mask].map(lambda doc_id: self_map[doc_id]["new_approved_by"])
            df.loc[self_mask, "approval_date"] = ids[self_mask].map(lambda doc_id: self_map[doc_id]["new_approval_date"])
            self_rows += int(self_mask.sum())
        skipped_mask = ids.isin(skipped_docs)
        if skipped_mask.any():
            df.loc[skipped_mask, "approved_by"] = ""
            df.loc[skipped_mask, "approval_date"] = ""
            skipped_rows += int(skipped_mask.sum())
        df.to_csv(path, index=False)
        combined_frames.append(df)
    pd.concat(combined_frames, ignore_index=True).to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    return {
        "self_approval_repaired_docs": int(len(self_map)),
        "self_approval_repaired_rows": self_rows,
        "skipped_approval_added_docs": int(len(skipped_docs)),
        "skipped_approval_added_rows": skipped_rows,
    }


def _patch_labels() -> dict[str, int]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    self_manifest = pd.read_csv(MANIFEST_DIR / "self_approval_repair_manifest.csv", dtype=str)
    skipped_manifest = pd.read_csv(MANIFEST_DIR / "skipped_approval_2023_add_manifest.csv", dtype=str)
    remove_self_docs = set(self_manifest["document_id"].dropna().astype(str))
    before_self = int(labels["anomaly_type"].eq("SelfApproval").sum())
    labels = labels.loc[
        ~(labels["anomaly_type"].eq("SelfApproval") & labels["document_id"].astype(str).isin(remove_self_docs))
    ].copy()
    removed_self = before_self - int(labels["anomaly_type"].eq("SelfApproval").sum())

    meta_col = _metadata_col(labels)
    next_id = _next_anomaly_id(labels)
    new_rows: list[dict[str, Any]] = []
    for row in skipped_manifest.to_dict(orient="records"):
        metadata = {
            "v68_patch": "l1_distribution_realism",
            "rule_id": "L1-07",
            "truth_layer": "confirmed_anomaly",
            "document_amount": int(float(row["document_amount"])),
            "approval_level": int(float(row["approval_level"])),
            "source": row["source"],
            "business_process": row["business_process"],
            "missing_approved_by": True,
            "anti_fitting_note": "Small 2023 coverage fixture selected from eligible manual/adjustment documents.",
        }
        metadata_json = json.dumps(metadata, ensure_ascii=False)
        new_row = {col: None for col in labels.columns}
        new_row.update(
            {
                "anomaly_id": f"ANO{next_id:08d}",
                "anomaly_category": "Process",
                "anomaly_type": "SkippedApproval",
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["posting_date"])[:10],
                "detection_timestamp": "2026-04-27 00:00:00",
                "confidence": "0.84",
                "severity": "4",
                "description": f"L1-07 SkippedApproval 2023 coverage: {row['document_number']} has no approver",
                "is_injected": "True",
                "monetary_impact": str(float(row["document_amount"])),
                "related_entities": json.dumps([row["document_number"]], ensure_ascii=False),
                "injection_strategy": "SkippedApproval2023Coverage",
                "structured_strategy_type": "SkippedApproval",
                "structured_strategy_json": metadata_json,
                "causal_reason_type": "SkippedApprovalFieldContract",
                "causal_reason_json": metadata_json,
                "child_anomaly_ids": "[]",
                meta_col: metadata_json,
            }
        )
        new_rows.append(new_row)
        next_id += 1
    if new_rows:
        labels = pd.concat([labels, pd.DataFrame(new_rows)], ignore_index=True)
    _write_label_files(labels)
    return {"removed_self_approval_labels": removed_self, "added_skipped_approval_labels": len(new_rows)}


def _copy_and_patch_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("self_approval_*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)

    skipped_manifest = pd.read_csv(MANIFEST_DIR / "skipped_approval_2023_add_manifest.csv", dtype=str)
    if not skipped_manifest.empty:
        for stem in ["skipped_approval_confirmed_anomalies", "skipped_approval_normal_controls"]:
            path = labels_dir / f"{stem}.csv"
            if not path.exists():
                continue
            df = pd.read_csv(path, dtype=str)
            if stem == "skipped_approval_confirmed_anomalies":
                additions = skipped_manifest.drop(
                    columns=["old_approved_by", "new_approved_by", "old_approval_date", "new_approval_date"],
                    errors="ignore",
                ).copy()
                additions["approved_by"] = ""
                additions["approval_date"] = ""
                additions["expected_l107_flag"] = "True"
                additions["truth_layer"] = "confirmed_anomaly"
                for col in df.columns:
                    if col not in additions.columns:
                        additions[col] = ""
                df = pd.concat([df, additions[df.columns]], ignore_index=True)
            else:
                remove_docs = set(skipped_manifest["document_id"].astype(str))
                df = df.loc[~df["document_id"].astype(str).isin(remove_docs)].copy()
            df.to_csv(path, index=False)
            _write_json(labels_dir / f"{stem}.json", df)
            for year in YEARS:
                subset = df.loc[df["fiscal_year"].astype(str).eq(str(year))]
                subset.to_csv(labels_dir / f"{stem}_{year}.csv", index=False)
                _write_json(labels_dir / f"{stem}_{year}.json", subset)

        controls_path = labels_dir / "approval_date_present_normal_controls.csv"
        if controls_path.exists():
            controls = pd.read_csv(controls_path, dtype=str)
            controls = controls.loc[~controls["document_id"].astype(str).isin(skipped_manifest["document_id"].astype(str))].copy()
            controls.to_csv(controls_path, index=False)
            _write_json(labels_dir / "approval_date_present_normal_controls.json", controls)
            for year in YEARS:
                subset = controls.loc[controls["fiscal_year"].astype(str).eq(str(year))]
                subset.to_csv(labels_dir / f"approval_date_present_normal_controls_{year}.csv", index=False)
                _write_json(labels_dir / f"approval_date_present_normal_controls_{year}.json", subset)


def _validate(patch_counts: dict[str, int], label_counts: dict[str, int]) -> dict[str, object]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    rows = []
    for year in YEARS:
        df = pd.read_csv(
            TARGET_DIR / f"journal_entries_{year}.csv",
            dtype=str,
            usecols=["document_id", "fiscal_year", "created_by", "approved_by", "source"],
            low_memory=False,
        )
        rows.append(
            df.groupby("document_id", as_index=False).agg(
                fiscal_year=("fiscal_year", "first"),
                created_by=("created_by", "first"),
                approved_by=("approved_by", "first"),
                source=("source", "first"),
            )
        )
    docs = pd.concat(rows, ignore_index=True)
    created = docs["created_by"].fillna("").astype(str).str.strip()
    approved = docs["approved_by"].fillna("").astype(str).str.strip()
    source = docs["source"].fillna("").astype(str).str.lower()
    actual_self = set(docs.loc[created.ne("") & created.eq(approved) & ~source.eq("automated"), "document_id"].astype(str))
    self_labels = set(labels.loc[labels["anomaly_type"].eq("SelfApproval"), "document_id"].dropna().astype(str))
    skipped_labels = set(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].dropna().astype(str))
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v67_candidate",
        "self_approval_actual_docs": len(actual_self),
        "self_approval_label_docs": len(self_labels),
        "self_approval_mismatch": len(actual_self.symmetric_difference(self_labels)),
        "skipped_approval_label_docs": len(skipped_labels),
        "wrong_period_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].nunique()),
        "approval_date_missing_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].nunique()),
        "patch_counts": patch_counts,
        "label_counts": label_counts,
    }
    validation["valid_candidate"] = (
        validation["self_approval_mismatch"] == 0
        and validation["wrong_period_label_docs_preserved"] == 731
        and validation["approval_date_missing_label_docs_preserved"] == 26
    )
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v68 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v68
source_baseline: data/journal/primary/datasynth_v67_candidate
included_manifests:
  - v65 WrongPeriod repair
  - v66 SkippedApproval cleanup
  - v67 ApprovalDateMissing cleanup
  - patch_manifest/self_approval_repair_manifest.csv
  - patch_manifest/skipped_approval_2023_add_manifest.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Reduce excessive L1-05 `SelfApproval` confirmed truth by changing non-confirmed self approvals to independent approvals.
- Add small 2023 L1-07 `SkippedApproval` coverage.
- Preserve v65/v66/v67 field-contract repairs.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V68_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _apply_journal_manifest()
    label_counts = _patch_labels()
    _copy_and_patch_sidecars()
    validation = _validate(patch_counts, label_counts)
    (TARGET_DIR / "V68_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
