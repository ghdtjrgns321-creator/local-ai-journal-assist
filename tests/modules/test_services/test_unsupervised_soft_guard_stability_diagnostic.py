"""Smoke tests for fixed5 soft guard slice stability diagnostic."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_soft_guard_stability_fixed5_20260530.json"
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


def test_soft_guard_stability_policy_and_decision_are_locked():
    payload = _payload()

    assert payload["primary_validation_dataset"] == "fixed5_normalcal5"
    assert payload["excluded_validation_datasets"] == {
        "fixed4": "known-broken DataSynth; excluded from adoption validation"
    }
    assert payload["diagnostic_only"] is True
    assert payload["truth_label_used_for_scoring"] is False
    assert payload["truth_label_used_only_for_aggregate_evaluation"] is True
    assert payload["q95_gate_changed"] is False
    assert payload["vae_score_or_threshold_changed"] is False
    assert payload["phase1_ranking_changed"] is False
    assert payload["phase2_fusion_changed"] is False
    assert payload["native_row_case_ordering_changed"] is False
    assert payload["slice_count"] == 74

    decision = payload["decision"]
    assert decision["best_defensive_surface"] == "hybrid_with_soft_repeated_normal_guard"
    assert decision["secondary_surface"] == "soft_guard_with_row_count_context"
    assert decision["upper_bound_surface"] == "hybrid_row_count_blended_surface_upper_bound"
    assert decision["adoption_candidate"] is True
    assert decision["production_adoption"] is False
    assert decision["repeated_normal_pressure_stable"] is False
    assert decision["evidence_quality_ready"] is True


def test_soft_guard_surface_stability_core_values_are_locked():
    stability = _payload()["surface_stability"]

    soft = stability["hybrid_with_soft_repeated_normal_guard"]
    assert soft["slice_count"] == 74
    assert soft["slices_current_or_better_top500"] == 74
    assert soft["slices_pressure_below_native"] == 65
    assert soft["slices_pressure_below_0_30"] == 3
    assert soft["worst_slice_top500_recall"] == 0
    assert soft["worst_slice_pressure"] == 1.0
    assert soft["best_slice_top500_recall"] == 150

    context = stability["soft_guard_with_row_count_context"]
    assert context["slices_current_or_better_top500"] == 74
    assert context["slices_pressure_below_native"] == 63
    assert context["best_slice_top500_recall"] == 200

    upper = stability["hybrid_row_count_blended_surface_upper_bound"]
    assert upper["slices_pressure_below_native"] == 48
    assert upper["slices_pressure_below_0_30"] == 0
    assert upper["best_slice_top500_recall"] == 246

    pressure_guard = stability["pressure_guard_surface"]
    assert pressure_guard["slices_current_or_better_top500"] == 54
    assert pressure_guard["slices_pressure_below_native"] == 74
    assert pressure_guard["best_slice_top500_recall"] == 91


def test_soft_guard_q95_backlog_slice_stability_is_locked():
    q95 = _payload()["q95_backlog_slice_stability"]

    assert q95["q95_gate_change_recommended"] is False
    assert q95["q95_backlog_concentration"] == 0.13138686131386862
    values = list(q95["q95_miss_truth_docs_by_slice"].values())
    assert max(item["q95_miss_truth_docs"] for item in values) == 90
    assert max(item["near_q95_truth_docs"] for item in values) == 33
    assert max(item["strong_document_context_truth_docs"] for item in values) == 14
    assert all("document_id" not in item for item in values)


def test_soft_guard_slice_metric_schema_is_present():
    payload = _payload()
    slice_metrics = payload["slice_metrics"]

    for surface in (
        "native_row_queue",
        "hybrid_with_soft_repeated_normal_guard",
        "soft_guard_with_row_count_context",
        "hybrid_row_count_blended_surface_upper_bound",
        "pressure_guard_surface",
    ):
        assert surface in slice_metrics
        sample = next(iter(slice_metrics[surface].values()))
        assert {"100", "500", "1000", "10000"}.issubset(sample["topn"])
        assert "repeated_normal_pressure" in sample
        assert "account_concentration" in sample
        assert "process_concentration" in sample
        assert "period_end_normal_background_ratio" in sample
        assert "single_row_high_amount_ratio" in sample
        assert "top_features_available_case_count" in sample
        assert "top_features_available_truth_docs" in sample
        assert "top_feature_evidence_added_truth_docs" in sample


def test_soft_guard_stability_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert all(document_id not in text for document_id in _truth_doc_ids())
    banned_keys = {
        "document" "_id",
        "document" "_ids",
        "r" "aw" "_document" "_id",
        "row" "_id",
        "row" "_ids",
        "r" "aw" "_row" "_id",
        "index" "_label",
        "r" "aw" "_index" "_label",
        "phase2" "_case" "_id",
        "phase2" "_case" "_ids",
    }
    assert banned_keys.isdisjoint({key.lower() for key in _walk_keys(payload)})
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
