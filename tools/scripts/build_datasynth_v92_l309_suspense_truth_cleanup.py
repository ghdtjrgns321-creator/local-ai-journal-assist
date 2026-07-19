"""Build v92 candidate by removing stale L3-09 suspense-aging truth.

v91 contains two L3-09 truth documents whose sidecar metadata no longer matches
the current journal rows. This patch keeps the L3-09 contract unchanged and
rebuilds the rule truth/review sidecar from the current journal fields.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.anomaly_rules_simple import c10_suspense_account  # noqa: E402

SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v91_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v92_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-09"
SUSPENSE_PREFIXES = ("1190", "1290", "2190", "2900", "9990")


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_journal() -> pd.DataFrame:
    rows = pd.read_csv(DEST / "journal_entries.csv", low_memory=False)
    gl = rows["gl_account"].astype(str).str.strip().str.replace(".0", "", regex=False)
    rows["is_suspense_account"] = gl.str.startswith(SUSPENSE_PREFIXES).fillna(False)
    for col in ("amount_open", "debit_amount", "credit_amount"):
        if col in rows.columns:
            rows[col] = pd.to_numeric(rows[col], errors="coerce")
    return rows


def _detector_docs(rows: pd.DataFrame) -> set[str]:
    result = c10_suspense_account(rows)
    return set(rows.loc[result, "document_id"].astype(str))


def _filter_sidecar_family(stem: str, keep_docs: set[str]) -> pd.DataFrame:
    path = LABELS / f"{stem}.csv"
    df = pd.read_csv(path, dtype=str, low_memory=False)
    filtered = df.loc[df["document_id"].astype(str).isin(keep_docs)].copy()
    filtered.to_csv(path, index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", filtered)
    for year in YEARS:
        year_df = filtered.loc[filtered["fiscal_year"].astype(str).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)
    return filtered


def _write_rule_truth(review: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
    ]
    truth = review[[col for col in cols if col in review.columns]].copy()
    truth["rule_id"] = RULE_ID
    truth["expected_hit"] = True
    truth["truth_layer"] = "rule_truth"
    truth["truth_basis"] = "suspense or clearing account remains unresolved beyond aging threshold"
    truth["evaluation_unit"] = "document"
    truth["truth_derivation"] = "src.detection.anomaly_rules_simple.c10_suspense_account"
    truth["source_candidate"] = "v92"
    truth = truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    truth.to_csv(LABELS / "rule_truth_L3_09.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth_L3_09.json", truth)
    for year in YEARS:
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_truth.to_csv(LABELS / f"rule_truth_L3_09_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"rule_truth_L3_09_{year}.json", year_truth)
    return truth


def _filter_lifecycle_population(valid_docs: set[str]) -> pd.DataFrame:
    """Drop lifecycle rows that no longer describe the current journal state."""
    path = LABELS / "suspense_lifecycle_population.csv"
    lifecycle = pd.read_csv(path, dtype=str, low_memory=False)
    normal = pd.read_csv(LABELS / "suspense_normal_controls.csv", dtype=str, usecols=["document_id"], low_memory=False)
    confirmed = pd.read_csv(LABELS / "suspense_confirmed_anomalies.csv", dtype=str, usecols=["document_id"], low_memory=False)
    keep_docs = valid_docs | set(normal["document_id"].astype(str)) | set(confirmed["document_id"].astype(str))
    filtered = lifecycle.loc[lifecycle["document_id"].astype(str).isin(keep_docs)].copy()
    filtered.to_csv(path, index=False, encoding="utf-8")
    _write_json_records(LABELS / "suspense_lifecycle_population.json", filtered)
    for year in YEARS:
        year_df = filtered.loc[filtered["fiscal_year"].astype(str).eq(str(year))].copy()
        year_df.to_csv(LABELS / f"suspense_lifecycle_population_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"suspense_lifecycle_population_{year}.json", year_df)
    return filtered


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
    rows = _read_journal()
    detector_docs = _detector_docs(rows)
    old_truth = pd.read_csv(LABELS / "rule_truth_L3_09.csv", dtype=str, low_memory=False)
    old_docs = set(old_truth["document_id"].astype(str))

    review = _filter_sidecar_family("suspense_aging_review_population", detector_docs)
    truth = _write_rule_truth(review)
    lifecycle = _filter_lifecycle_population(detector_docs)
    combined = _rebuild_combined_rule_truth()

    removed_docs = sorted(old_docs - detector_docs)
    summary = {
        "candidate": "v92",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "destination": str(DEST.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "remove stale L3-09 suspense-aging truth not supported by current journal rows",
        "old_l309_truth_docs": len(old_docs),
        "detector_l309_docs": len(detector_docs),
        "new_l309_truth_docs": int(truth["document_id"].nunique()),
        "removed_l309_truth_docs": len(removed_docs),
        "removed_document_ids": removed_docs,
        "suspense_aging_review_population_docs": int(review["document_id"].nunique()),
        "suspense_lifecycle_population_docs": int(lifecycle["document_id"].nunique()),
        "l309_by_year": {str(k): int(v) for k, v in truth["fiscal_year"].value_counts().sort_index().to_dict().items()},
        "combined_rule_truth_counts": {
            str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()
        },
    }
    (DEST / "V92_L309_SUSPENSE_TRUTH_CLEANUP.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V92_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v92 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: remove stale L3-09 suspense-aging truth not supported by current journal rows.",
                "",
                f"- Source: `{summary['source']}`",
                f"- L3-09 truth docs: `{summary['new_l309_truth_docs']}`",
                f"- Removed stale L3-09 truth docs: `{summary['removed_l309_truth_docs']}`",
                f"- Removed document IDs: `{summary['removed_document_ids']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
