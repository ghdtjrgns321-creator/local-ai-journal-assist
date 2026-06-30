"""Tab 0: EDA 프로파일 — 데이터 품질·분포·결측 시각화.

Why: 감사인이 분석 전 원시 데이터의 품질과 분포를 확인하는 투명성 대시보드.
     업로드 원본 데이터 기준 — 사이드바 필터와 무관.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_EDA_PROFILE, KEY_UPLOAD_COUNT
from dashboard.components.charts import (
    missing_rate_bar,
    numeric_box_plots,
    outlier_ratio_bar,
    quality_gauge,
)

if TYPE_CHECKING:
    from src.eda.models import EDAProfile
    from src.pipeline import PipelineResult


def render(result: PipelineResult) -> None:
    """EDA 프로파일 탭 메인 렌더."""
    st.caption("업로드 원본 데이터 기준 품질 분석 (필터 미적용)")

    profile = _get_or_compute_profile(result)
    if profile is None:
        return

    # Why: upload_key를 캐시 키에 포함 — 동일 크기 파일 교체 시 stale 방지
    upload_key = st.session_state.get(KEY_UPLOAD_COUNT, "")
    summary = _cached_summary(upload_key, profile.total_rows, profile.total_columns)
    _render_overview(summary)
    _render_column_profiles(summary)
    _render_missing_heatmap(summary)
    _render_outlier_distribution(summary)


def _get_or_compute_profile(result: PipelineResult) -> EDAProfile | None:
    """Lazy Loading: 최초 호출 시 프로파일 계산 → session_state 캐시."""
    profile = st.session_state.get(KEY_EDA_PROFILE)
    if profile is not None:
        return profile

    # Why: featured_data는 피처 생성 완료된 클린 DF. 없으면 result.data 사용.
    df = result.featured_data if result.featured_data is not None else result.data
    if df is None or df.empty:
        st.info("프로파일링할 데이터가 없습니다.")
        return None

    with st.spinner("EDA 프로파일 생성 중..."):
        from src.eda import profile_dataframe
        profile = profile_dataframe(df)

    st.session_state[KEY_EDA_PROFILE] = profile
    return profile


@st.cache_data(show_spinner=False)
def _cached_summary(_upload_key: str, _total_rows: int, _total_columns: int) -> dict:
    """summarize_for_dashboard 캐시 래퍼.

    Why: 캐시 키를 스칼라(upload_key, total_rows, total_columns)로 제한하여
         EDAProfile 해시 문제 방지. upload_key로 파일 교체 시 무효화 보장.
    """
    from src.eda.report import summarize_for_dashboard
    # Why: session_state에서 직접 가져옴 — 캐시 키와 실제 프로파일 동기화 보장
    profile = st.session_state[KEY_EDA_PROFILE]
    return summarize_for_dashboard(profile)


# ── 섹션 렌더러 ──────────────────────────────────────────────────


def _render_overview(summary: dict) -> None:
    """Section 1: 데이터 개요 — 전체 수준 통계 + 품질 게이지."""
    ov = summary["overview"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 행수", f"{ov['total_rows']:,}")
    c2.metric("총 컬럼수", f"{ov['total_columns']:,}")
    c3.metric("메모리", f"{ov['memory_mb']:.1f} MB")
    c4.metric("중복행", f"{ov['duplicate_rows']:,}")
    c5.metric("샘플링", "예" if ov["sampled"] else "아니오")

    col_gauge, col_warnings = st.columns([1, 2])
    with col_gauge:
        st.plotly_chart(quality_gauge(summary["quality_score"]), width="stretch")
    with col_warnings:
        if summary["warnings"]:
            for w in summary["warnings"]:
                st.warning(w)
        else:
            st.success("데이터 품질 경고 없음")

    st.divider()


def _render_column_profiles(summary: dict) -> None:
    """Section 2: 컬럼별 프로파일 카드 (3열 그리드)."""
    st.subheader("컬럼별 프로파일")
    cols_per_row = 3
    col_summaries = summary["column_summaries"]

    for i in range(0, len(col_summaries), cols_per_row):
        batch = col_summaries[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for widget, cs in zip(cols, batch):
            with widget:
                st.markdown(f"**{cs['name']}** (`{cs['dtype_group']}`)")
                st.caption(f"결측률: {cs['missing_rate']:.1%} | {cs['highlights']}")

    st.divider()


def _render_missing_heatmap(summary: dict) -> None:
    """Section 3: 결측률 히트맵 (수평 바 차트)."""
    st.subheader("결측률 히트맵")
    st.plotly_chart(
        missing_rate_bar(summary["missing_heatmap_data"]),
        width="stretch",
    )
    st.divider()


def _render_outlier_distribution(summary: dict) -> None:
    """Section 4: 이상치 분포 + 수치형 박스플롯."""
    st.subheader("이상치 분포")
    total_rows = summary["overview"]["total_rows"]

    if summary["numeric_stats_table"]:
        st.plotly_chart(
            outlier_ratio_bar(summary["numeric_stats_table"], total_rows),
            width="stretch",
        )
        st.plotly_chart(
            numeric_box_plots(summary["numeric_stats_table"]),
            width="stretch",
        )
    else:
        st.info("수치형 컬럼이 없어 이상치 분석을 건너뜁니다.")
