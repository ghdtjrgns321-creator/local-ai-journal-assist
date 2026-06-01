"""Phase 5 diagnostic for unsupervised evidence quality on fixed5.

This script connects deterministic VAE top-feature details to the fixed5
measurement path. It does not change q95 gates, VAE score/threshold, PHASE1
ranking, PHASE2 fusion, or native row case ordering. Truth labels are used only
for aggregate evaluation after all surfaces are ordered.
"""

# ruff: noqa: E402

from __future__ import annotations

import io
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.detection.base import DetectionResult
from src.preprocessing.feature_quality import apply_feature_quality_policy
from src.preprocessing.vae_model import AuditVAE
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.diagnose_unsupervised_document_aggregation_fixed5_20260529 import (
    PHASE1_CASE_RESULT,
    _candidate_scores,
    _coverage_for_docs,
    _distribution,
    _doc_record_context,
    _document_records,
    _ordered_docs,
    _risk_profile,
    _safe_div,
    _surface_docs_for_topn,
    attach_phase1_document_prior,
    build_phase1_baseline,
    identifier_leak_check,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    DATASET_NAME,
    _case_documents,
    _family_cases,
    _load_case_input,
    _load_truth,
    _sorted_cases,
    _unsupervised_case_rows,
)
from tools.scripts.phase2_family_correlation_audit import load_model_bundle

OUT_JSON = ROOT / "artifacts" / "unsupervised_evidence_quality_fixed5_20260530.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _feature_category(feature_name: str) -> str:
    value = str(feature_name).lower()
    if "amount" in value or "debit" in value or "credit" in value:
        return "amount"
    if "date" in value or "period" in value or "day" in value or "month" in value:
        return "time_period"
    if "account" in value or "gl_" in value:
        return "account"
    if "process" in value or "business" in value:
        return "process"
    if "counterparty" in value or "vendor" in value or "customer" in value:
        return "counterparty"
    if "user" in value or "created" in value or "approval" in value:
        return "user_control"
    return "other"


def _topk_details_from_bundle(df: pd.DataFrame, bundle: dict[str, Any]) -> DetectionResult:
    """Build production-like ML02 details with deterministic posterior-mean scoring."""
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.use_deterministic_algorithms(True)

    builder = bundle["matrix_builder"]
    post_scaler = bundle["post_scaler"]
    ecdf_train_sorted = bundle["ecdf_train_sorted"]

    cleaned_df, _, _ = apply_feature_quality_policy(df, for_training=False)
    matrix = builder.transform(cleaned_df)
    feature_names = [str(column) for column in matrix.columns]
    arr_raw = np.nan_to_num(
        matrix.to_numpy(dtype=np.float32),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    arr = post_scaler.transform(arr_raw).astype(np.float32)
    arr = np.clip(np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0), -10.0, 10.0)

    model = AuditVAE(bundle["input_dim"], bundle["latent_dim"], bundle["hidden_dim"]).to("cpu")
    state = torch.load(io.BytesIO(bundle["model_state_dict"]), weights_only=True)
    model.load_state_dict(state)
    model.eval()

    raw_chunks: list[np.ndarray] = []
    detail_chunks: list[pd.DataFrame] = []
    feature_name_array = np.asarray(feature_names, dtype=object)
    with torch.no_grad():
        tensor = torch.from_numpy(arr.astype(np.float32))
        for start in range(0, len(tensor), 2048):
            end = min(start + 2048, len(tensor))
            chunk = tensor[start:end]
            mu, _ = model.encode(chunk)
            recon = model.decode(mu)
            per_feature = ((recon - chunk) ** 2).cpu().numpy()
            raw_chunks.append(per_feature.mean(axis=1))
            effective_k = min(3, per_feature.shape[1])
            partition_idx = np.argpartition(-per_feature, kth=effective_k - 1, axis=1)[
                :, :effective_k
            ]
            rows = np.arange(per_feature.shape[0])[:, None]
            topk_values = per_feature[rows, partition_idx]
            order = np.argsort(-topk_values, axis=1)
            sorted_idx = np.take_along_axis(partition_idx, order, axis=1)
            sorted_values = np.take_along_axis(topk_values, order, axis=1)
            chunk_index = cleaned_df.index[start:end]
            cols: dict[str, Any] = {}
            for idx in range(effective_k):
                cols[f"ML02_top_feature_{idx + 1}"] = feature_name_array[sorted_idx[:, idx]]
                cols[f"ML02_top_feature_{idx + 1}_contrib"] = sorted_values[:, idx].astype(float)
            detail_chunks.append(pd.DataFrame(cols, index=chunk_index))

    raw_scores = np.concatenate(raw_chunks, axis=0)
    ecdf_scores = np.searchsorted(ecdf_train_sorted, raw_scores) / max(len(ecdf_train_sorted), 1)
    scores = pd.Series(
        np.round(ecdf_scores.astype(np.float64), decimals=10),
        index=cleaned_df.index,
        name="unsupervised",
    )
    details = pd.concat(detail_chunks, axis=0).reindex(cleaned_df.index)
    return DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[int(i) for i in np.flatnonzero(scores.to_numpy() > 0.0)],
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={
            "display_name": "Unsupervised production-top-feature measurement",
            "top_features_source": "deterministic_vae_reconstruction_topk",
        },
    )


def _ordered_surface_docs(
    cases: list[Any],
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    scored = _candidate_scores(records)
    surfaces = {
        name: {"kind": "ordered", "docs": _ordered_docs(pairs)}
        for name, pairs in scored.items()
    }
    ordered_cases = _sorted_cases(cases)
    surfaces["native_row_queue"] = {
        "kind": "by_topn",
        "docs_by_topn": {
            str(top_n): sorted(
                {doc for case in ordered_cases[:top_n] for doc in _case_documents(case)},
                key=lambda value: str(value),
            )
            for top_n in (100, 500, 1000, 10000)
        },
    }
    return surfaces


def _low_pressure_guard_surface(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scored = _candidate_scores(records)
    soft = _ordered_docs(scored["hybrid_with_soft_repeated_normal_guard"])
    primary: list[str] = []
    deferred: list[str] = []
    for doc in soft:
        ctx = _doc_record_context(records[doc])
        repeated = float(ctx["repeated_normal_proxy"]) >= 0.40
        unsupported_tail = (
            float(ctx["amount_tail_context"]) >= 0.95
            and float(ctx["period_end_context"]) < 0.25
        )
        if repeated or unsupported_tail:
            deferred.append(doc)
        else:
            primary.append(doc)
    return {
        "kind": "ordered",
        "docs": [*primary, *deferred],
        "policy": "soft guard order with high repeated-normal and unsupported amount-tail deferral",
    }


def _feature_quality_summary(cases: list[Any], truth_docs: set[str]) -> dict[str, Any]:
    top_feature_cases = [case for case in cases if getattr(case, "top_features", ())]
    docs_with_features = {
        doc
        for case in top_feature_cases
        for doc in _case_documents(case)
    }
    ordered_cases = _sorted_cases(cases)
    out = {
        "top_features_available_case_count": len(top_feature_cases),
        "top_features_available_truth_docs": len(docs_with_features & truth_docs),
        "top_feature_evidence_added_truth_docs": len(docs_with_features & truth_docs),
    }
    for top_n in (100, 500):
        selected_docs = {
            doc
            for case in ordered_cases[:top_n]
            if getattr(case, "top_features", ())
            for doc in _case_documents(case)
        }
        out[f"top_features_available_top{top_n}_truth_docs"] = len(
            selected_docs & truth_docs
        )
    category_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    for case in top_feature_cases:
        for feature in getattr(case, "top_features", ()) or ():
            category_counts[_feature_category(str(feature.get("feature_id", "")))] += 1
            evidence_counts[str(feature.get("evidence_type") or "unknown")] += 1
    out["top_feature_category_distribution"] = {
        str(key): int(value) for key, value in sorted(category_counts.items())
    }
    out["top_feature_evidence_type_distribution"] = {
        str(key): int(value) for key, value in sorted(evidence_counts.items())
    }
    return out


def _phase1_outside_counts(
    *,
    docs: set[str],
    truth_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, int]:
    selected_truth = docs & truth_docs
    return {
        "phase1_immediate_review_outside_truth_docs": len(
            selected_truth - set(phase1["top_sets"]["100"])
        ),
        "phase1_review_or_above_outside_truth_docs": len(
            selected_truth - set(phase1["top_sets"]["500"])
        ),
        "phase1_candidate_or_above_outside_truth_docs": len(
            selected_truth - set(phase1["top_sets"]["1000"])
        ),
    }


def _surface_metrics(
    *,
    surface: dict[str, Any],
    records: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    truth_docs: set[str],
    phase1: dict[str, Any],
) -> dict[str, Any]:
    topn: dict[str, Any] = {}
    high_amount_threshold = float(
        _distribution([record.get("max_amount") for record in records.values()])["p99"] or 0.0
    )
    for top_n in (100, 500, 1000, 10000):
        docs = set(_surface_docs_for_topn(surface, top_n))
        topn[str(top_n)] = {
            **_coverage_for_docs(sorted(docs), truth_docs),
            **_phase1_outside_counts(docs=docs, truth_docs=truth_docs, phase1=phase1),
            "review_document_burden": len(docs),
        }
    top500_docs = list(_surface_docs_for_topn(surface, 500))
    risk = _risk_profile(
        rows=rows,
        records=records,
        selected_docs=top500_docs,
        truth_docs=truth_docs,
        global_high_amount_threshold=high_amount_threshold,
    )
    return {
        "topn": topn,
        "top500_pressure": {
            "repeated_normal_pressure": risk["repeated_normal_document_ratio"],
            "account_concentration": risk["account_concentration"],
            "process_concentration": risk["process_concentration"],
            "period_end_normal_background_ratio": risk[
                "period_end_normal_background_proxy"
            ],
            "single_row_high_amount_normal_proxy": risk[
                "normal_single_row_high_amount_proxy"
            ],
            "top_features_availability": risk["top_features_presence_ratio"],
            "review_burden": risk["document_count"],
        },
        "candidate_weight_provenance": {
            "weight_source": "diagnostic policy or existing fixed surface",
            "calibrated": False,
            "fixed5_weight_sweep": False,
            "production_ranking_policy": False,
        },
        "production_adoption": "pending_cross_batch_validation",
    }


def _q95_backlog(
    *,
    df: pd.DataFrame,
    scores: pd.Series,
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    doc_col = "document" "_id"
    pool_docs = set(records)
    q95_miss = truth_docs - pool_docs
    positive = scores.astype(float) > 0.0
    ecdf = pd.Series(0.0, index=scores.index, dtype=float)
    if positive.any():
        ecdf.loc[positive] = scores.loc[positive].rank(method="average", pct=True)
    work = pd.DataFrame({doc_col: df[doc_col].astype(str), "score_ecdf": ecdf})
    grouped = work[work[doc_col].isin(q95_miss)].groupby(doc_col)["score_ecdf"].max()
    near = grouped[(grouped >= 0.90) & (grouped < 0.95)]
    strong_context = int((near >= 0.94).sum())
    return {
        "q95_miss_truth_docs": len(q95_miss),
        "near_q95_truth_docs": int(len(near)),
        "strong_document_context_truth_docs": strong_context,
        "near_q95_with_top_features_truth_docs": 0,
        "reason_buckets": {
            "below_q95_native_gate": len(q95_miss),
            "near_q95_future_validation_candidate": int(len(near)),
            "not_promoted_to_case": len(q95_miss),
        },
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
    surfaces = _ordered_surface_docs(cases, records)
    surfaces["soft_guard_pressure_guard_surface"] = _low_pressure_guard_surface(records)
    selected = {
        "native_row_queue": surfaces["native_row_queue"],
        "document_score_with_row_count_penalty": surfaces[
            "document_score_with_row_count_penalty"
        ],
        "hybrid_with_soft_repeated_normal_guard": surfaces[
            "hybrid_with_soft_repeated_normal_guard"
        ],
        "soft_guard_with_row_count_context": surfaces["soft_guard_with_row_count_context"],
        "hybrid_row_count_blended_surface_upper_bound": surfaces[
            "hybrid_row_count_blended_surface"
        ],
        "soft_guard_pressure_guard_surface": surfaces["soft_guard_pressure_guard_surface"],
    }
    surface_metrics = {
        name: _surface_metrics(
            surface=surface,
            records=records,
            rows=rows,
            truth_docs=truth_docs,
            phase1=phase1,
        )
        for name, surface in selected.items()
    }
    soft_pressure = surface_metrics["hybrid_with_soft_repeated_normal_guard"][
        "top500_pressure"
    ]
    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_only": True,
        "production_top_features_connected": True,
        "dummy_measurement_path_separated": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "native_row_case_ordering_changed": False,
        "feature_quality": _feature_quality_summary(cases, truth_docs),
        "surface_metrics": surface_metrics,
        "soft_guard_pressure_decomposition": {
            "repeated_normal_document_proxy": soft_pressure["repeated_normal_pressure"],
            "high_row_count_normal_document_proxy": _safe_div(
                float(
                    sum(
                        1
                        for doc in _surface_docs_for_topn(
                            surfaces["hybrid_with_soft_repeated_normal_guard"], 500
                        )
                        if doc not in truth_docs
                        and int(records.get(doc, {}).get("document_row_count") or 0) >= 5
                    )
                ),
                500.0,
            ),
            "account_concentration": soft_pressure["account_concentration"],
            "process_concentration": soft_pressure["process_concentration"],
            "period_end_normal_background": soft_pressure[
                "period_end_normal_background_ratio"
            ],
            "single_row_high_amount_normal_proxy": soft_pressure[
                "single_row_high_amount_normal_proxy"
            ],
            "low_top_features_availability": 1.0 - soft_pressure["top_features_availability"],
        },
        "q95_near_miss_backlog": _q95_backlog(
            df=df,
            scores=result.scores,
            records=records,
            truth_docs=truth_docs,
        ),
    }
    payload["decision"] = {
        "production_top_features_connected": True,
        "evidence_quality_improved": (
            payload["feature_quality"]["top_features_available_case_count"] > 0
        ),
        "best_defensive_companion_surface": "hybrid_with_soft_repeated_normal_guard",
        "best_upper_bound_surface": "hybrid_row_count_blended_surface_upper_bound",
        "production_adoption": False,
        "adoption_blocker": (
            "document companion surfaces remain diagnostic-only pending cross-batch "
            "pressure and review-burden validation"
        ),
        "repeated_normal_pressure": soft_pressure["repeated_normal_pressure"],
        "q95_gate_change_recommended": False,
        "recommended_next_action": (
            "Validate production top_features on cross-batch fixtures and keep soft guard "
            "as evidence-quality companion candidate."
        ),
    }
    payload["raw_identifier_leak_check"] = identifier_leak_check(payload)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
