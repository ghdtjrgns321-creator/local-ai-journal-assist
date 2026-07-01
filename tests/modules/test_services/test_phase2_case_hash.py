"""compute_raw_case_hash / compute_linked_case_hash 분리 검증.

v7-plan invariant: raw 는 phase1_case_refs 키 자체 부재, linked 는 정렬된
list 로 포함. 두 함수는 sub-routine 관계 없이 완전 분리되어야 한다.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from src.models.phase2_case import (
    Phase2CaseSet,
    Phase2RowRef,
    TimeseriesCase,
)
from src.services.phase2_case_hash import (
    _RAW_HASH_EXCLUDED_FIELDS,
    _case_to_canonical_dict,
    compute_linked_case_hash,
    compute_raw_case_hash,
)
from src.services.phase2_ref_canonical import canonicalize_ref_key


def _make_case(
    case_id: str = "p2_duplicate_pair_0000000001",
    phase1_refs: tuple[str, ...] = (),
) -> TimeseriesCase:
    """최소 TimeseriesCase fixture (case-hash 인프라 검증용 generic case)."""
    return TimeseriesCase(
        phase2_case_id=case_id,
        batch_id="batch-001",
        family="timeseries",
        unit_type="pair",
        row_refs=(),
        evidence_tier="moderate",
        case_generation_reason={"trigger": "L2-03a"},
        family_score=0.8,
        family_ecdf=0.95,
        phase1_case_refs=phase1_refs,
        sub_rule="L2-03a",
    )


# ---------------------------------------------------------------------------
# raw_hash — phase1_case_refs 명시 제외
# ---------------------------------------------------------------------------


def test_raw_hash_excludes_phase1_case_refs_default() -> None:
    """phase1_case_refs=() default 인 case 만 있어도 raw payload 에 키 자체 부재."""
    case = _make_case()
    payload_dict = _case_to_canonical_dict(case, exclude=_RAW_HASH_EXCLUDED_FIELDS)
    assert "phase1_case_refs" not in payload_dict


def test_raw_hash_invariant_under_with_phase1_refs() -> None:
    """with_phase1_refs 적용 전후 raw hash 동일 — phase1_case_refs 가 raw 에 영향 없음."""
    case = _make_case()
    case_set_before = Phase2CaseSet(timeseries_cases=(case,))
    case_with_refs = case.with_phase1_refs(("case-a", "case-b"))
    case_set_after = Phase2CaseSet(timeseries_cases=(case_with_refs,))

    raw_before = compute_raw_case_hash(case_set_before)
    raw_after = compute_raw_case_hash(case_set_after)
    assert raw_before == raw_after


def test_raw_hash_deterministic_repeat() -> None:
    """동일 case_set 반복 호출 시 동일 hash — 결정적 직렬화."""
    case_set = Phase2CaseSet(timeseries_cases=(_make_case(),))
    assert compute_raw_case_hash(case_set) == compute_raw_case_hash(case_set)


# ---------------------------------------------------------------------------
# linked_hash — phase1_case_refs 정렬된 list 포함
# ---------------------------------------------------------------------------


def test_linked_hash_payload_contains_sorted_phase1_case_refs() -> None:
    """같은 set, 다른 입력 순서 → 동일 linked hash — 정렬 효과 검증."""
    case_unsorted = _make_case(phase1_refs=("case-z", "case-a", "case-m"))
    case_sorted = _make_case(phase1_refs=("case-a", "case-m", "case-z"))
    set_unsorted = Phase2CaseSet(timeseries_cases=(case_unsorted,))
    set_sorted = Phase2CaseSet(timeseries_cases=(case_sorted,))
    assert compute_linked_case_hash(set_unsorted) == compute_linked_case_hash(set_sorted)


def test_linked_hash_changes_when_phase1_refs_set_changes() -> None:
    """phase1_case_refs set 변경 → linked hash 변경."""
    case_a = _make_case(phase1_refs=("case-a",))
    case_ab = _make_case(phase1_refs=("case-a", "case-b"))
    hash_a = compute_linked_case_hash(Phase2CaseSet(timeseries_cases=(case_a,)))
    hash_ab = compute_linked_case_hash(Phase2CaseSet(timeseries_cases=(case_ab,)))
    assert hash_a != hash_ab


def test_linked_hash_invariant_under_input_order() -> None:
    """phase1_case_refs 입력 순서만 다른 두 case 는 동일 linked hash (정렬 적용)."""
    case_1 = _make_case(phase1_refs=("c2", "c1"))
    case_2 = _make_case(phase1_refs=("c1", "c2"))
    h1 = compute_linked_case_hash(Phase2CaseSet(timeseries_cases=(case_1,)))
    h2 = compute_linked_case_hash(Phase2CaseSet(timeseries_cases=(case_2,)))
    assert h1 == h2


# ---------------------------------------------------------------------------
# raw 와 linked 함수 분리 — sub-routine 호출 금지 invariant
# ---------------------------------------------------------------------------


def test_raw_hash_function_separate_from_linked() -> None:
    """compute_raw_case_hash 가 compute_linked_case_hash 를 호출하지 않는지 검증.

    소스 inspection — raw 함수 본문에 linked 함수 식별자 부재.
    """
    raw_source = inspect.getsource(compute_raw_case_hash)
    linked_source = inspect.getsource(compute_linked_case_hash)
    assert "compute_linked_case_hash" not in raw_source
    assert "compute_raw_case_hash" not in linked_source


def test_raw_and_linked_hash_differ_when_refs_present() -> None:
    """phase1_case_refs 가 있는 case 는 raw 와 linked hash 가 달라야 한다 — payload 차이."""
    case = _make_case(phase1_refs=("case-a",))
    case_set = Phase2CaseSet(timeseries_cases=(case,))
    raw_h = compute_raw_case_hash(case_set)
    linked_h = compute_linked_case_hash(case_set)
    assert raw_h != linked_h


def test_module_excluded_fields_includes_phase1_case_refs() -> None:
    """_RAW_HASH_EXCLUDED_FIELDS frozenset 가 phase1_case_refs 를 포함 — 모듈 상단 상수 검증."""
    assert "phase1_case_refs" in _RAW_HASH_EXCLUDED_FIELDS
    assert isinstance(_RAW_HASH_EXCLUDED_FIELDS, frozenset)


def test_compute_raw_case_hash_returns_hex_sha256() -> None:
    """raw hash 출력은 sha256 hex (64 자, 소문자)."""
    case_set = Phase2CaseSet(timeseries_cases=(_make_case(),))
    result = compute_raw_case_hash(case_set)
    assert len(result) == 64
    assert result == result.lower()
    # 16진수 문자만 — int 변환 가능해야 함
    int(result, 16)


# ---------------------------------------------------------------------------
# Phase2RowRef.index_label canonicalization — Any 타입의 환경 의존성 차단
# ---------------------------------------------------------------------------


def _make_case_with_label(index_label: object) -> TimeseriesCase:
    """index_label 만 바꾼 minimal TimeseriesCase fixture (row_refs 1개).

    Phase2RowRef.index_label invariant 에 따라 canonical 문자열로 변환 후 주입.
    raw 타입 → canonical 매핑 안정성이 hash 결정성의 출발점.
    """
    ref = Phase2RowRef(
        row_position=0,
        index_label=canonicalize_ref_key(index_label),
        document_id="D1",
        line_number_key="i:1",
        company_code="C1",
    )
    return TimeseriesCase(
        phase2_case_id="p2_duplicate_pair_0000000001",
        batch_id="batch-001",
        family="timeseries",
        unit_type="pair",
        row_refs=(ref,),
        evidence_tier="moderate",
        case_generation_reason={"trigger": "L2-03a"},
        family_score=0.8,
        family_ecdf=0.95,
        sub_rule="L2-03a",
    )


def test_canonical_dict_replaces_pd_timestamp_index_label_with_canonical_string() -> None:
    """index_label 이 pd.Timestamp 일 때 payload 의 row_refs[0]['index_label'] 이 canonical 결과."""
    ts = pd.Timestamp("2026-01-01 12:00:00")
    case = _make_case_with_label(ts)
    payload = _case_to_canonical_dict(case)
    assert payload["row_refs"][0]["index_label"] == canonicalize_ref_key(ts)


def test_raw_hash_stable_under_pd_timestamp_index_label_instance_difference() -> None:
    """동일 시점의 다른 Timestamp 인스턴스 → 동일 raw hash (canonical 통과)."""
    case_a = _make_case_with_label(pd.Timestamp("2026-01-01 12:00:00"))
    case_b = _make_case_with_label(pd.Timestamp("2026-01-01 12:00:00"))
    set_a = Phase2CaseSet(timeseries_cases=(case_a,))
    set_b = Phase2CaseSet(timeseries_cases=(case_b,))
    assert compute_raw_case_hash(set_a) == compute_raw_case_hash(set_b)


def test_raw_hash_stable_under_np_int64_index_label() -> None:
    """np.int64 → canonical i:{int} 통과로 default=str 환경 의존성 차단."""
    case_np = _make_case_with_label(np.int64(42))
    case_py = _make_case_with_label(42)
    set_np = Phase2CaseSet(timeseries_cases=(case_np,))
    set_py = Phase2CaseSet(timeseries_cases=(case_py,))
    assert compute_raw_case_hash(set_np) == compute_raw_case_hash(set_py)


def test_raw_hash_stable_under_tuple_index_label() -> None:
    """tuple index_label (예: MultiIndex 라벨) → canonical t:(...) 결정성."""
    case_a = _make_case_with_label((1, "abc"))
    case_b = _make_case_with_label((1, "abc"))
    set_a = Phase2CaseSet(timeseries_cases=(case_a,))
    set_b = Phase2CaseSet(timeseries_cases=(case_b,))
    assert compute_raw_case_hash(set_a) == compute_raw_case_hash(set_b)


def test_raw_hash_differs_for_distinct_index_labels() -> None:
    """canonical 결과가 다르면 hash 도 달라야 한다 — 식별성 보장."""
    case_a = _make_case_with_label(pd.Timestamp("2026-01-01"))
    case_b = _make_case_with_label(pd.Timestamp("2026-01-02"))
    set_a = Phase2CaseSet(timeseries_cases=(case_a,))
    set_b = Phase2CaseSet(timeseries_cases=(case_b,))
    assert compute_raw_case_hash(set_a) != compute_raw_case_hash(set_b)


def test_linked_hash_also_canonicalizes_index_labels() -> None:
    """linked 경로도 동일하게 index_label canonicalize 통과."""
    case_a = _make_case_with_label(np.int64(7))
    case_b = _make_case_with_label(7)
    set_a = Phase2CaseSet(timeseries_cases=(case_a,))
    set_b = Phase2CaseSet(timeseries_cases=(case_b,))
    assert compute_linked_case_hash(set_a) == compute_linked_case_hash(set_b)
