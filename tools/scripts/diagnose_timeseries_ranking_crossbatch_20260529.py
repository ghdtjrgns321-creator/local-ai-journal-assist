"""Cross-batch diagnostic-only TS ranking candidate comparison.

This script reuses the fixed5 diagnostic candidate functions across fixed3,
fixed4, and fixed5 synthetic batches. It does not change product ordering,
thresholds, native case gates, PHASE1 ranking, or PHASE2 fusion. Truth labels are
used only after candidate ordering for aggregate evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import TimeseriesCase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.diagnose_timeseries_ranking_candidates_fixed5_20260529 import (
    _CANDIDATE_DESCRIPTIONS,
    _candidate_order,
    _candidate_summary,
    _case_feature_payload,
    _raw_identifier_leak_report,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID as FIXED5_BATCH_ID,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    TOP_NS,
    _run_rule_detector,
)

OUT_JSON = ROOT / "artifacts" / "timeseries_ranking_crossbatch_20260529.json"

_KEY_CANDIDATES = (
    "current_native_ts_ordering",
    "robust_context_baseline_sufficiency",
    "review_burden_penalized_context",
    "review_burden_closing_demoted_context",
    "mixed_signal_period_end_demoted",
    "non_period_end_surprise_priority",
)

_RETENTION_POLICY_PROVENANCE = {
    "label": "cross-batch exploratory diagnostic retention policies",
    "calibration_status": "not calibrated",
    "production_policy": "not production artifact retention policy",
    "adoption_requirement": "requires additional fixture/DataSynth validation before adoption",
}

_RETENTION_POLICY_DESCRIPTIONS = {
    "current_original_order_cap500": (
        "Current detector artifact retention: first 500 grouped windows in source order."
    ),
    "score_desc_cap500": (
        "Diagnostic retention: highest TS window score first, then original grouped order."
    ),
    "period_end_score_cap500": (
        "Diagnostic retention: period-end context first, then highest score and original order."
    ),
    "period_end_score_low_support_demoted_cap500": (
        "Diagnostic retention: period-end context first, one-row support windows demoted, "
        "then highest score and original order."
    ),
}


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    truth_csv: Path
    batch_id: str
    phase1_case_result: Path | None = None


BATCHES = (
    BatchSpec(
        name="fixed3",
        dataset="datasynth_manipulation_v7_candidate_fixed3",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed3"
        / "labels"
        / "manipulated_entry_truth.csv",
        batch_id="fixed3_timeseries_crossbatch_20260529",
    ),
    BatchSpec(
        name="fixed4",
        dataset="datasynth_manipulation_v7_candidate_fixed4",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed4"
        / "labels"
        / "manipulated_entry_truth.csv",
        batch_id="fixed4_timeseries_crossbatch_20260529",
        phase1_case_result=ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl",
    ),
    BatchSpec(
        name="fixed5_normalcal5",
        dataset="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
        / "labels"
        / "manipulated_entry_truth.csv",
        batch_id=FIXED5_BATCH_ID,
        phase1_case_result=ROOT
        / "artifacts"
        / "stage7_fixed5_normalcal5_phase1_case_result.pkl",
    ),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _load_case_input(path: Path) -> pd.DataFrame:
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    if "document_id" in df.columns:
        df["document_id"] = df["document_id"].astype(str)
    return df


def _load_truth(path: Path) -> pd.DataFrame:
    truth = pd.read_csv(path)
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _truth_scenario_by_doc(truth: pd.DataFrame) -> dict[str, str]:
    scenario_col = None
    for column in ("manipulation_scenario", "scenario", "scenario_name"):
        if column in truth.columns:
            scenario_col = column
            break
    if scenario_col is None:
        return {}
    return dict(zip(truth["document_id"].astype(str), truth[scenario_col].astype(str)))


def _phase1_reference_sets(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "available": False,
            "reason": "phase1_case_result_not_configured",
            "top100_docs": set(),
            "top500_docs": set(),
        }
    if not path.exists():
        return {
            "available": False,
            "reason": "phase1_case_result_missing",
            "top100_docs": set(),
            "top500_docs": set(),
        }
    with path.open("rb") as fh:
        phase1_result = pickle.load(fh)
    cases = list(getattr(phase1_result, "cases", []) or [])
    return {
        "available": True,
        "reason": None,
        "top100_docs": _phase1_case_docs(cases[:100]),
        "top500_docs": _phase1_case_docs(cases[:500]),
    }


def _phase1_case_docs(cases: list[Any]) -> set[str]:
    docs: set[str] = set()
    for case in cases:
        for doc_ref in getattr(case, "documents", []) or []:
            doc_id = getattr(doc_ref, "document_id", None)
            if doc_id not in (None, ""):
                docs.add(str(doc_id))
    return docs


def _run_batch(spec: BatchSpec) -> dict[str, Any]:
    started = time.perf_counter()
    _print(f"loading {spec.name}")
    df = _load_case_input(spec.case_input)
    truth = _load_truth(spec.truth_csv)
    truth_docs = set(truth["document_id"].astype(str))
    phase1_reference = _phase1_reference_sets(spec.phase1_case_result)

    ts_result = _run_rule_detector("timeseries", df)
    case_set = build_phase2_case_set(
        batch_id=spec.batch_id,
        detection_results=[ts_result],
        df=df,
    )
    cases = [case for case in case_set.timeseries_cases if isinstance(case, TimeseriesCase)]
    current_order = _candidate_order(cases, "current_native_ts_ordering")
    candidates = {
        candidate: _candidate_summary(
            candidate=candidate,
            cases=cases,
            current_order=current_order,
            truth_docs=truth_docs,
        )
        for candidate in _KEY_CANDIDATES
    }
    payload = {
        "dataset": spec.dataset,
        "case_count": len(cases),
        "truth_document_count": len(truth_docs),
        "row_count": len(df),
        "document_count": int(df["document_id"].nunique()) if "document_id" in df else None,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "feature_diagnostics": {
            "all_cases": _case_feature_payload(cases),
            "current_top500": _case_feature_payload(current_order[:500]),
        },
        "truth_coverage_flow": _truth_coverage_flow(
            detection_result=ts_result,
            cases=cases,
            df=df,
            truth_docs=truth_docs,
        ),
        "row_score_window_surface_diagnostic": _row_score_window_surface_diagnostic(
            detection_result=ts_result,
            df=df,
            truth_docs=truth_docs,
            scenario_by_doc=_truth_scenario_by_doc(truth),
            phase1_reference=phase1_reference,
        ),
        "candidates": candidates,
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    return payload


def _truth_coverage_flow(
    *,
    detection_result: Any,
    cases: list[TimeseriesCase],
    df: pd.DataFrame,
    truth_docs: set[str],
) -> dict[str, Any]:
    flagged_docs = _docs_for_positions(
        df,
        [
            int(pos)
            for pos in getattr(detection_result, "flagged_indices", [])
            if _is_valid_position(pos, df_len=len(df))
        ],
    )
    artifact = getattr(detection_result, "metadata", {}).get("timeseries_window_artifact", {})
    windows = artifact.get("windows", []) if isinstance(artifact, dict) else []
    artifact_positions: list[int] = []
    case_grade_positions: list[int] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        positions = _coerce_positions(window.get("row_positions") or [], df_len=len(df))
        artifact_positions.extend(positions)
        if str(window.get("evidence_tier")) in {"strong", "moderate"} and bool(
            window.get("sub_signal_high")
        ):
            case_grade_positions.extend(positions)

    artifact_docs = _docs_for_positions(df, artifact_positions)
    case_grade_docs = _docs_for_positions(df, case_grade_positions)
    native_case_docs = set().union(*[_case_docs_no_raw(case) for case in cases]) if cases else set()
    return {
        "flagged_truth_document_count": len(flagged_docs & truth_docs),
        "artifact_window_truth_document_count": len(artifact_docs & truth_docs),
        "case_grade_window_truth_document_count": len(case_grade_docs & truth_docs),
        "native_case_truth_document_count": len(native_case_docs & truth_docs),
        "flagged_document_count": len(flagged_docs),
        "artifact_window_document_count": len(artifact_docs),
        "case_grade_window_document_count": len(case_grade_docs),
        "native_case_document_count": len(native_case_docs),
        "ranking_can_improve": bool(native_case_docs & truth_docs),
        "primary_gap": (
            "ranking_gap" if native_case_docs & truth_docs else "artifact_truth_coverage_gap"
        ),
        "artifact_retention_diagnostic": _artifact_retention_diagnostic(
            detection_result=detection_result,
            df=df,
            truth_docs=truth_docs,
        ),
    }


def _artifact_retention_diagnostic(
    *,
    detection_result: Any,
    df: pd.DataFrame,
    truth_docs: set[str],
) -> dict[str, Any]:
    """Reconstruct aggregate candidate window retention without emitting identifiers."""
    if "posting_date" not in df.columns or "document_id" not in df.columns:
        return {"available": False, "reason": "missing_required_columns"}
    subject_col = "gl_account" if "gl_account" in df.columns else "business_process"
    if subject_col not in df.columns:
        return {"available": False, "reason": "missing_subject_column"}

    details = getattr(detection_result, "details", None)
    if not isinstance(details, pd.DataFrame) or details.empty:
        return {"available": False, "reason": "missing_detection_details"}

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce").dt.normalize()
    out: dict[str, Any] = {"available": True, "by_rule": {}}
    for rule in ("TS01", "TS02"):
        if rule not in details.columns:
            out["by_rule"][rule] = {"available": False, "reason": "missing_rule_detail"}
            continue
        candidates = pd.DataFrame(
            {
                "subject": df[subject_col].astype(str),
                "posting_date_norm": posting_date,
                "score": details[rule].reindex(df.index).fillna(0.0).astype(float),
                "document_id": df["document_id"].astype(str),
            },
            index=df.index,
        )
        candidates = candidates[candidates["score"] > 0.0].dropna(
            subset=["subject", "posting_date_norm"]
        )
        windows = _candidate_window_rows(candidates, truth_docs=truth_docs)
        out["by_rule"][rule] = _candidate_window_retention_summary(windows)
    return out


def _row_score_window_surface_diagnostic(
    *,
    detection_result: Any,
    df: pd.DataFrame,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    """Diagnostic native-like windows from final TS row_score, not TS01/TS02 flags."""
    if "posting_date" not in df.columns or "document_id" not in df.columns:
        return {"available": False, "reason": "missing_required_columns"}
    subject_col = "gl_account" if "gl_account" in df.columns else "business_process"
    if subject_col not in df.columns:
        return {"available": False, "reason": "missing_subject_column"}

    posting_date = pd.to_datetime(df["posting_date"], errors="coerce").dt.normalize()
    scores = getattr(detection_result, "scores", pd.Series(dtype=float))
    scores = scores.reindex(df.index).fillna(0.0).astype(float)
    out: dict[str, Any] = {
        "diagnostic_only": True,
        "production_case_generation_changed": False,
        "truth_label_used_for_surface_order": False,
        "truth_label_used_only_for_incremental_evaluation": True,
        "phase1_reference_available": bool(phase1_reference["available"]),
        "phase1_reference_reason": phase1_reference.get("reason"),
        "surfaces": {},
    }
    for threshold in (0.5, 0.8):
        candidates = pd.DataFrame(
            {
                "subject": df[subject_col].astype(str),
                "posting_date_norm": posting_date,
                "score": scores,
                "document_id": df["document_id"].astype(str),
                **_row_score_context_columns(df),
            },
            index=df.index,
        )
        candidates = candidates[candidates["score"] >= threshold].dropna(
            subset=["subject", "posting_date_norm"]
        )
        windows = _candidate_window_rows(candidates, truth_docs=truth_docs)
        for window, (_, grp) in zip(
            windows,
            candidates.groupby(["subject", "posting_date_norm"], sort=False),
            strict=False,
        ):
            window["_docs"] = set(grp["document_id"].astype(str))
        out["surfaces"][f"row_score_ge_{threshold:g}"] = _row_score_surface_summary(
            windows,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        )
    return out


def _row_score_surface_summary(
    windows: list[dict[str, Any]],
    *,
    truth_docs: set[str] | None = None,
    scenario_by_doc: dict[str, str] | None = None,
    phase1_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    truth_docs = truth_docs or set()
    scenario_by_doc = scenario_by_doc or {}
    phase1_reference = phase1_reference or _phase1_reference_sets(None)
    hybrid_order = sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["row_count"]) < 3,
            int(item["row_count"]) < 10,
            -int(
                bool(item["suspense_context"])
                + bool(item["manual_context"])
                + bool(item["after_hours_or_weekend_context"])
            ),
            -float(item["amount_zscore"]),
            -float(item["score"]),
            int(item["ordinal"]),
        ),
    )
    context_order = sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["row_count"]) < 3,
            int(item["row_count"]) < 10,
            -int(item["context_count"]),
            -float(item["score"]),
            int(item["ordinal"]),
        ),
    )
    policies = {
        "score_desc": _retention_policy_order(windows, "score_desc_cap500"),
        "period_end_score_low_support_demoted": _retention_policy_order(
            windows,
            "period_end_score_low_support_demoted_cap500",
        ),
        "period_end_mean_score": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                -float(item["mean_score"]),
                int(item["row_count"]) <= 1,
                int(item["ordinal"]),
            ),
        ),
        "period_end_support_bucket_score": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 3,
                int(item["row_count"]) < 10,
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        ),
        "period_end_support_amount": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 3,
                int(item["row_count"]) < 10,
                -float(item["amount_log"]),
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        ),
        "period_end_support_amount_zscore": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 3,
                int(item["row_count"]) < 10,
                -float(item["amount_zscore"]),
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        ),
        "period_end_support_context_count": context_order,
        "period_end_support_hybrid": hybrid_order,
        "hybrid_period_end_80pct_cap": _cap_prefix_order(
            hybrid_order,
            prefix_size=500,
            max_period_end_share=0.80,
        ),
        "hybrid_subject_cap10": _cap_prefix_order(
            hybrid_order,
            prefix_size=500,
            max_per_subject=10,
        ),
        "hybrid_high_amount_zscore_25pct_cap": _cap_prefix_order(
            hybrid_order,
            prefix_size=500,
            max_high_amount_zscore_share=0.25,
        ),
        "ui100_context_export500_hybrid": _split_ui_export_order(
            ui_order=context_order,
            export_order=hybrid_order,
            ui_size=100,
        ),
        "timing_primary_round_amount_demoted": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 3,
                bool(item["round_amount_context"]),
                float(item["amount_zscore"]) >= 10.0,
                float(item["amount_zscore"]) >= 3.0,
                -int(
                    bool(item["manual_context"])
                    + bool(item["after_hours_or_weekend_context"])
                ),
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        ),
        "timing_primary_support_round_amount_demoted": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 7,
                bool(item["round_amount_context"]),
                float(item["amount_zscore"]) >= 10.0,
                float(item["amount_zscore"]) >= 3.0,
                -int(
                    bool(item["manual_context"])
                    + bool(item["after_hours_or_weekend_context"])
                ),
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        ),
    }
    return {
        "window_count": len(windows),
        "truth_document_pool_count": _selected_truth_document_count(windows),
        "policies": {
            name: _surface_topn_summary(
                ordered,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                phase1_reference=phase1_reference,
            )
            for name, ordered in policies.items()
        },
    }


def _cap_prefix_order(
    ordered: list[dict[str, Any]],
    *,
    prefix_size: int,
    max_period_end_share: float | None = None,
    max_per_subject: int | None = None,
    max_high_amount_zscore_share: float | None = None,
) -> list[dict[str, Any]]:
    prefix: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    subject_counts: Counter[str] = Counter()
    max_period_end_count = (
        int(prefix_size * max_period_end_share)
        if max_period_end_share is not None
        else None
    )
    max_high_amount_count = (
        int(prefix_size * max_high_amount_zscore_share)
        if max_high_amount_zscore_share is not None
        else None
    )
    period_end_count = 0
    high_amount_count = 0

    for window in ordered:
        if len(prefix) >= prefix_size:
            deferred.append(window)
            continue
        subject = str(window.get("_subject", ""))
        is_period_end = bool(window.get("period_end_context"))
        is_high_amount = float(window.get("amount_zscore", 0.0)) >= 3.0
        violates_period_end = (
            max_period_end_count is not None
            and is_period_end
            and period_end_count >= max_period_end_count
        )
        violates_subject = (
            max_per_subject is not None and subject_counts[subject] >= max_per_subject
        )
        violates_high_amount = (
            max_high_amount_count is not None
            and is_high_amount
            and high_amount_count >= max_high_amount_count
        )
        if violates_period_end or violates_subject or violates_high_amount:
            deferred.append(window)
            continue
        prefix.append(window)
        subject_counts[subject] += 1
        period_end_count += int(is_period_end)
        high_amount_count += int(is_high_amount)

    selected_ids = {id(window) for window in prefix}
    remainder = [window for window in ordered if id(window) not in selected_ids]
    return prefix + remainder


def _split_ui_export_order(
    *,
    ui_order: list[dict[str, Any]],
    export_order: list[dict[str, Any]],
    ui_size: int,
) -> list[dict[str, Any]]:
    prefix = ui_order[:ui_size]
    selected_ids = {id(window) for window in prefix}
    return prefix + [window for window in export_order if id(window) not in selected_ids]


def _surface_topn_summary(
    windows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    topn: dict[str, Any] = {}
    for top_n in (100, 500, 1000, 2000, 5000, 10000):
        selected = windows[:top_n]
        topn[str(top_n)] = {
            "truth_document_count": _selected_truth_document_count(selected),
            "truth_window_count": sum(
                1 for window in selected if int(window["truth_doc_count"]) > 0
            ),
        }
    return {
        "topn": topn,
        "incremental_to_phase1": _phase1_incremental_summary(
            windows,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        ),
        "first_truth_window_rank": next(
            (
                rank
                for rank, window in enumerate(windows, start=1)
                if int(window["truth_doc_count"]) > 0
            ),
            None,
        ),
        "top500_review_burden_proxy": _retention_review_burden_proxy(windows[:500]),
        "top500_context_pressure": _context_pressure_summary(windows[:500]),
        "year_slice_summary": _surface_year_slice_summary(windows),
    }


_TS_ALIGNED_SCENARIOS = frozenset(
    {
        "period_end_adjustment_manipulation",
        "unusual_timing_manipulation",
    }
)


def _phase1_incremental_summary(
    windows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    if not bool(phase1_reference["available"]):
        return {"available": False, "reason": phase1_reference.get("reason")}
    top100_ref = phase1_reference["top100_docs"]
    top500_ref = phase1_reference["top500_docs"]
    out: dict[str, Any] = {
        "available": True,
        "phase1_top100_truth_document_count": len(top100_ref & truth_docs),
        "phase1_top500_truth_document_count": len(top500_ref & truth_docs),
        "ts_aligned_scenarios": sorted(_TS_ALIGNED_SCENARIOS),
        "topn": {},
    }
    for top_n in (100, 500, 1000):
        selected_docs = _selected_candidate_docs(windows[:top_n])
        selected_truth = selected_docs & truth_docs
        not_phase1_top100 = selected_truth - top100_ref
        not_phase1_top500 = selected_truth - top500_ref
        aligned_not_phase1_top100 = {
            doc
            for doc in not_phase1_top100
            if scenario_by_doc.get(doc) in _TS_ALIGNED_SCENARIOS
        }
        aligned_not_phase1_top500 = {
            doc
            for doc in not_phase1_top500
            if scenario_by_doc.get(doc) in _TS_ALIGNED_SCENARIOS
        }
        out["topn"][str(top_n)] = {
            "selected_truth_document_count": len(selected_truth),
            "not_in_phase1_top100_truth_document_count": len(not_phase1_top100),
            "not_in_phase1_top500_truth_document_count": len(not_phase1_top500),
            "ts_aligned_not_in_phase1_top100_truth_document_count": len(
                aligned_not_phase1_top100
            ),
            "ts_aligned_not_in_phase1_top500_truth_document_count": len(
                aligned_not_phase1_top500
            ),
            "not_in_phase1_top100_scenario_counts": _scenario_counts(
                not_phase1_top100,
                scenario_by_doc,
            ),
            "ts_aligned_not_in_phase1_top100_scenario_counts": _scenario_counts(
                aligned_not_phase1_top100,
                scenario_by_doc,
            ),
        }
    return out


def _selected_candidate_docs(windows: list[dict[str, Any]]) -> set[str]:
    docs: set[str] = set()
    for window in windows:
        raw_docs = window.get("_docs")
        if isinstance(raw_docs, set):
            docs.update(str(doc) for doc in raw_docs)
    return docs


def _scenario_counts(docs: set[str], scenario_by_doc: dict[str, str]) -> dict[str, int]:
    counts = Counter(scenario_by_doc.get(doc, "unknown") for doc in docs)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _context_pressure_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {
            "manual_context_share": 0.0,
            "after_hours_or_weekend_context_share": 0.0,
            "round_amount_context_share": 0.0,
            "suspense_context_share": 0.0,
            "risk_keyword_context_share": 0.0,
            "high_amount_zscore_share": 0.0,
            "amount_zscore_distribution": _num_dist([]),
            "row_count_distribution": _num_dist([]),
        }
    total = len(windows)
    return {
        "manual_context_share": _bool_share(windows, "manual_context"),
        "after_hours_or_weekend_context_share": _bool_share(
            windows,
            "after_hours_or_weekend_context",
        ),
        "round_amount_context_share": _bool_share(windows, "round_amount_context"),
        "suspense_context_share": _bool_share(windows, "suspense_context"),
        "risk_keyword_context_share": _bool_share(windows, "risk_keyword_context"),
        "high_amount_zscore_share": sum(
            1 for window in windows if float(window.get("amount_zscore", 0.0)) >= 3.0
        )
        / total,
        "amount_zscore_distribution": _num_dist(
            [window.get("amount_zscore", 0.0) for window in windows]
        ),
        "row_count_distribution": _num_dist([window.get("row_count", 0) for window in windows]),
    }


def _bool_share(windows: list[dict[str, Any]], field: str) -> float:
    if not windows:
        return 0.0
    return sum(1 for window in windows if bool(window.get(field))) / len(windows)


def _surface_year_slice_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    years = sorted(
        {
            int(pd.Timestamp(window["day"]).year)
            for window in windows
            if not pd.isna(pd.Timestamp(window["day"]))
        }
    )
    out: dict[str, Any] = {}
    for year in years:
        year_windows = [
            window for window in windows if int(pd.Timestamp(window["day"]).year) == year
        ]
        top100 = year_windows[:100]
        top500 = year_windows[:500]
        out[str(year)] = {
            "window_count": len(year_windows),
            "top100_truth_document_count": _selected_truth_document_count(top100),
            "top500_truth_document_count": _selected_truth_document_count(top500),
            "top100_review_burden_proxy": _retention_review_burden_proxy(top100),
            "top500_review_burden_proxy": _retention_review_burden_proxy(top500),
            "top500_context_pressure": _context_pressure_summary(top500),
        }
    return out


def _candidate_window_rows(
    candidates: pd.DataFrame,
    *,
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for ordinal, ((subject, day), grp) in enumerate(
        candidates.groupby(["subject", "posting_date_norm"], sort=False),
        start=1,
    ):
        docs = set(grp["document_id"].astype(str))
        windows.append(
            {
                "ordinal": ordinal,
                "score": float(grp["score"].max()),
                "mean_score": float(grp["score"].mean()),
                "amount_zscore": _group_max(grp, "amount_zscore"),
                "amount_log": _group_max(grp, "amount_log"),
                "manual_context": _group_bool(grp, "manual_context"),
                "after_hours_or_weekend_context": _group_bool(
                    grp,
                    "after_hours_or_weekend_context",
                ),
                "round_amount_context": _group_bool(grp, "round_amount_context"),
                "suspense_context": _group_bool(grp, "suspense_context"),
                "risk_keyword_context": _group_bool(grp, "risk_keyword_context"),
                "day": pd.Timestamp(day),
                "row_count": int(len(grp)),
                "truth_doc_count": len(docs & truth_docs),
                "_truth_docs": docs & truth_docs,
                "_subject": str(subject),
                "period_end_context": _is_period_end_day(pd.Timestamp(day)),
            }
        )
        windows[-1]["context_count"] = _window_context_count(windows[-1])
    return windows


def _row_score_context_columns(df: pd.DataFrame) -> dict[str, pd.Series]:
    amount_source = pd.Series(0.0, index=df.index)
    for column in ("local_amount", "debit_amount", "credit_amount"):
        if column in df.columns:
            amount_source = pd.concat(
                [
                    amount_source.abs(),
                    pd.to_numeric(df[column], errors="coerce").fillna(0.0).abs(),
                ],
                axis=1,
            ).max(axis=1)

    if "amount_zscore" in df.columns:
        amount_zscore = pd.to_numeric(df["amount_zscore"], errors="coerce").fillna(0.0).abs()
    else:
        amount_zscore = pd.Series(0.0, index=df.index)

    return {
        "amount_zscore": amount_zscore,
        "amount_log": np.log1p(amount_source),
        "manual_context": _bool_series(df, "is_manual_je"),
        "after_hours_or_weekend_context": _bool_series(df, "is_after_hours")
        | _bool_series(df, "is_weekend"),
        "round_amount_context": _bool_series(df, "is_round_number"),
        "suspense_context": _bool_series(df, "is_suspense_account"),
        "risk_keyword_context": _bool_series(df, "has_risk_keyword"),
    }


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    raw = df[column]
    if pd.api.types.is_bool_dtype(raw):
        return raw.fillna(False).astype(bool)
    normalized = raw.astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "t"})


def _group_max(grp: pd.DataFrame, column: str) -> float:
    if column not in grp.columns:
        return 0.0
    values = pd.to_numeric(grp[column], errors="coerce").fillna(0.0)
    return float(values.max()) if not values.empty else 0.0


def _group_bool(grp: pd.DataFrame, column: str) -> bool:
    if column not in grp.columns:
        return False
    return bool(grp[column].fillna(False).astype(bool).any())


def _window_context_count(window: dict[str, Any]) -> int:
    return sum(
        int(bool(window.get(column)))
        for column in (
            "manual_context",
            "after_hours_or_weekend_context",
            "round_amount_context",
            "suspense_context",
            "risk_keyword_context",
        )
    )


def _candidate_window_retention_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {
            "candidate_window_count": 0,
            "candidate_truth_window_count": 0,
            "current_cap500_truth_window_count": 0,
            "score_desc_cap500_truth_window_count": 0,
            "truth_window_ordinal_distribution": _num_dist([]),
            "truth_window_score_distribution": _num_dist([]),
        }
    truth_windows = [window for window in windows if int(window["truth_doc_count"]) > 0]
    current_cap = _retention_policy_order(
        windows,
        "current_original_order_cap500",
    )[:500]
    score_cap = _retention_policy_order(windows, "score_desc_cap500")[:500]
    period_end_cap = _retention_policy_order(windows, "period_end_score_cap500")[:500]
    period_end_low_support_demoted_cap = _retention_policy_order(
        windows,
        "period_end_score_low_support_demoted_cap500",
    )[:500]
    return {
        "candidate_window_count": len(windows),
        "candidate_truth_window_count": len(truth_windows),
        "current_cap500_truth_window_count": sum(
            1 for window in current_cap if int(window["truth_doc_count"]) > 0
        ),
        "current_cap500_truth_document_count": _selected_truth_document_count(current_cap),
        "score_desc_cap500_truth_window_count": sum(
            1 for window in score_cap if int(window["truth_doc_count"]) > 0
        ),
        "score_desc_cap500_truth_document_count": _selected_truth_document_count(score_cap),
        "period_end_score_cap500_truth_window_count": sum(
            1 for window in period_end_cap if int(window["truth_doc_count"]) > 0
        ),
        "period_end_score_cap500_truth_document_count": _selected_truth_document_count(
            period_end_cap
        ),
        "period_end_score_low_support_demoted_cap500_truth_window_count": sum(
            1
            for window in period_end_low_support_demoted_cap
            if int(window["truth_doc_count"]) > 0
        ),
        "period_end_score_low_support_demoted_cap500_truth_document_count": (
            _selected_truth_document_count(period_end_low_support_demoted_cap)
        ),
        "truth_window_ordinal_distribution": _num_dist(
            [window["ordinal"] for window in truth_windows]
        ),
        "truth_window_score_distribution": _num_dist([window["score"] for window in truth_windows]),
        "truth_window_period_end_context_count": sum(
            1 for window in truth_windows if bool(window["period_end_context"])
        ),
        "retention_surface_topn": {
            "current_original_order_cap500": _retention_surface_topn_summary(current_cap),
            "score_desc_cap500": _retention_surface_topn_summary(score_cap),
            "period_end_score_cap500": _retention_surface_topn_summary(period_end_cap),
            "period_end_score_low_support_demoted_cap500": _retention_surface_topn_summary(
                period_end_low_support_demoted_cap
            ),
        },
    }


def _retention_policy_order(
    windows: list[dict[str, Any]],
    policy: str,
) -> list[dict[str, Any]]:
    if policy == "current_original_order_cap500":
        return sorted(windows, key=lambda item: int(item["ordinal"]))
    if policy == "score_desc_cap500":
        return sorted(windows, key=lambda item: (-float(item["score"]), int(item["ordinal"])))
    if policy == "period_end_score_cap500":
        return sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        )
    if policy == "period_end_score_low_support_demoted_cap500":
        return sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) <= 1,
                -float(item["score"]),
                int(item["ordinal"]),
            ),
        )
    raise ValueError(f"unknown retention policy: {policy}")


def _selected_truth_document_count(windows: list[dict[str, Any]]) -> int:
    docs: set[str] = set()
    for window in windows:
        raw_docs = window.get("_truth_docs")
        if isinstance(raw_docs, set):
            docs.update(str(doc) for doc in raw_docs)
    return len(docs)


def _retention_surface_topn_summary(windows: list[dict[str, Any]]) -> dict[str, Any]:
    top100 = windows[:100]
    top500 = windows[:500]
    return {
        "top100_truth_document_count": _selected_truth_document_count(top100),
        "top500_truth_document_count": _selected_truth_document_count(top500),
        "top100_truth_window_count": sum(
            1 for window in top100 if int(window["truth_doc_count"]) > 0
        ),
        "top500_truth_window_count": sum(
            1 for window in top500 if int(window["truth_doc_count"]) > 0
        ),
        "top500_review_burden_proxy": _retention_review_burden_proxy(top500),
    }


def _retention_review_burden_proxy(windows: list[dict[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {
            "score": 0.0,
            "period_end_share": 0.0,
            "subject_top1_share": 0.0,
            "low_row_support_share": 0.0,
        }
    total = len(windows)
    period_end_share = sum(1 for window in windows if bool(window["period_end_context"])) / total
    subject_counts = Counter(str(window.get("_subject", "")) for window in windows)
    subject_top1_share = subject_counts.most_common(1)[0][1] / total if subject_counts else 0.0
    low_row_support_share = sum(1 for window in windows if int(window["row_count"]) <= 1) / total
    score = 0.45 * period_end_share + 0.35 * subject_top1_share + 0.20 * low_row_support_share
    return {
        "score": score,
        "period_end_share": period_end_share,
        "subject_top1_share": subject_top1_share,
        "low_row_support_share": low_row_support_share,
    }


def _retention_policy_fixture_validation() -> dict[str, Any]:
    """Deterministic no-truth fixture for retention policy behavior."""
    windows = [
        _fixture_window(
            ordinal=1,
            score=0.98,
            row_count=1,
            period_end_context=True,
            label="one_row_period_end_noise_high_score",
        ),
        _fixture_window(
            ordinal=2,
            score=0.92,
            row_count=12,
            period_end_context=True,
            label="supported_unusual_period_end_window",
        ),
        _fixture_window(
            ordinal=3,
            score=0.88,
            row_count=25,
            period_end_context=True,
            label="normal_supported_period_end_burst",
        ),
        _fixture_window(
            ordinal=4,
            score=0.99,
            row_count=20,
            period_end_context=False,
            label="non_period_end_high_score_window",
        ),
    ]
    policy = "period_end_score_low_support_demoted_cap500"
    ordered = _retention_policy_order(windows, policy)
    ordered_labels = [str(window["fixture_label"]) for window in ordered]
    return {
        "policy": policy,
        "truth_label_used": False,
        "ordered_labels": ordered_labels,
        "supported_unusual_before_one_row_noise": (
            ordered_labels.index("supported_unusual_period_end_window")
            < ordered_labels.index("one_row_period_end_noise_high_score")
        ),
        "period_end_context_before_non_period_end_high_score": (
            ordered_labels.index("normal_supported_period_end_burst")
            < ordered_labels.index("non_period_end_high_score_window")
        ),
        "expected_first_label": "supported_unusual_period_end_window",
    }


def _fixture_window(
    *,
    ordinal: int,
    score: float,
    row_count: int,
    period_end_context: bool,
    label: str,
) -> dict[str, Any]:
    return {
        "ordinal": ordinal,
        "score": score,
        "row_count": row_count,
        "period_end_context": period_end_context,
        "truth_doc_count": 0,
        "_truth_docs": set(),
        "_subject": label,
        "fixture_label": label,
    }


def _is_period_end_day(day: pd.Timestamp) -> bool:
    if pd.isna(day):
        return False
    month_end = day + pd.offsets.MonthEnd(0)
    return 0 <= int((month_end.normalize() - day.normalize()).days) <= 3


def _num_dist(values: list[Any]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and np.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "p50": None, "p90": None, "max": None}
    arr = np.asarray(clean, dtype=float)
    return {
        "count": int(len(arr)),
        "min": float(arr.min()),
        "p50": float(np.quantile(arr, 0.50)),
        "p90": float(np.quantile(arr, 0.90)),
        "max": float(arr.max()),
    }


def _coerce_positions(values: list[Any], *, df_len: int) -> list[int]:
    positions: list[int] = []
    for value in values:
        try:
            pos = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= pos < df_len:
            positions.append(pos)
    return positions


def _is_valid_position(value: Any, *, df_len: int) -> bool:
    try:
        pos = int(value)
    except (TypeError, ValueError):
        return False
    return 0 <= pos < df_len


def _docs_for_positions(df: pd.DataFrame, positions: list[int]) -> set[str]:
    if "document_id" not in df.columns:
        return set()
    docs: set[str] = set()
    for pos in positions:
        value = df["document_id"].iat[pos]
        if value is not None and str(value).strip():
            docs.add(str(value))
    return docs


def _case_docs_no_raw(case: TimeseriesCase) -> set[str]:
    return {
        str(ref.document_id)
        for ref in case.row_refs
        if getattr(ref, "document_id", None) not in (None, "")
    }


def _direction_summary(batch_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for batch_name, payload in batch_payloads.items():
        current = payload["candidates"]["current_native_ts_ordering"]
        burden = payload["candidates"]["review_burden_penalized_context"]
        burden_demoted = payload["candidates"]["review_burden_closing_demoted_context"]
        baseline = payload["candidates"]["robust_context_baseline_sufficiency"]
        rows[batch_name] = {
            "current_top100": current["topn"]["100"]["matched"],
            "current_top500": current["topn"]["500"]["matched"],
            "current_first_truth_rank": current["first_truth_rank"],
            "burden_top100": burden["topn"]["100"]["matched"],
            "burden_top500": burden["topn"]["500"]["matched"],
            "burden_first_truth_rank": burden["first_truth_rank"],
            "burden_fp_pressure": burden["top500_distribution"][
                "false_positive_pressure_proxy"
            ]["score"],
            "burden_demoted_top100": burden_demoted["topn"]["100"]["matched"],
            "burden_demoted_top500": burden_demoted["topn"]["500"]["matched"],
            "burden_demoted_first_truth_rank": burden_demoted["first_truth_rank"],
            "burden_demoted_fp_pressure": burden_demoted["top500_distribution"][
                "false_positive_pressure_proxy"
            ]["score"],
            "baseline_top500": baseline["topn"]["500"]["matched"],
            "baseline_first_truth_rank": baseline["first_truth_rank"],
            "direction": _batch_direction(current, burden),
        }
    return {
        "by_batch": rows,
        "all_batches_improve_top100_or_top500": all(
            row["burden_top100"] > row["current_top100"]
            or row["burden_top500"] > row["current_top500"]
            for row in rows.values()
        ),
        "all_batches_first_rank_nonworse": all(
            row["current_first_truth_rank"] is None
            or (
                row["burden_first_truth_rank"] is not None
                and row["burden_first_truth_rank"] <= row["current_first_truth_rank"]
            )
            for row in rows.values()
        ),
    }


def _batch_direction(current: dict[str, Any], candidate: dict[str, Any]) -> str:
    if candidate["topn"]["100"]["matched"] > current["topn"]["100"]["matched"]:
        return "top100_improved"
    if candidate["topn"]["500"]["matched"] > current["topn"]["500"]["matched"]:
        return "top500_improved"
    if (
        current["first_truth_rank"] is not None
        and candidate["first_truth_rank"] is not None
        and candidate["first_truth_rank"] < current["first_truth_rank"]
    ):
        return "first_rank_improved_only"
    return "no_material_improvement"


def main() -> int:
    started = time.perf_counter()
    batches = {spec.name: _run_batch(spec) for spec in BATCHES}
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "diagnostic_scope": "cross-batch timeseries native case ranking candidates only",
        "top_ns": list(TOP_NS),
        "guardrails": [
            "No detector thresholds, native case gates, PHASE1 ranking, or PHASE2 "
            "fusion are changed.",
            "Truth labels are used only for aggregate after-the-fact evaluation.",
            "Raw document identifiers and raw row identifiers are not emitted.",
        ],
        "no_fitting_assertions": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
        },
        "candidate_descriptions": {
            name: _CANDIDATE_DESCRIPTIONS[name] for name in _KEY_CANDIDATES
        },
        "retention_policy_provenance": dict(_RETENTION_POLICY_PROVENANCE),
        "retention_policy_descriptions": dict(_RETENTION_POLICY_DESCRIPTIONS),
        "retention_no_fitting_assertions": {
            "truth_label_used_for_retention_order": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_artifact_retention_changed": False,
            "detector_artifact_cap_changed": False,
            "ts01_candidate_generation_changed": False,
        },
        "batches": batches,
        "direction_summary": _direction_summary(batches),
        "retention_policy_readiness": _retention_policy_readiness(batches),
        "row_score_surface_readiness": _row_score_surface_readiness(batches),
        "row_score_burden_control_summary": _row_score_burden_control_summary(batches),
        "row_score_phase1_incremental_alignment_summary": (
            _row_score_phase1_incremental_alignment_summary(batches)
        ),
        "retention_policy_fixture_validation": _retention_policy_fixture_validation(),
    }
    leak_counts = [
        batch["raw_identifier_leak_check"] for batch in payload["batches"].values()
    ]
    payload["raw_identifier_leak_check"] = {
        "doc_like_token_count": sum(item["doc_like_token_count"] for item in leak_counts),
        "forbidden_identifier_key_count": sum(
            item["forbidden_identifier_key_count"] for item in leak_counts
        ),
        "phase2_case_id_like_token_count": sum(
            item["phase2_case_id_like_token_count"] for item in leak_counts
        ),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


def _retention_policy_readiness(batch_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    policy = "period_end_score_low_support_demoted_cap500"
    by_batch: dict[str, Any] = {}
    for batch_name, payload in batch_payloads.items():
        ts01 = payload["truth_coverage_flow"]["artifact_retention_diagnostic"]["by_rule"]["TS01"]
        current = ts01["retention_surface_topn"]["current_original_order_cap500"]
        candidate = ts01["retention_surface_topn"][policy]
        by_batch[batch_name] = {
            "current_top500_truth_docs": current["top500_truth_document_count"],
            "candidate_top500_truth_docs": candidate["top500_truth_document_count"],
            "current_top100_truth_docs": current["top100_truth_document_count"],
            "candidate_top100_truth_docs": candidate["top100_truth_document_count"],
            "candidate_burden_proxy": candidate["top500_review_burden_proxy"]["score"],
            "top500_improved": candidate["top500_truth_document_count"]
            > current["top500_truth_document_count"],
        }
    return {
        "candidate": policy,
        "status": "production_application_hold",
        "by_batch": by_batch,
        "all_batches_top500_improved": all(row["top500_improved"] for row in by_batch.values()),
        "reason_for_hold": (
            "Diagnostic cross-batch direction is positive at TOP500, but production adoption "
            "requires fixture/DataSynth validation and UI/report burden review."
        ),
    }


def _row_score_surface_readiness(batch_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    surface = "row_score_ge_0.5"
    policy = "period_end_support_hybrid"
    by_batch: dict[str, Any] = {}
    for batch_name, payload in batch_payloads.items():
        current = payload["candidates"]["current_native_ts_ordering"]
        candidate = payload["row_score_window_surface_diagnostic"]["surfaces"][surface][
            "policies"
        ][policy]
        year_top100 = [
            int(row["top100_truth_document_count"])
            for row in candidate["year_slice_summary"].values()
        ]
        year_top500 = [
            int(row["top500_truth_document_count"])
            for row in candidate["year_slice_summary"].values()
        ]
        pressure = candidate["top500_context_pressure"]
        burden = candidate["top500_review_burden_proxy"]
        by_batch[batch_name] = {
            "current_top100": current["topn"]["100"]["matched"],
            "current_top500": current["topn"]["500"]["matched"],
            "candidate_top100": candidate["topn"]["100"]["truth_document_count"],
            "candidate_top500": candidate["topn"]["500"]["truth_document_count"],
            "candidate_top100_improved": (
                candidate["topn"]["100"]["truth_document_count"]
                > current["topn"]["100"]["matched"]
            ),
            "candidate_top500_improved": (
                candidate["topn"]["500"]["truth_document_count"]
                > current["topn"]["500"]["matched"]
            ),
            "first_truth_window_rank": candidate["first_truth_window_rank"],
            "year_slice_top100_min": min(year_top100) if year_top100 else None,
            "year_slice_top100_max": max(year_top100) if year_top100 else None,
            "year_slice_top500_min": min(year_top500) if year_top500 else None,
            "year_slice_top500_max": max(year_top500) if year_top500 else None,
            "top500_burden_score": burden["score"],
            "top500_period_end_share": burden["period_end_share"],
            "top500_subject_top1_share": burden["subject_top1_share"],
            "top500_low_row_support_share": burden["low_row_support_share"],
            "top500_manual_context_share": pressure["manual_context_share"],
            "top500_after_hours_or_weekend_context_share": pressure[
                "after_hours_or_weekend_context_share"
            ],
            "top500_high_amount_zscore_share": pressure["high_amount_zscore_share"],
        }
    return {
        "candidate": policy,
        "surface": surface,
        "status": "production_application_hold",
        "diagnostic_only": True,
        "truth_label_used_for_surface_order": False,
        "production_case_generation_changed": False,
        "all_batches_top100_improved": all(
            row["candidate_top100_improved"] for row in by_batch.values()
        ),
        "all_batches_top500_improved": all(
            row["candidate_top500_improved"] for row in by_batch.values()
        ),
        "by_batch": by_batch,
        "reason_for_hold": (
            "Large recall recovery is cross-batch positive, but period-end concentration "
            "and amount/context review burden require UI/export burden controls before adoption."
        ),
    }


def _row_score_burden_control_summary(
    batch_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    surface = "row_score_ge_0.5"
    baseline_policy = "period_end_support_hybrid"
    policies = (
        "period_end_support_hybrid",
        "hybrid_period_end_80pct_cap",
        "hybrid_subject_cap10",
        "hybrid_high_amount_zscore_25pct_cap",
        "ui100_context_export500_hybrid",
    )
    by_batch: dict[str, Any] = {}
    for batch_name, payload in batch_payloads.items():
        policy_payload = payload["row_score_window_surface_diagnostic"]["surfaces"][surface][
            "policies"
        ]
        baseline = policy_payload[baseline_policy]
        baseline_top500 = baseline["topn"]["500"]["truth_document_count"]
        baseline_burden = baseline["top500_review_burden_proxy"]["score"]
        rows: dict[str, Any] = {}
        for policy in policies:
            candidate = policy_payload[policy]
            burden = candidate["top500_review_burden_proxy"]
            pressure = candidate["top500_context_pressure"]
            rows[policy] = {
                "top100": candidate["topn"]["100"]["truth_document_count"],
                "top500": candidate["topn"]["500"]["truth_document_count"],
                "top1000": candidate["topn"]["1000"]["truth_document_count"],
                "first_truth_window_rank": candidate["first_truth_window_rank"],
                "top500_burden_score": burden["score"],
                "top500_period_end_share": burden["period_end_share"],
                "top500_subject_top1_share": burden["subject_top1_share"],
                "top500_high_amount_zscore_share": pressure["high_amount_zscore_share"],
                "top500_delta_vs_hybrid": (
                    candidate["topn"]["500"]["truth_document_count"] - baseline_top500
                ),
                "burden_delta_vs_hybrid": burden["score"] - baseline_burden,
            }
        by_batch[batch_name] = rows
    return {
        "surface": surface,
        "baseline_policy": baseline_policy,
        "diagnostic_only": True,
        "truth_label_used_for_policy_order": False,
        "production_case_generation_changed": False,
        "policy_interpretation": {
            "hybrid_period_end_80pct_cap": (
                "reduces period-end concentration but loses TOP500 coverage"
            ),
            "hybrid_subject_cap10": (
                "reduces subject concentration with limited TOP100 impact"
            ),
            "hybrid_high_amount_zscore_25pct_cap": (
                "reduces high amount z-score concentration; fixed5 already below cap"
            ),
            "ui100_context_export500_hybrid": (
                "separates UI TOP100 context order from export TOP500 hybrid order"
            ),
        },
        "by_batch": by_batch,
    }


def _row_score_phase1_incremental_alignment_summary(
    batch_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    surface = "row_score_ge_0.5"
    policies = (
        "period_end_support_hybrid",
        "hybrid_high_amount_zscore_25pct_cap",
        "timing_primary_round_amount_demoted",
        "timing_primary_support_round_amount_demoted",
    )
    by_batch: dict[str, Any] = {}
    for batch_name, payload in batch_payloads.items():
        surface_payload = payload["row_score_window_surface_diagnostic"]
        if not surface_payload["phase1_reference_available"]:
            by_batch[batch_name] = {
                "available": False,
                "reason": surface_payload["phase1_reference_reason"],
            }
            continue
        policy_rows: dict[str, Any] = {}
        for policy in policies:
            candidate = surface_payload["surfaces"][surface]["policies"][policy]
            incremental = candidate["incremental_to_phase1"]
            top100 = incremental["topn"]["100"]
            top500 = incremental["topn"]["500"]
            policy_rows[policy] = {
                "top100_truth": top100["selected_truth_document_count"],
                "top100_not_phase1_top100": top100[
                    "not_in_phase1_top100_truth_document_count"
                ],
                "top100_ts_aligned_not_phase1_top100": top100[
                    "ts_aligned_not_in_phase1_top100_truth_document_count"
                ],
                "top500_truth": top500["selected_truth_document_count"],
                "top500_not_phase1_top100": top500[
                    "not_in_phase1_top100_truth_document_count"
                ],
                "top500_ts_aligned_not_phase1_top100": top500[
                    "ts_aligned_not_in_phase1_top100_truth_document_count"
                ],
                "top100_not_phase1_top100_scenario_counts": top100[
                    "not_in_phase1_top100_scenario_counts"
                ],
                "top500_not_phase1_top100_scenario_counts": top500[
                    "not_in_phase1_top100_scenario_counts"
                ],
            }
        by_batch[batch_name] = {
            "available": True,
            "phase1_top100_truth_document_count": surface_payload["surfaces"][surface][
                "policies"
            ]["period_end_support_hybrid"]["incremental_to_phase1"][
                "phase1_top100_truth_document_count"
            ],
            "phase1_top500_truth_document_count": surface_payload["surfaces"][surface][
                "policies"
            ]["period_end_support_hybrid"]["incremental_to_phase1"][
                "phase1_top500_truth_document_count"
            ],
            "policies": policy_rows,
        }
    return {
        "surface": surface,
        "diagnostic_only": True,
        "truth_label_used_for_policy_order": False,
        "truth_label_used_only_for_incremental_evaluation": True,
        "phase1_ranking_changed": False,
        "production_ranking_changed": False,
        "ts_aligned_scenarios": sorted(_TS_ALIGNED_SCENARIOS),
        "current_direction_read": (
            "broad hybrid has strong PHASE1-novel recall but weak TS-aligned TOP100 "
            "uplift; timing-primary candidates are not cross-batch stable yet"
        ),
        "by_batch": by_batch,
    }


if __name__ == "__main__":
    raise SystemExit(main())
