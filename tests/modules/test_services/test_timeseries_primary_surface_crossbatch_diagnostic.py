"""Tests for TS family Phase 5 fixed5 primary-surface diagnostic artifact."""

from __future__ import annotations

import csv
import inspect
import json
from pathlib import Path
from typing import Any

from tools.scripts import diagnose_timeseries_primary_surface_crossbatch_20260530 as diag

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_primary_surface_crossbatch_20260530.json"
TRUTH_ROOT = ROOT / "data" / "journal" / "primary"


def _payload() -> dict[str, Any]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


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


def _truth_doc_ids(dataset: str) -> list[str]:
    path = TRUTH_ROOT / dataset / "labels" / "manipulated_entry_truth.csv"
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [row["document_id"] for row in csv.DictReader(fh)]


def test_phase5_contract_and_guardrails():
    payload = _payload()

    assert set(payload["batches"]) == {"fixed5_normalcal5"}
    assert payload["primary_validation_dataset"] == "fixed5_normalcal5"
    assert payload["excluded_validation_datasets"] == ["fixed4"]
    assert (
        payload["exclusion_reason"]
        == "known-broken DataSynth baseline; not used for product adoption"
    )
    assert payload["guardrails"] == {
        "truth_label_used_for_policy_order": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "scenario_label_used_for_policy_order": False,
        "production_gate_ranking_fusion_changed": False,
        "phase1_ranking_changed": False,
        "broad_companion_and_ts_primary_separated": True,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    assert payload["ts_aligned_scenarios"] == [
        "period_end_adjustment_manipulation",
        "unusual_timing_manipulation",
    ]


def test_candidate_policy_order_does_not_accept_truth_inputs():
    signature = inspect.signature(diag._candidate_policies)

    assert tuple(signature.parameters) == ("windows",)
    assert "truth_docs" not in signature.parameters
    assert "scenario_by_doc" not in signature.parameters
    assert "phase1_reference" not in signature.parameters


def test_phase5_fixed5_primary_surface_metrics():
    payload = _payload()
    fixed5 = payload["batches"]["fixed5_normalcal5"]["policies"]

    current = fixed5["current_native_ts_order"]["topn"]
    assert current["100"]["ts_aligned_not_in_phase1_top100"] == 0
    assert current["500"]["ts_aligned_not_in_phase1_top100"] == 0

    fixed5_timing = fixed5["timing_primary_context_surface"]["topn"]
    assert fixed5_timing["100"]["ts_aligned_not_in_phase1_top100"] == 0
    assert fixed5_timing["500"]["ts_aligned_not_in_phase1_top100"] == 32
    assert fixed5_timing["1000"]["ts_aligned_not_in_phase1_top100"] == 32

    fixed5_conservative = fixed5["ts_primary_conservative_surface"]["topn"]
    assert fixed5_conservative["100"]["ts_aligned_not_in_phase1_top100"] == 13
    assert fixed5_conservative["500"]["ts_aligned_not_in_phase1_top100"] == 32
    assert fixed5["ts_primary_conservative_surface"]["baseline_available_ratio"] == 1.0
    assert fixed5["ts_primary_conservative_surface"]["one_row_support_ratio"] == 0.0
    assert fixed5["ts_primary_conservative_surface"]["low_support_ratio"] == 0.0


def test_phase5_broad_companion_is_separate_from_ts_primary():
    payload = _payload()
    fixed5_broad = payload["batches"]["fixed5_normalcal5"]["policies"][
        "broad_companion_reference_surface"
    ]["topn"]

    assert fixed5_broad["100"]["truth_docs_not_in_phase1_top100"] == 108
    assert fixed5_broad["100"]["ts_aligned_not_in_phase1_top100"] == 2
    assert fixed5_broad["500"]["ts_aligned_not_in_phase1_top100"] == 32


def test_phase5_slice_stability_and_decision_payload():
    decision = _payload()["decision"]

    assert decision["primary_validation_dataset"] == "fixed5_normalcal5"
    assert decision["excluded_validation_datasets"] == ["fixed4"]
    assert decision["best_ts_primary_candidate"] == "ts_primary_conservative_surface"
    assert decision["best_broad_companion_candidate"] == "broad_companion_reference_surface"
    assert decision["top100_adoption_allowed"] is False
    assert decision["top500_companion_allowed"] is True
    assert decision["production_adoption"] is False
    assert "TOP500 companion potential" in decision["adoption_blocker"]
    stability = decision["fixed5_slice_stability"]["by_policy"]
    conservative = stability["ts_primary_conservative_surface"]
    assert conservative["eligible_slice_count"] == 8
    assert conservative["top100_eligible_nonempty_rate"] == 0.75
    assert conservative["top500_eligible_nonempty_rate"] == 1.0
    assert conservative["year_top100_eligible_nonempty_rate"] == 2 / 3
    assert stability["current_native_ts_order"]["top500_eligible_nonempty_rate"] == 0.0


def test_phase5_fixed5_slice_metrics_are_recorded():
    slices = _payload()["batches"]["fixed5_normalcal5"]["slice_stability"]

    year = slices["year"]
    assert set(year) == {"2022", "2023", "2024"}
    assert year["2022"]["ts_primary_conservative_surface"]["topn"]["100"][
        "ts_aligned_not_in_phase1_top100"
    ] == 6
    assert year["2023"]["ts_primary_conservative_surface"]["topn"]["100"][
        "ts_aligned_not_in_phase1_top100"
    ] == 18
    assert year["2024"]["ts_primary_conservative_surface"]["topn"]["100"][
        "ts_aligned_not_in_phase1_top100"
    ] == 0
    assert year["2024"]["ts_primary_conservative_surface"]["topn"]["500"][
        "ts_aligned_not_in_phase1_top100"
    ] == 8
    assert year["2022"]["ts_primary_conservative_surface"]["baseline_available_ratio"] == 1.0
    assert year["2022"]["ts_primary_conservative_surface"]["one_row_support_ratio"] == 0.1


def test_phase5_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    truth_doc_ids: list[str] = []
    for batch in payload["batches"].values():
        truth_doc_ids.extend(_truth_doc_ids(batch["dataset"]))

    assert truth_doc_ids
    assert all(document_id not in text for document_id in truth_doc_ids)
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
    assert forbidden_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert "p2_timeseries_window_" not in text
