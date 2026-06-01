from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.scripts import measure_phase2_family_responsibility_recall_v2_fixed5_20260530 as m
from tools.scripts import measure_phase2_family_responsibility_recall_v21_fixed5_20260530 as m21

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "phase2_family_responsibility_recall_v2_fixed5_20260530.json"
V21_ARTIFACT = (
    ROOT / "artifacts" / "phase2_family_responsibility_recall_v21_fixed5_20260530.json"
)
V1_ARTIFACT = ROOT / "artifacts" / "phase2_family_responsibility_recall_fixed5_20260530.json"
TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
    "labels",
    "manipulated_entry_truth.csv",
)
DUPMETA_TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_dupmeta",
    "labels",
    "manipulated_entry_truth.csv",
)
DUPMETA_PAIR_TRUTH_CSV = DUPMETA_TRUTH_CSV.parent / "duplicate_pair_truth.csv"
DUPMETA_MANIFEST = (
    DUPMETA_TRUTH_CSV.parents[1] / "MANIPULATION_V7_DATASET_MANIFEST.json"
)
DEBUG_DOC = ROOT / "docs" / "debugging" / "PHASE2_FAMILY_RESPONSIBILITY_RECALL_20260530.md"
DECISION_DOC = ROOT / "docs" / "users" / "16_PHASE2_RESPONSIBILITY_MAP_DECISION.md"
TROUBLESHOOT_DOC = ROOT / "docs" / "TROUBLESHOOT.md"
PHASE2_RESULT_DOC = ROOT / "docs" / "DETECTION_RESULTS_MANIPULATION_V7_FIXED4_PHASE2.md"


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _payload_v21() -> dict:
    return json.loads(V21_ARTIFACT.read_text(encoding="utf-8"))


def _truth_ids() -> list[str]:
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


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


def test_v1_and_v2_artifacts_are_both_retained():
    payload = _payload()

    assert V1_ARTIFACT.exists()
    assert ARTIFACT.exists()
    assert payload["v1_artifact_retained"] is True
    assert payload["fixed4_used"] is False
    assert payload["production_ranking_gate_fusion_changed"] is False


def test_owner_roles_schema_accepts_expected_roles_and_rejects_bad_no_owner_mix():
    assignment = m.OwnerAssignmentV2(
        truth_case_hash="truth_test",
        expected_owners=["phase1", "timeseries"],
        owner_roles={"phase1": "baseline_review", "timeseries": "primary"},
        scenario_groups=["timing"],
        owner_confidence="high",
        no_clear_owner_reason="none",
        assignment_basis=["scenario_metadata"],
        audit_rationale="role schema test",
    )
    assert assignment.expected_owners == ["phase1", "timeseries"]
    assert assignment.owner_roles["phase1"] == "baseline_review"
    assert assignment.owner_roles["timeseries"] == "primary"

    with pytest.raises(ValueError):
        m.OwnerAssignmentV2(
            truth_case_hash="truth_bad",
            expected_owners=["no_clear_owner", "phase1"],
            owner_roles={"no_clear_owner": "no_clear_owner", "phase1": "baseline_review"},
            scenario_groups=["bad"],
            owner_confidence="low",
            no_clear_owner_reason="mixed_signal",
            assignment_basis=["scenario_metadata"],
            audit_rationale="invalid mix",
        )


def test_owner_role_distribution_separates_primary_from_context_and_baseline():
    payload = _payload()
    roles = payload["owner_role_distribution"]

    assert roles["phase1"]["primary"] == 397
    assert roles["phase1"]["baseline_review"] == 223
    assert roles["intercompany"]["primary"] == 34
    assert roles["relational"]["primary"] == 29
    assert roles["relational"]["secondary"] == 110
    assert roles["duplicate"]["primary"] == 0
    assert roles["duplicate"]["companion_context"] == 92
    assert roles["timeseries"]["primary"] == 21
    assert roles["timeseries"]["companion_context"] == 92
    assert roles["unsupervised"]["primary"] == 168
    assert roles["unsupervised"]["companion_context"] == 121


def test_primary_and_inclusive_recall_are_separated():
    payload = _payload()
    primary = payload["primary_owner_target_recall"]
    inclusive = payload["inclusive_owner_recall"]

    assert primary["intercompany"] == {
        "primary_truth_docs": 34,
        "matched_primary_docs": 34,
        "primary_target_recall": 1.0,
    }
    assert primary["duplicate"] == {
        "primary_truth_docs": 0,
        "matched_primary_docs": 0,
        "primary_target_recall": None,
    }
    assert primary["timeseries"]["primary_truth_docs"] == 21
    assert primary["timeseries"]["matched_primary_docs"] == 0
    assert primary["unsupervised"]["primary_truth_docs"] == 168
    assert primary["unsupervised"]["matched_primary_docs"] == 20

    assert inclusive["duplicate"]["inclusive_truth_docs"] == 92
    assert inclusive["duplicate"]["matched_inclusive_docs"] == 22
    assert inclusive["timeseries"]["inclusive_truth_docs"] == 113
    assert inclusive["phase1"]["inclusive_truth_docs"] == 620
    assert inclusive["phase1"]["matched_inclusive_docs"] == 544


def test_timeseries_period_end_is_companion_context_not_primary():
    payload = _payload()

    assert payload["timeseries_role_lock_alignment"] == {
        "period_end_adjustment_timeseries_primary_count": 0,
        "timeseries_primary_limited_to_timing_only": True,
        "period_end_adjustment_role": "companion_context",
    }
    assert payload["owner_role_distribution"]["timeseries"]["primary"] == 21
    assert payload["owner_role_distribution"]["timeseries"]["companion_context"] == 92


def test_duplicate_primary_metadata_insufficient_when_explicit_label_absent():
    payload = _payload()

    assert payload["duplicate_metadata_gap"] == {
        "duplicate_primary_denominator_status": "metadata_insufficient",
        "duplicate_primary_count": 0,
        "metadata_gap": [
            "injected_duplicate_like boolean needed",
            "duplicate_pair_semantic_group needed",
            "reference/amount/text similarity injection source needed",
        ],
    }
    assert payload["ambiguity"]["review_needed"] == 92
    assert payload["ambiguity"]["low_confidence"] == 92


def test_evidence_contribution_separates_secondary_and_companion_roles():
    payload = _payload()
    evidence = payload["evidence_contribution"]

    assert evidence["relational"]["matched_primary_docs"] == 0
    assert evidence["relational"]["matched_secondary_docs"] == 17
    assert evidence["duplicate"]["matched_primary_docs"] == 0
    assert evidence["duplicate"]["matched_companion_context_docs"] == 22
    assert evidence["unsupervised"]["matched_primary_docs"] == 20
    assert evidence["unsupervised"]["matched_companion_context_docs"] == 19


def test_v2_raw_leak_guard_and_no_detector_score_rank_matched_use():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "document_ids",
        "raw_document_id",
        "raw_document_ids",
        "row_id",
        "row_ids",
        "raw_row_id",
        "raw_row_ids",
        "index_label",
        "raw_index_label",
        "phase2_case_id",
        "phase2_case_ids",
    }

    assert all(raw_id not in text for raw_id in _truth_ids())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["fitting_leakage_guard"]["raw_identifier_leak_count"] == 0
    assert payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] == 0
    assert payload["fitting_leakage_guard"]["phase2_case_id_like_token_count"] == 0
    assert payload["fitting_leakage_guard"]["owner_assignment_detector_output_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_score_rank_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_matched_result_inspection"] == (
        "not_used_by_construction"
    )


def test_v21_artifact_keeps_v1_and_v2_baselines():
    payload = _payload_v21()

    assert V1_ARTIFACT.exists()
    assert ARTIFACT.exists()
    assert V21_ARTIFACT.exists()
    assert payload["v1_artifact_retained"] is True
    assert payload["v2_artifact_retained"] is True
    assert payload["fixed4_used"] is False
    assert payload["production_ranking_gate_fusion_changed"] is False
    assert payload["labeling_metadata"]["mode"] == "deterministic_rule_only_v21"
    assert payload["labeling_metadata"]["policy_model"] == (
        "audit_rule_first_evidence_companion"
    )


def test_v21_audit_rule_first_role_distribution_changes_from_v2():
    v2 = _payload()
    v21 = _payload_v21()
    roles = v21["owner_role_distribution"]

    assert roles["phase1"]["primary"] == 565
    assert roles["phase1"]["baseline_review"] == 55
    assert roles["relational"]["primary"] == 0
    assert roles["relational"]["secondary"] == 139
    assert roles["unsupervised"]["primary"] == 0
    assert roles["unsupervised"]["companion_context"] == 289
    assert roles["timeseries"]["primary"] == 21
    assert roles["timeseries"]["companion_context"] == 92

    assert v2["owner_role_distribution"]["relational"]["primary"] == 29
    assert v2["owner_role_distribution"]["unsupervised"]["primary"] == 168


def test_v21_policy_guards_for_fictitious_approval_and_period_end_roles():
    payload = _payload_v21()
    assignments = payload["owner_assignments"]

    fictitious = [
        item
        for item in assignments
        if "revenue_or_activity_existence_context" in item["scenario_groups"]
    ]
    assert fictitious
    assert all(item["owner_roles"]["phase1"] == "primary" for item in fictitious)
    assert all(
        item["owner_roles"]["unsupervised"] == "companion_context"
        for item in fictitious
    )

    approval = [
        item
        for item in assignments
        if "user_approval_relationship_context" in item["scenario_groups"]
    ]
    assert approval
    assert all(item["owner_roles"]["phase1"] == "primary" for item in approval)
    assert all(item["owner_roles"]["relational"] != "primary" for item in approval)
    assert all(item["owner_roles"]["relational"] == "secondary" for item in approval)

    period_end = [
        item for item in assignments if "manual_adjustment_context" in item["scenario_groups"]
    ]
    assert period_end
    assert all(item["owner_roles"]["timeseries"] == "companion_context" for item in period_end)
    assert all(item["owner_roles"]["duplicate"] == "companion_context" for item in period_end)


def test_v21_primary_recall_and_metadata_gap_policy():
    payload = _payload_v21()
    primary = payload["primary_owner_target_recall"]

    assert primary["phase1"] == {
        "primary_truth_docs": 565,
        "matched_primary_docs": 490,
        "primary_target_recall": 0.8672566371681416,
    }
    assert primary["relational"] == {
        "primary_truth_docs": 0,
        "matched_primary_docs": 0,
        "primary_target_recall": None,
    }
    assert primary["unsupervised"] == {
        "primary_truth_docs": 0,
        "matched_primary_docs": 0,
        "primary_target_recall": None,
    }
    assert primary["timeseries"]["primary_truth_docs"] == 21
    assert payload["unsupervised_primary_denominator_status"] == (
        "pending_explicit_broad_statistical_only_metadata"
    )
    assert payload["duplicate_metadata_gap"]["duplicate_primary_denominator_status"] == (
        "metadata_insufficient"
    )
    assert payload["ambiguity"]["multi_primary"] == 0
    assert payload["multi_primary_overlap_cases"] == []


def test_v21_pending_status_and_phase1_confidence_split():
    payload = _payload_v21()
    split = payload["phase1_primary_confidence_split"]

    assert payload["relational_primary_denominator_status"] == (
        "pending_explicit_relationship_primary_semantics"
    )
    assert split["phase1_primary_truth_docs"] == 565
    assert split["phase1_primary_high_medium_confidence_truth_docs"] == 473
    assert split["phase1_primary_low_confidence_truth_docs"] == 92
    assert (
        split["phase1_primary_high_medium_confidence_truth_docs"]
        + split["phase1_primary_low_confidence_truth_docs"]
        == split["phase1_primary_truth_docs"]
    )
    assert split["phase1_primary_low_confidence_reason"] == (
        "period_end_adjustment companion/metadata uncertainty"
    )


def test_v21_companion_context_recall_is_separate_from_primary_recall():
    payload = _payload_v21()
    companion = payload["companion_context_recall"]

    assert "companion_context_recall" in payload
    assert "companion_context_recall" not in payload["primary_owner_target_recall"]
    assert companion["metric_role"] == (
        "evidence_companion_lifecycle_not_primary_target_recall"
    )
    assert companion["product_default_adoption_basis"] == "not_standalone"
    assert companion["relational_secondary_truth_docs"] == 139
    assert companion["relational_secondary_matched_docs"] == 17
    assert companion["relational_secondary_recall"] == 17 / 139
    assert companion["duplicate_companion_truth_docs"] == 92
    assert companion["duplicate_companion_matched_docs"] == 22
    assert companion["duplicate_companion_recall"] == 22 / 92
    assert companion["timeseries_companion_truth_docs"] == 92
    assert companion["timeseries_companion_matched_docs"] == 0
    assert companion["timeseries_companion_recall"] == 0.0
    assert companion["unsupervised_companion_truth_docs"] == 289
    assert companion["unsupervised_companion_matched_docs"] == 39
    assert companion["unsupervised_companion_recall"] == 39 / 289


def test_v21_pending_trigger_conditions_are_documented():
    combined_docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [DEBUG_DOC, DECISION_DOC, TROUBLESHOOT_DOC, PHASE2_RESULT_DOC]
    )

    assert "explicit relationship-primary injected semantics" in combined_docs
    assert "R-family detector spec" in combined_docs
    assert "injected_duplicate_like" in combined_docs
    assert "duplicate_pair_semantic_group" in combined_docs
    assert "similarity injection source" in combined_docs
    assert "broad_statistical_only owner metadata" in combined_docs
    assert "period_end 92" in combined_docs
    assert "phase1 primary 565는 responsibility taxonomy" in combined_docs


def test_fixed5_dupmeta_duplicate_truth_metadata_contract():
    import pandas as pd

    truth = pd.read_csv(DUPMETA_TRUTH_CSV)
    pair_truth = pd.read_csv(DUPMETA_PAIR_TRUTH_CSV)
    manifest = json.loads(DUPMETA_MANIFEST.read_text(encoding="utf-8"))

    primary = m21._truth_bool_series(truth["duplicate_primary_target"])
    companion = m21._truth_bool_series(truth["duplicate_companion_target"])
    injected = m21._truth_bool_series(truth["injected_duplicate_like"])
    period_end = truth["manipulation_scenario"].astype(str).eq(
        "period_end_adjustment_manipulation"
    )

    assert len(truth) == 620
    assert truth["document_id"].astype(str).nunique() == 620
    assert int(injected.sum()) == 76
    assert truth.loc[primary, "document_id"].astype(str).nunique() == 76
    assert truth.loc[companion, "document_id"].astype(str).nunique() == 0
    assert truth.loc[primary & period_end, "document_id"].astype(str).nunique() == 0
    assert truth.loc[primary].groupby("manipulation_scenario")[
        "document_id"
    ].nunique().to_dict() == {"embezzlement_concealment": 76}
    assert len(pair_truth) == 76
    assert pair_truth["document_id"].astype(str).nunique() == 76
    assert pair_truth["duplicate_pair_group_id"].astype(str).nunique() == 38
    assert pair_truth.groupby("duplicate_pair_group_id")[
        "document_id"
    ].nunique().value_counts().sort_index().to_dict() == {2: 38}
    assert "family_truth_metadata_policy" in manifest
    assert "sidecar_use" in manifest["family_truth_metadata_policy"]


def test_v21_dupmeta_unlocks_duplicate_primary_denominator_without_ranking_input():
    payload = m21.build_payload(
        truth_csv=DUPMETA_TRUTH_CSV,
        dataset_name="datasynth_manipulation_v7_candidate_fixed5_dupmeta",
    )
    metadata = payload["duplicate_truth_metadata"]

    assert metadata["status"] == "available"
    assert metadata["primary_denominator_status"] == "available"
    assert metadata["primary_target_doc_count"] == 76
    assert metadata["companion_target_doc_count"] == 0
    assert metadata["period_end_primary_target_doc_count"] == 0
    assert metadata["primary_scenario_counts"] == {"embezzlement_concealment": 76}
    assert metadata["pair_sidecar_row_count"] == 76
    assert metadata["pair_sidecar_truth_doc_count"] == 76
    assert metadata["pair_group_count"] == 38
    assert metadata["pair_group_size_distribution"] == {"2": 38}
    assert metadata["policy"] == {
        "truth_label_used_for_detector_scoring": False,
        "truth_label_used_for_ranking": False,
        "truth_metadata_used_only_for_denominator": True,
        "period_end_promoted_to_duplicate_primary": False,
    }

    assert payload["owner_role_distribution"]["duplicate"]["primary"] == 76
    assert payload["owner_role_distribution"]["duplicate"]["companion_context"] == 92
    assert payload["primary_owner_target_recall"]["duplicate"] == {
        "primary_truth_docs": 76,
        "matched_primary_docs": 0,
        "primary_target_recall": 0.0,
    }
    assert payload["companion_context_recall"]["duplicate_companion_truth_docs"] == 92
    assert payload["companion_context_recall"]["duplicate_companion_matched_docs"] == 22
    assert payload["fitting_leakage_guard"]["raw_identifier_leak_count"] == 0
    assert payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] == 0
    assert payload["fitting_leakage_guard"]["phase2_case_id_like_token_count"] == 0


def test_v21_raw_leak_guard_and_no_detector_score_rank_matched_use():
    payload = _payload_v21()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "document_ids",
        "raw_document_id",
        "raw_document_ids",
        "row_id",
        "row_ids",
        "raw_row_id",
        "raw_row_ids",
        "index_label",
        "raw_index_label",
        "phase2_case_id",
        "phase2_case_ids",
    }

    assert all(raw_id not in text for raw_id in _truth_ids())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["fitting_leakage_guard"]["raw_identifier_leak_count"] == 0
    assert payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] == 0
    assert payload["fitting_leakage_guard"]["phase2_case_id_like_token_count"] == 0
    assert m21.RULE_VERSION == "phase2_family_responsibility_owner_role_rules_v21_20260530"
    assert payload["fitting_leakage_guard"]["owner_assignment_detector_output_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_score_rank_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_matched_result_inspection"] == (
        "not_used_by_construction"
    )
