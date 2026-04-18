"""Session-state helpers shared by dashboard entrypoints."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from dashboard._state import (
    KEY_BATCH_ID,
    KEY_COMPANY_CONTEXT,
    KEY_COMPANY_ID,
    KEY_EDA_PROFILE,
    KEY_ENGAGEMENT_ID,
    KEY_FEATURED_DATA,
    KEY_INGEST_STAGE,
    KEY_LOADED_FROM_DB,
    KEY_PHASE1_RESULT,
    KEY_PHASE2_RESULT,
    KEY_PIPELINE_RESULT,
    KEY_PREP_RESULT,
    KEY_UPLOAD_COUNT,
)


def clear_company_selection(state: MutableMapping[str, Any]) -> None:
    """Clear company-specific dashboard state before selecting a new engagement."""
    for key in [
        KEY_COMPANY_ID,
        KEY_ENGAGEMENT_ID,
        KEY_COMPANY_CONTEXT,
        KEY_PREP_RESULT,
        KEY_PHASE1_RESULT,
        KEY_PHASE2_RESULT,
        KEY_PIPELINE_RESULT,
        KEY_BATCH_ID,
        KEY_UPLOAD_COUNT,
        KEY_FEATURED_DATA,
        KEY_EDA_PROFILE,
        KEY_LOADED_FROM_DB,
    ]:
        state.pop(key, None)
    state[KEY_INGEST_STAGE] = "UPLOAD"


def has_analysis_output(result: Any) -> bool:
    """Return True when a pipeline-like result already contains analyzed risk output."""
    if result is None:
        return False
    df = getattr(result, "data", None)
    if df is None or "risk_level" not in df.columns:
        return False
    return bool(df["risk_level"].notna().any())


def restore_loaded_result(
    state: MutableMapping[str, Any],
    loaded: Any,
    batch_id: str,
) -> None:
    """Restore a previously saved batch into dashboard session state."""
    state[KEY_PREP_RESULT] = loaded
    state[KEY_PHASE2_RESULT] = None
    if has_analysis_output(loaded):
        state[KEY_PHASE1_RESULT] = loaded
        state[KEY_PIPELINE_RESULT] = loaded
    else:
        state[KEY_PHASE1_RESULT] = None
        state[KEY_PIPELINE_RESULT] = None
    state[KEY_BATCH_ID] = batch_id
    state[KEY_UPLOAD_COUNT] = loaded.file_name or ""
    state[KEY_LOADED_FROM_DB] = True
    state[KEY_FEATURED_DATA] = loaded.featured_data
    state.pop(KEY_EDA_PROFILE, None)


def current_display_result(state: MutableMapping[str, Any]) -> Any:
    """Return the current best-available pipeline result for rendering."""
    return (
        state.get(KEY_PHASE1_RESULT)
        or state.get(KEY_PHASE2_RESULT)
        or state.get(KEY_PIPELINE_RESULT)
        or state.get(KEY_PREP_RESULT)
    )
