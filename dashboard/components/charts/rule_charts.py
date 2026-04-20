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
    # Why: 알파벳순 정렬로 L1-01→L4-05 일관된 시각적 순서 보장.
    counts = counts.reindex(sorted(counts.index))

    # Why: Y축 라벨을 "L4-05 (비정상시간 집중입력)" 형태로 → 코드 암기 부담 제거.
    label_map = {code: f"{code} ({RULE_CODES.get(code, code)})" for code in counts.index}

    fig = go.Figure()
    for prefix, layer_key in _PREFIX_TO_LAYER.items():
        label = LAYER_LABELS[layer_key]
        mask = [code for code in counts.index if code.startswith(prefix)]
        if not mask:
            continue
        subset = counts[mask]
        y_labels = [label_map[c] for c in subset.index]
        fig.add_trace(go.Bar(
            y=y_labels,
            x=subset.values,
            orientation="h",
            name=label,
            marker_color=LAYER_COLORS[layer_key],
            hovertemplate="%{y}<br>%{x:,}건<extra></extra>",
        ))

    fig.update_layout(
        **{**DEFAULT_LAYOUT, "margin": {"l": 180, "r": 20, "t": 40, "b": 40}},
        title="룰별 위반 건수",
        barmode="stack",
        legend={"orientation": "h", "y": -0.15},
    )
    # Why: update_layout에서 xaxis/yaxis 중복 키워드 방지 → 별도 호출.
    fig.update_xaxes(title_text="위반 건수 (log scale)", type="log")
    fig.update_yaxes(categoryorder="category ascending")
    return fig
