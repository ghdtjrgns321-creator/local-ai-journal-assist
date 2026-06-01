"""Duplicate Phase 5 remaining potential diagnostic tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from tools.scripts.diagnose_duplicate_remaining_potential_fixed5_20260530 import (
    _select_current_with_tiebreak,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_remaining_potential_fixed5_20260530.json"
EXPECTED_LEAK_CHECK = {
    "doc_like_token_count": 0,
    "forbidden_identifier_key_count": 0,
    "forbidden_identifier_value_count": 0,
    "phase2_case_id_like_token_count": 0,
}


def test_tiebreak_selector_does_not_accept_truth_or_phase1_gap_inputs():
    params = set(inspect.signature(_select_current_with_tiebreak).parameters)

    assert params == {"pairs", "top_n"}


def test_remaining_potential_artifact_locks_fixed5_headroom_and_decision():
    payload_text = ARTIFACT.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert payload["raw_identifier_leak_check"] == EXPECTED_LEAK_CHECK
    assert "DOC-" not in payload_text
    assert "TRUTH-" not in payload_text
    assert "p2_duplicate_" not in payload_text
    assert payload["policy_constraints"] == {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_default_selector_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "threshold_changed": False,
        "row_scores_changed": False,
    }

    fixed5 = payload["batches"]["fixed5_normalcal5"]
    assert fixed5["duplicate_first_review_headroom"] == {
        "generated_potential_truth_docs": 24,
        "current_captured_truth_docs": 19,
        "current_missed_truth_docs": 5,
        "generated_potential_truth_docs_outside_phase1_top500": 8,
        "current_captured_truth_docs_outside_phase1_top500": 5,
        "current_missed_truth_docs_outside_phase1_top500": 3,
        "current_top100_truth_docs": 22,
        "current_top500_truth_docs": 22,
    }
    assert fixed5["missed_potential_classification"] == {
        "reason_distribution": {
            "artifact_cap_boundary": 2,
            "weak_pair_only": 3,
        },
        "case_grade_missed_doc_count": 2,
        "missed_doc_count": 5,
    }
    assert fixed5["decision_payload"] == {
        "duplicate_first_review_headroom": 5,
        "generated_potential_truth_docs": 24,
        "current_captured_truth_docs": 19,
        "current_missed_truth_docs": 5,
        "missed_potential_explainable": True,
        "recommended_action": "keep_current_first_review_and_use_case_grade_sidecar",
        "production_first_review_ranking_change": False,
        "sidecar_or_export_surface_candidate": "current_plus_case_grade_sidecar",
        "fitting_risk": True,
        "adoption_blocker": "first_review_tiebreak_loses_current_phase1_top100_complement",
    }


def test_remaining_potential_candidates_lock_sidecar_vs_tiebreak_tradeoff():
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    fixed5_candidates = payload["batches"]["fixed5_normalcal5"]["candidate_results"]

    sidecar = fixed5_candidates["current_plus_case_grade_sidecar"]
    assert sidecar["top100_truth_docs"] == 22
    assert sidecar["top100_phase1_top100_outside_truth_docs"] == 19
    assert sidecar["current_captured_19_maintained"] is True
    assert sidecar["current_captured_19_maintained_count"] == 19
    assert sidecar["missed_potential_recovery_count"] == 0
    assert sidecar["weak_pair_ratio"] == 0.0
    assert sidecar["case_grade_pair_ratio"] == 1.0
    assert sidecar["sidecar_top500_truth_docs"] == 36
    assert sidecar["sidecar_top500_phase1_top100_outside_truth_docs"] == 8

    tiebreak = fixed5_candidates["current_with_missed_potential_tiebreak"]
    assert tiebreak["current_captured_19_maintained"] is False
    assert tiebreak["current_captured_19_maintained_count"] == 0
    assert tiebreak["missed_potential_recovery_count"] == 0
    assert tiebreak["failed_if_current_capture_worsens"] is True
    assert tiebreak["weak_pair_ratio"] == 0.0
    assert tiebreak["case_grade_pair_ratio"] == 1.0


def test_remaining_potential_crossbatch_sanity_locks_instability():
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    fixed4 = payload["batches"]["fixed4"]

    assert fixed4["duplicate_first_review_headroom"][
        "generated_potential_truth_docs"
    ] == 164
    assert fixed4["duplicate_first_review_headroom"]["current_captured_truth_docs"] == 53
    assert fixed4["duplicate_first_review_headroom"]["current_missed_truth_docs"] == 111
    assert fixed4["missed_potential_classification"]["reason_distribution"] == {
        "artifact_cap_boundary": 8,
        "case_grade_filtered": 32,
        "weak_pair_only": 71,
    }
    assert fixed4["candidate_results"]["current_plus_case_grade_sidecar"][
        "sidecar_top500_truth_docs"
    ] == 100
    assert fixed4["candidate_results"]["current_plus_case_grade_sidecar"][
        "sidecar_top500_phase1_top100_outside_truth_docs"
    ] == 90
    assert fixed4["candidate_results"]["current_with_missed_potential_tiebreak"][
        "failed_if_current_capture_worsens"
    ] is True
