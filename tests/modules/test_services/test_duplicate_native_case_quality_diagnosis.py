"""Duplicate native case quality diagnosis helper tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from config.settings import AuditSettings
from tools.scripts.diagnose_duplicate_native_case_quality_fixed5_20260529 import (
    _copy_settings_with_top_n,
    case_builder_gate_diagnostic,
    pair_feature_profile,
    raw_identifier_leak_check,
)
from tools.scripts.diagnose_duplicate_phase1_uplift_fixed5_20260529 import (
    _select_phase1_gap_case_grade_pairs,
)
from tools.scripts.diagnose_duplicate_retention_candidates_fixed5_20260529 import (
    _select_case_grade_first,
    _select_case_grade_with_score_floor,
    _select_document_first,
    _select_document_pair_cap_with_fill,
    _select_hybrid_score_diversity_balanced,
    _select_rule_balanced_duplicate_surface,
    _select_tier_then_score_then_diversity,
    _select_two_stage_top100_score_top500_diversity,
)

ROOT = Path(__file__).resolve().parents[3]
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
DIAG_ARTIFACT = ROOT / "artifacts" / "duplicate_native_case_quality_diagnosis_fixed5_20260529.json"
RETENTION_CANDIDATE_ARTIFACT = (
    ROOT / "artifacts" / "duplicate_retention_candidates_fixed5_20260529.json"
)
CROSSBATCH_ARTIFACT = ROOT / "artifacts" / "duplicate_case_order_crossbatch_20260529.json"
PHASE1_UPLIFT_ARTIFACT = ROOT / "artifacts" / "duplicate_phase1_uplift_fixed5_20260529.json"
PHASE1_UPLIFT_CROSSBATCH_ARTIFACT = (
    ROOT / "artifacts" / "duplicate_phase1_uplift_crossbatch_20260530.json"
)
EXPECTED_LEAK_CHECK = {
    "doc_like_token_count": 0,
    "forbidden_identifier_key_count": 0,
    "forbidden_identifier_value_count": 0,
    "phase2_case_id_like_token_count": 0,
}


def _pair(
    *,
    left_doc: str,
    right_doc: str,
    tier: str = "strong",
    rule_id: str = "L2-03a",
) -> dict:
    if tier == "strong":
        features = {
            "same_account": True,
            "same_partner": True,
            "amount_similarity": 1.0,
            "date_distance_days": 0,
            "reference_similarity": 0.95,
            "text_similarity": 0.9,
        }
    elif tier == "moderate":
        features = {
            "same_account": True,
            "same_partner": True,
            "amount_similarity": 0.96,
            "date_distance_days": 1,
            "reference_similarity": 0.75,
            "text_similarity": 0.7,
        }
    else:
        features = {
            "same_account": True,
            "same_partner": False,
            "amount_similarity": 1.0,
            "date_distance_days": 0,
            "reference_similarity": 1.0,
            "text_similarity": 1.0,
        }
    return {
        "rule_id": rule_id,
        "pair_score": 1.0,
        "left_document_id": left_doc,
        "right_document_id": right_doc,
        "features": features,
    }


def test_retention_diagnostic_settings_only_changes_retention_cap():
    settings = AuditSettings(
        duplicate_pair_artifact_top_n=500,
        duplicate_fuzzy_threshold=83,
        duplicate_amount_tolerance=0.03,
    )

    copied = _copy_settings_with_top_n(settings, 2_000)

    assert copied.duplicate_pair_artifact_top_n == 2_000
    assert copied.duplicate_fuzzy_threshold == settings.duplicate_fuzzy_threshold
    assert copied.duplicate_amount_tolerance == settings.duplicate_amount_tolerance
    assert copied.duplicate_time_window_days == settings.duplicate_time_window_days


def test_weak_truth_pair_is_not_counted_as_case_grade():
    truth_docs = {"TRUTH-1"}
    top_pairs = [_pair(left_doc="TRUTH-1", right_doc="TRUTH-2", tier="weak")]

    diagnostic = case_builder_gate_diagnostic(
        top_pairs=top_pairs,
        cases=(),
        truth_docs=truth_docs,
    )

    assert diagnostic["weak_pair_truth_docs"] == 1
    assert diagnostic["case_grade_top_pairs_truth_docs"] == 0
    assert diagnostic["duplicate_case_truth_docs"] == 0


def test_strong_moderate_join_failure_is_recorded_in_diagnostics():
    truth_docs = {"TRUTH-1"}
    join_failed_pair = _pair(left_doc="TRUTH-1", right_doc="TRUTH-2", tier="moderate")

    diagnostic = case_builder_gate_diagnostic(
        top_pairs=[join_failed_pair],
        cases=(),
        truth_docs=truth_docs,
        join_failed_pairs=[join_failed_pair],
    )

    assert diagnostic["case_grade_top_pairs_truth_docs"] == 1
    assert diagnostic["pair_join_failed_truth_docs"] == 1
    assert diagnostic["case_builder_exclusion_reasons"]["pair_join_failed_truth_docs"] == 1


def test_pair_feature_profile_omits_raw_document_ids():
    profile = pair_feature_profile(
        [_pair(left_doc="TRUTH-SECRET-1", right_doc="DOC-SECRET-2", tier="strong")],
        {"TRUTH-SECRET-1"},
    )

    encoded = json.dumps(profile, ensure_ascii=False)

    assert "TRUTH-SECRET-1" not in encoded
    assert "DOC-SECRET-2" not in encoded
    assert profile["truth_doc_count"] == 1
    assert profile["document_diversity"]["unique_document_count"] == 2


def test_phase1_gap_selector_has_no_truth_or_scenario_input():
    signature = inspect.signature(_select_phase1_gap_case_grade_pairs)

    assert "truth_docs" not in signature.parameters
    assert "scenario_by_doc" not in signature.parameters
    assert "labels" not in signature.parameters


def test_phase1_gap_selector_prefers_case_grade_phase1_complement_pairs():
    pairs = [
        _pair(left_doc="P1_TOP", right_doc="P1_TOP_2", tier="strong"),
        _pair(left_doc="P1_LOW", right_doc="P1_LOW_2", tier="moderate"),
        _pair(left_doc="P1_LOW_3", right_doc="P1_LOW_4", tier="weak"),
    ]
    rank_by_doc = {
        "P1_TOP": 1,
        "P1_TOP_2": 2,
        "P1_LOW": 1200,
        "P1_LOW_2": 1300,
        "P1_LOW_3": 1400,
        "P1_LOW_4": 1500,
    }

    selected = _select_phase1_gap_case_grade_pairs(
        pairs=pairs,
        rank_by_doc=rank_by_doc,
        top_n=3,
    )

    assert selected[0]["left_document_id"] == "P1_LOW"
    assert selected[0]["right_document_id"] == "P1_LOW_2"
    assert selected[1]["left_document_id"] == "P1_TOP"


def test_raw_identifier_leak_check_counts_doc_like_tokens():
    payload = {"safe": {"count": 1}, "unsafe": "DOC-SECRET-1", "document_id": "hidden"}

    assert raw_identifier_leak_check(payload) == {
        "doc_like_token_count": 1,
        "forbidden_identifier_key_count": 1,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_fixed5_duplicate_diagnosis_artifact_locks_attrition_and_retention():
    payload = json.loads(DIAG_ARTIFACT.read_text(encoding="utf-8"))

    assert payload["stage_attrition"] == {
        "row_score_truth_docs": 285,
        "candidate_subset_truth_docs": 241,
        "generated_pair_truth_docs": 217,
        "top_pairs_truth_docs": 24,
        "case_grade_top_pairs_truth_docs": 22,
        "duplicate_case_truth_docs": 22,
        "loss_candidate_subset_to_generated_pair": 24,
        "loss_generated_pair_to_top_pairs": 193,
        "loss_top_pairs_to_case_grade": 2,
        "loss_case_grade_to_duplicate_case": 0,
    }
    expected_retention = {
        "500": (24, 22),
        "2000": (76, 41),
        "10000": (105, 60),
        "50000": (217, 94),
    }
    for retention_size, (truth_docs, case_grade_truth_docs) in expected_retention.items():
        row = payload["retention_diagnostic"][retention_size]
        assert row["truth_doc_count"] == truth_docs
        assert row["case_grade_truth_doc_count"] == case_grade_truth_docs


def test_fixed5_duplicate_diagnosis_artifact_has_no_raw_doc_tokens():
    payload_text = DIAG_ARTIFACT.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert "DOC-" not in payload_text
    assert "TRUTH-" not in payload_text
    assert payload["raw_identifier_leak_check"] == EXPECTED_LEAK_CHECK


def test_document_first_retention_prefers_new_document_coverage():
    pairs = [
        _pair(left_doc="DOC-1", right_doc="DOC-2", tier="strong"),
        _pair(left_doc="DOC-1", right_doc="DOC-2", tier="strong"),
        _pair(left_doc="DOC-3", right_doc="DOC-4", tier="weak"),
    ]

    selected = _select_document_first(pairs, 2)

    selected_docs = {
        doc
        for pair in selected
        for doc in (pair["left_document_id"], pair["right_document_id"])
    }
    assert selected_docs == {"DOC-1", "DOC-2", "DOC-3", "DOC-4"}


def test_case_grade_first_retention_does_not_promote_weak_pair():
    weak = _pair(left_doc="DOC-1", right_doc="DOC-2", tier="weak")
    moderate = _pair(left_doc="DOC-3", right_doc="DOC-4", tier="moderate")

    selected = _select_case_grade_first([weak, moderate], 1)

    assert selected == [moderate]


def test_fixed5_duplicate_retention_candidate_artifact_is_aggregate_only():
    payload_text = RETENTION_CANDIDATE_ARTIFACT.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert payload["policy_constraints"] == {
        "thresholds_changed": False,
        "row_scores_changed": False,
        "phase1_priority_or_ranking_changed": False,
        "phase2_family_fusion_changed": False,
        "truth_label_boosting_used": False,
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_default_selector_changed": False,
        "selector_strategy_flag_only": True,
    }
    assert payload["raw_identifier_leak_check"] == EXPECTED_LEAK_CHECK
    assert "DOC-" not in payload_text
    assert "TRUTH-" not in payload_text
    assert "p2_duplicate_" not in payload_text
    truth_text = TRUTH_CSV.read_text(encoding="utf-8")
    for doc_id in {line.split(",", 1)[0].strip() for line in truth_text.splitlines()[1:] if line}:
        assert doc_id not in payload_text


def test_fixed5_duplicate_retention_candidates_lock_key_diagnostic_counts():
    payload = json.loads(RETENTION_CANDIDATE_ARTIFACT.read_text(encoding="utf-8"))
    candidates = payload["candidate_results"]

    expected = {
        "current_document_diversity_top_500": {
            "duplicate_case_count_expected": 198,
            "truth_doc_count": 24,
            "case_truth_doc_count": 22,
            "weak_pair_ratio": 0.604,
        },
        "document_first_top_500": {
            "duplicate_case_count_expected": 176,
            "truth_doc_count": 74,
            "case_truth_doc_count": 30,
            "weak_pair_ratio": 0.648,
        },
        "case_grade_first_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 24,
            "case_truth_doc_count": 24,
            "weak_pair_ratio": 0.0,
        },
        "pair_diversity_score_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 36,
            "case_truth_doc_count": 36,
            "weak_pair_ratio": 0.0,
        },
        "evidence_diversity_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 36,
            "case_truth_doc_count": 36,
            "weak_pair_ratio": 0.0,
        },
        "evidence_diversity_top_1000": {
            "duplicate_case_count_expected": 1000,
            "truth_doc_count": 46,
            "case_truth_doc_count": 46,
            "weak_pair_ratio": 0.0,
        },
        "evidence_diversity_top_2000": {
            "duplicate_case_count_expected": 2000,
            "truth_doc_count": 46,
            "case_truth_doc_count": 46,
            "weak_pair_ratio": 0.0,
        },
        "evidence_diversity_top_5000": {
            "duplicate_case_count_expected": 5000,
            "truth_doc_count": 46,
            "case_truth_doc_count": 46,
            "weak_pair_ratio": 0.0,
        },
        "tier_then_score_then_diversity_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 3,
            "case_truth_doc_count": 3,
            "weak_pair_ratio": 0.0,
        },
        "two_stage_top100_score_top500_diversity": {
            "duplicate_case_count_expected": 455,
            "truth_doc_count": 28,
            "case_truth_doc_count": 28,
            "weak_pair_ratio": 0.09,
        },
        "hybrid_score_diversity_balanced_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 34,
            "case_truth_doc_count": 34,
            "weak_pair_ratio": 0.0,
        },
        "case_grade_with_score_floor_top_500": {
            "duplicate_case_count_expected": 500,
            "truth_doc_count": 24,
            "case_truth_doc_count": 24,
            "weak_pair_ratio": 0.0,
        },
        "document_pair_cap_with_fill_top_500": {
            "duplicate_case_count_expected": 198,
            "truth_doc_count": 24,
            "case_truth_doc_count": 22,
            "weak_pair_ratio": 0.604,
        },
        "rule_balanced_duplicate_surface_top_500": {
            "duplicate_case_count_expected": 169,
            "truth_doc_count": 24,
            "case_truth_doc_count": 22,
            "weak_pair_ratio": 0.662,
        },
    }
    for candidate_name, expected_values in expected.items():
        row = candidates[candidate_name]
        assert row["duplicate_case_count_expected"] == expected_values[
            "duplicate_case_count_expected"
        ]
        assert row["truth_doc_count"] == expected_values["truth_doc_count"]
        assert row["case_measurement"]["truth_doc_count"] == expected_values[
            "case_truth_doc_count"
        ]
        assert round(float(row["weak_pair_ratio"]), 3) == expected_values["weak_pair_ratio"]


def test_fixed5_duplicate_retention_candidate_provenance_and_topn_lock():
    payload = json.loads(RETENTION_CANDIDATE_ARTIFACT.read_text(encoding="utf-8"))
    candidates = payload["candidate_results"]
    row = candidates["evidence_diversity_top_500"]

    assert row["candidate_weight_provenance"] == {
        "weight_source": "fixed exploratory diagnostic weights",
        "calibrated_on_fixed5_truth": False,
        "production_ranking_policy": False,
        "requires_cross_batch_fixture_validation_before_adoption": True,
    }
    assert row["candidate_policy_constraints"] == {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_default_selector_changed": False,
        "selector_strategy_flag_only": True,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "threshold_changed": False,
        "row_scores_changed": False,
    }
    assert row["case_measurement"]["topn"]["100"]["truth_doc_count"] == 14
    assert row["case_measurement"]["topn"]["500"]["truth_doc_count"] == 36
    assert row["case_measurement"]["first_truth_case_rank"] == 11


def test_fixed5_duplicate_case_order_candidates_lock_key_counts():
    payload = json.loads(RETENTION_CANDIDATE_ARTIFACT.read_text(encoding="utf-8"))
    candidates = payload["case_order_candidate_results"]

    anchor = candidates["current_top100_case_anchor_plus_diversity_fill"]
    assert anchor["duplicate_case_count_expected"] == 682
    assert anchor["case_measurement"]["topn"]["100"]["truth_doc_count"] == 21
    assert anchor["case_measurement"]["topn"]["500"]["truth_doc_count"] == 41
    assert anchor["case_measurement"]["truth_doc_count"] == 48
    assert anchor["review_burden_vs_current_top500"]["case_count_delta"] == 484

    split = candidates["review_surface_split_ui100_export500"]
    assert split["ui_top100_truth_doc_count"] == 21
    assert split["export_top500_truth_doc_count"] == 36
    assert split["duplicate_case_count_expected"] == 500
    assert split["candidate_policy_constraints"]["production_default_selector_changed"] is False


def test_duplicate_retention_selectors_do_not_accept_truth_inputs():
    selectors = [
        _select_document_first,
        _select_case_grade_first,
        _select_tier_then_score_then_diversity,
        _select_two_stage_top100_score_top500_diversity,
        _select_hybrid_score_diversity_balanced,
        _select_case_grade_with_score_floor,
        _select_document_pair_cap_with_fill,
        _select_rule_balanced_duplicate_surface,
    ]
    for selector in selectors:
        params = set(inspect.signature(selector).parameters)
        assert params == {"pairs", "top_n"}


def test_duplicate_case_order_crossbatch_artifact_locks_direction_and_leak_guard():
    payload_text = CROSSBATCH_ARTIFACT.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert payload["raw_identifier_leak_check"] == EXPECTED_LEAK_CHECK
    assert payload["current_iteration_candidate"] == {
        "name": "grouped_summary_primary_with_full_manifest",
        "status": "diagnostic_contract_candidate",
        "reason": (
            "Keeps the split UI/export surface, preserves export aggregate coverage, "
            "and reduces first-level export review units from case-level rows to "
            "rule/tier/similarity groups."
        ),
        "production_default_selector_changed": False,
        "production_case_order_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "requires_followup": (
            "Define bounded representative drilldown semantics as partial sample, not full "
            "coverage, before any product adoption proposal."
        ),
    }
    assert "DOC-" not in payload_text
    assert "TRUTH-" not in payload_text
    assert "p2_duplicate_" not in payload_text

    fixed4 = payload["batches"]["fixed4"]["case_order_surfaces"]
    assert fixed4["current_default"]["top100_truth_doc_count"] == 56
    assert fixed4["current_default"]["top500_truth_doc_count"] == 81
    assert fixed4["evidence_diversity_default"]["top500_truth_doc_count"] == 100
    assert fixed4["current_top100_anchor_plus_diversity_fill"]["top500_truth_doc_count"] == 101
    assert fixed4["split_ui100_current_export500_evidence"]["ui_top100_truth_doc_count"] == 56

    fixed5 = payload["batches"]["fixed5_normalcal5"]["case_order_surfaces"]
    assert fixed5["current_default"]["top100_truth_doc_count"] == 21
    assert fixed5["current_default"]["top500_truth_doc_count"] == 22
    assert fixed5["evidence_diversity_default"]["top500_truth_doc_count"] == 36
    assert fixed5["current_top100_anchor_plus_diversity_fill"]["top500_truth_doc_count"] == 45
    assert fixed5["split_ui100_current_export500_evidence"]["ui_top100_truth_doc_count"] == 21

    fixed4_contract = payload["batches"]["fixed4"]["sidecar_contract_candidate"]
    assert fixed4_contract["schema_version"] == 1
    assert fixed4_contract["contract_status"] == "diagnostic_candidate"
    assert fixed4_contract["production_default_selector_changed"] is False
    assert fixed4_contract["ui_review_surface"]["review_cap"] == 100
    assert fixed4_contract["ui_review_surface"]["profile"]["case_grade_only"] is True
    assert fixed4_contract["export_sidecar_surface"]["review_cap"] == 500
    assert fixed4_contract["export_sidecar_surface"]["profile"]["case_grade_only"] is True
    assert fixed4_contract["export_sidecar_surface"]["connected_to_phase2_family_fusion"] is False

    fixed5_contract = payload["batches"]["fixed5_normalcal5"]["sidecar_contract_candidate"]
    assert fixed5_contract["ui_review_surface"]["top100_truth_doc_count"] == 21
    assert fixed5_contract["export_sidecar_surface"]["top500_truth_doc_count"] == 36
    assert fixed5_contract["review_burden_delta_vs_current"] == {
        "case_count_delta": 302,
        "nontruth_docs_delta": 841,
    }
    assert fixed5_contract["raw_identifier_policy"] == {
        "raw_document_ids_stored": False,
        "raw_row_ids_stored": False,
        "raw_index_labels_stored": False,
        "phase2_case_ids_stored": False,
    }

    fixed4_summary = payload["batches"]["fixed4"]["export_summary_group_candidate_results"]
    assert fixed4_summary["rule_tier_grouped_summary"]["summary_group_count"] == 4
    assert fixed4_summary["rule_tier_grouped_summary"]["underlying_pair_count"] == 500
    assert fixed4_summary["rule_tier_grouped_summary"]["truth_doc_count"] == 100
    assert fixed4_summary["rule_tier_grouped_summary"]["case_grade_only"] is True
    assert fixed4_summary["rule_tier_similarity_bucket_summary"]["summary_group_count"] == 5
    assert fixed4_summary["rule_tier_similarity_bucket_summary"][
        "bounded_representative_drilldown"
    ]["top20_per_group"] == {
        "representative_pair_count": 81,
        "docs_covered": 156,
        "truth_doc_count": 70,
        "nontruth_docs_covered": 86,
        "case_grade_only": True,
    }
    assert fixed4_summary["rule_tier_similarity_bucket_summary"][
        "summary_first_high_volume_contract"
    ] == {
        "schema_version": 1,
        "contract_status": "diagnostic_candidate",
        "policy": "summary_first_for_high_volume_groups",
        "high_volume_threshold": 100,
        "summary_group_count": 5,
        "summary_only_group_count": 1,
        "full_drilldown_group_count": 4,
        "underlying_pair_count": 500,
        "summary_truth_doc_count": 100,
        "summary_nontruth_docs_covered": 894,
        "full_drilldown_pair_count": 122,
        "full_drilldown_truth_doc_count": 98,
        "full_drilldown_nontruth_docs_covered": 140,
        "case_grade_only": True,
        "raw_identifier_policy": {
            "raw_document_ids_stored": False,
            "raw_pair_ids_stored": False,
            "phase2_case_ids_stored": False,
        },
        "policy_constraints": {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_default_selector_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "threshold_changed": False,
            "row_scores_changed": False,
        },
    }

    fixed5_summary = payload["batches"]["fixed5_normalcal5"][
        "export_summary_group_candidate_results"
    ]
    assert fixed5_summary["rule_tier_grouped_summary"]["summary_group_count"] == 4
    assert fixed5_summary["rule_tier_grouped_summary"]["underlying_pair_count"] == 500
    assert fixed5_summary["rule_tier_grouped_summary"]["truth_doc_count"] == 36
    assert fixed5_summary["rule_tier_similarity_bucket_summary"]["summary_group_count"] == 4
    assert fixed5_summary["rule_tier_grouped_summary"]["raw_identifier_policy"] == {
        "raw_document_ids_stored": False,
        "raw_pair_ids_stored": False,
        "phase2_case_ids_stored": False,
    }
    assert fixed5_summary["rule_tier_similarity_bucket_summary"][
        "bounded_representative_drilldown"
    ]["top20_per_group"] == {
        "representative_pair_count": 53,
        "docs_covered": 106,
        "truth_doc_count": 2,
        "nontruth_docs_covered": 104,
        "case_grade_only": True,
    }
    assert fixed5_summary["rule_tier_similarity_bucket_summary"][
        "summary_first_high_volume_contract"
    ]["full_drilldown_pair_count"] == 13
    assert fixed5_summary["rule_tier_similarity_bucket_summary"][
        "summary_first_high_volume_contract"
    ]["summary_truth_doc_count"] == 36
    assert fixed5_summary["rule_tier_similarity_bucket_summary"][
        "summary_first_high_volume_contract"
    ]["full_drilldown_truth_doc_count"] == 0


def test_fixed5_duplicate_phase1_uplift_diagnostic_is_stable():
    payload_text = PHASE1_UPLIFT_ARTIFACT.read_text(encoding="utf-8")
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

    phase1 = payload["phase1_reference"]
    assert phase1["truth_doc_count"] == 620
    assert phase1["truth_docs_in_phase1_top100"] == 246
    assert phase1["truth_docs_in_phase1_top500"] == 330
    assert phase1["truth_docs_in_phase1_top1000"] == 382
    assert phase1["truth_phase1_bucket_distribution"] == {
        "phase1_top100": 246,
        "phase1_101_500": 84,
        "phase1_501_1000": 52,
        "phase1_1001_plus": 162,
        "phase1_not_in_cases": 76,
    }

    current = payload["case_surfaces"]["current_document_diversity_top_500"]
    assert current["top100"]["truth_doc_count"] == 22
    assert current["top100"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top100"
    ] == 19
    assert current["top100"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top500"
    ] == 5

    evidence = payload["case_surfaces"]["evidence_diversity_top_500"]
    assert evidence["top500"]["truth_doc_count"] == 36
    assert evidence["top500"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top100"
    ] == 8
    assert evidence["top500"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top500"
    ] == 3

    phase1_gap = payload["case_surfaces"]["phase1_gap_case_grade_top_500"]
    assert phase1_gap["top500"]["truth_doc_count"] == 2
    assert phase1_gap["top500"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top100"
    ] == 2
    assert phase1_gap["top500"]["incremental_vs_phase1"][
        "all_docs_outside_phase1_top100"
    ] == 1000

    anchor = payload["case_surfaces"]["current_top100_anchor_plus_diversity_fill"]
    assert anchor["top100"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top100"
    ] == 19
    assert anchor["top500"]["truth_doc_count"] == 42
    assert anchor["top500"]["incremental_vs_phase1"][
        "truth_docs_outside_phase1_top100"
    ] == 19


def test_duplicate_phase1_uplift_crossbatch_diagnostic_is_stable():
    payload_text = PHASE1_UPLIFT_CROSSBATCH_ARTIFACT.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert payload["raw_identifier_leak_check"] == EXPECTED_LEAK_CHECK
    assert "DOC-" not in payload_text
    assert "TRUTH-" not in payload_text
    assert "p2_duplicate_" not in payload_text
    assert payload["policy_constraints"]["production_default_selector_changed"] is False
    assert payload["policy_constraints"]["phase1_ranking_changed"] is False
    assert payload["policy_constraints"]["phase2_fusion_changed"] is False

    fixed4 = payload["batches"]["fixed4"]
    assert fixed4["phase1_reference"]["truth_docs_in_phase1_top100"] == 85
    assert fixed4["case_surfaces"]["current_document_diversity_top_500"]["top100"][
        "incremental_vs_phase1"
    ]["truth_docs_outside_phase1_top100"] == 56
    assert fixed4["case_surfaces"]["evidence_diversity_top_500"]["top500"][
        "incremental_vs_phase1"
    ]["truth_docs_outside_phase1_top100"] == 90
    assert fixed4["case_surfaces"]["phase1_gap_case_grade_top_500"]["top500"][
        "truth_doc_count"
    ] == 88
    assert fixed4["pair_surfaces"]["phase1_gap_case_grade_top_500"][
        "case_grade_pair_ratio"
    ] == 1.0

    fixed5 = payload["batches"]["fixed5_normalcal5"]
    assert fixed5["phase1_reference"]["truth_docs_in_phase1_top100"] == 246
    assert fixed5["case_surfaces"]["current_document_diversity_top_500"]["top100"][
        "incremental_vs_phase1"
    ]["truth_docs_outside_phase1_top100"] == 19
    assert fixed5["case_surfaces"]["evidence_diversity_top_500"]["top500"][
        "incremental_vs_phase1"
    ]["truth_docs_outside_phase1_top100"] == 8
    assert fixed5["case_surfaces"]["phase1_gap_case_grade_top_500"]["top500"][
        "truth_doc_count"
    ] == 2
    assert fixed5["pair_surfaces"]["phase1_gap_case_grade_top_500"][
        "case_grade_pair_ratio"
    ] == 1.0

    assert fixed4["directional_checks"] == {
        "current_top100_has_phase1_top100_complement_value": True,
        "evidence_top500_improves_total_truth": True,
        "evidence_top500_reduces_phase1_top100_complement_vs_current_top100": False,
        "anchor_top500_preserves_current_phase1_top100_complement": True,
    }
    assert fixed5["directional_checks"] == {
        "current_top100_has_phase1_top100_complement_value": True,
        "evidence_top500_improves_total_truth": True,
        "evidence_top500_reduces_phase1_top100_complement_vs_current_top100": True,
        "anchor_top500_preserves_current_phase1_top100_complement": True,
    }
