"""Tests for fixed5 TS-specific TOP100 rank-band gap diagnostic artifact."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_top100_rankband_gap_fixed5_20260530.json"
TRUTH = (
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


def _truth_doc_ids() -> list[str]:
    with TRUTH.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


def test_rankband_gap_guardrails_and_raw_leak_check():
    payload = _payload()

    assert payload["dataset"] == "fixed5_normalcal5"
    assert payload["guardrails"] == {
        "truth_label_used_for_selector": False,
        "scenario_label_used_for_selector": False,
        "production_gate_ranking_fusion_changed": False,
        "phase1_ranking_changed": False,
        "fixed4_used_for_product_judgment": False,
        "broad_companion_used_as_ts_primary": False,
        "fixed5_top100_weight_sweep_used": False,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_rankband_group_counts_and_feature_gap():
    payload = _payload()
    baseline = payload["baseline"]
    comparison = payload["rank_band_comparison"]
    promoted = comparison["promoted_top100_ts_specific"]
    delayed = comparison["delayed_101_500_ts_specific"]
    gaps = comparison["directional_feature_gaps"]

    assert baseline == {
        "ts_specific_truth_docs": 32,
        "current_native_ts_top100_ts_specific": 0,
        "ts_primary_conservative_top100_ts_specific": 13,
        "ts_primary_conservative_top500_ts_specific": 32,
    }
    assert promoted["count"] == 13
    assert delayed["count"] == 19
    assert promoted["after_hours_or_weekend_context_ratio"] == 1.0
    assert delayed["after_hours_or_weekend_context_ratio"] == 0.421053
    assert promoted["subject_activity_rank_median"] == 61.0
    assert delayed["subject_activity_rank_median"] == 4.0
    assert promoted["business_process_distribution"] == {"TRE": 13}
    assert delayed["business_process_distribution"] == {"R2R": 11, "TRE": 8}
    assert gaps == {
        "after_hours_weekend_lower_in_delayed": True,
        "subject_activity_background_higher_in_delayed": True,
        "amount_tail_higher_in_delayed": True,
        "support_not_lower_in_delayed": True,
        "period_end_equally_present": True,
    }


def test_delayed_reason_buckets_are_aggregate_only():
    reasons = _payload()["delayed_101_500_miss_reasons"]

    assert reasons["score_tie_or_rank_band_collision"] == 19
    assert reasons["lower_robust_z"] == 11
    assert reasons["low_context_evidence"] == 11
    assert reasons["low_baseline_support"] == 11
    assert reasons["high_subject_activity_background"] == 11
    assert reasons["normal_period_end_competition"] == 11
    assert reasons["weak_after_hours_weekend_signal"] == 11
    assert reasons["one_row_or_low_support_window"] == 0
    assert reasons["no_clear_audit_observable_difference"] == 0


def test_stabilized_candidate_improves_ts_specific_without_mixed_inflation():
    payload = _payload()
    judgment = payload["candidate_feature_judgment"]
    candidate = payload["candidate_surface"]

    assert judgment["defensible_top100_feature_found"] is True
    assert judgment["accepted_candidate_features"] == [
        "after_hours_weekend_priority",
        "subject_activity_background_adjustment",
    ]
    assert candidate["created"] is True
    assert candidate["name"] == "ts_specific_top100_stabilized_surface"
    assert candidate["diagnostic_only"] is True
    assert candidate["top100_ts_specific_truth_docs"] == 21
    assert candidate["top500_ts_specific_truth_docs"] == 32
    assert candidate["top100_mixed_but_ts_relevant_truth_docs"] == 0
    assert candidate["top500_mixed_but_ts_relevant_truth_docs"] == 0
    assert candidate["top100_ts_specific_delta_vs_conservative"] == 8
    assert candidate["low_support_ratio"] == 0.0
    assert candidate["review_burden"] == candidate["conservative_review_burden"]


def test_rankband_gap_decision_payload():
    decision = _payload()["decision"]

    assert decision["promoted_top100_ts_specific_count"] == 13
    assert decision["delayed_101_500_ts_specific_count"] == 19
    assert decision["primary_delay_reason"] == "score_tie_or_rank_band_collision"
    assert decision["defensible_top100_feature_found"] is True
    assert decision["candidate_surface_created"] is True
    assert decision["candidate_surface_name"] == "ts_specific_top100_stabilized_surface"
    assert decision["top100_product_viable"] is True
    assert decision["top500_full_capture_retained"] is True
    assert decision["data_synth_alignment_issue_remaining"] is True
    assert decision["production_adoption"] is False


def test_rankband_gap_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    truth_doc_ids = _truth_doc_ids()

    assert truth_doc_ids
    assert all(document_id not in text for document_id in truth_doc_ids)
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
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert "p2_timeseries_window_" not in text
