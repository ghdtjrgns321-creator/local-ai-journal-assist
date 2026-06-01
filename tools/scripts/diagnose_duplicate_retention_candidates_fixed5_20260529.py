"""Diagnostic-only duplicate retention candidate comparison for fixed5.

This script compares audit-observable metadata retention strategies after
duplicate pair generation. It does not change detector scores, thresholds,
PHASE1 priority/ranking, or PHASE2 family fusion.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.detection.duplicate_detector as duplicate_detector_module
from config.settings import get_settings
from src.detection.base import DetectionResult
from src.detection.duplicate_detector import DuplicateDetector
from src.detection.duplicate_pair_features import build_duplicate_pair_artifact
from src.services.phase2_duplicate_case_builder import build_duplicate_cases
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    _dist,
    _doc_set_from_pairs,
    _pair_docs,
    _quantiles,
    _tier,
    raw_identifier_leak_check,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

DATASET_NAME = "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
CASE_INPUT_PKL = ROOT / "artifacts" / "phase1_manipulation_v7_fixed5_normalcal5_case_input.pkl"
TRUTH_CSV = (
    ROOT / "data" / "journal" / "primary" / DATASET_NAME / "labels" / "manipulated_entry_truth.csv"
)
OUT_JSON = ROOT / "artifacts" / "duplicate_retention_candidates_fixed5_20260529.json"
TOP_NS = (100, 500, 1000, 10000)
_PAIR_DIVERSITY_CACHE: dict[tuple[int, int], list[dict[str, Any]]] = {}


def _load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    with CASE_INPUT_PKL.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    df["document_id"] = df["document_id"].astype(str)
    truth = pd.read_csv(TRUTH_CSV)
    truth["document_id"] = truth["document_id"].astype(str)
    truth["manipulation_scenario"] = truth["manipulation_scenario"].astype(str)
    return df, truth


def _doc_pair_key(pair: dict[str, Any]) -> tuple[str, str]:
    docs = sorted(_pair_docs(pair))
    if not docs:
        return ("", "")
    if len(docs) == 1:
        return (docs[0], docs[0])
    return (docs[0], docs[-1])


def _tier_weight(pair: dict[str, Any]) -> int:
    return {"strong": 3, "moderate": 2, "weak": 1}.get(_tier(pair), 0)


def _evidence_score(pair: dict[str, Any]) -> float:
    features = pair.get("features", {})
    ref = features.get("reference_similarity") or 0.0
    text = features.get("text_similarity") or 0.0
    partner = 1.0 if features.get("same_partner") is True else 0.0
    try:
        return float(0.4 * float(ref) + 0.3 * float(text) + 0.3 * partner)
    except (TypeError, ValueError):
        return 0.0


def _same_partner_rate(pairs: list[dict[str, Any]]) -> float:
    if not pairs:
        return 0.0
    count = sum(
        1
        for pair in pairs
        if isinstance(pair.get("features"), dict)
        and pair["features"].get("same_partner") is True
    )
    return count / len(pairs)


def _component_snapshot(
    pair: dict[str, Any],
    *,
    doc_counts: Counter[str],
    pair_counts: Counter[tuple[str, str]],
    diversity_weight: float = 0.01,
    novelty_weight: float = 0.03,
    weak_penalty_weight: float = 0.10,
) -> dict[str, float]:
    docs = _pair_docs(pair)
    pair_key = _doc_pair_key(pair)
    pair_score = float(pair.get("pair_score") or 0.0)
    evidence = _evidence_score(pair)
    novelty = float(sum(1 for doc in docs if doc_counts[doc] == 0))
    repeat_penalty = float(sum(doc_counts[doc] for doc in docs) + pair_counts[pair_key] * 2)
    weak_penalty = 1.0 if _tier_weight(pair) <= 1 else 0.0
    selector_score = (
        pair_score
        + 0.05 * evidence
        + novelty_weight * novelty
        - diversity_weight * repeat_penalty
        - weak_penalty_weight * weak_penalty
    )
    return {
        "pair_score": pair_score,
        "evidence_score": evidence,
        "tier_weight": float(_tier_weight(pair)),
        "novelty_contribution": novelty_weight * novelty,
        "repeated_document_penalty_contribution": diversity_weight * repeat_penalty,
        "weak_penalty_contribution": weak_penalty_weight * weak_penalty,
        "candidate_selector_score": selector_score,
    }


def _selector_component_profile(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    doc_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    components: dict[str, list[float]] = {
        "pair_score": [],
        "evidence_score": [],
        "tier_weight": [],
        "novelty_contribution": [],
        "repeated_document_penalty_contribution": [],
        "weak_penalty_contribution": [],
        "candidate_selector_score": [],
    }
    for pair in pairs:
        snapshot = _component_snapshot(pair, doc_counts=doc_counts, pair_counts=pair_counts)
        for key, value in snapshot.items():
            components[key].append(value)
        for doc in _pair_docs(pair):
            doc_counts[doc] += 1
        pair_counts[_doc_pair_key(pair)] += 1
    return {key: _quantiles(values) for key, values in components.items()}


def _select_score_order(pairs: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return pairs[:top_n]


def _select_document_first(pairs: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    seen_docs: set[str] = set()
    for require_new_count in (2, 1):
        for pair in pairs:
            if len(selected) >= top_n:
                return selected
            if id(pair) in selected_ids:
                continue
            docs = _pair_docs(pair)
            if len(docs - seen_docs) >= require_new_count:
                selected.append(pair)
                selected_ids.add(id(pair))
                seen_docs.update(docs)
    for pair in pairs:
        if len(selected) >= top_n:
            break
        if id(pair) not in selected_ids:
            selected.append(pair)
            selected_ids.add(id(pair))
    return selected


def _select_case_grade_first(pairs: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -_tier_weight(item[1]),
            -float(item[1].get("pair_score") or 0.0),
            item[0],
        ),
    )
    return [pair for _idx, pair in ordered[:top_n]]


def _select_pair_diversity_score(pairs: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    """Phase 4 evidence-diversity candidate selector.

    Uses only audit-observable pair evidence: pair score, evidence tier,
    partner/reference/text support, and repeated document/document-pair
    concentration. Truth labels and scenario values are not inputs.
    """
    cache_key = (id(pairs), top_n)
    if cache_key in _PAIR_DIVERSITY_CACHE:
        return list(_PAIR_DIVERSITY_CACHE[cache_key])

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    pool_size = min(len(pairs), 25_000 if top_n <= 500 else 10_000)
    remaining = list(enumerate(pairs[:pool_size]))
    greedy_limit = min(top_n, 1_000)
    while remaining and len(selected) < greedy_limit:
        best_pos = 0
        best_key: tuple[float, float, int] | None = None
        for pos, (idx, pair) in enumerate(remaining):
            docs = _pair_docs(pair)
            pair_key = _doc_pair_key(pair)
            novelty = sum(1 for doc in docs if doc_counts[doc] == 0)
            repeat_penalty = sum(doc_counts[doc] for doc in docs) + pair_counts[pair_key] * 2
            score = (
                float(pair.get("pair_score") or 0.0)
                + 0.05 * _evidence_score(pair)
                + 0.03 * novelty
                - 0.01 * repeat_penalty
                - (0.10 if _tier_weight(pair) <= 1 else 0.0)
            )
            key = (score, -float(idx), -float(pos))
            if best_key is None or key > best_key:
                best_key = key
                best_pos = pos
        _idx, pair = remaining.pop(best_pos)
        if id(pair) in selected_ids:
            continue
        selected.append(pair)
        selected_ids.add(id(pair))
        for doc in _pair_docs(pair):
            doc_counts[doc] += 1
        pair_counts[_doc_pair_key(pair)] += 1

    if len(selected) < top_n:
        ordered_fill = sorted(
            (item for item in enumerate(pairs) if id(item[1]) not in selected_ids),
            key=lambda item: (
                -(
                    float(item[1].get("pair_score") or 0.0)
                    + 0.05 * _evidence_score(item[1])
                    - (0.10 if _tier_weight(item[1]) <= 1 else 0.0)
                ),
                item[0],
            ),
        )
        for _idx, pair in ordered_fill:
            if len(selected) >= top_n:
                break
            selected.append(pair)
            selected_ids.add(id(pair))
    _PAIR_DIVERSITY_CACHE[cache_key] = list(selected)
    return selected


def _select_tier_then_score_then_diversity(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -_tier_weight(item[1]),
            -float(item[1].get("pair_score") or 0.0),
            -_evidence_score(item[1]),
            item[0],
        ),
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_pair_counts: Counter[tuple[str, str]] = Counter()
    for max_pair_repeat in (1, 3, None):
        for _idx, pair in ordered:
            if len(selected) >= top_n:
                return selected
            if id(pair) in selected_ids:
                continue
            pair_key = _doc_pair_key(pair)
            if max_pair_repeat is not None and doc_pair_counts[pair_key] >= max_pair_repeat:
                continue
            selected.append(pair)
            selected_ids.add(id(pair))
            doc_pair_counts[pair_key] += 1
    return selected


def _select_two_stage_top100_score_top500_diversity(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    if top_n <= 100:
        return _select_score_order(pairs, top_n)
    head = _select_score_order(pairs, 100)
    head_ids = {id(pair) for pair in head}
    tail_pool = [pair for pair in pairs if id(pair) not in head_ids]
    return head + _select_pair_diversity_score(tail_pool, top_n - len(head))


def _select_hybrid_score_diversity_balanced(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    doc_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    pool = sorted(
        enumerate(pairs),
        key=lambda item: (
            -(float(item[1].get("pair_score") or 0.0) + 0.05 * _evidence_score(item[1])),
            item[0],
        ),
    )[: min(len(pairs), 25_000)]
    while pool and len(selected) < top_n:
        best_pos = 0
        best_key: tuple[float, float, float] | None = None
        for pos, (idx, pair) in enumerate(pool):
            components = _component_snapshot(
                pair,
                doc_counts=doc_counts,
                pair_counts=pair_counts,
                diversity_weight=0.004,
                novelty_weight=0.015,
                weak_penalty_weight=0.05,
            )
            key = (components["candidate_selector_score"], -float(idx), -float(pos))
            if best_key is None or key > best_key:
                best_key = key
                best_pos = pos
        _idx, pair = pool.pop(best_pos)
        if id(pair) in selected_ids:
            continue
        selected.append(pair)
        selected_ids.add(id(pair))
        for doc in _pair_docs(pair):
            doc_counts[doc] += 1
        pair_counts[_doc_pair_key(pair)] += 1
    if len(selected) < top_n:
        for pair in pairs:
            if len(selected) >= top_n:
                break
            if id(pair) not in selected_ids:
                selected.append(pair)
                selected_ids.add(id(pair))
    return selected


def _case_grade_floor_key(pair: dict[str, Any]) -> tuple[int, float]:
    features = pair.get("features", {})
    ref = float(features.get("reference_similarity") or 0.0) if isinstance(features, dict) else 0.0
    text = float(features.get("text_similarity") or 0.0) if isinstance(features, dict) else 0.0
    score = float(pair.get("pair_score") or 0.0)
    floor_pass = score >= 0.95 or ref >= 0.90 or text >= 0.90
    return (1 if floor_pass else 0, max(score, ref, text))


def _select_case_grade_with_score_floor(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -int(_tier_weight(item[1]) >= 2),
            -_case_grade_floor_key(item[1])[0],
            -_case_grade_floor_key(item[1])[1],
            -_tier_weight(item[1]),
            -float(item[1].get("pair_score") or 0.0),
            item[0],
        ),
    )
    return [pair for _idx, pair in ordered[:top_n]]


def _select_document_pair_cap_with_fill(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for pair in pairs:
        if len(selected) >= top_n:
            return selected
        pair_key = _doc_pair_key(pair)
        if pair_counts[pair_key] >= 1:
            continue
        selected.append(pair)
        selected_ids.add(id(pair))
        pair_counts[pair_key] += 1
    for pair in pairs:
        if len(selected) >= top_n:
            break
        if id(pair) not in selected_ids:
            selected.append(pair)
            selected_ids.add(id(pair))
    return selected


def _select_rule_balanced_duplicate_surface(
    pairs: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        buckets.setdefault(str(pair.get("rule_id") or "unknown"), []).append(pair)
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    while len(selected) < top_n and buckets:
        progressed = False
        for rule_id in sorted(buckets):
            bucket = buckets[rule_id]
            while bucket and id(bucket[0]) in selected_ids:
                bucket.pop(0)
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            selected_ids.add(id(selected[-1]))
            progressed = True
            if len(selected) >= top_n:
                break
        if not progressed:
            break
    if len(selected) < top_n:
        for pair in pairs:
            if len(selected) >= top_n:
                break
            if id(pair) not in selected_ids:
                selected.append(pair)
                selected_ids.add(id(pair))
    return selected


def _case_result_for_pairs(
    *,
    pairs: list[dict[str, Any]],
    df: pd.DataFrame,
    batch_id: str,
) -> tuple[Any, ...]:
    result = DetectionResult(
        track_name="duplicate",
        flagged_indices=[],
        scores=pd.Series(0.0, index=df.index),
        rule_flags=[],
        details=pd.DataFrame(index=df.index),
        metadata={"pair_artifact": {"schema_version": 1, "top_pairs": pairs}},
    )
    return build_duplicate_cases(batch_id=batch_id, detection_result=result, df=df)


def _case_docs(case: Any) -> set[str]:
    return {
        str(ref.document_id)
        for ref in getattr(case, "row_refs", ())
        if getattr(ref, "document_id", None) not in (None, "")
    }


def _case_key(case: Any) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(getattr(ref, "index_label", ""))
            for ref in getattr(case, "row_refs", ())
            if getattr(ref, "index_label", None) not in (None, "")
        )
    )


def _default_order_cases(cases: tuple[Any, ...] | list[Any]) -> list[Any]:
    return sorted(
        cases,
        key=lambda case: (
            -{"strong": 3, "moderate": 2, "weak": 1}.get(str(case.evidence_tier), 0),
            -float(case.family_score or 0.0),
            case.phase2_case_id,
        ),
    )


def _measure_ordered_cases(
    *,
    ordered: list[Any],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    case_doc_sets = [_case_docs(case) for case in ordered]
    first_truth_case_rank = None
    for rank, doc_set in enumerate(case_doc_sets, start=1):
        if doc_set & truth_docs:
            first_truth_case_rank = rank
            break
    out: dict[str, Any] = {"topn": {}, "first_truth_case_rank": first_truth_case_rank}
    for top_n in TOP_NS:
        docs: set[str] = set()
        for doc_set in case_doc_sets[:top_n]:
            docs.update(doc_set)
        matched = docs & truth_docs
        out["topn"][str(top_n)] = {
            "truth_doc_count": len(matched),
            "scenario_counts": _dist(
                scenario_by_doc[doc] for doc in matched if doc in scenario_by_doc
            ),
        }
    all_docs = set().union(*case_doc_sets) if case_doc_sets else set()
    out["docs_covered"] = len(all_docs)
    out["truth_doc_count"] = len(all_docs & truth_docs)
    return out


def _measure_cases(
    *,
    cases: tuple[Any, ...],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    return _measure_ordered_cases(
        ordered=_default_order_cases(cases),
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )


def _case_doc_concentration(cases: list[Any]) -> dict[str, Any]:
    doc_counts: Counter[str] = Counter()
    for case in cases:
        for doc in _case_docs(case):
            doc_counts[doc] += 1
    return {
        "case_count": len(cases),
        "doc_count": len(doc_counts),
        "max_cases_per_document": max(doc_counts.values()) if doc_counts else 0,
        "top_document_case_share": max(doc_counts.values()) / len(cases)
        if cases and doc_counts
        else 0.0,
    }


def _order_current_top100_case_anchor_plus_diversity_fill(
    *,
    current_cases: tuple[Any, ...],
    candidate_cases: tuple[Any, ...],
) -> list[Any]:
    ordered_current = _default_order_cases(current_cases)
    ordered_candidate = _default_order_cases(candidate_cases)
    selected = list(ordered_current[:100])
    selected_keys = {_case_key(case) for case in selected}
    for case in ordered_candidate:
        if _case_key(case) in selected_keys:
            continue
        selected.append(case)
        selected_keys.add(_case_key(case))
    for case in ordered_current[100:]:
        if _case_key(case) not in selected_keys:
            selected.append(case)
            selected_keys.add(_case_key(case))
    return selected


def _order_case_score_tiebreak_with_pair_diversity(cases: tuple[Any, ...]) -> list[Any]:
    pool = _default_order_cases(cases)
    selected: list[Any] = []
    selected_keys: set[tuple[str, ...]] = set()
    doc_counts: Counter[str] = Counter()
    while pool:
        best_pos = 0
        best_key: tuple[float, float, float] | None = None
        for pos, case in enumerate(pool):
            docs = _case_docs(case)
            novelty = sum(1 for doc in docs if doc_counts[doc] == 0)
            repeat_penalty = sum(doc_counts[doc] for doc in docs)
            tier_weight = {"strong": 3, "moderate": 2, "weak": 1}.get(str(case.evidence_tier), 0)
            score = (
                tier_weight
                + float(case.family_score or 0.0)
                + 0.03 * novelty
                - 0.01 * repeat_penalty
            )
            key = (score, -float(pos), -float(len(selected)))
            if best_key is None or key > best_key:
                best_key = key
                best_pos = pos
        case = pool.pop(best_pos)
        if _case_key(case) in selected_keys:
            continue
        selected.append(case)
        selected_keys.add(_case_key(case))
        for doc in _case_docs(case):
            doc_counts[doc] += 1
    return selected


def _order_case_grade_density_cap(cases: tuple[Any, ...]) -> list[Any]:
    ordered = _default_order_cases(cases)
    selected: list[Any] = []
    selected_keys: set[tuple[str, ...]] = set()
    doc_counts: Counter[str] = Counter()
    for max_doc_cases in (1, 2, 5, None):
        for case in ordered:
            if _case_key(case) in selected_keys:
                continue
            docs = _case_docs(case)
            if max_doc_cases is not None and any(
                doc_counts[doc] >= max_doc_cases for doc in docs
            ):
                continue
            selected.append(case)
            selected_keys.add(_case_key(case))
            for doc in docs:
                doc_counts[doc] += 1
    return selected


def evaluate_case_order_candidate(
    *,
    name: str,
    ordered_cases: list[Any],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    baseline_case_count: int,
    baseline_nontruth_docs: int,
) -> dict[str, Any]:
    measurement = _measure_ordered_cases(
        ordered=ordered_cases,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    docs = set().union(*(_case_docs(case) for case in ordered_cases)) if ordered_cases else set()
    truth_doc_count = len(docs & truth_docs)
    nontruth_docs = len(docs) - truth_doc_count
    return {
        "case_order_candidate": name,
        "duplicate_case_count_expected": len(ordered_cases),
        "case_measurement": measurement,
        "docs_covered": len(docs),
        "truth_doc_count": truth_doc_count,
        "nontruth_docs_covered": nontruth_docs,
        "case_concentration": _case_doc_concentration(ordered_cases),
        "review_burden_vs_current_top500": {
            "case_count_delta": int(len(ordered_cases) - baseline_case_count),
            "case_count_ratio": len(ordered_cases) / baseline_case_count
            if baseline_case_count
            else None,
            "nontruth_docs_delta": int(nontruth_docs - baseline_nontruth_docs),
        },
        "candidate_weight_provenance": {
            "weight_source": "fixed exploratory diagnostic weights",
            "calibrated_on_fixed5_truth": False,
            "production_ranking_policy": False,
            "requires_cross_batch_fixture_validation_before_adoption": True,
        },
        "candidate_policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "selector_strategy_flag_only": True,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }


def _concentration(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    doc_counts: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for pair in pairs:
        for doc in _pair_docs(pair):
            doc_counts[doc] += 1
        pair_counts[_doc_pair_key(pair)] += 1
    return {
        "doc_count": len(doc_counts),
        "document_pair_count": len(pair_counts),
        "max_pairs_per_document": max(doc_counts.values()) if doc_counts else 0,
        "max_pairs_per_document_pair": max(pair_counts.values()) if pair_counts else 0,
        "top_document_share": (
            max(doc_counts.values()) / (2 * len(pairs)) if pairs and doc_counts else 0.0
        ),
        "top_document_pair_share": (
            max(pair_counts.values()) / len(pairs) if pairs and pair_counts else 0.0
        ),
    }


def _feature_quantile_profile(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    def values_for(name: str) -> list[float]:
        values: list[float] = []
        for pair in pairs:
            features = pair.get("features", {})
            if not isinstance(features, dict):
                continue
            value = features.get(name)
            if value is None or isinstance(value, bool):
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        return values

    return {
        "pair_score": _quantiles([float(pair.get("pair_score") or 0.0) for pair in pairs]),
        "amount_similarity": _quantiles(values_for("amount_similarity")),
        "reference_similarity": _quantiles(values_for("reference_similarity")),
        "text_similarity": _quantiles(values_for("text_similarity")),
        "date_distance_days": _quantiles(values_for("date_distance_days")),
        "same_partner_ratio": _same_partner_rate(pairs),
    }


def evaluate_candidate(
    *,
    name: str,
    pairs: list[dict[str, Any]],
    df: pd.DataFrame,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    selector: Callable[[list[dict[str, Any]], int], list[dict[str, Any]]],
    top_n: int = 500,
) -> dict[str, Any]:
    selected = selector(pairs, top_n)
    cases = _case_result_for_pairs(
        pairs=selected,
        df=df,
        batch_id=f"fixed5_duplicate_retention_candidate_{name}",
    )
    pair_docs = _doc_set_from_pairs(selected)
    truth_doc_count = len(pair_docs & truth_docs)
    truth_ranks = [
        rank for rank, pair in enumerate(selected, start=1) if _pair_docs(pair) & truth_docs
    ]
    weak_count = sum(1 for pair in selected if _tier(pair) == "weak")
    case_grade_count = sum(1 for pair in selected if _tier(pair) in {"strong", "moderate"})
    nontruth_pair_doc_count = sum(len(_pair_docs(pair) - truth_docs) for pair in selected)
    pair_topn: dict[str, Any] = {}
    for top_n_key in TOP_NS:
        subset = selected[:top_n_key]
        subset_docs = _doc_set_from_pairs(subset)
        pair_topn[str(top_n_key)] = {
            "truth_doc_count": len(subset_docs & truth_docs),
            "docs_covered": len(subset_docs),
            "nontruth_docs_covered": len(subset_docs - truth_docs),
        }
    return {
        "top_pairs_count": len(selected),
        "duplicate_case_count_expected": len(cases),
        "docs_covered": len(pair_docs),
        "truth_doc_count": truth_doc_count,
        "nontruth_docs_covered": len(pair_docs) - truth_doc_count,
        "nontruth_pair_doc_count": int(nontruth_pair_doc_count),
        "case_measurement": _measure_cases(
            cases=cases,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
        ),
        "pair_topn": pair_topn,
        "scenario_matrix": _dist(
            scenario_by_doc[doc] for doc in (pair_docs & truth_docs) if doc in scenario_by_doc
        ),
        "evidence_tier_distribution": _dist(_tier(pair) for pair in selected),
        "rule_id_distribution": _dist(pair.get("rule_id") for pair in selected),
        "weak_pair_ratio": weak_count / len(selected) if selected else 0.0,
        "strong_moderate_pair_ratio": case_grade_count / len(selected) if selected else 0.0,
        "first_truth_pair_rank": min(truth_ranks) if truth_ranks else None,
        "truth_pair_rank_quantiles": _quantiles(truth_ranks),
        "nontruth_dense_repeat_concentration": _concentration(
            [pair for pair in selected if not (_pair_docs(pair) & truth_docs)]
        ),
        "all_pair_concentration": _concentration(selected),
        "pair_feature_quantiles": _feature_quantile_profile(selected),
        "selector_score_component_quantiles": _selector_component_profile(selected),
        "candidate_weight_provenance": {
            "weight_source": "fixed exploratory diagnostic weights",
            "calibrated_on_fixed5_truth": False,
            "production_ranking_policy": False,
            "requires_cross_batch_fixture_validation_before_adoption": True,
        },
        "candidate_policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "selector_strategy_flag_only": True,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }


def main() -> int:
    started = time.perf_counter()
    df, truth = _load_inputs()
    truth_docs = set(truth["document_id"])
    scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )
    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    result = DuplicateDetector(settings).detect(df)
    generated = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    pairs = list(generated.get("top_pairs", []))

    candidates: dict[str, Any] = {}
    for top_n in (500, 2_000, 10_000, 50_000):
        candidates[f"current_document_diversity_top_{top_n}"] = evaluate_candidate(
            name=f"current_{top_n}",
            pairs=pairs,
            df=df,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            selector=_select_score_order,
            top_n=top_n,
        )
    for name, selector in (
        ("document_first_top_500", _select_document_first),
        ("case_grade_first_top_500", _select_case_grade_first),
        ("pair_diversity_score_top_500", _select_pair_diversity_score),
    ):
        candidates[name] = evaluate_candidate(
            name=name,
            pairs=pairs,
            df=df,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            selector=selector,
            top_n=500,
        )
    for top_n in (500, 1_000, 2_000, 5_000):
        candidates[f"evidence_diversity_top_{top_n}"] = evaluate_candidate(
            name=f"evidence_diversity_top_{top_n}",
            pairs=pairs,
            df=df,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            selector=_select_pair_diversity_score,
            top_n=top_n,
        )
    for name, selector in (
        ("tier_then_score_then_diversity_top_500", _select_tier_then_score_then_diversity),
        (
            "two_stage_top100_score_top500_diversity",
            _select_two_stage_top100_score_top500_diversity,
        ),
        ("hybrid_score_diversity_balanced_top_500", _select_hybrid_score_diversity_balanced),
        ("case_grade_with_score_floor_top_500", _select_case_grade_with_score_floor),
        ("document_pair_cap_with_fill_top_500", _select_document_pair_cap_with_fill),
        ("rule_balanced_duplicate_surface_top_500", _select_rule_balanced_duplicate_surface),
    ):
        candidates[name] = evaluate_candidate(
            name=name,
            pairs=pairs,
            df=df,
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            selector=selector,
            top_n=500,
        )

    current_case_count = candidates["current_document_diversity_top_500"][
        "duplicate_case_count_expected"
    ]
    current_nontruth_docs = candidates["current_document_diversity_top_500"][
        "nontruth_docs_covered"
    ]
    current_nontruth_pair_docs = candidates["current_document_diversity_top_500"][
        "nontruth_pair_doc_count"
    ]
    for result_row in candidates.values():
        result_row["review_burden_vs_current_top500"] = {
            "case_count_delta": int(
                result_row["duplicate_case_count_expected"] - current_case_count
            ),
            "case_count_ratio": (
                result_row["duplicate_case_count_expected"] / current_case_count
                if current_case_count
                else None
            ),
            "nontruth_docs_delta": int(result_row["nontruth_docs_covered"] - current_nontruth_docs),
            "nontruth_pair_doc_count_delta": int(
                result_row["nontruth_pair_doc_count"] - current_nontruth_pair_docs
            ),
        }

    current_pairs_500 = _select_score_order(pairs, 500)
    evidence_pairs_500 = _select_pair_diversity_score(pairs, 500)
    current_cases_500 = _case_result_for_pairs(
        pairs=current_pairs_500,
        df=df,
        batch_id="fixed5_duplicate_case_order_current_500",
    )
    evidence_cases_500 = _case_result_for_pairs(
        pairs=evidence_pairs_500,
        df=df,
        batch_id="fixed5_duplicate_case_order_evidence_500",
    )
    ordered_current = _default_order_cases(current_cases_500)
    ordered_evidence = _default_order_cases(evidence_cases_500)
    current_case_measurement = _measure_ordered_cases(
        ordered=ordered_current,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    evidence_case_measurement = _measure_ordered_cases(
        ordered=ordered_evidence,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    case_order_candidate_results = {
        "current_top100_case_anchor_plus_diversity_fill": evaluate_case_order_candidate(
            name="current_top100_case_anchor_plus_diversity_fill",
            ordered_cases=_order_current_top100_case_anchor_plus_diversity_fill(
                current_cases=current_cases_500,
                candidate_cases=evidence_cases_500,
            ),
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            baseline_case_count=current_case_count,
            baseline_nontruth_docs=current_nontruth_docs,
        ),
        "case_score_tiebreak_with_pair_diversity": evaluate_case_order_candidate(
            name="case_score_tiebreak_with_pair_diversity",
            ordered_cases=_order_case_score_tiebreak_with_pair_diversity(evidence_cases_500),
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            baseline_case_count=current_case_count,
            baseline_nontruth_docs=current_nontruth_docs,
        ),
        "case_grade_density_cap": evaluate_case_order_candidate(
            name="case_grade_density_cap",
            ordered_cases=_order_case_grade_density_cap(evidence_cases_500),
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            baseline_case_count=current_case_count,
            baseline_nontruth_docs=current_nontruth_docs,
        ),
        "review_surface_split_ui100_export500": {
            "case_order_candidate": "review_surface_split_ui100_export500",
            "ui_surface_source": "current_document_diversity_top_500_default_case_order",
            "export_surface_source": "evidence_diversity_top_500_default_case_order",
            "ui_top100_truth_doc_count": current_case_measurement["topn"]["100"][
                "truth_doc_count"
            ],
            "export_top500_truth_doc_count": evidence_case_measurement["topn"]["500"][
                "truth_doc_count"
            ],
            "export_total_truth_doc_count": evidence_case_measurement["truth_doc_count"],
            "duplicate_case_count_expected": len(evidence_cases_500),
            "review_burden_vs_current_top500": {
                "case_count_delta": int(len(evidence_cases_500) - current_case_count),
                "case_count_ratio": len(evidence_cases_500) / current_case_count
                if current_case_count
                else None,
                "nontruth_docs_delta": int(
                    candidates["evidence_diversity_top_500"]["nontruth_docs_covered"]
                    - current_nontruth_docs
                ),
            },
            "candidate_weight_provenance": {
                "weight_source": "fixed exploratory diagnostic weights",
                "calibrated_on_fixed5_truth": False,
                "production_ranking_policy": False,
                "requires_cross_batch_fixture_validation_before_adoption": True,
            },
            "candidate_policy_constraints": {
                "truth_label_used_for_scoring": False,
                "truth_label_used_only_for_aggregate_evaluation": True,
                "production_default_selector_changed": False,
                "selector_strategy_flag_only": True,
                "phase1_ranking_changed": False,
                "phase2_fusion_changed": False,
                "threshold_changed": False,
                "row_scores_changed": False,
            },
        },
    }

    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "dataset": DATASET_NAME,
        "measurement_scope": (
            "diagnostic-only duplicate retention candidate comparison; aggregate only; "
            "raw document identifiers omitted"
        ),
        "policy_constraints": {
            "thresholds_changed": False,
            "row_scores_changed": False,
            "phase1_priority_or_ranking_changed": False,
            "phase2_family_fusion_changed": False,
            "truth_label_boosting_used": False,
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "selector_strategy_flag_only": True,
        },
        "generated_pair_count": len(pairs),
        "generated_artifact_truncated": bool(generated.get("truncated")),
        "generated_artifact_truncation_reason": generated.get("truncation_reason"),
        "candidate_results": candidates,
        "case_order_candidate_results": case_order_candidate_results,
        "raw_identifier_leak_check": {},
        "elapsed_seconds": None,
    }
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.as_posix(),
                "elapsed_seconds": payload["elapsed_seconds"],
                "candidate_summary": {
                    name: {
                        "truth_doc_count": result["truth_doc_count"],
                        "duplicate_case_count_expected": result[
                            "duplicate_case_count_expected"
                        ],
                        "case_truth_doc_count": result["case_measurement"]["truth_doc_count"],
                    }
                    for name, result in candidates.items()
                },
                "case_order_candidate_summary": {
                    name: {
                        "top100_truth_doc_count": (
                            result.get("case_measurement", {})
                            .get("topn", {})
                            .get("100", {})
                            .get("truth_doc_count", result.get("ui_top100_truth_doc_count"))
                        ),
                        "top500_truth_doc_count": (
                            result.get("case_measurement", {})
                            .get("topn", {})
                            .get("500", {})
                            .get("truth_doc_count", result.get("export_top500_truth_doc_count"))
                        ),
                        "duplicate_case_count_expected": result[
                            "duplicate_case_count_expected"
                        ],
                    }
                    for name, result in case_order_candidate_results.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
