from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "duplicate_v32_companion_sidecar_burden_20260531.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_duplicate_v32_companion_denominator_and_guardrails():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v32d"
    assert payload["responsibility_map_version"] == "v3.2d"
    assert payload["diagnostic_only"] is True
    assert payload["duplicate_companion_denominator"] == 111
    assert payload["duplicate_primary_denominator"] == 0
    assert payload["production_first_review_ranking_changed"] is False
    assert payload["row_score_threshold_changed"] is False
    assert payload["row_scores_changed"] is False
    assert payload["top_pairs_cap_changed"] is False
    assert payload["weak_pair_gate_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_metadata_used_as_selector"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True


def test_duplicate_v32_broad_profile_burden_locked():
    candidates = _payload()["candidate_results"]
    broad = candidates["observable_profile_top_10000"]
    bounded = candidates["observable_profile_top_2000"]

    assert broad["measurement_basis"] == "candidate_document_coverage_pre_pair_artifact"
    assert broad["candidate_docs"] == 10000
    assert broad["target_candidate_docs"] == 76
    assert broad["non_target_candidate_docs"] == 9924
    assert broad["target_candidate_doc_recall"] == 76 / 111

    assert bounded["candidate_docs"] == 2000
    assert bounded["target_candidate_docs"] == 76
    assert bounded["non_target_candidate_docs"] == 1924
    assert bounded["non_target_to_target_candidate_ratio"] == 25.315789


def test_duplicate_v32_strict_guard_tradeoff_locked():
    payload = _payload()
    strict = payload["candidate_results"]["strict_time_shift_reference_guard"]

    assert strict["guard_case_grade_by_construction"] is True
    assert strict["candidate_docs"] == 2239
    assert strict["target_candidate_docs"] == 28
    assert strict["non_target_candidate_docs"] == 2211
    assert strict["target_candidate_doc_recall"] == 28 / 111
    assert payload["experiment_summary"]["best_guard_candidate"] == (
        "strict_time_shift_reference_guard"
    )
    assert payload["decision"] == {
        "production_sidecar_adoption": False,
        "product_first_review_ordering_change": False,
        "main_candidate_subset_change": False,
        "weak_pair_promotion": False,
        "read": (
            "Observable duplicate-like guards can reduce burden versus the broad "
            "profile sample, but v3.2d duplicate remains a companion evidence lane. "
            "Do not adopt as product default until non-target burden and case-grade "
            "coverage are stable on regenerated DataSynth."
        ),
    }


def test_duplicate_v32_companion_raw_leak_guard():
    assert _payload()["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
