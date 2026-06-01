from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "relational_v33d_exact_primary_measurement_20260601.json"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_relational_v33d_adopted_surface_primary_profile():
    payload = _payload()
    adopted = payload["surfaces"]["structural_moderate_audit_then_business_lane_split_surface"]

    assert payload["metadata"]["dataset"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d"
    )
    assert payload["denominators"]["relational_primary"] == 23
    assert adopted["topn"]["top100"]["primary"]["matched_docs"] == 0
    assert adopted["topn"]["top500"]["primary"]["matched_docs"] == 15
    assert adopted["topn"]["top1000"]["primary"]["matched_docs"] == 23
    assert adopted["rank_band_diagnostic"]["primary_doc_first_rank_bands"] == {
        "top100": 0,
        "rank101_500": 15,
        "rank501_1000": 8,
        "gt1000": 0,
    }


def test_relational_v33d_employee_vendor_profile_is_not_product_adopted():
    surface = _payload()["surfaces"]["employee_vendor_observable_profile_surface"]

    assert surface["product_adoption_allowed"] is False
    assert surface["topn"]["top100"]["primary"]["matched_docs"] == 23
    assert surface["topn"]["top500"]["sub_rule_distribution"] == {
        "R01": 94,
        "R05": 373,
        "R07": 33,
    }
    assert surface["synthetic_shortcut_risk"].startswith("medium_high")


def test_relational_v33d_no_fitting_contract():
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
