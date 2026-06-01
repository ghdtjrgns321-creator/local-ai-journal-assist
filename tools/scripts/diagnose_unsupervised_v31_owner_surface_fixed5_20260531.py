"""VAE/unsupervised v3.1 owner-role surface diagnostic on fixed5.

Diagnostic-only. This reuses the existing deterministic VAE measurement path
and re-reads surfaces against the canonical v3.1 responsibility-map roles:
unsupervised primary (fictitious-entry statistical primary) and unsupervised
companion. It does not change q95 gate, VAE score/threshold, PHASE1 ranking, or
PHASE2 fusion. The product family-list display ordering now adopts the soft
document review priority surface.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.diagnose_unsupervised_document_aggregation_fixed5_20260529 import (
    PHASE1_CASE_RESULT,
    _candidate_scores,
    _document_records,
    _ordered_docs,
    _risk_profile,
    attach_phase1_document_prior,
    build_phase1_baseline,
    identifier_leak_check,
)
from tools.scripts.diagnose_unsupervised_evidence_quality_fixed5_20260530 import (
    _low_pressure_guard_surface,
    _topk_details_from_bundle,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    DATASET_NAME,
    _case_documents,
    _family_cases,
    _load_case_input,
    _sorted_cases,
    _unsupervised_case_rows,
)
from tools.scripts.phase2_family_correlation_audit import load_model_bundle

_V31_RESPONSIBILITY = import_module(
    "tools.scripts."
    "measure_phase2_family_responsibility_recall_v31_fixed5_ownermeta_ic_20260530"
)
V31_TRUTH_PATH = _V31_RESPONSIBILITY.TRUTH_PATH
_owner_masks = _V31_RESPONSIBILITY._owner_masks

OUT_JSON = ROOT / "artifacts" / "unsupervised_v31_owner_surface_fixed5_20260531.json"
TOP_N_VALUES = (100, 500, 1000, 10000)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _load_v31_truth() -> pd.DataFrame:
    truth = pd.read_csv(V31_TRUTH_PATH)
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _owner_doc_sets(truth: pd.DataFrame) -> dict[str, set[str]]:
    masks = _owner_masks(truth)
    return {
        "primary": set(
            truth.loc[masks["unsupervised"]["primary"], "document_id"].astype(str)
        ),
        "companion": set(
            truth.loc[masks["unsupervised"]["context"], "document_id"].astype(str)
        ),
    }


def _ordered_native_docs(cases: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for case in _sorted_cases(list(cases)):
        for doc in sorted(_case_documents(case), key=str):
            if doc not in seen:
                seen.add(doc)
                out.append(doc)
    return out


def _surface_orders(cases: list[Any], records: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    scored = _candidate_scores(records)
    soft_guard = _ordered_docs(scored["hybrid_with_soft_repeated_normal_guard"])
    soft_context = _ordered_docs(scored["soft_guard_with_row_count_context"])
    return {
        "native_row_queue": _ordered_native_docs(cases),
        "document_score_with_row_count_penalty": _ordered_docs(
            scored["document_score_with_row_count_penalty"]
        ),
        "hybrid_with_soft_repeated_normal_guard": soft_guard,
        "soft_guard_with_row_count_context": soft_context,
        "soft_guard_context_top100_probe": _top100_context_probe(
            soft_guard=soft_guard,
            soft_context=soft_context,
        ),
        "hybrid_row_count_blended_surface_upper_bound": _ordered_docs(
            scored["hybrid_row_count_blended_surface"]
        ),
        "soft_guard_pressure_guard_surface": list(_low_pressure_guard_surface(records)["docs"]),
    }


def _top100_context_probe(
    *,
    soft_guard: list[str],
    soft_context: list[str],
) -> list[str]:
    """Bounded diagnostic-only TOP100 context probe.

    Why: v3.1 primary recall has many target documents in the default soft-guard
    TOP500 but outside TOP100. This probe checks whether the existing
    row-count context surface can improve the first review page without changing
    q95 gating, score thresholds, case generation, or the broader soft-guard
    queue. It is not a product ordering policy.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for doc in [*soft_context[:100], *soft_guard]:
        if doc in seen:
            continue
        seen.add(doc)
        ordered.append(doc)
    return ordered


def _topn_role_metrics(
    ordered_docs: list[str],
    *,
    role_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for top_n in TOP_N_VALUES:
        selected = set(ordered_docs[:top_n])
        matched = selected & role_docs
        out[str(top_n)] = {
            "matched_docs": len(matched),
            "recall": None if not role_docs else len(matched) / len(role_docs),
            "phase1_immediate_review_outside_docs": len(
                matched - set(phase1["top_sets"]["100"])
            ),
            "phase1_review_or_above_outside_docs": len(
                matched - set(phase1["top_sets"]["500"])
            ),
            "phase1_candidate_or_above_outside_docs": len(
                matched - set(phase1["top_sets"]["1000"])
            ),
            "review_document_burden": min(top_n, len(ordered_docs)),
        }
    return out


def _pressure(
    ordered_docs: list[str],
    *,
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    role_docs: set[str],
) -> dict[str, Any]:
    top500 = ordered_docs[:500]
    max_amounts = [
        float(record.get("max_amount") or 0.0) for record in records.values()
    ]
    threshold = float(pd.Series(max_amounts).quantile(0.99)) if max_amounts else 0.0
    risk = _risk_profile(
        rows=rows,
        records=records,
        selected_docs=top500,
        truth_docs=role_docs,
        global_high_amount_threshold=threshold,
    )
    return {
        "repeated_normal_pressure": risk["repeated_normal_document_ratio"],
        "account_concentration": risk["account_concentration"],
        "process_concentration": risk["process_concentration"],
        "period_end_normal_background_ratio": risk["period_end_normal_background_proxy"],
        "single_row_high_amount_normal_proxy": risk[
            "normal_single_row_high_amount_proxy"
        ],
        "top_features_availability": risk["top_features_presence_ratio"],
        "review_burden": risk["document_count"],
    }


def _role_surface_metrics(
    surface_orders: dict[str, list[str]],
    *,
    role_docs: set[str],
    phase1: dict[str, Any],
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "topn": _topn_role_metrics(ordered, role_docs=role_docs, phase1=phase1),
            "top500_pressure": _pressure(
                ordered,
                rows=rows,
                records=records,
                role_docs=role_docs,
            ),
        }
        for name, ordered in surface_orders.items()
    }


def _rank_band_metrics(
    ordered_docs: list[str],
    *,
    role_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    bands = {
        "top100": (0, 100),
        "rank101_250": (100, 250),
        "rank251_500": (250, 500),
        "rank501_1000": (500, 1000),
        "rank1001_10000": (1000, 10000),
        "outside_top10000_or_not_candidate": (10000, None),
    }
    out: dict[str, dict[str, Any]] = {}
    ranked_role_docs: set[str] = set()
    for band, (start, end) in bands.items():
        if end is None:
            docs = role_docs - ranked_role_docs
        else:
            selected = set(ordered_docs[start:end])
            docs = selected & role_docs
            ranked_role_docs.update(docs)
        out[band] = {
            "matched_docs": len(docs),
            "phase1_immediate_review_outside_docs": len(
                docs - set(phase1["top_sets"]["100"])
            ),
            "phase1_review_or_above_outside_docs": len(
                docs - set(phase1["top_sets"]["500"])
            ),
            "phase1_candidate_or_above_outside_docs": len(
                docs - set(phase1["top_sets"]["1000"])
            ),
        }
    return out


def _primary_top100_gap_analysis(
    *,
    surface_orders: dict[str, list[str]],
    primary_docs: set[str],
    phase1: dict[str, Any],
    primary_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    default_name = "hybrid_with_soft_repeated_normal_guard"
    default_topn = primary_metrics[default_name]["topn"]
    probe_name = "soft_guard_context_top100_probe"
    probe_topn = primary_metrics[probe_name]["topn"]
    context_topn = primary_metrics["soft_guard_with_row_count_context"]["topn"]
    upper_topn = primary_metrics["hybrid_row_count_blended_surface_upper_bound"]["topn"]
    return {
        "default_surface": default_name,
        "default_rank_bands": _rank_band_metrics(
            surface_orders[default_name],
            role_docs=primary_docs,
            phase1=phase1,
        ),
        "top500_but_below_top100_docs": (
            int(default_topn["500"]["matched_docs"])
            - int(default_topn["100"]["matched_docs"])
        ),
        "top100_gap_classification": "rank_band_separation_not_candidate_pool_absence",
        "bounded_diagnostic_candidates": {
            probe_name: {
                "top100_matched_docs": probe_topn["100"]["matched_docs"],
                "top500_matched_docs": probe_topn["500"]["matched_docs"],
                "top100_lift_vs_default": (
                    int(probe_topn["100"]["matched_docs"])
                    - int(default_topn["100"]["matched_docs"])
                ),
                "top500_lift_vs_default": (
                    int(probe_topn["500"]["matched_docs"])
                    - int(default_topn["500"]["matched_docs"])
                ),
                "production_adoption": False,
                "reason": (
                    "diagnostic-only bounded TOP100 context probe; it reuses "
                    "runtime-observable row-count context but is not cross-batch "
                    "validated as a default policy"
                ),
            },
            "soft_guard_with_row_count_context": {
                "top100_matched_docs": context_topn["100"]["matched_docs"],
                "top500_matched_docs": context_topn["500"]["matched_docs"],
                "top100_lift_vs_default": (
                    int(context_topn["100"]["matched_docs"])
                    - int(default_topn["100"]["matched_docs"])
                ),
                "top500_lift_vs_default": (
                    int(context_topn["500"]["matched_docs"])
                    - int(default_topn["500"]["matched_docs"])
                ),
                "production_adoption": False,
                "reason": (
                    "coverage improves slightly but repeated-normal pressure "
                    "is higher than default soft guard"
                ),
            },
            "hybrid_row_count_blended_surface_upper_bound": {
                "top100_matched_docs": upper_topn["100"]["matched_docs"],
                "top500_matched_docs": upper_topn["500"]["matched_docs"],
                "top100_lift_vs_default": (
                    int(upper_topn["100"]["matched_docs"])
                    - int(default_topn["100"]["matched_docs"])
                ),
                "top500_lift_vs_default": (
                    int(upper_topn["500"]["matched_docs"])
                    - int(default_topn["500"]["matched_docs"])
                ),
                "production_adoption": False,
                "reason": "coverage upper-bound; pressure is too high for default adoption",
            },
        },
        "no_fitting_constraints": {
            "truth_label_used_for_ordering": False,
            "scenario_or_owner_metadata_used_for_ordering": False,
            "phase1_rank_used_for_ordering": False,
            "top_features_used_for_ordering": False,
            "q95_gate_changed": False,
            "vae_score_or_threshold_changed": False,
        },
    }


def _role_summary(role_docs: set[str], phase1: dict[str, Any]) -> dict[str, Any]:
    return {
        "truth_docs": len(role_docs),
        "phase1_immediate_review_covered_docs": len(
            role_docs & set(phase1["top_sets"]["100"])
        ),
        "phase1_review_or_above_covered_docs": len(
            role_docs & set(phase1["top_sets"]["500"])
        ),
        "phase1_candidate_or_above_covered_docs": len(
            role_docs & set(phase1["top_sets"]["1000"])
        ),
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_case_input()
    v31_truth = _load_v31_truth()
    role_docs = _owner_doc_sets(v31_truth)
    all_role_docs = set().union(*role_docs.values())

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
        _unsupervised_case_rows(cases, df=df, truth_docs=all_role_docs),
        df,
    )
    records = _document_records(rows)
    phase1 = build_phase1_baseline(df, all_role_docs, case_result_path=PHASE1_CASE_RESULT)
    surface_orders = _surface_orders(cases, records)

    primary_metrics = _role_surface_metrics(
        surface_orders,
        role_docs=role_docs["primary"],
        phase1=phase1,
        rows=rows,
        records=records,
    )
    companion_metrics = _role_surface_metrics(
        surface_orders,
        role_docs=role_docs["companion"],
        phase1=phase1,
        rows=rows,
        records=records,
    )
    soft_primary = primary_metrics["hybrid_with_soft_repeated_normal_guard"]["topn"][
        "500"
    ]["matched_docs"]
    soft_companion = companion_metrics["hybrid_with_soft_repeated_normal_guard"]["topn"][
        "500"
    ]["matched_docs"]
    primary_native = primary_metrics["native_row_queue"]
    primary_soft = primary_metrics["hybrid_with_soft_repeated_normal_guard"]
    companion_native = companion_metrics["native_row_queue"]
    companion_soft = companion_metrics["hybrid_with_soft_repeated_normal_guard"]
    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "responsibility_map": "v3.1",
        "diagnostic_only": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "native_row_case_ordering_changed": True,
        "product_default_adoption": True,
        "role_denominators": {
            "primary": _role_summary(role_docs["primary"], phase1),
            "companion": _role_summary(role_docs["companion"], phase1),
        },
        "surface_metrics_by_role": {
            "primary": primary_metrics,
            "companion": companion_metrics,
        },
        "primary_top100_gap_analysis": _primary_top100_gap_analysis(
            surface_orders=surface_orders,
            primary_docs=role_docs["primary"],
            phase1=phase1,
            primary_metrics=primary_metrics,
        ),
        "decision": {
            "best_defensive_companion_surface": (
                "hybrid_with_soft_repeated_normal_guard"
            ),
            "primary_top500_lift_vs_native": (
                soft_primary
                - primary_metrics["native_row_queue"]["topn"]["500"]["matched_docs"]
            ),
            "companion_top500_lift_vs_native": (
                soft_companion
                - companion_metrics["native_row_queue"]["topn"]["500"]["matched_docs"]
            ),
            "production_default_adoption": True,
            "adoption_note": (
                "soft guard is adopted as the default family-list display "
                "ordering for v3.1 primary-oriented document review priority"
            ),
            "q95_gate_change_recommended": False,
            "top_features_used_for_ranking": False,
        },
        "adoption_readiness": {
            "default_native_ordering_unchanged": False,
            "soft_guard_role": "v31_primary_oriented_default_document_review_priority",
            "product_default_adoption": True,
            "primary_top100_native": primary_native["topn"]["100"]["matched_docs"],
            "primary_top100_soft_guard": primary_soft["topn"]["100"]["matched_docs"],
            "primary_top500_native": primary_native["topn"]["500"]["matched_docs"],
            "primary_top500_soft_guard": primary_soft["topn"]["500"]["matched_docs"],
            "companion_top500_native": companion_native["topn"]["500"][
                "matched_docs"
            ],
            "companion_top500_soft_guard": companion_soft["topn"]["500"][
                "matched_docs"
            ],
            "companion_top500_improved": (
                companion_soft["topn"]["500"]["matched_docs"]
                > companion_native["topn"]["500"]["matched_docs"]
            ),
            "monitoring_guardrails": [
                "repeated-normal pressure requires monitoring",
                "period-end normal background requires monitoring",
                "account/process concentration requires monitoring",
                "single-row high amount normal proxy requires monitoring",
                "companion TOP500 does not improve",
            ],
            "monitoring_metrics": {
                "primary_native_repeated_normal_pressure_top500": primary_native[
                    "top500_pressure"
                ]["repeated_normal_pressure"],
                "primary_soft_guard_repeated_normal_pressure_top500": primary_soft[
                    "top500_pressure"
                ]["repeated_normal_pressure"],
                "primary_soft_guard_period_end_normal_background_top500": primary_soft[
                    "top500_pressure"
                ]["period_end_normal_background_ratio"],
                "primary_soft_guard_account_top1_share_top500": primary_soft[
                    "top500_pressure"
                ]["account_concentration"]["top1_share"],
                "primary_soft_guard_process_top1_share_top500": primary_soft[
                    "top500_pressure"
                ]["process_concentration"]["top1_share"],
                "primary_soft_guard_single_row_high_amount_normal_proxy_top500": primary_soft[
                    "top500_pressure"
                ][
                    "single_row_high_amount_normal_proxy"
                ],
            },
        },
    }
    payload["raw_identifier_leak_check"] = identifier_leak_check(payload)
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    primary = payload["surface_metrics_by_role"]["primary"][
        "hybrid_with_soft_repeated_normal_guard"
    ]["topn"]["500"]
    companion = payload["surface_metrics_by_role"]["companion"][
        "hybrid_with_soft_repeated_normal_guard"
    ]["topn"]["500"]
    _print(
        "wrote "
        f"{OUT_JSON.relative_to(ROOT).as_posix()} "
        f"primary_top500={primary['matched_docs']} "
        f"companion_top500={companion['matched_docs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
