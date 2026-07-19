"""Tests for fixed5 TS TOP100 failure diagnostic artifact."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_top100_failure_diagnostic_fixed5_20260530.json"
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


def test_top100_failure_guardrails_and_raw_leak_check():
    payload = _payload()

    assert payload["dataset"] == "fixed5_normalcal5"
    assert payload["guardrails"] == {
        "truth_label_used_for_selector": False,
        "scenario_label_used_for_selector": False,
        "production_gate_ranking_fusion_changed": False,
        "phase1_ranking_changed": False,
        "broad_companion_used_as_ts_primary": False,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_truth_attribution_and_label_alignment_counts():
    audit = _payload()["ts_truth_attribution_audit"]

    assert audit["ts_specific_truth_docs_count"] == 32
    assert audit["mixed_non_ts_truth_docs_count"] == 588
    assert audit["ts_candidate_pool_truth_docs_count"] == 502
    assert audit["candidate_pool_but_outside_top100_truth_docs_count"] == 489
    assert audit["candidate_pool_missing_truth_docs_count"] == 118
    assert audit["alignment_counts"] == {
        "mixed_but_ts_relevant": 400,
        "non_ts_primary_but_ts_context_present": 144,
        "not_ts_family_target": 44,
        "ts_primary_label_aligned": 32,
    }
    assert audit["feature_buckets"]["ts01_match"] == 13
    assert audit["feature_buckets"]["ts02_match"] == 0
    assert audit["feature_buckets"]["matched_by_other_phase2_family"] == 620


def test_top100_miss_reasons_and_implementation_verification():
    payload = _payload()
    reasons = payload["top100_miss_reason_summary"]

    assert reasons["implementation_suspect"] == 0
    assert reasons["mixed_scenario_not_ts_primary"] == 470
    assert reasons["normal_period_end_competition"] == 368
    assert reasons["ranking_formula_underweights_ts_specific_signal"] == 19

    verification = payload["implementation_verification"]
    assert verification["implementation_bug_suspected"] is False
    assert verification["artifact_window_count"] == 1000
    assert verification["artifact_sub_signal_high_window_count"] == 861
    assert verification["ts01_truth_doc_count"] == 13
    assert verification["ts02_truth_doc_count"] == 0


def test_candidate_surfaces_separate_ts_primary_from_mixed_surface():
    candidates = _payload()["candidate_surfaces"]

    current = candidates["current_native_ts_order"]
    assert current["topn"]["100"]["ts_specific_truth_docs"] == 0
    assert current["topn"]["500"]["ts_specific_truth_docs"] == 0

    conservative = candidates["ts_primary_conservative_surface"]
    assert conservative["topn"]["100"]["ts_specific_truth_docs"] == 13
    assert conservative["topn"]["100"]["mixed_but_ts_relevant_truth_docs"] == 0
    assert conservative["topn"]["500"]["ts_specific_truth_docs"] == 32
    assert conservative["topn"]["500"]["truth_docs_outside_phase1_top100"] == 32
    assert conservative["low_support_ratio"] == 0.0

    mixed = candidates["mixed_ts_relevant_surface"]
    assert mixed["topn"]["100"]["ts_specific_truth_docs"] == 2
    assert mixed["topn"]["100"]["mixed_but_ts_relevant_truth_docs"] == 236
    assert mixed["topn"]["500"]["mixed_but_ts_relevant_truth_docs"] == 275


def test_decision_payload_records_failure_source():
    decision = _payload()["decision"]

    assert decision["ts_top100_failure_primary_reason"] == "mixed_scenario_not_ts_primary"
    assert decision["implementation_bug_suspected"] is False
    assert decision["datasynth_label_alignment_issue_suspected"] is True
    assert decision["ts_primary_label_aligned_truth_docs"] == 32
    assert decision["mixed_but_ts_relevant_truth_docs"] == 400
    assert decision["candidate_pool_missing_truth_docs"] == 118
    assert decision["candidate_but_ranked_below_top100_truth_docs"] == 489
    assert decision["best_ts_primary_candidate"] == "ts_primary_conservative_surface"
    assert decision["top100_product_viable"] is True
    assert decision["top500_companion_only_rejected_as_final_goal"] is True
    assert decision["production_adoption"] is False


def test_top100_failure_artifact_does_not_emit_raw_identifiers():
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
