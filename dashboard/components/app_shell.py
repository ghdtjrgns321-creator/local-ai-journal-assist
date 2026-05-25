"""Main app shell helpers for dashboard orchestration."""

from __future__ import annotations

import streamlit as st


def build_batch_status_caption(
    file_label: str,
    total_rows: int,
    *,
    elapsed: float | None = None,
    loaded_from_db: bool = False,
) -> str:
    """배치 상태 한 줄 요약."""
    source_label = "복원 배치" if loaded_from_db else "현재 배치"
    if elapsed is None:
        return f"{source_label} · {file_label} · {total_rows:,}행"
    return f"{source_label} · {file_label} · {total_rows:,}행 · {elapsed:.1f}초"


def render_batch_header(
    file_label: str,
    total_rows: int,
    *,
    loaded_from_db: bool = False,
) -> bool:
    """상단 배치 헤더 렌더. 다른 파일 분석 클릭 시 True 반환."""
    status = "DB에서 복원됨" if loaded_from_db else "원본 파일 기준"

    col_info, col_btn = st.columns([4, 1])
    with col_info:
        st.markdown(
            f"### {file_label} "
            f"<span style='font-size:0.55em; color:#6B7280; font-weight:400; "
            f"margin-left:8px;'>| 총 {total_rows:,}행 · {status}</span>",
            unsafe_allow_html=True,
        )
    with col_btn:
        reset_clicked = st.button("다른 파일 분석", width="stretch")

    return reset_clicked


def render_sidebar_section_title(title: str, caption: str | None = None) -> None:
    """사이드바 섹션 제목 렌더."""
    st.markdown(f"**{title}**")
    if caption:
        st.caption(caption)
