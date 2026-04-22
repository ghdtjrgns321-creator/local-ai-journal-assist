from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v22_candidate"

YEARS = (2022, 2023, 2024)
VARIANT_CYCLE = ("exact", "reference_blank", "reference_variant", "date_shifted")


@dataclass
class DuplicatePair:
    pair_id: str
    year: int
    company_code: str
    vendor_code: str
    source_document_id: str
    duplicate_document_id: str
    source_document_number: str
    duplicate_document_number: str
    payment_amount: int
    original_posting_date: str
    duplicate_posting_date: str
    variant_type: str


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


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


def _copy_source_tree() -> None:
    if TARGET_DIR.exists():
        raise SystemExit(f"Target already exists: {TARGET_DIR}")
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _normalize_vendor(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("BA-"):
        return text[3:]
    return text


def _timestamp(date_text: str, time_text: str = "14:08:57") -> str:
    return f"{date_text} {time_text}"


def _date_shift(text: str, *, days: int = 0, months: int = 0) -> str:
    value = datetime.fromisoformat(text)
    year = value.year + ((value.month - 1 + months) // 12)
    month = ((value.month - 1 + months) % 12) + 1
    day = min(value.day, 28)
    shifted = value.replace(year=year, month=month, day=day) + timedelta(days=days)
    return shifted.strftime("%Y-%m-%d")


def _load_pairs() -> list[DuplicatePair]:
    raw = _read_json(SOURCE_DIR / "V20_FIXES.json").get("duplicate_payment_clones", [])
    pairs: list[DuplicatePair] = []
    for idx, row in enumerate(raw, start=1):
        year = int(row["year"])
        pairs.append(
            DuplicatePair(
                pair_id=f"DP-{year}-{idx:03d}",
                year=year,
                company_code=str(row["company_code"]),
                vendor_code=_normalize_vendor(str(row["trading_partner"])),
                source_document_id=str(row["source_document_id"]),
                duplicate_document_id=str(row["duplicate_document_id"]),
                source_document_number=str(row["source_document_number"]),
                duplicate_document_number=str(row["duplicate_document_number"]),
                payment_amount=int(float(row["payment_amount"])),
                original_posting_date="",
                duplicate_posting_date="",
                variant_type=VARIANT_CYCLE[(idx - 1) % len(VARIANT_CYCLE)],
            )
        )
    return pairs


def _pair_reference(pair: DuplicatePair) -> str:
    seq = pair.pair_id.split("-")[-1]
    return f"PAY:PAY-{pair.company_code}-{pair.year}-{seq}"


def _variant_reference(base_ref: str, variant_type: str) -> str:
    if variant_type == "reference_blank":
        return ""
    if variant_type == "reference_variant":
        return base_ref.replace("PAY:", "PAY / ", 1)
    return base_ref


def _doc_rows_index(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_doc: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_doc.setdefault(row["document_id"], []).append(row)
    return by_doc


def _write_payment_doc(
    doc_rows: list[dict[str, str]],
    *,
    company_code: str,
    vendor_code: str,
    posting_date: str,
    reference: str,
    payment_amount: int,
    header_text: str,
) -> None:
    timestamp = _timestamp(posting_date)
    approval_date = _timestamp(posting_date, "15:00:00")
    line_text = header_text
    for idx, row in enumerate(sorted(doc_rows, key=lambda r: int(r["line_number"]))):
        row["company_code"] = company_code
        row["fiscal_year"] = posting_date[:4]
        row["document_type"] = "KZ"
        row["business_process"] = "P2P"
        row["reference"] = reference
        row["posting_date"] = timestamp
        row["document_date"] = posting_date
        row["approval_date"] = approval_date
        row["trading_partner"] = vendor_code
        row["auxiliary_account_number"] = vendor_code
        row["auxiliary_account_label"] = vendor_code
        row["supporting_doc_type"] = ""
        row["delivery_date"] = ""
        row["invoice_amount"] = ""
        row["supply_amount"] = ""
        row["tax_code"] = ""
        row["tax_amount"] = ""
        row["header_text"] = header_text
        row["line_text"] = line_text
        row["has_attachment"] = "True"
        row["ip_address"] = ""
        if idx == 0:
            row["gl_account"] = "2000.0"
            row["debit_amount"] = str(payment_amount)
            row["credit_amount"] = "0"
            row["local_amount"] = str(payment_amount)
        else:
            row["gl_account"] = "1000.0"
            row["debit_amount"] = "0"
            row["credit_amount"] = str(payment_amount)
            row["local_amount"] = str(payment_amount)


def _patch_duplicate_pairs(rows: list[dict[str, str]], pairs: list[DuplicatePair]) -> None:
    by_doc = _doc_rows_index(rows)
    for idx, pair in enumerate(pairs, start=1):
        base_ref = _pair_reference(pair)
        source_date = min((row.get("posting_date") or "")[:10] for row in by_doc[pair.source_document_id])
        duplicate_date = min((row.get("posting_date") or "")[:10] for row in by_doc[pair.duplicate_document_id])
        if pair.variant_type == "date_shifted":
            duplicate_date = _date_shift(source_date, days=5)

        source_header = f"Payment {base_ref.replace('PAY:', '')} - {pair.vendor_code}"
        duplicate_header = source_header

        _write_payment_doc(
            by_doc[pair.source_document_id],
            company_code=pair.company_code,
            vendor_code=pair.vendor_code,
            posting_date=source_date,
            reference=base_ref,
            payment_amount=pair.payment_amount,
            header_text=source_header,
        )
        _write_payment_doc(
            by_doc[pair.duplicate_document_id],
            company_code=pair.company_code,
            vendor_code=pair.vendor_code,
            posting_date=duplicate_date,
            reference=_variant_reference(base_ref, pair.variant_type),
            payment_amount=pair.payment_amount,
            header_text=duplicate_header,
        )

        pair.original_posting_date = source_date
        pair.duplicate_posting_date = duplicate_date


def _build_negative_control_groups(rows: list[dict[str, str]], pairs: list[DuplicatePair]) -> list[dict[str, Any]]:
    by_doc = _doc_rows_index(rows)
    anomaly_docs = {pair.source_document_id for pair in pairs} | {pair.duplicate_document_id for pair in pairs}

    per_doc: list[tuple[str, list[dict[str, str]]]] = []
    for doc_id, doc_rows in by_doc.items():
        if doc_id in anomaly_docs:
            continue
        doc_type = doc_rows[0].get("document_type") or ""
        if doc_type != "KZ":
            continue
        per_doc.append((doc_id, doc_rows))

    per_doc.sort(key=lambda item: (item[1][0].get("company_code") or "", item[1][0].get("posting_date") or "", item[0]))

    controls: list[dict[str, Any]] = []
    docs_by_year: dict[int, list[tuple[str, list[dict[str, str]]]]] = {year: [] for year in YEARS}
    for doc_id, doc_rows in per_doc:
        year = int((doc_rows[0].get("posting_date") or "1900")[:4])
        if year in docs_by_year:
            docs_by_year[year].append((doc_id, doc_rows))

    for year in YEARS:
        groups_created = 0
        candidates = docs_by_year[year]
        cursor = 0
        while groups_created < 6 and cursor + 2 < len(candidates):
            chunk = candidates[cursor : cursor + 3]
            cursor += 3
            company = chunk[0][1][0]["company_code"]
            vendor = f"V-89{year % 100:02d}{groups_created + 1:02d}"
            amount = 120000 + (groups_created * 17500)
            posting_dates = [
                f"{year}-{month:02d}-25"
                for month in (2 + groups_created, 3 + groups_created, 4 + groups_created)
            ]
            header = f"Recurring payment schedule - {vendor}"
            for (_, doc_rows), posting_date in zip(chunk, posting_dates, strict=True):
                _write_payment_doc(
                    doc_rows,
                    company_code=company,
                    vendor_code=vendor,
                    posting_date=posting_date,
                    reference="",
                    payment_amount=amount,
                    header_text=header,
                )

            controls.append(
                {
                    "control_group_id": f"NC-{year}-{groups_created + 1:03d}",
                    "control_type": "recurring_payment_negative_control",
                    "pair_domain": "P2P",
                    "company_code": company,
                    "vendor_code": vendor,
                    "document_ids": [doc_id for doc_id, _ in chunk],
                    "document_numbers": [doc_rows[0]["document_number"] for _, doc_rows in chunk],
                    "posting_dates": posting_dates,
                    "amounts": [amount, amount, amount],
                    "reference_pattern": "blank",
                    "note": "Monthly recurring P2P payment series with same vendor and same amount; should not be treated as duplicate payment.",
                }
            )
            groups_created += 1

    return controls


def _write_pairs_sidecar(target_dir: Path, pairs: list[DuplicatePair]) -> None:
    sidecar_dir = target_dir / "labels"
    rows = [
        {
            "pair_id": pair.pair_id,
            "pair_domain": "P2P",
            "pair_label": "DuplicatePayment",
            "original_document_id": pair.source_document_id,
            "duplicate_document_id": pair.duplicate_document_id,
            "company_code": pair.company_code,
            "vendor_code": pair.vendor_code,
            "source_document_number": pair.source_document_number,
            "duplicate_document_number": pair.duplicate_document_number,
            "payment_amount": pair.payment_amount,
            "original_posting_date": pair.original_posting_date,
            "duplicate_posting_date": pair.duplicate_posting_date,
            "variant_type": pair.variant_type,
        }
        for pair in pairs
    ]
    _write_csv(sidecar_dir / "duplicate_payment_pairs.csv", list(rows[0].keys()), rows)
    _write_json(sidecar_dir / "duplicate_payment_pairs.json", rows)


def _write_negative_controls(target_dir: Path, controls: list[dict[str, Any]]) -> None:
    sidecar_dir = target_dir / "labels"
    if not controls:
        return
    csv_rows: list[dict[str, str]] = []
    for row in controls:
        out = dict(row)
        for key in ("document_ids", "document_numbers", "posting_dates", "amounts"):
            out[key] = json.dumps(out[key], ensure_ascii=False)
        csv_rows.append(out)
    _write_csv(sidecar_dir / "duplicate_payment_negative_controls.csv", list(csv_rows[0].keys()), csv_rows)
    _write_json(sidecar_dir / "duplicate_payment_negative_controls.json", controls)


def _patch_anomaly_sidecars(target_dir: Path, pairs: list[DuplicatePair]) -> None:
    pair_by_duplicate = {pair.duplicate_document_id: pair for pair in pairs}
    labels_dir = target_dir / "labels"
    _, csv_rows = _read_csv(labels_dir / "anomaly_labels.csv")
    json_rows = _read_json(labels_dir / "anomaly_labels.json")
    jsonl_rows = _read_jsonl(labels_dir / "anomaly_labels.jsonl")

    def patch_row(row: dict[str, Any]) -> dict[str, Any]:
        if row.get("anomaly_type") != "DuplicatePayment":
            return row
        pair = pair_by_duplicate.get(str(row.get("document_id", "")))
        if pair is None:
            return row
        row["document_type"] = "KZ"
        row["anomaly_date"] = pair.duplicate_posting_date
        row["description"] = f"Injected P2P duplicate payment candidate for {pair.vendor_code}"
        row["related_entities"] = json.dumps([pair.source_document_number], ensure_ascii=False)
        row["causal_reason_type"] = "EntityTargeting"
        row["causal_reason_json"] = json.dumps(
            {
                "EntityTargeting": {
                    "target_type": "Document",
                    "target_id": pair.source_document_number,
                    "target_domain": "P2P",
                }
            },
            ensure_ascii=False,
        )
        row["metadata_json"] = json.dumps(
            {
                "duplicate_payment_seed": True,
                "duplicate_payment_domain": "P2P",
                "duplicate_variant_type": pair.variant_type,
                "trading_partner": pair.vendor_code,
                "document_number": pair.duplicate_document_number,
                "source_document_number": pair.source_document_number,
            },
            ensure_ascii=False,
        )
        return row

    patched_csv = [patch_row(dict(row)) for row in csv_rows]
    patched_json = [patch_row(dict(row)) for row in json_rows]
    patched_jsonl = [patch_row(dict(row)) for row in jsonl_rows]

    fieldnames = list(patched_csv[0].keys()) if patched_csv else []
    _write_csv(labels_dir / "anomaly_labels.csv", fieldnames, patched_csv)
    _write_json(labels_dir / "anomaly_labels.json", patched_json)
    _write_jsonl(labels_dir / "anomaly_labels.jsonl", patched_jsonl)


def _write_freeze_note(target_dir: Path, pairs: list[DuplicatePair], controls: list[dict[str, Any]]) -> None:
    note = f"""# DataSynth V22 Candidate

- Frozen at: {datetime.now().astimezone().isoformat(timespec="seconds")}
- Base source: `data/journal/primary/datasynth/` freeze `v20.4`
- Scope: `B04 DuplicatePayment` P2P candidate only

## Design Choice

- This candidate rewrites `DuplicatePayment` to `P2P + KZ` payment semantics.
- Existing `DuplicatePayment` labeled documents remain the anomaly population.
- Original source documents stay unlabeled, but now form explicit P2P payment pairs.

## Candidate Changes

- duplicate payment lineage sidecar added:
  - `labels/duplicate_payment_pairs.csv`
  - `labels/duplicate_payment_pairs.json`
- pair domain changed from `TRE` to `P2P`
- duplicate documents now include mixed surface variants:
  - `exact`
  - `reference_blank`
  - `reference_variant`
  - `date_shifted`
- recurring payment negative controls added as actual `P2P + KZ` documents:
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
    (target_dir / "FREEZE_V22_CANDIDATE.md").write_text(note, encoding="utf-8")


def _patch_combined_and_yearly_files(pairs: list[DuplicatePair], controls: list[dict[str, Any]]) -> None:
    combined_path = TARGET_DIR / "journal_entries.csv"
    fields, rows = _read_csv(combined_path)
    _patch_duplicate_pairs(rows, pairs)
    _build_negative_control_groups(rows, pairs)
    _write_csv(combined_path, fields, rows)

    # Rebuild per-year files from the patched combined dataset to keep them in sync.
    for year in YEARS:
        year_rows = [row for row in rows if row["fiscal_year"] == str(year)]
        _write_csv(TARGET_DIR / f"journal_entries_{year}.csv", fields, year_rows)


def main() -> None:
    _copy_source_tree()
    pairs = _load_pairs()

    combined_path = TARGET_DIR / "journal_entries.csv"
    fields, rows = _read_csv(combined_path)
    _patch_duplicate_pairs(rows, pairs)
    controls = _build_negative_control_groups(rows, pairs)
    _write_csv(combined_path, fields, rows)

    for year in YEARS:
        year_rows = [row for row in rows if row["fiscal_year"] == str(year)]
        _write_csv(TARGET_DIR / f"journal_entries_{year}.csv", fields, year_rows)

    _patch_anomaly_sidecars(TARGET_DIR, pairs)
    _write_pairs_sidecar(TARGET_DIR, pairs)
    _write_negative_controls(TARGET_DIR, controls)
    _write_freeze_note(TARGET_DIR, pairs, controls)

    print(
        json.dumps(
            {
                "target_dir": str(TARGET_DIR),
                "duplicate_pairs": len(pairs),
                "negative_control_groups": len(controls),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
