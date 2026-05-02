"""Build v123 candidate by refreshing L4-06 truth after year-file sync.

v122 regenerated year journal files from the combined journal. That made the
year-file-based L4-06 detector universe slightly wider than the stale L4-06
truth sidecars. This patch rebuilds only the L4-06 raw detector-contract
universe from the current year files.

Confirmed BatchAnomaly labels and normal/boundary controls are not changed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import get_settings  # noqa: E402
from src.detection.anomaly_rules_batch import c13_batch_anomaly  # noqa: E402
from src.feature.time_features import add_all_time_features  # noqa: E402


SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v122_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v123_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
RULE_ID = "L4-06"
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V123_CANDIDATE.md", "V123_L406_TRUTH_REFRESH.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V123_L406_TRUTH_REFRESH.json")
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


def _cleanup_version_files() -> dict[str, list[str]]:
    removed_root: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed_root.append(path.name)
            path.unlink()
    removed_labels: list[str] = []
    for path in LABELS.glob("V*.json"):
        if re.match(r"^V\d+_.+\.json$", path.name):
            removed_labels.append(path.name)
            path.unlink()
    return {"root": sorted(removed_root), "labels": sorted(removed_labels)}


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _first_non_null(values: pd.Series) -> object:
    clean = values.dropna()
    return None if clean.empty else clean.iloc[0]


def _load_year_journal() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year in YEARS:
        header = pd.read_csv(DEST / f"journal_entries_{year}.csv", nrows=0).columns
        parse_dates = [col for col in ["posting_date", "document_date"] if col in header]
        frames.append(pd.read_csv(DEST / f"journal_entries_{year}.csv", parse_dates=parse_dates, low_memory=False))
    df = pd.concat(frames, ignore_index=True)
    for col in ("debit_amount", "credit_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    add_all_time_features(df, get_settings())
    return df


def _build_l406_truth(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    settings = get_settings()
    result = c13_batch_anomaly(
        rows,
        batch_sources=settings.batch_source_values,
        period_end_ratio=settings.batch_period_end_ratio,
        simultaneous_threshold=settings.batch_simultaneous_threshold,
        amount_zscore=settings.batch_amount_zscore,
    )
    mask = pd.Series(result, index=rows.index).fillna(False).astype(bool)
    annotations = result.attrs.get("row_annotations", {})
    scores = pd.Series(result.attrs.get("score_series", 0.0), index=rows.index).fillna(0.0)

    work = rows.loc[mask].copy()
    work["_l406_score"] = scores.loc[work.index].astype(float)
    work["_score_bucket"] = work.index.map(lambda idx: annotations.get(int(idx), {}).get("score_bucket", ""))
    work["_reason_codes"] = work.index.map(
        lambda idx: "|".join(annotations.get(int(idx), {}).get("reason_codes", []))
    )
    work["_primary_reason"] = work.index.map(lambda idx: annotations.get(int(idx), {}).get("primary_reason", ""))

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
            l406_score=("_l406_score", "max"),
            score_bucket=("_score_bucket", _first_non_null),
            reason_codes=("_reason_codes", _first_non_null),
            primary_reason=("_primary_reason", _first_non_null),
        )
        .reset_index()
    )
    grouped["fiscal_year"] = pd.to_numeric(grouped["fiscal_year"], errors="coerce").astype(int)
    grouped["posting_date"] = grouped["posting_date"].astype(str)
    grouped["case_id"] = [f"L406-{int(year)}-{idx + 1:05d}" for idx, year in enumerate(grouped["fiscal_year"].tolist())]
    grouped["rule_id"] = RULE_ID
    grouped["expected_hit"] = True
    grouped["truth_layer"] = "rule_truth"
    grouped["truth_basis"] = "batch-source review universe"
    grouped["evaluation_unit"] = "document_id"
    grouped["truth_derivation"] = "src.detection.anomaly_rules_batch.c13_batch_anomaly current detector output"
    grouped["source_candidate"] = "v123"
    grouped["truth_contract_version"] = "v123_active_candidate_contract"
    grouped["sidecar_role"] = "strict_truth_alias"
    grouped["sidecar_purpose"] = "detector_contract_universe"
    grouped["expected_detector_positive"] = "true"
    grouped["allowed_for_independent_sidecar_eval"] = False
    grouped["can_overlap_detector_universe"] = True
    grouped["evaluation_policy"] = (
        "Phase1 raw batch review universe; confirmed BatchAnomaly subset and "
        "normal/boundary controls are separate"
    )
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
        "l406_score",
        "score_bucket",
        "reason_codes",
        "primary_reason",
        "case_id",
        "rule_id",
        "expected_hit",
        "truth_layer",
        "truth_basis",
        "evaluation_unit",
        "truth_derivation",
        "source_candidate",
        "truth_contract_version",
        "sidecar_role",
        "sidecar_purpose",
        "expected_detector_positive",
        "allowed_for_independent_sidecar_eval",
        "can_overlap_detector_universe",
        "evaluation_policy",
    ]
    return grouped[columns].sort_values(["fiscal_year", "document_id"]).reset_index(drop=True), result.attrs.get("breakdown", {})


def _write_truth_family(truth: pd.DataFrame) -> None:
    for stem in ["rule_truth_L4_06", "batch_review_population", "batch_detector_universe"]:
        df = truth.copy()
        if stem == "batch_detector_universe":
            df["sidecar_name"] = stem
            df["alias_of_sidecar"] = "batch_review_population"
            df["legacy_sidecar_name"] = "batch_review_population"
        df.to_csv(LABELS / f"{stem}.csv", index=False)
        _write_json_records(LABELS / f"{stem}.json", df)
        for year in YEARS:
            year_df = df.loc[df["fiscal_year"].eq(year)].copy()
            year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
            _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _replace_combined_rule_truth(truth: pd.DataFrame) -> None:
    path = LABELS / "rule_truth.csv"
    combined = pd.read_csv(path, low_memory=False)
    combined = combined.loc[combined["rule_id"].astype(str).ne(RULE_ID)].copy()
    rebuilt = pd.concat([combined, truth], ignore_index=True, sort=False)
    rebuilt.to_csv(path, index=False)
    _write_json_records(LABELS / "rule_truth.json", rebuilt)


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        df = df.drop(columns=[col for col in ["source_candidate", "truth_contract_version"] if col in df.columns])
        df["source_candidate"] = "v123"
        df["truth_contract_version"] = "v123_active_candidate_contract"
        df.to_csv(path, index=False)
        _write_json_records(path.with_suffix(".json"), df)
        count += 1
        if "fiscal_year" in df.columns:
            for year in YEARS:
                year_path = LABELS / f"{path.stem}_{year}.csv"
                if year_path.exists():
                    year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
                    year_df.to_csv(year_path, index=False)
                    _write_json_records(year_path.with_suffix(".json"), year_df)
    return count


def _update_manifest(truth: pd.DataFrame) -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    if not path.exists():
        return {"manifest_rows": 0}
    manifest = pd.read_csv(path, low_memory=False)
    manifest["source_candidate"] = "v123"
    for stem in ["rule_truth_L4_06", "batch_review_population", "batch_detector_universe"]:
        mask = manifest["sidecar_name"].astype(str).eq(stem)
        if mask.any():
            manifest.loc[mask, "row_count"] = len(truth)
            manifest.loc[mask, "document_count"] = truth["document_id"].nunique()
            manifest.loc[mask, "owner_rule"] = "L4-06"
            manifest.loc[mask, "purpose"] = "detector_contract_universe"
            manifest.loc[mask, "sidecar_role"] = "strict_truth_alias"
            manifest.loc[mask, "expected_detector_positive"] = "true"
            manifest.loc[mask, "allowed_for_independent_sidecar_eval"] = False
            manifest.loc[mask, "can_overlap_detector_universe"] = True
            manifest.loc[mask, "semantics"] = (
                "Detector-contract universe. Use for L4-06 contract checks, not independent realism evaluation."
            )
            manifest.loc[mask, "reason"] = "v123 refreshed L4-06 from current year-file detector output."
    manifest.to_csv(path, index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)
    return {"manifest_rows": int(len(manifest))}


def _legacy_source_count() -> int:
    bad = {}
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda c: c == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v123"]:
            bad[path.name] = values
    if bad:
        raise SystemExit(f"legacy rule_truth source metadata remains: {bad}")
    return 0


def main() -> int:
    _copy_candidate_fast()
    removed_before = _cleanup_version_files()
    rows = _load_year_journal()
    previous_docs = set(pd.read_csv(LABELS / "rule_truth_L4_06.csv", usecols=["document_id"])["document_id"].astype(str))
    truth, breakdown = _build_l406_truth(rows)
    current_docs = set(truth["document_id"].astype(str))
    _write_truth_family(truth)
    _replace_combined_rule_truth(truth)
    normalized_truth_files = _normalize_rule_truth_metadata()
    manifest_stats = _update_manifest(truth)
    legacy_sources = _legacy_source_count()
    removed_after = _cleanup_version_files()
    summary = {
        "candidate_version": "v123",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "refresh L4-06 detector-contract truth from current year journal files",
        "previous_l406_docs": len(previous_docs),
        "current_l406_docs": len(current_docs),
        "added_l406_docs": sorted(current_docs - previous_docs),
        "removed_l406_docs": sorted(previous_docs - current_docs),
        "breakdown": breakdown,
        "sidecar_manifest": manifest_stats,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_sources,
        "removed_copied_version_manifests": removed_before,
        "removed_copied_version_manifests_after_write": removed_after,
    }
    (DEST / "V123_L406_TRUTH_REFRESH.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V123_CANDIDATE.md").write_text(
        "# DataSynth v123 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: L4-06 detector-contract truth refresh after v122 year-file consistency cleanup.\n\n"
        "Confirmed BatchAnomaly labels and normal/boundary controls are unchanged.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
