"""설정 변경 후 detection 재실행 버튼."""

from __future__ import annotations

import streamlit as st

from dashboard._state import KEY_FEATURED_DATA, KEY_LAYER_WEIGHTS, KEY_SETTINGS_DIRTY
from src.detection.constants import LAYER_WEIGHTS
from src.services.analysis_service import rerun_detection as rerun_detection_service


def rerun_detection() -> bool:
    """현재 featured data 기준으로 detection만 다시 실행한다."""
    if st.session_state.get(KEY_FEATURED_DATA) is None:
        st.error("원천 데이터가 없습니다. 파일을 먼저 업로드하세요.")
        return False
    return rerun_detection_service(st.session_state)


def render_apply_button() -> None:
    """설정 변경분을 재탐지에 반영하는 버튼."""
    dirty = st.session_state.get(KEY_SETTINGS_DIRTY, False)
    if not dirty:
        return

    weights = st.session_state.get(KEY_LAYER_WEIGHTS)
    if weights is None:
        weights = {k.value: v for k, v in LAYER_WEIGHTS.items()}
    total = sum(weights.values())
    valid = abs(total - 1.0) <= 0.01

    if st.button("새 설정 적용", disabled=not valid, use_container_width=True):
        with st.spinner("탐지 재실행 중..."):
            ok = rerun_detection()
        if ok:
            st.rerun()
