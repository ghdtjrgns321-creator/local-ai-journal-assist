"""Materialize DataSynth v69 candidate from L1 realism controls manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v68_candidate"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v69_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v69_patch_manifest"
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
    path.write_text(
        json.dumps(df.where(pd.notna(df), None).to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _apply_approval_date_delays() -> dict[str, int]:
    manifest = pd.read_csv(MANIFEST_DIR / "approval_date_delay_manifest.csv", dtype=str)
    patch_map = dict(zip(manifest["document_id"].astype(str), manifest["new_approval_date"].astype(str), strict=False))
    combined_frames: list[pd.DataFrame] = []
    patched_rows = 0
    patched_docs: set[str] = set()
    for year in YEARS:
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        df = pd.read_csv(path, dtype=str, low_memory=False)
        ids = df["document_id"].astype(str)
        mask = ids.isin(patch_map)
        if mask.any():
            df.loc[mask, "approval_date"] = ids[mask].map(patch_map)
            patched_rows += int(mask.sum())
            patched_docs.update(ids[mask])
        df.to_csv(path, index=False)
        combined_frames.append(df)
    pd.concat(combined_frames, ignore_index=True).to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    return {"approval_date_delayed_docs": len(patched_docs), "approval_date_delayed_rows": patched_rows}


def _copy_sidecars() -> None:
    labels_dir = TARGET_DIR / "labels"
    for path in MANIFEST_DIR.glob("l1_realism_normal_controls*"):
        if path.suffix.lower() in {".csv", ".json"}:
            shutil.copy2(path, labels_dir / path.name)

    controls = pd.read_csv(MANIFEST_DIR / "l1_realism_normal_controls.csv", dtype=str)
    approval_controls_path = labels_dir / "approval_date_present_normal_controls.csv"
    if approval_controls_path.exists():
        approval_controls = pd.read_csv(approval_controls_path, dtype=str)
        delay = controls.loc[controls["control_type"].eq("approval_date_delayed_but_present")].copy()
        if not delay.empty:
            delay = delay.rename(columns={"normal_reason": "normal_reason_v69"})
            for col in approval_controls.columns:
                if col not in delay.columns:
                    delay[col] = ""
            merged = pd.concat([approval_controls, delay[approval_controls.columns]], ignore_index=True)
            merged = merged.drop_duplicates("document_id", keep="last")
            merged.to_csv(approval_controls_path, index=False)
            _write_json(labels_dir / "approval_date_present_normal_controls.json", merged)
            for year in YEARS:
                subset = merged.loc[merged["fiscal_year"].astype(str).eq(str(year))]
                subset.to_csv(labels_dir / f"approval_date_present_normal_controls_{year}.csv", index=False)
                _write_json(labels_dir / f"approval_date_present_normal_controls_{year}.json", subset)


def _validate(patch_counts: dict[str, int]) -> dict[str, object]:
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    controls = pd.read_csv(TARGET_DIR / "labels" / "l1_realism_normal_controls.csv", dtype=str)
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth_v68_candidate",
        "l1_realism_control_docs": int(controls["document_id"].nunique()),
        "l1_realism_control_rows": int(len(controls)),
        "control_type_counts": controls["control_type"].value_counts().to_dict(),
        "self_approval_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("SelfApproval"), "document_id"].nunique()),
        "skipped_approval_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("SkippedApproval"), "document_id"].nunique()),
        "wrong_period_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("WrongPeriod"), "document_id"].nunique()),
        "approval_date_missing_label_docs_preserved": int(labels.loc[labels["anomaly_type"].eq("ApprovalDateMissing"), "document_id"].nunique()),
        "patch_counts": patch_counts,
    }
    validation["valid_candidate"] = (
        validation["l1_realism_control_docs"] > 0
        and validation["self_approval_label_docs_preserved"] == 217
        and validation["skipped_approval_label_docs_preserved"] == 17
        and validation["wrong_period_label_docs_preserved"] == 731
        and validation["approval_date_missing_label_docs_preserved"] == 26
    )
    return validation


def _write_docs(validation: dict[str, object]) -> None:
    text = f"""# DataSynth v69 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v69
source_baseline: data/journal/primary/datasynth_v68_candidate
included_manifests:
  - v65 WrongPeriod repair
  - v66 SkippedApproval cleanup
  - v67 ApprovalDateMissing cleanup
  - v68 L1 distribution realism
  - patch_manifest/approval_date_delay_manifest.csv
  - patch_manifest/l1_realism_normal_controls.csv
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Add L1 normal/boundary controls without creating unlabeled field violations.
- Delay approval dates on selected normal documents.
- Add normal controls for period boundary, approval threshold near-miss, and terse-but-valid descriptions.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```
"""
    (TARGET_DIR / "FREEZE_V69_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"missing source: {SOURCE_DIR}")
    if not MANIFEST_DIR.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_DIR}")
    _copy_source()
    _copy_manifests()
    patch_counts = _apply_approval_date_delays()
    _copy_sidecars()
    validation = _validate(patch_counts)
    (TARGET_DIR / "V69_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
