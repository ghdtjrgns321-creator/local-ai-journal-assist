from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_v33_exact_sidecar_fixed5_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_v33_denominators_and_current_path_locked():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b"
    assert payload["responsibility_map_version"] == "v3.3b"
    assert payload["diagnostic_only"] is True
    assert payload["duplicate_primary_denominator"] == 22
    assert payload["duplicate_companion_denominator"] == 71
    assert payload["production_first_review_ranking_changed"] is True
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["candidate_subset_supplement_changed"] is True
    assert payload["pair_artifact_selection_strategy_changed"] is True
    assert payload["document_profile_pair_builder_added"] is True
    assert payload["weak_pair_gate_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False

    current = payload["current_duplicate_path"]
    assert current["measurement_basis"] == "top_pair_artifact_exact_doc_join"
    assert current["row_score_primary_docs"] == 10
    assert current["row_score_companion_docs"] == 8
    assert current["candidate_subset_primary_docs"] == 22
    assert current["candidate_subset_companion_docs"] == 34
    assert current["candidate_subset_selected_rows"] == 50000
    assert current["candidate_subset_score_rows"] == 48966
    assert current["candidate_subset_supplement_rows"] == 1034
    assert current["candidate_subset_supplement_docs"] == 500
    assert current["candidate_subset_supplement_strategy"] == "observable_profile"
    assert current["pair_artifact_built"] is True
    assert current["primary_case_grade_docs"] == 10
    assert current["companion_case_grade_docs"] == 4
    assert current["rule_id_distribution"] == {
        "L2-03a": 275,
        "L2-03b": 166,
        "L2-03e": 59,
    }


def test_duplicate_v33_bounded_export_candidate_locked():
    payload = _payload()
    sidecars = payload["sidecar_results"]

    top2000 = sidecars["observable_profile_top_2000"]
    top500 = sidecars["observable_profile_top_500"]
    strict = sidecars["strict_time_shift_reference_guard"]
    mid = sidecars["mid_time_shift_reference_guard"]

    assert top2000["candidate_docs"] == 2000
    assert top2000["primary_case_grade_docs"] == 22
    assert top2000["companion_case_grade_docs"] == 34
    assert top2000["non_target_candidate_docs"] == 1944

    assert top500["candidate_docs"] == 500
    assert top500["primary_case_grade_docs"] == 22
    assert top500["companion_case_grade_docs"] == 34
    assert top500["non_target_candidate_docs"] == 444
    assert top500["primary_case_grade_recall"] == 1.0
    assert top500["non_target_to_all_target_candidate_ratio"] == 7.928571

    assert strict["candidate_docs"] == 36
    assert strict["primary_case_grade_docs"] == 10
    assert strict["companion_case_grade_docs"] == 4
    assert strict["non_target_candidate_docs"] == 22

    assert mid["candidate_docs"] == 38
    assert mid["primary_case_grade_docs"] == 10
    assert mid["companion_case_grade_docs"] == 4
    assert mid["non_target_candidate_docs"] == 24


def test_duplicate_v33_decision_and_leak_guard_locked():
    payload = _payload()

    assert payload["experiment_summary"]["best_sidecar_candidate"] == (
        "observable_profile_top_500"
    )
    assert payload["decision"]["production_sidecar_adoption"] is False
    assert payload["decision"]["bounded_export_sidecar_candidate"] == (
        "observable_profile_top_500"
    )
    assert (
        payload["decision"]["bounded_export_sidecar_candidate_ready_for_product_default"]
        is False
    )
    assert payload["decision"]["product_first_review_ordering_change"] is True
    assert payload["decision"]["main_candidate_subset_change"] is True
    assert payload["decision"]["weak_pair_promotion"] is False
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
