"""Diagnostic-only TS-primary surface comparison for fixed5-compatible slices.

The Phase 5 goal is not maximum overall recall. It is to test whether a
Timeseries-primary review surface is stable inside fixed5_normalcal5 slices.
fixed4 is a known-broken DataSynth baseline and is excluded from product
adoption decisions. Candidate ordering does not use truth labels, scenario
labels, PHASE1 ranks, raw document identifiers, row identifiers, or case
identifiers.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
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
    _candidate_order,
    _raw_identifier_leak_report,
)
from tools.scripts.diagnose_timeseries_ranking_crossbatch_20260529 import (
    _TS_ALIGNED_SCENARIOS,
    _bool_series,
    _context_pressure_summary,
    _is_period_end_day,
    _load_case_input,
    _load_truth,
    _num_dist,
    _phase1_reference_sets,
    _retention_review_burden_proxy,
    _scenario_counts,
    _truth_scenario_by_doc,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID as FIXED5_BATCH_ID,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import _run_rule_detector

OUT_JSON = ROOT / "artifacts" / "timeseries_primary_surface_crossbatch_20260530.json"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    truth_csv: Path
    batch_id: str
    phase1_case_result: Path


PRIMARY_VALIDATION_DATASET = "fixed5_normalcal5"
EXCLUDED_VALIDATION_DATASETS = ["fixed4"]
EXCLUSION_REASON = "known-broken DataSynth baseline; not used for product adoption"

BATCHES = (
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

TOP_NS = (100, 500, 1000)
PRIMARY_POLICIES = (
    "current_native_ts_order",
    "timing_primary_context_surface",
    "supported_period_end_anomaly_surface",
    "ts_primary_conservative_surface",
    "broad_companion_reference_surface",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _run_batch(spec: BatchSpec) -> dict[str, Any]:
    started = time.perf_counter()
    _print(f"loading {spec.name}")
    df = _load_case_input(spec.case_input)
    truth = _load_truth(spec.truth_csv)
    truth_docs = set(truth["document_id"].astype(str))
    scenario_by_doc = _truth_scenario_by_doc(truth)
    phase1_reference = _phase1_reference_sets(spec.phase1_case_result)
    ts_result = _run_rule_detector("timeseries", df)

    windows = _build_row_score_windows(df=df, detection_result=ts_result, truth_docs=truth_docs)
    policies = _candidate_policies(windows)
    policies["current_native_ts_order"] = _current_native_windows(
        df=df,
        detection_result=ts_result,
        batch_id=spec.batch_id,
        truth_docs=truth_docs,
    )
    policy_summaries = {
        name: _policy_summary(
            ordered,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        )
        for name, ordered in policies.items()
        if name in PRIMARY_POLICIES
    }
    payload = {
        "dataset": spec.dataset,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "truth_document_count": len(truth_docs),
        "row_count": len(df),
        "window_count": len(windows),
        "phase1_reference": {
            "available": bool(phase1_reference["available"]),
            "phase1_top100_truth_document_count": len(
                phase1_reference["top100_docs"] & truth_docs
            ),
            "phase1_top500_truth_document_count": len(
                phase1_reference["top500_docs"] & truth_docs
            ),
        },
        "rank_band_decomposition": _rank_band_decomposition(
            {name: policies[name] for name in PRIMARY_POLICIES},
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        ),
        "feature_comparison": _feature_comparison(
            current_order=policies["broad_companion_reference_surface"],
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
        ),
        "proxy_diagnostics": _proxy_diagnostics(
            policies,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        ),
        "slice_stability": _slice_stability(
            windows=windows,
            policies={name: policies[name] for name in PRIMARY_POLICIES},
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            phase1_reference=phase1_reference,
        ),
        "policies": policy_summaries,
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    return payload


def _build_row_score_windows(
    *,
    df: pd.DataFrame,
    detection_result: Any,
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    if "posting_date" not in df.columns or "document_id" not in df.columns:
        return []
    subject_col = "gl_account" if "gl_account" in df.columns else "business_process"
    posting_date = pd.to_datetime(df["posting_date"], errors="coerce").dt.normalize()
    scores = getattr(detection_result, "scores", pd.Series(dtype=float))
    scores = scores.reindex(df.index).fillna(0.0).astype(float)
    base = pd.DataFrame(
        {
            "subject": df[subject_col].astype(str),
            "business_process": (
                df["business_process"].astype(str)
                if "business_process" in df.columns
                else pd.Series("unknown", index=df.index)
            ),
            "posting_date_norm": posting_date,
            "score": scores,
            "document_id": df["document_id"].astype(str),
            **_row_context_columns(df),
        },
        index=df.index,
    )
    base = base[base["score"] >= 0.5].dropna(subset=["subject", "posting_date_norm"])
    subject_day_counts = (
        base.groupby(["subject", "posting_date_norm"], sort=False)
        .size()
        .rename("daily_count")
        .reset_index()
    )
    subject_totals = base.groupby("subject").size().to_dict()
    subject_rank = _subject_activity_ranks(subject_totals)
    baseline = _baseline_stats(subject_day_counts)

    windows: list[dict[str, Any]] = []
    for ordinal, ((subject, day), grp) in enumerate(
        base.groupby(["subject", "posting_date_norm"], sort=False),
        start=1,
    ):
        docs = set(grp["document_id"].astype(str))
        row_count = int(len(grp))
        stats = baseline.get(str(subject), {})
        expected_count = float(stats.get("expected_count", 0.0))
        robust_z = _robust_z(row_count, stats.get("baseline_values", []))
        period_end_lift = _period_end_lift(row_count, stats.get("period_end_values", []))
        period_end_context = _is_period_end_day(pd.Timestamp(day))
        manual_context = bool(grp["manual_or_adjustment_context"].any())
        after_context = bool(grp["after_hours_or_weekend_context"].any())
        round_context = bool(grp["round_amount_context"].any())
        amount_z = float(grp["amount_zscore"].max())
        context_count = int(manual_context) + int(after_context) + int(round_context)
        windows.append(
            {
                "ordinal": ordinal,
                "score": float(grp["score"].max()),
                "period_end_context": period_end_context,
                "period_end_day_offset": _period_end_day_offset(pd.Timestamp(day)),
                "period_end_lift": period_end_lift,
                "robust_z": robust_z,
                "expected_count": expected_count,
                "baseline_observation_count": int(stats.get("baseline_observation_count", 0)),
                "row_count": row_count,
                "window_support": row_count,
                "amount_tail_context": bool(amount_z >= 3.0),
                "amount_zscore": amount_z,
                "manual_or_adjustment_context": manual_context,
                "manual_context": manual_context,
                "after_hours_or_weekend_context": after_context,
                "round_amount_context": round_context,
                "subject_activity_rank": int(subject_rank.get(str(subject), 0)),
                "subject_frequency_context": int(subject_totals.get(str(subject), 0)),
                "context_evidence_count": context_count,
                "context_count": context_count,
                "rarity_context_count": int(amount_z >= 3.0) + int(not round_context),
                "truth_doc_count": len(docs & truth_docs),
                "_truth_docs": docs & truth_docs,
                "_docs": docs,
                "_subject": str(subject),
                "business_process": _mode_string(grp["business_process"]),
                "day": pd.Timestamp(day),
                "year": int(pd.Timestamp(day).year),
                "quarter": f"{int(pd.Timestamp(day).year)}Q{int(pd.Timestamp(day).quarter)}",
            }
        )
    return windows


def _mode_string(values: pd.Series) -> str:
    clean = values.dropna().astype(str)
    if clean.empty:
        return "unknown"
    return str(clean.mode().iat[0])


def _row_context_columns(df: pd.DataFrame) -> dict[str, pd.Series]:
    amount_source = pd.Series(0.0, index=df.index)
    for column in ("local_amount", "debit_amount", "credit_amount"):
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce").fillna(0.0).abs()
            amount_source = pd.concat([amount_source, values], axis=1).max(axis=1)
    if "amount_zscore" in df.columns:
        amount_zscore = pd.to_numeric(df["amount_zscore"], errors="coerce").fillna(0.0).abs()
    else:
        amount_zscore = pd.Series(0.0, index=df.index)
    return {
        "amount_zscore": amount_zscore,
        "amount_log": np.log1p(amount_source),
        "manual_or_adjustment_context": _bool_series(df, "is_manual_je")
        | _bool_series(df, "is_adjustment"),
        "after_hours_or_weekend_context": _bool_series(df, "is_after_hours")
        | _bool_series(df, "is_weekend"),
        "round_amount_context": _bool_series(df, "is_round_number"),
    }


def _subject_activity_ranks(subject_totals: dict[Any, int]) -> dict[str, int]:
    ordered = sorted(
        ((str(subject), int(total)) for subject, total in subject_totals.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return {subject: rank for rank, (subject, _) in enumerate(ordered, start=1)}


def _baseline_stats(subject_day_counts: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for subject, grp in subject_day_counts.groupby("subject", sort=False):
        counts = [float(value) for value in grp["daily_count"].tolist()]
        period_end_counts = [
            float(row.daily_count)
            for row in grp.itertuples(index=False)
            if _is_period_end_day(pd.Timestamp(row.posting_date_norm))
        ]
        out[str(subject)] = {
            "baseline_values": counts,
            "period_end_values": period_end_counts,
            "expected_count": float(np.median(counts)) if counts else 0.0,
            "baseline_observation_count": len(counts),
        }
    return out


def _robust_z(observed: int, values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    scale = 1.4826 * mad if mad > 0 else float(np.std(arr))
    if scale <= 0:
        return 0.0
    return float((observed - median) / scale)


def _period_end_lift(observed: int, values: list[float]) -> float:
    if not values:
        return 0.0
    expected = float(np.median(np.asarray(values, dtype=float)))
    if expected <= 0:
        return 0.0
    return float(observed / expected)


def _period_end_day_offset(day: pd.Timestamp) -> int | None:
    if pd.isna(day):
        return None
    month_end = day + pd.offsets.MonthEnd(0)
    return int((month_end.normalize() - day.normalize()).days)


def _candidate_policies(windows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    broad = sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["row_count"]) < 3,
            int(item["row_count"]) < 10,
            -int(
                bool(item["manual_or_adjustment_context"])
                + bool(item["after_hours_or_weekend_context"])
            ),
            -float(item["amount_zscore"]),
            -float(item["score"]),
            int(item["ordinal"]),
        ),
    )
    return {
        "broad_companion_reference_surface": broad,
        "timing_primary_context_surface": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 7,
                bool(item["round_amount_context"]),
                float(item["amount_zscore"]) >= 10.0,
                -float(item["robust_z"]),
                -int(item["context_evidence_count"]),
                -float(item["period_end_lift"]),
                int(item["ordinal"]),
            ),
        ),
        "supported_period_end_anomaly_surface": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["baseline_observation_count"]) < 10,
                int(item["row_count"]) < 7,
                bool(item["round_amount_context"]),
                -float(item["period_end_lift"]),
                -float(item["robust_z"]),
                -int(item["context_evidence_count"]),
                int(item["ordinal"]),
            ),
        ),
        "ts_primary_conservative_surface": sorted(
            windows,
            key=lambda item: (
                not bool(item["period_end_context"]),
                int(item["row_count"]) < 7,
                bool(item["round_amount_context"]),
                float(item["amount_zscore"]) >= 3.0,
                -int(item["context_evidence_count"]),
                -float(item["period_end_lift"]),
                -float(item["robust_z"]),
                int(item["ordinal"]),
            ),
        ),
    }


def _current_native_windows(
    *,
    df: pd.DataFrame,
    detection_result: Any,
    batch_id: str,
    truth_docs: set[str],
) -> list[dict[str, Any]]:
    case_set = build_phase2_case_set(
        batch_id=batch_id,
        detection_results=[detection_result],
        df=df,
    )
    cases = [case for case in case_set.timeseries_cases if isinstance(case, TimeseriesCase)]
    ordered = _candidate_order(cases, "current_native_ts_ordering")
    df_by_doc = (
        df.drop_duplicates("document_id").set_index("document_id")
        if "document_id" in df.columns
        else pd.DataFrame()
    )
    windows: list[dict[str, Any]] = []
    for ordinal, case in enumerate(ordered, start=1):
        docs = {
            str(ref.document_id)
            for ref in getattr(case, "row_refs", [])
            if getattr(ref, "document_id", None) not in (None, "")
        }
        rows = df_by_doc.reindex(list(docs)) if docs and not df_by_doc.empty else pd.DataFrame()
        if not rows.empty and "posting_date" in rows:
            day = pd.to_datetime(rows["posting_date"], errors="coerce").dropna().min()
        else:
            day = pd.NaT
        if pd.isna(day):
            day = pd.Timestamp("1970-01-01")
        amount_z = (
            float(pd.to_numeric(rows.get("amount_zscore"), errors="coerce").fillna(0.0).abs().max())
            if not rows.empty and "amount_zscore" in rows
            else 0.0
        )
        manual = _row_bool_any(rows, "is_manual_je") or _row_bool_any(rows, "is_adjustment")
        after = _row_bool_any(rows, "is_after_hours") or _row_bool_any(rows, "is_weekend")
        round_amount = _row_bool_any(rows, "is_round_number")
        context_count = int(manual) + int(after) + int(round_amount)
        windows.append(
            {
                "ordinal": ordinal,
                "score": float(getattr(case, "family_score", 0.0) or 0.0),
                "period_end_context": _is_period_end_day(pd.Timestamp(day)),
                "period_end_day_offset": _period_end_day_offset(pd.Timestamp(day)),
                "period_end_lift": float(getattr(case, "period_end_lift", 0.0) or 0.0),
                "robust_z": float(getattr(case, "robust_z", 0.0) or 0.0),
                "expected_count": float(getattr(case, "expected_count", 0.0) or 0.0),
                "baseline_observation_count": int(
                    getattr(case, "baseline_observation_count", 0) or 0
                ),
                "row_count": int(getattr(case, "row_count", 0) or len(docs)),
                "window_support": int(getattr(case, "row_count", 0) or len(docs)),
                "amount_tail_context": bool(amount_z >= 3.0),
                "amount_zscore": amount_z,
                "manual_or_adjustment_context": manual,
                "manual_context": manual,
                "after_hours_or_weekend_context": after,
                "round_amount_context": round_amount,
                "subject_activity_rank": int(getattr(case, "subject_activity_rank", 0) or 0),
                "subject_frequency_context": 0,
                "context_evidence_count": context_count,
                "context_count": context_count,
                "rarity_context_count": int(amount_z >= 3.0) + int(not round_amount),
                "truth_doc_count": len(docs & truth_docs),
                "_truth_docs": docs & truth_docs,
                "_docs": docs,
                "_subject": str(getattr(case, "subject", "")),
                "business_process": (
                    _mode_string(rows["business_process"])
                    if not rows.empty and "business_process" in rows
                    else "unknown"
                ),
                "day": pd.Timestamp(day),
                "year": int(pd.Timestamp(day).year),
                "quarter": f"{int(pd.Timestamp(day).year)}Q{int(pd.Timestamp(day).quarter)}",
            }
        )
    return windows


def _row_bool_any(rows: pd.DataFrame, column: str) -> bool:
    if rows.empty or column not in rows:
        return False
    values = rows[column]
    if pd.api.types.is_bool_dtype(values):
        return bool(values.fillna(False).any())
    return bool(values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"}).any())


def _policy_summary(
    ordered: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    topn: dict[str, Any] = {}
    for top_n in TOP_NS:
        docs = _selected_candidate_docs(ordered[:top_n])
        selected_truth = docs & truth_docs
        not_p1_top100 = selected_truth - phase1_reference["top100_docs"]
        not_p1_top500 = selected_truth - phase1_reference["top500_docs"]
        aligned = {
            doc for doc in selected_truth if scenario_by_doc.get(doc) in _TS_ALIGNED_SCENARIOS
        }
        aligned_not_p1_top100 = aligned - phase1_reference["top100_docs"]
        aligned_not_p1_top500 = aligned - phase1_reference["top500_docs"]
        topn[str(top_n)] = {
            "ts_aligned_truth_docs": len(aligned),
            "truth_docs_not_in_phase1_top100": len(not_p1_top100),
            "truth_docs_not_in_phase1_top500": len(not_p1_top500),
            "ts_aligned_not_in_phase1_top100": len(aligned_not_p1_top100),
            "ts_aligned_not_in_phase1_top500": len(aligned_not_p1_top500),
            "not_phase1_top100_scenario_counts": _scenario_counts(
                not_p1_top100,
                scenario_by_doc,
            ),
        }
    return {
        "topn": topn,
        "review_burden": _retention_review_burden_proxy(ordered[:500]),
        "period_end_concentration": _retention_review_burden_proxy(ordered[:500])[
            "period_end_share"
        ],
        "baseline_available_ratio": sum(
            1 for item in ordered[:500] if int(item["baseline_observation_count"]) > 0
        )
        / max(1, len(ordered[:500])),
        "one_row_support_ratio": sum(1 for item in ordered[:500] if int(item["row_count"]) <= 1)
        / max(1, len(ordered[:500])),
        "low_support_ratio": sum(1 for item in ordered[:500] if int(item["row_count"]) < 7)
        / max(1, len(ordered[:500])),
        "context_evidence_count_distribution": _num_dist(
            [item["context_evidence_count"] for item in ordered[:500]]
        ),
        "robust_z_distribution": _num_dist([item["robust_z"] for item in ordered[:500]]),
        "context_pressure": _context_pressure_summary(ordered[:500]),
    }


def _slice_stability(
    *,
    windows: list[dict[str, Any]],
    policies: dict[str, list[dict[str, Any]]],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    slice_sets = {
        "year": sorted({str(window["year"]) for window in windows}),
        "quarter": sorted({str(window["quarter"]) for window in windows}),
        "business_process": sorted({str(window["business_process"]) for window in windows}),
    }
    out: dict[str, Any] = {}
    for slice_kind, values in slice_sets.items():
        out[slice_kind] = {}
        for value in values:
            slice_windows = [
                window for window in windows if str(window.get(slice_kind)) == value
            ]
            if not slice_windows:
                continue
            slice_ids = {id(window) for window in slice_windows}
            out[slice_kind][value] = {
                policy: _policy_summary(
                    [window for window in ordered if id(window) in slice_ids],
                    truth_docs=truth_docs,
                    scenario_by_doc=scenario_by_doc,
                    phase1_reference=phase1_reference,
                )
                for policy, ordered in policies.items()
            }
    return out


def _selected_candidate_docs(windows: list[dict[str, Any]]) -> set[str]:
    docs: set[str] = set()
    for window in windows:
        raw_docs = window.get("_docs")
        if isinstance(raw_docs, set):
            docs.update(str(doc) for doc in raw_docs)
    return docs


def _rank_band_decomposition(
    policies: dict[str, list[dict[str, Any]]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for policy, ordered in policies.items():
        bands = {
            "TOP1_100": ordered[:100],
            "TOP101_500": ordered[100:500],
            "TOP501_1000": ordered[500:1000],
            "TOP1001_plus": ordered[1000:],
        }
        out[policy] = {
            name: _band_summary(
                band,
                truth_docs=truth_docs,
                scenario_by_doc=scenario_by_doc,
                phase1_reference=phase1_reference,
            )
            for name, band in bands.items()
        }
    return out


def _band_summary(
    windows: list[dict[str, Any]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    docs = _selected_candidate_docs(windows)
    selected_truth = docs & truth_docs
    aligned = {doc for doc in selected_truth if scenario_by_doc.get(doc) in _TS_ALIGNED_SCENARIOS}
    aligned_not_p1_top100 = aligned - phase1_reference["top100_docs"]
    return {
        "truth_docs": len(selected_truth),
        "ts_aligned_truth_docs": len(aligned),
        "ts_aligned_not_in_phase1_top100": len(aligned_not_p1_top100),
        "feature_distribution": _feature_distribution(
            [window for window in windows if window.get("_truth_docs")]
        ),
    }


def _feature_comparison(
    *,
    current_order: list[dict[str, Any]],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    aligned_windows = [
        window
        for window in current_order
        if {
            scenario_by_doc.get(doc)
            for doc in set(window.get("_docs", set())) & truth_docs
        }
        & _TS_ALIGNED_SCENARIOS
    ]
    return {
        "top100_current_cases": _feature_distribution(current_order[:100]),
        "top500_current_cases": _feature_distribution(current_order[:500]),
        "ts_aligned_truth_cases": _feature_distribution(aligned_windows),
        "direction_notes": _feature_direction_notes(current_order, aligned_windows),
    }


def _feature_distribution(windows: list[dict[str, Any]]) -> dict[str, Any]:
    features = (
        "period_end_day_offset",
        "period_end_lift",
        "robust_z",
        "expected_count",
        "baseline_observation_count",
        "row_count",
        "subject_activity_rank",
        "subject_frequency_context",
        "context_evidence_count",
        "rarity_context_count",
    )
    out = {feature: _num_dist([window.get(feature) for window in windows]) for feature in features}
    for feature in (
        "period_end_context",
        "amount_tail_context",
        "manual_or_adjustment_context",
        "after_hours_or_weekend_context",
        "round_amount_context",
    ):
        out[feature] = {"share": _bool_share(windows, feature), "count": len(windows)}
    return out


def _bool_share(windows: list[dict[str, Any]], field: str) -> float:
    if not windows:
        return 0.0
    return sum(1 for window in windows if bool(window.get(field))) / len(windows)


def _feature_direction_notes(
    current_order: list[dict[str, Any]],
    aligned_windows: list[dict[str, Any]],
) -> dict[str, Any]:
    top100 = current_order[:100]
    return {
        "round_amount_lower_in_aligned": _bool_share(aligned_windows, "round_amount_context")
        < _bool_share(top100, "round_amount_context"),
        "amount_tail_lower_in_aligned": _bool_share(aligned_windows, "amount_tail_context")
        < _bool_share(top100, "amount_tail_context"),
        "manual_or_adjustment_present_in_aligned": _bool_share(
            aligned_windows,
            "manual_or_adjustment_context",
        )
        > 0,
    }


def _proxy_diagnostics(
    policies: dict[str, list[dict[str, Any]]],
    *,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    phase1_reference: dict[str, Any],
) -> dict[str, Any]:
    broad = policies["broad_companion_reference_surface"]
    top500 = broad[:500]
    novel_windows = [
        window
        for window in top500
        if (set(window.get("_docs", set())) & truth_docs) - phase1_reference["top100_docs"]
    ]
    aligned_windows = [
        window
        for window in novel_windows
        if {
            scenario_by_doc.get(doc)
            for doc in (set(window.get("_docs", set())) & truth_docs)
            - phase1_reference["top100_docs"]
        }
        & _TS_ALIGNED_SCENARIOS
    ]
    non_aligned_windows = [window for window in novel_windows if window not in aligned_windows]
    return {
        "broad_top500_novel_window_count": len(novel_windows),
        "aligned_novel_window_count": len(aligned_windows),
        "non_aligned_novel_window_count": len(non_aligned_windows),
        "aligned_proxy_profile": _feature_distribution(aligned_windows),
        "non_aligned_proxy_profile": _feature_distribution(non_aligned_windows),
        "proxy_read": {
            "extreme_amount_zscore_can_overrepresent_non_ts": (
                _bool_share(non_aligned_windows, "amount_tail_context")
                > _bool_share(aligned_windows, "amount_tail_context")
            ),
            "round_amount_can_overrepresent_non_ts": (
                _bool_share(non_aligned_windows, "round_amount_context")
                > _bool_share(aligned_windows, "round_amount_context")
            ),
        },
    }


def _decision_payload(batches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fixed5 = batches["fixed5_normalcal5"]["policies"]
    candidates = (
        "timing_primary_context_surface",
        "supported_period_end_anomaly_surface",
        "ts_primary_conservative_surface",
    )
    stability = _fixed5_slice_stability_summary(batches["fixed5_normalcal5"])
    stable_candidates = [
        name
        for name in candidates
        if stability["by_policy"][name]["top500_eligible_nonempty_rate"] >= 1.0
    ]
    top100_candidates = [
        name
        for name in candidates
        if stability["by_policy"][name]["year_top100_eligible_nonempty_rate"] >= 1.0
    ]
    best_ts = max(
        candidates,
        key=lambda name: (
            fixed5[name]["topn"]["100"]["ts_aligned_not_in_phase1_top100"],
            fixed5[name]["topn"]["500"]["ts_aligned_not_in_phase1_top100"],
        ),
    )
    top500_allowed = bool(stable_candidates)
    return {
        "primary_validation_dataset": PRIMARY_VALIDATION_DATASET,
        "excluded_validation_datasets": list(EXCLUDED_VALIDATION_DATASETS),
        "exclusion_reason": EXCLUSION_REASON,
        "best_ts_primary_candidate": best_ts,
        "best_broad_companion_candidate": "broad_companion_reference_surface",
        "fixed5_slice_stability": stability,
        "top100_adoption_allowed": bool(top100_candidates),
        "top500_companion_allowed": top500_allowed,
        "production_adoption": False,
        "adoption_blocker": (
            "Diagnostic-only validation shows TOP500 companion potential, but production "
            "defaults require UI/export burden review and non-broken external fixture validation."
        ),
        "recommended_product_role": (
            "Use TS-primary candidate as diagnostic TOP500 companion candidate only; "
            "do not use broad companion as TS-primary default."
        ),
        "recommended_next_action": (
            "Validate fixed5-compatible slices in UI/export review burden flow."
        ),
    }


def _fixed5_slice_stability_summary(batch_payload: dict[str, Any]) -> dict[str, Any]:
    slice_payload = batch_payload["slice_stability"]
    current = batch_payload["policies"]["current_native_ts_order"]
    current_top100 = current["topn"]["100"]["ts_aligned_not_in_phase1_top100"]
    current_top500 = current["topn"]["500"]["ts_aligned_not_in_phase1_top100"]
    by_policy: dict[str, Any] = {}
    for policy in PRIMARY_POLICIES:
        top100_pass = 0
        top500_pass = 0
        total = 0
        eligible = 0
        year_eligible = 0
        year_top100_nonempty = 0
        nonempty_top100 = 0
        nonempty_top500 = 0
        for slice_group in slice_payload.values():
            for slice_name, slice_row in slice_group.items():
                total += 1
                row = slice_row[policy]["topn"]
                broad_row = slice_row["broad_companion_reference_surface"]["topn"]
                is_eligible = broad_row["1000"]["ts_aligned_not_in_phase1_top100"] > 0
                top100_value = row["100"]["ts_aligned_not_in_phase1_top100"]
                top500_value = row["500"]["ts_aligned_not_in_phase1_top100"]
                top100_pass += int(top100_value >= current_top100)
                top500_pass += int(top500_value >= current_top500)
                nonempty_top100 += int(top100_value > 0)
                nonempty_top500 += int(top500_value > 0)
                eligible += int(is_eligible)
                if is_eligible and slice_name in {"2022", "2023", "2024"}:
                    year_eligible += 1
                    year_top100_nonempty += int(top100_value > 0)
        by_policy[policy] = {
            "slice_count": total,
            "eligible_slice_count": eligible,
            "top100_slice_pass_rate": top100_pass / max(1, total),
            "top500_slice_pass_rate": top500_pass / max(1, total),
            "top100_nonempty_slice_rate": nonempty_top100 / max(1, total),
            "top500_nonempty_slice_rate": nonempty_top500 / max(1, total),
            "top100_eligible_nonempty_rate": nonempty_top100 / max(1, eligible),
            "top500_eligible_nonempty_rate": nonempty_top500 / max(1, eligible),
            "year_top100_eligible_nonempty_rate": year_top100_nonempty
            / max(1, year_eligible),
        }
    return {
        "current_top100_ts_aligned_not_phase1_top100": current_top100,
        "current_top500_ts_aligned_not_phase1_top100": current_top500,
        "by_policy": by_policy,
    }


def main() -> int:
    started = time.perf_counter()
    batches = {spec.name: _run_batch(spec) for spec in BATCHES}
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "diagnostic_scope": "TS family Phase 5 fixed5-compatible primary surface diagnostic",
        "primary_validation_dataset": PRIMARY_VALIDATION_DATASET,
        "excluded_validation_datasets": list(EXCLUDED_VALIDATION_DATASETS),
        "exclusion_reason": EXCLUSION_REASON,
        "guardrails": {
            "truth_label_used_for_policy_order": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "scenario_label_used_for_policy_order": False,
            "production_gate_ranking_fusion_changed": False,
            "phase1_ranking_changed": False,
            "broad_companion_and_ts_primary_separated": True,
        },
        "top_ns": list(TOP_NS),
        "ts_aligned_scenarios": sorted(_TS_ALIGNED_SCENARIOS),
        "candidate_descriptions": {
            "timing_primary_context_surface": (
                "robust_z, timing context, and period-end lift; one-row, round, "
                "and extreme amount windows are demoted"
            ),
            "supported_period_end_anomaly_surface": (
                "period-end windows remain eligible when baseline support, lift, "
                "and robust_z are present"
            ),
            "ts_primary_conservative_surface": (
                "lower-burden timing surface that prioritizes support, non-round "
                "context, and cross-batch stability"
            ),
            "broad_companion_reference_surface": (
                "broad TS-derived companion/export reference, not TS-primary"
            ),
        },
        "batches": batches,
        "decision": _decision_payload(batches),
    }
    leak_counts = [batch["raw_identifier_leak_check"] for batch in batches.values()]
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


if __name__ == "__main__":
    raise SystemExit(main())
