"""Smoke checks for duplicate v3.1 next-improvement diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_v31_improvement_next_fixed5_dupmeta_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_v31_next_improvement_contract() -> None:
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_or_owner_metadata_used_as_selector"] is False


def test_duplicate_v31_blocking_stage_locked() -> None:
    payload = _payload()

    assert payload["blocking_stage"] == {
        "classification": "candidate_generation_before_pair_evidence",
        "not_top_pairs_retention": True,
        "primary_docs": 76,
        "no_row_score_docs": 48,
        "low_score_docs_below_candidate_floor": 28,
        "candidate_subset_primary_docs": 0,
        "generated_pair_primary_docs": 0,
        "duplicate_case_primary_docs": 0,
    }

    no_score = payload["gap_profile"]["no_row_score_primary_docs"]
    assert no_score["share"] == 48 / 76
    assert no_score["observable_profile"]["same_account_ratio"] == 0.0
    assert no_score["observable_profile"]["partner_match_ratio"] == 1.0

    low_score = payload["gap_profile"]["low_score_l2_03d_primary_docs"]
    assert low_score["share"] == 28 / 76
    assert low_score["primary_l2_03d_score"] == 0.42857142857142855
    assert low_score["candidate_subset_min_score"] == 0.5989857631894374


def test_duplicate_v31_next_experiments_and_leak_guard_locked() -> None:
    payload = _payload()

    rejected = payload["rejected_fixes"]
    assert rejected["expand_top_pairs_cap"].startswith("not bottleneck")
    assert rejected["use_duplicate_primary_metadata_selector"].endswith("prohibited")
    assert [item["name"] for item in payload["recommended_experiments"]] == [
        "observable_l2_03d_floor_band_pair_path",
        "same_account_relaxation_diagnostic",
    ]
    assert payload["decision"]["change_product_default_now"] is False
    assert payload["decision"]["next_improvement_class"] == (
        "row_score_feature_coverage_and_observable_lower_score_pair_path"
    )
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
