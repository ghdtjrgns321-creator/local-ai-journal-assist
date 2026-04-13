"""연도(Engagement) 선택 컴포넌트 (RC-4-3).

회사 선택 후 연도 목록 표시 + 새 연도 생성 UI.
ID 설정만 담당하고, Context 생성은 app.py에서 수행한다 (SRP).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_COMPANY_ID, KEY_ENGAGEMENT_ID
from pydantic import ValidationError

from src.company.models import EngagementProfile, EngagementStatus

if TYPE_CHECKING:
    from src.company.repository import CompanyRepository

# Why: 상태 라벨 한국어 매핑
_STATUS_LABELS: dict[EngagementStatus, str] = {
    EngagementStatus.DRAFT: "초안",
    EngagementStatus.IN_PROGRESS: "진행 중",
    EngagementStatus.COMPLETED: "완료",
    EngagementStatus.ARCHIVED: "보관",
}


def render_engagement_selector(company_id: str, repo: CompanyRepository) -> None:
    """연도 선택 화면. company_id 설정 후, engagement_id 미설정일 때 호출."""
    try:
        profile = repo.get_company(company_id)
    except FileNotFoundError:
        st.error(f"회사 '{company_id}'를 찾을 수 없습니다.")
        st.session_state.pop(KEY_COMPANY_ID, None)
        return

    st.title(f"{profile.display_name}")
    st.caption(f"ID: {company_id} · 산업: {profile.industry or '-'}")

    if st.button("← 회사 선택으로 돌아가기"):
        st.session_state.pop(KEY_COMPANY_ID, None)
        st.rerun()

    st.divider()

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
    """연도 목록 — 연도/상태/기간 표시 + 삭제."""
    cols = st.columns(3)
    for idx, eng in enumerate(engagements):
        with cols[idx % 3]:
            with st.container(border=True):
                status_label = _STATUS_LABELS.get(eng.status, str(eng.status))
                st.subheader(f"FY {eng.fiscal_year}")
                period = ""
                if eng.period_start and eng.period_end:
                    period = f"{eng.period_start} ~ {eng.period_end}"
                st.caption(f"상태: {status_label}" + (f" · {period}" if period else ""))

                btn_col, del_col = st.columns([2, 1])
                with btn_col:
                    if st.button("선택", key=f"sel_eng_{eng.engagement_id}"):
                        st.session_state[KEY_ENGAGEMENT_ID] = eng.engagement_id
                        st.rerun()
                with del_col:
                    # Why: 2단계 확인 — 실수로 삭제 방지. session_state 토글 방식.
                    confirm_key = f"_del_confirm_{eng.engagement_id}"
                    if st.session_state.get(confirm_key, False):
                        if st.button(
                            "정말 삭제",
                            key=f"del2_{eng.engagement_id}",
                            type="primary",
                        ):
                            repo.delete_engagement(company_id, eng.engagement_id)
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                    else:
                        if st.button(
                            "삭제",
                            key=f"del1_{eng.engagement_id}",
                        ):
                            st.session_state[confirm_key] = True
                            st.rerun()


def _render_create_form(company_id: str, repo: CompanyRepository) -> None:
    """새 감사 연도 생성 폼."""
    with st.expander("새 감사 연도 생성"):
        with st.form("create_engagement"):
            current_year = date.today().year
            fiscal_year = st.number_input(
                "회계연도", min_value=2000, max_value=2099, value=current_year,
            )

            col1, col2 = st.columns(2)
            with col1:
                p_start = st.date_input(
                    "감사 대상기간 시작일", value=date(current_year, 1, 1),
                )
            with col2:
                p_end = st.date_input(
                    "감사 대상기간 종료일", value=date(current_year, 12, 31),
                )

            # Why: Engagement ID 자동 생성 — 오타/중복 방지
            eid = f"fy{fiscal_year}"

            submitted = st.form_submit_button("생성", type="primary")
            if submitted:
                try:
                    profile = EngagementProfile(
                        engagement_id=eid,
                        company_id=company_id,
                        fiscal_year=fiscal_year,
                        period_start=p_start,
                        period_end=p_end,
                    )
                    repo.create_engagement(company_id, profile)
                    st.session_state[KEY_ENGAGEMENT_ID] = profile.engagement_id
                    st.rerun()
                except FileExistsError:
                    st.error(f"'{eid}' ID의 연도가 이미 존재합니다.")
                except ValidationError as e:
                    first = e.errors()[0]
                    st.error(f"입력값 오류 — {first['loc'][0]}: {first['msg']}")
                except Exception as e:
                    st.error(f"생성 실패: {e}")
