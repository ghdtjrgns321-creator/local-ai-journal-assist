"""EDA 시각화 차트 — 결측률 바, 이상치 비율, 수치형 박스플롯, 품질 게이지.

Why: src/eda/report.py의 summarize_for_dashboard() 반환값을 시각화.
     기존 차트 모듈과 동일 패턴 (dict/list in → go.Figure out).
"""

from __future__ import annotations

import plotly.graph_objects as go

from dashboard.components.charts._theme import DEFAULT_LAYOUT, empty_figure

# Why: 결측률 10% 이상은 주의 필요 — EDA 경고 기준과 동일
_MISSING_WARN = 0.10


def missing_rate_bar(missing_data: dict[str, float]) -> go.Figure:
    """컬럼별 결측률 수평 바 차트. 10% 이상 빨간색 하이라이트."""
    if not missing_data:
        return empty_figure("결측 데이터 없음")

    # Why: 결측률 높은 순 정렬 → 문제 컬럼이 상단에 노출
    sorted_items = sorted(missing_data.items(), key=lambda x: x[1], reverse=True)
    cols = [item[0] for item in sorted_items]
    rates = [item[1] for item in sorted_items]
    colors = ["#FF4B4B" if r >= _MISSING_WARN else "#00CC96" for r in rates]

    fig = go.Figure(go.Bar(
        x=rates, y=cols, orientation="h",
        marker_color=colors,
        text=[f"{r:.1%}" for r in rates],
        textposition="auto",
    ))
    fig.update_layout(
        **DEFAULT_LAYOUT,
        title="컬럼별 결측률",
        xaxis_title="결측률",
        xaxis={"tickformat": ".0%", "range": [0, max(rates) * 1.15 or 0.1]},
        yaxis={"autorange": "reversed"},
        height=max(300, len(cols) * 25),
    )
    return fig


def outlier_ratio_bar(numeric_stats: list[dict], total_rows: int) -> go.Figure:
    """수치형 컬럼별 이상치 비율 수평 바 차트."""
    if not numeric_stats or total_rows == 0:
        return empty_figure("이상치 데이터 없음")

    # Why: outlier_count가 None인 컬럼 제외
    valid = [s for s in numeric_stats if s.get("outlier_count") is not None]
    if not valid:
        return empty_figure("이상치 데이터 없음")

    cols = [s["column"] for s in valid]
    ratios = [s["outlier_count"] / total_rows for s in valid]
    colors = ["#FF4B4B" if r >= 0.05 else "#636EFA" for r in ratios]

    fig = go.Figure(go.Bar(
        x=ratios, y=cols, orientation="h",
        marker_color=colors,
        text=[f"{r:.2%}" for r in ratios],
        textposition="auto",
    ))
    fig.update_layout(
        **DEFAULT_LAYOUT,
        title="수치형 컬럼별 이상치 비율 (Tukey IQR)",
        xaxis_title="이상치 비율",
        xaxis={"tickformat": ".1%"},
        yaxis={"autorange": "reversed"},
        height=max(300, len(cols) * 30),
    )
    return fig


def numeric_box_plots(numeric_stats: list[dict]) -> go.Figure:
    """수치형 컬럼 박스플롯 (Q1/median/Q3/min/max). 개별 서브플롯."""
    if not numeric_stats:
        return empty_figure("수치형 컬럼 없음")

    fig = go.Figure()
    for s in numeric_stats:
        q1 = s.get("q1", 0) or 0
        q3 = s.get("q3", 0) or 0
        iqr = q3 - q1
        # Why: Tukey's fence (1.5×IQR) 기반 fence — min/max 사용 시 이상치 표현 불가
        lower = max(s.get("min", 0) or 0, q1 - 1.5 * iqr)
        upper = min(s.get("max", 0) or 0, q3 + 1.5 * iqr)
        fig.add_trace(go.Box(
            name=s["column"],
            lowerfence=[lower],
            q1=[q1],
            median=[s.get("median", 0)],
            q3=[q3],
            upperfence=[upper],
            marker_color="#636EFA",
        ))

    fig.update_layout(
        **DEFAULT_LAYOUT,
        title="수치형 컬럼 분포 (Box Plot)",
        showlegend=False,
        # Why: 금액 컬럼(억 단위)과 카운트 컬럼(1자리) 스케일 차이 대응
        yaxis={"type": "log", "title": "값 (log scale)"},
        height=400,
    )
    return fig


def quality_gauge(score: float) -> go.Figure:
    """데이터 품질 점수 게이지 차트 (0~100)."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": "데이터 품질 점수"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#636EFA"},
            "steps": [
                {"range": [0, 60], "color": "#FFCCCC"},
                {"range": [60, 80], "color": "#FFF3CD"},
                {"range": [80, 100], "color": "#D4EDDA"},
            ],
            # Why: threshold line은 bar 색상과 시각적으로 중복되므로 제거
            #      gauge bar 자체가 현재 값을 충분히 표시
        },
    ))
    fig.update_layout(**DEFAULT_LAYOUT, height=250)
    return fig
