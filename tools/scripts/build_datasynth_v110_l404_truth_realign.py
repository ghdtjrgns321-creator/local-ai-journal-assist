"""Build v110 candidate by realigning L4-04 truth to current detector universe.

L4-04 is a Phase 1 review anchor: if the current detector finds a rare
debit-credit account pair, the document belongs to the rule review universe.
Confirmed `UnusualAccountPair` labels and normal rare-pair controls remain
subsets/context sidecars, not exhaustive rule truth.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402
from src.detection.anomaly_rules_statistical import c09_rare_account_pair  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v109_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v110_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L4-04"


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "rule_truth_L4_04.csv")
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


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_journal_minimal() -> pd.DataFrame:
    usecols = {
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_text",
        "header_text",
        "is_period_end",
        "is_after_hours",
        "is_weekend",
        "is_holiday",
    }
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [column for column in header if column in usecols]
        frames.append(pd.read_csv(path, usecols=cols, low_memory=False))
    return pd.concat(frames, ignore_index=True)


def _truth_from_detector(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    result = c09_rare_account_pair(
        df,
        percentile=get_settings().account_pair_rare_percentile,
    )
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=df.index).fillna(0.0)

    work = df.loc[mask].copy()
    work["_l404_score"] = scores.loc[work.index].astype(float)
    work["_score_bucket"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("score_bucket", "")
    )
    work["_reason_codes"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reason_codes", []))
    )
    work["_rare_pair_count"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("rare_pair_count", 0)
    )
    work["_sample_pairs"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("sample_pairs", []))
    )
    work["_threshold_count"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("threshold_count")
    )

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            created_by=("created_by", _first_non_null),
            approved_by=("approved_by", _first_non_null),
            line_count=("document_id", "size"),
            l404_score=("_l404_score", "max"),
            score_bucket=("_score_bucket", _first_non_null),
            reason_codes=("_reason_codes", _first_non_null),
            rare_pair_count=("_rare_pair_count", "max"),
            sample_pairs=("_sample_pairs", _first_non_null),
            threshold_count=("_threshold_count", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "rare debit-credit account pair review population"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = (
        "src.detection.anomaly_rules_statistical.c09_rare_account_pair current detector output"
    )
    grouped["source_candidate"] = "v110"
    grouped["evaluation_policy"] = (
        "Phase1 raw review universe; confirmed anomaly subset and normal controls are separate"
    )
    grouped["case_id"] = [
        f"L404-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]

    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "line_count",
        "l404_score",
        "score_bucket",
        "reason_codes",
        "rare_pair_count",
        "sample_pairs",
        "threshold_count",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), (
        result.attrs.get("breakdown", {})
    )


def _write_truth_family(truth: pd.DataFrame) -> None:
    truth.to_csv(LABELS / "rule_truth_L4_04.csv", index=False)
    _write_json_records(LABELS / "rule_truth_L4_04.json", truth)
    truth.to_csv(LABELS / "rare_account_pair_review_population.csv", index=False)
    _write_json_records(LABELS / "rare_account_pair_review_population.json", truth)
    for year in YEARS:
        year_df = truth.loc[truth["fiscal_year"].eq(year)].copy()
        year_df.to_csv(LABELS / f"rule_truth_L4_04_{year}.csv", index=False)
        _write_json_records(LABELS / f"rule_truth_L4_04_{year}.json", year_df)
        year_df.to_csv(LABELS / f"rare_account_pair_review_population_{year}.csv", index=False)
        _write_json_records(LABELS / f"rare_account_pair_review_population_{year}.json", year_df)


def _replace_combined_rule_truth(truth: pd.DataFrame) -> None:
    path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, truth], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _read_docs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=lambda column: column == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str).unique())


def _write_manifest(truth: pd.DataFrame, breakdown: dict[str, object], previous_truth: set[str]) -> None:
    current_truth = set(truth["document_id"].astype(str))
    confirmed = _read_docs(LABELS / "rare_account_pair_confirmed_anomalies.csv")
    normal = _read_docs(LABELS / "rare_account_pair_normal_controls.csv")
    manifest = {
        "version": "v110_candidate",
        "base_version": "v109_candidate",
        "patch": "l404_truth_realign_to_detector_universe",
        "rule_id": RULE_ID,
        "truth_docs": int(len(current_truth)),
        "truth_by_year": {
            str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()
        },
        "added_docs": int(len(current_truth - previous_truth)),
        "removed_stale_docs": int(len(previous_truth - current_truth)),
        "confirmed_subset_docs": int(len(confirmed)),
        "confirmed_subset_in_truth": int(len(confirmed & current_truth)),
        "normal_control_docs": int(len(normal)),
        "normal_control_in_truth": int(len(normal & current_truth)),
        "score_bucket_counts": {
            str(k): int(v) for k, v in truth["score_bucket"].value_counts().items()
        },
        "detector_breakdown": breakdown,
        "contract": {
            "rule_truth": "current L4-04 detector review universe",
            "confirmed_anomalies": "subset only; not exhaustive precision denominator",
            "normal_controls": "legitimate rare-pair controls; may be raw L4-04 hits",
            "anti_fitting": (
                "Detector output is not changed. The truth sidecar is realigned to the "
                "current Phase1 raw review-anchor contract."
            ),
        },
    }
    (LABELS / "V110_L404_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V110_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v110 Candidate",
                "",
                "Base: `datasynth_v109_candidate`",
                "",
                "Patch: realign L4-04 rule truth to the current rare account-pair detector universe.",
                "",
                "Contract:",
                "- `rule_truth_L4_04.csv` and `rare_account_pair_review_population.csv` are the raw L4-04 review universe.",
                "- `rare_account_pair_confirmed_anomalies.csv` remains a confirmed anomaly subset.",
                "- `rare_account_pair_normal_controls.csv` remains legitimate rare-pair control context.",
                "",
                f"Truth documents: {len(current_truth):,}",
                f"Added documents: {len(current_truth - previous_truth):,}",
                f"Removed stale documents: {len(previous_truth - current_truth):,}",
                f"Confirmed subset in truth: {len(confirmed & current_truth):,} / {len(confirmed):,}",
                f"Normal controls in truth: {len(normal & current_truth):,} / {len(normal):,}",
                "",
                "This patch does not modify journal entry rows or the detector.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    previous_truth = _read_docs(LABELS / "rule_truth_L4_04.csv")
    df = _load_journal_minimal()
    truth, breakdown = _truth_from_detector(df)
    _write_truth_family(truth)
    _replace_combined_rule_truth(truth)
    _write_manifest(truth, breakdown, previous_truth)
    current_truth = set(truth["document_id"].astype(str))
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "truth_docs": int(len(current_truth)),
                "added_docs": int(len(current_truth - previous_truth)),
                "removed_stale_docs": int(len(previous_truth - current_truth)),
                "truth_by_year": {
                    str(k): int(v)
                    for k, v in truth["fiscal_year"].value_counts().sort_index().items()
                },
                "score_bucket_counts": {
                    str(k): int(v) for k, v in truth["score_bucket"].value_counts().items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
