"""PHASE1 case drilldown local evidence brief component."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.evidence.local_evidence_brief import build_local_evidence_brief


def render_phase1_local_evidence_brief(drilldown: dict[str, Any]) -> None:
    """Render a deterministic brief from existing PHASE1/PHASE2 evidence."""
    brief = build_local_evidence_brief(drilldown)

    with st.container(border=True):
        st.markdown("**로컬 근거 요약**")
        st.caption(
            "이미 산출된 룰/패밀리 신호를 요약합니다. 외부 API 호출 없음. "
            "확정 판단이 아니라 검토 편의를 위한 요약입니다."
        )

        st.markdown("**핵심 근거**")
        for item in brief.key_evidence:
            st.markdown(f"- {item}")

        st.markdown("**확인 절차**")
        for item in brief.audit_actions:
            st.markdown(f"- {item}")

        st.markdown("**한계**")
        for item in brief.limitations:
            st.markdown(f"- {item}")
