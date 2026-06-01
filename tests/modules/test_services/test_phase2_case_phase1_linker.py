"""S4 — PHASE1 ↔ PHASE2 cross-reference linker 계약 검증.

Why: v7-plan S4 invariant #33~38 — link_phase2_to_phase1 가
PHASE1 priority_score / PHASE2 family_score 를 read-only 로 유지하고
row_position 등가만으로 phase1_case_refs 를 정렬된 tuple 로 부착하는지 확인.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.models.phase1_case import (
    CaseGroupResult,
    Phase1CaseResult,
    RawRuleHitRef,
)
from src.models.phase2_case import (
    DuplicateCase,
    Phase2CaseSet,
    Phase2RowRef,
    UnsupervisedCase,
)
from src.services.phase2_case_phase1_linker import (
    LinkerResult,
    link_phase2_to_phase1,
)

# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------


def _row_ref(pos: int, doc: str = "DOC") -> Phase2RowRef:
    """canonical prefix 를 만족하는 Phase2RowRef helper.

    Why: Phase2RowRef.__post_init__ 가 index_label canonical prefix 를 강제 — 테스트에서
    raw int 을 넣으면 ValueError. canonicalize_ref_key 결과 형식 "i:<n>" 을 직접 구성한다.
    """
    return Phase2RowRef(
        row_position=pos,
        index_label=f"i:{pos}",
        document_id=doc,
        line_number_key=None,
        company_code=None,
    )


def _duplicate_case(
    *,
    case_id: str,
    left_pos: int,
    right_pos: int,
    family_score: float = 0.8,
    family_ecdf: float = 0.5,
    reason: dict | None = None,
) -> DuplicateCase:
    left = _row_ref(left_pos, doc="DOC_L")
    right = _row_ref(right_pos, doc="DOC_R")
    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id="batch_test",
        family="duplicate",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason=reason or {"sub_rule": "L2-03a"},
        family_score=family_score,
        family_ecdf=family_ecdf,
        pair_id="pair_001",
        sub_rule="L2-03a",
        left_ref=left,
        right_ref=right,
        pair_evidence_tier="strong",
    )


def _unsupervised_case(
    *,
    case_id: str,
    positions: tuple[int, ...],
    family_score: float = 0.7,
    family_ecdf: float = 0.4,
) -> UnsupervisedCase:
    refs = tuple(_row_ref(p, doc=f"DOC_U{p}") for p in positions)
    return UnsupervisedCase(
        phase2_case_id=case_id,
        batch_id="batch_test",
        family="unsupervised",
        unit_type="row",
        row_refs=refs,
        evidence_tier="moderate",
        case_generation_reason={"model_id": "vae_v1"},
        family_score=family_score,
        family_ecdf=family_ecdf,
        anomaly_score=0.91,
        top_features=(),
        model_id="vae_v1",
        schema_hash="sha:abc",
    )


def _phase1_case(
    *,
    case_id: str,
    row_positions: tuple[int, ...],
    priority_score: float = 12.5,
) -> CaseGroupResult:
    """row_position list 로 raw_rule_hits 를 생성한 PHASE1 case."""
    hits = [
        RawRuleHitRef(
            rule_id="L1-01",
            severity=3,
            document_id=f"DOC_P{pos}",
            row_index=pos,
            evidence_type="control_failure",
        )
        for pos in row_positions
    ]
    return CaseGroupResult(
        case_id=case_id,
        primary_theme="control_failure",
        case_key=case_id,
        priority_score=priority_score,
        composite_sort_score=priority_score,
        raw_rule_hits=hits,
    )


def _phase1_result(cases: list[CaseGroupResult]) -> Phase1CaseResult:
    return Phase1CaseResult(
        run_id="phase1_linker_test",
        company_id="kr01",
        generated_at=datetime(2026, 5, 27, tzinfo=UTC),
        cases=cases,
    )


def _empty_phase1() -> Phase1CaseResult:
    return _phase1_result(cases=[])


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_empty_case_set_returns_empty_linked() -> None:
    """case_set 자체가 비어 있으면 그대로 반환하고 diagnostics counter 는 0."""
    case_set = Phase2CaseSet()
    phase1 = _phase1_result(cases=[_phase1_case(case_id="p1", row_positions=(0,))])

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert isinstance(result, LinkerResult)
    assert result.case_set is case_set  # short-circuit: 동일 객체 반환
    assert result.diagnostics["linked_count"] == 0
    assert result.diagnostics["phase1_hit_count"] == 0
    assert result.diagnostics["unmatched_phase2_count"] == 0


def test_empty_phase1_returns_case_set_with_no_refs() -> None:
    """PHASE1 cases 가 비어 있으면 모든 PHASE2 case 의 phase1_case_refs 는 빈 tuple."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="d1", left_pos=0, right_pos=1),),
    )
    phase1 = _empty_phase1()

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.linked is True
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert result.diagnostics["linked_count"] == 0
    assert result.diagnostics["unmatched_phase2_count"] == 1


def test_position_match_creates_phase1_case_refs() -> None:
    """row_position 등가 시 phase1_case_refs 에 PHASE1 case_id 가 부착된다."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=5, right_pos=7),),
    )
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(5,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)


def test_no_position_overlap_returns_empty_phase1_refs() -> None:
    """row_position 이 겹치지 않으면 phase1_case_refs 는 빈 tuple 유지."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=100, right_pos=101),),
    )
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(5, 6))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert result.diagnostics["linked_count"] == 0
    assert result.diagnostics["unmatched_phase2_count"] == 1


def test_multiple_phase1_cases_overlap_returns_sorted_refs() -> None:
    """여러 PHASE1 case 가 동일 PHASE2 case 와 매칭되면 phase1_case_refs 는 정렬된 tuple."""
    case_set = Phase2CaseSet(
        unsupervised_cases=(_unsupervised_case(case_id="uns_001", positions=(10, 11, 12)),),
    )
    # 입력 순서를 일부러 역순으로 — 결과는 사전순 정렬되어야 함.
    phase1 = _phase1_result(
        cases=[
            _phase1_case(case_id="p1_zeta", row_positions=(10,)),
            _phase1_case(case_id="p1_alpha", row_positions=(11,)),
            _phase1_case(case_id="p1_mike", row_positions=(12,)),
        ],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    refs = result.case_set.unsupervised_cases[0].phase1_case_refs
    assert refs == ("p1_alpha", "p1_mike", "p1_zeta")


def test_linker_returns_case_set_with_linked_true() -> None:
    """linked 플래그가 True 로 전환된다 (매칭 0건이어도)."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=0, right_pos=1),),
    )
    phase1 = _empty_phase1()
    assert case_set.linked is False

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.linked is True


def test_linker_preserves_phase1_priority_score() -> None:
    """invariant #33 — PHASE1 priority_score / composite_sort_score 변경 0건."""
    phase1_case = _phase1_case(
        case_id="p1_alpha",
        row_positions=(5,),
        priority_score=42.7,
    )
    phase1 = _phase1_result(cases=[phase1_case])
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=5, right_pos=7),),
    )

    before_priority = phase1.cases[0].priority_score
    before_composite = phase1.cases[0].composite_sort_score

    link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert phase1.cases[0].priority_score == before_priority
    assert phase1.cases[0].composite_sort_score == before_composite
    assert phase1.cases[0].priority_score == pytest.approx(42.7)


def test_linker_preserves_phase2_family_score() -> None:
    """invariant #34 — family_score / family_ecdf 변경 0건."""
    case = _duplicate_case(
        case_id="dup_001",
        left_pos=5,
        right_pos=7,
        family_score=0.83,
        family_ecdf=0.61,
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(5,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    linked = result.case_set.duplicate_cases[0]
    assert linked.family_score == pytest.approx(0.83)
    assert linked.family_ecdf == pytest.approx(0.61)


def test_linker_preserves_phase2_case_generation_reason() -> None:
    """invariant #34 — case_generation_reason dict 동일 보존."""
    reason = {"sub_rule": "L2-03a", "threshold": "strong"}
    case = _duplicate_case(
        case_id="dup_001",
        left_pos=5,
        right_pos=7,
        reason=reason,
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(5,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.duplicate_cases[0].case_generation_reason == reason


def test_linker_idempotent_when_case_set_already_linked() -> None:
    """invariant #38 — 이미 linked 된 case_set 재호출 시 동일 refs."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=5, right_pos=7),),
    )
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(5,))],
    )

    first = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")
    second = link_phase2_to_phase1(case_set=first.case_set, phase1=phase1, key_mode="position")

    first_refs = first.case_set.duplicate_cases[0].phase1_case_refs
    second_refs = second.case_set.duplicate_cases[0].phase1_case_refs
    assert first_refs == second_refs == ("p1_alpha",)
    assert second.case_set.linked is True


def test_linker_diagnostics_includes_match_counts() -> None:
    """diagnostics 에 linked_count / phase1_hit_count / unmatched_phase2_count 노출."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case(case_id="dup_001", left_pos=5, right_pos=7),
            _duplicate_case(case_id="dup_002", left_pos=900, right_pos=901),
        ),
        unsupervised_cases=(_unsupervised_case(case_id="uns_001", positions=(5, 7)),),
    )
    phase1 = _phase1_result(
        cases=[
            _phase1_case(case_id="p1_alpha", row_positions=(5,)),
            _phase1_case(case_id="p1_beta", row_positions=(7,)),
        ],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    diag = result.diagnostics
    assert diag["linked_count"] == 2  # dup_001 + uns_001
    assert diag["unmatched_phase2_count"] == 1  # dup_002
    # p1_alpha 5 / p1_beta 7 → needed_positions {5,7,900,901} 와 모두 교집합 → 2 hit
    assert diag["phase1_hit_count"] == 2


def test_phase1_case_refs_sorted_alphabetically_in_tuple() -> None:
    """invariant #36 — phase1_case_refs 는 set 의 sorted() 결과 = 사전순 tuple."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_001", left_pos=1, right_pos=2),),
    )
    # 동일 row_position 에 여러 PHASE1 hit — 순서 섞어서 입력.
    phase1 = _phase1_result(
        cases=[
            _phase1_case(case_id="zzz_last", row_positions=(1,)),
            _phase1_case(case_id="aaa_first", row_positions=(1,)),
            _phase1_case(case_id="mmm_mid", row_positions=(2,)),
        ],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    refs = result.case_set.duplicate_cases[0].phase1_case_refs
    assert list(refs) == sorted(refs)
    assert refs == ("aaa_first", "mmm_mid", "zzz_last")


def test_duplicate_case_left_ref_position_matches_phase1() -> None:
    """invariant #37 — DuplicateCase.left_ref 의 row_position 도 cross-ref 대상."""
    case = _duplicate_case(case_id="dup_001", left_pos=42, right_pos=99)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_left_only", row_positions=(42,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_left_only",)


def test_duplicate_case_right_ref_position_matches_phase1() -> None:
    """invariant #37 — DuplicateCase.right_ref 의 row_position 도 cross-ref 대상."""
    case = _duplicate_case(case_id="dup_001", left_pos=42, right_pos=99)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_right_only", row_positions=(99,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_right_only",)


def test_phase2_cases_without_phase1_overlap_keep_empty_refs() -> None:
    """invariant #35 — position 매칭 0인 case 는 phase1_case_refs=() 유지, linked=True."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_match", left_pos=1, right_pos=2),),
        unsupervised_cases=(_unsupervised_case(case_id="uns_nomatch", positions=(500, 501)),),
    )
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_alpha", row_positions=(1,))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.case_set.linked is True
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)
    assert result.case_set.unsupervised_cases[0].phase1_case_refs == ()


# ---------------------------------------------------------------------------
# Wave 4 Followup — stale phase1_case_refs reset 회귀 가드
# ---------------------------------------------------------------------------


def _phase1_with_cases(
    *,
    cases_data: tuple[tuple[str, tuple[int, ...]], ...],
) -> Phase1CaseResult:
    """phase1 fixture — (case_id, hit_positions) 튜플로 minimal CaseGroupResult 생성."""
    return Phase1CaseResult(
        run_id="run-test",
        company_id="co-test",
        generated_at=datetime.now(UTC),
        cases=[
            CaseGroupResult(
                case_id=case_id,
                case_key=case_id,
                primary_theme="t",
                primary_topic="t",
                raw_rule_hits=[
                    RawRuleHitRef(
                        rule_id="L2-03a",
                        severity=3,
                        document_id="D",
                        row_index=pos,
                        evidence_type="duplicate",
                    )
                    for pos in positions
                ],
            )
            for case_id, positions in cases_data
        ],
    )


def test_linker_resets_stale_refs_when_phase1_becomes_empty() -> None:
    """이전에 link 된 case_set 을 빈 phase1 로 재호출 시 phase1_case_refs 가 () 로 reset.

    Phase2CaseSet.with_phase1_refs 는 dict 에 없는 case 의 기존 refs 를 보존하므로
    linker 가 모든 case 에 명시적으로 refs (매칭 0 면 ()) 를 제공해야 stale 방지.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="p2_dup_1", left_pos=10, right_pos=11),),
    )
    phase1_initial = _phase1_with_cases(cases_data=(("p1_alpha", (10,)),))
    linked_once = link_phase2_to_phase1(
        case_set=case_set, phase1=phase1_initial, key_mode="position"
    )
    assert linked_once.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)

    # 빈 phase1 로 재호출 — refs 가 () 로 reset 되어야 함.
    phase1_empty = _phase1_with_cases(cases_data=())
    linked_again = link_phase2_to_phase1(
        case_set=linked_once.case_set, phase1=phase1_empty, key_mode="position"
    )
    assert linked_again.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert linked_again.case_set.linked is True
    assert linked_again.diagnostics["linked_count"] == 0
    assert linked_again.diagnostics["unmatched_phase2_count"] == 1


def test_linker_resets_stale_refs_when_phase1_positions_change() -> None:
    """phase1 case 의 position 이 바뀌어 매칭이 사라진 case 는 refs 가 () 로 reset."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case(case_id="p2_dup_a", left_pos=10, right_pos=11),
            _duplicate_case(case_id="p2_dup_b", left_pos=20, right_pos=21),
        ),
    )
    # 1차: 두 case 모두 매칭
    phase1_first = _phase1_with_cases(cases_data=(("p1_alpha", (10, 20)),))
    linked_first = link_phase2_to_phase1(
        case_set=case_set, phase1=phase1_first, key_mode="position"
    )
    assert linked_first.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)
    assert linked_first.case_set.duplicate_cases[1].phase1_case_refs == ("p1_alpha",)

    # 2차: position 이 모두 99 로 이동 — 두 case 모두 매칭 0 으로 변경.
    phase1_changed = _phase1_with_cases(cases_data=(("p1_alpha", (99,)),))
    linked_second = link_phase2_to_phase1(
        case_set=linked_first.case_set, phase1=phase1_changed, key_mode="position"
    )
    assert linked_second.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert linked_second.case_set.duplicate_cases[1].phase1_case_refs == ()


def test_linker_preserves_match_for_some_resets_others() -> None:
    """일부 case 는 매칭 유지, 다른 case 는 reset — mixed transition 검증."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case(case_id="p2_dup_a", left_pos=10, right_pos=11),
            _duplicate_case(case_id="p2_dup_b", left_pos=20, right_pos=21),
        ),
    )
    phase1_first = _phase1_with_cases(cases_data=(("p1_alpha", (10, 20)),))
    linked_first = link_phase2_to_phase1(
        case_set=case_set, phase1=phase1_first, key_mode="position"
    )
    # 2차: position 10 만 유지, 20 은 사라짐.
    phase1_partial = _phase1_with_cases(cases_data=(("p1_alpha", (10,)),))
    linked_second = link_phase2_to_phase1(
        case_set=linked_first.case_set, phase1=phase1_partial, key_mode="position"
    )
    assert linked_second.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)
    assert linked_second.case_set.duplicate_cases[1].phase1_case_refs == ()
    assert linked_second.diagnostics["linked_count"] == 1
    assert linked_second.diagnostics["unmatched_phase2_count"] == 1


# ---------------------------------------------------------------------------
# S4.next key_mode 분기 검증 (invariant #39~44)
# ---------------------------------------------------------------------------


def _row_ref_doc(pos: int, doc_id: str | None) -> Phase2RowRef:
    """document_id 를 None 으로 만들 수 있는 helper.

    Why: 기존 ``_row_ref`` 는 default ``"DOC"`` — invariant #42 (auto fallback) 검증
    에는 None 주입이 필요. canonical prefix 규약은 유지한다.
    """
    return Phase2RowRef(
        row_position=pos,
        index_label=f"i:{pos}",
        document_id=doc_id,
        line_number_key=None,
        company_code=None,
    )


def _duplicate_case_with_docs(
    *,
    case_id: str,
    left_pos: int,
    right_pos: int,
    left_doc: str | None,
    right_doc: str | None,
) -> DuplicateCase:
    """left/right 의 document_id 를 명시 지정한 DuplicateCase fixture."""
    left = _row_ref_doc(left_pos, left_doc)
    right = _row_ref_doc(right_pos, right_doc)
    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id="batch_test",
        family="duplicate",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason={"sub_rule": "L2-03a"},
        family_score=0.8,
        family_ecdf=0.5,
        pair_id="pair_001",
        sub_rule="L2-03a",
        left_ref=left,
        right_ref=right,
        pair_evidence_tier="strong",
    )


def _phase1_case_with_docs(
    *,
    case_id: str,
    hits: tuple[tuple[int, str | None], ...],
) -> CaseGroupResult:
    """(row_index, document_id) 쌍으로 PHASE1 case 생성.

    Why: ``document_id`` 는 RawRuleHitRef 에서 str (non-optional). 빈 문자열
    가능성은 도메인에서 발생할 수 있으므로 ``""`` 도 직접 주입할 수 있게 한다.
    """
    raw_hits = [
        RawRuleHitRef(
            rule_id="L1-01",
            severity=3,
            document_id=(doc if doc is not None else ""),
            row_index=row_idx,
            evidence_type="control_failure",
        )
        for row_idx, doc in hits
    ]
    return CaseGroupResult(
        case_id=case_id,
        primary_theme="control_failure",
        case_key=case_id,
        priority_score=10.0,
        composite_sort_score=10.0,
        raw_rule_hits=raw_hits,
    )


def test_doc_id_mode_matches_via_document_id() -> None:
    """key_mode='doc_id' 에서 document_id 등가만으로 phase1_case_refs 부착."""
    case = _duplicate_case_with_docs(
        case_id="dup_doc",
        left_pos=5,
        right_pos=6,
        left_doc="DOC_X",
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # row_index 는 일부러 다르게 — doc_id 가 같으면 매칭되어야 함.
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((999, "DOC_X"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)
    assert result.diagnostics["key_mode_used"] == "doc_id"


def test_doc_id_mode_matches_across_different_positions() -> None:
    """reload 시나리오 — PHASE1 row_index 42, PHASE2 row_position 5, 같은 document_id.

    position 매칭이라면 0건이지만 doc_id 매칭은 1건. invariant #40 검증.
    """
    case = _duplicate_case_with_docs(
        case_id="dup_reload",
        left_pos=5,
        right_pos=7,
        left_doc="DOC_RELOAD",
        right_doc="DOC_OTHER",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # PHASE1 의 row_index 는 PHASE2 position 과 무관 (42)
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_reload", hits=((42, "DOC_RELOAD"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_reload",)
    assert result.diagnostics["linked_count"] == 1


def test_doc_id_mode_excludes_phase2_refs_without_document_id() -> None:
    """PHASE2 ref 의 document_id 가 None 이면 매칭 후보에서 제외."""
    case = _duplicate_case_with_docs(
        case_id="dup_no_doc",
        left_pos=5,
        right_pos=6,
        left_doc=None,
        right_doc=None,
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # PHASE1 측은 정상 document_id 가 있어도 PHASE2 가 None 이므로 매칭 0.
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((5, "DOC_X"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert result.diagnostics["linked_count"] == 0


def test_doc_id_mode_excludes_phase1_hits_without_document_id() -> None:
    """PHASE1 hit 의 document_id 가 빈 문자열이면 매칭 후보에서 제외."""
    case = _duplicate_case_with_docs(
        case_id="dup_doc",
        left_pos=5,
        right_pos=6,
        left_doc="DOC_X",
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((5, ""),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert result.diagnostics["phase1_hit_count"] == 0


def test_doc_id_mode_diagnostics_records_key_mode_used() -> None:
    """diagnostics['key_mode_used'] == 'doc_id' (invariant #41)."""
    case = _duplicate_case_with_docs(
        case_id="dup_diag",
        left_pos=5,
        right_pos=6,
        left_doc="DOC_X",
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((5, "DOC_X"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")

    assert result.diagnostics["key_mode_used"] == "doc_id"


def test_auto_mode_falls_back_to_position_when_some_phase2_refs_lack_document_id() -> None:
    """invariant #42 — 하나라도 document_id 가 None 이면 'position' fallback."""
    # left_doc 만 None — 하나라도 None 이면 fallback.
    case = _duplicate_case_with_docs(
        case_id="dup_partial",
        left_pos=5,
        right_pos=6,
        left_doc=None,
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # position 5 매칭 → fallback 검증.
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((5, "DOC_X"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="auto")

    assert result.diagnostics["key_mode_used"] == "position"
    # position 매칭은 row_index 5 == row_position 5 → matched.
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)


def test_auto_mode_uses_doc_id_when_all_phase2_refs_have_document_id() -> None:
    """모든 ref 가 document_id 가용하면 auto → doc_id 채택."""
    case = _duplicate_case_with_docs(
        case_id="dup_all_doc",
        left_pos=5,
        right_pos=6,
        left_doc="DOC_X",
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # PHASE1 row_index 와 PHASE2 position 이 달라도 doc_id 가 같으면 매칭.
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((999, "DOC_X"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="auto")

    assert result.diagnostics["key_mode_used"] == "doc_id"
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)


def test_auto_mode_diagnostics_records_resolved_key_mode() -> None:
    """auto 분기는 항상 'doc_id' 또는 'position' 으로 해석된 결과를 diagnostics 에 기록."""
    case_doc = _duplicate_case_with_docs(
        case_id="dup_doc",
        left_pos=1,
        right_pos=2,
        left_doc="DOC_A",
        right_doc="DOC_B",
    )
    case_no_doc = _duplicate_case_with_docs(
        case_id="dup_no_doc",
        left_pos=3,
        right_pos=4,
        left_doc=None,
        right_doc=None,
    )
    phase1 = _phase1_result(cases=[])

    # 1) 모두 document_id 가용 → "doc_id"
    res_doc = link_phase2_to_phase1(
        case_set=Phase2CaseSet(duplicate_cases=(case_doc,)),
        phase1=phase1,
        key_mode="auto",
    )
    assert res_doc.diagnostics["key_mode_used"] == "doc_id"
    # 2) 하나라도 None → "position"
    res_pos = link_phase2_to_phase1(
        case_set=Phase2CaseSet(duplicate_cases=(case_no_doc,)),
        phase1=phase1,
        key_mode="auto",
    )
    assert res_pos.diagnostics["key_mode_used"] == "position"


def test_position_mode_explicit_still_works() -> None:
    """key_mode='position' 명시 호출은 S4 MVP 동작과 정확히 동일 (invariant #39).

    document_id 가 가용한 case 라도 position 매칭만 적용.
    """
    case = _duplicate_case_with_docs(
        case_id="dup_pos_explicit",
        left_pos=5,
        right_pos=6,
        left_doc="DOC_X",
        right_doc="DOC_Y",
    )
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # doc_id 는 매칭되지만 position 매칭은 row_index 5 ↔ row_position 5 만 작동.
    phase1 = _phase1_result(
        cases=[_phase1_case_with_docs(case_id="p1_alpha", hits=((5, "OTHER_DOC"),))],
    )

    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")

    assert result.diagnostics["key_mode_used"] == "position"
    # position 등가만으로 매칭 — document_id 차이 무관.
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_alpha",)


def test_invalid_key_mode_raises_value_error() -> None:
    """invariant #44 — 허용 외 key_mode 입력은 silent fallback 없이 ValueError."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_x", left_pos=0, right_pos=1),),
    )
    phase1 = _empty_phase1()

    with pytest.raises(ValueError, match="key_mode must be one of"):
        link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="bogus")


# ---------------------------------------------------------------------------
# match_precision diagnostics — looser doc_id 매칭을 호출자가 즉시 판별
# ---------------------------------------------------------------------------


def test_diagnostics_records_match_precision_row_for_position_mode() -> None:
    """key_mode='position' → match_precision='row' (row-level)."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_p", left_pos=10, right_pos=11),),
    )
    phase1 = _empty_phase1()
    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="position")
    assert result.diagnostics["match_precision"] == "row"


def test_diagnostics_records_match_precision_document_for_doc_id_mode() -> None:
    """key_mode='doc_id' → match_precision='document' — looser 매칭임을 명시."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_d", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    phase1 = _empty_phase1()
    result = link_phase2_to_phase1(case_set=case_set, phase1=phase1, key_mode="doc_id")
    assert result.diagnostics["match_precision"] == "document"


def test_diagnostics_match_precision_follows_auto_resolution() -> None:
    """auto 가 doc_id 로 resolve 되면 match_precision='document', position 이면 'row'."""
    # 모든 ref 가 document_id 가용 → auto → doc_id → document.
    case_set_doc = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_a", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    result_doc = link_phase2_to_phase1(
        case_set=case_set_doc, phase1=_empty_phase1(), key_mode="auto"
    )
    assert result_doc.diagnostics["key_mode_used"] == "doc_id"
    assert result_doc.diagnostics["match_precision"] == "document"

    # 하나라도 document_id 없음 → auto → position → row.
    # _row_ref_doc(pos, None) 은 document_id 를 None 으로 명시 설정한 ref.
    case_set_pos = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_b", left_pos=10, right_pos=11, left_doc=None, right_doc=None
            ),
        ),
    )
    result_pos = link_phase2_to_phase1(
        case_set=case_set_pos, phase1=_empty_phase1(), key_mode="auto"
    )
    assert result_pos.diagnostics["key_mode_used"] == "position"
    assert result_pos.diagnostics["match_precision"] == "row"


# ---------------------------------------------------------------------------
# S4.next.2 — doc_line / company_doc / label key_mode 검증 (invariant #45~49)
# ---------------------------------------------------------------------------


from src.services.phase2_ref_canonical import canonicalize_ref_key  # noqa: E402
from src.services.phase2_ref_pseudonymize import hash_ref_key  # noqa: E402

_TEST_SALT = "engagement-test-salt"


def _row_ref_full(
    pos: int,
    *,
    index_label_raw: Any = None,
    document_id: str | None,
    raw_line_number: Any = None,
    company_code: str | None = None,
) -> Phase2RowRef:
    """make_row_ref 와 동일한 canonicalization 규칙으로 Phase2RowRef 생성.

    Why: doc_line / label mode 테스트는 line_number_key 와 index_label canonical
    형태가 정확히 일치해야 하므로 make_row_ref 의 canonicalize 결과를 그대로 사용한다.
    """
    if index_label_raw is None:
        index_label_raw = pos
    canonical_index_label = canonicalize_ref_key(index_label_raw)
    if raw_line_number is None:
        line_number_key: str | None = None
    else:
        ck = canonicalize_ref_key(raw_line_number)
        line_number_key = None if ck == "n:" else ck
    return Phase2RowRef(
        row_position=pos,
        index_label=canonical_index_label,
        document_id=document_id,
        line_number_key=line_number_key,
        company_code=company_code,
    )


def _duplicate_case_full(
    *,
    case_id: str,
    left: Phase2RowRef,
    right: Phase2RowRef,
) -> DuplicateCase:
    """row_ref 두 개를 받아 DuplicateCase 를 만드는 fixture."""
    return DuplicateCase(
        phase2_case_id=case_id,
        batch_id="batch_test",
        family="duplicate",
        unit_type="pair",
        row_refs=(left, right),
        evidence_tier="strong",
        case_generation_reason={"sub_rule": "L2-03a"},
        family_score=0.8,
        family_ecdf=0.5,
        pair_id="pair_001",
        sub_rule="L2-03a",
        left_ref=left,
        right_ref=right,
        pair_evidence_tier="strong",
    )


def _row_ref_map_entry(
    *,
    position: int,
    index_label: str,
    document_id: str | None,
    company_code: str | None,
    line_number_key: str | None,
    salt: str = _TEST_SALT,
) -> dict[str, Any]:
    """row_ref_map.jsonl 1 줄 형식의 dict 생성 — store 출력과 동일 형태."""
    return {
        "position": position,
        "canonical_label_hash": hash_ref_key(index_label, salt=salt),
        "doc_id_hash": hash_ref_key(document_id, salt=salt) if document_id else None,
        "company_code_hash": (hash_ref_key(company_code, salt=salt) if company_code else None),
        "line_number_key": line_number_key,
    }


def _phase1_case_full(
    *,
    case_id: str,
    hits: tuple[tuple[int, str | None], ...],
) -> CaseGroupResult:
    """(row_index, document_id) 쌍으로 PHASE1 case 생성."""
    raw_hits = [
        RawRuleHitRef(
            rule_id="L1-01",
            severity=3,
            document_id=(doc if doc is not None else ""),
            row_index=row_idx,
            evidence_type="control_failure",
        )
        for row_idx, doc in hits
    ]
    return CaseGroupResult(
        case_id=case_id,
        primary_theme="control_failure",
        case_key=case_id,
        priority_score=10.0,
        composite_sort_score=10.0,
        raw_rule_hits=raw_hits,
    )


# -- validation (#45) --------------------------------------------------------


def test_doc_line_mode_accepts_none_row_ref_map_after_phase2() -> None:
    """invariant #78 (S6.next Phase 2): row_ref_map 은 fallback 용이 되어 None / empty 허용.

    이전 invariant #45 의 ``row_ref_map 필수`` 정책은 정정됨. PHASE1 hit 의 hash
    필드 (S6.next Phase 1) 우선 사용으로 row_ref_map sidecar 의존 제거.
    """
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_x", left=left, right=right),),
    )
    # row_ref_map=None + salt 가용 — ValueError 없이 진행. PHASE1 empty 라 매칭 0.
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,
        salt=_TEST_SALT,
        key_mode="doc_line",
    )
    assert result.diagnostics["key_mode_used"] == "doc_line"


def test_doc_line_mode_requires_salt() -> None:
    """doc_line mode 는 salt 없거나 공백전용이면 ValueError (#45)."""
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_x", left=left, right=right),),
    )
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        )
    ]
    with pytest.raises(ValueError, match="salt"):
        link_phase2_to_phase1(
            case_set=case_set,
            phase1=_empty_phase1(),
            row_ref_map=rrm,
            salt=None,
            key_mode="doc_line",
        )
    with pytest.raises(ValueError, match="salt"):
        link_phase2_to_phase1(
            case_set=case_set,
            phase1=_empty_phase1(),
            row_ref_map=rrm,
            salt="   \t",
            key_mode="doc_line",
        )


def test_company_doc_mode_requires_salt_only_after_phase2() -> None:
    """invariant #78 — company_doc 도 salt 만 필수. row_ref_map None / empty 허용."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_x", left=left, right=right),),
    )
    # row_ref_map=None 도 허용 (이전 ValueError → graceful pass).
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,
        salt=_TEST_SALT,
        key_mode="company_doc",
    )
    assert result.diagnostics["key_mode_used"] == "company_doc"
    # salt 부재 / 공백 전용 은 여전히 ValueError.
    with pytest.raises(ValueError, match="non-empty salt"):
        link_phase2_to_phase1(
            case_set=case_set,
            phase1=_empty_phase1(),
            row_ref_map=[],
            salt="",
            key_mode="company_doc",
        )


def test_label_mode_requires_salt_only_after_phase2() -> None:
    """invariant #78 — label 도 salt 만 필수. row_ref_map None / empty 허용."""
    left = _row_ref_full(5, document_id="DOC_X")
    right = _row_ref_full(6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_x", left=left, right=right),),
    )
    # row_ref_map=None — graceful pass (이전 ValueError → 허용).
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,
        salt=_TEST_SALT,
        key_mode="label",
    )
    assert result.diagnostics["key_mode_used"] == "label"


# -- doc_line mode 매칭 (#46) ------------------------------------------------


def test_doc_line_mode_matches_via_doc_and_normalized_line() -> None:
    """doc_line mode 는 (doc_id_hash, normalized line_number_key) 페어로 매칭."""
    # PHASE2 left: DOC_X line "0001"
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case = _duplicate_case_full(case_id="dup_doc_line", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0002",
        ),
    ]
    # PHASE1 hit: position 5 (linker 측 dispatch 용)
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_dl_alpha", row_positions=(5,))],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="doc_line",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_dl_alpha",)
    assert result.diagnostics["key_mode_used"] == "doc_line"
    assert result.diagnostics["match_precision"] == "row"


def test_doc_line_mode_distinguishes_lines_in_same_document() -> None:
    """같은 document_id 라도 line_number_key 가 다르면 매칭되지 않음 — row-precise (#46)."""
    # PHASE2: DOC_X line "0001" (position 5)
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_Y", raw_line_number=None)
    case = _duplicate_case_full(case_id="dup_distinguish", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # PHASE1 hit 의 row_index 는 999 — 같은 DOC_X 라도 line_number_key 는 "0099"
    # row_ref_map 에 (999, DOC_X, "s:0099") 가 있으므로 같은 doc 다른 line 분기.
    rrm.append(
        _row_ref_map_entry(
            position=999,
            index_label="i:999",
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0099",
        )
    )
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_other_line", row_positions=(999,))],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="doc_line",
    )

    # left 는 (DOC_X, "1"), PHASE1 hit 는 (DOC_X, "99") — 같은 doc 다른 line.
    # row-precise 매칭이므로 phase1_case_refs == ().
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()


# -- company_doc mode 매칭 (#47) --------------------------------------------


def test_company_doc_mode_matches_via_company_and_doc() -> None:
    """company_doc mode 는 (company_code_hash, doc_id_hash) 페어로 매칭."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case = _duplicate_case_full(case_id="dup_cd", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=100,
            index_label="i:100",
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
    ]
    # PHASE1 hit: position 100 — (CO_A, DOC_X) 매칭.
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_cd_alpha", row_positions=(100,))],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="company_doc",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_cd_alpha",)
    assert result.diagnostics["key_mode_used"] == "company_doc"
    assert result.diagnostics["match_precision"] == "document"


def test_company_doc_mode_disambiguates_across_companies() -> None:
    """다른 company_code 의 같은 doc_id 는 매칭되지 않음 — multi-company disambiguation (#47)."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case = _duplicate_case_full(case_id="dup_disambig", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=200,
            index_label="i:200",
            document_id="DOC_X",
            company_code="CO_B",  # 다른 회사
            line_number_key=None,
        ),
    ]
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_diff_company", row_positions=(200,))],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="company_doc",
    )

    # CO_A:DOC_X 와 CO_B:DOC_X 는 다른 페어 → 매칭 0.
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()


# -- label mode 매칭 + row-precision -----------------------------------------


def test_label_mode_matches_via_canonical_label_hash() -> None:
    """label mode 는 canonical_label_hash 직접 비교 — row-precise (#46)."""
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case = _duplicate_case_full(case_id="dup_label", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    phase1 = _phase1_result(
        cases=[_phase1_case(case_id="p1_label_alpha", row_positions=(5,))],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_label_alpha",)


def test_label_mode_returns_row_precision_in_diagnostics() -> None:
    """label mode → match_precision='row' (#46)."""
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case = _duplicate_case_full(case_id="dup_lp", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )

    assert result.diagnostics["key_mode_used"] == "label"
    assert result.diagnostics["match_precision"] == "row"


# -- auto resolution priority (#48) ------------------------------------------


def test_auto_resolves_to_label_when_row_ref_map_and_salt_available() -> None:
    """row_ref_map + salt 둘 다 가용하면 auto → label (#48)."""
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case = _duplicate_case_full(case_id="dup_auto_label", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )

    assert result.diagnostics["key_mode_used"] == "label"
    assert result.diagnostics["match_precision"] == "row"


def test_auto_falls_back_to_doc_id_without_row_ref_map_when_doc_ids_present() -> None:
    """row_ref_map 없지만 ref 들이 모두 document_id 가용하면 auto → doc_id (#48)."""
    left = _row_ref_full(5, document_id="DOC_X")
    right = _row_ref_full(6, document_id="DOC_Y")
    case = _duplicate_case_full(case_id="dup_auto_doc", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,
        salt=None,
        key_mode="auto",
    )

    assert result.diagnostics["key_mode_used"] == "doc_id"


def test_auto_falls_back_to_position_without_row_ref_map_or_doc_ids() -> None:
    """row_ref_map 없고 doc_id 도 일부 None → auto → position (#48)."""
    left = _row_ref_full(5, document_id=None)
    right = _row_ref_full(6, document_id="DOC_Y")
    case = _duplicate_case_full(case_id="dup_auto_pos", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,
        salt=None,
        key_mode="auto",
    )

    assert result.diagnostics["key_mode_used"] == "position"


# -- match_precision matrix --------------------------------------------------


def test_match_precision_row_for_label_doc_line_position() -> None:
    """label / doc_line / position → match_precision='row'."""
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_prec", left=left, right=right),),
    )
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0002",
        ),
    ]
    for mode in ("label", "doc_line", "position"):
        result = link_phase2_to_phase1(
            case_set=case_set,
            phase1=_empty_phase1(),
            row_ref_map=rrm,
            salt=_TEST_SALT,
            key_mode=mode,
        )
        assert result.diagnostics["match_precision"] == "row", f"{mode!r} should be row"


def test_match_precision_document_for_doc_id_company_doc() -> None:
    """doc_id / company_doc → match_precision='document'."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_dprec", left=left, right=right),),
    )
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code="CO_A",
            line_number_key=None,
        ),
    ]
    for mode in ("doc_id", "company_doc"):
        result = link_phase2_to_phase1(
            case_set=case_set,
            phase1=_empty_phase1(),
            row_ref_map=rrm,
            salt=_TEST_SALT,
            key_mode=mode,
        )
        assert result.diagnostics["match_precision"] == "document", f"{mode!r} should be document"


# ---------------------------------------------------------------------------
# Wave 4 Followup 7 — empty row_ref_map validation + auto truthy 분기
# ---------------------------------------------------------------------------


def test_label_mode_accepts_empty_row_ref_map_with_hit_hash_direct() -> None:
    """invariant #78 (S6.next Phase 2): hash mode 는 salt 만 필수.

    row_ref_map=[] 또는 None 도 허용 — PHASE1 hit 가 canonical_label_hash 보유 시
    row_ref_map sidecar 없이 hit hash 직접 사용 매칭 (#79).
    이전 invariant #50 의 empty row_ref_map 거절은 정정됨.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_x", left_pos=0, right_pos=1),),
    )
    # salt 만 있고 row_ref_map=[] — ValueError 안 던짐. PHASE1 empty 이므로 매칭 0.
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=[],
        salt=_TEST_SALT,
        key_mode="label",
    )
    assert result.diagnostics["key_mode_used"] == "label"


def test_doc_line_mode_accepts_empty_row_ref_map_with_hit_hash_direct() -> None:
    """invariant #78 — doc_line 도 row_ref_map 없이 hit hash 직접 사용 가능."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_y", left_pos=0, right_pos=1),),
    )
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=None,  # None 도 허용
        salt=_TEST_SALT,
        key_mode="doc_line",
    )
    assert result.diagnostics["key_mode_used"] == "doc_line"


def test_company_doc_mode_accepts_empty_row_ref_map_with_hit_hash_direct() -> None:
    """invariant #78 — company_doc 도 동일."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_z", left_pos=0, right_pos=1),),
    )
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=[],
        salt=_TEST_SALT,
        key_mode="company_doc",
    )
    assert result.diagnostics["key_mode_used"] == "company_doc"


def test_hash_mode_still_requires_salt() -> None:
    """invariant #78 — row_ref_map 은 optional 이 됐지만 salt 는 여전히 필수."""
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case(case_id="dup_s", left_pos=0, right_pos=1),),
    )
    for mode in ("label", "doc_line", "company_doc"):
        with pytest.raises(ValueError, match="non-empty salt"):
            link_phase2_to_phase1(
                case_set=case_set,
                phase1=_empty_phase1(),
                row_ref_map=None,
                salt=None,
                key_mode=mode,
            )


def test_auto_with_partial_phase1_hash_coverage_falls_back() -> None:
    """invariant #79 — auto 가 PHASE1 hit hash coverage 부족하고 row_ref_map fallback
    도 불가하면 label 회피.

    PHASE1 hit 중 일부가 canonical_label_hash 없고 row_ref_map 에도 없음 → label
    silent unmatched 위험 → doc_id 또는 position 으로 fallback.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_auto",
                left_pos=0,
                right_pos=1,
                left_doc="D_L",
                right_doc="D_R",
            ),
        ),
    )
    # PHASE1 hit 가 hash 부재 + row_ref_map 도 부재 → coverage False → label 회피.
    phase1_partial = _phase1_with_cases(cases_data=(("p1_partial", (99,)),))
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1_partial,
        row_ref_map=[],
        salt=_TEST_SALT,
        key_mode="auto",
    )
    # partial coverage → label 회피, doc_id 또는 position.
    assert result.diagnostics["key_mode_used"] in ("doc_id", "position")


def test_auto_resolves_to_label_with_hit_hash_coverage_no_row_ref_map() -> None:
    """invariant #79 — PHASE1 hit 가 모두 canonical_label_hash 가용하면 row_ref_map
    없이도 auto 가 label 채택.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_full_hash",
                left_pos=0,
                right_pos=1,
                left_doc="D_L",
                right_doc="D_R",
            ),
        ),
    )
    # 모든 PHASE1 hit 가 canonical_label_hash 보유.
    phase1_full_hash = Phase1CaseResult(
        run_id="run-test",
        company_id="co-test",
        generated_at=datetime.now(UTC),
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_full",
                hits=(
                    {"row_index": 0, "canonical_label_hash": "abc123"},
                    {"row_index": 1, "canonical_label_hash": "def456"},
                ),
            )
        ],
    )
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1_full_hash,
        row_ref_map=None,  # row_ref_map 부재해도 label 채택
        salt=_TEST_SALT,
        key_mode="auto",
    )
    assert result.diagnostics["key_mode_used"] == "label"


# ---------------------------------------------------------------------------
# Wave 4 Followup 8 — auto resolution 의 PHASE1 position coverage 검사
# ---------------------------------------------------------------------------


def _rrm_entry_for_position(pos: int, doc: str | None = "D", line: str | None = "i:1") -> dict:
    """테스트용 row_ref_map entry — coverage 검사 단순화 helper."""
    return {
        "position": pos,
        "canonical_label_hash": hash_ref_key(f"i:{pos}", salt=_TEST_SALT),
        "doc_id_hash": hash_ref_key(doc, salt=_TEST_SALT) if doc else None,
        "company_code_hash": None,
        "line_number_key": line,
    }


def test_auto_with_full_phase1_position_coverage_chooses_label() -> None:
    """PHASE1 hit position 모두 row_ref_map 에 있으면 auto → label 선택."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_cov", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    # row_ref_map 에 PHASE1 hit position (10, 11) 모두 포함.
    rrm = [_rrm_entry_for_position(10), _rrm_entry_for_position(11)]
    phase1 = _phase1_with_cases(cases_data=(("p1_full", (10, 11)),))
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )
    assert result.diagnostics["key_mode_used"] == "label"


def test_auto_with_partial_phase1_position_coverage_falls_back() -> None:
    """PHASE1 hit position 중 일부가 row_ref_map 에 없으면 auto → label 회피, fallback."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_partial", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    # row_ref_map 에는 position 10 만 있고, PHASE1 hit 은 10/99 — 99 부재.
    rrm = [_rrm_entry_for_position(10)]
    phase1 = _phase1_with_cases(cases_data=(("p1_partial", (10, 99)),))
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )
    # partial coverage → label 회피, doc_id 또는 position 으로 fallback.
    assert result.diagnostics["key_mode_used"] != "label"
    assert result.diagnostics["key_mode_used"] in ("doc_id", "position")


def test_auto_with_empty_phase1_cases_chooses_label_when_rrm_available() -> None:
    """PHASE1 cases 가 빈 경우 coverage 검사 무의미 → label 자동 채택."""
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_empty_p1", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    rrm = [_rrm_entry_for_position(10)]  # partial 이지만 PHASE1 hit 자체 없음
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=_empty_phase1(),
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )
    assert result.diagnostics["key_mode_used"] == "label"


def test_explicit_label_with_partial_coverage_still_works_but_warns() -> None:
    """명시 ``label`` 호출은 partial coverage 여도 그대로 진행 (호출자 책임).

    auto fallback 은 protection layer 일 뿐, 호출자가 명시적으로 label 을 지정하면
    그 의도를 존중. 단 매칭 결과는 row_ref_map 에 있는 PHASE1 position 만 link.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_explicit", left_pos=10, right_pos=11, left_doc="D_L", right_doc="D_R"
            ),
        ),
    )
    rrm = [_rrm_entry_for_position(10)]  # partial
    phase1 = _phase1_with_cases(cases_data=(("p1_explicit", (10, 99)),))
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )
    # 명시 호출은 fallback 없이 label 그대로.
    assert result.diagnostics["key_mode_used"] == "label"


# ---------------------------------------------------------------------------
# Wave 4 Followup 9 — coverage helper position 정규화 일관성
# ---------------------------------------------------------------------------


def test_auto_coverage_check_accepts_string_position_entries() -> None:
    """row_ref_map entry 의 ``position`` 이 문자열 숫자여도 coverage helper 가 인식.

    Why: explicit label 매칭은 ``_build_position_to_entry`` 의 ``int(entry["position"])``
    정규화로 문자열 ``"10"`` 도 통과한다. 이전 coverage helper 는 ``isinstance(int)``
    만 검사해 문자열 entry 를 누락 → auto 가 불필요하게 fallback. 두 helper 가 동일
    정규화 (`_build_position_to_entry.keys()`) 를 공유하므로 이제 정합.
    """
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_with_docs(
                case_id="dup_str_pos",
                left_pos=10,
                right_pos=11,
                left_doc="D_L",
                right_doc="D_R",
            ),
        ),
    )
    # entry position 이 문자열 ``"10"`` / ``"11"`` — 운영 JSON 출력은 아니지만 외부
    # 호출자가 jsonl 을 다른 경로로 재구성할 때 발생 가능.
    rrm_string_position = [
        {**_rrm_entry_for_position(10), "position": "10"},
        {**_rrm_entry_for_position(11), "position": "11"},
    ]
    phase1 = _phase1_with_cases(cases_data=(("p1_str", (10, 11)),))
    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm_string_position,
        salt=_TEST_SALT,
        key_mode="auto",
    )
    # 문자열 position 도 정규화 통과 → coverage 100% → label 채택.
    assert result.diagnostics["key_mode_used"] == "label"


# ---------------------------------------------------------------------------
# S6.next Phase 2 — hit hash 우선 + row_ref_map fallback (invariant #74~77)
# ---------------------------------------------------------------------------


def _phase1_case_with_hit_hashes(
    *,
    case_id: str,
    hits: tuple[dict, ...],
) -> CaseGroupResult:
    """RawRuleHitRef 의 hash 필드를 직접 명시한 PHASE1 case fixture.

    각 hit dict 는 row_index / document_id 외에 canonical_label_hash /
    doc_id_hash / line_number_key / company_code_hash 를 선택적으로 보유.
    """
    raw_hits = [
        RawRuleHitRef(
            rule_id="L1-01",
            severity=3,
            document_id=hit.get("document_id", ""),
            row_index=hit["row_index"],
            evidence_type="control_failure",
            canonical_label_hash=hit.get("canonical_label_hash", ""),
            doc_id_hash=hit.get("doc_id_hash", ""),
            line_number_key=hit.get("line_number_key"),
            company_code_hash=hit.get("company_code_hash", ""),
        )
        for hit in hits
    ]
    return CaseGroupResult(
        case_id=case_id,
        primary_theme="control_failure",
        case_key=case_id,
        priority_score=10.0,
        composite_sort_score=10.0,
        raw_rule_hits=raw_hits,
    )


# -- label mode: hit hash 우선 (#75) ----------------------------------------


def test_label_mode_uses_hit_canonical_label_hash_when_present() -> None:
    """invariant #75 — hit.canonical_label_hash 가 truthy 면 row_ref_map 조회 없이 직접 매칭."""
    # PHASE2 row_ref 는 label canonical "i:5" → hash_ref_key("i:5", salt=_TEST_SALT)
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_hit_hash", left=left, right=right),),
    )
    # row_ref_map 에는 position 5 의 entry 가 **없음** — 그러나 hit 측 hash 가 있어 매칭.
    rrm = [
        _row_ref_map_entry(
            position=999,
            index_label="i:999",
            document_id="DOC_OTHER",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # hit 의 row_index 는 999 (row_ref_map 에 존재) 이지만, hit 의 canonical_label_hash
    # 는 PHASE2 left ref 의 label hash 와 동일 (salt + canonical "i:5"). row_ref_map
    # 의 position 999 entry 와 무관하게 hit hash 가 매칭 source.
    expected_left_hash = hash_ref_key(left.index_label, salt=_TEST_SALT)
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_hit_hash",
                hits=(
                    {
                        "row_index": 999,
                        "document_id": "DOC_OTHER",
                        "canonical_label_hash": expected_left_hash,
                    },
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_hit_hash",)


def test_label_mode_falls_back_to_row_ref_map_when_hit_hash_empty() -> None:
    """invariant #75 backward compat — hit.canonical_label_hash 빈 값 → row_ref_map fallback."""
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_fallback", left=left, right=right),),
    )
    # row_ref_map 의 position 5 entry — hash 가 PHASE2 left ref 와 동일하게 산출됨.
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # hit 측 hash 는 빈 문자열 (구 schema 산출물 시뮬레이션) → row_ref_map fallback.
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_legacy",
                hits=({"row_index": 5, "document_id": "DOC_X"},),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_legacy",)


# -- doc_line mode: hit hash 우선 (#75) -------------------------------------


def test_doc_line_mode_uses_hit_doc_and_line_hash_when_present() -> None:
    """invariant #75 — hit.doc_id_hash + hit.line_number_key 가 있으면 직접 매칭."""
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case = _duplicate_case_full(case_id="dup_dl_hit", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    # row_ref_map 에는 PHASE1 hit position 부재. hit 의 hash 만으로 매칭.
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0002",
        ),
    ]
    hit_doc_hash = hash_ref_key("DOC_X", salt=_TEST_SALT)
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_dl_hit",
                hits=(
                    {
                        "row_index": 9999,  # row_ref_map 부재 — fallback 차단
                        "document_id": "DOC_X",
                        "doc_id_hash": hit_doc_hash,
                        "line_number_key": "s:0001",
                    },
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="doc_line",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_dl_hit",)


def test_doc_line_mode_falls_back_to_row_ref_map_when_hit_hash_empty() -> None:
    """invariant #75 backward compat — hit 의 hash 가 빈 값이면 row_ref_map fallback."""
    left = _row_ref_full(5, document_id="DOC_X", raw_line_number="0001")
    right = _row_ref_full(6, document_id="DOC_X", raw_line_number="0002")
    case = _duplicate_case_full(case_id="dup_dl_legacy", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0001",
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key="s:0002",
        ),
    ]
    # hit 측 doc_id_hash / line_number_key 빈 값 — row_ref_map fallback 으로 매칭.
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_dl_legacy",
                hits=({"row_index": 5, "document_id": "DOC_X"},),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="doc_line",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_dl_legacy",)


# -- company_doc mode: hit hash 우선 (#75) ----------------------------------


def test_company_doc_mode_uses_hit_hashes_when_present() -> None:
    """invariant #75 — hit.company_code_hash + hit.doc_id_hash 직접 매칭."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case = _duplicate_case_full(case_id="dup_cd_hit", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code="CO_A",
            line_number_key=None,
        ),
    ]
    # row_ref_map 에 PHASE1 hit position 부재. hit 의 hash 만으로 매칭.
    hit_company_hash = hash_ref_key("CO_A", salt=_TEST_SALT)
    hit_doc_hash = hash_ref_key("DOC_X", salt=_TEST_SALT)
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_cd_hit",
                hits=(
                    {
                        "row_index": 9999,
                        "document_id": "DOC_X",
                        "doc_id_hash": hit_doc_hash,
                        "company_code_hash": hit_company_hash,
                    },
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="company_doc",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_cd_hit",)


def test_company_doc_mode_falls_back_to_row_ref_map_when_hit_hash_empty() -> None:
    """invariant #75 backward compat — company_doc 도 fallback 동작 확인."""
    left = _row_ref_full(5, document_id="DOC_X", company_code="CO_A")
    right = _row_ref_full(6, document_id="DOC_Y", company_code="CO_A")
    case = _duplicate_case_full(case_id="dup_cd_legacy", left=left, right=right)
    case_set = Phase2CaseSet(duplicate_cases=(case,))
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code="CO_A",
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code="CO_A",
            line_number_key=None,
        ),
    ]
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_cd_legacy",
                hits=({"row_index": 5, "document_id": "DOC_X"},),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="company_doc",
    )

    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_cd_legacy",)


# -- coverage helper hash field 우선 (#76) ----------------------------------


def test_auto_coverage_passes_when_all_hits_have_canonical_label_hash() -> None:
    """invariant #76 — hit 가 모두 canonical_label_hash 가용 시 row_ref_map 부재해도 coverage 통과.

    auto 분기에서 label 채택 — row_ref_map 의 position entry 가 PHASE1 hit position
    을 커버하지 않더라도, hit 측 hash 만으로 coverage OK.
    """
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_cov_hit", left=left, right=right),),
    )
    # row_ref_map 에는 PHASE2 ref position 만 있음. PHASE1 hit position 9999 부재.
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # hit 측 canonical_label_hash 가 있어 coverage 검사 통과 → label 채택.
    expected_left_hash = hash_ref_key(left.index_label, salt=_TEST_SALT)
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_cov_hit",
                hits=(
                    {
                        "row_index": 9999,
                        "document_id": "DOC_X",
                        "canonical_label_hash": expected_left_hash,
                    },
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )

    # invariant #76 — hit hash 가 가용하므로 label 채택, 매칭 성공.
    assert result.diagnostics["key_mode_used"] == "label"
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_cov_hit",)


def test_auto_coverage_mixed_hits_uses_row_ref_map_fallback_for_legacy_hits() -> None:
    """일부 hit 은 hash 가용, 일부는 빈 값 — coverage 가 mixed 모드 정상 처리.

    invariant #76 — hash 있는 hit 은 통과, 없는 hit 은 row_ref_map 에서 보완 가능
    해야 coverage OK. 둘 다 충족하면 label 채택.
    """
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_mixed", left=left, right=right),),
    )
    # row_ref_map 은 position 5 / 6 만 보유.
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # hit A: row_index 9999 + hash 보유 → hit hash 로 통과
    # hit B: row_index 5 + hash 없음 → row_ref_map[5] 로 보완 가능
    hit_a_hash = hash_ref_key(left.index_label, salt=_TEST_SALT)
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_mixed",
                hits=(
                    {
                        "row_index": 9999,
                        "document_id": "DOC_X",
                        "canonical_label_hash": hit_a_hash,
                    },
                    {"row_index": 5, "document_id": "DOC_X"},
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )

    # 둘 다 coverage 통과 → label 채택.
    assert result.diagnostics["key_mode_used"] == "label"
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ("p1_mixed",)


def test_auto_coverage_fails_when_hit_lacks_hash_and_row_ref_map() -> None:
    """hit 측 hash 도 없고 row_ref_map 에도 position 부재 → coverage FAIL → label 회피."""
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(_duplicate_case_full(case_id="dup_no_cov", left=left, right=right),),
    )
    # row_ref_map 의 position 은 (5, 6) 만 — PHASE1 hit 9999 미수용.
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_no_cov",
                hits=({"row_index": 9999, "document_id": "DOC_X"},),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="auto",
    )

    # hit hash 도 빈 값 + row_ref_map 에도 9999 부재 → label 회피, fallback.
    assert result.diagnostics["key_mode_used"] != "label"


# -- salt 정합 책임 (#77) ----------------------------------------------------


def test_label_mode_different_salt_yields_zero_match() -> None:
    """invariant #77 — hit hash 와 PHASE2 ref 가 다른 salt 산출이면 매칭 0 (silent).

    호출자가 두 source 의 salt 정합을 보장해야 함. 본 테스트는 의도적으로 mismatched
    salt 를 주입해 silent zero-match 동작을 확인한다.
    """
    left = _row_ref_full(5, index_label_raw=5, document_id="DOC_X")
    right = _row_ref_full(6, index_label_raw=6, document_id="DOC_Y")
    case_set = Phase2CaseSet(
        duplicate_cases=(
            _duplicate_case_full(case_id="dup_salt_mismatch", left=left, right=right),
        ),
    )
    rrm = [
        _row_ref_map_entry(
            position=5,
            index_label=left.index_label,
            document_id="DOC_X",
            company_code=None,
            line_number_key=None,
        ),
        _row_ref_map_entry(
            position=6,
            index_label=right.index_label,
            document_id="DOC_Y",
            company_code=None,
            line_number_key=None,
        ),
    ]
    # hit 의 hash 는 **다른 salt** 로 산출 — PHASE2 측 _TEST_SALT 와 비교 시 다름.
    wrong_salt_hash = hash_ref_key(left.index_label, salt="DIFFERENT_SALT")
    phase1 = _phase1_result(
        cases=[
            _phase1_case_with_hit_hashes(
                case_id="p1_wrong_salt",
                hits=(
                    {
                        "row_index": 9999,
                        "document_id": "DOC_X",
                        "canonical_label_hash": wrong_salt_hash,
                    },
                ),
            ),
        ],
    )

    result = link_phase2_to_phase1(
        case_set=case_set,
        phase1=phase1,
        row_ref_map=rrm,
        salt=_TEST_SALT,
        key_mode="label",
    )

    # silent zero-match — ValueError 던지지 않음, 단순히 매칭 0.
    assert result.case_set.duplicate_cases[0].phase1_case_refs == ()
    assert result.diagnostics["linked_count"] == 0
