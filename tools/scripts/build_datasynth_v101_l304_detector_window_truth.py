"""Build v101 candidate by realigning L3-04 truth to detector period window.

The current L3-04 detector treats a document as period-end/start when:

- posting day is 1..5, or
- days remaining to month-end is 0..5.

That includes one more month-end boundary day than the old v94 builder.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v100_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v101_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-04"
WINDOW_DAYS = 5


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _period_window_mask(posting_date: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(posting_date, errors="coerce")
    days_to_month_end = parsed.dt.days_in_month - parsed.dt.day
    return parsed.notna() & (parsed.dt.day.le(WINDOW_DAYS) | days_to_month_end.le(WINDOW_DAYS))


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _build_year_truth(year: int) -> pd.DataFrame:
    df = pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False)
    if "posting_date" not in df.columns or "document_id" not in df.columns:
        raise SystemExit(f"journal_entries_{year}.csv missing posting_date or document_id")
    period_mask = _period_window_mask(df["posting_date"])
    work = df.loc[period_mask].copy()
    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            flagged_row_count=("document_id", "size"),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").fillna(year).astype(int)
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "actual period-end/start detector window review population"
    grouped["evaluation_unit"] = "document"
    grouped["truth_derivation"] = "posting_date day <= 5 or days_to_month_end <= 5"
    grouped["source_candidate"] = "v101"
    grouped["period_window_days"] = WINDOW_DAYS
    return grouped[
        [
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "document_type",
            "posting_date",
            "business_process",
            "source",
            "flagged_row_count",
            "rule_id",
            "expected_hit",
            "truth_layer",
            "truth_basis",
            "evaluation_unit",
            "truth_derivation",
            "source_candidate",
            "period_window_days",
        ]
    ]


def _replace_combined_rule_truth(l304: pd.DataFrame) -> None:
    combined_path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(combined_path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, l304], ignore_index=True, sort=False)
    rebuilt.to_csv(combined_path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _write_manifest(l304: pd.DataFrame, previous_count: int) -> None:
    manifest = {
        "version": "v101_candidate",
        "base_version": "v100_candidate",
        "patch": "l304_detector_period_window_truth",
        "rule_id": RULE_ID,
        "period_window_days": WINDOW_DAYS,
        "previous_l304_truth_count": int(previous_count),
        "truth_count": int(len(l304)),
        "added_truth_documents": int(len(l304) - previous_count),
        "truth_by_year": {str(k): int(v) for k, v in l304["fiscal_year"].value_counts().sort_index().items()},
        "contract": {
            "phase1_rule_truth": "posting day <= 5 or days_to_month_end <= 5",
            "why": "match current L3-04 detector window; score/priority still handled downstream",
        },
    }
    (LABELS / "V101_L304_DETECTOR_WINDOW_TRUTH.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V101_CANDIDATE.md").write_text(
        "# DataSynth v101 Candidate\n\n"
        "Base: `datasynth_v100_candidate`.\n\n"
        "Patch: rebuild L3-04 truth using the current detector period window.\n\n"
        f"```json\n{json.dumps(manifest, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    previous_count = len(pd.read_csv(LABELS / "rule_truth_L3_04.csv", usecols=["document_id"]))
    yearly = []
    for year in YEARS:
        truth = _build_year_truth(year)
        truth.to_csv(LABELS / f"rule_truth_L3_04_{year}.csv", index=False)
        _write_json_records(LABELS / f"rule_truth_L3_04_{year}.json", truth)
        yearly.append(truth)
    l304 = pd.concat(yearly, ignore_index=True)
    l304.to_csv(LABELS / "rule_truth_L3_04.csv", index=False)
    _write_json_records(LABELS / "rule_truth_L3_04.json", l304)
    _replace_combined_rule_truth(l304)
    _write_manifest(l304, previous_count)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "previous_l304_truth_count": int(previous_count),
                "l304_truth_count": int(len(l304)),
                "added_truth_documents": int(len(l304) - previous_count),
                "by_year": {
                    str(k): int(v) for k, v in l304["fiscal_year"].value_counts().sort_index().items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
