"""회사 CRUD 컴포넌트 (RC-4-2, RC-5-3 확장).

사이드바에서 회사 설정 편집, CoA 업로드/편집, 삭제를 제공한다.
RC-5-3: CoA 테이블 편집 + 검증 + export/import 추가.
"""

from __future__ import annotations

import csv
import io
import re
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_ENGAGEMENT_ID,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
)

if TYPE_CHECKING:
    from src.company.repository import CompanyRepository
    from src.context import ContextFactory


def render_company_manager(
    company_id: str,
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """회사 관리 패널 — 사이드바 expander에서 호출."""
    try:
        profile = repo.get_company(company_id)
    except FileNotFoundError:
        st.warning("회사 프로파일을 찾을 수 없습니다.")
        return

    _render_settings_editor(profile, repo, factory)
    _render_coa_uploader(company_id, repo, factory)
    _render_export_import(company_id, repo, factory)
    _render_delete_confirm(company_id, repo)


def _render_settings_editor(
    profile, repo: CompanyRepository, factory: ContextFactory
) -> None:
    """핵심 settings_overrides 편집 (5개 필드)."""
    st.markdown("**설정 오버라이드**")
    overrides = dict(profile.settings_overrides)

    # Why: 가장 빈번하게 회사별로 달라지는 5개 필드만 노출
    approval = st.number_input(
        "승인 금액 임계값",
        min_value=0,
        value=overrides.get("approval_amount_threshold", 50_000_000),
        step=1_000_000,
        key="cm_approval",
    )
    zscore = st.slider(
        "Z-Score 임계값",
        min_value=1.0, max_value=5.0,
        value=float(overrides.get("zscore_threshold", 2.5)),
        step=0.1,
        key="cm_zscore",
    )
    benford_mad = st.slider(
        "Benford MAD 임계값",
        min_value=0.001, max_value=0.05,
        value=float(overrides.get("benford_mad_threshold", 0.015)),
        step=0.001, format="%.3f",
        key="cm_benford",
    )

    if st.button("설정 저장", key="cm_save_settings"):
        new_overrides = {
            "approval_amount_threshold": approval,
            "zscore_threshold": zscore,
            "benford_mad_threshold": benford_mad,
        }
        profile.settings_overrides.update(new_overrides)
        repo.update_company(profile)
        factory.invalidate(profile.company_id)
        st.success("설정이 저장되었습니다.")


def _render_coa_uploader(
    company_id: str, repo: CompanyRepository, factory: ContextFactory
) -> None:
    """계정과목표(CoA) 업로드 + 편집 + 검증."""
    st.markdown("**계정과목표 (CoA)**")

    # CSV 업로드
    uploaded = st.file_uploader(
        "CSV 업로드 (첫 열: 계정코드)",
        type=["csv"],
        key=f"cm_coa_{company_id}",
    )
    if uploaded is not None:
        content = uploaded.read().decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if len(rows) < 2:
            st.error("헤더 + 최소 1행의 데이터가 필요합니다.")
            return

        coa_path = repo.company_dir(company_id) / "chart_of_accounts.csv"
        coa_path.write_text(content, encoding="utf-8")

        profile = repo.get_company(company_id)
        profile.has_custom_coa = True
        repo.update_company(profile)
        factory.invalidate(company_id)
        st.success(f"CoA 저장 완료 ({len(rows) - 1}개 계정)")

    # RC-5-3: 기존 CoA 테이블 편집
    coa = repo.load_company_coa(company_id)
    if coa:
        _render_coa_editor(company_id, coa, repo, factory)


def _render_coa_editor(
    company_id: str,
    coa: set[str],
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """CoA 테이블 편집 UI — st.data_editor + 저장 버튼."""
    coa_df = pd.DataFrame(sorted(coa), columns=["계정코드"])

    edited_df = st.data_editor(
        coa_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"coa_editor_{company_id}",
    )

    if st.button("CoA 변경사항 저장", key="cm_coa_save"):
        codes = edited_df["계정코드"].dropna().astype(str).str.strip().tolist()
        codes = [c for c in codes if c]

        errors = validate_coa_codes(codes)
        if errors:
            for err in errors:
                st.error(err)
            return

        # CSV 저장
        coa_path = repo.company_dir(company_id) / "chart_of_accounts.csv"
        coa_path.write_text(
            "account_code\n" + "\n".join(codes),
            encoding="utf-8",
        )
        factory.invalidate(company_id)
        st.success(f"CoA 저장 완료 ({len(codes)}개 계정)")


def validate_coa_codes(codes: list[str]) -> list[str]:
    """계정코드 리스트 검증.

    Returns:
        에러 메시지 리스트 (빈 리스트면 통과)
    """
    errors: list[str] = []

    if not codes:
        errors.append("최소 1개 이상의 계정코드가 필요합니다.")
        return errors

    # 형식 검증: 3~8자리 숫자 (한국 계정과목 범위)
    invalid = [c for c in codes if not re.match(r"^\d{3,8}$", c)]
    if invalid:
        samples = invalid[:5]
        errors.append(
            f"계정코드는 3~8자리 숫자여야 합니다: {', '.join(samples)}"
            + (f" 외 {len(invalid) - 5}건" if len(invalid) > 5 else "")
        )

    # 중복 검출
    seen: set[str] = set()
    dupes: set[str] = set()
    for c in codes:
        if c in seen:
            dupes.add(c)
        seen.add(c)
    if dupes:
        errors.append(f"중복 계정코드: {', '.join(sorted(dupes))}")

    return errors


def _render_export_import(
    company_id: str, repo: CompanyRepository, factory: ContextFactory,
) -> None:
    """회사 설정 export/import UI."""
    st.markdown("**설정 내보내기/가져오기**")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("설정 내보내기", key="cm_export"):
            import tempfile
            from pathlib import Path

            try:
                dest = Path(tempfile.mkdtemp())
                zip_path = repo.export_company(company_id, dest)
                with open(zip_path, "rb") as f:
                    st.download_button(
                        "ZIP 다운로드",
                        f.read(),
                        file_name=f"{company_id}_export.zip",
                        mime="application/zip",
                        key="cm_export_download",
                    )
            except FileNotFoundError:
                st.error("회사를 찾을 수 없습니다.")

    with col2:
        uploaded_zip = st.file_uploader(
            "설정 가져오기 (ZIP)", type=["zip"], key="cm_import_zip",
        )
        if uploaded_zip is not None:
            overwrite = st.checkbox("기존 설정 덮어쓰기", key="cm_import_overwrite")
            if st.button("가져오기 실행", key="cm_import_btn"):
                import tempfile
                from pathlib import Path

                tmp = None
                try:
                    # Why: mktemp()는 TOCTOU 취약점 → NamedTemporaryFile 사용
                    with tempfile.NamedTemporaryFile(
                        suffix=".zip", delete=False,
                    ) as f:
                        f.write(uploaded_zip.read())
                        tmp = Path(f.name)
                    imported_id = repo.import_company(tmp, overwrite=overwrite)
                    factory.invalidate(imported_id)
                    st.success(f"설정 가져오기 완료: {imported_id}")
                except FileExistsError:
                    st.error(
                        "동일 회사 ID가 이미 존재합니다. "
                        "'기존 설정 덮어쓰기'를 체크하세요."
                    )
                except ValueError as e:
                    st.error(f"ZIP 파일 오류: {e}")
                finally:
                    if tmp is not None:
                        tmp.unlink(missing_ok=True)


def _render_delete_confirm(company_id: str, repo: CompanyRepository) -> None:
    """회사 삭제 — 이중 확인."""
    st.markdown("---")
    with st.expander("회사 삭제", expanded=False):
        st.warning("이 작업은 되돌릴 수 없습니다. 모든 데이터가 삭제됩니다.")
        confirm = st.text_input(
            f"삭제하려면 '{company_id}'를 입력하세요",
            key="cm_delete_confirm",
        )
        if st.button("삭제", type="primary", key="cm_delete_btn"):
            if confirm == company_id:
                repo.delete_company(company_id)
                # Why: state 전체 리셋하여 회사 선택 화면으로 복귀
                for key in [KEY_COMPANY_ID, KEY_ENGAGEMENT_ID,
                            KEY_COMPANY_CONTEXT, KEY_PIPELINE_RESULT]:
                    st.session_state.pop(key, None)
                st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
                st.rerun()
            else:
                st.error("입력한 ID가 일치하지 않습니다.")
