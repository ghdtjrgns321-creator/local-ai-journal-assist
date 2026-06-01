"""Legacy disabled chat tab.

This module is intentionally kept as a no-op compatibility stub. The active
dashboard does not route to it, and it must not import or construct external
query-generation clients.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def render(result: Any | None = None) -> None:  # noqa: ARG001
    """Render a disabled notice for legacy callers."""
    st.info("Chat/Text-to-SQL 기능은 local-first 제품 경계에 따라 비활성화되었습니다.")
