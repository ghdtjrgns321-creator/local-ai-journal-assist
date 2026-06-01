"""`build_relational_cases` PHASE2 RelationalCase 변환 계약 검증 (v7-plan S6 Phase C).

Why: relational_edge_artifact.edges → RelationalCase tuple.
Gate (invariant #64): evidence_tier == 'strong' OR (
    moderate AND positive_metric_count >= 20 AND family_ecdf >= 0.95
).
family_ecdf 는 artifact edge metric_value 의 zero-preserving ECDF 로 계산한다.

evidence_signature 는 sub_rule + edge_a + edge_b 만 — metric_value/raw score 절대
포함 금지 (invariant #64).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.detection.base import DetectionResult
from src.models.phase2_case import RelationalCase
from src.services.phase2_relational_case_builder import (
    RELATIONAL_PRODUCT_ROLE,
    RELATIONAL_REVIEW_SURFACE_NAME,
    RELATIONAL_REVIEW_SURFACE_POLICY,
    build_relational_cases,
    sort_relational_cases_for_review_surface,
)

# ── fixtures ────────────────────────────────────────────────


def _make_df() -> pd.DataFrame:
    """3-row relational fixture — document_id / company_code / trading_partner / gl_account."""
    return pd.DataFrame(
        {
            "document_id": ["DOC100", "DOC101", "DOC102"],
            "line_number": [1, 1, 1],
            "trading_partner": ["V01", "RARE_V", "U99"],
            "gl_account": ["5100", "9999", "5200"],
            "debit_amount": [1_000_000.0, 50_000_000.0, 2_000_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "company_code": ["C01", "C01", "C01"],
        },
        index=pd.Index([10, 11, 12]),
    )


def _make_result(
    *,
    edge_artifact: dict[str, Any] | None,
    track_name: str = "relational",
    extra_metadata: dict[str, Any] | None = None,
) -> DetectionResult:
    metadata: dict[str, Any] = {}
    if extra_metadata:
        metadata.update(extra_metadata)
    if edge_artifact is not None:
        metadata["relational_edge_artifact"] = edge_artifact
    return DetectionResult(
        track_name=track_name,
        flagged_indices=[],
        scores=pd.Series([0.0, 0.0, 0.0], index=[10, 11, 12]),
        rule_flags=[],
        details=pd.DataFrame(),
        metadata=metadata,
    )


def _strong_artifact() -> dict[str, Any]:
    """R05 strong edge — RARE_V × 9999 (label=11, position=1)."""
    return {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [11],
                "row_positions": [1],
                "edge_a": "RARE_V",
                "edge_b": "9999",
                "metric_name": "rare_pair_score",
                "metric_value": 0.85,
                "evidence_tier": "strong",
            }
        ],
        "coverage": {"R05": 1},
    }


def _moderate_artifact() -> dict[str, Any]:
    """R01 moderate edge — V01 × "" (label=10, position=0)."""
    return {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R01",
                "row_indices": [10],
                "row_positions": [0],
                "edge_a": "V01",
                "edge_b": "",
                "metric_name": "new_counterparty_score",
                "metric_value": 0.5,
                "evidence_tier": "moderate",
            }
        ],
        "coverage": {"R01": 1},
    }


def _weak_artifact() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [12],
                "row_positions": [2],
                "edge_a": "U99",
                "edge_b": "5200",
                "metric_name": "rare_pair_score",
                "metric_value": 0.2,
                "evidence_tier": "weak",
            }
        ],
        "coverage": {"R05": 1},
    }


# ── 1. 빈 metadata graceful ─────────────────────────────────


def test_empty_metadata_returns_empty_tuple():
    """relational_edge_artifact 부재 → 빈 tuple (invariant #68)."""
    df = _make_df()
    result = _make_result(edge_artifact=None)
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()
    assert isinstance(cases, tuple)


# ── 2. strong tier emit ─────────────────────────────────────


def test_strong_tier_edge_emits_case():
    """evidence_tier=strong edge → RelationalCase 생성."""
    df = _make_df()
    result = _make_result(edge_artifact=_strong_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, RelationalCase)
    assert case.family == "relational"
    assert case.unit_type == "edge"
    assert case.evidence_tier == "strong"
    assert case.sub_rule == "R05"
    assert case.edge_a == "RARE_V"
    assert case.edge_b == "9999"
    assert case.metric_name == "rare_pair_score"
    assert case.metric_value == 0.85


# ── 3. moderate tier ECDF gate ──────────────────────────────


def test_moderate_tier_edge_q95_passes_when_sample_is_sufficient():
    """moderate tier + family_ecdf q95+ + 최소 표본 충족 → case 생성."""
    df = _make_df()
    edges: list[dict[str, Any]] = []
    for idx in range(20):
        edges.append(
            {
                "rule_id": "R01",
                "row_indices": [10 + (idx % 3)],
                "row_positions": [idx % 3],
                "edge_a": f"V{idx:02d}",
                "edge_b": "",
                "metric_name": "new_counterparty_score",
                "metric_value": float(idx + 1),
                "evidence_tier": "moderate",
            }
        )
    artifact = {"schema_version": 1, "edges": edges, "coverage": {"R01": 20}}
    result = _make_result(edge_artifact=artifact)
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 2
    assert {case.edge_a for case in cases} == {"V18", "V19"}
    assert {case.family_ecdf for case in cases} == {0.95, 1.0}
    assert all(
        case.case_generation_reason["gate"] == "relational_moderate_family_ecdf_q95"
        for case in cases
    )
    assert all(case.case_generation_reason["positive_metric_count"] == 20 for case in cases)


def test_moderate_tier_single_edge_filtered_for_small_sample():
    """단일 moderate edge 는 q95 의미가 약하므로 case-grade 승격 보류."""
    df = _make_df()
    result = _make_result(edge_artifact=_moderate_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


# ── 4. weak tier 차단 ───────────────────────────────────────


def test_weak_tier_edge_excluded():
    """evidence_tier=weak → case 생성 안 함."""
    df = _make_df()
    result = _make_result(edge_artifact=_weak_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert cases == ()


# ── 5. case_id 접두사 ─────────────────────────────────────


def test_case_id_uses_canonicalized_row_refs():
    """case_id 는 canonical row_ref 기반 — prefix 'p2_relational_edge_'."""
    df = _make_df()
    result = _make_result(edge_artifact=_strong_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    assert cases[0].phase2_case_id.startswith("p2_relational_edge_")


# ── 6. evidence_signature 구성 ──────────────────────────────


def test_evidence_signature_contains_sub_rule_and_edge_keys():
    """sub_rule, edge_a, edge_b 가 모두 case_id 에 영향. 하나만 바뀌어도 case_id 변경."""
    df = _make_df()
    artifact_a = _strong_artifact()
    # edge_b 만 변경 — case_id 변경되어야 한다.
    artifact_b: dict[str, Any] = {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [11],
                "row_positions": [1],
                "edge_a": "RARE_V",
                "edge_b": "9000",  # ← 변경
                "metric_name": "rare_pair_score",
                "metric_value": 0.85,
                "evidence_tier": "strong",
            }
        ],
        "coverage": {"R05": 1},
    }
    cases_a = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_a),
        df=df,
    )
    cases_b = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_b),
        df=df,
    )
    assert cases_a[0].phase2_case_id != cases_b[0].phase2_case_id


def test_evidence_signature_does_not_include_metric_value():
    """metric_value 만 다르고 sub_rule + edge_a + edge_b + row 가 같으면 case_id 동일.

    invariant #64 — case identity 에 raw score 절대 포함 금지.
    """
    df = _make_df()
    artifact_a = _strong_artifact()
    artifact_b: dict[str, Any] = {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [11],
                "row_positions": [1],
                "edge_a": "RARE_V",
                "edge_b": "9999",
                "metric_name": "rare_pair_score",
                "metric_value": 0.123456,  # ← 변경 (raw score)
                "evidence_tier": "strong",
            }
        ],
        "coverage": {"R05": 1},
    }
    cases_a = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_a),
        df=df,
    )
    cases_b = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_b),
        df=df,
    )
    assert cases_a[0].phase2_case_id == cases_b[0].phase2_case_id
    # family_score 는 다름 (evidence payload).
    assert cases_a[0].family_score != cases_b[0].family_score


def test_evidence_signature_does_not_include_raw_score_or_threshold_fields():
    """raw_score / threshold 보조 필드가 있어도 case_id 는 흔들리지 않는다."""
    df = _make_df()
    artifact_a = _strong_artifact()
    artifact_b: dict[str, Any] = {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [11],
                "row_positions": [1],
                "edge_a": "RARE_V",
                "edge_b": "9999",
                "metric_name": "rare_pair_score",
                "metric_value": 0.85,
                "raw_score": 0.85,
                "threshold": 0.95,
                "evidence_tier": "strong",
            }
        ],
        "coverage": {"R05": 1},
    }
    cases_a = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_a),
        df=df,
    )
    cases_b = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact_b),
        df=df,
    )
    assert cases_a[0].phase2_case_id == cases_b[0].phase2_case_id


# ── 7. phase1_case_refs 초기 빈 ────────────────────────────


def test_phase1_case_refs_empty_by_default():
    """builder 출력은 phase1_case_refs=() (invariant #67). linker S4 가 부착."""
    df = _make_df()
    result = _make_result(edge_artifact=_strong_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert cases[0].phase1_case_refs == ()


# ── 8. row_refs canonical form ───────────────────────────────


def test_row_refs_index_label_uses_df_index_canonical_form():
    """row_refs[*].index_label 은 df.index[position] canonicalize 결과 (invariant #66).

    df.index=[10, 11, 12] → label=11 의 canonical 은 'i:11'.
    """
    df = _make_df()
    result = _make_result(edge_artifact=_strong_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    case = cases[0]
    assert len(case.row_refs) == 1
    assert case.row_refs[0].row_position == 1
    # canonicalize_ref_key (int) → 'i:11'.
    assert case.row_refs[0].index_label == "i:11"
    assert case.row_refs[0].document_id == "DOC101"


# ── 9. return type contract ─────────────────────────────────


def test_return_type_is_tuple_of_relational_case():
    """반환 타입은 항상 tuple[RelationalCase, ...]."""
    df = _make_df()
    result = _make_result(edge_artifact=_strong_artifact())
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert isinstance(cases, tuple)
    assert all(isinstance(c, RelationalCase) for c in cases)


# ── 10. multi-row edge → row_refs 다건 ─────────────────────


def test_multi_row_edge_includes_all_row_positions():
    """한 edge entry 의 row_positions 가 여러 개 → row_refs 도 모두 포함.

    Why (Δ5): edge 단위 dedup 결과 같은 (rule, edge_a, edge_b) 의 여러 row 가
    한 case 로 묶이므로, row_refs 가 그 row 들을 모두 보유해야 PHASE1 cross-ref
    가 누락 없이 회수된다.
    """
    df = _make_df()
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R05",
                "row_indices": [10, 11],
                "row_positions": [0, 1],
                "edge_a": "RARE_V",
                "edge_b": "9999",
                "metric_name": "rare_pair_score",
                "metric_value": 0.85,
                "evidence_tier": "strong",
            }
        ],
        "coverage": {"R05": 1},
    }
    result = _make_result(edge_artifact=artifact)
    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)
    assert len(cases) == 1
    case = cases[0]
    assert len(case.row_refs) == 2
    positions = {ref.row_position for ref in case.row_refs}
    assert positions == {0, 1}


def test_default_relational_review_surface_policy_interleaves_structural_and_moderate_tail():
    """Product default is 1:1 structural R03/R07 and R01/R02 moderate audit/business lane."""
    rows: list[dict[str, Any]] = []
    for idx in range(22):
        rows.append(
            {
                "document_id": f"DOC{idx:03d}",
                "line_number": 1,
                "company_code": "C01",
                "trading_partner": f"V{idx:03d}",
                "gl_account": "4100",
                "posting_date": f"2024-01-{(idx % 28) + 1:02d}",
                "business_process": "P2P" if idx % 2 else "O2C",
            }
        )
    df = pd.DataFrame(rows, index=pd.RangeIndex(len(rows)))
    edges: list[dict[str, Any]] = [
        {
            "rule_id": "R03",
            "row_indices": [0],
            "row_positions": [0],
            "edge_a": "IC_A",
            "edge_b": "4100",
            "metric_name": "transfer_pricing_score",
            "metric_value": 0.9,
            "evidence_tier": "strong",
        },
        {
            "rule_id": "R07",
            "row_indices": [1],
            "row_positions": [1],
            "edge_a": "PARTNER_DORMANT",
            "edge_b": "",
            "metric_name": "dormant_partner_score",
            "metric_value": 0.8,
            "evidence_tier": "strong",
        },
    ]
    for idx in range(20):
        pos = idx + 2
        edges.append(
            {
                "rule_id": "R01",
                "row_indices": [pos],
                "row_positions": [pos],
                "edge_a": f"NEW{idx:03d}",
                "edge_b": "",
                "metric_name": "new_counterparty_score",
                "metric_value": float(idx + 1),
                "evidence_tier": "moderate",
            }
        )
    result = _make_result(edge_artifact={"schema_version": 1, "edges": edges})

    cases = build_relational_cases(batch_id="b1", detection_result=result, df=df)

    assert [case.sub_rule for case in cases] == ["R03", "R01", "R07", "R01"]
    assert cases[0].case_generation_reason["relational_review_surface_policy"] == (
        RELATIONAL_REVIEW_SURFACE_POLICY
    )
    assert cases[0].case_generation_reason["relational_review_surface_name"] == (
        RELATIONAL_REVIEW_SURFACE_NAME
    )
    assert cases[0].case_generation_reason["relational_product_role"] == (
        RELATIONAL_PRODUCT_ROLE
    )
    assert (
        cases[0].case_generation_reason["relational_role_scope"]
        == "relationship_review_surface_primary_pending"
    )
    assert cases[0].case_generation_reason["relational_primary_denominator_status"] == (
        "pending_relationship_primary_metadata"
    )
    assert "unavailable" in cases[0].case_generation_reason[
        "relational_primary_recall_pending_reason"
    ]
    assert cases[0].case_generation_reason["relational_primary_metadata_backlog"] == (
        "injected_relationship_edge_primary",
        "relationship_edge_semantic_group",
    )
    assert cases[0].case_generation_reason["relational_structural_lane_sub_rules"] == (
        "R03",
        "R07",
    )
    assert cases[0].case_generation_reason[
        "relational_moderate_audit_business_lane_sub_rules"
    ] == ("R01", "R02")
    assert cases[0].case_generation_reason["relational_context_lane_sub_rules"] == (
        "R05",
        "R06",
    )
    assert (
        cases[0].case_generation_reason["relational_primary_recall_tuning_allowed"]
        is False
    )
    assert (
        cases[0].case_generation_reason[
            "relational_primary_recall_tuning_blocked_until_metadata"
        ]
        is True
    )
    assert cases[0].case_generation_reason["relational_review_surface_rank"] == 1


def test_relational_review_surface_sort_does_not_accept_truth_inputs():
    params = sort_relational_cases_for_review_surface.__annotations__

    assert "truth_docs" not in params
    assert "truth_scenario_by_doc" not in params


def test_employee_vendor_profile_prefix_uses_observable_inputs_only():
    """Employee/vendor profile prefix can surface relationship cases without truth inputs."""
    df = pd.DataFrame(
        {
            "document_id": ["DOC-EV", "DOC-STRUCT"],
            "line_number": [1, 1],
            "company_code": ["C01", "C01"],
            "trading_partner": ["vendor reimbursement channel", "IC-PARTNER"],
            "reference": ["staff supplier reimbursement", "ordinary transfer"],
            "gl_account": ["1100", "4100"],
            "posting_date": ["2024-01-01", "2024-01-02"],
            "business_process": ["P2P", "O2C"],
        },
        index=pd.RangeIndex(2),
    )
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "edges": [
            {
                "rule_id": "R07",
                "row_indices": [1],
                "row_positions": [1],
                "edge_a": "IC-PARTNER",
                "edge_b": "",
                "metric_name": "dormant_partner_score",
                "metric_value": 0.99,
                "evidence_tier": "strong",
            },
            {
                "rule_id": "R07",
                "row_indices": [0],
                "row_positions": [0],
                "edge_a": "VENDOR-REIMBURSE",
                "edge_b": "",
                "metric_name": "dormant_partner_score",
                "metric_value": 0.50,
                "evidence_tier": "strong",
            },
        ],
    }

    cases = build_relational_cases(
        batch_id="b1",
        detection_result=_make_result(edge_artifact=artifact),
        df=df,
    )

    assert [case.edge_a for case in cases] == ["VENDOR-REIMBURSE", "IC-PARTNER"]
    reason = cases[0].case_generation_reason
    assert reason["relational_employee_vendor_profile_prefix_size"] == 100
    assert reason["relational_employee_vendor_profile_prefix_inputs"] == (
        "reference/trading_partner text, business_process, account_class, "
        "document_support"
    )
    assert reason["relational_primary_recall_tuning_allowed"] is False
