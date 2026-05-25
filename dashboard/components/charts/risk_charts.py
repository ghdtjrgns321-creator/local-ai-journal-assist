"""우선검토 등급 시각화 — risk_heatmap, risk_donut, anomaly_scatter."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    RISK_COLORS,
    empty_figure,
)

# Why: 위험등급 순서를 보장하여 도넛/범례가 항상 동일 순서로 표시.
_RISK_ORDER = ["High", "Medium", "Low", "Normal"]


def risk_heatmap(df: pd.DataFrame) -> go.Figure:
    """fiscal_period(1~12) x business_process 위험 히트맵.

    색상 = 평균 anomaly_score. pivot_table로 생성.
    """
    required = {"fiscal_period", "business_process", "anomaly_score"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("히트맵 데이터가 없습니다")

    pivot = df.pivot_table(
        index="business_process", columns="fiscal_period",
        values="anomaly_score", aggfunc="mean",
    ).fillna(0)

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[str(c) for c in pivot.columns],
        y=pivot.index.tolist(),
        colorscale="Reds",
        hovertemplate="기간: %{x}<br>프로세스: %{y}<br>평균 점수: %{z:.3f}<extra></extra>",
    ))
    fig.update_layout(**DEFAULT_LAYOUT, title="월별 × 프로세스 검토 신호 히트맵")
    return fig


def risk_donut(df: pd.DataFrame) -> go.Figure:
    """위험 등급(High/Medium/Low/Normal) 분포 도넛 차트."""
    if df.empty or "risk_level" not in df.columns:
        return empty_figure("검토 후보 등급 데이터가 없습니다")

    counts = df["risk_level"].value_counts()
    # Why: 정의된 순서대로 정렬하여 일관된 시각화 보장.
    labels = [r for r in _RISK_ORDER if r in counts.index]
    values = [counts[r] for r in labels]
    colors = [RISK_COLORS[r] for r in labels]

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.4, marker={"colors": colors},
        hovertemplate="%{label}: %{value}건 (%{percent})<extra></extra>",
    ))
    fig.update_layout(**DEFAULT_LAYOUT, title="검토 후보 등급 분포", showlegend=True)
    return fig


def _priority_sample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    """계층적 우선순위 샘플링 — 이상치 보존 + Normal 축소.

    Why: 단순 random sample은 High/Medium 이상치가 탈락할 위험이 있음.
         High/Medium은 전수 보존, Normal 위주로 다운샘플링.
    """
    if len(df) <= max_points:
        return df

    # Why: 감사 관점에서 High/Medium은 반드시 시각화해야 하므로 전수 유지.
    priority = df[df["risk_level"].isin(["High", "Medium"])]
    rest = df[~df.index.isin(priority.index)]

    remaining = max_points - len(priority)
    if remaining <= 0:
        return priority.sample(n=max_points, random_state=42)

    rest_sample = rest.sample(n=min(remaining, len(rest)), random_state=42)
    return pd.concat([priority, rest_sample])


def anomaly_scatter(
    df: pd.DataFrame, *, max_points: int = 5000,
) -> go.Figure:
    """debit_amount vs anomaly_score 산점도. risk_level별 색상.

    Why: 1M행 직접 렌더링 시 브라우저 멈춤 → 계층적 샘플링으로 이상치 보존.
    """
    required = {"anomaly_score", "risk_level", "debit_amount", "document_id"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("산점도 데이터가 없습니다")

    sample = _priority_sample(df, max_points)
    fig = go.Figure()

    for level in _RISK_ORDER:
        subset = sample[sample["risk_level"] == level]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["debit_amount"], y=subset["anomaly_score"],
            mode="markers", name=level,
            marker={"color": RISK_COLORS[level], "size": 5, "opacity": 0.6},
            hovertemplate=(
                "문서: %{customdata[0]}<br>금액: %{x:,.0f}<br>"
                "점수: %{y:.3f}<extra></extra>"
            ),
            customdata=subset[["document_id"]].values,
        ))

    fig.update_layout(
        **DEFAULT_LAYOUT, title="금액 — 우선순위 점수 산점도",
        xaxis_title="차변 금액", yaxis_title="이상 신호 점수",
    )
    return fig
