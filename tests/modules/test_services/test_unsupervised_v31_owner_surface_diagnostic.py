from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_v31_owner_surface_fixed5_20260531.json"


def _payload() -> dict[str, Any]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_v31_unsupervised_owner_surface_guardrails():
    payload = _payload()

    assert payload["responsibility_map"] == "v3.1"
    assert payload["diagnostic_only"] is True
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["native_row_case_ordering_changed"] is True
    assert payload["product_default_adoption"] is True


def test_v31_unsupervised_role_denominators_locked():
    denominators = _payload()["role_denominators"]

    assert denominators["primary"] == {
        "truth_docs": 168,
        "phase1_immediate_review_covered_docs": 0,
        "phase1_review_or_above_covered_docs": 41,
        "phase1_candidate_or_above_covered_docs": 42,
    }
    assert denominators["companion"] == {
        "truth_docs": 339,
        "phase1_immediate_review_covered_docs": 0,
        "phase1_review_or_above_covered_docs": 9,
        "phase1_candidate_or_above_covered_docs": 40,
    }


def test_v31_unsupervised_primary_surface_metrics_locked():
    primary = _payload()["surface_metrics_by_role"]["primary"]

    native = primary["native_row_queue"]["topn"]
    assert native["100"]["matched_docs"] == 12
    assert native["500"]["matched_docs"] == 23
    assert native["10000"]["matched_docs"] == 111

    soft = primary["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched_docs"] == 24
    assert soft["topn"]["500"]["matched_docs"] == 110
    assert soft["topn"]["500"]["phase1_review_or_above_outside_docs"] == 74
    assert soft["topn"]["500"]["phase1_candidate_or_above_outside_docs"] == 73
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.336
    assert soft["top500_pressure"]["period_end_normal_background_ratio"] == 0.578

    context = primary["soft_guard_with_row_count_context"]
    assert context["topn"]["500"]["matched_docs"] == 114
    assert context["top500_pressure"]["repeated_normal_pressure"] == 0.4

    probe = primary["soft_guard_context_top100_probe"]
    assert probe["topn"]["100"]["matched_docs"] == 31
    assert probe["topn"]["500"]["matched_docs"] == 110
    assert probe["top500_pressure"]["repeated_normal_pressure"] == 0.336


def test_v31_unsupervised_primary_top100_gap_analysis_locked():
    gap = _payload()["primary_top100_gap_analysis"]

    assert gap["default_surface"] == "hybrid_with_soft_repeated_normal_guard"
    assert gap["top500_but_below_top100_docs"] == 86
    assert (
        gap["top100_gap_classification"]
        == "rank_band_separation_not_candidate_pool_absence"
    )
    assert gap["default_rank_bands"]["top100"]["matched_docs"] == 24
    assert gap["default_rank_bands"]["rank101_250"]["matched_docs"] == 49
    assert gap["default_rank_bands"]["rank251_500"]["matched_docs"] == 37
    assert gap["default_rank_bands"]["rank501_1000"]["matched_docs"] == 21
    assert gap["default_rank_bands"]["outside_top10000_or_not_candidate"][
        "matched_docs"
    ] == 28

    probe = gap["bounded_diagnostic_candidates"][
        "soft_guard_context_top100_probe"
    ]
    assert probe["top100_matched_docs"] == 31
    assert probe["top500_matched_docs"] == 110
    assert probe["top100_lift_vs_default"] == 7
    assert probe["top500_lift_vs_default"] == 0
    assert probe["production_adoption"] is False

    assert gap["no_fitting_constraints"] == {
        "truth_label_used_for_ordering": False,
        "scenario_or_owner_metadata_used_for_ordering": False,
        "phase1_rank_used_for_ordering": False,
        "top_features_used_for_ordering": False,
        "q95_gate_changed": False,
        "vae_score_or_threshold_changed": False,
    }


def test_v31_unsupervised_companion_surface_metrics_locked():
    companion = _payload()["surface_metrics_by_role"]["companion"]

    native = companion["native_row_queue"]["topn"]
    assert native["500"]["matched_docs"] == 34
    assert native["10000"]["matched_docs"] == 225

    soft = companion["hybrid_with_soft_repeated_normal_guard"]
    assert soft["topn"]["100"]["matched_docs"] == 1
    assert soft["topn"]["500"]["matched_docs"] == 33
    assert soft["topn"]["10000"]["matched_docs"] == 275
    assert soft["top500_pressure"]["repeated_normal_pressure"] == 0.478

    upper = companion["hybrid_row_count_blended_surface_upper_bound"]
    assert upper["topn"]["500"]["matched_docs"] == 135
    assert upper["top500_pressure"]["repeated_normal_pressure"] == 0.634


def test_v31_unsupervised_decision_and_leak_guard_locked():
    payload = _payload()

    assert payload["decision"] == {
        "best_defensive_companion_surface": "hybrid_with_soft_repeated_normal_guard",
        "primary_top500_lift_vs_native": 87,
        "companion_top500_lift_vs_native": -1,
        "production_default_adoption": True,
        "adoption_note": (
            "soft guard is adopted as the default family-list display ordering "
            "for v3.1 primary-oriented document review priority"
        ),
        "q95_gate_change_recommended": False,
        "top_features_used_for_ranking": False,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    text = json.dumps(payload, ensure_ascii=False)
    assert "DOC-" not in text
    assert "TRUTH-" not in text
    assert "p2_unsupervised_" not in text


def test_v31_unsupervised_adoption_readiness_locked():
    readiness = _payload()["adoption_readiness"]

    assert readiness["default_native_ordering_unchanged"] is False
    assert (
        readiness["soft_guard_role"]
        == "v31_primary_oriented_default_document_review_priority"
    )
    assert readiness["product_default_adoption"] is True
    assert readiness["primary_top100_native"] == 12
    assert readiness["primary_top100_soft_guard"] == 24
    assert readiness["primary_top500_native"] == 23
    assert readiness["primary_top500_soft_guard"] == 110
    assert readiness["companion_top500_native"] == 34
    assert readiness["companion_top500_soft_guard"] == 33
    assert readiness["companion_top500_improved"] is False
    assert readiness["monitoring_guardrails"] == [
        "repeated-normal pressure requires monitoring",
        "period-end normal background requires monitoring",
        "account/process concentration requires monitoring",
        "single-row high amount normal proxy requires monitoring",
        "companion TOP500 does not improve",
    ]
    assert readiness["monitoring_metrics"] == {
        "primary_native_repeated_normal_pressure_top500": 0.818,
        "primary_soft_guard_repeated_normal_pressure_top500": 0.336,
        "primary_soft_guard_period_end_normal_background_top500": 0.578,
        "primary_soft_guard_account_top1_share_top500": 0.14396887159533073,
        "primary_soft_guard_process_top1_share_top500": 0.35797665369649806,
        "primary_soft_guard_single_row_high_amount_normal_proxy_top500": 0.0,
    }
