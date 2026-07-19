"""Build v94 candidate by rebuilding L3-04 truth from the current journal.

L3-04 is a Phase 1 review-population rule: entries posted within the
configured period-end/start window are rule truth. High amount, manual source,
and injected RushedPeriodEnd scenarios are priority/context signals, not truth
prerequisites.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v93_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v94_candidate"
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
    month_end_start_day = parsed.dt.days_in_month - WINDOW_DAYS + 1
    return parsed.notna() & (parsed.dt.day.le(WINDOW_DAYS) | parsed.dt.day.ge(month_end_start_day))


def _build_year_truth(year: int) -> pd.DataFrame:
    df = pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False)
    if "posting_date" not in df.columns or "document_id" not in df.columns:
        raise SystemExit(f"journal_entries_{year}.csv missing posting_date or document_id")

    period_mask = _period_window_mask(df["posting_date"])
    work = df.loc[period_mask].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
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
        )

    def first_non_null(values: pd.Series) -> object:
        clean = values.dropna()
        return None if clean.empty else clean.iloc[0]

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", first_non_null),
            company_code=("company_code", first_non_null),
            document_number=("document_number", first_non_null),
            document_type=("document_type", first_non_null),
            posting_date=("posting_date", first_non_null),
            business_process=("business_process", first_non_null),
            source=("source", first_non_null),
            flagged_row_count=("document_id", "size"),
        )
        .reset_index()
    )

    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").fillna(year).astype(int)
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "actual period-end/start window review population"
    grouped["evaluation_unit"] = "document"
    grouped["truth_derivation"] = "posting_date within month-end/month-start +/- 5 days"
    grouped["source_candidate"] = "v94"
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


def _write_manifest(l304: pd.DataFrame) -> None:
    anomaly_path = LABELS / "anomaly_labels.csv"
    rushed_count = 0
    if anomaly_path.exists():
        labels = pd.read_csv(anomaly_path, usecols=["anomaly_type"], low_memory=False)
        rushed_count = int(labels["anomaly_type"].eq("RushedPeriodEnd").sum())

    manifest = {
        "version": "v94_candidate",
        "base_version": "v93_candidate",
        "patch": "l304_period_window_truth",
        "rule_id": RULE_ID,
        "period_window_days": WINDOW_DAYS,
        "truth_count": int(len(l304)),
        "truth_by_year": {str(k): int(v) for k, v in l304["fiscal_year"].value_counts().sort_index().items()},
        "rushed_period_end_injected_labels": rushed_count,
        "contract": {
            "phase1_rule_truth": "posting_date within month-end/month-start +/- 5 days",
            "priority_only_signals": [
                "high_amount",
                "manual_or_adjustment_source",
                "sensitive_account",
                "approval_issue",
                "abnormal_timing",
                "weak_description",
                "RushedPeriodEnd injected scenario",
            ],
        },
    }
    (LABELS / "V94_L304_PERIOD_WINDOW_TRUTH.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V94_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v94 Candidate",
                "",
                "Base: `datasynth_v93_candidate`",
                "",
                "Patch: rebuild `L3-04` rule truth from the current journal.",
                "",
                "Contract:",
                "- L3-04 Phase 1 truth is every document posted within month-end/month-start +/- 5 days.",
                "- High amount, manual source, and `RushedPeriodEnd` injected labels are priority/scenario signals only.",
                "",
                f"Truth count: {len(l304):,}",
                "",
                "Year split:",
                *[
                    f"- {year}: {count:,}"
                    for year, count in l304["fiscal_year"].value_counts().sort_index().items()
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
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
    _write_manifest(l304)

    print(json.dumps({
        "dest": str(DEST.relative_to(ROOT)),
        "l304_truth_count": int(len(l304)),
        "by_year": {str(k): int(v) for k, v in l304["fiscal_year"].value_counts().sort_index().items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
