"""Build v95 candidate by converting L3-12 truth to user-level truth.

L3-12 is a user work-scope concentration rule. Previous candidates stored a
large document-level truth/projection as official rule truth, which made
document-id precision/recall misleading. This patch keeps document projection
as drill-down evidence and stores official truth at fiscal_year + created_by.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.fraud_rules_access import b14_work_scope_excess_review  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v94_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v95_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-12"
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


def _load_audit_rules() -> dict:
    path = ROOT / "config" / "audit_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _add_period_window_feature(df: pd.DataFrame) -> pd.DataFrame:
    if "is_period_end" in df.columns:
        return df
    parsed = pd.to_datetime(df.get("posting_date"), errors="coerce")
    month_end_start_day = parsed.dt.days_in_month - WINDOW_DAYS + 1
    df = df.copy()
    df["is_period_end"] = parsed.notna() & (
        parsed.dt.day.le(WINDOW_DAYS) | parsed.dt.day.ge(month_end_start_day)
    )
    return df


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _build_year(year: int, audit_rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(DEST / f"journal_entries_{year}.csv", low_memory=False)
    df = _add_period_window_feature(df)
    result = b14_work_scope_excess_review(df, audit_rules=audit_rules)
    scores = result.attrs.get("score_series", pd.Series(0.0, index=df.index))
    annotations = result.attrs.get("row_annotations", {})
    breakdown = result.attrs.get("breakdown", {})
    summaries = breakdown.get("user_summaries", {})

    projection = df.loc[result.fillna(False)].copy()
    if projection.empty:
        projection_docs = pd.DataFrame()
    else:
        projection["l312_score"] = scores.loc[projection.index].astype(float)
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
                l312_score=("l312_score", "max"),
                l312_bucket=("l312_bucket", _first_non_null),
                l312_reasons=("l312_reasons", _first_non_null),
            )
            .reset_index()
        )
        projection_docs["fiscal_year"] = (
            pd.to_numeric(projection_docs["fiscal_year"], errors="coerce").fillna(year).astype(int)
        )
        projection_docs["projection_layer"] = "document_projection"
        projection_docs["projection_basis"] = "L3-12 user-level score projected to current-period activity documents"
        projection_docs["source_candidate"] = "v95"

    summary_rows: list[dict[str, object]] = []
    for user_id, summary in summaries.items():
        user_docs = projection_docs.loc[
            projection_docs["created_by"].astype(str).str.lower().eq(str(user_id).lower())
        ] if not projection_docs.empty else pd.DataFrame()
        summary_rows.append(
            {
                "fiscal_year": year,
                "created_by": user_id,
                "case_id": f"L312-{year}-{user_id}",
                "rule_id": RULE_ID,
                "expected_hit": True,
                "truth_layer": "rule_truth",
                "truth_basis": "user work-scope concentration review population",
                "evaluation_unit": "fiscal_year+created_by",
                "truth_derivation": "src.detection.fraud_rules_access.b14_work_scope_excess_review user_summaries",
                "source_candidate": "v95",
                "user_persona": summary.get("persona"),
                "threshold_profile": summary.get("threshold_profile"),
                "process_count": summary.get("process_count"),
                "company_count": summary.get("company_count"),
                "document_type_count": summary.get("document_type_count"),
                "account_group_count": summary.get("account_group_count"),
                "source_count": summary.get("source_count"),
                "bucket": summary.get("bucket"),
                "score": summary.get("score"),
                "reasons": "|".join(summary.get("reasons", [])),
                "projected_document_count": int(user_docs["document_id"].nunique()) if not user_docs.empty else 0,
                "projected_row_count": int(
                    user_docs["projected_row_count"].sum()
                ) if not user_docs.empty else 0,
            }
        )

    truth = pd.DataFrame(summary_rows)
    return truth, projection_docs


def _replace_combined_rule_truth(l312: pd.DataFrame) -> None:
    combined_path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(combined_path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, l312], ignore_index=True, sort=False)
    rebuilt.to_csv(combined_path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _write_manifest(l312: pd.DataFrame, projection: pd.DataFrame) -> None:
    bucket_counts = l312["bucket"].value_counts().to_dict() if "bucket" in l312 else {}
    manifest = {
        "version": "v95_candidate",
        "base_version": "v94_candidate",
        "patch": "l312_user_level_truth",
        "rule_id": RULE_ID,
        "truth_count_users": int(len(l312)),
        "projection_count_documents": int(projection["document_id"].nunique()) if not projection.empty else 0,
        "projection_count_rows": int(projection["projected_row_count"].sum()) if not projection.empty else 0,
        "truth_by_year": {str(k): int(v) for k, v in l312["fiscal_year"].value_counts().sort_index().items()},
        "bucket_counts": {str(k): int(v) for k, v in bucket_counts.items()},
        "contract": {
            "phase1_rule_truth": "fiscal_year + created_by user work-scope concentration",
            "document_projection": "drill-down evidence only; do not use as strict precision/recall truth",
            "system_only_users": "excluded by detector policy",
        },
    }
    (LABELS / "V95_L312_USER_TRUTH.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V95_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v95 Candidate",
                "",
                "Base: `datasynth_v94_candidate`",
                "",
                "Patch: convert L3-12 official rule truth from document-level rows to user-level work-scope truth.",
                "",
                "Contract:",
                "- L3-12 Phase 1 truth is `fiscal_year + created_by` user work-scope concentration.",
                "- Document rows are projection/drill-down evidence, not strict rule-truth evaluation units.",
                "- System-only and admin-excluded users follow detector policy and are not truth users.",
                "",
                f"Truth users: {len(l312):,}",
                f"Projection documents: {manifest['projection_count_documents']:,}",
                "",
                "Year split:",
                *[
                    f"- {year}: {count:,}"
                    for year, count in l312["fiscal_year"].value_counts().sort_index().items()
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    audit_rules = _load_audit_rules()
    truth_parts = []
    projection_parts = []
    for year in YEARS:
        truth, projection = _build_year(year, audit_rules)
        truth.to_csv(LABELS / f"rule_truth_L3_12_{year}.csv", index=False)
        _write_json_records(LABELS / f"rule_truth_L3_12_{year}.json", truth)
        truth.to_csv(LABELS / f"work_scope_excess_review_population_{year}.csv", index=False)
        _write_json_records(LABELS / f"work_scope_excess_review_population_{year}.json", truth)
        projection.to_csv(LABELS / f"work_scope_excess_document_projection_{year}.csv", index=False)
        truth_parts.append(truth)
        projection_parts.append(projection)

    l312 = pd.concat(truth_parts, ignore_index=True)
    projection = pd.concat(projection_parts, ignore_index=True)
    l312.to_csv(LABELS / "rule_truth_L3_12.csv", index=False)
    _write_json_records(LABELS / "rule_truth_L3_12.json", l312)
    l312.to_csv(LABELS / "work_scope_excess_review_population.csv", index=False)
    _write_json_records(LABELS / "work_scope_excess_review_population.json", l312)
    projection.to_csv(LABELS / "work_scope_excess_document_projection.csv", index=False)

    _replace_combined_rule_truth(l312)
    _write_manifest(l312, projection)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "l312_truth_users": int(len(l312)),
                "truth_by_year": {
                    str(k): int(v) for k, v in l312["fiscal_year"].value_counts().sort_index().items()
                },
                "projection_documents": int(projection["document_id"].nunique()) if not projection.empty else 0,
                "projection_rows": int(projection["projected_row_count"].sum()) if not projection.empty else 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
