from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingest.datasynth_metadata import write_validated_metadata

DATASET_DIRS = [
    ROOT / "data" / "journal" / "primary" / "datasynth",
    ROOT / "data" / "journal" / "primary" / "datasynth_v20",
]
HOTFIX_FILENAME = "V20_4_EXCEEDED_APPROVAL_LIMIT_HOTFIX.json"
TARGET_ANOMALY = "ExceededApprovalLimit"


@dataclass
class Approver:
    user_id: str
    company_code: str
    approval_limit: float
    can_approve_je: bool


@dataclass
class DocInfo:
    document_id: str
    company_code: str
    fiscal_year: str
    document_number: str
    created_by: str
    approved_by: str
    approval_date: str
    posting_date: str
    amount: float


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_approvers(dataset_dir: Path) -> dict[str, list[Approver]]:
    employees = _load_json(dataset_dir / "master_data" / "employees.json")
    by_company: dict[str, list[Approver]] = defaultdict(list)
    for employee in employees:
        if not employee.get("can_approve_je"):
            continue
        try:
            limit = float(employee.get("approval_limit") or 0)
        except (TypeError, ValueError):
            continue
        by_company[str(employee.get("company_code") or "")].append(
            Approver(
                user_id=str(employee["user_id"]),
                company_code=str(employee.get("company_code") or ""),
                approval_limit=limit,
                can_approve_je=bool(employee.get("can_approve_je")),
            )
        )
    for approvers in by_company.values():
        approvers.sort(key=lambda a: a.approval_limit)
    return by_company


def _collect_doc_info(dataset_dir: Path, target_docs: set[str]) -> dict[str, DocInfo]:
    _, rows = _read_csv(dataset_dir / "journal_entries.csv")
    info: dict[str, DocInfo] = {}
    for row in rows:
        did = row["document_id"]
        if did not in target_docs:
            continue
        debit = float(row.get("debit_amount") or 0)
        credit = float(row.get("credit_amount") or 0)
        line_amount = debit + credit
        if did not in info:
            info[did] = DocInfo(
                document_id=did,
                company_code=str(row.get("company_code") or ""),
                fiscal_year=str(row.get("fiscal_year") or ""),
                document_number=str(row.get("document_number") or ""),
                created_by=str(row.get("created_by") or ""),
                approved_by=str(row.get("approved_by") or ""),
                approval_date=str(row.get("approval_date") or ""),
                posting_date=str(row.get("posting_date") or ""),
                amount=line_amount,
            )
        else:
            info[did].amount = max(info[did].amount, line_amount)
    return info


def _choose_approver(doc: DocInfo, by_company: dict[str, list[Approver]]) -> Approver | None:
    candidates = [
        approver
        for approver in by_company.get(doc.company_code, [])
        if approver.user_id != doc.created_by and doc.amount > approver.approval_limit
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a.approval_limit)


def _approval_date_from_posting(posting_date: str) -> str:
    text = (posting_date or "").strip()
    if not text:
        return ""
    return text[:10]


def _patch_dataset(dataset_dir: Path) -> dict[str, Any]:
    labels_path = dataset_dir / "labels" / "anomaly_labels.csv"
    label_fields, label_rows = _read_csv(labels_path)
    target_docs = {row["document_id"] for row in label_rows if row.get("anomaly_type") == TARGET_ANOMALY}
    by_company = _load_approvers(dataset_dir)
    doc_info = _collect_doc_info(dataset_dir, target_docs)

    keep_docs: dict[str, Approver] = {}
    remove_docs: set[str] = set()
    for did in sorted(target_docs):
        selected = _choose_approver(doc_info[did], by_company)
        if selected is None:
            remove_docs.add(did)
        else:
            keep_docs[did] = selected

    # Patch journal entries
    je_path = dataset_dir / "journal_entries.csv"
    je_fields, je_rows = _read_csv(je_path)
    for row in je_rows:
        did = row["document_id"]
        if did in keep_docs:
            approver = keep_docs[did]
            row["approved_by"] = approver.user_id
            if not (row.get("approval_date") or "").strip():
                row["approval_date"] = _approval_date_from_posting(row.get("posting_date") or "")
        elif did in remove_docs and row.get("anomaly_type") == TARGET_ANOMALY:
            row["is_anomaly"] = "False"
            row["anomaly_type"] = ""
    _write_csv(je_path, je_fields, je_rows)

    # Patch year-sliced journal entries
    for year in ("2022", "2023", "2024"):
        year_path = dataset_dir / f"journal_entries_{year}.csv"
        if not year_path.exists():
            continue
        year_fields, year_rows = _read_csv(year_path)
        for row in year_rows:
            did = row["document_id"]
            if did in keep_docs:
                approver = keep_docs[did]
                row["approved_by"] = approver.user_id
                if not (row.get("approval_date") or "").strip():
                    row["approval_date"] = _approval_date_from_posting(row.get("posting_date") or "")
            elif did in remove_docs and row.get("anomaly_type") == TARGET_ANOMALY:
                row["is_anomaly"] = "False"
                row["anomaly_type"] = ""
        _write_csv(year_path, year_fields, year_rows)

    # Patch document labels if present
    for year in ("2022", "2023", "2024"):
        doc_label_path = dataset_dir / "labels" / f"document_labels_{year}.csv"
        if not doc_label_path.exists():
            continue
        doc_fields, doc_rows = _read_csv(doc_label_path)
        for row in doc_rows:
            if row["document_id"] in remove_docs and row.get("anomaly_type") == TARGET_ANOMALY:
                row["is_anomaly"] = "False"
                row["anomaly_type"] = ""
        _write_csv(doc_label_path, doc_fields, doc_rows)

    # Patch anomaly_labels sidecars
    patched_label_rows: list[dict[str, str]] = []
    kept_records: list[dict[str, Any]] = []
    removed_records: list[dict[str, Any]] = []
    for row in label_rows:
        did = row["document_id"]
        if row.get("anomaly_type") != TARGET_ANOMALY:
            patched_label_rows.append(row)
            continue
        if did in remove_docs:
            removed_records.append(
                {
                    "document_id": did,
                    "company_code": doc_info[did].company_code,
                    "fiscal_year": doc_info[did].fiscal_year,
                    "document_number": doc_info[did].document_number,
                    "amount": doc_info[did].amount,
                    "reason": "no approver in same company has approval_limit below document amount",
                }
            )
            continue
        approver = keep_docs[did]
        row["description"] = (
            f"Exceeded approver approval limit: {doc_info[did].amount:.0f} vs "
            f"{approver.user_id} limit {approver.approval_limit:.0f}"
        )
        row["metadata_json"] = json.dumps(
            {
                "patched_approved_by": approver.user_id,
                "patched_approval_limit": approver.approval_limit,
                "document_amount": doc_info[did].amount,
            },
            ensure_ascii=False,
        )
        patched_label_rows.append(row)
        kept_records.append(
            {
                "document_id": did,
                "company_code": doc_info[did].company_code,
                "fiscal_year": doc_info[did].fiscal_year,
                "document_number": doc_info[did].document_number,
                "amount": doc_info[did].amount,
                "patched_approved_by": approver.user_id,
                "patched_approval_limit": approver.approval_limit,
            }
        )
    _write_csv(labels_path, label_fields, patched_label_rows)
    _write_json(dataset_dir / "labels" / "anomaly_labels.json", patched_label_rows)
    with (dataset_dir / "labels" / "anomaly_labels.jsonl").open("w", encoding="utf-8") as f:
        for row in patched_label_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_category = defaultdict(int)
    by_company_counts = defaultdict(int)
    for row in patched_label_rows:
        by_category[row["anomaly_category"]] += 1
        by_company_counts[row["company_code"]] += 1
    _write_json(
        dataset_dir / "labels" / "anomaly_labels_summary.json",
        {
            "total_labels": len(patched_label_rows),
            "by_category": dict(sorted(by_category.items())),
            "by_company": dict(sorted(by_company_counts.items())),
            "with_provenance": len(patched_label_rows),
            "in_scenarios": 0,
            "in_clusters": 0,
        },
    )

    # Refresh generation statistics
    stats_path = dataset_dir / "generation_statistics.json"
    stats = _load_json(stats_path)
    stats["anomalies_injected"] = len(patched_label_rows)
    _write_json(stats_path, stats)

    # Refresh validated metadata
    write_validated_metadata(dataset_dir / "journal_entries_2022.csv")
    if (dataset_dir / "journal_entries_2023.csv").exists():
        write_validated_metadata(dataset_dir / "journal_entries_2023.csv")
    if (dataset_dir / "journal_entries_2024.csv").exists():
        write_validated_metadata(dataset_dir / "journal_entries_2024.csv")

    report = {
        "hotfixed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rule_definition": "ExceededApprovalLimit := document amount > approved_by.approval_limit",
        "kept_and_patched_count": len(kept_records),
        "removed_label_count": len(removed_records),
        "kept_and_patched": kept_records,
        "removed_labels": removed_records,
    }
    _write_json(dataset_dir / HOTFIX_FILENAME, report)
    return report


def main() -> None:
    for dataset_dir in DATASET_DIRS:
        report = _patch_dataset(dataset_dir)
        print(
            f"{dataset_dir}: kept={report['kept_and_patched_count']} "
            f"removed={report['removed_label_count']}"
        )


if __name__ == "__main__":
    main()
