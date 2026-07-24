"""Benford 분석 시각화 — benford_overlay + benford_facet."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.charts._theme import DEFAULT_LAYOUT, empty_figure
from src.validation.benford import BENFORD_EXPECTED

_DIGITS = range(1, 10)


def benford_overlay(
    digits_df: pd.DataFrame,
    *,
    mad_threshold: float = 0.015,
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
    bar_colors = ["#DC2626" if d > mad_threshold else "#2563EB" for d in deviation]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["digit"],
            y=df["observed_freq"],
            name="관측 빈도",
            marker_color=bar_colors,
            hovertemplate="숫자: %{x}<br>관측: %{y:.4f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["digit"],
            y=df["expected_freq"],
            mode="lines+markers",
            name="기대 빈도 (Benford)",
            line={"color": "#6B7280", "width": 2, "dash": "dash"},
            hovertemplate="숫자: %{x}<br>기대: %{y:.4f}<extra></extra>",
        )
    )

    fig.update_layout(
        **DEFAULT_LAYOUT,
        title="Benford 첫째 자릿수 분석",
        xaxis_title="첫째 자릿수",
        yaxis_title="빈도",
        xaxis={"dtick": 1},
    )
    return fig


def benford_group_summary(
    df: pd.DataFrame,
    group_col: str,
    *,
    min_sample: int = 300,
) -> pd.DataFrame:
    """그룹별 표본 수·벤포드 이탈도(MAD) 요약 표.

    Why: 분리 분석의 '상위'를 건수가 아니라 벤포드 이탈도(=수상한 정도)로 정렬하기
         위한 사전 집계. 단, 표본이 적으면 분포가 우연히 크게 튀어 신호로 오인되므로
         min_sample 이상만 순위(eligible) 대상으로 삼는다.

    반환: index=group, columns=[count, mad, eligible].
          정렬 = eligible(이탈도 desc) → ineligible(건수 desc).
    """
    empty = pd.DataFrame(columns=["count", "mad", "eligible"])
    if df.empty or "first_digit" not in df.columns or group_col not in df.columns:
        return empty

    work = df[["first_digit", group_col]].dropna()
    if work.empty:
        return empty

    expected = pd.Series({d: BENFORD_EXPECTED[d] for d in _DIGITS})
    records: list[tuple] = []
    for group_name, sub in work.groupby(group_col)["first_digit"]:
        counts = sub.value_counts().reindex(_DIGITS, fill_value=0)
        total = int(counts.sum())
        if total == 0:
            continue
        freq = counts / total
        mad = float((freq - expected).abs().mean())
        records.append((group_name, total, mad))

    if not records:
        return empty

    summary = pd.DataFrame(records, columns=[group_col, "count", "mad"]).set_index(group_col)
    summary["eligible"] = summary["count"] >= min_sample
    # Why: 순위 대상(eligible)은 이탈도 높은 순, 나머지는 참고용으로 건수 많은 순.
    return pd.concat(
        [
            summary[summary["eligible"]].sort_values("mad", ascending=False),
            summary[~summary["eligible"]].sort_values("count", ascending=False),
        ]
    )


def benford_facet(
    df: pd.DataFrame,
    group_col: str,
    *,
    groups: list,
    mad_threshold: float = 0.015,
    group_labels: dict | None = None,
) -> go.Figure:
    """지정된 그룹들의 Benford 분포 facet 차트 (make_subplots).

    Why: facet_col은 기대선 overlay 불가. subplot 루프로 관측 bar + 기대 line 배치.
         그룹 선택·정렬(이탈도 순)은 호출부가 benford_group_summary로 결정하고,
         여기서는 넘겨받은 groups만 순서대로 그린다 (Others 병합 없음).
         group_labels: 그룹 원본값 → subplot 표시 라벨(예: 계정코드 → '2200 매출채권').
    """
    if df.empty or "first_digit" not in df.columns or group_col not in df.columns:
        return empty_figure("분리 분석 데이터가 없습니다")
    if not groups:
        return empty_figure("표시할 그룹이 없습니다")

    work = df[["first_digit", group_col]].dropna()
    if work.empty:
        return empty_figure("유효한 first_digit 데이터가 없습니다")

    labels = group_labels or {}
    n_groups = len(groups)
    cols = min(n_groups, 3)
    rows = math.ceil(n_groups / cols)

    # Why: 행이 늘수록 제목이 윗행 x축 라벨과 겹친다. 행 간 간격을 넉넉히(0.12) 두되
    #      plotly 제약(vertical_spacing ≤ 1/(rows-1))을 넘지 않게 clamp.
    v_spacing = min(0.12, 0.9 / (rows - 1)) if rows > 1 else 0.0
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[str(labels.get(g, g)) for g in groups],
        vertical_spacing=v_spacing,
        horizontal_spacing=0.07,
    )

    # Why: 계정 한글명이 길어 제목이 옆 칸을 침범 → 제목 폰트를 줄여 가독성 확보.
    for annotation in fig.layout.annotations:
        annotation.font.size = 12

    expected_freq = [BENFORD_EXPECTED[d] for d in _DIGITS]

    for idx, group_name in enumerate(groups):
        r, c = divmod(idx, cols)
        row, col = r + 1, c + 1
        sub = work[work[group_col] == group_name]["first_digit"]

        # Why: digit 8, 9가 0건이면 BENFORD_EXPECTED(길이 9)와 불일치 → reindex 필수
        counts = sub.value_counts().reindex(_DIGITS, fill_value=0)
        total = counts.sum()
        if total == 0:
            continue

        freq = counts / total
        deviation = (freq - pd.Series(expected_freq, index=freq.index)).abs()
        bar_colors = ["#DC2626" if d > mad_threshold else "#2563EB" for d in deviation]

        fig.add_trace(
            go.Bar(
                x=list(_DIGITS),
                y=freq.tolist(),
                marker_color=bar_colors,
                showlegend=False,
                hovertemplate="digit: %{x}<br>빈도: %{y:.4f}<extra></extra>",
            ),
            row=row,
            col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=list(_DIGITS),
                y=expected_freq,
                mode="lines+markers",
                line={"color": "#6B7280", "width": 1.5, "dash": "dash"},
                showlegend=False,
                hovertemplate="기대: %{y:.4f}<extra></extra>",
            ),
            row=row,
            col=col,
        )

    # Why: 차트 상단 title이 첫 행 subplot 제목과 겹친다. 제목은 호출부(tab_benford)의
    #      markdown 헤더로 대체하고, 차트 내부 title은 제거한다.
    layout = {k: v for k, v in DEFAULT_LAYOUT.items() if k != "margin"}
    fig.update_layout(
        **layout,
        margin={"l": 40, "r": 20, "t": 40, "b": 30},
        height=340 * rows,
        showlegend=False,
    )
    fig.update_xaxes(dtick=1)
    return fig
