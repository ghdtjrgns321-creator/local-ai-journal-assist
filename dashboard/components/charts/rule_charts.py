"""룰 위반 건수 시각화 — rule_violation_bar."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    LAYER_COLORS,
    LAYER_LABELS,
    empty_figure,
)
from src.detection.constants import RULE_CODES

# Why: 룰 접두사(A/B/C) → Layer enum 값 매핑. 차트 색상·범례에 사용.
_PREFIX_TO_LAYER: dict[str, str] = {
    "A": "layer_a",
    "B": "layer_b",
    "C": "layer_c",
}


def rule_violation_bar(df: pd.DataFrame) -> go.Figure:
    """24개 룰별 위반 건수 가로 바 차트. 레이어별 색상 구분.

    flagged_rules 컬럼(comma-separated)을 파싱하여 룰별 건수 집계.
    """
    if df.empty or "flagged_rules" not in df.columns:
        return empty_figure("룰 위반 데이터가 없습니다")

    # Why: 빈 문자열("")은 Normal 행 → NA 변환 후 제거해야 explode 시 오염 방지.
    rules = (
        df["flagged_rules"]
        .replace("", pd.NA)
        .dropna()
        .str.split(",")
        .explode()
        .str.strip()
    )
    if rules.empty:
        return empty_figure("위반된 룰이 없습니다")

    counts = rules.value_counts()
    # Why: 알파벳순 정렬로 A01→C12 일관된 시각적 순서 보장.
    counts = counts.reindex(sorted(counts.index))

    fig = go.Figure()
    # Why: _PREFIX_TO_LAYER 기준으로 순회. LAYER_LABELS에 benford 키가 있지만
    #      룰 코드에 benford 접두사는 없으므로 _PREFIX_TO_LAYER만 사용하여 오매핑 방지.
    for prefix, layer_key in _PREFIX_TO_LAYER.items():
        label = LAYER_LABELS[layer_key]
        mask = [code for code in counts.index if code.startswith(prefix)]
        if not mask:
            continue
        subset = counts[mask]
        # Why: hover에 한글 룰 이름 표시 → 감사인이 코드 외워야 하는 부담 제거.
        hover_names = [RULE_CODES.get(c, c) for c in subset.index]
        fig.add_trace(go.Bar(
            y=subset.index,
            x=subset.values,
            orientation="h",
            name=label,
            marker_color=LAYER_COLORS[layer_key],
            hovertemplate="%{y} %{customdata}<br>%{x}건<extra></extra>",
            customdata=hover_names,
        ))

    fig.update_layout(
        **DEFAULT_LAYOUT,
        title="룰별 위반 건수",
        xaxis_title="위반 건수",
        yaxis={"categoryorder": "category ascending"},
        barmode="stack",
        legend={"orientation": "h", "y": -0.15},
    )
    return fig
