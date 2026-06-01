from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_v31_primary_readiness_contract_lock():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_dupmeta"
    assert payload["diagnostic_only"] is True
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_metadata_used_as_selector"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True

    assert payload["source_artifacts"] == {
        "primary_target": "artifacts/duplicate_primary_target_fixed5_dupmeta_20260530.json",
        "candidate_sidecar": "artifacts/duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json",
    }


def test_duplicate_v31_primary_attrition_and_score_path_lock():
    payload = _payload()

    assert payload["v31_primary_target"] == {
        "primary_candidate_docs": 76,
        "pair_groups": 38,
        "pair_group_size_distribution": {"2": 38},
        "scenario_distribution": {"embezzlement_concealment": 76},
    }
    assert payload["attrition_lock"] == {
        "primary_candidate_docs": 76,
        "row_score_primary_docs": 28,
        "no_row_score_primary_docs": 48,
        "candidate_subset_primary_docs": 0,
        "generated_pair_primary_docs": 0,
        "top_pairs_primary_docs": 0,
        "case_grade_top_pairs_primary_docs": 0,
        "duplicate_case_primary_docs": 0,
    }

    score_path = payload["score_path_lock"]
    assert score_path["all_duplicate_row_score_hits"] == 152043
    assert score_path["primary_row_score_hit_row_count"] == 54
    assert score_path["primary_row_score_hit_doc_count"] == 28
    assert score_path["primary_rule_doc_counts"] == {
        "L2-03a": 0,
        "L2-03b": 0,
        "L2-03c": 0,
        "L2-03d": 28,
    }
    assert score_path["primary_rule_row_counts"] == {
        "L2-03a": 0,
        "L2-03b": 0,
        "L2-03c": 0,
        "L2-03d": 54,
    }
    assert score_path["primary_l2_03d_score"] == 0.42857142857142855
    assert score_path["candidate_subset_min_score"] == 0.5989857631894374
    assert score_path["primary_l2_03d_below_candidate_floor"] is True
    assert score_path["candidate_subset_selected_rows"] == 50000
    assert score_path["candidate_subset_mode"] == "row_score_subset"


def test_duplicate_v31_pair_path_and_next_action_lock():
    payload = _payload()

    assert payload["pair_path_lock"] == {
        "generated_pair_count": 200000,
        "top_pairs_count": 500,
        "generated_primary_doc_count": 0,
        "top_pairs_primary_doc_count": 0,
        "top_pairs_case_grade_primary_doc_count": 0,
        "retention_sizes_checked": [500, 2000, 10000, 50000],
        "top_pairs_cap_is_bottleneck": False,
    }
    assert payload["sidecar_readiness"] == {
        "non_oracle_sidecar_pair_feasibility_confirmed": False,
        "oracle_probe_pair_feasibility_confirmed": True,
        "oracle_probe_primary_docs": 76,
        "oracle_probe_case_grade_primary_docs": 76,
        "oracle_probe_weak_pair_ratio": 0.9775862068965517,
        "l2_03d_stratified_primary_docs": 0,
        "rule_balanced_primary_docs": 0,
        "product_sidecar_adoption_allowed": False,
    }

    decision = payload["decision"]
    assert decision["production_first_review_ordering_change"] is False
    assert decision["row_score_threshold_change"] is False
    assert decision["top_pairs_cap_expansion"] is False
    assert decision["weak_pair_promotion"] is False
    assert decision["truth_metadata_selector"] is False
    assert (
        decision["next_improvement_class"]
        == "row_score_feature_coverage_or_observable_lower_score_pair_path"
    )


def test_duplicate_v31_primary_gap_decomposition_lock():
    payload = _payload()

    gaps = payload["primary_gap_decomposition"]
    no_score = gaps["no_row_score_primary_docs"]
    assert no_score["doc_count"] == 48
    assert no_score["pair_group_count"] == 24
    no_score_profile = no_score["observable_profile"]
    assert no_score_profile["time_shift_bucket_distribution"] == {"1_3d": 48}
    assert no_score_profile["amount_similarity_bucket_distribution"] == {"near": 48}
    assert no_score_profile["reference_similarity_bucket_distribution"] == {"exact": 48}
    assert no_score_profile["text_similarity_bucket_distribution"] == {"medium": 48}
    assert no_score_profile["partner_match_ratio"] == 1.0
    assert no_score_profile["same_account_ratio"] == 0.0
    assert no_score_profile["same_business_process_ratio"] == 1.0
    assert no_score_profile["row_count_bucket_distribution"] == {
        "two_to_three_lines": 48
    }
    assert no_score_profile["line_amount_bucket_distribution"] == {"very_high": 48}
    assert no_score_profile["process_distribution"] == {"P2P": 48}
    assert no_score_profile["phase1_action_tier_distribution"] == {
        "low": 5,
        "medium": 4,
        "none": 39,
    }

    low_score = gaps["low_score_l2_03d_primary_docs"]
    assert low_score["doc_count"] == 28
    assert low_score["pair_group_count"] == 14
    assert low_score["row_score_hit_row_count"] == 54
    assert low_score["score_floor_gap"] == 0.17041433461800887
    assert low_score["primary_to_candidate_floor_ratio"] == 0.7154951835405927
    low_score_profile = low_score["observable_profile"]
    assert low_score_profile["time_shift_bucket_distribution"] == {"1_3d": 28}
    assert low_score_profile["amount_similarity_bucket_distribution"] == {"near": 28}
    assert low_score_profile["reference_similarity_bucket_distribution"] == {"exact": 28}
    assert low_score_profile["text_similarity_bucket_distribution"] == {"medium": 28}
    assert low_score_profile["partner_match_ratio"] == 1.0
    assert low_score_profile["same_account_ratio"] == 0.0
    assert low_score_profile["same_business_process_ratio"] == 1.0
    assert low_score_profile["phase1_action_tier_distribution"] == {
        "low": 13,
        "medium": 15,
    }


def test_duplicate_v31_non_oracle_sidecar_failure_profile_lock():
    payload = _payload()

    profile = payload["non_oracle_sidecar_failure_profile"]
    assert profile["l2_03d_stratified_low_score_sample"] == {
        "sidecar_candidate_docs": 10000,
        "bounded_row_count": 11825,
        "duplicate_primary_docs_entering_sidecar": 0,
        "generated_pair_evidence_primary_docs": 0,
        "case_grade_pair_primary_docs": 0,
        "rule_id_distribution": {"L2-03b": 5000},
        "weak_pair_ratio": 0.7818,
        "case_grade_pair_ratio": 0.2182,
    }
    assert profile["rule_balanced_duplicate_candidate_sample"] == {
        "sidecar_candidate_docs": 10000,
        "bounded_row_count": 11821,
        "duplicate_primary_docs_entering_sidecar": 0,
        "generated_pair_evidence_primary_docs": 0,
        "case_grade_pair_primary_docs": 0,
        "rule_id_distribution": {"L2-03a": 434, "L2-03b": 3910, "L2-03d": 656},
        "weak_pair_ratio": 0.795,
        "case_grade_pair_ratio": 0.205,
    }
    assert profile["oracle_probe_contrast"] == {
        "duplicate_primary_docs_entering_sidecar": 76,
        "generated_pair_evidence_primary_docs": 76,
        "case_grade_pair_primary_docs": 76,
        "weak_pair_ratio": 0.9775862068965517,
        "case_grade_pair_ratio": 0.022413793103448276,
        "same_partner_ratio": 0.022413793103448276,
        "usable_as_product_selector": False,
    }


def test_duplicate_v31_primary_readiness_raw_identifier_leak_guard():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    assert "DOC-" not in text
    assert "TRUTH-" not in text
    assert "p2_duplicate_" not in text
