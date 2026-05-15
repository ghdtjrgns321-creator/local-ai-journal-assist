"""Developer-mode controls for clearing persisted phase results."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import streamlit as st

from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_BATCH_ID,
    KEY_LOADED_FROM_DB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
)
from src.db.analysis_reset import (
    PhaseResetResult,
    reset_phase1_analysis,
    reset_phase2_analysis,
    reset_phase3_analysis,
)
from src.services.batch_service import load_batch_into_state

_RESET_MESSAGE_KEY = "_dev_analysis_reset_message"


def render_dev_analysis_reset(*, conn, state: MutableMapping[str, Any]) -> None:
    """Render destructive DB reset buttons for the current batch in dev mode."""
    batch_id = _current_batch_id(state)
    if not batch_id:
        return

    message = state.pop(_RESET_MESSAGE_KEY, None)
    if message:
        st.success(message)

    with st.expander("개발자 DB 초기화", expanded=False):
        st.caption(
            "현재 배치의 업로드/매핑 데이터는 유지하고 완료된 분석 산출물만 삭제합니다. "
            "Phase 1 삭제 시 하위 Phase 2/3 결과도 같이 삭제됩니다."
        )

        if st.button(
            "Phase 1 분석 완료된거 DB에서 삭제",
            key="dev_reset_phase1",
            use_container_width=True,
        ):
            _reset_and_refresh(conn, state, batch_id, phase="phase1")
        if st.button(
            "Phase 2 완료된거 DB에서 삭제",
            key="dev_reset_phase2",
            use_container_width=True,
        ):
            _reset_and_refresh(conn, state, batch_id, phase="phase2")
        if st.button(
            "Phase 3 완료된거 DB에서 삭제",
            key="dev_reset_phase3",
            use_container_width=True,
        ):
            _reset_and_refresh(conn, state, batch_id, phase="phase3")


def _reset_and_refresh(
    conn,
    state: MutableMapping[str, Any],
    batch_id: str,
    *,
    phase: str,
) -> None:
    if phase == "phase1":
        result = reset_phase1_analysis(conn, batch_id)
        _clear_phase1_state(state)
    elif phase == "phase2":
        result = reset_phase2_analysis(conn, batch_id)
        _clear_phase2_state(state)
    elif phase == "phase3":
        result = reset_phase3_analysis(conn, batch_id)
        _clear_phase3_state(state)
    else:  # pragma: no cover - defensive branch
        raise ValueError(f"Unsupported phase: {phase}")

    load_batch_into_state(state, conn, batch_id)
    state[_RESET_MESSAGE_KEY] = _format_reset_message(result)
    st.rerun()


def _clear_phase1_state(state: MutableMapping[str, Any]) -> None:
    state.pop(KEY_PHASE1_RESULT, None)
    state.pop(KEY_PHASE2_RESULT, None)
    state.pop(KEY_PIPELINE_RESULT, None)
    state[KEY_ACTIVE_RESULT_TAB] = "개요"
    state[KEY_LOADED_FROM_DB] = False


def _clear_phase2_state(state: MutableMapping[str, Any]) -> None:
    state.pop(KEY_PHASE2_RESULT, None)
    phase1_result = state.get(KEY_PHASE1_RESULT)
    if phase1_result is not None:
        _clear_phase_attrs(
            phase1_result,
            [
                "phase2_training_report_id",
                "phase2_inference_contract",
                "phase2_promotion_policy",
                "phase2_inference_mode",
                "phase2_case_overlays",
            ],
        )
        state[KEY_PIPELINE_RESULT] = phase1_result
        state[KEY_ACTIVE_RESULT_TAB] = "Phase 1 결과"
    else:
        state[KEY_ACTIVE_RESULT_TAB] = "개요"


def _clear_phase3_state(state: MutableMapping[str, Any]) -> None:
    for key in (KEY_PHASE2_RESULT, KEY_PHASE1_RESULT, KEY_PIPELINE_RESULT):
        result = state.get(key)
        if result is not None:
            _clear_phase_attrs(result, ["phase3_insight", "phase3_case_narratives"])


def _clear_phase_attrs(result: Any, names: list[str]) -> None:
    for name in names:
        if hasattr(result, name):
            if name.endswith("_narratives") or name.endswith("_overlays"):
                setattr(result, name, [])
            else:
                setattr(result, name, None)


def _current_batch_id(state: MutableMapping[str, Any]) -> str:
    if state.get(KEY_BATCH_ID):
        return str(state[KEY_BATCH_ID])
    for key in (KEY_PHASE2_RESULT, KEY_PHASE1_RESULT, KEY_PIPELINE_RESULT):
        result = state.get(key)
        batch_id = getattr(result, "batch_id", None)
        if batch_id:
            return str(batch_id)
    return ""


def _format_reset_message(result: PhaseResetResult) -> str:
    label = result.phase.upper().replace("PHASE", "Phase ")
    return f"{label} DB 결과 삭제 완료 ({result.total_affected:,}건)"
