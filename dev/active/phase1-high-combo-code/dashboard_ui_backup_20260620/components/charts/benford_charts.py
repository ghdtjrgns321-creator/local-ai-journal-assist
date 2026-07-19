"""Benford 분석 시각화 — benford_overlay + benford_facet."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.charts._theme import DEFAULT_LAYOUT, empty_figure
from src.validation.benford import BENFORD_EXPECTED

_DIGITS = range(1, 10)
_MIN_SAMPLE = 50  # facet subplot 최소 표본 수


def benford_overlay(
    digits_df: pd.DataFrame, *, mad_threshold: float = 0.015,
) -> go.Figure:
    """Benford 관측 vs 기대 빈도 오버레이 바+라인 차트.

    X=digit(1~9). 바=observed_freq, 라인=expected_freq.
    편차 > mad_threshold인 digit을 빨간색으로 강조.
    """
    required = {"digit", "observed_freq", "expected_freq"}
    if digits_df.empty or not required.issubset(digits_df.columns):
        return empty_figure("Benford 데이터가 없습니다")

    df = digits_df.sort_values("digit")
    deviation = (df["observed_freq"] - df["expected_freq"]).abs()
    # Why: MAD 초과 digit만 빨간색으로 강조하여 이상 분포 직관적 식별.
    bar_colors = [
        "#DC2626" if d > mad_threshold else "#2563EB"
        for d in deviation
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["digit"], y=df["observed_freq"],
        name="관측 빈도", marker_color=bar_colors,
        hovertemplate="숫자: %{x}<br>관측: %{y:.4f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["digit"], y=df["expected_freq"],
        mode="lines+markers", name="기대 빈도 (Benford)",
        line={"color": "#6B7280", "width": 2, "dash": "dash"},
        hovertemplate="숫자: %{x}<br>기대: %{y:.4f}<extra></extra>",
    ))

    fig.update_layout(
        **DEFAULT_LAYOUT, title="Benford 첫째 자릿수 분석",
        xaxis_title="첫째 자릿수", yaxis_title="빈도",
        xaxis={"dtick": 1},
    )
    return fig


def benford_facet(
    df: pd.DataFrame, group_col: str, *,
    mad_threshold: float = 0.015, max_groups: int = 6,
) -> go.Figure:
    """분리 기준별 Benford 분포 facet 차트 (make_subplots).

    Why: facet_col은 기대선 overlay 불가. subplot 루프로 관측 bar + 기대 line 배치.
         그룹 과다 시 브라우저 OOM 방지를 위해 Top N + Others 병합.
    """
    if df.empty or "first_digit" not in df.columns or group_col not in df.columns:
        return empty_figure("분리 분석 데이터가 없습니다")

    # Why: .dropna()는 뷰를 반환할 수 있어 .where() 시 원본 df 변조 위험 → .copy() 필수
    work = df[["first_digit", group_col]].dropna().copy()
    if work.empty:
        return empty_figure("유효한 first_digit 데이터가 없습니다")

    # Why: 그룹 20~30개 시 subplot OOM → 건수 Top N만, 나머지 Others 병합
    group_sizes = work[group_col].value_counts()
    if len(group_sizes) > max_groups:
        top_groups = set(group_sizes.head(max_groups).index)
        work[group_col] = work[group_col].where(
            work[group_col].isin(top_groups), other="기타(Others)",
        )
        group_sizes = work[group_col].value_counts()

    groups = group_sizes.index.tolist()
    n_groups = len(groups)
    cols = min(n_groups, 3)
    rows = math.ceil(n_groups / cols)

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=[str(g) for g in groups],
    )

    expected_freq = [BENFORD_EXPECTED[d] for d in _DIGITS]

    for idx, group_name in enumerate(groups):
        r, c = divmod(idx, cols)
        row, col = r + 1, c + 1
        sub = work[work[group_col] == group_name]["first_digit"]

        # Why: digit 8, 9가 0건이면 BENFORD_EXPECTED(길이 9)와 불일치 → reindex 필수
        counts = sub.value_counts().reindex(_DIGITS, fill_value=0)
        total = counts.sum()

        if total < _MIN_SAMPLE:
            # Why: Plotly subplot 축 ID는 x, x2, x3... (x1 아님). idx=0 → "", 나머지 → "2","3"...
            axis_suffix = "" if idx == 0 else str(idx + 1)
            fig.add_annotation(
                text=f"표본 부족 (n={total})",
                xref=f"x{axis_suffix}", yref=f"y{axis_suffix}",
                x=5, y=0.15, showarrow=False,
                font={"size": 12, "color": "#999"},
            )
            continue

        freq = counts / total
        deviation = (freq - pd.Series(expected_freq, index=freq.index)).abs()
        bar_colors = [
            "#DC2626" if d > mad_threshold else "#2563EB" for d in deviation
        ]

        fig.add_trace(
            go.Bar(x=list(_DIGITS), y=freq.tolist(), marker_color=bar_colors,
                   showlegend=False, hovertemplate="digit: %{x}<br>빈도: %{y:.4f}<extra></extra>"),
            row=row, col=col,
        )
        fig.add_trace(
            go.Scatter(x=list(_DIGITS), y=expected_freq, mode="lines+markers",
                       line={"color": "#6B7280", "width": 1.5, "dash": "dash"},
                       showlegend=False, hovertemplate="기대: %{y:.4f}<extra></extra>"),
            row=row, col=col,
        )

    fig.update_layout(
        **DEFAULT_LAYOUT,
        title=f"분리 분석: {group_col}별 Benford 분포",
        height=300 * rows,
        showlegend=False,
    )
    fig.update_xaxes(dtick=1)
    return fig
