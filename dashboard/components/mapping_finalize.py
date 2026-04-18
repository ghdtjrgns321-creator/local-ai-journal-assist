from __future__ import annotations

import logging

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_PREPARED_DF,
    KEY_INGEST_PREP_WARNINGS,
    KEY_LOADED_FROM_DB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
)

logger = logging.getLogger(__name__)


def prepare_mapped_data(file_key: str, progress_cb=None):
    """Run preparation only after mapping confirmation."""
    from dashboard.components.data_uploader import _run_pipeline_from_mapped

    def _progress(pct: float, msg: str) -> None:
        if progress_cb is not None:
            progress_cb(pct, msg)

    result, warns = _run_pipeline_from_mapped(
        file_key,
        _progress,
        prepare_only=True,
    )

    st.session_state[KEY_PREP_RESULT] = result
    st.session_state[KEY_PHASE1_RESULT] = None
    st.session_state[KEY_PHASE2_RESULT] = None
    st.session_state[KEY_PIPELINE_RESULT] = None
    st.session_state[KEY_BATCH_ID] = result.batch_id
    st.session_state[KEY_UPLOAD_COUNT] = file_key
    st.session_state[KEY_FEATURED_DATA] = result.featured_data
    st.session_state[KEY_INGEST_PREPARED_DF] = result.featured_data
    st.session_state[KEY_INGEST_PREP_WARNINGS] = warns
    st.session_state[KEY_INGEST_CONFIRMED] = True
    st.session_state[KEY_LOADED_FROM_DB] = False
    logger.info("mapped data prepared: rows=%s file=%s", len(result.data), file_key)
    return result
