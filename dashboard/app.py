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
    KEY_ACTIVE_RESULT_TAB,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_DEV_MODE,
    KEY_ENGAGEMENT_ID,
    KEY_INGEST_STAGE,
    KEY_LOADED_FROM_DB,
    KEY_PENDING_RESULT_TAB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
    PAGE_OVERVIEW,
    PAGE_PHASE1,
    RESULT_PAGES,
    init_state,
)
from dashboard._url_state import (
    hydrate_selection_from_query_params,
    sync_selection_to_query_params,
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

KEY_TOP_LEVEL_NAV = "audit_top_level_nav"

if "_company_repo" not in ss:
    ss["_company_repo"] = _repo
if "_context_factory" not in ss:
    ss["_context_factory"] = _factory
if "_conn_mgr" not in ss:
    ss["_conn_mgr"] = _conn_mgr

hydrate_selection_from_query_params(ss, st.query_params)


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


def _recover_selection_from_context() -> None:
    """Restore company/engagement keys when a rerun drops them but context survives."""
    ctx = ss.get(KEY_COMPANY_CONTEXT)
    if ctx is None or getattr(ctx, "is_anonymous", True):
        return
    if not ss.get(KEY_COMPANY_ID):
        ss[KEY_COMPANY_ID] = ctx.company_id
    if not ss.get(KEY_ENGAGEMENT_ID):
        ss[KEY_ENGAGEMENT_ID] = ctx.engagement_id
    sync_selection_to_query_params(ss, st.query_params)


def _coerce_page(value: str | None) -> str:
    """Return a valid top-level page label."""
    return value if value in RESULT_PAGES else PAGE_OVERVIEW


def _consume_pending_page() -> None:
    """Apply one-shot page transitions requested by analysis flows."""
    pending_page = ss.pop(KEY_PENDING_RESULT_TAB, None)
    if pending_page is None:
        return
    if pending_page in RESULT_PAGES:
        ss[KEY_ACTIVE_RESULT_TAB] = pending_page
        ss[KEY_TOP_LEVEL_NAV] = pending_page


def _render_company_settings_page(ctx) -> None:
    """Render pre-analysis hyperparameter settings as a first-class main page."""
    st.markdown("### 분석 전 회사별 설정 변경")
    st.caption("Phase 1/2/3 분석에 적용할 회사별 감사 기준과 탐지 민감도를 관리합니다.")

    from dashboard.components.analysis_runner import run_phase_analysis
    from dashboard.components.pre_analysis_settings import render_pre_analysis_settings
    from dashboard.components.scroll_anchor import scroll_to_anchor

    run_after_save = render_pre_analysis_settings()
    if run_after_save:
        scroll_to_anchor("pre_analysis_phase1_actions")
        st.info("Phase 1 분석을 시작했습니다. 완료 전까지 같은 화면에서 진행 상태를 표시합니다.")
        progress = st.progress(0, text="Phase 1 룰 기반 감사 시작... 약 5분 정도 소요됩니다.")
        try:
            progress.progress(20, text="Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다.")
            run_phase_analysis(phase="phase1")
            progress.progress(100, text="완료")
        except Exception as e:
            st.error(f"Phase 1 실행 실패: {e}")
            return
        ss[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
        ss[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
        st.rerun()


_recover_selection_from_context()
_consume_pending_page()


with st.sidebar:
    ctx = ss.get(KEY_COMPANY_CONTEXT)

    dev_mode = st.toggle(
        "개발 모드",
        value=ss.get(KEY_DEV_MODE, False),
        help="활성화 시 상세 오류 표시",
    )
    ss[KEY_DEV_MODE] = dev_mode

    result = current_display_result(ss)

    if result is not None:
        if dev_mode and ctx is not None and not ctx.is_anonymous:
            from dashboard.components.dev_analysis_reset import render_dev_analysis_reset

            reset_conn = _conn_mgr.get(str(ctx.db_path))
            render_dev_analysis_reset(conn=reset_conn, state=ss)


def _render_main() -> None:
    """Render the routed main page inside one replaceable root container."""
    _recover_selection_from_context()
    company_id = ss.get(KEY_COMPANY_ID)
    engagement_id = ss.get(KEY_ENGAGEMENT_ID)
    ctx = ss.get(KEY_COMPANY_CONTEXT)
    result = current_display_result(ss)

    if company_id is None:
        from dashboard.page_company import render_company_page

        render_company_page(_repo)
        st.stop()
        return

    if engagement_id is None:
        if result is not None:
            st.warning(
                "분석 결과는 남아 있지만 감사연도 선택 상태가 비었습니다. "
                "회사 선택으로 돌아가 다시 연도를 선택해 주세요."
            )
            st.stop()
            return
        from dashboard.components.engagement_selector import render_engagement_selector

        render_engagement_selector(company_id, _repo)
        st.stop()
        return

    if _needs_ctx_refresh(ctx, company_id, engagement_id):
        ctx = _factory.create(company_id, engagement_id)
        ss[KEY_COMPANY_CONTEXT] = ctx
        sync_selection_to_query_params(ss, st.query_params)

    ss[KEY_ACTIVE_RESULT_TAB] = _coerce_page(ss.get(KEY_ACTIVE_RESULT_TAB))

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
                progress.empty()
            except Exception:
                progress.empty()
                st.warning("이전 결과 로드 실패 - 새 파일을 업로드하세요.")

        result = current_display_result(ss)
        if result is None:
            from dashboard.components.data_uploader import render_uploader

            render_uploader()
            st.stop()
            return

    prep_result = ss.get(KEY_PREP_RESULT)
    phase1_result = ss.get(KEY_PHASE1_RESULT)
    display_result = current_display_result(ss)
    if display_result is None:
        st.stop()
        return

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
            ss[KEY_ACTIVE_RESULT_TAB] = PAGE_OVERVIEW
            ss[KEY_TOP_LEVEL_NAV] = PAGE_OVERVIEW
            ss[KEY_PENDING_RESULT_TAB] = None
            ss[KEY_LOADED_FROM_DB] = False
            ss[KEY_INGEST_STAGE] = "UPLOAD"
            ss["_force_upload"] = True
            st.rerun()
    st.divider()

    from dashboard.tab_overview import render_pre_analysis as render_overview  # noqa: E402
    from dashboard.tab_phase1 import render as render_phase1  # noqa: E402
    from dashboard.tab_phase2 import render as render_phase2  # noqa: E402

    phase2_result = ss.get(KEY_PHASE2_RESULT)

    default_top_tab = _coerce_page(ss.get(KEY_ACTIVE_RESULT_TAB, PAGE_OVERVIEW))
    if ss.get(KEY_TOP_LEVEL_NAV) not in RESULT_PAGES:
        ss[KEY_TOP_LEVEL_NAV] = default_top_tab
    # Why: on_change="rerun" 을 켜면 탭 클릭마다 추가 rerun 이 실행되며,
    #      _main_slot 안의 직전 DOM 이 새 DOM 과 누적되어 같은 페이지가
    #      위/아래로 두 번 그려지는 잔상이 발생한다. st.tabs 는 모든 탭 콘텐츠를
    #      한 번에 렌더한 뒤 CSS 로 활성 탭만 보여주므로 별도 rerun 이 필요 없다.
    overview_tab, settings_tab, phase1_tab, phase2_tab = st.tabs(
        list(RESULT_PAGES),
        default=default_top_tab,
        key=KEY_TOP_LEVEL_NAV,
    )
    with overview_tab:
        render_overview(prep_result or display_result)
    with settings_tab:
        _render_company_settings_page(ctx)
    with phase1_tab:
        render_phase1(prep_result or display_result, phase1_result)
    with phase2_tab:
        render_phase2(prep_result or display_result, phase2_result)


# Why: st.empty().container() 슬롯 래핑이 streamlit 1.55 에서 직전 rerun 의
#      컨테이너를 폐기하지 못하고 새 컨테이너를 그 아래에 누적시키는 문제 발생.
#      페이지 종류(company/selector/main/upload)별로 고유 key 컨테이너를 사용해
#      페이지 전환 시 streamlit 이 다른 DOM 식별자로 인식해 직전 콘텐츠를
#      깨끗이 폐기하도록 한다. 같은 페이지 내 rerun 은 같은 key 라 streamlit
#      기본 diff 로 정상 갱신.
def _route_page_key() -> str:
    if not ss.get(KEY_COMPANY_ID):
        return "company"
    if not ss.get(KEY_ENGAGEMENT_ID):
        return "selector"
    if current_display_result(ss) is None:
        return "upload"
    return "main"


with st.container(key=f"app_root_{_route_page_key()}"):
    _render_main()

