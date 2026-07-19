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


def close_dashboard_connections(
    state: MutableMapping[str, Any],
    db_path: str | None = None,
) -> None:
    """Close DuckDB connections held by dashboard state and the global manager.

    Streamlit reruns can leave both the app-scoped ``_conn_mgr`` and the module
    singleton from ``get_connection()`` alive. Close both before company,
    engagement, or data lifecycle transitions so stale DB handles cannot be reused.
    """

    managers = []
    state_mgr = state.get("_conn_mgr")
    if state_mgr is not None:
        managers.append(state_mgr)

    try:
        from src.db.connection import get_connection_manager

        global_mgr = get_connection_manager()
        if global_mgr is not state_mgr:
            managers.append(global_mgr)
    except Exception:
        global_mgr = None

    for manager in managers:
        try:
            if db_path:
                manager.close(db_path)
            else:
                manager.close_all()
        except Exception:
            pass


def clear_company_selection(state: MutableMapping[str, Any]) -> None:
    """Clear company-specific dashboard state before selecting a new engagement."""
    close_dashboard_connections(state)
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


def _has_phase2_artifacts(result: Any) -> bool:
    """Return True when a loaded batch carries persisted Phase 2 metadata.

    Why: `load_batch` attaches `phase2_training_report_id`,
    `phase2_inference_contract`, `phase2_promotion_policy`, and
    `phase2_inference_mode` from `batch_meta`. Any of these is enough evidence
    that Phase 2 inference was previously executed for this batch.
    """
    if result is None:
        return False
    if getattr(result, "phase2_training_report_id", None):
        return True
    if getattr(result, "phase2_inference_contract", None):
        return True
    if getattr(result, "phase2_inference_mode", None):
        return True
    return False


def restore_loaded_result(
    state: MutableMapping[str, Any],
    loaded: Any,
    batch_id: str,
) -> None:
    """Restore a previously saved batch into dashboard session state.

    Why: 1 CSV = 1 batch row 모델. phase1 분석이 row 의 phase1 컬럼을 채우고,
    phase2 추론은 같은 row 의 phase2 컬럼만 UPDATE 한다. 단일 row 가 phase1 +
    phase2 메타를 모두 들고 있으며, 두 슬롯에 같은 객체를 set 해도 정합. phase2
    메타가 없는 row 면 phase2 슬롯만 None.
    """
    state[KEY_PREP_RESULT] = loaded
    if has_analysis_output(loaded):
        state[KEY_PHASE1_RESULT] = loaded
        state[KEY_PIPELINE_RESULT] = loaded
    else:
        state[KEY_PHASE1_RESULT] = None
        state[KEY_PIPELINE_RESULT] = None
    if _has_phase2_artifacts(loaded):
        state[KEY_PHASE2_RESULT] = loaded
    else:
        state[KEY_PHASE2_RESULT] = None
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
