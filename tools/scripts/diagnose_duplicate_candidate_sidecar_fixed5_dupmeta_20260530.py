"""Diagnostic-only duplicate candidate sidecar sampling for fixed5_dupmeta.

The script keeps the main top-score candidate subset unchanged and evaluates
bounded sidecar candidate sources. Truth metadata is used only for aggregate
evaluation and for the explicitly labeled oracle feasibility probe.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import AuditSettings, get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import (
    _select_large_input_candidate_frame,
    build_duplicate_pair_artifact,
)
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _dist,
    _doc_set_from_pairs,
    _pair_docs,
    _quantiles,
    _tier,
    raw_identifier_leak_check,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_dupmeta"
CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
PHASE1_CASE_RESULT = ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
LABEL_DIR = ROOT / "data" / "journal" / "primary" / DATASET_NAME / "labels"
TRUTH_CSV = LABEL_DIR / "manipulated_entry_truth.csv"
DUPLICATE_PAIR_TRUTH_CSV = LABEL_DIR / "duplicate_pair_truth.csv"
OUT_JSON = ROOT / "artifacts" / "duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json"
SIDECAR_MAX_ROWS = 20_000
SIDECAR_MAX_DOCS = 10_000
SIDECAR_TOP_N = 5_000


def _truth_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def _bucket_amount(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown"
    amount = abs(float(numeric))
    if amount >= 10_000_000:
        return "very_high"
    if amount >= 1_000_000:
        return "high"
    if amount >= 100_000:
        return "medium"
    return "low"


def _bucket_line_count(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown"
    if numeric <= 1:
        return "single_line"
    if numeric <= 3:
        return "two_to_three_lines"
    return "four_or_more_lines"


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    truth = pd.read_csv(TRUTH_CSV)
    truth["document_id"] = truth["document_id"].astype(str)
    pair_truth = pd.read_csv(DUPLICATE_PAIR_TRUTH_CSV)
    pair_truth["document_id"] = pair_truth["document_id"].astype(str)
    return df, truth, pair_truth


def _phase1_band_by_doc() -> dict[str, str]:
    with PHASE1_CASE_RESULT.open("rb") as fh:
        result = pickle.load(fh)
    rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    band_by_doc: dict[str, str] = {}
    for case in getattr(result, "cases", []):
        band = str(getattr(case, "priority_band", "") or "none").lower()
        for hit in getattr(case, "raw_rule_hits", []):
            doc = getattr(hit, "document_id", None)
            if doc in (None, ""):
                continue
            current = band_by_doc.get(str(doc), "none")
            if rank.get(band, 0) > rank.get(current, 0):
                band_by_doc[str(doc)] = band
    return band_by_doc


def _same_value_ratio(df: pd.DataFrame, docs: set[str], column: str) -> float:
    if column not in df.columns or not docs:
        return 0.0
    subset = df[df["document_id"].isin(docs)]
    if subset.empty:
        return 0.0
    grouped = subset.groupby("document_id")[column].nunique(dropna=True)
    return float((grouped <= 1).mean()) if len(grouped) else 0.0


def _group_profile(
    *,
    name: str,
    docs: set[str],
    truth: pd.DataFrame,
    df: pd.DataFrame,
    band_by_doc: dict[str, str],
) -> dict[str, Any]:
    subset = truth[truth["document_id"].isin(docs)].copy()
    if subset.empty:
        return {"group": name, "doc_count": 0}
    subset["line_amount_bucket"] = subset["line_amount"].map(_bucket_amount)
    subset["row_count_bucket"] = subset["line_count"].map(_bucket_line_count)
    return {
        "group": name,
        "doc_count": len(docs),
        "semantic_group_present_doc_count": int(
            subset["duplicate_pair_semantic_group"].notna().sum()
        ),
        "semantic_group_count": int(
            subset["duplicate_pair_semantic_group"].dropna().astype(str).nunique()
        ),
        "similarity_injection_source_distribution": _dist(
            subset["similarity_injection_source"]
        ),
        "time_shift_bucket_distribution": _dist(subset["intended_date_distance_bucket"]),
        "amount_similarity_bucket_distribution": _dist(
            subset["intended_amount_similarity_band"]
        ),
        "reference_similarity_bucket_distribution": _dist(
            subset["intended_reference_similarity_band"]
        ),
        "text_similarity_bucket_distribution": _dist(subset["intended_text_similarity_band"]),
        "partner_match_ratio": float(
            _truth_bool_series(subset["intended_partner_match"]).mean()
        ),
        "same_account_ratio": _same_value_ratio(df, docs, "gl_account"),
        "same_business_process_ratio": float(
            (subset.groupby("document_id")["business_process"].nunique(dropna=True) <= 1).mean()
        ),
        "row_count_bucket_distribution": _dist(subset["row_count_bucket"]),
        "line_amount_bucket_distribution": _dist(subset["line_amount_bucket"]),
        "source_distribution": _dist(subset["source"]),
        "user_distribution": _dist(subset["entered_by"] if "entered_by" in subset else []),
        "process_distribution": _dist(subset["business_process"]),
        "phase1_action_tier_distribution": _dist(
            band_by_doc.get(doc, "none") for doc in docs
        ),
    }


def _sidecar_settings(base: AuditSettings) -> AuditSettings:
    return AuditSettings(
        duplicate_pair_artifact_top_n=SIDECAR_TOP_N,
        duplicate_pair_artifact_max_rows=SIDECAR_MAX_ROWS,
        duplicate_max_pairs_per_row=int(base.duplicate_max_pairs_per_row),
        duplicate_max_total_pairs=int(base.duplicate_max_total_pairs),
        duplicate_max_group_size=int(base.duplicate_max_group_size),
        duplicate_fuzzy_threshold=int(base.duplicate_fuzzy_threshold),
        duplicate_amount_tolerance=float(base.duplicate_amount_tolerance),
        duplicate_split_window_days=int(base.duplicate_split_window_days),
        duplicate_time_window_days=int(base.duplicate_time_window_days),
        duplicate_pair_artifact_max_pairs_per_document=int(
            base.duplicate_pair_artifact_max_pairs_per_document
        ),
        duplicate_pair_artifact_max_pairs_per_document_pair=int(
            base.duplicate_pair_artifact_max_pairs_per_document_pair
        ),
    )


def _bounded_by_document(df: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    subset = df.loc[index].copy()
    if subset.empty:
        return subset
    subset["_doc_pos"] = subset.groupby("document_id").cumcount()
    subset = subset[subset["_doc_pos"] < 2].drop(columns=["_doc_pos"])
    if subset["document_id"].nunique() > SIDECAR_MAX_DOCS:
        keep_docs = set(subset["document_id"].drop_duplicates().head(SIDECAR_MAX_DOCS))
        subset = subset[subset["document_id"].isin(keep_docs)]
    return subset.head(SIDECAR_MAX_ROWS)


def _l2_03d_stratified_sample(
    df: pd.DataFrame,
    details: pd.DataFrame,
    scores: pd.Series,
    main_candidate_index: set[Any],
) -> pd.DataFrame:
    mask = (details["L2-03d"] > 0) & ~details.index.isin(main_candidate_index)
    pool = pd.DataFrame(
        {
            "score": scores.reindex(details.index).fillna(0.0),
            "pos": range(len(details)),
        },
        index=details.index,
    )[mask]
    if pool.empty:
        return df.iloc[[]]
    pool["score_bin"] = pd.qcut(pool["score"].rank(method="first"), q=10, duplicates="drop")
    sampled_parts: list[pd.DataFrame] = []
    per_bin = max(SIDECAR_MAX_ROWS // max(pool["score_bin"].nunique(), 1), 1)
    for _bin, group in pool.groupby("score_bin", observed=True):
        ordered = group.sort_values(["score", "pos"], ascending=[False, True])
        if len(ordered) <= per_bin:
            sampled_parts.append(ordered)
            continue
        positions = np.linspace(0, len(ordered) - 1, num=per_bin, dtype=int)
        sampled_parts.append(ordered.iloc[positions])
    sampled = pd.concat(sampled_parts).sort_values(["score", "pos"], ascending=[False, True])
    return _bounded_by_document(df, sampled.index)


def _metadata_probe_sample(df: pd.DataFrame, primary_docs: set[str]) -> pd.DataFrame:
    return _bounded_by_document(df, df[df["document_id"].isin(primary_docs)].index)


def _rule_balanced_sample(
    df: pd.DataFrame,
    details: pd.DataFrame,
    scores: pd.Series,
    main_candidate_index: set[Any],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    per_rule = SIDECAR_MAX_ROWS // max(len(details.columns), 1)
    for rule_id in details.columns:
        mask = (details[rule_id] > 0) & ~details.index.isin(main_candidate_index)
        pool = pd.DataFrame(
            {
                "score": scores.reindex(details.index).fillna(0.0),
                "rule_score": details[rule_id],
                "pos": range(len(details)),
            },
            index=details.index,
        )[mask]
        if pool.empty:
            continue
        parts.append(
            pool.sort_values(["rule_score", "score", "pos"], ascending=[False, False, True]).head(
                per_rule
            )
        )
    if not parts:
        return df.iloc[[]]
    sampled = pd.concat(parts).sort_values(["score", "pos"], ascending=[False, True])
    return _bounded_by_document(df, sampled.index)


def _pair_feature_rates(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {
            "weak_pair_ratio": 0.0,
            "case_grade_pair_ratio": 0.0,
            "same_partner_ratio": 0.0,
            "reference_similarity_quantiles": {},
            "text_similarity_quantiles": {},
            "amount_similarity_quantiles": {},
        }
    weak = sum(_tier(pair) == "weak" for pair in pairs)
    case_grade = sum(_tier(pair) in {"strong", "moderate"} for pair in pairs)
    same_partner = sum(pair.get("features", {}).get("same_partner") is True for pair in pairs)
    return {
        "weak_pair_ratio": weak / len(pairs),
        "case_grade_pair_ratio": case_grade / len(pairs),
        "same_partner_ratio": same_partner / len(pairs),
        "reference_similarity_quantiles": _quantiles(
            pair.get("features", {}).get("reference_similarity") for pair in pairs
        ),
        "text_similarity_quantiles": _quantiles(
            pair.get("features", {}).get("text_similarity") for pair in pairs
        ),
        "amount_similarity_quantiles": _quantiles(
            pair.get("features", {}).get("amount_similarity") for pair in pairs
        ),
    }


def _evaluate_sidecar(
    *,
    name: str,
    df: pd.DataFrame,
    candidate_df: pd.DataFrame,
    settings: AuditSettings,
    primary_docs: set[str],
) -> dict[str, Any]:
    artifact = build_duplicate_pair_artifact(candidate_df, settings).to_dict()
    pairs = list(artifact.get("top_pairs", []))
    primary_pairs = [pair for pair in pairs if _pair_docs(pair) & primary_docs]
    case_grade_primary_pairs = [
        pair for pair in primary_pairs if _tier(pair) in {"strong", "moderate"}
    ]
    candidate_docs = (
        set(candidate_df["document_id"].astype(str)) if not candidate_df.empty else set()
    )
    primary_pair_docs = _doc_set_from_pairs(primary_pairs) & primary_docs
    case_grade_primary_docs = _doc_set_from_pairs(case_grade_primary_pairs) & primary_docs
    return {
        "sidecar_id": name,
        "diagnostic_only": True,
        "does_not_replace_main_candidate_subset": True,
        "not_case_grade_by_default": True,
        "bounded_row_count": int(len(candidate_df)),
        "bounded_document_count": int(candidate_df["document_id"].nunique())
        if not candidate_df.empty
        else 0,
        "sidecar_candidate_docs": len(candidate_docs),
        "duplicate_primary_docs_entering_sidecar": len(candidate_docs & primary_docs),
        "generated_pair_count": len(pairs),
        "generated_pair_evidence_primary_docs": len(primary_pair_docs),
        "case_grade_pair_primary_docs": len(case_grade_primary_docs),
        "expected_review_burden": {
            "top_pairs": len(pairs),
            "candidate_docs": len(candidate_docs),
            "nonprimary_candidate_docs": len(candidate_docs - primary_docs),
        },
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in pairs),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
        "primary_rule_id_distribution": _dist(pair.get("rule_id") for pair in primary_pairs),
        "primary_evidence_tier_distribution": _dist(_tier(pair) for pair in primary_pairs),
        **_pair_feature_rates(pairs),
        "primary_pair_feature_rates": _pair_feature_rates(primary_pairs),
        "artifact_coverage": {
            key: value
            for key, value in artifact.get("coverage", {}).items()
            if key != "top_pairs"
        },
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df, truth, pair_truth = _load_inputs()
    primary_docs = set(
        truth.loc[_truth_bool_series(truth["duplicate_primary_target"]), "document_id"].astype(str)
    )
    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    scores = result.scores.reindex(df.index).fillna(0.0).astype(float)
    details = result.details.reindex(df.index).apply(pd.to_numeric, errors="coerce").fillna(0.0)
    row_score_docs = set(df.loc[scores > 0, "document_id"].astype(str)) & primary_docs
    main_candidate_df, main_coverage = _select_large_input_candidate_frame(
        df,
        max_rows=int(settings.duplicate_pair_artifact_max_rows),
        candidate_scores=result.scores,
        candidate_details=result.details,
    )
    main_candidate_docs = (
        set()
        if main_candidate_df is None
        else set(main_candidate_df["document_id"].astype(str))
    )
    main_candidate_index = set() if main_candidate_df is None else set(main_candidate_df.index)
    no_row_score_docs = primary_docs - row_score_docs
    low_score_docs = row_score_docs - main_candidate_docs
    retained_docs = row_score_docs & main_candidate_docs
    band_by_doc = _phase1_band_by_doc()
    sidecar_settings = _sidecar_settings(settings)
    sidecar_frames = {
        "l2_03d_stratified_low_score_sample": _l2_03d_stratified_sample(
            df,
            details,
            scores,
            main_candidate_index,
        ),
        "duplicate_primary_metadata_probe_sample": _metadata_probe_sample(df, primary_docs),
        "rule_balanced_duplicate_candidate_sample": _rule_balanced_sample(
            df,
            details,
            scores,
            main_candidate_index,
        ),
    }
    sidecars = {
        name: _evaluate_sidecar(
            name=name,
            df=df,
            candidate_df=frame,
            settings=sidecar_settings,
            primary_docs=primary_docs,
        )
        for name, frame in sidecar_frames.items()
    }
    pair_feasible = any(
        item["generated_pair_evidence_primary_docs"] > 0 for item in sidecars.values()
    )
    non_oracle_pair_feasible = any(
        item["generated_pair_evidence_primary_docs"] > 0
        for name, item in sidecars.items()
        if name != "duplicate_primary_metadata_probe_sample"
    )
    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "diagnostic_only": True,
        "production_ranking_change_recommended": False,
        "production_first_review_ranking_changed": False,
        "threshold_change_recommended": False,
        "row_score_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "primary_target_docs": len(primary_docs),
        "row_score_coverage_docs": len(row_score_docs),
        "candidate_subset_coverage_docs": len(main_candidate_docs & primary_docs),
        "bottleneck_stage": "candidate_subset_prefilter",
        "top_pairs_cap_is_bottleneck": False,
        "row_score_coverage_gap_docs": len(no_row_score_docs),
        "low_score_cap_gap_docs": len(low_score_docs),
        "candidate_subset": {
            "main_candidate_subset_unchanged": True,
            "selected_candidate_rows": int(main_coverage.get("selected_candidate_rows", 0)),
            "primary_doc_count": len(main_candidate_docs & primary_docs),
            "selected_min_score": float(scores.loc[list(main_candidate_index)].min())
            if main_candidate_index
            else None,
            "coverage": main_coverage,
        },
        "primary_gap_groups": {
            "no_row_score_primary_docs": _group_profile(
                name="no_row_score_primary_docs",
                docs=no_row_score_docs,
                truth=truth,
                df=df,
                band_by_doc=band_by_doc,
            ),
            "low_score_l2_03d_primary_docs": _group_profile(
                name="low_score_l2_03d_primary_docs",
                docs=low_score_docs,
                truth=truth,
                df=df,
                band_by_doc=band_by_doc,
            ),
            "candidate_subset_retained_primary_docs": _group_profile(
                name="candidate_subset_retained_primary_docs",
                docs=retained_docs,
                truth=truth,
                df=df,
                band_by_doc=band_by_doc,
            ),
        },
        "sidecar_sampling_candidate": sidecars,
        "pair_feasibility_confirmed": pair_feasible,
        "non_oracle_sidecar_pair_feasibility_confirmed": non_oracle_pair_feasible,
        "sidecar_or_export_candidate": (
            "bounded_non_oracle_sidecar_candidate"
            if non_oracle_pair_feasible
            else "oracle_probe_only_not_product_sidecar"
        ),
        "datasynth_metadata_alignment_issue": {
            "status": "possible_feature_gap",
            "no_row_score_primary_docs": len(no_row_score_docs),
            "low_score_l2_03d_primary_docs": len(low_score_docs),
            "non_oracle_sidecars_reached_primary_docs": non_oracle_pair_feasible,
            "read": (
                "Duplicate primary metadata is aligned as an evaluation denominator, "
                "but current observable duplicate features do not reach pair evidence "
                "for most primary targets without an oracle metadata probe."
            ),
        },
        "decision": {
            "main_first_review_ordering_change": False,
            "threshold_change": False,
            "weak_pair_promotion": False,
            "top_pairs_cap_expansion": False,
            "next_product_direction": (
                "Validate bounded export sidecar only if pair feasibility is "
                "case-grade and cross-batch stable; otherwise revisit observable "
                "duplicate-like feature generation."
            ),
        },
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=set(truth["document_id"].astype(str))
        | set(pair_truth["document_id"].astype(str)),
    )
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "primary_target_docs": payload["primary_target_docs"],
                "row_score_coverage_docs": payload["row_score_coverage_docs"],
                "candidate_subset_coverage_docs": payload["candidate_subset_coverage_docs"],
                "pair_feasibility_confirmed": payload["pair_feasibility_confirmed"],
                "sidecars": {
                    key: {
                        "candidate_docs": value["sidecar_candidate_docs"],
                        "primary_docs": value["duplicate_primary_docs_entering_sidecar"],
                        "pair_primary_docs": value["generated_pair_evidence_primary_docs"],
                        "case_grade_primary_docs": value["case_grade_pair_primary_docs"],
                        "weak_pair_ratio": value["weak_pair_ratio"],
                    }
                    for key, value in payload["sidecar_sampling_candidate"].items()
                },
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
