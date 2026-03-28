"""Tab 1: Executive Summary — KPI + 데이터 품질 + 3-Row 차트 레이아웃.

Why: 경영진이 한 화면에서 감사 탐지 결과를 조망할 수 있는 요약 대시보드.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard._kpi import compute_kpis, compute_quality
from dashboard._state import KEY_FILTERS
from dashboard.components.charts import (
    company_comparison,
    monthly_trend,
    persona_risk_matrix,
    process_distribution_bar,
    risk_donut,
    risk_heatmap,
    rule_violation_bar,
)
from dashboard.components.filters import apply_filters
from src.pipeline import PipelineResult


@st.cache_data(show_spinner=False)
def _cached_kpis(df: pd.DataFrame) -> dict:
    """KPI 캐시 래퍼. 필터 결과가 동일하면 재계산 생략.

    Why: 100만 건 nunique() 반복 호출 방지.
         @st.cache_data가 DataFrame 내용을 자체 해싱하여 캐시 키 생성.
    """
    return compute_kpis(df)


def render(result: PipelineResult) -> None:
    """경영진 요약 대시보드 메인 렌더."""
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)
    kpis = _cached_kpis(df)

    # ── KPI 메트릭 카드 ──────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("총 전표수", f"{kpis['total_docs']:,}")
    c2.metric("총 라인아이템", f"{kpis['total_lines']:,}")
    c3.metric("이상 전표수", f"{kpis['anomaly_docs']:,}")
    c4.metric("이상 비율", f"{kpis['anomaly_rate']:.1f}%")
    c5.metric("이상 금액", f"₩{kpis['anomaly_amount']:,.0f}")
    c6.metric("부정 의심", f"{kpis['fraud_suspect']:,}")

    # ── 데이터 품질 (업로드 직후 피드백 우선) ────────────────
    quality = compute_quality(df)
    q1, q2, q3 = st.columns(3)
    q1.metric("데이터 완전성", f"{quality['completeness']:.1f}%")
    q2.metric("처리 시간", f"{result.elapsed:.1f}초")
    if result.warnings:
        with q3.expander(f"경고 {len(result.warnings)}건"):
            for w in result.warnings:
                st.warning(w, icon="⚠️")
    else:
        q3.metric("경고", "없음")

    st.divider()

    # ── Row 1: 룰 위반 건수 + 위험 등급 도넛 ────────────────
    r1_left, r1_right = st.columns([2, 1])
    with r1_left:
        st.plotly_chart(rule_violation_bar(df), use_container_width=True)
    with r1_right:
        st.plotly_chart(risk_donut(df), use_container_width=True)

    # ── Row 2: 월별 추이 + 기간×프로세스 히트맵 ─────────────
    r2_left, r2_right = st.columns(2)
    with r2_left:
        st.plotly_chart(monthly_trend(df), use_container_width=True)
    with r2_right:
        st.plotly_chart(risk_heatmap(df), use_container_width=True)

    # ── Row 3: 차원별 분석 (탭으로 분리 → full-width 확보) ──
    # Why: 1:1:1 columns에 한글 라벨 긴 차트 3개 → 글자 겹침/잘림 방지.
    dim_tabs = st.tabs(["프로세스별", "페르소나별", "법인별"])
    with dim_tabs[0]:
        st.plotly_chart(process_distribution_bar(df), use_container_width=True)
    with dim_tabs[1]:
        st.plotly_chart(persona_risk_matrix(df), use_container_width=True)
    with dim_tabs[2]:
        st.plotly_chart(company_comparison(df), use_container_width=True)
