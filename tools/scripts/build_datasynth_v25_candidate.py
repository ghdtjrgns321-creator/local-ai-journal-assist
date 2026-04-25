"""Build DataSynth v25 candidate with realistic DuplicateEntry pairs.

The production v23/v24 lineage has DuplicateEntry labels attached to source
marker documents. This candidate keeps the corpus mostly unchanged but rewrites
DuplicateEntry labels onto actual duplicate-result documents and adds sidecar
lineage so Phase 1 evaluation can use pair-level semantics.

This script does not modify the production dataset.
"""

from __future__ import annotations

import json
import random
import shutil
from datetime import timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "journal" / "primary" / "datasynth"
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v25_candidate"
TARGET_TYPES = {"DuplicateEntry", "ExactDuplicateAmount"}
VARIANTS = ["exact", "date_shifted", "reference_variant", "near_amount", "line_text_variant"]
VALIDATION_SNAPSHOT = {
    "rule": "b05_duplicate_entry",
    "rule_code_changed": False,
    "labeled_duplicate_docs": 64,
    "detected_docs": 142,
    "tp_docs": 38,
    "fn_docs": 26,
    "fp_docs": 104,
    "pair_aware_detected_pairs": 38,
    "pair_aware_total_pairs": 64,
    "unrelated_detected_docs": 66,
    "duplicate_imbalanced_docs": 0,
    "duplicate_detected_by_variant": {
        "exact": "13/13",
        "date_shifted": "10/13",
        "reference_variant": "5/13",
        "near_amount": "7/13",
        "line_text_variant": "3/12",
    },
}


def _copy_source() -> None:
    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    shutil.copytree(SOURCE_DIR, TARGET_DIR)


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _document_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("document_id", as_index=False).agg(
        document_number=("document_number", "first"),
        company_code=("company_code", "first"),
        fiscal_year=("fiscal_year", "first"),
        posting_date=("posting_date", "min"),
        document_date=("document_date", "min"),
        document_type=("document_type", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        reference=("reference", "first"),
        trading_partner=("trading_partner", "first"),
        auxiliary_account_number=("auxiliary_account_number", "first"),
        row_count=("document_id", "size"),
        amount=("debit_amount", "sum"),
    )


def _candidate_originals(df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    labeled_docs = set(labels.loc[labels["document_id"].notna(), "document_id"].astype(str))
    doc = _document_frame(df)
    eligible = doc.loc[
        ~doc["document_id"].astype(str).isin(labeled_docs)
        & doc["document_type"].isin(["SA", "KR", "DR"])
        & doc["business_process"].isin(["R2R", "P2P", "O2C"])
        & doc["amount"].between(50_000, 75_000_000)
        & doc["row_count"].between(2, 5)
    ].copy()
    return eligible.sort_values(["fiscal_year", "posting_date", "document_id"]).reset_index(drop=True)


def _next_document_number(existing: set[str], company: str, year: int, offset: int) -> str:
    prefix = f"{company}-{year}-"
    nums = []
    for value in existing:
        if value.startswith(prefix):
            try:
                nums.append(int(value.rsplit("-", 1)[1]))
            except ValueError:
                continue
    next_num = (max(nums) if nums else 0) + offset
    candidate = f"{company}-{year}-{next_num:06d}"
    while candidate in existing:
        next_num += 1
        candidate = f"{company}-{year}-{next_num:06d}"
    existing.add(candidate)
    return candidate


def _variant_reference(reference: object, *, variant: str) -> object:
    ref = _normalize_text(reference)
    if not ref:
        return reference
    if variant == "reference_variant":
        return ref.replace("-", " / ", 1) if "-" in ref else f"{ref}-R"
    return reference


def _variant_line_text(text: object, *, variant: str) -> object:
    value = _normalize_text(text)
    if not value:
        return text
    if variant == "line_text_variant":
        return f"{value} - 재전기"
    return text


def _scale_duplicate_amounts(lines: pd.DataFrame, factor: float) -> pd.DataFrame:
    out = lines.copy()
    if factor == 1.0:
        return out
    for col in ("debit_amount", "credit_amount"):
        values = pd.to_numeric(out[col], errors="coerce")
        out[col] = (values.fillna(0.0) * factor).round(0).where(values.notna(), values)
    debit_sum = float(pd.to_numeric(out["debit_amount"], errors="coerce").fillna(0).sum())
    credit_sum = float(pd.to_numeric(out["credit_amount"], errors="coerce").fillna(0).sum())
    diff = round(debit_sum - credit_sum)
    if diff:
        if diff > 0:
            rows = out.index[pd.to_numeric(out["credit_amount"], errors="coerce").fillna(0).gt(0)]
            if len(rows):
                out.at[rows[0], "credit_amount"] = float(out.at[rows[0], "credit_amount"]) + diff
        else:
            rows = out.index[pd.to_numeric(out["debit_amount"], errors="coerce").fillna(0).gt(0)]
            if len(rows):
                out.at[rows[0], "debit_amount"] = float(out.at[rows[0], "debit_amount"]) - diff
    return out


def _make_duplicate_lines(
    source_lines: pd.DataFrame,
    *,
    duplicate_doc_id: str,
    duplicate_doc_number: str,
    variant: str,
    sequence: int,
) -> pd.DataFrame:
    rng = random.Random(f"v25:{duplicate_doc_id}:{variant}:{sequence}")
    out = source_lines.copy()
    original_date = pd.to_datetime(out["posting_date"].iloc[0])
    day_shift = 0 if variant == "exact" else rng.choice([2, 3, 5, 7, 11])
    out["document_id"] = duplicate_doc_id
    out["document_number"] = duplicate_doc_number
    out["posting_date"] = original_date + timedelta(days=day_shift)
    out["document_date"] = pd.to_datetime(out["document_date"]).min() + timedelta(days=max(day_shift - 1, 0))
    out["reference"] = out["reference"].map(lambda value: _variant_reference(value, variant=variant))
    out["line_text"] = out["line_text"].map(lambda value: _variant_line_text(value, variant=variant))
    if variant == "near_amount":
        factor = rng.uniform(0.985, 1.018)
        out = _scale_duplicate_amounts(out, factor)
    return out


def _patch_label_row(row: pd.Series, *, duplicate_doc_id: str, variant: str, pair_id: str) -> pd.Series:
    patched = row.copy()
    patched["document_id"] = duplicate_doc_id
    patched["description"] = f"Duplicate entry result document ({variant}); see pair sidecar {pair_id}"
    metadata = {
        "duplicate_entry_role": "duplicate",
        "duplicate_pair_id": pair_id,
        "duplicate_variant_type": variant,
        "rule_definition": "DuplicateEntry := repeated JE-like document with matching account/amount/text evidence",
    }
    patched["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
    return patched


def _write_label_sidecars(labels: pd.DataFrame) -> None:
    labels_dir = TARGET_DIR / "labels"
    labels.to_csv(labels_dir / "anomaly_labels.csv", index=False)
    records = labels.where(pd.notna(labels), None).to_dict(orient="records")
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
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
        subset = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)]
        path = TARGET_DIR / f"journal_entries_{year}.csv"
        if subset.empty:
            if path.exists():
                path.unlink()
            continue
        subset.to_csv(path, index=False)


def _negative_controls(doc: pd.DataFrame) -> pd.DataFrame:
    controls = doc.loc[
        doc["document_type"].isin(["IC", "KZ"])
        | doc["business_process"].isin(["TRE", "INTERCOMPANY"])
    ].head(40).copy()
    if controls.empty:
        return pd.DataFrame(columns=["control_id", "document_id", "reason"])
    return pd.DataFrame(
        {
            "control_id": [f"DE-NC-{i + 1:03d}" for i in range(len(controls))],
            "document_id": controls["document_id"].astype(str).values,
            "reason": [
                "normal_intercompany_or_payment_repeat_not_duplicate_entry"
                for _ in range(len(controls))
            ],
        }
    )


def _write_candidate_docs(validation: dict[str, object]) -> None:
    variants = validation["variants"]
    snapshot = validation["validation_snapshot"]
    freeze = f"""# DataSynth v25 Candidate

Status: candidate, not production.

Source baseline: `data/journal/primary/datasynth` (`v23`).

## Purpose

Rewrite L2-03 `DuplicateEntry` / `ExactDuplicateAmount` labels from source-marker documents to actual duplicate-result documents, while keeping the existing detection rule unchanged.

## Generated Artifacts

- `journal_entries.csv`
- `journal_entries_2022.csv`
- `journal_entries_2023.csv`
- `journal_entries_2024.csv`
- `labels/anomaly_labels.csv`
- `labels/duplicate_entry_pairs.csv`
- `labels/duplicate_entry_pairs.json`
- `labels/duplicate_entry_negative_controls.csv`
- `labels/duplicate_entry_negative_controls.json`
- `V25_DUPLICATE_ENTRY_PATCH.json`

## Summary

- Rows: `{validation["rows"]:,}`
- Documents: `{validation["documents"]:,}`
- Duplicate-entry labels: `{validation["duplicate_entry_labels"]}`
- Pair rows: `{validation["pair_rows"]}`
- Negative controls: `{validation["negative_controls"]}`
- Injected duplicate imbalance: `{snapshot["duplicate_imbalanced_docs"]}`

Variant mix:

- `exact`: `{variants.get("exact", 0)}`
- `date_shifted`: `{variants.get("date_shifted", 0)}`
- `reference_variant`: `{variants.get("reference_variant", 0)}`
- `near_amount`: `{variants.get("near_amount", 0)}`
- `line_text_variant`: `{variants.get("line_text_variant", 0)}`

## L2-03 Validation Snapshot

Existing `b05_duplicate_entry()` rule, no rule edits:

- Labeled duplicate docs: `{snapshot["labeled_duplicate_docs"]}`
- Detected docs: `{snapshot["detected_docs"]}`
- TP docs: `{snapshot["tp_docs"]}`
- FN docs: `{snapshot["fn_docs"]}`
- FP docs: `{snapshot["fp_docs"]}`
- Pair-aware detected pairs: `{snapshot["pair_aware_detected_pairs"]} / {snapshot["pair_aware_total_pairs"]}`
- Unrelated detected docs outside injected pairs: `{snapshot["unrelated_detected_docs"]}`

This candidate is intentionally not fitted to `0 FN / 0 FP`. Exact duplicates are easy, while reference/amount/text variants remain partially hard.
"""
    (TARGET_DIR / "FREEZE_V25_CANDIDATE.md").write_text(freeze, encoding="utf-8")

    detected_by_variant = snapshot["duplicate_detected_by_variant"]
    preview = f"""# DataSynth v25 Candidate Preview

Status: candidate only. Production data remains `data/journal/primary/datasynth` until explicitly promoted.

## Purpose

`v25_candidate` fixes the L2-03 `DuplicateEntry` ground-truth shape without changing the detection rule.

The previous production baseline marked some source/original documents as "to be duplicated later". That is useful as injection metadata, but it is not the document a detector should match. This candidate moves the `DuplicateEntry` / `ExactDuplicateAmount` labels onto the actual duplicate-result documents and adds explicit pair lineage.

## Scope

- Source baseline: `data/journal/primary/datasynth` (`v23`)
- Candidate path: `data/journal/primary/datasynth_v25_candidate`
- Rows: `{validation["rows"]:,}`
- Documents: `{validation["documents"]:,}`
- Duplicate-entry labels: `{validation["duplicate_entry_labels"]}`
- Duplicate-entry pair sidecar rows: `{validation["pair_rows"]}`
- Negative-control sidecar rows: `{validation["negative_controls"]}`

## L2-03 Label Semantics

- Label is attached to `duplicate_document_id`.
- `original_document_id` is retained in `labels/duplicate_entry_pairs.csv`.
- The detector may flag both the original and duplicate rows because a duplicate pair is symmetric at row level.
- Evaluation should therefore support both document-level and pair-aware views.

## Variant Mix

The candidate intentionally avoids a perfect exact-copy-only fixture.

- `exact`: `{variants.get("exact", 0)}`
- `date_shifted`: `{variants.get("date_shifted", 0)}`
- `reference_variant`: `{variants.get("reference_variant", 0)}`
- `near_amount`: `{variants.get("near_amount", 0)}`
- `line_text_variant`: `{variants.get("line_text_variant", 0)}`

## Current L2-03 Check

Using the existing `b05_duplicate_entry()` rule, with no rule changes:

- Labeled duplicate docs: `{snapshot["labeled_duplicate_docs"]}`
- Detected docs: `{snapshot["detected_docs"]}`
- Duplicate-label TP docs: `{snapshot["tp_docs"]}`
- Duplicate-label FN docs: `{snapshot["fn_docs"]}`
- Document-level FP docs: `{snapshot["fp_docs"]}`
- Pair-aware detected pairs: `{snapshot["pair_aware_detected_pairs"]} / {snapshot["pair_aware_total_pairs"]}`
- Unrelated detected docs outside injected pairs: `{snapshot["unrelated_detected_docs"]}`
- Imbalanced injected duplicate docs: `{snapshot["duplicate_imbalanced_docs"]}`

Variant-level detected duplicate docs:

- `exact`: `{detected_by_variant["exact"]}`
- `date_shifted`: `{detected_by_variant["date_shifted"]}`
- `reference_variant`: `{detected_by_variant["reference_variant"]}`
- `near_amount`: `{detected_by_variant["near_amount"]}`
- `line_text_variant`: `{detected_by_variant["line_text_variant"]}`

This is not a fitted 0-FN/0-FP fixture. It deliberately leaves hard variants and legacy naturally duplicated-looking documents so L2-03 tuning is still meaningful.

## Sidecars

- `labels/duplicate_entry_pairs.csv`
- `labels/duplicate_entry_pairs.json`
- `labels/duplicate_entry_negative_controls.csv`
- `labels/duplicate_entry_negative_controls.json`
- `V25_DUPLICATE_ENTRY_PATCH.json`

## Notes

- `journal_entries_2022.csv`, `journal_entries_2023.csv`, and `journal_entries_2024.csv` were regenerated inside the candidate folder.
- Existing production data was not overwritten.
- Existing L2-03 rule code was not modified for this candidate.
"""
    (TARGET_DIR / "PREVIEW.md").write_text(preview, encoding="utf-8")


def main() -> None:
    _copy_source()
    df = pd.read_csv(TARGET_DIR / "journal_entries.csv", parse_dates=["posting_date", "document_date"], low_memory=False)
    labels = pd.read_csv(TARGET_DIR / "labels" / "anomaly_labels.csv")
    target_mask = labels["anomaly_type"].isin(TARGET_TYPES)
    target_labels = labels.loc[target_mask].copy().reset_index(drop=True)
    keep_labels = labels.loc[~target_mask].copy()

    originals = _candidate_originals(df, labels)
    if len(originals) < len(target_labels):
        raise RuntimeError(f"not enough source documents: {len(originals)} < {len(target_labels)}")

    existing_doc_numbers = set(df["document_number"].dropna().astype(str))
    new_lines: list[pd.DataFrame] = []
    patched_labels: list[pd.Series] = []
    pair_rows: list[dict[str, object]] = []

    for sequence, (_, label_row) in enumerate(target_labels.iterrows(), start=1):
        original = originals.iloc[sequence - 1]
        original_doc_id = str(original["document_id"])
        variant = VARIANTS[(sequence - 1) % len(VARIANTS)]
        duplicate_doc_id = f"DE-{original_doc_id}"
        duplicate_doc_number = _next_document_number(
            existing_doc_numbers,
            str(original["company_code"]),
            int(original["fiscal_year"]),
            100_000 + sequence,
        )
        source_lines = df.loc[df["document_id"].astype(str).eq(original_doc_id)].copy()
        duplicate_lines = _make_duplicate_lines(
            source_lines,
            duplicate_doc_id=duplicate_doc_id,
            duplicate_doc_number=duplicate_doc_number,
            variant=variant,
            sequence=sequence,
        )
        new_lines.append(duplicate_lines)

        pair_id = f"DE-{int(original['fiscal_year'])}-{sequence:03d}"
        patched_labels.append(
            _patch_label_row(label_row, duplicate_doc_id=duplicate_doc_id, variant=variant, pair_id=pair_id)
        )
        pair_rows.append(
            {
                "duplicate_entry_pair_id": pair_id,
                "original_document_id": original_doc_id,
                "duplicate_document_id": duplicate_doc_id,
                "original_document_number": original["document_number"],
                "duplicate_document_number": duplicate_doc_number,
                "fiscal_year": int(original["fiscal_year"]),
                "company_code": original["company_code"],
                "business_process": original["business_process"],
                "document_type": original["document_type"],
                "duplicate_variant_type": variant,
                "match_basis": "document_lines",
            }
        )

    df = pd.concat([df, *new_lines], ignore_index=True)
    labels = pd.concat([keep_labels, pd.DataFrame(patched_labels)], ignore_index=True)
    labels = labels.sort_values(["anomaly_date", "anomaly_id"], kind="stable").reset_index(drop=True)

    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_label_sidecars(labels)

    pair_df = pd.DataFrame(pair_rows)
    labels_dir = TARGET_DIR / "labels"
    pair_df.to_csv(labels_dir / "duplicate_entry_pairs.csv", index=False)
    (labels_dir / "duplicate_entry_pairs.json").write_text(
        json.dumps(pair_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    controls = _negative_controls(_document_frame(df))
    controls.to_csv(labels_dir / "duplicate_entry_negative_controls.csv", index=False)
    (labels_dir / "duplicate_entry_negative_controls.json").write_text(
        json.dumps(controls.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    validation = {
        "duplicate_entry_labels": int(labels["anomaly_type"].isin(TARGET_TYPES).sum()),
        "pair_rows": len(pair_df),
        "variants": pair_df["duplicate_variant_type"].value_counts().to_dict(),
        "negative_controls": len(controls),
        "rows": len(df),
        "documents": int(df["document_id"].nunique()),
        "validation_snapshot": VALIDATION_SNAPSHOT,
    }
    (TARGET_DIR / "V25_DUPLICATE_ENTRY_PATCH.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_candidate_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
