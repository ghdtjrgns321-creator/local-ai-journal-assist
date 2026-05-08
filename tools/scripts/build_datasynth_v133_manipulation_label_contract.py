"""Make datasynth_manipulation labels manipulation-only."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_DATA_DIR = Path("data/journal/primary/datasynth_manipulation")

ANOMALY_COLUMNS = [
    "anomaly_id",
    "anomaly_category",
    "anomaly_type",
    "document_id",
    "document_type",
    "company_code",
    "anomaly_date",
    "detection_timestamp",
    "confidence",
    "severity",
    "description",
    "is_injected",
    "monetary_impact",
    "related_entities",
    "cluster_id",
    "original_document_hash",
    "injection_strategy",
    "structured_strategy_type",
    "structured_strategy_json",
    "causal_reason_type",
    "causal_reason_json",
    "parent_anomaly_id",
    "child_anomaly_ids",
    "scenario_id",
    "run_id",
    "generation_seed",
    "metadata_json",
]


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    path.write_text(df.to_json(orient="records", force_ascii=False, date_format="iso"), encoding="utf-8")


def build_anomaly_labels(truth: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for idx, row in enumerate(truth.sort_values(["fiscal_year", "manipulation_scenario", "document_id"]).itertuples(index=False), start=1):
        metadata = {
            "dataset_role": "manipulation",
            "truth_source": "manipulated_entry_truth",
            "fiscal_year": int(row.fiscal_year),
            "manipulation_scenario": row.manipulation_scenario,
            "manipulation_subtype": row.manipulation_subtype,
            "year_concept": row.year_concept,
            "stealth_profile": row.stealth_profile,
            "not_rule_targeted": bool(row.not_rule_targeted),
        }
        structured = {
            "manipulation_scenario": row.manipulation_scenario,
            "manipulation_subtype": row.manipulation_subtype,
            "reference_pattern": row.reference_pattern,
        }
        rows.append(
            {
                "anomaly_id": f"MANIP{idx:06d}",
                "anomaly_category": "ManipulationTruth",
                "anomaly_type": row.manipulation_scenario,
                "document_id": row.document_id,
                "document_type": row.document_type,
                "company_code": row.company_code,
                "anomaly_date": str(row.posting_date).split(" ")[0],
                "detection_timestamp": now,
                "confidence": 1.0,
                "severity": 4,
                "description": f"Manipulation truth scenario: {row.manipulation_scenario}",
                "is_injected": True,
                "monetary_impact": float(row.line_amount) if pd.notna(row.line_amount) else None,
                "related_entities": json.dumps([row.document_id], ensure_ascii=False),
                "cluster_id": row.reference_pattern,
                "original_document_hash": "",
                "injection_strategy": row.manipulation_scenario,
                "structured_strategy_type": row.manipulation_subtype,
                "structured_strategy_json": json.dumps(structured, ensure_ascii=False),
                "causal_reason_type": "ManipulationScenario",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": row.manipulation_scenario,
                "run_id": "datasynth_manipulation_v133",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows, columns=ANOMALY_COLUMNS)


def write_anomaly_family(labels_dir: Path, labels: pd.DataFrame) -> None:
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    _write_json_records(labels_dir / "anomaly_labels.json", labels)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for record in labels.to_dict(orient="records"):
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    summary = {
        "dataset_role": "manipulation",
        "truth_source": "manipulated_entry_truth",
        "rows": int(len(labels)),
        "documents": int(labels["document_id"].nunique()),
        "anomaly_type_counts": {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().to_dict().items()},
        "note": "datasynth_manipulation anomaly_labels contains only actual manipulation truth documents.",
    }
    _write_json(labels_dir / "anomaly_labels_summary.json", summary)


def remove_non_manipulation_revenue_truth(labels_dir: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(labels_dir.glob("revenue_manipulation_*")):
        if path.is_file():
            removed.append(path.name)
            path.unlink()
    return removed


def write_label_readme(labels_dir: Path) -> None:
    text = """# DataSynth Manipulation Labels

This labels directory is frozen as manipulation-only from `v133_manipulation_label_contract`.

Active truth files:

- `manipulated_entry_truth*`: scenario-level manipulation truth.
- `anomaly_labels*`: compatibility label family rebuilt from `manipulated_entry_truth`.
- `manipulated_entry_scenario_summary*`: scenario count summary.

Removed from the active manipulation split:

- contract/rule truth labels from `datasynth_contract`
- revenue manipulation rule-truth sidecars that do not overlap `manipulated_entry_truth`

Phase 1 may still flag many non-truth documents as review candidates. That is expected hard-negative background behavior, not manipulation truth.
"""
    (labels_dir / "README_MANIPULATION_LABELS.md").write_text(text, encoding="utf-8")


def validate(labels_dir: Path, truth: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    truth_docs = set(truth["document_id"].astype(str))
    label_docs = set(labels["document_id"].astype(str))
    revenue_files = sorted(path.name for path in labels_dir.glob("revenue_manipulation_*"))
    failures: list[str] = []
    if label_docs != truth_docs:
        failures.append(
            f"anomaly_labels docs differ from manipulated_entry_truth: missing={len(truth_docs-label_docs)}, outside={len(label_docs-truth_docs)}"
        )
    if revenue_files:
        failures.append(f"revenue truth files remain active: {revenue_files[:5]} total={len(revenue_files)}")
    return {
        "failures": failures,
        "manipulated_truth_docs": len(truth_docs),
        "anomaly_label_docs": len(label_docs),
        "anomaly_label_rows": int(len(labels)),
        "overlap_manipulated_truth": len(truth_docs & label_docs),
        "outside_manipulated_truth": len(label_docs - truth_docs),
        "revenue_truth_files_remaining": revenue_files,
        "anomaly_type_counts": {str(k): int(v) for k, v in labels["anomaly_type"].value_counts().to_dict().items()},
    }


def refresh_metadata(base: Path, checks: dict[str, Any], removed_files: list[str]) -> None:
    meta_path = base / "validated_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["version"] = "v133_manipulation_label_contract"
    meta["status"] = "pass" if not checks["failures"] else "fail"
    meta["generated_at"] = datetime.now().isoformat(timespec="seconds")
    meta["label_contract"] = {
        "active_label_scope": "manipulation_only",
        "base_version": "v132_manipulation_circular_rp_strict",
        "removed_non_manipulation_truth_files": removed_files,
        "checks": checks,
    }
    _write_json(meta_path, meta)
    manifest = {
        "version": "v133_manipulation_label_contract",
        "base_version": "v132_manipulation_circular_rp_strict",
        "data_dir": str(base),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "removed_non_manipulation_truth_files": removed_files,
        "checks": checks,
    }
    _write_json(base / "V133_MANIPULATION_LABEL_CONTRACT.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    base = args.data_dir
    labels_dir = base / "labels"
    truth = pd.read_csv(labels_dir / "manipulated_entry_truth.csv")
    labels = build_anomaly_labels(truth)
    write_anomaly_family(labels_dir, labels)
    removed_files = remove_non_manipulation_revenue_truth(labels_dir)
    write_label_readme(labels_dir)
    checks = validate(labels_dir, truth, labels)
    refresh_metadata(base, checks, removed_files)
    print(json.dumps({"version": "v133_manipulation_label_contract", "checks": checks}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
