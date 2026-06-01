"""Smoke tests for Phase 5 unsupervised evidence quality diagnostic."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_evidence_quality_fixed5_20260530.json"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)


def _payload() -> dict[str, Any]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _truth_doc_ids() -> list[str]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def test_phase5_policy_flags_and_top_features_are_locked():
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_top_features_connected"] is True
    assert payload["dummy_measurement_path_separated"] is True
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["native_row_case_ordering_changed"] is False

    feature = payload["feature_quality"]
    assert feature["top_features_available_case_count"] == 51717
    assert feature["top_features_available_truth_docs"] == 483
    assert feature["top_feature_evidence_added_truth_docs"] == 483
    assert feature["top_features_available_top100_truth_docs"] == 5
    assert feature["top_features_available_top500_truth_docs"] == 39
    assert feature["top_feature_evidence_type_distribution"] == {
        "statistical_outlier": 155151,
    }
    assert feature["top_feature_category_distribution"]["amount"] == 15490
    assert feature["top_feature_category_distribution"]["time_period"] == 5909


def test_phase5_surface_metrics_are_locked():
    surfaces = _payload()["surface_metrics"]

    native = surfaces["native_row_queue"]["topn"]
    assert native["100"]["matched"] == 5
    assert native["500"]["matched"] == 39
    assert native["10000"]["matched"] == 289

    soft = surfaces["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched"] == 25
    assert soft["topn"]["500"]["matched"] == 151
    assert soft["topn"]["1000"]["matched"] == 307
    assert soft["topn"]["10000"]["matched"] == 483
    assert soft["topn"]["500"]["phase1_immediate_review_outside_truth_docs"] == 151
    assert soft["topn"]["500"]["phase1_review_or_above_outside_truth_docs"] == 114
    assert soft["topn"]["500"]["phase1_candidate_or_above_outside_truth_docs"] == 106
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.256
    assert soft["top500_pressure"]["top_features_availability"] == 1.0

    context = surfaces["soft_guard_with_row_count_context"]
    assert context["topn"]["500"]["matched"] == 174
    assert context["top500_pressure"]["repeated_normal_pressure"] == 0.282

    upper = surfaces["hybrid_row_count_blended_surface_upper_bound"]
    assert upper["topn"]["100"]["matched"] == 61
    assert upper["topn"]["500"]["matched"] == 263
    assert upper["top500_pressure"]["repeated_normal_pressure"] == 0.382

    guard = surfaces["soft_guard_pressure_guard_surface"]
    assert guard["topn"]["500"]["matched"] == 22
    assert guard["top500_pressure"]["repeated_normal_pressure"] == 0.0


def test_phase5_q95_backlog_and_decision_are_locked():
    payload = _payload()
    backlog = payload["q95_near_miss_backlog"]

    assert backlog["q95_miss_truth_docs"] == 137
    assert backlog["near_q95_truth_docs"] == 64
    assert backlog["strong_document_context_truth_docs"] == 25
    assert backlog["near_q95_with_top_features_truth_docs"] == 0
    assert backlog["reason_buckets"] == {
        "below_q95_native_gate": 137,
        "near_q95_future_validation_candidate": 64,
        "not_promoted_to_case": 137,
    }

    decision = payload["decision"]
    assert decision["production_top_features_connected"] is True
    assert decision["evidence_quality_improved"] is True
    assert decision["best_defensive_companion_surface"] == (
        "hybrid_with_soft_repeated_normal_guard"
    )
    assert decision["best_upper_bound_surface"] == (
        "hybrid_row_count_blended_surface_upper_bound"
    )
    assert decision["production_adoption"] is False
    assert decision["q95_gate_change_recommended"] is False
    assert decision["repeated_normal_pressure"] == 0.256


def test_phase5_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert all(document_id not in text for document_id in _truth_doc_ids())
    banned_keys = {
        "document" "_id",
        "document" "_ids",
        "r" "aw" "_document" "_id",
        "r" "aw" "_document" "_ids",
        "row" "_id",
        "row" "_ids",
        "r" "aw" "_row" "_id",
        "r" "aw" "_row" "_ids",
        "index" "_label",
        "r" "aw" "_index" "_label",
        "phase2" "_case" "_id",
        "phase2" "_case" "_ids",
    }
    assert banned_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
