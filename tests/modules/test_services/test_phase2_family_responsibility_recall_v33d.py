from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json"
)
V33B_ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v33_fixed5_ownermeta_v33b_20260531.json"
)
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d",
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


def test_v33d_artifact_exists_and_metadata_contract():
    payload = _payload()

    assert ARTIFACT.exists()
    assert V33B_ARTIFACT.exists()
    assert payload["metadata"]["owner_metadata_version"] == "v3.3d"
    assert payload["metadata"]["candidate_name"] == (
        "datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d"
    )
    assert payload["metadata"]["policy_model"] == (
        "audit_rule_first_v33d_owner_metadata_with_suspense_override"
    )
    assert payload["metadata"]["fixed4_used"] is False
    assert payload["metadata"]["production_ranking_changed"] is False
    assert payload["metadata"]["production_gate_changed"] is False
    assert payload["metadata"]["production_fusion_changed"] is False
    assert payload["metadata"]["detector_outputs_used_for_owner_assignment"] is False


def test_v33d_primary_denominator_exact_lock():
    denominators = _payload()["primary_denominators_v33d"]

    assert denominators["phase1"] == 483
    assert denominators["intercompany"] == 34
    assert denominators["relational"] == 23
    assert denominators["duplicate"] == 19
    assert denominators["timeseries"] == 21
    assert denominators["unsupervised"] == 40
    assert denominators["status"]["relational"] == "available"
    assert denominators["status"]["duplicate"] == "available"


def test_v33d_companion_denominator_exact_lock():
    assert _payload()["companion_context_denominators_v33d"] == {
        "relational_companion": 116,
        "duplicate_companion": 71,
        "timeseries_context": 92,
        "statistical_companion": 404,
    }


def test_v33d_semantic_and_shortcut_locks():
    checks = _payload()["data_quality_and_policy_checks"]

    assert checks["relationship_primary_semantic_group_counts"] == {
        "employee_vendor_hidden_relationship": 23
    }
    assert checks["duplicate_primary_semantic_group_counts"] == {
        "time_shifted_duplicate": 19
    }
    assert checks["fictitious_subtype_counts"]["fictitious_existence_statistical"] == 40
    assert checks["new_owner_truth_flags_in_journal_columns"] == []


def test_v33d_circular_is_ic_primary_and_relationship_companion_not_relational_primary():
    rows = _truth_rows()
    circular = [
        row for row in rows if row["manipulation_scenario"] == "circular_related_party_transaction"
    ]

    assert len(circular) == 34
    assert all(row["injected_intercompany_primary"] == "true" for row in circular)
    assert all(row["relationship_companion_target"] == "true" for row in circular)
    assert all(row["relationship_primary_target"] == "false" for row in circular)
    assert _payload()["overlap_matrix"]["ic_relational_primary_overlap"] == 0


def test_v33d_suspense_policy_override_is_phase1_primary_and_statistical_companion():
    checks = _payload()["data_quality_and_policy_checks"]

    assert checks["suspense_policy_override_count"] == 100
    assert checks["suspense_in_phase1_primary_count"] == 100
    assert checks["suspense_in_unsupervised_primary_count"] == 0
    assert checks["suspense_in_statistical_companion_count"] == 100


def test_v33d_ts_product_default_is_stabilized_surface_not_native():
    lock = _payload()["product_ordering_lock_v33d"]["timeseries"]

    assert lock["primary_denominator"] == 21
    assert lock["period_end_context_docs"] == 92
    assert lock["period_end_context_used_as_primary"] is False
    assert "native_product_default" not in lock
    assert "diagnostic_candidate" not in lock
    assert lock["product_default"]["ordering_strategy"] == (
        "ts_specific_top100_stabilized_surface"
    )
    assert lock["product_default"]["status"] == (
        "product_default_ordering_strategy_ts_specific_top100_stabilized_surface"
    )
    assert lock["product_default"]["top100_matched_docs"] == 21
    assert lock["product_default"]["top500_matched_docs"] == 21
    assert lock["debug_native_baseline"]["status"] == (
        "debug_only_previous_ordering_not_user_facing"
    )
    assert lock["product_default_adoption_allowed"] is True
    assert lock["production_default_ordering_changed"] is True


def test_v33d_primary_recall_uses_exact_native_join():
    recall = _payload()["primary_owner_target_recall_v33d"]

    assert recall["relational"]["denominator"] == 23
    assert recall["duplicate"]["denominator"] == 19
    assert recall["unsupervised"]["denominator"] == 40
    for family in ("relational", "duplicate", "unsupervised"):
        assert recall[family]["topn"]["top500"]["status"] == (
            "available_exact_v33d_native_join"
        )
        assert recall[family]["topn"]["top500"]["measurement_basis"] == (
            "exact_v33d_matched_doc_join"
        )


def test_v33d_failure_modes_are_separated_by_family():
    payload = _payload()
    modes = payload["family_failure_mode_diagnostics_v33d"]["families"]

    assert modes["intercompany"]["failure_mode"] == "fully_surfaced_top500"
    assert modes["intercompany"]["case_count"] == 246
    assert modes["intercompany"]["top500_matched_docs"] == 34
    assert modes["intercompany"]["primary_denominator"] == 34
    assert modes["intercompany"]["root_cause_status"] == (
        "resolved_in_v33d_full_run"
    )
    assert modes["relational"]["failure_mode"] == "cases_produced_not_surfaced_top500"
    assert modes["relational"]["case_count"] > 0
    assert modes["unsupervised"]["failure_mode"] == "cases_produced_not_surfaced_top500"
    assert modes["duplicate"]["failure_mode"] == "partially_surfaced_top500"
    assert "shortcut removal" in payload["family_failure_mode_diagnostics_v33d"][
        "shortcut_and_scale_note"
    ]


def test_v33d_data_quality_and_leakage_guards():
    payload = _payload()
    checks = payload["data_quality_and_policy_checks"]

    assert checks["truth_docs"] == 620
    assert checks["anomaly_label_docs"] == 620
    assert checks["journal_rows"] == 1_034_269
    assert checks["journal_docs"] == 318_653
    assert checks["journal_columns"] == 53
    assert all(checks["expected_denominator_counts_match"].values())
    assert checks["owner_assignment_uses_detector_output_score_rank_topn_matched_result"] is False
    assert checks["historical_artifacts_retained"] is True
    assert payload["native_measurement_metadata_v33d"]["truth_documents_present_in_journal"] == 620
    assert payload["native_measurement_metadata_v33d"]["truth_documents_missing_from_journal"] == 0
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_v33d_raw_identifier_keys_and_values_are_not_emitted():
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


def test_v33d_docs_mark_candidate_and_v33b_historical():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)

    assert "v3.3d = current canonical responsibility map candidate" in combined
    assert "v3.3b = historical responsibility map" in combined
    assert "relational primary 23" in combined
    assert "duplicate primary 19" in combined
    assert "VAE primary 40" in combined
    assert "shortcut token hits in journal = 0" in combined
    assert "fully_surfaced_top500" in combined
    assert "cases_produced_not_surfaced_top500" in combined
