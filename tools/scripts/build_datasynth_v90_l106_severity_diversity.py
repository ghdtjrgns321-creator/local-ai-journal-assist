"""Build v90 candidate by diversifying L1-06 SoD severity evidence.

v89 L1-06 direct SoD truth is field-correct but all rows score direct_medium
because every truth row uses ``preparer_approver`` and no threshold/IT-admin
evidence exists. This patch keeps the L1-06 truth population size stable while
changing evidence fields so score buckets cover medium/high/critical.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_audit_rules, get_settings  # noqa: E402
from src.detection.fraud_rules_access import b07_segregation_of_duties, build_access_rule_cache  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v89_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v90_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L1-06"

HIGH_CONFLICT_BY_PROCESS = {
    "P2P": "purchase_payment",
    "TRE": "treasury_payment",
    "O2C": "revenue_collection",
    "H2R": "payroll_payment",
    "R2R": "cash_disbursement",
    "A2R": "purchase_payment",
}

TARGET_BUCKETS = {
    "direct_medium": 7,
    "direct_high_conflict": 5,
    "direct_high_threshold": 4,
    "direct_critical": 3,
}


def _copy_candidate_safely() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(SOURCE, DEST, copy_function=shutil.copy2)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_rows() -> pd.DataFrame:
    frames = []
    for year in YEARS:
        frame = pd.read_csv(DEST / f"journal_entries_{year}.csv", dtype=str, low_memory=False)
        frame["_year_file"] = str(year)
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True, sort=False)
    if "exceeds_threshold" not in rows.columns:
        rows["exceeds_threshold"] = "False"
    rows["exceeds_threshold"] = rows["exceeds_threshold"].fillna("False").astype(str)
    return rows


def _write_rows(rows: pd.DataFrame) -> None:
    write_cols = [col for col in rows.columns if col != "_year_file"]
    for year in YEARS:
        rows.loc[rows["_year_file"].astype(str).eq(str(year)), write_cols].to_csv(
            DEST / f"journal_entries_{year}.csv",
            index=False,
            encoding="utf-8",
        )
    rows[write_cols].to_csv(DEST / "journal_entries.csv", index=False, encoding="utf-8")


def _truth_docs() -> pd.DataFrame:
    truth = pd.read_csv(LABELS / "rule_truth_L1_06.csv", dtype=str)
    return truth.sort_values(["fiscal_year", "business_process", "document_number", "document_id"]).reset_index(drop=True)


def _assign_buckets(truth: pd.DataFrame) -> pd.DataFrame:
    assigned = truth.copy()
    assigned["target_bucket"] = "direct_medium"
    assigned["target_conflict_type"] = "preparer_approver"
    assigned["target_exceeds_threshold"] = "False"
    assigned["target_user_persona"] = assigned["user_persona"]

    # Choose critical candidates from protected IT-admin processes only.
    protected = assigned["business_process"].isin(["TRE", "P2P", "O2C", "H2R"])
    critical_idx = assigned.loc[protected].tail(TARGET_BUCKETS["direct_critical"]).index
    assigned.loc[critical_idx, "target_bucket"] = "direct_critical"
    assigned.loc[critical_idx, "target_conflict_type"] = assigned.loc[critical_idx, "business_process"].map(
        HIGH_CONFLICT_BY_PROCESS
    ).fillna("treasury_payment")
    assigned.loc[critical_idx, "target_user_persona"] = "it_admin"

    remaining = assigned.index.difference(critical_idx)
    high_conflict_idx = assigned.loc[remaining].tail(TARGET_BUCKETS["direct_high_conflict"]).index
    assigned.loc[high_conflict_idx, "target_bucket"] = "direct_high_conflict"
    assigned.loc[high_conflict_idx, "target_conflict_type"] = assigned.loc[high_conflict_idx, "business_process"].map(
        HIGH_CONFLICT_BY_PROCESS
    ).fillna("cash_disbursement")

    remaining = remaining.difference(high_conflict_idx)
    high_threshold_idx = assigned.loc[remaining].tail(TARGET_BUCKETS["direct_high_threshold"]).index
    assigned.loc[high_threshold_idx, "target_bucket"] = "direct_high_threshold"
    assigned.loc[high_threshold_idx, "target_exceeds_threshold"] = "True"

    return assigned


def _patch_journal(rows: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    patch_log = assignments[
        [
            "document_id",
            "fiscal_year",
            "company_code",
            "document_number",
            "business_process",
            "source",
            "user_persona",
            "sod_conflict_type",
            "target_bucket",
            "target_conflict_type",
            "target_exceeds_threshold",
            "target_user_persona",
        ]
    ].copy()
    patch_log = patch_log.rename(
        columns={
            "user_persona": "user_persona_before",
            "sod_conflict_type": "sod_conflict_type_before",
        }
    )

    conflict_map = assignments.set_index("document_id")["target_conflict_type"]
    threshold_map = assignments.set_index("document_id")["target_exceeds_threshold"]
    persona_map = assignments.set_index("document_id")["target_user_persona"]
    doc = rows["document_id"].astype(str)
    mask = doc.isin(set(assignments["document_id"].astype(str)))
    rows.loc[mask, "sod_violation"] = "True"
    rows.loc[mask, "sod_conflict_type"] = doc.loc[mask].map(conflict_map).to_numpy()
    rows.loc[mask, "exceeds_threshold"] = doc.loc[mask].map(threshold_map).to_numpy()
    mapped_persona = doc.loc[mask].map(persona_map)
    rows.loc[mask & mapped_persona.notna(), "user_persona"] = mapped_persona.dropna().reindex(doc.loc[mask].index).to_numpy()

    patch_log["patch_reason"] = "diversify L1-06 direct SoD severity evidence"
    patch_log.to_csv(LABELS / "l106_severity_diversity_patch_log.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "l106_severity_diversity_patch_log.json", patch_log)
    return patch_log


def _prepare_detection_frame(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.copy()
    for col in ("debit_amount", "credit_amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    out["sod_violation"] = out["sod_violation"].fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"})
    out["exceeds_threshold"] = out["exceeds_threshold"].fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"})
    return out


def _row_annotations(result: pd.Series) -> pd.DataFrame:
    annotations = result.attrs.get("row_annotations", {})
    if not annotations:
        return pd.DataFrame(columns=["row_index"])
    return pd.DataFrame([{"row_index": idx, **value} for idx, value in annotations.items()])


def _build_l106_truth(rows: pd.DataFrame, result: pd.Series) -> pd.DataFrame:
    flagged = rows.loc[result.fillna(False).astype(bool)].copy()
    docs = flagged.drop_duplicates("document_id")[
        [
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
    ].copy()
    counts = flagged.groupby("document_id", as_index=False).size().rename(columns={"size": "flagged_row_count"})
    docs = docs.merge(counts, on="document_id", how="left")

    ann = _row_annotations(result)
    if not ann.empty:
        if "document_id" not in ann.columns:
            row_docs = flagged.reset_index(names="row_index")[["row_index", "document_id"]]
            ann = ann.merge(row_docs, on="row_index", how="left")
        ann_cols = [
            "document_id",
            "bucket",
            "score",
            "score_reason",
            "high_risk_conflict",
            "threshold_excess",
            "it_admin_high_risk",
        ]
        ann = ann[[col for col in ann_cols if col in ann.columns]].drop_duplicates("document_id")
        docs = docs.merge(ann, on="document_id", how="left")

    docs["rule_id"] = RULE_ID
    docs["expected_hit"] = True
    docs["truth_layer"] = "rule_truth"
    docs["truth_basis"] = "direct SoD conflict marker with diversified severity evidence"
    docs["evaluation_unit"] = "document"
    docs["truth_derivation"] = "src.detection.fraud_rules_access.b07_segregation_of_duties"
    docs["source_candidate"] = "v90"
    docs = docs.sort_values(["fiscal_year", "company_code", "document_number", "document_id"]).reset_index(drop=True)
    return docs


def _write_l106_outputs(truth: pd.DataFrame) -> None:
    stem = "rule_truth_L1_06"
    truth.to_csv(LABELS / f"{stem}.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / f"{stem}.json", truth)
    sidecar = truth.copy()
    sidecar["was_sod_violation"] = sidecar["sod_violation"]
    sidecar["expected_l106_flag"] = True
    sidecar["truth_layer"] = "confirmed_anomaly"
    sidecar.to_csv(LABELS / "sod_confirmed_anomalies.csv", index=False, encoding="utf-8")
    _write_json_records(LABELS / "sod_confirmed_anomalies.json", sidecar)
    for year in YEARS:
        year_truth = truth.loc[truth["fiscal_year"].astype(str).eq(str(year))].copy()
        year_truth.to_csv(LABELS / f"{stem}_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"{stem}_{year}.json", year_truth)
        year_sidecar = sidecar.loc[sidecar["fiscal_year"].astype(str).eq(str(year))].copy()
        year_sidecar.to_csv(LABELS / f"sod_confirmed_anomalies_{year}.csv", index=False, encoding="utf-8")
        _write_json_records(LABELS / f"sod_confirmed_anomalies_{year}.json", year_sidecar)


def _rebuild_combined() -> pd.DataFrame:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        stem = path.stem
        if stem.rsplit("_", 1)[-1] in {"2022", "2023", "2024"}:
            continue
        frames.append(pd.read_csv(path, dtype=str))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False, encoding="utf-8")
    combined_json = LABELS / "rule_truth.json"
    if combined_json.exists():
        combined_json.unlink()
    return combined


def main() -> None:
    _copy_candidate_safely()
    rows = _read_rows()
    truth_before = _truth_docs()
    assignments = _assign_buckets(truth_before)
    patch_log = _patch_journal(rows, assignments)
    _write_rows(rows)

    detect_rows = _prepare_detection_frame(rows.drop(columns=["_year_file"]))
    settings = get_settings()
    audit_rules = get_audit_rules()
    result = b07_segregation_of_duties(
        detect_rows,
        sod_threshold=settings.sod_process_threshold,
        audit_rules=audit_rules,
        cache=build_access_rule_cache(detect_rows),
    )
    truth = _build_l106_truth(detect_rows, result)
    _write_l106_outputs(truth)
    combined = _rebuild_combined()

    score_series = result.attrs.get("score_series")
    score_counts = {}
    if score_series is not None:
        score_counts = {
            str(k): int(v)
            for k, v in score_series.loc[result].value_counts().sort_index().to_dict().items()
        }
    bucket_counts = truth["bucket"].value_counts().sort_index().to_dict() if "bucket" in truth else {}
    summary = {
        "candidate": "v90",
        "source": str(SOURCE.relative_to(ROOT)),
        "destination": str(DEST.relative_to(ROOT)),
        "purpose": "diversify L1-06 direct SoD severity evidence without changing truth population size materially",
        "patched_documents": int(patch_log["document_id"].nunique()),
        "l106_truth_docs": int(truth["document_id"].nunique()),
        "l106_flagged_rows": int(result.sum()),
        "score_counts": score_counts,
        "bucket_counts": {str(k): int(v) for k, v in bucket_counts.items()},
        "conflict_type_counts": {str(k): int(v) for k, v in truth["sod_conflict_type"].value_counts().sort_index().to_dict().items()},
        "combined_rule_truth_counts": {str(k): int(v) for k, v in combined["rule_id"].value_counts().sort_index().to_dict().items()},
    }
    (DEST / "V90_L106_SEVERITY_DIVERSITY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (DEST / "FREEZE_V90_CANDIDATE.md").write_text(
        "\n".join(
            [
                "# DataSynth v90 Candidate",
                "",
                "Status: candidate, not promoted to production.",
                "",
                "Purpose: diversify L1-06 direct SoD severity evidence.",
                "",
                f"- L1-06 truth docs: `{summary['l106_truth_docs']}`",
                f"- L1-06 flagged rows: `{summary['l106_flagged_rows']}`",
                f"- Score counts: `{summary['score_counts']}`",
                f"- Bucket counts: `{summary['bucket_counts']}`",
                f"- Conflict type counts: `{summary['conflict_type_counts']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
