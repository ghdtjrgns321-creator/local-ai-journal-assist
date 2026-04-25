"""AI Audit Assistant — Streamlit 대시보드 메인 앱.

Usage: uv run streamlit run dashboard/app.py

RC-4 플로우:
  회사 선택 → 연도 선택 → 업로드/분석 → 5탭 (EDA, 요약, Benford, 탐색기, 연도비교)
  회사 등록 필수. 범용 모드 제거.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard._state import (
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_DEV_MODE,
    KEY_ENGAGEMENT_ID,
    KEY_INGEST_STAGE,
    KEY_LOADED_FROM_DB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
    init_state,
)
from dashboard.styles import inject_css
from src.company.repository import CompanyRepository
from src.context import ContextFactory
from src.db.connection import ConnectionManager
from src.services.batch_service import list_saved_batches, load_batch_into_state
from src.services.session_service import clear_company_selection, current_display_result

st.set_page_config(
    page_title="AI Audit Assistant",
    layout="wide",
    page_icon="🔍",
)
init_state()
inject_css()

_COMPANIES_DIR = Path("data/companies")
_repo = CompanyRepository(_COMPANIES_DIR)
_factory = ContextFactory(_repo)
_conn_mgr = ConnectionManager()

ss = st.session_state

if "_company_repo" not in ss:
    ss["_company_repo"] = _repo
if "_conn_mgr" not in ss:
    ss["_conn_mgr"] = _conn_mgr


def _reset_to_company_select() -> None:
    """회사 선택 화면으로 돌아가기 위한 state 리셋."""
    clear_company_selection(ss)
    st.rerun()


def _extract_file_name(upload_key: str) -> str:
    """upload_key에서 파일명만 추출.

    upload_key는 두 형태로 들어올 수 있다:
      1) `{basename}_{size}` — 업로드 직후 파이프라인 실행 경로
      2) 절대경로 또는 파일명 — DB에서 재로드된 경로 (size 없음)

    Why: `rsplit('_', 1)`로 무조건 자르면 `journal_entries_2022.csv`처럼 숫자가
    파일명에 포함된 경우 `_2022.csv`가 size로 오인되어 잘린다. 파일명만 취한 뒤,
    뒤에 붙은 `_숫자`만 선택적으로 제거한다.
    """
    if not upload_key:
        return "데이터"
    import re

    name = Path(upload_key).name or upload_key
    match = re.match(r"^(.+)_(\d+)$", name)
    if match:
        return match.group(1)
    return name


def _needs_ctx_refresh(ctx, company_id: str | None, engagement_id: str | None) -> bool:
    """현재 context가 선택된 ID와 불일치하면 True."""
    if ctx is None:
        return True
    if ctx.is_anonymous:
        return False
    return ctx.company_id != company_id or ctx.engagement_id != engagement_id


with st.sidebar:
    st.title("AI Audit Assistant")

    ctx = ss.get(KEY_COMPANY_CONTEXT)

    if ctx and not ctx.is_anonymous:
        try:
            profile = _repo.get_company(ctx.company_id)
            display_name = profile.display_name
        except FileNotFoundError:
            display_name = ctx.company_id
        st.caption(f"회사: {display_name} / {ctx.engagement_id}")
        if st.button("회사 변경"):
            _reset_to_company_select()
        with st.expander("회사 설정", expanded=False):
            from dashboard.components.company_manager import render_company_manager

            render_company_manager(ctx.company_id, _repo, _factory)
    elif ctx is None:
        st.caption("회사를 선택하세요")
        if st.button("회사 선택"):
            _reset_to_company_select()

    dev_mode = st.toggle(
        "개발 모드",
        value=ss.get(KEY_DEV_MODE, False),
        help="활성화 시 상세 오류 표시",
    )
    ss[KEY_DEV_MODE] = dev_mode

    result = current_display_result(ss)

    if result is not None:
        upload_key = ss.get(KEY_UPLOAD_COUNT, "")
        file_label = _extract_file_name(upload_key)
        st.caption(f"{file_label} | {len(result.data):,}행 | {result.elapsed:.1f}초")

        with st.expander("데이터 필터", expanded=False):
            from dashboard.components.filters import render_filters

            render_filters(result.data)

        if ss.get(KEY_LOADED_FROM_DB):
            st.caption("설정을 변경하려면 원본 파일을 다시 업로드해주세요")
        else:
            with st.expander("탐지 설정", expanded=False):
                from dashboard.components.preset_selector import render_preset_selector
                from dashboard.components.rule_panel import render_rule_panel
                from dashboard.components.threshold_sidebar import render_threshold_sidebar

                render_preset_selector()
                render_threshold_sidebar(show_admin=dev_mode)
                render_rule_panel(show_admin=dev_mode)

            from dashboard.components._redetect import render_apply_button

            render_apply_button()


company_id = ss.get(KEY_COMPANY_ID)
engagement_id = ss.get(KEY_ENGAGEMENT_ID)
ctx = ss.get(KEY_COMPANY_CONTEXT)
result = current_display_result(ss)

if company_id is None:
    from dashboard.page_company import render_company_page

    render_company_page(_repo)
    st.stop()

if engagement_id is None:
    from dashboard.components.engagement_selector import render_engagement_selector

    render_engagement_selector(company_id, _repo)
    st.stop()

if _needs_ctx_refresh(ctx, company_id, engagement_id):
    ctx = _factory.create(company_id, engagement_id)
    ss[KEY_COMPANY_CONTEXT] = ctx

if result is None:
    force_upload = ss.pop("_force_upload", False)

    conn = _conn_mgr.get(str(ctx.db_path))
    batches = list_saved_batches(conn)

    if not batches.empty and not force_upload:
        latest = batches.iloc[0]
        bid = latest["upload_batch_id"]
        progress = st.progress(0, text="이전 분석 결과 불러오는 중...")
        try:
            progress.progress(30, text="DB에서 데이터 조회 중...")
            load_batch_into_state(ss, conn, bid)
            progress.progress(70, text="탐지 결과 복원 중...")
            progress.progress(100, text="완료!")
            st.rerun()
        except Exception:
            progress.empty()
            st.warning("이전 결과 로드 실패 — 새 파일을 업로드하세요.")
    else:
        if not batches.empty:
            from dashboard.components.batch_selector import render_batch_selector

            render_batch_selector(conn)
            st.divider()
        from dashboard.components.data_uploader import render_uploader

        render_uploader()
        st.stop()

prep_result = ss.get(KEY_PREP_RESULT)
phase1_result = ss.get(KEY_PHASE1_RESULT)
phase2_result = ss.get(KEY_PHASE2_RESULT)
display_result = current_display_result(ss)
if display_result is None:
    st.stop()

col_info, col_btn = st.columns([4, 1])
with col_info:
    upload_key = ss.get(KEY_UPLOAD_COUNT, "")
    file_label = _extract_file_name(upload_key)
    st.markdown(f"### {file_label}")
with col_btn:
    if st.button("다른 파일 분석", use_container_width=True):
        ss.pop(KEY_PREP_RESULT, None)
        ss.pop(KEY_PHASE1_RESULT, None)
        ss.pop(KEY_PHASE2_RESULT, None)
        ss.pop(KEY_PIPELINE_RESULT, None)
        ss.pop(KEY_UPLOAD_COUNT, None)
        ss[KEY_LOADED_FROM_DB] = False
        ss[KEY_INGEST_STAGE] = "UPLOAD"
        ss["_force_upload"] = True
        st.rerun()
st.divider()

from dashboard.tab_data_quality import render as render_data_quality
from dashboard.tab_findings import render as render_findings
from dashboard.tab_overview import render as render_overview
from dashboard.tab_phase1 import render as render_phase1
from dashboard.tab_phase2 import render as render_phase2

tabs = st.tabs(["개요", "데이터 탐색", "룰 위반", "이상 탐지"])
with tabs[0]:
    render_overview(display_result)
with tabs[1]:
    render_data_quality(display_result)
with tabs[2]:
    if phase1_result is None:
        render_phase1(prep_result or display_result, phase1_result)
    else:
        render_findings(phase1_result)
with tabs[3]:
    render_phase2(prep_result or display_result, phase2_result)
