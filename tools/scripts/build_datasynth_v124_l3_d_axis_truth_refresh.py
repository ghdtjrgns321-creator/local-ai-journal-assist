"""Build v124 candidate by refreshing L3/D axis rule truth.

Base: datasynth_v123_candidate.

This patch does not mutate journal rows. It refreshes L3 detector-contract
truth from the current yearly journal files for rules that can drift after
journal/date/source synchronization:

- L3-02: source is manual or adjustment.
- L3-04: posting date is within the configured period-start/end window.
- L3-05: posting date is a weekend or holiday.
- L3-11: revenue/expense cutoff gap exceeds the configured tolerance.

D01/D02 membership is not changed. For Phase 1 A-axis evaluation their
rule_truth files are already the macro review universe. Confirmed macro
anomaly subsets remain separate sidecars.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v123_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v124_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V124_CANDIDATE.md", "V124_L3_D_AXIS_TRUTH_REFRESH.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V124_L3_D_AXIS_TRUTH_REFRESH.json")
        if all(path.exists() for path in required):
            return
        raise SystemExit(f"destination exists but is incomplete: {DEST}")

    source_resolved = SOURCE.resolve()
    dest_resolved = DEST.resolve()
    allowed_root = (ROOT / "data" / "journal" / "primary").resolve()
    if allowed_root not in dest_resolved.parents:
        raise SystemExit(f"refusing to write outside DataSynth root: {DEST}")

    for src in SOURCE.rglob("*"):
        rel = src.relative_to(source_resolved)
        dst = dest_resolved / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.parts and rel.parts[0] == "labels":
            shutil.copy2(src, dst)
        else:
            os.link(src, dst)


def _cleanup_version_files() -> dict[str, list[str]]:
    removed_root: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed_root.append(path.name)
            path.unlink()
    removed_labels: list[str] = []
    for path in LABELS.glob("V*.json"):
        if re.match(r"^V\d+_.+\.json$", path.name):
            removed_labels.append(path.name)
            path.unlink()
    return {"root": sorted(removed_root), "labels": sorted(removed_labels)}


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    year_values = pd.to_numeric(df["fiscal_year"], errors="coerce")
    for year in YEARS:
        year_df = df.loc[year_values.eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _unique_join(values: pd.Series) -> str:
    cleaned = values.dropna().astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    cleaned = cleaned[cleaned.ne("") & ~cleaned.str.lower().isin({"nan", "none", "nat"})]
    return "|".join(sorted(cleaned.unique()))


def _read_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False)
        frame["_year_file"] = year
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _label_types() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"], low_memory=False)
    return labels.groupby("document_id")["anomaly_type"].apply(
        lambda s: "|".join(sorted(set(s.dropna().astype(str))))
    ).to_dict()


def _old_docs(stem: str) -> set[str]:
    path = LABELS / f"{stem}.csv"
    if not path.exists():
        return set()
    old = pd.read_csv(path, usecols=lambda c: c == "document_id", low_memory=False)
    if "document_id" not in old.columns:
        return set()
    return set(old["document_id"].dropna().astype(str))


def _summarize_change(stem: str, truth: pd.DataFrame) -> dict[str, Any]:
    old = _old_docs(stem)
    new = set(truth["document_id"].dropna().astype(str)) if "document_id" in truth.columns else set()
    return {
        "old_docs": int(len(old)),
        "new_docs": int(len(new)),
        "old_minus_new": int(len(old - new)),
        "new_minus_old": int(len(new - old)),
        "old_minus_new_ids": sorted(old - new)[:20],
        "new_minus_old_ids": sorted(new - old)[:20],
        "by_year": {
            str(int(k)): int(v)
            for k, v in pd.to_numeric(truth["fiscal_year"], errors="coerce")
            .dropna()
            .astype(int)
            .value_counts()
            .sort_index()
            .items()
        }
        if "fiscal_year" in truth.columns
        else {},
    }


def _build_l302(rows: pd.DataFrame) -> pd.DataFrame:
    source = rows["source"].fillna("").astype(str).str.strip().str.lower()
    work = rows.loc[source.isin({"manual", "adjustment"})].copy()
    truth = work.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
    )
    truth["rule_id"] = "L3-02"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "manual or adjustment source population matching current journal"
    truth["evaluation_unit"] = "document"
    truth["truth_derivation"] = "source in {manual, adjustment}"
    truth["source_candidate"] = "v124"
    truth["truth_contract_version"] = "v124_active_candidate_contract"
    return truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _period_window_mask(posting_date: pd.Series) -> pd.Series:
    settings = get_settings()
    window_days = int(getattr(settings, "period_end_window_days", 5) or 5)
    parsed = pd.to_datetime(posting_date, errors="coerce")
    days_to_month_end = parsed.dt.days_in_month - parsed.dt.day
    return parsed.notna() & (parsed.dt.day.le(window_days) | days_to_month_end.le(window_days))


def _build_l304(rows: pd.DataFrame) -> pd.DataFrame:
    mask = _period_window_mask(rows["posting_date"])
    work = rows.loc[mask].copy()
    grouped = work.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        flagged_row_count=("document_id", "size"),
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["rule_id"] = "L3-04"
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "period-start or period-end posting candidate based on current journal posting_date"
    grouped["evaluation_unit"] = "document"
    grouped["truth_derivation"] = "posting_date day <= 5 or days_to_month_end <= 5"
    grouped["source_candidate"] = "v124"
    grouped["truth_contract_version"] = "v124_active_candidate_contract"
    grouped["period_window_days"] = int(getattr(get_settings(), "period_end_window_days", 5) or 5)
    return grouped.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _holiday_set(years: list[int]) -> set[date]:
    try:
        import holidays as hol

        return set(hol.KR(years=years).keys())
    except Exception:
        return {
            date(year, month, day)
            for year in years
            for month, day in (
                (1, 1),
                (3, 1),
                (5, 5),
                (6, 6),
                (8, 15),
                (10, 3),
                (10, 9),
                (12, 25),
            )
        }


def _signal_reason(row: pd.Series) -> tuple[str, str]:
    is_weekend = bool(row["is_weekend"])
    is_holiday = bool(row["is_holiday"])
    if is_weekend and is_holiday:
        return "weekend_holiday", "weekend_and_legal_or_company_holiday_posting"
    if is_holiday:
        return "weekday_holiday", "legal_or_company_holiday_posting"
    return "weekend", "weekend_posting"


def _build_l305(rows: pd.DataFrame) -> pd.DataFrame:
    doc_cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
    ]
    docs = rows.drop_duplicates("document_id")[doc_cols].copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["posting_day"] = docs["posting_ts"].dt.date
    holidays = _holiday_set([int(year) for year in YEARS])
    docs["is_weekend"] = docs["posting_ts"].dt.dayofweek.ge(5)
    docs["is_holiday"] = docs["posting_day"].isin(holidays)
    truth = docs.loc[docs["posting_ts"].notna() & (docs["is_weekend"] | docs["is_holiday"])].copy()
    reasons = truth.apply(_signal_reason, axis=1, result_type="expand")
    truth["calendar_signal"] = reasons[0]
    truth["calendar_reason"] = reasons[1]
    label_types = _label_types()
    truth["rule_id"] = "L3-05"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "weekend or holiday posting based on current journal posting_date"
    truth["evaluation_unit"] = "document"
    truth["related_anomaly_types"] = truth["document_id"].map(label_types).fillna("")
    truth["has_any_anomaly_label"] = truth["related_anomaly_types"].ne("")
    truth["population_type"] = "weekend_or_holiday_review_population"
    truth["source_candidate"] = "v124"
    truth["truth_contract_version"] = "v124_active_candidate_contract"
    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "is_weekend",
        "is_holiday",
        "calendar_signal",
        "calendar_reason",
        "population_type",
        "has_any_anomaly_label",
        "related_anomaly_types",
        "source_candidate",
        "truth_contract_version",
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


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


def _build_l311(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    settings = get_settings()
    audit_rules = get_audit_rules()
    evidence_cfg = audit_rules.get("evidence", {})
    patterns = audit_rules.get("patterns", {})
    revenue_prefixes = tuple(evidence_cfg.get("revenue_account_prefixes") or patterns.get("revenue_account_prefixes") or ["4"])
    expense_prefixes = tuple(evidence_cfg.get("expense_account_prefixes") or ["5"])
    revenue_days = int(settings.ev_revenue_cutoff_days)
    expense_days = int(settings.ev_expense_cutoff_days)

    work = rows.copy()
    work["_gl"] = work["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    work["_is_revenue"] = work["_gl"].str.startswith(revenue_prefixes)
    work["_is_expense"] = work["_gl"].str.startswith(expense_prefixes)
    work["_business_day_diff"] = _business_day_diff(work["posting_date"], work["delivery_date"])
    work["_has_event_date"] = work["_business_day_diff"].notna()
    work["_is_cutoff_hit"] = (
        (work["_is_revenue"] & work["_business_day_diff"].gt(revenue_days))
        | (work["_is_expense"] & work["_business_day_diff"].gt(expense_days))
    )
    hit_rows = work.loc[work["_is_cutoff_hit"]].copy()
    hit_docs = set(hit_rows["document_id"].astype(str))
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
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
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
    grouped["case_id"] = [f"L311REV-{int(row.fiscal_year)}-{idx + 1:04d}" for idx, row in enumerate(grouped.itertuples(index=False))]
    grouped["population_id"] = [f"L311POP-{int(row.fiscal_year)}-{idx + 1:04d}" for idx, row in enumerate(grouped.itertuples(index=False))]
    grouped["truth_basis"] = "posting date and event date exceed cutoff tolerance"
    grouped["normal_reason"] = ""
    grouped["source_candidate"] = "v124"
    grouped["truth_contract_version"] = "v124_active_candidate_contract"

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
    rule_truth["truth_derivation"] = "current journal revenue/expense cutoff business-day gap"
    rule_truth["source_candidate"] = "v124"
    rule_truth["truth_contract_version"] = "v124_active_candidate_contract"

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
            "source_candidate",
            "truth_contract_version",
        ]
    ].copy()

    cutoff_anomaly_docs = _cutoff_anomaly_docs()
    confirmed = review_population.loc[
        review_population["document_id"].astype(str).isin(cutoff_anomaly_docs)
    ].copy()

    candidate_rows = work.loc[
        work["_has_event_date"]
        & (work["_is_revenue"] | work["_is_expense"])
        & ~work["document_id"].astype(str).isin(hit_docs)
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
    normal_grouped["fiscal_year"] = pd.to_numeric(normal_grouped["fiscal_year"], errors="coerce").astype(int)
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
    normal_grouped["source_candidate"] = "v124"
    normal_grouped["truth_contract_version"] = "v124_active_candidate_contract"
    normal_grouped = normal_grouped.sort_values(
        ["fiscal_year", "company_code", "document_number", "document_id"]
    ).reset_index(drop=True)
    normal_grouped["case_id"] = [
        f"L311NC-{int(row.fiscal_year)}-{idx + 1:04d}"
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
            "source_candidate",
            "truth_contract_version",
        ]
    ].copy()
    return rule_truth, review_population, confirmed, normal_controls


def _replace_combined_rule_truth(replacements: dict[str, pd.DataFrame]) -> int:
    frames: list[pd.DataFrame] = []
    replace_ids = set(replacements)
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        rule_id = path.stem.removeprefix("rule_truth_").replace("_", "-")
        if rule_id in replace_ids:
            frames.append(replacements[rule_id])
        else:
            frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return int(len(combined))


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        for column in ("source_candidate", "truth_contract_version"):
            if column in df.columns:
                df = df.drop(columns=[column])
        df["source_candidate"] = "v124"
        df["truth_contract_version"] = "v124_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            years = pd.to_numeric(df["fiscal_year"], errors="coerce")
            for year in YEARS:
                year_df = df.loc[years.eq(year)].copy()
                year_df.to_csv(LABELS / f"{path.stem}_{year}.csv", index=False)
                _write_json_records(LABELS / f"{path.stem}_{year}.json", year_df)
    return count


def _update_sidecar_manifest() -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    if not path.exists():
        return {"manifest_rows": 0}
    manifest = pd.read_csv(path, low_memory=False)
    manifest["source_candidate"] = "v124"
    updates = {
        "rule_truth_L3_02": ("L3-02", "strict_truth_alias", "detector_contract_universe"),
        "manual_entry_population_truth": ("L3-02", "strict_truth_alias", "detector_contract_universe"),
        "rule_truth_L3_04": ("L3-04", "strict_truth_alias", "detector_contract_universe"),
        "rule_truth_L3_05": ("L3-05", "strict_truth_alias", "detector_contract_universe"),
        "weekend_review_population": ("L3-05", "strict_truth_alias", "detector_contract_universe"),
        "rule_truth_L3_11": ("L3-11", "strict_truth_alias", "detector_contract_universe"),
        "cutoff_review_population": ("L3-11", "strict_truth_alias", "detector_contract_universe"),
        "rule_truth_D01": ("D01", "strict_truth_alias", "detector_contract_universe"),
        "rule_truth_D02": ("D02", "strict_truth_alias", "detector_contract_universe"),
    }
    for stem, (owner, role, purpose) in updates.items():
        mask = manifest["sidecar_name"].astype(str).eq(stem)
        if mask.any():
            manifest.loc[mask, "owner_rule"] = owner
            manifest.loc[mask, "sidecar_role"] = role
            manifest.loc[mask, "sidecar_purpose"] = purpose
            manifest.loc[mask, "expected_detector_positive"] = "true"
            manifest.loc[mask, "allowed_for_independent_sidecar_eval"] = False
    manifest.to_csv(path, index=False)
    _write_json_records(path.with_suffix(".json"), manifest)
    return {"manifest_rows": int(len(manifest))}


def _verify_l3_contracts(expected: dict[str, pd.DataFrame]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for rule_id, df in expected.items():
        stem = f"rule_truth_{rule_id.replace('-', '_')}"
        actual = pd.read_csv(LABELS / f"{stem}.csv", usecols=["document_id"], low_memory=False)
        expected_docs = set(df["document_id"].dropna().astype(str))
        actual_docs = set(actual["document_id"].dropna().astype(str))
        checks[rule_id] = {
            "expected_docs": int(len(expected_docs)),
            "truth_docs": int(len(actual_docs)),
            "truth_minus_expected": int(len(actual_docs - expected_docs)),
            "expected_minus_truth": int(len(expected_docs - actual_docs)),
        }
    return checks


def _verify_d_axis_contracts() -> dict[str, Any]:
    pairs = {
        "D01": ("rule_truth_D01", "account_activity_variance_review_population", "account_activity_variance_truth"),
        "D02": ("rule_truth_D02", "monthly_pattern_shift_review_population", "monthly_pattern_shift_truth"),
    }
    out: dict[str, Any] = {}
    for rule_id, (truth_stem, review_stem, confirmed_stem) in pairs.items():
        truth = pd.read_csv(LABELS / f"{truth_stem}.csv", low_memory=False)
        review = pd.read_csv(LABELS / f"{review_stem}.csv", low_memory=False)
        confirmed = pd.read_csv(LABELS / f"{confirmed_stem}.csv", low_memory=False)
        keys = ["fiscal_year", "company_code", "gl_account"]
        def keyset(df: pd.DataFrame) -> set[tuple[str, str, str]]:
            return set(
                zip(
                    pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64").astype(str),
                    df["company_code"].astype(str),
                    df["gl_account"].astype(str),
                )
            )

        truth_keys = keyset(truth)
        review_keys = keyset(review)
        confirmed_keys = keyset(confirmed)
        out[rule_id] = {
            "a_axis_truth_groups": int(len(truth_keys)),
            "review_universe_groups": int(len(review_keys)),
            "confirmed_truth_groups": int(len(confirmed_keys)),
            "truth_vs_review_diff": int(len(truth_keys ^ review_keys)),
            "confirmed_not_in_truth": int(len(confirmed_keys - truth_keys)),
            "a_axis_policy": "use rule_truth/review universe for Phase1 A-axis; confirmed subset belongs to downstream/B-C analysis",
        }
    return out


def _write_manifest(summary: dict[str, Any]) -> None:
    (DEST / "V124_L3_D_AXIS_TRUTH_REFRESH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V124_CANDIDATE.md").write_text(
        "# DataSynth v124 Candidate\n\n"
        "Base: `datasynth_v123_candidate`.\n\n"
        "Patch: refresh L3-02/L3-04/L3-05/L3-11 A-axis rule truth from the current "
        "yearly journal files and pin D01/D02 A-axis evaluation to macro rule-truth "
        "review universe files.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    cleanup = _cleanup_version_files()
    rows = _read_rows()

    l302 = _build_l302(rows)
    l304 = _build_l304(rows)
    l305 = _build_l305(rows)
    l311, cutoff_review, cutoff_confirmed, cutoff_normal = _build_l311(rows)

    changes = {
        "L3-02": _summarize_change("rule_truth_L3_02", l302),
        "L3-04": _summarize_change("rule_truth_L3_04", l304),
        "L3-05": _summarize_change("rule_truth_L3_05", l305),
        "L3-11": _summarize_change("rule_truth_L3_11", l311),
    }

    _write_family("rule_truth_L3_02", l302)
    _write_family("manual_entry_population_truth", l302)
    _write_family("rule_truth_L3_04", l304)
    _write_family("rule_truth_L3_05", l305)
    _write_family("weekend_review_population", l305)
    _write_family("rule_truth_L3_11", l311)
    _write_family("cutoff_review_population", cutoff_review)
    _write_family("cutoff_confirmed_anomalies", cutoff_confirmed)
    _write_family("cutoff_normal_controls", cutoff_normal)

    combined_rows = _replace_combined_rule_truth(
        {
            "L3-02": l302,
            "L3-04": l304,
            "L3-05": l305,
            "L3-11": l311,
        }
    )
    normalized = _normalize_rule_truth_metadata()
    manifest_update = _update_sidecar_manifest()

    # Reload after metadata normalization so the verification reflects written files.
    l3_written = {
        "L3-02": pd.read_csv(LABELS / "rule_truth_L3_02.csv", low_memory=False),
        "L3-04": pd.read_csv(LABELS / "rule_truth_L3_04.csv", low_memory=False),
        "L3-05": pd.read_csv(LABELS / "rule_truth_L3_05.csv", low_memory=False),
        "L3-11": pd.read_csv(LABELS / "rule_truth_L3_11.csv", low_memory=False),
    }
    summary: dict[str, Any] = {
        "version": "v124_candidate",
        "base_version": "v123_candidate",
        "journal_rows_mutated": 0,
        "patch": "l3_d_axis_truth_refresh",
        "cleanup": cleanup,
        "rule_truth_rebuilt": ["L3-02", "L3-04", "L3-05", "L3-11"],
        "rule_truth_metadata_normalized_files": normalized,
        "combined_rule_truth_rows": combined_rows,
        "changes": changes,
        "l3_contract_checks": _verify_l3_contracts(l3_written),
        "d_axis_contract_checks": _verify_d_axis_contracts(),
        "sidecar_manifest": manifest_update,
    }
    _write_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
