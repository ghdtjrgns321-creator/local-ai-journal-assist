from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v21_candidate"


@dataclass
class DuplicatePair:
    pair_id: str
    year: int
    company_code: str
    trading_partner: str
    source_document_id: str
    duplicate_document_id: str
    source_document_number: str
    duplicate_document_number: str
    payment_amount: float
    original_posting_date: str
    duplicate_posting_date: str
    variant_type: str


def _read_json(path: Path) -> Any:
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


def _load_duplicate_pairs() -> list[DuplicatePair]:
    fixes = _read_json(SOURCE_DIR / "V20_FIXES.json")
    raw_pairs = fixes.get("duplicate_payment_clones", [])
    variant_cycle = ["exact", "reference_blank", "reference_variant", "date_shifted"]
    pairs: list[DuplicatePair] = []
    for idx, row in enumerate(raw_pairs, start=1):
        pairs.append(
            DuplicatePair(
                pair_id=f"DP-{row['year']}-{idx:03d}",
                year=int(row["year"]),
                company_code=str(row["company_code"]),
                trading_partner=str(row["trading_partner"]),
                source_document_id=str(row["source_document_id"]),
                duplicate_document_id=str(row["duplicate_document_id"]),
                source_document_number=str(row["source_document_number"]),
                duplicate_document_number=str(row["duplicate_document_number"]),
                payment_amount=float(row["payment_amount"]),
                original_posting_date=str(row["posting_date"]),
                duplicate_posting_date=str(row["posting_date"]),
                variant_type=variant_cycle[(idx - 1) % len(variant_cycle)],
            )
        )
    return pairs


def _variant_reference(reference: str) -> str:
    ref = (reference or "").strip()
    if not ref:
        return ref
    return ref.replace("PAY-", "PAY / ", 1)


def _shift_datetime(text: str, days: int) -> str:
    value = (text or "").strip()
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value)
        return (dt + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.fromisoformat(value[:10])
            return (dt + timedelta(days=days)).strftime("%Y-%m-%d")
        except ValueError:
            return value


def _patch_rows(rows: list[dict[str, str]], pairs: list[DuplicatePair]) -> list[dict[str, str]]:
    pair_by_duplicate = {pair.duplicate_document_id: pair for pair in pairs}
    for row in rows:
        pair = pair_by_duplicate.get(row["document_id"])
        if pair is None:
            continue
        variant = pair.variant_type
        if variant == "reference_blank":
            row["reference"] = ""
        elif variant == "reference_variant":
            row["reference"] = _variant_reference(row.get("reference") or "")
        elif variant == "date_shifted":
            row["posting_date"] = _shift_datetime(row.get("posting_date") or "", 5)
            if (row.get("approval_date") or "").strip():
                row["approval_date"] = _shift_datetime(row.get("approval_date") or "", 5)
    return rows


def _collect_ledger_posting_dates(rows: list[dict[str, str]], pairs: list[DuplicatePair]) -> None:
    targets = {pair.source_document_id for pair in pairs} | {pair.duplicate_document_id for pair in pairs}
    posting_by_doc: dict[str, str] = {}
    for row in rows:
        did = row["document_id"]
        if did in targets and did not in posting_by_doc:
            posting_by_doc[did] = (row.get("posting_date") or "")[:10]
    for pair in pairs:
        pair.original_posting_date = posting_by_doc.get(pair.source_document_id, pair.original_posting_date)
        pair.duplicate_posting_date = posting_by_doc.get(pair.duplicate_document_id, pair.duplicate_posting_date)


def _build_negative_controls(all_rows: list[dict[str, str]], duplicate_docs: set[str]) -> list[dict[str, Any]]:
    per_doc: dict[str, dict[str, Any]] = {}
    for row in all_rows:
        did = row["document_id"]
        if did in duplicate_docs:
            continue
        rec = per_doc.setdefault(
            did,
            {
                "document_id": did,
                "company_code": row.get("company_code") or "",
                "document_number": row.get("document_number") or "",
                "document_type": row.get("document_type") or "",
                "business_process": row.get("business_process") or "",
                "auxiliary_account_number": row.get("auxiliary_account_number") or "",
                "posting_date": (row.get("posting_date") or "")[:10],
                "amount": 0.0,
            },
        )
        rec["amount"] = max(
            rec["amount"],
            float(row.get("debit_amount") or 0) + float(row.get("credit_amount") or 0),
        )

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in per_doc.values():
        if rec["document_type"] != "KZ":
            continue
        if rec["business_process"] != "TRE":
            continue
        if not rec["auxiliary_account_number"]:
            continue
        groups[(rec["company_code"], rec["auxiliary_account_number"])].append(rec)

    controls: list[dict[str, Any]] = []
    for (company_code, vendor), docs in groups.items():
        docs.sort(key=lambda d: d["posting_date"])
        months = {d["posting_date"][:7] for d in docs if d["posting_date"]}
        if len(docs) < 3 or len(months) < 3:
            continue
        sample = docs[:3]
        amounts = {int(d["amount"]) for d in sample}
        if len(amounts) < 2:
            continue
        controls.append(
            {
                "control_group_id": f"NC-{company_code}-{vendor[-6:]}",
                "company_code": company_code,
                "auxiliary_account_number": vendor,
                "document_count": len(sample),
                "document_ids": [d["document_id"] for d in sample],
                "document_numbers": [d["document_number"] for d in sample],
                "posting_dates": [d["posting_date"] for d in sample],
                "amounts": [int(d["amount"]) for d in sample],
                "control_type": "recurring_payment_negative_control",
                "note": "Same vendor has repeated KZ payments across different months with non-identical amounts.",
            }
        )
        if len(controls) >= 18:
            break
    return controls


def _write_pairs_sidecar(target_dir: Path, pairs: list[DuplicatePair]) -> None:
    rows = [
        {
            "pair_id": pair.pair_id,
            "pair_domain": "TRE",
            "pair_label": "DuplicatePayment",
            "original_document_id": pair.source_document_id,
            "duplicate_document_id": pair.duplicate_document_id,
            "company_code": pair.company_code,
            "trading_partner": pair.trading_partner,
            "source_document_number": pair.source_document_number,
            "duplicate_document_number": pair.duplicate_document_number,
            "payment_amount": int(pair.payment_amount),
            "original_posting_date": pair.original_posting_date,
            "duplicate_posting_date": pair.duplicate_posting_date,
            "variant_type": pair.variant_type,
        }
        for pair in pairs
    ]
    fieldnames = list(rows[0].keys()) if rows else []
    sidecar_dir = target_dir / "labels"
    _write_csv(sidecar_dir / "duplicate_payment_pairs.csv", fieldnames, rows)
    _write_json(sidecar_dir / "duplicate_payment_pairs.json", rows)


def _write_negative_controls(target_dir: Path, controls: list[dict[str, Any]]) -> None:
    if not controls:
        return
    fieldnames = [
        "control_group_id",
        "company_code",
        "auxiliary_account_number",
        "document_count",
        "document_ids",
        "document_numbers",
        "posting_dates",
        "amounts",
        "control_type",
        "note",
    ]
    csv_rows = []
    for row in controls:
        out = dict(row)
        for key in ["document_ids", "document_numbers", "posting_dates", "amounts"]:
            out[key] = json.dumps(out[key], ensure_ascii=False)
        csv_rows.append(out)
    sidecar_dir = target_dir / "labels"
    _write_csv(sidecar_dir / "duplicate_payment_negative_controls.csv", fieldnames, csv_rows)
    _write_json(sidecar_dir / "duplicate_payment_negative_controls.json", controls)


def _write_freeze_note(target_dir: Path, pairs: list[DuplicatePair], controls: list[dict[str, Any]]) -> None:
    note = f"""# DataSynth V21 Candidate

- Frozen at: {datetime.now().astimezone().isoformat(timespec="seconds")}
- Base source: `data/journal/primary/datasynth/` freeze `v20.4`
- Scope: `B04 DuplicatePayment` realism candidate only

## Design Choice

- This candidate keeps `DuplicatePayment` in `TRE + KZ` semantics.
- It does **not** migrate the pattern to full P2P AP payment flow yet.
- Main purpose: add lineage visibility, mild surface variation, and explicit negative controls without changing the production baseline.

## Candidate Changes

- duplicate payment lineage sidecar added:
  - `labels/duplicate_payment_pairs.csv`
  - `labels/duplicate_payment_pairs.json`
- duplicate documents now include mixed surface variants:
  - `exact`
  - `reference_blank`
  - `reference_variant`
  - `date_shifted`
- recurring payment negative controls added:
  - `labels/duplicate_payment_negative_controls.csv`
  - `labels/duplicate_payment_negative_controls.json`

## Snapshot

- labeled duplicate documents: {len(pairs)}
- lineage pairs: {len(pairs)}
- recurring negative-control groups: {len(controls)}

## Caution

- This is an evaluation candidate, not the production baseline.
- Current production baseline remains `data/journal/primary/datasynth/`.
"""
    (target_dir / "FREEZE_V21_CANDIDATE.md").write_text(note, encoding="utf-8")


def main() -> None:
    if not TARGET_DIR.exists():
        raise SystemExit(f"Target directory does not exist: {TARGET_DIR}")

    pairs = _load_duplicate_pairs()

    # Patch combined journal entries
    journal_path = TARGET_DIR / "journal_entries.csv"
    fields, rows = _read_csv(journal_path)
    rows = _patch_rows(rows, pairs)
    _collect_ledger_posting_dates(rows, pairs)
    _write_csv(journal_path, fields, rows)

    # Patch year-sliced files
    for year in ("2022", "2023", "2024"):
        year_path = TARGET_DIR / f"journal_entries_{year}.csv"
        year_fields, year_rows = _read_csv(year_path)
        year_rows = _patch_rows(year_rows, pairs)
        _write_csv(year_path, year_fields, year_rows)

    duplicate_docs = {pair.duplicate_document_id for pair in pairs}
    negative_controls = _build_negative_controls(rows, duplicate_docs)

    _write_pairs_sidecar(TARGET_DIR, pairs)
    _write_negative_controls(TARGET_DIR, negative_controls)
    _write_freeze_note(TARGET_DIR, pairs, negative_controls)

    print(
        json.dumps(
            {
                "target_dir": str(TARGET_DIR),
                "duplicate_pairs": len(pairs),
                "negative_control_groups": len(negative_controls),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
