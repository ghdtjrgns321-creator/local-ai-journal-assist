"""PHASE2 native case 목록 + master-detail 패널 (S7).

`Phase2CaseSet` 의 5 family case 를 family 별 컬럼으로 보여주고, 선택된 row 의
detail (row_refs / evidence / linked PHASE1) 을 in-place 로 펼친다.

사용자 lock 5 결정 준수:
  1) family 별 전용 컬럼  2) master-detail in-place  3) PHASE1 cross-ref 텍스트 only
  4) evidence_tier → family_score 정렬  5) case_set 부재 시 안내 + 실행 버튼
"""

from __future__ import annotations

import html as _html
from collections.abc import Sequence
from typing import Any

import pandas as pd
import streamlit as st

from src.models.phase2_case import (
    DuplicateCase,
    IntercompanyCase,
    Phase2CaseBase,
    Phase2CaseSet,
    Phase2RowRef,
    RelationalCase,
    TimeseriesCase,
    UnsupervisedCase,
)

# evidence_tier 정렬 우선순위 — 높은 tier 가 먼저
_TIER_ORDER: dict[str, int] = {"strong": 3, "moderate": 2, "ml_quantile": 1, "weak": 0}
_UNSUPERVISED_DETAIL_EVIDENCE_LIMIT = 10

# family → Phase2CaseSet 필드 매핑
_FAMILY_TO_ATTR: dict[str, str] = {
    "duplicate": "duplicate_cases",
    "intercompany": "intercompany_cases",
    "relational": "relational_cases",
    "unsupervised": "unsupervised_cases",
    "timeseries": "timeseries_cases",
}

# tier → 한국어 라벨 + 색상 (감사인 시각 식별용)
_TIER_LABEL_KR: dict[str, str] = {
    "strong": "Strong",
    "moderate": "Moderate",
    "weak": "Weak",
    "ml_quantile": "ML",
}
_TIER_COLOR: dict[str, str] = {
    "strong": "#DC2626",  # 빨강
    "moderate": "#F59E0B",  # 주황
    "weak": "#6B7280",  # 회색
    "ml_quantile": "#2563EB",  # 파랑
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_phase2_native_case_panel(
    family: str,
    *,
    case_set: Phase2CaseSet | None,
    phase1_case_lookup: dict[str, dict] | None = None,
    pr=None,
) -> None:
    """Family 탭 안 PHASE2 native case 목록 + detail 렌더.

    case_set 부재 시: "PHASE2 추론이 실행되지 않았습니다" 안내 + "PHASE2 추론 실행" 버튼.

    phase1_case_lookup: case_id → {"priority_band": ..., "priority_score": ...}
        linked PHASE1 case 의 priority_band 텍스트 표시용. 없으면 case_id 만 표시.
    pr: PipelineResult — case 선택 시 document master + 원장 라인 표시에 사용.
    """
    if case_set is None:
        st.info("PHASE2 추론이 실행되지 않았습니다.")
        if st.button(
            "PHASE2 추론 실행",
            key=f"phase2_native_case_run_{family}",
            type="primary",
        ):
            # tab_phase2 와 순환 참조 방지 위해 함수 내부에서 lazy import
            from dashboard.tab_phase2 import _start_phase2_pipeline

            _start_phase2_pipeline(partition=None, train=False)
            st.rerun()
        return

    attr = _FAMILY_TO_ATTR.get(family)
    if attr is None:
        st.info(f"알 수 없는 family: `{family}`")
        return

    cases: Sequence[Phase2CaseBase] = getattr(case_set, attr, ()) or ()
    if not cases:
        st.info(f"`{family}` family 에 표시할 PHASE2 review case 후보가 없습니다.")
        return

    lookup = phase1_case_lookup or {}
    # Relational cases already carry the product review-surface order in the
    # Phase2CaseSet data path. Keep UI layout unchanged and preserve that order.
    sorted_cases = list(cases) if family == "relational" else sorted(cases, key=_sort_key)
    frame = _build_family_frame(family, sorted_cases, phase1_case_lookup=lookup)
    selected_id = _render_master_table(family, frame, sorted_cases)
    if selected_id:
        case = next((c for c in sorted_cases if c.phase2_case_id == selected_id), None)
        if case is not None:
            _render_case_detail(case, phase1_case_lookup=lookup, pr=pr)


# ---------------------------------------------------------------------------
# 정렬 / 공통 셀 값
# ---------------------------------------------------------------------------


def _sort_key(case: Phase2CaseBase) -> tuple[int, float, str]:
    """evidence_tier (높은 tier 우선) → family_score 내림차순 → id tie-break."""
    return (
        -_TIER_ORDER.get(str(case.evidence_tier or "").lower(), -1),
        -float(case.family_score or 0.0),
        case.phase2_case_id,
    )


def _short_case_id(full_id: str) -> str:
    """`p2_<family>_<hash>` 의 마지막 hash 부분만 반환. 형식 어긋나면 원본."""
    if not full_id:
        return "—"
    tail = full_id.rsplit("_", 1)
    return tail[-1] if len(tail) == 2 and tail[-1] else full_id


def _linked_to_text(refs: tuple[str, ...]) -> str:
    """phase1_case_refs → "id1, id2, id3 +N" (3개 이상 트런케이트)."""
    if not refs:
        return "—"
    head = list(refs[:3])
    suffix = f" +{len(refs) - 3}" if len(refs) > 3 else ""
    return ", ".join(head) + suffix


def _tier_cell(tier: str) -> str:
    """evidence_tier 한국어 라벨 (정렬 결정성은 별도 hidden 컬럼에서)."""
    key = str(tier or "").lower()
    return _TIER_LABEL_KR.get(key, tier or "—")


def _row_label(ref: Phase2RowRef | None) -> str:
    """Phase2RowRef → 사람이 읽을 수 있는 짧은 라벨."""
    if ref is None:
        return "—"
    parts: list[str] = []
    if ref.document_id:
        parts.append(str(ref.document_id))
    if ref.line_number_key:
        parts.append(f"line {ref.line_number_key}")
    if not parts:
        # canonical index_label 의 prefix 를 떼서 가독 향상
        label = str(ref.index_label or "")
        return label.split(":", 1)[-1] if ":" in label else label
    return " · ".join(parts)


def _fmt_amount(value: float | int | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_context_score(value: float | int | None) -> str:
    """Display document-context ratios without implying a hard finding."""
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_account_process_rarity(
    account_value: float | int | None,
    process_value: float | int | None,
) -> str:
    account = _fmt_context_score(account_value)
    process = _fmt_context_score(process_value)
    if account == "—" and process == "—":
        return "—"
    return f"acct {account} / proc {process}"


def _fmt_reason_tags(top_features: tuple[dict, ...]) -> str:
    tags: list[str] = []
    for feature in top_features or ():
        if not isinstance(feature, dict):
            continue
        label = str(feature.get("label_ko") or feature.get("tag") or "").strip()
        if label and label not in tags:
            tags.append(label)
    if not tags:
        return "—"
    head = tags[:3]
    suffix = f" +{len(tags) - 3}" if len(tags) > 3 else ""
    return ", ".join(head) + suffix


def _fmt_top_feature(top_features: tuple[dict, ...]) -> str:
    top = top_features[0] if top_features else None
    if not isinstance(top, dict):
        return "—"
    return str(top.get("label_ko") or top.get("feature_id") or "—")


def _unsupervised_review_unit(case: UnsupervisedCase) -> str:
    grouping = str((case.case_generation_reason or {}).get("document_grouping") or "")
    if grouping == "fallback_row_identity":
        return "전표 ID 없음 · 단일 행 review"
    document_ids = _document_ids_from_row_refs(case.row_refs)
    return str(case.document_id or (document_ids[0] if document_ids else "") or "—")


# ---------------------------------------------------------------------------
# Family 별 row builder
# ---------------------------------------------------------------------------


def _build_family_frame(
    family: str,
    cases: Sequence[Phase2CaseBase],
    *,
    phase1_case_lookup: dict[str, dict],
) -> pd.DataFrame:
    """family 별 dispatcher — 컴럼 spec 에 맞춰 DataFrame 반환."""
    builders = {
        "duplicate": _build_duplicate_row,
        "intercompany": _build_intercompany_row,
        "relational": _build_relational_row,
        "unsupervised": _build_unsupervised_row,
        "timeseries": _build_timeseries_row,
    }
    builder = builders.get(family)
    if builder is None:
        return pd.DataFrame()
    rows = [builder(case) for case in cases]
    return pd.DataFrame(rows)


def _build_duplicate_row(case: DuplicateCase) -> dict[str, Any]:  # type: ignore[override]
    return {
        "case_id": _short_case_id(case.phase2_case_id),
        "_full_case_id": case.phase2_case_id,
        "evidence_tier": _tier_cell(case.evidence_tier),
        "sub_rule": case.sub_rule or "—",
        "left_doc": _row_label(case.left_ref),
        "right_doc": _row_label(case.right_ref),
        "family_score": round(float(case.family_score or 0.0), 3),
        "linked_to": _linked_to_text(case.phase1_case_refs),
    }


def _build_intercompany_row(case: IntercompanyCase) -> dict[str, Any]:  # type: ignore[override]
    pair = case.counterparty_pair
    if pair and isinstance(pair, tuple) and len(pair) == 2 and pair[0] and pair[1]:
        pair_text = f"{pair[0]}↔{pair[1]}"
    elif pair and isinstance(pair, tuple):
        # 단일 reciprocal — 한쪽만 의미 있는 경우
        non_empty = [p for p in pair if p]
        pair_text = non_empty[0] if non_empty else "—"
    else:
        pair_text = "—"
    return {
        "case_id": _short_case_id(case.phase2_case_id),
        "_full_case_id": case.phase2_case_id,
        "evidence_tier": _tier_cell(case.evidence_tier),
        "ic_role": case.ic_role or "—",
        "counterparty_pair": pair_text,
        "amount_a": _fmt_amount(case.amount_a),
        "amount_b": _fmt_amount(case.amount_b),
        "linked_to": _linked_to_text(case.phase1_case_refs),
    }


def _build_relational_row(case: RelationalCase) -> dict[str, Any]:  # type: ignore[override]
    metric_name = str(case.metric_name or "").strip()
    try:
        metric_text = f"{metric_name}={float(case.metric_value):.2f}" if metric_name else "—"
    except (TypeError, ValueError):
        metric_text = metric_name or "—"
    return {
        "case_id": _short_case_id(case.phase2_case_id),
        "_full_case_id": case.phase2_case_id,
        "evidence_tier": _tier_cell(case.evidence_tier),
        "sub_rule": case.sub_rule or "—",
        "edge_a": case.edge_a or "—",
        "edge_b": case.edge_b or "—",
        "metric": metric_text,
        "linked_to": _linked_to_text(case.phase1_case_refs),
    }


def _build_unsupervised_row(case: UnsupervisedCase) -> dict[str, Any]:  # type: ignore[override]
    return {
        "case_id": _short_case_id(case.phase2_case_id),
        "_full_case_id": case.phase2_case_id,
        "evidence_tier": _tier_cell(case.evidence_tier),
        "review_unit": _unsupervised_review_unit(case),
        "reason_tag": _fmt_reason_tags(case.top_features),
        "top_feature": _fmt_top_feature(case.top_features),
        "amount_tail": _fmt_context_score(case.amount_tail_context),
        "period_end": _fmt_context_score(case.period_end_context),
        "account_process_rarity": _fmt_account_process_rarity(
            case.account_rarity_context,
            case.process_rarity_context,
        ),
        "evidence_row_count": int(case.evidence_row_count or len(case.row_refs or ())),
        "linked_to": _linked_to_text(case.phase1_case_refs),
    }


def _build_timeseries_row(case: TimeseriesCase) -> dict[str, Any]:  # type: ignore[override]
    start = str(case.window_start or "").strip()
    end = str(case.window_end or "").strip()
    if start and end and start != end:
        window_text = f"{start}~{end}"
    elif start:
        window_text = start
    else:
        window_text = "—"
    return {
        "case_id": _short_case_id(case.phase2_case_id),
        "_full_case_id": case.phase2_case_id,
        "evidence_tier": _tier_cell(case.evidence_tier),
        "sub_rule": case.sub_rule or "—",
        "subject": case.subject or "—",
        "window": window_text,
        "daily_count": int(case.daily_count or 0),
        "linked_to": _linked_to_text(case.phase1_case_refs),
    }


# ---------------------------------------------------------------------------
# Master 표 + selection
# ---------------------------------------------------------------------------


def _render_master_table(
    family: str,
    frame: pd.DataFrame,
    cases: Sequence[Phase2CaseBase],
) -> str | None:
    """AgGrid 기반 master 표 — 선택된 row 의 full case_id 반환.

    family 별 컬럼이 다르므로 generic 빌더 — `_full_case_id` 는 hidden 식별자.
    """
    if frame.empty:
        return None

    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    visible_frame = frame.drop(columns=["_full_case_id"], errors="ignore")
    gb = GridOptionsBuilder.from_dataframe(visible_frame)
    gb.configure_default_column(resizable=True, filter=True, sortable=True, wrapText=False)
    gb.configure_selection(selection_mode="single", use_checkbox=False, pre_selected_rows=[0])
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=25)
    gb.configure_grid_options(
        rowSelection="single",
        suppressRowClickSelection=False,
        suppressCellFocus=True,
        rowHeight=34,
    )
    # evidence_tier 컬럼: 사용자 식별성 강화 — cellStyle 로 색상 부여
    if "evidence_tier" in visible_frame.columns:
        # AgGrid JS 없이 표에서는 폭만 고정하고, 색상 강조는 detail 패널 badge 에서 처리.
        gb.configure_column("evidence_tier", minWidth=110, maxWidth=140)
    if "linked_to" in visible_frame.columns:
        gb.configure_column("linked_to", minWidth=160, tooltipField="linked_to")

    grid_options = gb.build()
    response = AgGrid(
        visible_frame,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=False,
        fit_columns_on_grid_load=True,
        height=min(420, 60 + 34 * min(len(visible_frame), 10)),
        key=f"phase2_native_case_master_{family}",
        theme="alpine",
    )
    selected_rows = response.get("selected_rows") if isinstance(response, dict) else None
    if selected_rows is None:
        return None
    # selected_rows 가 list 또는 DataFrame 으로 반환될 수 있음
    if isinstance(selected_rows, pd.DataFrame):
        if selected_rows.empty:
            return None
        short_id = str(selected_rows.iloc[0].get("case_id") or "")
    elif isinstance(selected_rows, list):
        if not selected_rows:
            return None
        first = selected_rows[0]
        if not isinstance(first, dict):
            return None
        short_id = str(first.get("case_id") or "")
    else:
        return None
    if not short_id:
        return None
    # short_id → full_id 역매핑
    for case in cases:
        if _short_case_id(case.phase2_case_id) == short_id:
            return case.phase2_case_id
    return None


# ---------------------------------------------------------------------------
# Detail 패널
# ---------------------------------------------------------------------------


def _render_case_detail(
    case: Phase2CaseBase,
    *,
    phase1_case_lookup: dict[str, dict],
    pr=None,
) -> None:
    """선택된 case 의 상세 — Phase 1 case drilldown 패턴 정합.

    구성: Case 설명 → 문서 master(AgGrid, document_id 등) → 선택 문서의 원장 라인.
    pr 가 없거나 row_refs 의 document_id 가 비어 있으면 fallback (row_refs 텍스트 + linked Phase 1).
    """
    with st.container(border=True):
        tier_key = str(case.evidence_tier or "").lower()
        tier_color = _TIER_COLOR.get(tier_key, "#6B7280")
        tier_label = _TIER_LABEL_KR.get(tier_key, case.evidence_tier or "—")

        st.markdown(
            f"<div style='display:flex; gap:0.6rem; align-items:center; margin-bottom:0.35rem;'>"
            f"<div style='font-size:1rem; font-weight:700; color:#111827;'>"
            f"📋 {_html.escape(case.phase2_case_id)}</div>"
            f"<div style='font-size:0.78rem; padding:2px 8px; border-radius:10px;"
            f" background:{tier_color}; color:white; font-weight:600;'>{tier_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Case 설명 — family 별 핵심 attribute 를 1~2 문장으로 풀어 표시.
        narrative = _build_case_narrative(case)
        st.markdown(f"**Case 설명**  \n{narrative}")

        if isinstance(case, UnsupervisedCase):
            _render_unsupervised_evidence_rows(case)

        # 문서 master + 라인: pr 필요. pr 미주입 시 row_refs 텍스트 fallback.
        document_ids = _document_ids_from_row_refs(case.row_refs)
        if pr is not None and document_ids:
            _render_phase2_case_documents(case, document_ids, pr=pr)
        elif case.row_refs:
            st.markdown(f"**Row refs ({len(case.row_refs)})**")
            row_lines = [_format_row_ref_line(ref) for ref in case.row_refs[:50]]
            st.markdown("\n".join(f"- {line}" for line in row_lines))
            if len(case.row_refs) > 50:
                st.caption(f"전체 {len(case.row_refs)}건 중 상위 50건만 표시.")

        # Linked PHASE1 (간단 표시 — Phase 1 case 와의 cross-ref)
        refs = case.phase1_case_refs
        if refs:
            st.markdown(f"**연계 PHASE1 case ({len(refs)})**")
            lines: list[str] = []
            for ref in refs:
                meta = phase1_case_lookup.get(ref, {})
                band = str(meta.get("priority_band") or "").strip()
                if band:
                    lines.append(f"- `{ref}` · {band.upper()}")
                else:
                    lines.append(f"- `{ref}`")
            st.markdown("\n".join(lines))


# ---------------------------------------------------------------------------
# Case 설명 / 문서 master / raw lines
# ---------------------------------------------------------------------------


# family → 한국어 base 라벨 (narrative 첫 토큰).
_FAMILY_NARRATIVE_LABEL: dict[str, str] = {
    "duplicate": "중복 전표 신호",
    "intercompany": "관계사 거래 신호",
    "relational": "관계망 신호",
    "unsupervised": "비지도 statistical outlier 신호",
    "timeseries": "시점 컨텍스트 신호",
}


def _build_case_narrative(case: Phase2CaseBase) -> str:
    """family 별 핵심 attribute 를 합쳐 1~2 문장 설명을 만든다.

    감사인 화면 첫 문장에서 "어떤 종류의 신호인지 + 강도 + 핵심 attribute" 가 보여야 한다.
    """
    tier_label = _TIER_LABEL_KR.get(
        str(case.evidence_tier or "").lower(), case.evidence_tier or "—"
    )
    base = _FAMILY_NARRATIVE_LABEL.get(case.family, f"{case.family} 신호")
    detail = _family_specific_detail(case)
    head = f"{base} · {tier_label} 강도"
    if detail:
        return f"{head}. {detail}"
    return f"{head}."


def _family_specific_detail(case: Phase2CaseBase) -> str:
    """family 별 추가 attribute 요약 (sub_rule, pair, metric 등)."""
    from src.models.phase2_case import (
        DuplicateCase,
        IntercompanyCase,
        RelationalCase,
        TimeseriesCase,
        UnsupervisedCase,
    )

    if isinstance(case, DuplicateCase):
        parts = []
        if case.sub_rule:
            parts.append(f"sub_rule {case.sub_rule}")
        left = _row_label(case.left_ref)
        right = _row_label(case.right_ref)
        if left != "—" or right != "—":
            parts.append(f"{left} ↔ {right}")
        return " · ".join(parts)
    if isinstance(case, IntercompanyCase):
        parts = []
        if case.ic_role:
            parts.append(f"역할 {case.ic_role}")
        pair = case.counterparty_pair
        if pair and pair[0] and pair[1]:
            parts.append(f"{pair[0]}↔{pair[1]}")
        if case.amount_a is not None or case.amount_b is not None:
            parts.append(f"금액 {_fmt_amount(case.amount_a)} vs {_fmt_amount(case.amount_b)}")
        return " · ".join(parts)
    if isinstance(case, RelationalCase):
        parts = []
        if case.sub_rule:
            parts.append(f"sub_rule {case.sub_rule}")
        if case.edge_a or case.edge_b:
            parts.append(f"{case.edge_a or '—'} → {case.edge_b or '—'}")
        if case.metric_name:
            try:
                parts.append(f"{case.metric_name}={float(case.metric_value):.2f}")
            except (TypeError, ValueError):
                parts.append(f"{case.metric_name}={case.metric_value}")
        return " · ".join(parts)
    if isinstance(case, UnsupervisedCase):
        parts = []
        try:
            parts.append(f"statistical outlier score={float(case.anomaly_score):.4f}")
        except (TypeError, ValueError):
            pass
        total = int(case.evidence_row_count or len(case.row_refs or ()))
        if total:
            parts.append(f"evidence rows {total}")
        if case.top_features:
            feature = _fmt_top_feature(case.top_features)
            if feature != "—":
                parts.append(f"top feature {feature}")
            reason_tags = _fmt_reason_tags(case.top_features)
            if reason_tags != "—":
                parts.append(f"reason tag {reason_tags}")
        grouping = str((case.case_generation_reason or {}).get("document_grouping") or "")
        if grouping == "fallback_row_identity":
            parts.append("전표 식별자가 없어 단일 행 기준으로 표시")
        return " · ".join(parts)
    if isinstance(case, TimeseriesCase):
        parts = []
        if case.sub_rule:
            parts.append(f"sub_rule {case.sub_rule}")
        if case.subject:
            parts.append(f"대상 {case.subject}")
        window = ""
        if case.window_start and case.window_end and case.window_start != case.window_end:
            window = f"{case.window_start}~{case.window_end}"
        elif case.window_start:
            window = case.window_start
        if window:
            parts.append(f"기간 {window}")
        if case.daily_count:
            expected_text = (
                f" (기대 {case.expected_count:.1f})" if case.expected_count is not None else ""
            )
            parts.append(f"건수 {case.daily_count}{expected_text}")
        return " · ".join(parts)
    return ""


def _document_ids_from_row_refs(row_refs: tuple[Phase2RowRef, ...]) -> list[str]:
    """row_refs 에서 unique document_id 를 등장 순으로 반환."""
    seen: set[str] = set()
    out: list[str] = []
    for ref in row_refs or ():
        doc_id = str(ref.document_id or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(doc_id)
    return out


def _render_phase2_case_documents(
    case: Phase2CaseBase,
    document_ids: list[str],
    *,
    pr,
) -> None:
    """문서 master(AgGrid) + 선택된 문서의 원장 라인 — Phase 1 와 같은 UX."""
    # Phase 1 의 검증된 헬퍼를 재사용해 표/포맷/라인 표시 정합.
    from dashboard.tab_phase1 import (
        _render_case_drilldown_document_master,
        _render_raw_lines_table,
    )

    documents = _build_phase2_documents_list(case, document_ids, pr=pr)
    if not documents:
        st.caption("선택된 case 의 원장 데이터를 찾지 못했습니다.")
        return

    safe_key = case.phase2_case_id.replace(" ", "_")
    selected_doc = _render_case_drilldown_document_master(
        documents,
        key_suffix=f"phase2_{safe_key}",
    )
    if not selected_doc:
        return

    raw_lines = _phase2_case_document_raw_lines(pr, case, selected_doc)
    if not raw_lines:
        st.caption("선택된 전표의 원장 라인을 찾지 못했습니다.")
        return
    _render_raw_lines_table("", raw_lines, key_suffix=f"phase2_case_{safe_key}")


def _render_unsupervised_evidence_rows(
    case: UnsupervisedCase,
    *,
    limit: int = _UNSUPERVISED_DETAIL_EVIDENCE_LIMIT,
) -> None:
    """D2 detail: show top-N evidence row refs and the total evidence count."""
    total = int(case.evidence_row_count or len(case.row_refs or ()))
    if total <= 0 or not case.row_refs:
        return

    display_rows = _unsupervised_evidence_row_display_rows(case)
    visible = display_rows[:limit]
    st.markdown(f"**Evidence rows ({len(visible)} / {total})**")
    st.dataframe(pd.DataFrame(visible), width="stretch", hide_index=True)
    if total > len(visible):
        st.caption(f"전체 evidence row {total:,}건 중 상위 {len(visible):,}건만 표시합니다.")


def _unsupervised_evidence_row_display_rows(case: UnsupervisedCase) -> list[dict[str, str]]:
    trace_rows = case.case_generation_reason.get("evidence_rows") or []
    ref_by_key = {ref.index_label: ref for ref in case.row_refs or ()}
    ref_by_position = {int(ref.row_position): ref for ref in case.row_refs or ()}
    ref_by_line = {_line_number_int(ref): ref for ref in case.row_refs or ()}
    rows: list[dict[str, str]] = []
    if isinstance(trace_rows, list):
        for item in sorted(
            (row for row in trace_rows if isinstance(row, dict)),
            key=lambda row: (
                -_as_float(row.get("score")),
                -_as_float(row.get("ecdf")),
                int(row.get("row_position") or 0),
            ),
        ):
            ref = ref_by_key.get(str(item.get("row_ref") or ""))
            row_position = _optional_int(item.get("row_position"))
            ref = ref or ref_by_position.get(row_position)
            ref = ref or ref_by_line.get(row_position)
            rows.append(
                {
                    "row_ref": _row_label(ref) if ref else "—",
                    "score": _fmt_decimal(item.get("score")),
                    "ecdf": _fmt_decimal(item.get("ecdf")),
                    "trace": "max score row" if _same_row_ref(ref, case.max_score_row_ref) else "",
                }
            )
    if rows:
        return rows

    return [
        {
            "row_ref": _row_label(ref),
            "score": "—",
            "ecdf": "—",
            "trace": "max score row" if _same_row_ref(ref, case.max_score_row_ref) else "",
        }
        for ref in _ordered_unsupervised_row_refs(case)
    ]


def _line_number_int(ref: Phase2RowRef) -> int:
    value = getattr(ref, "line_number_key", None)
    if value is None:
        return -1
    try:
        return int(str(value).removeprefix("i:"))
    except ValueError:
        return -1


def _optional_int(value: Any) -> int:
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_decimal(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "—"


def _ordered_unsupervised_row_refs(case: UnsupervisedCase) -> list[Phase2RowRef]:
    refs = list(case.row_refs or ())
    max_ref = case.max_score_row_ref
    if max_ref is None:
        return refs
    return sorted(refs, key=lambda ref: (0 if _same_row_ref(ref, max_ref) else 1, ref.row_position))


def _same_row_ref(left: Phase2RowRef | None, right: Phase2RowRef | None) -> bool:
    if left is None or right is None:
        return False
    return (
        left.row_position == right.row_position
        and left.index_label == right.index_label
        and left.document_id == right.document_id
    )


def _build_phase2_documents_list(
    case: Phase2CaseBase,
    document_ids: list[str],
    *,
    pr,
) -> list[dict[str, Any]]:
    """document_id set 으로 pr.data 를 집계해 문서 master rows 를 만든다.

    Phase 1 ``_render_case_drilldown_document_master`` 가 기대하는 컬럼
    (document_id, posting_date, created_by, gl_account, debit_amount,
    credit_amount, matched_rules) 을 채운다. matched_rules 컬럼은 PHASE2 case
    의 family/sub_rule 라벨로 대체해 감사인이 즉시 신호 종류를 인지하도록 한다.
    """
    df = getattr(pr, "featured_data", None)
    if df is None or getattr(df, "empty", True):
        df = getattr(pr, "data", None)
    if df is None or df.empty or "document_id" not in df.columns:
        return []

    subset = _phase2_case_document_subset(df, case)
    if subset.empty:
        document_id_str = df["document_id"].astype(str)
        subset = df[document_id_str.isin(set(document_ids))]
    if subset.empty:
        return []

    phase2_signal_label = _phase2_signal_label(case)
    documents: list[dict[str, Any]] = []
    for doc_id in document_ids:
        group = subset[subset["document_id"].astype(str) == doc_id]
        if group.empty:
            continue
        first = group.iloc[0]
        row: dict[str, Any] = {
            "document_id": doc_id,
            "posting_date": first.get("posting_date") if "posting_date" in group.columns else "",
            "created_by": first.get("created_by") if "created_by" in group.columns else "",
            "gl_account": first.get("gl_account") if "gl_account" in group.columns else "",
        }
        if "debit_amount" in group.columns:
            row["debit_amount"] = float(group["debit_amount"].fillna(0).sum())
        if "credit_amount" in group.columns:
            row["credit_amount"] = float(group["credit_amount"].fillna(0).sum())
        row["matched_rules"] = phase2_signal_label
        documents.append(row)
    return documents


def _phase2_case_document_raw_lines(
    pr,
    case: Phase2CaseBase,
    selected_doc: str,
) -> list[dict[str, Any]]:
    df = getattr(pr, "featured_data", None)
    if df is None or getattr(df, "empty", True):
        df = getattr(pr, "data", None)
    if df is None or df.empty or "document_id" not in df.columns:
        return []
    subset = _phase2_case_document_subset(df, case)
    if subset.empty:
        subset = df[df["document_id"].astype(str) == str(selected_doc)]
    else:
        subset = subset[subset["document_id"].astype(str) == str(selected_doc)]
    if subset.empty:
        return []
    return subset.to_dict("records")


def _phase2_case_document_subset(df: pd.DataFrame, case: Phase2CaseBase) -> pd.DataFrame:
    """Return ledger rows matching case document keys, preserving company isolation."""
    if df.empty or "document_id" not in df.columns:
        return df.iloc[0:0]
    keys = _document_keys_from_row_refs(case.row_refs)
    if not keys:
        return df.iloc[0:0]
    mask = pd.Series(False, index=df.index)
    doc_values = df["document_id"].astype(str)
    company_values = df["company_code"].astype(str) if "company_code" in df.columns else None
    for company_code, document_id in keys:
        key_mask = doc_values == document_id
        if company_values is not None and company_code:
            key_mask &= company_values == company_code
        mask |= key_mask
    return df[mask]


def _document_keys_from_row_refs(
    row_refs: tuple[Phase2RowRef, ...],
) -> list[tuple[str | None, str]]:
    seen: set[tuple[str | None, str]] = set()
    out: list[tuple[str | None, str]] = []
    for ref in row_refs or ():
        doc_id = str(ref.document_id or "").strip()
        if not doc_id:
            continue
        company_code = str(ref.company_code or "").strip() or None
        key = (company_code, doc_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _phase2_signal_label(case: Phase2CaseBase) -> str:
    """case 를 짧은 한국어 신호 라벨로 — Phase 1 의 matched_rules 칼럼 자리에 들어간다."""
    tier_label = _TIER_LABEL_KR.get(
        str(case.evidence_tier or "").lower(), case.evidence_tier or "—"
    )
    sub_rule = str(getattr(case, "sub_rule", "") or "").strip()
    ic_role = str(getattr(case, "ic_role", "") or "").strip()
    base = _FAMILY_NARRATIVE_LABEL.get(case.family, case.family)
    suffix = sub_rule or ic_role
    if suffix:
        return f"{base} · {suffix} · {tier_label}"
    return f"{base} · {tier_label}"


def _format_row_ref_line(ref: Phase2RowRef) -> str:
    """row_ref 한 줄 요약 — `doc-id line N (company)`."""
    parts: list[str] = []
    if ref.document_id:
        parts.append(f"`{ref.document_id}`")
    if ref.line_number_key:
        parts.append(f"line {ref.line_number_key}")
    if ref.company_code:
        parts.append(f"({ref.company_code})")
    if not parts:
        parts.append(f"`{ref.index_label}`")
    return " ".join(parts)


__all__ = ["render_phase2_native_case_panel"]
