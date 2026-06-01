"""Duplicate v3.1 feature-gap experiments for fixed5_dupmeta.

Diagnostic-only. The current duplicate primary bottleneck is before
top_pairs: v3.1 duplicate-like primary docs do not enter the large-input
candidate subset. This script keeps production ranking, thresholds, caps, and
weak-pair gate unchanged while testing oracle-free lower-score/document feature
sidecar candidates.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import _select_large_input_candidate_frame
from tools.scripts.diagnose_duplicate_candidate_sidecar_fixed5_dupmeta_20260530 import (
    SIDECAR_MAX_DOCS,
    _bounded_by_document,
    _evaluate_sidecar,
    _load_inputs,
    _sidecar_settings,
    _truth_bool_series,
)
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    raw_identifier_leak_check,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

OUT_JSON = ROOT / "artifacts" / "duplicate_v31_feature_gap_experiment_20260531.json"


def _doc_feature_frame(df: pd.DataFrame, *, exclude_index: set[Any]) -> pd.DataFrame:
    work = df.loc[~df.index.isin(exclude_index)].copy()
    if work.empty:
        return pd.DataFrame(index=pd.Index([], name="document_id"))
    amount = (
        pd.to_numeric(work.get("debit_amount", 0), errors="coerce").fillna(0.0).abs()
        + pd.to_numeric(work.get("credit_amount", 0), errors="coerce").fillna(0.0).abs()
    )
    work["_abs_amount"] = amount
    work["_has_reference"] = work.get("reference", "").fillna("").astype(str).str.len() > 0
    work["_has_partner"] = (
        work.get("trading_partner", "").fillna("").astype(str).str.len() > 0
    )
    process = work.get("business_process", "").fillna("").astype(str)
    grouped = work.groupby("document_id", sort=False).agg(
        row_count=("_abs_amount", "size"),
        max_amount=("_abs_amount", "max"),
        total_amount=("_abs_amount", "sum"),
        has_reference=("_has_reference", "max"),
        has_partner=("_has_partner", "max"),
    )
    grouped["is_p2p"] = process.groupby(work["document_id"]).agg(
        lambda values: bool((values == "P2P").any())
    )
    grouped["doc_score"] = (
        grouped["max_amount"].rank(method="first", pct=True)
        + grouped["total_amount"].rank(method="first", pct=True)
        + grouped["has_reference"].astype(float)
        + grouped["has_partner"].astype(float)
        + grouped["is_p2p"].astype(float)
        + grouped["row_count"].between(2, 3).astype(float)
    )
    return grouped.sort_values(
        ["doc_score", "max_amount", "total_amount"],
        ascending=[False, False, False],
    )


def _l2_03d_lower_score_floor_band_sample(
    df: pd.DataFrame,
    details: pd.DataFrame,
    scores: pd.Series,
    *,
    main_candidate_index: set[Any],
    selected_floor: float,
) -> pd.DataFrame:
    """Observable lower-score duplicate row sample.

    Uses only current duplicate row scores/details. The score band is
    diagnostic-only and is not a production threshold.
    """
    mask = (
        (details["L2-03d"] > 0)
        & (scores < selected_floor)
        & (scores >= 0.40)
        & ~details.index.isin(main_candidate_index)
    )
    pool = pd.DataFrame(
        {
            "score": scores.reindex(details.index).fillna(0.0),
            "rule_score": details["L2-03d"].reindex(details.index).fillna(0.0),
            "pos": range(len(details)),
        },
        index=details.index,
    )[mask]
    if pool.empty:
        return df.iloc[[]]
    ordered = pool.sort_values(["rule_score", "score", "pos"], ascending=[False, False, True])
    return _bounded_by_document(df, ordered.index)


def _observable_document_profile_sample(
    df: pd.DataFrame,
    *,
    main_candidate_index: set[Any],
) -> pd.DataFrame:
    """Document-level sample based on non-oracle duplicate-like audit features."""
    features = _doc_feature_frame(df, exclude_index=main_candidate_index)
    if features.empty:
        return df.iloc[[]]
    keep = features[
        features["is_p2p"]
        & features["has_reference"]
        & features["has_partner"]
        & features["row_count"].between(2, 3)
    ].head(SIDECAR_MAX_DOCS)
    if keep.empty:
        return df.iloc[[]]
    return _bounded_by_document(df, df[df["document_id"].isin(keep.index)].index)


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

    main_candidate_df, main_coverage = _select_large_input_candidate_frame(
        df,
        max_rows=int(settings.duplicate_pair_artifact_max_rows),
        candidate_scores=result.scores,
        candidate_details=result.details,
    )
    main_candidate_index = set() if main_candidate_df is None else set(main_candidate_df.index)
    selected_floor = (
        float(scores.loc[list(main_candidate_index)].min()) if main_candidate_index else 0.0
    )
    row_score_docs = set(df.loc[scores > 0, "document_id"].astype(str)) & primary_docs
    main_candidate_docs = (
        set()
        if main_candidate_df is None
        else set(main_candidate_df["document_id"].astype(str))
    )
    sidecar_settings = _sidecar_settings(settings)

    sidecar_frames = {
        "l2_03d_lower_score_floor_band_sample": _l2_03d_lower_score_floor_band_sample(
            df,
            details,
            scores,
            main_candidate_index=main_candidate_index,
            selected_floor=selected_floor,
        ),
        "observable_document_profile_sample": _observable_document_profile_sample(
            df,
            main_candidate_index=main_candidate_index,
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

    lower = sidecars["l2_03d_lower_score_floor_band_sample"]
    profile = sidecars["observable_document_profile_sample"]
    non_oracle_best = max(
        sidecars.values(),
        key=lambda item: (
            item["case_grade_pair_primary_docs"],
            item["generated_pair_evidence_primary_docs"],
            -item["expected_review_burden"]["nonprimary_candidate_docs"],
        ),
    )
    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": "datasynth_manipulation_v7_candidate_fixed5_dupmeta",
        "diagnostic_only": True,
        "production_first_review_ranking_changed": False,
        "row_score_threshold_changed": False,
        "row_scores_changed": False,
        "top_pairs_cap_changed": False,
        "weak_pair_gate_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_metadata_used_as_selector": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "baseline_attrition": {
            "primary_docs": len(primary_docs),
            "row_score_primary_docs": len(row_score_docs),
            "no_row_score_primary_docs": len(primary_docs - row_score_docs),
            "candidate_subset_primary_docs": len(main_candidate_docs & primary_docs),
            "candidate_subset_selected_rows": int(main_coverage.get("selected_candidate_rows", 0)),
            "candidate_subset_min_score": selected_floor,
        },
        "candidate_experiments": sidecars,
        "experiment_summary": {
            "l2_03d_lower_score_floor_band_primary_docs": lower[
                "generated_pair_evidence_primary_docs"
            ],
            "l2_03d_lower_score_floor_band_case_grade_primary_docs": lower[
                "case_grade_pair_primary_docs"
            ],
            "observable_document_profile_primary_docs": profile[
                "generated_pair_evidence_primary_docs"
            ],
            "observable_document_profile_case_grade_primary_docs": profile[
                "case_grade_pair_primary_docs"
            ],
            "best_non_oracle_candidate": non_oracle_best["sidecar_id"],
            "best_non_oracle_primary_docs": non_oracle_best[
                "generated_pair_evidence_primary_docs"
            ],
            "best_non_oracle_case_grade_primary_docs": non_oracle_best[
                "case_grade_pair_primary_docs"
            ],
        },
        "decision": {
            "main_candidate_subset_change": False,
            "production_sidecar_adoption": False,
            "weak_pair_promotion": False,
            "next_improvement_direction": (
                "Lower-score floor-band still fails, but observable document-profile "
                "sampling recovers primary pair evidence with high review burden. "
                "Next, reduce nonprimary burden with audit-stable guards before "
                "considering any export sidecar."
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
                "baseline": payload["baseline_attrition"],
                "summary": payload["experiment_summary"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
