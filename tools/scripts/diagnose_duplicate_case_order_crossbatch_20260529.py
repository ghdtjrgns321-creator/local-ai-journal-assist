"""Cross-batch duplicate case-order companion surface diagnostic.

This script compares fixed4 and fixed5 duplicate review surfaces without
changing detector thresholds, row scores, PHASE1 ranking, PHASE2 family fusion,
or the production default duplicate selector. Truth labels are used only after
candidate construction for aggregate evaluation.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import pickle
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
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
from tools.scripts.diagnose_duplicate_retention_candidates_fixed5_20260529 import (
    _case_result_for_pairs,
    _default_order_cases,
    _doc_set_from_pairs,
    _evidence_score,
    _measure_ordered_cases,
    _order_current_top100_case_anchor_plus_diversity_fill,
    _pair_docs,
    _select_pair_diversity_score,
    _select_score_order,
    _tier,
)
from tools.scripts.phase2_family_correlation_audit import _fast_time_shifted_duplicate

OUT_JSON = ROOT / "artifacts" / "duplicate_case_order_crossbatch_20260529.json"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    dataset: str
    case_input: Path
    truth_csv: Path
    batch_id: str
    retention_batch_prefix: str


BATCHES = (
    BatchSpec(
        name="fixed4",
        dataset="datasynth_manipulation_v7_candidate_fixed4",
        case_input=ROOT / "artifacts" / "phase1_manipulation_v7_fixed4_case_input.pkl",
        truth_csv=ROOT
        / "data"
        / "journal"
        / "primary"
        / "datasynth_manipulation_v7_candidate_fixed4"
        / "labels"
        / "manipulated_entry_truth.csv",
        batch_id="fixed4_duplicate_case_order_crossbatch_20260529",
        retention_batch_prefix="fixed4_duplicate_retention_candidate",
    ),
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
        batch_id="fixed5_duplicate_case_order_crossbatch_20260529",
        retention_batch_prefix="fixed5_duplicate_retention_candidate",
    ),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _print(message: str) -> None:
    print(f"[{_now_iso()}] {message}", flush=True)


def _load_case_input(path: Path) -> pd.DataFrame:
    with path.open("rb") as fh:
        payload = pickle.load(fh)
    df = payload["df"].copy()
    if "document_id" in df.columns:
        df["document_id"] = df["document_id"].astype(str)
    return df


def _load_truth(path: Path) -> pd.DataFrame:
    truth = pd.read_csv(path)
    truth["document_id"] = truth["document_id"].astype(str)
    return truth


def _case_docs_from_order(ordered_cases: list[Any]) -> set[str]:
    docs: set[str] = set()
    for case in ordered_cases:
        for ref in getattr(case, "row_refs", ()):
            doc = getattr(ref, "document_id", None)
            if doc not in (None, ""):
                docs.add(str(doc))
    return docs


def _case_order_summary(
    *,
    ordered_cases: list[Any],
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
) -> dict[str, Any]:
    measurement = _measure_ordered_cases(
        ordered=ordered_cases,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    docs = _case_docs_from_order(ordered_cases)
    return {
        "case_count": len(ordered_cases),
        "docs_covered": len(docs),
        "truth_doc_count": len(docs & truth_docs),
        "nontruth_docs_covered": len(docs - truth_docs),
        "top100_truth_doc_count": measurement["topn"]["100"]["truth_doc_count"],
        "top500_truth_doc_count": measurement["topn"]["500"]["truth_doc_count"],
        "top1000_truth_doc_count": measurement["topn"]["1000"]["truth_doc_count"],
        "first_truth_case_rank": measurement["first_truth_case_rank"],
    }


def _case_surface_profile(
    *,
    cases: list[Any],
    truth_docs: set[str],
) -> dict[str, Any]:
    docs = _case_docs_from_order(cases)
    doc_counts: Counter[str] = Counter()
    for case in cases:
        for doc in _case_docs_from_order([case]):
            doc_counts[doc] += 1
    return {
        "case_count": len(cases),
        "docs_covered": len(docs),
        "truth_doc_count": len(docs & truth_docs),
        "nontruth_docs_covered": len(docs - truth_docs),
        "evidence_tier_distribution": dict(
            sorted(Counter(str(case.evidence_tier) for case in cases).items())
        ),
        "rule_id_distribution": dict(
            sorted(
                Counter(str(getattr(case, "sub_rule", "") or "unknown") for case in cases).items()
            )
        ),
        "max_cases_per_document": max(doc_counts.values()) if doc_counts else 0,
        "top_document_case_share": max(doc_counts.values()) / len(cases)
        if cases and doc_counts
        else 0.0,
        "case_grade_only": all(str(case.evidence_tier) in {"strong", "moderate"} for case in cases),
    }


def _case_dedupe_key(case: Any) -> tuple[str, str, str]:
    row_refs = tuple(
        sorted(
            (
                str(getattr(ref, "document_id", "")),
                str(getattr(ref, "row_position", "")),
            )
            for ref in getattr(case, "row_refs", ())
        )
    )
    return (
        str(getattr(case, "case_type", "")),
        str(getattr(case, "sub_rule", "")),
        str(row_refs),
    )


def _order_current_top100_anchor_plus_diversity_fill_capped(
    *,
    current_cases: tuple[Any, ...],
    candidate_cases: tuple[Any, ...],
    cap: int = 500,
) -> list[Any]:
    """Keep the current TOP100 case order, then fill from diversity evidence.

    This is a diagnostic-only companion surface. It preserves the existing early
    review ordering while testing whether case-grade evidence diversity can add
    coverage without expanding the first-level case queue beyond a bounded cap.
    Truth labels are not inputs to this ordering.
    """
    selected: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    for case in _default_order_cases(current_cases)[:100]:
        selected.append(case)
        seen.add(_case_dedupe_key(case))
        if len(selected) >= cap:
            return selected
    for case in _default_order_cases(candidate_cases):
        key = _case_dedupe_key(case)
        if key in seen:
            continue
        selected.append(case)
        seen.add(key)
        if len(selected) >= cap:
            break
    return selected


def _split_sidecar_contract_candidate(
    *,
    current_order: list[Any],
    evidence_order: list[Any],
    truth_docs: set[str],
    current_summary: dict[str, Any],
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    ui_cases = current_order[:100]
    export_cases = evidence_order[:500]
    return {
        "schema_version": 1,
        "contract_status": "diagnostic_candidate",
        "surface_design": "split_ui_review_surface_and_export_sidecar",
        "production_default_selector_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "threshold_changed": False,
        "row_scores_changed": False,
        "raw_identifier_policy": {
            "raw_document_ids_stored": False,
            "raw_row_ids_stored": False,
            "raw_index_labels_stored": False,
            "phase2_case_ids_stored": False,
        },
        "ui_review_surface": {
            "source": "current_document_diversity_top_500_default_case_order",
            "review_cap": 100,
            "ordering_changed": False,
            "top100_truth_doc_count": current_summary["top100_truth_doc_count"],
            "profile": _case_surface_profile(cases=ui_cases, truth_docs=truth_docs),
        },
        "export_sidecar_surface": {
            "source": "evidence_diversity_top_500_default_case_order",
            "review_cap": 500,
            "connected_to_phase2_family_fusion": False,
            "top500_truth_doc_count": evidence_summary["top500_truth_doc_count"],
            "total_truth_doc_count": evidence_summary["truth_doc_count"],
            "profile": _case_surface_profile(cases=export_cases, truth_docs=truth_docs),
        },
        "review_burden_delta_vs_current": {
            "case_count_delta": int(evidence_summary["case_count"] - current_summary["case_count"]),
            "nontruth_docs_delta": int(
                evidence_summary["nontruth_docs_covered"]
                - current_summary["nontruth_docs_covered"]
            ),
        },
    }


def _pair_document_key(pair: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(_pair_docs(pair)))


def _select_group_by_document_pair_representative(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best: dict[tuple[str, ...], dict[str, Any]] = {}
    best_key: dict[tuple[str, ...], tuple[float, float, float]] = {}
    for idx, pair in enumerate(pairs):
        key = _pair_document_key(pair)
        score_key = (
            float(pair.get("pair_score") or 0.0),
            _evidence_score(pair),
            -float(idx),
        )
        if key not in best_key or score_key > best_key[key]:
            best[key] = pair
            best_key[key] = score_key
    return list(best.values())


def _select_group_by_document_with_best_pair(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for pair in sorted(
        enumerate(pairs),
        key=lambda item: (
            -(float(item[1].get("pair_score") or 0.0) + 0.05 * _evidence_score(item[1])),
            item[0],
        ),
    ):
        candidate = pair[1]
        docs = _pair_docs(candidate)
        if not docs or docs & seen_docs:
            continue
        selected.append(candidate)
        seen_docs.update(docs)
    return selected


def _select_rule_tier_balanced_export(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pair in pairs:
        buckets.setdefault((str(pair.get("rule_id") or "unknown"), _tier(pair)), []).append(pair)
    selected: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    while len(selected) < len(pairs):
        progressed = False
        for bucket_key in sorted(buckets):
            bucket = buckets[bucket_key]
            while bucket and id(bucket[0]) in seen_ids:
                bucket.pop(0)
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            seen_ids.add(id(selected[-1]))
            progressed = True
        if not progressed:
            break
    return selected


def _select_high_similarity_export_subset(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for pair in pairs:
        features = pair.get("features")
        if not isinstance(features, dict):
            continue
        ref = float(features.get("reference_similarity") or 0.0)
        text = float(features.get("text_similarity") or 0.0)
        same_partner = features.get("same_partner") is True
        score = float(pair.get("pair_score") or 0.0)
        if same_partner and score >= 0.95 and (ref >= 0.90 or text >= 0.90):
            selected.append(pair)
    return selected


def _audit_feature_score(pair: dict[str, Any]) -> float:
    features = pair.get("features")
    if not isinstance(features, dict):
        return float(pair.get("pair_score") or 0.0)
    repeat_size = float(features.get("repeat_key_group_size_max") or 0.0)
    burst_size = float(features.get("same_day_burst_group_size_max") or 0.0)
    period_end_bonus = 0.05 if features.get("both_period_end_window_3d") is True else 0.0
    routine_penalty = 0.08 if features.get("routine_repeat_candidate") is True else 0.0
    repeat_penalty = min(repeat_size / 100.0, 0.08)
    burst_bonus = min(burst_size / 100.0, 0.04)
    return (
        float(pair.get("pair_score") or 0.0)
        + 0.05 * _evidence_score(pair)
        + period_end_bonus
        + burst_bonus
        - repeat_penalty
        - routine_penalty
    )


def _select_audit_feature_weighted_export(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pair
        for _idx, pair in sorted(
            enumerate(pairs),
            key=lambda item: (-_audit_feature_score(item[1]), item[0]),
        )
    ]


def _select_nonroutine_then_audit_feature_export(
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def is_routine(pair: dict[str, Any]) -> bool:
        features = pair.get("features")
        return isinstance(features, dict) and features.get("routine_repeat_candidate") is True

    return [
        pair
        for _idx, pair in sorted(
            enumerate(pairs),
            key=lambda item: (
                int(is_routine(item[1])),
                -_audit_feature_score(item[1]),
                item[0],
            ),
        )
    ]


def _select_case_grade_audit_feature_export(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        enumerate(pairs),
        key=lambda item: (
            -int(_tier(item[1]) in {"strong", "moderate"}),
            -_audit_feature_score(item[1]),
            -float(item[1].get("pair_score") or 0.0),
            item[0],
        ),
    )
    return [pair for _idx, pair in ordered]


def _feature_profile(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    def numeric_values(key: str) -> list[int]:
        values: list[int] = []
        for pair in pairs:
            features = pair.get("features")
            if not isinstance(features, dict):
                continue
            value = features.get(key)
            if isinstance(value, bool) or value is None:
                continue
            try:
                values.append(int(value))
            except (TypeError, ValueError):
                continue
        return values

    period_end_count = sum(
        1
        for pair in pairs
        if isinstance(pair.get("features"), dict)
        and pair["features"].get("both_period_end_window_3d") is True
    )
    routine_count = sum(
        1
        for pair in pairs
        if isinstance(pair.get("features"), dict)
        and pair["features"].get("routine_repeat_candidate") is True
    )
    return {
        "both_period_end_window_3d_ratio": period_end_count / len(pairs) if pairs else 0.0,
        "routine_repeat_candidate_ratio": routine_count / len(pairs) if pairs else 0.0,
        "repeat_key_group_size_max_quantiles": _simple_quantiles(
            numeric_values("repeat_key_group_size_max")
        ),
        "same_day_burst_group_size_max_quantiles": _simple_quantiles(
            numeric_values("same_day_burst_group_size_max")
        ),
    }


def _export_grouping_candidate_summary(
    *,
    name: str,
    pairs: list[dict[str, Any]],
    df: pd.DataFrame,
    batch_id: str,
    truth_docs: set[str],
    scenario_by_doc: dict[str, str],
    baseline_nontruth_docs: int,
) -> dict[str, Any]:
    bounded_pairs = pairs[:500]
    cases = _case_result_for_pairs(pairs=bounded_pairs, df=df, batch_id=batch_id)
    ordered = _default_order_cases(cases)
    summary = _case_order_summary(
        ordered_cases=ordered,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    return {
        "candidate": name,
        "grouped_unit_count": len(pairs),
        "export_case_count": len(cases),
        "top500_truth_doc_count": summary["top500_truth_doc_count"],
        "total_truth_doc_count": summary["truth_doc_count"],
        "docs_covered": summary["docs_covered"],
        "nontruth_docs_covered": summary["nontruth_docs_covered"],
        "nontruth_docs_delta_vs_evidence_export": int(
            summary["nontruth_docs_covered"] - baseline_nontruth_docs
        ),
        "evidence_tier_distribution": dict(
            sorted(Counter(str(case.evidence_tier) for case in cases).items())
        ),
        "rule_id_distribution": dict(
            sorted(
                Counter(str(getattr(case, "sub_rule", "") or "unknown") for case in cases).items()
            )
        ),
        "case_grade_only": all(str(case.evidence_tier) in {"strong", "moderate"} for case in cases),
        "audit_feature_profile": _feature_profile(bounded_pairs),
        "policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }


def _similarity_bucket(pair: dict[str, Any]) -> str:
    features = pair.get("features")
    if not isinstance(features, dict):
        return "unknown"
    ref = float(features.get("reference_similarity") or 0.0)
    text = float(features.get("text_similarity") or 0.0)
    same_partner = features.get("same_partner") is True
    if same_partner and ref >= 0.90 and text >= 0.90:
        return "partner_ref_text_high"
    if same_partner and (ref >= 0.90 or text >= 0.90):
        return "partner_one_high"
    if same_partner:
        return "partner_other"
    return "no_partner_match"


def _export_summary_group_candidate(
    *,
    name: str,
    pairs: list[dict[str, Any]],
    group_keys: tuple[str, ...],
    truth_docs: set[str],
    baseline_nontruth_docs: int,
) -> dict[str, Any]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for pair in pairs:
        values: list[str] = []
        for key in group_keys:
            if key == "rule_id":
                values.append(str(pair.get("rule_id") or "unknown"))
            elif key == "tier":
                values.append(_tier(pair))
            elif key == "similarity_bucket":
                values.append(_similarity_bucket(pair))
            else:
                values.append("unknown")
        groups.setdefault(tuple(values), []).append(pair)

    docs = _doc_set_from_pairs(pairs)
    group_sizes = [len(group_pairs) for group_pairs in groups.values()]
    return {
        "candidate": name,
        "summary_group_keys": list(group_keys),
        "summary_group_count": len(groups),
        "underlying_pair_count": len(pairs),
        "docs_covered": len(docs),
        "truth_doc_count": len(docs & truth_docs),
        "nontruth_docs_covered": len(docs - truth_docs),
        "nontruth_docs_delta_vs_evidence_export": int(
            len(docs - truth_docs) - baseline_nontruth_docs
        ),
        "group_size_quantiles": _simple_quantiles(group_sizes),
        "bounded_representative_drilldown": {
            "top3_per_group": _bounded_representative_profile(
                groups=groups,
                truth_docs=truth_docs,
                max_representatives_per_group=3,
            ),
            "top5_per_group": _bounded_representative_profile(
                groups=groups,
                truth_docs=truth_docs,
                max_representatives_per_group=5,
            ),
            "top10_per_group": _bounded_representative_profile(
                groups=groups,
                truth_docs=truth_docs,
                max_representatives_per_group=10,
            ),
            "top20_per_group": _bounded_representative_profile(
                groups=groups,
                truth_docs=truth_docs,
                max_representatives_per_group=20,
            ),
        },
        "full_evidence_manifest_candidate": _full_evidence_manifest_candidate(
            groups=groups,
            truth_docs=truth_docs,
        ),
        "summary_first_high_volume_contract": _summary_first_high_volume_contract(
            groups=groups,
            truth_docs=truth_docs,
            high_volume_threshold=100,
        ),
        "case_grade_only": all(_tier(pair) in {"strong", "moderate"} for pair in pairs),
        "raw_identifier_policy": {
            "raw_document_ids_stored": False,
            "raw_pair_ids_stored": False,
            "phase2_case_ids_stored": False,
        },
        "policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }


def _summary_first_high_volume_contract(
    *,
    groups: dict[tuple[str, ...], list[dict[str, Any]]],
    truth_docs: set[str],
    high_volume_threshold: int,
) -> dict[str, Any]:
    full_drilldown_pairs: list[dict[str, Any]] = []
    summary_only_groups = 0
    full_drilldown_groups = 0
    for group_pairs in groups.values():
        if len(group_pairs) > high_volume_threshold:
            summary_only_groups += 1
        else:
            full_drilldown_groups += 1
            full_drilldown_pairs.extend(group_pairs)
    all_pairs = [pair for group_pairs in groups.values() for pair in group_pairs]
    all_docs = _doc_set_from_pairs(all_pairs)
    drilldown_docs = _doc_set_from_pairs(full_drilldown_pairs)
    return {
        "schema_version": 1,
        "contract_status": "diagnostic_candidate",
        "policy": "summary_first_for_high_volume_groups",
        "high_volume_threshold": int(high_volume_threshold),
        "summary_group_count": len(groups),
        "summary_only_group_count": summary_only_groups,
        "full_drilldown_group_count": full_drilldown_groups,
        "underlying_pair_count": len(all_pairs),
        "summary_truth_doc_count": len(all_docs & truth_docs),
        "summary_nontruth_docs_covered": len(all_docs - truth_docs),
        "full_drilldown_pair_count": len(full_drilldown_pairs),
        "full_drilldown_truth_doc_count": len(drilldown_docs & truth_docs),
        "full_drilldown_nontruth_docs_covered": len(drilldown_docs - truth_docs),
        "case_grade_only": all(_tier(pair) in {"strong", "moderate"} for pair in all_pairs),
        "raw_identifier_policy": {
            "raw_document_ids_stored": False,
            "raw_pair_ids_stored": False,
            "phase2_case_ids_stored": False,
        },
        "policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }


def _full_evidence_manifest_candidate(
    *,
    groups: dict[tuple[str, ...], list[dict[str, Any]]],
    truth_docs: set[str],
) -> dict[str, Any]:
    group_records: list[dict[str, Any]] = []
    offset = 1
    for ordinal, (group_key, group_pairs) in enumerate(sorted(groups.items()), start=1):
        docs = _doc_set_from_pairs(group_pairs)
        count = len(group_pairs)
        group_records.append(
            {
                "group_ordinal": ordinal,
                "group_key": list(group_key),
                "evidence_unit_count": count,
                "evidence_ordinal_start": offset,
                "evidence_ordinal_end": offset + count - 1 if count else offset,
                "docs_covered": len(docs),
                "truth_doc_count": len(docs & truth_docs),
                "nontruth_docs_covered": len(docs - truth_docs),
                "case_grade_only": all(
                    _tier(pair) in {"strong", "moderate"} for pair in group_pairs
                ),
            }
        )
        offset += count
    return {
        "schema_version": 1,
        "manifest_status": "diagnostic_candidate",
        "manifest_unit": "grouped_duplicate_pair_evidence",
        "raw_identifier_policy": {
            "raw_document_ids_stored": False,
            "raw_row_ids_stored": False,
            "raw_pair_ids_stored": False,
            "phase2_case_ids_stored": False,
        },
        "group_count": len(group_records),
        "evidence_unit_count": sum(record["evidence_unit_count"] for record in group_records),
        "groups": group_records,
    }


def _bounded_representative_profile(
    *,
    groups: dict[tuple[str, ...], list[dict[str, Any]]],
    truth_docs: set[str],
    max_representatives_per_group: int,
) -> dict[str, Any]:
    representatives: list[dict[str, Any]] = []
    for group_pairs in groups.values():
        ordered = sorted(
            enumerate(group_pairs),
            key=lambda item: (
                -(float(item[1].get("pair_score") or 0.0) + 0.05 * _evidence_score(item[1])),
                item[0],
            ),
        )
        representatives.extend(
            pair for _idx, pair in ordered[: max(max_representatives_per_group, 0)]
        )
    docs = _doc_set_from_pairs(representatives)
    return {
        "representative_pair_count": len(representatives),
        "docs_covered": len(docs),
        "truth_doc_count": len(docs & truth_docs),
        "nontruth_docs_covered": len(docs - truth_docs),
        "case_grade_only": all(
            _tier(pair) in {"strong", "moderate"} for pair in representatives
        ),
    }


def _simple_quantiles(values: list[int]) -> dict[str, float]:
    if not values:
        return {}
    vals = sorted(float(value) for value in values)

    def q(pct: float) -> float:
        return vals[int(round((len(vals) - 1) * pct))]

    return {
        "min": vals[0],
        "p50": q(0.50),
        "p90": q(0.90),
        "max": vals[-1],
    }


def _run_batch(spec: BatchSpec) -> dict[str, Any]:
    started = time.perf_counter()
    _print(f"loading {spec.name}")
    df = _load_case_input(spec.case_input)
    truth = _load_truth(spec.truth_csv)
    truth_docs = set(truth["document_id"].astype(str))
    scenario_by_doc = dict(
        zip(
            truth["document_id"].astype(str),
            truth["manipulation_scenario"].astype(str),
            strict=False,
        )
    )

    settings = get_settings()
    duplicate_detector_module.b05d_time_shifted_duplicate = _fast_time_shifted_duplicate
    _print(f"running duplicate detector for {spec.name}")
    result = DuplicateDetector(settings).detect(df)
    artifact = build_duplicate_pair_artifact(
        df,
        _copy_settings_with_top_n(settings, int(settings.duplicate_max_total_pairs)),
        candidate_scores=result.scores,
        candidate_details=result.details,
    ).to_dict()
    pairs = list(artifact.get("top_pairs", []))
    current_pairs = _select_score_order(pairs, 500)
    evidence_pairs = _select_pair_diversity_score(pairs, 500)

    current_cases = _case_result_for_pairs(
        pairs=current_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_current_500",
    )
    evidence_cases = _case_result_for_pairs(
        pairs=evidence_pairs,
        df=df,
        batch_id=f"{spec.retention_batch_prefix}_evidence_diversity_top_500",
    )
    current_order = _default_order_cases(current_cases)
    evidence_order = _default_order_cases(evidence_cases)
    anchor_order = _order_current_top100_case_anchor_plus_diversity_fill(
        current_cases=current_cases,
        candidate_cases=evidence_cases,
    )
    capped_anchor_order = _order_current_top100_anchor_plus_diversity_fill_capped(
        current_cases=current_cases,
        candidate_cases=evidence_cases,
        cap=500,
    )

    current_docs = _doc_set_from_pairs(current_pairs)
    evidence_docs = _doc_set_from_pairs(evidence_pairs)
    current_summary = _case_order_summary(
        ordered_cases=current_order,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    evidence_summary = _case_order_summary(
        ordered_cases=evidence_order,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    anchor_summary = _case_order_summary(
        ordered_cases=anchor_order,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    capped_anchor_summary = _case_order_summary(
        ordered_cases=capped_anchor_order,
        truth_docs=truth_docs,
        scenario_by_doc=scenario_by_doc,
    )
    split_summary = {
        "ui_top100_truth_doc_count": current_summary["top100_truth_doc_count"],
        "export_top500_truth_doc_count": evidence_summary["top500_truth_doc_count"],
        "export_total_truth_doc_count": evidence_summary["truth_doc_count"],
        "case_count": evidence_summary["case_count"],
        "nontruth_docs_covered": evidence_summary["nontruth_docs_covered"],
    }
    sidecar_contract_candidate = _split_sidecar_contract_candidate(
        current_order=current_order,
        evidence_order=evidence_order,
        truth_docs=truth_docs,
        current_summary=current_summary,
        evidence_summary=evidence_summary,
    )
    export_grouping_candidates = {
        "group_by_document_pair_representative": _select_group_by_document_pair_representative(
            evidence_pairs
        ),
        "group_by_document_with_best_pair": _select_group_by_document_with_best_pair(
            evidence_pairs
        ),
        "rule_tier_balanced_export": _select_rule_tier_balanced_export(evidence_pairs),
        "high_similarity_export_subset": _select_high_similarity_export_subset(evidence_pairs),
        "audit_feature_weighted_export": _select_audit_feature_weighted_export(evidence_pairs),
        "audit_feature_weighted_from_generated_pairs": _select_audit_feature_weighted_export(pairs),
        "nonroutine_then_audit_feature_from_generated_pairs": (
            _select_nonroutine_then_audit_feature_export(pairs)
        ),
        "case_grade_audit_feature_from_generated_pairs": (
            _select_case_grade_audit_feature_export(pairs)
        ),
    }
    export_grouping_candidate_results = {
        name: _export_grouping_candidate_summary(
            name=name,
            pairs=selected_pairs,
            df=df,
            batch_id=f"{spec.retention_batch_prefix}_{name}",
            truth_docs=truth_docs,
            scenario_by_doc=scenario_by_doc,
            baseline_nontruth_docs=evidence_summary["nontruth_docs_covered"],
        )
        for name, selected_pairs in export_grouping_candidates.items()
    }
    export_summary_group_candidates = {
        "rule_tier_grouped_summary": _export_summary_group_candidate(
            name="rule_tier_grouped_summary",
            pairs=evidence_pairs,
            group_keys=("rule_id", "tier"),
            truth_docs=truth_docs,
            baseline_nontruth_docs=evidence_summary["nontruth_docs_covered"],
        ),
        "rule_tier_similarity_bucket_summary": _export_summary_group_candidate(
            name="rule_tier_similarity_bucket_summary",
            pairs=evidence_pairs,
            group_keys=("rule_id", "tier", "similarity_bucket"),
            truth_docs=truth_docs,
            baseline_nontruth_docs=evidence_summary["nontruth_docs_covered"],
        ),
    }
    return {
        "dataset": spec.dataset,
        "row_count": len(df),
        "truth_doc_count": len(truth_docs),
        "generated_pair_count": len(pairs),
        "generated_artifact_truncated": bool(artifact.get("truncated")),
        "generated_artifact_truncation_reason": artifact.get("truncation_reason"),
        "pair_surfaces": {
            "current_document_diversity_top_500": {
                "pair_truth_doc_count": len(current_docs & truth_docs),
                "docs_covered": len(current_docs),
            },
            "evidence_diversity_top_500": {
                "pair_truth_doc_count": len(evidence_docs & truth_docs),
                "docs_covered": len(evidence_docs),
            },
        },
        "case_order_surfaces": {
            "current_default": current_summary,
            "evidence_diversity_default": evidence_summary,
            "current_top100_anchor_plus_diversity_fill": anchor_summary,
            "current_top100_anchor_plus_diversity_fill_capped_500": capped_anchor_summary,
            "split_ui100_current_export500_evidence": split_summary,
        },
        "sidecar_contract_candidate": sidecar_contract_candidate,
        "export_grouping_candidate_results": export_grouping_candidate_results,
        "export_summary_group_candidate_results": export_summary_group_candidates,
        "directional_checks": {
            "split_preserves_current_top100": (
                split_summary["ui_top100_truth_doc_count"]
                >= current_summary["top100_truth_doc_count"]
            ),
            "split_improves_export_top500": (
                split_summary["export_top500_truth_doc_count"]
                > current_summary["top500_truth_doc_count"]
            ),
            "anchor_preserves_current_top100": (
                anchor_summary["top100_truth_doc_count"]
                >= current_summary["top100_truth_doc_count"]
            ),
            "anchor_improves_top500": (
                anchor_summary["top500_truth_doc_count"]
                > current_summary["top500_truth_doc_count"]
            ),
            "capped_anchor_preserves_current_top100": (
                capped_anchor_summary["top100_truth_doc_count"]
                >= current_summary["top100_truth_doc_count"]
            ),
            "capped_anchor_improves_top500": (
                capped_anchor_summary["top500_truth_doc_count"]
                > current_summary["top500_truth_doc_count"]
            ),
        },
        "policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    started = time.perf_counter()
    batches: dict[str, Any] = {}
    all_truth_docs: set[str] = set()
    for spec in BATCHES:
        batch_payload = _run_batch(spec)
        batches[spec.name] = batch_payload
        truth = _load_truth(spec.truth_csv)
        all_truth_docs.update(truth["document_id"].astype(str))

    payload: dict[str, Any] = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "measurement_scope": (
            "diagnostic-only duplicate case-order companion surface cross-batch comparison; "
            "aggregate only; raw identifiers omitted"
        ),
        "current_iteration_candidate": {
            "name": "grouped_summary_primary_with_full_manifest",
            "status": "diagnostic_contract_candidate",
            "reason": (
                "Keeps the split UI/export surface, preserves export aggregate coverage, "
                "and reduces first-level export review units from case-level rows to "
                "rule/tier/similarity groups."
            ),
            "production_default_selector_changed": False,
            "production_case_order_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "requires_followup": (
                "Define bounded representative drilldown semantics as partial sample, not full "
                "coverage, before any product adoption proposal."
            ),
        },
        "batches": batches,
        "raw_identifier_leak_check": {},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    payload["raw_identifier_leak_check"] = raw_identifier_leak_check(
        payload,
        forbidden_values=all_truth_docs,
    )
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": OUT_JSON.as_posix(),
                "elapsed_seconds": payload["elapsed_seconds"],
                "summary": {
                    name: batch["directional_checks"] for name, batch in batches.items()
                },
                "raw_identifier_leak_check": payload["raw_identifier_leak_check"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
