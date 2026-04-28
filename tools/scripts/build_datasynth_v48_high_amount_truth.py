from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


CONFIRMED_TARGETS = {
    2022: {"UnusuallyHighAmount": 9, "StatisticalOutlier": 5, "normal": 55, "boundary": 35},
    2023: {"UnusuallyHighAmount": 7, "StatisticalOutlier": 6, "normal": 64, "boundary": 42},
    2024: {"UnusuallyHighAmount": 10, "StatisticalOutlier": 4, "normal": 58, "boundary": 39},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v48 L4-03 high amount truth and controls.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v47_candidate")
    parser.add_argument("--output", required=True, help="Output candidate directory")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory")
    return parser.parse_args()


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().str.replace(r"\.0+$", "", regex=True)


def bool_series(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.lower().isin({"true", "1", "yes", "y"})


def first_nonempty(values: pd.Series) -> str:
    for value in values:
        if pd.notna(value) and str(value).strip():
            return str(value)
    return ""


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


def load_existing_labels(labels_dir: Path) -> tuple[pd.DataFrame, set[str]]:
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_docs = set(
        labels.loc[
            labels["anomaly_type"].isin(["UnusuallyHighAmount", "StatisticalOutlier"]),
            "document_id",
        ].astype(str)
    )
    return labels, existing_docs


def document_summary(df: pd.DataFrame, year: int) -> pd.DataFrame:
    work = df.copy()
    work["_account_code"] = account_code(work.get("gl_account", pd.Series(dtype=object)))
    debit = pd.to_numeric(work.get("debit_amount", 0), errors="coerce").fillna(0.0)
    credit = pd.to_numeric(work.get("credit_amount", 0), errors="coerce").fillna(0.0)
    work["_line_amount"] = pd.concat([debit.abs(), credit.abs()], axis=1).max(axis=1)
    if "amount_zscore" in work.columns:
        work["_line_zscore"] = pd.to_numeric(work["amount_zscore"], errors="coerce").fillna(0.0)
    else:
        account_group = work["_account_code"].where(work["_account_code"].ne(""), "__missing__")
        group_mean = work["_line_amount"].groupby(account_group).transform("mean")
        group_std = work["_line_amount"].groupby(account_group).transform("std").replace(0, pd.NA)
        fallback_mean = work["_line_amount"].mean()
        fallback_std = work["_line_amount"].std()
        zscore = (work["_line_amount"] - group_mean) / group_std
        if pd.notna(fallback_std) and fallback_std > 0:
            zscore = zscore.fillna((work["_line_amount"] - fallback_mean) / fallback_std)
        work["_line_zscore"] = zscore.fillna(0.0)
    work["_is_revenue"] = work["_account_code"].str.startswith("4")
    work["_is_cash"] = work["_account_code"].str.startswith(("10", "11"))
    work["_is_asset"] = work["_account_code"].str.startswith(("1", "12", "15", "16"))
    work["_is_liability"] = work["_account_code"].str.startswith("2")
    work["_is_expense"] = work["_account_code"].str.startswith("5")

    doc_max = work["_line_amount"].groupby(work["document_id"]).transform("max")
    global_q90 = float(work["_line_amount"].quantile(0.90))
    global_q95 = float(work["_line_amount"].quantile(0.95))
    global_q99 = float(work["_line_amount"].quantile(0.99))
    rows: list[dict] = []
    for doc_id, group in work.groupby("document_id", sort=False):
        max_idx = group["_line_amount"].idxmax()
        max_line = group.loc[max_idx]
        source = first_nonempty(group.get("source", pd.Series(dtype=object))).lower()
        is_period_end = bool_series(group.get("is_period_end", pd.Series(False, index=group.index))).any()
        posting_date = first_nonempty(group.get("posting_date", pd.Series(dtype=object)))
        parsed_posting = pd.to_datetime(posting_date, errors="coerce")
        if not is_period_end and pd.notna(parsed_posting):
            is_period_end = int(parsed_posting.day) >= 26 or int(parsed_posting.day) <= 5
        amount = float(group["_line_amount"].max())
        zscore = float(group["_line_zscore"].max())
        if amount >= global_q99:
            amount_band = "global_p99_plus"
        elif amount >= global_q95:
            amount_band = "global_p95_p99"
        elif amount >= global_q90:
            amount_band = "global_p90_p95"
        else:
            amount_band = "below_global_p90"
        rows.append(
            {
                "document_id": str(doc_id),
                "company_code": first_nonempty(group.get("company_code", pd.Series(dtype=object))),
                "fiscal_year": year,
                "posting_date": posting_date,
                "document_number": first_nonempty(group.get("document_number", pd.Series(dtype=object))),
                "document_type": first_nonempty(group.get("document_type", pd.Series(dtype=object))),
                "business_process": first_nonempty(group.get("business_process", pd.Series(dtype=object))),
                "source": source,
                "created_by": first_nonempty(group.get("created_by", pd.Series(dtype=object))),
                "approved_by": first_nonempty(group.get("approved_by", pd.Series(dtype=object))),
                "max_amount_account": str(max_line["_account_code"]),
                "max_line_amount": round(amount, 2),
                "max_amount_zscore": round(zscore, 4),
                "amount_band": amount_band,
                "is_period_boundary": bool(is_period_end),
                "has_revenue_line": bool(group["_is_revenue"].any()),
                "has_cash_line": bool(group["_is_cash"].any()),
                "has_asset_line": bool(group["_is_asset"].any()),
                "has_liability_line": bool(group["_is_liability"].any()),
                "has_expense_line": bool(group["_is_expense"].any()),
                "line_count": int(len(group)),
                "global_q90": round(global_q90, 2),
                "global_q95": round(global_q95, 2),
                "global_q99": round(global_q99, 2),
                "doc_max_amount": round(float(doc_max.loc[group.index].max()), 2),
            }
        )
    return pd.DataFrame(rows)


def add_priority_columns(population: pd.DataFrame) -> pd.DataFrame:
    pop = population.copy()
    source_bonus = pop["source"].isin(["manual", "adjustment"]).astype(int) * 2
    period_bonus = pop["is_period_boundary"].astype(int)
    process_bonus = pop["business_process"].isin(["R2R", "A2R", "TRE", "O2C"]).astype(int)
    pop["_confirmed_priority"] = (
        pop["max_amount_zscore"].clip(lower=0)
        + source_bonus
        + period_bonus
        + process_bonus
        + pop["amount_band"].map({"global_p99_plus": 5, "global_p95_p99": 3, "global_p90_p95": 1}).fillna(0)
    )
    pop["_normal_priority"] = (
        pop["max_line_amount"].rank(pct=True)
        + pop["business_process"].isin(["TRE", "A2R"]).astype(int)
        + pop["source"].isin(["recurring", "automated", "batch", "system"]).astype(int)
    )
    pop["_boundary_priority"] = -((pop["max_amount_zscore"] - 2.7).abs()) + (
        pop["amount_band"].isin(["global_p90_p95", "global_p95_p99"]).astype(int)
    )
    return pop


def pick(pool: pd.DataFrame, year: int, key: str, count: int, used: set[str], priority_col: str) -> pd.DataFrame:
    eligible = pool[~pool["document_id"].isin(used)].drop_duplicates("document_id").copy()
    if count <= 0 or eligible.empty:
        return eligible.head(0)
    eligible["_sort_key"] = eligible["document_id"].map(lambda value: f"{year}:{key}:{value}")
    picked = eligible.sort_values([priority_col, "_sort_key"], ascending=[False, True]).head(count)
    used.update(picked["document_id"].astype(str))
    return picked.drop(columns=["_sort_key"])


def make_record(row: pd.Series, *, case_id: str, label_type: str, truth_basis: str, evaluation_policy: str) -> dict:
    return {
        "case_id": case_id,
        "document_id": row["document_id"],
        "company_code": row["company_code"],
        "fiscal_year": int(row["fiscal_year"]),
        "posting_date": row["posting_date"],
        "document_number": row["document_number"],
        "document_type": row["document_type"],
        "business_process": row["business_process"],
        "source": row["source"],
        "created_by": row["created_by"],
        "approved_by": row["approved_by"],
        "anomaly_type": label_type,
        "max_amount_account": row["max_amount_account"],
        "max_line_amount": row["max_line_amount"],
        "max_amount_zscore": row["max_amount_zscore"],
        "amount_band": row["amount_band"],
        "is_period_boundary": bool(row["is_period_boundary"]),
        "has_revenue_line": bool(row["has_revenue_line"]),
        "has_cash_line": bool(row["has_cash_line"]),
        "has_asset_line": bool(row["has_asset_line"]),
        "has_liability_line": bool(row["has_liability_line"]),
        "has_expense_line": bool(row["has_expense_line"]),
        "line_count": int(row["line_count"]),
        "truth_basis": truth_basis,
        "evaluation_policy": evaluation_policy,
    }


def classify_year(population: pd.DataFrame, year: int, existing_docs: set[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    pop = add_priority_columns(population)
    used = set(existing_docs)
    targets = CONFIRMED_TARGETS[year]
    confirmed_pool = pop[(pop["max_amount_zscore"] > 3.0) & pop["amount_band"].isin(["global_p95_p99", "global_p99_plus"])].copy()
    if confirmed_pool.empty:
        confirmed_pool = pop[pop["max_amount_zscore"] > 3.0].copy()
    unusually = pick(confirmed_pool, year, "unusually_high_amount", targets["UnusuallyHighAmount"], used, "_confirmed_priority")
    stat_pool = confirmed_pool[~confirmed_pool["document_id"].isin(used)].copy()
    stat = pick(stat_pool, year, "statistical_outlier", targets["StatisticalOutlier"], used, "_confirmed_priority")

    normal_pool = pop[
        pop["amount_band"].isin(["global_p95_p99", "global_p99_plus"])
        & (pop["max_amount_zscore"] <= 3.0)
        & pop["business_process"].isin(["TRE", "A2R", "P2P", "O2C"])
    ].copy()
    normal = pick(normal_pool, year, "normal_high_amount", targets["normal"], used, "_normal_priority")
    boundary_pool = pop[
        pop["amount_band"].isin(["global_p90_p95", "global_p95_p99"])
        & (pop["max_amount_zscore"] > 2.2)
        & (pop["max_amount_zscore"] <= 3.0)
    ].copy()
    boundary = pick(boundary_pool, year, "boundary_high_amount", targets["boundary"], used, "_boundary_priority")

    confirmed_records: list[dict] = []
    review_records: list[dict] = []
    normal_records: list[dict] = []
    boundary_records: list[dict] = []

    for idx, (_, row) in enumerate(unusually.iterrows(), start=1):
        record = make_record(
            row,
            case_id=f"L403UHA-{year}-{idx:04d}",
            label_type="UnusuallyHighAmount",
            truth_basis="confirmed unusually high amount anomaly",
            evaluation_policy="confirmed anomaly recall subset",
        )
        confirmed_records.append(record)
        review_records.append(record | {"population_id": f"L403POP-{year}-{len(review_records)+1:05d}"})
    for idx, (_, row) in enumerate(stat.iterrows(), start=1):
        record = make_record(
            row,
            case_id=f"L403STAT-{year}-{idx:04d}",
            label_type="StatisticalOutlier",
            truth_basis="confirmed statistical high-amount outlier",
            evaluation_policy="confirmed anomaly recall subset",
        )
        confirmed_records.append(record)
        review_records.append(record | {"population_id": f"L403POP-{year}-{len(review_records)+1:05d}"})
    for idx, (_, row) in enumerate(normal.iterrows(), start=1):
        record = make_record(
            row,
            case_id=f"L403NC-{year}-{idx:04d}",
            label_type="NormalHighAmountBusinessEvent",
            truth_basis="normal high-amount business event control",
            evaluation_policy="review candidate, not confirmed anomaly",
        )
        normal_records.append(record)
        review_records.append(record | {"population_id": f"L403POP-{year}-{len(review_records)+1:05d}"})
    for idx, (_, row) in enumerate(boundary.iterrows(), start=1):
        record = make_record(
            row,
            case_id=f"L403BC-{year}-{idx:04d}",
            label_type="HighAmountBoundaryControl",
            truth_basis="near-threshold amount-zscore boundary control",
            evaluation_policy="negative control for hard threshold fitting",
        )
        boundary_records.append(record)
    return confirmed_records, review_records, normal_records, boundary_records


def append_labels(labels_dir: Path, confirmed_records: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    max_id = max(int(value.replace("ANO", "")) for value in labels["anomaly_id"].astype(str) if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(confirmed_records, start=1):
        metadata = {
            "rule_id": "L4-03",
            "case_id": record["case_id"],
            "max_amount_account": record["max_amount_account"],
            "max_line_amount": record["max_line_amount"],
            "max_amount_zscore": record["max_amount_zscore"],
            "amount_band": record["amount_band"],
            "truth_basis": record["truth_basis"],
            "evaluation_policy": "confirmed subset; high_amount_review_population is coverage only",
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "Statistical",
                "anomaly_type": record["anomaly_type"],
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.76",
                "severity": "3",
                "description": f"L4-03 high amount outlier: {record['anomaly_type']}",
                "is_injected": "True",
                "monetary_impact": str(record["max_line_amount"]),
                "related_entities": json.dumps([record["document_id"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": "HighAmountOutlierCoverage",
                "structured_strategy_type": record["anomaly_type"],
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "HighAmountOutlier",
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
        for row in merged.to_dict("records"):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary_path = labels_dir / "anomaly_labels_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    counts = merged["anomaly_type"].value_counts().to_dict()
    summary["total_labels"] = int(len(merged))
    summary["label_counts"] = {str(key): int(value) for key, value in counts.items()}
    summary["v48_high_amount_outlier"] = {
        "added_confirmed_labels": len(new_rows),
        "policy": "confirmed subset only; high_amount_review_population is coverage truth, normal controls remain unlabeled",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


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
    _, existing_docs = load_existing_labels(labels_dir)
    confirmed_records: list[dict] = []
    review_records: list[dict] = []
    normal_records: list[dict] = []
    boundary_records: list[dict] = []
    summary: dict[int, dict[str, int]] = {}
    for year in (2022, 2023, 2024):
        df = pd.read_csv(output / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        population = document_summary(df, year)
        confirmed, review, normal, boundary = classify_year(population, year, existing_docs | {r["document_id"] for r in confirmed_records})
        confirmed_records.extend(confirmed)
        review_records.extend(review)
        normal_records.extend(normal)
        boundary_records.extend(boundary)
        summary[year] = {
            "confirmed": len(confirmed),
            "review_population": len(review),
            "normal_controls": len(normal),
            "boundary_controls": len(boundary),
        }

    write_sidecar_family(labels_dir, "high_amount_confirmed_anomalies", confirmed_records)
    write_sidecar_family(labels_dir, "high_amount_review_population", review_records)
    write_sidecar_family(labels_dir, "high_amount_normal_controls", normal_records)
    write_sidecar_family(labels_dir, "high_amount_boundary_controls", boundary_records)
    append_labels(labels_dir, confirmed_records)

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v48_candidate",
            "source": source.name,
            "purpose": "Add L4-03 high amount confirmed subset, review population, and normal/boundary controls.",
            "summary": {str(year): values for year, values in summary.items()},
            "anti_fitting_policy": [
                "Do not label every high amount as UnusuallyHighAmount.",
                "Keep normal high-amount business events as review candidates, not confirmed anomalies.",
                "Keep near-threshold boundary controls to discourage hard-threshold fitting.",
                "Evaluate L4-03 confirmed recall separately from review-population coverage.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V48_CANDIDATE.md").write_text(
        "# DataSynth v48 Candidate\n\n"
        "L4-03 high amount truth and review-population patch.\n\n"
        "- Source: `datasynth_v47_candidate`\n"
        "- Adds `labels/high_amount_confirmed_anomalies*`.\n"
        "- Adds `labels/high_amount_review_population*`.\n"
        "- Adds `labels/high_amount_normal_controls*` for normal large business events.\n"
        "- Adds `labels/high_amount_boundary_controls*` for near-threshold controls.\n"
        "- Keeps L4-03 as review anchor, not exhaustive high-amount fraud truth.\n\n"
        f"Summary: `{json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
