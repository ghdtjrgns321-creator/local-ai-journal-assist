"""Build DataSynth v26 candidate with scenario-rich DuplicateEntry pairs.

This candidate keeps the production corpus unchanged and rebuilds only the
DuplicateEntry ground truth shape in a separate candidate directory.

Compared with v25, duplicates are not just generic clones. Each injected pair
has a business cause scenario such as manual re-entry, batch resubmission,
reference normalization error, correction reposting, or rounding reprocess.
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
TARGET_DIR = ROOT / "data" / "journal" / "primary" / "datasynth_v26_candidate"
TARGET_TYPES = {"DuplicateEntry", "ExactDuplicateAmount"}

SCENARIOS = [
    "manual_reentry",
    "batch_resubmission",
    "correction_repost",
    "reference_normalization_error",
    "rounding_reprocess",
    "period_close_repost",
]


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
        header_text=("header_text", "first"),
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
        & doc["amount"].between(50_000, 90_000_000)
        & doc["row_count"].between(2, 6)
    ].copy()
    eligible["source_rank"] = eligible["source"].map({"manual": 0, "recurring": 1, "automated": 2}).fillna(3)
    return eligible.sort_values(["fiscal_year", "source_rank", "posting_date", "document_id"]).reset_index(drop=True)


def _label_years(df: pd.DataFrame, target_labels: pd.DataFrame) -> pd.Series:
    doc_year = df[["document_id", "fiscal_year"]].drop_duplicates()
    labelled = target_labels[["document_id"]].merge(doc_year, on="document_id", how="left")
    return labelled["fiscal_year"].reset_index(drop=True)


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


def _safe_shift(date_value: object, shift_days: int, fiscal_year: int) -> pd.Timestamp:
    date = pd.to_datetime(date_value)
    shifted = date + timedelta(days=shift_days)
    if shifted.year != fiscal_year:
        shifted = date - timedelta(days=max(1, shift_days))
    if shifted.year != fiscal_year:
        shifted = pd.Timestamp(year=fiscal_year, month=12, day=28)
    return shifted


def _format_reference(value: object, scenario: str, sequence: int) -> object:
    ref = _normalize_text(value)
    if not ref:
        if scenario in {"manual_reentry", "reference_normalization_error"}:
            return f"MANUAL-REF-{sequence:05d}"
        return value
    if scenario == "reference_normalization_error":
        if sequence % 2 == 0:
            return ref
        return ref.replace("-", "/", 1) if "-" in ref else f"{ref}-A"
    if scenario == "correction_repost":
        if sequence % 3 == 0:
            return ref
        return f"{ref}-REV"
    if scenario == "batch_resubmission":
        return ref if sequence % 3 else f"{ref}-B2"
    if scenario == "period_close_repost":
        if sequence % 2 == 0:
            return ref
        return f"{ref}-CL"
    return ref


def _line_text(value: object, scenario: str) -> object:
    text = _normalize_text(value)
    if not text:
        return value
    suffix = {
        "manual_reentry": "manual re-entry",
        "batch_resubmission": "batch resend",
        "correction_repost": "correction repost",
        "reference_normalization_error": "reference normalized",
        "rounding_reprocess": "rounding adjustment",
        "period_close_repost": "period close repost",
    }[scenario]
    return f"{text} / {suffix}"


def _header_text(value: object, scenario: str) -> object:
    text = _normalize_text(value)
    suffix = {
        "manual_reentry": "re-entered by AP clerk",
        "batch_resubmission": "resubmitted by interface job",
        "correction_repost": "correction repost after review",
        "reference_normalization_error": "reference format normalized",
        "rounding_reprocess": "rounding difference repost",
        "period_close_repost": "period close repost",
    }[scenario]
    return f"{text} - {suffix}" if text else suffix


def _scale_duplicate_amounts(lines: pd.DataFrame, factor: float) -> pd.DataFrame:
    out = lines.copy()
    if factor == 1.0:
        return out
    for col in ("debit_amount", "credit_amount", "local_amount"):
        if col not in out.columns:
            continue
        values = pd.to_numeric(out[col], errors="coerce")
        out[col] = (values.fillna(0.0) * factor).round(0).where(values.notna(), values)
    debit_sum = float(pd.to_numeric(out["debit_amount"], errors="coerce").fillna(0).sum())
    credit_sum = float(pd.to_numeric(out["credit_amount"], errors="coerce").fillna(0).sum())
    diff = round(debit_sum - credit_sum)
    if diff > 0:
        rows = out.index[pd.to_numeric(out["credit_amount"], errors="coerce").fillna(0).gt(0)]
        if len(rows):
            out.at[rows[0], "credit_amount"] = float(out.at[rows[0], "credit_amount"]) + diff
    elif diff < 0:
        rows = out.index[pd.to_numeric(out["debit_amount"], errors="coerce").fillna(0).gt(0)]
        if len(rows):
            out.at[rows[0], "debit_amount"] = float(out.at[rows[0], "debit_amount"]) - diff
    return out


def _make_duplicate_lines(
    source_lines: pd.DataFrame,
    *,
    duplicate_doc_id: str,
    duplicate_doc_number: str,
    scenario: str,
    sequence: int,
) -> pd.DataFrame:
    rng = random.Random(f"v26:{duplicate_doc_id}:{scenario}:{sequence}")
    out = source_lines.copy()
    fiscal_year = int(out["fiscal_year"].iloc[0])
    base_date = pd.to_datetime(out["posting_date"]).min()
    shift_options = {
        "manual_reentry": [1, 2, 4, 6],
        "batch_resubmission": [0, 1, 2],
        "correction_repost": [3, 5, 9, 14],
        "reference_normalization_error": [2, 3, 7],
        "rounding_reprocess": [1, 3, 10],
        "period_close_repost": [1, 2, 5],
    }
    shifted_posting = _safe_shift(base_date, rng.choice(shift_options[scenario]), fiscal_year)
    shifted_document = _safe_shift(pd.to_datetime(out["document_date"]).min(), max(0, (shifted_posting - base_date).days - 1), fiscal_year)

    out["document_id"] = duplicate_doc_id
    out["document_number"] = duplicate_doc_number
    out["posting_date"] = shifted_posting
    out["document_date"] = shifted_document
    out["reference"] = out["reference"].map(lambda value: _format_reference(value, scenario, sequence))
    out["header_text"] = out["header_text"].map(lambda value: _header_text(value, scenario))
    out["line_text"] = out["line_text"].map(lambda value: _line_text(value, scenario))

    if scenario == "manual_reentry":
        out["source"] = "manual"
    elif scenario == "batch_resubmission":
        out["source"] = "automated"
    elif scenario == "period_close_repost":
        out["source"] = "manual" if sequence % 2 else out["source"]

    if scenario == "rounding_reprocess":
        out = _scale_duplicate_amounts(out, rng.uniform(0.996, 1.006))
    elif scenario == "correction_repost" and sequence % 2 == 0:
        out = _scale_duplicate_amounts(out, rng.uniform(0.990, 1.012))

    return out


def _patch_label_row(row: pd.Series, *, duplicate_doc_id: str, scenario: str, pair_id: str) -> pd.Series:
    patched = row.copy()
    patched["document_id"] = duplicate_doc_id
    patched["description"] = f"Duplicate entry result document ({scenario}); see pair sidecar {pair_id}"
    metadata = {
        "duplicate_entry_role": "duplicate",
        "duplicate_pair_id": pair_id,
        "duplicate_scenario": scenario,
        "rule_definition": "DuplicateEntry := repeated JE-like document with account/amount/reference/text evidence",
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
    ].head(48).copy()
    return pd.DataFrame(
        {
            "control_id": [f"DE26-NC-{i + 1:03d}" for i in range(len(controls))],
            "document_id": controls["document_id"].astype(str).values,
            "reason": ["normal_repeat_or_intercompany_not_duplicate_entry" for _ in range(len(controls))],
        }
    )


def _write_candidate_docs(validation: dict[str, object]) -> None:
    scenario_counts = validation["scenarios"]
    snapshot = validation.get("validation_snapshot", {})
    freeze = f"""# DataSynth v26 Candidate

Status: candidate, not production.

Source baseline: `data/journal/primary/datasynth` (`v23`).

## Purpose

Rebuild L2-03 `DuplicateEntry` / `ExactDuplicateAmount` labels as actual duplicate-result documents and make duplicate causes more business-like than generic cloning.

## Scenario Mix

- `manual_reentry`: `{scenario_counts.get("manual_reentry", 0)}`
- `batch_resubmission`: `{scenario_counts.get("batch_resubmission", 0)}`
- `correction_repost`: `{scenario_counts.get("correction_repost", 0)}`
- `reference_normalization_error`: `{scenario_counts.get("reference_normalization_error", 0)}`
- `rounding_reprocess`: `{scenario_counts.get("rounding_reprocess", 0)}`
- `period_close_repost`: `{scenario_counts.get("period_close_repost", 0)}`

## Summary

- Rows: `{validation["rows"]:,}`
- Documents: `{validation["documents"]:,}`
- Duplicate-entry labels: `{validation["duplicate_entry_labels"]}`
- Pair rows: `{validation["pair_rows"]}`
- Negative controls: `{validation["negative_controls"]}`
- Injected duplicate imbalance: `{snapshot.get("duplicate_imbalanced_docs", "not_checked")}`

## Validation Snapshot

- Rule code changed: `{snapshot.get("rule_code_changed", False)}`
- Labeled duplicate docs: `{snapshot.get("labeled_duplicate_docs", "not_checked")}`
- Detected docs: `{snapshot.get("detected_docs", "not_checked")}`
- TP docs: `{snapshot.get("tp_docs", "not_checked")}`
- FN docs: `{snapshot.get("fn_docs", "not_checked")}`
- FP docs: `{snapshot.get("fp_docs", "not_checked")}`
- Pair-aware detected pairs: `{snapshot.get("pair_aware_detected_pairs", "not_checked")} / {snapshot.get("pair_aware_total_pairs", "not_checked")}`

This candidate is intentionally not fitted to `0 FN / 0 FP`.
"""
    (TARGET_DIR / "FREEZE_V26_CANDIDATE.md").write_text(freeze, encoding="utf-8")

    preview = f"""# DataSynth v26 Candidate Preview

Status: candidate only. Production data remains `data/journal/primary/datasynth` until explicitly promoted.

## What Changed

`v26_candidate` improves L2-03 synthetic realism. It keeps the rule unchanged and changes only the DataSynth duplicate-entry data.

- Labels are attached to actual duplicate-result documents.
- Pair lineage is stored in `labels/duplicate_entry_pairs.csv`.
- Duplicate causes are split into business scenarios instead of simple clone variants.
- Negative controls keep normal repeat/intercompany/payment-like documents visible but unlabeled.

## Scale

- Rows: `{validation["rows"]:,}`
- Documents: `{validation["documents"]:,}`
- Duplicate-entry labels: `{validation["duplicate_entry_labels"]}`
- Pair sidecar rows: `{validation["pair_rows"]}`
- Negative controls: `{validation["negative_controls"]}`

## Scenario Mix

- `manual_reentry`: `{scenario_counts.get("manual_reentry", 0)}`
- `batch_resubmission`: `{scenario_counts.get("batch_resubmission", 0)}`
- `correction_repost`: `{scenario_counts.get("correction_repost", 0)}`
- `reference_normalization_error`: `{scenario_counts.get("reference_normalization_error", 0)}`
- `rounding_reprocess`: `{scenario_counts.get("rounding_reprocess", 0)}`
- `period_close_repost`: `{scenario_counts.get("period_close_repost", 0)}`

## Sidecars

- `labels/duplicate_entry_pairs.csv`
- `labels/duplicate_entry_pairs.json`
- `labels/duplicate_entry_negative_controls.csv`
- `labels/duplicate_entry_negative_controls.json`
- `V26_DUPLICATE_ENTRY_PATCH.json`
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
    label_years = _label_years(df, target_labels)
    if label_years.isna().any():
        missing = int(label_years.isna().sum())
        raise RuntimeError(f"cannot resolve fiscal_year for {missing} target labels")
    if len(originals) < len(target_labels):
        raise RuntimeError(f"not enough source documents: {len(originals)} < {len(target_labels)}")
    originals_by_year = {
        int(year): group.reset_index(drop=True)
        for year, group in originals.groupby("fiscal_year", sort=True)
    }
    year_offsets = {year: 0 for year in originals_by_year}
    for year, count in label_years.astype(int).value_counts().items():
        available = len(originals_by_year.get(int(year), pd.DataFrame()))
        if available < int(count):
            raise RuntimeError(f"not enough source documents for {year}: {available} < {count}")

    existing_doc_numbers = set(df["document_number"].dropna().astype(str))
    new_lines: list[pd.DataFrame] = []
    patched_labels: list[pd.Series] = []
    pair_rows: list[dict[str, object]] = []

    for sequence, (_, label_row) in enumerate(target_labels.iterrows(), start=1):
        target_year = int(label_years.iloc[sequence - 1])
        original = originals_by_year[target_year].iloc[year_offsets[target_year]]
        year_offsets[target_year] += 1
        original_doc_id = str(original["document_id"])
        scenario = SCENARIOS[(sequence - 1) % len(SCENARIOS)]
        duplicate_doc_id = f"DE26-{original_doc_id}"
        duplicate_doc_number = _next_document_number(
            existing_doc_numbers,
            str(original["company_code"]),
            int(original["fiscal_year"]),
            120_000 + sequence,
        )
        source_lines = df.loc[df["document_id"].astype(str).eq(original_doc_id)].copy()
        duplicate_lines = _make_duplicate_lines(
            source_lines,
            duplicate_doc_id=duplicate_doc_id,
            duplicate_doc_number=duplicate_doc_number,
            scenario=scenario,
            sequence=sequence,
        )
        new_lines.append(duplicate_lines)

        pair_id = f"DE26-{int(original['fiscal_year'])}-{sequence:03d}"
        patched_labels.append(
            _patch_label_row(label_row, duplicate_doc_id=duplicate_doc_id, scenario=scenario, pair_id=pair_id)
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
                "duplicate_scenario": scenario,
                "match_basis": "document_lines_and_business_context",
            }
        )

    df = pd.concat([df, *new_lines], ignore_index=True)
    labels = pd.concat([keep_labels, pd.DataFrame(patched_labels)], ignore_index=True)
    labels = labels.sort_values(["anomaly_date", "anomaly_id"], kind="stable").reset_index(drop=True)

    df.to_csv(TARGET_DIR / "journal_entries.csv", index=False)
    _write_year_splits(df)
    _write_label_sidecars(labels)

    labels_dir = TARGET_DIR / "labels"
    pair_df = pd.DataFrame(pair_rows)
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

    validation: dict[str, object] = {
        "duplicate_entry_labels": int(labels["anomaly_type"].isin(TARGET_TYPES).sum()),
        "pair_rows": len(pair_df),
        "scenarios": pair_df["duplicate_scenario"].value_counts().to_dict(),
        "negative_controls": len(controls),
        "rows": len(df),
        "documents": int(df["document_id"].nunique()),
    }
    (TARGET_DIR / "V26_DUPLICATE_ENTRY_PATCH.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_candidate_docs(validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
