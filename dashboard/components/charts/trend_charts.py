"""시계열 패턴 시각화 — monthly_trend, hourly_heatmap."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts._theme import DEFAULT_LAYOUT, empty_figure


def monthly_trend(df: pd.DataFrame) -> go.Figure:
    """fiscal_period(1~12) 월별 전표 건수 추이 (전체 vs 이상).

    분기말(3, 6, 9, 12)에 수직 참조선 표시.
    """
    required = {"fiscal_period", "document_id", "risk_level"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("월별 추이 데이터가 없습니다")

    monthly = df.groupby("fiscal_period").agg(
        total=("document_id", "size"),
        abnormal=("risk_level", lambda s: (s != "Normal").sum()),
    ).reindex(range(1, 13), fill_value=0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=monthly.index, y=monthly["total"],
        mode="lines+markers", name="전체",
        line={"color": "#636EFA"},
    ))
    fig.add_trace(go.Scatter(
        x=monthly.index, y=monthly["abnormal"],
        mode="lines+markers", name="이상",
        line={"color": "#EF553B"},
    ))

    # Why: 분기말은 결산 집중 기간 → 시각적 구분으로 패턴 인식 지원.
    for q in (3, 6, 9, 12):
        fig.add_vline(x=q, line_dash="dot", line_color="#ccc", opacity=0.7)

    fig.update_layout(
        **DEFAULT_LAYOUT, title="월별 전표 추이",
        xaxis_title="회계기간", yaxis_title="건수",
        xaxis={"dtick": 1},
    )
    return fig


def hourly_heatmap(df: pd.DataFrame) -> go.Figure:
    """요일(월~일) x 시간(0~23) 전표 건수 히트맵.

    심야(22~6) / 주말 영역에 점선 박스 오버레이 → C02/C03 탐지 연계.
    """
    if df.empty or "posting_date" not in df.columns:
        return empty_figure("시간대별 데이터가 없습니다")

    dates = pd.to_datetime(df["posting_date"], errors="coerce")
    valid = dates.dropna()
    if valid.empty:
        return empty_figure("유효한 날짜 데이터가 없습니다")

    temp = pd.DataFrame({"weekday": valid.dt.dayofweek, "hour": valid.dt.hour})
    pivot = temp.groupby(["weekday", "hour"]).size().unstack(fill_value=0)
    # Why: 0~6(월~일) 전체 행, 0~23 전체 열 보장.
    pivot = pivot.reindex(index=range(7), columns=range(24), fill_value=0)

    day_labels = ["월", "화", "수", "목", "금", "토", "일"]
    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=list(range(24)), y=day_labels,
        colorscale="YlOrRd",
        hovertemplate="시간: %{x}시<br>요일: %{y}<br>건수: %{z}<extra></extra>",
    ))

    # Why: 심야(22~6) 영역 — 두 구간으로 분리 (0~6시 + 22~23시). C03 탐지 연계.
    fig.add_shape(
        type="rect", x0=-0.5, x1=6.5, y0=-0.5, y1=6.5,
        line={"dash": "dash", "color": "#FF4B4B", "width": 2},
    )
    fig.add_shape(
        type="rect", x0=21.5, x1=23.5, y0=-0.5, y1=6.5,
        line={"dash": "dash", "color": "#FF4B4B", "width": 2},
    )
    # Why: 주말(토·일) 영역 점선 박스 — C02 탐지 영역 시각화.
    fig.add_shape(
        type="rect", x0=-0.5, x1=23.5, y0=4.5, y1=6.5,
        line={"dash": "dash", "color": "#FFA500", "width": 2},
    )

    fig.update_layout(
        **DEFAULT_LAYOUT, title="시간대별 전표 히트맵",
        xaxis_title="시간", yaxis_title="요일",
    )
    return fig
