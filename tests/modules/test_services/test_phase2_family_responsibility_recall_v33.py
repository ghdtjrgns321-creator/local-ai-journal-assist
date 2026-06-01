from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.json"
)
TS_ADOPTION_ARTIFACT = ROOT / "artifacts" / "timeseries_product_adoption_v33_20260601.json"
V32_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v32_fixed5_ownermeta_v32d_20260531.json"
)
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b",
    "labels",
    "manipulated_entry_truth.csv",
)
DOCS = [
    ROOT / "docs" / "debugging" / "PHASE2_FAMILY_RESPONSIBILITY_RECALL_20260530.md",
    ROOT / "docs" / "users" / "16_PHASE2_RESPONSIBILITY_MAP_DECISION.md",
    ROOT / "docs" / "TROUBLESHOOT.md",
    ROOT / "docs" / "DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md",
]


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _ts_adoption_payload() -> dict:
    return json.loads(TS_ADOPTION_ARTIFACT.read_text(encoding="utf-8"))


def _truth_rows() -> list[dict[str, str]]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _walk_keys(value) -> list[str]:
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


def test_v33_artifact_exists_and_metadata_contract():
    payload = _payload()

    assert ARTIFACT.exists()
    assert V32_ARTIFACT.exists()
    assert payload["metadata"]["owner_metadata_version"] == "v3.3b"
    assert payload["metadata"]["candidate_name"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33b"
    )
    assert payload["metadata"]["current_canonical_candidate"] is True
    assert payload["metadata"]["fixed4_used"] is False
    assert payload["metadata"]["production_ranking_changed"] is False
    assert payload["metadata"]["production_gate_changed"] is False
    assert payload["metadata"]["production_fusion_changed"] is False
    assert payload["metadata"]["detector_outputs_used_for_owner_assignment"] is False


def test_v33_primary_denominator_exact_lock():
    denominators = _payload()["primary_denominators_v33"]

    assert denominators["phase1"] == 483
    assert denominators["intercompany"] == 34
    assert denominators["relational"] == 20
    assert denominators["duplicate"] == 22
    assert denominators["timeseries"] == 21
    assert denominators["unsupervised"] == 40
    assert denominators["status"]["relational"] == "available"
    assert denominators["status"]["duplicate"] == "available"


def test_v33_companion_denominator_exact_lock():
    assert _payload()["companion_context_denominators_v33"] == {
        "relational_companion": 119,
        "duplicate_companion": 71,
        "timeseries_context": 92,
        "statistical_companion": 404,
    }


def test_v33_semantic_group_exact_locks():
    checks = _payload()["data_quality_and_policy_checks"]

    assert checks["relationship_primary_semantic_group_counts"] == {
        "employee_vendor_hidden_relationship": 20
    }
    assert checks["duplicate_primary_semantic_group_counts"] == {
        "time_shifted_duplicate": 22
    }
    assert checks["fictitious_subtype_counts"] == {
        "fictitious_account_policy": 50,
        "fictitious_period_end_like": 41,
        "fictitious_existence_statistical": 40,
        "fictitious_duplicate_like": 37,
    }


def test_v33_circular_is_ic_primary_and_relationship_companion_not_relational_primary():
    rows = _truth_rows()
    circular = [
        row for row in rows if row["manipulation_scenario"] == "circular_related_party_transaction"
    ]

    assert len(circular) == 34
    assert all(row["injected_intercompany_primary"] == "true" for row in circular)
    assert all(row["relationship_companion_target"] == "true" for row in circular)
    assert all(row["relationship_primary_target"] == "false" for row in circular)
    assert _payload()["overlap_matrix"]["ic_relational_primary_overlap"] == 0


def test_v33_suspense_policy_override_is_phase1_primary_and_statistical_companion():
    checks = _payload()["data_quality_and_policy_checks"]

    assert checks["suspense_policy_override_count"] == 100
    assert checks["suspense_in_phase1_primary_count"] == 100
    assert checks["suspense_in_unsupervised_primary_count"] == 0
    assert checks["suspense_in_statistical_companion_count"] == 100


def test_v33_ts_stabilized_surface_is_product_default_with_native_debug_fallback():
    lock = _payload()["product_ordering_lock_v33"]["timeseries"]

    assert lock["primary_denominator"] == 21
    assert lock["period_end_context_docs"] == 92
    assert lock["period_end_context_used_as_primary"] is False
    assert lock["native_debug_baseline"] == {
        "top100_matched_docs": 0,
        "top500_matched_docs": 0,
        "top100_recall": 0.0,
        "top500_recall": 0.0,
        "status": "historical_debug_fallback_not_product_result",
    }
    assert lock["product_default_ordering"]["status"] == "product_default_ordering_adopted"
    assert (
        lock["product_default_ordering"]["ordering_strategy"]
        == "ts_specific_top100_stabilized_surface"
    )
    assert lock["product_default_ordering"]["top100_matched_docs"] == 21
    assert lock["product_default_ordering"]["top500_matched_docs"] == 21
    assert lock["product_default_ordering"]["top100_recall"] == 1.0
    assert lock["product_default_ordering"]["top500_recall"] == 1.0
    assert lock["adoption_decision"]["status"] == "adopted_product_default_ordering"
    assert (
        lock["adoption_decision"]["previous_source_artifact_status"]
        == "diagnostic_candidate_not_product_default"
    )
    assert lock["product_default_adoption_allowed"] is True
    assert lock["production_default_ordering_changed"] is True


def test_v33_ts_adoption_artifact_locks_selector_guardrails():
    payload = _ts_adoption_payload()

    assert payload["adopted_ordering_strategy"] == "ts_specific_top100_stabilized_surface"
    assert payload["native_fallback_strategy"] == "native"
    assert payload["primary_denominator"] == 21
    assert payload["period_end_context_docs"] == 92
    assert payload["period_end_context_used_as_primary"] is False
    assert payload["product_default_result"]["top100_matched_docs"] == 21
    assert payload["product_default_result"]["top500_matched_docs"] == 21
    assert payload["native_debug_baseline"]["top100_matched_docs"] == 0
    assert payload["native_debug_baseline"]["top500_matched_docs"] == 0
    assert payload["decision"]["production_adoption"] is True
    assert payload["decision"]["production_default_ordering_changed"] is True
    selector = payload["selector_input_policy"]
    assert selector["truth_label_used"] is False
    assert selector["scenario_label_used"] is False
    assert selector["owner_metadata_used"] is False
    assert selector["phase1_rank_used"] is False
    assert selector["matched_result_used"] is False
    assert selector["raw_identifier_used"] is False
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_v33_primary_recall_measurement_modes():
    recall = _payload()["primary_owner_target_recall_v33"]

    assert recall["relational"]["topn"]["top500"]["status"] == (
        "available_exact_matched_doc_join"
    )
    assert recall["relational"]["topn"]["top500"]["matched_docs"] == 13
    assert recall["relational"]["topn"]["top500"]["recall"] == 13 / 20
    assert recall["duplicate"]["topn"]["top500"]["status"] == (
        "estimated_proration_exact_join_required"
    )
    assert recall["unsupervised"]["topn"]["top500"]["status"] == (
        "available_exact_native_join"
    )
    assert recall["unsupervised"]["topn"]["top500"]["matched_docs"] == 7
    assert recall["unsupervised"]["topn"]["top500"]["recall"] == 7 / 40


def test_v33_data_quality_and_leakage_guards():
    payload = _payload()
    checks = payload["data_quality_and_policy_checks"]

    assert checks["truth_docs"] == 620
    assert checks["anomaly_label_docs"] == 620
    assert checks["journal_rows"] == 1_034_269
    assert checks["journal_docs"] == 318_653
    assert checks["journal_columns"] == 53
    assert checks["new_owner_truth_flags_in_journal_columns"] == []
    assert all(checks["expected_denominator_counts_match"].values())
    assert checks["owner_assignment_uses_detector_output_score_rank_topn_matched_result"] is False
    assert checks["historical_artifacts_retained"] is True
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_v33_raw_identifier_keys_and_values_are_not_emitted():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "raw_document_id",
        "row_id",
        "raw_row_id",
        "phase2_case_id",
        "phase2_case_ids",
        "relationship_group_id",
        "duplicate_pair_group_id",
        "relationship_source_entity",
        "relationship_target_entity",
    }

    assert all(row["document_id"] not in text for row in _truth_rows())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})


def test_v33_docs_mark_candidate_and_v32_historical():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)

    assert "v3.3d = current canonical responsibility map candidate" in combined
    assert "v3.3b = historical responsibility map" in combined
    assert "v3.2d = historical responsibility map" in combined
    assert "relational primary 20" in combined
    assert "duplicate primary 22" in combined
    assert "VAE primary 40" in combined
    assert "diagnostic candidate" in combined
