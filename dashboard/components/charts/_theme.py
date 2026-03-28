"""차트 공통 테마 — 색상·레이아웃·빈 데이터 Figure.

Why: 11종 차트의 시각적 일관성을 한 곳에서 관리.
"""

from __future__ import annotations

import plotly.graph_objects as go

# ── 색상 팔레트 ──────────────────────────────────────────────────

RISK_COLORS: dict[str, str] = {
    "High": "#FF4B4B",
    "Medium": "#FFA500",
    "Low": "#FFD700",
    "Normal": "#00CC96",
}

# Why: Layer enum 값(snake_case)을 키로 사용. constants.py Layer와 1:1 대응.
LAYER_COLORS: dict[str, str] = {
    "layer_a": "#636EFA",
    "layer_b": "#EF553B",
    "layer_c": "#FFA15A",
    "benford": "#AB63FA",
}

LAYER_LABELS: dict[str, str] = {
    "layer_a": "Layer A (무결성)",
    "layer_b": "Layer B (부정)",
    "layer_c": "Layer C (징후)",
    "benford": "Benford",
}

# ── 기본 레이아웃 ─────────────────────────────────────────────

DEFAULT_LAYOUT: dict = {
    "template": "plotly_white",
    "font": {"family": "Pretendard, Noto Sans KR, sans-serif"},
    "margin": {"l": 40, "r": 20, "t": 40, "b": 40},
    "hovermode": "closest",
}


def empty_figure(message: str = "데이터가 없습니다") -> go.Figure:
    """빈 DataFrame일 때 표시할 안내 Figure."""
    fig = go.Figure()
    fig.update_layout(
        **DEFAULT_LAYOUT,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
            "text": message,
            "xref": "paper", "yref": "paper",
            "x": 0.5, "y": 0.5,
            "showarrow": False,
            "font": {"size": 16, "color": "#999"},
        }],
    )
    return fig
