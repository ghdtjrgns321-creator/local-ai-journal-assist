"""특수 목적 차트 — fraud_type_treemap (개발모드), layer_score_radar (Explorer 상세)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    LAYER_LABELS,
    empty_figure,
)


def fraud_type_treemap(df: pd.DataFrame) -> go.Figure:
    """fraud_type별 건수 Treemap. 개발 모드 전용 (호출부에서 분기).

    Why: 13종 부정유형의 상대적 규모를 직관적으로 파악.
    """
    if df.empty or "fraud_type" not in df.columns:
        return empty_figure("부정유형 데이터가 없습니다")

    # Why: NaN/빈 문자열 제외 — fraud_type이 없는 정상 전표 필터링.
    valid = df[df["fraud_type"].notna() & (df["fraud_type"] != "")]
    if valid.empty:
        return empty_figure("부정유형 데이터가 없습니다")

    counts = valid["fraud_type"].value_counts()
    fig = go.Figure(go.Treemap(
        labels=counts.index.tolist(),
        parents=[""] * len(counts),
        values=counts.values.tolist(),
        hovertemplate="유형: %{label}<br>건수: %{value}<extra></extra>",
    ))
    fig.update_layout(**DEFAULT_LAYOUT, title="부정유형 분포 (Treemap)")
    return fig


def layer_score_radar(scores: dict[str, float]) -> go.Figure:
    """선택 전표의 Layer A/B/C/Benford 점수 방사형 차트.

    Args:
        scores: {"layer_a": 0.3, "layer_b": 0.8, ...} 형태.
                Explorer 탭 행 선택 시 DetectionResult.details에서 추출.
    """
    if not scores:
        return empty_figure("레이어 점수가 없습니다")

    layers = list(scores.keys())
    values = list(scores.values())
    labels = [LAYER_LABELS.get(k, k) for k in layers]

    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],  # Why: 방사형 차트 닫기 위해 첫 값 반복.
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor="rgba(99, 110, 250, 0.15)",
        line={"color": "#636EFA"},
        hovertemplate="%{theta}: %{r:.3f}<extra></extra>",
    ))

    fig.update_layout(
        **DEFAULT_LAYOUT, title="레이어별 점수",
        polar={"radialaxis": {"visible": True, "range": [0, 1]}},
        showlegend=False,
    )
    return fig
