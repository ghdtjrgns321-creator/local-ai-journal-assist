"""Readiness guards for optional unsupervised document companion surface."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from dashboard.components import phase2_native_case_metrics as native_metrics
from dashboard.components import phase2_native_case_panel as native_panel
from src.detection.base import DetectionResult
from src.export.analysis_status import summarize_export_analysis_status
from src.models.phase2_case import Phase2CaseSet, UnsupervisedCase, make_row_ref
from src.services.phase2_inference_service import _attach_phase2_family_policy_summary
from src.services.phase2_unsupervised_case_builder import build_unsupervised_cases

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "unsupervised_soft_guard_stability_fixed5_20260530.json"
TRUTH_DOC_COUNT = 620


def _payload() -> dict[str, Any]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _case(case_id: str, score: float, row_position: int) -> UnsupervisedCase:
    ref = make_row_ref(
        row_position=row_position,
        index_label=row_position,
        document_id=f"DOC-ML-{row_position}",
        raw_line_number=str(row_position + 1),
        company_code="C01",
    )
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id="bid-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(ref,),
        evidence_tier="strong",
        case_generation_reason={"gate": "q95_ecdf"},
        family_score=score,
        family_ecdf=score,
        anomaly_score=score,
        top_features=({"feature_id": "amount_abs", "contrib": 0.3},),
        model_id="vae-fixture",
        schema_hash="schema-fixture",
    )


def _case_set() -> Phase2CaseSet:
    lower_score_first = _case("p2_unsupervised_document_first001", 0.20, 0)
    higher_score_second = _case("p2_unsupervised_document_second002", 0.90, 1)
    return Phase2CaseSet(unsupervised_cases=(lower_score_first, higher_score_second))


def test_soft_guard_action_tier_incremental_metrics_are_present_and_bounded():
    metrics = _payload()["soft_guard_action_tier_incremental_metrics"]

    assert metrics["surface"] == "hybrid_with_soft_repeated_normal_guard"
    assert metrics["phase1_action_tier_truth_baseline"] == {
        "immediate_truth_docs": 264,
        "review_or_higher_truth_docs": 354,
        "candidate_or_higher_truth_docs": 544,
    }
    assert metrics["top100_truth_docs"] == 25
    assert metrics["top500_truth_docs"] == 151
    assert metrics["top10000_truth_docs"] == 483

    for top_n in ("100", "500", "10000"):
        item = metrics["topn"][top_n]
        assert 0 <= item["truth_docs"] <= TRUTH_DOC_COUNT
        for key in (
            "phase1_immediate_review_outside_truth_docs",
            "phase1_review_or_above_outside_truth_docs",
            "phase1_candidate_or_above_outside_truth_docs",
        ):
            assert 0 <= item[key] <= item["truth_docs"]


def test_soft_guard_action_tier_incremental_values_are_locked():
    metrics = _payload()["soft_guard_action_tier_incremental_metrics"]

    assert metrics["top100_phase1_immediate_review_outside_truth_docs"] == 13
    assert metrics["top500_phase1_immediate_review_outside_truth_docs"] == 95
    assert metrics["top10000_phase1_immediate_review_outside_truth_docs"] == 270
    assert metrics["top100_phase1_review_or_above_outside_truth_docs"] == 9
    assert metrics["top500_phase1_review_or_above_outside_truth_docs"] == 64
    assert metrics["top10000_phase1_review_or_above_outside_truth_docs"] == 188
    assert metrics["top100_phase1_candidate_or_above_outside_truth_docs"] == 5
    assert metrics["top500_phase1_candidate_or_above_outside_truth_docs"] == 11
    assert metrics["top10000_phase1_candidate_or_above_outside_truth_docs"] == 47


def test_companion_policy_summary_records_document_case_default_ordering():
    case_set = _case_set()
    result = SimpleNamespace(phase2_family_policy_summary={})
    native_order_before = tuple(case.phase2_case_id for case in case_set.unsupervised_cases)

    _attach_phase2_family_policy_summary(result, case_set)

    summary = result.phase2_family_policy_summary["unsupervised"]
    assert summary["production_adoption"] is True
    assert summary["adoption_candidate"] is False
    assert summary["production_default_ranking_changed"] is False
    assert summary["native_row_ordering_changed"] is True
    # P3 lock update: row-case emission was intentionally replaced by document-case
    # emission. This is a product-surface generation change, while q95/score/
    # threshold and PHASE1/PHASE2 fusion guardrails below remain unchanged.
    assert summary["case_generation_changed"] is True
    assert summary["case_generation_change"] == "row_case_to_document_case"
    assert summary["ordering_context_policy"] == {
        "ordering_layer_uses_document_context": False,
        "used_context_fields": (),
        "context_fields_display_only": True,
        "detector_score_weight_changed": False,
        "phase1_ranking_changed": False,
        "phase2_fusion_changed": False,
        "overlay_context_used_for_primary_queue": False,
    }
    assert summary["top_features_connected"] is True
    assert summary["q95_gate_change_recommended"] is False
    assert tuple(case.phase2_case_id for case in case_set.unsupervised_cases) == native_order_before
    assert summary["product_role"] == "broad_statistical_review_companion_evidence_surface"
    assert summary["fraud_primary_recall_family"] is False
    assert summary["primary_recall_metric_role"] == "diagnostic_only_not_product_judgement"
    assert summary["optional_companion_surface"]["replaces_native_case_ordering"] is False
    assert (
        summary["optional_companion_surface"]["adoption_state"]
        == "historical_diagnostic_not_current_default"
    )
    assert summary["optional_companion_surface"]["descriptor_only"] is True
    assert (
        summary["responsibility_target"]["primary_target_status"]
        == "debug_only_historical_v31_not_product_goal"
    )
    assert (
        summary["responsibility_target"]["primary_target_metric_role"]
        == "debug_only_not_fraud_primary_recall"
    )
    assert summary["responsibility_target"]["primary_target_truth_docs_fixed5"] == 168
    assert summary["responsibility_target"]["companion_target_truth_docs_fixed5"] == 339
    assert (
        summary["responsibility_target"]["must_capture_statistical_primary_40_by_vae"]
        is False
    )
    assert (
        summary["product_judgement_metrics"][
            "broad_statistical_review_contribution"
        ]["recommended_surface_top500_truth_docs_fixed5"]
        == 151
    )
    assert (
        summary["product_judgement_metrics"]["repeated_normal_pressure"][
            "recommended_surface_top500_fixed5"
        ]
        == 0.256
    )
    assert summary["q95_backlog_policy"]["near_miss_promoted_to_case"] is False
    assert summary["anti_fitting_guardrails"] == {
        "hybrid_upper_bound_default_adoption": False,
        "q95_gate_relaxation": False,
        "vae_score_threshold_recall_fitting": False,
        "threshold_or_weight_recall_fitting": False,
        "top_features_used_for_ranking": False,
        "phase1_prior_disguised_as_vae": False,
        "datasynth_changed_to_match_vae_score": False,
        "truth_owner_scenario_shortcut_feature_allowed": False,
        "truth_or_owner_metadata_used_as_selector": False,
    }


def test_downstream_helpers_ignore_optional_companion_descriptor():
    case_set = _case_set()
    result = SimpleNamespace(
        detector_statuses=[],
        warnings=[],
        phase2_case_set=case_set,
        phase2_family_policy_summary={},
        phase2_case_overlays=[],
        phase3_case_narratives=[],
    )
    _attach_phase2_family_policy_summary(result, case_set)

    assert native_metrics.count_native_cases_total(case_set) == 2
    assert tuple(native_metrics.iter_unsupervised_cases(case_set)) == case_set.unsupervised_cases
    frame = native_panel._build_family_frame(
        "unsupervised",
        case_set.unsupervised_cases,
        phase1_case_lookup={},
    )
    assert list(frame["_full_case_id"]) == [
        "p2_unsupervised_document_first001",
        "p2_unsupervised_document_second002",
    ]
    export_status = summarize_export_analysis_status(result)
    assert export_status["status"] == "unknown"
    assert "phase2_contract" in export_status


def test_companion_fixture_missing_document_id_uses_f1_singleton_fallback():
    df = pd.DataFrame(
        {
            "document_id": [pd.NA],
            "line_number": [1],
            "company_code": ["C01"],
            "amount": [1_000.0],
        },
        index=pd.Index([0]),
    ).astype({"document_id": "object"})
    scores = pd.Series([0.99], index=df.index)
    details = pd.DataFrame(
        {
            "ML02_top_feature_1": ["amount_abs"],
            "ML02_top_feature_1_contrib": [0.3],
        },
        index=df.index,
    )
    result = DetectionResult(
        track_name="ml_unsupervised",
        flagged_indices=[0],
        scores=scores,
        rule_flags=[],
        details=details,
        metadata={},
    )

    cases = build_unsupervised_cases(
        batch_id="bid-1",
        detection_result=result,
        df=df,
        model_id="vae-fixture",
        schema_hash="schema-fixture",
        ecdf_gate=0.95,
        ordering_strategy="native",
    )

    assert len(cases) == 1
    assert cases[0].unit_type == "document"
    assert cases[0].document_id is None
    assert cases[0].case_generation_reason["document_grouping"] == "fallback_row_identity"
