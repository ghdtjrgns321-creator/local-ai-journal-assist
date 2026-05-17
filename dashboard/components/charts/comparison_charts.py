"""전기 비교 차트 — 분석적 절차(ISA 520) flux analysis 시각화.

DuckDB SQL 집계 결과(소규모 DataFrame) 또는 카테고리 dict 를 받아 Plotly Figure 로
변환한다. 원본 raw 데이터를 Python 으로 적재하지 않는다 (메모리 폭발 방지).

설계 원칙:
  · 변동의 절대값과 증감률(%) 을 동시 표시
  · materiality 임계값(기본 10%) 초과 항목은 색으로 강조
  · K-IFRS 대분류(자산/부채/자본/매출/원가/판관비) 단위 분해
"""

from __future__ import annotations

import math
import unicodedata

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    RISK_COLORS,
    empty_figure,
)
from dashboard.components.coa_categories import (
    CATEGORY_ORDER,
    account_display,
)

# Why: 당기/전기 색상을 일관되게 적용.
_CURRENT_COLOR = "#2563EB"  # blue-600
_PRIOR_COLOR = "#B0BEC5"  # blue-gray-200
_DELTA_UP_COLOR = "#DC2626"  # red-600 — materiality 초과 증가
_DELTA_DOWN_COLOR = "#16A34A"  # green-600 — materiality 초과 감소
_DELTA_NEUTRAL = "#94A3B8"  # slate-400 — 임계값 이하


def _format_amount(value: float) -> str:
    """₩ 금액을 한국식(억/만) 축약."""
    v = float(value)
    sign = "-" if v < 0 else ""
    av = abs(v)
    if av >= 1_0000_0000:
        return f"{sign}{av / 1_0000_0000:,.2f}억"
    if av >= 1_0000:
        return f"{sign}{av / 1_0000:,.1f}만"
    return f"{sign}{av:,.0f}"


def _pct_change(current: float, prior: float) -> float | None:
    """전기 대비 변동률. 전기가 0 이면 None (∞ 방어).

    분모는 abs(prior) — NI 처럼 음수 base 에서 부호가 "방향(증감)" 의미를 잃지
    않도록 정규화. prior 가 음수이고 current 가 더 큰 (덜 부정적) 값이면 +%로
    표시되어 손실 감소를 시각적으로 올바르게 나타낸다.
    """
    if prior is None or math.isclose(prior, 0.0):
        return None
    return (current - prior) / abs(prior) * 100.0


def _visual_width(s: str) -> int:
    """문자열 시각 폭 (CJK=2, ASCII=1) — 한·영 혼합 라벨 정렬용."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _left_align_labels(labels: list[str]) -> list[str]:
    """가장 긴 라벨 폭에 맞춰 trailing space padding — monospace 폰트와 결합 시 좌측 정렬 효과."""
    target = max((_visual_width(s) for s in labels), default=0)
    return [s + " " * max(0, target - _visual_width(s)) for s in labels]


_TICK_FONT_MONO = {"size": 11, "family": "Consolas, 'D2Coding', monospace"}


# ── 1) 카테고리별 flux analysis (핵심) ─────────────────────────


def category_flux_bar(
    df: pd.DataFrame,
    *,
    materiality_pct: float = 10.0,
) -> go.Figure:
    """K-IFRS 대분류별 변동률(diverging variance) — audit analytical procedure 표준 시각화.

    설계: ISA 520 분석적 절차에서 1차 신호는 변동률(materiality 대비). 막대 길이=변동률
    이므로 임계 초과 카테고리가 즉시 눈에 들어온다. 절대 변동액·전기/당기 값은 hover
    및 우측 annotation 으로 보조 표시.

    범례 주의: BS(자산/부채/자본) 합계는 거래 활동량(기말 잔액 ≠), PL 중 매출/수익의
    "차변" 합계는 매출환입·할인 활동 흐름이라 본 매출 신호와 다름 — hover 에 명시.

    Args:
        df: columns = [category, current_amount, prior_amount]
        materiality_pct: 변동률 임계값(%) — 초과 시 빨강/초록 강조.
    """
    if df.empty:
        return empty_figure("카테고리별 거래 데이터 없음")

    order = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    df = df.copy()
    df["_order"] = df["category"].map(lambda c: order.get(c, 999))
    df = df.sort_values(by="_order")

    categories = df["category"].tolist()
    current_vals = df["current_amount"].tolist()
    prior_vals = df["prior_amount"].tolist()
    deltas = [c - p for c, p in zip(current_vals, prior_vals, strict=False)]
    raw_pcts = [_pct_change(c, p) for c, p in zip(current_vals, prior_vals, strict=False)]

    # Why: 전기=0(신규) 케이스는 시각적 길이를 임계×4 로 캡 — bar 자체는 표시하되
    #      "신규" 라벨로 구분, 무한대 확장 방지.
    cap = materiality_pct * 4
    bar_pcts: list[float] = []
    bar_colors: list[str] = []
    annotation_texts: list[str] = []
    is_new_flags: list[bool] = []
    is_other_flags: list[bool] = []
    for cat, delta, pct in zip(categories, deltas, raw_pcts, strict=False):
        is_other = cat in {"가/임시 계정", "미분류"}
        is_other_flags.append(is_other)
        if pct is None:
            sign = 1.0 if delta > 0 else -1.0 if delta < 0 else 0.0
            bar_pcts.append(sign * cap)
            bar_colors.append(_DELTA_NEUTRAL if delta == 0 else _DELTA_UP_COLOR)
            is_new_flags.append(True)
            annotation_texts.append(f"신규  Δ{_format_amount(delta)}")
        else:
            bar_pcts.append(pct)
            if is_other:
                color = _DELTA_NEUTRAL
            elif abs(pct) >= materiality_pct:
                color = _DELTA_UP_COLOR if pct > 0 else _DELTA_DOWN_COLOR
            else:
                color = _DELTA_NEUTRAL
            bar_colors.append(color)
            is_new_flags.append(False)
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "—"
            annotation_texts.append(f"{arrow} {abs(pct):.1f}%  Δ{_format_amount(delta)}")

    hover_texts = []
    for cat, cur, pri, delta, pct, is_other in zip(
        categories, current_vals, prior_vals, deltas, raw_pcts, is_other_flags, strict=False
    ):
        pct_str = "신규(전기 0)" if pct is None else f"{pct:+.1f}%"
        note = ""
        amount_label = "차변 합계"
        if cat == "당기순이익":
            amount_label = "NI"
            note = "<br><i>K-IFRS 손익 net = 매출(대변−차변) − 매출원가·판관비·영업외·법인세 (차변−대변)</i>"
        elif cat == "매출/수익":
            note = "<br><i>차변 합계 = 매출환입·할인 흐름 (본 매출은 대변)</i>"
        elif is_other:
            note = "<br><i>가/임시 계정은 큰 변동이 정상</i>"
        hover_texts.append(
            f"<b>{cat}</b><br>당기 {amount_label}: {cur:,.0f}원"
            f"<br>전기 {amount_label}: {pri:,.0f}원"
            f"<br>증감액: {delta:+,.0f}원 ({pct_str}){note}"
        )

    aligned_categories = _left_align_labels(categories)

    fig = go.Figure(
        go.Bar(
            x=bar_pcts,
            y=aligned_categories,
            orientation="h",
            marker_color=bar_colors,
            customdata=hover_texts,
            hovertemplate="%{customdata}<extra></extra>",
        )
    )

    annotations = []
    for cat, txt, bar_pct, is_new in zip(
        aligned_categories, annotation_texts, bar_pcts, is_new_flags, strict=False
    ):
        xanchor = "left" if bar_pct >= 0 else "right"
        x_offset = 1 if bar_pct >= 0 else -1
        annotations.append(
            {
                "x": bar_pct + x_offset,
                "y": cat,
                "text": ("<i>" + txt + "</i>") if is_new else txt,
                "showarrow": False,
                "font": {"size": 11, "color": "#111827"},
                "xanchor": xanchor,
            }
        )

    fig.update_layout(
        **{**DEFAULT_LAYOUT, "margin": {"l": 140, "r": 100, "t": 30, "b": 65}},
        height=max(280, 48 * len(categories) + 80),
        showlegend=False,
        annotations=annotations,
        shapes=[
            {
                "type": "line",
                "x0": materiality_pct,
                "x1": materiality_pct,
                "y0": -0.5,
                "y1": len(categories) - 0.5,
                "line": {"color": _DELTA_UP_COLOR, "width": 1, "dash": "dot"},
            },
            {
                "type": "line",
                "x0": -materiality_pct,
                "x1": -materiality_pct,
                "y0": -0.5,
                "y1": len(categories) - 0.5,
                "line": {"color": _DELTA_DOWN_COLOR, "width": 1, "dash": "dot"},
            },
        ],
    )
    fig.update_xaxes(
        title_text=f"전기 대비 변동률 (%, 점선 = ±{materiality_pct:.0f}% materiality)",
        title_standoff=18,
        ticksuffix="%",
        zeroline=True,
        zerolinecolor="#374151",
        zerolinewidth=1,
        gridcolor="rgba(226,229,233,0.5)",
    )
    # monospace + trailing space padding 으로 y 라벨 좌측 정렬 효과.
    fig.update_yaxes(
        autorange="reversed",
        tickfont={**_TICK_FONT_MONO, "color": "#111827"},
    )
    return fig


# ── 2) 변동 큰 계정 Top N (드릴다운) ───────────────────────────


def top_changed_accounts_bar(
    df: pd.DataFrame,
    *,
    top_n: int = 15,
    materiality_pct: float = 10.0,
) -> go.Figure:
    """변동액 절대값 Top N 계정 — 당기 vs 전기 그룹 막대.

    Args:
        df: columns = [gl_account, current_amount, prior_amount]
    """
    if df.empty:
        return empty_figure("계정 변동 데이터 없음")

    work = df.copy()
    work["delta"] = work["current_amount"] - work["prior_amount"]
    work["pct"] = work.apply(lambda r: _pct_change(r["current_amount"], r["prior_amount"]), axis=1)
    work["abs_delta"] = work["delta"].abs()
    work = work.nlargest(top_n, "abs_delta")
    work = work.sort_values(by="delta")  # 작은 감소 → 큰 증가 순서로 표시

    labels = [account_display(a) for a in work["gl_account"]]
    aligned_labels = _left_align_labels(labels)
    colors = []
    for pct, delta in zip(work["pct"], work["delta"], strict=False):
        if pct is None:
            colors.append(_DELTA_UP_COLOR if delta > 0 else _DELTA_NEUTRAL)
        elif abs(pct) >= materiality_pct:
            colors.append(_DELTA_UP_COLOR if delta > 0 else _DELTA_DOWN_COLOR)
        else:
            colors.append(_DELTA_NEUTRAL)

    hover_texts = []
    for cur, pri, delta, pct in zip(
        work["current_amount"], work["prior_amount"], work["delta"], work["pct"], strict=False
    ):
        pct_str = "신규" if pct is None else f"{pct:+.1f}%"
        hover_texts.append(
            f"당기: {cur:,.0f}원<br>전기: {pri:,.0f}원<br>증감: {delta:+,.0f}원 ({pct_str})"
        )

    fig = go.Figure(
        go.Bar(
            x=work["delta"],
            y=aligned_labels,
            orientation="h",
            marker_color=colors,
            text=[_format_amount(d) for d in work["delta"]],
            textposition="outside",
            textfont={"size": 10},
            customdata=hover_texts,
            hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        **{**DEFAULT_LAYOUT, "margin": {"l": 220, "r": 60, "t": 20, "b": 40}},
        height=max(320, 30 * len(labels) + 60),
        showlegend=False,
    )
    fig.update_xaxes(
        title_text="당기 - 전기 (₩)",
        tickformat=",.0f",
        gridcolor="rgba(226,229,233,0.5)",
        zeroline=True,
        zerolinecolor="#374151",
    )
    fig.update_yaxes(tickfont={**_TICK_FONT_MONO, "color": "#111827"})
    return fig


# ── 3) 월별 추세 비교 ──────────────────────────────────────────


def monthly_trend_comparison(
    df: pd.DataFrame,
    *,
    value_col: str = "row_count",
) -> go.Figure:
    """월별 거래 건수/금액 — 당기 vs 전기 라인 차트.

    Args:
        df: columns = [period, month, row_count, total_amount]
            period = "current" 또는 "prior", month = 1..12
    """
    if df.empty:
        return empty_figure("월별 추세 데이터 없음")

    title_text = {
        "row_count": "월별 전표 건수",
        "total_amount": "월별 거래 금액",
        "net_sales": "월별 순매출 (대변 - 차변)",
    }.get(value_col, value_col)
    is_amount = value_col in ("total_amount", "net_sales")

    fig = go.Figure()
    for period, name, color in [
        ("prior", "전기", _PRIOR_COLOR),
        ("current", "당기", _CURRENT_COLOR),
    ]:
        sub = df[df["period"] == period].sort_values(by="month")
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["month"],
                y=sub[value_col],
                mode="lines+markers",
                name=name,
                line={"color": color, "width": 2.5, "shape": "spline", "smoothing": 0.3},
                marker={"size": 8, "color": color},
                hovertemplate=(
                    f"{name} %{{x}}월: %{{y:,.0f}}"
                    + ("원" if is_amount else "건")
                    + "<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        **{**DEFAULT_LAYOUT, "margin": {"l": 50, "r": 20, "t": 30, "b": 40}},
        height=300,
        title=None,
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "x": 0.0},
    )
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(1, 13)),
        ticktext=[f"{m}월" for m in range(1, 13)],
        title_text=None,
        gridcolor="rgba(226,229,233,0.5)",
    )
    fig.update_yaxes(
        title_text=title_text,
        tickformat=",.0f",
        gridcolor="rgba(226,229,233,0.5)",
        rangemode="tozero",
    )
    return fig


# ── 4) 위험등급 분포 비교 (도넛) ───────────────────────────────


def risk_distribution_comparison(
    current_df: pd.DataFrame,
    prior_df: pd.DataFrame,
) -> go.Figure:
    """위험등급 분포 비교 — 도넛 2개 나란히.

    Args:
        current_df: columns=[risk_level, cnt]
        prior_df: columns=[risk_level, cnt]
    """
    if current_df.empty and prior_df.empty:
        return empty_figure("위험등급 데이터 없음")

    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "pie"}, {"type": "pie"}]],
        subplot_titles=["당기", "전기"],
    )
    for col_idx, (df, name) in enumerate([(current_df, "당기"), (prior_df, "전기")], 1):
        if df.empty:
            continue
        colors = [RISK_COLORS.get(r, "#999") for r in df["risk_level"]]
        fig.add_trace(
            go.Pie(
                labels=df["risk_level"],
                values=df["cnt"],
                hole=0.5,
                marker={"colors": colors},
                name=name,
                textinfo="label+percent",
                hovertemplate="%{label}: %{value:,}건 (%{percent})<extra></extra>",
            ),
            row=1,
            col=col_idx,
        )
    fig.update_layout(**DEFAULT_LAYOUT, height=320, showlegend=False)
    return fig


# ── 5) 룰별 위반 증감 ──────────────────────────────────────────


def rule_violation_delta(
    current_df: pd.DataFrame,
    prior_df: pd.DataFrame,
) -> go.Figure:
    """룰별 위반 건수 증감 — 수평 바 차트.

    Args:
        current_df: columns=[rule_code, cnt]
        prior_df: columns=[rule_code, cnt]

    Y축 라벨은 `{rule_code} · {한국어 이름}` 형식 (rule_labels.RULE_NAMES_KR).
    """
    if current_df.empty and prior_df.empty:
        return empty_figure("룰 위반 데이터 없음")

    from dashboard.components.rule_labels import rule_label

    merged = pd.merge(
        current_df.rename(columns={"cnt": "당기"}),
        prior_df.rename(columns={"cnt": "전기"}),
        on="rule_code",
        how="outer",
    ).fillna(0)
    merged["증감"] = merged["당기"] - merged["전기"]
    # Why: 변동 없는 룰은 제거 — 신호가 약해진다.
    merged = merged[merged["증감"] != 0].sort_values(by="증감")
    if merged.empty:
        return empty_figure("룰 위반 변동 없음")

    merged["rule_label"] = merged["rule_code"].astype(str).map(lambda r: rule_label(r))
    aligned_labels = _left_align_labels(merged["rule_label"].astype(str).tolist())

    colors = [_DELTA_UP_COLOR if v > 0 else _DELTA_DOWN_COLOR for v in merged["증감"]]
    fig = go.Figure(
        go.Bar(
            x=merged["증감"],
            y=aligned_labels,
            orientation="h",
            marker_color=colors,
            text=[f"{int(v):+,}" for v in merged["증감"]],
            textposition="outside",
            customdata=list(zip(merged["당기"], merged["전기"], strict=False)),
            hovertemplate=(
                "<b>%{y}</b><br>당기: %{customdata[0]:,.0f}건"
                "<br>전기: %{customdata[1]:,.0f}건<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **{**DEFAULT_LAYOUT, "margin": {"l": 200, "r": 70, "t": 20, "b": 40}},
        height=max(280, 28 * len(merged) + 60),
        showlegend=False,
    )
    fig.update_xaxes(
        title_text="당기 - 전기 (건)",
        gridcolor="rgba(226,229,233,0.5)",
        zeroline=True,
        zerolinecolor="#374151",
    )
    # Why: monospace family + trailing space padding 으로 좌측 정렬 효과.
    fig.update_yaxes(tickfont=_TICK_FONT_MONO)
    return fig


# ── 6) 신규/소멸 계정 테이블 ───────────────────────────────────


def changed_accounts_table(
    current_accounts: set[str],
    prior_accounts: set[str],
) -> pd.DataFrame:
    """신규/소멸 계정과목 목록 — 한국어 계정명 동반 DataFrame.

    Returns:
        columns = [구분, 계정코드, 계정명] — 신규(당기에만) · 소멸(전기에만)
    """
    new = sorted(current_accounts - prior_accounts)
    removed = sorted(prior_accounts - current_accounts)
    rows: list[dict[str, str]] = []
    for code in new:
        rows.append({"구분": "신규", "계정코드": code, "계정명": _name_only(code) or "(매핑 없음)"})
    for code in removed:
        rows.append({"구분": "소멸", "계정코드": code, "계정명": _name_only(code) or "(매핑 없음)"})
    if not rows:
        return pd.DataFrame(columns=["구분", "계정코드", "계정명"])
    return pd.DataFrame(rows)


def _name_only(code: str) -> str:
    """account_display 에서 코드 뒤 한국어 부분만 추출."""
    full = account_display(code)
    if not full or full == code:
        return ""
    return full[len(code) + 1 :]


# ── 하위 호환 — 기존 단순 막대 (다른 모듈에서 import 할 수 있어 보존) ─


def yoy_count_bar(current: int, prior: int) -> go.Figure:
    """건수 YoY 비교 — 단순 수평 바 2개 (legacy)."""
    if current == 0 and prior == 0:
        return empty_figure("비교 데이터 없음")
    fig = go.Figure(
        [
            go.Bar(
                name="전기", x=[prior], y=["전표 건수"], orientation="h", marker_color=_PRIOR_COLOR
            ),
            go.Bar(
                name="당기",
                x=[current],
                y=["전표 건수"],
                orientation="h",
                marker_color=_CURRENT_COLOR,
            ),
        ]
    )
    fig.update_layout(**DEFAULT_LAYOUT, title="건수 비교", barmode="group", height=200)
    return fig


def yoy_amount_bar(current_amt: float, prior_amt: float) -> go.Figure:
    """금액 YoY 비교 — 단순 수평 바 2개 (legacy)."""
    if current_amt == 0 and prior_amt == 0:
        return empty_figure("비교 데이터 없음")
    fig = go.Figure(
        [
            go.Bar(
                name="전기",
                x=[prior_amt],
                y=["총 차변 금액"],
                orientation="h",
                marker_color=_PRIOR_COLOR,
            ),
            go.Bar(
                name="당기",
                x=[current_amt],
                y=["총 차변 금액"],
                orientation="h",
                marker_color=_CURRENT_COLOR,
            ),
        ]
    )
    fig.update_layout(**DEFAULT_LAYOUT, title="금액 비교", barmode="group", height=200)
    return fig


def new_accounts_table(
    current_accounts: set[str],
    prior_accounts: set[str],
) -> pd.DataFrame:
    """legacy 호환 — 새 함수는 changed_accounts_table 사용."""
    new = current_accounts - prior_accounts
    removed = prior_accounts - current_accounts
    rows = [{"계정코드": a, "구분": "신규"} for a in sorted(new)]
    rows += [{"계정코드": a, "구분": "제거"} for a in sorted(removed)]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["계정코드", "구분"])
