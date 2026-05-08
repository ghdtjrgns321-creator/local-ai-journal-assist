"""개요 탭 — 분석 전(Before) / 분석 후(After) 2단계 변신.

Before: 기본 정보 KPI + 대형 CTA "전체 감사 파이프라인 가동"
After : 위험 KPI + LLM 배치 요약 + Top 5 고위험 전표 + 기존 차트
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._kpi import compute_kpis
from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_COMPANY_CONTEXT,
    KEY_FILTERS,
    KEY_PENDING_RESULT_TAB,
    KEY_TOP_LEVEL_NAV,
    PAGE_COMPANY_SETTINGS,
    PAGE_PHASE1,
    PAGE_PHASE2,
)
from dashboard.components.charts import (
    benford_overlay,
    monthly_trend,
    risk_donut,
    rule_violation_bar,
)
from dashboard.components.filters import apply_filters
from src.metrics.models import PerformanceReport, RuleMetric
from src.services.session_service import has_analysis_output

if TYPE_CHECKING:
    from src.pipeline import PipelineResult


_BATCH_INSIGHT_KEY = "_overview_batch_insight"


@st.cache_data(show_spinner=False)
def _cached_kpis(df: pd.DataFrame) -> dict:
    return compute_kpis(df)


# ── 공용 포매터 ──────────────────────────────────────────────


def _fmt_amount(value: float) -> str:
    """금액을 한국식 축약 (조·억·만)."""
    v = float(value)
    if abs(v) >= 1_0000_0000_0000:
        return f"{v / 1_0000_0000_0000:,.2f}조"
    if abs(v) >= 1_0000_0000:
        return f"{v / 1_0000_0000:,.2f}억"
    if abs(v) >= 1_0000:
        return f"{v / 1_0000:,.1f}만"
    return f"{v:,.0f}"


def _period_range(df: pd.DataFrame) -> str:
    """posting_date 범위를 'YYYY-MM-DD ~ YYYY-MM-DD' 또는 연월로 표시."""
    if "posting_date" not in df.columns:
        return "—"
    series = pd.to_datetime(df["posting_date"], errors="coerce").dropna()
    if series.empty:
        return "—"
    start = series.min().strftime("%Y-%m-%d")
    end = series.max().strftime("%Y-%m-%d")
    return f"{start} ~ {end}"


# ── 엔트리 ────────────────────────────────────────────────


def render(result: PipelineResult) -> None:
    """개요 탭 엔트리 — 분석 결과 유무에 따라 Before/After 자동 분기."""
    if has_analysis_output(result):
        _render_after(result)
    else:
        _render_before(result)


def render_pre_analysis(result: PipelineResult) -> None:
    """분석 결과와 분리해 개요 탭은 항상 실행 전 화면으로 유지."""
    _render_before(result)


def render_analysis_result(result: PipelineResult) -> None:
    """Phase 결과 탭에서 분석 후 화면만 렌더링."""
    _render_after(result)


# ── Before — 분석 전 ───────────────────────────────────────


def _render_before(result: PipelineResult) -> None:
    """분석 전 — Row1 KPI 3카드 / Row2 차트 2카드 → 품질 진단 → Phase 브리핑 → CTA."""
    df = result.data

    st.subheader("데이터 개요")
    st.caption("회사의 비즈니스 성격과 데이터 건전성을 한눈에 보여주는 지표입니다.")

    period = _period_range(df)
    total_docs = (
        int(df["document_id"].nunique()) if "document_id" in df.columns else len(df)
    )
    total_debit = (
        float(df["debit_amount"].sum()) if "debit_amount" in df.columns else 0.0
    )

    # Row 1: KPI 3개 카드 (균등 폭, 균등 높이)
    c1, c2, c3 = st.columns(3, gap="small")
    with c1:
        _render_kpi_card("분석 기간", period)
    with c2:
        _render_kpi_card("총 전표 수", f"{total_docs:,}", unit="건")
    with c3:
        _render_kpi_card("총 거래 금액", _fmt_amount(total_debit))

    # Row 2: 차트 2개 카드 — 꺾은선(시계열)은 가로로 넓어야 자연스러워 1 : 1.5
    # Why: 도넛은 outside 라벨이 차트 밖으로 나오고 꺾은선은 상단 값 라벨 + 하단 footer
    #      caption까지 합산하면 305px로는 부족해 컨테이너에 스크롤바가 생긴다.
    #      카드 380, plotly 도넛 280 / 라인 280으로 헤더+차트+caption 합산이 카드 높이 안에
    #      맞도록 조정.
    c_types, c_monthly = st.columns([1, 1.5], gap="small")
    with c_types:
        with st.container(border=True, height=380):
            _render_document_type_donut(df)
    with c_monthly:
        with st.container(border=True, height=380):
            _render_monthly_trend_line(df)

    st.divider()

    _render_quality_checklist(df)

    st.divider()

    _render_pipeline_briefing()

    _render_pipeline_cta()


# ── KPI 카드 ──────────────────────────────────────────────


def _render_kpi_card(label: str, value: str, unit: str | None = None) -> None:
    """단일 KPI 카드 — container 고정 높이 + 내부 100% flex center.

    Why: container 높이가 content에 의해 결정되면 Streamlit wrapper의 비대칭
         padding 때문에 flex center가 실제 카드 중앙으로 오지 않는다.
         `st.container(height=...)`로 카드 높이를 고정하고, 내부 div를 `height:100%`로
         꽉 채운 뒤 flex center를 적용하면 실제 정중앙에 온다.
    """
    unit_html = ""
    if unit:
        unit_html = (
            f"<span style='font-size:0.9rem; font-weight:500; color:#6B7280; "
            f"margin-left:3px;'>{unit}</span>"
        )

    html = (
        "<div class='tab-overview-scoped' style='height:100%; display:flex; "
        "flex-direction:column; justify-content:center; align-items:center; "
        "text-align:center;'>"
        f"<div style='color:#6B7280; font-size:0.82rem; line-height:1.2; "
        f"margin:0 0 0.3rem;'>{label}</div>"
        f"<div style='color:#111827; font-size:1.5rem; font-weight:700; "
        f"letter-spacing:-0.025em; line-height:1.15; margin:0;'>"
        f"{value}{unit_html}</div>"
        "</div>"
    )
    # Why: height=70로 상하폭 슬림 + overflow 방지.
    with st.container(border=True, height=70):
        st.markdown(html, unsafe_allow_html=True)


# ── 우: 주요 거래 유형 가로 바 차트 ────────────────────────


_DOCUMENT_TYPE_NAMES = {
    "SA": "일반분개 (수기 조정)",
    "DR": "매출채권",
    "KR": "매입채무",
    "KZ": "대금지급",
    "DZ": "대금수금",
    "WE": "자재입고",
    "AA": "고정자산",
    "HR": "인건비",
    "IC": "관계사거래",
}


def _render_document_type_donut(df: pd.DataFrame) -> None:
    """주요 거래 유형 Top 4 + 기타 — Plotly 도넛."""
    if "document_type" not in df.columns:
        st.caption("document_type 컬럼이 없어 거래 유형 분포를 그릴 수 없습니다.")
        return

    counts = df["document_type"].dropna().value_counts()
    if counts.empty:
        st.caption("거래 유형 정보가 비어 있습니다.")
        return

    top = counts.head(4)
    others = int(counts.iloc[4:].sum()) if len(counts) > 4 else 0

    labels: list[str] = []
    values: list[int] = []
    for code, cnt in top.items():
        name = _DOCUMENT_TYPE_NAMES.get(str(code), "기타")
        labels.append(f"{code} {name}")
        values.append(int(cnt))
    if others > 0:
        labels.append("기타")
        values.append(others)

    import plotly.graph_objects as go

    # Why: 슬레이트 팔레트로 일관성 유지. 5단계 명도 그라데이션.
    colors = ["#111827", "#374151", "#6B7280", "#9CA3AF", "#D1D5DB"]

    # 캡션 계산 — SA 비율 기반 자동 생성
    total_v = sum(values)
    sa_pct = 0.0
    for label, cnt in zip(labels, values):
        if label.startswith("SA "):
            sa_pct = cnt / total_v * 100 if total_v else 0.0
            break

    if sa_pct >= 40:
        caption = (
            f"SA 일반분개 {sa_pct:.0f}% · 수기 조정 전표 비중 높음"
        )
    elif sa_pct >= 20:
        caption = (
            f"SA 일반분개 {sa_pct:.0f}% · 수기 조정 전표 비중 평균 수준"
        )
    else:
        caption = (
            f"SA 일반분개 {sa_pct:.0f}% · 자동화 수준 양호"
        )

    # 헤더: 제목만 (꺾은선과 동일하게 캡션은 차트 아래로)
    st.markdown(
        "<div class='tab-overview-scoped' style='padding:0.55rem 0.75rem 0.3rem;'>"
        "<div style='color:#111827; font-size:0.95rem; font-weight:600;'>"
        "주요 거래 유형</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=colors[: len(labels)], line=dict(color="#FFFFFF", width=2)),
            textinfo="label+percent",
            textposition="outside",
            textfont=dict(color="#111827", size=11),
            hovertemplate="%{label}: %{value:,}건 (%{percent})<extra></extra>",
            sort=False,
            # Why: domain으로 도넛 중앙 영역을 확보해 outside 라벨이 잘리지 않게.
            domain=dict(x=[0.12, 0.88], y=[0.05, 0.95]),
            automargin=True,
        )
    )
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=4, b=4),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
        key="overview_before_document_type_donut",
    )

    # 차트 아래 캡션 — 꺾은선의 footer와 동일 패턴
    st.markdown(
        "<div class='tab-overview-scoped' style='color:#6B7280; "
        f"font-size:0.75rem; text-align:center; padding:0 0.75rem 0.5rem;'>"
        f"{caption}</div>",
        unsafe_allow_html=True,
    )


def _render_monthly_trend_line(df: pd.DataFrame) -> None:
    """월별 전표 추이 — Plotly 꺾은선 + 값 라벨."""
    if "posting_date" not in df.columns:
        st.caption("posting_date 컬럼이 없어 월별 추이를 그릴 수 없습니다.")
        return

    if "document_id" in df.columns:
        doc_dates = df.drop_duplicates("document_id")["posting_date"]
    else:
        doc_dates = df["posting_date"]

    dt = pd.to_datetime(doc_dates, errors="coerce").dropna()
    if dt.empty:
        st.caption("유효한 기표일이 없습니다.")
        return

    monthly = dt.dt.month.value_counts().sort_index()
    full = {m: int(monthly.get(m, 0)) for m in range(1, 13)}
    x = list(full.keys())
    y = list(full.values())

    import plotly.graph_objects as go

    fig = go.Figure(
        go.Scatter(
            x=x,
            y=y,
            mode="lines+markers+text",
            line=dict(color="#374151", width=2.5, shape="spline", smoothing=0.3),
            marker=dict(size=7, color="#111827"),
            text=[f"{v:,}" for v in y],
            textposition="top center",
            textfont=dict(color="#111827", size=10),
            hovertemplate="%{x}월: %{y:,}건<extra></extra>",
        )
    )
    peak = max(full, key=lambda m: full[m])
    peak_cnt = full[peak]
    footer_caption = f"최다월 {peak}월 · {peak_cnt:,}건"

    # 헤더: 제목만 (꺾은선은 원래대로 — 최다월 캡션은 차트 아래로)
    st.markdown(
        "<div class='tab-overview-scoped' style='padding:0.55rem 0.75rem 0.3rem;'>"
        "<div style='color:#111827; font-size:0.95rem; font-weight:600;'>"
        "월별 전표 추이</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    fig.update_layout(
        height=280,
        margin=dict(l=8, r=8, t=6, b=24),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(1, 13)),
            ticktext=[f"{m}월" for m in range(1, 13)],
            showgrid=False,
            tickfont=dict(color="#6B7280", size=11),
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#F1F3F5",
            tickfont=dict(color="#6B7280", size=10),
            rangemode="tozero",
            zeroline=False,
            automargin=True,
        ),
        showlegend=False,
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
        key="overview_before_monthly_trend_line",
    )

    # 하단 최다월 footer
    st.markdown(
        "<div class='tab-overview-scoped' style='color:#6B7280; "
        f"font-size:0.75rem; text-align:center; padding:0 0.75rem 0.5rem;'>"
        f"{footer_caption}</div>",
        unsafe_allow_html=True,
    )


# ── 품질 진단 체크리스트 ────────────────────────────────────


_STATUS_ICON = {"ok": "✅", "warn": "🟡", "err": "⚠️"}


def _render_quality_checklist(df: pd.DataFrame) -> None:
    """Phase 실행 전 즉시 확인 가능한 품질 지표를 2 카테고리 체크리스트로 표시."""
    st.markdown(
        "<div style='color:#111827; font-size:1.05rem; font-weight:600; "
        "margin-bottom:0.25rem;'>품질 진단</div>"
        "<div style='color:#6B7280; font-size:0.85rem; margin-bottom:0.25rem;'>"
        "Phase 실행 전 감사 대상 데이터의 무결성·정합성을 1차 점검한 결과입니다.</div>"
        "<div style='color:#6B7280; font-size:0.8rem; margin-bottom:1rem;'>"
        "✅ 정상 · 🟡 검토 권장 · ⚠️ 통제 취약</div>",
        unsafe_allow_html=True,
    )

    structure = [
        _check_master_data(df),
        _check_manual_je(df),
        _check_self_approval(df),
        _check_date_consistency(df),
    ]
    accounting = [
        _check_trial_balance(df),
        _check_benford(df),
        _check_timing(df),
        _check_period_end_concentration(df),
    ]

    # Why: 카드 height를 None(auto)로 두면 content에 맞춰 상하 padding이 대칭 유지.
    #      두 카테고리 모두 4항목이라 자연히 같은 높이가 된다.
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            _render_checklist_card("데이터 구조 및 무결성", structure)
    with c2:
        with st.container(border=True):
            _render_checklist_card("회계 및 통계 정합성", accounting)


def _render_checklist_card(
    title: str, items: list[tuple[str, str, str] | None],
) -> None:
    """카테고리 제목 + 체크 항목. padding 상하 대칭으로 여백 일관."""
    parts: list[str] = [
        "<div class='tab-overview-scoped' style='padding:0.75rem 1.2rem;'>",
        f"<div style='color:#111827; font-weight:600; font-size:1.05rem; "
        f"margin:0 0 0.55rem;'>{title}</div>",
    ]
    rendered = 0
    for item in items:
        if item is None:
            continue
        status, label, detail = item
        icon = _STATUS_ICON.get(status, "•")
        parts.append(
            "<div style='margin:0.3rem 0; font-size:0.95rem; line-height:1.5;'>"
            f"<span style='margin-right:0.5rem; font-size:1rem;'>{icon}</span>"
            f"<span style='color:#111827; font-weight:500;'>{label}</span>"
            f"<span style='color:#6B7280;'>: {detail}</span>"
            "</div>"
        )
        rendered += 1
    if rendered == 0:
        parts.append(
            "<div style='color:#9CA3AF; font-size:0.82rem;'>"
            "해당 카테고리의 검증 항목을 수행할 수 없습니다.</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# 개별 체크 함수들 — (status, label, detail) or None


def _check_self_approval(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """자기승인 거래 — 작성자와 승인자가 동일한 전표 비율.

    감사 시사점: SoD(ISA 315) 위반 사전 스크리닝. B06/B07 룰의 직접 선행 지표.
    """
    if "created_by" not in df.columns or "approved_by" not in df.columns:
        return None

    # 문서 단위로 대조 — 같은 전표의 여러 라인이 중복 집계되지 않도록
    if "document_id" in df.columns:
        subset = (
            df.groupby("document_id")
            .agg(created_by=("created_by", "first"), approved_by=("approved_by", "first"))
            .dropna()
        )
    else:
        subset = df[["created_by", "approved_by"]].dropna()

    if subset.empty:
        return None

    self_approved = int((subset["created_by"] == subset["approved_by"]).sum())
    total = len(subset)
    rate = self_approved / total * 100

    if self_approved == 0:
        return "ok", "자기승인 거래", "0건 (정상)"
    if rate < 1.0:
        return "warn", "자기승인 거래", f"{self_approved:,}건 ({rate:.2f}%) 검토 권장"
    return "err", "자기승인 거래", f"{self_approved:,}건 ({rate:.1f}%) 통제 취약"


def _check_date_consistency(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """posting_date의 월(month)과 fiscal_period 일치 여부.

    감사 시사점: 기간귀속 오류(Cutoff) 사전 감지. 회계기간과 실제 기표일이 다른 전표는
    결산조정·기간귀속 검증 대상으로 플래그해야 한다.
    """
    if "posting_date" not in df.columns or "fiscal_period" not in df.columns:
        return None

    dt = pd.to_datetime(df["posting_date"], errors="coerce")
    period = pd.to_numeric(df["fiscal_period"], errors="coerce")

    valid = dt.notna() & period.notna()
    if not valid.any():
        return None

    months = dt[valid].dt.month
    periods = period[valid].astype(int)
    mismatches = int((months != periods).sum())
    total = int(valid.sum())

    if mismatches == 0:
        return "ok", "날짜 일관성", f"100% 일치 ({total:,}건)"

    # Why: floor로 반올림해 불일치가 있을 때 절대 100%로 표기되지 않도록.
    rate = math.floor((total - mismatches) / total * 10000) / 100
    if mismatches / total < 0.005:
        return "warn", "날짜 일관성", f"{rate:.2f}% 일치 · 불일치 {mismatches:,}건"
    return "err", "날짜 일관성", f"{rate:.1f}% 일치 · 불일치 {mismatches:,}건"


def _check_master_data(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """마스터 데이터(Entity) 복잡도 — 계정·사용자·거래처·코스트센터 차원 집계."""
    dims: list[str] = []
    if "gl_account" in df.columns:
        n = int(df["gl_account"].dropna().nunique())
        if n > 0:
            dims.append(f"활성 계정 {n:,}개")
    if "created_by" in df.columns:
        n = int(df["created_by"].dropna().nunique())
        if n > 0:
            dims.append(f"기표 사용자 {n:,}명")
    if "trading_partner" in df.columns:
        n = int(df["trading_partner"].dropna().nunique())
        if n > 0:
            dims.append(f"거래처 {n:,}곳")
    if "cost_center" in df.columns:
        n = int(df["cost_center"].dropna().nunique())
        if n > 0:
            dims.append(f"코스트센터 {n:,}개")

    if not dims:
        return "warn", "마스터 데이터 복잡도", "엔티티 컬럼 없음"
    # Why: 너무 많으면 한 줄이 길어지니 상위 3개만 노출
    return "ok", "마스터 데이터 복잡도", " · ".join(dims[:3])


def _check_manual_je(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """수기 전표(Manual Journal Entry) 비율 — source 또는 user_persona 기반."""
    manual_rate: float | None = None

    if "source" in df.columns:
        s = df["source"].dropna().astype(str).str.lower()
        if not s.empty:
            manual = int(s.str.contains("manual", na=False).sum())
            manual_rate = manual / len(s) * 100
    elif "user_persona" in df.columns:
        s = df["user_persona"].dropna().astype(str).str.lower()
        if not s.empty:
            automated = int(s.str.contains("automated", na=False).sum())
            manual_rate = (1 - automated / len(s)) * 100

    if manual_rate is None:
        return None

    if manual_rate < 10:
        return "ok", "수기 전표 비율", f"{manual_rate:.1f}% (자동화율 양호)"
    if manual_rate < 30:
        return "warn", "수기 전표 비율", f"{manual_rate:.1f}% (검토 권장)"
    return "err", "수기 전표 비율", f"{manual_rate:.1f}% (통제 취약)"


def _check_trial_balance(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """문서 단위 차대변 대사."""
    if "document_id" not in df.columns:
        return None
    if "debit_amount" not in df.columns or "credit_amount" not in df.columns:
        return None

    grouped = df.groupby("document_id")[["debit_amount", "credit_amount"]].sum()
    if grouped.empty:
        return None

    diff = (grouped["debit_amount"] - grouped["credit_amount"]).abs()
    unbalanced = int((diff > 1.0).sum())  # 1원 이하 반올림 오차는 무시
    total = len(grouped)

    if unbalanced == 0:
        return "ok", "차대변 대사", f"100% 일치 ({total:,}건)"

    # Why: 불일치가 1건이라도 있으면 100%로 반올림되지 않도록 floor 적용.
    rate = math.floor((total - unbalanced) / total * 10000) / 100
    level = "warn" if unbalanced / max(total, 1) < 0.01 else "err"
    return level, "차대변 대사", f"{rate:.2f}% 일치 · 불균형 {unbalanced:,}건"


def _check_benford(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """Benford 첫째자리 분포 판정."""
    if "debit_amount" not in df.columns:
        return None
    amounts = df["debit_amount"].dropna()
    amounts = amounts[amounts > 0]
    if len(amounts) < 100:
        return "warn", "벤포드 법칙", f"표본 부족 ({len(amounts):,}건)"

    # Why: 과학적 표기법 · 선행 0 방어
    first_str = amounts.abs().astype(str).str.lstrip("0.").str[:1]
    first = pd.to_numeric(first_str, errors="coerce").dropna().astype(int)
    first = first[(first >= 1) & (first <= 9)]
    if len(first) < 100:
        return "warn", "벤포드 법칙", "유효 표본 부족"

    try:
        from config.settings import get_settings
        from src.validation.benford import analyze_benford

        settings = get_settings()
        br, _ = analyze_benford(first, settings=settings)
    except Exception:
        return "warn", "벤포드 법칙", "분석 실패"

    if br.mad is None:
        return "warn", "벤포드 법칙", "분석 실패"

    mad_str = f"MAD {br.mad:.4f}"
    if br.mad_conformity in ("close", "acceptable"):
        return "ok", "벤포드 법칙 (자릿수 분포)", f"정상 ({mad_str})"
    if br.mad_conformity == "marginally":
        return "warn", "벤포드 법칙 (자릿수 분포)", f"경계 ({mad_str})"
    return "err", "벤포드 법칙 (자릿수 분포)", f"부적합 ({mad_str})"


def _check_timing(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """posting_date의 심야/주말 비율."""
    if "posting_date" not in df.columns:
        return None
    dt = pd.to_datetime(df["posting_date"], errors="coerce").dropna()
    if dt.empty:
        return None

    hour = dt.dt.hour
    dow = dt.dt.dayofweek
    total = len(dt)
    weekend_rate = (dow >= 5).sum() / total * 100

    # Why: 시간 정보가 모두 00:00 이면 심야 판정 의미 없음 → 주말만 체크
    if hour.nunique() <= 1:
        if weekend_rate > 15:
            return "warn", "시간대 분포", f"주말 기표 {weekend_rate:.1f}% 감지"
        return "ok", "시간대 분포", f"주말 기표 {weekend_rate:.1f}%"

    night_rate = ((hour >= 22) | (hour < 6)).sum() / total * 100
    if night_rate > 5 or weekend_rate > 15:
        return (
            "warn",
            "시간대 분포",
            f"심야 {night_rate:.1f}% · 주말 {weekend_rate:.1f}% 감지",
        )
    return (
        "ok",
        "시간대 분포",
        f"심야 {night_rate:.1f}% · 주말 {weekend_rate:.1f}%",
    )


def _check_period_end_concentration(df: pd.DataFrame) -> tuple[str, str, str] | None:
    """기말(12월·마지막 5일) 기표 집중도.

    감사 시사점: Cutoff 검증(ISA 545) · 결산조정·이익조정 집중 의심의 사전 지표.
    """
    if "posting_date" not in df.columns:
        return None

    # 문서 단위로 중복 제거 (라인 여러 개인 전표의 편향 제거)
    if "document_id" in df.columns:
        dates = (
            df.groupby("document_id")["posting_date"]
            .first()
            .pipe(pd.to_datetime, errors="coerce")
            .dropna()
        )
    else:
        dates = pd.to_datetime(df["posting_date"], errors="coerce").dropna()

    total = len(dates)
    if total == 0:
        return None

    dec_rate = (dates.dt.month == 12).sum() / total * 100
    last5_rate = (
        (dates.dt.month == 12) & (dates.dt.day >= 27)
    ).sum() / total * 100

    # 월별 균등 가정 시 12월 평균 8.3% — 15% 초과 시 집중, 25% 초과 시 심각
    if dec_rate < 15:
        return (
            "ok",
            "기말 집중도",
            f"12월 {dec_rate:.1f}% · 마지막 5일 {last5_rate:.1f}%",
        )
    if dec_rate < 25:
        return (
            "warn",
            "기말 집중도",
            f"12월 {dec_rate:.1f}% · 마지막 5일 {last5_rate:.1f}% (검토 권장)",
        )
    return (
        "err",
        "기말 집중도",
        f"12월 {dec_rate:.1f}% · 마지막 5일 {last5_rate:.1f}% (결산조정 집중)",
    )


# ── 파이프라인 브리핑 ──────────────────────────────────────


def _render_pipeline_briefing() -> None:
    """3단계 파이프라인을 간결한 카드로 예고."""
    st.markdown(
        "<div style='color:#111827; font-size:1.05rem; font-weight:600; "
        "margin-bottom:0.25rem;'>AI 감사 파이프라인 가동 대기</div>"
        "<div style='color:#6B7280; font-size:0.85rem; margin-bottom:1rem;'>"
        "실행 시 아래 세 단계가 순차적으로 진행됩니다.</div>",
        unsafe_allow_html=True,
    )

    cards = [
        (
            "Phase 1",
            "룰 기반 감사",
            "K-IFRS 24개 부정 시나리오",
            "자기승인·중복지급 등 명백한 룰 위반 전표를 1차 스캐닝합니다.",
        ),
        (
            "Phase 2",
            "ML 이상 탐지",
            "Isolation Forest · VAE · XGBoost",
            "감사인이 놓치기 쉬운 비선형·우회적 이상 패턴을 식별합니다.",
        ),
        (
            "Phase 3",
            "LLM 위험 요약",
            "적요·그래프 분석 + 자연어 요약",
            "식별된 위험 요소를 종합하여 설명하고, 위험 사유서를 생성합니다.",
        ),
    ]

    cols = st.columns(3)
    for col, (phase, title, desc, value) in zip(cols, cards, strict=False):
        with col:
            st.markdown(
                f"""
                <div style='padding:1rem 1.1rem; border:1px solid #E2E5E9;
                            border-radius:10px; background:#FFFFFF; height:100%;
                            box-shadow:0 1px 2px rgba(15,23,42,0.03);'>
                    <div style='color:#6B7280; font-size:0.72rem; font-weight:600;
                                letter-spacing:0.05em; text-transform:uppercase;
                                margin-bottom:0.3rem;'>{phase}</div>
                    <div style='color:#111827; font-size:0.95rem; font-weight:600;
                                margin-bottom:0.35rem;'>{title}</div>
                    <div style='color:#6B7280; font-size:0.8rem;
                                margin-bottom:0.6rem;'>{desc}</div>
                    <div style='color:#4B5563; font-size:0.78rem; line-height:1.5;
                                padding-top:0.55rem; border-top:1px dashed #E2E5E9;'>
                        {value}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Phase 카드와 실행 버튼 사이 여백 — 카드 바로 아래에 붙으면 답답함
    st.markdown("<div style='margin-bottom:2.5rem;'></div>", unsafe_allow_html=True)


def _render_pipeline_cta() -> None:
    """3분할 실행 버튼 — 회사설정(secondary) / Phase1·Phase2 분석 시작(primary)."""
    col_settings, col_p1, col_p2 = st.columns(3)
    with col_settings:
        settings_clicked = st.button(
            "분석 전 회사설정",
            use_container_width=True,
            key="overview_goto_settings",
        )
    with col_p1:
        p1_clicked = st.button(
            "Phase 1 분석 시작",
            type="primary",
            use_container_width=True,
            key="overview_run_phase1",
        )
    with col_p2:
        p2_clicked = st.button(
            "Phase 2 분석 시작",
            type="primary",
            use_container_width=True,
            key="overview_run_phase2",
        )

    if settings_clicked:
        st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_COMPANY_SETTINGS
        st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_COMPANY_SETTINGS
        st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_COMPANY_SETTINGS
        st.rerun()

    # Why: 클릭 전에는 placeholder 자체를 만들지 않는다. 미리 st.empty() 를 깔면
    #      버튼 아래 빈 박스 슬롯이 항상 남는다(_run_phase1/_start_phase2_analysis
    #      는 자체적으로 st.spinner/st.progress 로 시각 피드백을 처리).
    if p1_clicked:
        _run_phase1()
    elif p2_clicked:
        from dashboard.tab_phase2 import _start_phase2_analysis

        _start_phase2_analysis()


def _run_phase1() -> None:
    """Run Phase 1 only. Completed result is reflected on rerun."""
    from dashboard.components.analysis_runner import run_phase_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
    st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_PHASE1

    with st.spinner("Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다."):
        try:
            run_phase_analysis(phase="phase1")
        except Exception as e:
            st.error(f"Phase 1 실행 실패: {e}")
            return
    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
    st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_PHASE1
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
    st.rerun()


# ── After — 분석 후 ────────────────────────────────────────


def _render_after(result: PipelineResult) -> None:
    """분석 후 화면 — 위험 KPI + LLM 요약 + Top 5 + 기존 차트."""
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)
    kpis = _cached_kpis(df)

    # 상단: 제목 + 작은 재실행 버튼
    col_title, col_rerun = st.columns([5, 1])
    with col_title:
        st.subheader("감사 결과 개요")
        st.caption("아래 KPI·요약·Top 5로 배치 전체 위험을 빠르게 확인하세요.")
    with col_rerun:
        if st.button("재실행", use_container_width=True, key="overview_rerun"):
            _run_phase1()

    _render_risk_kpis(kpis)
    st.divider()

    # LLM 배치 요약
    _render_batch_insight(result)
    st.divider()

    # Top 5 고위험 전표
    _render_top5_high_risk(df)
    st.divider()

    # 기존 차트 3종
    col_donut, col_bar = st.columns([1, 2])
    with col_donut:
        st.plotly_chart(
            risk_donut(df),
            use_container_width=True,
            key="overview_after_risk_donut",
        )
    with col_bar:
        st.plotly_chart(
            rule_violation_bar(df),
            use_container_width=True,
            key="overview_after_rule_violation_bar",
        )

    _render_monthly_highlights(df)
    st.plotly_chart(
        monthly_trend(df),
        use_container_width=True,
        key="overview_after_monthly_trend",
    )

    _render_benford_summary(df)


def _render_risk_kpis(kpis: dict) -> None:
    """위험 등급별 핵심 KPI 4개."""
    anomaly_pct = kpis["anomaly_rate"]
    high_ratio = kpis["high_risk_docs"] / max(kpis["anomaly_docs"], 1) * 100
    fraud_pct = kpis["fraud_suspect"] / max(kpis["total_docs"], 1) * 100

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            label="이상 의심 전표",
            value=f"{kpis['anomaly_docs']:,}건",
            help="감사 룰에서 비정상 패턴이 1건 이상 감지된 전표의 총 수",
        )
        st.caption(f"전체의 {anomaly_pct}%")
    with c2:
        st.metric(
            label="이상 의심 금액",
            value=kpis["anomaly_amount_fmt"],
            help="High·Medium 등급 전표에 포함된 차변 금액 합계",
        )
        st.caption(f"총 {kpis['total_amount_fmt']}의 {kpis['amount_ratio']}%")
    with c3:
        st.metric(
            label="고위험(High) 전표",
            value=f"{kpis['high_risk_docs']:,}건",
            help="위험 점수 최상위 전표. 감사 시 최우선 검토 대상",
        )
        st.caption(f"이상 전표의 {high_ratio:.1f}%")
    with c4:
        st.metric(
            label="부정 의심 (Layer B)",
            value=f"{kpis['fraud_suspect']:,}건",
            help="중복 지급, 자기 승인 등 횡령/배임 시나리오에 해당하는 전표 수",
        )
        st.caption(f"전체의 {fraud_pct:.1f}%")


# ── LLM 배치 요약 ──────────────────────────────────────────


def _render_batch_insight(result: PipelineResult) -> None:
    """LLM 배치 요약 — 세션 캐시에 있으면 표시, 없으면 생성 버튼."""
    st.subheader("LLM 배치 요약")

    insight = st.session_state.get(_BATCH_INSIGHT_KEY)
    if insight is None:
        st.caption(
            "LLM이 배치 전체를 분석해 거시적 위험 평가를 자연어로 정리합니다. "
            "비용이 발생할 수 있어 사용자가 요청할 때만 실행합니다."
        )
        if st.button("요약 생성", key="overview_gen_insight"):
            _generate_batch_insight()
        return

    st.markdown(insight.summary)

    if insight.top_risks:
        st.markdown("**주요 위험 포인트**")
        for risk in insight.top_risks:
            st.markdown(f"- {risk}")

    if insight.significant_tx_opinions:
        with st.expander(
            f"유의적 거래 의견 {len(insight.significant_tx_opinions)}건",
            expanded=False,
        ):
            for opinion in insight.significant_tx_opinions:
                doc_id = getattr(opinion, "document_id", "—")
                rationale = getattr(opinion, "rationale", "")
                st.markdown(f"- **{doc_id}** — {rationale}")

    if st.button("다시 생성", key="overview_regen_insight"):
        st.session_state.pop(_BATCH_INSIGHT_KEY, None)
        _generate_batch_insight()


def _generate_batch_insight() -> None:
    """InsightGenerator 호출 + 세션 캐시."""
    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    if ctx is None or ctx.is_anonymous:
        st.warning("회사 컨텍스트가 필요합니다.")
        return

    try:
        from src.db.connection import get_connection
        from src.llm.insight_generator import InsightGenerator

        conn = get_connection(str(ctx.db_path))
        with st.spinner("LLM 배치 요약 생성 중..."):
            generator = InsightGenerator(conn)
            insight = generator.generate_batch_insight()
        st.session_state[_BATCH_INSIGHT_KEY] = insight
        st.rerun()
    except Exception as e:
        st.error(f"요약 생성 실패: {e}")


# ── Top 5 고위험 전표 ──────────────────────────────────────


def _render_top5_high_risk(df: pd.DataFrame) -> None:
    """가장 점수가 높은 전표 5건을 요약 테이블로 표시."""
    st.subheader("Top 5 고위험 전표")

    if "risk_level" not in df.columns:
        st.caption("위험 등급 정보가 없습니다. 파이프라인을 먼저 실행하세요.")
        return

    high = df[df["risk_level"] == "High"].copy()
    if high.empty:
        st.caption("High 등급 전표가 없습니다. Medium·Low 전표는 아래 차트·탐색 탭에서 확인하세요.")
        return

    # 정렬 키 우선순위: risk_score → anomaly_score → debit_amount
    sort_col = next(
        (c for c in ["risk_score", "anomaly_score", "debit_amount"] if c in high.columns),
        None,
    )
    if sort_col is None:
        st.caption("정렬 가능한 점수/금액 컬럼이 없습니다.")
        return

    top5 = high.nlargest(5, sort_col)

    display_cols = [
        c for c in [
            "document_id",
            "posting_date",
            "gl_account",
            "debit_amount",
            "credit_amount",
            "risk_score",
            "flagged_rules",
            "line_text",
        ]
        if c in top5.columns
    ]
    st.dataframe(
        top5[display_cols],
        use_container_width=True,
        hide_index=True,
    )


# ── 월별 / Benford — 기존 로직 유지 ─────────────────────────


def _render_monthly_highlights(df: pd.DataFrame) -> None:
    """월별 데이터에서 감사인이 주목할 특이점을 자동 추출."""
    if "fiscal_period" not in df.columns or "risk_level" not in df.columns:
        return

    monthly = df.groupby("fiscal_period").agg(
        total=("document_id", "count"),
        anomaly=("risk_level", lambda x: (x != "Normal").sum()),
    )
    if monthly.empty or len(monthly) < 3:
        return

    avg_total = monthly["total"].mean()
    avg_anomaly = monthly["anomaly"].mean()
    findings: list[str] = []

    spike_months = monthly[monthly["total"] > avg_total * 1.5]
    for period, row in spike_months.iterrows():
        ratio = row["total"] / avg_total
        findings.append(f"**{int(period)}월** 전표 건수 급증 (평균 대비 {ratio:.1f}배)")

    monthly["anomaly_rate"] = monthly["anomaly"] / monthly["total"].clip(lower=1)
    avg_rate = avg_anomaly / max(avg_total, 1)
    high_rate_months = monthly[monthly["anomaly_rate"] > avg_rate * 2]
    for period, row in high_rate_months.iterrows():
        pct = row["anomaly_rate"] * 100
        ratio = row["anomaly_rate"] / max(avg_rate, 0.001)
        findings.append(f"**{int(period)}월** 이상 비율 {pct:.1f}% (전체 평균의 {ratio:.1f}배)")

    if "risk_level" in df.columns:
        high_monthly = df[df["risk_level"] == "High"].groupby("fiscal_period").size()
        if not high_monthly.empty:
            peak_month = high_monthly.idxmax()
            peak_count = high_monthly.max()
            if peak_count > high_monthly.mean() * 1.5:
                findings.append(
                    f"**{int(peak_month)}월** 고위험(High) 전표 집중 ({peak_count:,}건)"
                )

    if not findings:
        return

    st.subheader("월별 특이점")
    for f in findings[:5]:
        st.markdown(f"- {f}")
    st.divider()


def _render_benford_summary(df: pd.DataFrame) -> None:
    """Benford 분석 요약 — 오버레이 차트 + MAD 판정."""
    if "first_digit" not in df.columns:
        st.caption("Benford 분석: first_digit 피처 없음 (feature engineering 필요)")
        return

    digits = df["first_digit"].dropna()
    if len(digits) < 30:
        st.caption(f"Benford 분석: 유효 표본 {len(digits)}건 — 최소 30건 필요")
        return

    st.divider()
    st.subheader("Benford 분석")

    from config.settings import get_settings
    from src.validation.benford import BENFORD_EXPECTED, analyze_benford

    settings = get_settings()
    br, _ = analyze_benford(digits, settings=settings)

    digits_df = pd.DataFrame({
        "digit": range(1, 10),
        "observed_freq": [br.observed.get(d, 0.0) for d in range(1, 10)],
        "expected_freq": [BENFORD_EXPECTED[d] for d in range(1, 10)],
    })

    col_chart, col_metrics = st.columns([2, 1])
    with col_chart:
        fig = benford_overlay(digits_df, mad_threshold=settings.benford_mad_threshold)
        st.plotly_chart(
            fig,
            use_container_width=True,
            key="overview_after_benford_overlay",
        )
    with col_metrics:
        conformity = {
            "close": "Close (적합)",
            "acceptable": "Acceptable (수용)",
            "marginally": "Marginal (경계)",
            "nonconforming": "Nonconformity (부적합)",
        }.get(br.mad_conformity, br.mad_conformity)
        st.metric("표본", f"{br.sample_size:,}건")
        st.metric(
            "MAD (평균절대편차)",
            f"{br.mad:.4f}" if br.mad is not None else "N/A",
            help="실제 첫째자리 분포와 Benford 이론 분포의 평균 차이. 0에 가까울수록 정상.",
        )
        st.metric("판정", conformity)


_SEPARATE_BENCHMARK_RULES: dict[str, str] = {
    "L4-02": "dataset / segment",
    "L4-03": "entry / population",
    "L4-04": "pair / population",
    "L3-09": "account / aging-bucket",
    "L4-05": "user / user-day",
}

_STATUS_LABELS: dict[str, str] = {
    "ok": "Evaluated",
    "no_label": "No Label",
    "skipped": "Skipped",
    "coverage_anchor": "Coverage Anchor",
    "population": "Population",
}


def _format_percent(value: float | None, *, allow_blank: bool = False) -> str:
    """Format a percentage value for display."""

    if value is None:
        return "" if allow_blank else "N/A"
    return f"{value * 100:.1f}%"


def _build_metric_row(metric: RuleMetric) -> dict[str, object]:
    """Convert a RuleMetric into a table row."""

    return {
        "Rule ID": metric.rule_code,
        "Status": _STATUS_LABELS.get(metric.evaluation_status, metric.evaluation_status),
        "Labels": metric.label_docs,
        "Flagged": metric.flagged_docs,
        "TP": metric.tp_docs,
        "FP": metric.fp_docs,
        "FN": metric.fn_docs,
        "Precision": _format_percent(metric.precision),
        "Recall": _format_percent(metric.recall),
        "F1": _format_percent(metric.f1),
        "Objective": metric.rule_objective or "",
        "Expected Coverage": metric.expected_coverage or "",
        "Overlap Docs": metric.overlap_docs,
        "Standalone Docs": metric.standalone_docs,
        "Review Queue Docs": metric.review_queue_docs,
    }


def _build_datasynth_rule_tables(
    report: PerformanceReport,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rule metrics into regular and separate-benchmark tables."""

    evaluated_rows: list[dict[str, object]] = []
    separate_rows: list[dict[str, object]] = []

    for metric in report.rule_metrics:
        row = _build_metric_row(metric)
        if metric.rule_code in _SEPARATE_BENCHMARK_RULES:
            row["Benchmark Type"] = "Separate Benchmark"
            row["Benchmark Scope"] = _SEPARATE_BENCHMARK_RULES[metric.rule_code]
            separate_rows.append(row)
        else:
            evaluated_rows.append(row)

    evaluated_df = pd.DataFrame(
        evaluated_rows,
        columns=[
            "Rule ID",
            "Status",
            "Labels",
            "Flagged",
            "TP",
            "FP",
            "FN",
            "Precision",
            "Recall",
            "F1",
            "Objective",
            "Expected Coverage",
            "Overlap Docs",
            "Standalone Docs",
            "Review Queue Docs",
        ],
    )
    separate_df = pd.DataFrame(
        separate_rows,
        columns=[
            "Rule ID",
            "Status",
            "Labels",
            "Flagged",
            "TP",
            "FP",
            "FN",
            "Precision",
            "Recall",
            "F1",
            "Benchmark Type",
            "Benchmark Scope",
        ],
    )
    return evaluated_df, separate_df
