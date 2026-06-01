from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.scripts import (
    measure_phase2_family_responsibility_recall_v22_fixed5_relmeta_20260530 as m22,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (
    ROOT
    / "artifacts"
    / "phase2_family_responsibility_recall_v22_fixed5_relmeta_20260530.json"
)
NORMAL_TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_normalcal5",
    "labels",
    "manipulated_entry_truth.csv",
)
RELMETA_TRUTH_CSV = ROOT.joinpath(
    "data",
    "journal",
    "primary",
    "datasynth_manipulation_v7_candidate_fixed5_relmeta",
    "labels",
    "manipulated_entry_truth.csv",
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


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


def test_v22_relationship_sidecar_unlocks_relational_primary_denominator():
    payload = _payload()
    metadata = payload["relationship_truth_metadata"]

    assert metadata["status"] == "available"
    assert metadata["primary_denominator_status"] == (
        "available_from_datasynth_relationship_edge_truth"
    )
    assert metadata["schema_version"] == "relationship_edge_truth_v1"
    assert metadata["source"].endswith("labels/relationship_edge_truth.csv")
    assert metadata["primary_target_doc_count"] == 63
    assert metadata["secondary_target_doc_count"] == 76
    assert metadata["context_target_doc_count"] == 0
    assert metadata["primary_semantic_group_counts"] == {
        "approval_sod_bypass": 29,
        "related_party_loop": 34,
    }
    assert metadata["secondary_semantic_group_counts"] == {
        "employee_payment_relationship": 76,
    }
    assert metadata["policy"] == {
        "truth_label_used_for_detector_scoring": False,
        "truth_label_used_for_ranking": False,
        "truth_metadata_used_only_for_denominator": True,
        "r05_r06_promoted_to_primary": False,
        "co_primary_allowed": True,
        "co_primary_with": ["intercompany"],
    }


def test_v22_sidecar_missing_keeps_v21_relational_fallback():
    payload = m22.build_payload(
        truth_csv=NORMAL_TRUTH_CSV,
        dataset_name="datasynth_manipulation_v7_candidate_fixed5_normalcal5",
    )

    assert payload["relationship_truth_metadata"]["status"] == "metadata_unavailable"
    assert payload["relational_primary_denominator_status"] == (
        "pending_explicit_relationship_primary_semantics"
    )
    assert payload["owner_role_distribution"]["relational"]["primary"] == 0
    assert payload["owner_role_distribution"]["relational"]["secondary"] == 139
    assert payload["primary_owner_target_recall"]["relational"] == {
        "primary_truth_docs": 0,
        "matched_primary_docs": 0,
        "primary_target_recall": None,
    }


def test_v22_circular_is_ic_and_relational_co_primary():
    payload = _payload()
    roles = payload["owner_role_distribution"]
    co_primary = payload["relational_co_primary_policy"]

    assert roles["intercompany"]["primary"] == 34
    assert roles["relational"]["primary"] == 63
    assert co_primary["primary_owner_exclusive"] is False
    assert co_primary["co_primary_allowed"] is True
    assert co_primary["co_primary_with"] == ["intercompany"]
    assert co_primary["co_primary_overlap_count"] == 34
    assert co_primary["co_primary_overlap_group"] == {
        "circular_related_party_transaction": 34,
    }
    assert co_primary["portfolio_recall_double_counted"] is False
    assert payload["ambiguity"]["multi_primary"] == 63


def test_v22_relational_primary_and_secondary_recall_metrics():
    payload = _payload()
    primary = payload["primary_owner_target_recall"]
    detail = payload["relational_primary_recall_detail"]
    companion = payload["companion_context_recall"]

    assert primary["intercompany"] == {
        "primary_truth_docs": 34,
        "matched_primary_docs": 34,
        "primary_target_recall": 1.0,
    }
    assert primary["relational"] == {
        "primary_truth_docs": 63,
        "matched_primary_docs": 9,
        "primary_target_recall": 9 / 63,
    }
    assert detail["relational_primary_truth_docs"] == 63
    assert detail["relational_primary_matched_docs"] == 9
    assert detail["relational_primary_recall"] == 9 / 63
    assert detail["relational_primary_top100_matched_docs"] == 4
    assert detail["relational_primary_top500_matched_docs"] == 9
    assert detail["relational_primary_outside_PHASE1_immediate"] == 57
    assert detail["relational_primary_outside_PHASE1_review_or_higher"] == 47
    assert detail["relational_primary_outside_PHASE1_candidate_or_higher"] == 1

    assert companion["relational_secondary_truth_docs"] == 76
    assert companion["relational_secondary_matched_docs"] == 8
    assert companion["relational_secondary_recall"] == 8 / 76


def test_v22_relationship_sidecar_rejects_invalid_role(tmp_path: Path):
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    truth_csv = labels_dir / "manipulated_entry_truth.csv"
    pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "manipulation_scenario": ["approval_sod_bypass"],
            "manipulation_subtype": ["approval"],
            "reference_pattern": ["approval_sod_bypass:approval"],
            "business_process": ["R2R"],
            "source": ["manual"],
            "document_type": ["SA"],
            "posting_date": ["2024-12-31"],
            "line_amount": [1000],
            "line_count": [2],
        }
    ).to_csv(truth_csv, index=False)
    pd.DataFrame(
        {
            "document_id": ["DOC-1"],
            "relationship_edge_role": ["bad_role"],
            "relationship_edge_semantic_group": ["approval_sod_bypass"],
            "relationship_edge_type": ["self_approval_or_approval_route_edge"],
            "relationship_evidence_intent": ["self_approval_or_sod_bypass_edge"],
            "is_primary_target": [True],
            "is_secondary_target": [False],
            "is_context_target": [False],
        }
    ).to_csv(labels_dir / "relationship_edge_truth.csv", index=False)

    with pytest.raises(ValueError, match="invalid relationship_edge_role"):
        m22.build_payload(truth_csv=truth_csv, dataset_name="bad_relmeta")


def test_v22_raw_leak_guard_and_no_production_path_change():
    payload = _payload()
    truth_ids = pd.read_csv(RELMETA_TRUTH_CSV)["document_id"].astype(str).tolist()
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

    assert payload["production_ranking_gate_fusion_changed"] is False
    assert payload["fixed4_used"] is False
    assert payload["fitting_leakage_guard"]["raw_identifier_leak_count"] == 0
    assert payload["fitting_leakage_guard"]["forbidden_identifier_key_count"] == 0
    assert payload["fitting_leakage_guard"]["phase2_case_id_like_token_count"] == 0
    assert all(raw_id not in text for raw_id in truth_ids)
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["fitting_leakage_guard"]["owner_assignment_detector_output_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_score_rank_inspection"] == (
        "not_used_by_construction"
    )
    assert payload["fitting_leakage_guard"]["owner_assignment_matched_result_inspection"] == (
        "not_used_by_construction"
    )
