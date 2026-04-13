"""저장된 배치 이력 목록 UI — 이전 분석 결과 불러오기.

Why: Streamlit 재시작 후에도 DB에 저장된 이전 분석 결과를
     선택하여 session_state를 복원하고 대시보드를 렌더링할 수 있다.
"""

from __future__ import annotations

import logging

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_EDA_PROFILE,
    KEY_FEATURED_DATA,
    KEY_LOADED_FROM_DB,
    KEY_PIPELINE_RESULT,
    KEY_UPLOAD_COUNT,
)
from src.db.batch_reader import list_batches, load_batch

logger = logging.getLogger(__name__)


def render_batch_selector(conn) -> bool:
    """저장된 배치 목록을 카드로 표시하고 선택 시 session_state 복원.

    Returns:
        True이면 배치가 1개 이상 표시됨, False이면 표시 없음.
    """
    batches = list_batches(conn)
    if batches.empty:
        return False

    st.subheader("이전 분석 결과")

    for _, row in batches.iterrows():
        bid = row["upload_batch_id"]
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                fname = row["file_name"] or "(파일명 없음)"
                st.markdown(f"**{fname}**")
                st.caption(
                    f"{row['row_count']:,}행 · "
                    f"이상 {row['anomaly_count']:,}건 · "
                    f"High {row['high_risk_count']}건 · "
                    f"{row['created_at']}"
                )
            with col2:
                if st.button("불러오기", key=f"load_{bid}"):
                    _load_and_restore(conn, bid)

    return True


def _load_and_restore(conn, batch_id: str) -> None:
    """DB에서 배치 로드 → session_state 복원 → rerun."""
    try:
        result = load_batch(conn, batch_id)
        st.session_state[KEY_PIPELINE_RESULT] = result
        st.session_state[KEY_BATCH_ID] = batch_id
        st.session_state[KEY_UPLOAD_COUNT] = result.file_name or ""
        st.session_state[KEY_LOADED_FROM_DB] = True
        st.session_state[KEY_FEATURED_DATA] = None
        st.session_state.pop(KEY_EDA_PROFILE, None)
        st.rerun()
    except ValueError as exc:
        st.error(f"배치 로드 실패: {exc}")
    except Exception:
        logger.warning("배치 로드 실패: %s", batch_id, exc_info=True)
        st.error("배치 로드 중 오류가 발생했습니다.")
