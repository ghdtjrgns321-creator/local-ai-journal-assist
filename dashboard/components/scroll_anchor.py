"""Small helpers for preserving scroll position around long-running actions."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def render_scroll_anchor(anchor_id: str) -> None:
    """Render a DOM anchor that can be targeted from a tiny component script."""
    st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)


def scroll_to_anchor(anchor_id: str) -> None:
    """Scroll the parent Streamlit document to an anchor rendered in the main page."""
    components.html(
        f"""
        <script>
        const anchor = window.parent.document.getElementById("{anchor_id}");
        if (anchor) {{
            anchor.scrollIntoView({{behavior: "auto", block: "center"}});
        }}
        </script>
        """,
        height=0,
        width=0,
    )
