"""Smoke checks for the fixed5 Intercompany incremental-value diagnostic."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "intercompany_incremental_value_fixed5_20260529.json"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)


def _payload() -> dict[str, Any]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


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


def test_intercompany_incremental_diagnostic_separates_phase1_all_and_topn():
    payload = _payload()
    baseline = payload["phase1_baseline"]
    uplift = payload["topn_uplift"]

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    assert payload["truth_document_count"] == 620
    assert baseline["all_truth_document_count"] == 544
    assert baseline["top100_truth_document_count"] == 0
    assert baseline["top500_truth_document_count"] == 50
    assert baseline["top1000_truth_document_count"] == 87
    assert uplift["phase1_all_truth_document_coverage"] == 544
    assert uplift["phase1_top100_truth_document_coverage"] == 0
    assert uplift["phase1_top500_truth_document_coverage"] == 50
    assert uplift["phase1_top1000_truth_document_coverage"] == 87


def test_intercompany_topn_uplift_fields_are_locked():
    uplift = _payload()["topn_uplift"]

    assert uplift["ic_top100_truth_not_in_phase1_top100"] == 34
    assert uplift["ic_top500_truth_not_in_phase1_top500"] == 34
    assert uplift["ic_top1000_truth_not_in_phase1_top1000"] == 32
    assert uplift["net_truth_uplift_vs_phase1_top100"] == 34
    assert uplift["net_truth_uplift_vs_phase1_top500"] == -16
    assert uplift["net_truth_uplift_vs_phase1_top1000"] == -53


def test_intercompany_evidence_incremental_breakdown_is_locked():
    evidence = _payload()["evidence_incremental"]

    top100 = evidence["100"]
    assert top100["ic_evidence_added_truth_docs"] == 34
    assert top100["ic_evidence_added_case_count"] == 34
    assert top100["reciprocal_flow_evidence_added_truth_docs"] == 34
    assert top100["amount_mismatch_evidence_added_truth_docs"] == 0
    assert top100["paired_row_ref_truth_docs"] == 34
    assert top100["counterparty_pair_truth_docs"] == 34
    assert top100["amount_symmetry_truth_docs"] == 34
    assert top100["phase2_specific_ic_reason_truth_docs"] == 34
    assert top100["ic_role_distribution"] == {
        "amount_mismatch": 66,
        "reciprocal_flow": 34,
    }

    top500 = evidence["500"]
    assert top500["phase1_only_generic_reason_truth_docs"] == 50
    assert top500["ic_role_distribution"] == {
        "amount_mismatch": 212,
        "reciprocal_flow": 34,
    }


def test_intercompany_explanation_and_decision_payload_are_locked():
    payload = _payload()
    explanation = payload["explanation_incremental"]
    decision = payload["decision"]

    assert explanation["100"]["truth_scenario_counts"] == {
        "circular_related_party_transaction": 34,
    }
    assert explanation["100"]["ic_truth_with_phase1_generic_or_non_ic_reason"] == 1
    assert explanation["100"]["ic_truth_with_phase1_ic_or_related_reason"] == 33
    assert explanation["500"]["phase1_topn_truth_docs_without_ic_surface"] == 50
    assert explanation["1000"]["ic_truth_docs_not_in_phase1_topn"] == 32

    assert decision["document_inclusion_incremental_value"] == (
        "reported_separately_not_decision_basis"
    )
    assert decision["topn_uplift_value"] == "medium"
    assert decision["evidence_incremental_value"] == "high"
    assert decision["explanation_incremental_value"] == "high"
    assert decision["primary_product_role"] == "ic_specific_evidence_strengthening"
    assert decision["broad_recall_expansion_family"] is False
    assert decision["production_ranking_changed"] is False
    assert decision["new_policy_adopted"] is False
    assert decision["adopted_default_allowed"] is False
    assert "does not disable" in decision["production_adoption_interpretation"]


def test_intercompany_existing_success_lock_and_fitting_guard_are_preserved():
    payload = _payload()

    assert payload["ic_native_success_lock"] == {
        "case_count": 246,
        "top100_circular_truth_docs": 34,
        "circular_scenario_truth_coverage": "34/34",
    }
    assert payload["fitting_guard"] == {
        "truth_used_for_ordering": False,
        "scenario_used_for_ordering": False,
        "ic_gate_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "production_ranking_changed": False,
        "new_policy_adopted": False,
        "raw_identifiers_emitted": False,
    }


def test_intercompany_incremental_diagnostic_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden_keys = {
        "document_id",
        "raw_document_id",
        "row_id",
        "raw_row_id",
        "phase2_case_id",
        "counterparty_id",
        "raw_counterparty_id",
    }

    assert all(doc_id not in text for doc_id in _truth_doc_ids())
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
        "counterparty_raw_id_like_key_count": 0,
    }
