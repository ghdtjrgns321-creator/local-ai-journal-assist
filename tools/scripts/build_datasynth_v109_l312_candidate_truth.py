"""Build v109 candidate with separate L3-12 candidate and scored truth.

L3-12 emits two different signals:

* raw candidate: user-year work-scope breadth that should be surfaced
* scored truth: user-year work-scope candidates that deserve a review score

Older L3 evaluation compared raw candidates against scored truth, so zero-score
system/admin observations looked like false positives. This patch keeps the
existing scored truth and materializes raw candidate truth separately.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.fraud_rules_access import b14_work_scope_excess_review  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v108_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v109_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-12"
WINDOW_DAYS = 5


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(LABELS / "rule_truth_L3_12.csv")
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


def _load_audit_rules() -> dict:
    path = ROOT / "config" / "audit_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _add_period_window_feature(df: pd.DataFrame) -> pd.DataFrame:
    if "is_period_end" in df.columns:
        return df
    parsed = pd.to_datetime(df.get("posting_date"), errors="coerce")
    month_end_start_day = parsed.dt.days_in_month - WINDOW_DAYS + 1
    out = df.copy()
    out["is_period_end"] = parsed.notna() & (
        parsed.dt.day.le(WINDOW_DAYS) | parsed.dt.day.ge(month_end_start_day)
    )
    return out


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _build_projection(df: pd.DataFrame, result: pd.Series, year: int) -> pd.DataFrame:
    annotations = result.attrs.get("row_annotations", {})
    review_scores = pd.Series(
        result.attrs.get("review_score_series", pd.Series(0.0, index=df.index)),
        index=df.index,
    ).fillna(0.0)
    projection = df.loc[result.fillna(False)].copy()
    if projection.empty:
        return pd.DataFrame()

    projection["l312_review_score"] = review_scores.loc[projection.index].astype(float)
    projection["l312_bucket"] = projection.index.map(
        lambda idx: annotations.get(int(idx), {}).get("bucket")
    )
    projection["l312_reasons"] = projection.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reasons", []))
    )
    projection_docs = (
        projection.groupby(["created_by", "document_id"], dropna=False)
        .agg(
            fiscal_year=("fiscal_year", _first_non_null),
            company_code=("company_code", _first_non_null),
            document_number=("document_number", _first_non_null),
            document_type=("document_type", _first_non_null),
            posting_date=("posting_date", _first_non_null),
            business_process=("business_process", _first_non_null),
            source=("source", _first_non_null),
            user_persona=("user_persona", _first_non_null),
            projected_row_count=("document_id", "size"),
            l312_review_score=("l312_review_score", "max"),
            l312_bucket=("l312_bucket", _first_non_null),
            l312_reasons=("l312_reasons", _first_non_null),
        )
        .reset_index()
    )
    projection_docs["fiscal_year"] = (
        pd.to_numeric(projection_docs["fiscal_year"], errors="coerce")
        .fillna(year)
        .astype(int)
    )
    projection_docs["projection_layer"] = "candidate_document_projection"
    projection_docs["projection_basis"] = (
        "L3-12 raw candidate user-year projected to current-period activity documents"
    )
    projection_docs["source_candidate"] = "v109"
    return projection_docs


def _build_year(year: int, audit_rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False)
    df = _add_period_window_feature(df)
    result = b14_work_scope_excess_review(df, audit_rules=audit_rules)
    projection_docs = _build_projection(df, result, year)

    summaries = result.attrs.get("breakdown", {}).get("user_summaries", {})
    rows: list[dict[str, object]] = []
    for summary_key, summary in summaries.items():
        if ":" in str(summary_key):
            _, created_by = str(summary_key).split(":", 1)
        else:
            created_by = str(summary_key)
        user_docs = (
            projection_docs.loc[
                projection_docs["created_by"].astype(str).str.lower().eq(created_by.lower())
            ]
            if not projection_docs.empty
            else pd.DataFrame()
        )
        review_score = float(summary.get("score") or 0.0)
        rows.append(
            {
                "fiscal_year": year,
                "created_by": created_by,
                "case_id": f"L312-CAND-{year}-{created_by}",
                "rule_id": RULE_ID,
                "expected_hit": True,
                "truth_layer": "candidate_truth",
                "truth_basis": "raw L3-12 work-scope candidate population",
                "evaluation_unit": "fiscal_year+created_by",
                "truth_derivation": (
                    "src.detection.fraud_rules_access.b14_work_scope_excess_review raw_candidate"
                ),
                "source_candidate": "v109",
                "user_persona": summary.get("persona"),
                "threshold_profile": summary.get("threshold_profile"),
                "process_count": summary.get("process_count"),
                "company_count": summary.get("company_count"),
                "document_type_count": summary.get("document_type_count"),
                "account_group_count": summary.get("account_group_count"),
                "source_count": summary.get("source_count"),
                "bucket": summary.get("bucket"),
                "review_score": review_score,
                "candidate_score_band": "scored" if review_score > 0 else "zero_score_observation",
                "is_scored_truth": review_score > 0,
                "reasons": "|".join(summary.get("reasons", [])),
                "projected_document_count": (
                    int(user_docs["document_id"].nunique()) if not user_docs.empty else 0
                ),
                "projected_row_count": (
                    int(user_docs["projected_row_count"].sum()) if not user_docs.empty else 0
                ),
            }
        )

    return pd.DataFrame(rows), projection_docs


def _write_candidate_population(candidate: pd.DataFrame, projection: pd.DataFrame) -> None:
    candidate.to_csv(LABELS / "work_scope_raw_candidate_population.csv", index=False)
    _write_json_records(LABELS / "work_scope_raw_candidate_population.json", candidate)
    projection.to_csv(LABELS / "work_scope_raw_candidate_document_projection.csv", index=False)
    for year in YEARS:
        year_candidates = candidate.loc[candidate["fiscal_year"].eq(year)].copy()
        year_candidates.to_csv(
            LABELS / f"work_scope_raw_candidate_population_{year}.csv",
            index=False,
        )
        _write_json_records(
            LABELS / f"work_scope_raw_candidate_population_{year}.json",
            year_candidates,
        )
        year_projection = projection.loc[projection["fiscal_year"].eq(year)].copy()
        year_projection.to_csv(
            LABELS / f"work_scope_raw_candidate_document_projection_{year}.csv",
            index=False,
        )


def _write_manifest(candidate: pd.DataFrame, projection: pd.DataFrame) -> None:
    scored = candidate.loc[candidate["is_scored_truth"].astype(bool)]
    manifest = {
        "version": "v109_candidate",
        "base_version": "v108_candidate",
        "patch": "l312_candidate_scored_truth_split",
        "rule_id": RULE_ID,
        "candidate_truth_user_years": int(len(candidate)),
        "scored_truth_user_years": int(len(scored)),
        "candidate_projection_documents": (
            int(projection["document_id"].nunique()) if not projection.empty else 0
        ),
        "candidate_by_year": {
            str(k): int(v) for k, v in candidate["fiscal_year"].value_counts().sort_index().items()
        },
        "scored_by_year": {
            str(k): int(v) for k, v in scored["fiscal_year"].value_counts().sort_index().items()
        },
        "bucket_counts": {str(k): int(v) for k, v in candidate["bucket"].value_counts().items()},
        "contract": {
            "candidate_truth": "labels/work_scope_raw_candidate_population.csv",
            "scored_truth": "labels/rule_truth_L3_12.csv",
            "document_projection": "drill-down only; do not use for strict precision/recall",
            "anti_fitting": (
                "Detector output is not changed. Truth layers are separated to match the existing "
                "raw-candidate vs review-score contract."
            ),
        },
    }
    (LABELS / "V109_L312_CANDIDATE_TRUTH_SPLIT.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V109_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v109 Candidate",
                "",
                "Base: `datasynth_v108_candidate`",
                "",
                "Patch: split L3-12 raw candidate truth from scored review truth.",
                "",
                "Contract:",
                "- `work_scope_raw_candidate_population.csv`: all L3-12 raw candidate user-years.",
                "- `rule_truth_L3_12.csv`: scored L3-12 review user-years.",
                "- Document projections are drill-down evidence only.",
                "",
                f"Candidate user-years: {len(candidate):,}",
                f"Scored user-years: {len(scored):,}",
                f"Candidate projection documents: {manifest['candidate_projection_documents']:,}",
                "",
                "Candidate year split:",
                *[
                    f"- {year}: {count:,}"
                    for year, count in candidate["fiscal_year"].value_counts().sort_index().items()
                ],
                "",
                "This patch does not modify journal entry rows or the detector.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    _copy_candidate_fast()
    audit_rules = _load_audit_rules()
    candidate_parts: list[pd.DataFrame] = []
    projection_parts: list[pd.DataFrame] = []
    for year in YEARS:
        candidate, projection = _build_year(year, audit_rules)
        candidate_parts.append(candidate)
        projection_parts.append(projection)

    candidate_all = pd.concat(candidate_parts, ignore_index=True)
    projection_all = pd.concat(projection_parts, ignore_index=True)
    _write_candidate_population(candidate_all, projection_all)
    _write_manifest(candidate_all, projection_all)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "candidate_user_years": int(len(candidate_all)),
                "scored_user_years_in_candidate": int(candidate_all["is_scored_truth"].sum()),
                "candidate_by_year": {
                    str(k): int(v)
                    for k, v in candidate_all["fiscal_year"].value_counts().sort_index().items()
                },
                "bucket_counts": {
                    str(k): int(v) for k, v in candidate_all["bucket"].value_counts().items()
                },
                "projection_documents": int(projection_all["document_id"].nunique()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
