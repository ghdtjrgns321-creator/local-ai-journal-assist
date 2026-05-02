"""Build v96 candidate by diversifying L3-12 truth interpretation buckets.

The v95 L3-12 evaluation unit is correct (fiscal_year + created_by), but all
truth rows inherited the same detector bucket/score. This patch keeps detector
evidence for traceability and adds diversified business-context buckets so the
DataSynth truth does not imply every work-scope user is the same risk pattern.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v95_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v96_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L3-12"


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _classify(row: pd.Series) -> tuple[str, float, str]:
    persona = str(row.get("user_persona") or "").strip().lower()
    process_count = int(row.get("process_count") or 0)
    company_count = int(row.get("company_count") or 0)
    document_type_count = int(row.get("document_type_count") or 0)
    projected_docs = int(row.get("projected_document_count") or 0)
    reasons = set(str(row.get("reasons") or "").split("|"))

    if persona in {"automated_system", "batch_user"}:
        return (
            "system_mixed_scope_review",
            0.30,
            "system persona has non-system/manual mixed activity and should be reviewed separately from human users",
        )
    if persona in {"controller", "manager"}:
        return (
            "leadership_broad_scope_review",
            0.35,
            "manager/controller users naturally span broader areas; review as governance concentration, not direct violation",
        )
    if process_count >= 6 and company_count >= 3 and document_type_count >= 6 and projected_docs >= 10000:
        return (
            "enterprise_wide_compound_scope",
            0.65,
            "user spans many processes, companies, document types, and high activity volume",
        )
    if "manual_source" in reasons and "sensitive_account" in reasons:
        return (
            "manual_sensitive_scope_review",
            0.55,
            "manual activity overlaps with sensitive account coverage across broad work scope",
        )
    if process_count >= 5 and company_count >= 3:
        return (
            "broad_process_company_scope",
            0.45,
            "user spans multiple processes and companies, but without the strongest volume/context profile",
        )
    return (
        "work_scope_observation",
        0.25,
        "lower-priority user work-scope observation",
    )


def _diversify(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "detector_bucket" not in out.columns:
        out["detector_bucket"] = out.get("bucket")
    if "detector_score" not in out.columns:
        out["detector_score"] = out.get("score")
    classified = out.apply(_classify, axis=1, result_type="expand")
    out["bucket"] = classified[0]
    out["score"] = classified[1].astype(float)
    out["truth_score_band"] = pd.cut(
        out["score"],
        bins=[-0.01, 0.34, 0.49, 0.59, 1.0],
        labels=["low", "review", "elevated", "compound"],
    ).astype(str)
    out["business_context"] = classified[2]
    out["source_candidate"] = "v96"
    out["truth_derivation"] = (
        "v95 user-level detector truth with v96 business-context bucket diversification"
    )
    return out


def _replace_combined_rule_truth(l312: pd.DataFrame) -> None:
    combined_path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(combined_path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, l312], ignore_index=True, sort=False)
    rebuilt.to_csv(combined_path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _update_projection(l312: pd.DataFrame) -> pd.DataFrame:
    path = LABELS / "work_scope_excess_document_projection.csv"
    projection = pd.read_csv(path, low_memory=False)
    key = l312[
        [
            "fiscal_year",
            "created_by",
            "bucket",
            "score",
            "truth_score_band",
            "business_context",
            "detector_bucket",
            "detector_score",
        ]
    ].copy()
    key = key.rename(
        columns={
            "bucket": "truth_bucket",
            "score": "truth_score",
            "detector_bucket": "l312_detector_bucket",
            "detector_score": "l312_detector_score",
        }
    )
    projection = projection.merge(key, on=["fiscal_year", "created_by"], how="left")
    projection.to_csv(path, index=False)
    for year in YEARS:
        year_df = projection.loc[projection["fiscal_year"].eq(year)].copy()
        year_df.to_csv(LABELS / f"work_scope_excess_document_projection_{year}.csv", index=False)
    return projection


def _write_manifest(l312: pd.DataFrame, projection: pd.DataFrame) -> None:
    manifest = {
        "version": "v96_candidate",
        "base_version": "v95_candidate",
        "patch": "l312_bucket_diversity",
        "rule_id": RULE_ID,
        "truth_count_users": int(len(l312)),
        "projection_count_documents": int(projection["document_id"].nunique()),
        "bucket_counts": {str(k): int(v) for k, v in l312["bucket"].value_counts().items()},
        "score_counts": {str(k): int(v) for k, v in l312["score"].value_counts().sort_index().items()},
        "detector_bucket_counts": {
            str(k): int(v) for k, v in l312["detector_bucket"].value_counts().items()
        },
        "contract": {
            "evaluation_unit": "fiscal_year + created_by",
            "detector_evidence": "detector_bucket/detector_score preserve v95 detector output",
            "truth_bucket": "business-context interpretation for DataSynth realism",
        },
    }
    (LABELS / "V96_L312_BUCKET_DIVERSITY.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V96_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v96 Candidate",
                "",
                "Base: `datasynth_v95_candidate`",
                "",
                "Patch: diversify L3-12 user-level truth buckets while preserving detector evidence.",
                "",
                "Truth users: 64",
                "",
                "Bucket split:",
                *[f"- {k}: {v}" for k, v in l312["bucket"].value_counts().items()],
                "",
                "Production baseline remains unchanged.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    _copy_candidate_safely()
    l312 = pd.read_csv(LABELS / "rule_truth_L3_12.csv", low_memory=False)
    l312 = _diversify(l312)
    l312.to_csv(LABELS / "rule_truth_L3_12.csv", index=False)
    _write_json_records(LABELS / "rule_truth_L3_12.json", l312)
    l312.to_csv(LABELS / "work_scope_excess_review_population.csv", index=False)
    _write_json_records(LABELS / "work_scope_excess_review_population.json", l312)
    for year in YEARS:
        year_df = l312.loc[l312["fiscal_year"].eq(year)].copy()
        year_df.to_csv(LABELS / f"rule_truth_L3_12_{year}.csv", index=False)
        _write_json_records(LABELS / f"rule_truth_L3_12_{year}.json", year_df)
        year_df.to_csv(LABELS / f"work_scope_excess_review_population_{year}.csv", index=False)
        _write_json_records(LABELS / f"work_scope_excess_review_population_{year}.json", year_df)
    _replace_combined_rule_truth(l312)
    projection = _update_projection(l312)
    _write_manifest(l312, projection)
    print(
        json.dumps(
            {
                "dest": str(DEST.relative_to(ROOT)),
                "l312_truth_users": int(len(l312)),
                "bucket_counts": {
                    str(k): int(v) for k, v in l312["bucket"].value_counts().items()
                },
                "score_counts": {
                    str(k): int(v) for k, v in l312["score"].value_counts().sort_index().items()
                },
                "projection_documents": int(projection["document_id"].nunique()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
