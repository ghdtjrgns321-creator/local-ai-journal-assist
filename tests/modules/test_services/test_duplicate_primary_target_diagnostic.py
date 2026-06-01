from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_primary_target_fixed5_dupmeta_20260530.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_primary_target_attrition_lock():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_dupmeta"
    assert payload["diagnostic_only"] is True
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True

    assert payload["duplicate_primary_target"] == {
        "primary_doc_count": 76,
        "pair_group_count": 38,
        "pair_group_size_distribution": {"2": 38},
        "scenario_distribution": {"embezzlement_concealment": 76},
        "period_end_primary_doc_count": 0,
    }
    assert payload["stage_attrition"] == {
        "primary_target_docs": 76,
        "row_score_primary_docs": 28,
        "candidate_subset_primary_docs": 0,
        "generated_pair_primary_docs": 0,
        "top_pairs_primary_docs": 0,
        "case_grade_top_pairs_primary_docs": 0,
        "duplicate_case_primary_docs": 0,
    }
    assert payload["reason_distribution"] == {
        "candidate_subset_excluded": 28,
        "no_duplicate_row_score": 48,
    }


def test_duplicate_primary_target_candidate_subset_score_profile_lock():
    payload = _payload()
    profile = payload["row_score_selection_profile"]

    assert profile["all_row_score_hit_count"] == 152043
    assert profile["primary_row_count"] == 152
    assert profile["primary_row_score_hit_row_count"] == 54
    assert profile["primary_row_score_hit_doc_count"] == 28
    assert profile["selected_candidate_min_score"] == 0.5989857631894374
    assert profile["primary_row_score_quantiles"]["max"] == 0.42857142857142855
    assert profile["primary_rule_doc_counts"] == {
        "L2-03a": 0,
        "L2-03b": 0,
        "L2-03c": 0,
        "L2-03d": 28,
    }
    assert profile["primary_rule_row_counts"] == {
        "L2-03a": 0,
        "L2-03b": 0,
        "L2-03c": 0,
        "L2-03d": 54,
    }


def test_duplicate_primary_target_retention_and_case_surface_lock():
    payload = _payload()

    for size in ("500", "2000", "10000", "50000"):
        retention = payload["retention_diagnostic"][size]
        assert retention["primary_doc_count"] == 0
        assert retention["case_grade_primary_doc_count"] == 0
        assert retention["first_primary_pair_rank"] is None
        assert retention["primary_pair_group_coverage"] == {
            "exact_pair_group_count": 0,
            "partial_pair_group_count": 0,
            "case_grade_exact_pair_group_count": 0,
            "weak_exact_pair_group_count": 0,
        }

    assert payload["duplicate_cases"]["case_count"] == 198
    assert payload["duplicate_cases"]["docs_covered"] == 145
    assert payload["duplicate_cases"]["primary_doc_count"] == 0
    assert payload["duplicate_cases"]["case_grade_only"] is True


def test_duplicate_primary_target_raw_identifier_leak_guard():
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
