"""개요 탭 — 감사 탐지 결과 핵심 요약.

감사인 관점의 정보 흐름: "위험이 얼마나 있나?" → KPI/도넛/바/추이.
커스텀 KPI 카드 4개 + 차트 3종으로 구성.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._kpi import compute_kpis
from dashboard._state import KEY_FILTERS
from dashboard.components.charts import (
    benford_overlay,
    monthly_trend,
    risk_donut,
    rule_violation_bar,
)
from dashboard.components.filters import apply_filters

if TYPE_CHECKING:
    from src.pipeline import PipelineResult


@st.cache_data(show_spinner=False)
def _cached_kpis(df: pd.DataFrame) -> dict:
    return compute_kpis(df)


# ── 커스텀 KPI 카드 HTML ──────────────────────────────────────

def _kpi_card(
    label: str,
    subtitle: str,
    value: str,
    unit: str,
    badge_text: str,
) -> str:
    """KPI 카드 HTML. subtitle로 설명 표시, 배지는 연한 노란색."""
    return f"""
    <div style="padding:1rem 1.25rem; border:1px solid #E2E5E9; border-radius:8px;
                background:#FFFFFF; height:100%;">
        <div style="color:#6B7280; font-size:0.8rem; font-weight:500; margin-bottom:0.15rem;">
            {label}
        </div>
        <div style="color:#9CA3AF; font-size:0.68rem; margin-bottom:0.5rem;">
            {subtitle}
        </div>
        <div style="color:#111827; font-size:1.85rem; font-weight:700;
                    letter-spacing:-0.02em; margin-bottom:0.35rem;">
            {value}<span style="font-size:0.9rem; font-weight:500; margin-left:2px;">{unit}</span>
        </div>
        <div style="color:#92400E; font-size:0.8rem; font-weight:500;
                    background:#FEF9C3; display:inline-block;
                    padding:0.15rem 0.5rem; border-radius:4px;">
            {badge_text}
        </div>
    </div>
    """


def render(result: PipelineResult) -> None:
    """개요 탭 메인 렌더."""
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)
    kpis = _cached_kpis(df)

    anomaly_pct = kpis["anomaly_rate"]
    high_ratio = kpis["high_risk_docs"] / max(kpis["anomaly_docs"], 1) * 100
    fraud_pct = kpis["fraud_suspect"] / max(kpis["total_docs"], 1) * 100

    # ── KPI 4개 (st.metric + help 아이콘) ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            label="이상 의심 전표",
            value=f"{kpis['anomaly_docs']:,}건",
            help="감사 룰에서 비정상 패턴이 1건 이상 감지된 전표의 총 수",
        )
        st.caption(f"전체의 {anomaly_pct}%")
    with c2:
        st.metric(
            label="이상 의심 금액",
            value=kpis["anomaly_amount_fmt"],
            help="High·Medium 등급 전표에 포함된 차변 금액 합계",
        )
        st.caption(f"총 {kpis['total_amount_fmt']}의 {kpis['amount_ratio']}%")
    with c3:
        st.metric(
            label="고위험(High) 전표",
            value=f"{kpis['high_risk_docs']:,}건",
            help="위험 점수 최상위 전표. 감사 시 최우선 검토 대상",
        )
        st.caption(f"이상 전표의 {high_ratio:.1f}%")
    with c4:
        st.metric(
            label="부정 의심 (Layer B)",
            value=f"{kpis['fraud_suspect']:,}건",
            help="중복 지급, 자기 승인 등 횡령/배임 시나리오에 해당하는 전표 수",
        )
        st.caption(f"전체의 {fraud_pct:.1f}%")

    st.divider()

    # ── Row 1: 도넛 + 룰 위반 바 ──
    col_donut, col_bar = st.columns([1, 2])
    with col_donut:
        st.plotly_chart(risk_donut(df), use_container_width=True)
    with col_bar:
        st.plotly_chart(rule_violation_bar(df), use_container_width=True)

    # ── Row 2: 월별 특이점 요약 + 추이 ──
    _render_monthly_highlights(df)
    st.plotly_chart(monthly_trend(df), use_container_width=True)

    # ── Row 3: Benford 요약 ──
    _render_benford_summary(df)


def _render_monthly_highlights(df: pd.DataFrame) -> None:
    """월별 데이터에서 감사인이 주목할 특이점을 자동 추출."""
    if "fiscal_period" not in df.columns or "risk_level" not in df.columns:
        return

    # Why: 월별 전표 건수 + 이상 건수를 집계하여 평균 대비 급증 구간 탐지.
    monthly = df.groupby("fiscal_period").agg(
        total=("document_id", "count"),
        anomaly=("risk_level", lambda x: (x != "Normal").sum()),
    )
    if monthly.empty or len(monthly) < 3:
        return

    avg_total = monthly["total"].mean()
    avg_anomaly = monthly["anomaly"].mean()

    findings = []

    # 전표 건수 급증 (평균 대비 1.5배 이상)
    spike_months = monthly[monthly["total"] > avg_total * 1.5]
    for period, row in spike_months.iterrows():
        ratio = row["total"] / avg_total
        findings.append(f"**{int(period)}월** 전표 건수 급증 (평균 대비 {ratio:.1f}배)")

    # 이상 비율 급증 (해당 월 이상 비율이 전체 평균의 2배 이상)
    monthly["anomaly_rate"] = monthly["anomaly"] / monthly["total"].clip(lower=1)
    avg_rate = avg_anomaly / max(avg_total, 1)
    high_rate_months = monthly[monthly["anomaly_rate"] > avg_rate * 2]
    for period, row in high_rate_months.iterrows():
        pct = row["anomaly_rate"] * 100
        findings.append(f"**{int(period)}월** 이상 비율 {pct:.1f}% (전체 평균의 {row['anomaly_rate'] / max(avg_rate, 0.001):.1f}배)")

    # 고위험 전표 집중 월
    if "risk_level" in df.columns:
        high_monthly = df[df["risk_level"] == "High"].groupby("fiscal_period").size()
        if not high_monthly.empty:
            peak_month = high_monthly.idxmax()
            peak_count = high_monthly.max()
            if peak_count > high_monthly.mean() * 1.5:
                findings.append(f"**{int(peak_month)}월** 고위험(High) 전표 집중 ({peak_count:,}건)")

    if not findings:
        return

    st.subheader("월별 특이점")
    for f in findings[:5]:
        st.markdown(f"- {f}")
    st.divider()


def _render_benford_summary(df: pd.DataFrame) -> None:
    """Benford 분석 요약 — 오버레이 차트 + MAD 판정."""
    if "first_digit" not in df.columns:
        st.caption("Benford 분석: first_digit 피처 없음 (feature engineering 필요)")
        return

    digits = df["first_digit"].dropna()
    if len(digits) < 30:
        st.caption(f"Benford 분석: 유효 표본 {len(digits)}건 — 최소 30건 필요")
        return

    st.divider()
    st.subheader("Benford 분석")

    from config.settings import get_settings
    from src.validation.benford import BENFORD_EXPECTED, analyze_benford

    settings = get_settings()
    br, _ = analyze_benford(digits, settings=settings)

    digits_df = pd.DataFrame({
        "digit": range(1, 10),
        "observed_freq": [br.observed.get(d, 0.0) for d in range(1, 10)],
        "expected_freq": [BENFORD_EXPECTED[d] for d in range(1, 10)],
    })

    col_chart, col_metrics = st.columns([2, 1])
    with col_chart:
        fig = benford_overlay(digits_df, mad_threshold=settings.benford_mad_threshold)
        st.plotly_chart(fig, use_container_width=True)
    with col_metrics:
        conformity = {
            "close": "Close (적합)",
            "acceptable": "Acceptable (수용)",
            "marginally": "Marginal (경계)",
            "nonconforming": "Nonconformity (부적합)",
        }.get(br.mad_conformity, br.mad_conformity)
        st.metric("표본", f"{br.sample_size:,}건")
        st.metric(
            "MAD (평균절대편차)",
            f"{br.mad:.4f}" if br.mad is not None else "N/A",
            help="실제 첫째자리 분포와 Benford 이론 분포의 평균 차이. 0에 가까울수록 정상.",
        )
        st.metric("판정", conformity)
