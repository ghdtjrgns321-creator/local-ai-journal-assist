from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections import defaultdict
from pathlib import Path

import duckdb


MANUAL_SOURCES = ("manual", "adjustment")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build document-level manual-entry population truth sidecars.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to a datasynth dataset directory that contains journal_entries.csv and labels/anomaly_labels.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = Path(args.dataset).resolve()
    labels_dir = dataset / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)

    journal_csv = dataset / "journal_entries.csv"
    anomaly_csv = labels_dir / "anomaly_labels.csv"
    out_csv = labels_dir / "manual_entry_population_truth.csv"
    out_json = labels_dir / "manual_entry_population_truth.json"
    out_summary = labels_dir / "manual_entry_population_summary.json"

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE je AS SELECT * FROM read_csv_auto(?, header=true, sample_size=-1)",
        [str(journal_csv)],
    )
    con.execute(
        "CREATE TABLE labels AS SELECT * FROM read_csv_auto(?, header=true, sample_size=-1)",
        [str(anomaly_csv)],
    )

    rows = con.execute(
        """
        WITH doc_base AS (
            SELECT
                document_id,
                any_value(company_code) AS company_code,
                any_value(CAST(fiscal_year AS INTEGER)) AS fiscal_year,
                any_value(CAST(posting_date AS DATE)) AS posting_date,
                any_value(document_number) AS document_number,
                any_value(document_type) AS document_type,
                any_value(business_process) AS business_process,
                any_value(created_by) AS created_by,
                any_value(approved_by) AS approved_by,
                lower(any_value(source)) AS source
            FROM je
            GROUP BY document_id
        ),
        label_agg AS (
            SELECT
                document_id,
                bool_or(anomaly_type = 'ManualOverride') AS has_manualoverride_label,
                string_agg(DISTINCT anomaly_type, '|' ORDER BY anomaly_type) AS anomaly_types
            FROM labels
            GROUP BY document_id
        )
        SELECT
            b.document_id,
            b.company_code,
            b.fiscal_year,
            b.posting_date,
            b.document_number,
            b.document_type,
            b.business_process,
            b.created_by,
            b.approved_by,
            b.source,
            CASE
                WHEN b.source = 'manual' THEN 'manual'
                WHEN b.source = 'adjustment' THEN 'adjustment'
                ELSE NULL
            END AS manual_source_type,
            TRUE AS is_manual_population,
            COALESCE(l.has_manualoverride_label, FALSE) AS has_manualoverride_label,
            COALESCE(l.anomaly_types, '') AS anomaly_types
        FROM doc_base b
        LEFT JOIN label_agg l USING (document_id)
        WHERE b.source IN ('manual', 'adjustment')
        ORDER BY b.fiscal_year, b.posting_date, b.document_id
        """
    ).fetchall()

    fieldnames = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "created_by",
        "approved_by",
        "source",
        "manual_source_type",
        "is_manual_population",
        "has_manualoverride_label",
        "anomaly_types",
    ]

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(fieldnames)
        writer.writerows(rows)

    json_rows = []
    for row in rows:
        record: dict[str, object] = {}
        for idx, value in enumerate(row):
            key = fieldnames[idx]
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
            else:
                record[key] = value
        json_rows.append(record)
    out_json.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    rows_by_year: dict[int, list[dict[str, object]]] = defaultdict(list)
    for record in json_rows:
        fiscal_year = int(record["fiscal_year"])
        rows_by_year[fiscal_year].append(record)

    for fiscal_year, year_rows in sorted(rows_by_year.items()):
        year_csv = labels_dir / f"manual_entry_population_truth_{fiscal_year}.csv"
        year_json = labels_dir / f"manual_entry_population_truth_{fiscal_year}.json"
        with year_csv.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(fieldnames)
            for record in year_rows:
                writer.writerow([record[name] for name in fieldnames])
        year_json.write_text(json.dumps(year_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    year_counts: Counter[int] = Counter()
    source_counts: Counter[str] = Counter()
    process_counts: Counter[str] = Counter()
    manualoverride_overlap = 0

    for row in json_rows:
        year_counts[int(row["fiscal_year"])] += 1
        source_counts[str(row["source"])] += 1
        process_counts[str(row["business_process"] or "")] += 1
        manualoverride_overlap += int(bool(row["has_manualoverride_label"]))

    summary = {
        "dataset": str(dataset),
        "truth_type": "manual_entry_population",
        "manual_sources": list(MANUAL_SOURCES),
        "document_count": len(json_rows),
        "year_counts": {str(year): count for year, count in sorted(year_counts.items())},
        "source_counts": dict(sorted(source_counts.items())),
        "process_counts": dict(sorted(process_counts.items(), key=lambda item: (-item[1], item[0]))),
        "manualoverride_overlap_docs": manualoverride_overlap,
        "manualoverride_overlap_ratio": round(manualoverride_overlap / len(json_rows), 6) if json_rows else 0.0,
        "notes": [
            "L3-02 truth is the full manual/adjustment document population, not the ManualOverride anomaly subset.",
            "ManualOverride remains a separate anomaly label for suspicious override scenarios.",
        ],
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
