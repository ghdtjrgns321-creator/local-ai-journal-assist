from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch LatePosting date integrity into a v33 candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v32_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def read_metadata(value: object) -> dict:
    if pd.isna(value) or str(value).strip() == "":
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def dump_metadata(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def normalize_date(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d")


def normalize_datetime(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def load_labels(labels_csv: Path) -> pd.DataFrame:
    return pd.read_csv(labels_csv, low_memory=False)


def patch_journal_dates(output: Path, labels: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    journal_csv = output / "journal_entries.csv"
    je = pd.read_csv(journal_csv, low_memory=False)
    doc_dates = (
        je[["document_id", "posting_date", "document_date", "fiscal_year"]]
        .drop_duplicates("document_id")
        .copy()
    )
    doc_dates["posting_ts"] = pd.to_datetime(doc_dates["posting_date"], errors="coerce")
    doc_dates["document_ts"] = pd.to_datetime(doc_dates["document_date"], errors="coerce")
    doc_dates["actual_diff_days"] = (
        doc_dates["posting_ts"].dt.normalize() - doc_dates["document_ts"].dt.normalize()
    ).dt.days

    late_docs = set(labels.loc[labels["anomaly_type"].eq("LatePosting"), "document_id"])
    broken = doc_dates[
        doc_dates["document_id"].isin(late_docs)
        & ~(doc_dates["actual_diff_days"] > 30)
    ].copy()
    if broken.empty:
        return je, []

    label_meta_by_doc = {}
    for _, row in labels[labels["anomaly_type"].eq("LatePosting")].iterrows():
        metadata = read_metadata(row.get("metadata_json", ""))
        label_meta_by_doc[row["document_id"]] = metadata

    patch_records: list[dict] = []
    for _, row in broken.sort_values(["fiscal_year", "posting_ts", "document_id"]).iterrows():
        doc_id = row["document_id"]
        posting_ts = row["posting_ts"]
        if pd.isna(posting_ts):
            continue

        metadata = label_meta_by_doc.get(doc_id, {})
        try:
            intended_delay = int(metadata.get("delay_days", 0))
        except (TypeError, ValueError):
            intended_delay = 0
        applied_delay = max(31, min(60, intended_delay or 45))
        patched_document_date = posting_ts.normalize() - pd.Timedelta(days=applied_delay)
        previous_document_date = row["document_ts"]

        mask = je["document_id"].eq(doc_id)
        je.loc[mask, "document_date"] = normalize_date(patched_document_date)

        patch_records.append(
            {
                "document_id": doc_id,
                "fiscal_year": int(row["fiscal_year"]),
                "previous_posting_date": normalize_datetime(posting_ts),
                "previous_document_date": normalize_date(previous_document_date) if pd.notna(previous_document_date) else "",
                "patched_document_date": normalize_date(patched_document_date),
                "intended_delay_days": intended_delay,
                "applied_delay_days": applied_delay,
                "previous_actual_diff_days": int(row["actual_diff_days"]) if pd.notna(row["actual_diff_days"]) else "",
                "actual_diff_days": applied_delay,
                "patch_reason": "lateposting_clamp_repair",
            }
        )

    je.to_csv(journal_csv, index=False)
    for year, year_df in je.groupby("fiscal_year"):
        year_path = output / f"journal_entries_{int(year)}.csv"
        year_df.to_csv(year_path, index=False)

    return je, patch_records


def patch_json_journal(output: Path, patch_records: list[dict]) -> None:
    json_path = output / "journal_entries.json"
    if not json_path.exists() or not patch_records:
        return

    patch_by_doc = {record["document_id"]: record for record in patch_records}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return

    for entry in entries:
        doc_id = entry.get("document_id")
        if doc_id in patch_by_doc:
            entry["document_date"] = patch_by_doc[doc_id]["patched_document_date"]

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def patch_label_metadata(output: Path, labels: pd.DataFrame, patch_records: list[dict]) -> pd.DataFrame:
    patch_by_doc = {record["document_id"]: record for record in patch_records}
    for idx, row in labels[labels["anomaly_type"].eq("LatePosting")].iterrows():
        doc_id = row["document_id"]
        if doc_id not in patch_by_doc:
            continue
        record = patch_by_doc[doc_id]
        metadata = read_metadata(row.get("metadata_json", ""))
        metadata.update(
            {
                "lateposting_patch_version": "v33",
                "original_document_date": record["previous_document_date"],
                "intended_posting_date": record["previous_posting_date"],
                "applied_posting_date": record["previous_posting_date"],
                "patched_document_date": record["patched_document_date"],
                "intended_delay_days": str(record["intended_delay_days"]),
                "applied_delay_days": str(record["applied_delay_days"]),
                "actual_diff_days": str(record["actual_diff_days"]),
            }
        )
        labels.at[idx, "metadata_json"] = dump_metadata(metadata)
        labels.at[idx, "description"] = f"Late posting: {record['actual_diff_days']} days after transaction"
    labels.to_csv(output / "labels" / "anomaly_labels.csv", index=False)
    return labels


def rewrite_label_jsons(labels_dir: Path, labels: pd.DataFrame) -> None:
    records = []
    for _, row in labels.iterrows():
        metadata = read_metadata(row.get("metadata_json", ""))
        related = []
        related_raw = row.get("related_entities", "")
        if pd.notna(related_raw) and str(related_raw).strip():
            try:
                parsed = json.loads(str(related_raw))
                related = parsed if isinstance(parsed, list) else [str(related_raw)]
            except json.JSONDecodeError:
                related = [str(related_raw)]
        causal = None
        causal_raw = row.get("causal_reason_json", "")
        if pd.notna(causal_raw) and str(causal_raw).strip():
            try:
                causal = json.loads(str(causal_raw))
            except json.JSONDecodeError:
                causal = None
        records.append(
            {
                "anomaly_id": row["anomaly_id"],
                "anomaly_type": {row["anomaly_category"]: row["anomaly_type"]},
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "company_code": row["company_code"],
                "anomaly_date": str(row["anomaly_date"]),
                "detection_timestamp": str(row["detection_timestamp"]),
                "confidence": row["confidence"],
                "severity": int(row["severity"]) if pd.notna(row["severity"]) else None,
                "description": row["description"],
                "related_entities": related,
                "monetary_impact": None if pd.isna(row.get("monetary_impact")) or row.get("monetary_impact") == "" else row.get("monetary_impact"),
                "metadata": metadata,
                "is_injected": bool(row["is_injected"]),
                "injection_strategy": row["injection_strategy"],
                "cluster_id": None if pd.isna(row.get("cluster_id")) or row.get("cluster_id") == "" else row.get("cluster_id"),
                "causal_reason": causal,
            }
        )
    (labels_dir / "anomaly_labels.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "total_labels": int(len(labels)),
        "by_category": {k: int(v) for k, v in labels["anomaly_category"].value_counts().to_dict().items()},
        "by_company": {k: int(v) for k, v in labels["company_code"].value_counts().to_dict().items()},
        "with_provenance": int(labels["causal_reason_json"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_scenarios": int(labels["scenario_id"].fillna("").astype(str).str.len().gt(0).sum()),
        "in_clusters": int(labels["cluster_id"].fillna("").astype(str).str.len().gt(0).sum()),
    }
    (labels_dir / "anomaly_labels_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_patch_sidecars(output: Path, patch_records: list[dict], labels: pd.DataFrame) -> dict:
    labels_dir = output / "labels"
    fields = [
        "document_id",
        "fiscal_year",
        "previous_posting_date",
        "previous_document_date",
        "patched_document_date",
        "intended_delay_days",
        "applied_delay_days",
        "previous_actual_diff_days",
        "actual_diff_days",
        "patch_reason",
    ]
    sidecar = labels_dir / "lateposting_patch_cases.csv"
    with sidecar.open("w", encoding="utf-8", newline="") as fh:
        import csv

        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(patch_records)
    (labels_dir / "lateposting_patch_cases.json").write_text(
        json.dumps(patch_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for year, records in _records_by_year(patch_records).items():
        with (labels_dir / f"lateposting_patch_cases_{year}.csv").open("w", encoding="utf-8", newline="") as fh:
            import csv

            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
        (labels_dir / f"lateposting_patch_cases_{year}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "candidate_version": "v33_candidate",
        "source_baseline": "datasynth_v32_candidate",
        "focus_rule": "L3-07",
        "patched_lateposting_docs": len(patch_records),
        "patched_year_counts": dict(Counter(str(record["fiscal_year"]) for record in patch_records)),
        "lateposting_label_count": int(labels["anomaly_type"].eq("LatePosting").sum()),
        "metadata_fields_added": [
            "lateposting_patch_version",
            "original_document_date",
            "intended_posting_date",
            "applied_posting_date",
            "patched_document_date",
            "intended_delay_days",
            "applied_delay_days",
            "actual_diff_days",
        ],
    }
    (output / "V33_LATEPOSTING_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    preview = f"""# DataSynth v33 Candidate Preview

`datasynth_v33_candidate` repairs LatePosting date integrity on top of `datasynth_v32_candidate`.

## What Changed

- LatePosting documents whose actual `posting_date - document_date` was 30 days or less were patched.
- The patch changes `document_date`, preserving the original posting timestamp.
- LatePosting metadata now records intended/applied dates and `actual_diff_days`.

## Snapshot

- Patched LatePosting documents: `{len(patch_records)}`
- LatePosting labels: `{int(labels['anomaly_type'].eq('LatePosting').sum())}`
- Patch sidecar: `labels/lateposting_patch_cases.csv`

## Status

Candidate only. Not yet promoted to `data/journal/primary/datasynth/`.
"""
    (output / "PREVIEW.md").write_text(preview, encoding="utf-8")
    freeze = f"""# Freeze Note

Version: `datasynth_v33_candidate`

## Scope

This candidate fixes L3-07 `LatePosting` ground-truth integrity.

## Freeze Gate

Every `LatePosting` label must satisfy:

`posting_date - document_date > 30 days`

## Status

Candidate only. Not yet promoted to `data/journal/primary/datasynth/`.
"""
    (output / "FREEZE_V33_CANDIDATE.md").write_text(freeze, encoding="utf-8")
    return summary


def _records_by_year(records: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for record in records:
        out.setdefault(int(record["fiscal_year"]), []).append(record)
    return dict(sorted(out.items()))


def main() -> None:
    args = parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output already exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    for stale_name in ("FREEZE_V32_CANDIDATE.md",):
        stale_path = output / stale_name
        if stale_path.exists():
            stale_path.unlink()

    labels = load_labels(output / "labels" / "anomaly_labels.csv")
    _, patch_records = patch_journal_dates(output, labels)
    labels = patch_label_metadata(output, labels, patch_records)
    patch_json_journal(output, patch_records)
    rewrite_label_jsons(output / "labels", labels)
    summary = write_patch_sidecars(output, patch_records, labels)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
