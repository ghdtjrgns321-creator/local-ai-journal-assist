"""Build v105 candidate by fixing and adding L3 explanatory sidecars.

Base: datasynth_v104_candidate.

This patch does not mutate journal rows or rule truth. It only rebuilds or adds
sidecars that explain L3 review populations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v104_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v105_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)


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


def _read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(LABELS / name, dtype=str, low_memory=False)


def _read_journal_docs() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True, sort=False)
    amount_cols = ["debit_amount", "credit_amount", "local_amount"]
    for col in amount_cols:
        if col in rows.columns:
            rows[col] = pd.to_numeric(rows[col], errors="coerce").fillna(0)
    docs = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        created_by=("created_by", "first"),
        max_line_amount=("local_amount", "max"),
        line_count=("line_number", "count"),
    )
    return docs


def _label_type_map() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"], low_memory=False)
    return labels.groupby("document_id")["anomaly_type"].apply(
        lambda s: "|".join(sorted(set(s.dropna().astype(str))))
    ).to_dict()


def _with_label_flags(df: pd.DataFrame, label_map: dict[str, str]) -> pd.DataFrame:
    out = df.copy()
    out["related_anomaly_types"] = out["document_id"].astype(str).map(label_map).fillna("")
    out["has_any_anomaly_label"] = out["related_anomaly_types"].ne("")
    return out


def _representative_sample(df: pd.DataFrame, per_year: int, sort_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    chunks = []
    for year, year_df in df.groupby(df["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True), sort=True):
        source_groups = []
        per_source = max(1, per_year // max(1, year_df["source"].nunique()))
        for _, source_df in year_df.groupby("source", sort=True):
            source_groups.append(source_df.sort_values(sort_cols).head(per_source))
        sampled = pd.concat(source_groups, ignore_index=True, sort=False).sort_values(sort_cols).head(per_year)
        chunks.append(sampled)
    return pd.concat(chunks, ignore_index=True, sort=False)


def _rebuild_l305_contexts(label_map: dict[str, str]) -> dict[str, int]:
    weekend = _read_csv("weekend_review_population.csv")
    weekend = _with_label_flags(weekend, label_map)

    normal = weekend.loc[~weekend["has_any_anomaly_label"].astype(bool)].copy()
    normal["sidecar_semantics"] = "normal_context_within_l305_review_population"
    normal["within_l305_review_population"] = True
    normal["not_a_negative_control"] = True
    normal["evaluation_policy"] = "context_only_not_strict_precision_denominator"
    normal["normal_context_type"] = normal["calendar_signal"].map(
        {
            "weekend": "routine_weekend_operation",
            "weekday_holiday": "routine_holiday_operation",
            "weekend_holiday": "routine_weekend_holiday_operation",
        }
    ).fillna("routine_weekend_or_holiday_operation")
    _write_family("normal_weekend_context", normal)
    _write_family("weekend_normal_context_within_review_population", normal)

    confirmed = weekend.loc[weekend["related_anomaly_types"].str.contains("WeekendPosting", na=False)].copy()
    confirmed["sidecar_semantics"] = "confirmed_weekend_posting_anomaly_subset"
    confirmed["within_l305_review_population"] = True
    _write_family("weekend_confirmed_anomalies", confirmed)
    return {
        "normal_weekend_context": int(len(normal)),
        "weekend_confirmed_anomalies": int(len(confirmed)),
    }


def _rebuild_l306_alias(label_map: dict[str, str]) -> dict[str, int]:
    legacy = _read_csv("normal_after_hours_context.csv")
    review_ids = set(_read_csv("afterhours_review_population.csv")["document_id"].dropna().astype(str))
    alias = _with_label_flags(legacy, label_map)
    alias["within_l306_review_population"] = alias["document_id"].astype(str).isin(review_ids)
    alias["sidecar_semantics"] = "normal_context_within_l306_afterhours_review_population"
    alias["not_a_negative_control"] = True
    alias["evaluation_policy"] = "context_only_not_strict_precision_denominator"
    _write_family("afterhours_normal_context_within_review_population", alias)
    return {
        "afterhours_normal_context_within_review_population": int(len(alias)),
        "outside_l306_review_population": int((~alias["within_l306_review_population"]).sum()),
    }


def _build_l304_contexts(docs: pd.DataFrame, label_map: dict[str, str]) -> dict[str, int]:
    truth = _read_csv("rule_truth_L3_04.csv")
    truth = truth.merge(
        docs[["document_id", "max_line_amount", "line_count"]],
        on="document_id",
        how="left",
    )
    truth = _with_label_flags(truth, label_map)
    truth["source_norm"] = truth["source"].fillna("").str.lower().str.strip()
    truth["max_line_amount"] = pd.to_numeric(truth["max_line_amount"], errors="coerce").fillna(0)
    threshold = truth["max_line_amount"].quantile(0.99)

    normal = truth.loc[
        (~truth["has_any_anomaly_label"])
        & truth["source_norm"].isin({"automated", "interface", "recurring"})
    ].copy()
    normal = _representative_sample(
        normal,
        per_year=1200,
        sort_cols=["source_norm", "business_process", "company_code", "document_number", "document_id"],
    )
    normal["sidecar_semantics"] = "representative_normal_close_context_within_l304_review_population"
    normal["within_l304_review_population"] = True
    normal["sample_policy"] = "deterministic_representative_sample_by_year_source_process"

    priority = truth.loc[
        truth["has_any_anomaly_label"]
        | truth["source_norm"].isin({"manual", "adjustment"})
        | truth["max_line_amount"].ge(threshold)
    ].copy()
    priority = _representative_sample(
        priority,
        per_year=1500,
        sort_cols=["source_norm", "business_process", "company_code", "document_number", "document_id"],
    )
    priority["sidecar_semantics"] = "priority_context_within_l304_review_population"
    priority["within_l304_review_population"] = True
    priority["priority_reason"] = ""
    priority.loc[priority["has_any_anomaly_label"], "priority_reason"] += "anomaly_label;"
    priority.loc[priority["source_norm"].isin({"manual", "adjustment"}), "priority_reason"] += "manual_or_adjustment;"
    priority.loc[priority["max_line_amount"].ge(threshold), "priority_reason"] += "top_1pct_amount;"

    _write_family("period_end_normal_close_context", normal)
    _write_family("period_end_priority_context", priority)
    return {
        "period_end_normal_close_context": int(len(normal)),
        "period_end_priority_context": int(len(priority)),
        "period_end_priority_amount_threshold": int(threshold),
    }


def _build_l302_contexts(docs: pd.DataFrame, label_map: dict[str, str]) -> dict[str, int]:
    truth = _read_csv("rule_truth_L3_02.csv")
    truth = truth.merge(
        docs[["document_id", "max_line_amount", "line_count"]],
        on="document_id",
        how="left",
    )
    truth = _with_label_flags(truth, label_map)
    high_risk_ids = set(_read_csv("rule_truth_L3_10.csv")["document_id"].dropna().astype(str))
    truth["within_l310_high_risk_account_population"] = truth["document_id"].astype(str).isin(high_risk_ids)

    normal = truth.loc[
        (~truth["has_any_anomaly_label"])
        & (~truth["within_l310_high_risk_account_population"])
    ].copy()
    normal = _representative_sample(
        normal,
        per_year=1200,
        sort_cols=["source", "business_process", "company_code", "document_number", "document_id"],
    )
    normal["sidecar_semantics"] = "representative_normal_manual_adjustment_context_within_l302_population"
    normal["within_l302_review_population"] = True
    normal["sample_policy"] = "deterministic_representative_sample_by_year_source_process"

    confirmed = truth.loc[truth["related_anomaly_types"].str.contains("ManualOverride", na=False)].copy()
    confirmed["sidecar_semantics"] = "confirmed_manual_override_anomaly_subset"
    confirmed["within_l302_review_population"] = True

    sensitive = truth.loc[truth["within_l310_high_risk_account_population"]].copy()
    sensitive["sidecar_semantics"] = "manual_adjustment_sensitive_account_context"
    sensitive["within_l302_review_population"] = True
    sensitive["within_l310_high_risk_account_population"] = True

    _write_family("manual_entry_normal_context", normal)
    _write_family("manual_override_confirmed_anomalies", confirmed)
    _write_family("manual_sensitive_account_context", sensitive)
    return {
        "manual_entry_normal_context": int(len(normal)),
        "manual_override_confirmed_anomalies": int(len(confirmed)),
        "manual_sensitive_account_context": int(len(sensitive)),
    }


def _build_l303_contexts() -> dict[str, int]:
    exceptions = _read_csv("intercompany_exception_cases.csv")
    mapping = {
        "UnmatchedIntercompany": "ic_unmatched_cases",
        "IntercompanyAmountMismatch": "ic_amount_mismatch_cases",
        "IntercompanyTimingMismatch": "ic_timing_gap_cases",
        "TransferPricingAnomaly": "transfer_pricing_review_cases",
    }
    summary: dict[str, int] = {}
    for anomaly_type, stem in mapping.items():
        subset = exceptions.loc[exceptions["anomaly_type"].eq(anomaly_type)].copy()
        subset["sidecar_semantics"] = f"{anomaly_type}_drilldown_context"
        subset["source_sidecar"] = "intercompany_exception_cases"
        _write_family(stem, subset)
        summary[stem] = int(len(subset))
    return summary


def main() -> None:
    _copy_candidate_safely()
    docs = _read_journal_docs()
    label_map = _label_type_map()
    summary = {
        "version": "v105_candidate",
        "base_version": "v104_candidate",
        "journal_rows_mutated": 0,
        "rule_truth_mutated": 0,
        "L3-05": _rebuild_l305_contexts(label_map),
        "L3-06": _rebuild_l306_alias(label_map),
        "L3-04": _build_l304_contexts(docs, label_map),
        "L3-02": _build_l302_contexts(docs, label_map),
        "L3-03": _build_l303_contexts(),
    }
    (LABELS / "V105_L3_SIDECAR_CONTEXTS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V105_CANDIDATE.md").write_text(
        "# DataSynth v105 Candidate\n\n"
        "Base: `datasynth_v104_candidate`.\n\n"
        "Patch: rebuild/add L3 explanatory sidecars only. Journal rows and rule truth are unchanged.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
