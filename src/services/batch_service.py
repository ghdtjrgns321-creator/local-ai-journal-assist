"""Batch loading services to isolate dashboard from DB reader details."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pandas as pd

from src.db.batch_reader import list_batches, load_batch
from src.services.session_service import restore_loaded_result


def list_saved_batches(conn) -> pd.DataFrame:
    """Return saved upload batches for the current engagement DB."""
    return list_batches(conn)


def load_batch_into_state(
    state: MutableMapping[str, Any],
    conn,
    batch_id: str,
):
    """Load a saved batch and restore it into dashboard session state.

    Why: `load_batch` 는 DB 의 phase2 메타(report_id/contract/mode) 만 attach
    한다. ``phase2_case_overlays`` 본체는 engagement 폴더의 JSON 파일에 별도로
    영속화되므로, restore 전에 같은 batch 의 overlay 를 attach 한다.
    """
    loaded = load_batch(conn, batch_id)
    _attach_persisted_phase2_overlays(state, loaded, batch_id)
    restore_loaded_result(state, loaded, batch_id)
    return loaded


def _attach_persisted_phase2_overlays(
    state: MutableMapping[str, Any],
    loaded: Any,
    batch_id: str,
) -> None:
    """Engagement 폴더의 overlay JSON 을 loaded 에 attach (best-effort).

    Why: 진단 정보까지 loaded 에 attach 해서 UI 가 status 별 안내 메시지를 다르게
    표시할 수 있게 한다. ``status == LOADED`` 일 때만 overlay 본체를 attach 하고,
    그 외 분기는 ``loaded.phase2_overlay_status`` / ``phase2_overlay_message`` 만
    채워 사용자에게 사유와 next action 을 보여준다.

    Attach 되는 attribute:
      - ``loaded.phase2_case_overlays`` (LOADED 일 때만)
      - ``loaded.phase2_overlay_status`` (OverlayStatus 상수)
      - ``loaded.phase2_overlay_message`` (영어 진단 메시지, UI 는 별도 한국어 매핑)
      - ``loaded.phase2_overlay_metadata`` (path/expected/got 등)
    """
    from src.services.phase2_overlay_store import (
        OverlayStatus,
    )

    result = _resolve_overlay_load_result(state, loaded, batch_id)
    _set_loaded_attr(loaded, "phase2_overlay_status", result.status)
    _set_loaded_attr(loaded, "phase2_overlay_message", result.message)
    _set_loaded_attr(loaded, "phase2_overlay_metadata", dict(result.metadata))

    if result.status == OverlayStatus.LOADED and result.overlays is not None:
        _set_loaded_attr(loaded, "phase2_case_overlays", result.overlays)


def _resolve_overlay_load_result(
    state: MutableMapping[str, Any],
    loaded: Any,
    batch_id: str,
):
    """state/loaded 에서 ctx + expected report_id 를 모아 status 결과 반환."""
    from dashboard._state import KEY_COMPANY_CONTEXT
    from src.services.phase2_overlay_store import (
        OverlayLoadResult,
        OverlayStatus,
        load_phase2_overlay_status,
    )

    ctx = state.get(KEY_COMPANY_CONTEXT)
    if not batch_id:
        return OverlayLoadResult(
            status=OverlayStatus.UNSAFE_BATCH_ID,
            message="batch_id is empty",
        )
    expected_report = getattr(loaded, "phase2_training_report_id", None)
    return load_phase2_overlay_status(
        ctx=ctx,
        batch_id=batch_id,
        expected_training_report_id=str(expected_report) if expected_report else None,
    )


def _set_loaded_attr(loaded: Any, name: str, value: Any) -> None:
    """PipelineResult 가 frozen 으로 바뀌어도 깨지지 않도록 setattr 가드."""
    try:
        setattr(loaded, name, value)
    except (AttributeError, TypeError):
        return
