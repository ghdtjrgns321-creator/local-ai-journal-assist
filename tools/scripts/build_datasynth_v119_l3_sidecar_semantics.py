"""Build v119 candidate by tightening L3 sidecar semantics.

Changes:

- Split labeled documents out of L3-06 normal after-hours context sidecars.
- Add explicit L3-06 detector-contract columns to the normal-context alias.
- Add L3-03 linkage columns to IC exception drilldown sidecars.
- Refresh sidecar manifest classifications for the touched sidecars.

No journal rows or rule-truth membership are changed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v118_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v119_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V119_CANDIDATE.md", "V119_L3_SIDECAR_SEMANTICS.json"}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V119_L3_SIDECAR_SEMANTICS.json")
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


def _cleanup_copied_version_files() -> list[str]:
    removed = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed.append(path.name)
            path.unlink()
    return sorted(removed)


def _write_json_records(path: Path, df: pd.DataFrame) -> None:
    records = df.where(pd.notna(df), None).to_dict(orient="records")
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_family(stem: str, df: pd.DataFrame) -> None:
    df.to_csv(LABELS / f"{stem}.csv", index=False)
    _write_json_records(LABELS / f"{stem}.json", df)
    if "fiscal_year" not in df.columns:
        return
    for year in YEARS:
        year_df = df.loc[pd.to_numeric(df["fiscal_year"], errors="coerce").eq(year)].copy()
        year_df.to_csv(LABELS / f"{stem}_{year}.csv", index=False)
        _write_json_records(LABELS / f"{stem}_{year}.json", year_df)


def _load_label_map() -> pd.DataFrame:
    labels = pd.read_csv(
        LABELS / "anomaly_labels.csv",
        usecols=["document_id", "anomaly_type"],
        low_memory=False,
    )
    labels["document_id"] = labels["document_id"].astype(str)
    return (
        labels.groupby("document_id")["anomaly_type"]
        .apply(lambda value: "|".join(sorted(set(value.dropna().astype(str)))))
        .reset_index(name="anomaly_types_from_labels")
    )


def _patch_afterhours_context() -> dict[str, Any]:
    label_map = _load_label_map()
    labeled_docs = set(label_map["document_id"].astype(str))
    stats: dict[str, Any] = {}

    source = pd.read_csv(LABELS / "afterhours_normal_context_within_review_population.csv", low_memory=False)
    source["document_id"] = source["document_id"].astype(str)
    source = source.merge(label_map, on="document_id", how="left")
    is_labeled = source["document_id"].isin(labeled_docs)

    cross = source.loc[is_labeled].copy()
    normal = source.loc[~is_labeled].copy()

    for frame, role in ((normal, "normal_context_within_l306_afterhours_review_population"), (cross, "cross_rule_labeled_context_within_l306_afterhours_review_population")):
        frame["rule_id"] = "L3-06"
        frame["expected_hit"] = True
        frame["truth_layer"] = "rule_truth"
        frame["truth_basis"] = "posting_date hour is within configured after-hours window"
        frame["evaluation_unit"] = "document_id"
        frame["within_l306_review_population"] = True
        frame["sidecar_semantics"] = role
        frame["source_candidate"] = "v119"
        frame["truth_contract_version"] = "v119_active_candidate_contract"

    normal["has_any_anomaly_label"] = False
    normal["anomaly_types"] = ""
    normal["related_anomaly_types"] = ""
    normal = normal.drop(columns=["anomaly_types_from_labels"], errors="ignore")

    cross["has_any_anomaly_label"] = True
    cross["related_anomaly_types"] = cross["anomaly_types_from_labels"].fillna("")
    cross["anomaly_types"] = cross["anomaly_types_from_labels"].fillna("")
    cross["normal_after_hours_context"] = False
    cross["background_temporal_pattern"] = False
    cross["not_a_negative_control"] = True
    cross["evaluation_policy"] = (
        "Cross-rule labeled context inside L3-06 review population. Do not use as normal after-hours control."
    )
    cross = cross.drop(columns=["anomaly_types_from_labels"], errors="ignore")

    _write_family("afterhours_normal_context_within_review_population", normal)
    _write_family("normal_after_hours_context", normal)
    _write_family("afterhours_cross_rule_labeled_context", cross)

    stats["original_normal_context_docs"] = int(source["document_id"].nunique())
    stats["remaining_unlabeled_normal_context_docs"] = int(normal["document_id"].nunique())
    stats["cross_rule_labeled_context_docs"] = int(cross["document_id"].nunique())
    stats["cross_rule_anomaly_types"] = (
        cross["related_anomaly_types"].fillna("").str.split("|").explode().value_counts().to_dict()
        if not cross.empty
        else {}
    )
    return stats


def _patch_ic_drilldowns() -> dict[str, Any]:
    truth = pd.read_csv(LABELS / "rule_truth_L3_03.csv", usecols=["document_id"], low_memory=False)
    truth_docs = set(truth["document_id"].dropna().astype(str))
    stems = [
        "ic_unmatched_cases",
        "ic_amount_mismatch_cases",
        "ic_timing_gap_cases",
        "transfer_pricing_review_cases",
    ]
    frames = []
    stats: dict[str, Any] = {}
    for stem in stems:
        df = pd.read_csv(LABELS / f"{stem}.csv", low_memory=False)
        target = df.get("target_document_id", pd.Series("", index=df.index)).fillna("").astype(str)
        counterpart = df.get("counterpart_document_id", pd.Series("", index=df.index)).fillna("").astype(str)
        df["target_in_l303_rule_truth"] = target.isin(truth_docs)
        df["counterpart_in_l303_rule_truth"] = counterpart.isin(truth_docs)
        df["linked_l303_document_ids"] = [
            "|".join([doc for doc in (t, c) if doc in truth_docs])
            for t, c in zip(target, counterpart, strict=False)
        ]
        df["linked_l303_document_count"] = df["linked_l303_document_ids"].apply(
            lambda value: 0 if not value else len(str(value).split("|"))
        )
        df["sidecar_semantics"] = "ic_exception_case_level_drilldown_not_l303_document_subset"
        df["owner_rule"] = {
            "ic_unmatched_cases": "IC01",
            "ic_amount_mismatch_cases": "IC02",
            "ic_timing_gap_cases": "IC03",
            "transfer_pricing_review_cases": "GR03",
        }[stem]
        df["linked_l303_policy"] = (
            "Case-level IC exception drilldown. Link to L3-03 via target/counterpart document ids, "
            "not via this file's document_id subset semantics."
        )
        df["source_candidate"] = "v119"
        _write_family(stem, df)
        frames.append(df.assign(source_sidecar=stem))
        stats[stem] = {
            "rows": int(len(df)),
            "target_in_l303": int(df["target_in_l303_rule_truth"].sum()),
            "counterpart_in_l303": int(df["counterpart_in_l303_rule_truth"].sum()),
            "any_linked_l303": int(df["linked_l303_document_count"].gt(0).sum()),
        }

    combined = pd.concat(frames, ignore_index=True, sort=False)
    _write_family("intercompany_exception_cases", combined)
    stats["intercompany_exception_cases"] = {
        "rows": int(len(combined)),
        "any_linked_l303": int(combined["linked_l303_document_count"].gt(0).sum()),
    }
    return stats


def _update_sidecar_manifest() -> dict[str, Any]:
    path = LABELS / "sidecar_manifest.csv"
    manifest = pd.read_csv(path, low_memory=False)
    overrides = {
        "afterhours_normal_context_within_review_population": {
            "purpose": "realism_control",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "Unlabeled normal-looking after-hours context inside L3-06 review population.",
            "reason": "Labeled cross-rule context is split into afterhours_cross_rule_labeled_context.",
        },
        "normal_after_hours_context": {
            "purpose": "realism_control",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "Unlabeled normal-looking after-hours context inside L3-06 review population.",
            "reason": "Legacy alias kept clean of anomaly-labeled documents.",
        },
        "afterhours_cross_rule_labeled_context": {
            "purpose": "review_population",
            "expected_detector_positive": "true",
            "allowed_for_independent_sidecar_eval": False,
            "semantics": "Anomaly-labeled after-hours context inside L3-06 review population.",
            "reason": "Cross-rule context, not a normal after-hours control.",
        },
        "ic_unmatched_cases": {
            "purpose": "drilldown_case",
            "expected_detector_positive": "null",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "IC01 case-level drilldown linked to L3-03 via target/counterpart ids.",
            "reason": "Not a document-level subset of rule_truth_L3_03.",
        },
        "ic_amount_mismatch_cases": {
            "purpose": "drilldown_case",
            "expected_detector_positive": "null",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "IC02 case-level drilldown linked to L3-03 via target/counterpart ids.",
            "reason": "Not a document-level subset of rule_truth_L3_03.",
        },
        "ic_timing_gap_cases": {
            "purpose": "drilldown_case",
            "expected_detector_positive": "null",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "IC03 case-level drilldown linked to L3-03 via target/counterpart ids.",
            "reason": "Not a document-level subset of rule_truth_L3_03.",
        },
        "transfer_pricing_review_cases": {
            "purpose": "drilldown_case",
            "expected_detector_positive": "null",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "GR03 case-level drilldown linked to L3-03 via target/counterpart ids.",
            "reason": "Not a document-level subset of rule_truth_L3_03.",
        },
        "intercompany_exception_cases": {
            "purpose": "drilldown_case",
            "expected_detector_positive": "null",
            "allowed_for_independent_sidecar_eval": True,
            "semantics": "Combined IC exception case-level drilldown.",
            "reason": "Not a document-level subset of rule_truth_L3_03.",
        },
    }

    existing = set(manifest["sidecar_name"].astype(str))
    new_rows = []
    for stem, values in overrides.items():
        csv_path = LABELS / f"{stem}.csv"
        if stem in existing:
            for key, value in values.items():
                manifest.loc[manifest["sidecar_name"].eq(stem), key] = value
            manifest.loc[manifest["sidecar_name"].eq(stem), "source_candidate"] = "v119"
            if csv_path.exists():
                manifest.loc[manifest["sidecar_name"].eq(stem), "row_count"] = len(pd.read_csv(csv_path, low_memory=False))
                doc_df = pd.read_csv(csv_path, usecols=lambda c: c == "document_id", low_memory=False)
                if "document_id" in doc_df.columns:
                    manifest.loc[manifest["sidecar_name"].eq(stem), "document_count"] = doc_df["document_id"].dropna().astype(str).nunique()
        elif csv_path.exists():
            df = pd.read_csv(csv_path, usecols=lambda c: c == "document_id", low_memory=False)
            new_rows.append({
                "sidecar_name": stem,
                "path": f"labels/{stem}.csv",
                "exists": True,
                "row_count": int(len(pd.read_csv(csv_path, low_memory=False))),
                "document_count": int(df["document_id"].dropna().astype(str).nunique()) if "document_id" in df.columns else None,
                "owner_rule": "L3-06" if stem.startswith("afterhours") else "IC",
                **values,
                "source_candidate": "v119",
            })
    if new_rows:
        manifest = pd.concat([manifest, pd.DataFrame(new_rows)], ignore_index=True, sort=False)

    if "source_candidate" in manifest.columns:
        manifest["source_candidate"] = "v119"
    manifest.to_csv(path, index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)
    return {
        "manifest_rows": int(len(manifest)),
        "purpose_counts": {str(k): int(v) for k, v in manifest["purpose"].value_counts().sort_index().to_dict().items()},
        "independent_allowed": int(manifest["allowed_for_independent_sidecar_eval"].astype(bool).sum()),
    }


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        df = df.drop(columns=[col for col in ["source_candidate", "truth_contract_version"] if col in df.columns])
        df["source_candidate"] = "v119"
        df["truth_contract_version"] = "v119_active_candidate_contract"
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


def _rebuild_combined_rule_truth() -> dict[str, int]:
    frames = []
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        frames.append(pd.read_csv(path, low_memory=False))
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(LABELS / "rule_truth.csv", index=False)
    _write_json_records(LABELS / "rule_truth.json", combined)
    return {str(rule): int(count) for rule, count in combined["rule_id"].value_counts().sort_index().to_dict().items()}


def _legacy_source_count() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda c: c == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v119"]:
            count += 1
    return count


def main() -> int:
    _copy_candidate_fast()
    old_manifest_files = _cleanup_copied_version_files()
    afterhours_stats = _patch_afterhours_context()
    ic_stats = _patch_ic_drilldowns()
    manifest_stats = _update_sidecar_manifest()
    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    legacy_sources = _legacy_source_count()
    if legacy_sources:
        raise SystemExit(f"legacy rule_truth source metadata remains: {legacy_sources}")

    summary = {
        "candidate_version": "v119",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "tighten L3-06 after-hours context and L3-03 IC drilldown semantics",
        "afterhours": afterhours_stats,
        "intercompany": ic_stats,
        "sidecar_manifest": manifest_stats,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_sources,
        "removed_copied_version_manifests": old_manifest_files,
        "rule_counts": rule_counts,
    }
    (DEST / "V119_L3_SIDECAR_SEMANTICS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V119_CANDIDATE.md").write_text(
        "# DataSynth v119 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: L3 sidecar semantics cleanup. No journal rows or rule truth membership changed.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_copied_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
