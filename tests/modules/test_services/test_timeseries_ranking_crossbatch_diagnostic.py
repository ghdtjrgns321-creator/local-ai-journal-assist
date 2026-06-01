"""Smoke tests for cross-batch TS diagnostic-only ranking candidate artifact."""

from __future__ import annotations

import csv
import inspect
import json
from pathlib import Path
from typing import Any

from tools.scripts import diagnose_timeseries_ranking_crossbatch_20260529 as crossbatch

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "timeseries_ranking_crossbatch_20260529.json"
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


def test_crossbatch_artifact_contract_and_guardrails():
    payload = _payload()

    assert set(payload["batches"]) == {"fixed3", "fixed4", "fixed5_normalcal5"}
    assert payload["no_fitting_assertions"] == {
        "truth_label_used_for_scoring": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_ranking_changed": False,
        "threshold_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
    }
    assert payload["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "phase2_case_id_like_token_count": 0,
    }
    assert payload["retention_policy_provenance"] == {
        "label": "cross-batch exploratory diagnostic retention policies",
        "calibration_status": "not calibrated",
        "production_policy": "not production artifact retention policy",
        "adoption_requirement": "requires additional fixture/DataSynth validation before adoption",
    }
    assert payload["retention_no_fitting_assertions"] == {
        "truth_label_used_for_retention_order": False,
        "truth_label_used_only_for_aggregate_evaluation": True,
        "production_artifact_retention_changed": False,
        "detector_artifact_cap_changed": False,
        "ts01_candidate_generation_changed": False,
    }


def test_crossbatch_records_ranking_gap_vs_artifact_coverage_gap():
    payload = _payload()

    fixed3 = payload["batches"]["fixed3"]["truth_coverage_flow"]
    fixed4 = payload["batches"]["fixed4"]["truth_coverage_flow"]
    fixed5 = payload["batches"]["fixed5_normalcal5"]["truth_coverage_flow"]

    assert fixed3["flagged_truth_document_count"] == 13
    assert fixed3["native_case_truth_document_count"] == 0
    assert fixed3["ranking_can_improve"] is False
    assert fixed3["primary_gap"] == "artifact_truth_coverage_gap"

    assert fixed4["flagged_truth_document_count"] == 13
    assert fixed4["native_case_truth_document_count"] == 0
    assert fixed4["ranking_can_improve"] is False
    assert fixed4["primary_gap"] == "artifact_truth_coverage_gap"

    assert fixed5["flagged_truth_document_count"] == 13
    assert fixed5["native_case_truth_document_count"] == 8
    assert fixed5["ranking_can_improve"] is True
    assert fixed5["primary_gap"] == "ranking_gap"


def test_crossbatch_records_artifact_retention_candidate_gap():
    payload = _payload()

    for batch_name in ("fixed3", "fixed4"):
        retention = payload["batches"][batch_name]["truth_coverage_flow"][
            "artifact_retention_diagnostic"
        ]["by_rule"]
        ts01 = retention["TS01"]
        ts02 = retention["TS02"]

        assert ts01["candidate_window_count"] == 4761
        assert ts01["candidate_truth_window_count"] == 3
        assert ts01["current_cap500_truth_window_count"] == 0
        assert ts01["current_cap500_truth_document_count"] == 0
        assert ts01["score_desc_cap500_truth_window_count"] == 3
        assert ts01["score_desc_cap500_truth_document_count"] == 13
        assert ts01["period_end_score_cap500_truth_window_count"] == 3
        assert ts01["period_end_score_cap500_truth_document_count"] == 13
        assert (
            ts01["period_end_score_low_support_demoted_cap500_truth_window_count"] == 3
        )
        assert (
            ts01["period_end_score_low_support_demoted_cap500_truth_document_count"]
            == 13
        )
        assert ts01["truth_window_period_end_context_count"] == 3
        assert ts01["truth_window_ordinal_distribution"]["min"] == 705.0
        assert ts01["truth_window_ordinal_distribution"]["max"] == 2284.0

        assert ts02["candidate_truth_window_count"] == 0
        assert ts02["score_desc_cap500_truth_window_count"] == 0

    fixed5_ts01 = payload["batches"]["fixed5_normalcal5"]["truth_coverage_flow"][
        "artifact_retention_diagnostic"
    ]["by_rule"]["TS01"]
    assert fixed5_ts01["candidate_truth_window_count"] == 3
    assert fixed5_ts01["current_cap500_truth_window_count"] == 1
    assert fixed5_ts01["current_cap500_truth_document_count"] == 8
    assert fixed5_ts01["period_end_score_cap500_truth_window_count"] == 3
    assert fixed5_ts01["period_end_score_cap500_truth_document_count"] == 13
    assert fixed5_ts01["period_end_score_low_support_demoted_cap500_truth_window_count"] == 3
    assert fixed5_ts01["period_end_score_low_support_demoted_cap500_truth_document_count"] == 13


def test_crossbatch_retention_surface_topn_and_burden_proxy():
    payload = _payload()

    for batch_name in ("fixed3", "fixed4", "fixed5_normalcal5"):
        surfaces = payload["batches"][batch_name]["truth_coverage_flow"][
            "artifact_retention_diagnostic"
        ]["by_rule"]["TS01"]["retention_surface_topn"]
        low_support = surfaces["period_end_score_low_support_demoted_cap500"]
        period_end = surfaces["period_end_score_cap500"]

        assert low_support["top500_truth_document_count"] == 13
        assert low_support["top500_truth_window_count"] == 3
        assert low_support["top500_review_burden_proxy"]["low_row_support_share"] == 0.0
        assert low_support["top500_review_burden_proxy"]["score"] < period_end[
            "top500_review_burden_proxy"
        ]["score"]

    fixed5_low_support = payload["batches"]["fixed5_normalcal5"]["truth_coverage_flow"][
        "artifact_retention_diagnostic"
    ]["by_rule"]["TS01"]["retention_surface_topn"][
        "period_end_score_low_support_demoted_cap500"
    ]
    assert fixed5_low_support["top100_truth_document_count"] == 13


def test_retention_policy_order_does_not_accept_truth_inputs():
    signature = inspect.signature(crossbatch._retention_policy_order)

    assert tuple(signature.parameters) == ("windows", "policy")
    assert "truth_docs" not in signature.parameters
    assert "scenario_by_doc" not in signature.parameters

    windows = [
        {"ordinal": 1, "score": 0.9, "period_end_context": False, "row_count": 10},
        {"ordinal": 2, "score": 0.7, "period_end_context": True, "row_count": 1},
        {"ordinal": 3, "score": 0.6, "period_end_context": True, "row_count": 5},
    ]
    ordered = crossbatch._retention_policy_order(
        windows,
        "period_end_score_low_support_demoted_cap500",
    )

    assert [window["ordinal"] for window in ordered] == [3, 2, 1]


def test_row_score_surface_order_does_not_accept_truth_inputs():
    signature = inspect.signature(crossbatch._row_score_surface_summary)

    assert tuple(signature.parameters) == (
        "windows",
        "truth_docs",
        "scenario_by_doc",
        "phase1_reference",
    )
    assert signature.parameters["truth_docs"].default is None
    assert signature.parameters["scenario_by_doc"].default is None
    assert signature.parameters["phase1_reference"].default is None


def test_crossbatch_retention_readiness_holds_production_application():
    readiness = _payload()["retention_policy_readiness"]

    assert readiness["candidate"] == "period_end_score_low_support_demoted_cap500"
    assert readiness["status"] == "production_application_hold"
    assert readiness["all_batches_top500_improved"] is True
    assert readiness["by_batch"]["fixed3"]["top500_improved"] is True
    assert readiness["by_batch"]["fixed4"]["top500_improved"] is True
    assert readiness["by_batch"]["fixed5_normalcal5"]["top500_improved"] is True
    assert "requires fixture/DataSynth validation" in readiness["reason_for_hold"]


def test_crossbatch_row_score_window_surface_records_larger_recovery_path():
    payload = _payload()

    fixed3_surface = payload["batches"]["fixed3"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_score_low_support_demoted"]
    fixed4_surface = payload["batches"]["fixed4"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_score_low_support_demoted"]
    fixed5_surface = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.5"]["policies"]["period_end_score_low_support_demoted"]
    fixed5_high_surface = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.8"]["policies"]["period_end_score_low_support_demoted"]
    fixed3_support_bucket = payload["batches"]["fixed3"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_support_bucket_score"]
    fixed4_support_bucket = payload["batches"]["fixed4"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_support_bucket_score"]
    fixed5_support_bucket = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.5"]["policies"]["period_end_support_bucket_score"]
    fixed3_hybrid = payload["batches"]["fixed3"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_support_hybrid"]
    fixed4_hybrid = payload["batches"]["fixed4"]["row_score_window_surface_diagnostic"][
        "surfaces"
    ]["row_score_ge_0.5"]["policies"]["period_end_support_hybrid"]
    fixed5_hybrid = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.5"]["policies"]["period_end_support_hybrid"]
    fixed5_context = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.5"]["policies"]["period_end_support_context_count"]
    fixed5_amount_z = payload["batches"]["fixed5_normalcal5"][
        "row_score_window_surface_diagnostic"
    ]["surfaces"]["row_score_ge_0.5"]["policies"]["period_end_support_amount_zscore"]

    assert fixed3_surface["topn"]["500"]["truth_document_count"] == 43
    assert fixed4_surface["topn"]["500"]["truth_document_count"] == 43
    assert fixed5_surface["topn"]["1000"]["truth_document_count"] == 13
    assert fixed5_surface["topn"]["2000"]["truth_document_count"] == 275
    assert fixed5_surface["topn"]["5000"]["truth_document_count"] == 373
    assert fixed5_high_surface["topn"]["500"]["truth_document_count"] == 8
    assert fixed5_high_surface["topn"]["2000"]["truth_document_count"] == 270
    assert fixed5_surface["topn"]["100"]["truth_document_count"] == 0
    assert fixed3_support_bucket["topn"]["100"]["truth_document_count"] == 43
    assert fixed3_support_bucket["topn"]["500"]["truth_document_count"] == 51
    assert fixed4_support_bucket["topn"]["100"]["truth_document_count"] == 43
    assert fixed4_support_bucket["topn"]["500"]["truth_document_count"] == 51
    assert fixed5_support_bucket["topn"]["500"]["truth_document_count"] == 264
    assert fixed5_support_bucket["topn"]["2000"]["truth_document_count"] == 348
    assert fixed5_support_bucket["first_truth_window_rank"] == 142
    assert fixed5_support_bucket["top500_review_burden_proxy"]["low_row_support_share"] == 0.0
    assert fixed3_hybrid["topn"]["100"]["truth_document_count"] == 158
    assert fixed3_hybrid["topn"]["500"]["truth_document_count"] == 290
    assert fixed3_hybrid["topn"]["1000"]["truth_document_count"] == 301
    assert fixed4_hybrid["topn"]["100"]["truth_document_count"] == 158
    assert fixed4_hybrid["topn"]["500"]["truth_document_count"] == 290
    assert fixed4_hybrid["topn"]["1000"]["truth_document_count"] == 301
    assert fixed5_hybrid["topn"]["100"]["truth_document_count"] == 222
    assert fixed5_hybrid["topn"]["500"]["truth_document_count"] == 340
    assert fixed5_hybrid["topn"]["1000"]["truth_document_count"] == 362
    assert fixed5_hybrid["first_truth_window_rank"] == 6
    assert fixed5_hybrid["year_slice_summary"]["2022"]["top100_truth_document_count"] == 58
    assert fixed5_hybrid["year_slice_summary"]["2023"]["top100_truth_document_count"] == 122
    assert fixed5_hybrid["year_slice_summary"]["2024"]["top100_truth_document_count"] == 105
    assert fixed5_hybrid["year_slice_summary"]["2022"]["top500_truth_document_count"] == 94
    assert fixed5_hybrid["year_slice_summary"]["2023"]["top500_truth_document_count"] == 135
    assert fixed5_hybrid["year_slice_summary"]["2024"]["top500_truth_document_count"] == 136
    assert fixed5_hybrid["top500_context_pressure"]["manual_context_share"] == 0.766
    assert fixed5_hybrid["top500_context_pressure"][
        "after_hours_or_weekend_context_share"
    ] == 0.508
    assert fixed5_hybrid["top500_context_pressure"]["high_amount_zscore_share"] == 0.104
    assert fixed5_hybrid["top500_review_burden_proxy"]["score"] < fixed5_support_bucket[
        "top500_review_burden_proxy"
    ]["score"] + 0.01
    assert fixed5_context["topn"]["100"]["truth_document_count"] == 222
    assert fixed5_context["topn"]["500"]["truth_document_count"] == 324
    assert fixed5_amount_z["topn"]["100"]["truth_document_count"] == 219
    assert payload["batches"]["fixed5_normalcal5"]["row_score_window_surface_diagnostic"][
        "truth_label_used_for_surface_order"
    ] is False


def test_row_score_surface_readiness_records_hold_and_year_slice_floor():
    readiness = _payload()["row_score_surface_readiness"]

    assert readiness["candidate"] == "period_end_support_hybrid"
    assert readiness["surface"] == "row_score_ge_0.5"
    assert readiness["status"] == "production_application_hold"
    assert readiness["diagnostic_only"] is True
    assert readiness["truth_label_used_for_surface_order"] is False
    assert readiness["production_case_generation_changed"] is False
    assert readiness["all_batches_top100_improved"] is True
    assert readiness["all_batches_top500_improved"] is True

    fixed3 = readiness["by_batch"]["fixed3"]
    fixed4 = readiness["by_batch"]["fixed4"]
    fixed5 = readiness["by_batch"]["fixed5_normalcal5"]

    assert fixed3["candidate_top100"] == 158
    assert fixed3["candidate_top500"] == 290
    assert fixed3["year_slice_top100_min"] == 59
    assert fixed4["candidate_top100"] == 158
    assert fixed4["candidate_top500"] == 290
    assert fixed4["year_slice_top500_max"] == 126
    assert fixed5["candidate_top100"] == 222
    assert fixed5["candidate_top500"] == 340
    assert fixed5["year_slice_top100_min"] == 58
    assert fixed5["year_slice_top500_max"] == 136
    assert fixed5["top500_period_end_share"] == 1.0
    assert fixed5["top500_low_row_support_share"] == 0.0
    assert "review burden" in readiness["reason_for_hold"]


def test_row_score_burden_control_summary_records_tradeoffs():
    summary = _payload()["row_score_burden_control_summary"]

    assert summary["surface"] == "row_score_ge_0.5"
    assert summary["baseline_policy"] == "period_end_support_hybrid"
    assert summary["diagnostic_only"] is True
    assert summary["truth_label_used_for_policy_order"] is False
    assert summary["production_case_generation_changed"] is False

    fixed3 = summary["by_batch"]["fixed3"]
    fixed4 = summary["by_batch"]["fixed4"]
    fixed5 = summary["by_batch"]["fixed5_normalcal5"]

    for rows in (fixed3, fixed4):
        assert rows["period_end_support_hybrid"]["top100"] == 158
        assert rows["period_end_support_hybrid"]["top500"] == 290
        assert rows["hybrid_period_end_80pct_cap"]["top500"] == 254
        assert rows["hybrid_period_end_80pct_cap"]["top500_period_end_share"] == 0.8
        assert rows["hybrid_period_end_80pct_cap"]["burden_delta_vs_hybrid"] == -0.0872
        assert rows["hybrid_subject_cap10"]["top100"] == 159
        assert rows["hybrid_subject_cap10"]["top500_subject_top1_share"] == 0.02
        assert rows["hybrid_high_amount_zscore_25pct_cap"]["top500"] == 296
        assert rows["hybrid_high_amount_zscore_25pct_cap"][
            "top500_high_amount_zscore_share"
        ] == 0.25
        assert rows["ui100_context_export500_hybrid"]["top100"] == 59
        assert rows["ui100_context_export500_hybrid"]["top500"] == 290

    assert fixed5["period_end_support_hybrid"]["top100"] == 222
    assert fixed5["period_end_support_hybrid"]["top500"] == 340
    assert fixed5["hybrid_period_end_80pct_cap"]["top500"] == 264
    assert fixed5["hybrid_period_end_80pct_cap"]["top500_period_end_share"] == 0.8
    assert fixed5["hybrid_subject_cap10"]["top500"] == 340
    assert fixed5["hybrid_subject_cap10"]["top500_subject_top1_share"] == 0.02
    assert fixed5["hybrid_high_amount_zscore_25pct_cap"]["top500"] == 340
    assert fixed5["ui100_context_export500_hybrid"]["first_truth_window_rank"] == 3


def test_phase1_incremental_alignment_summary_reframes_ts_direction():
    summary = _payload()["row_score_phase1_incremental_alignment_summary"]

    assert summary["surface"] == "row_score_ge_0.5"
    assert summary["diagnostic_only"] is True
    assert summary["truth_label_used_for_policy_order"] is False
    assert summary["truth_label_used_only_for_incremental_evaluation"] is True
    assert summary["phase1_ranking_changed"] is False
    assert summary["production_ranking_changed"] is False
    assert summary["ts_aligned_scenarios"] == [
        "period_end_adjustment_manipulation",
        "unusual_timing_manipulation",
    ]
    assert "weak TS-aligned TOP100 uplift" in summary["current_direction_read"]

    fixed3 = summary["by_batch"]["fixed3"]
    assert fixed3 == {
        "available": False,
        "reason": "phase1_case_result_not_configured",
    }

    fixed4 = summary["by_batch"]["fixed4"]
    fixed5 = summary["by_batch"]["fixed5_normalcal5"]
    assert fixed4["phase1_top100_truth_document_count"] == 85
    assert fixed4["phase1_top500_truth_document_count"] == 273
    assert fixed5["phase1_top100_truth_document_count"] == 246
    assert fixed5["phase1_top500_truth_document_count"] == 330

    fixed4_hybrid = fixed4["policies"]["period_end_support_hybrid"]
    assert fixed4_hybrid["top100_not_phase1_top100"] == 123
    assert fixed4_hybrid["top100_ts_aligned_not_phase1_top100"] == 0
    assert fixed4_hybrid["top500_ts_aligned_not_phase1_top100"] == 59
    assert fixed4["policies"]["hybrid_high_amount_zscore_25pct_cap"][
        "top500_ts_aligned_not_phase1_top100"
    ] == 65
    assert fixed4["policies"]["timing_primary_support_round_amount_demoted"][
        "top100_ts_aligned_not_phase1_top100"
    ] == 0

    fixed5_hybrid = fixed5["policies"]["period_end_support_hybrid"]
    assert fixed5_hybrid["top100_not_phase1_top100"] == 108
    assert fixed5_hybrid["top100_ts_aligned_not_phase1_top100"] == 2
    assert fixed5_hybrid["top500_ts_aligned_not_phase1_top100"] == 32
    fixed5_timing = fixed5["policies"]["timing_primary_support_round_amount_demoted"]
    assert fixed5_timing["top100_not_phase1_top100"] == 13
    assert fixed5_timing["top100_ts_aligned_not_phase1_top100"] == 13
    assert fixed5_timing["top500_ts_aligned_not_phase1_top100"] == 32
    assert fixed5_timing["top100_not_phase1_top100_scenario_counts"] == {
        "unusual_timing_manipulation": 13
    }


def test_retention_policy_fixture_validation_is_no_truth_and_audit_observable():
    fixture = _payload()["retention_policy_fixture_validation"]

    assert fixture["policy"] == "period_end_score_low_support_demoted_cap500"
    assert fixture["truth_label_used"] is False
    assert fixture["expected_first_label"] == "supported_unusual_period_end_window"
    assert fixture["ordered_labels"] == [
        "supported_unusual_period_end_window",
        "normal_supported_period_end_burst",
        "one_row_period_end_noise_high_score",
        "non_period_end_high_score_window",
    ]
    assert fixture["supported_unusual_before_one_row_noise"] is True
    assert fixture["period_end_context_before_non_period_end_high_score"] is True


def test_crossbatch_locks_current_limit_and_fixed5_candidate_improvement():
    payload = _payload()
    summary = payload["direction_summary"]

    assert summary["all_batches_improve_top100_or_top500"] is False
    assert summary["all_batches_first_rank_nonworse"] is True
    assert summary["by_batch"]["fixed3"]["direction"] == "no_material_improvement"
    assert summary["by_batch"]["fixed4"]["direction"] == "no_material_improvement"
    assert summary["by_batch"]["fixed5_normalcal5"]["direction"] == "top100_improved"

    fixed5 = payload["batches"]["fixed5_normalcal5"]["candidates"]
    current = fixed5["current_native_ts_ordering"]
    burden = fixed5["review_burden_penalized_context"]
    demoted = fixed5["review_burden_closing_demoted_context"]

    assert current["topn"]["100"]["matched"] == 0
    assert current["topn"]["500"]["matched"] == 0
    assert current["first_truth_rank"] == 762
    assert burden["topn"]["100"]["matched"] == 8
    assert burden["first_truth_rank"] == 76
    assert demoted["topn"]["100"]["matched"] == 8
    assert demoted["first_truth_rank"] == 98
    assert demoted["top500_distribution"]["false_positive_pressure_proxy"]["score"] < burden[
        "top500_distribution"
    ]["false_positive_pressure_proxy"]["score"]


def test_crossbatch_artifact_does_not_emit_raw_identifiers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    truth_doc_ids = []
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
