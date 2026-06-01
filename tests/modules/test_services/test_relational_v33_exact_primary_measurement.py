from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "relational_v33_exact_primary_measurement_20260531.json"
RESPONSIBILITY_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.json"
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _responsibility() -> dict:
    return json.loads(RESPONSIBILITY_ARTIFACT.read_text(encoding="utf-8"))


def test_relational_v33_exact_measurement_contract():
    payload = _payload()

    assert payload["metadata"]["dataset"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b"
    )
    assert payload["metadata"]["adopted_surface"] == (
        "structural_moderate_audit_then_business_lane_split_surface"
    )
    assert payload["metadata"]["production_ordering_changed"] is False
    assert payload["metadata"]["production_gate_changed"] is False
    assert payload["metadata"]["phase1_ranking_changed"] is False
    assert payload["metadata"]["phase2_fusion_changed"] is False
    assert payload["metadata"]["truth_used_for_scoring"] is False
    assert payload["denominators"] == {
        "relational_primary": 20,
        "relational_companion": 119,
    }
    assert payload["runtime"]["bounded_or_cached_fallback_used"] is False
    assert payload["runtime"]["timeout_observed"] is False


def test_relational_v33_current_vs_adopted_exact_primary_recall():
    surfaces = _payload()["surfaces"]

    current = surfaces["current_native"]["topn"]
    assert current["top100"]["primary"]["matched_docs"] == 0
    assert current["top500"]["primary"]["matched_docs"] == 0
    assert current["top1000"]["primary"]["matched_docs"] == 0
    assert surfaces["current_native"]["rank_band_diagnostic"][
        "primary_doc_first_rank_bands"
    ] == {
        "top100": 0,
        "rank101_500": 0,
        "rank501_1000": 0,
        "gt1000": 20,
    }

    adopted = surfaces["structural_moderate_audit_then_business_lane_split_surface"][
        "topn"
    ]
    assert adopted["top100"]["primary"]["matched_docs"] == 0
    assert adopted["top500"]["primary"]["matched_docs"] == 13
    assert adopted["top500"]["primary"]["recall"] == 0.65
    assert adopted["top500"]["primary"]["by_truth_owner_subtype"] == {
        "employee_vendor_hidden_relationship": 13
    }
    assert adopted["top1000"]["primary"]["matched_docs"] == 20
    assert adopted["top1000"]["primary"]["recall"] == 1.0
    assert surfaces["structural_moderate_audit_then_business_lane_split_surface"][
        "rank_band_diagnostic"
    ]["primary_doc_first_rank_bands"] == {
        "top100": 0,
        "rank101_500": 13,
        "rank501_1000": 7,
        "gt1000": 0,
    }


def test_relational_v33_employee_vendor_profile_surface_is_diagnostic_only():
    surface = _payload()["surfaces"]["employee_vendor_observable_profile_surface"]
    topn = surface["topn"]

    assert surface["product_adoption_allowed"] is False
    assert "synthetic_shortcut_risk" in surface
    assert topn["top100"]["primary"]["matched_docs"] == 20
    assert topn["top100"]["primary"]["recall"] == 1.0
    assert topn["top500"]["companion"]["matched_docs"] == 16
    assert topn["top500"]["sub_rule_distribution"] == {
        "R01": 95,
        "R05": 372,
        "R07": 33,
    }
    assert surface["rank_band_diagnostic"]["primary_doc_first_rank_bands"] == {
        "top100": 20,
        "rank101_500": 0,
        "rank501_1000": 0,
        "gt1000": 0,
    }


def test_relational_v33_exact_companion_recall_and_rule_mix():
    adopted = _payload()["surfaces"][
        "structural_moderate_audit_then_business_lane_split_surface"
    ]["topn"]

    assert adopted["top100"]["companion"]["matched_docs"] == 6
    assert adopted["top500"]["companion"]["matched_docs"] == 21
    assert adopted["top500"]["companion"]["recall"] == 21 / 119
    assert adopted["top1000"]["companion"]["matched_docs"] == 52
    assert adopted["top1000"]["companion"]["recall"] == 52 / 119
    assert adopted["top500"]["sub_rule_distribution"] == {
        "R01": 248,
        "R02": 2,
        "R07": 250,
    }


def test_relational_v33_responsibility_artifact_was_updated_from_proration():
    responsibility = _responsibility()
    relational = responsibility["primary_owner_target_recall_v33"]["relational"]["topn"]
    companion = responsibility["companion_context_contribution_v33"][
        "relational_companion"
    ]["topn"]

    assert relational["top500"]["status"] == "available_exact_matched_doc_join"
    assert relational["top500"]["matched_docs"] == 13
    assert relational["top500"]["matched_docs_estimated_proration"] is None
    assert relational["top1000"]["matched_docs"] == 20
    assert companion["top500"]["status"] == "available_exact_matched_doc_join"
    assert companion["top500"]["matched_docs"] == 21
    assert responsibility["relational_v33_exact_measurement"] == {
        "artifact": "relational_v33_exact_primary_measurement_20260531.json",
        "current_native_top500_primary": 0,
        "adopted_top500_primary": 13,
        "adopted_top500_companion": 21,
        "diagnostic_top100_candidate_artifact": (
            "relational_v33_exact_primary_measurement_20260531.json"
        ),
        "diagnostic_candidate_product_adoption": False,
        "production_ordering_changed": False,
        "truth_used_for_scoring": False,
    }


def test_relational_v33_no_fitting_and_raw_leak_guard():
    payload = _payload()

    assert payload["no_fitting_contract"] == {
        "truth_label_used_for_scoring": False,
        "owner_metadata_used_for_scoring": False,
        "owner_metadata_used_for_denominator_and_exact_join_only": True,
        "selector_uses_detector_output_only": True,
        "production_ranking_changed": False,
        "threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
