"""AI Audit Assistant — Streamlit 대시보드 메인 앱.

Usage: uv run streamlit run dashboard/app.py

RC-4 플로우:
  회사 선택 → 연도 선택 → 업로드/분석 → 5탭 (EDA, 요약, Benford, 탐색기, 연도비교)
  범용 모드(회사 없이 즉시 분석) 하위 호환.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_DEV_MODE,
    KEY_EDA_PROFILE,
    KEY_ENGAGEMENT_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
    KEY_UPLOAD_COUNT,
    init_state,
)
from src.company.repository import CompanyRepository
from src.context import ContextFactory
from src.db.connection import ConnectionManager

st.set_page_config(
    page_title="AI Audit Assistant",
    layout="wide",
    page_icon="🔍",
)
init_state()

# ── 인프라 인스턴스 (모듈 레벨 — Streamlit re-run 시 재사용) ────
_COMPANIES_DIR = Path("data/companies")
_repo = CompanyRepository(_COMPANIES_DIR)
_factory = ContextFactory(_repo)
_conn_mgr = ConnectionManager()

ss = st.session_state

# Why: RC-5-2 — 컴포넌트(mapping_review 등)에서 repo에 접근할 수 있도록 공유
if "_company_repo" not in ss:
    ss["_company_repo"] = _repo


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _reset_to_company_select() -> None:
    """회사 선택 화면으로 돌아가기 위한 state 리셋."""
    for key in [
        KEY_COMPANY_ID, KEY_ENGAGEMENT_ID, KEY_COMPANY_CONTEXT,
        KEY_PIPELINE_RESULT, KEY_BATCH_ID, KEY_UPLOAD_COUNT,
        KEY_FEATURED_DATA, KEY_EDA_PROFILE,
    ]:
        ss.pop(key, None)
    ss[KEY_INGEST_STAGE] = "UPLOAD"
    st.rerun()


def _needs_ctx_refresh(ctx, company_id: str | None, engagement_id: str | None) -> bool:
    """현재 context가 선택된 ID와 불일치하면 True."""
    if ctx is None:
        return True
    if ctx.is_anonymous:
        return False
    return ctx.company_id != company_id or ctx.engagement_id != engagement_id


# ── Sidebar ──────────────────────────────────────────────────────

with st.sidebar:
    st.title("AI Audit Assistant")

    ctx = ss.get(KEY_COMPANY_CONTEXT)

    # Why: 회사/연도 정보 표시 + 전환 버튼 (RC-4-4)
    if ctx and not ctx.is_anonymous:
        try:
            profile = _repo.get_company(ctx.company_id)
            display_name = profile.display_name
        except FileNotFoundError:
            display_name = ctx.company_id
        st.caption(f"회사: {display_name} / {ctx.engagement_id}")
        if st.button("회사 변경"):
            _reset_to_company_select()
        # Why: 회사 관리 패널 (RC-4-2) — 분석 중에도 설정 편집 가능
        with st.expander("회사 설정", expanded=False):
            from dashboard.components.company_manager import render_company_manager
            render_company_manager(ctx.company_id, _repo, _factory)
    elif ctx and ctx.is_anonymous:
        st.caption("범용 모드")
        if st.button("회사 선택"):
            _reset_to_company_select()

    dev_mode = st.toggle(
        "개발 모드",
        value=ss.get(KEY_DEV_MODE, False),
        help="활성화 시 상세 오류 표시",
    )
    ss[KEY_DEV_MODE] = dev_mode

    result = ss.get(KEY_PIPELINE_RESULT)

    # 결과 있을 때만 필터/설정 표시
    if result is not None:
        upload_key = ss.get(KEY_UPLOAD_COUNT, "")
        file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
        st.caption(f"{file_label} | {len(result.data):,}행 | {result.elapsed:.1f}초")

        with st.expander("데이터 필터", expanded=False):
            from dashboard.components.filters import render_filters
            render_filters(result.data)

        with st.expander("탐지 설정", expanded=False):
            from dashboard.components.preset_selector import render_preset_selector
            render_preset_selector()

            from dashboard.components.threshold_sidebar import render_threshold_sidebar
            render_threshold_sidebar()

            from dashboard.components.rule_panel import render_rule_panel
            render_rule_panel()

        from dashboard.components._redetect import render_apply_button
        render_apply_button()

# ── Main: 분기 로직 ──────────────────────────────────────────────

company_id = ss.get(KEY_COMPANY_ID)
engagement_id = ss.get(KEY_ENGAGEMENT_ID)
ctx = ss.get(KEY_COMPANY_CONTEXT)
result = ss.get(KEY_PIPELINE_RESULT)

# 1) 회사 미선택 + 비범용 → 회사 선택 화면
if company_id is None and ctx is None:
    from dashboard.page_company import render_company_page
    render_company_page(_repo)
    st.stop()

# 2) 회사 선택됨 + 연도 미선택 (범용 모드 제외) → 연도 선택
if engagement_id is None and (ctx is None or not ctx.is_anonymous):
    from dashboard.components.engagement_selector import render_engagement_selector
    render_engagement_selector(company_id, _repo)
    st.stop()

# 3) context 동기화 (최초 생성 or ID 변경 시)
if _needs_ctx_refresh(ctx, company_id, engagement_id):
    ctx = _factory.create(company_id, engagement_id)
    ss[KEY_COMPANY_CONTEXT] = ctx

# 4) 결과 없음 → 업로드
if result is None:
    from dashboard.components.data_uploader import render_uploader
    render_uploader()
    st.stop()

# 5) 결과 있음 → 정보 바 + 5탭
col_info, col_btn = st.columns([4, 1])
with col_info:
    upload_key = ss.get(KEY_UPLOAD_COUNT, "")
    file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
    risk = result.risk_summary
    st.markdown(
        f"**{file_label}** — {len(result.data):,}행 · "
        f"High {risk.get('High', 0)} · Medium {risk.get('Medium', 0)} · "
        f"Low {risk.get('Low', 0)} · Normal {risk.get('Normal', 0)}"
    )
with col_btn:
    if st.button("다른 파일 분석"):
        ss.pop(KEY_PIPELINE_RESULT, None)
        ss.pop(KEY_UPLOAD_COUNT, None)
        ss[KEY_INGEST_STAGE] = "UPLOAD"
        st.rerun()

from dashboard import tab_benford, tab_eda
from dashboard.tab_comparison import render as render_comparison
from dashboard.tab_explorer import render as render_explorer
from dashboard.tab_summary import render as render_summary

tabs = st.tabs(["📊 EDA", "📋 요약", "🔔 Benford", "🔍 탐색기", "📈 연도 비교"])

with tabs[0]:
    tab_eda.render(result)
with tabs[1]:
    render_summary(result)
with tabs[2]:
    tab_benford.render(result)
with tabs[3]:
    render_explorer(result)
with tabs[4]:
    render_comparison(result, _repo, _conn_mgr)
