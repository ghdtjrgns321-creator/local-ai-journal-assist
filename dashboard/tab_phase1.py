from __future__ import annotations

import streamlit as st


def render(prep_result, phase1_result) -> None:
    st.subheader("Phase 1 룰 기반 탐지")
    st.caption("핵심 감사 흐름의 첫 단계입니다. 설명 가능한 룰로 이상 거래를 먼저 식별하고 근거를 검토합니다.")

    if phase1_result is None:
        st.info("아직 Phase 1 분석을 실행하지 않았습니다. 이 단계에서 규칙 기반 근거와 감사자 확인 포인트를 먼저 확보합니다.")
        _render_prep_summary(prep_result)
        if st.button("Phase 1 분석 시작", type="primary", key="run_phase1"):
            from dashboard.components.analysis_runner import run_phase_analysis

            with st.spinner("Phase 1 분석 중..."):
                run_phase_analysis(phase="phase1")
            st.rerun()
        return

    st.caption("선택한 전표를 내려가며 룰 근거, 설명 계층, 예외 처리를 함께 확인하세요.")
    from dashboard.tab_findings import render as render_findings

    render_findings(phase1_result)


def _render_prep_summary(prep_result) -> None:
    data = prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    c1, c2, c3 = st.columns(3)
    c1.metric("준비 행 수", f"{len(data):,}")
    c2.metric("준비 컬럼 수", f"{len(data.columns):,}")
    c3.metric("준비 경고", f"{len(prep_result.warnings):,}")
