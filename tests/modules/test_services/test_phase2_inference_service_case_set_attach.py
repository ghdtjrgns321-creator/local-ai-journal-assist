"""`_attach_phase2_case_set` hook 계약 검증 (S3.next Phase B, invariant #84~87).

Why: ``run_phase2_inference`` 가 orchestrator + linker hook 을 통해 PHASE2
``phase2_case_set`` 과 ``phase2_linker_diagnostics`` 를 ``result`` 에 부착하는지
검증한다. orchestrator / linker 자체의 비즈니스 로직은 monkeypatch 로 stub 하여
hook 의 책임 (graceful skip · salt 도출 · PHASE1 분기) 만 잠근다.

invariant
- #84: result.results / data / batch_id 부재 → graceful skip (ValueError 없음).
- #85: engagement_salt = ctx.engagement_id + batch_id (없으면 salt="" — position fallback).
- #86: PHASE1 부재 → linker skip, case_set 만 부착 (linked=False).
- #87: unsupervised model_id / schema_hash 는 snapshot 에서 도출, 부재 시 빈 문자열.
"""

from __future__ import annotations

import builtins
from types import SimpleNamespace
from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import (
    Phase2CaseSet,
    TimeseriesCase,
    UnsupervisedCase,
    make_row_ref,
)
from src.services.phase2_case_phase1_linker import LinkerResult
from src.services.phase2_inference_service import (
    _attach_phase2_case_overlays,
    _attach_phase2_case_set,
)
from tests.modules.test_services.test_phase2_case_contract import _phase1_result

# ---------------------------------------------------------------------------
# 공용 fixture / helper
# ---------------------------------------------------------------------------


def _make_df() -> pd.DataFrame:
    """orchestrator stub 으로 위임 — 내용 무관 minimal frame."""
    return pd.DataFrame({"amount": [10.0, 20.0]}, index=pd.Index([0, 1]))


# sentinel — `None` 자체를 의도된 값으로 전달하기 위한 default marker.
# `data=None` graceful skip 검증과 default fixture 분기를 구분.
_UNSET = object()


def _make_result(
    *,
    results: Any = _UNSET,
    data: Any = _UNSET,
    batch_id: str = "bid-1",
    phase1_case_result: Any = None,
    warnings: list[str] | None = None,
) -> SimpleNamespace:
    """PipelineResult-like SimpleNamespace — 통합 흔적은 최소.

    ``results`` / ``data`` 를 명시적 ``None`` 으로 전달하면 graceful skip 검증용.
    인자 미전달 시 default fixture 채움.
    """
    return SimpleNamespace(
        results=([object()] if results is _UNSET else results),
        data=(_make_df() if data is _UNSET else data),
        batch_id=batch_id,
        phase1_case_result=phase1_case_result,
        warnings=warnings if warnings is not None else [],
    )


def _make_case_set() -> Phase2CaseSet:
    """empty case_set. orchestrator stub 이 반환할 sentinel."""
    return Phase2CaseSet()


def _make_unsupervised_case_set() -> Phase2CaseSet:
    first_ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="DOC-ML-A",
        raw_line_number="1",
        company_code="C01",
    )
    second_ref = make_row_ref(
        row_position=1,
        index_label=1,
        document_id="DOC-ML-B",
        raw_line_number="2",
        company_code="C01",
    )
    lower_score_first = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_first001",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(first_ref,),
        evidence_tier="strong",
        case_generation_reason={"gate": "q95_ecdf"},
        family_score=0.20,
        family_ecdf=0.95,
        anomaly_score=0.20,
        top_features=({"feature_id": "amount_abs", "contrib": 0.3},),
        model_id="vae-fixture",
        schema_hash="schema-fixture",
    )
    higher_score_second = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_second002",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(second_ref,),
        evidence_tier="strong",
        case_generation_reason={"gate": "q95_ecdf"},
        family_score=0.90,
        family_ecdf=0.99,
        anomaly_score=0.90,
        top_features=({"feature_id": "posting_day", "contrib": 0.2},),
        model_id="vae-fixture",
        schema_hash="schema-fixture",
    )
    return Phase2CaseSet(unsupervised_cases=(lower_score_first, higher_score_second))


def _make_timeseries_case_set() -> Phase2CaseSet:
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="DOC-TS-A",
        raw_line_number="1",
        company_code="C01",
    )
    case = TimeseriesCase(
        phase2_case_id="ts-native-1",
        batch_id="bid-1",
        family="timeseries",
        unit_type="window",
        row_refs=(ref,),
        evidence_tier="strong",
        case_generation_reason={"gate": "timeseries_strong_sub_signal_high"},
        family_score=5.0,
        family_ecdf=0.0,
        sub_rule="TS01",
        subject="5100",
        window_start="2025-12-31",
        window_end="2025-12-31",
        period_end_context=True,
    )
    return Phase2CaseSet(timeseries_cases=(case,))


class _OrchestratorRecorder:
    """build_phase2_case_set monkeypatch — kwargs capture + 고정 case_set 반환."""

    def __init__(self, case_set: Phase2CaseSet | None = None) -> None:
        self.case_set = case_set if case_set is not None else _make_case_set()
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Phase2CaseSet:
        self.calls.append(kwargs)
        return self.case_set


class _LinkerRecorder:
    """link_phase2_to_phase1 monkeypatch — kwargs capture + LinkerResult 반환."""

    def __init__(self, *, linked_case_set: Phase2CaseSet | None = None) -> None:
        # default: linked=True 빈 set (with_phase1_refs({}) 와 동등).
        self.linked_case_set = (
            linked_case_set
            if linked_case_set is not None
            else _make_case_set().with_phase1_refs({})
        )
        self.calls: list[dict[str, Any]] = []
        self.diagnostics: dict[str, Any] = {
            "linked_count": 0,
            "phase1_hit_count": 0,
            "unmatched_phase2_count": 0,
            "key_mode_used": "position",
            "match_precision": "row",
        }

    def __call__(self, **kwargs: Any) -> LinkerResult:
        self.calls.append(kwargs)
        return LinkerResult(case_set=self.linked_case_set, diagnostics=self.diagnostics)


def _patch(monkeypatch, *, orchestrator=None, linker=None) -> None:
    """orchestrator / linker 둘 다 monkeypatch — phase2_inference_service 내부 import 대상."""
    if orchestrator is not None:
        monkeypatch.setattr(
            "src.services.phase2_case_set_orchestrator.build_phase2_case_set",
            orchestrator,
        )
    if linker is not None:
        monkeypatch.setattr(
            "src.services.phase2_case_phase1_linker.link_phase2_to_phase1",
            linker,
        )


# ---------------------------------------------------------------------------
# graceful skip 검증 (invariant #84)
# ---------------------------------------------------------------------------


def test_attach_skips_when_results_empty(monkeypatch) -> None:
    """results 가 빈 list → orchestrator 호출 0건, phase2_case_set 부착 안 됨."""
    orch = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(results=[])
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert orch.calls == []
    assert linker.calls == []
    assert (
        not hasattr(result, "phase2_case_set") or getattr(result, "phase2_case_set", None) is None
    )
    assert (
        not hasattr(result, "phase2_linker_diagnostics")
        or getattr(result, "phase2_linker_diagnostics", None) is None
    )


def test_attach_skips_when_data_none(monkeypatch) -> None:
    """data 가 None → graceful skip (invariant #84)."""
    orch = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(data=None)
    # ValueError 미발생 보장
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert orch.calls == []
    assert linker.calls == []


def test_attach_skips_when_batch_id_empty(monkeypatch) -> None:
    """batch_id 가 빈 문자열 → graceful skip."""
    orch = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(batch_id="")
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert orch.calls == []
    assert linker.calls == []


# ---------------------------------------------------------------------------
# 정상 attach (invariant #86, #87)
# ---------------------------------------------------------------------------


def test_attach_attaches_case_set_to_result(monkeypatch) -> None:
    """results / data / batch_id 가용 + PHASE1 부재 → case_set 만 부착 (#86)."""
    sentinel_case_set = _make_case_set()
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    # orchestrator 1회 호출 — 정확히 같은 case_set 부착
    assert len(orch.calls) == 1
    call_kwargs = orch.calls[0]
    assert call_kwargs["batch_id"] == "bid-1"
    assert call_kwargs["detection_results"] == list(result.results)
    assert call_kwargs["df"] is result.data
    # invariant #87 — snapshot 부재 시 빈 문자열 default
    assert call_kwargs["unsupervised_model_id"] == ""
    assert call_kwargs["unsupervised_schema_hash"] == ""

    # PHASE1 부재 → linker 호출 0건 (invariant #86)
    assert linker.calls == []
    # case_set 만 부착, linker_diagnostics 는 None / 부재
    assert result.phase2_case_set is sentinel_case_set
    assert getattr(result, "phase2_linker_diagnostics", None) is None


def test_attach_records_timeseries_default_stabilized_policy(
    monkeypatch,
) -> None:
    """Timeseries metadata records stabilized ordering as the product default."""
    sentinel_case_set = _make_timeseries_case_set()
    native_order_before = tuple(case.phase2_case_id for case in sentinel_case_set.timeseries_cases)
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert (
        tuple(case.phase2_case_id for case in result.phase2_case_set.timeseries_cases)
        == native_order_before
    )
    summary = result.phase2_family_policy_summary["timeseries"]
    assert summary["primary_product_role"] == "timing_primary_diagnostic_candidate"
    assert summary["production_adoption"] is True
    assert summary["production_default_ordering_changed"] is True
    assert summary["native_ordering_changed"] is True
    assert summary["explicit_ordering_flag_available"] is True
    assert summary["default_ordering_strategy"] == ("ts_specific_top100_stabilized_surface")
    assert summary["native_ordering_fallback"] is True
    assert summary["candidate_ordering_strategy"] == ("ts_specific_top100_stabilized_surface")
    assert summary["v31_primary_target"]["truth_docs"] == 21
    assert summary["v31_primary_target"]["period_end_context_docs"] == 92
    assert summary["v31_primary_target"]["native_top500_matched_docs"] == 0
    assert summary["v31_primary_target"]["candidate_top100_matched_docs"] == 21
    assert summary["v31_primary_target"]["phase1_immediate_high_covered_docs"] == 0
    assert summary["v31_primary_target"]["phase1_review_or_higher_covered_docs"] == 2
    assert summary["v31_primary_target"]["phase1_candidate_or_higher_covered_docs"] == 21
    assert summary["context_target"] == {
        "period_end_context_docs": 92,
        "used_as_primary_denominator": False,
        "broad_companion_used_as_ts_primary": False,
    }
    assert summary["selector_input_policy"]["truth_label_used"] is False
    assert summary["selector_input_policy"]["scenario_label_used"] is False
    assert summary["selector_input_policy"]["phase1_rank_used"] is False
    assert summary["selector_input_policy"]["matched_result_used"] is False
    assert summary["selector_input_policy"]["raw_identifier_used"] is False
    assert summary["guardrails"]["broad_companion_used_as_ts_primary"] is False
    assert summary["adoption_readiness"] == {
        "status": "product_default_ordering_adopted",
        "product_default_ordering_strategy": "ts_specific_top100_stabilized_surface",
        "candidate_ordering_strategy": "ts_specific_top100_stabilized_surface",
        "explicit_flag_required": False,
        "product_default_adoption_allowed": True,
        "native_fallback_strategy": "native",
        "period_end_context_primary_denominator": False,
        "fixed4_used_for_product_judgment": False,
        "required_validation_before_default": {
            "regenerated_owner_metadata_datasynth": {
                "required": True,
                "minimum_primary_docs": 21,
                "required_top100_primary_capture": 21,
                "required_top500_primary_capture": 21,
                "period_end_context_denominator_allowed": False,
            },
            "fixed5_compatible_slice_validation": {
                "required": True,
                "each_slice_top500_capture_must_equal_primary_docs": True,
                "top100_slice_regression_requires_review": True,
                "must_not_use_fixed4": True,
            },
            "selector_contract": {
                "truth_label_allowed": False,
                "scenario_label_allowed": False,
                "owner_metadata_allowed": False,
                "phase1_rank_allowed": False,
                "matched_result_allowed": False,
                "raw_identifier_allowed": False,
            },
        },
        "post_adoption_monitoring": [
            "single fixed5 owner-metadata candidate validation only",
            (
                "requires regenerated owner-metadata DataSynth or fixed5-compatible "
                "slice validation after default adoption"
            ),
            "must keep period-end context docs out of TS primary denominator",
        ],
    }


def test_attach_records_unsupervised_document_case_default_policy(
    monkeypatch,
) -> None:
    """Unsupervised metadata records document-case default display ordering."""
    sentinel_case_set = _make_unsupervised_case_set()
    native_order_before = tuple(
        case.phase2_case_id for case in sentinel_case_set.unsupervised_cases
    )
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert result.phase2_case_set is sentinel_case_set
    assert (
        tuple(case.phase2_case_id for case in result.phase2_case_set.unsupervised_cases)
        == native_order_before
    )
    summary = result.phase2_family_policy_summary["unsupervised"]
    assert summary["primary_product_role"] == "broad_statistical_review_companion_evidence_surface"
    assert summary["product_role"] == "broad_statistical_review_companion_evidence_surface"
    assert summary["role_scope"] == "broad_statistical_review_companion"
    assert summary["fraud_primary_recall_family"] is False
    assert summary["primary_recall_metric_role"] == "diagnostic_only_not_product_judgement"
    assert summary["native_row_ordering_changed"] is True
    assert summary["production_default_ranking_changed"] is False
    assert summary["production_adoption"] is True
    assert summary["adoption_candidate"] is False
    assert summary["recommended_surface"] == "document_case_max_score_order"
    assert summary["default_display_ordering"] == "document_case_max_score_order"
    # P3 lock update: unsupervised native generation now emits document review
    # cases instead of row cases. Ranking/fusion/threshold guardrails remain locked.
    assert summary["case_generation_changed"] is True
    assert summary["case_generation_change"] == "row_case_to_document_case"
    assert summary["ordering_context_policy"]["detector_score_weight_changed"] is False
    assert summary["ordering_context_policy"]["overlay_context_used_for_primary_queue"] is False
    assert summary["evidence_quality_ready"] is True
    assert summary["evidence_quality_improved"] is True
    assert summary["top_features_connected"] is True
    assert summary["q95_gate_change_recommended"] is False
    assert "q95 gate" in summary["adoption_note"]
    assert summary["case_count"] == 2
    assert summary["top_features_available_case_count"] == 2
    companion = summary["optional_companion_surface"]
    assert companion["policy_id"] == "unsupervised_document_review_priority_soft_guard_v1"
    assert companion["surface_name"] == "hybrid_with_soft_repeated_normal_guard"
    assert companion["v31_owner_surface_artifact_path"] == (
        "artifacts/unsupervised_v31_owner_surface_fixed5_20260531.json"
    )
    assert companion["adoption_state"] == "historical_diagnostic_not_current_default"
    assert companion["descriptor_only"] is True
    assert companion["replaces_native_case_ordering"] is False
    assert companion["top_features_used_for_ranking"] is False
    assert companion["aggregate_counts"]["native_top500_truth_docs_fixed5"] == 39
    assert companion["aggregate_counts"]["recommended_surface_top500_truth_docs_fixed5"] == 151
    judgement = summary["product_judgement_metrics"]
    assert (
        judgement["broad_statistical_review_contribution"]["metric_role"]
        == "review_contribution_not_fraud_primary_recall"
    )
    assert (
        judgement["broad_statistical_review_contribution"][
            "recommended_surface_top500_truth_docs_fixed5"
        ]
        == 151
    )
    assert judgement["repeated_normal_pressure"]["recommended_surface_top500_fixed5"] == 0.256
    assert (
        judgement["outside_phase1_complement"]["top500_phase1_immediate_review_outside_truth_docs"]
        == 95
    )
    assert judgement["evidence_explainability"]["top_features_connected"] is True
    responsibility = summary["responsibility_target"]
    assert responsibility["primary_target_status"] == "debug_only_historical_v31_not_product_goal"
    assert responsibility["primary_target_metric_role"] == "debug_only_not_fraud_primary_recall"
    assert responsibility["primary_target_truth_docs_fixed5"] == 168
    assert (
        responsibility["primary_target_source"]
        == "historical v3.1 fictitious-entry statistical diagnostic"
    )
    assert responsibility["primary_target_product_goal"] is False
    assert responsibility["must_capture_statistical_primary_40_by_vae"] is False
    assert responsibility["companion_target_truth_docs_fixed5"] == 339
    assert responsibility["native_row_queue_top100_primary_docs_fixed5"] == 12
    assert responsibility["soft_guard_top100_primary_docs_fixed5"] == 24
    assert responsibility["native_row_queue_top500_primary_docs_fixed5"] == 23
    assert responsibility["soft_guard_top500_primary_docs_fixed5"] == 110
    assert responsibility["soft_guard_phase1_immediate_outside_top500_primary_docs_fixed5"] == 110
    assert (
        responsibility["soft_guard_phase1_review_or_above_outside_top500_primary_docs_fixed5"] == 74
    )
    assert (
        responsibility["soft_guard_phase1_candidate_or_above_outside_top500_primary_docs_fixed5"]
        == 73
    )
    assert responsibility["native_row_queue_top500_companion_docs_fixed5"] == 34
    assert responsibility["soft_guard_top500_companion_docs_fixed5"] == 33
    assert responsibility["soft_guard_phase1_immediate_outside_top500_companion_docs_fixed5"] == 33
    assert (
        responsibility["soft_guard_phase1_review_or_above_outside_top500_companion_docs_fixed5"]
        == 32
    )
    assert (
        responsibility["soft_guard_phase1_candidate_or_above_outside_top500_companion_docs_fixed5"]
        == 25
    )
    readiness = summary["v31_adoption_readiness"]
    assert readiness["default_native_ordering_unchanged"] is False
    assert readiness["soft_guard_role"] == "historical_document_review_priority_diagnostic"
    assert readiness["product_default_adoption"] is False
    assert readiness["primary_top500_lift_vs_native"] == 87
    assert readiness["primary_lift_metric_role"] == "debug_only_historical_v31"
    assert readiness["companion_top500_lift_vs_native"] == -1
    assert readiness["companion_top500_improved"] is False
    assert readiness["readiness_artifact_path"] == (
        "artifacts/unsupervised_v31_owner_surface_fixed5_20260531.json"
    )
    assert readiness["monitoring_guardrails"] == (
        "repeated-normal pressure requires monitoring",
        "period-end normal background requires monitoring",
        "account/process concentration requires monitoring",
        "single-row high amount normal proxy requires monitoring",
        "companion TOP500 does not improve",
    )
    assert (
        summary["pressure_monitoring"]["v31_primary_soft_guard_repeated_normal_pressure_top500"]
        == 0.336
    )
    assert (
        summary["pressure_monitoring"]["v31_primary_soft_guard_period_end_normal_background_top500"]
        == 0.578
    )
    assert summary["q95_backlog_policy"]["near_miss_promoted_to_case"] is False
    assert summary["anti_fitting_guardrails"]["hybrid_upper_bound_default_adoption"] is False
    assert summary["anti_fitting_guardrails"]["q95_gate_relaxation"] is False
    assert summary["anti_fitting_guardrails"]["vae_score_threshold_recall_fitting"] is False
    assert summary["anti_fitting_guardrails"]["threshold_or_weight_recall_fitting"] is False
    assert summary["anti_fitting_guardrails"]["top_features_used_for_ranking"] is False
    assert summary["anti_fitting_guardrails"]["phase1_prior_disguised_as_vae"] is False
    assert summary["anti_fitting_guardrails"]["datasynth_changed_to_match_vae_score"] is False
    assert (
        summary["anti_fitting_guardrails"]["truth_owner_scenario_shortcut_feature_allowed"] is False
    )
    assert summary["anti_fitting_guardrails"]["truth_or_owner_metadata_used_as_selector"] is False


def test_attach_with_phase1_invokes_linker_and_records_diagnostics(monkeypatch) -> None:
    """PHASE1 가용 → linker 호출 + diagnostics 부착, case_set 이 linker 산출로 교체."""
    orch_case_set = _make_case_set()
    linked_case_set = _make_case_set().with_phase1_refs({})
    orch = _OrchestratorRecorder(case_set=orch_case_set)
    linker = _LinkerRecorder(linked_case_set=linked_case_set)
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    phase1 = SimpleNamespace(cases=[])  # truthy phase1 sentinel
    ctx = SimpleNamespace(engagement_id="eng-X")
    result = _make_result(phase1_case_result=phase1)
    _attach_phase2_case_set(result, ctx=ctx, snapshot=None)

    # orchestrator 1회 + linker 1회 호출
    assert len(orch.calls) == 1
    assert len(linker.calls) == 1
    # linker kwargs 검증 — case_set 은 orchestrator 산출 그대로 전달, phase1 동일 객체
    linker_call = linker.calls[0]
    assert linker_call["case_set"] is orch_case_set
    assert linker_call["phase1"] is phase1
    assert linker_call["key_mode"] == "auto"
    # linked case_set 으로 교체됨
    assert result.phase2_case_set is linked_case_set
    # diagnostics 부착 — linker recorder 의 dict 그대로
    assert result.phase2_linker_diagnostics == linker.diagnostics


def test_attach_without_phase1_skips_linker_keeps_linked_false(monkeypatch) -> None:
    """PHASE1 부재 → linker 호출 0건, case_set 의 linked 는 False 유지 (#86)."""
    orch_case_set = _make_case_set()  # default linked=False
    orch = _OrchestratorRecorder(case_set=orch_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert linker.calls == []
    assert result.phase2_case_set is orch_case_set
    assert result.phase2_case_set.linked is False


# ---------------------------------------------------------------------------
# engagement_salt 도출 (invariant #85)
# ---------------------------------------------------------------------------


def test_attach_with_engagement_salt_auto_resolves_to_hash_mode(monkeypatch) -> None:
    """ctx.engagement_id 가용 → linker 에 ``engagement_id|batch_id`` salt 전달."""
    orch = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    phase1 = SimpleNamespace(cases=[])
    ctx = SimpleNamespace(engagement_id="eng-42")
    result = _make_result(batch_id="bid-7", phase1_case_result=phase1)
    _attach_phase2_case_set(result, ctx=ctx, snapshot=None)

    assert len(linker.calls) == 1
    linker_call = linker.calls[0]
    # salt = "eng-42|bid-7" — invariant #85 정합
    assert linker_call["salt"] == "eng-42|bid-7"
    assert linker_call["key_mode"] == "auto"


def test_attach_without_engagement_salt_falls_back_to_position(monkeypatch) -> None:
    """ctx 부재 → linker 에 salt=None 전달 (position auto fallback, invariant #85)."""
    orch = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    phase1 = SimpleNamespace(cases=[])
    result = _make_result(phase1_case_result=phase1)
    # ctx 자체가 None — engagement_id 도출 불가
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert len(linker.calls) == 1
    linker_call = linker.calls[0]
    # salt 가 None 또는 빈 문자열 — 둘 다 linker auto resolve 가 position 으로 fallback
    assert linker_call["salt"] in (None, "")
    assert linker_call["key_mode"] == "auto"


# ---------------------------------------------------------------------------
# Phase B Followup — store persist + phase1 salt 통합 가드
# ---------------------------------------------------------------------------


def test_attach_persists_case_set_to_store_when_ctx_and_salt_available(monkeypatch) -> None:
    """ctx + engagement_salt 가용 시 _attach_phase2_case_set 가 save_phase2_case_set 호출.

    invariant #88 — case_set artifact 영속화 hook. linker diagnostics 의
    key_mode_used 가 store manifest 의 key_mode 로 전달되어 정합 (#49).
    """
    orchestrator = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    linker.diagnostics["key_mode_used"] = "doc_id"  # store 가 받을 값 추적용
    _patch(monkeypatch, orchestrator=orchestrator, linker=linker)

    store_calls: list[dict[str, Any]] = []

    def _stub_store(**kwargs: Any):
        store_calls.append(kwargs)
        return SimpleNamespace(status="saved", manifest_path=None, diagnostics={})

    monkeypatch.setattr(
        "src.services.phase2_case_store.save_phase2_case_set",
        _stub_store,
    )

    phase1 = SimpleNamespace(cases=[])
    result = _make_result(phase1_case_result=phase1, batch_id="batch-007")
    ctx = SimpleNamespace(engagement_id="eng-A")
    _attach_phase2_case_set(result, ctx=ctx, snapshot=None)

    assert len(store_calls) == 1
    call = store_calls[0]
    assert call["batch_id"] == "batch-007"
    assert call["salt"] == "eng-A|batch-007"
    # linker 의 resolved key_mode_used 가 store key_mode 로 전달 (manifest 정합).
    assert call["key_mode"] == "doc_id"
    assert call["case_set"] is linker.linked_case_set


def test_attach_skips_store_when_ctx_or_salt_missing(monkeypatch) -> None:
    """ctx None 또는 engagement_id 부재 → store 호출 skip (warning 없이 silent)."""
    orchestrator = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orchestrator, linker=linker)

    store_calls: list[dict[str, Any]] = []

    def _stub_store(**kwargs: Any):
        store_calls.append(kwargs)
        return SimpleNamespace(status="saved", manifest_path=None, diagnostics={})

    monkeypatch.setattr(
        "src.services.phase2_case_store.save_phase2_case_set",
        _stub_store,
    )

    phase1 = SimpleNamespace(cases=[])
    result = _make_result(phase1_case_result=phase1)
    # ctx None → salt 도출 불가 → store skip.
    _attach_phase2_case_set(result, ctx=None, snapshot=None)
    assert len(store_calls) == 0


def test_attach_records_warning_when_store_status_not_saved(monkeypatch) -> None:
    """store 가 status != 'saved' 반환 시 warning 누적, inference 계속 (#88 best-effort)."""
    orchestrator = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orchestrator, linker=linker)

    def _failing_store(**kwargs: Any):
        return SimpleNamespace(
            status="row_ref_map_hash_mismatch",
            manifest_path=None,
            diagnostics={},
        )

    monkeypatch.setattr(
        "src.services.phase2_case_store.save_phase2_case_set",
        _failing_store,
    )

    phase1 = SimpleNamespace(cases=[])
    result = _make_result(phase1_case_result=phase1, batch_id="batch-009")
    ctx = SimpleNamespace(engagement_id="eng-fail")
    _attach_phase2_case_set(result, ctx=ctx, snapshot=None)

    # warning 누적 확인.
    warnings = getattr(result, "warnings", [])
    assert any("phase2_case_set persist skipped" in w for w in warnings)
    assert any("row_ref_map_hash_mismatch" in w for w in warnings)
    # case_set 은 여전히 부착 (best-effort).
    assert result.phase2_case_set is not None


def test_attach_records_warning_when_store_raises_exception(monkeypatch) -> None:
    """store 가 예외 던질 때 warning 누적 + inference 계속 (#88 best-effort)."""
    orchestrator = _OrchestratorRecorder()
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orchestrator, linker=linker)

    def _exploding_store(**kwargs: Any):
        raise OSError("disk full simulated")

    monkeypatch.setattr(
        "src.services.phase2_case_store.save_phase2_case_set",
        _exploding_store,
    )

    phase1 = SimpleNamespace(cases=[])
    result = _make_result(phase1_case_result=phase1, batch_id="batch-010")
    ctx = SimpleNamespace(engagement_id="eng-explode")
    _attach_phase2_case_set(result, ctx=ctx, snapshot=None)

    warnings = getattr(result, "warnings", [])
    assert any("phase2_case_set persist failed" in w for w in warnings)
    assert any("disk full simulated" in w for w in warnings)
    # exception 후에도 case_set 은 부착되어 있어야 함 (in-memory 보존).
    assert result.phase2_case_set is not None


def test_attach_phase2_case_overlays_uses_document_case_set_context() -> None:
    """P3 wiring: inference overlay consumes attached document-case context."""
    df = pd.DataFrame({"document_id": ["D1", "D1", "D2"]})
    row0 = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="D1",
        raw_line_number="1",
        company_code="C01",
    )
    row1 = make_row_ref(
        row_position=1,
        index_label=1,
        document_id="D1",
        raw_line_number="2",
        company_code="C01",
    )
    document_case = UnsupervisedCase(
        phase2_case_id="p2_unsupervised_document_d1",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="document",
        row_refs=(row0, row1),
        evidence_tier="ml_quantile",
        case_generation_reason={"gate": "unsupervised_ecdf"},
        family_score=0.97,
        family_ecdf=0.99,
        anomaly_score=0.97,
        top_features=(
            {
                "feature_id": "num__posting_date_weekend",
                "contrib": 0.55,
                "tag": "unusual_timing",
                "label_ko": "비정상 거래시점",
            },
        ),
        document_id="D1",
        evidence_row_count=2,
        top_score_mean=0.91,
        score_spread=0.12,
        max_score_row_ref=row1,
        amount_tail_context=0.8,
        period_end_context=0.7,
        account_rarity_context=0.25,
        process_rarity_context=0.5,
        repeated_normal_pressure=0.0,
    )
    result = SimpleNamespace(
        data=df,
        results=[
            DetectionResult(
                track_name="ml_unsupervised",
                flagged_indices=[0, 1],
                scores=pd.Series([0.2, 0.3, 0.0], index=df.index),
                rule_flags=[],
                details=pd.DataFrame({"ML02": [0.2, 0.3, 0.0]}, index=df.index),
                metadata={},
            )
        ],
        phase1_case_result=_phase1_result(),
        phase2_case_set=Phase2CaseSet(unsupervised_cases=(document_case,)),
        detector_statuses=[],
    )

    _attach_phase2_case_overlays(result)

    overlay = result.phase2_case_overlays[0]
    contribution = next(
        item for item in overlay["family_contributions"] if item["family"] == "unsupervised"
    )
    assert overlay["phase2_family_scores"]["unsupervised"] == 0.97
    assert contribution["unit_type"] == "document"
    assert contribution["evidence_row_count"] == 2
    assert contribution["top_score_mean"] == 0.91
    assert "document_id" not in contribution["document_context"]
    assert "max_score_row_ref" not in contribution["document_context"]
