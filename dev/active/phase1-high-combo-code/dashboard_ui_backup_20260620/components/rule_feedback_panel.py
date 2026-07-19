"""Legacy disabled rule feedback panel."""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_rule_feedback_panel(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
    """Render a disabled notice for legacy callers."""
    st.info("룰 피드백 생성 기능은 local-first 제품 경계에 따라 비활성화되었습니다.")
