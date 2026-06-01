"""Tests for v3.1 TS primary diagnostic artifact."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json"
TRUTH = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic"
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


def test_v31_timeseries_primary_target_and_guardrails():
    payload = _payload()

    assert payload["dataset"] == "fixed5_ownermeta_ic"
    assert payload["source_candidate"] == "datasynth_manipulation_v7_candidate_fixed5_ownermeta_ic"
    assert payload["guardrails"] == {
        "diagnostic_only": True,
        "truth_label_used_for_selector": False,
        "scenario_label_used_for_selector": False,
        "phase1_rank_used_for_selector": False,
        "matched_result_used_for_selector": False,
        "raw_identifier_used_for_selector": False,
        "owner_metadata_used_for_denominator_only": True,
        "production_gate_ranking_fusion_changed": False,
        "production_default_ordering_changed": False,
        "phase1_ranking_changed": False,
        "fixed4_used": False,
        "broad_companion_used_as_ts_primary": False,
    }
    assert payload["v31_primary_target"]["timeseries_primary_docs"] == 21
    assert payload["v31_primary_target"]["period_end_context_docs"] == 92
    assert payload["v31_primary_target"]["v31_responsibility_consistency"] == {
        "available": True,
        "v31_primary_denominator": 21,
        "v31_native_top500_matched_docs": 0,
        "matches_truth_metadata_count": True,
    }


def test_v31_timeseries_surface_comparison():
    surfaces = _payload()["candidate_surfaces"]

    assert surfaces["current_native_ts_order"]["top100_matched_docs"] == 0
    assert surfaces["current_native_ts_order"]["top500_matched_docs"] == 0
    assert surfaces["current_native_ts_order"]["missing_from_top500_docs"] == 21

    conservative = surfaces["ts_primary_conservative_surface"]
    assert conservative["top100_matched_docs"] == 13
    assert conservative["top500_matched_docs"] == 21
    assert conservative["top100_recall"] == 0.619048
    assert conservative["top500_recall"] == 1.0

    stabilized = surfaces["ts_specific_top100_stabilized_surface"]
    assert stabilized["top100_matched_docs"] == 21
    assert stabilized["top500_matched_docs"] == 21
    assert stabilized["top100_recall"] == 1.0
    assert stabilized["top500_recall"] == 1.0
    assert stabilized["top500_review_burden"]["low_support_ratio"] == 0.0
    assert stabilized["top500_review_burden"]["period_end_ratio"] == 1.0


def test_v31_timeseries_decision_payload():
    payload = _payload()
    decision = payload["decision"]

    assert decision["best_candidate"] == "ts_specific_top100_stabilized_surface"
    assert decision["best_candidate_top100_matched_docs"] == 21
    assert decision["best_candidate_top500_matched_docs"] == 21
    assert decision["current_native_top500_matched_docs"] == 0
    assert decision["primary_improvement_available"] is True
    assert decision["top500_full_capture_available"] is True
    assert decision["production_adoption"] is False
    assert decision["production_default_ordering"] == "native"

    assert payload["selector_input_policy"] == {
        "candidate_surface": "ts_specific_top100_stabilized_surface",
        "truth_label_used": False,
        "scenario_label_used": False,
        "owner_metadata_used": False,
        "phase1_rank_used": False,
        "matched_result_used": False,
        "raw_identifier_used": False,
        "allowed_feature_groups": [
            "period_end_context",
            "row_ref_support_count",
            "round_amount_context",
            "after_hours_or_weekend_context",
            "context_evidence_count",
            "period_end_lift",
            "robust_z",
            "subject_activity_rank",
        ],
    }
    assert payload["adoption_readiness"] == {
        "status": "diagnostic_candidate_not_product_default",
        "product_default_ordering_strategy": "native",
        "candidate_ordering_strategy": "ts_specific_top100_stabilized_surface",
        "explicit_flag_required": True,
        "product_default_adoption_allowed": False,
        "period_end_context_primary_denominator": False,
        "fixed4_used_for_product_judgment": False,
        "required_validation_before_default": {
            "regenerated_owner_metadata_datasynth": {
                "required": True,
                "minimum_primary_docs": 21,
                "required_top100_primary_capture": 21,
                "required_top500_primary_capture": 21,
                "period_end_context_denominator_allowed": False,
            },
            "fixed5_compatible_slice_validation": {
                "required": True,
                "each_slice_top500_capture_must_equal_primary_docs": True,
                "top100_slice_regression_requires_review": True,
                "must_not_use_fixed4": True,
            },
            "selector_contract": {
                "truth_label_allowed": False,
                "scenario_label_allowed": False,
                "owner_metadata_allowed": False,
                "phase1_rank_allowed": False,
                "matched_result_allowed": False,
                "raw_identifier_allowed": False,
            },
        },
        "blockers": [
            "single fixed5 owner-metadata candidate validation only",
            (
                "requires regenerated owner-metadata DataSynth or fixed5-compatible "
                "slice validation before default adoption"
            ),
            "must keep period-end context docs out of TS primary denominator",
        ],
        "next_adoption_gate": (
            "promote only if stabilized timing/window features keep 21/21 primary capture "
            "without broad companion or period-end-context denominator inflation"
        ),
    }


def test_v31_timeseries_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    truth_doc_ids = _truth_doc_ids()

    assert truth_doc_ids
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
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
