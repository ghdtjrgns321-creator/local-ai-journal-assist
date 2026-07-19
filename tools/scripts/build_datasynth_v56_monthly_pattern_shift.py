from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import pandas as pd


JSD_THRESHOLD = 0.30
REVIEW_JSD_LOW = 0.25
STRONG_JSD = 0.50
MIN_MONTHS = 3
MIN_ACCOUNT_DOCS = 100
MIN_TOP_MONTH_DELTA = 0.25
MAX_RELATED_DOCS = 25
TARGET_ANOMALIES = {
    "RevenueManipulation",
    "RevenueCutoffMismatch",
    "ExpenseCutoffMismatch",
    "WrongPeriod",
    "LatePosting",
    "BackdatedEntry",
    "RushedPeriodEnd",
    "ReversedAmount",
    "SuspenseAccountAbuse",
    "UnusualAccountPair",
    "BatchAnomaly",
}
NORMAL_CONTEXT_ANOMALIES = {
    "VagueDescription",
    "VagueOrRiskyDescription",
    "LateApproval",
    "MissingDocumentation",
    "AfterHoursPosting",
    "WeekendPosting",
    "ApprovalDateMissing",
}
STABLE_CONTROL_LIMIT_PER_YEAR = 120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v56 D02 monthly pattern shift sidecars.")
    parser.add_argument("--source", required=True, help="Source dataset directory, normally datasynth_v55_candidate")
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


def load_year(base: Path, year: int) -> tuple[pd.DataFrame, list[dict]]:
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
    blank = df[df["_account_code"].eq("")]
    exclusions = [
        {
            "case_id": f"D02-EXCL-BLANK-{year}-{idx:05d}",
            "fiscal_year": year,
            "prior_fiscal_year": year - 1 if year > 2022 else "",
            "company_code": row.get("company_code", ""),
            "gl_account": "",
            "document_id": row.get("document_id", ""),
            "exclusion_reason": "blank_gl_account",
            "evaluation_unit": "row_input_quality",
        }
        for idx, (_, row) in enumerate(blank.iterrows(), start=1)
    ]
    df = df[df["_account_code"].ne("") & df["_activity_amount"].gt(0)].copy()
    return df, exclusions


def distribution(values: pd.Series) -> tuple[list[float], int, int, float]:
    monthly = values.groupby(level=0).sum().reindex(range(1, 13), fill_value=0.0)
    total = float(monthly.sum())
    if total <= 0:
        return [0.0] * 12, 0, 0, 0.0
    ratios = [float(v / total) for v in monthly.tolist()]
    top_month = int(max(range(12), key=lambda idx: ratios[idx]) + 1)
    return ratios, int((monthly > 0).sum()), top_month, float(max(ratios))


def js_distance(a: list[float], b: list[float]) -> float:
    m = [(x + y) / 2 for x, y in zip(a, b)]

    def kld(p: list[float], q: list[float]) -> float:
        return sum(x * math.log(x / y) for x, y in zip(p, q) if x > 0 and y > 0)

    return math.sqrt((kld(a, m) + kld(b, m)) / 2)


def document_profiles(df: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    doc_label = (
        labels.groupby("document_id")["anomaly_type"]
        .agg(lambda values: "|".join(sorted(set(str(v) for v in values if str(v)))))
        .reset_index()
    )
    doc_label["has_d02_target_anomaly"] = doc_label["anomaly_type"].map(
        lambda text: bool(set(text.split("|")) & TARGET_ANOMALIES)
    )
    doc_label["has_normal_context_anomaly"] = doc_label["anomaly_type"].map(
        lambda text: bool(set(text.split("|")) & NORMAL_CONTEXT_ANOMALIES)
    )
    docs = (
        df[["company_code", "_account_code", "document_id", "business_process", "source", "fiscal_period"]]
        .drop_duplicates()
        .merge(doc_label, on="document_id", how="left")
    )
    docs["anomaly_type"] = docs["anomaly_type"].fillna("")
    docs["has_d02_target_anomaly"] = docs["has_d02_target_anomaly"].map(lambda value: value is True)
    docs["has_normal_context_anomaly"] = docs["has_normal_context_anomaly"].map(lambda value: value is True)
    docs["_is_manual"] = docs["source"].astype(str).str.lower().isin({"manual", "adjustment"})
    profile = (
        docs.groupby(["company_code", "_account_code"], dropna=False)
        .agg(
            related_document_ids=("document_id", lambda values: "|".join(sorted(set(values))[:MAX_RELATED_DOCS])),
            d02_target_document_count=("has_d02_target_anomaly", "sum"),
            normal_context_document_count=("has_normal_context_anomaly", "sum"),
            manual_document_count=("_is_manual", "sum"),
            business_processes=("business_process", lambda values: "|".join(sorted(set(str(v) for v in values if str(v))))),
            sources=("source", lambda values: "|".join(sorted(set(str(v) for v in values if str(v))))),
        )
        .reset_index()
        .rename(columns={"_account_code": "gl_account"})
    )
    return profile


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


def classify(row: pd.Series) -> tuple[str, str, bool]:
    family = account_family(row["gl_account"])
    jsd = float(row["jsd"])
    current_top_month = int(row["current_top_month"])
    target_docs = int(row.get("d02_target_document_count", 0))
    normal_docs = int(row.get("normal_context_document_count", 0))
    manual_docs = int(row.get("manual_document_count", 0))

    if target_docs > 0 and current_top_month in {11, 12} and family == "revenue":
        return "revenue_period_end_push", "", True
    if target_docs > 0 and current_top_month in {11, 12} and family in {"expense_or_cogs", "expense"}:
        return "expense_deferral_or_yearend_concentration", "", True
    if target_docs > 0 and jsd >= STRONG_JSD:
        return "target_anomaly_monthly_shift", "", True
    if target_docs > 0 and manual_docs > 0 and row["expected_d02_flag"]:
        return "manual_monthly_shift_with_target_anomaly", "", True

    if family == "revenue" and current_top_month in {3, 6, 9, 12}:
        return "normal_seasonal_or_quarter_end_revenue", "seasonal or quarter-end revenue concentration", False
    if family in {"expense_or_cogs", "expense"} and current_top_month in {6, 12}:
        return "normal_project_or_bonus_expense_concentration", "project cost, bonus, or year-end expense timing", False
    if "automated" in str(row.get("sources", "")).lower() or "recurring" in str(row.get("sources", "")).lower():
        return "normal_recurring_or_interface_batch", "recurring, depreciation, allocation, or interface batch pattern", False
    if normal_docs > target_docs:
        return "non_d02_document_context", "document-level context anomaly is not D02 monthly pattern truth", False
    if jsd <= REVIEW_JSD_LOW:
        return "stable_monthly_profile", "normal account with low year-over-year monthly drift", False
    return "review_only_monthly_shift", "insufficient evidence for confirmed D02 truth", False


def group_monthly(df: pd.DataFrame) -> dict[tuple[str, str], dict]:
    grouped: dict[tuple[str, str], dict] = {}
    monthly = (
        df.groupby(["company_code", "_account_code", "fiscal_period"], dropna=False)["_activity_amount"]
        .sum()
        .reset_index()
    )
    counts = (
        df.groupby(["company_code", "_account_code"], dropna=False)
        .agg(document_count=("document_id", "nunique"), annual_amount=("_activity_amount", "sum"))
        .reset_index()
    )
    count_map = {
        (row["company_code"], row["_account_code"]): (int(row["document_count"]), float(row["annual_amount"]))
        for _, row in counts.iterrows()
    }
    for (company, account), part in monthly.groupby(["company_code", "_account_code"], dropna=False):
        periods = pd.to_numeric(part["fiscal_period"], errors="coerce")
        amounts = pd.to_numeric(part["_activity_amount"], errors="coerce").fillna(0.0)
        series = pd.Series(amounts.to_numpy(), index=periods.to_numpy()).dropna()
        ratios, active_months, top_month, top_ratio = distribution(series)
        doc_count, annual_amount = count_map.get((company, account), (0, 0.0))
        grouped[(str(company), str(account))] = {
            "ratios": ratios,
            "active_months": active_months,
            "top_month": top_month,
            "top_ratio": top_ratio,
            "document_count": doc_count,
            "annual_amount": annual_amount,
        }
    return grouped


def build_records(base: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    labels = pd.read_csv(base / "labels" / "anomaly_labels.csv", dtype=str, usecols=["document_id", "anomaly_type"], keep_default_na=False)
    yearly: dict[int, pd.DataFrame] = {}
    exclusions: list[dict] = []
    for year in (2022, 2023, 2024):
        yearly[year], blank_exclusions = load_year(base, year)
        exclusions.extend(blank_exclusions)

    monthly_by_year = {year: group_monthly(df) for year, df in yearly.items()}
    profiles = {year: document_profiles(df, labels) for year, df in yearly.items()}

    confirmed: list[dict] = []
    controls: list[dict] = []
    review: list[dict] = []

    for year in (2023, 2024):
        prior_year = year - 1
        current_groups = monthly_by_year[year]
        prior_groups = monthly_by_year[prior_year]
        profile = profiles[year]
        profile_map = {
            (row["company_code"], row["gl_account"]): row.to_dict()
            for _, row in profile.iterrows()
        }
        stable_candidates: list[dict] = []
        all_keys = sorted(set(current_groups) | set(prior_groups))
        for ordinal, key in enumerate(all_keys, start=1):
            current = current_groups.get(key)
            prior = prior_groups.get(key)
            company, account = key
            if current is None:
                exclusions.append({
                    "case_id": f"D02-EXCL-MISSING-CURRENT-{year}-{ordinal:05d}",
                    "fiscal_year": year,
                    "prior_fiscal_year": prior_year,
                    "company_code": company,
                    "gl_account": account,
                    "document_id": "",
                    "exclusion_reason": "missing_current_account_group",
                    "evaluation_unit": "fiscal_year+company_code+gl_account",
                })
                continue
            if prior is None:
                exclusions.append({
                    "case_id": f"D02-EXCL-NEW-ACCOUNT-{year}-{ordinal:05d}",
                    "fiscal_year": year,
                    "prior_fiscal_year": prior_year,
                    "company_code": company,
                    "gl_account": account,
                    "document_id": "",
                    "exclusion_reason": "no_prior_account_group_use_d01",
                    "evaluation_unit": "fiscal_year+company_code+gl_account",
                })
                continue

            prior_months = int(prior["active_months"])
            current_months = int(current["active_months"])
            current_doc_count = int(current["document_count"])
            current_annual_amount = float(current["annual_amount"])
            jsd = js_distance(prior["ratios"], current["ratios"])
            top_delta = abs(float(current["top_ratio"]) - float(prior["top_ratio"]))
            skip_reason = ""
            if prior_months < MIN_MONTHS:
                skip_reason = "insufficient_prior_months"
            elif current_months < MIN_MONTHS:
                skip_reason = "insufficient_current_months"
            elif current_doc_count < MIN_ACCOUNT_DOCS:
                skip_reason = "insufficient_current_docs"
            elif top_delta < MIN_TOP_MONTH_DELTA:
                skip_reason = "small_top_month_delta"

            prof = profile_map.get((company, account), {})
            expected = not skip_reason and jsd > JSD_THRESHOLD
            row = pd.Series({
                "gl_account": account,
                "jsd": jsd,
                "current_top_month": int(current["top_month"]),
                "expected_d02_flag": expected,
                **prof,
            })
            scenario, normal_reason, is_truth = classify(row)
            record = {
                "case_id": f"D02-{year}-{ordinal:05d}",
                "fiscal_year": year,
                "prior_fiscal_year": prior_year,
                "company_code": company,
                "gl_account": account,
                "account_family": account_family(account),
                "monthly_pattern_label": "MonthlyPatternShift",
                "expected_d02_flag": bool(expected),
                "is_true_positive_account": bool(expected and is_truth),
                "scenario_type": scenario,
                "normal_reason": normal_reason,
                "jsd": round(float(jsd), 6),
                "jsd_threshold": JSD_THRESHOLD,
                "prior_active_months": prior_months,
                "current_active_months": current_months,
                "current_doc_count": current_doc_count,
                "current_annual_amount": round(current_annual_amount, 2),
                "prior_top_month": int(prior["top_month"]),
                "current_top_month": int(current["top_month"]),
                "prior_top_ratio": round(float(prior["top_ratio"]), 6),
                "current_top_ratio": round(float(current["top_ratio"]), 6),
                "top_month_delta": round(float(top_delta), 6),
                "min_top_month_delta": MIN_TOP_MONTH_DELTA,
                "skip_reason": skip_reason,
                "d02_target_document_count": int(prof.get("d02_target_document_count", 0) or 0),
                "normal_context_document_count": int(prof.get("normal_context_document_count", 0) or 0),
                "manual_document_count": int(prof.get("manual_document_count", 0) or 0),
                "business_processes": prof.get("business_processes", ""),
                "sources": prof.get("sources", ""),
                "related_document_ids": prof.get("related_document_ids", ""),
                "prior_distribution_json": json.dumps({i + 1: round(v, 6) for i, v in enumerate(prior["ratios"])}, ensure_ascii=False),
                "current_distribution_json": json.dumps({i + 1: round(v, 6) for i, v in enumerate(current["ratios"])}, ensure_ascii=False),
                "evaluation_unit": "fiscal_year+company_code+gl_account",
                "evaluation_policy": "D02 monthly-pattern sidecar; row-level flags are drill-down only.",
            }
            if skip_reason:
                if (
                    skip_reason == "small_top_month_delta"
                    and jsd <= REVIEW_JSD_LOW
                    and current_doc_count >= MIN_ACCOUNT_DOCS
                ):
                    stable_record = {
                        **record,
                        "expected_d02_flag": False,
                        "is_true_positive_account": False,
                        "scenario_type": "stable_monthly_profile",
                        "normal_reason": "normal account with low year-over-year monthly drift",
                    }
                    stable_candidates.append(stable_record)
                exclusions.append({
                    **{k: record[k] for k in [
                        "case_id",
                        "fiscal_year",
                        "prior_fiscal_year",
                        "company_code",
                        "gl_account",
                        "jsd",
                        "prior_active_months",
                        "current_active_months",
                        "current_doc_count",
                        "top_month_delta",
                    ]},
                    "document_id": "",
                    "exclusion_reason": skip_reason,
                    "evaluation_unit": "fiscal_year+company_code+gl_account",
                })
                continue
            if expected:
                review.append(record)
                if record["is_true_positive_account"]:
                    confirmed.append(record)
                else:
                    controls.append(record)
            elif scenario == "stable_monthly_profile":
                stable_candidates.append(record)

        stable_candidates = sorted(
            stable_candidates,
            key=lambda item: (float(item["jsd"]), item["company_code"], item["gl_account"]),
        )[:STABLE_CONTROL_LIMIT_PER_YEAR]
        controls.extend(stable_candidates)

    return confirmed, controls, review, exclusions


def summarize(records: list[dict]) -> dict:
    years = sorted({int(record["fiscal_year"]) for record in records if str(record.get("fiscal_year", "")).isdigit()})
    return {
        "total": len(records),
        "by_year": {
            str(year): sum(int(record["fiscal_year"]) == year for record in records)
            for year in years
        },
        "by_scenario": pd.Series([record.get("scenario_type", record.get("exclusion_reason", "")) for record in records]).value_counts().to_dict()
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
    confirmed, controls, review, exclusions = build_records(output)
    write_sidecar_family(labels_dir, "monthly_pattern_shift_confirmed_anomalies", confirmed)
    write_sidecar_family(labels_dir, "monthly_pattern_shift_normal_controls", controls)
    write_sidecar_family(labels_dir, "monthly_pattern_shift_review_population", review)
    write_sidecar_family(labels_dir, "monthly_pattern_shift_exclusions", exclusions)

    summary = {
        "confirmed_anomalies": summarize(confirmed),
        "normal_controls": summarize(controls),
        "review_population": summarize(review),
        "exclusions": summarize(exclusions),
    }
    summary_path = labels_dir / "anomaly_labels_summary.json"
    label_summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    label_summary["v56_monthly_pattern_shift"] = {
        "policy": "D02 account-level monthly pattern sidecars; do not evaluate D02 by document-level is_anomaly.",
        "summary": summary,
    }
    summary_path.write_text(json.dumps(label_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("candidate_patches", []).append(
        {
            "version": "v56_candidate",
            "source": source.name,
            "purpose": "Add D02 monthly pattern shift truth/control/exclusion sidecars.",
            "summary": summary,
            "anti_fitting_policy": [
                "Do not change journal rows or smooth monthly distributions.",
                "Use fiscal_year+company_code+gl_account as the D02 evaluation unit.",
                "Separate confirmed monthly shifts from normal seasonal/project/batch controls.",
                "Keep stable normal monthly profiles as negative controls.",
            ],
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    (output / "FREEZE_V56_CANDIDATE.md").write_text(
        "# DataSynth v56 Candidate\n\n"
        "D02 monthly pattern shift sidecar patch.\n\n"
        "- Source: `datasynth_v55_candidate`\n"
        "- Keeps journal rows and document labels unchanged.\n"
        "- Adds D02 confirmed anomalies, normal controls, review population, and exclusions.\n"
        "- Evaluation unit: `fiscal_year + company_code + gl_account`.\n"
        "- 2023 compares against 2022; 2024 compares against 2023.\n\n"
        f"Summary: `{json.dumps(summary, ensure_ascii=False)}`\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
