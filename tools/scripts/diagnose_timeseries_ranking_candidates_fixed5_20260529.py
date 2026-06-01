"""Diagnostic-only TS ranking candidate comparison for fixed5.

This script does not change detector thresholds, native case generation,
PHASE1 ranking, or PHASE2 family fusion. Candidate scores are computed after
native TimeseriesCase objects exist and are evaluated only as aggregate
diagnostics. Raw document IDs remain in memory and are not written.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.phase2_case import TimeseriesCase
from src.services.phase2_case_set_orchestrator import build_phase2_case_set
from tools.scripts.measure_phase2_native_cases_fixed5_20260528 import (
    BATCH_ID,
    DATASET_NAME,
    TOP_NS,
    _case_documents,
    _load_case_input,
    _load_truth,
    _run_rule_detector,
    _sorted_cases,
)

OUT_JSON = ROOT / "artifacts" / "timeseries_ranking_candidates_fixed5_20260529.json"

_WEIGHT_PROVENANCE = {
    "label": "fixed5 exploratory diagnostic weights",
    "calibration_status": "not calibrated",
    "production_policy": "not production ranking policy",
    "adoption_requirement": "requires cross-batch/fixture validation before adoption",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _log_lift(case: TimeseriesCase) -> float:
    return math.log1p(max(_finite(case.period_end_lift), 0.0))


def _context_count(case: TimeseriesCase) -> float:
    return _finite(case.context_evidence_count)


def _robust_z(case: TimeseriesCase) -> float:
    return _finite(case.robust_z)


def _subject_activity_adjustment(case: TimeseriesCase) -> float:
    # Lower subject_activity_rank means more active subject background. Diagnostic
    # candidate gives a small lift to less-active subjects, without touching product sort.
    rank = _finite(case.subject_activity_rank, default=0.0)
    return math.log1p(rank) if rank > 0 else 0.0


def _baseline_sufficiency(case: TimeseriesCase) -> float:
    obs = _finite(case.baseline_observation_count)
    if obs <= 0:
        return 0.0
    return min(obs / 10.0, 1.0)


def _daily_expected_ratio(case: TimeseriesCase) -> float:
    expected = _finite(case.expected_count)
    if expected <= 0:
        return 0.0
    observed = max(_finite(case.window_count), _finite(case.daily_count))
    return observed / expected


def _period_end_normalized_score(case: TimeseriesCase) -> float:
    if not bool(case.period_end_context):
        return 0.0
    historical_ratio = _finite(case.subject_period_end_historical_ratio)
    lift = _finite(case.period_end_lift)
    context = _context_count(case)
    return (_robust_z(case) + 0.25 * context) / (1.0 + historical_ratio + math.log1p(lift))


def _non_period_end_surprise_score(case: TimeseriesCase) -> float:
    lift = _finite(case.period_end_lift)
    period_end_penalty = 0.65 if bool(case.period_end_context) else 1.0
    if lift > 0 and lift < 2.0:
        period_end_penalty = max(period_end_penalty, 0.85)
    return (_robust_z(case) + 0.30 * _context_count(case)) * period_end_penalty


def _mixed_signal_score(case: TimeseriesCase) -> float:
    robust = _robust_z(case)
    context = _context_count(case)
    lift = _finite(case.period_end_lift)
    if robust < 1.0 or context < 2:
        return 0.0
    lift_dominance_penalty = min(math.log1p(lift), 2.5) * 0.20
    period_end_lift = 0.40 if bool(case.period_end_context) else 0.0
    return robust + 0.45 * context + period_end_lift - lift_dominance_penalty


def _normal_closing_spike_strength(case: TimeseriesCase) -> float:
    if not _is_normal_closing_proxy(case):
        return 0.0
    ratio = _finite(case.subject_period_end_historical_ratio)
    lift = _finite(case.period_end_lift)
    baseline = _finite(case.subject_non_period_end_baseline_count)
    return min(2.0, ratio * 2.0) + min(2.0, math.log1p(lift)) + min(1.0, baseline / 5.0)


def _candidate_score(candidate: str, case: TimeseriesCase) -> float:
    if candidate == "robust_z_context_composite":
        return _robust_z(case) + 0.35 * _context_count(case)
    if candidate == "period_end_lift_robust_balanced":
        return _robust_z(case) + 0.75 * _log_lift(case)
    if candidate == "period_end_normalized_mixed_signal":
        return _robust_z(case) + 0.30 * _context_count(case) + 0.40 * _log_lift(case)
    if candidate == "subject_activity_rank_adjusted":
        return (
            _robust_z(case)
            + 0.25 * _context_count(case)
            + 0.15 * _subject_activity_adjustment(case)
        )
    if candidate == "robust_context_baseline_sufficiency":
        sufficiency = _baseline_sufficiency(case)
        return (_robust_z(case) + 0.40 * _context_count(case)) * (0.55 + 0.45 * sufficiency)
    if candidate == "mixed_signal_period_end_demoted":
        return _mixed_signal_score(case) - 0.55 * _normal_closing_spike_strength(case)
    if candidate == "non_period_end_surprise_priority":
        return _non_period_end_surprise_score(case)
    if candidate == "review_burden_penalized_context":
        return _robust_z(case) + 0.45 * _context_count(case)
    raise ValueError(f"unknown candidate: {candidate}")


def _candidate_order(cases: list[TimeseriesCase], candidate: str) -> list[TimeseriesCase]:
    if candidate == "current_native_ts_ordering":
        return [case for case in _sorted_cases(cases) if isinstance(case, TimeseriesCase)]
    if candidate == "ts01_ts02_balanced_surface":
        return _balanced_sub_rule_order(cases)
    if candidate == "review_burden_penalized_context":
        return _review_burden_penalized_order(cases, candidate)
    if candidate == "review_burden_closing_demoted_context":
        return _review_burden_closing_demoted_order(cases)
    return sorted(
        cases,
        key=lambda case: (
            -_candidate_score(candidate, case),
            -_finite(case.family_score),
            case.phase2_case_id,
        ),
    )


def _balanced_sub_rule_order(cases: list[TimeseriesCase]) -> list[TimeseriesCase]:
    by_rule: dict[str, list[TimeseriesCase]] = {}
    for case in cases:
        by_rule.setdefault(str(case.sub_rule), []).append(case)
    for rule, rule_cases in by_rule.items():
        by_rule[rule] = sorted(
            rule_cases,
            key=lambda case: (
                -_candidate_score("robust_context_baseline_sufficiency", case),
                -_finite(case.family_score),
                case.phase2_case_id,
            ),
        )
    rules = sorted(by_rule)
    out: list[TimeseriesCase] = []
    seen: set[str] = set()
    index = 0
    while len(out) < len(cases):
        progressed = False
        for rule in rules:
            bucket = by_rule[rule]
            if index < len(bucket):
                case = bucket[index]
                if case.phase2_case_id not in seen:
                    out.append(case)
                    seen.add(case.phase2_case_id)
                progressed = True
        if not progressed:
            break
        index += 1
    return out


def _window_kind_for_case(case: TimeseriesCase) -> str:
    return "single_day" if str(case.window_start) == str(case.window_end) else "trailing_window"


def _review_burden_penalized_order(
    cases: list[TimeseriesCase],
    candidate: str,
) -> list[TimeseriesCase]:
    subject_kind_counts = Counter(
        (str(case.subject), _window_kind_for_case(case)) for case in cases
    )
    return sorted(
        cases,
        key=lambda case: (
            -(
                _candidate_score(candidate, case)
                / math.sqrt(
                    max(
                        subject_kind_counts[(str(case.subject), _window_kind_for_case(case))],
                        1,
                    )
                )
            ),
            -_finite(case.family_score),
            case.phase2_case_id,
        ),
    )


def _review_burden_closing_demoted_order(cases: list[TimeseriesCase]) -> list[TimeseriesCase]:
    subject_kind_counts = Counter(
        (str(case.subject), _window_kind_for_case(case)) for case in cases
    )

    def score(case: TimeseriesCase) -> float:
        burden = math.sqrt(
            max(subject_kind_counts[(str(case.subject), _window_kind_for_case(case))], 1)
        )
        period_end_penalty = 0.10 if bool(case.period_end_context) else 0.0
        return (
            (_robust_z(case) + 0.45 * _context_count(case)) / burden
            - 0.10 * _normal_closing_spike_strength(case)
            - period_end_penalty
        )

    return sorted(
        cases,
        key=lambda case: (-score(case), -_finite(case.family_score), case.phase2_case_id),
    )


def _truth_metrics(
    ordered: list[TimeseriesCase],
    *,
    truth_docs: set[str],
) -> dict[str, Any]:
    case_doc_sets = [_case_documents(case) for case in ordered]
    topn: dict[str, dict[str, Any]] = {}
    for top_n in TOP_NS:
        docs: set[str] = set()
        for doc_set in case_doc_sets[:top_n]:
            docs.update(doc_set)
        matched_docs = docs & truth_docs
        topn[str(top_n)] = {
            "matched": len(matched_docs),
            "recall": len(matched_docs) / max(len(truth_docs), 1),
        }

    first_truth_rank: int | None = None
    for rank, doc_set in enumerate(case_doc_sets, start=1):
        if doc_set & truth_docs:
            first_truth_rank = rank
            break
    return {"topn": topn, "first_truth_rank": first_truth_rank}


def _distribution_counts(ordered: list[TimeseriesCase], top_n: int = 500) -> dict[str, Any]:
    top = ordered[:top_n]
    period_end = sum(1 for case in top if bool(case.period_end_context))
    mixed_count = sum(1 for case in top if _is_mixed_period_end(case))
    normal_closing_proxy = sum(1 for case in top if _is_normal_closing_proxy(case))
    rule_counts = Counter(case.sub_rule for case in top)
    subject_counts = Counter(str(case.subject) for case in top)
    baseline_sufficient = sum(1 for case in top if _baseline_sufficiency(case) >= 1.0)
    false_positive_pressure = _false_positive_pressure_proxy(top)
    return {
        "top_n": top_n,
        "period_end_context": {
            "true": period_end,
            "false": len(top) - period_end,
            "true_share": period_end / max(len(top), 1),
        },
        "sub_rule_counts": dict(sorted(rule_counts.items())),
        "mixed_period_end_context_count": mixed_count,
        "normal_closing_spike_proxy": {
            "count": normal_closing_proxy,
            "share": normal_closing_proxy / max(len(top), 1),
        },
        "subject_concentration": {
            "unique_subject_count": len(subject_counts),
            "top1_share": subject_counts.most_common(1)[0][1] / max(len(top), 1)
            if subject_counts
            else 0.0,
            "top5_share": sum(count for _subject, count in subject_counts.most_common(5))
            / max(len(top), 1),
        },
        "baseline_sufficient_ratio": baseline_sufficient / max(len(top), 1),
        "false_positive_pressure_proxy": false_positive_pressure,
    }


def _is_mixed_period_end(case: TimeseriesCase) -> bool:
    return bool(case.period_end_context) and _robust_z(case) > 1.0 and _context_count(case) >= 3


def _is_normal_closing_proxy(case: TimeseriesCase) -> bool:
    ratio = _finite(case.subject_period_end_historical_ratio, default=0.0)
    lift = _finite(case.period_end_lift, default=0.0)
    return bool(case.period_end_context) and ratio >= 0.10 and lift >= 4.0


def _false_positive_pressure_proxy(cases: list[TimeseriesCase]) -> dict[str, Any]:
    if not cases:
        return {
            "score": 0.0,
            "normal_closing_spike_share": 0.0,
            "low_context_share": 0.0,
            "baseline_insufficient_share": 0.0,
            "subject_top1_share": 0.0,
        }
    n = len(cases)
    normal_share = sum(1 for case in cases if _is_normal_closing_proxy(case)) / n
    low_context_share = sum(1 for case in cases if _context_count(case) < 2) / n
    baseline_insufficient_share = sum(1 for case in cases if _baseline_sufficiency(case) < 1.0) / n
    subject_counts = Counter(str(case.subject) for case in cases)
    top1_share = subject_counts.most_common(1)[0][1] / n if subject_counts else 0.0
    score = (
        0.45 * normal_share
        + 0.20 * low_context_share
        + 0.20 * baseline_insufficient_share
        + 0.15 * top1_share
    )
    return {
        "score": score,
        "normal_closing_spike_share": normal_share,
        "low_context_share": low_context_share,
        "baseline_insufficient_share": baseline_insufficient_share,
        "subject_top1_share": top1_share,
    }


def _numeric_distribution(values: Iterable[Any]) -> dict[str, Any]:
    clean = [_finite(value) for value in values if value is not None]
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


def _new_top500_profile(
    *,
    current: list[TimeseriesCase],
    candidate_ordered: list[TimeseriesCase],
) -> dict[str, Any]:
    current_ids = {case.phase2_case_id for case in current[:500]}
    promoted = [case for case in candidate_ordered[:500] if case.phase2_case_id not in current_ids]
    return {
        "new_case_count": len(promoted),
        "period_end_context_count": sum(1 for case in promoted if bool(case.period_end_context)),
        "mixed_period_end_context_count": sum(1 for case in promoted if _is_mixed_period_end(case)),
        "sub_rule_counts": dict(sorted(Counter(case.sub_rule for case in promoted).items())),
        "robust_z_distribution": _numeric_distribution(case.robust_z for case in promoted),
        "period_end_lift_distribution": _numeric_distribution(
            case.period_end_lift for case in promoted
        ),
        "context_evidence_count_distribution": _numeric_distribution(
            case.context_evidence_count for case in promoted
        ),
        "subject_activity_rank_distribution": _numeric_distribution(
            case.subject_activity_rank for case in promoted
        ),
        "daily_expected_ratio_distribution": _numeric_distribution(
            _daily_expected_ratio(case) for case in promoted
        ),
        "period_end_normalized_score_distribution": _numeric_distribution(
            _period_end_normalized_score(case) for case in promoted
        ),
        "non_period_end_surprise_score_distribution": _numeric_distribution(
            _non_period_end_surprise_score(case) for case in promoted
        ),
        "mixed_signal_score_distribution": _numeric_distribution(
            _mixed_signal_score(case) for case in promoted
        ),
    }


def _candidate_summary(
    *,
    candidate: str,
    cases: list[TimeseriesCase],
    current_order: list[TimeseriesCase],
    truth_docs: set[str],
) -> dict[str, Any]:
    ordered = _candidate_order(cases, candidate)
    top500_ids = {case.phase2_case_id for case in ordered[:500]}
    current_top500_ids = {case.phase2_case_id for case in current_order[:500]}
    return {
        "description": _CANDIDATE_DESCRIPTIONS[candidate],
        "weight_provenance": dict(_WEIGHT_PROVENANCE),
        "diagnostic_only": True,
        "native_product_ordering_changed": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_ranking_changed": False,
        "threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        **_truth_metrics(ordered, truth_docs=truth_docs),
        "top500_distribution": _distribution_counts(ordered, 500),
        "top500_new_case_count_vs_current": len(top500_ids - current_top500_ids),
        "new_top500_context_profile": _new_top500_profile(
            current=current_order,
            candidate_ordered=ordered,
        ),
    }


_CANDIDATE_DESCRIPTIONS: dict[str, str] = {
    "current_native_ts_ordering": (
        "Current native TS ordering: evidence_tier, family_score desc, case id."
    ),
    "robust_z_context_composite": "Diagnostic score: robust_z plus context_evidence_count.",
    "period_end_lift_robust_balanced": "Diagnostic score: robust_z balanced with period_end_lift.",
    "period_end_normalized_mixed_signal": (
        "Diagnostic score preserving mixed period-end robust/context signal."
    ),
    "subject_activity_rank_adjusted": "Diagnostic score with small less-active-subject adjustment.",
    "robust_context_baseline_sufficiency": (
        "Diagnostic score combining robust_z, context evidence, and baseline sufficiency."
    ),
    "mixed_signal_period_end_demoted": (
        "Diagnostic score preserving robust/context period-end signal while demoting "
        "normal closing spikes."
    ),
    "non_period_end_surprise_priority": (
        "Diagnostic score prioritizing robust surprise outside dominant period-end context."
    ),
    "ts01_ts02_balanced_surface": (
        "Diagnostic interleaved TS01/TS02 surface for concentration comparison only."
    ),
    "review_burden_penalized_context": (
        "Diagnostic score reducing repeated subject/window_kind concentration pressure."
    ),
    "review_burden_closing_demoted_context": (
        "Diagnostic repeated-subject pressure score with weak normal-closing demotion."
    ),
}


def _case_feature_payload(cases: list[TimeseriesCase]) -> dict[str, Any]:
    return {
        "robust_z": _numeric_distribution(case.robust_z for case in cases),
        "expected_count": _numeric_distribution(case.expected_count for case in cases),
        "baseline_observation_count": _numeric_distribution(
            case.baseline_observation_count for case in cases
        ),
        "period_end_context": dict(
            sorted(Counter(str(bool(case.period_end_context)) for case in cases).items())
        ),
        "period_end_lift": _numeric_distribution(case.period_end_lift for case in cases),
        "subject_period_end_historical_ratio": _numeric_distribution(
            case.subject_period_end_historical_ratio for case in cases
        ),
        "subject_non_period_end_baseline_count": _numeric_distribution(
            case.subject_non_period_end_baseline_count for case in cases
        ),
        "amount_tail_context": _numeric_distribution(case.amount_tail_context for case in cases),
        "manual_or_adjustment_context": _numeric_distribution(
            case.manual_or_adjustment_context for case in cases
        ),
        "after_hours_or_weekend_context": _numeric_distribution(
            case.after_hours_or_weekend_context for case in cases
        ),
        "round_amount_context": _numeric_distribution(case.round_amount_context for case in cases),
        "rarity_context_count": _numeric_distribution(case.rarity_context_count for case in cases),
        "context_evidence_count": _numeric_distribution(
            case.context_evidence_count for case in cases
        ),
        "subject_activity_rank": _numeric_distribution(
            case.subject_activity_rank for case in cases
        ),
        "window_kind": dict(sorted(Counter(_window_kind_for_case(case) for case in cases).items())),
        "sub_rule": dict(sorted(Counter(str(case.sub_rule) for case in cases).items())),
        "daily_count_expected_count_ratio": _numeric_distribution(
            _daily_expected_ratio(case) for case in cases
        ),
        "baseline_sufficiency_flag": dict(
            sorted(
                Counter(
                    "sufficient" if _baseline_sufficiency(case) >= 1.0 else "insufficient"
                    for case in cases
                ).items()
            )
        ),
        "period_end_normalized_score": _numeric_distribution(
            _period_end_normalized_score(case) for case in cases
        ),
        "non_period_end_surprise_score": _numeric_distribution(
            _non_period_end_surprise_score(case) for case in cases
        ),
        "mixed_signal_score": _numeric_distribution(_mixed_signal_score(case) for case in cases),
        "normal_closing_spike_proxy": {
            "count": sum(1 for case in cases if _is_normal_closing_proxy(case)),
            "share": sum(1 for case in cases if _is_normal_closing_proxy(case))
            / max(len(cases), 1),
        },
    }


def _safe_artifact_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _raw_identifier_leak_report(
    payload: dict[str, Any],
    *,
    truth_docs: set[str],
) -> dict[str, int]:
    text = _safe_artifact_text(payload)
    forbidden_keys = {
        "document_id",
        "document_ids",
        "raw_document_id",
        "raw_document_ids",
        "row_id",
        "row_ids",
        "raw_row_id",
        "raw_row_ids",
        "index_label",
        "raw_index_label",
        "phase2_case_id",
        "phase2_case_ids",
    }
    return {
        "doc_like_token_count": sum(1 for document_id in truth_docs if document_id in text),
        "forbidden_identifier_key_count": sum(
            1
            for key in _walk_json_keys(payload)
            if str(key) in forbidden_keys
        ),
        "phase2_case_id_like_token_count": len(re.findall(r"p2_timeseries_window_", text)),
    }


def _walk_json_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_keys(child)


def main() -> int:
    started = time.perf_counter()
    df = _load_case_input()
    truth = _load_truth()
    truth_docs = set(truth["document_id"].astype(str))

    ts_result = _run_rule_detector("timeseries", df)
    case_set = build_phase2_case_set(
        batch_id=BATCH_ID,
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
        for candidate in _CANDIDATE_DESCRIPTIONS
    }
    payload = {
        "generated_at": _now_iso(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "dataset": DATASET_NAME,
        "diagnostic_scope": "timeseries native case ranking candidates only",
        "case_count": len(cases),
        "truth_document_count": len(truth_docs),
        "top_ns": list(TOP_NS),
        "no_fitting_assertions": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
        },
        "guardrails": [
            "No detector thresholds, native case gates, PHASE1 ranking, or PHASE2 "
            "fusion are changed.",
            "Truth labels are used only for aggregate after-the-fact evaluation.",
            "Raw document identifiers and raw row identifiers are not emitted.",
            "Candidate weights are fixed5 exploratory diagnostic weights, not "
            "calibrated, not production ranking policy, and require cross-batch/"
            "fixture validation before adoption.",
        ],
        "candidate_weight_provenance": dict(_WEIGHT_PROVENANCE),
        "feature_diagnostics": {
            "all_cases": _case_feature_payload(cases),
            "current_top500": _case_feature_payload(current_order[:500]),
            "diagnostic_note": (
                "Feature distributions are aggregate-only and are not used by product ordering."
            ),
        },
        "candidates": candidates,
    }
    payload["raw_identifier_leak_check"] = _raw_identifier_leak_report(
        payload,
        truth_docs=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(f"wrote {OUT_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
