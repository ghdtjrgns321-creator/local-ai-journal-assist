"""Phase1 / Phase2 결과 cross-reference 비교 탭.

대분류 "Phase1, 2 비교" 진입 시 보이는 화면. 소분류 3 sub-tabs:
  1. Phase1 only — rule 만 잡고 PHASE2 가 보강 못 한 case
  2. Phase2 only — PHASE2 family 가 잡고 rule 은 못 본 신호
  3. Phase1+2 결합 — 양 phase 모두 잡아 corroborate 된 case

Why: 감사인이 phase2 까지 돌린 후 두 phase 의 교차 결과를 한 화면에서 보기 위함.
     phase1/phase2 결과 탭은 각 phase 단독 관점이므로 cross-ref 만 따로 묶는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
import streamlit as st

from src.models.phase1_case import CaseGroupResult, Phase1CaseResult
from src.models.phase2_case import Phase2CaseBase, Phase2CaseSet


def render(prep_result: Any, phase1_result: Any, phase2_result: Any) -> None:
    """대분류 "Phase1, 2 비교" 진입점.

    prep_result 는 시그니처 호환을 위해 받지만 본 탭에서는 cross-ref 만 다룬다.
    phase1_result / phase2_result 가 모두 부재면 안내만 표시.
    """
    del prep_result  # 시그니처 호환 — 본 탭은 phase 결과만 사용

    st.markdown("### Phase1 ↔ Phase2 교차 비교")
    st.caption(
        "rule 기반 PHASE1 결과와 family 기반 PHASE2 결과를 cross-reference 로 묶어 "
        "어느 쪽이 단독으로 잡았는지 / 양쪽이 합의했는지를 한 화면에서 본다."
    )

    phase1_case_set = _extract_phase1_case_set(phase1_result)
    phase2_case_set = _extract_phase2_case_set(phase2_result)

    if phase1_case_set is None and phase2_case_set is None:
        st.info("Phase1, Phase2 모두 실행되지 않았습니다. 좌측 탭에서 먼저 분석을 실행하세요.")
        return

    referenced_p1_ids = _collect_referenced_phase1_ids(phase2_case_set)
    phase1_only_cases = _filter_phase1_only(phase1_case_set, referenced_p1_ids)
    phase2_only_cases = _filter_phase2_by_link(phase2_case_set, linked=False)
    both_cases = _filter_phase2_by_link(phase2_case_set, linked=True)

    _render_kpi_row(
        phase1_only_count=len(phase1_only_cases),
        phase2_only_count=len(phase2_only_cases),
        both_count=len(both_cases),
    )

    tab_labels = (
        f"Phase1 only ({len(phase1_only_cases)})",
        f"Phase2 only ({len(phase2_only_cases)})",
        f"Phase1+2 결합 ({len(both_cases)})",
    )
    tab_p1, tab_p2, tab_both = st.tabs(tab_labels)

    with tab_p1:
        _render_phase1_only_section(phase1_only_cases, phase1_present=phase1_case_set is not None)
    with tab_p2:
        _render_phase2_only_section(phase2_only_cases, phase2_present=phase2_case_set is not None)
    with tab_both:
        _render_both_section(
            both_cases,
            phase1_case_set=phase1_case_set,
            phase2_present=phase2_case_set is not None,
        )


# ──────────────────────────────────────────────────────────────────────────
# 데이터 추출 / 분류
# ──────────────────────────────────────────────────────────────────────────


def _extract_phase1_case_set(phase1_result: Any) -> Phase1CaseResult | None:
    """PipelineResult 또는 dict 에서 Phase1CaseResult 추출. 부재 시 None."""
    if phase1_result is None:
        return None
    candidate = getattr(phase1_result, "phase1_case_result", None)
    if candidate is None and isinstance(phase1_result, dict):
        candidate = phase1_result.get("phase1_case_result")
    return candidate if isinstance(candidate, Phase1CaseResult) else None


def _extract_phase2_case_set(phase2_result: Any) -> Phase2CaseSet | None:
    """PipelineResult 에서 Phase2CaseSet 추출. 부재 시 None."""
    if phase2_result is None:
        return None
    candidate = getattr(phase2_result, "phase2_case_set", None)
    if candidate is None and isinstance(phase2_result, dict):
        candidate = phase2_result.get("phase2_case_set")
    return candidate if isinstance(candidate, Phase2CaseSet) else None


def _collect_referenced_phase1_ids(case_set: Phase2CaseSet | None) -> frozenset[str]:
    """Phase2CaseSet 의 모든 case 의 phase1_case_refs 합집합."""
    if case_set is None:
        return frozenset()
    refs: set[str] = set()
    for case in case_set.iter_all_cases_sorted():
        refs.update(case.phase1_case_refs)
    return frozenset(refs)


def _filter_phase1_only(
    case_set: Phase1CaseResult | None,
    referenced_ids: frozenset[str],
) -> tuple[CaseGroupResult, ...]:
    """PHASE1 case 중 PHASE2 어느 case 에도 ref 안 된 case 만 반환."""
    if case_set is None:
        return ()
    return tuple(case for case in case_set.cases if case.case_id not in referenced_ids)


def _filter_phase2_by_link(
    case_set: Phase2CaseSet | None,
    *,
    linked: bool,
) -> tuple[Phase2CaseBase, ...]:
    """Phase2CaseSet 의 case 를 phase1_case_refs 유무 기준 분리."""
    if case_set is None:
        return ()
    return tuple(
        case for case in case_set.iter_all_cases_sorted() if bool(case.phase1_case_refs) == linked
    )


# ──────────────────────────────────────────────────────────────────────────
# KPI / 소분류 렌더
# ──────────────────────────────────────────────────────────────────────────


def _render_kpi_row(*, phase1_only_count: int, phase2_only_count: int, both_count: int) -> None:
    """3 분류 KPI 한 줄. label=분류 / value=count (수치만)."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Phase1 only", phase1_only_count)
    with c2:
        st.metric("Phase2 only", phase2_only_count)
    with c3:
        st.metric("Phase1+2 결합", both_count)


def _render_phase1_only_section(
    cases: tuple[CaseGroupResult, ...],
    *,
    phase1_present: bool,
) -> None:
    """Phase1 only: rule 만 잡고 PHASE2 보강 없는 case 테이블."""
    if not phase1_present:
        st.info("룰 기반 결과가 없습니다. 먼저 '룰 기반' 탭에서 분석을 실행하세요.")
        return
    if not cases:
        st.info(
            "Phase1 단독 case 가 없습니다. 모든 PHASE1 case 가 PHASE2 family 와 cross-reference 되었습니다."
        )
        return
    st.caption("rule 기반 PHASE1 이 잡았지만 PHASE2 family 가 보강하지 못한 case 입니다.")
    df = pd.DataFrame(_phase1_rows(cases))
    st.dataframe(df, width="stretch", hide_index=True)


def _render_phase2_only_section(
    cases: tuple[Phase2CaseBase, ...],
    *,
    phase2_present: bool,
) -> None:
    """Phase2 only: family 단독 신호 테이블."""
    if not phase2_present:
        st.info("비지도(VAE) 결과가 없습니다. 먼저 '비지도(VAE)' 탭에서 추론을 실행하세요.")
        return
    if not cases:
        st.info(
            "Phase2 단독 신호가 없습니다. 모든 PHASE2 case 가 PHASE1 rule 과 cross-reference 되었습니다."
        )
        return
    st.caption("PHASE2 family 가 잡았지만 rule 기반 PHASE1 이 잡지 못한 신호입니다.")
    df = pd.DataFrame(_phase2_rows(cases, with_phase1_refs=False))
    st.dataframe(df, width="stretch", hide_index=True)


def _render_both_section(
    cases: tuple[Phase2CaseBase, ...],
    *,
    phase1_case_set: Phase1CaseResult | None,
    phase2_present: bool,
) -> None:
    """Phase1+2 결합: 양 phase 가 모두 잡은 corroborate case 테이블."""
    if not phase2_present:
        st.info("비지도(VAE) 결과가 없어 결합 case 를 산출할 수 없습니다.")
        return
    if not cases:
        st.info("PHASE1 과 PHASE2 가 동시에 잡은 case 가 없습니다.")
        return
    st.caption(
        "PHASE2 family 와 PHASE1 rule 이 같은 영역을 잡아 corroborate 된 case 입니다. "
        "감사인의 우선 검토 대상."
    )
    p1_band_lookup = _build_phase1_band_lookup(phase1_case_set)
    df = pd.DataFrame(_phase2_rows(cases, with_phase1_refs=True, phase1_band_lookup=p1_band_lookup))
    st.dataframe(df, width="stretch", hide_index=True)


# ──────────────────────────────────────────────────────────────────────────
# 테이블 row 빌더
# ──────────────────────────────────────────────────────────────────────────


def _phase1_rows(cases: Iterable[CaseGroupResult]) -> list[dict[str, Any]]:
    """PHASE1 case 한 행 — case_id / 분류 / 위험도 / row,doc 수 / 금액."""
    return [
        {
            "case_id": case.case_id,
            "분류": case.primary_topic_label or case.primary_topic,
            "위험도": case.priority_band,
            "우선순위 점수": round(case.priority_score, 3),
            "row 수": case.row_count,
            "문서 수": case.document_count,
            "금액": round(case.total_amount, 0),
        }
        for case in cases
    ]


def _phase2_rows(
    cases: Iterable[Phase2CaseBase],
    *,
    with_phase1_refs: bool,
    phase1_band_lookup: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """PHASE2 case 한 행 — phase2_case_id / family / tier / score / row 수.

    with_phase1_refs=True 면 매칭된 PHASE1 case_id 와 priority_band 도 함께 표시.
    """
    lookup = phase1_band_lookup or {}
    rows: list[dict[str, Any]] = []
    for case in cases:
        row: dict[str, Any] = {
            "phase2_case_id": case.phase2_case_id,
            "family": case.family,
            "tier": case.evidence_tier,
            "family_score": round(float(case.family_score), 3),
            "row 수": len(case.row_refs),
        }
        if with_phase1_refs:
            refs = case.phase1_case_refs
            row["PHASE1 case_id"] = ", ".join(refs)
            row["PHASE1 위험도"] = ", ".join(lookup.get(ref, "?") for ref in refs)
        rows.append(row)
    return rows


def _build_phase1_band_lookup(case_set: Phase1CaseResult | None) -> dict[str, str]:
    """case_id → priority_band 매핑. None 이면 빈 dict."""
    if case_set is None:
        return {}
    return {case.case_id: case.priority_band for case in case_set.cases}
