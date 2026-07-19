from __future__ import annotations

import streamlit as st

from dashboard._state import KEY_PREP_RESULT
from src.services.analysis_service import run_phase_analysis as run_phase_analysis_service


def run_phase_analysis(*, phase: str):
    if st.session_state.get(KEY_PREP_RESULT) is None:
        raise RuntimeError("준비 결과가 없습니다.")
    return run_phase_analysis_service(st.session_state, phase=phase)
