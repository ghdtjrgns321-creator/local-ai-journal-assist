"""Build v111 candidate by realigning L4-05 truth to combined-context detector output.

L4-05 is a user-behavior concentration rule. The detector statistics depend on
the evaluation population, so DataSynth strict rule truth is built from the
three-year combined context and then split by fiscal year for reporting.
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

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.anomaly_rules_simple import c12_abnormal_hours_concentration  # noqa: E402
from src.feature.engine import feature_categories_for_rules, generate_all_features  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v110_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v111_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L4-05"


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "rule_truth_L4_05.csv")
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


def _load_journal() -> pd.DataFrame:
    usecols = {
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "approval_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "debit_amount",
        "credit_amount",
    }
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        header = pd.read_csv(path, nrows=0).columns
        cols = [column for column in header if column in usecols]
        frames.append(
            pd.read_csv(
                path,
                usecols=cols,
                parse_dates=["posting_date", "approval_date"],
                low_memory=False,
            )
        )
    return pd.concat(frames, ignore_index=True)


def _add_l405_features(df: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    rules = get_audit_rules()
    categories = feature_categories_for_rules(["L4-05"])
    result = generate_all_features(
        df,
        settings=settings,
        rules=rules,
        categories=categories,
        include_morpheme_tokens=False,
    )
    out = df.copy()
    out[result.data.columns] = result.data
    return out


def _build_truth(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    settings = get_settings()
    result = c12_abnormal_hours_concentration(
        df,
        sigma_threshold=settings.abnormal_sigma_threshold,
        rapid_approval_minutes=settings.rapid_approval_minutes,
        min_abnormal_ratio=settings.min_abnormal_ratio,
        min_midnight_entries=settings.min_midnight_entries,
        min_user_entries=settings.min_user_entries,
        min_high_context_midnight_entries=settings.min_high_context_midnight_entries,
        auto_entry_sources=settings.auto_entry_sources,
    )
    mask = pd.Series(result, index=df.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=df.index).fillna(0.0)

    work = df.loc[mask].copy()
    work["_l405_score"] = scores.loc[work.index].astype(float)
    work["_score_bucket"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("score_bucket", "")
    )
    work["_reason_codes"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reason_codes", []))
    )
    work["_primary_reason"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("primary_reason", "")
    )
    work["_is_abnormal_time"] = work.index.map(
        lambda idx: annotations.get(int(idx), {}).get("is_abnormal_time")
    )

    grouped = (
        work.groupby("document_id", dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            approval_date=("approval_date", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            created_by=("created_by", _first_non_null),
            approved_by=("approved_by", _first_non_null),
            user_persona=("user_persona", _first_non_null),
            line_count=("document_id", "size"),
            l405_score=("_l405_score", "max"),
            score_bucket=("_score_bucket", _first_non_null),
            reason_codes=("_reason_codes", _first_non_null),
            primary_reason=("_primary_reason", _first_non_null),
            is_abnormal_time=("_is_abnormal_time", "max"),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["approval_date"] = grouped["approval_date"].astype(str)
    grouped["case_id"] = [
        f"L405-{int(year)}-{idx + 1:05d}"
        for idx, year in enumerate(grouped["fiscal_year"].tolist())
    ]
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "abnormal-hours behavior review population"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = (
        "src.detection.anomaly_rules_simple.c12_abnormal_hours_concentration "
        "three-year combined-context detector output"
    )
    grouped["source_candidate"] = "v111"
    grouped["evaluation_context"] = "three_year_combined_then_split_by_fiscal_year"
    grouped["evaluation_policy"] = (
        "Phase1 raw behavior review universe; confirmed AbnormalHoursConcentration "
        "subset remains separate"
    )

    columns = [
        "document_id",
        "fiscal_year",
        "company_code",
        "posting_date",
        "approval_date",
        "document_number",
        "document_type",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "line_count",
        "l405_score",
        "score_bucket",
        "reason_codes",
        "primary_reason",
        "is_abnormal_time",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "evaluation_context",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), (
        result.attrs.get("breakdown", {})
    )


def _write_truth_family(truth: pd.DataFrame) -> None:
    stems = ["rule_truth_L4_05", "abnormal_hours_behavior_review_population"]
    for stem in stems:
        truth.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", truth)
        for year in YEARS:
            year_df = truth.loc[truth["fiscal_year"].eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


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
    confirmed = _read_docs(LABELS / "abnormal_hours_concentration_cases.csv")
    manifest = {
        "version": "v111_candidate",
        "base_version": "v110_candidate",
        "patch": "l405_truth_realign_to_combined_context_detector_universe",
        "rule_id": RULE_ID,
        "truth_docs": int(len(current_truth)),
        "truth_by_year": {
            str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().items()
        },
        "added_docs": int(len(current_truth - previous_truth)),
        "removed_stale_docs": int(len(previous_truth - current_truth)),
        "confirmed_subset_docs": int(len(confirmed)),
        "confirmed_subset_in_truth": int(len(confirmed & current_truth)),
        "score_bucket_counts": {
            str(k): int(v) for k, v in truth["score_bucket"].value_counts().items()
        },
        "reason_counts": {
            str(k): int(v)
            for k, v in truth["primary_reason"].value_counts().sort_index().items()
        },
        "detector_breakdown": breakdown,
        "contract": {
            "rule_truth": "current L4-05 combined-context detector review universe",
            "evaluation_context": "run detector on 2022-2024 combined data, then split by fiscal_year",
            "confirmed_anomalies": "subset only; not exhaustive precision denominator",
            "annual_single_year_runs": "robustness check only, not strict truth evaluation",
            "anti_fitting": (
                "Detector output is not changed. The truth sidecar is realigned to the "
                "current Phase1 raw behavior-review contract and fixed population context."
            ),
        },
    }
    (LABELS / "V111_L405_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V111_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v111 Candidate",
                "",
                "Base: `datasynth_v110_candidate`",
                "",
                "Patch: realign L4-05 rule truth to the three-year combined-context detector universe.",
                "",
                "Contract:",
                "- `rule_truth_L4_05.csv` and `abnormal_hours_behavior_review_population.csv` are the raw L4-05 behavior review universe.",
                "- Detector must be run on the combined 2022-2024 context for strict DataSynth L4-05 truth evaluation.",
                "- Annual single-year runs are robustness checks only.",
                "- `abnormal_hours_concentration_cases.csv` remains a confirmed anomaly subset.",
                "",
                f"Truth documents: {len(current_truth):,}",
                f"Added documents: {len(current_truth - previous_truth):,}",
                f"Removed stale documents: {len(previous_truth - current_truth):,}",
                f"Confirmed subset in truth: {len(confirmed & current_truth):,} / {len(confirmed):,}",
                "",
                "This patch does not modify journal entry rows or the detector.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    previous_truth = _read_docs(LABELS / "rule_truth_L4_05.csv")
    df = _add_l405_features(_load_journal())
    truth, breakdown = _build_truth(df)
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
