"""VAE/unsupervised v3.3b exact owner-surface diagnostic.

Diagnostic-only. This measures VAE document surfaces against the v3.3b
responsibility map with exact matched-document joins. It reads the v3.3b
DataSynth journal directly and does not mix fixed5_normalcal5 case input.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts.diagnose_unsupervised_document_aggregation_fixed5_20260529 import (
    _candidate_scores,
    _ordered_docs,
    _period_end_score,
)
from tools.scripts.diagnose_unsupervised_v31_owner_surface_fixed5_20260531 import (
    BATCH_ID,
    PHASE1_CASE_RESULT,
    _document_records,
    _family_cases,
    _primary_top100_gap_analysis,
    _role_summary,
    _role_surface_metrics,
    _surface_orders,
    _topk_details_from_bundle,
    _unsupervised_case_rows,
    attach_phase1_document_prior,
    build_phase1_baseline,
    build_phase2_case_set,
    identifier_leak_check,
    load_model_bundle,
)

V33_RESPONSIBILITY = import_module(
    os.environ.get(
        "UNSUPERVISED_RESPONSIBILITY_MODULE",
        "tools.scripts."
        "measure_phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531",
    )
)

OUT_JSON = (
    ROOT
    / os.environ.get(
        "UNSUPERVISED_DIAGNOSTIC_OUT",
        "artifacts/unsupervised_v33_exact_owner_surface_fixed5_20260531.json",
    )
)
V33_RESPONSIBILITY_ARTIFACT = V33_RESPONSIBILITY.OUT_JSON
DATASET_NAME = V33_RESPONSIBILITY.CANDIDATE_NAME


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load_v33_truth() -> pd.DataFrame:
    truth = pd.read_csv(V33_RESPONSIBILITY.TRUTH_PATH, dtype=str).fillna("")
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _load_v33_case_input() -> pd.DataFrame:
    df = pd.read_csv(V33_RESPONSIBILITY.JOURNAL_PATH, low_memory=False)
    df["document_id"] = df["document_id"].astype(str)
    return df


def _owner_doc_sets(truth: pd.DataFrame) -> dict[str, set[str]]:
    masks = V33_RESPONSIBILITY._owner_masks(truth)
    return {
        "primary": set(
            truth.loc[masks["unsupervised"]["primary"], "document_id"].astype(str)
        ),
        "companion": set(
            truth.loc[masks["unsupervised"]["companion"], "document_id"].astype(str)
        ),
    }


def _load_responsibility_reference() -> dict[str, Any]:
    if not V33_RESPONSIBILITY_ARTIFACT.exists():
        return {"status": "v33_responsibility_artifact_missing"}
    payload = json.loads(V33_RESPONSIBILITY_ARTIFACT.read_text(encoding="utf-8"))
    primary_key = (
        "primary_owner_target_recall_v33d"
        if "primary_owner_target_recall_v33d" in payload
        else "primary_owner_target_recall_v33"
    )
    topn = payload[primary_key]["unsupervised"]["topn"]
    return {
        "status": "responsibility_native_reference_not_product_surface",
        "measurement_basis": "exact_native_join_in_responsibility_artifact",
        "topn": {
            key: {
                "matched_docs": value.get("matched_docs"),
                "recall": value.get("recall"),
                "official_status_in_v33_artifact": value.get("status"),
                "measurement_basis": value.get("measurement_basis"),
            }
            for key, value in topn.items()
        },
    }


def _percentile_by_doc(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (float(item[1]), str(item[0])))
    denominator = max(len(ordered), 1)
    return {doc: (idx + 1) / denominator for idx, (doc, _value) in enumerate(ordered)}


def _rarity_scores(records: dict[str, dict[str, Any]]) -> dict[str, float]:
    account_freq: dict[str, int] = {}
    process_freq: dict[str, int] = {}
    for record in records.values():
        for account in set(str(value) for value in record.get("accounts") or ()):
            account_freq[account] = account_freq.get(account, 0) + 1
        for process in set(str(value) for value in record.get("processes") or ()):
            process_freq[process] = process_freq.get(process, 0) + 1

    raw: dict[str, float] = {}
    for doc, record in records.items():
        accounts = [str(value) for value in record.get("accounts") or ()]
        processes = [str(value) for value in record.get("processes") or ()]
        account_rarity = max(
            [1.0 / max(account_freq.get(value, 1), 1) for value in accounts] or [0.0]
        )
        process_rarity = max(
            [1.0 / max(process_freq.get(value, 1), 1) for value in processes] or [0.0]
        )
        raw[doc] = max(account_rarity, process_rarity)
    return _percentile_by_doc(raw)


def _row_shape_scores(records: dict[str, dict[str, Any]]) -> dict[str, float]:
    row_counts = {
        doc: float(max(int(record.get("document_row_count") or 0), 0))
        for doc, record in records.items()
    }
    percentiles = _percentile_by_doc(row_counts)
    return {
        doc: max(float(percentile), 1.0 - float(percentile))
        for doc, percentile in percentiles.items()
    }


def _top_feature_strength(records: dict[str, dict[str, Any]]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for doc, record in records.items():
        case_count = max(int(record.get("case_count") or 0), 1)
        top_feature_cases = int(record.get("top_feature_case_count") or 0)
        raw[doc] = min(top_feature_cases / case_count, 1.0)
    return raw


def _v33_signal_surface_orders(
    cases: list[Any],
    records: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    base = _surface_orders(cases, records)
    scored = _candidate_scores(records)
    soft_scores = dict(scored["hybrid_with_soft_repeated_normal_guard"])
    upper_scores = dict(scored["hybrid_row_count_blended_surface"])
    rarity_scores = _rarity_scores(records)
    row_shape_scores = _row_shape_scores(records)
    top_feature_scores = _top_feature_strength(records)

    signal_pairs: list[tuple[str, float]] = []
    pressure_capped_pairs: list[tuple[str, float]] = []
    for doc, record in records.items():
        scores = [float(value) for value in record.get("scores", ()) if value is not None]
        if not scores:
            continue
        case_count = max(int(record.get("case_count") or 0), 0)
        repeated_proxy = min(case_count / 5.0, 1.0)
        amount_tail = float(record.get("amount_percentile") or 0.0)
        period_end = _period_end_score(record.get("min_period_end_proximity_days"))
        rarity = float(rarity_scores.get(doc, 0.0))
        row_shape = float(row_shape_scores.get(doc, 0.0))
        top_feature = float(top_feature_scores.get(doc, 0.0))
        soft = float(soft_scores.get(doc, 0.0))
        upper = float(upper_scores.get(doc, 0.0))

        signal_score = (
            (0.48 * soft)
            + (0.18 * rarity)
            + (0.14 * amount_tail)
            + (0.12 * row_shape)
            + (0.08 * top_feature)
        )
        pressure_capped_score = (
            (0.58 * soft)
            + (0.16 * rarity)
            + (0.14 * amount_tail)
            + (0.12 * row_shape)
        ) * (1.0 - (0.18 * repeated_proxy))
        # Period-end proximity is already a known normal-background pressure
        # source for this lane, so the capped probe demotes pure period-end
        # context unless other observable signal is also strong.
        if period_end > 0.90 and max(rarity, row_shape, amount_tail) < 0.85:
            pressure_capped_score *= 0.82

        signal_pairs.append((doc, signal_score))
        pressure_capped_pairs.append((doc, max(pressure_capped_score, 0.10 * upper)))

    base["v33_statistical_signal_probe"] = _ordered_docs(signal_pairs)
    base["v33_pressure_capped_signal_probe"] = _ordered_docs(pressure_capped_pairs)
    return base


def _distribution(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"count": 0, "p50": None, "p90": None, "max": None}
    series = pd.Series(clean, dtype=float)
    return {
        "count": int(series.count()),
        "p50": float(series.quantile(0.50)),
        "p90": float(series.quantile(0.90)),
        "max": float(series.max()),
    }


def _feature_profile(
    docs: set[str],
    *,
    records: dict[str, dict[str, Any]],
    surface_orders: dict[str, list[str]],
) -> dict[str, Any]:
    soft_order = surface_orders["hybrid_with_soft_repeated_normal_guard"]
    soft_rank = {doc: idx + 1 for idx, doc in enumerate(soft_order)}
    rarity_scores = _rarity_scores(records)
    row_shape_scores = _row_shape_scores(records)
    rows = [records[doc] for doc in docs if doc in records]
    return {
        "doc_count": len(docs),
        "soft_guard_rank_distribution": _distribution(
            [float(soft_rank.get(doc, 10001)) for doc in docs]
        ),
        "max_score_distribution": _distribution(
            [max([float(value) for value in row.get("scores", ())] or [0.0]) for row in rows]
        ),
        "amount_tail_distribution": _distribution(
            [float(row.get("amount_percentile") or 0.0) for row in rows]
        ),
        "account_process_rarity_distribution": _distribution(
            [float(rarity_scores.get(doc, 0.0)) for doc in docs]
        ),
        "document_shape_outlier_distribution": _distribution(
            [float(row_shape_scores.get(doc, 0.0)) for doc in docs]
        ),
        "case_count_distribution": _distribution(
            [float(row.get("case_count") or 0.0) for row in rows]
        ),
        "row_count_distribution": _distribution(
            [float(row.get("document_row_count") or 0.0) for row in rows]
        ),
        "period_end_context_distribution": _distribution(
            [
                _period_end_score(row.get("min_period_end_proximity_days"))
                for row in rows
            ]
        ),
        "top_feature_availability_distribution": _distribution(
            [
                min(
                    int(row.get("top_feature_case_count") or 0)
                    / max(int(row.get("case_count") or 0), 1),
                    1.0,
                )
                for row in rows
            ]
        ),
    }


def _primary_capture_differential(
    *,
    primary_docs: set[str],
    records: dict[str, dict[str, Any]],
    surface_orders: dict[str, list[str]],
) -> dict[str, Any]:
    soft_top500 = set(surface_orders["hybrid_with_soft_repeated_normal_guard"][:500])
    captured = primary_docs & soft_top500
    missed = primary_docs - captured
    return {
        "basis": "soft_guard_top500_capture_vs_miss",
        "captured_docs": len(captured),
        "missed_docs": len(missed),
        "captured_profile": _feature_profile(
            captured,
            records=records,
            surface_orders=surface_orders,
        ),
        "missed_profile": _feature_profile(
            missed,
            records=records,
            surface_orders=surface_orders,
        ),
        "read": (
            "The captured-vs-missed split is aggregate-only. It compares "
            "selector-observable feature distributions after the soft-guard "
            "surface is ordered; document identifiers are not emitted."
        ),
    }


def build_payload() -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_v33_case_input()
    truth = _load_v33_truth()
    role_docs = _owner_doc_sets(truth)
    all_role_docs = set().union(*role_docs.values())

    result = _topk_details_from_bundle(df, load_model_bundle())
    case_set = build_phase2_case_set(
        batch_id=f"{BATCH_ID}_v33b_journal",
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
    surface_orders = _v33_signal_surface_orders(cases, records)

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
    default_name = "hybrid_with_soft_repeated_normal_guard"
    probe_name = "soft_guard_context_top100_probe"
    default_primary = primary_metrics[default_name]
    probe_primary = primary_metrics[probe_name]
    pressure_delta = (
        probe_primary["top500_pressure"]["repeated_normal_pressure"]
        - default_primary["top500_pressure"]["repeated_normal_pressure"]
    )

    payload: dict[str, Any] = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "responsibility_map": "v3.3b",
        "source_candidate": V33_RESPONSIBILITY.CANDIDATE_NAME,
        "detector_input_source": str(
            V33_RESPONSIBILITY.JOURNAL_PATH.relative_to(ROOT)
        ).replace("\\", "/"),
        "phase1_action_tier_source": str(PHASE1_CASE_RESULT.relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "diagnostic_only": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "truth_or_owner_metadata_used_as_selector": False,
        "truth_or_owner_metadata_used_only_for_exact_matched_doc_join": True,
        "measurement_basis": "exact_matched_doc_join",
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "case_generation_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "product_default_changed_by_this_diagnostic": False,
        "current_product_default_surface": default_name,
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
        "primary_capture_differential": _primary_capture_differential(
            primary_docs=role_docs["primary"],
            records=records,
            surface_orders=surface_orders,
        ),
        "responsibility_reference": _load_responsibility_reference(),
        "decision": {
            "adopted_surface": default_name,
            "probe_surface": probe_name,
            "change_product_default_now": False,
            "probe_top100_lift_vs_adopted": (
                int(probe_primary["topn"]["100"]["matched_docs"])
                - int(default_primary["topn"]["100"]["matched_docs"])
            ),
            "probe_top500_lift_vs_adopted": (
                int(probe_primary["topn"]["500"]["matched_docs"])
                - int(default_primary["topn"]["500"]["matched_docs"])
            ),
            "probe_repeated_normal_pressure_delta": pressure_delta,
            "probe_pressure_not_above_adopted": pressure_delta <= 0,
            "read": (
                "v3.3b exact owner join keeps the adopted soft guard as the "
                "single VAE family-list ordering. The TOP100 probe and "
                "selector-safe signal probes do not replace the default unless "
                "they improve recall without raising review-pressure guardrails."
            ),
        },
    }
    payload["raw_identifier_leak_check"] = identifier_leak_check(payload)
    return payload


def main() -> int:
    payload = build_payload()
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": OUT_JSON.relative_to(ROOT).as_posix(),
                "primary_denominator": payload["role_denominators"]["primary"][
                    "truth_docs"
                ],
                "companion_denominator": payload["role_denominators"]["companion"][
                    "truth_docs"
                ],
                "adopted_top100": payload["surface_metrics_by_role"]["primary"][
                    "hybrid_with_soft_repeated_normal_guard"
                ]["topn"]["100"]["matched_docs"],
                "adopted_top500": payload["surface_metrics_by_role"]["primary"][
                    "hybrid_with_soft_repeated_normal_guard"
                ]["topn"]["500"]["matched_docs"],
                "probe_top100": payload["surface_metrics_by_role"]["primary"][
                    "soft_guard_context_top100_probe"
                ]["topn"]["100"]["matched_docs"],
                "probe_pressure_delta": payload["decision"][
                    "probe_repeated_normal_pressure_delta"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
