"""Build a manifest for DataSynth v60 approval contract patch.

This script does not materialize a candidate. It only inspects the current
production DataSynth baseline and writes a patch manifest for v60.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
MANIFEST_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v60_patch_manifest"
YEARS = (2022, 2023, 2024)
APPROVAL_THRESHOLDS = [10_000_000, 100_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000, 50_000_000_000]
PATCHABLE_LABELS = {"ExceededApprovalLimit", "JustBelowThreshold"}


def _norm(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _load_doc_summary() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    usecols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_type",
        "posting_date",
        "created_by",
        "approved_by",
        "user_persona",
        "debit_amount",
    ]
    for year in YEARS:
        df = pd.read_csv(SOURCE_DIR / f"journal_entries_{year}.csv", dtype=str, usecols=usecols, low_memory=False)
        docs = df.groupby("document_id", as_index=False).agg(
            fiscal_year=("fiscal_year", "first"),
            company_code=("company_code", "first"),
            document_type=("document_type", "first"),
            posting_date=("posting_date", "first"),
            created_by=("created_by", "first"),
            approved_by=("approved_by", "first"),
            user_persona=("user_persona", "first"),
            amount=("debit_amount", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        )
        frames.append(docs)
    return pd.concat(frames, ignore_index=True)


def _load_employees() -> list[dict[str, Any]]:
    return json.loads((SOURCE_DIR / "master_data" / "employees.json").read_text(encoding="utf-8"))


def _dominant(series: pd.Series, default: str) -> str:
    values = series.dropna().astype(str).str.strip()
    values = values.loc[values.ne("")]
    if values.empty:
        return default
    return str(values.value_counts().idxmax())


def _employee_additions(doc_summary: pd.DataFrame, employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {_norm(row.get("user_id")) for row in employees if _norm(row.get("user_id"))}
    actors = set(doc_summary["created_by"].dropna().astype(str).str.strip())
    actors.update(doc_summary["approved_by"].dropna().astype(str).str.strip())
    actors.discard("")
    missing = sorted(actors - existing)
    additions: list[dict[str, Any]] = []
    for seq, actor in enumerate(missing, start=1):
        rows = doc_summary.loc[
            doc_summary["created_by"].fillna("").astype(str).str.strip().eq(actor)
            | doc_summary["approved_by"].fillna("").astype(str).str.strip().eq(actor)
        ]
        is_approver = bool(doc_summary["approved_by"].fillna("").astype(str).str.strip().eq(actor).any())
        persona = _dominant(rows.get("user_persona", pd.Series(dtype=str)), "senior_accountant")
        is_system = actor in {"SYSTEM", "IC_GENERATOR"} or persona == "automated_system"
        additions.append(
            {
                "user_id": actor,
                "employee_id": f"EMP-JE-{seq:06d}",
                "company_code": _dominant(rows.get("company_code", pd.Series(dtype=str)), "C001"),
                "display_name": actor.replace("_", " ").title(),
                "persona": "automated_system" if is_system else persona,
                "job_level": "system" if is_system else ("manager" if is_approver else "staff"),
                "job_title": "ERP System Actor" if is_system else ("JE Approver" if is_approver else "JE Preparer"),
                "approval_limit": 50_000_000_000 if is_approver and not is_system else 100_000_000,
                "can_approve_je": bool(is_approver and not is_system),
                "source": "v60_je_actor_backfill",
            }
        )
    return additions


def _approval_tier_changes(employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_limit: dict[int, list[str]] = defaultdict(list)
    for row in employees:
        user_id = _norm(row.get("user_id"))
        if not user_id:
            continue
        try:
            limit = int(float(row.get("approval_limit")))
        except (TypeError, ValueError):
            continue
        if limit in APPROVAL_THRESHOLDS:
            if row.get("can_approve_je") is True:
                by_limit[limit].append(user_id)

    changes: list[dict[str, Any]] = []
    for limit in APPROVAL_THRESHOLDS:
        if by_limit[limit]:
            continue
        candidates = []
        for row in employees:
            try:
                row_limit = int(float(row.get("approval_limit")))
            except (TypeError, ValueError):
                continue
            if row_limit == limit and _norm(row.get("user_id")):
                candidates.append(row)
        if not candidates:
            continue
        selected = sorted(candidates, key=lambda r: _norm(r.get("user_id")))[0]
        changes.append(
            {
                "user_id": _norm(selected.get("user_id")),
                "field_name": "can_approve_je",
                "old_value": str(selected.get("can_approve_je")),
                "new_value": "True",
                "approval_limit": limit,
                "reason": "ensure_current_six_tier_approval_contract_has_at_least_one_approver",
            }
        )
    return changes


def _build_limit_users(employees: list[dict[str, Any]], tier_changes: list[dict[str, Any]]) -> dict[int, list[str]]:
    promoted = {row["user_id"] for row in tier_changes}
    by_limit: dict[int, list[str]] = defaultdict(list)
    for row in employees:
        user_id = _norm(row.get("user_id"))
        if not user_id:
            continue
        try:
            limit = int(float(row.get("approval_limit")))
        except (TypeError, ValueError):
            continue
        if limit in APPROVAL_THRESHOLDS and (row.get("can_approve_je") is True or user_id in promoted):
            by_limit[limit].append(user_id)
    for users in by_limit.values():
        users.sort()
    return by_limit


def _near_target(limit: int, sequence: int, year: int) -> tuple[int, float, str]:
    ratios = [0.914, 0.936, 0.957, 0.981, 0.992]
    units = [1, 100, 1_000, 10_000, 100_000]
    ratio = ratios[(sequence + year) % len(ratios)]
    unit = units[(sequence * 3 + year) % len(units)]
    amount = int(round((limit * ratio) / unit) * unit)
    amount = max(amount, int(limit * 0.90))
    amount = min(amount, limit - unit)
    return amount, amount / limit, f"ratio_{ratio}:round_{unit}"


def _amount_patch_manifest(labels: pd.DataFrame, docs: pd.DataFrame, users_by_limit: dict[int, list[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    docs_by_id = docs.set_index("document_id")
    journal_patches: list[dict[str, Any]] = []
    label_patches: list[dict[str, Any]] = []
    target_labels = labels.loc[labels["anomaly_type"].isin(PATCHABLE_LABELS), ["document_id", "anomaly_type"]]
    for seq, row in enumerate(target_labels.itertuples(index=False), start=1):
        doc_id = str(row.document_id)
        anomaly_type = str(row.anomaly_type)
        if doc_id not in docs_by_id.index:
            continue
        doc = docs_by_id.loc[doc_id]
        amount = float(doc["amount"])
        year = int(doc["fiscal_year"])
        if anomaly_type == "ExceededApprovalLimit":
            eligible_limits = [limit for limit in APPROVAL_THRESHOLDS if limit < amount]
            approval_limit = max(eligible_limits) if eligible_limits else APPROVAL_THRESHOLDS[0]
            target_amount = amount
            target_ratio = ""
            amount_pattern = "preserve_amount"
            rule = "ExceededApprovalLimit := document_amount > approved_by.approval_limit"
        else:
            matching_limits = [limit for limit in APPROVAL_THRESHOLDS if limit * 0.90 <= amount < limit]
            approval_limit = matching_limits[0] if matching_limits else APPROVAL_THRESHOLDS[seq % 4]
            target_amount, target_ratio, amount_pattern = _near_target(approval_limit, seq, year)
            rule = "JustBelowThreshold := approved_by.approval_limit * 0.90 <= document_amount < approved_by.approval_limit"
        approver = users_by_limit[approval_limit][seq % len(users_by_limit[approval_limit])]
        journal_patches.append(
            {
                "patch_id": f"V60-JE-{seq:05d}",
                "rule_id": "L1-04" if anomaly_type == "ExceededApprovalLimit" else "L2-01",
                "anomaly_type": anomaly_type,
                "document_id": doc_id,
                "field_name": "approved_by",
                "old_value": _norm(doc["approved_by"]),
                "new_value": approver,
                "source_file": f"journal_entries_{year}.csv",
                "fiscal_year": year,
                "reason": "align_approval_label_to_employee_master_limit_contract",
                "expected_validation": rule,
            }
        )
        if anomaly_type == "JustBelowThreshold" and abs(float(target_amount) - amount) > 0.5:
            journal_patches.append(
                {
                    "patch_id": f"V60-AMT-{seq:05d}",
                    "rule_id": "L2-01",
                    "anomaly_type": anomaly_type,
                    "document_id": doc_id,
                    "field_name": "document_amount",
                    "old_value": str(amount),
                    "new_value": str(target_amount),
                    "source_file": f"journal_entries_{year}.csv",
                    "fiscal_year": year,
                    "reason": "remove_stale_300M_3B_threshold_pattern",
                    "expected_validation": rule,
                    "target_ratio": target_ratio,
                    "amount_pattern": amount_pattern,
                }
            )
        label_patches.append(
            {
                "document_id": doc_id,
                "anomaly_type": anomaly_type,
                "approved_by": approver,
                "approval_limit": approval_limit,
                "document_amount": target_amount,
                "previous_document_amount": amount,
                "target_ratio": target_ratio,
                "amount_pattern": amount_pattern,
                "rule_definition": rule,
            }
        )
    return journal_patches, label_patches


def _missing_approval_manifest(labels: pd.DataFrame, docs: pd.DataFrame, users_by_limit: dict[int, list[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    excluded_labels = {"SkippedApproval", "IncompleteApprovalChain", "ApprovalDateMissing", *PATCHABLE_LABELS}
    excluded_docs = set(labels.loc[labels["anomaly_type"].isin(excluded_labels), "document_id"].astype(str))
    existing_eal = set(labels.loc[labels["anomaly_type"].eq("ExceededApprovalLimit"), "document_id"].astype(str))
    missing = docs["approved_by"].isna() | docs["approved_by"].astype(str).str.strip().eq("")
    target = docs.loc[missing & docs["amount"].gt(APPROVAL_THRESHOLDS[0]) & ~docs["document_id"].astype(str).isin(excluded_docs)].copy()
    patches: list[dict[str, Any]] = []
    new_eal: list[dict[str, Any]] = []
    for seq, doc in enumerate(target.itertuples(index=False), start=1):
        amount = float(doc.amount)
        eligible_limits = [limit for limit in APPROVAL_THRESHOLDS if limit >= amount]
        approval_limit = min(eligible_limits) if eligible_limits else max(APPROVAL_THRESHOLDS)
        approver = users_by_limit[approval_limit][seq % len(users_by_limit[approval_limit])]
        patches.append(
            {
                "patch_id": f"V60-APPR-{seq:05d}",
                "rule_id": "approval_workflow_quality",
                "anomaly_type": "ApprovalWorkflowBackfill",
                "document_id": str(doc.document_id),
                "field_name": "approved_by",
                "old_value": "",
                "new_value": approver,
                "source_file": f"journal_entries_{int(doc.fiscal_year)}.csv",
                "fiscal_year": int(doc.fiscal_year),
                "reason": "high_value_document_should_have_approver_unless_explicit_missing_approval_truth",
                "expected_validation": "approved_by resolves to employees.user_id",
            }
        )
        if amount > approval_limit and str(doc.document_id) not in existing_eal:
            new_eal.append(
                {
                    "document_id": str(doc.document_id),
                    "anomaly_type": "ExceededApprovalLimit",
                    "fiscal_year": int(doc.fiscal_year),
                    "company_code": str(doc.company_code),
                    "document_type": str(doc.document_type),
                    "posting_date": str(doc.posting_date),
                    "approved_by": approver,
                    "approval_limit": approval_limit,
                    "document_amount": amount,
                    "previous_document_amount": amount,
                    "target_ratio": "",
                    "amount_pattern": "preserve_amount_top_limit_excess",
                    "rule_definition": "ExceededApprovalLimit := document_amount > approved_by.approval_limit",
                }
            )
    return patches, new_eal


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    docs = _load_doc_summary()
    employees = _load_employees()
    labels = pd.read_csv(SOURCE_DIR / "labels" / "anomaly_labels.csv", dtype=str)

    additions = _employee_additions(docs, employees)
    tier_changes = _approval_tier_changes(employees)
    users_by_limit = _build_limit_users(employees, tier_changes)
    missing_limits = [limit for limit in APPROVAL_THRESHOLDS if not users_by_limit.get(limit)]
    if missing_limits:
        raise SystemExit(f"missing approver tier users for limits: {missing_limits}")

    label_journal_patches, label_patches = _amount_patch_manifest(labels, docs, users_by_limit)
    workflow_patches, new_eal = _missing_approval_manifest(labels, docs, users_by_limit)
    journal_patches = label_journal_patches + workflow_patches
    all_label_patches = label_patches + new_eal

    _write_csv(MANIFEST_DIR / "employee_additions.csv", additions)
    _write_csv(MANIFEST_DIR / "employee_tier_changes.csv", tier_changes)
    _write_csv(MANIFEST_DIR / "journal_patch_manifest.csv", journal_patches)
    _write_csv(MANIFEST_DIR / "label_patch_manifest.csv", all_label_patches)

    audit = {
        "candidate_version": "v60",
        "source_baseline": "data/journal/primary/datasynth@v59",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "approval_thresholds": APPROVAL_THRESHOLDS,
        "employee_additions": len(additions),
        "employee_tier_changes": len(tier_changes),
        "journal_field_patches": len(journal_patches),
        "label_contract_patches": len(label_patches),
        "new_exceeded_approval_labels": len(new_eal),
        "missing_approved_by_high_value_backfills": len(workflow_patches),
        "anti_fitting_note": (
            "Patch fixes DataSynth approval master/label-field contradictions. "
            "It is not derived from detector outputs and keeps normal missing-approval labels separate."
        ),
    }
    (MANIFEST_DIR / "approval_master_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (MANIFEST_DIR / "included_manifests.json").write_text(
        json.dumps(
            {
                "candidate_version": "v60",
                "source_baseline": "data/journal/primary/datasynth@v59",
                "included_manifests": [
                    "employee_additions.csv",
                    "employee_tier_changes.csv",
                    "journal_patch_manifest.csv",
                    "label_patch_manifest.csv",
                ],
                "excluded_candidates": ["data/journal/primary/datasynth_v60_candidate (interrupted prior attempt)"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    plan = f"""# DataSynth v60 Patch Plan

Source baseline: `data/journal/primary/datasynth/` freeze `v59`

Candidate: `data/journal/primary/datasynth_v60_candidate/`

## Scope

- Fix DataSynth approval master consistency.
- Use current six-tier approval thresholds: `10M, 100M, 1B, 5B, 10B, 50B`.
- Backfill JE actors into `employees.json`.
- Repoint L1-04/L2-01 label documents to approvers that exist in employee master.
- Remove stale `300M` and `3B` JustBelowThreshold patterns.
- Fill high-value missing approvers except explicit missing-approval truth documents.

## Anti-Fitting

This patch is not detector-output fitting. It fixes contradictions between journal fields, employee master, and label contracts.
Confirmed anomalies, missing-approval truth, and workflow-quality backfills stay separated in manifests.

## Summary

```json
{json.dumps(audit, ensure_ascii=False, indent=2)}
```
"""
    (MANIFEST_DIR / "PATCH_PLAN.md").write_text(plan, encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
