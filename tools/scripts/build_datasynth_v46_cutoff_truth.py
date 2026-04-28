from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd
from pandas.tseries.offsets import BDay


REVENUE_LABEL = "RevenueCutoffMismatch"
EXPENSE_LABEL = "ExpenseCutoffMismatch"
REVENUE_PREFIXES = ("4",)
EXPENSE_PREFIXES = ("5",)
REVENUE_CUTOFF_DAYS = 5
EXPENSE_CUTOFF_DAYS = 7

TARGETS = {
    2022: {"revenue": 23, "expense": 11, "normal": 78, "reasonable_delay": 6, "untestable": 120},
    2023: {"revenue": 28, "expense": 15, "normal": 91, "reasonable_delay": 9, "untestable": 135},
    2024: {"revenue": 20, "expense": 13, "normal": 84, "reasonable_delay": 5, "untestable": 128},
}

REVENUE_DIFFS = [6, 7, 8, 10, 12, 14, 17, 21]
EXPENSE_DIFFS = [8, 9, 10, 12, 15, 18]
NORMAL_REVENUE_DIFFS = [0, 1, 2, 3, 4, 5]
NORMAL_EXPENSE_DIFFS = [0, 1, 2, 3, 4, 5, 6, 7]
REASONABLE_DELAY_DIFFS = [8, 9, 11, 13]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v46 L3-11 cutoff truth and controls.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally production datasynth v45")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)


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


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


def doc_candidates(df: pd.DataFrame, existing_label_docs: set[str], prefixes: tuple[str, ...]) -> pd.DataFrame:
    work = df.copy()
    work["_account_code"] = account_code(work["gl_account"])
    work["_target_line"] = work["_account_code"].str.startswith(prefixes)
    target_docs = set(work.loc[work["_target_line"], "document_id"].astype(str))
    rows: list[dict] = []
    for doc_id, group in work[work["document_id"].astype(str).isin(target_docs)].groupby("document_id", sort=False):
        if str(doc_id) in existing_label_docs:
            continue
        target_lines = group[group["_target_line"]]
        posting = pd.to_datetime(first_nonempty(group["posting_date"]), errors="coerce")
        if pd.isna(posting):
            continue
        rows.append(
            {
                "document_id": str(doc_id),
                "company_code": first_nonempty(group["company_code"]),
                "fiscal_year": int(first_nonempty(group["fiscal_year"])),
                "posting_date": posting,
                "document_type": first_nonempty(group["document_type"]),
                "business_process": first_nonempty(group["business_process"]),
                "source": first_nonempty(group["source"]),
                "created_by": first_nonempty(group["created_by"]),
                "document_number": first_nonempty(group["document_number"]),
                "matched_accounts": "|".join(sorted(set(target_lines["_account_code"].astype(str)))),
            }
        )
    return pd.DataFrame(rows)


def choose(pool: pd.DataFrame, year: int, key: str, count: int, used: set[str]) -> pd.DataFrame:
    if count <= 0:
        return pool.head(0).copy()
    eligible = pool[~pool["document_id"].isin(used)].drop_duplicates("document_id").copy()
    if eligible.empty:
        return eligible
    eligible["_sort_key"] = eligible["document_id"].map(lambda value: f"{year}:{key}:{value}")
    picked = eligible.sort_values(["posting_date", "_sort_key"]).head(count).drop(columns=["_sort_key"])
    used.update(picked["document_id"].astype(str))
    return picked


def event_date(posting: pd.Timestamp, diff_days: int, direction: str) -> pd.Timestamp:
    if direction == "posted_before_event":
        return posting + BDay(diff_days)
    return posting - BDay(diff_days)


def scenario_record(
    row: pd.Series,
    *,
    case_id: str,
    cutoff_class: str,
    label_type: str,
    business_day_diff: int,
    direction: str,
    truth_basis: str,
    normal_reason: str = "",
) -> dict:
    delivery = event_date(row["posting_date"], business_day_diff, direction)
    return {
        "case_id": case_id,
        "document_id": row["document_id"],
        "company_code": row["company_code"],
        "fiscal_year": int(row["fiscal_year"]),
        "posting_date": row["posting_date"].strftime("%Y-%m-%d"),
        "delivery_date": delivery.strftime("%Y-%m-%d"),
        "document_type": row["document_type"],
        "business_process": row["business_process"],
        "source": row["source"],
        "created_by": row["created_by"],
        "document_number": row["document_number"],
        "matched_accounts": row["matched_accounts"],
        "cutoff_class": cutoff_class,
        "anomaly_type": label_type,
        "business_day_diff": business_day_diff,
        "direction": direction,
        "truth_basis": truth_basis,
        "normal_reason": normal_reason,
    }


def build_year(output: Path, year: int, existing_label_docs: set[str]) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    path = output / f"journal_entries_{year}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    revenue_pool = doc_candidates(df, existing_label_docs, REVENUE_PREFIXES)
    expense_pool = doc_candidates(df, existing_label_docs, EXPENSE_PREFIXES)

    used: set[str] = set()
    targets = TARGETS[year]
    picked_revenue = choose(
        revenue_pool[revenue_pool["business_process"].isin(["O2C", "R2R"])],
        year,
        "revenue_cutoff",
        targets["revenue"],
        used,
    )
    picked_expense = choose(
        expense_pool[expense_pool["business_process"].isin(["P2P", "R2R", "H2R"])],
        year,
        "expense_cutoff",
        targets["expense"],
        used,
    )
    normal_pool = pd.concat([revenue_pool, expense_pool], ignore_index=True)
    picked_normal = choose(normal_pool, year, "normal_cutoff_boundary", targets["normal"], used)
    picked_delay = choose(normal_pool, year, "reasonable_delay_control", targets["reasonable_delay"], used)
    picked_untestable = choose(normal_pool, year, "untestable_missing_event_date", targets["untestable"], used)

    confirmed: list[dict] = []
    review_population: list[dict] = []
    normal_controls: list[dict] = []
    reasonable_delay_controls: list[dict] = []
    untestable_controls: list[dict] = []

    patch_by_doc: dict[str, str] = {}
    for idx, (_, row) in enumerate(picked_revenue.iterrows(), start=1):
        diff = REVENUE_DIFFS[(idx + year) % len(REVENUE_DIFFS)]
        direction = "posted_before_event" if idx % 3 != 0 else "posted_after_event"
        record = scenario_record(
            row,
            case_id=f"L311REV-{year}-{idx:04d}",
            cutoff_class="revenue_cutoff",
            label_type=REVENUE_LABEL,
            business_day_diff=diff,
            direction=direction,
            truth_basis="confirmed revenue cutoff mismatch",
        )
        confirmed.append(record)
        review_population.append(record | {"population_id": f"L311POP-{year}-{len(review_population)+1:04d}"})
        patch_by_doc[row["document_id"]] = record["delivery_date"]

    for idx, (_, row) in enumerate(picked_expense.iterrows(), start=1):
        diff = EXPENSE_DIFFS[(idx + year) % len(EXPENSE_DIFFS)]
        direction = "posted_after_event" if idx % 2 else "posted_before_event"
        record = scenario_record(
            row,
            case_id=f"L311EXP-{year}-{idx:04d}",
            cutoff_class="expense_cutoff",
            label_type=EXPENSE_LABEL,
            business_day_diff=diff,
            direction=direction,
            truth_basis="confirmed expense cutoff mismatch",
        )
        confirmed.append(record)
        review_population.append(record | {"population_id": f"L311POP-{year}-{len(review_population)+1:04d}"})
        patch_by_doc[row["document_id"]] = record["delivery_date"]

    for idx, (_, row) in enumerate(picked_normal.iterrows(), start=1):
        is_revenue = str(row["matched_accounts"]).startswith("4")
        diffs = NORMAL_REVENUE_DIFFS if is_revenue else NORMAL_EXPENSE_DIFFS
        diff = diffs[(idx + year) % len(diffs)]
        direction = "posted_after_event" if idx % 2 else "posted_before_event"
        label_type = "NormalRevenueCutoffBoundary" if is_revenue else "NormalExpenseCutoffBoundary"
        record = scenario_record(
            row,
            case_id=f"L311NC-{year}-{idx:04d}",
            cutoff_class="normal_boundary",
            label_type=label_type,
            business_day_diff=diff,
            direction=direction,
            truth_basis="normal cutoff boundary control",
            normal_reason="within_configured_cutoff_window",
        )
        normal_controls.append(record)
        patch_by_doc[row["document_id"]] = record["delivery_date"]

    for idx, (_, row) in enumerate(picked_delay.iterrows(), start=1):
        diff = REASONABLE_DELAY_DIFFS[(idx + year) % len(REASONABLE_DELAY_DIFFS)]
        direction = "posted_after_event" if idx % 2 else "posted_before_event"
        record = scenario_record(
            row,
            case_id=f"L311RD-{year}-{idx:04d}",
            cutoff_class="reasonable_delay_control",
            label_type="NormalLongCutoffDelay",
            business_day_diff=diff,
            direction=direction,
            truth_basis="normal long-delay control",
            normal_reason="contractual_acceptance_or_late_vendor_documentation",
        )
        reasonable_delay_controls.append(record)
        review_population.append(record | {"population_id": f"L311POP-{year}-{len(review_population)+1:04d}"})
        patch_by_doc[row["document_id"]] = record["delivery_date"]

    for idx, (_, row) in enumerate(picked_untestable.iterrows(), start=1):
        untestable_controls.append(
            {
                "case_id": f"L311UT-{year}-{idx:04d}",
                "document_id": row["document_id"],
                "company_code": row["company_code"],
                "fiscal_year": int(row["fiscal_year"]),
                "posting_date": row["posting_date"].strftime("%Y-%m-%d"),
                "document_type": row["document_type"],
                "business_process": row["business_process"],
                "source": row["source"],
                "created_by": row["created_by"],
                "document_number": row["document_number"],
                "matched_accounts": row["matched_accounts"],
                "truth_basis": "untestable because recognition-basis event date is absent",
                "normal_reason": "missing_delivery_date_is_unknown_not_normal",
            }
        )

    if patch_by_doc:
        mask = df["document_id"].astype(str).isin(patch_by_doc)
        df.loc[mask, "delivery_date"] = df.loc[mask, "document_id"].astype(str).map(patch_by_doc)
        # Keep evidence fields realistic when a source-event date is available.
        if "supporting_doc_type" in df.columns:
            df.loc[mask & df["supporting_doc_type"].isna(), "supporting_doc_type"] = "delivery_note"
        df.to_csv(path, index=False)

    return confirmed, review_population, normal_controls, reasonable_delay_controls, untestable_controls


def append_anomaly_labels(labels_dir: Path, confirmed: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    existing_ids = labels["anomaly_id"].astype(str)
    max_id = max(int(value.replace("ANO", "")) for value in existing_ids if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed, start=1):
        metadata = {
            "rule_id": "L3-11",
            "case_id": record["case_id"],
            "cutoff_class": record["cutoff_class"],
            "business_day_diff": record["business_day_diff"],
            "direction": record["direction"],
            "posting_date": record["posting_date"],
            "delivery_date": record["delivery_date"],
            "matched_accounts": record["matched_accounts"],
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "ReviewSignal",
                "anomaly_type": record["anomaly_type"],
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.74",
                "severity": "3",
                "description": f"L3-11 cutoff mismatch: {record['cutoff_class']} {record['business_day_diff']} business days",
                "is_injected": "True",
                "monetary_impact": "",
                "related_entities": json.dumps([record["document_id"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": "CutoffMismatch",
                "structured_strategy_type": "CutoffMismatch",
                "structured_strategy_json": "",
                "causal_reason_type": "RecognitionEventTiming",
                "causal_reason_json": json.dumps(metadata, ensure_ascii=False),
                "parent_anomaly_id": "",
                "child_anomaly_ids": "[]",
                "scenario_id": "",
                "run_id": "",
                "generation_seed": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
            }
        )
    merged = pd.concat([labels, pd.DataFrame(new_rows, columns=labels.columns)], ignore_index=True)
    merged.to_csv(labels_path, index=False)
    merged.to_json(labels_dir / "anomaly_labels.json", orient="records", force_ascii=False, indent=2)
    with (labels_dir / "anomaly_labels.jsonl").open("w", encoding="utf-8") as fh:
        for item in merged.to_dict("records"):
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary_path = labels_dir / "anomaly_labels_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(k): int(v) for k, v in merged["anomaly_type"].value_counts().to_dict().items()}
    summary["v46_cutoff_truth"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "Revenue/expense cutoff labels are confirmed subset; normal and untestable controls remain sidecars.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_combined(output: Path) -> None:
    frames = [pd.read_csv(output / f"journal_entries_{year}.csv", dtype=str, low_memory=False) for year in (2022, 2023, 2024)]
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(output / "journal_entries.csv", index=False)
    json_path = output / "journal_entries.json"
    if json_path.exists():
        combined.to_json(json_path, orient="records", force_ascii=False)


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
    existing_labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_label_docs = set(existing_labels["document_id"].astype(str))

    confirmed: list[dict] = []
    review_population: list[dict] = []
    normal_controls: list[dict] = []
    reasonable_delay_controls: list[dict] = []
    untestable_controls: list[dict] = []

    for year in (2022, 2023, 2024):
        c, p, n, r, u = build_year(output, year, existing_label_docs)
        confirmed.extend(c)
        review_population.extend(p)
        normal_controls.extend(n)
        reasonable_delay_controls.extend(r)
        untestable_controls.extend(u)
        existing_label_docs.update(record["document_id"] for record in c)

    write_sidecar_family(labels_dir, "cutoff_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "cutoff_review_population", review_population)
    write_sidecar_family(labels_dir, "cutoff_normal_controls", normal_controls)
    write_sidecar_family(labels_dir, "cutoff_reasonable_delay_controls", reasonable_delay_controls)
    write_sidecar_family(labels_dir, "cutoff_untestable_controls", untestable_controls)
    append_anomaly_labels(labels_dir, confirmed)
    refresh_combined(output)

    by_year = {
        str(year): {
            "confirmed": sum(1 for r in confirmed if int(r["fiscal_year"]) == year),
            "review_population": sum(1 for r in review_population if int(r["fiscal_year"]) == year),
            "normal_controls": sum(1 for r in normal_controls if int(r["fiscal_year"]) == year),
            "reasonable_delay_controls": sum(1 for r in reasonable_delay_controls if int(r["fiscal_year"]) == year),
            "untestable_controls": sum(1 for r in untestable_controls if int(r["fiscal_year"]) == year),
        }
        for year in (2022, 2023, 2024)
    }
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v46_candidate",
            "source": source.name,
            "purpose": "Add L3-11 revenue/expense cutoff truth and controls.",
            "summary": by_year,
            "anti_fitting_policy": [
                "Confirmed labels are not the entire delivery_date population.",
                "Within-threshold normal controls are included.",
                "Long but reasonable delay controls are included and may be raw rule hits.",
                "Missing delivery_date controls remain untestable, not normal.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V46_CANDIDATE.md").write_text(
        "# DataSynth v46 Candidate\n\n"
        "L3-11 cutoff truth patch on top of v45.\n\n"
        f"Summary: `{json.dumps(by_year, ensure_ascii=False)}`\n\n"
        "- Adds `RevenueCutoffMismatch` and `ExpenseCutoffMismatch` confirmed labels.\n"
        "- Adds normal, reasonable-delay, and untestable cutoff controls.\n"
        "- Updates yearly and combined journal CSV/JSON files.\n",
        encoding="utf-8",
    )
    print(json.dumps(by_year, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
