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
    """Load a saved batch and restore it into dashboard session state."""
    loaded = load_batch(conn, batch_id)
    restore_loaded_result(state, loaded, batch_id)
    return loaded
