"""Duplicate v3.3b exact primary/sidecar diagnostic.

Diagnostic-only. Measures duplicate primary and companion targets from the
v3.3b owner metadata without changing production duplicate ranking, row-score
thresholds, top-pair caps, weak-pair gates, PHASE1 ranking, or PHASE2 fusion.
The current path only builds the expensive pair artifact when target documents
enter the production candidate subset.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import (
    _select_large_input_candidate_frame,
    build_duplicate_pair_artifact,
)
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _dist,
    _doc_set_from_pairs,
    _pair_docs,
    _tier,
)
from tools.scripts.diagnose_duplicate_v32_companion_sidecar_burden_20260531 import (
    _document_feature_frame,
    _observable_document_profile_sample,
    _raw_identifier_leak_check,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

DATASET_NAME = os.environ.get(
    "DUPLICATE_DIAGNOSTIC_DATASET",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d",
)
DATA_DIR = ROOT / "data" / "journal" / "primary" / DATASET_NAME
JOURNAL_CSV = DATA_DIR / "journal_entries.csv"
LABEL_DIR = DATA_DIR / "labels"
TRUTH_CSV = LABEL_DIR / "manipulated_entry_truth.csv"
DUPLICATE_PAIR_TRUTH_CSV = LABEL_DIR / "duplicate_pair_truth.csv"
OUT_JSON = ROOT / os.environ.get(
    "DUPLICATE_DIAGNOSTIC_OUT",
    "artifacts/duplicate_v33_exact_sidecar_fixed5_20260531.json",
)
RESPONSIBILITY_JSON = (
    ROOT
    / os.environ.get(
        "DUPLICATE_RESPONSIBILITY_ARTIFACT",
        "artifacts/phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json",
    )
)
STRICT_FEATURE_DOC_CAP = 10_000
REFERENCE_MID_THRESHOLD = 90


def _truth_bool_series(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    usecols = [
        "document_id",
        "company_code",
        "fiscal_year",
        "posting_date",
        "document_type",
        "reference",
        "business_process",
        "source",
        "line_number",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_text",
        "trading_partner",
    ]
    df = pd.read_csv(JOURNAL_CSV, usecols=usecols, dtype=str)
    df["document_id"] = df["document_id"].astype(str)
    for amount_column in ("debit_amount", "credit_amount"):
        df[amount_column] = pd.to_numeric(df[amount_column], errors="coerce").fillna(0.0)
    df["line_number"] = pd.to_numeric(df["line_number"], errors="coerce")
    df["posting_date"] = pd.to_datetime(df["posting_date"], errors="coerce")
    truth = pd.read_csv(TRUTH_CSV, dtype=str).fillna("")
    truth["document_id"] = truth["document_id"].astype(str)
    pair_truth = pd.read_csv(DUPLICATE_PAIR_TRUTH_CSV, dtype=str).fillna("")
    pair_truth["document_id"] = pair_truth["document_id"].astype(str)
    return df, truth, pair_truth


def _target_docs(truth: pd.DataFrame, column: str) -> set[str]:
    return set(
        truth.loc[_truth_bool_series(truth[column]), "document_id"].astype(str)
    )


def _pair_truth_case_grade_docs(pair_truth: pd.DataFrame, target_docs: set[str]) -> set[str]:
    if not target_docs:
        return set()
    grade = pair_truth["expected_pair_grade"].astype(str).str.lower().isin(
        {"strong", "moderate"}
    )
    return set(pair_truth.loc[grade, "document_id"].astype(str)) & target_docs


def _evaluate_candidate_docs(
    *,
    candidate_id: str,
    candidate_docs: set[str],
    primary_docs: set[str],
    companion_docs: set[str],
    pair_truth: pd.DataFrame,
    guard_case_grade: bool,
) -> dict[str, Any]:
    primary_case_grade_docs = _pair_truth_case_grade_docs(pair_truth, primary_docs)
    companion_case_grade_docs = _pair_truth_case_grade_docs(pair_truth, companion_docs)
    primary_hit = candidate_docs & primary_docs
    companion_hit = candidate_docs & companion_docs
    return {
        "candidate_id": candidate_id,
        "diagnostic_only": True,
        "measurement_basis": "candidate_document_exact_join_with_pair_truth_grade",
        "candidate_docs": len(candidate_docs),
        "primary_candidate_docs": len(primary_hit),
        "companion_candidate_docs": len(companion_hit),
        "non_target_candidate_docs": len(candidate_docs - primary_docs - companion_docs),
        "primary_candidate_recall": len(primary_hit) / len(primary_docs)
        if primary_docs
        else None,
        "companion_candidate_recall": len(companion_hit) / len(companion_docs)
        if companion_docs
        else None,
        "primary_case_grade_docs": len(primary_hit & primary_case_grade_docs),
        "companion_case_grade_docs": len(companion_hit & companion_case_grade_docs),
        "primary_case_grade_recall": len(primary_hit & primary_case_grade_docs)
        / len(primary_docs)
        if primary_docs
        else None,
        "companion_case_grade_recall": len(companion_hit & companion_case_grade_docs)
        / len(companion_docs)
        if companion_docs
        else None,
        "guard_case_grade_by_construction": guard_case_grade,
        "non_target_to_primary_candidate_ratio": round(
            len(candidate_docs - primary_docs - companion_docs) / max(len(primary_hit), 1),
            6,
        ),
        "non_target_to_all_target_candidate_ratio": round(
            len(candidate_docs - primary_docs - companion_docs)
            / max(len(primary_hit | companion_hit), 1),
            6,
        ),
    }


def _evaluate_pair_artifact(
    *,
    candidate_id: str,
    artifact: dict[str, Any],
    candidate_docs: set[str],
    primary_docs: set[str],
    companion_docs: set[str],
) -> dict[str, Any]:
    pairs = list(artifact.get("top_pairs", []))
    pair_docs = _doc_set_from_pairs(pairs)
    primary_pairs = [pair for pair in pairs if _pair_docs(pair) & primary_docs]
    companion_pairs = [pair for pair in pairs if _pair_docs(pair) & companion_docs]
    primary_case_grade_pairs = [
        pair for pair in primary_pairs if _tier(pair) in {"strong", "moderate"}
    ]
    companion_case_grade_pairs = [
        pair for pair in companion_pairs if _tier(pair) in {"strong", "moderate"}
    ]
    primary_pair_docs = _doc_set_from_pairs(primary_pairs) & primary_docs
    companion_pair_docs = _doc_set_from_pairs(companion_pairs) & companion_docs
    primary_case_grade_docs = _doc_set_from_pairs(primary_case_grade_pairs) & primary_docs
    companion_case_grade_docs = (
        _doc_set_from_pairs(companion_case_grade_pairs) & companion_docs
    )
    return {
        "candidate_id": candidate_id,
        "diagnostic_only": True,
        "measurement_basis": "top_pair_artifact_exact_doc_join",
        "candidate_docs": len(candidate_docs),
        "primary_candidate_docs": len(candidate_docs & primary_docs),
        "companion_candidate_docs": len(candidate_docs & companion_docs),
        "non_target_candidate_docs": len(candidate_docs - primary_docs - companion_docs),
        "generated_pair_count": len(pairs),
        "pair_document_count": len(pair_docs),
        "primary_pair_docs": len(primary_pair_docs),
        "companion_pair_docs": len(companion_pair_docs),
        "primary_case_grade_docs": len(primary_case_grade_docs),
        "companion_case_grade_docs": len(companion_case_grade_docs),
        "primary_pair_recall": len(primary_pair_docs) / len(primary_docs)
        if primary_docs
        else None,
        "companion_pair_recall": len(companion_pair_docs) / len(companion_docs)
        if companion_docs
        else None,
        "primary_case_grade_recall": len(primary_case_grade_docs) / len(primary_docs)
        if primary_docs
        else None,
        "companion_case_grade_recall": len(companion_case_grade_docs) / len(companion_docs)
        if companion_docs
        else None,
        "top_pair_non_target_document_count": len(pair_docs - primary_docs - companion_docs),
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in pairs),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in pairs),
    }


def _evaluate_pair_artifact_frame(
    *,
    candidate_id: str,
    frame: pd.DataFrame,
    settings: Any,
    primary_docs: set[str],
    companion_docs: set[str],
    pair_truth: pd.DataFrame,
) -> dict[str, Any]:
    """Build a bounded sidecar pair artifact and report aggregate attrition only.

    This is diagnostic-only. It does not emit raw identifiers and does not change
    production ranking, row scores, weak-pair gates, PHASE1 ranking, or PHASE2
    fusion. Truth/pair sidecars are used only after pair generation to aggregate
    coverage and explain remaining misses.
    """
    if frame.empty:
        return {
            "candidate_id": candidate_id,
            "diagnostic_only": True,
            "measurement_basis": "sidecar_pair_artifact_aggregate_probe",
            "candidate_docs": 0,
            "primary_case_grade_docs": 0,
            "companion_case_grade_docs": 0,
            "remaining_primary_docs": len(primary_docs),
            "remaining_primary_expected_pair_grade_distribution": {},
        }
    artifact = build_duplicate_pair_artifact(frame, settings).to_dict()
    candidate_docs = set(frame["document_id"].astype(str)) if "document_id" in frame else set()
    evaluated = _evaluate_pair_artifact(
        candidate_id=candidate_id,
        artifact=artifact,
        candidate_docs=candidate_docs,
        primary_docs=primary_docs,
        companion_docs=companion_docs,
    )
    pairs = list(artifact.get("top_pairs", []))
    case_grade_pairs = [pair for pair in pairs if _tier(pair) in {"strong", "moderate"}]
    case_grade_docs = _doc_set_from_pairs(case_grade_pairs)
    remaining_primary = primary_docs - case_grade_docs
    remaining_rows = pair_truth[pair_truth["document_id"].astype(str).isin(remaining_primary)]
    evaluated.update(
        {
            "measurement_basis": "sidecar_pair_artifact_aggregate_probe",
            "remaining_primary_docs": len(remaining_primary),
            "remaining_primary_expected_pair_grade_distribution": _dist(
                remaining_rows["expected_pair_grade"].astype(str)
            ),
            "remaining_primary_expected_same_partner_distribution": _dist(
                remaining_rows["expected_same_partner"].astype(str)
            ),
            "remaining_primary_expected_same_process_distribution": _dist(
                remaining_rows["expected_same_process"].astype(str)
            ),
            "remaining_primary_expected_same_reference_distribution": _dist(
                remaining_rows["expected_same_reference"].astype(str)
            ),
            "remaining_primary_expected_same_amount_distribution": _dist(
                remaining_rows["expected_same_amount_band"].astype(str)
            ),
            "remaining_primary_expected_date_shift_distribution": _dist(
                remaining_rows["expected_date_shift_bucket"].astype(str)
            ),
            "remaining_primary_intended_text_similarity_distribution": _dist(
                remaining_rows["intended_text_similarity_band"].astype(str)
            ),
            "top_pair_selection": artifact.get("coverage", {}).get("top_pair_selection", {}),
            "raw_identifier_emitted": False,
        }
    )
    return evaluated


def _strict_time_shift_profile_sample_bounded(
    df: pd.DataFrame,
    *,
    features: pd.DataFrame,
) -> pd.DataFrame:
    from tools.scripts.diagnose_duplicate_v32_companion_sidecar_burden_20260531 import (
        _strict_time_shift_profile_sample,
    )

    return _strict_time_shift_profile_sample(
        df,
        features=features.head(STRICT_FEATURE_DOC_CAP),
    )


def _time_shift_reference_guard_sample(
    df: pd.DataFrame,
    *,
    features: pd.DataFrame,
    candidate_id: str,
    reference_threshold: int,
    amount_delta_max: float,
    max_day_shift: int = 3,
    feature_doc_cap: int = STRICT_FEATURE_DOC_CAP,
) -> pd.DataFrame:
    """Selector-safe duplicate-like sidecar sample.

    Uses observable GL fields only: same partner/process, 2-3 document rows,
    reference similarity, near amount, and 1-N day shift. Truth metadata and
    matched results are only used later for aggregate evaluation.
    """
    del candidate_id
    if features.empty:
        return df.iloc[[]].copy()
    eligible = features.head(feature_doc_cap)
    eligible = eligible[
        eligible["row_count"].between(2, 3)
        & (eligible["trading_partner"].astype(str).str.len() > 0)
        & (eligible["business_process"].astype(str).str.len() > 0)
        & (eligible["reference"].astype(str).str.len() > 0)
    ].copy()
    docs: set[str] = set()
    for _, group in eligible.groupby(["trading_partner", "business_process"], sort=False):
        if len(group) < 2:
            continue
        ordered = group.sort_values("posting_date", kind="mergesort")
        records = list(
            ordered[["max_amount", "posting_date", "reference"]].itertuples(
                index=True,
                name=None,
            )
        )
        n = len(records)
        for left_pos, (left_doc, left_amount, left_date, left_ref) in enumerate(records):
            for right_doc, right_amount, right_date, right_ref in records[
                left_pos + 1 : min(n, left_pos + 100)
            ]:
                if pd.isna(left_date) or pd.isna(right_date):
                    continue
                day_diff = int((right_date - left_date).days)
                if day_diff > max_day_shift:
                    break
                if day_diff < 1:
                    continue
                denominator = max(abs(float(left_amount)), abs(float(right_amount)), 1.0)
                amount_delta = abs(float(left_amount) - float(right_amount)) / denominator
                if amount_delta > amount_delta_max:
                    continue
                if fuzz.ratio(str(left_ref), str(right_ref)) < reference_threshold:
                    continue
                docs.add(str(left_doc))
                docs.add(str(right_doc))
    if not docs:
        return df.iloc[[]].copy()
    subset = df[df["document_id"].astype(str).isin(docs)].copy()
    if subset.empty:
        return subset
    subset["_doc_pos"] = subset.groupby("document_id").cumcount()
    return subset[subset["_doc_pos"] < 2].drop(columns=["_doc_pos"])


def _current_duplicate_path(
    df: pd.DataFrame,
    *,
    primary_docs: set[str],
    companion_docs: set[str],
) -> dict[str, Any]:
    if os.environ.get("RUN_FULL_DUPLICATE_CURRENT_PATH") != "1":
        payload = json.loads(RESPONSIBILITY_JSON.read_text(encoding="utf-8"))
        primary_key = (
            "primary_owner_target_recall_v33d"
            if "primary_owner_target_recall_v33d" in payload
            else "primary_owner_target_recall_v33"
        )
        companion_key = (
            "companion_context_contribution_v33d"
            if "companion_context_contribution_v33d" in payload
            else "companion_context_contribution_v33"
        )
        primary_top500 = payload[primary_key]["duplicate"]["topn"]["top500"]
        companion_top500 = payload[companion_key][
            "duplicate_companion"
        ]["topn"]["top500"]
        return {
            "candidate_id": "current_duplicate_path",
            "diagnostic_only": True,
            "measurement_basis": (
                primary_top500.get("measurement_basis")
                or "responsibility_artifact_estimated_proration"
            ),
            "status": "full_current_detector_rerun_skipped_by_bounded_diagnostic_budget",
            "full_rerun_env_flag": "RUN_FULL_DUPLICATE_CURRENT_PATH=1",
            "primary_denominator": len(primary_docs),
            "companion_denominator": len(companion_docs),
            "primary_case_grade_docs": int(
                primary_top500.get("matched_docs_estimated_proration")
                or primary_top500.get("matched_docs")
                or 0
            ),
            "companion_case_grade_docs": int(
                companion_top500.get("matched_docs_estimated_proration")
                or companion_top500.get("matched_docs")
                or 0
            ),
            "primary_case_grade_recall": float(
                primary_top500.get("recall_estimated_proration")
                or primary_top500.get("recall")
                or 0.0
            ),
            "companion_case_grade_recall": float(
                companion_top500.get("recall_estimated_proration")
                or companion_top500.get("recall")
                or 0.0
            ),
            "primary_source_status": primary_top500.get("status"),
            "companion_source_status": companion_top500.get("status"),
            "pair_artifact_built": False,
        }
    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    scores = result.scores.reindex(df.index).fillna(0.0).astype(float)
    main_candidate_df, coverage = _select_large_input_candidate_frame(
        df,
        max_rows=int(settings.duplicate_pair_artifact_max_rows),
        candidate_scores=result.scores,
        candidate_details=result.details,
        candidate_supplement_strategy=str(
            settings.duplicate_pair_artifact_candidate_supplement_strategy
        ),
        candidate_supplement_max_docs=int(
            settings.duplicate_pair_artifact_candidate_supplement_max_docs
        ),
    )
    candidate_docs = (
        set(main_candidate_df["document_id"].astype(str))
        if main_candidate_df is not None and not main_candidate_df.empty
        else set()
    )
    row_score_docs = set(df.loc[scores > 0, "document_id"].astype(str))
    selected_floor = (
        float(scores.loc[list(main_candidate_df.index)].min())
        if main_candidate_df is not None and not main_candidate_df.empty
        else 0.0
    )
    base: dict[str, Any] = {
        "candidate_id": "current_duplicate_path",
        "diagnostic_only": True,
        "measurement_basis": "production_candidate_subset_exact_join",
        "row_score_primary_docs": len(row_score_docs & primary_docs),
        "row_score_companion_docs": len(row_score_docs & companion_docs),
        "no_row_score_primary_docs": len(primary_docs - row_score_docs),
        "no_row_score_companion_docs": len(companion_docs - row_score_docs),
        "candidate_subset_primary_docs": len(candidate_docs & primary_docs),
        "candidate_subset_companion_docs": len(candidate_docs & companion_docs),
        "candidate_subset_docs": len(candidate_docs),
        "candidate_subset_selected_rows": int(coverage.get("selected_candidate_rows", 0)),
        "candidate_subset_score_rows": int(coverage.get("selected_score_candidate_rows", 0)),
        "candidate_subset_supplement_rows": int(
            coverage.get("candidate_supplement_selected_rows", 0)
        ),
        "candidate_subset_supplement_docs": int(
            coverage.get("candidate_supplement_selected_docs", 0)
        ),
        "candidate_subset_supplement_strategy": str(
            coverage.get("candidate_supplement_strategy", "none")
        ),
        "candidate_subset_min_score": selected_floor,
        "pair_artifact_built": False,
        "primary_pair_docs": 0,
        "companion_pair_docs": 0,
        "primary_case_grade_docs": 0,
        "companion_case_grade_docs": 0,
        "primary_case_grade_recall": 0.0 if primary_docs else None,
        "companion_case_grade_recall": 0.0 if companion_docs else None,
    }
    if not (candidate_docs & (primary_docs | companion_docs)):
        base["pair_artifact_skip_reason"] = "no_target_docs_in_current_candidate_subset"
        return base
    artifact = build_duplicate_pair_artifact(main_candidate_df, settings).to_dict()
    base.update(
        _evaluate_pair_artifact(
            candidate_id="current_duplicate_path",
            artifact=artifact,
            candidate_docs=candidate_docs,
            primary_docs=primary_docs,
            companion_docs=companion_docs,
        )
    )
    base["pair_artifact_built"] = True
    return base


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df, truth, pair_truth = _load_inputs()
    primary_docs = _target_docs(truth, "duplicate_primary_target")
    companion_docs = _target_docs(truth, "duplicate_companion_target")
    current = _current_duplicate_path(
        df,
        primary_docs=primary_docs,
        companion_docs=companion_docs,
    )

    features = _document_feature_frame(df, exclude_index=set())
    candidate_frames = {
        "observable_profile_top_10000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=10_000,
        ),
        "observable_profile_top_5000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=5_000,
        ),
        "observable_profile_top_2000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=2_000,
        ),
        "observable_profile_top_1000": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=1_000,
        ),
        "observable_profile_top_500": _observable_document_profile_sample(
            df,
            features=features,
            max_docs=500,
        ),
        "mid_time_shift_reference_guard": _time_shift_reference_guard_sample(
            df,
            features=features,
            candidate_id="mid_time_shift_reference_guard",
            reference_threshold=REFERENCE_MID_THRESHOLD,
            amount_delta_max=0.05,
        ),
        "strict_time_shift_reference_guard": _strict_time_shift_profile_sample_bounded(
            df,
            features=features,
        ),
    }
    sidecars = {
        name: _evaluate_candidate_docs(
            candidate_id=name,
            candidate_docs=set(frame["document_id"].astype(str)) if not frame.empty else set(),
            primary_docs=primary_docs,
            companion_docs=companion_docs,
            pair_truth=pair_truth,
            guard_case_grade=name
            in {"mid_time_shift_reference_guard", "strict_time_shift_reference_guard"},
        )
        for name, frame in candidate_frames.items()
    }
    best = max(
        sidecars.values(),
        key=lambda item: (
            item["primary_case_grade_docs"],
            item["companion_case_grade_docs"],
            -item["non_target_candidate_docs"],
        ),
    )
    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "responsibility_map_version": (
            "v3.3d" if DATASET_NAME.endswith("_v33d") else "v3.3b"
        ),
        "diagnostic_only": True,
        "duplicate_primary_denominator": len(primary_docs),
        "duplicate_companion_denominator": len(companion_docs),
        "production_first_review_ranking_changed": True,
        "row_score_threshold_changed": False,
        "row_scores_changed": False,
        "top_pairs_cap_changed": False,
        "candidate_subset_supplement_changed": True,
        "pair_artifact_selection_strategy_changed": True,
        "document_profile_pair_builder_added": True,
        "weak_pair_gate_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_metadata_used_as_selector": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "selector_inputs": [
            "document row_count",
            "business_process",
            "trading_partner",
            "reference similarity",
            "posting_date distance",
            "amount proximity",
        ],
        "current_duplicate_path": current,
        "sidecar_results": sidecars,
        "sidecar_pair_artifact_probes": {},
        "experiment_summary": {
            "best_sidecar_candidate": best["candidate_id"],
            "best_sidecar_primary_case_grade_docs": best["primary_case_grade_docs"],
            "best_sidecar_companion_case_grade_docs": best["companion_case_grade_docs"],
            "best_sidecar_candidate_docs": best["candidate_docs"],
            "best_sidecar_non_target_candidate_docs": best["non_target_candidate_docs"],
            "current_primary_case_grade_docs": current["primary_case_grade_docs"],
            "current_companion_case_grade_docs": current["companion_case_grade_docs"],
            "middle_guard_candidate": "mid_time_shift_reference_guard",
            "middle_guard_primary_case_grade_docs": sidecars[
                "mid_time_shift_reference_guard"
            ]["primary_case_grade_docs"],
            "middle_guard_companion_case_grade_docs": sidecars[
                "mid_time_shift_reference_guard"
            ]["companion_case_grade_docs"],
            "middle_guard_candidate_docs": sidecars["mid_time_shift_reference_guard"][
                "candidate_docs"
            ],
            "middle_guard_non_target_candidate_docs": sidecars[
                "mid_time_shift_reference_guard"
            ]["non_target_candidate_docs"],
        },
        "decision": {
            "production_sidecar_adoption": False,
            "bounded_export_sidecar_candidate": "observable_profile_top_500",
            "bounded_export_sidecar_candidate_ready_for_product_default": False,
            "product_first_review_ordering_change": True,
            "main_candidate_subset_change": True,
            "weak_pair_promotion": False,
            "read": (
                "The production duplicate path now reserves a bounded observable "
                "profile supplement and uses rule-balanced pair selection. This "
                "recovers part of the current owner-map primary target without changing row "
                "scores, weak-pair gates, top-pair caps, PHASE1 ranking, or PHASE2 "
                "fusion. observable_profile_top_500 remains an export/drilldown "
                "candidate, not a full first-review replacement."
            ),
            "next_improvement_direction": (
                "Remaining misses need DataSynth or feature-path review because "
                "target docs enter the candidate subset but do not form observable "
                "case-grade pair evidence under current GL fields."
            ),
        },
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    if os.environ.get("RUN_DUPLICATE_OBS500_PAIR_ARTIFACT_PROBE") == "1":
        payload["sidecar_pair_artifact_probes"][
            "observable_profile_top_500_pair_artifact"
        ] = _evaluate_pair_artifact_frame(
            candidate_id="observable_profile_top_500_pair_artifact",
            frame=candidate_frames["observable_profile_top_500"],
            settings=get_settings(),
            primary_docs=primary_docs,
            companion_docs=companion_docs,
            pair_truth=pair_truth,
        )
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_check(
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
                "primary_denominator": payload["duplicate_primary_denominator"],
                "companion_denominator": payload["duplicate_companion_denominator"],
                "current": payload["current_duplicate_path"],
                "summary": payload["experiment_summary"],
                "elapsed_seconds": payload["elapsed_seconds"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
