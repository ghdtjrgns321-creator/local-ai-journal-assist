"""회사 선택/생성 화면 (RC-4-1).

app.py에서 KEY_COMPANY_ID가 None일 때 렌더링된다.
"새 회사 등록" / "기존 회사 분석" 2탭 구조.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st
from pydantic import ValidationError

from dashboard._state import KEY_COMPANY_ID
from src.company.models import CompanyProfile
from src.services.session_service import close_dashboard_connections

if TYPE_CHECKING:
    from src.company.repository import CompanyRepository

# Why: KSIC 대분류 기준. 감사 대상 회사에서 흔히 등장하는 산업 목록.
INDUSTRY_OPTIONS = [
    "제조업",
    "건설업",
    "도매 및 소매업",
    "금융 및 보험업",
    "정보통신업",
    "부동산업",
    "전문·과학·기술 서비스업",
    "운수 및 창고업",
    "숙박 및 음식점업",
    "전기·가스·수도사업",
    "보건업 및 사회복지 서비스업",
    "교육 서비스업",
    "예술·스포츠·여가 서비스업",
    "농업·임업·어업",
    "광업",
    "기타(직접입력)",
]

# Why: 한국 기업에서 사용 빈도 높은 ERP 시스템 목록.
ERP_OPTIONS = [
    "SAP",
    "Oracle EBS",
    "더존(iCUBE)",
    "더존(Smart A)",
    "영림원(K-System)",
    "위하고(Wehago)",
    "MS Dynamics",
    "자체개발(In-house)",
    "기타(직접입력)",
]

CURRENCY_OPTIONS = ["KRW", "USD", "JPY", "CNY", "EUR"]


def render_company_page(repo: CompanyRepository) -> None:
    """회사 선택 메인 화면. company_id=None일 때 호출."""
    st.title("AI Audit Assistant")

    tab_existing, tab_register = st.tabs(["기존 회사 분석", "새 회사 등록"])

    with tab_existing:
        companies = repo.list_companies()
        if companies:
            _render_company_cards(companies, repo)
        else:
            st.info("등록된 회사가 없습니다. '새 회사 등록' 탭에서 먼저 회사를 등록하세요.")

    with tab_register:
        _render_register_form(repo)


def _render_company_cards(
    companies: list[CompanyProfile],
    repo: CompanyRepository,
) -> None:
    """회사 카드 목록 — 3열 그리드 + 삭제 버튼."""
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

                btn_col, del_col = st.columns([3, 1])
                with btn_col:
                    if st.button("선택", key=f"select_{profile.company_id}"):
                        close_dashboard_connections(st.session_state)
                        st.session_state[KEY_COMPANY_ID] = profile.company_id
                        st.rerun()
                with del_col:
                    if st.button(
                        "삭제",
                        key=f"delete_{profile.company_id}",
                        type="secondary",
                    ):
                        st.session_state[f"_confirm_del_{profile.company_id}"] = True

                # Why: 실수 방지를 위한 2단계 삭제 확인
                if st.session_state.get(f"_confirm_del_{profile.company_id}"):
                    st.warning(f"'{profile.display_name}' 회사를 정말 삭제하시겠습니까?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("삭제 확인", key=f"confirm_del_{profile.company_id}"):
                            close_dashboard_connections(st.session_state)
                            repo.delete_company(profile.company_id)
                            st.session_state.pop(
                                f"_confirm_del_{profile.company_id}",
                                None,
                            )
                            st.rerun()
                    with c2:
                        if st.button("취소", key=f"cancel_del_{profile.company_id}"):
                            st.session_state.pop(
                                f"_confirm_del_{profile.company_id}",
                                None,
                            )
                            st.rerun()


def _render_register_form(repo: CompanyRepository) -> None:
    """새 회사 등록 폼."""
    with st.form("register_company"):
        cid = st.text_input(
            "회사 ID",
            placeholder="acme_corp",
            help=(
                '공백과 < > : " / \\ | ? * 문자를 제외한 한글·영문·숫자·기호를 '
                "허용합니다 (최대 64자)."
            ),
        )
        name = st.text_input("회사명", placeholder="ACME 주식회사")

        col1, col2 = st.columns(2)
        with col1:
            industry_idx = st.selectbox(
                "산업",
                options=range(len(INDUSTRY_OPTIONS)),
                format_func=lambda i: INDUSTRY_OPTIONS[i],
            )
            industry = INDUSTRY_OPTIONS[industry_idx]
            if industry == "기타(직접입력)":
                industry = st.text_input("산업 직접입력", key="industry_custom")

            fiscal_start = st.selectbox(
                "회계연도 시작월",
                options=list(range(1, 13)),
                format_func=lambda m: f"{m}월",
            )

        with col2:
            erp_idx = st.selectbox(
                "ERP 시스템",
                options=range(len(ERP_OPTIONS)),
                format_func=lambda i: ERP_OPTIONS[i],
            )
            erp = ERP_OPTIONS[erp_idx]
            if erp == "기타(직접입력)":
                erp = st.text_input("ERP 직접입력", key="erp_custom")

            currency = st.selectbox("통화", options=CURRENCY_OPTIONS)

        submitted = st.form_submit_button("등록", type="primary")
        if submitted:
            if not cid or not name:
                st.error("회사 ID와 회사명은 필수입니다.")
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
                st.session_state[KEY_COMPANY_ID] = profile.company_id
                st.rerun()
            except FileExistsError:
                st.error(f"'{cid}' ID 의 회사가 이미 존재합니다.")
            except ValidationError as e:
                first = e.errors()[0]
                st.error(f"입력값 오류 — {first['loc'][0]}: {first['msg']}")
            except Exception as e:
                st.error(f"등록 실패: {e}")
