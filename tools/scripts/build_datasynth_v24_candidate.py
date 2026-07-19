"""Build DataSynth v24 candidate with approved-by based L2-01 labels.

This candidate keeps the current production v23 baseline and patches only
JustBelowThreshold documents so that they satisfy the business definition:

    document debit total is in [approved_by.approval_limit * ratio, approval_limit)

It does not rewrite the production dataset.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
import random

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v24_candidate"
TARGET_ANOMALY = "JustBelowThreshold"
NEAR_RATIO = 0.95
MIN_RATIO = 0.902
MAX_RATIO = 0.992


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _load_employee_limits() -> tuple[dict[str, float], dict[float, list[str]]]:
    employees_path = TARGET_DIR / "master_data" / "employees.json"
    employees = json.loads(employees_path.read_text(encoding="utf-8"))
    by_user: dict[str, float] = {}
    by_limit: dict[float, list[str]] = {}
    for row in employees:
        user_id = str(row.get("user_id", "")).strip()
        if not user_id:
            continue
        raw_limit = row.get("approval_limit")
        if raw_limit in (None, "", "nan"):
            continue
        try:
            limit = float(raw_limit)
        except (TypeError, ValueError):
            continue
        if limit <= 0:
            continue
        if row.get("can_approve_je") is False:
            continue
        by_user[user_id] = limit
        by_limit.setdefault(limit, []).append(user_id)
    return by_user, by_limit


def _choose_approver(
    *,
    current_approver: object,
    current_amount: float,
    limits_by_user: dict[str, float],
    users_by_limit: dict[float, list[str]],
    sequence: int,
) -> tuple[str, float]:
    current = "" if pd.isna(current_approver) else str(current_approver).strip()
    current_limit = limits_by_user.get(current)
    if current_limit and current_limit > 0:
        return current, current_limit

    # Pick the smallest approval limit that can hold the current document after
    # scaling. This keeps the synthetic case plausible and avoids always using
    # the same high-limit approver.
    eligible_limits = sorted(limit for limit in users_by_limit if limit >= 10_000_000)
    for limit in eligible_limits:
        if limit >= max(10_000_000, current_amount):
            users = sorted(users_by_limit[limit])
            return users[sequence % len(users)], limit

    limit = max(eligible_limits)
    users = sorted(users_by_limit[limit])
    return users[sequence % len(users)], limit


def _scale_document_amounts(
    df: pd.DataFrame,
    *,
    doc_id: str,
    target_total: float,
) -> None:
    mask = df["document_id"].astype(str).eq(doc_id)
    debit = pd.to_numeric(df.loc[mask, "debit_amount"], errors="coerce").fillna(0.0)
    current_total = float(debit.sum())
    if current_total <= 0:
        return
    factor = target_total / current_total
    for col in ("debit_amount", "credit_amount"):
        values = pd.to_numeric(df.loc[mask, col], errors="coerce")
        scaled = (values.fillna(0.0) * factor).round(0)
        zero_mask = values.isna()
        df.loc[mask, col] = scaled.where(~zero_mask, values)

    # Correct rounding drift on the largest debit/credit lines so document
    # balance remains exact at whole-KRW precision.
    debit_after = pd.to_numeric(df.loc[mask, "debit_amount"], errors="coerce").fillna(0.0)
    credit_after = pd.to_numeric(df.loc[mask, "credit_amount"], errors="coerce").fillna(0.0)
    debit_sum = float(debit_after.sum())
    credit_sum = float(credit_after.sum())
    diff = round(target_total - debit_sum)
    if diff:
        debit_rows = df.loc[mask & pd.to_numeric(df["debit_amount"], errors="coerce").fillna(0).gt(0)].index
        if len(debit_rows):
            idx = pd.to_numeric(df.loc[debit_rows, "debit_amount"], errors="coerce").idxmax()
            df.at[idx, "debit_amount"] = float(df.at[idx, "debit_amount"]) + diff
    diff = round(target_total - credit_sum)
    if diff:
        credit_rows = df.loc[mask & pd.to_numeric(df["credit_amount"], errors="coerce").fillna(0).gt(0)].index
        if len(credit_rows):
            idx = pd.to_numeric(df.loc[credit_rows, "credit_amount"], errors="coerce").idxmax()
            df.at[idx, "credit_amount"] = float(df.at[idx, "credit_amount"]) + diff


def _natural_target_amount(limit: float, *, sequence: int, year: int) -> tuple[float, float, str]:
    """Return a varied just-below-limit amount.

    The amount remains inside the L2-01 band but avoids a single synthetic
    95%-of-limit pattern. Patterns are deterministic for reproducibility.
    """

    rng = random.Random(f"v24:{year}:{sequence}:{int(limit)}")
    bands = [
        (0.902, 0.919, "low_band"),
        (0.923, 0.947, "mid_band"),
        (0.951, 0.976, "upper_band"),
        (0.982, 0.992, "edge_band"),
    ]
    lo, hi, pattern = bands[sequence % len(bands)]
    ratio = rng.uniform(lo, hi)
    raw = limit * ratio

    rounding_patterns = [
        ("irregular_krw", 1),
        ("round_100", 100),
        ("round_1000", 1_000),
        ("round_10000", 10_000),
        ("invoice_like_500", 500),
        ("contract_like_100000", 100_000),
    ]
    suffix, unit = rounding_patterns[(sequence + year) % len(rounding_patterns)]
    amount = round(raw / unit) * unit

    lower = limit * 0.90
    if amount < lower:
        amount = round((lower + max(unit, 1)) / unit) * unit
    if amount >= limit:
        amount = round((limit - max(unit, 1)) / unit) * unit
    if amount < lower or amount >= limit:
        amount = limit * 0.95

    actual_ratio = float(amount) / float(limit)
    return float(amount), actual_ratio, f"{pattern}:{suffix}"


def _patch_labels(labels: pd.DataFrame, changes: list[dict[str, object]]) -> pd.DataFrame:
    by_doc = {row["document_id"]: row for row in changes}
    patched = labels.copy()
    for idx, row in patched.loc[patched["anomaly_type"].eq(TARGET_ANOMALY)].iterrows():
        doc_id = str(row["document_id"])
        change = by_doc.get(doc_id)
        if change is None:
            continue
        limit = float(change["approval_limit"])
        amount = float(change["target_amount"])
        approver = str(change["approved_by"])
        patched.at[idx, "description"] = (
            f"Adjusted total to {amount:.0f} just below approver {approver} "
            f"approval limit {limit:.0f}"
        )
        metadata = {
            "rule_definition": "JustBelowThreshold := approved_by.approval_limit * 0.90 <= document_amount < approved_by.approval_limit",
            "patched_approved_by": approver,
            "patched_approval_limit": limit,
            "document_amount": amount,
            "near_threshold_ratio": 0.90,
            "target_ratio": change["target_ratio"],
            "amount_pattern": change["amount_pattern"],
            "previous_amount": change["previous_amount"],
            "previous_approved_by": change["previous_approved_by"],
        }
        patched.at[idx, "metadata"] = json.dumps(metadata, ensure_ascii=False)
    return patched


def _write_label_sidecars(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "total_labels": len(labels),
        "by_anomaly_type": labels["anomaly_type"].value_counts().to_dict(),
        "by_category": labels["category"].value_counts().to_dict() if "category" in labels else {},
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_year_splits(df: pd.DataFrame) -> None:
    for year in (2022, 2023, 2024, 2025):
        out = TARGET_DIR / f"journal_entries_{year}.csv"
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)]
        if subset.empty:
            if out.exists():
                out.unlink()
            continue
        subset.to_csv(out, index=False)


def _write_freeze_doc(changes: list[dict[str, object]]) -> None:
    years = pd.DataFrame(changes).groupby("fiscal_year").size().to_dict()
    text = f"""# DataSynth v24 Candidate

Status: candidate, not production

Base: `data/journal/primary/datasynth/` production freeze `v23`

Purpose:
- Correct `L2-01 / JustBelowThreshold` semantics to approved-by based approval limit logic.
- Avoid regenerating the full DataSynth corpus.
- Patch only labeled `JustBelowThreshold` documents while preserving balanced journal entries.

Patch summary:
- Patched documents: `{len(changes)}`
- By year: `{years}`
- Rule definition: `approved_by.approval_limit * 0.90 <= document_amount < approved_by.approval_limit`
- Patch target ratio range: `{MIN_RATIO}` to `{MAX_RATIO}`
- Patch target amount patterns: irregular KRW, round 100/1,000/10,000, invoice-like 500, contract-like 100,000

Validation target:
- All `JustBelowThreshold` labels should match the approved-by approval-limit definition.
- Production baseline remains `v23` until this candidate is explicitly promoted.

Created: `{datetime.now().isoformat(timespec='seconds')}`
"""
    (TARGET_DIR / "FREEZE_V24_CANDIDATE.md").write_text(text, encoding="utf-8")


def _validate(
    df: pd.DataFrame,
    labels: pd.DataFrame,
    limits_by_user: dict[str, float],
    patched_docs: set[str],
) -> dict[str, object]:
    doc = df.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        amount=("debit_amount", "sum"),
        approved_by=("approved_by", "first"),
    )
    doc["approval_limit"] = doc["approved_by"].fillna("").astype(str).str.strip().map(limits_by_user).astype(float)
    doc["near"] = (
        doc["approval_limit"].notna()
        & (doc["amount"] >= doc["approval_limit"] * 0.90)
        & (doc["amount"] < doc["approval_limit"])
    )
    labeled = set(labels.loc[labels["anomaly_type"].eq(TARGET_ANOMALY), "document_id"].astype(str))
    near = set(doc.loc[doc["near"], "document_id"].astype(str))
    balance = df.groupby("document_id").agg(
        debit=("debit_amount", "sum"),
        credit=("credit_amount", "sum"),
    )
    balance["diff"] = (balance["debit"] - balance["credit"]).abs()
    unbalanced_docs = set(labels.loc[labels["anomaly_type"].eq("UnbalancedEntry"), "document_id"].astype(str))
    all_imbalance = int((balance["diff"] > 1).sum())
    clean_imbalance = int(((balance["diff"] > 1) & ~balance.index.astype(str).isin(unbalanced_docs)).sum())
    patched_imbalance = int(((balance["diff"] > 1) & balance.index.astype(str).isin(patched_docs)).sum())
    return {
        "labeled": len(labeled),
        "near_approved_limit": len(near),
        "labeled_matching": len(labeled & near),
        "labeled_not_matching": len(labeled - near),
        "near_not_labeled": len(near - labeled),
        "all_imbalanced_documents": all_imbalance,
        "clean_imbalanced_documents": clean_imbalance,
        "patched_imbalanced_documents": patched_imbalance,
    }


def main() -> None:
    _copy_source()
    limits_by_user, users_by_limit = _load_employee_limits()
    df = pd.read_csv(TARGET_DIR / "journal_entries.csv", low_memory=False)
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv")

    target_docs = labels.loc[labels["anomaly_type"].eq(TARGET_ANOMALY), "document_id"].astype(str).drop_duplicates().tolist()
    changes: list[dict[str, object]] = []
    for sequence, doc_id in enumerate(target_docs):
        mask = df["document_id"].astype(str).eq(doc_id)
        if not mask.any():
            continue
        current_amount = float(pd.to_numeric(df.loc[mask, "debit_amount"], errors="coerce").fillna(0.0).sum())
        current_approver = df.loc[mask, "approved_by"].iloc[0] if "approved_by" in df else None
        approver, limit = _choose_approver(
            current_approver=current_approver,
            current_amount=current_amount,
            limits_by_user=limits_by_user,
            users_by_limit=users_by_limit,
            sequence=sequence,
        )
        fiscal_year = int(df.loc[mask, "fiscal_year"].iloc[0])
        target_amount, target_ratio, amount_pattern = _natural_target_amount(
            limit,
            sequence=sequence,
            year=fiscal_year,
        )
        df.loc[mask, "approved_by"] = approver
        _scale_document_amounts(df, doc_id=doc_id, target_total=target_amount)
        changes.append(
            {
                "document_id": doc_id,
                "fiscal_year": fiscal_year,
                "previous_amount": current_amount,
                "target_amount": target_amount,
                "target_ratio": target_ratio,
                "amount_pattern": amount_pattern,
                "previous_approved_by": "" if pd.isna(current_approver) else str(current_approver),
                "approved_by": approver,
                "approval_limit": limit,
            }
        )

    labels = _patch_labels(labels, changes)
    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_label_sidecars(labels)
    validation = _validate(df, labels, limits_by_user, {str(row["document_id"]) for row in changes})
    validation["changes"] = changes
    (TARGET_DIR / "V24_JUST_BELOW_THRESHOLD_PATCH.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_freeze_doc(changes)
    print(json.dumps({k: v for k, v in validation.items() if k != "changes"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
