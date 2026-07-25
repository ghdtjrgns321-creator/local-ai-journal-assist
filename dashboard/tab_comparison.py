"""전기 비교 탭 — 분석적 절차(ISA 520) flux analysis 시각화.

감사 표준 요건(분석적 절차)에 맞춰 세 소분류로 구성:
  ① 분석적 절차 (Flux)   — KPI 리본 + K-IFRS 카테고리 변동 + 월별 추세 + 월별 분포 변동(D02)
  ② 계정과목 변동         — 변동 큰 계정 Top N + 신규/소멸 계정 + 계정 활동 변동(D01)
  ③ 검토 신호 변동       — 룰별 신호 증감

함정3 방어: 집계 연산은 DuckDB SQL 에 위임. Pandas 에는 요약표만 전달.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
)
from dashboard.components.charts.comparison_charts import (
    category_flux_bar,
    changed_accounts_table,
    monthly_trend_comparison,
    rule_violation_delta,
    top_changed_accounts_bar,
)
from dashboard.components.coa_categories import (
    DERIVED_NET_INCOME_LABEL,
    account_display,
    category_label,
)
from src.db.queries import attached_engagement
from src.formatting import format_krw_compact

if TYPE_CHECKING:
    import duckdb

    from src.company.repository import CompanyRepository
    from src.db.connection import ConnectionManager
    from src.pipeline import PipelineResult

# Why: 분석적 절차에서 사용하는 표준 materiality 임계값. ISA 520·실무 가이드는
#      "10% 또는 일정 금액 중 큰 쪽" 패턴. 우선 10% 만 노출하고, 추후 회사별
#      configurable threshold 필요 시 settings.yaml 로 빼낸다.
_MATERIALITY_PCT = 10.0


_PRIOR_MASTER_KEY = "_comparison_prior_master"


def render(
    result: PipelineResult,
    repo: CompanyRepository,
    conn_mgr: ConnectionManager,
) -> None:
    """전기 비교 탭 진입점 (최상위 탭 — 분석적 검토 우측, VAE 좌측).

    페이지 구조:
      "전기 비교" 큰 제목 → sub-tabs(3) → 각 sub-tab 안에서
      비교 대상 연도 selectbox → 전기 대비 변동 분석 헤더 + KPI 16 → sub-tab 콘텐츠
    """
    del result  # Why: 시그니처 호환용. render 자체는 session_state 결과를 직접 본다.

    ctx = st.session_state.get(KEY_COMPANY_CONTEXT)
    if ctx is None or ctx.is_anonymous:
        st.info("전기 비교는 회사를 선택한 후 사용할 수 있습니다.")
        return

    company_id = st.session_state.get(KEY_COMPANY_ID)
    if not company_id:
        return

    # Why: 전기 비교는 PHASE1 검토 신호/PHASE2 우선순위 점수를 모두 활용하지만, 임시로
    #      Phase 2 가드는 풀어 Phase 1 만 실행된 상태에서도 진입할 수 있게 한다.
    # TODO: PHASE2 결과를 카드에 결합한 뒤 phase2_done 조건을 다시 활성화.
    phase1_done = st.session_state.get(KEY_PHASE1_RESULT) is not None
    _phase2_done = st.session_state.get(KEY_PHASE2_RESULT) is not None  # noqa: F841
    if not phase1_done:
        st.info(
            "전기 비교를 보려면 **Phase 1** 분석을 먼저 실행해야 합니다. "
            "Phase 1 결과 탭에서 실행 후 다시 열어 주세요."
        )
        return

    others = [e for e in repo.list_engagements(company_id) if e.engagement_id != ctx.engagement_id]
    if not others:
        # PHASE1 결과 헤더처럼 큰 제목을 먼저 노출한 뒤 안내.
        st.markdown("## 전기 비교")
        st.info("전기가 없습니다. 동일 회사에 다른 회계연도 분석이 등록되어 있지 않습니다.")
        return

    current_batch = st.session_state.get(KEY_BATCH_ID, "")
    if not current_batch:
        st.warning("당기의 분석 결과가 없습니다.")
        return

    # ── master state 초기화: 선택된 전기 engagement_id ──
    options = [e.engagement_id for e in others]
    if (
        _PRIOR_MASTER_KEY not in st.session_state
        or st.session_state[_PRIOR_MASTER_KEY] not in options
    ):
        st.session_state[_PRIOR_MASTER_KEY] = options[0]
    prior = st.session_state[_PRIOR_MASTER_KEY]

    prior_db = repo.db_path(company_id, prior)
    if not prior_db.exists():
        st.markdown("## 전기 비교")
        st.warning(f"전기({prior}) DB 파일이 존재하지 않습니다. 먼저 전기 분석을 실행하세요.")
        return

    # ── 데이터 수집: master prior 기반 1회 ──
    conn = conn_mgr.get(ctx.db_path)
    prior_batch: str = ""
    try:
        with attached_engagement(conn, prior_db, f"prior_{prior}") as alias:
            prior_batch = _resolve_prior_batch(conn, alias)
            if not prior_batch:
                st.markdown("## 전기 비교")
                st.warning(f"전기({prior}) 업로드 배치를 찾을 수 없습니다.")
                return
            data = _collect_comparison_data(conn, current_batch, alias, prior_batch)
    except Exception as exc:  # noqa: BLE001
        st.markdown("## 전기 비교")
        st.error(f"전기 비교 쿼리 실패: {exc}")
        return

    # Why: D01/D02 는 Phase 1 실행 시점에 고정된 전기와 비교한 결과다. 이 화면의 전기
    #      selectbox 로는 다시 계산되지 않으므로, 두 연도가 어긋나면 표에 그 사실을 밝힌다.
    selected = next((e for e in others if e.engagement_id == prior), None)
    data["selected_prior_fiscal_year"] = getattr(selected, "fiscal_year", None)

    _render_page(others, data)


# ── 페이지 구성 ────────────────────────────────────────────────


def _render_page(others, data: dict) -> None:
    """큰 제목 + sub-tabs(3) + 각 sub-tab 콘텐츠.

    Why: "전기 대비 변동 분석" 헤더 + KPI 그리드는 첫 sub-tab 에만 노출한다.
         다른 sub-tab 에서 KPI 헤더가 같이 보이면 시야가 분산되고,
         탭을 클릭해도 KPI 가 계속 고정된 것처럼 보이는 시각적 버그가 된다.
    """
    st.markdown("## 전기 비교")

    sub_tabs = st.tabs(["전체 요약", "계정과목 변동", "검토 신호 변동"])
    with sub_tabs[0]:
        _prior_selectbox(others, suffix="overview")
        _render_header(data["overview"])
        _render_flux_subtab(data)
    with sub_tabs[1]:
        _prior_selectbox(others, suffix="account")
        _render_account_subtab(data)
    with sub_tabs[2]:
        _prior_selectbox(others, suffix="risk")
        _render_risk_subtab(data)


# ── 전기 연도 selectbox (sub-tabs 동기화) ─────────────────────


def _prior_selectbox(others, *, suffix: str) -> str | None:
    """sub-tab 안에서 호출하는 비교 대상 연도 selectbox.

    Why: 같은 widget key 를 여러 sub-tab 에서 호출하면 streamlit 이 에러를 낸다.
         각 sub-tab 별 다른 key 를 쓰되 master state 와 양방향 sync 한다.
         어느 sub-tab 에서 변경해도 다음 rerun 에 다른 sub-tab 의 widget 이
         master 값으로 다시 그려진다.
    """
    labels = {e.engagement_id: f"FY {e.fiscal_year} ({e.engagement_id})" for e in others}
    options = list(labels.keys())
    widget_key = f"_comparison_prior_{suffix}"

    # Why: 이번 rerun 의 master 값을 widget 인스턴스화 직전 widget_key 에 주입.
    #      다른 sub-tab 에서 변경된 master 값을 이 widget 이 그대로 표시하게 된다.
    if _PRIOR_MASTER_KEY in st.session_state and st.session_state[_PRIOR_MASTER_KEY] in options:
        st.session_state[widget_key] = st.session_state[_PRIOR_MASTER_KEY]

    def _sync_master() -> None:
        st.session_state[_PRIOR_MASTER_KEY] = st.session_state[widget_key]

    return st.selectbox(
        "비교 대상 (전기) 연도",
        options,
        format_func=lambda x: labels[x],
        key=widget_key,
        on_change=_sync_master,
    )


# ── 헤더 (KPI 그리드 8개) ──────────────────────────────────────


# Why: KPI 카드 디자인 시스템 — 카테고리 라벨 + 4행 4열 그리드.
#      카테고리별로 좌측에 얇은 컬러 보더를 두어 시각적으로 그룹을 분리한다.
_KPI_CARD_CSS = """
<style>
/* 줄 사이는 좁게, 블록 아래는 넉넉하게 — 뒤따르는 차트 컨테이너와 붙지 않도록
   .comp-kpi-wrap 이 KPI 전체와 다음 요소 사이의 간격을 혼자 책임진다. */
.comp-kpi-wrap { margin-bottom:1.1rem; }
.comp-kpi-section { margin:0 0 0.5rem; }
.comp-kpi-wrap .comp-kpi-section:last-child { margin-bottom:0; }
.comp-kpi-section-header { display:flex; align-items:center; gap:0.45rem;
                           margin:0 0 0.28rem 0.15rem; }
.comp-kpi-section-dot { width:6px; height:6px; border-radius:999px; }
.comp-kpi-section-title { color:#374151; font-size:0.75rem; font-weight:600;
                          letter-spacing:0.06em; text-transform:uppercase;
                          line-height:1.2; }
.comp-kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:0.45rem; }
.comp-kpi-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:9px;
                 padding:0.5rem 0.8rem 0.45rem; box-shadow:0 1px 2px rgba(15,23,42,0.04);
                 border-left:3px solid var(--accent,#E5E7EB); }
.comp-kpi-label { color:#6B7280; font-size:0.73rem; font-weight:500;
                  letter-spacing:0.01em; margin-bottom:0.15rem; line-height:1.25; }
.comp-kpi-row { display:flex; align-items:baseline; justify-content:space-between;
                gap:0.4rem; }
.comp-kpi-value { color:#111827; font-size:1.3rem; font-weight:700;
                  letter-spacing:-0.02em; line-height:1.1; }
.comp-kpi-unit { font-size:0.78rem; font-weight:500; color:#6B7280; margin-left:2px; }
.comp-kpi-delta { font-size:0.72rem; font-weight:600; padding:1px 6px;
                  border-radius:999px; white-space:nowrap; }
.comp-kpi-delta-up   { background:#FEE2E2; color:#B91C1C; }
.comp-kpi-delta-down { background:#DCFCE7; color:#15803D; }
.comp-kpi-delta-flat { background:#F3F4F6; color:#4B5563; }
.comp-kpi-prior { color:#9CA3AF; font-size:0.7rem; margin-top:0.25rem; line-height:1.2;
                  border-top:1px dashed #F1F3F5; padding-top:0.22rem; }
</style>
"""

# Why: 카테고리별 어센트 컬러 — 거래/위험/통제/마스터 4개를 구분.
_SECTION_COLORS: dict[str, str] = {
    "거래": "#2563EB",  # blue-600
    "위험": "#DC2626",  # red-600
    "통제": "#7C3AED",  # violet-600
    "마스터": "#0F766E",  # teal-700
}


def _render_header(overview: pd.DataFrame) -> None:
    """탭 헤더 + 4 카테고리 × 4 카드 = 총 16 KPI 그리드."""
    st.markdown("##### 전기 대비 변동 분석")

    cur = overview[overview["period"] == "current"]
    pri = overview[overview["period"] == "prior"]
    cur_row = cur.iloc[0] if not cur.empty else None
    pri_row = pri.iloc[0] if not pri.empty else None

    def _v(row, col, default=0.0) -> float:
        if row is None:
            return default
        try:
            return float(row[col])
        except (TypeError, ValueError):
            return default

    accent = _SECTION_COLORS

    # ── 거래 규모 ──
    section_trade = [
        _build_kpi_card(
            label="전표 건수",
            current_value=int(_v(cur_row, "row_count")),
            prior_value=int(_v(pri_row, "row_count")),
            unit="건",
            inverse=False,
            accent=accent["거래"],
        ),
        _build_kpi_card(
            label="총 거래 금액",
            current_value=_v(cur_row, "total_debit"),
            prior_value=_v(pri_row, "total_debit"),
            unit=None,
            inverse=False,
            value_fmt=_format_amount_short,
            accent=accent["거래"],
        ),
        _build_kpi_card(
            label="평균 전표 금액",
            current_value=_v(cur_row, "avg_per_doc"),
            prior_value=_v(pri_row, "avg_per_doc"),
            unit=None,
            inverse=False,
            value_fmt=_format_amount_short,
            tooltip="총 차변 / distinct document_id — 전표 1건당 평균 거래 규모",
            accent=accent["거래"],
        ),
        _build_kpi_card(
            label="일평균 전표 건수",
            current_value=_v(cur_row, "daily_avg_rows"),
            prior_value=_v(pri_row, "daily_avg_rows"),
            unit="건/일",
            inverse=False,
            value_fmt=lambda v: f"{v:,.1f}",
            tooltip="전표 건수 / 분석 기간 일수 — 회계기간 길이 차이를 정규화한 활동 강도",
            accent=accent["거래"],
        ),
    ]

    # ── 통제 환경 ──
    section_control = [
        _build_kpi_card(
            label="수기 전표 비율",
            current_value=_v(cur_row, "manual_rate"),
            prior_value=_v(pri_row, "manual_rate"),
            unit="%",
            inverse=True,
            value_fmt=_format_pct,
            tooltip="source 가 manual 인 전표 비율 — 자동화 수준 하락 시 통제 약화 검토 신호",
            accent=accent["통제"],
        ),
        _build_kpi_card(
            label="자기승인 비율",
            current_value=_v(cur_row, "self_approve_rate"),
            prior_value=_v(pri_row, "self_approve_rate"),
            unit="%",
            inverse=True,
            value_fmt=_format_pct,
            tooltip="작성자 = 승인자 비율 — SoD(직무분리) 통제 약화 신호",
            accent=accent["통제"],
        ),
        _build_kpi_card(
            label="심야/주말 기표 비율",
            current_value=_v(cur_row, "night_weekend_rate"),
            prior_value=_v(pri_row, "night_weekend_rate"),
            unit="%",
            inverse=True,
            value_fmt=_format_pct,
            tooltip="22시 이후·06시 이전 또는 토·일 기표 비율 — 우회 통제·이상 작업 신호",
            accent=accent["통제"],
        ),
        _build_kpi_card(
            label="기말 집중도(12월)",
            current_value=_v(cur_row, "year_end_rate"),
            prior_value=_v(pri_row, "year_end_rate"),
            unit="%",
            inverse=True,
            value_fmt=_format_pct,
            tooltip="12월에 기표된 전표 비율 — 결산 조정·기간 귀속 집중 신호 (ISA 545)",
            accent=accent["통제"],
        ),
    ]

    # ── 조직 / 마스터 ──
    section_master = [
        _build_kpi_card(
            label="활성 계정 수",
            current_value=int(_v(cur_row, "account_count")),
            prior_value=int(_v(pri_row, "account_count")),
            unit="개",
            inverse=False,
            tooltip="distinct gl_account — 사업 다양성·과목 변경 신호",
            accent=accent["마스터"],
        ),
        _build_kpi_card(
            label="활동 사용자 수",
            current_value=int(_v(cur_row, "user_count")),
            prior_value=int(_v(pri_row, "user_count")),
            unit="명",
            inverse=False,
            tooltip="distinct created_by — 조직·SoD 변화 신호",
            accent=accent["마스터"],
        ),
        _build_kpi_card(
            label="활성 거래처 수",
            current_value=int(_v(cur_row, "partner_count")),
            prior_value=int(_v(pri_row, "partner_count")),
            unit="곳",
            inverse=False,
            tooltip="distinct trading_partner — 거래처 다양성·신규 벤더 확장 신호",
            accent=accent["마스터"],
        ),
        _build_kpi_card(
            label="활성 거래 유형",
            current_value=int(_v(cur_row, "doc_type_count")),
            prior_value=int(_v(pri_row, "doc_type_count")),
            unit="종",
            inverse=False,
            tooltip="distinct document_type — SA(수기조정)·DR(매출채권)·KR(매입채무) 등 거래 종류 다양성",
            accent=accent["마스터"],
        ),
    ]

    # Why: 세 섹션을 st.markdown 세 번으로 나눠 그리면 streamlit 이 블록마다 자체
    #      세로 간격을 끼워 넣어 카드 줄 사이가 벌어진다. 한 번에 그려 그 간격을
    #      없애고, 줄 간 여백은 CSS(.comp-kpi-section margin)로만 통제한다.
    sections = (
        _kpi_section_html("거래 규모", accent["거래"], section_trade)
        + _kpi_section_html("통제 환경", accent["통제"], section_control)
        + _kpi_section_html("조직 · 마스터", accent["마스터"], section_master)
    )
    st.markdown(
        _KPI_CARD_CSS + f"<div class='comp-kpi-wrap'>{sections}</div>",
        unsafe_allow_html=True,
    )


def _kpi_section_html(title: str, color: str, cards: list[str]) -> str:
    """카테고리 헤더 + 4 카드 그리드 한 섹션의 HTML."""
    return (
        "<div class='comp-kpi-section'>"
        "<div class='comp-kpi-section-header'>"
        f"<span class='comp-kpi-section-dot' style='background:{color};'></span>"
        f"<span class='comp-kpi-section-title'>{title}</span>"
        "</div>"
        "<div class='comp-kpi-grid'>" + "".join(cards) + "</div>"
        "</div>"
    )


def _render_flux_subtab(data: dict) -> None:
    """소분류 ① — K-IFRS 카테고리별 변동 + 월별 추세."""
    section_cat = st.container(border=True)
    section_cat.markdown(f"##### K-IFRS 대분류별 변동률 (임계 {_MATERIALITY_PCT:.0f}%)")

    cat_df = _aggregate_categories(data["category"])
    if cat_df.empty:
        section_cat.info("카테고리별 거래 데이터가 없습니다.")
    else:
        section_cat.plotly_chart(
            category_flux_bar(cat_df, materiality_pct=_MATERIALITY_PCT),
            width="stretch",
            key="comparison_category_flux",
        )
        with section_cat.expander("카테고리별 수치 표 보기", expanded=False):
            display = cat_df.copy()
            display["증감액(₩)"] = display["current_amount"] - display["prior_amount"]
            display["증감률(%)"] = (
                (display["current_amount"] - display["prior_amount"])
                / display["prior_amount"].replace(0, pd.NA)
                * 100
            )
            display = display.rename(
                columns={
                    "category": "카테고리",
                    "current_amount": "당기(₩)",
                    "prior_amount": "전기(₩)",
                }
            )
            st.dataframe(
                display[["카테고리", "당기(₩)", "전기(₩)", "증감액(₩)", "증감률(%)"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "당기(₩)": st.column_config.NumberColumn(format="%,.0f"),
                    "전기(₩)": st.column_config.NumberColumn(format="%,.0f"),
                    "증감액(₩)": st.column_config.NumberColumn(format="%,.0f"),
                    "증감률(%)": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

    section_month = st.container(border=True)
    section_month.markdown("##### 월별 거래 추세 (당기 vs 전기)")
    section_month.caption(
        "특정 월에 한쪽 곡선이 급등·급락하면 **기간 귀속(cutoff)** 또는 "
        "**결산 조정**의 이상 신호일 수 있습니다."
    )
    col_count, col_sales = section_month.columns(2)
    with col_count:
        st.markdown("**월별 전표 건수**")
        st.plotly_chart(
            monthly_trend_comparison(data["monthly"], value_col="row_count"),
            width="stretch",
            key="comparison_monthly_count",
        )
    with col_sales:
        st.markdown("**월별 순매출** (매출 계정 대변 − 차변)")
        st.plotly_chart(
            monthly_trend_comparison(data["monthly"], value_col="net_sales"),
            width="stretch",
            key="comparison_monthly_sales",
        )

    _render_monthly_shift_section(data)


# ── D01/D02 — PHASE1-2 분석적 검토 신호를 전기 비교 맥락에 붙인다 ──
#
# Why: D01(계정 활동 변동)·D02(월별 분포 변동)는 Phase 1 파이프라인이 전기 engagement 를
#      attach 해 계산한 ISA 520 신호다. 전기가 있어야 산출된다는 전제가 이 탭과 같고,
#      묻는 질문(어떤 계정이 전기 대비 바뀌었나)도 같아 각 소분류 안에 함께 둔다.
#      신호 소유권은 PHASE1-2 에 그대로 있고, 여기서는 표시만 한다(점수 비병합).


def _macro_findings(rule_id: str) -> list[dict]:
    """세션의 Phase 1 결과에서 macro finding 을 읽는다. 없으면 빈 목록."""
    result = st.session_state.get(KEY_PHASE1_RESULT)
    if result is None:
        return []
    from src.export.phase1_case_view import build_phase1_macro_finding_queue

    return build_phase1_macro_finding_queue(result, rule_id=rule_id)


def _prior_year_note(findings: list[dict], data: dict) -> str:
    """finding 이 실제로 비교한 전기와 화면에서 고른 전기가 다르면 밝힌다."""
    years: set[int] = set()
    for finding in findings:
        try:
            years.add(int(finding.get("prior_fiscal_year")))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not years:
        return ""
    used = " · ".join(str(y) for y in sorted(years))
    selected = data.get("selected_prior_fiscal_year")
    if selected is not None and {int(selected)} != years:
        return (
            f"이 표는 Phase 1 실행 시점에 비교한 전기(FY {used}) 기준입니다. "
            f"위에서 고른 FY {selected} 과 달라 다른 연도를 보고 있습니다."
        )
    return f"비교 기준 전기: FY {used}"


def _pct_change(current: object, prior: object) -> float | None:
    """증감률(%) — 전기가 없거나 0 이면 계산하지 않는다(신규 계정 등)."""
    try:
        cur = float(current)  # type: ignore[arg-type]
        pri = float(prior)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if pri == 0:
        return None
    return (cur - pri) / abs(pri) * 100.0


_D01_REASON_KR = {"new_account": "신규 계정", "activity_variance": "활동 변동"}

# 목록에서 빠지는 유일한 사유 = 분포를 비교할 수 없음. 신호 강도 컷은 2026-07-25 에 폐지했다.
_D02_NOT_COMPARABLE_KR: dict[str, str] = {
    "insufficient_prior_months": "전기 거래월 부족",
    "insufficient_current_months": "당기 거래월 부족",
}


def _d02_diagnostics() -> list[dict]:
    """Layer D 트랙이 남긴 계정별 D02 판정 근거(비교 가능·불가 전부)를 읽는다."""
    result = st.session_state.get(KEY_PHASE1_RESULT)
    for track in getattr(result, "results", None) or []:
        metadata = getattr(track, "metadata", None)
        if isinstance(metadata, dict) and "d02_account_diagnostics" in metadata:
            rows = metadata.get("d02_account_diagnostics") or []
            return [row for row in rows if isinstance(row, dict)]
    return []


def _d02_coverage_text(listed_count: int) -> str:
    """몇 개 계정을 세웠고, 비교 자체가 불가해 빠진 계정은 몇 개인지."""
    return _format_d02_coverage(listed_count, _d02_diagnostics())


def _format_d02_coverage(listed_count: int, diagnostics: list[dict]) -> str:
    """세션 접근과 분리한 순수 문장 조립 — 판정 근거 목록만 받는다."""
    if not diagnostics:
        return ""

    excluded: dict[str, int] = {}
    for row in diagnostics:
        reason = str(row.get("skip_reason") or "")
        if reason in _D02_NOT_COMPARABLE_KR:
            excluded[reason] = excluded.get(reason, 0) + 1

    text = f"계정 {listed_count}개를 변화폭 순으로 모두 세웠습니다(잘라내지 않음)."
    if excluded:
        parts = [
            f"{_D02_NOT_COMPARABLE_KR[reason]} {count}개"
            for reason, count in sorted(excluded.items(), key=lambda kv: -kv[1])
        ]
        text += (
            " 거래한 달이 너무 적어 분포를 비교할 수 없는 계정은 제외 — " + ", ".join(parts) + "."
        )
    return text


def _render_account_activity_section(data: dict) -> None:
    """계정 활동 변동(D01) — 금액·건수·평균의 당기/전기 원값으로 표시."""
    section = st.container(border=True)
    section.markdown("##### 계정 활동 변동 (분석적 검토 신호)")
    section.caption(
        "전기 대비 **금액·건수·평균 단가**가 함께 크게 바뀐 계정입니다. 위 변동액 Top 15 는 "
        "금액만 보지만, 이 표는 거래 건수와 건당 평균까지 봐서 '금액은 비슷한데 건수가 "
        "급감(=건당 단가 급등)' 같은 변화를 잡아냅니다."
    )

    findings = _macro_findings("D01")
    if not findings:
        section.info("전기 데이터가 연결되지 않아 계정 활동을 비교할 수 없습니다.")
        return

    note = _prior_year_note(findings, data)
    if note:
        section.caption(note)
    section.caption(f"계정 {len(findings)}개를 변동 금액 순으로 모두 세웠습니다(잘라내지 않음).")

    rows = []
    for item in findings:
        m = item.get("metrics") or {}
        cur_amt, pri_amt = m.get("current_total_amount"), m.get("prior_total_amount")
        rows.append(
            {
                "계정": account_display(item.get("gl_account")),
                "구분": _D01_REASON_KR.get(str(m.get("reason")), "활동 변동"),
                "당기 금액": cur_amt,
                "전기 금액": pri_amt,
                "변동액": m.get("amount_delta"),
                "증감률(%)": _pct_change(cur_amt, pri_amt),
                "당기 건수": m.get("current_count"),
                "전기 건수": m.get("prior_count"),
                "건당 평균 증감률(%)": _pct_change(
                    m.get("current_avg_amount"), m.get("prior_avg_amount")
                ),
            }
        )

    section.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "당기 금액": st.column_config.NumberColumn(format="%,.0f"),
            "전기 금액": st.column_config.NumberColumn(format="%,.0f"),
            "변동액": st.column_config.NumberColumn(
                format="%,.0f",
                help="당기 금액 − 전기 금액. 이 값의 절대값이 큰 순으로 정렬합니다.",
            ),
            "증감률(%)": st.column_config.NumberColumn(format="%.1f%%"),
            "당기 건수": st.column_config.NumberColumn(format="%,d"),
            "전기 건수": st.column_config.NumberColumn(format="%,d"),
            "건당 평균 증감률(%)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )


def _render_monthly_shift_section(data: dict) -> None:
    """월별 분포 변동(D02) — 어느 달에 몰렸었는지가 어떻게 바뀌었는지."""
    section = st.container(border=True)
    section.markdown("##### 월별 분포 변동 (분석적 검토 신호)")
    section.caption(
        "위 추세는 원장 전체지만, 이 표는 **계정별로** 1년 금액이 어느 달에 몰려 있었는지 "
        "그 모양이 전기와 달라진 계정입니다. 몰린 달이 기말로 옮겨갔다면 기간 귀속(cutoff) "
        "이나 결산 조정을 확인할 지점입니다."
    )

    findings = _macro_findings("D02")
    coverage = _d02_coverage_text(len(findings))
    if not findings:
        section.info(coverage or "전기 데이터가 연결되지 않아 월별 분포를 비교할 수 없습니다.")
        return

    note = _prior_year_note(findings, data)
    if note:
        section.caption(note)
    if coverage:
        section.caption(coverage)

    rows = []
    for item in findings:
        m = item.get("metrics") or {}
        pri_ratio, cur_ratio = m.get("prior_top_ratio"), m.get("current_top_ratio")
        rows.append(
            {
                "계정": account_display(item.get("gl_account")),
                "가장 몰린 달 (전기 → 당기)": _month_shift_label(
                    m.get("prior_top_month"), m.get("current_top_month")
                ),
                "그 달 비중 (전기)": pri_ratio,
                "그 달 비중 (당기)": cur_ratio,
                "변화폭(%p)": _ratio_gap_pp(pri_ratio, cur_ratio),
                "당기 거래 금액": m.get("current_annual_amount"),
            }
        )

    section.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "그 달 비중 (전기)": st.column_config.NumberColumn(format="percent"),
            "그 달 비중 (당기)": st.column_config.NumberColumn(format="percent"),
            "변화폭(%p)": st.column_config.NumberColumn(
                format="%.1f",
                help=(
                    "한 달에 몰린 정도가 전기 대비 몇 %p 달라졌는지. 이 값이 큰 순으로 정렬합니다."
                ),
            ),
            "당기 거래 금액": st.column_config.NumberColumn(format="%,.0f"),
        },
    )


def _ratio_gap_pp(prior_ratio: object, current_ratio: object) -> float | None:
    """두 비중(0~1)의 차이를 %p 로. 값이 없으면 계산하지 않는다."""
    try:
        return abs(float(current_ratio) - float(prior_ratio)) * 100.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _month_shift_label(prior_month: object, current_month: object) -> str:
    """'11월 → 12월' 형태. 같은 달이면 비중만 바뀐 경우라 화살표를 생략."""
    try:
        pri, cur = int(prior_month), int(current_month)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "-"
    return f"{pri}월 (변동 없음)" if pri == cur else f"{pri}월 → {cur}월"


# ── ② 계정과목 변동 ────────────────────────────────────────────


def _render_account_subtab(data: dict) -> None:
    """소분류 ② — 변동 큰 계정 Top N + 신규/소멸 계정."""
    section_top = st.container(border=True)
    section_top.markdown("##### 변동액 Top 15 계정과목")

    acct_df = data["accounts"]
    if acct_df.empty:
        section_top.info("계정별 변동 데이터가 없습니다.")
    else:
        section_top.plotly_chart(
            top_changed_accounts_bar(
                acct_df,
                top_n=15,
                materiality_pct=_MATERIALITY_PCT,
            ),
            width="stretch",
            key="comparison_top_accounts",
        )

    section_changed = st.container(border=True)
    section_changed.markdown("##### 신규 / 소멸 계정과목")
    table = changed_accounts_table(set(data["current_accounts"]), set(data["prior_accounts"]))
    if table.empty:
        section_changed.success("당기·전기에서 계정과목 변화가 없습니다.")
    else:
        new_df = table[table["구분"] == "신규"][["계정코드", "계정명"]].reset_index(drop=True)
        rm_df = table[table["구분"] == "소멸"][["계정코드", "계정명"]].reset_index(drop=True)
        col_new, col_rm = section_changed.columns(2, gap="large")
        with col_new:
            _render_changed_account_card(new_df, kind="new")
        with col_rm:
            _render_changed_account_card(rm_df, kind="removed")

    _render_account_activity_section(data)


def _render_changed_account_card(df: pd.DataFrame, *, kind: str) -> None:
    """신규/소멸 계정 카드 — 색상 스트라이프 헤더 + 카운트 칩 + 표.

    좌우 2분할로 신규/소멸을 분리해 시선 이동 없이 비교 가능. 표는 [계정코드,
    계정명] 2컬럼만 (구분 컬럼은 좌우 분리로 표현되므로 제거).
    """
    is_new = kind == "new"
    accent = "#0EA5E9" if is_new else "#94A3B8"  # sky-500 / slate-400
    bg = "#F0F9FF" if is_new else "#F8FAFC"  # sky-50 / slate-50
    label = "신규 계정" if is_new else "소멸 계정"
    icon = "＋" if is_new else "−"
    count = len(df)

    st.markdown(
        f"""
        <div style='display:flex; align-items:center; gap:0.65rem; padding:0.6rem 0.9rem;
                    background:{bg}; border-left:3px solid {accent}; border-radius:6px;
                    margin-bottom:0.7rem;'>
            <div style='font-size:1.0rem; font-weight:700; color:{accent};
                        width:1.7rem; height:1.7rem; border-radius:999px;
                        background:#FFFFFF; display:flex; align-items:center;
                        justify-content:center; box-shadow:0 1px 2px rgba(15,23,42,0.05);
                        flex-shrink:0;'>{icon}</div>
            <div style='display:flex; align-items:baseline; gap:0.45rem;'>
                <div style='color:#6B7280; font-size:0.73rem; font-weight:600;
                            letter-spacing:0.04em; text-transform:uppercase;'>{label}</div>
                <div style='color:#111827; font-size:1.35rem; font-weight:700;
                            line-height:1.0; letter-spacing:-0.02em;'>{count:,}<span
                            style='font-size:0.78rem; color:#6B7280; margin-left:2px;
                            font-weight:500;'>개</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if df.empty:
        st.caption("해당 없음")
        return

    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        column_config={
            "계정코드": st.column_config.TextColumn(width="small"),
            "계정명": st.column_config.TextColumn(width="medium"),
        },
        height=min(38 + 35 * len(df), 360),
    )


# ── ③ 검토 신호 변동 ───────────────────────────────────────────


def _render_risk_subtab(data: dict) -> None:
    """소분류 ③ — 룰별 검토 신호 증감."""
    section_rule = st.container(border=True)
    section_rule.markdown("##### 룰별 검토 신호 건수 증감")
    section_rule.caption(
        "각 룰의 **당기 - 전기 검토 신호 건수 차이**. 빨강 막대는 당기에 늘어난 룰, "
        "초록 막대는 줄어든 룰입니다. 신규로 발동된 룰은 새로운 통제 약점 검토 신호입니다."
    )
    cur_rules = data["current_rules"]
    pri_rules = data["prior_rules"]
    section_rule.plotly_chart(
        rule_violation_delta(cur_rules, pri_rules),
        width="stretch",
        key="comparison_rule_delta",
    )

    cur_set = set(cur_rules["rule_code"]) if not cur_rules.empty else set()
    pri_set = set(pri_rules["rule_code"]) if not pri_rules.empty else set()
    new_rules = sorted(cur_set - pri_set)
    gone_rules = sorted(pri_set - cur_set)
    if new_rules or gone_rules:
        from dashboard.components.rule_labels import rule_label

        col_new, col_gone = section_rule.columns(2)
        with col_new:
            st.markdown("**신규 발동 룰** (전기엔 없었음)")
            if new_rules:
                st.write(", ".join(rule_label(r) for r in new_rules))
            else:
                st.caption("없음")
        with col_gone:
            st.markdown("**소멸 룰** (전기에만 발동)")
            if gone_rules:
                st.write(", ".join(rule_label(r) for r in gone_rules))
            else:
                st.caption("없음")


# ── 데이터 수집 (SQL 위임) ─────────────────────────────────────


def _resolve_prior_batch(conn: duckdb.DuckDBPyConnection, alias: str) -> str:
    """전기 DB의 최신 upload_batch_id."""
    row = conn.execute(
        f"""
        SELECT upload_batch_id FROM {alias}.general_ledger
        GROUP BY upload_batch_id ORDER BY MAX(created_at) DESC LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row else ""


def _collect_comparison_data(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    alias: str,
    prior_batch: str,
) -> dict:
    """전기 비교에 필요한 모든 집계 결과를 한 번에 SQL 으로 수집."""
    return {
        "overview": _query_overview(conn, current_batch, alias, prior_batch),
        "category": _query_category_amounts(conn, current_batch, alias, prior_batch),
        "monthly": _query_monthly(conn, current_batch, alias, prior_batch),
        "accounts": _query_account_amounts(conn, current_batch, alias, prior_batch),
        "current_rules": _query_rule_counts(conn, current_batch=current_batch, schema=None),
        "prior_rules": _query_rule_counts(conn, current_batch=prior_batch, schema=alias),
        "current_accounts": _query_accounts(conn, current_batch=current_batch, schema=None),
        "prior_accounts": _query_accounts(conn, current_batch=prior_batch, schema=alias),
    }


def _query_overview(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    alias: str,
    prior_batch: str,
) -> pd.DataFrame:
    """4 카테고리 × 4 KPI — 당기/전기 한 번에 집계.

    반환 컬럼:
      거래: row_count, total_debit, avg_per_doc, daily_avg_rows
      검토 신호: anomaly_count, high_count, anomaly_rate (+ rule_kind_count는 별도 쿼리)
      통제: manual_rate, self_approve_rate, night_weekend_rate, year_end_rate
      마스터: account_count, user_count, partner_count, doc_type_count
    """
    sql_one = """
        SELECT ? AS period,
               COUNT(*) AS row_count,
               COALESCE(SUM(debit_amount), 0) AS total_debit,
               -- 평균 전표당 차변 금액
               COALESCE(SUM(debit_amount) / NULLIF(COUNT(DISTINCT document_id), 0), 0)
                   AS avg_per_doc,
               -- 일평균 전표 건수 = row_count / 분석 기간 일수
               --   분석 기간 = max(posting_date) - min(posting_date) + 1.
               --   NULL/길이 0 방어로 NULLIF 사용. 결과는 float.
               COALESCE(
                   1.0 * COUNT(*)
                       / NULLIF(
                           DATE_DIFF('day', MIN(CAST(posting_date AS DATE)),
                                            MAX(CAST(posting_date AS DATE))) + 1,
                           0
                       ),
                   0.0
               ) AS daily_avg_rows,
               -- 우선검토 등급
               SUM(CASE WHEN risk_level IS NOT NULL AND risk_level <> 'Normal'
                        THEN 1 ELSE 0 END) AS anomaly_count,
               SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END) AS high_count,
               -- 이상 신호율(%) = anomaly_count / 전체 × 100
               COALESCE(
                   100.0 * SUM(CASE WHEN risk_level IS NOT NULL AND risk_level <> 'Normal'
                                    THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*), 0),
                   0.0
               ) AS anomaly_rate,
               -- 마스터 데이터
               COUNT(DISTINCT gl_account) AS account_count,
               COUNT(DISTINCT created_by) AS user_count,
               COUNT(DISTINCT trading_partner) AS partner_count,
               COUNT(DISTINCT document_type) AS doc_type_count,
               -- Why: source 컬럼이 NULL/공백일 수 있어 NULLIF 로 분모 방어. 대소문자 무관.
               COALESCE(
                   100.0 * SUM(CASE WHEN LOWER(COALESCE(source,'')) LIKE '%manual%'
                                    THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*), 0),
                   0.0
               ) AS manual_rate,
               -- Why: 작성자 = 승인자 비율. 둘 다 NOT NULL 인 라인만 분모/분자에 포함.
               COALESCE(
                   100.0 * SUM(CASE
                       WHEN created_by IS NOT NULL AND approved_by IS NOT NULL
                            AND created_by = approved_by THEN 1 ELSE 0 END)
                         / NULLIF(
                             SUM(CASE WHEN created_by IS NOT NULL
                                       AND approved_by IS NOT NULL THEN 1 ELSE 0 END),
                             0
                         ),
                   0.0
               ) AS self_approve_rate,
               -- Why: 심야(22~05시) 또는 토·일(DOW 0=Sun, 6=Sat) 기표 비율.
               COALESCE(
                   100.0 * SUM(CASE
                       WHEN posting_date IS NULL THEN 0
                       WHEN EXTRACT(DOW FROM posting_date) IN (0, 6) THEN 1
                       WHEN EXTRACT(HOUR FROM posting_date) >= 22 THEN 1
                       WHEN EXTRACT(HOUR FROM posting_date) < 6 THEN 1
                       ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN posting_date IS NOT NULL THEN 1 ELSE 0 END), 0),
                   0.0
               ) AS night_weekend_rate,
               -- 12월 기표 비율 (기말 집중도)
               COALESCE(
                   100.0 * SUM(CASE WHEN EXTRACT(MONTH FROM posting_date) = 12
                                    THEN 1 ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN posting_date IS NOT NULL THEN 1 ELSE 0 END), 0),
                   0.0
               ) AS year_end_rate
        FROM {table}
        WHERE upload_batch_id = ?
    """
    cur_sql = sql_one.format(table="general_ledger")
    pri_sql = sql_one.format(table=f"{alias}.general_ledger")
    cur_df = conn.execute(cur_sql, ["current", current_batch]).fetchdf()
    pri_df = conn.execute(pri_sql, ["prior", prior_batch]).fetchdf()

    # Why: flagged_rules 는 comma-separated 문자열이라 UNNEST 필요 — 별도 쿼리로 종류 수 추출.
    cur_kind = _query_rule_kind_count(conn, current_batch, schema=None)
    pri_kind = _query_rule_kind_count(conn, prior_batch, schema=alias)
    cur_df["rule_kind_count"] = cur_kind
    pri_df["rule_kind_count"] = pri_kind
    return pd.concat([cur_df, pri_df], ignore_index=True)


def _query_rule_kind_count(
    conn: duckdb.DuckDBPyConnection,
    batch_id: str,
    *,
    schema: str | None,
) -> int:
    """flagged_rules 안의 distinct rule_code 종류 수."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"
    sql = f"""
        SELECT COUNT(DISTINCT TRIM(rule_code)) AS kinds
        FROM (
            SELECT UNNEST(STRING_SPLIT(flagged_rules, ',')) AS rule_code
            FROM {table}
            WHERE upload_batch_id = ?
              AND flagged_rules IS NOT NULL AND flagged_rules <> ''
        )
        WHERE TRIM(rule_code) <> ''
    """
    row = conn.execute(sql, [batch_id]).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _query_category_amounts(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    alias: str,
    prior_batch: str,
) -> pd.DataFrame:
    """gl_account 별 차변·대변 합계 — 카테고리 매핑·NI 계산은 파이썬에서 적용."""
    sql_cur = """
        SELECT gl_account,
               SUM(debit_amount) AS debit_amt,
               SUM(credit_amount) AS credit_amt
        FROM general_ledger
        WHERE upload_batch_id = ? AND gl_account IS NOT NULL
        GROUP BY gl_account
    """
    sql_pri = f"""
        SELECT gl_account,
               SUM(debit_amount) AS debit_amt,
               SUM(credit_amount) AS credit_amt
        FROM {alias}.general_ledger
        WHERE upload_batch_id = ? AND gl_account IS NOT NULL
        GROUP BY gl_account
    """
    cur = conn.execute(sql_cur, [current_batch]).fetchdf()
    pri = conn.execute(sql_pri, [prior_batch]).fetchdf()
    cur = cur.rename(columns={"debit_amt": "current_debit", "credit_amt": "current_credit"})
    pri = pri.rename(columns={"debit_amt": "prior_debit", "credit_amt": "prior_credit"})
    merged = pd.merge(cur, pri, on="gl_account", how="outer").fillna(0)
    # 기존 차트는 current_amount/prior_amount (차변 합계) 를 기대 — 호환 유지.
    merged["current_amount"] = merged["current_debit"]
    merged["prior_amount"] = merged["prior_debit"]
    return merged


def _aggregate_categories(account_df: pd.DataFrame) -> pd.DataFrame:
    """gl_account 단위 합계를 K-IFRS 대분류로 집계 + 당기순이익(NI) derived row 추가.

    NI = (매출/수익 net) − (매출원가 net) − (판관비 net) − (영업외 net) − (법인세 net)
       · 수익 net  = 대변 − 차변  (수익은 대변이 본 자리)
       · 비용 net  = 차변 − 대변  (비용은 차변이 본 자리)
    BS 카테고리(자산/부채/자본)와 가/임시는 기존과 동일하게 차변 합계만 표시.
    """
    if account_df.empty:
        return pd.DataFrame(columns=["category", "current_amount", "prior_amount"])
    df = account_df.copy()
    df["category"] = df["gl_account"].apply(category_label)
    df = df[df["category"] != "미분류"]

    has_credit_cols = {"current_credit", "prior_credit"}.issubset(df.columns)
    grouped = df.groupby("category", as_index=False).agg(
        current_amount=("current_amount", "sum"),
        prior_amount=("prior_amount", "sum"),
    )

    if has_credit_cols:
        # K-IFRS NI 계산. 카테고리가 누락되어도 0 으로 보존.
        credit_grouped = df.groupby("category", as_index=False).agg(
            current_credit=("current_credit", "sum"),
            prior_credit=("prior_credit", "sum"),
        )
        net_df = pd.merge(grouped, credit_grouped, on="category", how="left").fillna(0)

        def _ni(side: str) -> float:
            def _get(cat: str, kind: str) -> float:
                row = net_df[net_df["category"] == cat]
                if row.empty:
                    return 0.0
                col = f"{side}_{kind}"
                return float(row.iloc[0][col]) if col in row.columns else 0.0

            rev_net = _get("매출/수익", "credit") - _get("매출/수익", "amount")
            cogs_net = _get("매출원가", "amount") - _get("매출원가", "credit")
            sga_net = _get("판매비와관리비", "amount") - _get("판매비와관리비", "credit")
            ono_net = _get("영업외/금융", "amount") - _get("영업외/금융", "credit")
            tax_net = _get("법인세", "amount") - _get("법인세", "credit")
            return rev_net - cogs_net - sga_net - ono_net - tax_net

        ni_row = pd.DataFrame(
            [
                {
                    "category": DERIVED_NET_INCOME_LABEL,
                    "current_amount": _ni("current"),
                    "prior_amount": _ni("prior"),
                }
            ]
        )
        grouped = pd.concat([grouped, ni_row], ignore_index=True)

    return grouped


def _query_account_amounts(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    alias: str,
    prior_batch: str,
) -> pd.DataFrame:
    """gl_account 차변 합계 — Top N 차트용."""
    return _query_category_amounts(conn, current_batch, alias, prior_batch)


def _query_monthly(
    conn: duckdb.DuckDBPyConnection,
    current_batch: str,
    alias: str,
    prior_batch: str,
) -> pd.DataFrame:
    """월(1..12)별 건수·차변금액·순매출 — 당기/전기 한 테이블.

    Why: net_sales = SUM(credit) - SUM(debit) on gl_account LIKE '4%'.
         매출 인식은 대변, 매출 차감(반품·할인)은 차변이므로 순매출은 대변-차변.
         K-IFRS 매출/수익 계정은 코드 첫 자리 = 4.
    """
    sales_expr = (
        "COALESCE("
        "  SUM(CASE WHEN SUBSTR(CAST(gl_account AS VARCHAR), 1, 1) = '4'"
        "           THEN COALESCE(credit_amount, 0) - COALESCE(debit_amount, 0)"
        "           ELSE 0 END), 0)"
    )
    sql = f"""
        SELECT 'current' AS period,
               EXTRACT(MONTH FROM posting_date) AS month,
               COUNT(*) AS row_count,
               COALESCE(SUM(debit_amount), 0) AS total_amount,
               {sales_expr} AS net_sales
        FROM general_ledger
        WHERE upload_batch_id = ? AND posting_date IS NOT NULL
        GROUP BY EXTRACT(MONTH FROM posting_date)
        UNION ALL
        SELECT 'prior',
               EXTRACT(MONTH FROM posting_date),
               COUNT(*),
               COALESCE(SUM(debit_amount), 0),
               {sales_expr}
        FROM {alias}.general_ledger
        WHERE upload_batch_id = ? AND posting_date IS NOT NULL
        GROUP BY EXTRACT(MONTH FROM posting_date)
        ORDER BY period, month
    """
    return conn.execute(sql, [current_batch, prior_batch]).fetchdf()


def _query_rule_counts(
    conn: duckdb.DuckDBPyConnection,
    *,
    current_batch: str,
    schema: str | None,
) -> pd.DataFrame:
    """룰별 위반 건수 — flagged_rules 파싱."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"
    sql = f"""
        SELECT TRIM(rule_code) AS rule_code, COUNT(*) AS cnt
        FROM (
            SELECT UNNEST(STRING_SPLIT(flagged_rules, ',')) AS rule_code
            FROM {table}
            WHERE upload_batch_id = ?
              AND flagged_rules IS NOT NULL AND flagged_rules <> ''
        )
        WHERE TRIM(rule_code) <> ''
        GROUP BY TRIM(rule_code) ORDER BY cnt DESC
    """
    return conn.execute(sql, [current_batch]).fetchdf()


def _query_accounts(
    conn: duckdb.DuckDBPyConnection,
    *,
    current_batch: str,
    schema: str | None,
) -> list[str]:
    """계정과목 고유 목록."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"
    sql = f"""
        SELECT DISTINCT gl_account FROM {table}
        WHERE upload_batch_id = ? AND gl_account IS NOT NULL
    """
    rows = conn.execute(sql, [current_batch]).fetchall()
    return [str(r[0]) for r in rows]


# ── 포매팅 ─────────────────────────────────────────────────────


def _format_amount_short(value: float) -> str:
    """KPI 카드용 ₩ 축약."""
    return format_krw_compact(value, jo_digits=2, eok_digits=2, man_digits=1)


def _format_pct(value: float) -> str:
    """비율(%) 표시 — KPI 카드에서 활성 사용자/manual_rate 등에 사용."""
    return f"{value:.1f}"


def _format_count(value: float | int) -> str:
    """건수 1,000 단위 포매팅."""
    return f"{int(value):,}"


def _build_kpi_card(
    *,
    label: str,
    current_value: float,
    prior_value: float,
    unit: str | None,
    inverse: bool,
    value_fmt=None,
    tooltip: str | None = None,
    accent: str | None = None,
) -> str:
    """단일 KPI 카드 HTML 생성.

    Args:
        label: 카드 상단 라벨 (작은 회색).
        current_value: 당기 값 (숫자).
        prior_value: 전기 값 (숫자).
        unit: 값 뒤 단위 (예: "건", "%", "개"). None 이면 미표시.
        inverse: True 면 증가가 나쁜 방향 (이상 신호·High·수기·자기승인).
        value_fmt: 값 포매터 함수. None 이면 _format_count.
        tooltip: title 속성에 들어갈 도움말. None 이면 미표시.
        accent: 카드 좌측 보더 색상 (카테고리 구분용). None 이면 회색.
    """
    fmt = value_fmt or _format_count
    cur_text = fmt(current_value)
    pri_text = fmt(prior_value)

    diff = current_value - prior_value
    if prior_value == 0 and current_value == 0:
        delta_html = "<span class='comp-kpi-delta comp-kpi-delta-flat'>—</span>"
        prior_html = "전기 데이터 없음"
    elif prior_value == 0:
        # Why: 전기 0 인데 당기 값이 생긴 경우. 증감률은 정의 불가 → '신규' 배지.
        css = "comp-kpi-delta-up" if inverse else "comp-kpi-delta-down"
        delta_html = f"<span class='comp-kpi-delta {css}'>신규</span>"
        prior_html = f"전기 0{unit or ''}"
    else:
        pct = diff / prior_value * 100
        arrow = "▲" if pct > 0 else "▼" if pct < 0 else "—"
        # Why: 증가=빨강, 감소=초록 통일. inverse 인지 여부와 무관하게 시각적
        #      방향(빨강/초록)은 변화의 방향만 표현. 의미(좋다/나쁘다)는 라벨이 짊어진다.
        if abs(pct) < 0.05:
            css = "comp-kpi-delta-flat"
        elif pct > 0:
            css = "comp-kpi-delta-up"
        else:
            css = "comp-kpi-delta-down"
        delta_html = f"<span class='comp-kpi-delta {css}'>{arrow} {abs(pct):.1f}%</span>"
        prior_html = f"전기 {pri_text}{unit or ''}"

    unit_html = f"<span class='comp-kpi-unit'>{unit}</span>" if unit else ""
    title_attr = f" title='{tooltip}'" if tooltip else ""
    style_attr = f" style='--accent:{accent};'" if accent else ""
    return (
        f"<div class='comp-kpi-card'{style_attr}{title_attr}>"
        f"<div class='comp-kpi-label'>{label}</div>"
        f"<div class='comp-kpi-row'>"
        f"<div class='comp-kpi-value'>{cur_text}{unit_html}</div>"
        f"{delta_html}"
        f"</div>"
        f"<div class='comp-kpi-prior'>{prior_html}</div>"
        f"</div>"
    )
