from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


LABEL_TYPE = "RevenueManipulation"
SUBTYPE_TARGETS = {
    2022: {
        "high_value_revenue_outlier": 7,
        "cutoff_mismatch": 8,
        "reversal_return_credit": 5,
        "period_end_push": 6,
        "manual_revenue_entry": 4,
        "process_account_mismatch": 5,
        "composite_low_amount_dispersion": 3,
    },
    2023: {
        "high_value_revenue_outlier": 9,
        "cutoff_mismatch": 11,
        "reversal_return_credit": 7,
        "period_end_push": 5,
        "manual_revenue_entry": 8,
        "process_account_mismatch": 6,
        "composite_low_amount_dispersion": 4,
    },
    2024: {
        "high_value_revenue_outlier": 6,
        "cutoff_mismatch": 9,
        "reversal_return_credit": 8,
        "period_end_push": 9,
        "manual_revenue_entry": 5,
        "process_account_mismatch": 7,
        "composite_low_amount_dispersion": 5,
    },
}

SUBTYPE_RULE_HINTS = {
    "high_value_revenue_outlier": "L4-01 direct truth subset",
    "cutoff_mismatch": "L3-11 + L4-01 combined review",
    "reversal_return_credit": "L2-05 / reversal analytics review",
    "period_end_push": "L3-04 + L4-01 combined review",
    "manual_revenue_entry": "L3-02 + L4-01 combined review",
    "process_account_mismatch": "L3-01 + L4-01 combined review",
    "composite_low_amount_dispersion": "Phase 2/3 weak-signal coverage, not L4-01 direct truth",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v47 RevenueManipulation subtype coverage candidate.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v46_candidate")
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


def read_existing_docs(labels_dir: Path) -> tuple[pd.DataFrame, set[str], set[str], set[str]]:
    labels = pd.read_csv(labels_dir / "anomaly_labels.csv", dtype=str, keep_default_na=False)
    existing_revenue = set(labels.loc[labels["anomaly_type"].eq(LABEL_TYPE), "document_id"].astype(str))
    reversal = set(labels.loc[labels["anomaly_type"].eq("ReversedAmount"), "document_id"].astype(str))
    cutoff = set()
    cutoff_path = labels_dir / "cutoff_confirmed_anomalies.csv"
    if cutoff_path.exists():
        cutoff_df = pd.read_csv(cutoff_path, dtype=str, keep_default_na=False)
        cutoff = set(
            cutoff_df.loc[cutoff_df["anomaly_type"].eq("RevenueCutoffMismatch"), "document_id"].astype(str)
        )
    return labels, existing_revenue, reversal, cutoff


def document_summary(df: pd.DataFrame, year: int) -> pd.DataFrame:
    work = df.copy()
    work["_account_code"] = account_code(work["gl_account"])
    work["_is_revenue"] = work["_account_code"].str.startswith("4")
    amounts = pd.concat(
        [
            pd.to_numeric(work.get("debit_amount", 0), errors="coerce").fillna(0.0).abs(),
            pd.to_numeric(work.get("credit_amount", 0), errors="coerce").fillna(0.0).abs(),
        ],
        axis=1,
    ).max(axis=1)
    work["_line_amount"] = amounts
    revenue_lines = work[work["_is_revenue"]].copy()
    if revenue_lines.empty:
        return pd.DataFrame()
    group_keys = ["fiscal_year", "_account_code"]
    means = revenue_lines.groupby(group_keys)["_line_amount"].transform("mean")
    stds = revenue_lines.groupby(group_keys)["_line_amount"].transform("std").replace(0, pd.NA)
    revenue_lines["_revenue_zscore"] = ((revenue_lines["_line_amount"] - means) / stds).fillna(0.0)
    work["_revenue_zscore"] = 0.0
    work.loc[revenue_lines.index, "_revenue_zscore"] = revenue_lines["_revenue_zscore"]

    rows: list[dict] = []
    for doc_id, group in work.groupby("document_id", sort=False):
        rev = group[group["_is_revenue"]]
        if rev.empty:
            continue
        line_text = " | ".join(group.get("line_text", pd.Series(dtype=object)).fillna("").astype(str).head(8))
        header_text = first_nonempty(group.get("header_text", pd.Series(dtype=object)))
        source = first_nonempty(group.get("source", pd.Series(dtype=object))).lower()
        process = first_nonempty(group.get("business_process", pd.Series(dtype=object)))
        posting_date = first_nonempty(group.get("posting_date", pd.Series(dtype=object)))
        parsed_posting = pd.to_datetime(posting_date, errors="coerce")
        is_period_end = bool_series(group.get("is_period_end", pd.Series(False, index=group.index))).any()
        if not is_period_end and pd.notna(parsed_posting):
            is_period_end = int(parsed_posting.day) >= 26
        rows.append(
            {
                "document_id": str(doc_id),
                "company_code": first_nonempty(group.get("company_code", pd.Series(dtype=object))),
                "fiscal_year": year,
                "posting_date": posting_date,
                "document_number": first_nonempty(group.get("document_number", pd.Series(dtype=object))),
                "document_type": first_nonempty(group.get("document_type", pd.Series(dtype=object))),
                "business_process": process,
                "source": source,
                "created_by": first_nonempty(group.get("created_by", pd.Series(dtype=object))),
                "approved_by": first_nonempty(group.get("approved_by", pd.Series(dtype=object))),
                "is_period_end": bool(is_period_end),
                "revenue_accounts": "|".join(sorted(set(rev["_account_code"].astype(str)))),
                "revenue_line_count": int(len(rev)),
                "revenue_amount_sum": float(rev["_line_amount"].sum()),
                "max_revenue_amount": float(rev["_line_amount"].max()),
                "max_revenue_zscore": float(rev["_revenue_zscore"].max()),
                "text": f"{header_text} {line_text}".lower(),
                "has_return_language": any(token in f"{header_text} {line_text}" for token in ["환입", "취소", "반품", "credit", "return"]),
            }
        )
    return pd.DataFrame(rows)


def pick(pool: pd.DataFrame, year: int, subtype: str, count: int, used: set[str]) -> pd.DataFrame:
    eligible = pool[~pool["document_id"].isin(used)].drop_duplicates("document_id").copy()
    if eligible.empty or count <= 0:
        return eligible.head(0)
    eligible["_sort_key"] = eligible["document_id"].map(lambda value: f"{year}:{subtype}:{value}")
    picked = eligible.sort_values(["_priority", "_sort_key"], ascending=[False, True]).head(count).drop(columns=["_sort_key"])
    used.update(picked["document_id"].astype(str))
    return picked


def subtype_pools(summary: pd.DataFrame, reversal_docs: set[str], cutoff_docs: set[str]) -> dict[str, pd.DataFrame]:
    pools: dict[str, pd.DataFrame] = {}

    high = summary[summary["max_revenue_zscore"] >= 3.0].copy()
    high["_priority"] = high["max_revenue_zscore"]
    pools["high_value_revenue_outlier"] = high

    cutoff = summary[summary["document_id"].isin(cutoff_docs)].copy()
    cutoff["_priority"] = cutoff["max_revenue_zscore"].clip(lower=0) + 1.0
    pools["cutoff_mismatch"] = cutoff

    reversal = summary[summary["document_id"].isin(reversal_docs) | summary["has_return_language"]].copy()
    reversal["_priority"] = (
        (reversal["max_revenue_zscore"] < 3.0).astype(int) * 30
        + reversal["has_return_language"].astype(int) * 10
        - (reversal["max_revenue_zscore"] - 1.5).abs()
    )
    pools["reversal_return_credit"] = reversal

    period = summary[summary["is_period_end"] & summary["source"].isin(["manual", "adjustment"])].copy()
    period["_priority"] = (
        (period["max_revenue_zscore"] < 3.0).astype(int) * 50
        + ((period["max_revenue_zscore"] >= 3.0) & (period["max_revenue_zscore"] < 10.0)).astype(int) * 15
        - (period["max_revenue_zscore"] - 2.0).abs()
    )
    pools["period_end_push"] = period

    manual = summary[summary["source"].isin(["manual", "adjustment"])].copy()
    manual["_priority"] = (
        (manual["max_revenue_zscore"] < 3.0).astype(int) * 50
        + ((manual["max_revenue_zscore"] >= 3.0) & (manual["max_revenue_zscore"] < 10.0)).astype(int) * 15
        - (manual["max_revenue_zscore"] - 1.5).abs()
    )
    pools["manual_revenue_entry"] = manual

    mismatch = summary[~summary["business_process"].isin(["O2C"])].copy()
    mismatch["_priority"] = (
        (mismatch["max_revenue_zscore"] < 3.0).astype(int) * 50
        + ((mismatch["max_revenue_zscore"] >= 3.0) & (mismatch["max_revenue_zscore"] < 10.0)).astype(int) * 15
        + mismatch["business_process"].isin(["P2P", "H2R", "TRE"]).astype(int) * 3
        - (mismatch["max_revenue_zscore"] - 1.5).abs()
    )
    pools["process_account_mismatch"] = mismatch

    low = summary[
        (summary["revenue_line_count"] >= 2)
        & (summary["max_revenue_zscore"] < 3.0)
        & (summary["revenue_amount_sum"] > 0)
    ].copy()
    low["_priority"] = low["revenue_line_count"] - low["max_revenue_zscore"].clip(lower=0)
    pools["composite_low_amount_dispersion"] = low
    return pools


def build_records_for_year(
    summary: pd.DataFrame,
    year: int,
    existing_revenue_docs: set[str],
    reversal_docs: set[str],
    cutoff_docs: set[str],
) -> tuple[list[dict], dict[str, int]]:
    used = set(existing_revenue_docs)
    pools = subtype_pools(summary, reversal_docs, cutoff_docs)
    records: list[dict] = []
    actual_counts: dict[str, int] = {}
    for subtype, target in SUBTYPE_TARGETS[year].items():
        picked = pick(pools[subtype], year, subtype, target, used)
        actual_counts[subtype] = int(len(picked))
        for offset, (_, row) in enumerate(picked.iterrows(), start=1):
            records.append(
                {
                    "case_id": f"L401REV-{year}-{subtype.upper().replace('_', '-')}-{offset:04d}",
                    "document_id": row["document_id"],
                    "company_code": row["company_code"],
                    "fiscal_year": year,
                    "posting_date": row["posting_date"],
                    "document_number": row["document_number"],
                    "document_type": row["document_type"],
                    "business_process": row["business_process"],
                    "source": row["source"],
                    "created_by": row["created_by"],
                    "approved_by": row["approved_by"],
                    "revenue_subtype": subtype,
                    "rule_hint": SUBTYPE_RULE_HINTS[subtype],
                    "revenue_accounts": row["revenue_accounts"],
                    "revenue_line_count": int(row["revenue_line_count"]),
                    "revenue_amount_sum": round(float(row["revenue_amount_sum"]), 2),
                    "max_revenue_amount": round(float(row["max_revenue_amount"]), 2),
                    "max_revenue_zscore": round(float(row["max_revenue_zscore"]), 4),
                    "is_l401_direct_truth": subtype == "high_value_revenue_outlier",
                    "truth_basis": "RevenueManipulation broad fraud subtype coverage",
                    "evaluation_policy": "Use only high_value_revenue_outlier as direct L4-01 truth; other subtypes are combination or Phase 2/3 coverage.",
                }
            )
    return records, actual_counts


def append_revenue_labels(labels_dir: Path, records: list[dict]) -> None:
    labels_path = labels_dir / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    max_id = max(int(value.replace("ANO", "")) for value in labels["anomaly_id"].astype(str) if value.startswith("ANO"))
    new_rows = []
    for offset, record in enumerate(records, start=1):
        metadata = {
            "rule_id": "L4-01",
            "case_id": record["case_id"],
            "revenue_subtype": record["revenue_subtype"],
            "rule_hint": record["rule_hint"],
            "is_l401_direct_truth": bool(record["is_l401_direct_truth"]),
            "revenue_accounts": record["revenue_accounts"],
            "max_revenue_zscore": record["max_revenue_zscore"],
            "truth_basis": record["truth_basis"],
            "evaluation_policy": record["evaluation_policy"],
        }
        new_rows.append(
            {
                "anomaly_id": f"ANO{max_id + offset:08d}",
                "anomaly_category": "Fraud",
                "anomaly_type": LABEL_TYPE,
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "company_code": record["company_code"],
                "anomaly_date": record["posting_date"],
                "detection_timestamp": "2026-04-26 00:00:00",
                "confidence": "0.78" if record["is_l401_direct_truth"] else "0.64",
                "severity": "5" if record["is_l401_direct_truth"] else "4",
                "description": f"Revenue manipulation subtype coverage: {record['revenue_subtype']}",
                "is_injected": "True",
                "monetary_impact": str(record["revenue_amount_sum"]),
                "related_entities": json.dumps([record["document_id"]], ensure_ascii=False),
                "cluster_id": "",
                "original_document_hash": "",
                "injection_strategy": "RevenueManipulationSubtypeCoverage",
                "structured_strategy_type": "RevenueManipulation",
                "structured_strategy_json": json.dumps(metadata, ensure_ascii=False),
                "causal_reason_type": "RevenueManipulationSubtype",
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
    summary["v47_revenue_manipulation_subtypes"] = {
        "added_labels": len(new_rows),
        "policy": "RevenueManipulation remains broad; only high_value_revenue_outlier is direct L4-01 truth.",
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
    labels, existing_revenue_docs, reversal_docs, cutoff_docs = read_existing_docs(labels_dir)
    all_records: list[dict] = []
    summary: dict[int, dict[str, int]] = {}
    for year in (2022, 2023, 2024):
        df = pd.read_csv(output / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        doc_summary = document_summary(df, year)
        records, counts = build_records_for_year(
            doc_summary,
            year,
            existing_revenue_docs | {r["document_id"] for r in all_records},
            reversal_docs,
            cutoff_docs,
        )
        all_records.extend(records)
        summary[year] = counts | {"added_labels": len(records)}

    direct_records = [r for r in all_records if r["is_l401_direct_truth"]]
    non_direct_records = [r for r in all_records if not r["is_l401_direct_truth"]]
    write_sidecar_family(labels_dir, "revenue_manipulation_subtypes", all_records)
    write_sidecar_family(labels_dir, "revenue_manipulation_l401_direct_truth", direct_records)
    write_sidecar_family(labels_dir, "revenue_manipulation_combination_coverage", non_direct_records)
    append_revenue_labels(labels_dir, all_records)

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v47_candidate",
            "source": source.name,
            "purpose": "Add broad RevenueManipulation subtype coverage without making every subtype direct L4-01 truth.",
            "summary": {str(year): values for year, values in summary.items()},
            "anti_fitting_policy": [
                "RevenueManipulation remains a broad fraud type.",
                "Only high_value_revenue_outlier is direct L4-01 truth.",
                "Cutoff, reversal, period-end, manual, process-mismatch, and low-amount dispersion subtypes are combination or downstream coverage.",
                "Subtype counts vary by year and are selected from existing ledger context instead of patching every case to match L4-01.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    freeze = output / "FREEZE_V47_CANDIDATE.md"
    freeze.write_text(
        "# DataSynth v47 Candidate\n\n"
        "L4-01 RevenueManipulation subtype coverage patch.\n\n"
        "- Source: `datasynth_v46_candidate`\n"
        "- Keeps `RevenueManipulation` as a broad fraud type.\n"
        "- Adds `labels/revenue_manipulation_subtypes*` for subtype-level coverage.\n"
        "- Adds `labels/revenue_manipulation_l401_direct_truth*` for the direct L4-01 high-value subset.\n"
        "- Adds `labels/revenue_manipulation_combination_coverage*` for cutoff/reversal/period-end/manual/process/low-amount scenarios.\n"
        "- Does not force all RevenueManipulation labels to be L4-01 hits.\n\n"
        f"Summary: `{json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps({str(year): values for year, values in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
