from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


LABEL_TYPE = "BatchAnomaly"
RUN_SPECS = {
    2022: {
        "confirmed": {"count": 58, "timestamp": "2022-03-31 23:15:00", "source": "automated", "process": "R2R"},
        "normal": {"count": 90, "timestamp": "2022-06-15 02:10:00", "source": "recurring", "process": "H2R"},
        "boundary": {"count": 42, "timestamp": "2022-10-20 01:35:00", "source": "automated", "process": "P2P"},
    },
    2023: {
        "confirmed": {"count": 64, "timestamp": "2023-09-30 23:25:00", "source": "automated", "process": "R2R"},
        "normal": {"count": 76, "timestamp": "2023-05-16 02:05:00", "source": "recurring", "process": "H2R"},
        "boundary": {"count": 47, "timestamp": "2023-11-17 01:40:00", "source": "automated", "process": "O2C"},
    },
    2024: {
        "confirmed": {"count": 53, "timestamp": "2024-12-30 23:05:00", "source": "automated", "process": "R2R"},
        "normal": {"count": 84, "timestamp": "2024-04-15 02:20:00", "source": "recurring", "process": "H2R"},
        "boundary": {"count": 39, "timestamp": "2024-08-19 01:55:00", "source": "automated", "process": "TRE"},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v50 L4-06 batch anomaly truth candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v49_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def bool_from_timestamp(timestamp: str) -> bool:
    parsed = pd.to_datetime(timestamp, errors="coerce")
    if pd.isna(parsed):
        return False
    return int(parsed.day) >= 26 or int(parsed.day) <= 5


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for record in records for key in record}) if records else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict]) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(r["fiscal_year"]) for r in records}):
        year_records = [r for r in records if int(r["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def document_summary(df: pd.DataFrame, existing_label_docs: set[str]) -> pd.DataFrame:
    debit = pd.to_numeric(df.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    work = df.copy()
    work["_line_amount"] = pd.concat([debit, credit], axis=1).max(axis=1)
    rows: list[dict] = []
    for doc_id, group in work.groupby("document_id", sort=False):
        source = first_nonempty(group.get("source", pd.Series(dtype=object))).lower()
        process = first_nonempty(group.get("business_process", pd.Series(dtype=object)))
        if source not in {"automated", "recurring"}:
            continue
        rows.append(
            {
                "document_id": str(doc_id),
                "company_code": first_nonempty(group.get("company_code", pd.Series(dtype=object))),
                "fiscal_year": int(first_nonempty(group.get("fiscal_year", pd.Series(dtype=object)))),
                "posting_date": first_nonempty(group.get("posting_date", pd.Series(dtype=object))),
                "document_number": first_nonempty(group.get("document_number", pd.Series(dtype=object))),
                "document_type": first_nonempty(group.get("document_type", pd.Series(dtype=object))),
                "business_process": process,
                "source": source,
                "created_by": first_nonempty(group.get("created_by", pd.Series(dtype=object))),
                "approved_by": first_nonempty(group.get("approved_by", pd.Series(dtype=object))),
                "user_persona": first_nonempty(group.get("user_persona", pd.Series(dtype=object))),
                "line_count": int(len(group)),
                "max_line_amount": round(float(group["_line_amount"].max()), 2),
                "has_existing_anomaly_label": str(doc_id) in existing_label_docs,
            }
        )
    return pd.DataFrame(rows)


def choose(pool: pd.DataFrame, count: int, used: set[str], key: str) -> pd.DataFrame:
    eligible = pool[~pool["document_id"].isin(used)].drop_duplicates("document_id").copy()
    if eligible.empty:
        return eligible.head(0)
    eligible["_sort_key"] = eligible["document_id"].map(lambda value: f"{key}:{value}")
    picked = eligible.sort_values(["has_existing_anomaly_label", "max_line_amount", "_sort_key"], ascending=[True, False, True]).head(count)
    used.update(picked["document_id"].astype(str))
    return picked.drop(columns=["_sort_key"])


def patch_year(output: Path, year: int, labels_dir: Path, existing_label_docs: set[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    path = output / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    docs = document_summary(df, existing_label_docs)
    used: set[str] = set()
    confirmed_records: list[dict] = []
    review_records: list[dict] = []
    normal_records: list[dict] = []
    boundary_records: list[dict] = []
    patch_map: dict[str, dict[str, object]] = {}

    for run_type, spec in RUN_SPECS[year].items():
        pool = docs[
            docs["source"].eq(spec["source"])
            & docs["business_process"].eq(spec["process"])
        ].copy()
        if len(pool) < int(spec["count"]):
            pool = docs[docs["source"].eq(spec["source"])].copy()
        picked = choose(pool, int(spec["count"]), used, f"{year}:{run_type}")
        run_id = f"L406-{year}-{run_type.upper()}-RUN"
        is_period_end = bool_from_timestamp(str(spec["timestamp"]))
        for idx, (_, row) in enumerate(picked.iterrows(), start=1):
            patch_map[str(row["document_id"])] = {
                "posting_date": spec["timestamp"],
                "source": spec["source"],
                "business_process": spec["process"],
                "is_period_end": is_period_end,
            }
            record = {
                "case_id": f"{run_id}-{idx:04d}",
                "run_id": run_id,
                "run_type": run_type,
                "document_id": row["document_id"],
                "company_code": row["company_code"],
                "fiscal_year": year,
                "posting_date": spec["timestamp"],
                "document_number": row["document_number"],
                "document_type": row["document_type"],
                "business_process": spec["process"],
                "source": spec["source"],
                "created_by": row["created_by"],
                "approved_by": row["approved_by"],
                "user_persona": row["user_persona"],
                "line_count": int(row["line_count"]),
                "max_line_amount": row["max_line_amount"],
                "run_document_count": int(spec["count"]),
                "is_period_end": bool(is_period_end),
                "batch_signal": "period_end_batch_run" if run_type == "confirmed" else "normal_batch_run",
                "truth_basis": "L4-06 batch run review population",
                "evaluation_policy": "confirmed subset only; normal and boundary runs are controls",
            }
            review_records.append(record | {"population_id": f"L406POP-{year}-{len(review_records)+1:04d}"})
            if run_type == "confirmed":
                confirmed_records.append(
                    record
                    | {
                        "anomaly_type": LABEL_TYPE,
                        "truth_basis": "confirmed batch anomaly run with period-end concentration",
                        "evaluation_policy": "confirmed anomaly recall subset",
                    }
                )
            elif run_type == "normal":
                normal_records.append(
                    record
                    | {
                        "control_id": f"L406NC-{year}-{len(normal_records)+1:04d}",
                        "control_reason": "normal recurring automated batch run",
                        "truth_basis": "normal batch control",
                    }
                )
            else:
                boundary_records.append(
                    record
                    | {
                        "control_id": f"L406BC-{year}-{len(boundary_records)+1:04d}",
                        "control_reason": "below simultaneous-threshold batch run",
                        "truth_basis": "batch threshold boundary control",
                    }
                )

    for doc_id, patch in patch_map.items():
        mask = df["document_id"].astype(str).eq(doc_id)
        df.loc[mask, "posting_date"] = str(patch["posting_date"])
        df.loc[mask, "source"] = str(patch["source"])
        df.loc[mask, "business_process"] = str(patch["business_process"])
        if "is_period_end" in df.columns:
            df.loc[mask, "is_period_end"] = "True" if patch["is_period_end"] else "False"
    df.to_csv(path, index=False)
    return confirmed_records, review_records, normal_records, boundary_records


def append_labels(labels_dir: Path, confirmed_records: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    max_id = max(int(value.replace("ANO", "")) for value in labels["anomaly_id"].astype(str) if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed_records, start=1):
        metadata = {
            "rule_id": "L4-06",
            "case_id": record["case_id"],
            "run_id": record["run_id"],
            "run_document_count": record["run_document_count"],
            "source": record["source"],
            "business_process": record["business_process"],
            "batch_signal": record["batch_signal"],
            "truth_basis": record["truth_basis"],
            "evaluation_policy": "confirmed subset; batch_review_population is coverage only",
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "Statistical",
                "anomaly_type": LABEL_TYPE,
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.68",
                "severity": "2",
                "description": "L4-06 batch posting anomaly run",
                "is_injected": "True",
                "monetary_impact": str(record["max_line_amount"]),
                "related_entities": json.dumps([record["document_id"], record["run_id"]], ensure_ascii=False),
                "cluster_id": record["run_id"],
                "original_document_hash": "",
                "injection_strategy": "BatchAnomalyRunCoverage",
                "structured_strategy_type": LABEL_TYPE,
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "BatchRunConcentration",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": record["run_id"],
                "run_id": "",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    merged = pd.concat([labels, pd.DataFrame(new_rows, columns=labels.columns)], ignore_index=True)
    merged.to_csv(labels_path, index=False)
    merged.to_json(labels_dir / "anomaly_labels.json", orient="records", force_ascii=False, indent=2)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for row in merged.to_dict("records"):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary_path = labels_dir / "anomaly_labels_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    counts = merged["anomaly_type"].value_counts().to_dict()
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(key): int(value) for key, value in counts.items()}
    summary["v50_batch_anomaly"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "confirmed period-end batch subset only; normal and boundary batch runs remain controls",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_combined_outputs(output: Path) -> None:
    frames = [pd.read_csv(output / f"journal_entries_{year}.csv", dtype=str, low_memory=False) for year in (2022, 2023, 2024)]
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(output / "journal_entries.csv", index=False)
    combined.to_json(output / "journal_entries.json", orient="records", force_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output}")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_label_docs = set(labels["document_id"].astype(str))
    confirmed: list[dict] = []
    review: list[dict] = []
    normal: list[dict] = []
    boundary: list[dict] = []
    for year in (2022, 2023, 2024):
        c, r, n, b = patch_year(output, year, labels_dir, existing_label_docs | {x["document_id"] for x in confirmed})
        confirmed.extend(c)
        review.extend(r)
        normal.extend(n)
        boundary.extend(b)

    write_sidecar_family(labels_dir, "batch_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "batch_review_population", review)
    write_sidecar_family(labels_dir, "batch_normal_controls", normal)
    write_sidecar_family(labels_dir, "batch_boundary_controls", boundary)
    append_labels(labels_dir, confirmed)
    refresh_combined_outputs(output)

    summary = {
        str(year): {
            "confirmed": sum(int(r["fiscal_year"]) == year for r in confirmed),
            "review_population": sum(int(r["fiscal_year"]) == year for r in review),
            "normal_controls": sum(int(r["fiscal_year"]) == year for r in normal),
            "boundary_controls": sum(int(r["fiscal_year"]) == year for r in boundary),
        }
        for year in (2022, 2023, 2024)
    }
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v50_candidate",
            "source": source.name,
            "purpose": "Add L4-06 batch run truth and controls without changing detector code.",
            "summary": summary,
            "anti_fitting_policy": [
                "Confirmed labels are only period-end automated batch runs.",
                "Normal recurring batch runs remain unlabeled controls.",
                "Below-threshold batch runs test simultaneous-count boundary behavior.",
                "Future detector should use distinct document count, not row count.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "FREEZE_V50_CANDIDATE.md").write_text(
        "# DataSynth v50 Candidate\n\n"
        "L4-06 batch anomaly truth and controls patch.\n\n"
        "- Source: `datasynth_v49_candidate`\n"
        "- Adds exact batch-run timestamps to selected automated/recurring documents.\n"
        "- Adds `labels/batch_confirmed_anomalies*`.\n"
        "- Adds `labels/batch_review_population*`.\n"
        "- Adds `labels/batch_normal_controls*`.\n"
        "- Adds `labels/batch_boundary_controls*`.\n"
        "- Does not modify L4-06 detector code.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
