"""Company CRUD sidebar component."""

from __future__ import annotations

import csv
import io
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from config.settings import get_settings
from dashboard._state import (
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_DEV_MODE,
    KEY_ENGAGEMENT_ID,
    KEY_INGEST_STAGE,
    KEY_PIPELINE_RESULT,
)
from src.company.merger import normalize_settings_overrides, resolve_settings

if TYPE_CHECKING:
    from src.company.models import CompanyProfile
    from src.company.repository import CompanyRepository
    from src.context import ContextFactory


def render_company_manager(
    company_id: str,
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """Render company management controls in the sidebar."""
    try:
        profile = repo.get_company(company_id)
    except FileNotFoundError:
        st.warning("회사 프로필을 찾을 수 없습니다.")
        return

    _render_settings_editor(profile, repo, factory)
    _render_coa_uploader(company_id, repo, factory)
    _render_export_import(company_id, repo, factory)
    _render_delete_confirm(company_id, repo)


def _render_settings_editor(
    profile: CompanyProfile,
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """Edit the small, high-signal subset of company-specific settings."""
    st.markdown("**설정 오버라이드**")

    defaults = get_settings()
    resolved = resolve_settings(company_overrides=profile.settings_overrides)
    thresholds = list(resolved.approval_thresholds)
    threshold_df = pd.DataFrame(
        {
            "Level": range(1, len(thresholds) + 1),
            "금액": thresholds,
        }
    )

    edited_thresholds = st.data_editor(
        threshold_df,
        key=f"cm_thresholds_{profile.company_id}",
        hide_index=True,
        num_rows="fixed",
        use_container_width=True,
        disabled=["Level"],
    )

    period_margin = st.slider(
        "기말 마감 마진(일)",
        min_value=1,
        max_value=30,
        value=int(resolved.period_end_margin_days),
        step=1,
        key="cm_period_margin",
    )
    admin_overrides: dict[str, object] = {}
    if st.session_state.get(KEY_DEV_MODE, False):
        with st.expander("관리자 설정", expanded=False):
            admin_overrides["zscore_threshold"] = st.slider(
                "Z-Score 임계값",
                min_value=1.0,
                max_value=5.0,
                value=float(resolved.zscore_threshold),
                step=0.1,
                key="cm_zscore",
            )
            admin_overrides["benford_mad_threshold"] = st.slider(
                "Benford MAD 임계값",
                min_value=0.001,
                max_value=0.05,
                value=float(resolved.benford_mad_threshold),
                step=0.001,
                format="%.3f",
                key="cm_benford",
            )
    col1, col2, col3 = st.columns(3)
    with col1:
        enable_nlp = st.checkbox(
            "NLP 탐지",
            value=bool(resolved.enable_nlp_detection),
            key="cm_enable_nlp",
        )
    with col2:
        enable_graph = st.checkbox(
            "Graph 탐지",
            value=bool(resolved.enable_graph_detection),
            key="cm_enable_graph",
        )
    with col3:
        enable_ml = st.checkbox(
            "ML 탐지",
            value=bool(resolved.enable_ml_detection),
            key="cm_enable_ml",
        )

    if st.button("설정 저장", key="cm_save_settings"):
        amounts = (
            edited_thresholds["금액"]
            .fillna(0)
            .astype(int)
            .tolist()
        )
        amounts = [amount for amount in amounts if amount > 0]
        if not amounts:
            st.error("승인 한도는 최소 1개 이상 필요합니다.")
            return

        overrides = {
            "approval_thresholds": amounts,
            "period_end_margin_days": period_margin,
            "enable_nlp_detection": enable_nlp,
            "enable_graph_detection": enable_graph,
            "enable_ml_detection": enable_ml,
        }
        overrides.update(admin_overrides)
        merged_overrides = dict(profile.settings_overrides)
        merged_overrides.update(overrides)
        normalized = normalize_settings_overrides(merged_overrides, scope="company")
        updated = profile.model_copy(update={"settings_overrides": normalized})
        repo.update_company(updated)
        factory.invalidate(profile.company_id)
        st.success("설정이 저장되었습니다.")
        st.caption(
            "전역 기본값과 다른 회사별 설정만 저장합니다. "
            f"기본 승인한도 개수: {len(defaults.approval_thresholds)}"
        )


def _render_coa_uploader(
    company_id: str,
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """Upload and edit a company-specific chart of accounts."""
    st.markdown("**계정과목표(CoA)**")

    uploaded = st.file_uploader(
        "CSV 업로드 (첫 열 = 계정코드)",
        type=["csv"],
        key=f"cm_coa_{company_id}",
    )
    if uploaded is not None:
        content = uploaded.read().decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if len(rows) < 2:
            st.error("헤더와 최소 1개 이상의 계정코드가 필요합니다.")
            return

        coa_path = repo.company_dir(company_id) / "chart_of_accounts.csv"
        coa_path.write_text(content, encoding="utf-8")

        profile = repo.get_company(company_id)
        updated = profile.model_copy(update={"has_custom_coa": True})
        repo.update_company(updated)
        factory.invalidate(company_id)
        st.success(f"CoA 저장 완료 ({len(rows) - 1}개 계정)")

    coa = repo.load_company_coa(company_id)
    if coa:
        _render_coa_editor(company_id, coa, repo, factory)


def _render_coa_editor(
    company_id: str,
    coa: set[str],
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """Edit company CoA via `st.data_editor`."""
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

        coa_path = repo.company_dir(company_id) / "chart_of_accounts.csv"
        coa_path.write_text("account_code\n" + "\n".join(codes), encoding="utf-8")
        factory.invalidate(company_id)
        st.success(f"CoA 저장 완료 ({len(codes)}개 계정)")


def validate_coa_codes(codes: list[str]) -> list[str]:
    """Validate a list of chart-of-account codes."""
    errors: list[str] = []
    if not codes:
        errors.append("최소 1개 이상의 계정코드가 필요합니다.")
        return errors

    invalid = [c for c in codes if not re.match(r"^\d{3,8}$", c)]
    if invalid:
        sample = ", ".join(invalid[:5])
        suffix = f" 외 {len(invalid) - 5}건" if len(invalid) > 5 else ""
        errors.append(f"계정코드는 3~8자리 숫자여야 합니다: {sample}{suffix}")

    seen: set[str] = set()
    dupes: set[str] = set()
    for code in codes:
        if code in seen:
            dupes.add(code)
        seen.add(code)
    if dupes:
        errors.append(f"중복 계정코드: {', '.join(sorted(dupes))}")

    return errors


def _render_export_import(
    company_id: str,
    repo: CompanyRepository,
    factory: ContextFactory,
) -> None:
    """Render company export/import controls."""
    st.markdown("**설정 내보내기/가져오기**")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("설정 내보내기", key="cm_export"):
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
            "설정 가져오기(ZIP)",
            type=["zip"],
            key="cm_import_zip",
        )
        if uploaded_zip is not None:
            overwrite = st.checkbox("기존 설정 덮어쓰기", key="cm_import_overwrite")
            if st.button("가져오기 실행", key="cm_import_btn"):
                tmp: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
                        f.write(uploaded_zip.read())
                        tmp = Path(f.name)
                    imported_id = repo.import_company(tmp, overwrite=overwrite)
                    factory.invalidate(imported_id)
                    st.success(f"설정 가져오기 완료: {imported_id}")
                except FileExistsError:
                    st.error(
                        "같은 회사 ID가 이미 존재합니다. "
                        "'기존 설정 덮어쓰기'를 켜고 다시 시도하세요."
                    )
                except ValueError as exc:
                    st.error(f"ZIP 파일 오류: {exc}")
                finally:
                    if tmp is not None:
                        tmp.unlink(missing_ok=True)


def _render_delete_confirm(company_id: str, repo: CompanyRepository) -> None:
    """Render destructive company deletion control with confirmation text."""
    st.markdown("---")
    with st.expander("회사 삭제", expanded=False):
        st.warning("이 작업은 되돌릴 수 없습니다. 모든 회사 데이터가 삭제됩니다.")
        confirm = st.text_input(
            f"삭제하려면 '{company_id}'를 입력하세요.",
            key="cm_delete_confirm",
        )
        if st.button("삭제", type="primary", key="cm_delete_btn"):
            if confirm == company_id:
                repo.delete_company(company_id)
                for key in [
                    KEY_COMPANY_ID,
                    KEY_ENGAGEMENT_ID,
                    KEY_COMPANY_CONTEXT,
                    KEY_PIPELINE_RESULT,
                ]:
                    st.session_state.pop(key, None)
                st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
                st.rerun()
            else:
                st.error("입력한 ID가 일치하지 않습니다.")
