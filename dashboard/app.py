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
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_DEV_MODE,
    KEY_EDA_PROFILE,
    KEY_ENGAGEMENT_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_STAGE,
    KEY_LOADED_FROM_DB,
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

# Why: shadcn-inspired 커스텀 CSS 주입. set_page_config 직후, 다른 렌더링 전에 호출.
from dashboard.styles import inject_css
inject_css()

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
        KEY_FEATURED_DATA, KEY_EDA_PROFILE, KEY_LOADED_FROM_DB,
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

    result = ss.get(KEY_PIPELINE_RESULT)

    # 결과 있을 때만 필터/설정 표시
    if result is not None:
        upload_key = ss.get(KEY_UPLOAD_COUNT, "")
        file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
        st.caption(f"{file_label} | {len(result.data):,}행 | {result.elapsed:.1f}초")

        with st.expander("데이터 필터", expanded=False):
            from dashboard.components.filters import render_filters
            render_filters(result.data)

        # Why: DB에서 불러온 결과는 featured_data가 없으므로 재탐지 불가
        if ss.get(KEY_LOADED_FROM_DB):
            st.caption("설정을 변경하려면 원본 파일을 다시 업로드해주세요")
        else:
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

# 1) 회사 미선택 → 회사 선택 화면
if company_id is None and ctx is None:
    from dashboard.page_company import render_company_page
    render_company_page(_repo)
    st.stop()

# 2) 회사 선택됨 + 연도 미선택 → 연도 선택
if engagement_id is None:
    from dashboard.components.engagement_selector import render_engagement_selector
    render_engagement_selector(company_id, _repo)
    st.stop()

# 3) context 동기화 (최초 생성 or ID 변경 시)
if _needs_ctx_refresh(ctx, company_id, engagement_id):
    ctx = _factory.create(company_id, engagement_id)
    ss[KEY_COMPANY_CONTEXT] = ctx

# 4) 결과 없음 → 최신 배치 자동 로드 또는 업로드
if result is None:
    # Why: "다른 파일 분석" 클릭 시 자동 로드를 건너뛰고 업로드 화면으로 직행
    force_upload = ss.pop("_force_upload", False)

    from src.db.batch_reader import list_batches, load_batch

    conn = _conn_mgr.get(str(ctx.db_path))
    batches = list_batches(conn)

    if not batches.empty and not force_upload:
        # Why: 최신 배치를 자동 로드 — engagement 선택 즉시 결과 표시
        latest = batches.iloc[0]
        bid = latest["upload_batch_id"]
        progress = st.progress(0, text="이전 분석 결과 불러오는 중...")
        try:
            progress.progress(30, text="DB에서 데이터 조회 중...")
            loaded = load_batch(conn, bid)
            progress.progress(70, text="탐지 결과 복원 중...")
            ss[KEY_PIPELINE_RESULT] = loaded
            ss[KEY_BATCH_ID] = bid
            ss[KEY_UPLOAD_COUNT] = loaded.file_name or ""
            ss[KEY_LOADED_FROM_DB] = True
            ss[KEY_FEATURED_DATA] = None
            ss.pop(KEY_EDA_PROFILE, None)
            progress.progress(100, text="완료!")
            st.rerun()
        except Exception:
            progress.empty()
            st.warning("이전 결과 로드 실패 — 새 파일을 업로드하세요.")
    else:
        # Why: 배치 없거나 "다른 파일 분석" → 이전 배치 목록 + 업로더
        if not batches.empty:
            from dashboard.components.batch_selector import render_batch_selector
            render_batch_selector(conn)
            st.divider()
        from dashboard.components.data_uploader import render_uploader
        render_uploader()
        st.stop()

# 5) 결과 있음 → 정보 바 + 탭
# Why: 등급별 건수는 KPI/도넛에서 보여주므로 헤더는 Context(파일명+행수)만 표시.
col_info, col_btn = st.columns([4, 1])
with col_info:
    upload_key = ss.get(KEY_UPLOAD_COUNT, "")
    file_label = upload_key.rsplit("_", 1)[0] if upload_key else "데이터"
    total_rows = len(result.data)
    st.markdown(
        f"### {file_label} "
        f"<span style='font-size:0.55em; color:#6B7280; font-weight:400; "
        f"margin-left:8px;'>| 총 {total_rows:,}행 분석 완료</span>",
        unsafe_allow_html=True,
    )
with col_btn:
    if st.button("다른 파일 분석", use_container_width=True):
        ss.pop(KEY_PIPELINE_RESULT, None)
        ss.pop(KEY_UPLOAD_COUNT, None)
        ss[KEY_LOADED_FROM_DB] = False
        ss[KEY_INGEST_STAGE] = "UPLOAD"
        ss["_force_upload"] = True
        st.rerun()
st.divider()

from dashboard.tab_overview import render as render_overview
from dashboard.tab_data_quality import render as render_data_quality
from dashboard.tab_findings import render as render_findings

tabs = st.tabs(["개요", "데이터 탐색", "룰 위반", "이상 탐지"])

with tabs[0]:
    render_overview(result)
with tabs[1]:
    render_data_quality(result)
with tabs[2]:
    render_findings(result)
with tabs[3]:
    st.info("Phase 2에서 ML/DL 기반 이상 탐지 모델이 추가됩니다.")
    st.caption("VAE, XGBoost, 앙상블 등 비지도/지도 학습 탐지기 예정")
