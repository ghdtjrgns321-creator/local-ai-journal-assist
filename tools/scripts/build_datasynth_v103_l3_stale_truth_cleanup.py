"""Build v103 candidate by cleaning stale L3 rule truth after later patches.

This patch starts from v102 and does not mutate journal rows. It rebuilds:

- L3-02 from current journal source in {manual, adjustment}
- L3-03 from current journal intercompany GL prefixes
- L3-05 from current journal posting_date weekend/holiday calendar
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v102_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v103_candidate"
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


def _read_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _unique_join(values: pd.Series) -> str:
    cleaned = values.dropna().astype(str).map(str.strip)
    cleaned = cleaned[cleaned.ne("") & ~cleaned.str.lower().isin({"nan", "none", "nat"})]
    return "|".join(sorted(cleaned.unique()))


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _label_types() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
    return labels.groupby("document_id")["anomaly_type"].apply(
        lambda s: "|".join(sorted(set(s.dropna().astype(str))))
    ).to_dict()


def _write_truth_family(stem: str, truth: pd.DataFrame) -> None:
    truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", truth)
    for year in YEARS:
        year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


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


def _old_docs(stem: str) -> set[str]:
    path = LABELS / f"{stem}.csv"
    if not path.exists():
        return set()
    old = pd.read_csv(path, dtype=str, usecols=["document_id"], low_memory=False)
    return set(old["document_id"].dropna().astype(str))


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
    truth["source_candidate"] = "v103"
    return truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _ic_prefixes() -> tuple[str, ...]:
    config_path = ROOT / "config" / "audit_rules.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    pairs = (((raw.get("patterns") or {}).get("intercompany") or {}).get("pairs") or [])
    prefixes: list[str] = []
    for pair in pairs:
        for key in ("receivable", "payable"):
            value = str(pair.get(key, "")).strip()
            if value:
                prefixes.append(value)
    return tuple(dict.fromkeys(prefixes or ["1150", "2050", "4500", "2700"]))


def _build_l303(rows: pd.DataFrame) -> pd.DataFrame:
    prefixes = _ic_prefixes()
    gl = rows["gl_account"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    ic_rows = rows.loc[gl.str.startswith(prefixes, na=False)].copy()
    ic_rows["_normalized_gl_account"] = gl.loc[ic_rows.index]
    ic_rows["_ic_prefix"] = ""
    for prefix in prefixes:
        ic_rows.loc[ic_rows["_normalized_gl_account"].str.startswith(prefix), "_ic_prefix"] = prefix

    label_types = _label_types()
    truth = ic_rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", _first_non_null),
        company_code=("company_code", _first_non_null),
        document_number=("document_number", _first_non_null),
        document_type=("document_type", _first_non_null),
        posting_date=("posting_date", _first_non_null),
        business_process=("business_process", _first_non_null),
        source=("source", _first_non_null),
        created_by=("created_by", _first_non_null),
        ic_account_prefixes=("_ic_prefix", _unique_join),
        ic_gl_accounts=("_normalized_gl_account", _unique_join),
        has_trading_partner=("trading_partner", lambda s: bool(_unique_join(s))),
        trading_partners=("trading_partner", _unique_join),
    )
    truth["rule_id"] = "L3-03"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "intercompany GL account prefix population matching current L3-03 detector contract"
    truth["population_basis"] = "ic_gl_account_prefix"
    truth["evaluation_unit"] = "document"
    truth["related_anomaly_types"] = truth["document_id"].map(label_types).fillna("")
    truth["has_any_anomaly_label"] = truth["related_anomaly_types"].ne("")
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
        "population_basis",
        "evaluation_unit",
        "ic_account_prefixes",
        "ic_gl_accounts",
        "has_trading_partner",
        "trading_partners",
        "has_any_anomaly_label",
        "related_anomaly_types",
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


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
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


def _summarize_change(stem: str, truth: pd.DataFrame) -> dict[str, object]:
    old = _old_docs(stem)
    new = set(truth["document_id"].astype(str))
    return {
        "old_docs": int(len(old)),
        "new_docs": int(len(new)),
        "old_minus_new": int(len(old - new)),
        "new_minus_old": int(len(new - old)),
        "old_minus_new_ids": sorted(old - new)[:20],
        "new_minus_old_ids": sorted(new - old)[:20],
        "by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()},
    }


def _write_manifest(summary: dict[str, object]) -> None:
    (LABELS / "V103_L3_STALE_TRUTH_CLEANUP.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V103_CANDIDATE.md").write_text(
        "# DataSynth v103 Candidate\n\n"
        "Base: `datasynth_v102_candidate`.\n\n"
        "Patch: rebuild L3-02/L3-03/L3-05 truth from current journal fields.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    rows = _read_rows()

    l302 = _build_l302(rows)
    l303 = _build_l303(rows)
    l305 = _build_l305(rows)

    summary = {
        "version": "v103_candidate",
        "base_version": "v102_candidate",
        "journal_rows_mutated": 0,
        "rule_truth_rebuilt": ["L3-02", "L3-03", "L3-05"],
        "L3-02": _summarize_change("rule_truth_L3_02", l302),
        "L3-03": _summarize_change("rule_truth_L3_03", l303),
        "L3-05": _summarize_change("rule_truth_L3_05", l305),
    }

    _write_truth_family("rule_truth_L3_02", l302)
    _write_truth_family("manual_entry_population_truth", l302)
    _write_truth_family("rule_truth_L3_03", l303)
    _write_truth_family("intercompany_population_truth", l303)
    _write_truth_family("rule_truth_L3_05", l305)
    _write_truth_family("weekend_review_population", l305)
    combined = _rebuild_rule_truth_json()
    summary["combined_rule_truth_counts"] = {
        str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().items()
    }
    _write_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
