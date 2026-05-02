"""Build v89 candidate by realigning L3-05 calendar truth.

L3-05 rule truth is the current journal posting calendar condition:
weekend or holiday. Earlier source/date patches can make old sidecars stale, so
this patch rebuilds rule_truth_L3_05 and weekend_review_population from
posting_date.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v88_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v89_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-05"


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
        # Minimal fixed-date fallback. The project environment normally has
        # holidays installed; this keeps the builder usable in constrained envs.
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


def _read_year_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _load_label_types() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"])
    return labels.groupby("document_id")["anomaly_type"].apply(lambda s: "|".join(sorted(set(s.dropna().astype(str))))).to_dict()


def _signal_reason(row: pd.Series) -> tuple[str, str]:
    is_weekend = bool(row["is_weekend"])
    is_holiday = bool(row["is_holiday"])
    if is_weekend and is_holiday:
        return "weekend_holiday", "weekend_and_legal_or_company_holiday_posting"
    if is_holiday:
        return "weekday_holiday", "legal_or_company_holiday_posting"
    return "weekend", "weekend_posting"


def _build_l305_truth(rows: pd.DataFrame) -> pd.DataFrame:
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
    truth = docs.loc[docs["is_weekend"] | docs["is_holiday"]].copy()
    reasons = truth.apply(_signal_reason, axis=1, result_type="expand")
    truth["calendar_signal"] = reasons[0]
    truth["calendar_reason"] = reasons[1]
    label_types = _load_label_types()
    truth["rule_id"] = RULE_ID
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


def _write_l305_truth(truth: pd.DataFrame) -> None:
    for stem in ("rule_truth_L3_05", "weekend_review_population"):
        truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    combined_json = LABELS / "rule_truth.json"
    if combined_json.exists():
        combined_json.unlink()
    return combined


def main() -> None:
    _copy_candidate_safely()
    rows = _read_year_rows()
    old_truth = pd.read_csv(LABELS / "rule_truth_L3_05.csv", dtype=str)
    old_docs = set(old_truth["document_id"].astype(str))
    truth = _build_l305_truth(rows)
    _write_l305_truth(truth)
    combined = _rebuild_combined_rule_truth()

    new_docs = set(truth["document_id"].astype(str))
    by_year = truth.groupby("fiscal_year")["document_id"].nunique().to_dict()
    by_signal = truth["calendar_signal"].value_counts().sort_index().to_dict()
    summary = {
        "candidate": "v89",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "realign L3-05 rule truth to current journal posting_date calendar condition",
        "old_l305_truth_docs": int(len(old_docs)),
        "new_l305_truth_docs": int(len(new_docs)),
        "old_minus_new_docs": int(len(old_docs - new_docs)),
        "new_minus_old_docs": int(len(new_docs - old_docs)),
        "new_l305_truth_by_year": {str(k): int(v) for k, v in by_year.items()},
        "new_l305_truth_by_signal": {str(k): int(v) for k, v in by_signal.items()},
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V89_L305_CALENDAR_TRUTH.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "FREEZE_V89_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v89 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: realign L3-05 rule truth to current posting-date calendar condition.",
                "",
                f"- L3-05 old truth docs: `{summary['old_l305_truth_docs']}`",
                f"- L3-05 new truth docs: `{summary['new_l305_truth_docs']}`",
                f"- Old minus new: `{summary['old_minus_new_docs']}`",
                f"- New minus old: `{summary['new_minus_old_docs']}`",
                f"- By year: `{summary['new_l305_truth_by_year']}`",
                f"- By signal: `{summary['new_l305_truth_by_signal']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
