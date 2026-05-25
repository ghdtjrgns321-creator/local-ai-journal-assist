"""Review Queue Narrator — candidate 카드 + citation 점프 패널.

PHASE3 v2 Sprint E1 — Narrator JSON(`ReviewNarrative`)을 카드로 렌더하고,
reasoning.evidence를 클릭하면 원본 룰 메타데이터 / feature 값 / 전표 라인으로
점프할 수 있는 보조 패널을 함께 표시한다.

설계:
- 카드 1건은 priority_rank + confidence 뱃지 + summary + reasoning(citation 버튼)
  + suggested_actions로 구성.
- citation 클릭은 session_state(`KEY_REVIEW_QUEUE_CITATION_TARGET`)에 type/id를
  적재해 우측 점프 패널이 동일 rerun에서 표적을 그린다.
- 본 모듈은 표시 전용. 데이터 적재(DB read, candidate index)는 호출부 책임.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard._state import (
    KEY_REVIEW_QUEUE_CITATION_TARGET,
    KEY_REVIEW_QUEUE_SELECTED_CANDIDATE,
)

# Why: confidence 3단계의 시각 톤. 카드 우측 상단 뱃지에 사용.
_CONFIDENCE_TONE: dict[str, tuple[str, str]] = {
    "high": ("높음", "#16A34A"),  # green-600
    "medium": ("보통", "#D97706"),  # amber-600
    "low": ("낮음", "#DC2626"),  # red-600
}

_EVIDENCE_LABEL: dict[str, str] = {
    "rule_hit": "룰",
    "ml_feature": "ML 피처",
    "row": "전표 라인",
}


def _confidence_badge(confidence: str) -> str:
    label, color = _CONFIDENCE_TONE.get(confidence, ("?", "#6B7280"))
    # Why: 카드 한 줄 헤더에 들어가는 작은 chip — HTML 단편이 가장 안정적.
    return (
        f"<span style='background:{color};color:#fff;padding:2px 8px;"
        f"border-radius:12px;font-size:0.75rem;font-weight:600'>"
        f"신뢰도 {label}</span>"
    )


def _citation_key(prefix: str, candidate_id: str, r_idx: int, e_idx: int) -> str:
    """citation 버튼 위젯 키 — rerun 시 동일 카드가 같은 key를 유지하도록 결정론적."""
    return f"{prefix}_{candidate_id}_{r_idx}_{e_idx}"


def _format_citation_label(evidence: dict[str, Any]) -> str:
    ev_type = evidence.get("type", "")
    label = _EVIDENCE_LABEL.get(ev_type, ev_type)
    if ev_type == "rule_hit":
        return f"{label}: {evidence.get('rule_id', '?')}"
    if ev_type == "ml_feature":
        model = evidence.get("model_id") or "?"
        feature = evidence.get("feature_id") or "?"
        return f"{label}: {model}/{feature}"
    if ev_type == "row":
        jid = evidence.get("journal_id") or "?"
        line_no = evidence.get("line_no") or 0
        return f"{label}: {jid}#{line_no}"
    return label or "(unknown)"


def _set_citation_target(candidate_id: str, evidence: dict[str, Any]) -> None:
    """citation 버튼 클릭 시 session_state에 점프 표적 적재."""
    st.session_state[KEY_REVIEW_QUEUE_SELECTED_CANDIDATE] = candidate_id
    st.session_state[KEY_REVIEW_QUEUE_CITATION_TARGET] = {
        "candidate_id": candidate_id,
        "type": evidence.get("type", ""),
        "rule_id": evidence.get("rule_id", ""),
        "model_id": evidence.get("model_id", ""),
        "feature_id": evidence.get("feature_id", ""),
        "journal_id": evidence.get("journal_id", ""),
        "line_no": int(evidence.get("line_no") or 0),
    }


def render_candidate_card(narrative: dict[str, Any]) -> None:
    """단일 candidate 카드 렌더 — priority_rank, summary, reasoning, suggested_actions."""
    candidate_id = narrative.get("candidate_id", "?")
    rank = narrative.get("priority_rank", 999)
    score = narrative.get("priority_score", 0.0) or 0.0
    confidence = narrative.get("confidence", "low")
    summary = narrative.get("summary", "")
    reasoning = narrative.get("reasoning") or []
    actions = narrative.get("suggested_actions") or []

    with st.container(border=True):
        col_title, col_badge = st.columns([5, 2])
        with col_title:
            st.markdown(f"**#{rank} · `{candidate_id}`** · 점수 `{score:.3f}`")
        with col_badge:
            st.markdown(_confidence_badge(confidence), unsafe_allow_html=True)

        if summary:
            st.markdown(summary)

        if reasoning:
            st.markdown("**의심 근거**")
            for r_idx, item in enumerate(reasoning):
                claim = item.get("claim", "") if isinstance(item, dict) else ""
                evidence_list = item.get("evidence", []) if isinstance(item, dict) else []
                st.markdown(f"- {claim}" if claim else "- (claim 누락)")
                if not evidence_list:
                    st.caption("⚠️ 인용 누락 — citation_validator 강등 대상")
                    continue
                btn_cols = st.columns(min(len(evidence_list), 4))
                for e_idx, evidence in enumerate(evidence_list):
                    target = btn_cols[e_idx % len(btn_cols)]
                    target.button(
                        _format_citation_label(evidence),
                        key=_citation_key("rqcit", candidate_id, r_idx, e_idx),
                        on_click=_set_citation_target,
                        args=(candidate_id, evidence),
                        width="stretch",
                    )

        if actions:
            st.markdown("**감사인 다음 행동**")
            for action in actions:
                action_type = action.get("action_type", "?")
                desc = action.get("description", "")
                target = action.get("target", "")
                tail = f" · 대상: `{target}`" if target else ""
                st.markdown(f"- `{action_type}` — {desc}{tail}")
