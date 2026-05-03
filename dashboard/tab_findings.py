"""이상 항목 탭 — 탐지된 전표 목록 탐색 + HITL 예외처리.

감사인 관점: "어디에 있나?" → AgGrid 드릴다운.
기존 tab_explorer.py의 컴포넌트를 재활용.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_DEV_MODE, KEY_FILTERS, KEY_SELECTED_DOC
from dashboard.components.filters import apply_filters

if TYPE_CHECKING:
    from src.pipeline import PipelineResult


def _render_filter_summary(df_filtered, df_original) -> None:
    """적용된 필터 결과 한 줄 요약."""
    total = len(df_original)
    filtered = len(df_filtered)

    if "risk_level" in df_filtered.columns:
        risk_counts = df_filtered["risk_level"].value_counts()
        high = risk_counts.get("High", 0)
        medium = risk_counts.get("Medium", 0)
        st.caption(
            f"전체 {total:,}건 중 {filtered:,}건 표시 · "
            f"High {high:,} · Medium {medium:,}"
        )
    else:
        st.caption(f"전체 {total:,}건 중 {filtered:,}건 표시")


def render(result: PipelineResult) -> None:
    """이상 항목 탭 메인 렌더."""
    filters = st.session_state.get(KEY_FILTERS, {})
    df = apply_filters(result.data, filters)

    _render_filter_summary(df, result.data)
    if df.empty:
        st.info("필터 조건에 해당하는 전표가 없습니다.")
        return

    # ── AgGrid 테이블 ──
    from dashboard.components.explorer_grid import build_grid
    dev_mode = st.session_state.get(KEY_DEV_MODE, False)
    prev_selected = st.session_state.get(KEY_SELECTED_DOC)
    grid_response = build_grid(df, dev_mode=dev_mode, selected_doc=prev_selected)

    # ── 상세 패널 (행 선택 시) ──
    selected = grid_response.selected_rows
    conn = None
    if selected is not None and len(selected) > 0:
        doc_id = selected.iloc[0]["document_id"]
        st.session_state[KEY_SELECTED_DOC] = doc_id
        conn = _get_connection(result)
        from dashboard.components.explorer_detail import render_detail
        render_detail(
            doc_id,
            result.data,
            conn=conn,
            batch_id=result.batch_id,
            results=result.results,
            shap_contributions=result.shap_contributions,
            shap_base_value=result.shap_base_value,
        )

    # ── HITL 예외 저장 (DB 연결 시) ──
    if conn is not None and selected is not None and len(selected) > 0:
        from dashboard.components.explorer_whitelist import render_whitelist
        modified = render_whitelist(doc_id, conn, result.batch_id, result.data)
        if modified:
            st.rerun()


def _get_connection(result: PipelineResult):
    """DB 적재 완료 시 싱글톤 DuckDB 커넥션 반환, 아니면 None."""
    if result.load_result is None:
        return None
    try:
        from src.db.connection import get_connection
        return get_connection()
    except Exception:
        return None
