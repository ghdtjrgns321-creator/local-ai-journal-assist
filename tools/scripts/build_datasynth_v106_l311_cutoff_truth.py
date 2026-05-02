"""Build v106 candidate by realigning L3-11 cutoff truth to current journal.

Base: datasynth_v105_candidate.

This patch does not mutate journal rows. It rebuilds L3-11 rule truth and
cutoff sidecars from the current journal using the same date-gap contract as
the detector: business-day difference, revenue threshold > 5, expense threshold
> 7, revenue prefix 4, expense prefix 5.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v105_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v106_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
REVENUE_CUTOFF_DAYS = 5
EXPENSE_CUTOFF_DAYS = 7
MAX_DAY_DIFF = 30


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        year_df = df.loc[df["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _unique_join(values: pd.Series) -> str:
    cleaned = values.dropna().astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    cleaned = cleaned[cleaned.ne("") & ~cleaned.str.lower().isin({"nan", "none", "nat"})]
    return "|".join(sorted(cleaned.unique()))


def _read_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frames.append(pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False))
    return pd.concat(frames, ignore_index=True, sort=False)


def _business_day_diff(posting: pd.Series, delivery: pd.Series) -> pd.Series:
    posting_ts = pd.to_datetime(posting, errors="coerce")
    delivery_ts = pd.to_datetime(delivery, errors="coerce")
    valid = posting_ts.notna() & delivery_ts.notna()
    out = pd.Series(np.nan, index=posting.index, dtype="float64")
    if valid.any():
        p_np = posting_ts[valid].values.astype("datetime64[D]")
        d_np = delivery_ts[valid].values.astype("datetime64[D]")
        out.loc[valid] = np.abs(np.busday_count(d_np, p_np)).astype(float)
    return out


def _cutoff_anomaly_docs() -> set[str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return set()
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"], low_memory=False)
    return set(
        labels.loc[
            labels["anomaly_type"].isin({"RevenueCutoffMismatch", "ExpenseCutoffMismatch"}),
            "document_id",
        ].dropna().astype(str)
    )


def _build_cutoff_sets(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = rows.copy()
    work["_gl"] = work["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    work["_is_revenue"] = work["_gl"].str.startswith("4")
    work["_is_expense"] = work["_gl"].str.startswith("5")
    work["_business_day_diff"] = _business_day_diff(work["posting_date"], work["delivery_date"])
    work["_has_event_date"] = work["_business_day_diff"].notna()
    work["_is_cutoff_hit"] = (
        (work["_is_revenue"] & work["_business_day_diff"].gt(REVENUE_CUTOFF_DAYS))
        | (work["_is_expense"] & work["_business_day_diff"].gt(EXPENSE_CUTOFF_DAYS))
    )
    hit_rows = work.loc[work["_is_cutoff_hit"]].copy()
    hit_docs = set(hit_rows["document_id"].astype(str))

    doc_rows = work.drop_duplicates("document_id").copy()
    grouped = hit_rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        delivery_date=("delivery_date", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
        matched_accounts=("_gl", _unique_join),
        business_day_diff=("_business_day_diff", "max"),
        has_revenue_account=("_is_revenue", "max"),
        has_expense_account=("_is_expense", "max"),
    )
    grouped["cutoff_class"] = np.where(grouped["has_revenue_account"], "revenue_cutoff", "expense_cutoff")
    grouped["anomaly_type"] = np.where(
        grouped["cutoff_class"].eq("revenue_cutoff"),
        "RevenueCutoffMismatch",
        "ExpenseCutoffMismatch",
    )
    grouped["direction"] = np.where(
        pd.to_datetime(grouped["posting_date"], errors="coerce")
        .ge(pd.to_datetime(grouped["delivery_date"], errors="coerce")),
        "posted_after_event",
        "posted_before_event",
    )
    grouped = grouped.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    grouped["case_id"] = [
        f"L311REV-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(grouped.itertuples(index=False))
    ]
    grouped["population_id"] = [
        f"L311POP-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(grouped.itertuples(index=False))
    ]
    grouped["truth_basis"] = "posting date and event date exceed cutoff tolerance"
    grouped["normal_reason"] = ""

    rule_truth = grouped[
        [
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "case_id",
        ]
    ].copy()
    rule_truth["rule_id"] = "L3-11"
    rule_truth["expected_hit"] = True
    rule_truth["truth_layer"] = "rule_truth"
    rule_truth["truth_basis"] = "posting date and event date exceed cutoff tolerance"
    rule_truth["evaluation_unit"] = "document"

    review_population = grouped[
        [
            "population_id",
            "case_id",
            "document_id",
            "company_code",
            "fiscal_year",
            "posting_date",
            "delivery_date",
            "document_type",
            "business_process",
            "source",
            "created_by",
            "document_number",
            "matched_accounts",
            "cutoff_class",
            "anomaly_type",
            "business_day_diff",
            "direction",
            "truth_basis",
            "normal_reason",
        ]
    ].copy()

    cutoff_anomaly_docs = _cutoff_anomaly_docs()
    confirmed = review_population.loc[
        review_population["document_id"].astype(str).isin(cutoff_anomaly_docs)
    ].copy()

    candidate_rows = work.loc[
        work["_has_event_date"] & (work["_is_revenue"] | work["_is_expense"]) & ~work["document_id"].astype(str).isin(hit_docs)
    ].copy()
    normal_grouped = candidate_rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        delivery_date=("delivery_date", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
        matched_accounts=("_gl", _unique_join),
        business_day_diff=("_business_day_diff", "max"),
        has_revenue_account=("_is_revenue", "max"),
        has_expense_account=("_is_expense", "max"),
    )
    normal_grouped["cutoff_class"] = "normal_boundary"
    normal_grouped["anomaly_type"] = np.where(
        normal_grouped["has_revenue_account"],
        "NormalRevenueCutoffBoundary",
        "NormalExpenseCutoffBoundary",
    )
    normal_grouped["direction"] = np.where(
        pd.to_datetime(normal_grouped["posting_date"], errors="coerce")
        .ge(pd.to_datetime(normal_grouped["delivery_date"], errors="coerce")),
        "posted_after_event",
        "posted_before_event",
    )
    normal_grouped["normal_reason"] = "within_configured_cutoff_window"
    normal_grouped["truth_basis"] = "normal cutoff boundary control"
    normal_grouped = normal_grouped.sort_values(
        ["fiscal_year", "company_code", "document_number", "document_id"]
    ).reset_index(drop=True)
    normal_grouped["case_id"] = [
        f"L311NC-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(normal_grouped.itertuples(index=False))
    ]
    normal_controls = normal_grouped[
        [
            "case_id",
            "document_id",
            "company_code",
            "fiscal_year",
            "posting_date",
            "delivery_date",
            "document_type",
            "business_process",
            "source",
            "created_by",
            "document_number",
            "matched_accounts",
            "cutoff_class",
            "anomaly_type",
            "business_day_diff",
            "direction",
            "truth_basis",
            "normal_reason",
        ]
    ].copy()

    reasonable = review_population.loc[
        ~review_population["document_id"].astype(str).isin(cutoff_anomaly_docs)
    ].copy()
    if not reasonable.empty:
        reasonable["normal_reason"] = "raw_cutoff_review_not_injected_anomaly_label"
        reasonable["truth_basis"] = "rule truth cutoff hit without confirmed anomaly label"
    untestable_rows = doc_rows.loc[
        pd.to_datetime(doc_rows.get("delivery_date"), errors="coerce").isna()
    ].copy()
    # Keep this as a representative control sidecar. The exhaustive missing-event
    # population is too large for a controls file and is already derivable from
    # the journal.
    untestable_rows = (
        untestable_rows.sort_values(["fiscal_year", "business_process", "source", "company_code", "document_number", "document_id"])
        .groupby(["fiscal_year", "business_process", "source"], group_keys=False)
        .head(8)
        .reset_index(drop=True)
    )
    untestable = untestable_rows[
        [
            "document_id",
            "company_code",
            "fiscal_year",
            "posting_date",
            "document_type",
            "business_process",
            "source",
            "created_by",
            "document_number",
        ]
    ].copy()
    untestable["case_id"] = [
        f"L311UT-{int(float(row.fiscal_year))}-{idx + 1:04d}"
        for idx, row in enumerate(untestable.itertuples(index=False))
    ]
    untestable["matched_accounts"] = ""
    untestable["truth_basis"] = "untestable because recognition-basis event date is absent"
    untestable["normal_reason"] = "missing_delivery_date_is_unknown_not_normal"

    return rule_truth, review_population, confirmed, normal_controls, reasonable, untestable


def _rebuild_rule_truth_json() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if path.stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def main() -> None:
    _copy_candidate_safely()
    old_truth = pd.read_csv(LABELS / "rule_truth_L3_11.csv", dtype=str, low_memory=False)
    old_normal = pd.read_csv(LABELS / "cutoff_normal_controls.csv", dtype=str, low_memory=False)
    rows = _read_rows()
    rule_truth, review, confirmed, normal, reasonable, untestable = _build_cutoff_sets(rows)

    _write_family("rule_truth_L3_11", rule_truth)
    _write_family("cutoff_review_population", review)
    _write_family("cutoff_confirmed_anomalies", confirmed)
    _write_family("cutoff_normal_controls", normal)
    _write_family("cutoff_reasonable_delay_controls", reasonable)
    _write_family("cutoff_untestable_controls", untestable)
    combined = _rebuild_rule_truth_json()

    old_ids = set(old_truth["document_id"].dropna().astype(str))
    new_ids = set(rule_truth["document_id"].dropna().astype(str))
    old_normal_ids = set(old_normal["document_id"].dropna().astype(str))
    summary = {
        "version": "v106_candidate",
        "base_version": "v105_candidate",
        "journal_rows_mutated": 0,
        "rule_truth_rebuilt": ["L3-11"],
        "old_l311_truth_docs": int(len(old_ids)),
        "new_l311_truth_docs": int(len(new_ids)),
        "added_truth_docs": sorted(new_ids - old_ids),
        "removed_truth_docs": sorted(old_ids - new_ids),
        "added_from_old_normal_controls": sorted((new_ids - old_ids) & old_normal_ids),
        "cutoff_review_population": int(len(review)),
        "cutoff_confirmed_anomalies": int(len(confirmed)),
        "cutoff_normal_controls": int(len(normal)),
        "cutoff_reasonable_delay_controls": int(len(reasonable)),
        "cutoff_untestable_controls": int(len(untestable)),
        "combined_rule_truth_counts": {
            str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().items()
        },
    }
    (LABELS / "V106_L311_CUTOFF_TRUTH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V106_CANDIDATE.md").write_text(
        "# DataSynth v106 Candidate\n\n"
        "Base: `datasynth_v105_candidate`.\n\n"
        "Patch: rebuild L3-11 cutoff truth and sidecars from current journal fields.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
