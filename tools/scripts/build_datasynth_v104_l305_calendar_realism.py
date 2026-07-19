"""Build v104 candidate by reducing excessive normal weekend/holiday postings.

This patch starts from v103. It mutates only selected normal journal posting dates:

- preserve all L3-05 documents with anomaly labels
- preserve manual/adjustment weekend/holiday postings
- move a deterministic subset of normal automated/interface/recurring documents
  from weekend/holiday posting dates to nearby same-month business days
- rebuild L3-04 and L3-05 rule truth after the date changes
"""

from __future__ import annotations

import calendar
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v103_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v104_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
TARGET_L305_RATIO_BY_YEAR = {
    2022: 0.040,
    2023: 0.038,
    2024: 0.042,
}
PROTECTED_SOURCES = {"manual", "adjustment"}
MOVEABLE_SOURCES = {"automated", "interface", "recurring"}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _is_weekend_or_holiday(ts: pd.Timestamp, holidays: set[date]) -> bool:
    if pd.isna(ts):
        return False
    return bool(ts.dayofweek >= 5 or ts.date() in holidays)


def _nearest_same_month_business_datetime(value: str, holidays: set[date]) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return value
    original = ts.to_pydatetime()
    candidates: list[datetime] = []
    for offset in range(1, 8):
        candidates.extend([original + timedelta(days=offset), original - timedelta(days=offset)])
    for candidate in candidates:
        candidate_date = candidate.date()
        if candidate.month != original.month:
            continue
        if candidate.weekday() < 5 and candidate_date not in holidays:
            return candidate.strftime("%Y-%m-%d %H:%M:%S")
    # Conservative fallback: keep month stable and search every day in the month.
    _, last_day = calendar.monthrange(original.year, original.month)
    for day in range(1, last_day + 1):
        candidate = original.replace(day=day)
        candidate_date = candidate.date()
        if candidate.weekday() < 5 and candidate_date not in holidays:
            return candidate.strftime("%Y-%m-%d %H:%M:%S")
    return value


def _read_all_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _write_year_rows(rows: pd.DataFrame) -> None:
    rows = rows.drop(columns=["_year_file"], errors="ignore")
    for year in YEARS:
        year_rows = rows.loc[rows["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(year))].copy()
        year_rows.to_csv(DEST / f"journal_entries_{year}.csv", index=False, encoding="utf-8")


def _anomaly_docs() -> set[str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return set()
    labels = pd.read_csv(path, dtype=str, usecols=["document_id"], low_memory=False)
    return set(labels["document_id"].dropna().astype(str))


def _protected_rule_truth_docs() -> set[str]:
    protected: set[str] = set()
    for stem in ("rule_truth_L1_08", "rule_truth_L3_07", "rule_truth_L3_11"):
        path = LABELS / f"{stem}.csv"
        if path.exists():
            frame = pd.read_csv(path, dtype=str, usecols=["document_id"], low_memory=False)
            protected.update(frame["document_id"].dropna().astype(str))
    return protected


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _write_truth_family(stem: str, truth: pd.DataFrame) -> None:
    truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", truth)
    for year in YEARS:
        year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _signal_reason(row: pd.Series) -> tuple[str, str]:
    is_weekend = bool(row["is_weekend"])
    is_holiday = bool(row["is_holiday"])
    if is_weekend and is_holiday:
        return "weekend_holiday", "weekend_and_legal_or_company_holiday_posting"
    if is_holiday:
        return "weekday_holiday", "legal_or_company_holiday_posting"
    return "weekend", "weekend_posting"


def _label_types() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
    return labels.groupby("document_id")["anomaly_type"].apply(
        lambda s: "|".join(sorted(set(s.dropna().astype(str))))
    ).to_dict()


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


def _build_l304(rows: pd.DataFrame) -> pd.DataFrame:
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
    ts = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["posting_ts"] = ts
    days_in_month = ts.dt.days_in_month
    docs["days_to_month_end"] = days_in_month - ts.dt.day
    docs["is_period_start"] = ts.dt.day.le(5)
    docs["is_period_end"] = docs["days_to_month_end"].le(5)
    truth = docs.loc[ts.notna() & (docs["is_period_start"] | docs["is_period_end"])].copy()
    truth["rule_id"] = "L3-04"
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "period start or period end posting based on current journal posting_date"
    truth["evaluation_unit"] = "document"
    truth["population_type"] = "period_start_or_end_review_population"
    truth["posting_day"] = truth["posting_ts"].dt.day
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
        "is_period_start",
        "is_period_end",
        "days_to_month_end",
        "posting_day",
        "population_type",
    ]
    return truth[columns].sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)


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


def _select_calendar_docs_to_move(rows: pd.DataFrame) -> pd.DataFrame:
    holidays = _holiday_set([int(year) for year in YEARS])
    protected_docs = _anomaly_docs() | _protected_rule_truth_docs()
    docs = rows.drop_duplicates("document_id").copy()
    docs["posting_ts"] = pd.to_datetime(docs["posting_date"], errors="coerce")
    docs["is_l305"] = docs["posting_ts"].map(lambda ts: _is_weekend_or_holiday(ts, holidays))
    docs["source_norm"] = docs["source"].fillna("").astype(str).str.lower().str.strip()
    docs["fiscal_year_int"] = docs["fiscal_year"].astype(str).str.replace(r"\.0$", "", regex=True).astype(int)
    docs["is_protected_truth"] = docs["document_id"].astype(str).isin(protected_docs)
    l305 = docs.loc[docs["is_l305"]].copy()
    selected_frames = []
    for year in YEARS:
        year_docs = docs.loc[docs["fiscal_year_int"].eq(year)]
        current = l305.loc[l305["fiscal_year_int"].eq(year)]
        target = round(len(year_docs) * TARGET_L305_RATIO_BY_YEAR[year])
        remove_count = max(0, len(current) - target)
        candidates = current.loc[
            ~current["is_protected_truth"] & current["source_norm"].isin(MOVEABLE_SOURCES)
        ].copy()
        candidates["_source_priority"] = candidates["source_norm"].map(
            {"automated": 0, "interface": 1, "recurring": 2}
        ).fillna(9)
        candidates = candidates.sort_values(
            ["_source_priority", "business_process", "company_code", "document_number", "document_id"]
        )
        selected_frames.append(candidates.head(remove_count))
    if not selected_frames:
        return pd.DataFrame()
    return pd.concat(selected_frames, ignore_index=True, sort=False)


def _apply_calendar_realism(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    holidays = _holiday_set([int(year) for year in YEARS])
    selected = _select_calendar_docs_to_move(rows)
    move_map = {
        str(row.document_id): _nearest_same_month_business_datetime(str(row.posting_date), holidays)
        for row in selected.itertuples(index=False)
    }
    before_dates = selected.set_index("document_id")["posting_date"].astype(str).to_dict()
    rows = rows.copy()
    target_mask = rows["document_id"].astype(str).isin(move_map)
    moved_journal_rows = int(target_mask.sum())
    rows.loc[target_mask, "posting_date"] = rows.loc[target_mask, "document_id"].map(move_map)
    new_ts = pd.to_datetime(rows.loc[target_mask, "posting_date"], errors="coerce")
    rows.loc[target_mask, "fiscal_period"] = new_ts.dt.month.astype("Int64").astype(str)

    summary = {
        "moved_documents": int(len(move_map)),
        "moved_journal_rows": moved_journal_rows,
        "moved_by_year": {str(k): int(v) for k, v in selected["fiscal_year_int"].value_counts().sort_index().items()},
        "moved_by_source": {str(k): int(v) for k, v in selected["source_norm"].value_counts().sort_index().items()},
        "protected_sources": sorted(PROTECTED_SOURCES),
        "moveable_sources": sorted(MOVEABLE_SOURCES),
        "protected_truth_documents_moved": int(selected["is_protected_truth"].sum()),
        "sample_moves": [
            {
                "document_id": did,
                "old_posting_date": before_dates[did],
                "new_posting_date": move_map[did],
            }
            for did in sorted(move_map)[:20]
        ],
    }
    return rows, summary


def _write_manifest(summary: dict[str, object]) -> None:
    (LABELS / "V104_L305_CALENDAR_REALISM.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V104_CANDIDATE.md").write_text(
        "# DataSynth v104 Candidate\n\n"
        "Base: `datasynth_v103_candidate`.\n\n"
        "Patch: reduce excessive normal weekend/holiday postings by moving selected "
        "automated/interface/recurring documents to nearby same-month business days, "
        "then rebuild L3-04 and L3-05 truth.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    rows = _read_all_rows()
    old_l305 = pd.read_csv(LABELS / "rule_truth_L3_05.csv", dtype=str, low_memory=False)
    old_l304 = pd.read_csv(LABELS / "rule_truth_L3_04.csv", dtype=str, low_memory=False)

    rows, move_summary = _apply_calendar_realism(rows)
    _write_year_rows(rows)

    rebuilt_rows = _read_all_rows()
    l304 = _build_l304(rebuilt_rows)
    l305 = _build_l305(rebuilt_rows)
    _write_truth_family("rule_truth_L3_04", l304)
    _write_truth_family("period_end_review_population", l304)
    _write_truth_family("rule_truth_L3_05", l305)
    _write_truth_family("weekend_review_population", l305)
    combined = _rebuild_rule_truth_json()

    total_docs = rebuilt_rows["document_id"].nunique()
    summary = {
        "version": "v104_candidate",
        "base_version": "v103_candidate",
        "journal_rows_mutated": int(move_summary["moved_journal_rows"]),
        "L3-05_old_docs": int(old_l305["document_id"].nunique()),
        "L3-05_new_docs": int(l305["document_id"].nunique()),
        "L3-05_new_ratio": round(float(l305["document_id"].nunique() / total_docs), 4),
        "L3-05_by_year": {str(k): int(v) for k, v in l305["fiscal_year"].value_counts().sort_index().items()},
        "L3-05_by_source": {str(k): int(v) for k, v in l305["source"].value_counts().sort_index().items()},
        "L3-04_old_docs": int(old_l304["document_id"].nunique()),
        "L3-04_new_docs": int(l304["document_id"].nunique()),
        "move_summary": move_summary,
        "combined_rule_truth_counts": {
            str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().items()
        },
    }
    _write_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
