"""Tab 1: Executive summary with KPI, data quality, charts, and PHASE1 topic summary."""

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
from src.export.phase1_case_view import summarize_phase1_case_result
from src.pipeline import PipelineResult


@st.cache_data(show_spinner=False)
def _cached_kpis(df: pd.DataFrame) -> dict:
    return compute_kpis(df)


def render(result: PipelineResult) -> None:
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)
    kpis = _cached_kpis(df)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("총 전표", f"{kpis['total_docs']:,}")
    c2.metric("총 라인 수", f"{kpis['total_lines']:,}")
    c3.metric("이상 전표", f"{kpis['anomaly_docs']:,}")
    c4.metric("이상 비율", f"{kpis['anomaly_rate']:.1f}%")
    c5.metric("이상 금액", f"{kpis['anomaly_amount']:,.0f}")
    c6.metric("부정 의심", f"{kpis['fraud_suspect']:,}")

    quality = compute_quality(df)
    q1, q2, q3 = st.columns(3)
    q1.metric("데이터 완전성", f"{quality['completeness']:.1f}%")
    q2.metric("처리 시간", f"{result.elapsed:.1f}초")
    if result.warnings:
        with q3.expander(f"경고 {len(result.warnings)}건"):
            for warning in result.warnings:
                st.warning(warning)
    else:
        q3.metric("경고", "없음")

    _render_phase1_case_summary(result)

    st.divider()

    r1_left, r1_right = st.columns([2, 1])
    with r1_left:
        st.plotly_chart(
            rule_violation_bar(df),
            width="stretch",
            key="summary_rule_violation_bar",
        )
    with r1_right:
        st.plotly_chart(
            risk_donut(df),
            width="stretch",
            key="summary_risk_donut",
        )

    r2_left, r2_right = st.columns(2)
    with r2_left:
        st.plotly_chart(
            monthly_trend(df),
            width="stretch",
            key="summary_monthly_trend",
        )
    with r2_right:
        st.plotly_chart(
            risk_heatmap(df),
            width="stretch",
            key="summary_risk_heatmap",
        )

    dim_tabs = st.tabs(["프로세스별", "페르소나별", "법인별"])
    with dim_tabs[0]:
        st.plotly_chart(
            process_distribution_bar(df),
            width="stretch",
            key="summary_process_distribution_bar",
        )
    with dim_tabs[1]:
        st.plotly_chart(
            persona_risk_matrix(df),
            width="stretch",
            key="summary_persona_risk_matrix",
        )
    with dim_tabs[2]:
        st.plotly_chart(
            company_comparison(df),
            width="stretch",
            key="summary_company_comparison",
        )


def _render_phase1_case_summary(result: PipelineResult) -> None:
    summary = summarize_phase1_case_result(result)
    if not summary.get("available"):
        return

    st.divider()
    st.caption("PHASE1 Case Queue 요약")

    theme_rows = summary["themes"]
    high_count = sum(theme["high_count"] for theme in theme_rows)

    c1, c2, c3 = st.columns(3)
    c1.metric("PHASE1 Case", f"{summary['case_count']:,}")
    c2.metric("High Case", f"{high_count:,}")
    c3.metric("Top Topics", ", ".join(summary.get("top_theme_labels", [])) or "-")

    if theme_rows:
        theme_df = pd.DataFrame(theme_rows).rename(
            columns={
                "theme_label": "Topic",
                "case_count": "Cases",
                "high_count": "High",
                "medium_count": "Medium",
                "low_count": "Low",
                "total_amount": "Amount",
            }
        )[["Topic", "Cases", "High", "Medium", "Low", "Amount"]]
        st.dataframe(theme_df, width="stretch", hide_index=True)
