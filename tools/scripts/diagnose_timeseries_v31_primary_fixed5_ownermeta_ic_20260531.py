"""Diagnose TS v3.1 primary target placement on fixed5 ownermeta_ic.

Diagnostic-only. Owner denominator comes from DataSynth family metadata, while
candidate ordering does not use truth labels, scenario labels, PHASE1 rank, raw
identifiers, or matched results.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts.diagnose_timeseries_primary_surface_crossbatch_20260530 import (
    _build_row_score_windows,
    _candidate_policies,
    _current_native_windows,
)
from tools.scripts.diagnose_timeseries_ranking_candidates_fixed5_20260529 import (
    _raw_identifier_leak_report,
)
from tools.scripts.diagnose_timeseries_ranking_crossbatch_20260529 import (
    _load_case_input,
    _phase1_reference_sets,
)
from tools.scripts.diagnose_timeseries_top100_failure_fixed5_20260530 import (
    CASE_INPUT,
    PHASE1_RESULT,
    _selected_docs,
)
from tools.scripts.diagnose_timeseries_top100_rankband_gap_fixed5_20260530 import (
    _ts_specific_top100_stabilized_surface,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID as FIXED5_BATCH_ID,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import _run_rule_detector

TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic"
    / "labels"
    / "manipulated_entry_truth.csv"
)
V31_RESPONSIBILITY = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530.json"
)
OUT_JSON = ROOT / "artifacts" / "timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_truth() -> pd.DataFrame:
    if not TRUTH_CSV.exists():
        raise FileNotFoundError(f"missing truth metadata: {TRUTH_CSV}")
    return pd.read_csv(TRUTH_CSV, dtype=str).fillna("")


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.lower().eq("true")


def _ordered_summary(
    ordered: list[dict[str, Any]],
    *,
    ts_primary_docs: set[str],
) -> dict[str, Any]:
    top100 = _selected_docs(ordered[:100]) & ts_primary_docs
    top500 = _selected_docs(ordered[:500]) & ts_primary_docs
    top1000 = _selected_docs(ordered[:1000]) & ts_primary_docs
    first_ranks = _first_ranks(ordered, ts_primary_docs)
    return {
        "top100_matched_docs": len(top100),
        "top500_matched_docs": len(top500),
        "top1000_matched_docs": len(top1000),
        "top100_recall": _ratio(len(top100), len(ts_primary_docs)),
        "top500_recall": _ratio(len(top500), len(ts_primary_docs)),
        "top1000_recall": _ratio(len(top1000), len(ts_primary_docs)),
        "first_rank_distribution": _rank_distribution(first_ranks),
        "missing_from_top500_docs": len(ts_primary_docs - top500),
        "top500_review_burden": _review_burden(ordered[:500]),
    }


def _first_ranks(ordered: list[dict[str, Any]], target_docs: set[str]) -> list[int]:
    first: dict[str, int] = {}
    for rank, window in enumerate(ordered, start=1):
        for doc in set(window.get("_docs", set())) & target_docs:
            first.setdefault(doc, rank)
    return list(first.values())


def _rank_distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {
            "covered_docs": 0,
            "min": None,
            "p50": None,
            "p90": None,
            "max": None,
        }
    series = pd.Series(values, dtype="float64")
    return {
        "covered_docs": int(len(series)),
        "min": int(series.min()),
        "p50": int(series.quantile(0.5)),
        "p90": int(series.quantile(0.9)),
        "max": int(series.max()),
    }


def _review_burden(windows: list[dict[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {"window_count": 0, "low_support_ratio": 0.0, "period_end_ratio": 0.0}
    return {
        "window_count": len(windows),
        "low_support_ratio": round(
            sum(1 for item in windows if int(item.get("row_count") or 0) < 7) / len(windows),
            6,
        ),
        "period_end_ratio": round(
            sum(1 for item in windows if bool(item.get("period_end_context"))) / len(windows),
            6,
        ),
        "after_hours_or_weekend_ratio": round(
            sum(1 for item in windows if bool(item.get("after_hours_or_weekend_context")))
            / len(windows),
            6,
        ),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else round(numerator / denominator, 6)


def _phase1_action_coverage(ts_primary_docs: set[str]) -> dict[str, int]:
    phase1_sets = _phase1_reference_sets(PHASE1_RESULT)
    candidate_or_higher = set(phase1_sets.get("candidate_or_higher", set()))
    if not candidate_or_higher and V31_RESPONSIBILITY.exists():
        payload = json.loads(V31_RESPONSIBILITY.read_text(encoding="utf-8"))
        action = payload["phase1_action_tier_comparison_v31"]["timeseries"]
        return {
            "phase1_immediate_high_covered_primary_docs": int(
                action["phase1_immediate_high_covered_primary_docs"]
            ),
            "phase1_review_or_higher_covered_primary_docs": int(
                action["phase1_review_or_higher_covered_primary_docs"]
            ),
            "phase1_candidate_or_higher_covered_primary_docs": int(
                action["phase1_candidate_or_higher_covered_primary_docs"]
            ),
        }
    return {
        "phase1_immediate_high_covered_primary_docs": len(
            ts_primary_docs & set(phase1_sets["top100_docs"])
        ),
        "phase1_review_or_higher_covered_primary_docs": len(
            ts_primary_docs & set(phase1_sets["top500_docs"])
        ),
        "phase1_candidate_or_higher_covered_primary_docs": len(
            ts_primary_docs & candidate_or_higher
        ),
    }


def _v31_timeseries_check(ts_primary_docs: set[str]) -> dict[str, Any]:
    if not V31_RESPONSIBILITY.exists():
        return {"available": False}
    payload = json.loads(V31_RESPONSIBILITY.read_text(encoding="utf-8"))
    primary = payload["primary_denominators_v31"]["timeseries"]
    recall = payload["primary_owner_target_recall_v31"]["timeseries"]
    return {
        "available": True,
        "v31_primary_denominator": primary,
        "v31_native_top500_matched_docs": recall["native_top500_matched_docs"],
        "matches_truth_metadata_count": primary == len(ts_primary_docs),
    }


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input(CASE_INPUT)
    truth = _load_truth()
    truth_docs = set(truth["document_id"].astype(str))
    ts_primary_docs = set(
        truth.loc[_bool_series(truth, "injected_timing_primary"), "document_id"].astype(str)
    )
    period_end_context_docs = set(
        truth.loc[truth["timing_role"].astype(str).eq("context"), "document_id"].astype(str)
    )

    ts_result = _run_rule_detector("timeseries", df)
    windows = _build_row_score_windows(df=df, detection_result=ts_result, truth_docs=truth_docs)
    policies = _candidate_policies(windows)
    current_native = _current_native_windows(
        df=df,
        detection_result=ts_result,
        batch_id=FIXED5_BATCH_ID,
        truth_docs=truth_docs,
    )
    candidate_surfaces = {
        "current_native_ts_order": current_native,
        "ts_primary_conservative_surface": policies["ts_primary_conservative_surface"],
        "ts_specific_top100_stabilized_surface": _ts_specific_top100_stabilized_surface(windows),
    }
    surface_summary = {
        name: _ordered_summary(ordered, ts_primary_docs=ts_primary_docs)
        for name, ordered in candidate_surfaces.items()
    }
    best = "ts_specific_top100_stabilized_surface"
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": "fixed5_ownermeta_ic",
        "source_candidate": "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic",
        "guardrails": {
            "diagnostic_only": True,
            "truth_label_used_for_selector": False,
            "scenario_label_used_for_selector": False,
            "phase1_rank_used_for_selector": False,
            "matched_result_used_for_selector": False,
            "raw_identifier_used_for_selector": False,
            "owner_metadata_used_for_denominator_only": True,
            "production_gate_ranking_fusion_changed": False,
            "production_default_ordering_changed": False,
            "phase1_ranking_changed": False,
            "fixed4_used": False,
            "broad_companion_used_as_ts_primary": False,
        },
        "v31_primary_target": {
            "timeseries_primary_docs": len(ts_primary_docs),
            "period_end_context_docs": len(period_end_context_docs),
            "truth_docs_total": len(truth_docs),
            "v31_responsibility_consistency": _v31_timeseries_check(ts_primary_docs),
            "phase1_action_coverage": _phase1_action_coverage(ts_primary_docs),
        },
        "candidate_surfaces": surface_summary,
        "selector_input_policy": {
            "candidate_surface": best,
            "truth_label_used": False,
            "scenario_label_used": False,
            "owner_metadata_used": False,
            "phase1_rank_used": False,
            "matched_result_used": False,
            "raw_identifier_used": False,
            "allowed_feature_groups": [
                "period_end_context",
                "row_ref_support_count",
                "round_amount_context",
                "after_hours_or_weekend_context",
                "context_evidence_count",
                "period_end_lift",
                "robust_z",
                "subject_activity_rank",
            ],
        },
        "adoption_readiness": {
            "status": "diagnostic_candidate_not_product_default",
            "product_default_ordering_strategy": "native",
            "candidate_ordering_strategy": best,
            "explicit_flag_required": True,
            "product_default_adoption_allowed": False,
            "period_end_context_primary_denominator": False,
            "fixed4_used_for_product_judgment": False,
            "required_validation_before_default": {
                "regenerated_owner_metadata_datasynth": {
                    "required": True,
                    "minimum_primary_docs": len(ts_primary_docs),
                    "required_top100_primary_capture": len(ts_primary_docs),
                    "required_top500_primary_capture": len(ts_primary_docs),
                    "period_end_context_denominator_allowed": False,
                },
                "fixed5_compatible_slice_validation": {
                    "required": True,
                    "each_slice_top500_capture_must_equal_primary_docs": True,
                    "top100_slice_regression_requires_review": True,
                    "must_not_use_fixed4": True,
                },
                "selector_contract": {
                    "truth_label_allowed": False,
                    "scenario_label_allowed": False,
                    "owner_metadata_allowed": False,
                    "phase1_rank_allowed": False,
                    "matched_result_allowed": False,
                    "raw_identifier_allowed": False,
                },
            },
            "blockers": [
                "single fixed5 owner-metadata candidate validation only",
                (
                    "requires regenerated owner-metadata DataSynth or fixed5-compatible "
                    "slice validation before default adoption"
                ),
                "must keep period-end context docs out of TS primary denominator",
            ],
            "next_adoption_gate": (
                "promote only if stabilized timing/window features keep 21/21 primary capture "
                "without broad companion or period-end-context denominator inflation"
            ),
        },
        "decision": {
            "best_candidate": best,
            "best_candidate_top100_matched_docs": surface_summary[best]["top100_matched_docs"],
            "best_candidate_top500_matched_docs": surface_summary[best]["top500_matched_docs"],
            "current_native_top500_matched_docs": surface_summary["current_native_ts_order"][
                "top500_matched_docs"
            ],
            "primary_improvement_available": (
                surface_summary[best]["top100_matched_docs"]
                > surface_summary["current_native_ts_order"]["top100_matched_docs"]
            ),
            "top500_full_capture_available": (
                surface_summary[best]["top500_matched_docs"] == len(ts_primary_docs)
            ),
            "production_adoption": False,
            "production_default_ordering": "native",
            "next_action": (
                "validate stabilized surface with regenerated owner-metadata DataSynth or "
                "implement behind explicit diagnostic flag before product adoption"
            ),
        },
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
