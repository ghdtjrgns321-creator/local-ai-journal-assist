from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_v31_feature_gap_experiment_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_v31_feature_gap_guardrails_locked():
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["weak_pair_gate_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_metadata_used_as_selector"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True


def test_duplicate_v31_feature_gap_baseline_attrition_locked():
    baseline = _payload()["baseline_attrition"]

    assert baseline == {
        "primary_docs": 76,
        "row_score_primary_docs": 28,
        "no_row_score_primary_docs": 48,
        "candidate_subset_primary_docs": 0,
        "candidate_subset_selected_rows": 50000,
        "candidate_subset_min_score": 0.5989857631894374,
    }


def test_duplicate_v31_feature_gap_experiments_locked():
    payload = _payload()
    summary = payload["experiment_summary"]

    assert summary == {
        "l2_03d_lower_score_floor_band_primary_docs": 0,
        "l2_03d_lower_score_floor_band_case_grade_primary_docs": 0,
        "observable_document_profile_primary_docs": 75,
        "observable_document_profile_case_grade_primary_docs": 74,
        "best_non_oracle_candidate": "observable_document_profile_sample",
        "best_non_oracle_primary_docs": 75,
        "best_non_oracle_case_grade_primary_docs": 74,
    }

    profile = payload["candidate_experiments"]["observable_document_profile_sample"]
    assert profile["expected_review_burden"] == {
        "top_pairs": 5000,
        "candidate_docs": 10000,
        "nonprimary_candidate_docs": 9924,
    }
    assert profile["weak_pair_ratio"] == 0.992

    l2 = payload["candidate_experiments"]["l2_03d_lower_score_floor_band_sample"]
    assert l2["generated_pair_evidence_primary_docs"] == 0
    assert l2["case_grade_pair_primary_docs"] == 0


def test_duplicate_v31_feature_gap_decision_and_leak_guard_locked():
    payload = _payload()

    assert payload["decision"] == {
        "main_candidate_subset_change": False,
        "production_sidecar_adoption": False,
        "weak_pair_promotion": False,
        "next_improvement_direction": (
            "Lower-score floor-band still fails, but observable document-profile "
            "sampling recovers primary pair evidence with high review burden. "
            "Next, reduce nonprimary burden with audit-stable guards before "
            "considering any export sidecar."
        ),
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
