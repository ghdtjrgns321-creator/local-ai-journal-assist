from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd


NORMAL_CONTEXT_TARGETS = {2022: 640, 2023: 620, 2024: 600}
WEEKEND_LABEL_TYPES = {"WeekendPosting"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v40 L3-05 weekend review population and normal controls.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v39_candidate")
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


def load_labels(labels_path: Path) -> tuple[set[str], dict[str, str], set[str]]:
    labels = pd.read_csv(labels_path, low_memory=False)
    weekend_labels = labels[labels["anomaly_type"].isin(WEEKEND_LABEL_TYPES)].copy()
    weekend_label_docs = set(weekend_labels["document_id"].astype(str))
    weekend_label_type_by_doc = dict(zip(weekend_labels["document_id"].astype(str), weekend_labels["anomaly_type"].astype(str)))
    all_labeled_docs = set(labels["document_id"].astype(str))
    return weekend_label_docs, weekend_label_type_by_doc, all_labeled_docs


def load_existing_normal_context(labels_dir: Path) -> set[str]:
    path = labels_dir / "normal_weekend_context.csv"
    if not path.exists():
        return set()
    ctx = pd.read_csv(path, usecols=["document_id"], low_memory=False)
    return set(ctx["document_id"].astype(str))


def classify_weekend_context(row: pd.Series) -> tuple[str, str]:
    source = str(row.get("source", "")).lower()
    doc_type = str(row.get("document_type", ""))
    bp = str(row.get("business_process", ""))
    hour = int(row.get("posting_hour", 0))
    day = int(row.get("posting_day", 0))

    if source in {"automated", "system"}:
        return "scheduled_batch", "scheduled_weekend_erp_batch"
    if source in {"recurring", "batch"}:
        return "recurring_operation", "recurring_weekend_processing"
    if day >= 26 or day <= 3:
        return "close_calendar", "month_end_or_month_start_close"
    if bp in {"O2C", "P2P"} and doc_type in {"DR", "KR", "WE", "WL"}:
        return "operational_flow", "sales_procurement_logistics_weekend_operation"
    if bp in {"TRE", "R2R", "A2R"}:
        return "backoffice_operation", "treasury_accounting_asset_weekend_operation"
    if hour < 7 or hour >= 20:
        return "extended_hours", "extended_hours_weekend_work"
    return "manual_business_need", "manual_weekend_business_need"


def build_review_records(base: Path, year: int, weekend_label_docs: set[str], weekend_label_type_by_doc: dict[str, str], all_labeled_docs: set[str], existing_normal_docs: set[str]) -> list[dict]:
    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "debit_amount",
        "credit_amount",
    ]
    df = pd.read_csv(base / f"journal_entries_{year}.csv", usecols=cols, low_memory=False, parse_dates=["posting_date"])
    df["_amount"] = df[["debit_amount", "credit_amount"]].fillna(0).max(axis=1)
    df["posting_weekday"] = df["posting_date"].dt.weekday
    df["posting_hour"] = df["posting_date"].dt.hour
    df["posting_day"] = df["posting_date"].dt.day
    weekend = df[df["posting_weekday"].ge(5)].copy()
    doc_df = (
        weekend.groupby("document_id")
        .agg(
            company_code=("company_code", "first"),
            fiscal_year=("fiscal_year", "first"),
            posting_date=("posting_date", "first"),
            posting_weekday=("posting_weekday", "first"),
            posting_hour=("posting_hour", "first"),
            posting_day=("posting_day", "first"),
            document_number=("document_number", "first"),
            document_type=("document_type", "first"),
            business_process=("business_process", "first"),
            source=("source", "first"),
            created_by=("created_by", "first"),
            max_amount=("_amount", "max"),
            line_count=("document_id", "size"),
        )
        .reset_index()
    )
    records: list[dict] = []
    for row in doc_df.sort_values(["posting_date", "document_id"]).iterrows():
        _, series = row
        doc_id = str(series["document_id"])
        context_type, reason = classify_weekend_context(series)
        is_confirmed = doc_id in weekend_label_docs
        has_any_label = doc_id in all_labeled_docs
        records.append(
            {
                "document_id": doc_id,
                "fiscal_year": int(series["fiscal_year"]),
                "company_code": series["company_code"],
                "posting_date": series["posting_date"].strftime("%Y-%m-%d %H:%M:%S"),
                "weekday": int(series["posting_weekday"]),
                "posting_hour": int(series["posting_hour"]),
                "document_number": series["document_number"],
                "document_type": series["document_type"],
                "business_process": series["business_process"],
                "source": series["source"],
                "created_by": series["created_by"],
                "max_amount": round(float(series["max_amount"]), 2),
                "line_count": int(series["line_count"]),
                "timing_rule_id": "L3-05",
                "timing_signal": "weekend_or_holiday_posting",
                "truth_basis": "weekend_review_population",
                "weekend_context_type": context_type,
                "normal_weekend_reason": reason,
                "is_confirmed_weekend_anomaly": bool(is_confirmed),
                "weekend_anomaly_type": weekend_label_type_by_doc.get(doc_id, ""),
                "has_any_anomaly_label": bool(has_any_label),
                "existing_normal_weekend_context": bool(doc_id in existing_normal_docs),
                "evaluation_policy": "review_population_not_raw_precision_denominator",
            }
        )
    return records


def select_normal_context(review_records: list[dict]) -> list[dict]:
    rng = random.Random(4005)
    selected: list[dict] = []
    context_targets = {
        "scheduled_batch": 0.32,
        "recurring_operation": 0.18,
        "close_calendar": 0.14,
        "operational_flow": 0.18,
        "backoffice_operation": 0.10,
        "extended_hours": 0.04,
        "manual_business_need": 0.04,
    }
    for year, target in NORMAL_CONTEXT_TARGETS.items():
        year_pool = [
            record for record in review_records
            if int(record["fiscal_year"]) == year
            and not record["is_confirmed_weekend_anomaly"]
            and not record["has_any_anomaly_label"]
        ]
        by_context: dict[str, list[dict]] = {}
        for record in year_pool:
            by_context.setdefault(str(record["weekend_context_type"]), []).append(record)
        year_selected: list[dict] = []
        for context, ratio in context_targets.items():
            pool = by_context.get(context, [])
            rng.shuffle(pool)
            count = min(len(pool), max(1, int(round(target * ratio))))
            year_selected.extend(pool[:count])
        if len(year_selected) < target:
            already = {r["document_id"] for r in year_selected}
            remaining = [record for record in year_pool if record["document_id"] not in already]
            rng.shuffle(remaining)
            year_selected.extend(remaining[: target - len(year_selected)])
        year_selected = year_selected[:target]
        for idx, record in enumerate(year_selected, start=1):
            item = dict(record)
            item.update(
                {
                    "control_id": f"L305NC-{year}-{idx:04d}",
                    "normal_context_type": "normal_weekend_context",
                    "expected_l305_raw_result": "true",
                    "anomaly_label_expected": "false",
                    "control_policy": "routine_weekend_or_holiday_posting_context",
                }
            )
            selected.append(item)
    return selected


def write_preview(output: Path, summary: dict) -> None:
    text = f"""# DataSynth v40 Candidate

v40 keeps v39 and adds L3-05 weekend/holiday review policy sidecars.

## Summary

- Source baseline: `datasynth_v39_candidate`
- L3-05 review population: {summary['weekend_review_population']['total']} documents
- Confirmed WeekendPosting anomalies: {summary['confirmed_weekend_anomalies']['total']} documents
- Normal weekend controls: {summary['normal_weekend_context']['total']} documents
- Policy: weekend/holiday postings are review signals, not raw anomaly precision denominator.

## Files

- `labels/weekend_review_population.csv/json`
- `labels/weekend_review_population_2022/2023/2024.csv/json`
- `labels/weekend_confirmed_anomalies.csv/json`
- `labels/normal_weekend_context.csv/json`
- `labels/normal_weekend_context_2022/2023/2024.csv/json`
- `V40_WEEKEND_REVIEW_POLICY.json`
"""
    (output / "PREVIEW.md").write_text(text, encoding="utf-8")
    (output / "FREEZE_V40_CANDIDATE.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    output = Path(args.output)
    if output.exists():
        if not args.force:
            raise FileExistsError(f"{output} already exists; pass --force")
        shutil.rmtree(output)
    shutil.copytree(source, output)

    labels_dir = output / "labels"
    weekend_label_docs, weekend_label_type_by_doc, all_labeled_docs = load_labels(labels_dir / "anomaly_labels.csv")
    existing_normal_docs = load_existing_normal_context(labels_dir)
    review_records: list[dict] = []
    for year in [2022, 2023, 2024]:
        review_records.extend(
            build_review_records(output, year, weekend_label_docs, weekend_label_type_by_doc, all_labeled_docs, existing_normal_docs)
        )
    confirmed = [record for record in review_records if record["is_confirmed_weekend_anomaly"]]
    normal_context = select_normal_context(review_records)

    write_sidecar_family(labels_dir, "weekend_review_population", review_records)
    write_sidecar_family(labels_dir, "weekend_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "normal_weekend_context", normal_context)

    summary = {
        "candidate_version": "v40_candidate",
        "source_baseline": "datasynth_v39_candidate",
        "focus": "Separate L3-05 weekend review population from confirmed WeekendPosting anomalies and normal contexts",
        "weekend_review_population": {
            "total": len(review_records),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in review_records).items())},
            "by_context": {str(k): int(v) for k, v in sorted(Counter(r["weekend_context_type"] for r in review_records).items())},
        },
        "confirmed_weekend_anomalies": {
            "total": len(confirmed),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in confirmed).items())},
        },
        "normal_weekend_context": {
            "total": len(normal_context),
            "by_year": {str(k): int(v) for k, v in sorted(Counter(r["fiscal_year"] for r in normal_context).items())},
            "by_context": {str(k): int(v) for k, v in sorted(Counter(r["weekend_context_type"] for r in normal_context).items())},
        },
        "contract": {
            "l305_review_population": "All weekend/holiday postings are review candidates.",
            "confirmed_anomaly_truth": "Only WeekendPosting labels are confirmed anomaly truth.",
            "normal_controls": "Routine weekend contexts are stored separately and must not be counted as confirmed anomaly labels.",
            "not_test_fitting": "Weekend hits are not converted into anomaly labels; sidecars preserve evaluation semantics.",
        },
    }
    (output / "V40_WEEKEND_REVIEW_POLICY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
