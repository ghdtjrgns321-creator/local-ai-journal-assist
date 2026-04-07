"""연도 비교 차트 5종 (RC-4-7).

DuckDB SQL 집계 결과(소규모 DataFrame)를 받아 Plotly Figure로 변환한다.
원본 데이터를 Python에 적재하지 않는다 (메모리 폭발 방지).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    RISK_COLORS,
    empty_figure,
)

# Why: 당기/전기 색상을 일관되게 적용
_CURRENT_COLOR = "#636EFA"
_PRIOR_COLOR = "#B0BEC5"


def yoy_count_bar(current: int, prior: int) -> go.Figure:
    """건수 YoY 비교 — 수평 바 2개."""
    if current == 0 and prior == 0:
        return empty_figure("비교 데이터 없음")
    fig = go.Figure([
        go.Bar(name="전기", x=[prior], y=["전표 건수"], orientation="h",
               marker_color=_PRIOR_COLOR),
        go.Bar(name="당기", x=[current], y=["전표 건수"], orientation="h",
               marker_color=_CURRENT_COLOR),
    ])
    fig.update_layout(**DEFAULT_LAYOUT, title="건수 비교", barmode="group", height=200)
    return fig


def yoy_amount_bar(current_amt: float, prior_amt: float) -> go.Figure:
    """금액 YoY 비교 — 수평 바 2개."""
    if current_amt == 0 and prior_amt == 0:
        return empty_figure("비교 데이터 없음")
    fig = go.Figure([
        go.Bar(name="전기", x=[prior_amt], y=["총 차변 금액"], orientation="h",
               marker_color=_PRIOR_COLOR),
        go.Bar(name="당기", x=[current_amt], y=["총 차변 금액"], orientation="h",
               marker_color=_CURRENT_COLOR),
    ])
    fig.update_layout(**DEFAULT_LAYOUT, title="금액 비교", barmode="group", height=200)
    return fig


def risk_distribution_comparison(
    current_df: pd.DataFrame, prior_df: pd.DataFrame,
) -> go.Figure:
    """위험등급 분포 비교 — 도넛 2개 나란히.

    Args:
        current_df: columns=[risk_level, cnt]
        prior_df: columns=[risk_level, cnt]
    """
    if current_df.empty and prior_df.empty:
        return empty_figure("위험등급 데이터 없음")

    fig = make_subplots(
        rows=1, cols=2, specs=[[{"type": "pie"}, {"type": "pie"}]],
        subplot_titles=["당기", "전기"],
    )
    for col_idx, (df, name) in enumerate([(current_df, "당기"), (prior_df, "전기")], 1):
        if df.empty:
            continue
        colors = [RISK_COLORS.get(r, "#999") for r in df["risk_level"]]
        fig.add_trace(
            go.Pie(labels=df["risk_level"], values=df["cnt"],
                   hole=0.45, marker={"colors": colors}, name=name),
            row=1, col=col_idx,
        )
    fig.update_layout(**DEFAULT_LAYOUT, title="위험등급 분포 비교", height=350)
    return fig


def rule_violation_delta(
    current_df: pd.DataFrame, prior_df: pd.DataFrame,
) -> go.Figure:
    """룰별 위반 건수 증감 — 수평 바 차트.

    Args:
        current_df: columns=[rule_code, cnt]
        prior_df: columns=[rule_code, cnt]
    """
    if current_df.empty and prior_df.empty:
        return empty_figure("룰 위반 데이터 없음")

    # Why: 두 연도의 룰 코드를 합집합으로 정렬
    merged = pd.merge(
        current_df.rename(columns={"cnt": "당기"}),
        prior_df.rename(columns={"cnt": "전기"}),
        on="rule_code", how="outer",
    ).fillna(0)
    merged["증감"] = merged["당기"] - merged["전기"]
    merged = merged.sort_values("증감")

    colors = ["#FF4B4B" if v > 0 else "#00CC96" for v in merged["증감"]]
    fig = go.Figure(
        go.Bar(x=merged["증감"], y=merged["rule_code"], orientation="h",
               marker_color=colors),
    )
    fig.update_layout(**DEFAULT_LAYOUT, title="룰별 위반 증감 (당기 - 전기)", height=400)
    return fig


def new_accounts_table(
    current_accounts: set[str], prior_accounts: set[str],
) -> pd.DataFrame:
    """신규/제거 계정과목 목록 — DataFrame 반환 (st.dataframe으로 표시).

    Returns:
        columns=[계정코드, 구분] — "신규"(당기에만 존재) 또는 "제거"(전기에만 존재)
    """
    new = current_accounts - prior_accounts
    removed = prior_accounts - current_accounts
    rows = [{"계정코드": a, "구분": "신규"} for a in sorted(new)]
    rows += [{"계정코드": a, "구분": "제거"} for a in sorted(removed)]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["계정코드", "구분"])
