"""Materialize DataSynth v60 candidate from validated manifests."""

from __future__ import annotations

import csv
import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v60_candidate"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v60_patch_manifest"
YEARS = (2022, 2023, 2024)


def _read_csv_manifest(name: str) -> list[dict[str, str]]:
    path = MANIFEST_DIR / name
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _employee_template(employees: list[dict[str, Any]]) -> dict[str, Any]:
    template = deepcopy(employees[0])
    for key, value in list(template.items()):
        if isinstance(value, list):
            template[key] = []
        elif isinstance(value, dict):
            template[key] = {}
        else:
            template[key] = None
    return template


def _patch_employees() -> int:
    employees_path = TARGET_DIR / "master_data" / "employees.json"
    employees = json.loads(employees_path.read_text(encoding="utf-8"))
    by_user = {str(row.get("user_id", "")).strip(): row for row in employees}
    for change in _read_csv_manifest("employee_tier_changes.csv"):
        user = by_user.get(change["user_id"])
        if user is None:
            raise SystemExit(f"employee tier change target missing: {change['user_id']}")
        if str(user.get("can_approve_je")) != change["old_value"]:
            raise SystemExit(f"employee old value mismatch: {change['user_id']}")
        user["can_approve_je"] = change["new_value"].lower() == "true"
    template = _employee_template(employees)
    additions = _read_csv_manifest("employee_additions.csv")
    for add in additions:
        if add["user_id"] in by_user:
            continue
        row = deepcopy(template)
        row.update(
            {
                "user_id": add["user_id"],
                "employee_id": add["employee_id"],
                "display_name": add["display_name"],
                "first_name": add["display_name"].split(" ")[0],
                "last_name": add["display_name"].split(" ")[-1],
                "email": f"{add['user_id'].lower().replace('á', 'a')}@datasynth.local",
                "company_code": add["company_code"],
                "persona": add["persona"],
                "job_level": add["job_level"],
                "job_title": add["job_title"],
                "department_id": "FIN",
                "cost_center": f"CC-{add['company_code']}-FIN",
                "status": "active",
                "approval_limit": str(int(float(add["approval_limit"]))),
                "can_approve_je": add["can_approve_je"].lower() == "true",
                "can_approve_pr": False,
                "can_approve_po": False,
                "can_approve_invoice": False,
                "can_release_payment": False,
                "authorized_company_codes": [add["company_code"]],
                "authorized_cost_centers": [f"CC-{add['company_code']}-FIN"],
                "system_roles": ["JE_APPROVER"] if add["can_approve_je"].lower() == "true" else ["JE_PREPARER"],
                "transaction_codes": ["FBV0", "FB50"] if add["can_approve_je"].lower() == "true" else ["FB50"],
                "manager_id": None,
                "direct_reports": [],
                "termination_date": None,
            }
        )
        employees.append(row)
        by_user[add["user_id"]] = row
    employees_path.write_text(json.dumps(employees, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(employees)


def _build_patch_maps() -> tuple[dict[str, str], dict[str, float]]:
    approved_by_updates: dict[str, str] = {}
    target_amounts: dict[str, float] = {}
    for patch in _read_csv_manifest("journal_patch_manifest.csv"):
        doc_id = patch["document_id"]
        if patch["field_name"] == "approved_by":
            approved_by_updates[doc_id] = patch["new_value"]
        elif patch["field_name"] == "document_amount":
            target_amounts[doc_id] = float(patch["new_value"])
    return approved_by_updates, target_amounts


def _compute_amount_patch_rows(path: Path, target_amounts: dict[str, float]) -> dict[tuple[str, str], dict[str, str]]:
    if not target_amounts:
        return {}
    rows_by_doc: dict[str, list[dict[str, str]]] = {doc: [] for doc in target_amounts}
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            doc_id = row["document_id"]
            if doc_id in rows_by_doc:
                rows_by_doc[doc_id].append(row)

    patches: dict[tuple[str, str], dict[str, str]] = {}
    for doc_id, rows in rows_by_doc.items():
        if not rows:
            continue
        current = sum(float(row["debit_amount"] or 0) for row in rows)
        if current <= 0:
            continue
        target = target_amounts[doc_id]
        factor = target / current
        by_col: dict[str, list[float]] = {"debit_amount": [], "credit_amount": [], "local_amount": []}
        for row in rows:
            for col in by_col:
                raw = row.get(col, "")
                by_col[col].append(float(raw) * factor if raw not in ("", None) else float("nan"))
        for col in ("debit_amount", "credit_amount"):
            values = [round(v) if v == v else v for v in by_col[col]]
            diff = round(target - sum(v for v in values if v == v))
            if diff:
                indexes = [i for i, v in enumerate(values) if v == v and v > 0]
                if indexes:
                    idx = max(indexes, key=lambda i: values[i])
                    values[idx] += diff
            by_col[col] = values
        by_col["local_amount"] = [round(v) if v == v else v for v in by_col["local_amount"]]
        for idx, row in enumerate(rows):
            key = (doc_id, row["line_number"])
            patches[key] = {}
            for col, values in by_col.items():
                value = values[idx]
                if value == value:
                    patches[key][col] = str(int(value))
    return patches


def _patch_year_file(year: int, approved_by_updates: dict[str, str], target_amounts: dict[str, float]) -> None:
    path = TARGET_DIR / f"journal_entries_{year}.csv"
    tmp = TARGET_DIR / f"journal_entries_{year}.tmp"
    amount_rows = _compute_amount_patch_rows(path, target_amounts)
    with path.open("r", newline="", encoding="utf-8") as source, tmp.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            doc_id = row["document_id"]
            if doc_id in approved_by_updates:
                row["approved_by"] = approved_by_updates[doc_id]
            row_patch = amount_rows.get((doc_id, row["line_number"]))
            if row_patch:
                row.update(row_patch)
            writer.writerow(row)
    tmp.replace(path)


def _rebuild_combined() -> None:
    combined = TARGET_DIR / "journal_entries.csv"
    tmp = TARGET_DIR / "journal_entries.tmp"
    wrote_header = False
    with tmp.open("w", newline="", encoding="utf-8") as out:
        writer = None
        for year in YEARS:
            with (TARGET_DIR / f"journal_entries_{year}.csv").open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if not wrote_header:
                    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\n")
                    writer.writeheader()
                    wrote_header = True
                assert writer is not None
                for row in reader:
                    writer.writerow(row)
    tmp.replace(combined)


def _metadata_col(labels: pd.DataFrame) -> str:
    return "metadata_json" if "metadata_json" in labels.columns else "metadata"


def _patch_labels() -> int:
    labels_path = TARGET_DIR / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str)
    patches = _read_csv_manifest("label_patch_manifest.csv")
    by_doc_type = {(row["document_id"], row["anomaly_type"]): row for row in patches}
    meta_col = _metadata_col(labels)
    patched_count = 0
    for idx, row in labels.loc[labels["anomaly_type"].isin(["ExceededApprovalLimit", "JustBelowThreshold"])].iterrows():
        patch = by_doc_type.get((str(row["document_id"]), str(row["anomaly_type"])))
        if patch is None:
            continue
        metadata = {
            "v60_patch": "approval_master_contract",
            "rule_definition": patch["rule_definition"],
            "approved_by": patch["approved_by"],
            "approval_limit": int(float(patch["approval_limit"])),
            "document_amount": int(float(patch["document_amount"])),
            "previous_document_amount": int(float(patch["previous_document_amount"])),
            "target_ratio": patch.get("target_ratio", ""),
            "amount_pattern": patch.get("amount_pattern", ""),
        }
        labels.at[idx, "description"] = (
            f"{patch['anomaly_type']} aligned to approver {patch['approved_by']} "
            f"limit {int(float(patch['approval_limit']))} and amount {int(float(patch['document_amount']))}"
        )
        labels.at[idx, meta_col] = json.dumps(metadata, ensure_ascii=False)
        patched_count += 1

    new_rows = []
    existing_eal = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    next_id = int(pd.to_numeric(labels["anomaly_id"].astype(str).str.extract(r"(\d+)")[0], errors="coerce").max()) + 1
    for patch in patches:
        if patch["anomaly_type"] != "ExceededApprovalLimit" or patch["document_id"] in existing_eal:
            continue
        row = {col: None for col in labels.columns}
        metadata = {
            "v60_patch": "top_limit_excess_truth",
            "rule_definition": patch["rule_definition"],
            "approved_by": patch["approved_by"],
            "approval_limit": int(float(patch["approval_limit"])),
            "document_amount": int(float(patch["document_amount"])),
        }
        row.update(
            {
                "anomaly_id": f"ANO{next_id:08d}",
                "anomaly_category": "Fraud",
                "anomaly_type": "ExceededApprovalLimit",
                "document_id": patch["document_id"],
                "document_type": patch.get("document_type", ""),
                "company_code": patch.get("company_code", ""),
                "anomaly_date": patch.get("posting_date", ""),
                "detection_timestamp": "2026-04-27 00:00:00",
                "confidence": "0.82",
                "severity": "3",
                "description": "Exceeded top approver limit after v60 approval contract repair",
                "is_injected": "True",
                "monetary_impact": str(max(float(patch["document_amount"]) - float(patch["approval_limit"]), 0.0)),
                "related_entities": json.dumps([patch["document_id"]]),
                "injection_strategy": "ApprovalMasterContractPatch",
                "structured_strategy_type": "ExceededApprovalLimit",
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "ApprovalMasterContractPatch",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "child_anomaly_ids": "[]",
                meta_col: json.dumps(metadata, ensure_ascii=False),
            }
        )
        new_rows.append(row)
        next_id += 1
    if new_rows:
        labels = pd.concat([labels, pd.DataFrame(new_rows)], ignore_index=True)

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
    return patched_count + len(new_rows)


def _copy_manifests_to_candidate() -> None:
    target = TARGET_DIR / "patch_manifest"
    target.mkdir(exist_ok=True)
    for path in MANIFEST_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, target / path.name)


def _validate(employee_count: int, label_patch_count: int) -> dict[str, Any]:
    employees = json.loads((TARGET_DIR / "master_data" / "employees.json").read_text(encoding="utf-8"))
    ids = {str(row.get("user_id", "")).strip() for row in employees if str(row.get("user_id", "")).strip()}
    limits = {
        str(row.get("user_id", "")).strip(): float(row.get("approval_limit"))
        for row in employees
        if str(row.get("user_id", "")).strip() and row.get("approval_limit") not in (None, "")
    }
    frames = []
    for year in YEARS:
        df = pd.read_csv(
            TARGET_DIR / f"journal_entries_{year}.csv",
            dtype=str,
            usecols=["document_id", "created_by", "approved_by", "debit_amount"],
            low_memory=False,
        )
        docs = df.groupby("document_id", as_index=False).agg(
            approved_by=("approved_by", "first"),
            amount=("debit_amount", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        )
        frames.append(df[["created_by", "approved_by"]])
        if year == YEARS[0]:
            all_docs = docs
        else:
            all_docs = pd.concat([all_docs, docs], ignore_index=True)
    actors = pd.concat(frames, ignore_index=True)
    created = set(actors["created_by"].dropna().astype(str).str.strip()) - {""}
    approved = set(actors["approved_by"].dropna().astype(str).str.strip()) - {""}
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv", dtype=str)
    eal = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    jbt = set(labels.loc[labels["anomaly_type"].eq("JustBelowThreshold"), "document_id"].astype(str))
    all_docs["limit"] = all_docs["approved_by"].fillna("").astype(str).str.strip().map(limits)
    eal_docs = all_docs.loc[all_docs["document_id"].astype(str).isin(eal)]
    jbt_docs = all_docs.loc[all_docs["document_id"].astype(str).isin(jbt)]
    validation = {
        "valid_candidate": True,
        "source_baseline": "data/journal/primary/datasynth@v59",
        "created_by_unmatched": len(created - ids),
        "approved_by_unmatched": len(approved - ids),
        "employee_count": employee_count,
        "label_patch_count": label_patch_count,
        "exceeded_labels": len(eal_docs),
        "exceeded_matching": int((eal_docs["amount"] > eal_docs["limit"]).fillna(False).sum()),
        "just_below_labels": len(jbt_docs),
        "just_below_matching": int(
            (
                jbt_docs["limit"].notna()
                & (jbt_docs["amount"] >= jbt_docs["limit"] * 0.90)
                & (jbt_docs["amount"] < jbt_docs["limit"])
            ).sum()
        ),
    }
    validation["valid_candidate"] = (
        validation["created_by_unmatched"] == 0
        and validation["approved_by_unmatched"] == 0
        and validation["exceeded_labels"] == validation["exceeded_matching"]
        and validation["just_below_labels"] == validation["just_below_matching"]
    )
    return validation


def _write_docs(validation: dict[str, Any]) -> None:
    text = f"""# DataSynth v60 Candidate

Status: candidate only, not production.

Created: `{datetime.now().isoformat(timespec='seconds')}`

## Lineage

```yaml
candidate_version: v60
source_baseline: data/journal/primary/datasynth@v59
included_manifests:
  - patch_manifest/employee_additions.csv
  - patch_manifest/employee_tier_changes.csv
  - patch_manifest/journal_patch_manifest.csv
  - patch_manifest/label_patch_manifest.csv
excluded_candidates:
  - previous interrupted datasynth_v60_candidate
validation_status: {'pass' if validation['valid_candidate'] else 'fail'}
promotion_status: candidate_only
```

## Scope

- Fix DataSynth approval master consistency.
- Align approval thresholds to `10M, 100M, 1B, 5B, 10B, 50B`.
- Backfill JE actors into `employees.json`.
- Repoint L1-04/L2-01 label documents to resolvable approvers.
- Remove stale `300M` and `3B` just-below-threshold patterns.

## Validation

```json
{json.dumps(validation, ensure_ascii=False, indent=2)}
```

Do not promote without explicit approval.
"""
    (TARGET_DIR / "FREEZE_V60_CANDIDATE.md").write_text(text, encoding="utf-8")
    (TARGET_DIR / "PREVIEW.md").write_text(text, encoding="utf-8")


def main() -> None:
    _copy_source()
    _copy_manifests_to_candidate()
    employee_count = _patch_employees()
    approved_by_updates, target_amounts = _build_patch_maps()
    for year in YEARS:
        year_docs = set(pd.read_csv(TARGET_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=["document_id"])["document_id"].astype(str))
        year_approved = {doc: value for doc, value in approved_by_updates.items() if doc in year_docs}
        year_amounts = {doc: value for doc, value in target_amounts.items() if doc in year_docs}
        _patch_year_file(year, year_approved, year_amounts)
    _rebuild_combined()
    label_patch_count = _patch_labels()
    validation = _validate(employee_count, label_patch_count)
    (TARGET_DIR / "V60_VALIDATION.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["valid_candidate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
