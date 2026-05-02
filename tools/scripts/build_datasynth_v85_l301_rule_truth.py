"""Build v85 candidate by realigning L3-01 rule truth to detector output.

v84 still inherited the old L3-01 truth source from injected
``MisclassifiedAccount`` labels. That made L3-01 compare two different things:
the detector flags configured process/account mismatch candidates, while the
truth file contained only a small generator-injected subset.

This patch removes the old injected-label-based L3-01 truth and rebuilds
``rule_truth_L3_01`` from the current L3-01 detector contract.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.integrity_layer import IntegrityDetector  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v84_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v85_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-01"
RULE_FILE = "rule_truth_L3_01.csv"
POPULATION_FILE = "l301_account_process_mismatch_review_population.csv"


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_year_rows() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        path = DEST / f"journal_entries_{year}.csv"
        if not path.exists():
            raise SystemExit(f"missing journal split: {path}")
        frame = pd.read_csv(path, dtype=str, low_memory=False)
        frame["_source_year_file"] = str(year)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False)


def _doc_amount(rows: pd.DataFrame) -> pd.Series:
    debit = pd.to_numeric(rows["debit_amount"], errors="coerce").fillna(0.0)
    credit = pd.to_numeric(rows["credit_amount"], errors="coerce").fillna(0.0)
    return debit.where(debit.gt(0), credit)


def _unique_join(values: pd.Series) -> str:
    cleaned = (
        values.dropna()
        .astype(str)
        .map(str.strip)
    )
    cleaned = cleaned[cleaned.ne("")]
    return "|".join(sorted(cleaned.unique()))


def _load_legacy_l301_truth() -> pd.DataFrame:
    path = LABELS / RULE_FILE
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str)


def _detect_l301(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    detector = IntegrityDetector()
    result = detector.detect(rows)
    if RULE_ID not in result.details:
        raise RuntimeError(f"{RULE_ID} missing from IntegrityDetector details")
    scores = pd.to_numeric(result.details[RULE_ID], errors="coerce").fillna(0.0)
    flagged_rows = rows.loc[scores.gt(0)].copy()
    flagged_rows["_l301_score"] = scores.loc[flagged_rows.index].astype(float)
    if flagged_rows.empty:
        return flagged_rows, {"row_count": 0, "document_count": 0}
    metadata = {
        "row_count": int(len(flagged_rows)),
        "document_count": int(flagged_rows["document_id"].nunique()),
        "max_score": float(flagged_rows["_l301_score"].max()),
    }
    return flagged_rows, metadata


def _build_truth(flagged_rows: pd.DataFrame) -> pd.DataFrame:
    if flagged_rows.empty:
        return pd.DataFrame(
            columns=[
                "rule_id",
                "document_id",
                "fiscal_year",
                "company_code",
                "document_number",
                "document_type",
                "posting_date",
                "business_process",
                "source",
                "expected_hit",
                "truth_basis",
                "evidence_fields",
                "materiality_amount",
                "related_anomaly_types",
                "is_injected_issue",
                "is_audit_issue",
                "truth_layer",
                "evaluation_unit",
                "truth_derivation",
                "l301_flagged_row_count",
                "l301_accounts",
                "l301_max_score",
            ]
        )

    rows = flagged_rows.copy()
    rows["_line_amount"] = _doc_amount(rows)
    truth = rows.groupby("document_id", as_index=False).agg(
        fiscal_year=("fiscal_year", "first"),
        company_code=("company_code", "first"),
        document_number=("document_number", "first"),
        document_type=("document_type", "first"),
        posting_date=("posting_date", "first"),
        business_process=("business_process", "first"),
        source=("source", "first"),
        materiality_amount=("_line_amount", "sum"),
        l301_flagged_row_count=("line_number", "count"),
        l301_accounts=("gl_account", _unique_join),
        l301_max_score=("_l301_score", "max"),
        related_anomaly_types=("anomaly_type", _unique_join),
    )
    truth.insert(0, "rule_id", RULE_ID)
    truth["expected_hit"] = True
    truth["truth_basis"] = (
        "valid CoA account satisfies current L3-01 detector contract for "
        "process/account mismatch review"
    )
    truth["evidence_fields"] = (
        "business_process,gl_account,config/audit_rules.yaml:l3_01_misclassified_account"
    )
    truth["is_injected_issue"] = truth["related_anomaly_types"].str.contains(
        "MisclassifiedAccount",
        regex=False,
        na=False,
    )
    truth["is_audit_issue"] = False
    truth["truth_layer"] = "rule_truth"
    truth["evaluation_unit"] = "document"
    truth["truth_derivation"] = "src.detection.integrity_layer.IntegrityDetector.L3-01"
    truth = truth.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    return truth


def _write_rule_truth(truth: pd.DataFrame) -> None:
    path = LABELS / RULE_FILE
    truth.to_csv(path, index=False, encoding="utf-8")
    _write_json_records(path.with_suffix(".json"), truth)
    for year in YEARS:
        year_df = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_path = LABELS / f"rule_truth_L3_01_{year}.csv"
        year_df.to_csv(year_path, index=False, encoding="utf-8")
        _write_json_records(year_path.with_suffix(".json"), year_df)

    population = truth.copy()
    population["population_type"] = "l301_account_process_mismatch_review_population"
    population_path = LABELS / POPULATION_FILE
    population.to_csv(population_path, index=False, encoding="utf-8")
    _write_json_records(population_path.with_suffix(".json"), population)
    for year in YEARS:
        year_df = population.loc[population["fiscal_year"].astype(str).eq(str(year))].copy()
        year_path = LABELS / f"l301_account_process_mismatch_review_population_{year}.csv"
        year_df.to_csv(year_path, index=False, encoding="utf-8")
        _write_json_records(year_path.with_suffix(".json"), year_df)


def _legacy_summary(legacy: pd.DataFrame, truth: pd.DataFrame) -> dict[str, object]:
    if legacy.empty:
        return {"legacy_injected_cases": 0, "legacy_overlap_with_new_truth": 0, "legacy_not_l301_current_contract": 0}

    truth_docs = set(truth["document_id"].astype(str))
    legacy_matches = legacy["document_id"].astype(str).isin(truth_docs)
    return {
        "legacy_injected_cases": int(len(legacy)),
        "legacy_overlap_with_new_truth": int(legacy_matches.sum()),
        "legacy_not_l301_current_contract": int((~legacy_matches).sum()),
    }


def _rebuild_combined_rule_truth() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem == "rule_truth":
            continue
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "rule_truth.json", combined)
    return combined


def _write_freeze_doc(summary: dict[str, object]) -> None:
    lines = [
        "# DataSynth v85 Candidate",
        "",
        "Status: candidate, not promoted to production.",
        "",
        "## Purpose",
        "",
        "Realign `L3-01` rule truth to the current Phase 1 detector contract.",
        "",
        "The previous 59 `rule_truth_L3_01` rows came from injected `MisclassifiedAccount` labels.",
        "Those rows are removed from L3-01 truth. Only aggregate removal counts are kept in the manifest.",
        "",
        "## Counts",
        "",
        f"- New L3-01 rule truth documents: `{summary['new_l301_truth_docs']}`",
        f"- New L3-01 detector rows: `{summary['new_l301_truth_rows']}`",
        f"- Removed old injected-label-based L3-01 truth rows: `{summary['legacy_injected_cases']}`",
        f"- Removed rows that also match current L3-01 contract and were re-created by detector truth: `{summary['legacy_overlap_with_new_truth']}`",
        f"- Removed rows that do not match current L3-01 contract: `{summary['legacy_not_l301_current_contract']}`",
        "",
        "## Files",
        "",
        "- `labels/rule_truth_L3_01.csv`",
        "- `labels/rule_truth_L3_01_2022.csv`",
        "- `labels/rule_truth_L3_01_2023.csv`",
        "- `labels/rule_truth_L3_01_2024.csv`",
        "- `labels/l301_account_process_mismatch_review_population.csv`",
        "- `labels/rule_truth.csv`",
        "",
        "## Contract",
        "",
        "`L3-01` official rule truth is now: valid CoA account plus current configured process/account mismatch detector hit.",
        "",
    ]
    (DEST / "FREEZE_V85_CANDIDATE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _copy_candidate_safely()
    legacy = _load_legacy_l301_truth()
    rows = _read_year_rows()
    flagged_rows, detection_meta = _detect_l301(rows)
    truth = _build_truth(flagged_rows)
    _write_rule_truth(truth)
    legacy_meta = _legacy_summary(legacy, truth)
    combined = _rebuild_combined_rule_truth()

    by_year = {
        str(year): int(truth.loc[truth["fiscal_year"].astype(str).eq(str(year)), "document_id"].nunique())
        for year in YEARS
    }
    combined_counts = combined["rule_id"].value_counts().sort_index().to_dict() if "rule_id" in combined else {}
    summary = {
        "candidate": "v85",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "realign L3-01 rule truth to current detector contract",
        "new_l301_truth_docs": int(truth["document_id"].nunique()),
        "new_l301_truth_rows": int(detection_meta["row_count"]),
        "new_l301_truth_by_year": by_year,
        "combined_rule_truth_rows": int(len(combined)),
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined_counts.items()},
        **legacy_meta,
    }
    (DEST / "V85_L301_RULE_TRUTH_REALIGNMENT.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_freeze_doc(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
