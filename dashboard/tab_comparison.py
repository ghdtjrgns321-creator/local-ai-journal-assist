"""전기 비교 탭 — 분석적 절차(ISA 520) flux analysis 시각화.

감사 표준 요건(분석적 절차)에 맞춰 네 소분류로 구성:
  ① 분석적 절차 (Flux)   — KPI 리본 + K-IFRS 카테고리 변동 + 월별 추세
  ② 계정과목 변동         — 변동 큰 계정 Top N + 신규/소멸 계정
  ③ 검토 신호 변동       — 검토 후보 등급 분포 + 룰별 신호 증감
  ④ PHASE2 보조 신호      — 영역별 신호 case·근거 강도·세부 탐지 증감

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
    risk_distribution_comparison,
    rule_violation_delta,
    top_changed_accounts_bar,
)
from dashboard.components.coa_categories import DERIVED_NET_INCOME_LABEL, category_label
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
    """전기 비교 탭 진입점 (최상위 탭 — Phase2 결과 우측).

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

    # PHASE2 overlay 는 DB 가 아닌 engagement 폴더의 JSON 이라 attach 컨텍스트 밖에서 로드.
    data.update(_collect_phase2_signal_data(ctx, current_batch, prior_db, prior_batch))

    _render_page(others, data)


# ── 페이지 구성 ────────────────────────────────────────────────


def _render_page(others, data: dict) -> None:
    """큰 제목 + sub-tabs(4) + 각 sub-tab 콘텐츠.

    Why: "전기 대비 변동 분석" 헤더 + KPI 16 그리드는 첫 sub-tab 에만 노출한다.
         다른 sub-tab 에서 KPI 헤더가 같이 보이면 시야가 분산되고,
         탭을 클릭해도 KPI 가 계속 고정된 것처럼 보이는 시각적 버그가 된다.
         "PHASE2 보조 신호" 는 통합 점수 비교가 아니라 영역별 보조 신호 증감만 노출.
    """
    st.markdown("## 전기 비교")

    sub_tabs = st.tabs(["전체 요약", "계정과목 변동", "검토 신호 변동", "PHASE2 보조 신호"])
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
    with sub_tabs[3]:
        _prior_selectbox(others, suffix="phase2")
        _render_phase2_subtab(data)


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
.comp-kpi-section { margin:0.25rem 0 0.8rem; }
.comp-kpi-section-header { display:flex; align-items:center; gap:0.5rem;
                           margin:0 0 0.45rem 0.15rem; }
.comp-kpi-section-dot { width:6px; height:6px; border-radius:999px; }
.comp-kpi-section-title { color:#374151; font-size:0.78rem; font-weight:600;
                          letter-spacing:0.06em; text-transform:uppercase; }
.comp-kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:0.55rem; }
.comp-kpi-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px;
                 padding:0.75rem 0.95rem; box-shadow:0 1px 2px rgba(15,23,42,0.04);
                 border-left:3px solid var(--accent,#E5E7EB); }
.comp-kpi-label { color:#6B7280; font-size:0.75rem; font-weight:500;
                  letter-spacing:0.01em; margin-bottom:0.35rem; }
.comp-kpi-row { display:flex; align-items:baseline; justify-content:space-between;
                gap:0.4rem; }
.comp-kpi-value { color:#111827; font-size:1.4rem; font-weight:700;
                  letter-spacing:-0.02em; line-height:1.15; }
.comp-kpi-unit { font-size:0.8rem; font-weight:500; color:#6B7280; margin-left:2px; }
.comp-kpi-delta { font-size:0.74rem; font-weight:600; padding:2px 7px;
                  border-radius:999px; white-space:nowrap; }
.comp-kpi-delta-up   { background:#FEE2E2; color:#B91C1C; }
.comp-kpi-delta-down { background:#DCFCE7; color:#15803D; }
.comp-kpi-delta-flat { background:#F3F4F6; color:#4B5563; }
.comp-kpi-prior { color:#9CA3AF; font-size:0.72rem; margin-top:0.4rem;
                  border-top:1px dashed #F1F3F5; padding-top:0.35rem; }
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

    # ── 검토 신호 ──
    section_risk = [
        _build_kpi_card(
            label="이상 신호 전표",
            current_value=int(_v(cur_row, "anomaly_count")),
            prior_value=int(_v(pri_row, "anomaly_count")),
            unit="건",
            inverse=True,
            tooltip="risk_level ≠ Normal 전표 수",
            accent=accent["위험"],
        ),
        _build_kpi_card(
            label="High 우선검토 전표",
            current_value=int(_v(cur_row, "high_count")),
            prior_value=int(_v(pri_row, "high_count")),
            unit="건",
            inverse=True,
            accent=accent["위험"],
        ),
        _build_kpi_card(
            label="이상 신호율",
            current_value=_v(cur_row, "anomaly_rate"),
            prior_value=_v(pri_row, "anomaly_rate"),
            unit="%",
            inverse=True,
            value_fmt=_format_pct,
            tooltip="이상 신호 전표 / 전체 전표 × 100 — 전표 증가에 정규화한 검토 신호율",
            accent=accent["위험"],
        ),
        _build_kpi_card(
            label="발동 룰 종류",
            current_value=int(_v(cur_row, "rule_kind_count")),
            prior_value=int(_v(pri_row, "rule_kind_count")),
            unit="개",
            inverse=True,
            tooltip="flagged_rules 에 등장한 distinct rule_code 수 (검토 시나리오 다양성)",
            accent=accent["위험"],
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

    st.markdown(_KPI_CARD_CSS, unsafe_allow_html=True)
    _render_kpi_section("거래 규모", accent["거래"], section_trade)
    _render_kpi_section("검토 신호", accent["위험"], section_risk)
    _render_kpi_section("통제 환경", accent["통제"], section_control)
    _render_kpi_section("조직 · 마스터", accent["마스터"], section_master)


def _render_kpi_section(title: str, color: str, cards: list[str]) -> None:
    """카테고리 헤더 + 4 카드 그리드 한 섹션 출력."""
    html = (
        "<div class='comp-kpi-section'>"
        "<div class='comp-kpi-section-header'>"
        f"<span class='comp-kpi-section-dot' style='background:{color};'></span>"
        f"<span class='comp-kpi-section-title'>{title}</span>"
        "</div>"
        "<div class='comp-kpi-grid'>" + "".join(cards) + "</div>"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


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
    """소분류 ③ — 검토 후보 등급 분포 + 룰별 검토 신호 증감."""
    section_risk = st.container(border=True)
    section_risk.markdown("##### 검토 후보 등급 분포 비교")
    section_risk.caption(
        "룰 기반 review signal 등급(High/Medium/Low/Normal) 비율의 당기·전기 분포입니다. "
        "High·Medium 비중이 커진 쪽은 감사 표본 확장 후보입니다."
    )
    section_risk.plotly_chart(
        risk_distribution_comparison(data["current_risk"], data["prior_risk"]),
        width="stretch",
        key="comparison_risk_donut",
    )

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
        "current_risk": _query_risk_dist(conn, current_batch=current_batch, schema=None),
        "prior_risk": _query_risk_dist(conn, current_batch=prior_batch, schema=alias),
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


def _query_risk_dist(
    conn: duckdb.DuckDBPyConnection,
    *,
    current_batch: str,
    schema: str | None,
) -> pd.DataFrame:
    """위험등급 분포 — GROUP BY risk_level."""
    table = f"{schema}.general_ledger" if schema else "general_ledger"
    sql = f"""
        SELECT risk_level, COUNT(*) AS cnt
        FROM {table}
        WHERE upload_batch_id = ? AND risk_level IS NOT NULL
        GROUP BY risk_level ORDER BY risk_level
    """
    return conn.execute(sql, [current_batch]).fetchdf()


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


# ── ④ PHASE2 보조 신호 ─────────────────────────────────────────
#
# Why: PHASE2 통합 점수의 전기 대비 변화가 아니라, family(분석 영역) 별 보조 신호의
#      증감을 본다. PHASE2 철학상 통합 위험 등급화·순위 비교는 의미가 없고,
#      "어느 영역에서 검토 후보가 늘었는가"가 감사인이 받아 가야 할 정보다.
#      (docs/PHASE2_GOVERNANCE_DESIGN.md 결정 8, PHASE2_TIMESERIES_ROLE_LOCK 결정 9)

# 표시 순서는 active ranker 4개(중복/관계망/관계사/시점) 다음에 VAE.
# VAE 는 ml_quantile 단위라 strong/moderate/weak 축과 측정 단위가 다르다.
_PHASE2_FAMILY_ORDER: tuple[str, ...] = (
    "duplicate",
    "relational",
    "intercompany",
    "timeseries",
    "unsupervised",
)
_PHASE2_FAMILY_KO: dict[str, str] = {
    "duplicate": "중복 전표",
    "relational": "관계망 이상",
    "intercompany": "관계사 매칭",
    "timeseries": "시점 이상 (보조)",
    "unsupervised": "VAE 통계 이상",
}
_PHASE2_FAMILY_HINT: dict[str, str] = {
    "duplicate": "중복·분할·반복 전표 후보 변화",
    "relational": "희귀 거래관계·휴면 재활성 후보 변화",
    "intercompany": "미매칭·금액·시차·순환 거래 후보 변화",
    "timeseries": "결산·시점 맥락 변화 (단독 ranker 아님)",
    "unsupervised": "VAE 통계 이상 패턴 변화",
}
_PHASE2_TIER_ORDER: tuple[str, ...] = ("strong", "moderate", "weak", "ml_quantile")
_PHASE2_TIER_KO: dict[str, str] = {
    "strong": "Strong",
    "moderate": "Moderate",
    "weak": "Weak",
    "ml_quantile": "ML Quantile",
}


def _collect_phase2_signal_data(
    ctx,
    current_batch: str,
    prior_db_path,
    prior_batch: str,
) -> dict:
    """당기/전기 PHASE2 overlay 를 한 번에 로드해 dict 로 반환.

    Why: overlay 는 DB 가 아니라 engagement 폴더의 JSON 파일에 저장된다
    (``phase2_overlays/<batch_id>.json``). 전기 ctx 를 만들어 동일 로더를 재사용한다.
    overlay 로딩이 실패하거나 파일이 없어도 sub-tab 진입은 가능해야 하므로 status 도 함께 반환.
    """
    from types import SimpleNamespace

    from src.services.phase2_overlay_store import (
        OverlayStatus,
        load_phase2_overlay_status,
    )

    current_result = load_phase2_overlay_status(ctx=ctx, batch_id=current_batch)
    # Why: prior engagement 의 db_path 만 있으면 overlay_dir 해석이 가능하다.
    #      별도 CompanyContext 구성 없이 db_path 만 들고 있는 stub 으로 충분.
    prior_stub = SimpleNamespace(db_path=prior_db_path)
    prior_result = load_phase2_overlay_status(ctx=prior_stub, batch_id=prior_batch)

    return {
        "phase2_current_overlays": (
            current_result.overlays if current_result.status == OverlayStatus.LOADED else None
        ),
        "phase2_prior_overlays": (
            prior_result.overlays if prior_result.status == OverlayStatus.LOADED else None
        ),
        "phase2_current_status": current_result.status,
        "phase2_prior_status": prior_result.status,
    }


def _family_signal_has_positive(entry: dict) -> bool:
    """family_contribution 1개가 후보 신호로 카운트될 자격이 있는지.

    Why: ``dashboard.tab_phase2._family_contribution_has_positive_signal`` 과
    동일 로직을 본 모듈에 옮겨 두어 외부 의존을 피한다. IC01 review-only 처럼
    confirmed score 로 승격하지 않는 신호는 ``review_only_count`` 메타가 있을 때만
    후보 신호로 본다. 일반 family 는 양수 score/ECDF 를 후보 신호로 본다.
    """
    try:
        if int(entry.get("review_only_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    checked = False
    for key in ("score", "ecdf", "raw_score", "normalized_score"):
        if key not in entry:
            continue
        checked = True
        try:
            if float(entry.get(key) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return not checked


def _phase2_family_signal_counts(overlays: list[dict] | None) -> dict[str, int]:
    """family → 양수 신호 보유 case 수."""
    counts: dict[str, int] = dict.fromkeys(_PHASE2_FAMILY_ORDER, 0)
    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            family = str(entry.get("family") or "")
            if family in counts and _family_signal_has_positive(entry):
                counts[family] += 1
    return counts


def _phase2_tier_counts_per_family(
    overlays: list[dict] | None,
) -> dict[str, dict[str, int]]:
    """family → tier → case 수.

    Why: VAE(unsupervised) 는 family-level evidence_tier 가 None 인 경우가 많고,
         sub_detectors[*].evidence_tier 만 ``ml_quantile`` 로 마킹된다. 이 경우
         unsupervised 의 ml_quantile 카운터에 +1 하여 통계적 이상치 신호로 노출한다.
    """
    out: dict[str, dict[str, int]] = {
        family: dict.fromkeys(_PHASE2_TIER_ORDER, 0) for family in _PHASE2_FAMILY_ORDER
    }
    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            family = str(entry.get("family") or "")
            if family not in out or not _family_signal_has_positive(entry):
                continue
            tier = str(entry.get("evidence_tier") or "").strip().lower()
            if tier in out[family]:
                out[family][tier] += 1
                continue
            if family == "unsupervised":
                # 통계적 이상치는 sub_detector 의 ml_quantile 로만 표시되는 경우가 있음.
                for sub in entry.get("sub_detectors") or []:
                    sub_tier = str(sub.get("evidence_tier") or "").strip().lower()
                    if sub_tier == "ml_quantile":
                        out[family]["ml_quantile"] += 1
                        break
    return out


def _phase2_subdetector_counts(
    overlays: list[dict] | None,
) -> dict[tuple[str, str], int]:
    """(family, sub_detector_code) → case 수.

    SUB_DETECTORS 에 등록된 canonical 코드만 카운트하고 VAE-01 은 별도 추가.
    """
    from dashboard.components.phase2_subdetector_grid import SUB_DETECTORS

    counts: dict[tuple[str, str], int] = {}
    for family, code, _label in SUB_DETECTORS:
        counts[(family, code)] = 0
    counts[("unsupervised", "VAE-01")] = 0

    for overlay in overlays or []:
        for entry in overlay.get("family_contributions") or []:
            family = str(entry.get("family") or "")
            for sub in entry.get("sub_detectors") or []:
                code = str(sub.get("code") or "")
                key = (family, code)
                if key in counts:
                    counts[key] += 1
    return counts


def _build_phase2_family_delta_frame(
    cur_counts: dict[str, int],
    pri_counts: dict[str, int],
    cur_case_total: int,
    pri_case_total: int,
) -> pd.DataFrame:
    """영역별 신호 case 증감 표 — 점유율 변화(pp) 포함."""
    rows: list[dict[str, object]] = []
    for family in _PHASE2_FAMILY_ORDER:
        cur = cur_counts.get(family, 0)
        pri = pri_counts.get(family, 0)
        cur_share = (cur / cur_case_total * 100.0) if cur_case_total else 0.0
        pri_share = (pri / pri_case_total * 100.0) if pri_case_total else 0.0
        rows.append(
            {
                "분석 영역": _PHASE2_FAMILY_KO[family],
                "당기 신호 case": cur,
                "전기 신호 case": pri,
                "증감(case)": cur - pri,
                "당기 점유율(%)": round(cur_share, 1),
                "전기 점유율(%)": round(pri_share, 1),
                "증감(pp)": round(cur_share - pri_share, 1),
                "해석": _PHASE2_FAMILY_HINT[family],
            }
        )
    return pd.DataFrame(rows)


def _build_phase2_tier_delta_matrix(
    cur_tier: dict[str, dict[str, int]],
    pri_tier: dict[str, dict[str, int]],
) -> pd.DataFrame:
    """근거 강도 × 분석 영역 case 증감 매트릭스 (값 = 당기 - 전기)."""
    rows: list[dict[str, object]] = []
    for tier in _PHASE2_TIER_ORDER:
        row: dict[str, object] = {"근거 강도": _PHASE2_TIER_KO[tier]}
        for family in _PHASE2_FAMILY_ORDER:
            cur = cur_tier.get(family, {}).get(tier, 0)
            pri = pri_tier.get(family, {}).get(tier, 0)
            row[_PHASE2_FAMILY_KO[family]] = cur - pri
        rows.append(row)
    return pd.DataFrame(rows)


def _build_phase2_subdetector_delta_for_family(
    family: str,
    cur_sub: dict[tuple[str, str], int],
    pri_sub: dict[tuple[str, str], int],
) -> pd.DataFrame:
    """family 별 sub-detector 증감 표."""
    from dashboard.components.phase2_subdetector_grid import SUB_DETECTORS

    if family == "unsupervised":
        codes_labels: list[tuple[str, str]] = [
            ("VAE-01", "audit_vae_reconstruction"),
        ]
    else:
        codes_labels = [(code, label) for (f, code, label) in SUB_DETECTORS if f == family]
    rows: list[dict[str, object]] = []
    for code, label in codes_labels:
        cur = cur_sub.get((family, code), 0)
        pri = pri_sub.get((family, code), 0)
        rows.append(
            {
                "세부 탐지 코드": code,
                "탐지 내용": label,
                "당기 case": cur,
                "전기 case": pri,
                "증감(case)": cur - pri,
            }
        )
    return pd.DataFrame(rows)


def _render_phase2_summary_cards(
    cur_counts: dict[str, int],
    pri_counts: dict[str, int],
    cur_tier: dict[str, dict[str, int]],
    pri_tier: dict[str, dict[str, int]],
) -> None:
    """상단 요약 카드 3개 — 신호 case / Strong 근거 / 변화 최대 영역."""
    cur_total = sum(cur_counts.values())
    pri_total = sum(pri_counts.values())
    cur_strong = sum(t.get("strong", 0) for t in cur_tier.values())
    pri_strong = sum(t.get("strong", 0) for t in pri_tier.values())

    deltas = {f: cur_counts.get(f, 0) - pri_counts.get(f, 0) for f in _PHASE2_FAMILY_ORDER}
    top_family = max(deltas, key=lambda key: deltas[key])
    top_delta = deltas[top_family]
    top_ko = _PHASE2_FAMILY_KO[top_family]
    top_label = "가장 증가한 영역" if top_delta >= 0 else "가장 감소한 영역"

    accent = "#7C3AED"  # violet-600 — PHASE2 통제 카테고리와 동일 톤
    cards = [
        _build_kpi_card(
            label="PHASE2 보조 신호 case",
            current_value=cur_total,
            prior_value=pri_total,
            unit="건",
            inverse=False,
            tooltip="각 영역 family_contributions 양수 신호 case 합계 (영역 중복 포함)",
            accent=accent,
        ),
        _build_kpi_card(
            label="Strong 근거 case",
            current_value=cur_strong,
            prior_value=pri_strong,
            unit="건",
            inverse=False,
            tooltip="evidence_tier=Strong 인 family contribution case 합계",
            accent=accent,
        ),
    ]

    # Why: 3번째 카드는 "변화 최대 영역" — 표준 KPI 카드(value/delta) 구조 대신
    #      라벨에 영역명을 두고 delta 배지에 증감값을 넣는 변형 카드를 사용.
    if top_delta > 0:
        delta_css = "comp-kpi-delta-up"
        sign = "+"
    elif top_delta < 0:
        delta_css = "comp-kpi-delta-down"
        sign = ""  # 음수 부호는 숫자에 이미 포함
    else:
        delta_css = "comp-kpi-delta-flat"
        sign = "±"
    top_card = (
        f"<div class='comp-kpi-card' style='--accent:{accent};'>"
        f"<div class='comp-kpi-label'>{top_label}</div>"
        f"<div class='comp-kpi-row'>"
        f"<div class='comp-kpi-value' style='font-size:1.05rem;'>{top_ko}</div>"
        f"<span class='comp-kpi-delta {delta_css}'>{sign}{top_delta:,}건</span>"
        f"</div>"
        f"<div class='comp-kpi-prior'>"
        f"당기 {cur_counts.get(top_family, 0):,}건 / 전기 {pri_counts.get(top_family, 0):,}건"
        f"</div>"
        f"</div>"
    )
    cards.append(top_card)

    st.markdown(_KPI_CARD_CSS, unsafe_allow_html=True)
    st.markdown(
        "<div class='comp-kpi-grid' style='grid-template-columns:repeat(3,1fr);'>"
        + "".join(cards)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_phase2_subtab(data: dict) -> None:
    """소분류 ④ — PHASE2 영역별 보조 신호 전기 비교.

    Why: PHASE2 통합 점수·통합 위험 등급은 비교 대상이 아니다. 영역별 보조 신호의
         case·근거 강도·세부 탐지 변화만 노출해 검토 후보 확대 신호로 해석한다.
    """
    cur_overlays = data.get("phase2_current_overlays")
    pri_overlays = data.get("phase2_prior_overlays")
    cur_status = data.get("phase2_current_status")
    pri_status = data.get("phase2_prior_status")

    st.caption(
        "PHASE2 는 통합 점수로 비교하지 않고, 감사인이 놓치기 쉬운 비선형·우회적 "
        "이상 패턴 후보가 어느 분석 영역에서 증가·감소했는지 비교합니다. "
        "**증가 = 검토 후보 확대 신호**이며, 위험 확정이 아닙니다."
    )

    # ── overlay 부재 분기 ──
    if cur_overlays is None:
        st.info(
            "당기 PHASE2 overlay 가 없습니다. Phase 2 결과 탭에서 PHASE2 추론을 "
            f"먼저 실행하세요. (status: {cur_status or 'unknown'})"
        )
        return
    if pri_overlays is None:
        st.info(
            "전기 PHASE2 overlay 가 없어 보조 신호 전기 비교를 생성할 수 없습니다. "
            "전기 engagement 에서 PHASE2 를 실행한 뒤 다시 비교하세요. "
            f"(status: {pri_status or 'unknown'})"
        )
        return

    # ── 집계 ──
    cur_signals = _phase2_family_signal_counts(cur_overlays)
    pri_signals = _phase2_family_signal_counts(pri_overlays)
    cur_tier = _phase2_tier_counts_per_family(cur_overlays)
    pri_tier = _phase2_tier_counts_per_family(pri_overlays)
    cur_sub = _phase2_subdetector_counts(cur_overlays)
    pri_sub = _phase2_subdetector_counts(pri_overlays)

    # ── 상단 요약 카드 (3개) ──
    _render_phase2_summary_cards(cur_signals, pri_signals, cur_tier, pri_tier)

    # ── ① 영역별 신호 증감 표 ──
    section_family = st.container(border=True)
    section_family.markdown("##### 영역별 보조 신호 case 증감")
    section_family.caption(
        "case 단위 = PHASE1 case. 한 case 는 여러 영역에 동시에 후보 신호를 낼 수 있어 "
        "영역별 합계는 PHASE1 case 총수와 일치하지 않을 수 있습니다."
    )
    family_df = _build_phase2_family_delta_frame(
        cur_signals,
        pri_signals,
        len(cur_overlays),
        len(pri_overlays),
    )
    section_family.dataframe(
        family_df,
        hide_index=True,
        width="stretch",
        column_config={
            "당기 신호 case": st.column_config.NumberColumn(format="%,d"),
            "전기 신호 case": st.column_config.NumberColumn(format="%,d"),
            "증감(case)": st.column_config.NumberColumn(format="%+,d"),
            "당기 점유율(%)": st.column_config.NumberColumn(format="%.1f%%"),
            "전기 점유율(%)": st.column_config.NumberColumn(format="%.1f%%"),
            "증감(pp)": st.column_config.NumberColumn(format="%+.1f"),
        },
    )

    # ── ② 영역 × 근거 강도 매트릭스 ──
    section_tier = st.container(border=True)
    section_tier.markdown("##### 영역 × 근거 강도 case 증감")
    section_tier.caption(
        "행 = Strong / Moderate / Weak / ML Quantile, 열 = 분석 영역. "
        "값 = 당기 − 전기 case 수. VAE 는 통계적 이상치라 **ML Quantile 행으로만** 집계됩니다."
    )
    tier_matrix = _build_phase2_tier_delta_matrix(cur_tier, pri_tier)
    tier_column_config = {
        col: st.column_config.NumberColumn(format="%+,d")
        for col in tier_matrix.columns
        if col != "근거 강도"
    }
    section_tier.dataframe(
        tier_matrix,
        hide_index=True,
        width="stretch",
        column_config=tier_column_config,
    )

    # ── ③ 세부 탐지 증감 (영역별 expander) ──
    section_sub = st.container(border=True)
    section_sub.markdown("##### 세부 탐지별 case 증감")
    section_sub.caption(
        "각 영역의 sub-detector 단위 case 변화입니다. 영역을 펼쳐 어떤 패턴이 늘었는지 확인하세요."
    )
    for family in _PHASE2_FAMILY_ORDER:
        sub_df = _build_phase2_subdetector_delta_for_family(family, cur_sub, pri_sub)
        if sub_df.empty:
            continue
        with section_sub.expander(_PHASE2_FAMILY_KO[family], expanded=False):
            st.dataframe(
                sub_df,
                hide_index=True,
                width="stretch",
                column_config={
                    "당기 case": st.column_config.NumberColumn(format="%,d"),
                    "전기 case": st.column_config.NumberColumn(format="%,d"),
                    "증감(case)": st.column_config.NumberColumn(format="%+,d"),
                },
            )
