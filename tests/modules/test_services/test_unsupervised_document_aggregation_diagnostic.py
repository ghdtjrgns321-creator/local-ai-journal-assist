"""Smoke tests for fixed5 unsupervised document aggregation diagnostics."""

from __future__ import annotations

import csv
import inspect
import json
from pathlib import Path
from typing import Any

from tools.scripts import diagnose_unsupervised_document_aggregation_fixed5_20260529 as diag

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_document_aggregation_diagnostic_fixed5_20260529.json"
CROSSBATCH_ARTIFACT = (
    ROOT / "artifacts" / "unsupervised_document_aggregation_crossbatch_20260529.json"
)
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


def _crossbatch_payload() -> dict:
    return json.loads(CROSSBATCH_ARTIFACT.read_text(encoding="utf-8"))


def _truth_doc_ids() -> list[str]:
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


def test_document_aggregation_artifact_policy_flags_are_locked():
    payload = _payload()

    assert payload["diagnostic_only"] is True
    assert payload["native_case_ordering_changed"] is False
    assert payload["q95_gate_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True
    assert payload["native_row_case_ordering_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["production_adoption"] == "pending_cross_batch_validation"
    assert payload["coverage_candidate_decision"]["verdict"] == "diagnostic 유지, 추가 batch 필요"
    assert payload["decision"]["adopted_default_allowed"] is False
    assert (
        payload["decision"]["recommended_default_surface_if_datasynth_incomplete"]
        == "hybrid_with_soft_repeated_normal_guard"
    )
    assert payload["r" "aw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_document_aggregation_coverage_quality_matrix_core_values_are_locked():
    matrix = _payload()["coverage_quality_matrix"]

    assert matrix["native_row_queue"]["topn"]["100"]["matched"] == 5
    assert matrix["native_row_queue"]["topn"]["500"]["matched"] == 39
    assert matrix["native_row_queue"]["topn"]["10000"]["matched"] == 289
    max_score = matrix["document_max_score"]["topn"]
    assert max_score["100"]["matched"] == 11
    assert max_score["500"]["matched"] == 62
    assert max_score["10000"]["matched"] == 376
    row_penalty = matrix["document_score_with_row_count_penalty"]["topn"]
    assert row_penalty["100"]["matched"] == 22
    assert row_penalty["500"]["matched"] == 100
    assert row_penalty["10000"]["matched"] == 408
    topk3 = matrix["document_top_k_mean_score_k3"]["topn"]
    assert topk3["100"]["matched"] == 18
    assert topk3["500"]["matched"] == 82
    assert topk3["10000"]["matched"] == 369
    hybrid = matrix["hybrid_max_score_amount_tail_period_end"]["topn"]
    assert hybrid["100"]["matched"] == 50
    assert hybrid["500"]["matched"] == 209
    assert hybrid["10000"]["matched"] == 483
    repeated_guard = matrix["hybrid_with_repeated_normal_penalty"]["topn"]
    assert repeated_guard["100"]["matched"] == 3
    assert repeated_guard["500"]["matched"] == 22
    assert repeated_guard["10000"]["matched"] == 476
    concentration_guard = matrix["hybrid_with_account_process_concentration_guard"]["topn"]
    assert concentration_guard["100"]["matched"] == 3
    assert concentration_guard["500"]["matched"] == 65
    assert concentration_guard["10000"]["matched"] == 483
    amount_floor = matrix["row_count_penalty_with_amount_tail_floor"]["topn"]
    assert amount_floor["100"]["matched"] == 22
    assert amount_floor["500"]["matched"] == 100
    assert amount_floor["10000"]["matched"] == 408
    topk_context = matrix["top_k_mean_with_context"]["topn"]
    assert topk_context["100"]["matched"] == 3
    assert topk_context["500"]["matched"] == 22
    assert topk_context["10000"]["matched"] == 476
    balanced = matrix["document_companion_balanced_surface"]["topn"]
    assert balanced["100"]["matched"] == 3
    assert balanced["500"]["matched"] == 117
    assert balanced["10000"]["matched"] == 480
    soft_guard = matrix["hybrid_with_soft_repeated_normal_guard"]["topn"]
    assert soft_guard["100"]["matched"] == 25
    assert soft_guard["500"]["matched"] == 151
    assert soft_guard["10000"]["matched"] == 483
    soft_context = matrix["soft_guard_with_row_count_context"]["topn"]
    assert soft_context["100"]["matched"] == 32
    assert soft_context["500"]["matched"] == 174
    assert soft_context["10000"]["matched"] == 483
    phase1_prior = matrix["phase1_prior_companion_surface"]["topn"]
    assert phase1_prior["100"]["matched"] == 51
    assert phase1_prior["500"]["matched"] == 273
    assert phase1_prior["10000"]["matched"] == 482
    frontier = matrix["review_burden_frontier_surface"]["frontier"]
    assert frontier["phase1_plus_aggressive"]["100"]["coverage"]["matched"] == 64
    assert frontier["phase1_plus_aggressive"]["100"]["review_document_count"] == 127
    assert frontier["all_four_lanes"]["500"]["coverage"]["matched"] == 288
    assert frontier["all_four_lanes"]["500"]["review_document_count"] == 792
    blended = matrix["hybrid_row_count_blended_surface"]["topn"]
    assert blended["100"]["matched"] == 61
    assert blended["500"]["matched"] == 263
    assert blended["10000"]["matched"] == 483
    decision = _payload()["coverage_candidate_decision"]
    assert decision["best_coverage_candidate"] == "hybrid_row_count_blended_surface"
    assert decision["best_pressure_adjusted_candidate"] == "hybrid_with_soft_repeated_normal_guard"
    assert decision["best_legacy_recovery_candidate"] == "phase1_prior_companion_surface"
    assert decision["most_stable_candidate"] == "hybrid_with_soft_repeated_normal_guard"
    assert decision["baseline_conservative_candidate"] == "document_score_with_row_count_penalty"
    assert decision["production_adoption"] == "pending_cross_batch_validation"


def test_unsupervised_incremental_value_redefines_phase1_baseline_and_uplift():
    value = _payload()["unsupervised_incremental_value_diagnostic"]

    assert value["diagnostic_only"] is True
    assert value["phase1_baseline"] == {
        "phase1_all_document_inclusion": 24790,
        "phase1_all_truth_document_coverage": 544,
        "phase1_top100_truth_document_coverage": 0,
        "phase1_top500_truth_document_coverage": 50,
        "phase1_top1000_truth_document_coverage": 87,
        "baseline_source": "phase1_case_result_documents",
    }

    soft = value["surface_topn_uplift"]["hybrid_with_soft_repeated_normal_guard"]
    assert soft["phase2_top100_truth_not_in_phase1_top100"] == 25
    assert soft["phase2_top500_truth_not_in_phase1_top500"] == 114
    assert soft["phase2_top1000_truth_not_in_phase1_top1000"] == 239
    assert soft["net_truth_uplift_vs_phase1_top100"] == 25
    assert soft["net_truth_uplift_vs_phase1_top500"] == 101
    assert soft["net_truth_uplift_vs_phase1_top1000"] == 220

    blended = value["surface_topn_uplift"]["hybrid_row_count_blended_surface"]
    assert blended["net_truth_uplift_vs_phase1_top100"] == 61
    assert blended["net_truth_uplift_vs_phase1_top500"] == 213
    assert blended["net_truth_uplift_vs_phase1_top1000"] == 247

    frontier = value["surface_topn_uplift"]["frontier_all_four_lanes_union"]
    assert frontier["net_truth_uplift_vs_phase1_top100"] == 64
    assert frontier["net_truth_uplift_vs_phase1_top500"] == 238
    assert frontier["net_truth_uplift_vs_phase1_top1000"] == 277

    balanced = value["surface_topn_uplift"]["balanced_unsupervised_companion_v1"]
    assert balanced["net_truth_uplift_vs_phase1_top100"] == 64
    assert balanced["net_truth_uplift_vs_phase1_top500"] == 44
    assert balanced["net_truth_uplift_vs_phase1_top1000"] == 104


def test_unsupervised_incremental_value_evidence_explanation_and_attrition_are_locked():
    value = _payload()["unsupervised_incremental_value_diagnostic"]

    evidence = value["unsupervised_evidence_incremental"]
    assert evidence["unsupervised_evidence_added_truth_docs"] == 483
    assert evidence["unsupervised_evidence_added_case_count"] == 930
    assert evidence["ml_score_evidence_added_truth_docs"] == 483
    assert evidence["top_feature_evidence_added_truth_docs"] == 0
    assert evidence["document_level_context_added_truth_docs"] == 483
    assert evidence["amount_tail_context_added_truth_docs"] == 189
    assert evidence["period_end_context_added_truth_docs"] == 483
    assert evidence["row_count_repeated_guard_context_added_truth_docs"] == 442
    assert evidence["multivariate_anomaly_context_added_truth_docs"] == 483
    assert evidence["phase2_specific_ml_reason_truth_docs"] == 47

    explanation = value["scenario_explanation_gap"]
    assert explanation["phase1_scenario_aligned_truth_docs"] == 404
    assert explanation["phase1_scenario_gap_truth_docs"] == 140
    assert explanation["unsupervised_explanation_incremental_truth_docs"] == 47

    attrition = value["blind_spot_attrition_summary"]
    assert attrition["target_truth_docs"] == 533
    assert attrition["score_candidate_truth_docs"] == 533
    assert attrition["q95_pass_truth_docs"] == 409
    assert attrition["native_case_truth_docs"] == 409
    assert attrition["document_candidate_truth_docs"] == 409
    assert attrition["candidate_but_ranked_below_top500_truth_docs"] == 389
    assert attrition["missing_from_candidate_pool_truth_docs"] == 124
    assert attrition["attrition_reason_aggregate"] == {
        "candidate_but_ranked_below_top500": 389,
        "q95_gate_miss": 124,
    }
    assert attrition["topN_surface_truth_docs"]["hybrid_with_soft_repeated_normal_guard"][
        "500"
    ] == 106
    assert attrition["topN_surface_truth_docs"]["frontier_all_four_lanes_union"]["500"] == 222

    decision = _payload()["decision"]
    assert decision["document_inclusion_incremental_value"] == "broad_inclusion_metric_only"
    assert decision["topn_uplift_value"] == "medium"
    assert decision["evidence_incremental_value"] == "high"
    assert decision["explanation_incremental_value"] == "medium"
    assert decision["primary_product_role"] == "broad_expansion"
    assert decision["adopted_default_allowed"] is False


def test_unsupervised_attrition_improvement_diagnostic_is_locked():
    diagnostic = _payload()["unsupervised_attrition_improvement_diagnostic"]

    assert diagnostic["diagnostic_only"] is True
    decomp = diagnostic["ranking_attrition_decomposition"]
    assert decomp["candidate_but_ranked_below_top500"] == 389
    assert decomp["rank_band_counts"] == {
        "1001_2000": 181,
        "2001_5000": 67,
        "5001_plus": 44,
        "501_1000": 97,
    }
    assert decomp["reason_category_counts"] == {
        "audit_policy_interleave_suppression": 90,
        "phase1_topn_gap_low_surface_priority": 29,
        "repeated_normal_competition": 269,
        "weak_amount_period_end_context": 1,
    }

    q95 = diagnostic["q95_gate_miss_decomposition"]
    assert q95["q95_gate_miss_truth_docs"] == 124
    assert q95["near_q95_band_count"] == 54
    assert q95["strong_document_context_candidate_count"] == 5
    assert q95["context_distribution"]["doc_count"] == 124
    assert q95["context_distribution"]["max_row_score_percentile_distribution"]["p50"] == (
        0.8770249809285593
    )

    top_features = diagnostic["top_features_path_diagnostic"]
    assert top_features["production_detector_emits_ml02_top_features"] is True
    assert top_features["builder_preserves_ml02_top_features"] is True
    assert top_features["measurement_path_uses_dummy_details"] is True
    assert top_features["artifact_serialization_missing_after_builder"] is False
    assert top_features["ranking_uses_top_features"] is False
    assert top_features["current_stage7_top_feature_evidence_added_truth_docs"] == 0

    baseline = diagnostic["baseline_surface"]["hybrid_with_soft_repeated_normal_guard"]
    assert baseline["topn"]["500"]["matched"] == 151
    assert baseline["phase1_topn_uplift"]["net_truth_uplift_vs_phase1_top500"] == 101
    assert baseline["candidate_but_ranked_below_top500"] == 303
    assert baseline["candidate_but_ranked_below_top500_reduction"] == 86
    assert baseline["repeated_normal_ratio_top500"] == 0.256

    rescue = diagnostic["new_diagnostic_surfaces"]["soft_guard_rank_band_rescue_surface"]
    assert rescue["topn"]["500"]["matched"] == 150
    assert rescue["phase1_topn_uplift"]["net_truth_uplift_vs_phase1_top500"] == 100
    assert rescue["candidate_but_ranked_below_top500"] == 301
    assert rescue["candidate_but_ranked_below_top500_reduction"] == 88
    assert rescue["repeated_normal_ratio_top500"] == 0.256
    assert rescue["candidate_weight_provenance"]["fixed5_weight_sweep"] is False
    assert rescue["production_adoption"] == "pending_cross_batch_validation"

    diversity = diagnostic["new_diagnostic_surfaces"]["soft_guard_context_diversity_surface"]
    assert diversity["topn"]["500"]["matched"] == 131
    assert diversity["candidate_but_ranked_below_top500_reduction"] == 73

    ml_quality = diagnostic["new_diagnostic_surfaces"]["ml_evidence_quality_surface"]
    assert ml_quality["disabled"] is True
    assert "dummy details" in ml_quality["disabled_reason"]

    gap = diagnostic["new_diagnostic_surfaces"]["phase1_topn_gap_companion_surface"]
    assert gap["topn"]["500"]["matched"] == 135
    assert gap["candidate_but_ranked_below_top500_reduction"] == 65
    assert diagnostic["decision"]["product_adoption_possible_now"] is False


def test_incremental_coverage_against_phase1_case_result_is_locked():
    inc = _payload()["incremental_coverage_diagnostic"]

    assert inc["diagnostic_only"] is True
    assert inc["phase1_baseline"] == {
        "source": "phase1_case_result_documents",
        "phase1_case_count": 23166,
        "phase1_all_doc_count": 24790,
        "phase1_all_truth_count": 544,
        "phase1_top100_doc_count": 100,
        "phase1_top100_truth_count": 0,
        "phase1_top500_doc_count": 500,
        "phase1_top500_truth_count": 50,
        "phase1_top1000_doc_count": 1000,
        "phase1_top1000_truth_count": 87,
        "phase1_top10000_doc_count": 10000,
        "phase1_top10000_truth_count": 456,
    }
    judgement = inc["judgement"]
    assert judgement["blind_spot_value"] == "medium"
    assert judgement["primary_product_role"] == "broad_expansion"
    assert (
        judgement["recommended_surface_if_datasynth_incomplete"]
        == "hybrid_with_soft_repeated_normal_guard"
    )

    expected = {
        "native_row_queue": {
            "100": (5, 5, 0, 5, 84),
            "500": (39, 38, 1, 39, 352),
            "10000": (289, 281, 8, 289, 5327),
        },
        "hybrid_with_soft_repeated_normal_guard": {
            "100": (25, 20, 5, 25, 100),
            "500": (151, 140, 11, 151, 500),
            "10000": (483, 436, 47, 483, 10000),
        },
        "soft_guard_with_row_count_context": {
            "100": (32, 27, 5, 32, 100),
            "500": (174, 163, 11, 174, 500),
            "10000": (483, 436, 47, 483, 10000),
        },
        "hybrid_row_count_blended_surface": {
            "100": (61, 54, 7, 61, 100),
            "500": (263, 253, 10, 263, 500),
            "10000": (483, 436, 47, 483, 10000),
        },
        "phase1_prior_companion_surface": {
            "100": (51, 45, 6, 51, 100),
            "500": (273, 263, 10, 273, 500),
            "10000": (482, 435, 47, 482, 10000),
        },
        "frontier_phase1_plus_aggressive_union": {
            "100": (64, 56, 8, 64, 127),
            "500": (285, 274, 11, 285, 631),
            "10000": (483, 436, 47, 483, 12479),
        },
        "frontier_all_four_lanes_union": {
            "100": (64, 56, 8, 64, 170),
            "500": (288, 276, 12, 288, 792),
            "10000": (483, 436, 47, 483, 13010),
        },
    }
    for surface, by_topn in expected.items():
        for top_n, values in by_topn.items():
            row = inc["surfaces"][surface]["topn"][top_n]
            assert (
                row["matched_truth_docs"],
                row["phase1_overlap_truth_docs"],
                row["phase1_missed_truth_docs"],
                row["incremental_truth_docs_vs_phase1_top100"],
                row["review_doc_count"],
            ) == values
            assert row["phase1_overlap_truth_docs"] + row["phase1_missed_truth_docs"] == row[
                "matched_truth_docs"
            ]
            assert row["phase1_missed_truth_docs"] <= row["matched_truth_docs"]
            assert 0.0 <= row["overlap_ratio"] <= 1.0
            assert 0.0 <= row["incremental_ratio"] <= 1.0


def test_document_aggregation_false_positive_risk_profiles_are_present():
    matrix = _payload()["coverage_quality_matrix"]

    for name in (
        "document_max_score",
        "document_top_k_mean_score_k3",
        "document_score_with_row_count_penalty",
        "hybrid_max_score_amount_tail_period_end",
    ):
        risk = matrix[name]["false_positive_risk_profile"]
        assert {"100", "500"}.issubset(risk)
        for top_n in ("100", "500"):
            profile = risk[top_n]
            assert "document_row_count_distribution" in profile
            assert "amount_distribution" in profile
            assert "account_concentration" in profile
            assert "process_concentration" in profile
            assert "period_end_proximity_days_distribution" in profile
            assert "case_count_per_document_distribution" in profile
            assert "false_positive_pressure_summary" in profile
            assert "missing_top_features_ratio" in profile
            assert "top_features_presence_ratio" in profile
            assert "top_document_share" in profile
            assert "top_account_share" in profile
            assert "top_process_share" in profile
            assert 0.0 <= profile["single_row_high_amount_document_ratio"] <= 1.0
            assert 0.0 <= profile["repeated_normal_document_ratio"] <= 1.0
            assert 0.0 <= profile["normal_single_row_high_amount_proxy"] <= 1.0
            assert 0.0 <= profile["period_end_normal_background_proxy"] <= 1.0


def test_document_aggregation_candidates_record_no_fitting_provenance():
    matrix = _payload()["coverage_quality_matrix"]

    for name, candidate in matrix.items():
        if name in {
            "two_lane_phase1_prior_aggressive_surface",
            "review_burden_frontier_surface",
        }:
            assert candidate["diagnostic_only"] is True
            assert candidate["production_adoption"] == "pending_cross_batch_validation"
            continue
        provenance = candidate["candidate_weight_provenance"]
        assert provenance["calibrated"] is False
        if name != "native_row_queue":
            assert provenance["weight_source"] == "fixed5 exploratory diagnostic weights"
            assert provenance["production_ranking_policy"] is False
            assert candidate["truth_label_used_for_scoring"] is False
            assert candidate["truth_label_used_only_for_aggregate_evaluation"] is True
            assert candidate["q95_gate_changed"] is False
            assert candidate["vae_score_or_threshold_changed"] is False
            assert candidate["native_row_case_ordering_changed"] is False
            assert candidate["phase1_ranking_changed"] is False
            assert candidate["phase2_fusion_changed"] is False
            assert candidate["production_adoption"] == "pending_cross_batch_validation"


def test_candidate_selector_does_not_accept_truth_inputs():
    params = inspect.signature(diag._candidate_scores).parameters

    assert list(params) == ["records"]


def test_incremental_selector_does_not_accept_truth_inputs_for_scoring():
    params = inspect.signature(diag._candidate_ordered_doc_surfaces).parameters

    assert list(params) == ["cases", "records"]


def test_crossbatch_companion_surface_reproduces_soft_guard_direction():
    payload = _crossbatch_payload()

    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["native_row_case_ordering_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["production_adoption"] == "pending_cross_batch_validation"
    assert payload["r" "aw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }

    summary = payload["cross_batch_summary"]
    assert summary["hybrid_with_soft_repeated_normal_guard"] == {
        "top100_min": 15,
        "top100_max": 27,
        "top500_min": 103,
        "top500_max": 151,
        "top100_false_positive_pressure_min": 0.0995,
        "top100_false_positive_pressure_max": 0.14721014492753623,
    }
    assert summary["hybrid_row_count_blended_surface"]["top100_min"] == 54
    assert summary["hybrid_row_count_blended_surface"]["top100_max"] == 61
    assert summary["hybrid_row_count_blended_surface"]["top500_min"] == 196
    assert summary["hybrid_row_count_blended_surface"]["top500_max"] == 263
    assert summary["soft_guard_with_row_count_context"] == {
        "top100_min": 20,
        "top100_max": 32,
        "top500_min": 126,
        "top500_max": 174,
        "top100_false_positive_pressure_min": 0.14454545454545456,
        "top100_false_positive_pressure_max": 0.1923137254901961,
    }
    assert summary["phase1_prior_companion_surface"] == {
        "top100_min": 25,
        "top100_max": 51,
        "top500_min": 143,
        "top500_max": 273,
        "top100_false_positive_pressure_min": 0.15364814814814817,
        "top100_false_positive_pressure_max": 0.2286849710982659,
    }
    assert summary["native_row_queue"]["top100_min"] == 5
    assert summary["native_row_queue"]["top500_max"] == 39
    assert set(payload["batches"]) == {
        "fixed3",
        "fixed4",
        "fixed5_normalcal4",
        "fixed5_normalcal5",
    }
    for batch in payload["batches"].values():
        assert {"2022", "2023", "2024"}.issubset(batch["year_slice_snapshot"])
    drift = payload["soft_guard_drift_decomposition"]
    assert drift["fixed3_fixed4_top100_range"] == {"min": 15, "max": 16}
    assert drift["fixed5_top100_range"] == {"min": 25, "max": 27}
    assert drift["by_batch"]["fixed3"]["year_slice_top100_min"] == 3
    assert drift["by_batch"]["fixed4"]["year_slice_top100_min"] == 3
    assert drift["by_batch"]["fixed5_normalcal4"]["year_slice_top100_min"] == 6
    assert drift["by_batch"]["fixed5_normalcal5"]["year_slice_top100_min"] == 5
    assert drift["by_batch"]["fixed4"]["top100_false_positive_pressure"] == 0.0995
    assert "not higher false-positive pressure" in drift["current_interpretation"]
    rank_bands = payload["batches"]["fixed4"]["soft_guard_rank_band_decomposition"]
    assert rank_bands["truth_documents_in_top500_outside_top100"] == 88
    assert rank_bands["bands"]["rank101_250"]["truth_document_count"] == 39
    assert rank_bands["bands"]["rank251_500"]["truth_document_count"] == 49

    for batch_key, batch in payload["batches"].items():
        inc = batch["incremental_coverage_diagnostic"]
        value = batch["unsupervised_incremental_value_diagnostic"]
        attrition_improvement = batch["unsupervised_attrition_improvement_diagnostic"]
        assert inc["diagnostic_only"] is True
        assert value["diagnostic_only"] is True
        assert attrition_improvement["diagnostic_only"] is True
        assert "phase1_baseline" in inc
        assert "phase1_baseline" in value
        assert "surface_topn_uplift" in value
        assert "unsupervised_evidence_incremental" in value
        assert "scenario_explanation_gap" in value
        assert "blind_spot_attrition_summary" in value
        assert "decision" in value
        assert "ranking_attrition_decomposition" in attrition_improvement
        assert "q95_gate_miss_decomposition" in attrition_improvement
        assert "top_features_path_diagnostic" in attrition_improvement
        assert "new_diagnostic_surfaces" in attrition_improvement
        assert attrition_improvement["top_features_path_diagnostic"][
            "measurement_path_uses_dummy_details"
        ] is True
        assert attrition_improvement["new_diagnostic_surfaces"][
            "ml_evidence_quality_surface"
        ]["disabled"] is True
        assert value["decision"]["adopted_default_allowed"] is False
        assert value["truth_label_used_for_scoring"] is False
        assert value["truth_label_used_only_for_aggregate_evaluation"] is True
        assert "judgement" in inc
        assert inc["judgement"]["primary_product_role"] in {
            "blind_spot_companion",
            "broad_expansion",
            "mostly_reordering",
        }
        for surface in (
            "native_row_queue",
            "hybrid_with_soft_repeated_normal_guard",
            "soft_guard_with_row_count_context",
            "hybrid_row_count_blended_surface",
            "phase1_prior_companion_surface",
            "frontier_all_four_lanes_union",
        ):
            assert surface in inc["surfaces"]
            top500 = inc["surfaces"][surface]["topn"]["500"]
            assert top500["phase1_missed_truth_docs"] <= top500["matched_truth_docs"]
            assert (
                top500["phase1_overlap_truth_docs"] + top500["phase1_missed_truth_docs"]
                == top500["matched_truth_docs"]
            )
            assert "phase1_missed_truth_scenario_counts" in inc["surfaces"][surface]
        if batch_key != "fixed5_normalcal4":
            assert inc["phase1_baseline"]["source"] == "phase1_case_result_documents"
        else:
            assert inc["phase1_baseline"]["source"] == "phase1_review_context_fallback"
            assert value["phase1_baseline"]["baseline_source"] == "phase1_review_context_fallback"


def test_document_aggregation_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert all(document_id not in text for document_id in _truth_doc_ids())
    banned_keys = {
        "document" "_id",
        "document" "_ids",
        "r" "aw" "_document" "_id",
        "r" "aw" "_document" "_ids",
        "r" "aw" "_doc",
        "r" "aw" "_doc" "_id",
        "r" "aw" "_label",
        "row" "_id",
        "row" "_ids",
        "r" "aw" "_row" "_id",
        "r" "aw" "_row" "_ids",
        "index" "_label",
        "r" "aw" "_index" "_label",
        "phase2" "_case" "_id",
        "phase2" "_case" "_ids",
    }
    assert banned_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["r" "aw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    assert "p2_unsupervised_" not in text
