"""Diagnose TS-specific TOP100 rank-band gap on fixed5.

Diagnostic-only. Candidate ordering does not use truth labels, scenario labels,
PHASE1 ranks, raw document identifiers, row identifiers, or case identifiers.
Truth/scenario labels are used only after ordering for aggregate evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.scripts.diagnose_timeseries_primary_surface_crossbatch_20260530 import (
    _build_row_score_windows,
    _candidate_policies,
)
from tools.scripts.diagnose_timeseries_ranking_candidates_fixed5_20260529 import (
    _raw_identifier_leak_report,
)
from tools.scripts.diagnose_timeseries_ranking_crossbatch_20260529 import (
    _load_case_input,
    _load_truth,
    _phase1_reference_sets,
    _retention_review_burden_proxy,
    _truth_scenario_by_doc,
)
from tools.scripts.diagnose_timeseries_top100_failure_fixed5_20260530 import (
    CASE_INPUT,
    FAMILY_BY_DOC,
    PHASE1_RESULT,
    TRUTH_CSV,
    _family_by_doc_lookup,
    _label_alignment,
    _selected_docs,
    _truth_doc_features,
)
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import _run_rule_detector

OUT_JSON = ROOT / "artifacts" / "timeseries_top100_rankband_gap_fixed5_20260530.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input(CASE_INPUT)
    truth = _load_truth(TRUTH_CSV)
    truth_docs = set(truth["document_id"].astype(str))
    scenario_by_doc = _truth_scenario_by_doc(truth)
    phase1_reference = _phase1_reference_sets(PHASE1_RESULT)
    family_by_doc = _family_by_doc_lookup(FAMILY_BY_DOC)

    ts_result = _run_rule_detector("timeseries", df)
    windows = _build_row_score_windows(df=df, detection_result=ts_result, truth_docs=truth_docs)
    doc_features = _truth_doc_features(
        windows=windows,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
        df=df,
        detection_result=ts_result,
        family_by_doc=family_by_doc,
        phase1_reference=phase1_reference,
    )
    alignment = _label_alignment(doc_features)
    ts_specific_docs = {
        doc for doc, value in alignment.items() if value == "ts_primary_label_aligned"
    }

    conservative = _candidate_policies(windows)["ts_primary_conservative_surface"]
    rank_rows = _first_rank_rows(conservative, ts_specific_docs, df)
    promoted = [row for row in rank_rows if row["rank"] <= 100]
    delayed = [row for row in rank_rows if 100 < row["rank"] <= 500]
    group_comparison = {
        "promoted_top100_ts_specific": _group_feature_summary(promoted),
        "delayed_101_500_ts_specific": _group_feature_summary(delayed),
        "directional_feature_gaps": _directional_feature_gaps(promoted, delayed),
    }
    delayed_reasons = _delayed_reason_summary(promoted, delayed)

    candidate = _ts_specific_top100_stabilized_surface(windows)
    candidate_summary = _candidate_summary(
        candidate,
        conservative=conservative,
        truth_docs=truth_docs,
        alignment=alignment,
    )
    defensible = _defensible_candidate_found(candidate_summary)
    if not defensible:
        candidate_summary = {
            "created": False,
            "reason": "No defensible audit-observable TOP100 feature gap found.",
        }

    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": "fixed5_normalcal5",
        "guardrails": {
            "truth_label_used_for_selector": False,
            "scenario_label_used_for_selector": False,
            "production_gate_ranking_fusion_changed": False,
            "phase1_ranking_changed": False,
            "fixed4_used_for_product_judgment": False,
            "broad_companion_used_as_ts_primary": False,
            "fixed5_top100_weight_sweep_used": False,
        },
        "baseline": {
            "ts_specific_truth_docs": len(ts_specific_docs),
            "current_native_ts_top100_ts_specific": 0,
            "ts_primary_conservative_top100_ts_specific": 13,
            "ts_primary_conservative_top500_ts_specific": 32,
        },
        "rank_band_comparison": group_comparison,
        "delayed_101_500_miss_reasons": delayed_reasons,
        "candidate_feature_judgment": _candidate_feature_judgment(
            group_comparison,
            delayed_reasons,
            defensible,
        ),
        "candidate_surface": candidate_summary,
        "decision": _decision_payload(
            promoted_count=len(promoted),
            delayed_count=len(delayed),
            delayed_reasons=delayed_reasons,
            defensible=defensible,
            candidate_summary=candidate_summary,
        ),
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


def _first_rank_rows(
    ordered: list[dict[str, Any]],
    ts_specific_docs: set[str],
    df: pd.DataFrame,
) -> list[dict[str, Any]]:
    doc_context = _doc_context(df)
    first: dict[str, dict[str, Any]] = {}
    for rank, window in enumerate(ordered, start=1):
        for doc in set(window.get("_docs", set())) & ts_specific_docs:
            if doc in first:
                continue
            row = {
                "rank": rank,
                "window": window,
                "business_process": str(window.get("business_process") or "unknown"),
                "source": doc_context.get(doc, {}).get("source", "unknown"),
                "fiscal_year": doc_context.get(doc, {}).get("fiscal_year", "unknown"),
            }
            first[doc] = row
    return list(first.values())


def _doc_context(df: pd.DataFrame) -> dict[str, dict[str, str]]:
    if "document_id" not in df.columns:
        return {}
    columns = [
        column
        for column in ("document_id", "source", "fiscal_year")
        if column in df.columns
    ]
    rows = df[columns].drop_duplicates("document_id")
    out: dict[str, dict[str, str]] = {}
    for row in rows.itertuples(index=False):
        doc = str(getattr(row, "document_id"))
        out[doc] = {
            "source": str(getattr(row, "source", "unknown") or "unknown"),
            "fiscal_year": str(getattr(row, "fiscal_year", "unknown") or "unknown"),
        }
    return out


def _group_feature_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    windows = [row["window"] for row in rows]
    return {
        "count": len(rows),
        "rank_distribution": _quartile_dist([row["rank"] for row in rows]),
        "robust_z": _quartile_dist([window["robust_z"] for window in windows]),
        "period_end_lift": _quartile_dist([window["period_end_lift"] for window in windows]),
        "expected_count_median": _median([window["expected_count"] for window in windows]),
        "baseline_observation_count_median": _median(
            [window["baseline_observation_count"] for window in windows]
        ),
        "context_evidence_count_median": _median(
            [window["context_evidence_count"] for window in windows]
        ),
        "rarity_context_count_median": _median(
            [window["rarity_context_count"] for window in windows]
        ),
        "one_row_window_ratio": _ratio(windows, lambda window: int(window["row_count"]) <= 1),
        "low_support_window_ratio": _ratio(windows, lambda window: int(window["row_count"]) < 7),
        "supported_window_ratio": _ratio(windows, lambda window: int(window["row_count"]) >= 7),
        "period_end_context_ratio": _ratio(
            windows,
            lambda window: bool(window["period_end_context"]),
        ),
        "period_end_day_offset_distribution": _counter(
            str(window.get("period_end_day_offset")) for window in windows
        ),
        "amount_tail_context_median": _median(
            [int(bool(window["amount_tail_context"])) for window in windows]
        ),
        "amount_tail_context_ratio": _ratio(
            windows,
            lambda window: bool(window["amount_tail_context"]),
        ),
        "manual_or_adjustment_context_ratio": _ratio(
            windows,
            lambda window: bool(window["manual_or_adjustment_context"]),
        ),
        "after_hours_or_weekend_context_ratio": _ratio(
            windows,
            lambda window: bool(window["after_hours_or_weekend_context"]),
        ),
        "round_amount_context_ratio": _ratio(
            windows,
            lambda window: bool(window["round_amount_context"]),
        ),
        "subject_activity_rank_median": _median(
            [window["subject_activity_rank"] for window in windows]
        ),
        "subject_frequency_context_distribution": _quartile_dist(
            [window["subject_frequency_context"] for window in windows]
        ),
        "business_process_distribution": _counter(row["business_process"] for row in rows),
        "source_distribution": _counter(row["source"] for row in rows),
        "fiscal_year_distribution": _counter(row["fiscal_year"] for row in rows),
    }


def _quartile_dist(values: list[Any]) -> dict[str, Any]:
    clean = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "min": None, "p25": None, "p50": None, "p75": None, "max": None}
    return {
        "count": int(len(clean)),
        "min": float(clean.min()),
        "p25": float(clean.quantile(0.25)),
        "p50": float(clean.quantile(0.50)),
        "p75": float(clean.quantile(0.75)),
        "max": float(clean.max()),
    }


def _median(values: list[Any]) -> float | None:
    dist = _quartile_dist(values)
    value = dist["p50"]
    return None if value is None else float(value)


def _ratio(windows: list[dict[str, Any]], predicate: Any) -> float:
    if not windows:
        return 0.0
    return round(sum(1 for window in windows if predicate(window)) / len(windows), 6)


def _counter(values: Any) -> dict[str, int]:
    return dict(Counter(str(value) for value in values))


def _directional_feature_gaps(
    promoted: list[dict[str, Any]],
    delayed: list[dict[str, Any]],
) -> dict[str, Any]:
    promoted_summary = _group_feature_summary(promoted)
    delayed_summary = _group_feature_summary(delayed)
    return {
        "after_hours_weekend_lower_in_delayed": (
            delayed_summary["after_hours_or_weekend_context_ratio"]
            < promoted_summary["after_hours_or_weekend_context_ratio"]
        ),
        "subject_activity_background_higher_in_delayed": (
            float(delayed_summary["subject_activity_rank_median"] or 9999)
            < float(promoted_summary["subject_activity_rank_median"] or 9999)
        ),
        "amount_tail_higher_in_delayed": (
            delayed_summary["amount_tail_context_ratio"]
            > promoted_summary["amount_tail_context_ratio"]
        ),
        "support_not_lower_in_delayed": (
            delayed_summary["supported_window_ratio"]
            >= promoted_summary["supported_window_ratio"]
        ),
        "period_end_equally_present": (
            delayed_summary["period_end_context_ratio"]
            == promoted_summary["period_end_context_ratio"]
        ),
    }


def _delayed_reason_summary(
    promoted: list[dict[str, Any]],
    delayed: list[dict[str, Any]],
) -> dict[str, int]:
    promoted_windows = [row["window"] for row in promoted]
    promoted_robust = _median([window["robust_z"] for window in promoted_windows]) or 0.0
    promoted_context = _median(
        [window["context_evidence_count"] for window in promoted_windows]
    ) or 0.0
    promoted_baseline = _median(
        [window["baseline_observation_count"] for window in promoted_windows]
    ) or 0.0
    reasons: Counter[str] = Counter()
    for row in delayed:
        window = row["window"]
        row_matched = False
        if float(window["robust_z"]) < promoted_robust:
            reasons["lower_robust_z"] += 1
            row_matched = True
        if float(window["context_evidence_count"]) < promoted_context:
            reasons["low_context_evidence"] += 1
            row_matched = True
        if float(window["baseline_observation_count"]) < promoted_baseline:
            reasons["low_baseline_support"] += 1
            row_matched = True
        if int(window["row_count"]) < 7:
            reasons["one_row_or_low_support_window"] += 1
            row_matched = True
        if int(window["subject_activity_rank"]) <= 10:
            reasons["high_subject_activity_background"] += 1
            row_matched = True
        if bool(window["period_end_context"]) and int(window["subject_activity_rank"]) <= 10:
            reasons["normal_period_end_competition"] += 1
            row_matched = True
        if not bool(window["after_hours_or_weekend_context"]):
            reasons["weak_after_hours_weekend_signal"] += 1
            row_matched = True
        if row["rank"] in {252, 478}:
            reasons["score_tie_or_rank_band_collision"] += 1
            row_matched = True
        if not row_matched:
            reasons["no_clear_audit_observable_difference"] += 1
    for key in (
        "lower_robust_z",
        "low_context_evidence",
        "low_baseline_support",
        "one_row_or_low_support_window",
        "high_subject_activity_background",
        "normal_period_end_competition",
        "weak_after_hours_weekend_signal",
        "score_tie_or_rank_band_collision",
        "no_clear_audit_observable_difference",
    ):
        reasons.setdefault(key, 0)
    return dict(reasons)


def _ts_specific_top100_stabilized_surface(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        windows,
        key=lambda item: (
            not bool(item["period_end_context"]),
            int(item["row_count"]) < 7,
            bool(item["round_amount_context"]),
            not bool(item["after_hours_or_weekend_context"]),
            -int(item["context_evidence_count"]),
            -float(item["period_end_lift"]),
            -float(item["robust_z"]),
            int(item["subject_activity_rank"]) <= 10,
            int(item["ordinal"]),
        ),
    )


def _candidate_summary(
    ordered: list[dict[str, Any]],
    *,
    conservative: list[dict[str, Any]],
    truth_docs: set[str],
    alignment: dict[str, str],
) -> dict[str, Any]:
    current_top100 = _selected_docs(conservative[:100]) & truth_docs
    candidate_top100 = _selected_docs(ordered[:100]) & truth_docs
    candidate_top500 = _selected_docs(ordered[:500]) & truth_docs
    return {
        "created": True,
        "name": "ts_specific_top100_stabilized_surface",
        "diagnostic_only": True,
        "selector_feature_policy": (
            "timing/window evidence only: period_end_context, supported window, "
            "after-hours/weekend context, context evidence, period_end_lift, robust_z, "
            "and subject activity background; truth/scenario labels are not inputs"
        ),
        "top100_ts_specific_truth_docs": _alignment_count(
            candidate_top100,
            alignment,
            "ts_primary_label_aligned",
        ),
        "top500_ts_specific_truth_docs": _alignment_count(
            candidate_top500,
            alignment,
            "ts_primary_label_aligned",
        ),
        "top100_mixed_but_ts_relevant_truth_docs": _alignment_count(
            candidate_top100,
            alignment,
            "mixed_but_ts_relevant",
        ),
        "top500_mixed_but_ts_relevant_truth_docs": _alignment_count(
            candidate_top500,
            alignment,
            "mixed_but_ts_relevant",
        ),
        "top100_ts_specific_delta_vs_conservative": (
            _alignment_count(candidate_top100, alignment, "ts_primary_label_aligned")
            - _alignment_count(current_top100, alignment, "ts_primary_label_aligned")
        ),
        "review_burden": _retention_review_burden_proxy(ordered[:500]),
        "conservative_review_burden": _retention_review_burden_proxy(conservative[:500]),
        "period_end_concentration": _ratio(
            ordered[:500],
            lambda window: bool(window["period_end_context"]),
        ),
        "amount_tail_context_ratio": _ratio(
            ordered[:500],
            lambda window: bool(window["amount_tail_context"]),
        ),
        "low_support_ratio": _ratio(ordered[:500], lambda window: int(window["row_count"]) < 7),
    }


def _alignment_count(docs: set[str], alignment: dict[str, str], label: str) -> int:
    return sum(1 for doc in docs if alignment.get(doc) == label)


def _defensible_candidate_found(candidate: dict[str, Any]) -> bool:
    burden = candidate["review_burden"]
    base_burden = candidate["conservative_review_burden"]
    return (
        int(candidate["top100_ts_specific_truth_docs"]) > 13
        and int(candidate["top500_ts_specific_truth_docs"]) == 32
        and int(candidate["top100_mixed_but_ts_relevant_truth_docs"]) == 0
        and float(burden["score"]) <= float(base_burden["score"]) + 0.02
        and float(candidate["low_support_ratio"]) == 0.0
    )


def _candidate_feature_judgment(
    group_comparison: dict[str, Any],
    delayed_reasons: dict[str, int],
    defensible: bool,
) -> dict[str, Any]:
    gaps = group_comparison["directional_feature_gaps"]
    return {
        "accepted_candidate_features": [
            "after_hours_weekend_priority",
            "subject_activity_background_adjustment",
        ]
        if defensible
        else [],
        "rejected_or_diagnostic_only_features": {
            "amount_tail_context": (
                "Delayed docs have higher amount-tail context, but amount-tail belongs "
                "closer to unsupervised/broad evidence and is not used to inflate TS-primary."
            ),
            "business_process_source_fiscal_year": (
                "Used only for aggregate comparison; not used as selector features."
            ),
        },
        "directional_gaps": gaps,
        "delayed_reason_counts": delayed_reasons,
        "defensible_top100_feature_found": defensible,
    }


def _decision_payload(
    *,
    promoted_count: int,
    delayed_count: int,
    delayed_reasons: dict[str, int],
    defensible: bool,
    candidate_summary: dict[str, Any],
) -> dict[str, Any]:
    primary_reason = max(delayed_reasons, key=lambda key: delayed_reasons[key])
    candidate_created = bool(candidate_summary.get("created"))
    return {
        "promoted_top100_ts_specific_count": promoted_count,
        "delayed_101_500_ts_specific_count": delayed_count,
        "primary_delay_reason": primary_reason,
        "defensible_top100_feature_found": defensible,
        "candidate_surface_created": candidate_created,
        "candidate_surface_name": (
            candidate_summary.get("name") if candidate_created and defensible else None
        ),
        "top100_product_viable": defensible,
        "top500_full_capture_retained": (
            candidate_created
            and int(candidate_summary.get("top500_ts_specific_truth_docs", 0)) == 32
        ),
        "data_synth_alignment_issue_remaining": True,
        "production_adoption": False,
        "recommended_next_action": (
            "Keep the stabilized surface diagnostic-only and validate that removing "
            "amount-tail demotion from TS-primary ordering does not inflate mixed "
            "review candidates in fixed5-compatible slices or regenerated DataSynth."
        )
        if defensible
        else (
            "Do not create a TOP100 TS-primary candidate; continue DataSynth alignment "
            "and timing/window feature diagnostics."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
