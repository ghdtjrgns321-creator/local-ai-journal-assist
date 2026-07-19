from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pandas as pd


VARIANCE_THRESHOLD = 0.50
NEAR_THRESHOLD_LOW = 0.40
MAX_RELATED_DOCS = 25
TARGET_ANOMALIES = {
    "InvalidAccount",
    "MisclassifiedAccount",
    "ImproperCapitalization",
    "RevenueManipulation",
    "UnusualAccountPair",
    "HighRiskAccountUse",
    "SuspenseAccountAbuse",
    "DormantAccountActivity",
    "FictitiousEntry",
}
NON_D01_ANOMALIES = {
    "VagueDescription",
    "VagueOrRiskyDescription",
    "LateApproval",
    "DuplicateEntry",
    "DuplicatePayment",
    "MissingDocumentation",
    "ApprovalDateMissing",
    "AfterHoursPosting",
    "WeekendPosting",
}
HIGH_VOLUME_PREFIXES = ("1000", "1001", "1002", "2000", "2001", "2002")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v55 D01 account activity variance sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v54_candidate")
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


def write_sidecar_family(labels_dir: Path, stem: str, records: list[dict]) -> None:
    write_records(labels_dir / f"{stem}.csv", records)
    (labels_dir / f"{stem}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    for year in sorted({int(record["fiscal_year"]) for record in records}):
        year_records = [record for record in records if int(record["fiscal_year"]) == year]
        write_records(labels_dir / f"{stem}_{year}.csv", year_records)
        (labels_dir / f"{stem}_{year}.json").write_text(
            json.dumps(year_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def account_code(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)


def load_year(base: Path, year: int) -> pd.DataFrame:
    path = base / f"journal_entries_{year}.csv"
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "fiscal_period",
        "business_process",
        "source",
        "gl_account",
        "debit_amount",
        "credit_amount",
    ]
    header = pd.read_csv(path, nrows=0).columns
    df = pd.read_csv(path, dtype=str, usecols=[col for col in usecols if col in header], low_memory=False)
    df["fiscal_year"] = year
    df["_account_code"] = account_code(df.get("gl_account", pd.Series(index=df.index, dtype=object)))
    debit = pd.to_numeric(df.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
    credit = pd.to_numeric(df.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    df["_activity_amount"] = debit + credit
    df = df[df["_account_code"].ne("") & df["_activity_amount"].gt(0)].copy()
    return df


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["company_code", "_account_code"], dropna=False)
        .agg(
            total_amount=("_activity_amount", "sum"),
            count=("_activity_amount", "size"),
            avg_amount=("_activity_amount", "mean"),
            related_document_count=("document_id", "nunique"),
        )
        .reset_index()
        .rename(columns={"_account_code": "gl_account"})
    )
    return grouped


def document_profiles(df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    doc_label = (
        labels.groupby("document_id")["anomaly_type"]
        .agg(lambda values: "|".join(sorted(set(str(v) for v in values if str(v)))))
        .reset_index()
    )
    doc_label["has_d01_target_anomaly"] = doc_label["anomaly_type"].map(
        lambda text: bool(set(text.split("|")) & TARGET_ANOMALIES)
    )
    doc_label["has_non_d01_anomaly"] = doc_label["anomaly_type"].map(
        lambda text: bool(set(text.split("|")) & NON_D01_ANOMALIES)
    )
    docs = (
        df[["company_code", "_account_code", "document_id", "business_process", "source"]]
        .drop_duplicates()
        .merge(doc_label, on="document_id", how="left")
    )
    docs["anomaly_type"] = docs["anomaly_type"].fillna("")
    docs["has_d01_target_anomaly"] = docs["has_d01_target_anomaly"].map(lambda value: value is True)
    docs["has_non_d01_anomaly"] = docs["has_non_d01_anomaly"].map(lambda value: value is True)
    profile = (
        docs.groupby(["company_code", "_account_code"], dropna=False)
        .agg(
            current_document_ids=("document_id", lambda values: "|".join(sorted(set(values))[:MAX_RELATED_DOCS])),
            d01_target_document_count=("has_d01_target_anomaly", "sum"),
            non_d01_document_count=("has_non_d01_anomaly", "sum"),
            manual_document_count=("source", lambda values: sum(str(v).lower() in {"manual", "adjustment"} for v in values)),
            business_processes=("business_process", lambda values: "|".join(sorted(set(str(v) for v in values if str(v))))),
            sources=("source", lambda values: "|".join(sorted(set(str(v) for v in values if str(v))))),
        )
        .reset_index()
        .rename(columns={"_account_code": "gl_account"})
    )
    return profile


def safe_var(current: float, prior: float) -> float:
    return abs(float(current) - float(prior)) / max(abs(float(prior)), 1.0)


def account_family(gl_account: str) -> str:
    code = str(gl_account)
    if code.startswith("1"):
        return "asset"
    if code.startswith("2"):
        return "liability"
    if code.startswith("4"):
        return "revenue"
    if code.startswith("5"):
        return "expense_or_cogs"
    if code.startswith("6"):
        return "expense"
    if code.startswith("7"):
        return "other_income_expense"
    if code.startswith("8") or code.startswith("9"):
        return "suspense_or_statistical"
    return "unknown"


def classify_scenario(row: pd.Series) -> tuple[str, str, bool]:
    acct = str(row["gl_account"])
    family = account_family(acct)
    weighted = float(row["weighted_variance"])
    prior_missing = bool(row["prior_missing"])
    count_var = float(row["count_variance"])
    avg_var = float(row["avg_amount_variance"])
    total_var = float(row["total_amount_variance"])
    target_docs = int(row.get("d01_target_document_count", 0))
    non_d01_docs = int(row.get("non_d01_document_count", 0))
    high_volume = acct.startswith(HIGH_VOLUME_PREFIXES)

    if prior_missing and target_docs > 0:
        return "suspicious_new_or_bypass_account", "", True
    if target_docs > 0 and family in {"revenue", "expense_or_cogs", "expense", "suspense_or_statistical"}:
        return "target_anomaly_concentrated_account", "", True
    if target_docs > 0 and weighted >= 0.75:
        return "anomaly_supported_activity_shift", "", True
    if family in {"revenue", "expense_or_cogs", "expense"} and total_var >= 1.25 and count_var >= 0.50:
        return "revenue_expense_activity_surge", "", True
    if avg_var >= 1.50 and target_docs > 0:
        return "average_entry_amount_shift", "", True
    if count_var >= 1.50 and target_docs > 0:
        return "transaction_count_surge", "", True

    if prior_missing:
        return "normal_new_account", "new account without D01 target anomaly evidence", False
    if high_volume:
        return "normal_high_volume_operational_change", "cash/AP/AR activity can vary materially in normal operations", False
    if non_d01_docs > target_docs:
        return "non_d01_anomaly_not_account_variance_truth", "document-level anomaly does not imply account activity variance truth", False
    if family in {"expense_or_cogs", "expense"} and weighted >= VARIANCE_THRESHOLD:
        return "normal_business_volume_or_price_change", "expense or COGS movement can reflect volume or price changes", False
    if family == "asset" and weighted >= VARIANCE_THRESHOLD:
        return "normal_investment_or_working_capital_change", "asset account activity can shift from working-capital or investment timing", False
    return "review_only_activity_variance", "insufficient anomaly evidence for confirmed D01 truth", False


def build_records(base: Path) -> tuple[list[dict], list[dict], list[dict]]:
    labels_path = base / "labels" / "anomaly_labels.csv"
    labels = pd.read_csv(labels_path, dtype=str, usecols=["document_id", "anomaly_type"], keep_default_na=False)
    yearly = {year: load_year(base, year) for year in (2022, 2023, 2024)}
    aggregates = {year: aggregate(df) for year, df in yearly.items()}

    truth: list[dict] = []
    controls: list[dict] = []
    review: list[dict] = []

    for year in (2023, 2024):
        prior = aggregates[year - 1].rename(
            columns={
                "total_amount": "prior_total_amount",
                "count": "prior_count",
                "avg_amount": "prior_avg_amount",
                "related_document_count": "prior_related_document_count",
            }
        )
        current = aggregates[year].rename(
            columns={
                "total_amount": "current_total_amount",
                "count": "current_count",
                "avg_amount": "current_avg_amount",
                "related_document_count": "current_related_document_count",
            }
        )
        profile = document_profiles(yearly[year], labels)
        merged = current.merge(prior, on=["company_code", "gl_account"], how="left")
        merged = merged.merge(profile, on=["company_code", "gl_account"], how="left")
        for col in [
            "prior_total_amount",
            "prior_count",
            "prior_avg_amount",
            "prior_related_document_count",
            "d01_target_document_count",
            "non_d01_document_count",
            "manual_document_count",
        ]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
        for col in ["current_document_ids", "business_processes", "sources"]:
            merged[col] = merged[col].fillna("")

        merged["prior_missing"] = merged["prior_count"].eq(0)
        merged["total_amount_variance"] = merged.apply(
            lambda row: 1.0 if row["prior_missing"] else safe_var(row["current_total_amount"], row["prior_total_amount"]),
            axis=1,
        )
        merged["count_variance"] = merged.apply(
            lambda row: 1.0 if row["prior_missing"] else safe_var(row["current_count"], row["prior_count"]),
            axis=1,
        )
        merged["avg_amount_variance"] = merged.apply(
            lambda row: 1.0 if row["prior_missing"] else safe_var(row["current_avg_amount"], row["prior_avg_amount"]),
            axis=1,
        )
        merged["weighted_variance"] = (
            merged["total_amount_variance"] * 0.5
            + merged["count_variance"] * 0.3
            + merged["avg_amount_variance"] * 0.2
        )

        candidates = merged[
            merged["prior_missing"]
            | merged["weighted_variance"].ge(NEAR_THRESHOLD_LOW)
            | merged["d01_target_document_count"].gt(0)
        ].copy()
        candidates = candidates.sort_values(
            ["weighted_variance", "d01_target_document_count", "current_total_amount"],
            ascending=[False, False, False],
        )

        for idx, row in candidates.iterrows():
            scenario, normal_reason, is_truth = classify_scenario(row)
            expected_flag = bool(row["prior_missing"] or row["weighted_variance"] > VARIANCE_THRESHOLD)
            record = {
                "case_id": f"D01-{year}-{idx:05d}",
                "fiscal_year": year,
                "prior_fiscal_year": year - 1,
                "company_code": row["company_code"],
                "gl_account": row["gl_account"],
                "account_family": account_family(row["gl_account"]),
                "account_variance_label": "AccountActivityVariance",
                "expected_d01_flag": expected_flag,
                "is_true_positive_account": bool(is_truth and expected_flag),
                "scenario_type": scenario,
                "normal_reason": normal_reason,
                "prior_missing": bool(row["prior_missing"]),
                "prior_total_amount": round(float(row["prior_total_amount"]), 2),
                "current_total_amount": round(float(row["current_total_amount"]), 2),
                "prior_count": int(row["prior_count"]),
                "current_count": int(row["current_count"]),
                "prior_avg_amount": round(float(row["prior_avg_amount"]), 2),
                "current_avg_amount": round(float(row["current_avg_amount"]), 2),
                "total_amount_variance": round(float(row["total_amount_variance"]), 6),
                "count_variance": round(float(row["count_variance"]), 6),
                "avg_amount_variance": round(float(row["avg_amount_variance"]), 6),
                "weighted_variance": round(float(row["weighted_variance"]), 6),
                "variance_threshold": VARIANCE_THRESHOLD,
                "d01_target_document_count": int(row["d01_target_document_count"]),
                "non_d01_document_count": int(row["non_d01_document_count"]),
                "manual_document_count": int(row["manual_document_count"]),
                "current_related_document_count": int(row["current_related_document_count"]),
                "prior_related_document_count": int(row["prior_related_document_count"]),
                "business_processes": row["business_processes"],
                "sources": row["sources"],
                "related_document_ids": row["current_document_ids"],
                "evaluation_unit": "fiscal_year+company_code+gl_account",
                "evaluation_policy": "Use as D01 account-level truth/control, not row-level anomaly truth.",
            }
            if expected_flag:
                review.append(record)
            if record["is_true_positive_account"]:
                truth.append(record)
            elif expected_flag:
                controls.append(record)

    return truth, controls, review


def summarize(records: list[dict]) -> dict:
    return {
        "total": len(records),
        "by_year": {
            str(year): sum(int(record["fiscal_year"]) == year for record in records)
            for year in (2023, 2024)
        },
        "by_scenario": pd.Series([record["scenario_type"] for record in records]).value_counts().to_dict()
        if records
        else {},
    }


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
    truth, controls, review = build_records(output)
    write_sidecar_family(labels_dir, "account_activity_variance_truth", truth)
    write_sidecar_family(labels_dir, "account_activity_variance_normal_controls", controls)
    write_sidecar_family(labels_dir, "account_activity_variance_review_population", review)

    summary = {
        "truth": summarize(truth),
        "normal_controls": summarize(controls),
        "review_population": summarize(review),
    }

    summary_path = labels_dir / "anomaly_labels_summary.json"
    label_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    label_summary["v55_account_activity_variance"] = {
        "policy": "D01 account-level sidecars; do not evaluate D01 by document-level is_anomaly.",
        "summary": summary,
    }
    summary_path.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v55_candidate",
            "source": source.name,
            "purpose": "Add D01 account activity variance truth/control sidecars.",
            "summary": summary,
            "anti_fitting_policy": [
                "Do not change journal rows.",
                "Use fiscal_year+company_code+gl_account as the D01 evaluation unit.",
                "Separate confirmed account-level truth from normal high-variance controls.",
                "Do not require TP/FP/FN=0 because D01 is an analytical review signal.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V55_CANDIDATE.md").write_text(
        "# DataSynth v55 Candidate\n\n"
        "D01 account activity variance sidecar patch.\n\n"
        "- Source: `datasynth_v54_candidate`\n"
        "- Keeps journal rows and document labels unchanged.\n"
        "- Adds account-level truth, normal controls, and review population sidecars.\n"
        "- Evaluation unit: `fiscal_year + company_code + gl_account`.\n"
        "- 2023 compares against 2022; 2024 compares against 2023.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
