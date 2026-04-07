"""회사 선택/생성 화면 (RC-4-1).

app.py에서 KEY_COMPANY_ID가 None일 때 렌더링된다.
회사 카드 목록 + 등록 폼 + "범용 모드" 버튼을 제공한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_COMPANY_CONTEXT, KEY_COMPANY_ID
from pydantic import ValidationError

from src.company.models import CompanyProfile
from src.context import ContextFactory

if TYPE_CHECKING:
    from src.company.repository import CompanyRepository


def render_company_page(repo: CompanyRepository) -> None:
    """회사 선택 메인 화면. company_id=None일 때 호출."""
    st.title("AI Audit Assistant")
    st.markdown("회사를 선택하거나, 범용 모드로 바로 분석을 시작하세요.")

    _render_anonymous_button()
    st.divider()

    companies = repo.list_companies()
    if companies:
        _render_company_cards(companies)
    else:
        st.info("등록된 회사가 없습니다. 아래에서 새 회사를 등록하세요.")

    _render_register_form(repo)


def _render_anonymous_button() -> None:
    """범용 모드 진입 — 회사 없이 즉시 분석."""
    if st.button("범용 모드로 시작", type="secondary", use_container_width=True):
        # Why: anonymous context를 생성하여 기존 동작(업로드→분석) 유지
        ctx = ContextFactory.create_anonymous()
        st.session_state[KEY_COMPANY_CONTEXT] = ctx
        st.rerun()


def _render_company_cards(companies: list[CompanyProfile]) -> None:
    """회사 카드 목록 — 3열 그리드."""
    cols = st.columns(3)
    for idx, profile in enumerate(companies):
        with cols[idx % 3]:
            with st.container(border=True):
                st.subheader(profile.display_name)
                st.caption(
                    f"ID: {profile.company_id}"
                    f" · 산업: {profile.industry or '-'}"
                    f" · ERP: {profile.erp_system or '-'}"
                )
                overrides_count = len(profile.settings_overrides)
                custom_flags = sum([
                    profile.has_custom_coa,
                    profile.has_custom_keywords,
                    profile.has_custom_rules,
                    profile.has_custom_risk_keywords,
                ])
                st.caption(f"설정 오버라이드 {overrides_count}개 · 커스텀 리소스 {custom_flags}개")

                if st.button("선택", key=f"select_{profile.company_id}"):
                    # Why: 함정2 방어 — rerun 전 state에 ID 즉시 저장
                    st.session_state[KEY_COMPANY_ID] = profile.company_id
                    st.rerun()


def _render_register_form(repo: CompanyRepository) -> None:
    """새 회사 등록 폼."""
    with st.expander("새 회사 등록"):
        with st.form("register_company"):
            cid = st.text_input("회사 ID (영소문자, 숫자, 밑줄)", placeholder="acme_corp")
            name = st.text_input("표시 이름", placeholder="ACME 주식회사")
            col1, col2 = st.columns(2)
            with col1:
                industry = st.text_input("산업", placeholder="제조업")
                fiscal_start = st.number_input("회계연도 시작월", 1, 12, 1)
            with col2:
                erp = st.text_input("ERP 시스템", placeholder="SAP")
                currency = st.text_input("통화", value="KRW", max_chars=3)

            submitted = st.form_submit_button("등록", type="primary")
            if submitted:
                if not cid or not name:
                    st.error("회사 ID와 표시 이름은 필수입니다.")
                    return
                try:
                    profile = CompanyProfile(
                        company_id=cid,
                        display_name=name,
                        industry=industry,
                        erp_system=erp,
                        fiscal_year_start=fiscal_start,
                        currency=currency,
                    )
                    repo.create_company(profile)
                    # Why: 함정2 방어 — rerun 전 state 업데이트
                    st.session_state[KEY_COMPANY_ID] = profile.company_id
                    st.rerun()
                except FileExistsError:
                    st.error(f"'{cid}' ID의 회사가 이미 존재합니다.")
                except ValidationError as e:
                    first = e.errors()[0]
                    st.error(f"입력값 오류 — {first['loc'][0]}: {first['msg']}")
                except Exception as e:
                    st.error(f"등록 실패: {e}")
