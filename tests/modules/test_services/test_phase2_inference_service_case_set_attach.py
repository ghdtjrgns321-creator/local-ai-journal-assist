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

from src.models.phase2_case import (
    DuplicateCase,
    IntercompanyCase,
    Phase2CaseSet,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
    make_row_ref,
)
from src.services.phase2_case_phase1_linker import LinkerResult
from src.services.phase2_inference_service import _attach_phase2_case_set

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
    """empty 5 family case_set. orchestrator stub 이 반환할 sentinel."""
    return Phase2CaseSet()


def _make_intercompany_case_set() -> Phase2CaseSet:
    left = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="DOC-IC-A",
        raw_line_number="1",
        company_code="C01",
    )
    right = make_row_ref(
        row_position=1,
        index_label=1,
        document_id="DOC-IC-A",
        raw_line_number="2",
        company_code="C02",
    )
    reciprocal = IntercompanyCase(
        phase2_case_id="p2_intercompany_pair_reciprocal001",
        batch_id="bid-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason={"gate": "ic_strong_evidence", "ic_role": "reciprocal_flow"},
        family_score=1.0,
        family_ecdf=0.0,
        ic_role="reciprocal_flow",
        counterparty_pair=("C01", "C02"),
        amount_a=100.0,
        amount_b=100.0,
        amount_symmetry=1.0,
    )
    mismatch = IntercompanyCase(
        phase2_case_id="p2_intercompany_pair_mismatch001",
        batch_id="bid-1",
        family="intercompany",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="moderate",
        case_generation_reason={"gate": "ic_moderate_evidence", "ic_role": "amount_mismatch"},
        family_score=0.7,
        family_ecdf=0.0,
        ic_role="amount_mismatch",
        counterparty_pair=("C01", "C02"),
        amount_a=100.0,
        amount_b=90.0,
        amount_symmetry=0.9,
    )
    return Phase2CaseSet(intercompany_cases=(reciprocal, mismatch))


def _make_duplicate_case_set() -> Phase2CaseSet:
    left = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="DOC-DUP-A",
        raw_line_number="1",
        company_code="C01",
    )
    right = make_row_ref(
        row_position=1,
        index_label=1,
        document_id="DOC-DUP-B",
        raw_line_number="2",
        company_code="C01",
    )
    duplicate = DuplicateCase(
        phase2_case_id="p2_duplicate_pair_fixture001",
        batch_id="bid-1",
        family="duplicate",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason={"gate": "case_grade_pair"},
        family_score=1.0,
        family_ecdf=0.0,
        pair_id="pair-fixture",
        sub_rule="L2-03a",
        left_ref=left,
        right_ref=right,
        pair_evidence_tier="strong",
    )
    return Phase2CaseSet(duplicate_cases=(duplicate,))


def _make_relational_case_set() -> Phase2CaseSet:
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id="DOC-REL-A",
        raw_line_number="1",
        company_code="C01",
    )
    case = RelationalCase(
        phase2_case_id="p2_relational_edge_fixture001",
        batch_id="bid-1",
        family="relational",
        unit_type="edge",
        row_refs=(ref,),
        evidence_tier="strong",
        case_generation_reason={"gate": "relational_edge_artifact"},
        family_score=0.8,
        family_ecdf=0.99,
        sub_rule="R03",
        edge_a="partner-a",
        edge_b="account-b",
        metric_name="transfer_pricing_deviation",
        metric_value=1.2,
    )
    return Phase2CaseSet(relational_cases=(case,))


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
        phase2_case_id="p2_unsupervised_row_first001",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="row",
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
        phase2_case_id="p2_unsupervised_row_second002",
        batch_id="bid-1",
        family="unsupervised",
        unit_type="row",
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


def test_attach_records_intercompany_policy_summary_without_changing_ranking(monkeypatch) -> None:
    """IntercompanyCase reaches PipelineResult with aggregate-only policy metadata."""
    sentinel_case_set = _make_intercompany_case_set()
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert result.phase2_case_set is sentinel_case_set
    assert len(result.phase2_case_set.intercompany_cases) == 2
    summary = result.phase2_family_policy_summary["intercompany"]
    assert summary["primary_product_role"] == "ic_specific_evidence_strengthening"
    assert summary["broad_recall_expansion_family"] is False
    assert summary["production_adoption"] is False
    assert summary["production_ranking_changed"] is False
    assert summary["new_policy_adopted"] is False
    assert summary["ic_gate_changed"] is False
    assert summary["phase2_fusion_changed"] is False
    assert summary["phase1_ranking_changed"] is False
    assert summary["case_count"] == 2
    assert summary["reciprocal_flow_case_count"] == 1
    assert summary["amount_mismatch_case_count"] == 1
    assert "not that IC is disabled" in summary["interpretation"]


def test_attach_records_duplicate_policy_summary_without_replacing_case_order(
    monkeypatch,
) -> None:
    """Duplicate policy metadata is sidecar-only and does not replace case ordering."""
    sentinel_case_set = _make_duplicate_case_set()
    native_order_before = tuple(case.phase2_case_id for case in sentinel_case_set.duplicate_cases)
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert result.phase2_case_set is sentinel_case_set
    assert tuple(case.phase2_case_id for case in result.phase2_case_set.duplicate_cases) == (
        native_order_before
    )
    summary = result.phase2_family_policy_summary["duplicate"]
    assert summary["primary_product_role"] == (
        "bounded_pair_evidence_first_review_with_case_grade_sidecar"
    )
    assert summary["production_adoption"] is True
    assert summary["adoption_scope"] == (
        "bounded_candidate_subset_and_pair_artifact_selection"
    )
    assert summary["production_first_review_ranking_changed"] is True
    assert summary["native_ordering_changed"] is True
    assert summary["production_default_selector_changed"] is True
    assert summary["candidate_subset_supplement_changed"] is True
    assert summary["pair_artifact_selection_strategy_changed"] is True
    assert summary["document_profile_pair_builder_added"] is True
    assert summary["phase2_fusion_changed"] is False
    assert summary["phase1_ranking_changed"] is False
    assert summary["recommended_first_review_surface"] == (
        "bounded_observable_profile_rule_balanced_pair_surface"
    )
    assert summary["recommended_sidecar_surface"] == "current_plus_case_grade_sidecar"
    assert summary["v31_primary_target_status"] == "pending_pair_evidence_validation"
    assert summary["v31_primary_candidate_docs"] == 76
    assert summary["v31_primary_pair_groups"] == 38
    assert summary["v31_native_top500_primary_docs"] == 0
    assert summary["v31_primary_recall_applicable"] is False
    assert "observable row-score and pair generation path" in (
        summary["v31_primary_pending_reason"]
    )
    assert summary["missed_potential_explainable"] is True
    assert summary["missed_potential_primary_reason"] == (
        "weak_pair_only_and_artifact_cap_boundary"
    )
    assert summary["ranking_change_rejected_reason"] == (
        "would sacrifice current captured high-quality pair evidence"
    )
    assert summary["weak_pair_promotion_allowed"] is False
    assert summary["case_count"] == 1
    assert summary["primary_target_artifact_path"] == (
        "artifacts/duplicate_primary_target_fixed5_dupmeta_20260530.json"
    )
    assert summary["candidate_sidecar_artifact_path"] == (
        "artifacts/duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json"
    )
    assert summary["v31_primary_readiness_artifact_path"] == (
        "artifacts/duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json"
    )
    assert summary["v33_exact_sidecar_artifact_path"] == (
        "artifacts/duplicate_v33_exact_sidecar_fixed5_20260531.json"
    )
    assert summary["v33_current_path_fixed5_ownermeta_v33b"] == {
        "primary_target_docs": 22,
        "companion_target_docs": 71,
        "candidate_subset_primary_docs": 22,
        "candidate_subset_companion_docs": 34,
        "case_grade_primary_docs": 10,
        "case_grade_companion_docs": 4,
        "primary_case_grade_recall": 0.45454545454545453,
        "companion_case_grade_recall": 0.056338028169014086,
        "candidate_subset_supplement_docs": 500,
        "candidate_subset_supplement_rows": 1034,
        "pair_rule_distribution": {
            "L2-03a": 275,
            "L2-03b": 166,
            "L2-03e": 59,
        },
    }
    assert summary["primary_target_attrition_fixed5_dupmeta"] == {
        "primary_target_docs": 76,
        "row_score_primary_docs": 28,
        "candidate_subset_primary_docs": 0,
        "generated_pair_primary_docs": 0,
        "duplicate_case_primary_docs": 0,
        "no_row_score_primary_docs": 48,
        "low_score_l2_03d_primary_docs": 28,
        "main_candidate_subset_min_score": 0.5989857631894374,
        "primary_l2_03d_score": 0.42857142857142855,
        "top_pairs_cap_is_bottleneck": False,
    }
    assert summary["v31_primary_readiness_fixed5_dupmeta"] == {
        "primary_pair_groups": 38,
        "primary_row_score_hit_row_count": 54,
        "primary_rule_doc_counts": {
            "L2-03a": 0,
            "L2-03b": 0,
            "L2-03c": 0,
            "L2-03d": 28,
        },
        "primary_l2_03d_below_candidate_floor": True,
        "generated_pair_primary_docs": 0,
        "top_pairs_primary_docs": 0,
        "case_grade_top_pairs_primary_docs": 0,
        "non_oracle_sidecar_pair_feasibility_confirmed": False,
        "oracle_probe_weak_pair_ratio": 0.9775862068965517,
        "next_improvement_class": (
            "row_score_feature_coverage_or_observable_lower_score_pair_path"
        ),
    }
    assert summary["v31_primary_gap_decomposition_fixed5_dupmeta"] == {
        "no_row_score_primary_docs": {
            "doc_count": 48,
            "pair_group_count": 24,
            "time_shift_bucket_distribution": {"1_3d": 48},
            "amount_similarity_bucket_distribution": {"near": 48},
            "reference_similarity_bucket_distribution": {"exact": 48},
            "text_similarity_bucket_distribution": {"medium": 48},
            "partner_match_ratio": 1.0,
            "same_account_ratio": 0.0,
            "same_business_process_ratio": 1.0,
            "phase1_action_tier_distribution": {
                "low": 5,
                "medium": 4,
                "none": 39,
            },
        },
        "low_score_l2_03d_primary_docs": {
            "doc_count": 28,
            "pair_group_count": 14,
            "row_score_hit_row_count": 54,
            "score_floor_gap": 0.17041433461800887,
            "primary_to_candidate_floor_ratio": 0.7154951835405927,
            "phase1_action_tier_distribution": {
                "low": 13,
                "medium": 15,
            },
        },
    }
    assert summary["v31_non_oracle_sidecar_failure_fixed5_dupmeta"] == {
        "l2_03d_stratified_primary_docs": 0,
        "rule_balanced_primary_docs": 0,
        "non_oracle_candidate_docs_per_sample": 10000,
        "l2_03d_sample_rule_distribution": {"L2-03b": 5000},
        "rule_balanced_sample_rule_distribution": {
            "L2-03a": 434,
            "L2-03b": 3910,
            "L2-03d": 656,
        },
        "oracle_probe_case_grade_pair_ratio": 0.022413793103448276,
        "oracle_probe_usable_as_product_selector": False,
    }
    assert summary["candidate_sidecar_result_fixed5_dupmeta"] == {
        "non_oracle_sidecar_pair_feasibility_confirmed": False,
        "oracle_probe_primary_docs": 76,
        "oracle_probe_weak_pair_ratio": 0.9775862068965517,
        "product_sidecar_adoption_allowed": False,
    }
    assert summary["primary_target_guardrails"] == {
        "do_not_use_duplicate_primary_metadata_as_selector": True,
        "do_not_relax_row_score_threshold_for_fixed5": True,
        "do_not_expand_top_pairs_cap_as_primary_fix": True,
        "do_not_promote_weak_pairs_to_duplicate_case": True,
        "preserve_current_first_review_ordering": False,
        "do_not_use_truth_or_owner_metadata_as_selector": True,
    }

    descriptor = summary["sidecar_descriptor"]
    assert descriptor["sidecar_surface_id"] == "duplicate_case_grade_sidecar_v1"
    assert descriptor["sidecar_case_grade_only"] is True
    assert descriptor["sidecar_weak_pair_ratio"] == 0.0
    assert descriptor["sidecar_top500_truth_docs"] == 36
    assert descriptor["first_review_top100_captured_outside_phase1_top100"] == 19
    assert descriptor["missed_potential_count"] == 5
    assert descriptor["weak_pair_only_missed_count"] == 3
    assert descriptor["artifact_cap_boundary_missed_count"] == 2
    assert descriptor["replaces_default_duplicate_case_ordering"] is False
    assert descriptor["weak_pair_promotion_allowed"] is False
    assert descriptor["raw_identifier_leak_check"] == {
        "doc_like_token_count": 0,
        "forbidden_identifier_key_count": 0,
        "forbidden_identifier_value_count": 0,
        "phase2_case_id_like_token_count": 0,
    }


def test_attach_records_relational_relmeta_policy_without_changing_order(monkeypatch) -> None:
    """Relational policy metadata exposes relmeta target status without reordering."""
    sentinel_case_set = _make_relational_case_set()
    native_order_before = tuple(
        case.phase2_case_id for case in sentinel_case_set.relational_cases
    )
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert result.phase2_case_set is sentinel_case_set
    assert tuple(
        case.phase2_case_id for case in result.phase2_case_set.relational_cases
    ) == native_order_before
    summary = result.phase2_family_policy_summary["relational"]
    assert summary["primary_product_role"] == "relationship_evidence_review_surface"
    assert summary["role_scope"] == "relationship_review_surface_primary_pending"
    assert summary["primary_target_status"] == "pending_relationship_primary_metadata"
    assert (
        summary["primary_denominator_status"]
        == "pending_relationship_primary_metadata"
    )
    assert summary["primary_target_recall_applicable"] is False
    assert "no relationship-primary denominator" in summary["primary_recall_pending_reason"]
    assert summary["primary_recall_tuning_allowed"] is False
    assert summary["primary_recall_tuning_blocked_until_metadata"] is True
    assert summary["primary_target_truth_docs"] == 0
    assert summary["primary_target_matched_docs"] == 0
    assert summary["primary_target_recall_fixed5_relmeta"] is None
    assert summary["co_primary_allowed_by_policy"] is True
    assert summary["co_primary_with"] == []
    assert summary["co_primary_overlap_count"] == 0
    assert summary["adopted_surface"] == (
        "structural_moderate_audit_then_business_lane_split_v1"
    )
    assert summary["primary_metadata_backlog"] == (
        "injected_relationship_edge_primary",
        "relationship_edge_semantic_group",
    )
    assert summary["structural_lane_sub_rules"] == ("R03", "R07")
    assert summary["moderate_audit_business_lane_sub_rules"] == ("R01", "R02")
    assert summary["context_lane_sub_rules"] == ("R05", "R06")
    assert summary["r05_r06_primary_surface_default"] is False
    assert summary["fixed5_ratio_tuning_allowed"] is False
    assert summary["production_ranking_changed"] is False
    assert summary["detector_gate_changed"] is False
    assert summary["phase2_fusion_changed"] is False
    assert summary["case_count"] == 1

    coverage = summary["relationship_companion_coverage_fixed5_v32d"]
    assert coverage["truth_docs"] == 139
    assert coverage["matched_docs"] == 33
    assert coverage["recall"] == 33 / 139
    assert coverage["metric_role"] == (
        "interim_relationship_evidence_surface_until_primary_denominator_available"
    )
    assert summary["guardrails"] == {
        "do_not_claim_primary_recall_without_primary_denominator": True,
        "do_not_treat_pending_denominator_as_family_retirement": True,
        "do_not_mix_r05_r06_into_primary_surface": True,
        "do_not_tune_against_fixed5_truth_ratio": True,
        "preserve_audit_then_business_ordering": True,
        "relationship_sidecar_used_for_detector_or_ranking": False,
    }


def test_attach_records_timeseries_default_stabilized_policy(
    monkeypatch,
) -> None:
    """Timeseries metadata records stabilized ordering as the product default."""
    sentinel_case_set = _make_timeseries_case_set()
    native_order_before = tuple(
        case.phase2_case_id for case in sentinel_case_set.timeseries_cases
    )
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    assert tuple(
        case.phase2_case_id for case in result.phase2_case_set.timeseries_cases
    ) == native_order_before
    summary = result.phase2_family_policy_summary["timeseries"]
    assert summary["primary_product_role"] == "timing_primary_diagnostic_candidate"
    assert summary["production_adoption"] is True
    assert summary["production_default_ordering_changed"] is True
    assert summary["native_ordering_changed"] is True
    assert summary["explicit_ordering_flag_available"] is True
    assert summary["default_ordering_strategy"] == (
        "ts_specific_top100_stabilized_surface"
    )
    assert summary["native_ordering_fallback"] is True
    assert summary["candidate_ordering_strategy"] == (
        "ts_specific_top100_stabilized_surface"
    )
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


def test_attach_records_unsupervised_default_document_review_priority_policy(
    monkeypatch,
) -> None:
    """Unsupervised metadata records default soft-guard display ordering."""
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
    assert tuple(
        case.phase2_case_id for case in result.phase2_case_set.unsupervised_cases
    ) == native_order_before
    summary = result.phase2_family_policy_summary["unsupervised"]
    assert (
        summary["primary_product_role"]
        == "broad_statistical_review_companion_evidence_surface"
    )
    assert summary["product_role"] == "broad_statistical_review_companion_evidence_surface"
    assert summary["role_scope"] == "broad_statistical_review_companion"
    assert summary["fraud_primary_recall_family"] is False
    assert summary["primary_recall_metric_role"] == "diagnostic_only_not_product_judgement"
    assert summary["native_row_ordering_changed"] is True
    assert summary["production_default_ranking_changed"] is True
    assert summary["production_adoption"] is True
    assert summary["adoption_candidate"] is False
    assert summary["recommended_surface"] == "hybrid_with_soft_repeated_normal_guard"
    assert summary["default_display_ordering"] == "hybrid_with_soft_repeated_normal_guard"
    assert summary["case_generation_changed"] is False
    assert summary["evidence_quality_ready"] is True
    assert summary["evidence_quality_improved"] is True
    assert summary["top_features_connected"] is True
    assert summary["q95_gate_change_recommended"] is False
    assert "q95 gate" in summary["adoption_note"]
    assert summary["case_count"] == 2
    assert summary["top_features_available_case_count"] == 2
    companion = summary["optional_companion_surface"]
    assert (
        companion["policy_id"]
        == "unsupervised_document_review_priority_soft_guard_v1"
    )
    assert companion["surface_name"] == "hybrid_with_soft_repeated_normal_guard"
    assert companion["v31_owner_surface_artifact_path"] == (
        "artifacts/unsupervised_v31_owner_surface_fixed5_20260531.json"
    )
    assert companion["adoption_state"] == "adopted_default_display_ordering"
    assert companion["descriptor_only"] is False
    assert companion["replaces_native_case_ordering"] is True
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
    assert (
        judgement["repeated_normal_pressure"]["recommended_surface_top500_fixed5"]
        == 0.256
    )
    assert (
        judgement["outside_phase1_complement"][
            "top500_phase1_immediate_review_outside_truth_docs"
        ]
        == 95
    )
    assert judgement["evidence_explainability"]["top_features_connected"] is True
    responsibility = summary["responsibility_target"]
    assert (
        responsibility["primary_target_status"]
        == "debug_only_historical_v31_not_product_goal"
    )
    assert (
        responsibility["primary_target_metric_role"]
        == "debug_only_not_fraud_primary_recall"
    )
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
    assert (
        responsibility["soft_guard_phase1_immediate_outside_top500_primary_docs_fixed5"]
        == 110
    )
    assert (
        responsibility["soft_guard_phase1_review_or_above_outside_top500_primary_docs_fixed5"]
        == 74
    )
    assert (
        responsibility["soft_guard_phase1_candidate_or_above_outside_top500_primary_docs_fixed5"]
        == 73
    )
    assert responsibility["native_row_queue_top500_companion_docs_fixed5"] == 34
    assert responsibility["soft_guard_top500_companion_docs_fixed5"] == 33
    assert (
        responsibility["soft_guard_phase1_immediate_outside_top500_companion_docs_fixed5"]
        == 33
    )
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
    assert (
        readiness["soft_guard_role"]
        == "broad_statistical_companion_default_document_review_priority"
    )
    assert readiness["product_default_adoption"] is True
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
        summary["pressure_monitoring"][
            "v31_primary_soft_guard_repeated_normal_pressure_top500"
        ]
        == 0.336
    )
    assert (
        summary["pressure_monitoring"][
            "v31_primary_soft_guard_period_end_normal_background_top500"
        ]
        == 0.578
    )
    assert summary["q95_backlog_policy"]["near_miss_promoted_to_case"] is False
    assert summary["anti_fitting_guardrails"]["hybrid_upper_bound_default_adoption"] is False
    assert summary["anti_fitting_guardrails"]["q95_gate_relaxation"] is False
    assert summary["anti_fitting_guardrails"]["vae_score_threshold_recall_fitting"] is False
    assert summary["anti_fitting_guardrails"]["threshold_or_weight_recall_fitting"] is False
    assert summary["anti_fitting_guardrails"]["top_features_used_for_ranking"] is False
    assert summary["anti_fitting_guardrails"]["phase1_prior_disguised_as_vae"] is False
    assert (
        summary["anti_fitting_guardrails"]["datasynth_changed_to_match_vae_score"]
        is False
    )
    assert (
        summary["anti_fitting_guardrails"][
            "truth_owner_scenario_shortcut_feature_allowed"
        ]
        is False
    )
    assert (
        summary["anti_fitting_guardrails"]["truth_or_owner_metadata_used_as_selector"]
        is False
    )


def test_intercompany_policy_summary_does_not_import_relational_builder(monkeypatch) -> None:
    """IC policy metadata must not depend on relational builder import health."""
    sentinel_case_set = _make_intercompany_case_set()
    orch = _OrchestratorRecorder(case_set=sentinel_case_set)
    linker = _LinkerRecorder()
    _patch(monkeypatch, orchestrator=orch, linker=linker)

    real_import = builtins.__import__

    def _guarded_import(name: str, *args: Any, **kwargs: Any):
        if name == "src.services.phase2_relational_case_builder":
            raise ImportError("simulated relational builder import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    result = _make_result(phase1_case_result=None)
    _attach_phase2_case_set(result, ctx=None, snapshot=None)

    summary = result.phase2_family_policy_summary["intercompany"]
    assert summary["primary_product_role"] == "ic_specific_evidence_strengthening"
    assert summary["case_count"] == 2


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
