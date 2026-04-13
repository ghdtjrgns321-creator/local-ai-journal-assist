"""차원별 분포 시각화 — process_distribution_bar, persona_risk_matrix, company_comparison."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    RISK_COLORS,
    empty_figure,
)


def process_distribution_bar(df: pd.DataFrame) -> go.Figure:
    """business_process별 전표 건수 + 이상 비율 이중축 바+라인 차트."""
    required = {"business_process", "document_id", "risk_level"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("프로세스 분포 데이터가 없습니다")

    stats = df.groupby("business_process").agg(
        count=("document_id", "size"),
        abnormal=("risk_level", lambda s: (s != "Normal").sum()),
    )
    stats["abnormal_rate"] = (stats["abnormal"] / stats["count"] * 100).round(1)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=stats.index, y=stats["count"], name="건수", marker_color="#2563EB"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=stats.index, y=stats["abnormal_rate"],
            mode="lines+markers", name="이상 비율(%)",
            line={"color": "#DC2626", "width": 2},
        ),
        secondary_y=True,
    )

    fig.update_layout(**DEFAULT_LAYOUT, title="프로세스별 전표 분포")
    fig.update_yaxes(title_text="건수", secondary_y=False)
    fig.update_yaxes(title_text="이상 비율(%)", secondary_y=True)
    return fig


def persona_risk_matrix(df: pd.DataFrame) -> go.Figure:
    """user_persona(5종) x risk_level(4등급) 교차표 히트맵."""
    required = {"user_persona", "risk_level"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("페르소나 데이터가 없습니다")

    risk_order = list(RISK_COLORS.keys())
    pivot = pd.crosstab(df["user_persona"], df["risk_level"])
    # Why: 모든 위험등급 컬럼 보장 (데이터에 없는 등급도 0으로 표시).
    for r in risk_order:
        if r not in pivot.columns:
            pivot[r] = 0
    pivot = pivot[risk_order]

    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
        colorscale="Blues",
        text=pivot.values, texttemplate="%{text}",
        hovertemplate="페르소나: %{y}<br>등급: %{x}<br>건수: %{z}<extra></extra>",
    ))
    fig.update_layout(**DEFAULT_LAYOUT, title="페르소나 × 위험등급 매트릭스")
    return fig


def company_comparison(df: pd.DataFrame) -> go.Figure:
    """법인별(company_code) KPI 비교 — 건수(좌축) + 평균점수(우축) 이중축."""
    required = {"company_code", "document_id", "risk_level", "anomaly_score"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("법인 비교 데이터가 없습니다")

    stats = df.groupby("company_code").agg(
        total=("document_id", "size"),
        abnormal=("risk_level", lambda s: (s != "Normal").sum()),
        avg_score=("anomaly_score", "mean"),
    )

    companies = stats.index.tolist()
    # Why: 건수와 점수(0~1)는 스케일이 다르므로 이중축으로 분리.
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=companies, y=stats["total"], name="전표수", marker_color="#2563EB"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=companies, y=stats["abnormal"], name="이상수", marker_color="#DC2626"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=companies, y=stats["avg_score"].round(3),
            mode="lines+markers", name="평균 위험점수",
            line={"color": "#FFA15A", "width": 2},
        ),
        secondary_y=True,
    )

    fig.update_layout(**DEFAULT_LAYOUT, title="법인별 KPI 비교", barmode="group")
    fig.update_yaxes(title_text="건수", secondary_y=False)
    fig.update_yaxes(title_text="평균 위험점수", range=[0, 1], secondary_y=True)
    return fig
