"""Build v91 candidate by realigning L3-06 truth to actual after-hours postings.

v90 L3-06 rule truth was built from the old normal-after-hours sidecar plus
AfterHoursPosting labels. That misses naturally occurring after-hours documents
that the detector correctly surfaces from posting_date/is_after_hours features.
This patch keeps anomaly labels unchanged and rebuilds only rule-truth/review
population sidecars from the actual journal timestamp contract.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v90_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v91_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-06"


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_docs() -> pd.DataFrame:
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
        "user_persona",
        "is_anomaly",
        "anomaly_type",
    ]
    rows = pd.read_csv(DEST / "journal_entries.csv", dtype=str, low_memory=False)
    rows = rows[[col for col in columns if col in rows.columns]].copy()
    return rows.drop_duplicates("document_id").reset_index(drop=True)


def _anomaly_map() -> dict[str, str]:
    path = LABELS / "anomaly_labels.csv"
    if not path.exists():
        return {}
    labels = pd.read_csv(path, dtype=str, usecols=["document_id", "anomaly_type"], low_memory=False)
    grouped = labels.groupby("document_id")["anomaly_type"].apply(
        lambda values: "|".join(sorted({str(value) for value in values if pd.notna(value) and str(value)}))
    )
    return grouped.to_dict()


def _after_hours_docs(docs: pd.DataFrame) -> pd.DataFrame:
    posting = pd.to_datetime(docs["posting_date"], errors="coerce")
    hour = posting.dt.hour
    mask = hour.ge(22).fillna(False) | hour.lt(6).fillna(False)
    out = docs.loc[mask].copy()
    out["posting_hour"] = hour.loc[mask].astype("Int64")
    out["time_bucket"] = "late_evening_22_23"
    out.loc[out["posting_hour"].lt(6), "time_bucket"] = "midnight_00_05"

    source = out.get("source", pd.Series("", index=out.index)).fillna("").str.strip().str.lower()
    persona = out.get("user_persona", pd.Series("", index=out.index)).fillna("").str.strip().str.lower()
    actor = out.get("created_by", pd.Series("", index=out.index)).fillna("").str.strip().str.lower()
    system_actor = pd.Series(False, index=out.index)
    for token in ("batch", "system", "auto", "if_", "svc_"):
        system_actor = system_actor | actor.str.contains(token, regex=False)
    system_context = source.isin({"automated", "batch", "interface", "system"}) | persona.eq("automated_system") | system_actor
    out["source_category"] = "human_or_unknown"
    out.loc[system_context, "source_category"] = "system_or_batch"
    out["expected_score"] = 0.45
    out.loc[system_context, "expected_score"] = 0.20
    out["rule_id"] = RULE_ID
    out["expected_hit"] = True
    out["truth_layer"] = "rule_truth"
    out["truth_basis"] = "posting_date hour is within configured after-hours window"
    out["evaluation_unit"] = "document"
    out["truth_derivation"] = "posting_date hour >= 22 or < 6"
    out["source_candidate"] = "v91"
    return out.sort_values(["fiscal_year", "company_code", "posting_date", "document_number", "document_id"])


def _write_l306_truth(truth: pd.DataFrame) -> None:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "posting_hour",
        "time_bucket",
        "business_process",
        "source",
        "created_by",
        "user_persona",
        "source_category",
        "expected_score",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
    ]
    truth = truth[[col for col in cols if col in truth.columns]].copy()
    truth.to_csv(LABELS / "rule_truth_L3_06.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth_L3_06.json", truth)
    truth.to_csv(LABELS / "afterhours_review_population.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "afterhours_review_population.json", truth)

    for year in YEARS:
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_truth.to_csv(LABELS / f"rule_truth_L3_06_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"rule_truth_L3_06_{year}.json", year_truth)
        year_truth.to_csv(LABELS / f"afterhours_review_population_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"afterhours_review_population_{year}.json", year_truth)


def _write_normal_context(truth: pd.DataFrame, anomaly_types: dict[str, str]) -> pd.DataFrame:
    normal = truth.copy()
    normal["anomaly_types"] = normal["document_id"].map(anomaly_types).fillna("")
    normal["has_any_anomaly_label"] = normal["anomaly_types"].astype(str).ne("")
    normal = normal.loc[~normal["has_any_anomaly_label"]].copy()
    normal["normal_after_hours_context"] = True
    normal["background_temporal_pattern"] = True
    normal["time_zone_category"] = "midnight"
    normal["normal_after_hours_reason"] = normal["source_category"].map(
        {
            "system_or_batch": "scheduled_system_or_batch_after_hours",
            "human_or_unknown": "human_after_hours_business_context",
        }
    )

    cols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "posting_hour",
        "time_bucket",
        "document_number",
        "document_type",
        "business_process",
        "created_by",
        "user_persona",
        "source",
        "source_category",
        "time_zone_category",
        "normal_after_hours_context",
        "background_temporal_pattern",
        "normal_after_hours_reason",
        "has_any_anomaly_label",
        "anomaly_types",
    ]
    normal = normal[[col for col in cols if col in normal.columns]].copy()
    normal.to_csv(LABELS / "normal_after_hours_context.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "normal_after_hours_context.json", normal)
    for year in YEARS:
        year_normal = normal.loc[normal["fiscal_year"].astype(str).eq(str(year))].copy()
        year_normal.to_csv(LABELS / f"normal_after_hours_context_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"normal_after_hours_context_{year}.json", year_normal)
    return normal


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    json_path = LABELS / "rule_truth.json"
    if json_path.exists():
        json_path.unlink()
    return combined


def main() -> None:
    _copy_candidate_safely()
    docs = _read_docs()
    anomaly_types = _anomaly_map()
    old_truth = pd.read_csv(LABELS / "rule_truth_L3_06.csv", dtype=str, usecols=["document_id"], low_memory=False)
    old_docs = set(old_truth["document_id"].astype(str))

    truth = _after_hours_docs(docs)
    _write_l306_truth(truth)
    normal = _write_normal_context(truth, anomaly_types)
    combined = _rebuild_combined_rule_truth()

    new_docs = set(truth["document_id"].astype(str))
    summary = {
        "candidate": "v91",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "destination": str(DEST.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "realign L3-06 rule truth to actual after-hours journal postings",
        "old_l306_truth_docs": len(old_docs),
        "new_l306_truth_docs": len(new_docs),
        "added_l306_truth_docs": len(new_docs - old_docs),
        "removed_l306_truth_docs": len(old_docs - new_docs),
        "normal_after_hours_context_docs": int(len(normal)),
        "l306_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "l306_by_source": {str(k): int(v) for k, v in truth["source"].value_counts(dropna=False).sort_index().to_dict().items()},
        "l306_by_source_category": {
            str(k): int(v) for k, v in truth["source_category"].value_counts(dropna=False).sort_index().to_dict().items()
        },
        "l306_score_distribution": {
            str(k): int(v) for k, v in truth["expected_score"].value_counts(dropna=False).sort_index().to_dict().items()
        },
        "combined_rule_truth_counts": {
            str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()
        },
    }
    (DEST / "V91_L306_AFTERHOURS_TRUTH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V91_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v91 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: realign L3-06 rule truth to actual after-hours journal postings.",
                "",
                f"- Source: `{summary['source']}`",
                f"- L3-06 truth docs: `{summary['new_l306_truth_docs']}`",
                f"- Added L3-06 truth docs: `{summary['added_l306_truth_docs']}`",
                f"- Removed L3-06 truth docs: `{summary['removed_l306_truth_docs']}`",
                f"- Normal after-hours context docs: `{summary['normal_after_hours_context_docs']}`",
                f"- Source split: `{summary['l306_by_source']}`",
                f"- Score split: `{summary['l306_score_distribution']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
