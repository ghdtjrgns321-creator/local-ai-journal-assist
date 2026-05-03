"""Engagement selection component."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import streamlit as st
from pydantic import ValidationError

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_EDA_PROFILE,
    KEY_ENGAGEMENT_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_COLUMN_DIFF,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_PREP_WARNINGS,
    KEY_INGEST_PREPARED_DF,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
    KEY_LOADED_FROM_DB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
)
from src.company.models import EngagementProfile, EngagementStatus

# Why: engagement 삭제 시 분석 결과/ingest 캐시/CompanyContext가 stale 상태로 남으면
#      이후 화면이 잘못된 데이터를 표시하므로, 한 번에 깨끗이 정리한다.
_ENGAGEMENT_SCOPED_KEYS: tuple[str, ...] = (
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_FEATURED_DATA,
    KEY_EDA_PROFILE,
    KEY_BATCH_ID,
    KEY_UPLOAD_COUNT,
    KEY_LOADED_FROM_DB,
    KEY_COMPANY_CONTEXT,
    KEY_INGEST_STAGE,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_COLUMN_DIFF,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_PREPARED_DF,
    KEY_INGEST_PREP_WARNINGS,
    "_ingest_file_key",
    "_ingest_source_hint",
    "_ingest_tmp_path",
    "_ingest_is_user_path",
    "_ingest_current_fy",
    "_ingest_prior_fy",
)


def _purge_engagement_caches(company_id: str, engagement_id: str) -> None:
    """삭제된 engagement에 묶인 session_state + ContextFactory 캐시 정리."""
    # 1) ContextFactory 메모리 캐시 무효화
    factory = st.session_state.get("_context_factory")
    if factory is not None:
        try:
            factory.invalidate(company_id, engagement_id)
        except Exception:
            pass

    # 2) 현재 선택된 engagement가 삭제 대상이라면 선택 해제
    if st.session_state.get(KEY_ENGAGEMENT_ID) == engagement_id:
        st.session_state.pop(KEY_ENGAGEMENT_ID, None)

    # 3) engagement-scope 분석/ingest 결과 캐시 제거
    for key in _ENGAGEMENT_SCOPED_KEYS:
        st.session_state.pop(key, None)

    # 4) Streamlit 글로벌 데이터 캐시 정리 (DataFrame 등)
    try:
        st.cache_data.clear()
    except Exception:
        pass

if TYPE_CHECKING:
    from src.company.repository import CompanyRepository


_STATUS_LABELS: dict[EngagementStatus, str] = {
    EngagementStatus.DRAFT: "Draft",
    EngagementStatus.IN_PROGRESS: "In Progress",
    EngagementStatus.COMPLETED: "Completed",
    EngagementStatus.ARCHIVED: "Archived",
}


def render_engagement_selector(
    company_id: str | None,
    repo: CompanyRepository,
) -> None:
    """Render the engagement selection page for a chosen company."""
    if company_id is None:
        st.info("먼저 회사를 선택하세요.")
        st.session_state.pop(KEY_COMPANY_ID, None)
        st.session_state.pop(KEY_ENGAGEMENT_ID, None)
        return

    try:
        profile = repo.get_company(company_id)
    except FileNotFoundError:
        st.error(f"회사 '{company_id}'를 찾을 수 없습니다.")
        st.session_state.pop(KEY_COMPANY_ID, None)
        st.session_state.pop(KEY_ENGAGEMENT_ID, None)
        return

    # Why: Streamlit 기본 gap(약 1rem)으로 title/caption/button/divider 사이가
    #      지나치게 비어 보여 한 HTML 블록으로 묶어 margin을 직접 제어한다.
    st.markdown(
        f"<div style='padding-bottom:0.25rem;'>"
        f"<h1 style='margin:0 0 0.2rem; font-size:1.875rem; font-weight:700; "
        f"color:#111827; letter-spacing:-0.025em;'>{profile.display_name}</h1>"
        f"<div style='color:#6B7280; font-size:0.82rem;'>"
        f"ID: {company_id} | 업종: {profile.industry or '-'}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    if st.button("회사 선택으로 돌아가기"):
        st.session_state.pop(KEY_COMPANY_ID, None)
        st.session_state.pop(KEY_ENGAGEMENT_ID, None)
        st.rerun()

    # Why: st.divider 기본 여백(상하 ~1rem씩)이 과도 → 얇은 inline hr + 작은 margin.
    st.markdown(
        "<hr style='margin:0.75rem 0 0.5rem; border:none; "
        "border-top:1px solid #E2E5E9;'>",
        unsafe_allow_html=True,
    )

    engagements = repo.list_engagements(company_id)
    if engagements:
        _render_engagement_list(engagements, company_id, repo)
    else:
        st.info("등록된 감사 연도가 없습니다. 아래에서 새 연도를 생성하세요.")

    _render_create_form(company_id, repo)


def _render_engagement_list(
    engagements: list[EngagementProfile],
    company_id: str,
    repo: CompanyRepository,
) -> None:
    """Show available engagements with select and delete actions."""
    cols = st.columns(3)
    for idx, eng in enumerate(engagements):
        with cols[idx % 3]:
            with st.container(border=True):
                status_label = _STATUS_LABELS.get(eng.status, str(eng.status))
                st.subheader(f"FY {eng.fiscal_year}")
                period = ""
                if eng.period_start and eng.period_end:
                    period = f"{eng.period_start} ~ {eng.period_end}"
                st.caption(f"상태: {status_label}" + (f" | {period}" if period else ""))

                btn_col, del_col = st.columns([2, 1])
                with btn_col:
                    if st.button("선택", key=f"sel_eng_{eng.engagement_id}"):
                        st.session_state[KEY_ENGAGEMENT_ID] = eng.engagement_id
                        st.rerun()
                with del_col:
                    confirm_key = f"_del_confirm_{eng.engagement_id}"
                    if st.session_state.get(confirm_key, False):
                        if st.button(
                            "확인 삭제",
                            key=f"del2_{eng.engagement_id}",
                            type="primary",
                        ):
                            try:
                                repo.delete_engagement(
                                    company_id, eng.engagement_id,
                                )
                            except PermissionError as exc:
                                st.error(
                                    f"파일 잠금으로 삭제 실패: {exc}. "
                                    "앱을 재시작 후 다시 시도하세요."
                                )
                            else:
                                _purge_engagement_caches(
                                    company_id, eng.engagement_id,
                                )
                            finally:
                                st.session_state.pop(confirm_key, None)
                            st.rerun()
                    else:
                        if st.button("삭제", key=f"del1_{eng.engagement_id}"):
                            st.session_state[confirm_key] = True
                            st.rerun()


def _render_create_form(company_id: str, repo: CompanyRepository) -> None:
    """Render the create-engagement form."""
    with st.expander("새 감사 연도 생성"):
        with st.form("create_engagement"):
            current_year = date.today().year
            fiscal_year = st.number_input(
                "회계연도",
                min_value=2000,
                max_value=2099,
                value=current_year,
            )

            col1, col2 = st.columns(2)
            with col1:
                p_start = st.date_input(
                    "감사 대상기간 시작일",
                    value=date(current_year, 1, 1),
                )
            with col2:
                p_end = st.date_input(
                    "감사 대상기간 종료일",
                    value=date(current_year, 12, 31),
                )

            engagement_id = f"fy{fiscal_year}"

            submitted = st.form_submit_button("생성", type="primary")
            if submitted:
                try:
                    profile = EngagementProfile(
                        engagement_id=engagement_id,
                        company_id=company_id,
                        fiscal_year=fiscal_year,
                        period_start=p_start,
                        period_end=p_end,
                    )
                    repo.create_engagement(company_id, profile)
                    st.session_state[KEY_ENGAGEMENT_ID] = profile.engagement_id
                    st.rerun()
                except FileExistsError:
                    st.error(f"'{engagement_id}' ID의 연도가 이미 존재합니다.")
                except ValidationError as exc:
                    first = exc.errors()[0]
                    st.error(f"입력값 오류 - {first['loc'][0]}: {first['msg']}")
                except Exception as exc:
                    st.error(f"생성 실패: {exc}")
