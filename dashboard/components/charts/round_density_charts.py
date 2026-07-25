"""라운드넘버 밀집도(ROUND-DENSITY) finding 시각화 — 축별 수평 막대 + 원장 기준선.

Why: 이 신호의 뜻은 "이 그룹의 둥근 금액 비율이 원장 전체 기준선보다 높다"이다. 표로 두면
     감사인이 비율·기준선·초과분 세 숫자를 눈으로 빼서 비교해야 한다. 막대 길이(비율)와
     기준선(수직 점선)을 함께 그리면 초과 폭이 한 번에 읽히고, 정렬이 곧 검토 우선순위다.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from dashboard.components.charts._theme import (
    AXIS_STYLE,
    DEFAULT_LAYOUT,
    empty_figure,
)

# 축(scope) → 한글 라벨. detector 가 내는 축은 계정·전기월·작성자 3종
# (src/detection/round_density_rules._axis_keys).
SCOPE_LABELS: dict[str, str] = {
    "gl_account": "계정",
    "posting_month": "전기월",
    "created_by": "작성자",
}

# 축별 색 — LAYER_COLORS 와 겹치지 않는 3 hue. 룰 layer 색으로 오독되지 않게 분리.
SCOPE_COLORS: dict[str, str] = {
    "gl_account": "#2563EB",  # blue-600
    "posting_month": "#0D9488",  # teal-600
    "created_by": "#F97316",  # orange-500
}
_FALLBACK_COLOR = "#64748B"  # slate-500 — 축이 늘어나도 차트가 깨지지 않게

_BASELINE_COLOR = "#DC2626"  # red-600 — 기준선(비교 기준이지 위험 등급이 아님)

SEVERITY_LABELS: dict[str, str] = {"strong": "뚜렷", "moderate": "보통"}


def scope_label(scope: str) -> str:
    """축 코드 → 표시 라벨. 미등록 축은 코드 그대로."""
    return SCOPE_LABELS.get(scope, scope)


def round_density_bar(findings: list[dict[str, Any]], *, top_n: int = 20) -> go.Figure:
    """finding 을 둥근 금액 비율 수평 막대로. 초과분 큰 순으로 위에서 아래.

    Args:
        findings: build_phase1_macro_finding_queue(rule_id="ROUND-DENSITY") 결과.
        top_n: 차트에 그릴 최대 개수. 초과분은 호출부가 표로 노출한다.
    """
    rows = _rows(findings)
    if not rows:
        return empty_figure("Round Number 밀집 finding 이 없습니다")

    rows = rows[:top_n]
    # Why: plotly 수평 막대는 y 배열의 뒤쪽이 위로 간다 — 초과분 큰 것을 맨 위에 두려면 역순.
    rows.reverse()

    baseline = rows[0]["baseline"]
    fig = go.Figure(
        go.Bar(
            x=[r["ratio"] for r in rows],
            y=[r["label"] for r in rows],
            orientation="h",
            marker={"color": [SCOPE_COLORS.get(r["scope"], _FALLBACK_COLOR) for r in rows]},
            text=[f"{r['ratio']:.1%}" for r in rows],
            textposition="outside",
            textfont={"size": 11},
            customdata=[
                [r["n"], r["round_n"], r["baseline"], r["excess"], r["p"], r["severity"]]
                for r in rows
            ],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "표본 %{customdata[0]:,}건 중 둥근 금액 %{customdata[1]:,}건 (%{x:.1%})<br>"
                "원장 기준선 %{customdata[2]:.1%} · 초과 %{customdata[3]:+.1%}p<br>"
                "p=%{customdata[4]:.4f} · 신호 %{customdata[5]}"
                "<extra></extra>"
            ),
        )
    )
    fig.add_vline(
        x=baseline,
        line={"color": _BASELINE_COLOR, "width": 1.5, "dash": "dash"},
        annotation={
            "text": f"원장 기준선 {baseline:.1%}",
            "font": {"size": 11, "color": _BASELINE_COLOR},
        },
        annotation_position="top",
    )

    max_ratio = max(r["ratio"] for r in rows)
    fig.update_layout(
        **{
            **DEFAULT_LAYOUT,
            # Why: 상단 여백은 기준선 주석이 잘리지 않을 만큼, 좌측은 "계정 · 8110 지급수수료"
            #      길이의 라벨이 들어갈 만큼 확보한다.
            "margin": {"l": 190, "r": 40, "t": 34, "b": 44},
        },
        height=38 * len(rows) + 96,
        showlegend=False,
        bargap=0.35,
    )
    fig.update_xaxes(
        title_text="둥근 금액 비율",
        tickformat=".0%",
        range=[0, max_ratio * 1.22],
        **AXIS_STYLE,
    )
    fig.update_yaxes(title_text="", ticksuffix="  ")
    return fig


def _rows(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """finding dict → 차트용 평탄 레코드. 초과분 내림차순."""
    rows: list[dict[str, Any]] = []
    for item in findings or []:
        metrics = item.get("metrics") or {}
        ratio = metrics.get("round_ratio")
        baseline = metrics.get("baseline_ratio")
        if ratio is None or baseline is None:
            continue
        excess = metrics.get("excess")
        scope = str(item.get("scope") or "")
        group = str(item.get("group_key") or "")
        rows.append(
            {
                "scope": scope,
                "label": f"{scope_label(scope)} · {group}" if scope else group,
                "n": int(item.get("sample_size") or 0),
                "round_n": int(item.get("candidate_rows") or 0),
                "ratio": float(ratio),
                "baseline": float(baseline),
                "excess": float(excess) if excess is not None else float(ratio) - float(baseline),
                "p": float(metrics.get("p_value") or 0.0),
                "severity": SEVERITY_LABELS.get(
                    str(item.get("finding_severity") or ""),
                    str(item.get("finding_severity") or ""),
                ),
            }
        )
    rows.sort(key=lambda r: (-r["excess"], -r["n"]))
    return rows
