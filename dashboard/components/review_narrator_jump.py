"""Review Queue Narrator — citation 점프 패널.

`KEY_REVIEW_QUEUE_CITATION_TARGET`이 비어있지 않으면 대응되는 원본 신호(rule 메타
데이터 / feature 값 / 전표 라인)를 패널 한 칸으로 렌더한다.

설계:
- 표시 전용. 모든 데이터 접근은 candidate dict + pipeline result.data DataFrame에서.
- rule 메타데이터는 `src.detection.rule_detail_metadata.get_rule_detail_metadata`로
  단일 출처 조회 — 외부 파일 추가 의존 없이 dashboard 패키지가 활용 가능.
- 모듈 분리 이유: tab_review_queue.py + 카드 컴포넌트가 100줄 가이드를 넘지 않도록.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard._state import (
    KEY_REVIEW_QUEUE_CANDIDATE_INDEX,
    KEY_REVIEW_QUEUE_CITATION_TARGET,
)


def _rule_metadata(rule_id: str) -> dict[str, Any] | None:
    try:
        from dataclasses import asdict, is_dataclass

        from src.detection.rule_detail_metadata import (
            canonicalize_rule_id,
            get_rule_detail_metadata,
        )
    except Exception:
        return None
    try:
        canonical = canonicalize_rule_id(rule_id)
        meta = get_rule_detail_metadata(canonical)
    except Exception:
        return None
    if meta is None:
        return None
    # Why: RuleDetailMetadata 는 frozen dataclass — asdict 로 평탄화.
    if is_dataclass(meta) and not isinstance(meta, type):
        return asdict(meta)
    return None


def _render_rule(target: dict[str, Any]) -> None:
    rule_id = target.get("rule_id", "")
    st.markdown(f"### 룰 메타데이터 · `{rule_id}`")
    meta = _rule_metadata(rule_id)
    if meta is None:
        st.info("해당 rule_id의 메타데이터를 찾을 수 없습니다.")
        return
    # Why: 룰 카드 핵심 필드만 우선 노출. 전체 표는 expander 안에 보존.
    summary_keys = (
        "canonical_rule_id",
        "final_topic",
        "scoring_role",
        "status",
        "presenter_surface",
    )
    for key in summary_keys:
        value = meta.get(key)
        if value:
            st.markdown(f"- **{key}**: `{value}`")
    display_copy = meta.get("display_copy") or {}
    if isinstance(display_copy, dict):
        title = display_copy.get("display_title")
        if title:
            st.markdown(f"- **display_title**: {title}")
    with st.expander("전체 메타데이터", expanded=False):
        st.json(meta)


def _render_ml_feature(target: dict[str, Any], candidate: dict[str, Any] | None) -> None:
    feature_id = target.get("feature_id", "")
    model_id = target.get("model_id", "")
    st.markdown(f"### ML 피처 · `{model_id}/{feature_id}`")
    if candidate is None:
        st.info("candidate dict가 세션에 없어 피처 값을 표시할 수 없습니다.")
        return
    # Why: candidate.ml_scores 리스트에서 매칭되는 (model_id, feature_id) 항목 찾기.
    matched: list[dict[str, Any]] = []
    for ml_entry in candidate.get("ml_scores", []) or []:
        if model_id and ml_entry.get("model_id") != model_id:
            continue
        for feat in ml_entry.get("top_features", []) or []:
            if feat.get("feature_id") == feature_id:
                matched.append(
                    {
                        "model_id": ml_entry.get("model_id", model_id),
                        "score": ml_entry.get("score"),
                        "percentile": ml_entry.get("percentile"),
                        **feat,
                    }
                )
    if not matched:
        st.info("candidate.ml_scores 에서 해당 feature_id를 찾을 수 없습니다.")
        return
    for entry in matched:
        st.write(entry)


def _render_row(
    target: dict[str, Any],
    data: pd.DataFrame | None,
    candidate: dict[str, Any] | None,
) -> None:
    journal_id = target.get("journal_id", "")
    line_no = int(target.get("line_no") or 0)
    st.markdown(f"### 전표 라인 · `{journal_id}` · line `{line_no}`")
    if data is None or data.empty:
        if candidate is not None:
            st.write(candidate.get("journal_ref", {}))
            return
        st.info("PipelineResult.data가 비어 있어 전표 라인을 표시할 수 없습니다.")
        return
    # Why: document_id / journal_id 둘 다 사용될 수 있는 환경 — 둘 다 시도.
    mask = pd.Series(False, index=data.index)
    for key in ("journal_id", "document_id"):
        if key in data.columns:
            mask = mask | (data[key].astype(str) == str(journal_id))
    subset: pd.DataFrame = data.loc[mask]
    if subset.empty:
        st.info("PipelineResult.data 에서 해당 journal_id 라인을 찾지 못했습니다.")
        return
    if line_no and "line_no" in subset.columns:
        line_subset: pd.DataFrame = subset.loc[subset["line_no"].astype("Int64") == line_no]
        if not line_subset.empty:
            subset = line_subset
    st.dataframe(subset, use_container_width=True, hide_index=True)


def render_citation_jump_panel(data: pd.DataFrame | None) -> None:
    """citation 클릭 표적이 있으면 우측 패널에 원본 신호를 렌더."""
    target = st.session_state.get(KEY_REVIEW_QUEUE_CITATION_TARGET)
    if not target:
        st.caption("좌측 카드의 인용 버튼을 누르면 원본 룰 / 피처 / 전표가 여기 표시됩니다.")
        return
    candidate_index = st.session_state.get(KEY_REVIEW_QUEUE_CANDIDATE_INDEX) or {}
    candidate = candidate_index.get(target.get("candidate_id", ""))

    ev_type = target.get("type", "")
    if ev_type == "rule_hit":
        _render_rule(target)
    elif ev_type == "ml_feature":
        _render_ml_feature(target, candidate)
    elif ev_type == "row":
        _render_row(target, data, candidate)
    else:
        st.warning(f"알 수 없는 citation type: {ev_type!r}")
