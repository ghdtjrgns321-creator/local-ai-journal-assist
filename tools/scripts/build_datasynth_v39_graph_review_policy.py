from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.detection.graph_rules import gr01_circular_transaction


IC_PREFIXES = ("1150", "2050", "4500", "2700")
NORMAL_CONTROL_COUNTS = {2022: 17, 2023: 19, 2024: 16}
GRAPH_LABEL_TYPES = {"CircularTransaction", "CircularIntercompany"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v39 GR01 review population and normal cycle controls.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v38_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict], year_key: str = "fiscal_year") -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r[year_key]) for r in records}):
        year_records = [r for r in records if int(r[year_key]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(json.dumps(year_records, ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph_labels(labels_path: Path) -> tuple[set[str], dict[str, str], set[str]]:
    labels = pd.read_csv(labels_path, low_memory=False)
    graph_labels = labels[labels["anomaly_type"].isin(GRAPH_LABEL_TYPES)].copy()
    graph_label_docs = set(graph_labels["document_id"].astype(str))
    graph_label_type_by_doc = dict(zip(graph_labels["document_id"].astype(str), graph_labels["anomaly_type"].astype(str)))
    all_labeled_docs = set(labels["document_id"].astype(str))
    return graph_label_docs, graph_label_type_by_doc, all_labeled_docs


def build_year_records(base: Path, year: int, graph_label_docs: set[str], graph_label_type_by_doc: dict[str, str], all_labeled_docs: set[str]) -> tuple[list[dict], dict]:
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_type",
        "business_process",
        "source",
        "reference",
        "trading_partner",
        "gl_account",
        "debit_amount",
        "credit_amount",
    ]
    df = pd.read_csv(base / f"journal_entries_{year}.csv", usecols=cols, low_memory=False)
    df["is_intercompany"] = df["gl_account"].astype(str).str.startswith(IC_PREFIXES)
    metadata: dict = {}
    scores = gr01_circular_transaction(df, metadata=metadata)
    hit_df = df.loc[scores.gt(0)].copy()
    hit_df["_amount"] = hit_df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    doc_df = (
        hit_df.groupby("document_id")
        .agg(
            company_code=("company_code", "first"),
            fiscal_year=("fiscal_year", "first"),
            posting_date=("posting_date", "first"),
            document_type=("document_type", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            reference=("reference", "first"),
            trading_partner=("trading_partner", lambda s: next((x for x in s.dropna().astype(str) if x.strip()), "")),
            max_amount=("_amount", "max"),
            hit_lines=("document_id", "size"),
        )
        .reset_index()
    )
    records: list[dict] = []
    for row in doc_df.sort_values(["posting_date", "document_id"]).itertuples(index=False):
        doc_id = str(row.document_id)
        is_confirmed = doc_id in graph_label_docs
        has_any_label = doc_id in all_labeled_docs
        records.append(
            {
                "document_id": doc_id,
                "fiscal_year": int(row.fiscal_year),
                "company_code": row.company_code,
                "posting_date": row.posting_date,
                "document_type": row.document_type,
                "business_process": row.business_process,
                "source": row.source,
                "reference": row.reference,
                "trading_partner": row.trading_partner,
                "max_amount": round(float(row.max_amount), 2),
                "hit_lines": int(row.hit_lines),
                "graph_rule_id": "GR01",
                "graph_signal": "n_hop_cycle_hit",
                "truth_basis": "graph_review_population",
                "is_confirmed_graph_anomaly": bool(is_confirmed),
                "graph_anomaly_type": graph_label_type_by_doc.get(doc_id, ""),
                "has_any_anomaly_label": bool(has_any_label),
                "evaluation_policy": "review_population_not_raw_precision_denominator",
                "gr01_cycles_found_year": int(metadata.get("gr01_cycles_found", 0)),
                "gr01_edges_built_year": int(metadata.get("gr01_edges_built", 0)),
            }
        )
    return records, metadata


def select_normal_controls(review_records: list[dict]) -> list[dict]:
    rng = random.Random(3901)
    controls: list[dict] = []
    for year, count in NORMAL_CONTROL_COUNTS.items():
        pool = [
            record for record in review_records
            if int(record["fiscal_year"]) == year
            and not record["is_confirmed_graph_anomaly"]
            and not record["has_any_anomaly_label"]
        ]
        # Prefer operationally routine records as normal controls. This is not a
        # detector backfill; it is a small sidecar for "cycle can be normal" tests.
        pool.sort(key=lambda r: (
            str(r["source"]).lower() not in {"automated", "system"},
            str(r["document_type"]) != "IC",
            -float(r["max_amount"]),
            str(r["document_id"]),
        ))
        top = pool[: max(count * 3, count)]
        rng.shuffle(top)
        selected = top[:count]
        if len(selected) < count:
            raise RuntimeError(f"Only selected {len(selected)}/{count} GR01 normal controls for {year}")
        for idx, record in enumerate(selected, start=1):
            item = dict(record)
            item.update(
                {
                    "control_id": f"GR01NC-{year}-{idx:04d}",
                    "normal_control_type": "normal_graph_cycle_control",
                    "expected_exception_label": "false",
                    "control_policy": "unlabeled_routine_ic_cycle_for_precision_context",
                }
            )
            controls.append(item)
    return controls


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v39 Candidate

v39 keeps v38 exception labels and adds GR01 graph review policy sidecars.

## Summary

- Source baseline: `datasynth_v38_candidate`
- GR01 review population: {summary['review_population']['total']} documents
- Confirmed GR01 anomaly labels: {summary['confirmed_graph_anomalies']['total']} documents
- Normal graph cycle controls: {summary['normal_graph_cycle_controls']['total']} documents
- Policy: GR01 hits are review population, not a raw fraud precision denominator.

## Files

- `labels/graph_gr01_review_population.csv/json`
- `labels/graph_gr01_review_population_2022/2023/2024.csv/json`
- `labels/graph_gr01_confirmed_anomalies.csv/json`
- `labels/graph_gr01_normal_cycle_controls.csv/json`
- `labels/graph_gr01_normal_cycle_controls_2022/2023/2024.csv/json`
- `V39_GRAPH_REVIEW_POLICY.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V39_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    graph_label_docs, graph_label_type_by_doc, all_labeled_docs = load_graph_labels(output / "labels" / "anomaly_labels.csv")
    review_records: list[dict] = []
    metadata_by_year: dict[str, dict] = {}
    for year in [2022, 2023, 2024]:
        year_records, metadata = build_year_records(output, year, graph_label_docs, graph_label_type_by_doc, all_labeled_docs)
        review_records.extend(year_records)
        metadata_by_year[str(year)] = {k: int(v) if isinstance(v, (int, float)) else v for k, v in metadata.items()}

    confirmed = [record for record in review_records if record["is_confirmed_graph_anomaly"]]
    controls = select_normal_controls(review_records)
    labels_dir = output / "labels"
    write_sidecar_family(labels_dir, "graph_gr01_review_population", review_records)
    write_sidecar_family(labels_dir, "graph_gr01_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "graph_gr01_normal_cycle_controls", controls)

    summary = {
        "candidate_version": "v39_candidate",
        "source_baseline": "datasynth_v38_candidate",
        "focus": "Separate GR01 review population from confirmed graph anomaly labels and normal cycle controls",
        "review_population": {
            "total": len(review_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in review_records).items())},
        },
        "confirmed_graph_anomalies": {
            "total": len(confirmed),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in confirmed).items())},
        },
        "normal_graph_cycle_controls": {
            "total": len(controls),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in controls).items())},
        },
        "metadata_by_year": metadata_by_year,
        "contract": {
            "gr01_review_population": "All GR01 hits are review candidates.",
            "confirmed_anomaly_truth": "Only CircularTransaction/CircularIntercompany labels are confirmed anomaly truth.",
            "normal_controls": "Unlabeled routine IC cycles are stored separately and must not be counted as confirmed anomaly labels.",
            "not_test_fitting": "No detector hits are converted into anomaly labels; sidecars preserve evaluation semantics.",
        },
    }
    (output / "V39_GRAPH_REVIEW_POLICY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
