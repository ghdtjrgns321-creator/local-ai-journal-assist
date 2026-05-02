"""데이터 탐색 탭 — 데이터 품질 + 탐색적 분석(EDA).

감사인 관점: "데이터를 믿을 수 있나?" + "어떤 패턴이 있나?"
품질 검증(결측/분포) + 탐색적 차트(히트맵/산점도/트리맵) 통합.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_EDA_PROFILE, KEY_FILTERS, KEY_UPLOAD_COUNT
from dashboard.components.charts import (
    amount_box_plot,
    anomaly_scatter,
    fraud_type_treemap,
    hourly_heatmap,
    missing_rate_bar,
    quality_gauge,
    risk_heatmap,
)
from dashboard.components.filters import apply_filters
from src.eda import profile_to_dict

if TYPE_CHECKING:
    from src.eda.models import EDAProfile
    from src.pipeline import PipelineResult

# Why: 이 키워드가 포함된 경고는 개발자용 — 감사인에게 노출하지 않음
_DEV_KEYWORDS = ["카디널리티", "TargetEncoder", "Encoder", "인코딩"]


def render(result: PipelineResult) -> None:
    """데이터 탐색 탭 메인 렌더 — 품질 + EDA."""
    # ── 품질 섹션 ──
    profile = _get_or_compute_profile(result)
    if profile is None:
        return

    upload_key = st.session_state.get(KEY_UPLOAD_COUNT, "")
    summary = _cached_summary(
        upload_key,
        profile.total_rows,
        profile.total_columns,
        profile_to_dict(profile),
    )

    _render_metrics(summary)
    _render_missing(summary)
    _render_amount_distribution(summary)

    # ── EDA 차트 섹션 ──
    _render_eda_charts(result)

    _render_advanced(summary)


def _get_or_compute_profile(result: PipelineResult) -> EDAProfile | None:
    """Lazy Loading: 최초 호출 시 프로파일 계산 → session_state 캐시."""
    profile = st.session_state.get(KEY_EDA_PROFILE)
    if profile is not None:
        return profile

    df = result.featured_data if result.featured_data is not None else result.data
    if df is None or df.empty:
        st.info("프로파일링할 데이터가 없습니다.")
        return None

    with st.spinner("데이터 품질 분석 중..."):
        from src.eda import profile_dataframe
        profile = profile_dataframe(df)

    st.session_state[KEY_EDA_PROFILE] = profile
    return profile


@st.cache_data(show_spinner=False)
def _cached_summary(
    _upload_key: str,
    _total_rows: int,
    _total_columns: int,
    profile_data: dict,
) -> dict:
    from src.eda.models import ColumnProfile, EDAProfile
    from src.eda.report import summarize_for_dashboard

    columns = {
        name: ColumnProfile(**column_data)
        for name, column_data in profile_data["columns"].items()
    }
    profile = EDAProfile(
        total_rows=profile_data["total_rows"],
        total_columns=profile_data["total_columns"],
        memory_bytes=profile_data["memory_bytes"],
        duplicate_rows=profile_data["duplicate_rows"],
        sampled=profile_data["sampled"],
        sample_size=profile_data["sample_size"],
        columns=columns,
    )
    return summarize_for_dashboard(profile)


def _render_metrics(summary: dict) -> None:
    """감사인용 핵심 메트릭 4개 + 품질 게이지."""
    ov = summary["overview"]

    # Why: 기간 범위는 datetime 컬럼에서 추출
    date_range = ""
    for cs in summary["column_summaries"]:
        if cs["dtype_group"] == "datetime" and cs.get("highlights"):
            date_range = cs["highlights"]
            break

    avg_missing = 0.0
    missing_data = summary.get("missing_heatmap_data", {})
    if missing_data:
        avg_missing = sum(missing_data.values()) / len(missing_data) * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("데이터 건수", f"{ov['total_rows']:,}")
    c2.metric("기간 범위", date_range or "-")
    c3.metric("평균 결측률", f"{avg_missing:.1f}%")
    c4.metric("중복행", f"{ov['duplicate_rows']:,}")

    col_gauge, col_warnings = st.columns([1, 2])
    with col_gauge:
        st.plotly_chart(
            quality_gauge(summary["quality_score"]),
            use_container_width=True,
            key="data_quality_quality_gauge",
        )
    with col_warnings:
        # Why: 감사인용 경고만 표시
        audit_warnings = [
            w for w in summary.get("warnings", [])
            if not any(kw in w for kw in _DEV_KEYWORDS)
        ]
        if audit_warnings:
            for w in audit_warnings:
                st.warning(w)
        else:
            st.success("데이터 품질 경고 없음")

    st.divider()


def _render_missing(summary: dict) -> None:
    """결측률 바 차트."""
    missing_data = summary.get("missing_heatmap_data", {})
    # Why: 결측률이 0인 컬럼은 숨겨서 차트를 간결하게
    nonzero = {k: v for k, v in missing_data.items() if v > 0}
    if nonzero:
        st.subheader("결측률")
        st.plotly_chart(
            missing_rate_bar(nonzero),
            use_container_width=True,
            key="data_quality_missing_rate_bar",
        )
        st.divider()


def _render_amount_distribution(summary: dict) -> None:
    """금액 컬럼 박스플롯."""
    if summary.get("numeric_stats_table"):
        st.subheader("금액 분포")
        st.plotly_chart(
            amount_box_plot(summary["numeric_stats_table"]),
            use_container_width=True,
            key="data_quality_amount_box_plot",
        )
        st.divider()


def _render_advanced(summary: dict) -> None:
    """개발자/파워유저용 상세 정보 — 접힌 상태."""
    with st.expander("고급: 컬럼 프로파일 상세"):
        # 개발자용 경고
        dev_warnings = [
            w for w in summary.get("warnings", [])
            if any(kw in w for kw in _DEV_KEYWORDS)
        ]
        if dev_warnings:
            for w in dev_warnings:
                st.info(w)

        # 컬럼별 프로파일
        cols_per_row = 3
        col_summaries = summary["column_summaries"]
        for i in range(0, len(col_summaries), cols_per_row):
            batch = col_summaries[i : i + cols_per_row]
            cols = st.columns(cols_per_row)
            for widget, cs in zip(cols, batch):
                with widget:
                    st.markdown(f"**{cs['name']}** (`{cs['dtype_group']}`)")
                    st.caption(f"결측률: {cs['missing_rate']:.1%} | {cs['highlights']}")


def _render_eda_charts(result: PipelineResult) -> None:
    """탐색적 분석 차트 4종 — 위험 히트맵, 산점도, 시간대, 부정유형."""
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)

    st.subheader("탐색적 분석")

    # Row 1: 위험 히트맵 + 시간대 히트맵
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            risk_heatmap(df),
            use_container_width=True,
            key="data_quality_risk_heatmap",
        )
    with col2:
        st.plotly_chart(
            hourly_heatmap(df),
            use_container_width=True,
            key="data_quality_hourly_heatmap",
        )

    # Row 2: 산점도 + 부정유형 트리맵
    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            anomaly_scatter(df),
            use_container_width=True,
            key="data_quality_anomaly_scatter",
        )
    with col4:
        st.plotly_chart(
            fraud_type_treemap(df),
            use_container_width=True,
            key="data_quality_fraud_type_treemap",
        )

    st.divider()
