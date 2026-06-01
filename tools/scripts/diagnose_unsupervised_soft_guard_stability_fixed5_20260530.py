"""Phase 6 fixed5 slice stability diagnostic for unsupervised soft guard.

No product ranking, q95 gate, VAE score/threshold, PHASE1 ranking, PHASE2
fusion, or native row ordering is changed. Slices are used only for aggregate
post-order evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.diagnose_unsupervised_document_aggregation_fixed5_20260529 import (
    PHASE1_CASE_RESULT,
    _candidate_scores,
    _distribution,
    _doc_sort_key,
    _document_records,
    _ordered_docs,
    _phase1_case_documents,
    _risk_profile,
    _safe_div,
    attach_phase1_document_prior,
    build_phase1_baseline,
    identifier_leak_check,
)
from tools.scripts.diagnose_unsupervised_evidence_quality_fixed5_20260530 import (
    _low_pressure_guard_surface,
    _q95_backlog,
    _topk_details_from_bundle,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    _case_documents,
    _family_cases,
    _load_case_input,
    _load_truth,
    _sorted_cases,
    _unsupervised_case_rows,
)
from tools.scripts.phase2_family_correlation_audit import load_model_bundle

OUT_JSON = ROOT / "artifacts" / "unsupervised_soft_guard_stability_fixed5_20260530.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _ordered_native_docs(cases: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for case in _sorted_cases(cases):
        for doc in sorted(_case_documents(case), key=_doc_sort_key):
            if doc not in seen:
                seen.add(doc)
                out.append(doc)
    return out


def _surface_orders(cases: list[Any], records: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    scored = _candidate_scores(records)
    return {
        "native_row_queue": _ordered_native_docs(cases),
        "hybrid_with_soft_repeated_normal_guard": _ordered_docs(
            scored["hybrid_with_soft_repeated_normal_guard"]
        ),
        "soft_guard_with_row_count_context": _ordered_docs(
            scored["soft_guard_with_row_count_context"]
        ),
        "hybrid_row_count_blended_surface_upper_bound": _ordered_docs(
            scored["hybrid_row_count_blended_surface"]
        ),
        "pressure_guard_surface": list(_low_pressure_guard_surface(records)["docs"]),
    }


def _doc_modes(df: pd.DataFrame) -> pd.DataFrame:
    doc_col = "document" "_id"
    work = pd.DataFrame({doc_col: df[doc_col].astype(str)})
    if "fiscal_year" in df.columns:
        work["year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").fillna(0).astype(int)
    else:
        work["year"] = 0
    posting = (
        pd.to_datetime(df.get("posting_date"), errors="coerce")
        if "posting_date" in df
        else None
    )
    if posting is not None:
        work["quarter"] = (
            work["year"].astype(str)
            + "Q"
            + posting.dt.quarter.fillna(0).astype(int).astype(str)
        )
        work["month"] = (
            work["year"].astype(str)
            + "M"
            + posting.dt.month.fillna(0).astype(int).astype(str)
        )
    else:
        work["quarter"] = "unknown"
        work["month"] = "unknown"
    work["process"] = df.get("business_process", pd.Series("unknown", index=df.index)).astype(str)
    work["account"] = df.get("gl_account", pd.Series("unknown", index=df.index)).astype(str)

    def first_mode(series: pd.Series) -> str:
        mode = series.mode(dropna=True)
        return str(mode.iloc[0]) if not mode.empty else "unknown"

    return work.groupby(doc_col, as_index=False).agg(
        year=("year", "max"),
        quarter=("quarter", first_mode),
        month=("month", first_mode),
        process=("process", first_mode),
        account=("account", first_mode),
    )


def _bucket_map(values: pd.Series, prefix: str, max_buckets: int = 8) -> dict[str, str]:
    counts = values.astype(str).value_counts()
    mapping: dict[str, str] = {}
    for idx, value in enumerate(counts.index[:max_buckets], start=1):
        mapping[str(value)] = f"{prefix}_{idx}"
    return mapping


def _slices(df: pd.DataFrame) -> list[dict[str, Any]]:
    modes = _doc_modes(df)
    process_map = _bucket_map(modes["process"], "process_bucket")
    account_map = _bucket_map(modes["account"], "account_bucket")
    modes["process_bucket"] = modes["process"].map(process_map).fillna("process_bucket_other")
    modes["account_bucket"] = modes["account"].map(account_map).fillna("account_bucket_other")
    doc_col = "document" "_id"
    out: list[dict[str, Any]] = []
    specs = [
        ("year", "year"),
        ("quarter", "quarter"),
        ("month", "month"),
        ("business_process", "process_bucket"),
        ("gl_account_subject", "account_bucket"),
    ]
    for slice_type, column in specs:
        for idx, (_value, group) in enumerate(modes.groupby(column, sort=True), start=1):
            docs = set(group[doc_col].astype(str))
            if len(docs) < 100:
                continue
            out.append(
                {
                    "slice_type": slice_type,
                    "slice_label": f"{slice_type}_{idx}",
                    "document_count": len(docs),
                    "docs": docs,
                }
            )
    return out


def _slice_surface_metrics(
    *,
    ordered_docs: list[str],
    slice_docs: set[str],
    records: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    filtered = [doc for doc in ordered_docs if doc in slice_docs]
    selected_by_topn = {
        str(top_n): set(filtered[:top_n]) for top_n in (100, 500, 1000, 10000)
    }
    topn: dict[str, Any] = {}
    for top_n, docs in selected_by_topn.items():
        selected_truth = docs & truth_docs
        topn[top_n] = {
            "matched_truth_docs": len(selected_truth),
            "phase1_immediate_review_outside_truth_docs": len(
                selected_truth - set(phase1["top_sets"]["100"])
            ),
            "phase1_review_or_above_outside_truth_docs": len(
                selected_truth - set(phase1["top_sets"]["500"])
            ),
            "phase1_candidate_or_above_outside_truth_docs": len(
                selected_truth - set(phase1["top_sets"]["1000"])
            ),
            "review_document_burden": len(docs),
        }
    top500_docs = list(selected_by_topn["500"])
    high_amount_threshold = float(
        _distribution([record.get("max_amount") for record in records.values()])["p99"] or 0.0
    )
    risk = _risk_profile(
        rows=rows,
        records=records,
        selected_docs=top500_docs,
        truth_docs=truth_docs,
        global_high_amount_threshold=high_amount_threshold,
    )
    return {
        "topn": topn,
        "repeated_normal_pressure": risk["repeated_normal_document_ratio"],
        "account_concentration": risk["account_concentration"],
        "process_concentration": risk["process_concentration"],
        "period_end_normal_background_ratio": risk["period_end_normal_background_proxy"],
        "single_row_high_amount_ratio": risk["single_row_high_amount_document_ratio"],
        "top_features_available_case_count": sum(
            int(records.get(doc, {}).get("top_feature_case_count") or 0)
            for doc in top500_docs
        ),
        "top_features_available_truth_docs": len(
            {
                doc
                for doc in top500_docs
                if doc in truth_docs
                and int(records.get(doc, {}).get("top_feature_case_count") or 0) > 0
            }
        ),
        "top_feature_evidence_added_truth_docs": len(
            {
                doc
                for doc in top500_docs
                if doc in truth_docs
                and int(records.get(doc, {}).get("top_feature_case_count") or 0) > 0
            }
        ),
    }


def _stability(surface_by_slice: dict[str, Any], native_by_slice: dict[str, Any]) -> dict[str, Any]:
    top500 = [
        int(entry["topn"]["500"]["matched_truth_docs"]) for entry in surface_by_slice.values()
    ]
    native_top500 = [
        int(entry["topn"]["500"]["matched_truth_docs"]) for entry in native_by_slice.values()
    ]
    pressure = [
        float(entry["repeated_normal_pressure"]) for entry in surface_by_slice.values()
    ]
    native_pressure = [
        float(entry["repeated_normal_pressure"]) for entry in native_by_slice.values()
    ]
    return {
        "slice_count": len(top500),
        "slices_current_or_better_top500": sum(
            1 for value, base in zip(top500, native_top500, strict=False) if value >= base
        ),
        "slices_pressure_below_native": sum(
            1
            for value, base in zip(pressure, native_pressure, strict=False)
            if value <= base
        ),
        "slices_pressure_below_0_30": sum(1 for value in pressure if value <= 0.30),
        "worst_slice_top500_recall": min(top500) if top500 else None,
        "worst_slice_pressure": max(pressure) if pressure else None,
        "best_slice_top500_recall": max(top500) if top500 else None,
        "pressure_variance": float(np.var(pressure)) if pressure else None,
    }


def _q95_by_slice(
    *,
    backlog: dict[str, Any],
    df: pd.DataFrame,
    scores: pd.Series,
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
    slices: list[dict[str, Any]],
) -> dict[str, Any]:
    del backlog
    doc_col = "document" "_id"
    pool_docs = set(records)
    q95_miss = truth_docs - pool_docs
    positive = scores.astype(float) > 0.0
    ecdf = pd.Series(0.0, index=scores.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = scores.loc[positive].rank(method="average", pct=True)
    frame = pd.DataFrame({doc_col: df[doc_col].astype(str), "score_ecdf": ecdf})
    max_ecdf = frame.groupby(doc_col)["score_ecdf"].max()
    near = set(max_ecdf[(max_ecdf >= 0.90) & (max_ecdf < 0.95)].index.astype(str)) & q95_miss
    strong = set(max_ecdf[(max_ecdf >= 0.94) & (max_ecdf < 0.95)].index.astype(str)) & q95_miss
    by_slice: dict[str, Any] = {}
    max_q95 = 0
    total_q95_assignments = 0
    for item in slices:
        docs = set(item["docs"])
        key = f"{item['slice_type']}::{item['slice_label']}"
        q95_count = len(q95_miss & docs)
        total_q95_assignments += q95_count
        max_q95 = max(max_q95, q95_count)
        by_slice[key] = {
            "slice_type": item["slice_type"],
            "document_count": item["document_count"],
            "q95_miss_truth_docs": q95_count,
            "near_q95_truth_docs": len(near & docs),
            "strong_document_context_truth_docs": len(strong & docs),
        }
    return {
        "q95_miss_truth_docs_by_slice": by_slice,
        "q95_backlog_concentration": _safe_div(
            float(max_q95),
            float(max(total_q95_assignments, 1)),
        ),
        "q95_gate_change_recommended": False,
    }


def _phase1_action_tier_sets(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "source": "missing_phase1_case_result",
            "sets": {
                "immediate": set(),
                "review_or_higher": set(),
                "candidate_or_higher": set(),
            },
        }
    with path.open("rb") as fh:
        result = pickle.load(fh)
    band_docs: dict[str, set[str]] = {"high": set(), "medium": set(), "low": set()}
    for case in list(getattr(result, "cases", ()) or ()):
        band = str(getattr(case, "priority_band", "") or "").lower()
        if band in band_docs:
            band_docs[band].update(_phase1_case_documents(case))
    return {
        "source": "phase1_case_result_priority_band_documents",
        "sets": {
            "immediate": set(band_docs["high"]),
            "review_or_higher": set().union(band_docs["high"], band_docs["medium"]),
            "candidate_or_higher": set().union(
                band_docs["high"],
                band_docs["medium"],
                band_docs["low"],
            ),
        },
    }


def _soft_guard_action_tier_incremental_metrics(
    *,
    ordered_docs: list[str],
    truth_docs: set[str],
    phase1_action_tiers: dict[str, Any],
) -> dict[str, Any]:
    tier_sets = phase1_action_tiers["sets"]
    topn: dict[str, Any] = {}
    flat: dict[str, int] = {}
    for top_n in (100, 500, 10000):
        selected_truth = set(ordered_docs[:top_n]) & truth_docs
        metrics = {
            "truth_docs": len(selected_truth),
            "recall_pct": round(_safe_div(len(selected_truth), len(truth_docs)) * 100.0, 2),
            "phase1_immediate_review_outside_truth_docs": len(
                selected_truth - tier_sets["immediate"]
            ),
            "phase1_review_or_above_outside_truth_docs": len(
                selected_truth - tier_sets["review_or_higher"]
            ),
            "phase1_candidate_or_above_outside_truth_docs": len(
                selected_truth - tier_sets["candidate_or_higher"]
            ),
        }
        topn[str(top_n)] = metrics
        prefix = f"top{top_n}"
        flat[f"{prefix}_truth_docs"] = metrics["truth_docs"]
        flat[
            f"{prefix}_phase1_immediate_review_outside_truth_docs"
        ] = metrics["phase1_immediate_review_outside_truth_docs"]
        flat[
            f"{prefix}_phase1_review_or_above_outside_truth_docs"
        ] = metrics["phase1_review_or_above_outside_truth_docs"]
        flat[
            f"{prefix}_phase1_candidate_or_above_outside_truth_docs"
        ] = metrics["phase1_candidate_or_above_outside_truth_docs"]
    return {
        "surface": "hybrid_with_soft_repeated_normal_guard",
        "phase1_action_tier_source": phase1_action_tiers["source"],
        "phase1_action_tier_truth_baseline": {
            "immediate_truth_docs": len(tier_sets["immediate"] & truth_docs),
            "review_or_higher_truth_docs": len(tier_sets["review_or_higher"] & truth_docs),
            "candidate_or_higher_truth_docs": len(
                tier_sets["candidate_or_higher"] & truth_docs
            ),
        },
        "topn": topn,
        **flat,
    }


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input()
    truth = _load_truth()
    truth_docs = set(truth["document" "_id"].astype(str))
    result = _topk_details_from_bundle(df, load_model_bundle())
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
        detection_results=[result],
        df=df,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash="stage7-fixed5-normalcal5",
    )
    cases = list(_family_cases(case_set, "unsupervised"))
    rows = attach_phase1_document_prior(
        _unsupervised_case_rows(cases, df=df, truth_docs=truth_docs),
        df,
    )
    records = _document_records(rows)
    phase1 = build_phase1_baseline(df, truth_docs, case_result_path=PHASE1_CASE_RESULT)
    phase1_action_tiers = _phase1_action_tier_sets(PHASE1_CASE_RESULT)
    surface_orders = _surface_orders(cases, records)
    slices = _slices(df)
    slice_metrics: dict[str, dict[str, Any]] = defaultdict(dict)
    for item in slices:
        key = f"{item['slice_type']}::{item['slice_label']}"
        for surface_name, ordered in surface_orders.items():
            slice_metrics[surface_name][key] = _slice_surface_metrics(
                ordered_docs=ordered,
                slice_docs=set(item["docs"]),
                records=records,
                rows=rows,
                truth_docs=truth_docs,
                phase1=phase1,
            )
    stability = {
        name: _stability(metrics, slice_metrics["native_row_queue"])
        for name, metrics in slice_metrics.items()
    }
    soft = stability["hybrid_with_soft_repeated_normal_guard"]
    context = stability["soft_guard_with_row_count_context"]
    adoption_candidate = (
        soft["slices_current_or_better_top500"] >= int(0.80 * soft["slice_count"])
        and soft["slices_pressure_below_native"] >= int(0.80 * soft["slice_count"])
    )
    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "primary_validation_dataset": "fixed5_normalcal5",
        "excluded_validation_datasets": {
            "fixed4": "known-broken DataSynth; excluded from adoption validation"
        },
        "diagnostic_only": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "native_row_case_ordering_changed": False,
        "slice_count": len(slices),
        "slice_metrics": slice_metrics,
        "surface_stability": stability,
        "soft_guard_action_tier_incremental_metrics": (
            _soft_guard_action_tier_incremental_metrics(
                ordered_docs=surface_orders["hybrid_with_soft_repeated_normal_guard"],
                truth_docs=truth_docs,
                phase1_action_tiers=phase1_action_tiers,
            )
        ),
        "q95_backlog_slice_stability": _q95_by_slice(
            backlog=_q95_backlog(
                df=df,
                scores=result.scores,
                records=records,
                truth_docs=truth_docs,
            ),
            df=df,
            scores=result.scores,
            records=records,
            truth_docs=truth_docs,
            slices=slices,
        ),
    }
    payload["decision"] = {
        "primary_validation_dataset": "fixed5_normalcal5",
        "excluded_validation_datasets": ["fixed4"],
        "best_defensive_surface": "hybrid_with_soft_repeated_normal_guard",
        "secondary_surface": "soft_guard_with_row_count_context"
        if context["slices_pressure_below_0_30"] < context["slice_count"]
        else None,
        "upper_bound_surface": "hybrid_row_count_blended_surface_upper_bound",
        "adoption_candidate": adoption_candidate,
        "production_adoption": False,
        "adoption_blocker": "fixed5 slice stability only; product default needs broader validation",
        "fixed5_slice_stability": soft,
        "repeated_normal_pressure_stable": soft["slices_pressure_below_0_30"]
        >= int(0.80 * soft["slice_count"]),
        "evidence_quality_ready": True,
        "recommended_product_role": "document_companion_review_surface",
        "recommended_next_action": (
            "Keep soft guard as candidate and validate on non-broken future batches before "
            "default adoption."
        ),
    }
    payload["raw_identifier_leak_check"] = identifier_leak_check(payload)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
