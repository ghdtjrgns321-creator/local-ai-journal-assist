"""Duplicate Phase 5 remaining potential diagnostic.

The goal is not to maximize recall. This script checks whether the remaining
generated/capped duplicate potential missed by the current first-review TOP100
has audit-observable feature differences that justify a future candidate. It
does not change production first-review ordering, detector thresholds, row
scores, PHASE1 ranking, or PHASE2 family fusion.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    raw_identifier_leak_check,
)
from tools.scripts.diagnose_duplicate_phase1_uplift_fixed5_20260529 import (
    _case_docs_for_top_n,
    _load_case_input,
    _load_truth,
    _phase1_bucket,
    _phase1_doc_rank_map,
    _policy_constraints,
)
from tools.scripts.diagnose_duplicate_retention_candidates_fixed5_20260529 import (
    _case_docs,
    _case_result_for_pairs,
    _default_order_cases,
    _doc_set_from_pairs,
    _measure_ordered_cases,
    _pair_docs,
    _select_pair_diversity_score,
    _select_score_order,
    _tier,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

OUT_JSON = ROOT / "artifacts" / "duplicate_remaining_potential_fixed5_20260530.json"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    phase1_result: Path
    truth_csv: Path
    retention_batch_prefix: str


BATCHES = (
    BatchSpec(
        name="fixed5_normalcal5",
        dataset="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl",
        phase1_result=ROOT / "artifacts" / "stage7_fixed5_normalcal5_phase1_case_result.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
        / "labels"
        / "manipulated_entry_truth.csv",
        retention_batch_prefix="fixed5_duplicate_remaining_potential",
    ),
    BatchSpec(
        name="fixed4",
        dataset="datasynth_manipulation_v7_candidate_fixed4",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl",
        phase1_result=ROOT / "artifacts" / "stage7_fixed4_phase1_case_result.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed4"
        / "labels"
        / "manipulated_entry_truth.csv",
        retention_batch_prefix="fixed4_duplicate_remaining_potential",
    ),
)


def _load_phase1_case_priority(path: Path) -> tuple[Any, dict[str, float]]:
    with path.open("rb") as fh:
        result = pickle.load(fh)
    priority_by_doc: dict[str, float] = {}
    for case in getattr(result, "cases", ()):
        priority = float(getattr(case, "priority_score", 0.0) or 0.0)
        for ref in getattr(case, "documents", ()):
            doc = getattr(ref, "document_id", None)
            if doc in (None, ""):
                continue
            priority_by_doc.setdefault(str(doc), priority)
    return result, priority_by_doc


def _priority_bucket(value: float | None) -> str:
    if value is None:
        return "phase1_not_in_cases"
    if value >= 0.9:
        return "priority_very_high"
    if value >= 0.7:
        return "priority_high"
    if value >= 0.4:
        return "priority_medium"
    return "priority_low"


def _feature(pair: dict[str, Any], key: str, default: Any = None) -> Any:
    features = pair.get("features")
    if isinstance(features, dict):
        return features.get(key, default)
    return default


def _float_feature(pair: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(_feature(pair, key, default) or default)
    except (TypeError, ValueError):
        return default


def _score(pair: dict[str, Any]) -> float:
    try:
        return float(pair.get("pair_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "p90": None, "max": None}
    vals = sorted(float(value) for value in values)

    def pick(pct: float) -> float:
        return vals[int(round((len(vals) - 1) * pct))]

    return {
        "min": round(vals[0], 6),
        "p50": round(pick(0.50), 6),
        "p90": round(pick(0.90), 6),
        "max": round(vals[-1], 6),
    }


def _band(value: float | None, cuts: tuple[float, ...], labels: tuple[str, ...]) -> str:
    if value is None:
        return "missing"
    for cut, label in zip(cuts, labels, strict=False):
        if value <= cut:
            return label
    return labels[-1]


def _similarity_band(value: float | None) -> str:
    return _band(
        value,
        (0.50, 0.75, 0.90, 0.98),
        ("<=0.50", "0.50_0.75", "0.75_0.90", "0.90_0.98", ">0.98"),
    )


def _amount_delta_band(pair: dict[str, Any]) -> str:
    amount_similarity = _float_feature(pair, "amount_similarity", 0.0)
    delta = max(0.0, 1.0 - amount_similarity)
    return _band(
        delta,
        (0.001, 0.01, 0.05, 0.20),
        ("<=0.001", "0.001_0.01", "0.01_0.05", "0.05_0.20", ">0.20"),
    )


def _date_distance_band(pair: dict[str, Any]) -> str:
    distance = _float_feature(pair, "date_distance_days", 999999.0)
    return _band(
        distance,
        (0, 1, 3, 7, 30),
        ("same_day", "1_day", "2_3_days", "4_7_days", "8_30_days", ">30_days"),
    )


def _period_end_bucket(pair: dict[str, Any]) -> str:
    if _feature(pair, "both_period_end_window_3d", False) is True:
        return "both_period_end_window_3d"
    distance = _feature(pair, "min_period_end_distance_days")
    if distance is None:
        return "unknown"
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return "unknown"
    if value <= 3:
        return "near_period_end_3d"
    if value <= 7:
        return "near_period_end_7d"
    return "not_near_period_end"


def _count_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value <= 2:
        return "2"
    if value <= 5:
        return "3_5"
    if value <= 20:
        return "6_20"
    if value <= 100:
        return "21_100"
    return ">100"


def _doc_pair_key(pair: dict[str, Any]) -> tuple[str, str]:
    docs = sorted(_pair_docs(pair))
    if len(docs) >= 2:
        return (docs[0], docs[1])
    if docs:
        return (docs[0], "")
    return ("", "")


def _pairs_for_docs(pairs: list[dict[str, Any]], docs: set[str]) -> list[dict[str, Any]]:
    return [pair for pair in pairs if _pair_docs(pair) & docs]


def _profile_group(
    *,
    name: str,
    docs: set[str],
    pairs: list[dict[str, Any]],
    rank_by_doc: dict[str, int],
    priority_by_doc: dict[str, float],
    doc_counts: Counter[str],
    pair_counts: Counter[tuple[str, str]],
) -> dict[str, Any]:
    related_pairs = _pairs_for_docs(pairs, docs)
    tiers = Counter(_tier(pair) for pair in related_pairs)
    same_partner_count = sum(1 for pair in related_pairs if _feature(pair, "same_partner") is True)
    rule_reason = Counter(str(pair.get("rule_id") or "unknown") for pair in related_pairs)
    diagnostic_reason = Counter(
        str(pair.get("diagnostic_reason") or pair.get("sub_reason") or "not_provided")
        for pair in related_pairs
    )
    doc_repetition = [
        max((doc_counts[doc] for doc in _pair_docs(pair)), default=0) for pair in related_pairs
    ]
    return {
        "group": name,
        "truth_doc_count": len(docs),
        "related_pair_count": len(related_pairs),
        "evidence_tier_distribution": dict(sorted(tiers.items())),
        "weak_moderate_strong_ratio": {
            "weak": round(tiers.get("weak", 0) / len(related_pairs), 6)
            if related_pairs
            else 0.0,
            "moderate": round(tiers.get("moderate", 0) / len(related_pairs), 6)
            if related_pairs
            else 0.0,
            "strong": round(tiers.get("strong", 0) / len(related_pairs), 6)
            if related_pairs
            else 0.0,
        },
        "case_grade_pair_ratio": round(
            sum(1 for pair in related_pairs if _tier(pair) in {"strong", "moderate"})
            / len(related_pairs),
            6,
        )
        if related_pairs
        else 0.0,
        "pair_score_quantiles": _quantiles([_score(pair) for pair in related_pairs]),
        "same_partner_ratio": round(same_partner_count / len(related_pairs), 6)
        if related_pairs
        else 0.0,
        "reference_similarity_band_distribution": dict(
            sorted(
                Counter(
                    _similarity_band(_float_feature(pair, "reference_similarity", 0.0))
                    for pair in related_pairs
                ).items()
            )
        ),
        "text_similarity_band_distribution": dict(
            sorted(
                Counter(
                    _similarity_band(_float_feature(pair, "text_similarity", 0.0))
                    for pair in related_pairs
                ).items()
            )
        ),
        "amount_similarity_quantiles": _quantiles(
            [_float_feature(pair, "amount_similarity", 0.0) for pair in related_pairs]
        ),
        "amount_delta_band_distribution": dict(
            sorted(Counter(_amount_delta_band(pair) for pair in related_pairs).items())
        ),
        "posting_date_distance_band_distribution": dict(
            sorted(Counter(_date_distance_band(pair) for pair in related_pairs).items())
        ),
        "document_pair_repetition_bucket_distribution": dict(
            sorted(
                Counter(
                    _count_bucket(pair_counts[_doc_pair_key(pair)]) for pair in related_pairs
                ).items()
            )
        ),
        "left_right_document_repetition_bucket_distribution": dict(
            sorted(Counter(_count_bucket(value) for value in doc_repetition).items())
        ),
        "period_end_context_bucket_distribution": dict(
            sorted(Counter(_period_end_bucket(pair) for pair in related_pairs).items())
        ),
        "phase1_rank_bucket_distribution": dict(
            sorted(Counter(_phase1_bucket(rank_by_doc.get(doc)) for doc in docs).items())
        ),
        "phase1_action_tier_bucket_distribution": dict(
            sorted(
                Counter(_priority_bucket(priority_by_doc.get(doc)) for doc in docs).items()
            )
        ),
        "duplicate_sub_reason_distribution": dict(sorted(rule_reason.items())),
        "diagnostic_reason_distribution": dict(sorted(diagnostic_reason.items())),
    }


def _classify_missed_docs(
    *,
    missed_docs: set[str],
    generated_pairs: list[dict[str, Any]],
    current_top500_pairs: list[dict[str, Any]],
    current_top100_docs: set[str],
    doc_counts: Counter[str],
    pair_counts: Counter[tuple[str, str]],
) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    case_grade_missed = 0
    current_top500_docs = _doc_set_from_pairs(current_top500_pairs)
    selected_pair_ids = {id(pair) for pair in current_top500_pairs}
    for doc in missed_docs:
        related = [pair for pair in generated_pairs if doc in _pair_docs(pair)]
        if not related:
            reasons["artifact_cap_boundary"] += 1
            continue
        tiers = {_tier(pair) for pair in related}
        case_grade_pairs = [pair for pair in related if _tier(pair) in {"strong", "moderate"}]
        if case_grade_pairs:
            case_grade_missed += 1
        if tiers == {"weak"}:
            reasons["weak_pair_only"] += 1
            continue
        best_similarity = max(
            (
                max(
                    _float_feature(pair, "reference_similarity", 0.0),
                    _float_feature(pair, "text_similarity", 0.0),
                )
                for pair in related
            ),
            default=0.0,
        )
        same_partner = any(_feature(pair, "same_partner") is True for pair in related)
        if best_similarity < 0.75 or not same_partner:
            reasons["low_similarity_pair"] += 1
            continue
        if doc not in current_top500_docs:
            reasons["artifact_cap_boundary"] += 1
            continue
        if (
            any(id(pair) in selected_pair_ids for pair in related)
            and doc not in current_top100_docs
        ):
            reasons["case_grade_filtered"] += 1
            continue
        if any(pair_counts[_doc_pair_key(pair)] > 5 for pair in related):
            reasons["document_pair_cap_suppressed"] += 1
            continue
        if doc_counts[doc] > 20:
            reasons["repeated_document_suppressed"] += 1
            continue
        if any(_period_end_bucket(pair).startswith("near_period_end") for pair in related):
            reasons["period_end_noise_competition"] += 1
            continue
        if related and max(_score(pair) for pair in related) >= 0.99:
            reasons["score_tie_lost"] += 1
            continue
        reasons["no_audit_observable_difference"] += 1
    return {
        "reason_distribution": dict(sorted(reasons.items())),
        "case_grade_missed_doc_count": int(case_grade_missed),
        "missed_doc_count": len(missed_docs),
    }


def _select_current_with_tiebreak(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    """Diagnostic near-tie tiebreak using only duplicate evidence features."""
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -round(_score(item[1]), 6),
            -{"strong": 3, "moderate": 2, "weak": 1}.get(_tier(item[1]), 0),
            -int(_feature(item[1], "same_partner") is True),
            -_float_feature(item[1], "reference_similarity", 0.0),
            -_float_feature(item[1], "text_similarity", 0.0),
            _float_feature(item[1], "date_distance_days", 999999.0),
            item[0],
        ),
    )
    return [pair for _idx, pair in ordered[:top_n]]


def _candidate_metrics(
    *,
    name: str,
    pairs: list[dict[str, Any]],
    df: pd.DataFrame,
    batch_id: str,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    rank_by_doc: dict[str, int],
    current_captured_docs: set[str],
    missed_docs: set[str],
) -> dict[str, Any]:
    cases = _case_result_for_pairs(pairs=pairs, df=df, batch_id=batch_id)
    ordered = _default_order_cases(cases)
    measurement = _measure_ordered_cases(
        ordered=ordered,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    top100_docs = _case_docs_for_top_n(ordered, 100)
    top500_docs = _case_docs_for_top_n(ordered, 500)
    all_docs = set().union(*(_case_docs(case) for case in ordered)) if ordered else set()
    tiers = Counter(_tier(pair) for pair in pairs)
    return {
        "candidate": name,
        "expected_duplicate_case_count": len(ordered),
        "top100_truth_docs": len(top100_docs & truth_docs),
        "top500_truth_docs": len(top500_docs & truth_docs),
        "top100_phase1_top100_outside_truth_docs": len(
            {
                doc
                for doc in top100_docs & truth_docs
                if _phase1_bucket(rank_by_doc.get(doc)) != "phase1_top100"
            }
        ),
        "top500_phase1_top100_outside_truth_docs": len(
            {
                doc
                for doc in top500_docs & truth_docs
                if _phase1_bucket(rank_by_doc.get(doc)) != "phase1_top100"
            }
        ),
        "top100_phase1_top500_outside_truth_docs": len(
            {
                doc
                for doc in top100_docs & truth_docs
                if _phase1_bucket(rank_by_doc.get(doc))
                in {"phase1_501_1000", "phase1_1001_plus", "phase1_not_in_cases"}
            }
        ),
        "top500_phase1_top500_outside_truth_docs": len(
            {
                doc
                for doc in top500_docs & truth_docs
                if _phase1_bucket(rank_by_doc.get(doc))
                in {"phase1_501_1000", "phase1_1001_plus", "phase1_not_in_cases"}
            }
        ),
        "current_captured_19_maintained_count": len(current_captured_docs & top100_docs),
        "current_captured_19_maintained": current_captured_docs <= top100_docs,
        "missed_potential_recovery_count": len(missed_docs & top100_docs),
        "weak_pair_ratio": round(tiers.get("weak", 0) / len(pairs), 6) if pairs else 0.0,
        "case_grade_pair_ratio": round(
            (tiers.get("strong", 0) + tiers.get("moderate", 0)) / len(pairs), 6
        )
        if pairs
        else 0.0,
        "nontruth_review_burden": {
            "docs_covered": len(all_docs),
            "nontruth_docs_covered": len(all_docs - truth_docs),
        },
        "case_measurement": measurement,
        "policy_constraints": _policy_constraints(),
    }


def _run_batch(spec: BatchSpec) -> dict[str, Any]:
    started = time.perf_counter()
    df = _load_case_input(spec.case_input)
    truth = _load_truth(spec.truth_csv)
    truth_docs = set(truth["document_id"])
    scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    phase1_result, priority_by_doc = _load_phase1_case_priority(spec.phase1_result)
    rank_by_doc = _phase1_doc_rank_map(phase1_result)

    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    generated_artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    generated_pairs = list(generated_artifact.get("top_pairs", []))
    current_pairs = _select_score_order(generated_pairs, 500)
    sidecar_pairs = _select_pair_diversity_score(generated_pairs, 500)
    tiebreak_pairs = _select_current_with_tiebreak(generated_pairs, 500)
    doc_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for pair in generated_pairs:
        pair_counts[_doc_pair_key(pair)] += 1
        for doc in _pair_docs(pair):
            doc_counts[doc] += 1

    current_cases = _case_result_for_pairs(
        pairs=current_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_current_500",
    )
    current_order = _default_order_cases(current_cases)
    current_top100_docs = _case_docs_for_top_n(current_order, 100)
    current_top500_docs = _case_docs_for_top_n(current_order, 500)

    phase1_top100_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 100}
    phase1_top500_docs = {doc for doc, rank in rank_by_doc.items() if rank <= 500}
    generated_docs = _doc_set_from_pairs(generated_pairs)
    generated_potential_docs = (generated_docs & truth_docs) - phase1_top100_docs
    current_captured_docs = (current_top100_docs & truth_docs) - phase1_top100_docs
    missed_docs = generated_potential_docs - current_captured_docs

    generated_potential_top500_docs = (generated_docs & truth_docs) - phase1_top500_docs
    current_captured_top500_outside_docs = (current_top100_docs & truth_docs) - phase1_top500_docs
    missed_top500_outside_docs = (
        generated_potential_top500_docs - current_captured_top500_outside_docs
    )

    group_profiles = {
        "generated_potential": _profile_group(
            name="generated_potential",
            docs=generated_potential_docs,
            pairs=generated_pairs,
            rank_by_doc=rank_by_doc,
            priority_by_doc=priority_by_doc,
            doc_counts=doc_counts,
            pair_counts=pair_counts,
        ),
        "current_captured": _profile_group(
            name="current_captured",
            docs=current_captured_docs,
            pairs=generated_pairs,
            rank_by_doc=rank_by_doc,
            priority_by_doc=priority_by_doc,
            doc_counts=doc_counts,
            pair_counts=pair_counts,
        ),
        "current_missed": _profile_group(
            name="current_missed",
            docs=missed_docs,
            pairs=generated_pairs,
            rank_by_doc=rank_by_doc,
            priority_by_doc=priority_by_doc,
            doc_counts=doc_counts,
            pair_counts=pair_counts,
        ),
    }
    missed_classification = _classify_missed_docs(
        missed_docs=missed_docs,
        generated_pairs=generated_pairs,
        current_top500_pairs=current_pairs,
        current_top100_docs=current_top100_docs,
        doc_counts=doc_counts,
        pair_counts=pair_counts,
    )
    sidecar_candidate = _candidate_metrics(
        name="current_plus_case_grade_sidecar",
        pairs=sidecar_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_sidecar_case_grade_500",
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
        rank_by_doc=rank_by_doc,
        current_captured_docs=current_captured_docs,
        missed_docs=missed_docs,
    )
    sidecar_candidate["first_review_ordering_changed"] = False
    sidecar_candidate["first_review_metrics_source"] = "current_document_diversity_top100"
    sidecar_candidate["sidecar_only_candidate"] = True
    sidecar_candidate["sidecar_top500_truth_docs"] = sidecar_candidate["top500_truth_docs"]
    sidecar_candidate["sidecar_top500_phase1_top100_outside_truth_docs"] = (
        sidecar_candidate["top500_phase1_top100_outside_truth_docs"]
    )
    sidecar_candidate["sidecar_nontruth_review_burden"] = sidecar_candidate[
        "nontruth_review_burden"
    ]
    sidecar_candidate["top100_truth_docs"] = len(current_top100_docs & truth_docs)
    sidecar_candidate["top500_truth_docs"] = len(current_top500_docs & truth_docs)
    sidecar_candidate["top100_phase1_top100_outside_truth_docs"] = len(
        current_captured_docs
    )
    sidecar_candidate["top500_phase1_top100_outside_truth_docs"] = len(
        (current_top500_docs & truth_docs) - phase1_top100_docs
    )
    sidecar_candidate["top100_phase1_top500_outside_truth_docs"] = len(
        (current_top100_docs & truth_docs) - phase1_top500_docs
    )
    sidecar_candidate["top500_phase1_top500_outside_truth_docs"] = len(
        (current_top500_docs & truth_docs) - phase1_top500_docs
    )
    sidecar_candidate["current_captured_19_maintained_count"] = len(current_captured_docs)
    sidecar_candidate["current_captured_19_maintained"] = True
    sidecar_candidate["missed_potential_recovery_count"] = 0

    tiebreak_candidate = _candidate_metrics(
        name="current_with_missed_potential_tiebreak",
        pairs=tiebreak_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_audit_tiebreak_500",
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
        rank_by_doc=rank_by_doc,
        current_captured_docs=current_captured_docs,
        missed_docs=missed_docs,
    )
    tiebreak_candidate["first_review_ordering_changed"] = True
    tiebreak_candidate["failed_if_current_capture_worsens"] = not tiebreak_candidate[
        "current_captured_19_maintained"
    ]

    missed_explainable = (
        missed_classification["case_grade_missed_doc_count"] > 0
        and missed_classification["reason_distribution"].get("no_audit_observable_difference", 0)
        < missed_classification["missed_doc_count"]
    )
    recommended_action = (
        "keep_current_first_review_and_use_case_grade_sidecar"
        if not tiebreak_candidate["current_captured_19_maintained"]
        else "diagnostic_only_compare_tiebreak_crossbatch"
    )
    return {
        "dataset": spec.dataset,
        "duplicate_first_review_headroom": {
            "generated_potential_truth_docs": len(generated_potential_docs),
            "current_captured_truth_docs": len(current_captured_docs),
            "current_missed_truth_docs": len(missed_docs),
            "generated_potential_truth_docs_outside_phase1_top500": len(
                generated_potential_top500_docs
            ),
            "current_captured_truth_docs_outside_phase1_top500": len(
                current_captured_top500_outside_docs
            ),
            "current_missed_truth_docs_outside_phase1_top500": len(
                missed_top500_outside_docs
            ),
            "current_top100_truth_docs": len(current_top100_docs & truth_docs),
            "current_top500_truth_docs": len(current_top500_docs & truth_docs),
        },
        "potential_captured_missed_profiles": group_profiles,
        "missed_potential_classification": missed_classification,
        "candidate_results": {
            "current_plus_case_grade_sidecar": sidecar_candidate,
            "current_with_missed_potential_tiebreak": tiebreak_candidate,
        },
        "decision_payload": {
            "duplicate_first_review_headroom": len(missed_docs),
            "generated_potential_truth_docs": len(generated_potential_docs),
            "current_captured_truth_docs": len(current_captured_docs),
            "current_missed_truth_docs": len(missed_docs),
            "missed_potential_explainable": bool(missed_explainable),
            "recommended_action": recommended_action,
            "production_first_review_ranking_change": False,
            "sidecar_or_export_surface_candidate": "current_plus_case_grade_sidecar",
            "fitting_risk": bool(
                spec.name == "fixed5_normalcal5"
                and not tiebreak_candidate["current_captured_19_maintained"]
            ),
            "adoption_blocker": (
                "first_review_tiebreak_loses_current_phase1_top100_complement"
                if not tiebreak_candidate["current_captured_19_maintained"]
                else "requires_cross_batch_validation_before_any_ranking_change"
            ),
        },
        "policy_constraints": _policy_constraints(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    started = time.perf_counter()
    batches = {spec.name: _run_batch(spec) for spec in BATCHES}
    all_truth_docs: set[str] = set()
    for spec in BATCHES:
        truth = _load_truth(spec.truth_csv)
        all_truth_docs.update(truth["document_id"].astype(str))
    fixed5 = batches["fixed5_normalcal5"]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "measurement_scope": (
            "Duplicate Phase 5 remaining generated potential diagnostic; aggregate only; "
            "raw identifiers omitted"
        ),
        "primary_batch": "fixed5_normalcal5",
        "batches": batches,
        "decision_payload": fixed5["decision_payload"],
        "policy_constraints": _policy_constraints(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=all_truth_docs,
    )
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT_JSON),
                "elapsed_seconds": payload["elapsed_seconds"],
                "fixed5_headroom": fixed5["duplicate_first_review_headroom"],
                "fixed5_decision": fixed5["decision_payload"],
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
