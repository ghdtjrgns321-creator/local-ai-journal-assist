"""Smoke checks for the fixed5 PHASE2 native case remeasurement artifact.

The full remeasurement script is intentionally slow because it rebuilds all
native family review candidate lanes from the fixed5 population. These checks
lock the aggregate output contract and catch accidental drift in checked-in
case_count / TOP-N values without exposing raw document identifiers.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "phase2_native_case_remeasure_fixed5_20260528.json"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)
RELATIONAL_DIAGNOSTIC = (
    ROOT / "artifacts" / "phase2_relational_native_case_diagnostic_fixed5_20260528.json"
)
INTERCOMPANY_INCREMENTAL = (
    ROOT / "artifacts" / "intercompany_incremental_value_fixed5_20260529.json"
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _relational_diagnostic_payload() -> dict:
    return json.loads(RELATIONAL_DIAGNOSTIC.read_text(encoding="utf-8"))


def _intercompany_incremental_payload() -> dict:
    return json.loads(INTERCOMPANY_INCREMENTAL.read_text(encoding="utf-8"))


def _all_truth_doc_ids() -> list[str]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def test_fixed5_unsupervised_native_case_counts_and_topn_stay_within_measurement_band():
    """Stage7 unsupervised scoring has small q95-boundary drift across runs.

    The smoke locks the measurement contract and material movement, not a single
    exact ML boundary count. Rule-style families below remain exact.
    """
    payload = _payload()
    unsupervised = payload["family_results"]["unsupervised"]

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    assert payload["truth_document_count"] == 620
    assert 51_000 <= unsupervised["case_count"] <= 52_500
    assert 4 <= unsupervised["topn"]["100"]["matched"] <= 8
    assert 35 <= unsupervised["topn"]["500"]["matched"] <= 50
    assert 280 <= unsupervised["topn"]["10000"]["matched"] <= 310
    assert unsupervised["top100_primary_scenario"] == "fictitious_entry"
    assert set(unsupervised["top500_scenario_counts"]) <= {
        "expense_capitalization",
        "fictitious_entry",
        "unusual_timing_manipulation",
    }


def test_fixed5_unsupervised_diagnostic_records_row_to_document_attrition():
    payload = _payload()
    diag = payload["family_diagnostics"]["unsupervised"]

    assert diag["total_unsupervised_cases"] == payload["family_results"]["unsupervised"][
        "case_count"
    ]
    assert diag["unique_docs_covered_by_cases"] == payload["family_results"]["unsupervised"][
        "docs_covered"
    ]
    assert diag["truth_docs_covered_by_all_cases"] >= diag["truth_docs_in_topn"]["10000"]
    assert diag["first_truth_case_rank"] is not None
    assert diag["truth_case_rank_distribution"]["count"] > 0
    assert diag["truth_doc_best_rank_distribution"]["count"] > 0
    assert diag["cases_per_document_distribution"]["max"] >= 1
    assert diag["truth_cases_per_document_distribution"]["count"] > 0
    assert diag["nontruth_cases_per_document_distribution"]["count"] > 0


def test_fixed5_unsupervised_document_aggregation_is_diagnostic_only():
    payload = _payload()
    experiment = payload["family_diagnostics"]["unsupervised"][
        "document_aggregation_experiment"
    ]

    assert experiment["diagnostic_only"] is True
    assert experiment["native_case_ordering_changed"] is False
    candidate_rankings = experiment["candidate_rankings"]
    expected = {
        "document_max_score",
        "document_top_k_mean_score_k3",
        "document_top_k_mean_score_k5",
        "document_case_count_weighted_score",
        "document_ecdf_max",
        "document_score_with_row_count_penalty",
        "document_score_with_diversity_penalty",
    }
    assert expected.issubset(candidate_rankings)
    for ranking in expected:
        topn = candidate_rankings[ranking]["topn"]
        assert {"100", "500", "1000", "10000"}.issubset(topn)
        assert 0 <= topn["100"]["matched"] <= topn["10000"]["matched"] <= 620

    row_penalty = candidate_rankings["document_score_with_row_count_penalty"]["topn"]
    assert row_penalty["100"]["matched"] == 22
    assert row_penalty["500"]["matched"] == 100
    assert row_penalty["10000"]["matched"] == 408
    topk3 = candidate_rankings["document_top_k_mean_score_k3"]["topn"]
    assert topk3["100"]["matched"] == 18
    assert topk3["500"]["matched"] == 82
    assert topk3["10000"]["matched"] == 369
    case_count_weighted = candidate_rankings["document_case_count_weighted_score"]["topn"]
    assert case_count_weighted["100"]["matched"] == 0
    assert case_count_weighted["500"]["matched"] == 0


def test_fixed5_unsupervised_diagnostic_does_not_emit_raw_document_ids():
    payload = _payload()
    diagnostic = payload["family_diagnostics"]["unsupervised"]
    diagnostic_text = json.dumps(diagnostic, ensure_ascii=False)
    truth_doc_ids = _all_truth_doc_ids()

    assert truth_doc_ids
    assert all(document_id not in diagnostic_text for document_id in truth_doc_ids)
    banned_keys = {
        "document_id",
        "document_ids",
        "raw_document_id",
        "raw_document_ids",
        "raw_doc",
        "raw_doc_id",
        "raw_label",
        "row_id",
        "row_ids",
        "raw_row_id",
        "raw_row_ids",
        "index_label",
        "raw_index_label",
        "phase2_case_id",
        "phase2_case_ids",
    }
    assert banned_keys.isdisjoint({key.lower() for key in _walk_keys(diagnostic)})


def test_fixed5_relational_native_case_count_and_topn_are_stable():
    payload = _payload()
    relational = payload["family_results"]["relational"]

    assert relational["case_count"] == 57640
    assert relational["topn"]["100"]["matched"] == 5
    assert relational["topn"]["500"]["matched"] == 19
    assert relational["top100_scenario_counts"] == {
        "circular_related_party_transaction": 4,
        "embezzlement_concealment": 1,
    }


def test_fixed5_relational_diagnostic_records_sub_rule_distribution_and_gap_reasons():
    payload = _relational_diagnostic_payload()

    assert "positive_metric_count >= 20" in payload["case_grade_policy"]
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
    assert payload["top100_sub_rule_counts"] == {"R03": 72, "R07": 28}
    assert payload["top1000_sub_rule_counts"] == {
        "R03": 211,
        "R05": 545,
        "R06": 160,
        "R07": 84,
    }
    assert payload["top100_matched_by_sub_rule"] == {"R03": 4, "R07": 1}
    assert payload["top500_matched_by_sub_rule"] == {
        "R03": 9,
        "R06": 2,
        "R07": 8,
    }
    assert payload["rule_gap_summary"]["R01"]["gap_reasons"] == {
        "row_score_hit_without_edge_identity": 0,
        "edge_gate_filtered_or_below_tail": 800,
        "edge_row_position_invalid": 0,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
        "raw_edge_like_token_count": 0,
    }
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
    assert payload["phase1_baseline"]["topn"]["500"]["truth_document_count"] == 15
    assert payload["phase1_topn_uplift"]["phase2_top500_truth_not_in_phase1_top500"] == 19
    assert payload["phase1_topn_uplift"]["net_truth_uplift_vs_phase1_top500"] == 4
    evidence = payload["relational_evidence_incremental"]["500"]
    assert evidence["relational_evidence_added_truth_docs"] == 19
    assert evidence["structural_evidence_added_truth_docs"] == 17
    assert evidence["moderate_tail_evidence_added_truth_docs"] == 0
    assert evidence["r05_r06_context_evidence_added_truth_docs"] == 2
    assert "scenario_explanation_gap" in evidence
    incremental = payload["incremental_coverage_vs_phase1"]["500"]
    assert incremental["matched_truth_docs"] == 19
    assert incremental["phase1_overlap_truth_docs"] == 19
    assert incremental["phase1_missed_truth_docs"] == 0
    assert incremental["incremental_truth_docs_vs_phase1_all"] == 0
    assert incremental["incremental_truth_docs_vs_phase1_top100"] == 19
    assert incremental["incremental_truth_docs_vs_phase1_top500"] == 19
    assert incremental["incremental_truth_docs_vs_phase1_top1000"] == 19
    assert incremental["scenario_incremental_counts"] == {}
    assert (
        incremental["phase1_overlap_truth_docs"]
        + incremental["phase1_missed_truth_docs"]
        == incremental["matched_truth_docs"]
    )
    assert incremental["sub_rule_incremental_breakdown"]["R03"] == {
        "matched_truth_docs": 9,
        "phase1_overlap_truth_docs": 9,
        "phase1_missed_truth_docs": 0,
        "incremental_truth_docs_vs_phase1_all": 0,
        "overlap_ratio": 1.0,
        "incremental_ratio": 0.0,
    }
    r05 = payload["sub_rule_decomposition"]["R05"]
    r06 = payload["sub_rule_decomposition"]["R06"]
    assert r05["case_count"] == 44404
    assert r06["case_count"] == 11874
    assert r05["top_concentration"]["edge_count"] == 44404
    assert r06["top_concentration"]["edge_count"] == 11874
    assert payload["case_count_growth_truth_coverage"]["R05"][
        "matched_truth_count"
    ] == 126
    assert payload["case_count_growth_truth_coverage"]["R06"][
        "matched_truth_count"
    ] == 70


def test_fixed5_intercompany_native_case_count_and_circular_coverage_are_stable():
    payload = _payload()
    intercompany = payload["family_results"]["intercompany"]
    circular = payload["top500_scenario_matrix"]["circular_related_party_transaction"]

    assert intercompany["case_count"] == 246
    assert intercompany["topn"]["100"]["matched"] == 34
    assert intercompany["top100_scenario_counts"] == {
        "circular_related_party_transaction": 34,
    }
    assert circular["truth_n"] == 34
    assert circular["intercompany"] == {"matched": 34, "scenario_recall": 1.0}


def test_fixed5_intercompany_incremental_artifact_preserves_existing_success_lock():
    payload = _intercompany_incremental_payload()

    assert payload["ic_native_success_lock"] == {
        "case_count": 246,
        "top100_circular_truth_docs": 34,
        "circular_scenario_truth_coverage": "34/34",
    }
    assert payload["decision"]["primary_product_role"] == (
        "ic_specific_evidence_strengthening"
    )
    assert payload["decision"]["broad_recall_expansion_family"] is False
    assert payload["decision"]["production_ranking_changed"] is False
    assert payload["decision"]["new_policy_adopted"] is False
    assert payload["decision"]["adopted_default_allowed"] is False


def test_fixed5_duplicate_native_case_diversity_retention_is_stable():
    payload = _payload()
    duplicate = payload["family_results"]["duplicate"]
    period_end = payload["top500_scenario_matrix"]["period_end_adjustment_manipulation"]

    assert duplicate["case_count"] == 198
    assert duplicate["docs_covered"] == 145
    assert duplicate["topn"]["100"]["matched"] == 22
    assert duplicate["topn"]["500"]["matched"] == 22
    assert duplicate["top100_scenario_counts"] == {
        "period_end_adjustment_manipulation": 22,
    }
    assert period_end["duplicate"] == {
        "matched": 22,
        "scenario_recall": 0.2391304347826087,
    }


def test_fixed5_timeseries_diagnostic_records_ranking_gap_and_baseline_context():
    payload = _payload()
    ts = payload["family_diagnostics"]["timeseries"]

    assert ts["artifact_window_count"] == 1000
    assert ts["case_count"] == 861
    assert ts["baseline_available_window_count"] == 999
    assert ts["baseline_available_case_count"] == 860
    assert ts["first_truth_case_rank"] == 762
    assert ts["primary_gap_classification"] == "ranking_gap"
    assert ts["builder_excluded_window_reasons"] == {"sub_signal_high_false": 139}
    assert ts["top500_truth_miss_reasons"] == {"period_end_normalized_downrank": 1}
    assert ts["top_truth_covering_cases"][0]["top500_gap_reason"] == (
        "period_end_normalized_downrank"
    )
    truth_case = ts["top_truth_covering_cases"][0]
    assert truth_case["period_end_day_offset"] == 0
    assert truth_case["period_end_lift"] == 5.5
    assert truth_case["context_evidence_count"] == 4
    comparison = ts["period_end_disambiguation_comparison"]
    assert comparison["top500_period_end_case_count"] == 119
    assert comparison["truth_case_lower_rank_reason"] == "mixed_period_end_context"
    assert comparison["period_end_lift_distribution"]["count"] == 119


def test_fixed5_artifact_records_stage7_top_feature_limitation():
    payload = _payload()

    assert any(
        "top_features are unavailable in the Stage7 measurement path" in note
        for note in payload["output_notes"]
    )
    assert any(
        "q95-boundary aggregate counts may still drift slightly" in note
        for note in payload["output_notes"]
    )
    assert "No raw document identifiers" in payload["output_notes"][0]
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
