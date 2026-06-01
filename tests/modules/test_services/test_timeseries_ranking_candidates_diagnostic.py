"""Smoke tests for fixed5 TS diagnostic-only ranking candidate artifact."""

from __future__ import annotations

import csv
import inspect
import json
import re
from pathlib import Path

from tools.scripts import diagnose_timeseries_ranking_candidates_fixed5_20260529 as ts_diag

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_ranking_candidates_fixed5_20260529.json"
TRUTH_CSV = (
    ROOT
    / "data"
    / "journal"
    / "primary"
    / "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    / "labels"
    / "manipulated_entry_truth.csv"
)


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_timeseries_ranking_candidates_artifact_contract():
    payload = _payload()

    assert payload["dataset"] == "datasynth_manipulation_v7_candidate_fixed5_normalcal5"
    assert payload["case_count"] == 861
    assert payload["truth_document_count"] == 620
    assert set(payload["candidates"]) == {
        "current_native_ts_ordering",
        "robust_z_context_composite",
        "period_end_lift_robust_balanced",
        "period_end_normalized_mixed_signal",
        "subject_activity_rank_adjusted",
        "robust_context_baseline_sufficiency",
        "mixed_signal_period_end_demoted",
        "non_period_end_surprise_priority",
        "ts01_ts02_balanced_surface",
        "review_burden_penalized_context",
        "review_burden_closing_demoted_context",
    }
    assert all("Truth labels are used only" in note for note in payload["guardrails"][1:2])
    assert payload["candidate_weight_provenance"] == {
        "label": "fixed5 exploratory diagnostic weights",
        "calibration_status": "not calibrated",
        "production_policy": "not production ranking policy",
        "adoption_requirement": "requires cross-batch/fixture validation before adoption",
    }
    assert any("not production ranking policy" in note for note in payload["guardrails"])
    assert payload["no_fitting_assertions"] == {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_ranking_changed": False,
        "threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
    }
    assert "feature_diagnostics" in payload


def test_timeseries_ranking_candidates_record_topn_and_first_truth_rank():
    candidates = _payload()["candidates"]

    expected = {
        "current_native_ts_ordering": {
            "top100": 0,
            "top500": 0,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 762,
        },
        "robust_z_context_composite": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 300,
        },
        "period_end_lift_robust_balanced": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 359,
        },
        "period_end_normalized_mixed_signal": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 328,
        },
        "subject_activity_rank_adjusted": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 323,
        },
        "robust_context_baseline_sufficiency": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 295,
        },
        "mixed_signal_period_end_demoted": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 381,
        },
        "non_period_end_surprise_priority": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 445,
        },
        "ts01_ts02_balanced_surface": {
            "top100": 0,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 335,
        },
        "review_burden_penalized_context": {
            "top100": 8,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 76,
        },
        "review_burden_closing_demoted_context": {
            "top100": 8,
            "top500": 8,
            "top1000": 8,
            "top10000": 8,
            "first_truth_rank": 98,
        },
    }
    for candidate, metrics in expected.items():
        actual = candidates[candidate]
        assert actual["topn"]["100"]["matched"] == metrics["top100"]
        assert actual["topn"]["500"]["matched"] == metrics["top500"]
        assert actual["topn"]["1000"]["matched"] == metrics["top1000"]
        assert actual["topn"]["10000"]["matched"] == metrics["top10000"]
        assert actual["first_truth_rank"] == metrics["first_truth_rank"]

    assert candidates["current_native_ts_ordering"]["topn"]["500"]["matched"] == 0
    assert candidates["current_native_ts_ordering"]["first_truth_rank"] == 762
    assert candidates["robust_z_context_composite"]["topn"]["500"]["matched"] == 8
    assert candidates["robust_z_context_composite"]["first_truth_rank"] == 300
    assert candidates["period_end_normalized_mixed_signal"]["topn"]["500"]["matched"] == 8
    assert candidates["period_end_normalized_mixed_signal"]["first_truth_rank"] == 328


def test_timeseries_ranking_candidates_record_context_profiles():
    candidates = _payload()["candidates"]
    robust = candidates["robust_z_context_composite"]
    current = candidates["current_native_ts_ordering"]
    burden_penalized = candidates["review_burden_penalized_context"]
    burden_demoted = candidates["review_burden_closing_demoted_context"]

    assert current["top500_distribution"]["mixed_period_end_context_count"] == 14
    assert robust["top500_distribution"]["mixed_period_end_context_count"] == 32
    assert robust["new_top500_context_profile"]["new_case_count"] == 229
    assert robust["top500_new_case_count_vs_current"] == 229
    assert "robust_z_distribution" in robust["new_top500_context_profile"]
    assert "period_end_lift_distribution" in robust["new_top500_context_profile"]
    assert "context_evidence_count_distribution" in robust["new_top500_context_profile"]
    assert "daily_expected_ratio_distribution" in robust["new_top500_context_profile"]
    assert burden_penalized["top500_distribution"]["subject_concentration"][
        "top1_share"
    ] < current["top500_distribution"]["subject_concentration"]["top1_share"]
    assert burden_penalized["top500_distribution"]["false_positive_pressure_proxy"][
        "score"
    ] < current["top500_distribution"]["false_positive_pressure_proxy"]["score"]
    assert burden_penalized["top500_new_case_count_vs_current"] == 250
    assert burden_demoted["top500_new_case_count_vs_current"] == 248
    assert burden_demoted["top500_distribution"]["false_positive_pressure_proxy"][
        "score"
    ] < burden_penalized["top500_distribution"]["false_positive_pressure_proxy"]["score"]
    assert burden_demoted["top500_distribution"]["normal_closing_spike_proxy"]["count"] == 16
    assert burden_demoted["top500_distribution"]["period_end_context"]["true"] == 25


def test_timeseries_candidate_scoring_does_not_accept_truth_inputs():
    score_sig = inspect.signature(ts_diag._candidate_score)
    order_sig = inspect.signature(ts_diag._candidate_order)

    assert tuple(score_sig.parameters) == ("candidate", "case")
    assert tuple(order_sig.parameters) == ("cases", "candidate")
    assert "truth_docs" not in score_sig.parameters
    assert "scenario_by_doc" not in score_sig.parameters


def _walk_json_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_keys(child)


def _walk_json_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_values(child)
    elif isinstance(value, str):
        yield value


def test_timeseries_ranking_candidates_do_not_emit_raw_identifiers():
    payload = _payload()
    artifact_text = json.dumps(payload, ensure_ascii=False)
    with TRUTH_CSV.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        truth_doc_ids = [row["document_id"] for row in reader]

    assert truth_doc_ids
    assert all(document_id not in artifact_text for document_id in truth_doc_ids)
    all_keys = {str(key) for key in _walk_json_keys(payload)}
    all_values = list(_walk_json_values(payload))
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
    assert forbidden_keys.isdisjoint(all_keys)
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }

    raw_identifier_key_pattern = re.compile(
        r'"(?:raw_)?(?:document_id|document_ids|row_id|row_ids|index_label|phase2_case_id|phase2_case_ids)"\s*:'
    )
    assert raw_identifier_key_pattern.search(artifact_text) is None
    assert not any(value.startswith("p2_timeseries_window_") for value in all_values)
    assert re.search(r"p2_timeseries_window_[0-9a-f]{10}", artifact_text) is None
