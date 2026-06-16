"""Phase2RowRef + make_row_ref + Phase2CaseBase/Set 테스트.

v7-plan S1 단일 출처 테스트명. line_number_key 정규화 미적용 (S4 deferred)
와 with_phase1_refs 정렬·linked=True 부착을 검증한다.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from src.models.phase2_case import (
    DuplicateCase,
    IntercompanyCase,
    Phase2CaseBase,
    Phase2CaseSet,
    Phase2RowRef,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
    make_row_ref,
)

# ---------------------------------------------------------------------------
# Phase2RowRef immutability + 필드 옵셔널성
# ---------------------------------------------------------------------------


def test_phase2_row_ref_frozen() -> None:
    """frozen dataclass — 필드 변경 시 FrozenInstanceError."""
    ref = Phase2RowRef(
        row_position=0,
        index_label="s:A",
        document_id="doc-1",
        line_number_key="i:1",
        company_code="CO-001",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.row_position = 99  # type: ignore[misc]


def test_phase2_row_ref_company_code_optional() -> None:
    """company_code 는 None 허용."""
    ref = Phase2RowRef(
        row_position=0,
        index_label="s:A",
        document_id="doc-1",
        line_number_key="i:1",
        company_code=None,
    )
    assert ref.company_code is None


# ---------------------------------------------------------------------------
# make_row_ref — canonicalize 위임 + None 수렴
# ---------------------------------------------------------------------------


def test_make_row_ref_helper_basic() -> None:
    """raw_line_number=1 → canonical "i:1" 이 line_number_key 에 그대로 저장."""
    ref = make_row_ref(
        row_position=3,
        index_label=10,
        document_id="doc-1",
        raw_line_number=1,
        company_code="CO-001",
    )
    assert ref.row_position == 3
    # make_row_ref 가 canonicalize 통과 — int 10 → "i:10".
    assert ref.index_label == "i:10"
    assert ref.document_id == "doc-1"
    assert ref.line_number_key == "i:1"
    assert ref.company_code == "CO-001"


def test_line_number_key_preserves_dtype_difference_until_s4() -> None:
    """문자열 "0001" 과 정수 1 은 다른 line_number_key — S4 까지 dtype 보존."""
    ref_str = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number="0001",
        company_code=None,
    )
    ref_int = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number=1,
        company_code=None,
    )
    assert ref_str.line_number_key == "s:0001"
    assert ref_int.line_number_key == "i:1"
    assert ref_str.line_number_key != ref_int.line_number_key


def test_line_number_key_nan_collapses_to_none() -> None:
    """float NaN → canonicalize "n:" → None."""
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number=float("nan"),
        company_code=None,
    )
    assert ref.line_number_key is None


def test_line_number_key_none_passthrough() -> None:
    """raw_line_number=None → canonicalize 호출 없이 바로 None."""
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number=None,
        company_code=None,
    )
    assert ref.line_number_key is None


def test_line_number_key_pd_na_collapses_to_none() -> None:
    """pd.NA → canonicalize "n:" → None."""
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number=pd.NA,
        company_code=None,
    )
    assert ref.line_number_key is None


# ---------------------------------------------------------------------------
# Phase2CaseBase.with_phase1_refs — 정렬된 tuple 반환
# ---------------------------------------------------------------------------


def _make_minimal_case(case_id: str = "p2_duplicate_pair_aaaaaaaaaa") -> DuplicateCase:
    """공통 fixture — 최소 DuplicateCase."""
    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="duplicate",
        unit_type="pair",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"trigger": "L2-03a"},
        family_score=0.8,
        family_ecdf=0.95,
        pair_id="pair-001",
        sub_rule="L2-03a",
    )


def test_phase2_case_base_with_phase1_refs_returns_sorted() -> None:
    """입력 순서 무관, refs 가 정렬된 tuple 로 부착된 새 case 반환."""
    case = _make_minimal_case()
    updated = case.with_phase1_refs(("case-z", "case-a", "case-m"))
    assert isinstance(updated, Phase2CaseBase)
    assert updated.phase1_case_refs == ("case-a", "case-m", "case-z")
    # 원본 immutability — 새 인스턴스 반환
    assert case.phase1_case_refs == ()


# ---------------------------------------------------------------------------
# Phase2CaseSet — 전 family 순회 + linked 부착
# ---------------------------------------------------------------------------


def _make_unsupervised(case_id: str) -> UnsupervisedCase:
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="unsupervised",
        unit_type="document",
        row_refs=(),
        evidence_tier="ml_quantile",
        case_generation_reason={"trigger": "vae_top"},
        family_score=0.9,
        family_ecdf=0.97,
        anomaly_score=2.5,
        model_id="vae-v1",
        schema_hash="hash-xyz",
    )


def _make_ic(case_id: str) -> IntercompanyCase:
    return IntercompanyCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="intercompany",
        unit_type="pair",
        row_refs=(),
        evidence_tier="strong",
        case_generation_reason={"trigger": "ic_reciprocal"},
        family_score=0.85,
        family_ecdf=0.96,
        ic_role="reciprocal_flow",
        counterparty_pair=("A", "B"),
    )


def _make_relational(case_id: str) -> RelationalCase:
    return RelationalCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="relational",
        unit_type="edge",
        row_refs=(),
        evidence_tier="strong",
        case_generation_reason={"trigger": "R01"},
        family_score=0.75,
        family_ecdf=0.92,
        sub_rule="R01",
        edge_a="N1",
        edge_b="N2",
        metric_name="centrality",
        metric_value=0.42,
    )


def _make_timeseries(case_id: str) -> TimeseriesCase:
    return TimeseriesCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="timeseries",
        unit_type="window",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"trigger": "TS01"},
        family_score=0.7,
        family_ecdf=0.91,
        sub_rule="TS01",
        subject="acct-1001",
        window_start="2026-01-01",
        window_end="2026-01-31",
        daily_count=12,
        expected_count=4.5,
        z_score=3.1,
    )


def test_phase2_case_set_iter_all_cases_sorted() -> None:
    """다섯 family 가 섞여도 phase2_case_id 사전순으로 yield."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_make_minimal_case("p2_d_z"),),
        intercompany_cases=(_make_ic("p2_i_a"),),
        relational_cases=(_make_relational("p2_r_m"),),
        unsupervised_cases=(_make_unsupervised("p2_u_b"),),
        timeseries_cases=(_make_timeseries("p2_t_k"),),
    )
    ids = [case.phase2_case_id for case in case_set.iter_all_cases_sorted()]
    assert ids == sorted(ids)
    assert set(ids) == {"p2_d_z", "p2_i_a", "p2_r_m", "p2_u_b", "p2_t_k"}


def test_phase2_case_set_with_phase1_refs_sets_linked_true() -> None:
    """refs_by_case_id 적용 후 linked=True 인 새 set, 명시되지 않은 case 는 기존 유지."""
    dup_case = _make_minimal_case("p2_d_x")
    ic_case = _make_ic("p2_i_y")
    case_set = Phase2CaseSet(
        duplicate_cases=(dup_case,),
        intercompany_cases=(ic_case,),
    )
    assert case_set.linked is False
    updated_set = case_set.with_phase1_refs({"p2_d_x": ("case-b", "case-a")})
    assert updated_set.linked is True
    # 명시된 case 는 정렬된 refs 부착
    assert updated_set.duplicate_cases[0].phase1_case_refs == ("case-a", "case-b")
    # 명시되지 않은 case 는 기존 () 유지
    assert updated_set.intercompany_cases[0].phase1_case_refs == ()
    # 원본 set 의 linked 는 False 그대로 (immutable)
    assert case_set.linked is False


# np 사용은 placeholder — numpy 의존 명시 (future test 확장 대비)
def test_make_row_ref_with_numpy_int_preserves_canonical() -> None:
    """np.int64 → canonicalize 결과 "i:..." 그대로 — dtype 보존 확인."""
    ref = make_row_ref(
        row_position=0,
        index_label=0,
        document_id=None,
        raw_line_number=np.int64(42),
        company_code=None,
    )
    assert ref.line_number_key == "i:42"


# ---------------------------------------------------------------------------
# Wave 3 Followup 3 — Phase2RowRef.__post_init__ runtime invariant 강제
# ---------------------------------------------------------------------------


def test_phase2_row_ref_post_init_rejects_non_string_index_label() -> None:
    """index_label 이 str 이 아니면 TypeError — int / Timestamp 등 raw 타입 차단."""
    with pytest.raises(TypeError, match="canonical str"):
        Phase2RowRef(
            row_position=0,
            index_label=10,  # type: ignore[arg-type]
            document_id=None,
            line_number_key=None,
            company_code=None,
        )


def test_phase2_row_ref_post_init_rejects_non_canonical_string_index_label() -> None:
    """canonical prefix 가 없는 raw 문자열 ('A', 'DOC001') 은 ValueError."""
    with pytest.raises(ValueError, match="canonical"):
        Phase2RowRef(
            row_position=0,
            index_label="A",
            document_id=None,
            line_number_key=None,
            company_code=None,
        )
    with pytest.raises(ValueError, match="canonical"):
        Phase2RowRef(
            row_position=0,
            index_label="DOC001",
            document_id=None,
            line_number_key=None,
            company_code=None,
        )


def test_phase2_row_ref_post_init_accepts_all_canonical_prefixes() -> None:
    """canonicalize_ref_key 의 모든 prefix (n:/b:/i:/f:/d:/ts:/t:/s:) 통과."""
    for prefix_value in (
        "n:",
        "b:1",
        "i:42",
        "f:3.14",
        "d:1.5",
        "ts:2026-01-01T00:00:00",
        "t:(i:1|s:abc)",
        "s:account-1001",
    ):
        ref = Phase2RowRef(
            row_position=0,
            index_label=prefix_value,
            document_id=None,
            line_number_key=None,
            company_code=None,
        )
        assert ref.index_label == prefix_value


def test_make_row_ref_output_passes_post_init() -> None:
    """make_row_ref 가 생성하는 Phase2RowRef 는 항상 invariant 통과 — 안정성 회귀."""
    # int / str / pd.NA / pd.Timestamp 모두 make_row_ref 통과 후 __post_init__ 정상.
    for raw_label in (10, "raw_doc", pd.NA, "i:already_canonical"):
        ref = make_row_ref(
            row_position=0,
            index_label=raw_label,
            document_id=None,
            raw_line_number=None,
            company_code=None,
        )
        # 예외 안 던짐 + canonical prefix 보장
        assert ref.index_label.startswith(("n:", "b:", "i:", "f:", "d:", "ts:", "t:", "s:"))
