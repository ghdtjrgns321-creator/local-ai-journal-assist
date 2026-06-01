from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_candidate_sidecar_decision_payload_lock():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_dupmeta"
    assert payload["diagnostic_only"] is True
    assert payload["production_ranking_change_recommended"] is False
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["threshold_change_recommended"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True

    assert payload["primary_target_docs"] == 76
    assert payload["row_score_coverage_docs"] == 28
    assert payload["candidate_subset_coverage_docs"] == 0
    assert payload["bottleneck_stage"] == "candidate_subset_prefilter"
    assert payload["top_pairs_cap_is_bottleneck"] is False
    assert payload["row_score_coverage_gap_docs"] == 48
    assert payload["low_score_cap_gap_docs"] == 28
    assert payload["pair_feasibility_confirmed"] is True
    assert payload["non_oracle_sidecar_pair_feasibility_confirmed"] is False
    assert payload["sidecar_or_export_candidate"] == "oracle_probe_only_not_product_sidecar"


def test_duplicate_candidate_sidecar_group_profiles_lock():
    payload = _payload()
    groups = payload["primary_gap_groups"]

    no_score = groups["no_row_score_primary_docs"]
    assert no_score["doc_count"] == 48
    assert no_score["semantic_group_count"] == 24
    assert no_score["similarity_injection_source_distribution"] == {"mixed": 48}
    assert no_score["time_shift_bucket_distribution"] == {"1_3d": 48}
    assert no_score["amount_similarity_bucket_distribution"] == {"near": 48}
    assert no_score["reference_similarity_bucket_distribution"] == {"exact": 48}
    assert no_score["text_similarity_bucket_distribution"] == {"medium": 48}
    assert no_score["partner_match_ratio"] == 1.0
    assert no_score["same_business_process_ratio"] == 1.0
    assert no_score["phase1_action_tier_distribution"] == {
        "low": 5,
        "medium": 4,
        "none": 39,
    }

    low_score = groups["low_score_l2_03d_primary_docs"]
    assert low_score["doc_count"] == 28
    assert low_score["semantic_group_count"] == 14
    assert low_score["similarity_injection_source_distribution"] == {"mixed": 28}
    assert low_score["time_shift_bucket_distribution"] == {"1_3d": 28}
    assert low_score["amount_similarity_bucket_distribution"] == {"near": 28}
    assert low_score["reference_similarity_bucket_distribution"] == {"exact": 28}
    assert low_score["text_similarity_bucket_distribution"] == {"medium": 28}
    assert low_score["partner_match_ratio"] == 1.0
    assert low_score["phase1_action_tier_distribution"] == {
        "low": 13,
        "medium": 15,
    }


def test_duplicate_candidate_sidecar_sampling_outcomes_lock():
    payload = _payload()
    sidecars = payload["sidecar_sampling_candidate"]

    l2 = sidecars["l2_03d_stratified_low_score_sample"]
    assert l2["does_not_replace_main_candidate_subset"] is True
    assert l2["diagnostic_only"] is True
    assert l2["not_case_grade_by_default"] is True
    assert l2["sidecar_candidate_docs"] == 10000
    assert l2["duplicate_primary_docs_entering_sidecar"] == 0
    assert l2["generated_pair_evidence_primary_docs"] == 0
    assert l2["case_grade_pair_primary_docs"] == 0
    assert l2["weak_pair_ratio"] == 0.7818

    oracle = sidecars["duplicate_primary_metadata_probe_sample"]
    assert oracle["sidecar_candidate_docs"] == 76
    assert oracle["duplicate_primary_docs_entering_sidecar"] == 76
    assert oracle["generated_pair_evidence_primary_docs"] == 76
    assert oracle["case_grade_pair_primary_docs"] == 76
    assert oracle["weak_pair_ratio"] == 0.9775862068965517
    assert oracle["case_grade_pair_ratio"] == 0.022413793103448276
    assert oracle["rule_id_distribution"] == {"L2-03b": 2873, "L2-03d": 27}

    rule_balanced = sidecars["rule_balanced_duplicate_candidate_sample"]
    assert rule_balanced["sidecar_candidate_docs"] == 10000
    assert rule_balanced["duplicate_primary_docs_entering_sidecar"] == 0
    assert rule_balanced["generated_pair_evidence_primary_docs"] == 0
    assert rule_balanced["case_grade_pair_primary_docs"] == 0
    assert rule_balanced["weak_pair_ratio"] == 0.795


def test_duplicate_candidate_sidecar_raw_identifier_leak_guard():
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
