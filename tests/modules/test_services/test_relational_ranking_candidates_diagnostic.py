"""Smoke checks for relational ranking candidate diagnostics.

The diagnostic artifact compares review-surface ordering candidates only. It
must not change production case counts, PHASE1 ranking, or PHASE2 family fusion,
and it must not emit raw document/row/edge identifiers.
"""

from __future__ import annotations

import csv
import inspect
import json
import re
from pathlib import Path

from tools.scripts import diagnose_relational_ranking_candidates_fixed5_20260529 as diag

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "relational_ranking_candidates_fixed5_20260529.json"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _candidate(payload: dict, name: str) -> dict:
    return payload["candidate_rankings"][name]


def test_relational_ranking_candidates_record_non_scope_and_case_count():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    assert payload["case_count"] == 57640
    assert payload["artifact_edge_count"] == 58046
    assert payload["sub_rule_case_counts"] == {
        "R01": 646,
        "R02": 5,
        "R03": 278,
        "R05": 44404,
        "R06": 11874,
        "R07": 433,
    }
    assert "No PHASE1 priority_score/composite_sort_score/ranking change." in payload[
        "non_scope"
    ]
    assert "No PHASE2 family fusion change." in payload["non_scope"]
    assert payload["privacy_contract"] == (
        "Aggregate-only counts, quantiles, and shares are emitted."
    )
    assert payload["truth_label_use_contract"] == {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_ranking_changed": False,
        "threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "relational_case_gate_changed": False,
    }
    policy = payload["adopted_relational_product_policy"]
    assert policy["relational_review_surface_policy"] == (
        "structural_moderate_audit_then_business_lane_split_v1"
    )
    assert policy["relational_review_surface_name"] == (
        "structural_moderate_audit_then_business_lane_split_surface"
    )
    assert policy["primary_product_role"] == "relationship_evidence_review_surface"
    assert policy["role_scope"] == "relationship_review_surface_primary_pending"
    assert policy["primary_denominator_status"] == (
        "pending_relationship_primary_metadata"
    )
    assert policy["primary_target_recall_applicable"] is False
    assert policy["primary_recall_tuning_allowed"] is False
    assert policy["primary_metadata_backlog"] == [
        "injected_relationship_edge_primary",
        "relationship_edge_semantic_group",
    ]
    assert policy["structural_lane_sub_rules"] == ["R03", "R07"]
    assert policy["moderate_audit_business_lane_sub_rules"] == ["R01", "R02"]
    assert policy["context_lane_sub_rules"] == ["R05", "R06"]
    assert policy["interleave_ratio"] == "1:1"
    assert policy["r05_r06_primary_surface_default"] is False
    assert policy["fixed5_ratio_tuning_allowed"] is False
    assert policy["diagnostic_upper_bound_not_adopted"] == (
        "structural_anchor_moderate_1_to_4_surface"
    )


def test_relational_ranking_candidates_include_r05_r06_volume_decomposition():
    payload = _payload()
    volume = payload["volume_decomposition"]

    assert set(volume) == {"R05", "R06"}
    assert volume["R05"]["case_count"] == 44404
    assert volume["R06"]["case_count"] == 11874
    for rule in ("R05", "R06"):
        assert volume[rule]["rows_per_edge_distribution"]["count"] == volume[rule][
            "case_count"
        ]
        assert volume[rule]["documents_per_edge_distribution"]["count"] == volume[rule][
            "case_count"
        ]
        assert volume[rule]["metric_value_quantiles"]["count"] == volume[rule]["case_count"]
        assert volume[rule]["edge_concentration"]["edge_count"] == volume[rule][
            "case_count"
        ]
        assert 0 <= volume[rule]["top_subject_share"] <= 1
        assert 0 <= volume[rule]["top_account_share"] <= 1
        assert volume[rule]["family_ecdf_distribution"]["count"] == volume[rule][
            "case_count"
        ]
        proxy = volume[rule]["high_volume_nontruth_edge_dominance"]
        assert 0 <= proxy["high_volume_nontruth_share"] <= 1


def test_relational_ranking_candidates_compare_expected_top_surfaces():
    payload = _payload()
    candidates = payload["candidate_rankings"]
    expected = {
        "current",
        "edge_support_penalty",
        "document_diversity_penalty",
        "rare_edge_balanced_sampling_per_sub_rule",
        "r03_r07_priority_first_surface",
        "r05_r06_volume_capped_by_edge_support",
        "moderate_tail_only_surface_q95",
        "moderate_tail_only_surface_q99",
        "moderate_tail_low_burden_surface",
        "moderate_tail_business_balanced_surface",
        "moderate_tail_audit_context_balanced_surface",
        "moderate_tail_audit_then_business_balanced_surface",
        "moderate_tail_capped_context_surface",
        "sub_rule_balanced_review_surface",
        "edge_novelty_with_tier_guard",
        "account_partner_context_surface",
        "r03_r07_structural_only_surface",
        "r01_r02_moderate_tail_surface",
        "r05_r06_context_lane_surface",
        "structural_moderate_tail_lane_split_surface",
        "structural_moderate_low_burden_lane_split_surface",
        "structural_moderate_business_balanced_lane_split_surface",
        "structural_moderate_audit_context_balanced_lane_split_surface",
        "structural_moderate_audit_then_business_lane_split_surface",
        "structural_moderate_capped_context_lane_split_surface",
        "structural_anchor_moderate_1_to_2_surface",
        "structural_anchor_moderate_1_to_3_surface",
        "structural_anchor_moderate_1_to_4_surface",
        "three_lane_structural_moderate_context_surface",
    }
    assert expected == set(candidates)

    for name, candidate in candidates.items():
        if name in {
            "r03_r07_structural_only_surface",
            "r01_r02_moderate_tail_surface",
            "r05_r06_context_lane_surface",
        }:
            assert candidate["case_count_in_candidate_surface"] <= payload["case_count"], name
        else:
            assert candidate["case_count_in_candidate_surface"] == payload["case_count"], name
        assert candidate["candidate_weight_provenance"] == {
            "source": "fixed5 exploratory diagnostic weights",
            "calibrated": False,
            "production_ranking_policy": False,
            "requires_cross_batch_fixture_validation_before_adoption": True,
        }
        assert candidate["no_fitting_contract"] == {
            "truth_label_used_for_scoring": False,
            "truth_label_used_only_for_aggregate_evaluation": True,
            "production_ranking_changed": False,
            "threshold_changed": False,
            "phase1_ranking_changed": False,
            "phase2_fusion_changed": False,
            "relational_case_gate_changed": False,
        }
        for top_n in ("100", "500", "1000", "10000"):
            topn = candidate["topn"][top_n]
            assert 0 <= topn["matched"] <= 620
            assert topn["sub_rule_distribution"]
            assert topn["edge_concentration"]["max_cases_per_edge"] >= 1
            assert 0 <= topn["false_positive_pressure_proxy"][
                "high_volume_nontruth_share"
            ] <= 1
            incremental = candidate["incremental_coverage"][top_n]
            assert incremental["matched_truth_docs"] == topn["matched"]
            assert (
                incremental["phase1_overlap_truth_docs"]
                + incremental["phase1_missed_truth_docs"]
                == incremental["matched_truth_docs"]
            )
            assert (
                incremental["phase1_missed_truth_docs"]
                <= incremental["matched_truth_docs"]
            )
            assert 0 <= incremental["overlap_ratio"] <= 1
            assert 0 <= incremental["incremental_ratio"] <= 1
            assert "sub_rule_incremental_breakdown" in incremental
            assert "scenario_incremental_counts" in incremental
        uplift = candidate["phase1_topn_uplift"]
        for suffix in ("100", "500", "1000"):
            assert f"phase2_top{suffix}_truth_not_in_phase1_top{suffix}" in uplift
            assert f"net_truth_uplift_vs_phase1_top{suffix}" in uplift
        evidence = candidate["relational_evidence_incremental"]["500"]
        assert "relational_evidence_added_truth_docs" in evidence
        assert "relational_evidence_added_case_count" in evidence
        assert "structural_evidence_added_truth_docs" in evidence
        assert "moderate_tail_evidence_added_truth_docs" in evidence
        assert "r05_r06_context_evidence_added_truth_docs" in evidence
        assert "scenario_explanation_gap" in evidence


def test_relational_ranking_candidates_lock_candidate_matched_counts_first_rank_and_sub_rules():
    payload = _payload()

    current = _candidate(payload, "current")
    assert current["topn"]["100"]["matched"] == 5
    assert current["topn"]["500"]["matched"] == 19
    assert current["topn"]["1000"]["matched"] == 19
    assert current["topn"]["10000"]["matched"] == 35
    assert current["first_truth_rank"] == 51
    assert current["topn"]["500"]["sub_rule_distribution"] == {
        "R03": 211,
        "R05": 45,
        "R06": 160,
        "R07": 84,
    }

    edge_support = _candidate(payload, "edge_support_penalty")
    assert edge_support["topn"]["100"]["matched"] == 0
    assert edge_support["topn"]["500"]["matched"] == 0
    assert edge_support["topn"]["1000"]["matched"] == 1
    assert edge_support["topn"]["500"]["false_positive_pressure_proxy"][
        "high_volume_nontruth_share"
    ] == 1.0

    document_diversity = _candidate(payload, "document_diversity_penalty")
    assert document_diversity["topn"]["100"]["matched"] == 4
    assert document_diversity["topn"]["500"]["matched"] == 8
    assert document_diversity["topn"]["1000"]["matched"] == 9

    balanced = _candidate(payload, "rare_edge_balanced_sampling_per_sub_rule")
    assert balanced["topn"]["100"]["matched"] == 6
    assert balanced["topn"]["500"]["matched"] == 27
    assert balanced["topn"]["1000"]["matched"] == 57
    assert balanced["topn"]["10000"]["matched"] == 179
    assert balanced["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 99,
        "R02": 5,
        "R03": 99,
        "R05": 99,
        "R06": 99,
        "R07": 99,
    }

    priority_first = _candidate(payload, "r03_r07_priority_first_surface")
    assert priority_first["topn"]["100"]["matched"] == 5
    assert priority_first["topn"]["500"]["matched"] == 33
    assert priority_first["topn"]["1000"]["matched"] == 35
    assert priority_first["topn"]["10000"]["matched"] == 50
    assert priority_first["topn"]["500"]["sub_rule_distribution"] == {
        "R03": 249,
        "R07": 251,
    }

    moderate_q95 = _candidate(payload, "moderate_tail_only_surface_q95")
    assert moderate_q95["first_truth_rank"] == 2
    assert moderate_q95["topn"]["100"]["matched"] == 8
    assert moderate_q95["topn"]["500"]["matched"] == 98
    assert moderate_q95["topn"]["1000"]["matched"] == 143
    assert moderate_q95["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 496,
        "R02": 4,
    }

    moderate_q99 = _candidate(payload, "moderate_tail_only_surface_q99")
    assert moderate_q99["topn"]["500"]["matched"] == 98

    balanced_review = _candidate(payload, "sub_rule_balanced_review_surface")
    assert balanced_review["topn"]["100"]["matched"] == 3
    assert balanced_review["topn"]["500"]["matched"] == 19
    assert balanced_review["topn"]["1000"]["matched"] == 36

    account_partner = _candidate(payload, "account_partner_context_surface")
    assert account_partner["first_truth_rank"] == 16
    assert account_partner["topn"]["500"]["matched"] == 12

    lane_split = _candidate(payload, "structural_moderate_tail_lane_split_surface")
    assert lane_split["first_truth_rank"] == 4
    assert lane_split["topn"]["100"]["matched"] == 7
    assert lane_split["topn"]["500"]["matched"] == 41
    assert lane_split["topn"]["1000"]["matched"] == 131
    assert lane_split["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 249,
        "R02": 1,
        "R03": 181,
        "R07": 69,
    }

    three_lane = _candidate(payload, "three_lane_structural_moderate_context_surface")
    assert three_lane["first_truth_rank"] == 4
    assert three_lane["topn"]["100"]["matched"] == 6
    assert three_lane["topn"]["500"]["matched"] == 38
    assert three_lane["topn"]["1000"]["matched"] == 65
    assert three_lane["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 199,
        "R02": 1,
        "R03": 147,
        "R06": 100,
        "R07": 53,
    }

    moderate_business = _candidate(payload, "moderate_tail_business_balanced_surface")
    assert moderate_business["first_truth_rank"] == 5
    assert moderate_business["topn"]["100"]["matched"] == 27
    assert moderate_business["topn"]["500"]["matched"] == 108
    assert moderate_business["topn"]["1000"]["matched"] == 143

    structural_business = _candidate(
        payload,
        "structural_moderate_business_balanced_lane_split_surface",
    )
    assert structural_business["first_truth_rank"] == 10
    assert structural_business["topn"]["100"]["matched"] == 12
    assert structural_business["topn"]["500"]["matched"] == 92
    assert structural_business["topn"]["1000"]["matched"] == 141
    assert structural_business["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 247,
        "R02": 3,
        "R03": 181,
        "R07": 69,
    }

    structural_hybrid = _candidate(
        payload,
        "structural_moderate_audit_then_business_lane_split_surface",
    )
    assert structural_hybrid["first_truth_rank"] == 2
    assert structural_hybrid["topn"]["100"]["matched"] == 51
    assert structural_hybrid["topn"]["500"]["matched"] == 92
    assert structural_hybrid["topn"]["1000"]["matched"] == 141
    assert structural_hybrid["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 245,
        "R02": 5,
        "R03": 181,
        "R07": 69,
    }

    structural_capped = _candidate(
        payload,
        "structural_moderate_capped_context_lane_split_surface",
    )
    assert structural_capped["first_truth_rank"] == 2
    assert structural_capped["topn"]["100"]["matched"] == 51
    assert structural_capped["topn"]["500"]["matched"] == 92
    assert structural_capped["topn"]["1000"]["matched"] == 141

    structural_anchor = _candidate(payload, "structural_anchor_moderate_1_to_4_surface")
    assert structural_anchor["first_truth_rank"] == 2
    assert structural_anchor["topn"]["100"]["matched"] == 59
    assert structural_anchor["topn"]["500"]["matched"] == 100
    assert structural_anchor["topn"]["1000"]["matched"] == 141
    assert structural_anchor["topn"]["500"]["sub_rule_distribution"] == {
        "R01": 395,
        "R02": 5,
        "R03": 72,
        "R07": 28,
    }

    structural_only = _candidate(payload, "r03_r07_structural_only_surface")
    assert structural_only["case_count_in_candidate_surface"] == 711
    assert structural_only["topn"]["500"]["matched"] == 33

    moderate_tail = _candidate(payload, "r01_r02_moderate_tail_surface")
    assert moderate_tail["case_count_in_candidate_surface"] == 651
    assert moderate_tail["topn"]["500"]["matched"] == 98

    context_lane = _candidate(payload, "r05_r06_context_lane_surface")
    assert context_lane["case_count_in_candidate_surface"] == 56278
    assert context_lane["topn"]["500"]["matched"] == 2


def test_relational_ranking_candidates_include_incremental_phase1_coverage_decision():
    payload = _payload()

    assert payload["incremental_value_definition"]["phase1_all_document_inclusion"].startswith(
        "Broad review-universe inclusion"
    )
    assert payload["phase1_baseline"]["truth_document_count"] == 620
    assert payload["phase1_baseline"]["phase1_all_document_inclusion"] == {
        "truth_document_coverage": 620,
        "truth_document_total": 620,
        "coverage_ratio": 1.0,
        "interpretation": (
            "Broad PHASE1 review universe inclusion only; this does not prove "
            "relational evidence or scenario explanation coverage."
        ),
    }
    assert payload["phase1_baseline"]["topn"]["100"]["truth_document_count"] == 3
    assert payload["phase1_baseline"]["topn"]["500"]["truth_document_count"] == 15
    assert payload["phase1_baseline"]["topn"]["1000"]["truth_document_count"] == 41
    assert payload["incremental_decision"] == {
        "document_inclusion_incremental_value": "broad_inclusion_only_not_decision_basis",
        "topn_uplift_value": "high",
        "evidence_incremental_value": "high",
        "explanation_incremental_value": "high",
        "primary_product_role": "relationship_evidence_review_surface",
        "product_role": "relationship_evidence_review_surface",
        "role_scope": "relationship_review_surface_primary_pending",
        "primary_denominator_status": "pending_relationship_primary_metadata",
        "primary_target_recall_applicable": False,
        "primary_recall_pending_reason": (
            "relationship-primary denominator is unavailable in fixed5 v3.2d; "
            "audit_then_business remains the product review surface until "
            "relationship-primary/co-primary metadata is regenerated"
        ),
        "recommended_default_surface_if_datasynth_incomplete": (
            "structural_moderate_audit_then_business_lane_split_surface"
        ),
        "adopted_default_allowed": True,
        "reason": (
            "audit_then_business is evaluated as PHASE1 TOP-N uplift plus structural "
            "evidence/explanation incremental, not as broad PHASE1 document-inclusion "
            "blind-spot recovery. TOP100 uplift=48, TOP500 uplift=77, TOP500 "
            "relational evidence truth docs=92, structural=16, moderate_tail=76. "
            "1:4 anchor remains diagnostic upper-bound only."
        ),
    }

    candidate = _candidate(
        payload,
        "structural_moderate_audit_then_business_lane_split_surface",
    )
    top500 = candidate["incremental_coverage"]["500"]
    assert top500["matched_truth_docs"] == 92
    assert top500["phase1_overlap_truth_docs"] == 92
    assert top500["phase1_missed_truth_docs"] == 0
    assert top500["incremental_truth_docs_vs_phase1_all"] == 0
    assert top500["incremental_truth_docs_vs_phase1_top100"] == 92
    assert top500["incremental_truth_docs_vs_phase1_top500"] == 89
    assert top500["incremental_truth_docs_vs_phase1_top1000"] == 80
    assert top500["sub_rule_incremental_breakdown"]["R01"] == {
        "matched_truth_docs": 76,
        "phase1_overlap_truth_docs": 76,
        "phase1_missed_truth_docs": 0,
        "incremental_truth_docs_vs_phase1_all": 0,
        "overlap_ratio": 1.0,
        "incremental_ratio": 0.0,
    }
    assert top500["scenario_incremental_counts"] == {}
    uplift = candidate["phase1_topn_uplift"]
    assert uplift["phase1_all_truth_document_coverage"] == 620
    assert uplift["phase1_top100_truth_document_coverage"] == 3
    assert uplift["phase1_top500_truth_document_coverage"] == 15
    assert uplift["phase1_top1000_truth_document_coverage"] == 41
    assert uplift["phase2_top100_truth_not_in_phase1_top100"] == 51
    assert uplift["phase2_top500_truth_not_in_phase1_top500"] == 89
    assert uplift["phase2_top1000_truth_not_in_phase1_top1000"] == 129
    assert uplift["net_truth_uplift_vs_phase1_top100"] == 48
    assert uplift["net_truth_uplift_vs_phase1_top500"] == 77
    assert uplift["net_truth_uplift_vs_phase1_top1000"] == 100
    evidence = candidate["relational_evidence_incremental"]["500"]
    assert evidence["relational_evidence_added_truth_docs"] == 92
    assert evidence["relational_evidence_added_case_count"] == 37
    assert evidence["structural_evidence_added_truth_docs"] == 16
    assert evidence["moderate_tail_evidence_added_truth_docs"] == 76
    assert evidence["r05_r06_context_evidence_added_truth_docs"] == 0
    assert evidence["phase1_only_generic_reason_truth_docs"] == 12
    assert evidence["phase2_specific_relational_reason_truth_docs"] == 92
    assert (
        evidence["scenario_explanation_gap"]["phase2_relational_truth_docs_not_in_phase1_topn"]
        == 89
    )


def test_relational_ranking_candidates_decompose_moderate_tail_burden():
    payload = _payload()
    tail = payload["moderate_tail_decomposition"]

    assert tail["q95"]["tail_case_count"] == 651
    assert tail["q95"]["sub_rule_distribution"] == {"R01": 646, "R02": 5}
    assert tail["q95"]["top500_sub_rule_distribution"] == {
        "R01": 496,
        "R02": 4,
    }
    assert tail["q95"]["top500_matched"] == 98
    assert tail["q95"]["top500_review_burden"] == {
        "case_count": 500,
        "truth_case_count": 48,
        "nontruth_case_count": 452,
        "cases_per_matched_case": 10.416666666666666,
    }
    assert tail["q95"]["top500_edge_concentration"]["max_cases_per_edge"] == 1
    assert tail["q95"]["top500_context_buckets"]["business_process"] == {
        "A2R": 2,
        "H2R": 12,
        "Intercompany": 1,
        "O2C": 218,
        "P2P": 226,
        "R2R": 36,
        "TRE": 5,
    }
    assert tail["q99"]["tail_case_count"] == 648
    assert tail["q99"]["top500_matched"] == 98


def test_relational_ranking_candidates_include_fixed4_cross_batch_snapshot():
    payload = _payload()
    fixed4 = payload["cross_batch_validation"]["fixed4"]

    assert fixed4["available"] is True
    assert fixed4["dataset"] == "datasynth_manipulation_v7_candidate_fixed4"
    assert fixed4["case_count"] == 57780
    assert fixed4["truth_document_count"] == 620
    assert fixed4["sub_rule_case_counts"] == {
        "R01": 641,
        "R02": 5,
        "R03": 379,
        "R05": 44617,
        "R06": 11708,
        "R07": 430,
    }
    rankings = fixed4["candidate_rankings"]
    assert rankings["current"]["topn"]["500"]["matched"] == 17
    assert rankings["moderate_tail_only_surface_q95"]["topn"]["500"]["matched"] == 107
    assert rankings["moderate_tail_business_balanced_surface"]["topn"]["500"][
        "matched"
    ] == 107
    assert rankings["structural_moderate_tail_lane_split_surface"]["topn"]["500"][
        "matched"
    ] == 42
    assert rankings["structural_moderate_business_balanced_lane_split_surface"]["topn"][
        "500"
    ]["matched"] == 90
    assert rankings["structural_moderate_audit_then_business_lane_split_surface"]["topn"][
        "100"
    ]["matched"] == 51
    assert rankings["structural_moderate_audit_then_business_lane_split_surface"]["topn"][
        "500"
    ]["matched"] == 89
    assert rankings["structural_moderate_capped_context_lane_split_surface"]["topn"][
        "500"
    ]["matched"] == 89
    assert rankings["structural_anchor_moderate_1_to_4_surface"]["topn"]["500"][
        "matched"
    ] == 105
    assert rankings["three_lane_structural_moderate_context_surface"]["topn"]["500"][
        "matched"
    ] == 40
    assert fixed4["moderate_tail_decomposition"]["q95"]["top500_review_burden"] == {
        "case_count": 500,
        "truth_case_count": 50,
        "nontruth_case_count": 450,
        "cases_per_matched_case": 10.0,
    }


def test_relational_ranking_candidates_split_validation_preserves_direction():
    payload = _payload()
    candidate = "structural_moderate_audit_then_business_lane_split_surface"

    expected = {
        "fixed5": {
            "2022": {"current_100": 2, "candidate_100": 52, "current_500": 2, "candidate_500": 80},
            "2023": {"current_100": 2, "candidate_100": 20, "current_500": 3, "candidate_500": 29},
            "2024": {"current_100": 8, "candidate_100": 18, "current_500": 11, "candidate_500": 31},
        },
        "fixed4": {
            "2022": {"current_100": 2, "candidate_100": 51, "current_500": 2, "candidate_500": 79},
            "2023": {"current_100": 2, "candidate_100": 20, "current_500": 2, "candidate_500": 29},
            "2024": {"current_100": 6, "candidate_100": 16, "current_500": 8, "candidate_500": 29},
        },
    }
    nodes = {
        "fixed5": payload,
        "fixed4": payload["cross_batch_validation"]["fixed4"],
    }
    for dataset, expected_by_year in expected.items():
        by_year = nodes[dataset]["split_validation"]["fiscal_year"]
        for year, metrics in expected_by_year.items():
            current = by_year[year]["candidate_rankings"]["current"]["topn"]
            proposed = by_year[year]["candidate_rankings"][candidate]["topn"]
            assert current["100"]["matched"] == metrics["current_100"]
            assert proposed["100"]["matched"] == metrics["candidate_100"]
            assert current["500"]["matched"] == metrics["current_500"]
            assert proposed["500"]["matched"] == metrics["candidate_500"]
            assert proposed["100"]["matched"] >= current["100"]["matched"]
            assert proposed["500"]["matched"] >= current["500"]["matched"]


def test_relational_ranking_candidate_selectors_do_not_accept_truth_inputs():
    selector_names = [
        "_current_sort",
        "_edge_support_penalty_sort",
        "_document_diversity_penalty_sort",
        "_balanced_sub_rule_sort",
        "_r03_r07_priority_surface",
        "_volume_capped_by_edge_support_surface",
        "_sub_rule_balanced_review_surface",
        "_edge_novelty_with_tier_guard_surface",
        "_account_partner_context_surface",
        "_r03_r07_structural_only_surface",
        "_r01_r02_moderate_tail_surface",
        "_r05_r06_context_lane_surface",
        "_structural_moderate_tail_lane_split_surface",
        "_structural_moderate_low_burden_lane_split_surface",
        "_structural_moderate_business_balanced_lane_split_surface",
        "_structural_moderate_audit_context_balanced_lane_split_surface",
        "_structural_moderate_audit_then_business_lane_split_surface",
        "_structural_moderate_capped_context_lane_split_surface",
        "_structural_anchor_moderate_1_to_4_surface",
        "_three_lane_structural_moderate_context_surface",
    ]
    for name in selector_names:
        params = inspect.signature(getattr(diag, name)).parameters
        assert "truth_docs" not in params
        assert "truth_scenario_by_doc" not in params


def test_relational_ranking_candidates_do_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        truth_doc_ids = [row["document_id"] for row in reader]

    assert truth_doc_ids
    assert all(document_id not in text for document_id in truth_doc_ids)
    assert not re.search(r"p2_relational_edge_[0-9a-f]{10}", text)
    assert not re.search(r'"phase2_case_id"\s*:', text)
    assert not re.search(r'"edge_a"\s*:', text)
    assert not re.search(r'"edge_b"\s*:', text)
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
        "raw_edge_like_token_count": 0,
    }
    assert "edge_concentration" in text
