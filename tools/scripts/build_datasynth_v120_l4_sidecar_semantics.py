"""Build v120 candidate by clarifying L4 sidecar semantics.

Changes:

- Treat L4 review-population files as detector-contract universes, not
  independent realism sidecars.
- Add explicit detector-universe aliases for L4 review populations.
- Add clearer context aliases for normal/boundary files that may overlap raw
  detector hits.
- Refresh sidecar_manifest classifications for L4 and Benford sidecars.

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
SOURCE = ROOT / "data" / "journal" / "primary" / "datasynth_v119_candidate"
DEST = ROOT / "data" / "journal" / "primary" / "datasynth_v120_candidate"
LABELS = DEST / "labels"
YEARS = (2022, 2023, 2024)
YEAR_SUFFIX_RE = re.compile(r"_20\d{2}$")
KEEP_VERSION_FILES = {"FREEZE_V120_CANDIDATE.md", "V120_L4_SIDECAR_SEMANTICS.json"}


DETECTOR_UNIVERSE_ALIASES = {
    "revenue_outlier_review_population": {
        "alias": "revenue_outlier_detector_universe",
        "rule": "L4-01",
    },
    "high_amount_review_population": {
        "alias": "high_amount_detector_universe",
        "rule": "L4-03",
    },
    "rare_account_pair_review_population": {
        "alias": "rare_account_pair_detector_universe",
        "rule": "L4-04",
    },
    "abnormal_hours_behavior_review_population": {
        "alias": "abnormal_hours_behavior_detector_universe",
        "rule": "L4-05",
    },
    "batch_review_population": {
        "alias": "batch_detector_universe",
        "rule": "L4-06",
    },
}

CONTEXT_ALIASES = {
    "high_amount_normal_controls": {
        "alias": "high_amount_legitimate_contexts",
        "rule": "L4-03",
        "role": "normal_context",
        "description": "High-value business contexts that can be legitimate even when review-worthy.",
    },
    "high_amount_boundary_controls": {
        "alias": "high_amount_boundary_contexts",
        "rule": "L4-03",
        "role": "boundary_control",
        "description": "High-amount boundary contexts near review thresholds.",
    },
    "rare_account_pair_normal_controls": {
        "alias": "rare_account_pair_legitimate_contexts",
        "rule": "L4-04",
        "role": "normal_context",
        "description": "Legitimate rare-pair contexts; may still belong to the raw L4-04 review universe.",
    },
    "batch_normal_controls": {
        "alias": "batch_legitimate_contexts",
        "rule": "L4-06",
        "role": "normal_context",
        "description": "Legitimate batch/interface contexts; not a strict negative detector set.",
    },
    "batch_boundary_controls": {
        "alias": "batch_boundary_contexts",
        "rule": "L4-06",
        "role": "boundary_control",
        "description": "Batch boundary contexts that may be review-worthy but are not confirmed anomalies.",
    },
    "revenue_outlier_boundary_controls": {
        "alias": "revenue_outlier_boundary_contexts",
        "rule": "L4-01",
        "role": "boundary_control",
        "description": "Revenue outlier boundary contexts for L4-01 scoring interpretation.",
    },
}

L4_CLASSIFICATIONS = {
    "rule_truth_L4_01": ("L4-01", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rule_truth_L4_02": ("L4-02", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rule_truth_L4_03": ("L4-03", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rule_truth_L4_04": ("L4-04", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rule_truth_L4_05": ("L4-05", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rule_truth_L4_06": ("L4-06", "strict_truth_alias", "detector_contract_universe", "true", False),
    "revenue_outlier_review_population": ("L4-01", "strict_truth_alias", "detector_contract_universe", "true", False),
    "revenue_outlier_detector_universe": ("L4-01", "strict_truth_alias", "detector_contract_universe", "true", False),
    "high_amount_review_population": ("L4-03", "strict_truth_alias", "detector_contract_universe", "true", False),
    "high_amount_detector_universe": ("L4-03", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rare_account_pair_review_population": ("L4-04", "strict_truth_alias", "detector_contract_universe", "true", False),
    "rare_account_pair_detector_universe": ("L4-04", "strict_truth_alias", "detector_contract_universe", "true", False),
    "abnormal_hours_behavior_review_population": ("L4-05", "strict_truth_alias", "detector_contract_universe", "true", False),
    "abnormal_hours_behavior_detector_universe": ("L4-05", "strict_truth_alias", "detector_contract_universe", "true", False),
    "batch_review_population": ("L4-06", "strict_truth_alias", "detector_contract_universe", "true", False),
    "batch_detector_universe": ("L4-06", "strict_truth_alias", "detector_contract_universe", "true", False),
    "revenue_manipulation_l401_direct_truth": ("L4-01", "confirmed_subset", "scenario_coverage", "true", True),
    "high_amount_confirmed_anomalies": ("L4-03", "confirmed_subset", "scenario_coverage", "true", True),
    "rare_account_pair_confirmed_anomalies": ("L4-04", "confirmed_subset", "scenario_coverage", "true", True),
    "abnormal_hours_concentration_cases": ("L4-05", "confirmed_subset", "scenario_coverage", "true", True),
    "batch_confirmed_anomalies": ("L4-06", "confirmed_subset", "scenario_coverage", "true", True),
    "high_amount_normal_controls": ("L4-03", "normal_context", "realism_control", "may_be_true", True),
    "high_amount_legitimate_contexts": ("L4-03", "normal_context", "realism_control", "may_be_true", True),
    "high_amount_boundary_controls": ("L4-03", "boundary_control", "realism_control", "may_be_true", True),
    "high_amount_boundary_contexts": ("L4-03", "boundary_control", "realism_control", "may_be_true", True),
    "rare_account_pair_normal_controls": ("L4-04", "normal_context", "realism_control", "may_be_true", True),
    "rare_account_pair_legitimate_contexts": ("L4-04", "normal_context", "realism_control", "may_be_true", True),
    "rare_account_pair_excluded_large_docs": ("L4-04", "contract_manifest", "contract_manifest", "false", False),
    "batch_normal_controls": ("L4-06", "normal_context", "realism_control", "may_be_true", True),
    "batch_legitimate_contexts": ("L4-06", "normal_context", "realism_control", "may_be_true", True),
    "batch_boundary_controls": ("L4-06", "boundary_control", "realism_control", "may_be_true", True),
    "batch_boundary_contexts": ("L4-06", "boundary_control", "realism_control", "may_be_true", True),
    "revenue_outlier_boundary_controls": ("L4-01", "boundary_control", "realism_control", "may_be_true", True),
    "revenue_outlier_boundary_contexts": ("L4-01", "boundary_control", "realism_control", "may_be_true", True),
}

BENFORD_CLASSIFICATIONS = {
    "benford_finding_truth": ("L4-02", "strict_truth_alias", "detector_contract_universe", "true", False),
    "benford_broad_digit_findings": ("L4-02", "drilldown_candidate", "drilldown_candidate", "null", True),
    "benford_drilldown_candidates": ("L4-02", "drilldown_candidate", "drilldown_candidate", "null", True),
    "benford_adversarial_holdout": ("L4-02", "adversarial_holdout", "realism_control", "true", True),
    "benford_weak_fraud_holdout": ("L4-02", "adversarial_holdout", "realism_control", "may_be_true", True),
    "benford_boundary_groups": ("L4-02", "boundary_control", "realism_control", "may_be_true", True),
    "benford_high_mad_normal_controls": ("L4-02", "normal_context", "realism_control", "may_be_true", True),
    "benford_business_skew_normal_groups": ("L4-02", "normal_context", "realism_control", "may_be_true", True),
    "benford_company_specific_normals": ("L4-02", "normal_context", "realism_control", "may_be_true", True),
    "benford_normal_groups": ("L4-02", "normal_context", "realism_control", "false", True),
    "benford_small_sample_controls": ("L4-02", "boundary_control", "realism_control", "false", True),
    "benford_skipped_small_groups": ("L4-02", "contract_manifest", "contract_manifest", "false", False),
}


def _copy_candidate_fast() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source dataset: {SOURCE}")
    if DEST.exists():
        required = [DEST / f"journal_entries_{year}.csv" for year in YEARS]
        required.append(DEST / "V120_L4_SIDECAR_SEMANTICS.json")
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


def _cleanup_copied_version_files() -> dict[str, list[str]]:
    removed_root: list[str] = []
    for path in DEST.iterdir():
        if not path.is_file() or path.name in KEEP_VERSION_FILES:
            continue
        if path.name.startswith("FREEZE_V") or re.match(r"^V\d+_", path.name):
            removed_root.append(path.name)
            path.unlink()

    removed_labels: list[str] = []
    if LABELS.exists():
        for path in LABELS.iterdir():
            if path.is_file() and re.match(r"^V\d+_.+\.json$", path.name):
                removed_labels.append(path.name)
                path.unlink()
    return {"root": sorted(removed_root), "labels": sorted(removed_labels)}


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


def _read_csv(stem: str) -> pd.DataFrame:
    return pd.read_csv(LABELS / f"{stem}.csv", low_memory=False)


def _doc_set(stem: str) -> set[str]:
    path = LABELS / f"{stem}.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, usecols=lambda c: c == "document_id", low_memory=False)
    if "document_id" not in df.columns:
        return set()
    return set(df["document_id"].dropna().astype(str))


def _annotate_sidecar(
    df: pd.DataFrame,
    *,
    stem: str,
    owner_rule: str,
    sidecar_role: str,
    purpose: str,
    expected_detector_positive: str,
    independent_eval: bool,
    can_overlap: bool,
    semantics: str,
    alias_of: str | None = None,
) -> pd.DataFrame:
    df = df.copy()
    df["owner_rule"] = owner_rule
    df["sidecar_role"] = sidecar_role
    df["sidecar_purpose"] = purpose
    df["sidecar_semantics"] = semantics
    df["expected_detector_positive"] = expected_detector_positive
    df["allowed_for_independent_sidecar_eval"] = independent_eval
    df["can_overlap_detector_universe"] = can_overlap
    df["source_candidate"] = "v120"
    df["truth_contract_version"] = "v120_active_candidate_contract"
    if alias_of:
        df["alias_of_sidecar"] = alias_of
        df["legacy_sidecar_name"] = alias_of
    else:
        df["alias_of_sidecar"] = ""
        df["legacy_sidecar_name"] = ""
    df["sidecar_name"] = stem
    return df


def _create_aliases_and_annotate_l4() -> dict[str, Any]:
    stats: dict[str, Any] = {"detector_universe_aliases": {}, "context_aliases": {}, "overlaps": {}}

    detector_sets = {
        "L4-01": _doc_set("rule_truth_L4_01"),
        "L4-03": _doc_set("rule_truth_L4_03"),
        "L4-04": _doc_set("rule_truth_L4_04"),
        "L4-05": _doc_set("rule_truth_L4_05"),
        "L4-06": _doc_set("rule_truth_L4_06"),
    }

    for source_stem, cfg in DETECTOR_UNIVERSE_ALIASES.items():
        if not (LABELS / f"{source_stem}.csv").exists():
            continue
        source = _read_csv(source_stem)
        rule = cfg["rule"]
        semantics = (
            f"{source_stem} is a detector-contract universe alias for {rule}. "
            "Use for rule contract checks, not as an independent realism sidecar."
        )
        source = _annotate_sidecar(
            source,
            stem=source_stem,
            owner_rule=rule,
            sidecar_role="strict_truth_alias",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            independent_eval=False,
            can_overlap=True,
            semantics=semantics,
        )
        _write_family(source_stem, source)

        alias = source.copy()
        alias_stem = cfg["alias"]
        alias = _annotate_sidecar(
            alias,
            stem=alias_stem,
            owner_rule=rule,
            sidecar_role="strict_truth_alias",
            purpose="detector_contract_universe",
            expected_detector_positive="true",
            independent_eval=False,
            can_overlap=True,
            semantics=semantics,
            alias_of=source_stem,
        )
        _write_family(alias_stem, alias)
        docs = set(alias["document_id"].dropna().astype(str)) if "document_id" in alias.columns else set()
        stats["detector_universe_aliases"][alias_stem] = {
            "source": source_stem,
            "rows": int(len(alias)),
            "document_count": int(len(docs)),
            "diff_vs_rule_truth": int(len(docs.symmetric_difference(detector_sets.get(rule, set())))),
        }

    for source_stem, cfg in CONTEXT_ALIASES.items():
        if not (LABELS / f"{source_stem}.csv").exists():
            continue
        source = _read_csv(source_stem)
        rule = cfg["rule"]
        role = cfg["role"]
        source = _annotate_sidecar(
            source,
            stem=source_stem,
            owner_rule=rule,
            sidecar_role=role,
            purpose="realism_control",
            expected_detector_positive="may_be_true",
            independent_eval=True,
            can_overlap=True,
            semantics=cfg["description"],
        )
        _write_family(source_stem, source)

        alias_stem = cfg["alias"]
        alias = _annotate_sidecar(
            source,
            stem=alias_stem,
            owner_rule=rule,
            sidecar_role=role,
            purpose="realism_control",
            expected_detector_positive="may_be_true",
            independent_eval=True,
            can_overlap=True,
            semantics=cfg["description"],
            alias_of=source_stem,
        )
        _write_family(alias_stem, alias)
        docs = set(alias["document_id"].dropna().astype(str)) if "document_id" in alias.columns else set()
        overlap = int(len(docs & detector_sets.get(rule, set())))
        stats["context_aliases"][alias_stem] = {
            "source": source_stem,
            "rows": int(len(alias)),
            "document_count": int(len(docs)),
            "overlap_with_owner_detector_universe": overlap,
        }
        stats["overlaps"][source_stem] = overlap

    for stem, values in {**L4_CLASSIFICATIONS, **BENFORD_CLASSIFICATIONS}.items():
        path = LABELS / f"{stem}.csv"
        if not path.exists():
            continue
        if stem in DETECTOR_UNIVERSE_ALIASES or stem in CONTEXT_ALIASES:
            continue
        df = _read_csv(stem)
        owner_rule, role, purpose, expected, independent = values
        df = _annotate_sidecar(
            df,
            stem=stem,
            owner_rule=owner_rule,
            sidecar_role=role,
            purpose=purpose,
            expected_detector_positive=expected,
            independent_eval=independent,
            can_overlap=expected in {"true", "may_be_true", "null"},
            semantics=f"{stem} classified as {role} for {owner_rule}.",
        )
        _write_family(stem, df)

    return stats


def _load_manifest() -> pd.DataFrame:
    path = LABELS / "sidecar_manifest.csv"
    if path.exists():
        manifest = pd.read_csv(path, low_memory=False)
    else:
        manifest = pd.DataFrame(columns=["sidecar_name"])
    for col in [
        "sidecar_name",
        "path",
        "exists",
        "row_count",
        "document_count",
        "owner_rule",
        "purpose",
        "expected_detector_positive",
        "allowed_for_independent_sidecar_eval",
        "semantics",
        "reason",
        "source_candidate",
        "sidecar_role",
        "can_overlap_detector_universe",
        "preferred_replacement",
        "legacy_sidecar_name",
    ]:
        if col not in manifest.columns:
            manifest[col] = None
    return manifest


def _manifest_row(stem: str, values: tuple[str, str, str, str, bool]) -> dict[str, Any]:
    path = LABELS / f"{stem}.csv"
    owner_rule, role, purpose, expected, independent = values
    if path.exists():
        df = pd.read_csv(path, low_memory=False)
        row_count = len(df)
        document_count = int(df["document_id"].dropna().astype(str).nunique()) if "document_id" in df.columns else None
    else:
        row_count = 0
        document_count = None
    semantics = {
        "strict_truth_alias": "Detector-contract universe. Use for contract checks, not independent realism evaluation.",
        "confirmed_subset": "Plausible confirmed/scenario subset for behavioral coverage.",
        "normal_context": "Legitimate or normal-looking context; detector may still flag it as review-worthy.",
        "boundary_control": "Boundary context for score interpretation; not a strict negative set.",
        "adversarial_holdout": "Holdout/adversarial group intended for realism evaluation.",
        "drilldown_candidate": "Drilldown candidate context, not document-level strict truth.",
        "contract_manifest": "Manifest/diagnostic context, not independent sidecar truth.",
    }.get(role, "Classified sidecar.")
    preferred = {
        "rare_account_pair_normal_controls": "rare_account_pair_legitimate_contexts",
        "batch_boundary_controls": "batch_boundary_contexts",
        "batch_normal_controls": "batch_legitimate_contexts",
        "high_amount_normal_controls": "high_amount_legitimate_contexts",
        "high_amount_boundary_controls": "high_amount_boundary_contexts",
        "revenue_outlier_boundary_controls": "revenue_outlier_boundary_contexts",
        "high_amount_review_population": "high_amount_detector_universe",
        "rare_account_pair_review_population": "rare_account_pair_detector_universe",
        "batch_review_population": "batch_detector_universe",
        "abnormal_hours_behavior_review_population": "abnormal_hours_behavior_detector_universe",
        "revenue_outlier_review_population": "revenue_outlier_detector_universe",
    }.get(stem, "")
    return {
        "sidecar_name": stem,
        "path": f"labels/{stem}.csv",
        "exists": path.exists(),
        "row_count": row_count,
        "document_count": document_count,
        "owner_rule": owner_rule,
        "purpose": purpose,
        "expected_detector_positive": expected,
        "allowed_for_independent_sidecar_eval": independent,
        "semantics": semantics,
        "reason": "v120 L4 sidecar role classification.",
        "source_candidate": "v120",
        "sidecar_role": role,
        "can_overlap_detector_universe": expected in {"true", "may_be_true", "null"},
        "preferred_replacement": preferred,
        "legacy_sidecar_name": "",
    }


def _update_sidecar_manifest() -> dict[str, Any]:
    manifest = _load_manifest()
    classifications = {**L4_CLASSIFICATIONS, **BENFORD_CLASSIFICATIONS}
    for old, cfg in DETECTOR_UNIVERSE_ALIASES.items():
        classifications[cfg["alias"]] = L4_CLASSIFICATIONS[cfg["alias"]]
        classifications[old] = L4_CLASSIFICATIONS[old]
    for old, cfg in CONTEXT_ALIASES.items():
        classifications[cfg["alias"]] = L4_CLASSIFICATIONS[cfg["alias"]]
        classifications[old] = L4_CLASSIFICATIONS[old]

    rows = []
    for stem, values in sorted(classifications.items()):
        row = _manifest_row(stem, values)
        rows.append(row)
        if stem in set(manifest["sidecar_name"].astype(str)):
            mask = manifest["sidecar_name"].astype(str).eq(stem)
            for key, value in row.items():
                manifest.loc[mask, key] = value
        else:
            manifest = pd.concat([manifest, pd.DataFrame([row])], ignore_index=True, sort=False)

    manifest["source_candidate"] = "v120"
    manifest.to_csv(LABELS / "sidecar_manifest.csv", index=False)
    _write_json_records(LABELS / "sidecar_manifest.json", manifest)
    l4_manifest = manifest.loc[
        manifest["sidecar_name"].astype(str).isin(classifications)
        | manifest["owner_rule"].astype(str).str.startswith("L4", na=False)
    ].copy()
    return {
        "manifest_rows": int(len(manifest)),
        "l4_manifest_rows": int(len(l4_manifest)),
        "l4_role_counts": {str(k): int(v) for k, v in l4_manifest["sidecar_role"].fillna("").value_counts().sort_index().to_dict().items()},
        "purpose_counts": {str(k): int(v) for k, v in manifest["purpose"].fillna("").value_counts().sort_index().to_dict().items()},
    }


def _normalize_rule_truth_metadata() -> int:
    count = 0
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, low_memory=False)
        df = df.drop(columns=[col for col in ["source_candidate", "truth_contract_version"] if col in df.columns])
        df["source_candidate"] = "v120"
        df["truth_contract_version"] = "v120_active_candidate_contract"
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
    bad: dict[str, list[str]] = {}
    for path in sorted(LABELS.glob("rule_truth_*.csv")):
        if YEAR_SUFFIX_RE.search(path.stem):
            continue
        df = pd.read_csv(path, usecols=lambda c: c == "source_candidate", low_memory=False)
        values = sorted(df["source_candidate"].dropna().astype(str).unique().tolist())
        if values != ["v120"]:
            count += 1
            bad[path.name] = values
    if bad:
        raise SystemExit(f"legacy rule_truth source metadata remains: {bad}")
    return count


def main() -> int:
    _copy_candidate_fast()
    removed_version_files = _cleanup_copied_version_files()
    alias_stats = _create_aliases_and_annotate_l4()
    manifest_stats = _update_sidecar_manifest()
    normalized_truth_files = _normalize_rule_truth_metadata()
    rule_counts = _rebuild_combined_rule_truth()
    legacy_sources = _legacy_source_count()
    removed_version_files_after = _cleanup_copied_version_files()

    summary = {
        "candidate_version": "v120",
        "source_baseline": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "patch_scope": "clarify L4 sidecar semantics; no journal rows or rule-truth membership changed",
        "aliases_and_contexts": alias_stats,
        "sidecar_manifest": manifest_stats,
        "normalized_rule_truth_files": normalized_truth_files,
        "legacy_rule_truth_source_files": legacy_sources,
        "removed_copied_version_manifests": removed_version_files,
        "removed_copied_version_manifests_after_write": removed_version_files_after,
        "rule_counts": rule_counts,
    }
    (DEST / "V120_L4_SIDECAR_SEMANTICS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (DEST / "FREEZE_V120_CANDIDATE.md").write_text(
        "# DataSynth v120 Candidate\n\n"
        f"Source baseline: `{summary['source_baseline']}`.\n\n"
        "Scope: L4 sidecar semantics cleanup. No journal rows or rule-truth membership changed.\n\n"
        "Key policy: L4 `*_review_population` files are detector-contract universes, not independent realism samples.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2, default=str)}\n```\n",
        encoding="utf-8",
    )
    _cleanup_copied_version_files()
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
