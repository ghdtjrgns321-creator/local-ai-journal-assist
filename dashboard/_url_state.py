"""Helpers for persisting company/engagement selection in Streamlit query params."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from dashboard._state import KEY_COMPANY_ID, KEY_ENGAGEMENT_ID


def hydrate_selection_from_query_params(
    state: MutableMapping[str, Any],
    query_params: Mapping[str, Any],
) -> None:
    """Restore company/engagement selection from the current URL when state is empty."""
    if not state.get(KEY_COMPANY_ID):
        company_id = _first_value(query_params.get("company"))
        if company_id:
            state[KEY_COMPANY_ID] = company_id

    if not state.get(KEY_ENGAGEMENT_ID):
        engagement_id = _first_value(query_params.get("engagement"))
        if engagement_id:
            state[KEY_ENGAGEMENT_ID] = engagement_id


def sync_selection_to_query_params(
    state: Mapping[str, Any],
    query_params: MutableMapping[str, Any],
) -> None:
    """Keep URL query params aligned with the active company/engagement selection."""
    company_id = state.get(KEY_COMPANY_ID)
    engagement_id = state.get(KEY_ENGAGEMENT_ID)

    if company_id:
        query_params["company"] = str(company_id)
    else:
        query_params.pop("company", None)

    if engagement_id:
        query_params["engagement"] = str(engagement_id)
    else:
        query_params.pop("engagement", None)


def _first_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        first = value[0]
        return str(first) if first else None
    return str(value)
