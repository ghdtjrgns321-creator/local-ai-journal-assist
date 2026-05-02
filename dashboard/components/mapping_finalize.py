from __future__ import annotations

import logging

import streamlit as st

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_COLUMN_DIFF,
    KEY_INGEST_CONFIRMED,
    KEY_INGEST_DATA_DF,
    KEY_INGEST_MAPPING_RESULT,
    KEY_INGEST_PREP_WARNINGS,
    KEY_INGEST_PREPARED_DF,
    KEY_INGEST_READ_RESULT,
    KEY_INGEST_SELECTED_SHEET,
    KEY_INGEST_SHEET_SCORES,
    KEY_INGEST_SOURCE_COLUMNS,
    KEY_INGEST_STAGE,
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
    _clear_ingest_review_state()
    logger.info("mapped data prepared: rows=%s file=%s", len(result.data), file_key)
    return result


def _clear_ingest_review_state() -> None:
    """Leave the completed prep result active and clear upload/review-only state."""

    for key in [
        KEY_INGEST_READ_RESULT,
        KEY_INGEST_MAPPING_RESULT,
        KEY_INGEST_SHEET_SCORES,
        KEY_INGEST_SELECTED_SHEET,
        KEY_INGEST_SOURCE_COLUMNS,
        KEY_INGEST_DATA_DF,
        KEY_INGEST_COLUMN_DIFF,
        "_ingest_file_key",
        "_ingest_source_hint",
        "_ingest_tmp_path",
        "_ingest_is_user_path",
        "_ingest_current_fy",
        "_ingest_prior_fy",
    ]:
        st.session_state.pop(key, None)
    st.session_state[KEY_INGEST_STAGE] = "UPLOAD"
