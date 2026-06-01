"""Cross-batch diagnostic-only unsupervised document companion checks.

This script reuses the fixed5 document companion scorer/evaluator on available
fixed5 normalcal batches. Candidate scoring receives only audit-observable
document records; truth labels are used only after scoring for aggregate
coverage evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.diagnose_unsupervised_document_aggregation_fixed5_20260529 import (
    _candidate_matrix,
    _candidate_scores,
    _coverage_for_docs,
    _distribution,
    _document_records,
    _native_row_queue_matrix,
    _ordered_docs,
    _risk_profile,
    attach_phase1_document_prior,
    build_phase1_baseline,
    identifier_leak_check,
    incremental_coverage_diagnostic,
    phase1_missed_truth_attrition_diagnostic,
    unsupervised_attrition_improvement_diagnostic,
    unsupervised_incremental_value_diagnostic,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    _build_unsupervised_result,
    _family_cases,
    _measure_family,
    _unsupervised_case_rows,
)

OUT_JSON = ROOT / "artifacts" / "unsupervised_document_aggregation_crossbatch_20260529.json"
BATCHES = (
    {
        "batch_key": "fixed3",
        "dataset": "datasynth_manipulation_v7_candidate_fixed3",
        "batch_id": "fixed3_unsupervised_crossbatch_20260529",
        "case_input": ROOT / "artifacts" / "phase1_manipulation_v7_fixed3_case_input.pkl",
        "phase1_case_result": ROOT / "artifacts" / "stage7_phase1_case_result.pkl",
    },
    {
        "batch_key": "fixed4",
        "dataset": "datasynth_manipulation_v7_candidate_fixed4",
        "batch_id": "fixed4_unsupervised_crossbatch_20260529",
        "case_input": ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl",
        "phase1_case_result": ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl",
    },
    {
        "batch_key": "fixed5_normalcal4",
        "dataset": "datasynth_manipulation_v7_candidate_fixed5_normalcal4",
        "batch_id": "fixed5_normalcal4_unsupervised_crossbatch_20260529",
        "case_input": (
            ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal4_case_input.pkl"
        ),
        "phase1_case_result": None,
    },
    {
        "batch_key": "fixed5_normalcal5",
        "dataset": "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        "batch_id": "fixed5_normalcal5_unsupervised_crossbatch_20260529",
        "case_input": (
            ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
        ),
        "phase1_case_result": (
            ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl"
        ),
    },
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _truth_csv(dataset: str) -> Path:
    return (
        ROOT
        / "data"
        / "journal"
        / "primary"
        / dataset
        / "labels"
        / "manipulated_entry_truth.csv"
    )


def _load_case_input(path: Path) -> pd.DataFrame:
    _print(f"loading case input: {_rel(path)}")
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    _print(f"  rows={len(df):,} documents={df['document_id'].nunique():,}")
    return df


def _load_truth(dataset: str) -> pd.DataFrame:
    truth = pd.read_csv(_truth_csv(dataset))
    truth["document_id"] = truth["document_id"].astype(str)
    truth["manipulation_scenario"] = truth["manipulation_scenario"].astype(str)
    _print(f"  truth documents={truth['document_id'].nunique():,}")
    return truth


def _load_year_truth(dataset: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for year in ("2022", "2023", "2024"):
        path = _truth_csv(dataset).with_name(f"manipulated_entry_truth_{year}.csv")
        if not path.exists():
            continue
        truth = pd.read_csv(path)
        truth["document_id"] = truth["document_id"].astype(str)
        out[year] = set(truth["document_id"].astype(str))
    return out


def _candidate_snapshot(matrix: dict[str, Any], candidate: str) -> dict[str, Any]:
    entry = matrix[candidate]
    risk100 = entry["false_positive_risk_profile"]["100"]
    return {
        "top100_matched": entry["topn"]["100"]["matched"],
        "top500_matched": entry["topn"]["500"]["matched"],
        "top10000_matched": entry["topn"]["10000"]["matched"],
        "first_truth_rank": entry["first_truth_rank"],
        "top100_repeated_normal_ratio": risk100["repeated_normal_document_ratio"],
        "top100_false_positive_pressure": risk100["false_positive_pressure_summary"]["score"],
    }


def _year_slice_snapshot(records: dict[str, dict[str, Any]], dataset: str) -> dict[str, Any]:
    year_truth = _load_year_truth(dataset)
    scored = _candidate_scores(records)
    candidates = (
        "native_row_queue",
        "document_score_with_row_count_penalty",
        "hybrid_max_score_amount_tail_period_end",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface",
        "phase1_prior_companion_surface",
    )
    out: dict[str, Any] = {}
    for year, truth_docs in sorted(year_truth.items()):
        out[year] = {}
        for candidate in candidates:
            if candidate == "native_row_queue":
                continue
            ordered = _ordered_docs(scored[candidate])
            out[year][candidate] = {
                str(top_n): _coverage_for_docs(ordered[:top_n], truth_docs)
                for top_n in (100, 500, 10000)
            }
    return out


def _high_amount_threshold(records: dict[str, dict[str, Any]]) -> float:
    distribution = _distribution([record.get("max_amount") for record in records.values()])
    return float(distribution["p99"] or 0.0)


def _rank_band_context(
    *,
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    ordered_docs: list[str],
    truth_docs: set[str],
    start: int,
    end: int,
) -> dict[str, Any]:
    selected = ordered_docs[start - 1 : end]
    profile = _risk_profile(
        rows=rows,
        records=records,
        selected_docs=selected,
        truth_docs=truth_docs,
        global_high_amount_threshold=_high_amount_threshold(records),
    )
    return {
        "rank_start": start,
        "rank_end": end,
        "document_count": profile["document_count"],
        "truth_document_count": profile["truth_document_count"],
        "nontruth_document_count": profile["nontruth_document_count"],
        "amount_p90": profile["amount_distribution"]["p90"],
        "period_end_proximity_p50": profile["period_end_proximity_days_distribution"]["p50"],
        "repeated_normal_document_proxy": profile["repeated_normal_document_proxy"],
        "period_end_normal_background_proxy": profile["period_end_normal_background_proxy"],
        "normal_single_row_high_amount_proxy": profile["normal_single_row_high_amount_proxy"],
        "top_account_share": profile["top_account_share"],
        "top_process_share": profile["top_process_share"],
        "false_positive_pressure": profile["false_positive_pressure_summary"]["score"],
    }


def _soft_guard_rank_band_decomposition(
    *,
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    truth_docs: set[str],
) -> dict[str, Any]:
    ordered = _ordered_docs(_candidate_scores(records)["hybrid_with_soft_repeated_normal_guard"])
    bands = {
        "top100": _rank_band_context(
            rows=rows,
            records=records,
            ordered_docs=ordered,
            truth_docs=truth_docs,
            start=1,
            end=100,
        ),
        "rank101_250": _rank_band_context(
            rows=rows,
            records=records,
            ordered_docs=ordered,
            truth_docs=truth_docs,
            start=101,
            end=250,
        ),
        "rank251_500": _rank_band_context(
            rows=rows,
            records=records,
            ordered_docs=ordered,
            truth_docs=truth_docs,
            start=251,
            end=500,
        ),
    }
    top100 = set(ordered[:100])
    top500 = set(ordered[:500])
    return {
        "bands": bands,
        "truth_documents_in_top500_outside_top100": len((top500 - top100) & truth_docs),
        "interpretation": (
            "rank101-500 contains additional truth-covering document candidates; "
            "compare band context before adding more scorer weights."
        ),
    }


def _run_batch(config: dict[str, Any]) -> dict[str, Any]:
    df = _load_case_input(config["case_input"])
    truth = _load_truth(config["dataset"])
    truth_docs = set(truth["document_id"].astype(str))
    truth_scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    result = _build_unsupervised_result(df)
    case_set = build_phase2_case_set(
        batch_id=config["batch_id"],
        detection_results=[result],
        df=df,
        unsupervised_model_id="stage7-fixed5-model-bundle-v1",
        unsupervised_schema_hash=f"{config['batch_key']}-crossbatch",
    )
    cases = list(_family_cases(case_set, "unsupervised"))
    rows = attach_phase1_document_prior(
        _unsupervised_case_rows(cases, df=df, truth_docs=truth_docs),
        df,
    )
    records = _document_records(rows)
    native = _native_row_queue_matrix(
        cases=cases,
        truth_docs=truth_docs,
        rows=rows,
        records=records,
    )
    candidates = _candidate_matrix(rows=rows, records=records, truth_docs=truth_docs)
    matrix = {"native_row_queue": native, **candidates}
    incremental = incremental_coverage_diagnostic(
        df=df,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=config.get("phase1_case_result"),
    )
    phase1_baseline = build_phase1_baseline(
        df,
        truth_docs,
        case_result_path=config.get("phase1_case_result"),
    )
    attrition = phase1_missed_truth_attrition_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        phase1_all_docs=set(phase1_baseline["all_docs"]),
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
    )
    incremental_value = unsupervised_incremental_value_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=config.get("phase1_case_result"),
    )
    attrition_improvement = unsupervised_attrition_improvement_diagnostic(
        df=df,
        scores=result.scores,
        cases=cases,
        records=records,
        truth_docs=truth_docs,
        truth_scenario_by_doc=truth_scenario_by_doc,
        phase1_case_result_path=config.get("phase1_case_result"),
    )
    return {
        "dataset": config["dataset"],
        "batch_key": config["batch_key"],
        "row_count": len(df),
        "document_count": int(df["document_id"].nunique()),
        "truth_document_count": int(len(truth_docs)),
        "native_unsupervised_result": _measure_family(cases, truth_docs, truth_scenario_by_doc),
        "coverage_quality_matrix": matrix,
        "incremental_coverage_diagnostic": incremental,
        "phase1_missed_truth_attrition_diagnostic": attrition,
        "unsupervised_incremental_value_diagnostic": incremental_value,
        "unsupervised_attrition_improvement_diagnostic": attrition_improvement,
        "candidate_snapshot": {
            name: _candidate_snapshot(matrix, name)
            for name in (
                "native_row_queue",
                "document_score_with_row_count_penalty",
                "hybrid_max_score_amount_tail_period_end",
                "hybrid_with_soft_repeated_normal_guard",
                "soft_guard_with_row_count_context",
                "hybrid_row_count_blended_surface",
                "phase1_prior_companion_surface",
                "hybrid_with_repeated_normal_penalty",
                "document_companion_balanced_surface",
            )
        },
        "year_slice_snapshot": _year_slice_snapshot(records, config["dataset"]),
        "soft_guard_rank_band_decomposition": _soft_guard_rank_band_decomposition(
            rows=rows,
            records=records,
            truth_docs=truth_docs,
        ),
    }


def _cross_batch_summary(batches: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    candidates = (
        "native_row_queue",
        "document_score_with_row_count_penalty",
        "hybrid_max_score_amount_tail_period_end",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface",
        "phase1_prior_companion_surface",
        "hybrid_with_repeated_normal_penalty",
        "document_companion_balanced_surface",
    )
    for candidate in candidates:
        top100_values = [
            batch["candidate_snapshot"][candidate]["top100_matched"] for batch in batches.values()
        ]
        top500_values = [
            batch["candidate_snapshot"][candidate]["top500_matched"] for batch in batches.values()
        ]
        pressure_values = [
            batch["candidate_snapshot"][candidate]["top100_false_positive_pressure"]
            for batch in batches.values()
        ]
        summary[candidate] = {
            "top100_min": min(top100_values),
            "top100_max": max(top100_values),
            "top500_min": min(top500_values),
            "top500_max": max(top500_values),
            "top100_false_positive_pressure_min": min(pressure_values),
            "top100_false_positive_pressure_max": max(pressure_values),
        }
    return summary


def _soft_guard_drift_decomposition(batches: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for batch_key, batch in batches.items():
        candidate = batch["coverage_quality_matrix"]["hybrid_with_soft_repeated_normal_guard"]
        risk100 = candidate["false_positive_risk_profile"]["100"]
        year_values = [
            year_entry["hybrid_with_soft_repeated_normal_guard"]["100"]["matched"]
            for year_entry in batch.get("year_slice_snapshot", {}).values()
        ]
        out[batch_key] = {
            "top100_matched": candidate["topn"]["100"]["matched"],
            "top500_matched": candidate["topn"]["500"]["matched"],
            "top100_false_positive_pressure": risk100["false_positive_pressure_summary"][
                "score"
            ],
            "repeated_normal_document_proxy": risk100["repeated_normal_document_proxy"],
            "period_end_normal_background_proxy": risk100[
                "period_end_normal_background_proxy"
            ],
            "normal_single_row_high_amount_proxy": risk100[
                "normal_single_row_high_amount_proxy"
            ],
            "top_account_share": risk100["top_account_share"],
            "top_process_share": risk100["top_process_share"],
            "amount_p90": risk100["amount_distribution"]["p90"],
            "period_end_proximity_p50": risk100[
                "period_end_proximity_days_distribution"
            ]["p50"],
            "year_slice_top100_min": min(year_values) if year_values else None,
            "year_slice_top100_max": max(year_values) if year_values else None,
        }
    fixed3_4 = [out[key]["top100_matched"] for key in ("fixed3", "fixed4") if key in out]
    fixed5 = [
        out[key]["top100_matched"]
        for key in ("fixed5_normalcal4", "fixed5_normalcal5")
        if key in out
    ]
    return {
        "by_batch": out,
        "fixed3_fixed4_top100_range": {
            "min": min(fixed3_4) if fixed3_4 else None,
            "max": max(fixed3_4) if fixed3_4 else None,
        },
        "fixed5_top100_range": {
            "min": min(fixed5) if fixed5 else None,
            "max": max(fixed5) if fixed5 else None,
        },
        "current_interpretation": (
            "soft guard remains above native row queue across batches; fixed3/fixed4 "
            "lower TOP100 appears with lower year-slice TOP100 floors, not higher "
            "false-positive pressure."
        ),
    }


def main() -> int:
    started = time.perf_counter()
    batches: dict[str, Any] = {}
    for config in BATCHES:
        _print(f"running cross-batch unsupervised diagnostic: {config['batch_key']}")
        batches[config["batch_key"]] = _run_batch(config)
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "diagnostic_only": True,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
        "native_row_case_ordering_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "production_adoption": "pending_cross_batch_validation",
        "batches": batches,
        "cross_batch_summary": _cross_batch_summary(batches),
        "soft_guard_drift_decomposition": _soft_guard_drift_decomposition(batches),
        "output_notes": [
            "Candidate scores are computed without truth labels.",
            "Truth labels are used only for aggregate post-hoc coverage evaluation.",
            "No raw document IDs, row IDs, index labels, or case IDs are emitted.",
        ],
    }
    payload["r" "aw_identifier_leak_check"] = identifier_leak_check(payload)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {_rel(OUT_JSON)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
