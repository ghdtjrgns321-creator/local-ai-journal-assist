"""Tab 3: Anomaly Explorer — 이상 전표 상세 탐색 + HITL 예외 처리.

Why: 감사인이 AgGrid 테이블에서 이상 전표를 탐색하고,
     행 선택 시 룰별 점수를 확인하며, 오탐을 예외 처리하는
     end-to-end 워크플로우의 오케스트레이터.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from dashboard._state import KEY_DEV_MODE, KEY_FILTERS, KEY_SELECTED_DOC
from dashboard.components.explorer_detail import render_detail
from dashboard.components.explorer_grid import build_grid
from dashboard.components.explorer_whitelist import render_whitelist
from dashboard.components.filters import apply_filters

if TYPE_CHECKING:
    from src.pipeline import PipelineResult


def render(result: "PipelineResult") -> None:
    """Tab 3 메인 렌더 함수."""
    # 1. 필터 적용
    df = apply_filters(result.data, st.session_state.get(KEY_FILTERS, {}))
    dev_mode = st.session_state.get(KEY_DEV_MODE, False)

    if df.empty:
        st.info("필터 조건에 해당하는 전표가 없습니다.")
        return

    # 2. DuckDB 연결 (DB 적재 완료 시에만)
    conn = _get_connection(result)

    # 3. Whitelist 로드 → 그리드에 표시용
    whitelist_docs = _load_whitelist_docs(conn, result.batch_id)

    # 4. session_state에서 이전 선택 복원 (rerun 후 UX 유지)
    prev_selected = st.session_state.get(KEY_SELECTED_DOC)

    # 5. AgGrid 렌더링
    grid_response = build_grid(df, dev_mode, whitelist_docs, prev_selected)

    # 6. 행 선택 → session_state 동기화
    selected = grid_response.selected_rows
    if selected is not None and len(selected) > 0:
        doc_id = selected.iloc[0]["document_id"]
        st.session_state[KEY_SELECTED_DOC] = doc_id

        # 7. 상세 패널 — SHAP 데이터가 있으면 피처 기여도 패널도 함께 렌더
        render_detail(
            doc_id, result.data, conn, result.batch_id,
            shap_contributions=result.shap_contributions,
            shap_base_value=result.shap_base_value,
        )

        # 8. HITL 예외 저장 UI (DB 연결 시에만 활성)
        if conn is not None:
            modified = render_whitelist(doc_id, conn, result.batch_id, result.data)
            if modified:
                st.rerun()
    else:
        st.info("행을 선택하면 상세 정보를 확인할 수 있습니다.")


def _get_connection(result: "PipelineResult"):
    """DB 적재 완료 시 싱글톤 DuckDB 커넥션 반환, 아니면 None.

    Why: 매 렌더마다 duckdb.connect()를 호출하면 파일 핸들 누수 + 쓰기 락 충돌.
         src/db/connection.py 싱글톤을 사용하여 커넥션 재활용.
    """
    if result.load_result is None:
        return None
    try:
        from src.db.connection import get_connection
        return get_connection()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("DuckDB 연결 실패", exc_info=True)
        return None


def _load_whitelist_docs(conn, batch_id: str) -> set[str]:
    """현재 배치의 whitelist document_id 집합 로드."""
    if conn is None:
        return set()
    try:
        from src.db.queries import execute_preset
        wl_df = execute_preset(conn, "batch_whitelist", batch_id=batch_id)
        return set(wl_df["document_id"].unique()) if not wl_df.empty else set()
    except Exception:
        return set()
