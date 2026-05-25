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
    KEY_PENDING_RESULT_TAB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
    PAGE_COMPANY_SETTINGS,
    PAGE_COMPARISON,
    PAGE_OVERVIEW,
    PAGE_PHASE1,
    PAGE_PHASE2,
    PAGE_REVIEW_QUEUE,
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
from src.db.connection import get_connection_manager
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
_conn_mgr = get_connection_manager()

ss = st.session_state

KEY_TOP_LEVEL_NAV = "audit_top_level_nav"

if "_company_repo" not in ss:
    ss["_company_repo"] = _repo
if "_context_factory" not in ss:
    ss["_context_factory"] = _factory
existing_conn_mgr = ss.get("_conn_mgr")
if existing_conn_mgr is not None and existing_conn_mgr is not _conn_mgr:
    try:
        existing_conn_mgr.close_all()
    except Exception:
        pass
ss["_conn_mgr"] = _conn_mgr

hydrate_selection_from_query_params(ss, st.query_params)


def _reset_to_company_select() -> None:
    """회사 선택 화면으로 돌아가기 위한 state 리셋.

    Why: clear_company_selection 은 session_state 만 비운다. URL query params
         (?company=X&engagement=Y) 가 남아 있으면 다음 rerun 의
         hydrate_selection_from_query_params 가 URL 에서 다시 ID 를 복원해
         회사 선택 화면으로 돌아가지 못한다. ss 를 비운 직후 URL 도 동기화.
    """
    clear_company_selection(ss)
    sync_selection_to_query_params(ss, st.query_params)
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
    """Apply one-shot page transitions requested by analysis flows.

    Why: ``st.tabs`` 를 ``on_change="rerun"`` 로 쓰면 widget 이 ``st.session_state[key]``
         에 binding 되어, widget 렌더 전에 그 값을 덮어쓰면 강제 전환된다. 분석 완료
         직후 ``KEY_PENDING_RESULT_TAB`` 를 통해 다음 rerun 의 활성 탭을 지정한다.
    """
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

    run_after_save = render_pre_analysis_settings()
    if run_after_save:
        # Why: scrollIntoView(block:"center") 를 호출하면 폼 하단 버튼을 막 누른
        #      사용자를 다시 화면 중앙으로 끌어올려 "버튼 누르자마자 위로 튕긴다"
        #      는 시각적 충격을 만든다. 이미 사용자는 그 위치에 있으므로 강제
        #      스크롤 없이 인라인 진행 표시만 추가한다.
        st.info("Phase 1 분석을 시작했습니다. 완료 전까지 같은 화면에서 진행 상태를 표시합니다.")
        progress = st.progress(0, text="Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다.")
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
        from src.services.session_service import close_dashboard_connections

        close_dashboard_connections(ss)
        ctx = _factory.create(company_id, engagement_id)
        ss[KEY_COMPANY_CONTEXT] = ctx
        sync_selection_to_query_params(ss, st.query_params)

    ss[KEY_ACTIVE_RESULT_TAB] = _coerce_page(ss.get(KEY_ACTIVE_RESULT_TAB))

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
        if st.button("처음으로 돌아가기", width="stretch"):
            ss[KEY_ACTIVE_RESULT_TAB] = PAGE_OVERVIEW
            ss[KEY_PENDING_RESULT_TAB] = None
            _reset_to_company_select()
    st.divider()

    from dashboard.tab_comparison import render as render_comparison  # noqa: E402
    from dashboard.tab_overview import render_pre_analysis as render_overview  # noqa: E402
    from dashboard.tab_phase1 import render as render_phase1  # noqa: E402
    from dashboard.tab_phase2 import render as render_phase2  # noqa: E402
    from dashboard.tab_review_queue import render as render_review_queue  # noqa: E402

    phase2_result = ss.get(KEY_PHASE2_RESULT)

    # Why: on_change="rerun" 으로 widget 을 session_state[KEY_TOP_LEVEL_NAV] 에
    #      binding. 분석 완료 후 _consume_pending_page 가 widget 렌더 전에 그 값을
    #      덮어쓰면 강제 전환되고, 일반 탭 클릭은 streamlit 이 자동 동기화한다.
    default_top_tab = _coerce_page(ss.get(KEY_ACTIVE_RESULT_TAB, PAGE_OVERVIEW))
    if ss.get(KEY_TOP_LEVEL_NAV) not in RESULT_PAGES:
        ss[KEY_TOP_LEVEL_NAV] = default_top_tab
    # Why: st.tabs 는 nav 만 담당하고 콘텐츠는 active tab 만 렌더해
    #      6개 panel 의 동시 평가로 인한 로딩 지연을 제거한다.
    #      탭 widget 자체는 그대로 두므로 시각 UI 변경 없음.
    st.tabs(
        list(RESULT_PAGES),
        default=default_top_tab,
        key=KEY_TOP_LEVEL_NAV,
        on_change="rerun",
    )
    active_tab = ss.get(KEY_TOP_LEVEL_NAV, default_top_tab)
    ss[KEY_ACTIVE_RESULT_TAB] = active_tab

    if active_tab == PAGE_OVERVIEW:
        render_overview(prep_result or display_result)
    elif active_tab == PAGE_COMPANY_SETTINGS:
        _render_company_settings_page(ctx)
    elif active_tab == PAGE_PHASE1:
        render_phase1(prep_result or display_result, phase1_result)
    elif active_tab == PAGE_PHASE2:
        render_phase2(prep_result or display_result, phase2_result)
    elif active_tab == PAGE_COMPARISON:
        render_comparison(prep_result or display_result, _repo, _conn_mgr)
    elif active_tab == PAGE_REVIEW_QUEUE:
        render_review_queue(prep_result or display_result)


# Why: 페이지 분기마다 컨테이너 key 를 바꾸면 (upload → main 등) Streamlit 이
#      매 전환마다 컨테이너 DOM 을 폐기/재생성한다. 이러면 매핑 확인 직후
#      rerun 에서 컨테이너 식별자가 바뀌어 브라우저가 새 컨테이너를 최상단부터
#      그리며 화면이 위로 튕긴다.
#      과거 stacking 이슈는 `st.empty().container()` 래핑 때문이었고 현재는
#      `st.container(key=...)` 직접 호출로 제거됐다. 안정 key 로 통일해 같은
#      컨테이너 안에서 내용만 diff 되도록 한다.
with st.container(key="app_root"):
    _render_main()
