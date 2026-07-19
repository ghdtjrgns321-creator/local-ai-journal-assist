"""저장된 배치 이력 목록 UI — 이전 분석 결과 불러오기.

Why: Streamlit 재시작 후에도 DB에 저장된 이전 분석 결과를
     선택하여 session_state를 복원하고 대시보드를 렌더링할 수 있다.
"""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from src.services.batch_service import list_saved_batches, load_batch_into_state

logger = logging.getLogger(__name__)


def _display_file_name(value: object) -> str:
    """Return a compact file name for paths persisted as batch metadata."""
    raw = str(value or "").strip()
    if not raw:
        return "(파일명 없음)"
    return Path(raw).name or raw


def _display_created_at(value: object) -> str:
    raw = str(value or "").strip()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    return raw


def render_batch_selector(conn) -> bool:
    """저장된 배치 목록을 카드로 표시하고 선택 시 session_state 복원.

    Returns:
        True이면 배치가 1개 이상 표시됨, False이면 표시 없음.
    """
    batches = list_saved_batches(conn)
    if batches.empty:
        return False

    st.subheader("이전 분석 결과")

    for position, (_, row) in enumerate(batches.iterrows()):
        bid = row["upload_batch_id"]
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                fname = _display_file_name(row["file_name"])
                label = f"**{fname}**"
                if position == 0:
                    label += "  \n최근 결과"
                st.markdown(label)
                st.caption(
                    f"{row['row_count']:,}행 · "
                    f"이상 {row['anomaly_count']:,}건 · "
                    f"High {row['high_risk_count']}건 · "
                    f"{_display_created_at(row['created_at'])}"
                )
            with col2:
                if st.button("불러오기", key=f"load_{bid}"):
                    _load_and_restore(conn, bid)

    return True


def _load_and_restore(conn, batch_id: str) -> None:
    """DB에서 배치 로드 → session_state 복원 → rerun."""
    try:
        load_batch_into_state(st.session_state, conn, batch_id)
        st.rerun()
    except ValueError as exc:
        st.error(f"배치 로드 실패: {exc}")
    except Exception:
        logger.warning("배치 로드 실패: %s", batch_id, exc_info=True)
        st.error("배치 로드 중 오류가 발생했습니다.")
