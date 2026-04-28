"""Build v80 candidate by splitting direct SoD truth from work-scope review.

v79 still carried role/process breadth review candidates inside L1-06 truth.
v80 keeps L1-06 for direct SoD conflict markers and material IT/admin
postings, then materializes role/work-scope breadth as L3-12 rule truth and
review-population sidecar.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.fraud_rules_access import (  # noqa: E402
    b07_segregation_of_duties,
    b14_work_scope_excess_review,
    build_access_rule_cache,
)
from src.feature.amount_features import add_all_amount_features  # noqa: E402
from src.feature.pattern_features import add_all_pattern_features  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402
from src.ingest.datasynth_labels import SOURCE_PATH_ATTR  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v79_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v80_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")

INPUT_COLUMNS = [
    "document_id",
    "fiscal_year",
    "company_code",
    "document_number",
    "document_type",
    "business_process",
    "source",
    "created_by",
    "approved_by",
    "approval_date",
    "posting_date",
    "document_date",
    "fiscal_period",
    "currency",
    "user_persona",
    "reference",
    "header_text",
    "line_text",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "sod_violation",
    "sod_conflict_type",
    "description_quality",
    "lettrage",
    "lettrage_date",
    "amount_open",
    "is_cleared",
    "settlement_status",
    "settlement_date",
]


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _read_year(year: int) -> pd.DataFrame:
    path = DEST / f"journal_entries_{year}.csv"
    available = pd.read_csv(path, nrows=0).columns.tolist()
    cols = [col for col in INPUT_COLUMNS if col in available]
    frame = pd.read_csv(path, dtype=str, usecols=cols, low_memory=False)
    for col in INPUT_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[INPUT_COLUMNS].copy()
    frame["fiscal_year"] = frame["fiscal_year"].fillna(str(year))
    return frame


def _read_rows() -> pd.DataFrame:
    rows = pd.concat([_read_year(year) for year in YEARS], ignore_index=True)
    for col in ("posting_date", "document_date", "approval_date", "lettrage_date", "settlement_date"):
        rows[col] = pd.to_datetime(rows[col], errors="coerce")
    rows["fiscal_period"] = pd.to_numeric(rows["fiscal_period"], errors="coerce")
    for col in ("debit_amount", "credit_amount", "amount_open"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    rows[["debit_amount", "credit_amount"]] = rows[["debit_amount", "credit_amount"]].fillna(0.0)
    rows.attrs[SOURCE_PATH_ATTR] = str((DEST / "journal_entries_2022.csv").resolve())
    return rows


def _add_features(rows: pd.DataFrame) -> pd.DataFrame:
    settings = get_settings()
    audit_rules = get_audit_rules()
    out = rows.copy()
    out.attrs[SOURCE_PATH_ATTR] = rows.attrs[SOURCE_PATH_ATTR]
    add_all_time_features(out, settings)
    add_all_amount_features(out, settings, audit_rules)
    add_all_pattern_features(out, audit_rules.get("patterns", {}))
    return out


def _doc_context(rows: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "document_id",
        "fiscal_year",
        "company_code",
        "document_number",
        "document_type",
        "posting_date",
        "business_process",
        "source",
        "created_by",
        "approved_by",
        "user_persona",
        "sod_violation",
        "sod_conflict_type",
    ]
    docs = rows[cols].dropna(subset=["document_id"]).drop_duplicates("document_id").copy()
    docs["posting_date"] = docs["posting_date"].astype(str)
    return docs


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _row_annotations_frame(result: pd.Series) -> pd.DataFrame:
    annotations = result.attrs.get("row_annotations", {})
    if not annotations:
        return pd.DataFrame(columns=["row_index"])
    records = [{"row_index": idx, **value} for idx, value in annotations.items()]
    return pd.DataFrame(records)


def _write_rule_truth(
    rule_id: str,
    rows: pd.DataFrame,
    flag: pd.Series,
    basis: str,
    derivation: str,
    result: pd.Series | None = None,
) -> pd.DataFrame:
    flagged = rows.loc[flag.fillna(False).astype(bool)]
    docs = _doc_context(flagged) if not flagged.empty else _doc_context(rows).iloc[0:0].copy()
    if not flagged.empty:
        counts = flagged.groupby("document_id", as_index=False).size().rename(columns={"size": "flagged_row_count"})
        docs = docs.merge(counts, on="document_id", how="left")
    else:
        docs["flagged_row_count"] = pd.Series(dtype="int64")

    if result is not None and not flagged.empty:
        annotations = _row_annotations_frame(result)
        if not annotations.empty:
            if "document_id" not in annotations.columns and "row_index" in annotations.columns:
                row_docs = flagged.reset_index(names="row_index")[["row_index", "document_id"]]
                annotations = annotations.merge(row_docs, on="row_index", how="left")
            annotation_cols = [
                col
                for col in (
                    "document_id",
                    "bucket",
                    "score",
                    "process_count",
                    "company_count",
                    "document_type_count",
                    "account_group_count",
                    "source_count",
                    "reasons",
                )
                if col in annotations.columns
            ]
            if annotation_cols:
                ann = annotations[annotation_cols].drop_duplicates("document_id")
                docs = docs.merge(ann, on="document_id", how="left")

    docs["rule_id"] = rule_id
    docs["expected_hit"] = True
    docs["truth_layer"] = "rule_truth"
    docs["truth_basis"] = basis
    docs["evaluation_unit"] = "document"
    docs["truth_derivation"] = derivation
    docs["source_candidate"] = "v80"

    stem = f"rule_truth_{rule_id.replace('-', '_')}"
    docs.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", docs)
    for year in YEARS:
        subset = docs.loc[docs["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", subset)
    return docs


def _write_l312_sidecar(l312_docs: pd.DataFrame, result: pd.Series) -> dict[str, int]:
    sidecar = l312_docs.copy()
    sidecar["sidecar_type"] = "work_scope_excess_review_population"
    sidecar["sidecar_purpose"] = (
        "DataSynth contract truth for L3-12 review candidates; not an injected fraud label"
    )
    sidecar.to_csv(LABELS / "work_scope_excess_review_population.csv", index=False)
    _write_json_records(LABELS / "work_scope_excess_review_population.json", sidecar)

    for year in YEARS:
        subset = sidecar.loc[sidecar["fiscal_year"].astype(str).eq(str(year))]
        subset.to_csv(LABELS / f"work_scope_excess_review_population_{year}.csv", index=False)
        _write_json_records(LABELS / f"work_scope_excess_review_population_{year}.json", subset)

    breakdown = result.attrs.get("breakdown", {})
    bucket_counts = breakdown.get("bucket_counts", {}) if isinstance(breakdown, dict) else {}
    return {str(key): int(value) for key, value in bucket_counts.items()}


def _rebuild_combined() -> dict[str, int]:
    frames: list[pd.DataFrame] = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem.removeprefix("rule_truth_")
        if YEAR_SUFFIX_RE.search(stem):
            continue
        frames.append(pd.read_csv(path, dtype=str, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    return {
        str(rule): int(count)
        for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()
    }


def main() -> None:
    _copy_candidate_safely()
    rows = _add_features(_read_rows())
    settings = get_settings()
    audit_rules = get_audit_rules()
    cache = build_access_rule_cache(rows)

    l106_result = b07_segregation_of_duties(
        rows,
        sod_threshold=settings.sod_process_threshold,
        audit_rules=audit_rules,
        cache=cache,
    )
    l312_result = b14_work_scope_excess_review(rows, audit_rules=audit_rules)

    l106_docs = _write_rule_truth(
        "L1-06",
        rows,
        l106_result.fillna(False).astype(bool),
        "direct SoD conflict markers or IT/admin direct business posting evidence only",
        "src.detection.fraud_rules_access.b07_segregation_of_duties",
        l106_result,
    )
    l312_docs = _write_rule_truth(
        "L3-12",
        rows,
        l312_result.fillna(False).astype(bool),
        "work-scope/process-breadth review candidate population",
        "src.detection.fraud_rules_access.b14_work_scope_excess_review",
        l312_result,
    )
    l312_bucket_counts = _write_l312_sidecar(l312_docs, l312_result)
    rule_counts = _rebuild_combined()

    summary = {
        "candidate_version": "v80",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "split L1-06 direct SoD truth from L3-12 work-scope review truth",
        "replaced_rule_counts": {
            "L1-06": int(len(l106_docs)),
            "L3-12": int(len(l312_docs)),
        },
        "l312_bucket_counts": l312_bucket_counts,
        "all_rule_counts": rule_counts,
        "anti_fitting_note": (
            "L1-06/L3-12 truth is derived from rule contract populations. Injected fraud/anomaly "
            "labels remain separate and should not be used as exhaustive Phase 1 rule truth."
        ),
    }
    (DEST / "V80_L106_L312_SPLIT_PATCH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V80_CANDIDATE.md").write_text(
        "# DataSynth v80 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: L1-06 direct SoD and L3-12 work-scope review split.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
