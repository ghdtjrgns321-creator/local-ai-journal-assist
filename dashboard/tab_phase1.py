from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard._state import (
    KEY_ACTIVE_RESULT_TAB,
    KEY_PENDING_RESULT_TAB,
    KEY_TOP_LEVEL_NAV,
    PAGE_PHASE1,
    PAGE_PHASE2,
)
from src.detection.constants import RULE_CODES
from src.detection.rule_detail_metadata import (
    PresenterSurface,
    get_rule_detail_metadata,
    include_in_l1_l4_transaction_count,
)
from src.detection.rule_detail_metadata import (
    canonicalize_rule_id as _canonicalize_metadata_rule_id,
)
from src.detection.rule_scoring import TOPIC_REGISTRY
from src.export.phase1_case_view import (
    _case_row,
    _case_signal_counts,
    _case_topic_ids,
    _case_topic_score,
    build_phase1_audit_risk_by_queue,
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    build_phase1_data_quality_gate,
    build_phase1_integrity_rule_view,
    build_phase1_raw_rule_truth_index,
    build_phase1_review_candidate_summary,
    build_phase1_rule_case_doc_map,
    build_phase1_rule_cases,
    build_phase1_rule_document_counts,
    build_phase1_rule_document_detail,
    build_phase1_rule_documents,
    build_phase1_topic_top_n,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)

# Why: TOPIC_REGISTRY.label 은 export/리포트 API 의 외부 계약이라 변경 시 파급이 크다.
#      대시보드 탭과 우측 차트에서만 쓸 짧은 라벨을 별도 매핑으로 분리.
_TOPIC_SHORT_LABELS: dict[str, str] = {
    "ledger_integrity": "데이터 정합성",
    "approval_control": "권한·통제",
    "closing_timing": "결산·시점",
    "account_logic": "계정·분류",
    "duplicate_outflow": "자금 위험",
    "intercompany_cycle": "내부 거래",
    "revenue_statistical": "통계 이상",
}

_DATA_QUALITY_RULES = {"L1-01", "L1-02", "L1-03", "L1-08"}
_PHASE1_RULE_IDS = [
    "L1-01",
    "L1-02",
    "L1-03",
    "L3-01",
    "L4-01",
    "L2-01",
    "L1-04",
    "L2-02",
    "L2-03",
    "L1-05",
    "L1-06",
    "L3-02",
    "L1-07",
    "L1-09",
    "L3-10",
    "L3-12",
    "L3-03",
    "L2-04",
    "L3-04",
    "L3-05",
    "L3-06",
    "L3-07",
    "L1-08",
    "L3-08",
    "L4-03",
    "L4-04",
    "L3-09",
    "L2-05",
    "L4-05",
    "L4-06",
    "L4-02",
    "D01",
    "D02",
]
_MASTER_GRID_COLUMNS = [
    "document_id",
    "posting_date",
    "company_code",
    "business_process",
    "source",
    "created_by",
    "document_type",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "local_amount",
    "risk_level",
    "anomaly_score",
    "flagged_rules",
    "review_rules",
]


def render(prep_result, phase1_result) -> None:
    st.subheader("PHASE1 결과")

    if phase1_result is None:
        st.info("아직 Phase 1 분석 결과가 없습니다.")
        if prep_result is None:
            st.caption("회사별 설정 탭에서 데이터를 먼저 준비하세요.")
            return
        _render_prep_summary(prep_result)
        # Why: 미리 st.empty() 를 깔면 빈 슬롯이 항상 박스로 남는다(tab_overview 와 동일 이슈).
        #      placeholder 없이 직접 버튼/spinner 만 그려 빈 박스 잔상을 제거한다.
        if st.button("Phase 1 분석 시작", type="primary", key="run_phase1"):
            with st.spinner("Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다."):
                _start_phase1_analysis()
        return

    summary = summarize_phase1_case_result(phase1_result)
    if summary.get("available"):
        section_tabs = st.tabs(
            ["전체 요약"]
            + [
                _TOPIC_SHORT_LABELS.get(topic_id, topic.label)
                for topic_id, topic in TOPIC_REGISTRY.items()
            ]
            + ["AI 결론"]
        )
        with section_tabs[0]:
            _render_overview(phase1_result, summary)
        for index, (topic_id, topic) in enumerate(TOPIC_REGISTRY.items(), start=1):
            with section_tabs[index]:
                _render_topic_top_n(phase1_result, topic_id, topic.label)
        with section_tabs[-1]:
            _render_ai_conclusion(phase1_result, summary)
        return
    if not summary["available"]:
        st.warning("PHASE1 case 결과를 불러오지 못했습니다.")
        return

    # Why: 라디오 한 줄 → 상단 대분류와 동일한 st.tabs 사용. dashboard/app.py 의
    #      탭 패턴과 일관성을 맞추고, 시각적으로도 "섹션 전환"임을 즉시 인지하게 한다.
    section_tabs = st.tabs(
        [
            "전체데이터",
            "데이터정합성",
            "Topic Top N",
            "Topic 보조 표시",
            "Scenario badge",
            "AI결론",
        ]
    )
    with section_tabs[0]:
        _render_overview(phase1_result, summary)
    with section_tabs[1]:
        _render_data_quality_gate(phase1_result)
    with section_tabs[2]:
        _render_priority_risk_queue(phase1_result)
    with section_tabs[3]:
        _render_low_priority_risk_queue(phase1_result)
    with section_tabs[4]:
        _render_context_review_candidates(phase1_result)
    with section_tabs[5]:
        _render_ai_conclusion(phase1_result, summary)


def _render_prep_summary(prep_result) -> None:
    data = prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    c1, c2, c3 = st.columns(3)
    c1.metric("준비 rows", f"{len(data):,}")
    c2.metric("준비 columns", f"{len(data.columns):,}")
    c3.metric("준비 경고", f"{len(prep_result.warnings):,}")


def _render_phase1_summary_ribbon(
    *,
    row_count: int,
    case_count: int,
    case_ratio: float,
    direct_risk_case_count: int,
    triggered_rule_count: int,
    total_rule_count: int,
    l1_triggered_count: int,
    top_rule_id: str | None,
    top_rule_count: int,
) -> None:
    """KPI 4개를 단일 리본 배너로 표시 — flex 레이아웃 + 세로 구분선.

    Why: 4개 카드가 분리되면 시선이 흩어진다. 하나의 패널로 묶어 '요약 배너'로 인식되게.
    """
    delta_case_html = (
        f"<div style='color:#9CA3AF; font-size:0.72rem; margin-top:3px;'>"
        f"전체의 {case_ratio:.1%}</div>"
        if case_count
        else ""
    )
    high_risk_delta_html = (
        f"<div style='color:#9CA3AF; font-size:0.72rem; margin-top:3px;'>"
        f"전체 {case_count:,}건 중 즉시 검토가 필요한 악성 건수</div>"
        if case_count
        else ""
    )
    # Why: 다른 카드 서브텍스트와 동일한 회색(#9CA3AF)·0.72rem·margin-top:3px 적용.
    #      L1 발동 + 최다 룰을 한 줄에 dot separator(·)로 묶고, 한쪽이 없으면
    #      해당 조각만 출력해 카드 폭(약 300px) 안에서 자연스럽게 한 줄로 표시.
    parts: list[str] = []
    if l1_triggered_count:
        parts.append(f"통제 우회(L1) {l1_triggered_count}건 포함")
    if top_rule_id and top_rule_count:
        parts.append(f"최다 {top_rule_id} ({top_rule_count:,}건)")
    triggered_delta_html = (
        f"<div style='color:#9CA3AF; font-size:0.72rem; margin-top:3px;'>{' · '.join(parts)}</div>"
        if parts
        else ""
    )

    block_style = "text-align:center; flex:1; padding:0 1rem; border-right:1px solid #E5E7EB;"
    last_block_style = "text-align:center; flex:1; padding:0 1rem;"
    label_style = (
        "color:#6B7280; font-size:0.78rem; margin-bottom:6px; "
        "font-weight:500; letter-spacing:0.01em;"
    )
    value_base = "font-size:1.7rem; font-weight:700; letter-spacing:-0.02em; line-height:1.2;"
    unit_style = "font-size:0.95rem; font-weight:500; color:#6B7280;"

    ribbon_html = f"""
<div style="display:flex; justify-content:space-around; align-items:center;
            background:#F9FAFB; padding:0.6rem 1rem;
            border-radius:12px; border:1px solid #F3F4F6;
            box-shadow:0 1px 2px rgba(15,23,42,0.04);
            margin:0.25rem 0 1rem;">
    <div style="{block_style}">
        <div style="{label_style}">총 검사 전표</div>
        <div style="color:#111827; {value_base}">
            {row_count:,} <span style="{unit_style}">건</span>
        </div>
    </div>
    <div style="{block_style}">
        <div style="{label_style}">탐지된 위험 케이스</div>
        <div style="color:#DC2626; {value_base}">
            {case_count:,} <span style="{unit_style}">건</span>
        </div>
        {delta_case_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}">High 리스크 케이스</div>
        <div style="color:#EA580C; {value_base}">
            {direct_risk_case_count:,} <span style="{unit_style}">건</span>
        </div>
        {high_risk_delta_html}
    </div>
    <div style="{last_block_style}">
        <div style="{label_style}">발동된 위험 시나리오</div>
        <div style="color:#111827; {value_base}">
            {triggered_rule_count}
            <span style="{unit_style}">/ {total_rule_count} 개</span>
        </div>
        {triggered_delta_html}
    </div>
</div>
"""
    st.markdown(ribbon_html, unsafe_allow_html=True)


def _render_overview(pr, summary: dict) -> None:
    data = _feature_frame(pr)
    risk_df = _risk_distribution(pr, data)
    row_count = len(data)
    case_count = int(summary.get("case_count", 0) or 0)
    case_ratio = case_count / row_count if row_count else 0.0
    direct_risk_case_count = _direct_risk_case_count(pr)

    # Why: rule_audit 결과를 리본 카드 4(발동된 시나리오 비율, L1 통제 우회 카운트,
    #      최다 발동 룰)와 §2 룰 요약이 공유하므로 한 번만 계산해서 재사용한다.
    rule_audit = _phase1_rule_audit(pr)
    triggered_rule_count = int(rule_audit.get("generated_count", 0) or 0)
    total_rule_count = int(rule_audit.get("target_count", 0) or 0)
    generated_rules = [
        rule for rule in rule_audit.get("rules", []) if rule.get("status") == "generated"
    ]
    l1_triggered_count = sum(
        1 for rule in generated_rules if _rule_layer_prefix(str(rule.get("rule_id", ""))) == "L1"
    )
    # 동률이면 layer 우선순위(L1, L3, L2, L4, D) → rule_id 사전순으로 안정 정렬.
    top_rule = max(
        generated_rules,
        key=lambda r: (
            int(r.get("flag_count", 0) or 0),
            -_RULE_LAYER_ORDER.index(_rule_layer_prefix(str(r.get("rule_id", ""))))
            if _rule_layer_prefix(str(r.get("rule_id", ""))) in _RULE_LAYER_ORDER
            else -len(_RULE_LAYER_ORDER),
        ),
        default=None,
    )
    top_rule_id = str(top_rule.get("rule_id", "")) if top_rule else None
    top_rule_count = int(top_rule.get("flag_count", 0) or 0) if top_rule else 0

    st.markdown("#### 1. PHASE 1 실행 요약")
    _render_phase1_summary_ribbon(
        row_count=row_count,
        case_count=case_count,
        case_ratio=case_ratio,
        direct_risk_case_count=direct_risk_case_count,
        triggered_rule_count=triggered_rule_count,
        total_rule_count=total_rule_count,
        l1_triggered_count=l1_triggered_count,
        top_rule_id=top_rule_id,
        top_rule_count=top_rule_count,
    )

    if not risk_df.empty:
        st.markdown(
            "<div style='color:#18181B; font-size:1rem; font-weight:600; "
            "margin:1.5rem 0 0.75rem;'>위험도 분포</div>",
            unsafe_allow_html=True,
        )
        _render_risk_pie(risk_df, summary.get("topics", []))

    st.markdown("#### 2. 분석 룰 요약")
    _render_phase1_rule_audit(rule_audit)

    # Why: AgGrid 가 무거워 펼친 상태로 default 두면 탭 진입이 느려진다.
    #      expander 로 닫아 두고 사용자가 펼칠 때만 렌더하게 한다.
    with st.expander("3. 전체 데이터 탐색기", expanded=False):
        _render_master_data_grid(pr, data)


_VIEW_MODES: list[tuple[str, str]] = [
    ("전체", "all"),
    ("룰 위반 전표", "rule"),
    ("데이터 정합성 위반", "data_quality"),
    ("Topic score", "audit_risk"),
    ("Scenario detail", "review"),
]
_GRID_ROW_CAP = 100_000


@st.fragment
def _render_master_data_grid(pr, data: pd.DataFrame) -> None:
    """Why: 뷰 모드/룰 선택 변경 시 페이지 전체가 아닌 그리드 영역만 rerun."""
    if data.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    # 1. 뷰 선택 — 단일 radio (mutually exclusive)
    view_labels = [label for label, _ in _VIEW_MODES]
    selected_label = st.radio(
        "뷰 선택",
        options=view_labels,
        horizontal=True,
        key="phase1_grid_view_mode",
        label_visibility="collapsed",
    )
    view_mode = next(code for label, code in _VIEW_MODES if label == selected_label)

    # 2. 룰 모드에서만 multiselect 노출 (보조 컨트롤)
    selected_rules: list[str] = []
    if view_mode == "rule":
        rule_options = _available_rules(data, pr=pr)
        if rule_options:
            selected_rules = st.multiselect(
                "룰 선택 (비워두면 모든 룰 위반 전표)",
                options=rule_options,
                default=[],
                key="phase1_grid_rule_select",
            )

    # 3. 필터 적용 — review case의 document_id 집합도 함께 전달해 case-level 매칭 보강
    review_document_ids = _review_case_document_ids(pr) if view_mode == "review" else None
    filtered = _filter_master_data(
        data,
        pr=pr,
        rule_only=(view_mode == "rule"),
        selected_rules=selected_rules,
        data_quality_only=(view_mode == "data_quality"),
        audit_risk_only=(view_mode == "audit_risk"),
        review_only=(view_mode == "review"),
        review_document_ids=review_document_ids,
    )

    # 4. AgGrid 안전 cap (브라우저 부하 방지)
    truncated = len(filtered) > _GRID_ROW_CAP
    show_df_full = filtered.iloc[:_GRID_ROW_CAP] if truncated else filtered

    display_columns = [column for column in _MASTER_GRID_COLUMNS if column in show_df_full.columns]
    if not display_columns:
        display_columns = list(show_df_full.columns[:20])

    # 5. 건수 표시 — 우측 정렬 caption (카드 박스 제거)
    count_html = (
        f"<div style='text-align:right; color:#6B7280; font-size:0.85rem; "
        f"margin:0.4rem 0 0.6rem;'>"
        f"<b style='color:#111827;'>{len(filtered):,}</b>"
        f" / {len(data):,} rows 조회됨"
    )
    if truncated:
        count_html += f" · 표시 상한 {_GRID_ROW_CAP:,}건 적용"
    count_html += "</div>"
    st.markdown(count_html, unsafe_allow_html=True)

    # 6. AgGrid — 내장 페이지네이션 + 정렬/필터/리사이즈
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    show_df = show_df_full[display_columns].reset_index(drop=True)
    gb = GridOptionsBuilder.from_dataframe(show_df)
    gb.configure_default_column(
        resizable=True,
        filter=True,
        sortable=True,
        floatingFilter=False,
    )
    gb.configure_pagination(
        paginationAutoPageSize=False,
        paginationPageSize=100,
    )
    gb.configure_grid_options(domLayout="normal")
    AgGrid(
        show_df,
        gridOptions=gb.build(),
        height=520,
        theme="streamlit",
        key=f"phase1_master_grid_{view_mode}",
        allow_unsafe_jscode=True,
        update_mode=GridUpdateMode.NO_UPDATE,
    )


@st.fragment
def _render_phase1_rule_audit(rule_audit: dict[str, Any]) -> None:
    """단일 카드에 33개 룰을 한 번에 표시. 룰별 상태 배지를 옆에 부착.

    배지 종류:
      - Flag N건 (생성됨, 강조)
      - 스킵됨 (회색)
      - 미생성 (옅은 회색)
    """
    rules: list[dict[str, Any]] = rule_audit.get("rules", [])
    if not rules:
        st.info("PHASE1 대상 룰이 없습니다.")
        return

    # Why: 사용자 요청 형태 — ⓘ 아이콘은 박스 좌상단 고정, 두 줄 본문은 같은 들여쓰기로
    #      정렬. "위험케이스수"는 옅은 회색 코드형 칩. 통계 줄 없음.
    info_html = (
        "<div style='background:#F8FAFC; border:1px solid #E5E7EB; border-radius:8px; "
        "padding:12px 16px 12px 36px; position:relative; margin:0.25rem 0 0.9rem; "
        "color:#475569; font-size:0.85rem; line-height:1.7;'>"
        "<span style='position:absolute; left:14px; top:12px; color:#64748B; "
        "font-size:0.95rem;'>&#9432;</span>"
        "<div>우측 배지는 "
        "<span style='display:inline-block; padding:1px 6px; background:#F1F5F9; "
        "color:#334155; border:1px solid #E2E8F0; border-radius:4px; font-size:0.78rem; "
        "font-weight:500; margin:0 0.15rem;'>위험케이스수</span>"
        " (검토 대상 미합산, 중복 케이스는 중복 카운트).</div>"
        "<div>룰 행을 클릭하면 상세 설명이 펼쳐집니다.</div>"
        "</div>"
    )
    st.markdown(info_html, unsafe_allow_html=True)

    # 레이어별 그룹화
    groups: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        prefix = _rule_layer_prefix(str(rule.get("rule_id", "")))
        groups.setdefault(prefix, []).append(rule)

    ordered_sections: list[tuple[str, list[dict[str, Any]]]] = []
    rendered_layers: set[str] = set()
    for layer in _RULE_LAYER_ORDER:
        items = groups.get(layer)
        if items:
            items.sort(key=lambda r: str(r.get("rule_id", "")))
            ordered_sections.append((_RULE_LAYER_TITLES[layer], items))
            rendered_layers.add(layer)
    leftover_items: list[dict[str, Any]] = []
    for prefix, items in groups.items():
        if prefix in rendered_layers:
            continue
        leftover_items.extend(items)
    if leftover_items:
        leftover_items.sort(key=lambda r: str(r.get("rule_id", "")))
        ordered_sections.append(("기타", leftover_items))

    # 각 룰 row HTML — 좌: 룰 ID·이름, 우: 상태 배지
    # 섹션 헤더는 회색 배경 + 우측 "총 N건" 으로 구분 (skipped 제외 합계).
    section_html_parts: list[str] = []
    for title, items in ordered_sections:
        rows_html = "".join(_rule_audit_row_html(rule) for rule in items)
        section_total = sum(
            int(item.get("flag_count", 0) or 0)
            for item in items
            if str(item.get("status", "")) != "skipped"
        )
        section_html_parts.append(
            "<div style='background:#FFFFFF; border:1px solid #E5E7EB; "
            "border-radius:12px; box-shadow:0 1px 2px rgba(15,23,42,0.04); "
            "overflow:hidden;'>"
            "<div style='display:flex; justify-content:space-between; align-items:center; "
            "background:#F1F5F9; padding:0.7rem 1.5rem; "
            "border-bottom:1px solid #E5E7EB;'>"
            f"<div style='color:#0F172A; font-size:0.92rem; font-weight:600;'>{title}</div>"
            "<div style='color:#1D4ED8; font-size:0.82rem; font-weight:600;'>"
            f"총 {section_total:,}건</div>"
            "</div>"
            "<div style='padding:0.4rem 1.5rem 0.6rem;'>"
            f"{rows_html}"
            "</div>"
            "</div>"
        )

    # Why: <details>/<summary> 기본 disclosure 삼각형 제거 → 깔끔한 row 디자인 유지.
    #      cursor:pointer + hover/open 배경색으로 클릭 affordance를 살린다.
    style_block = (
        "<style>"
        ".phase1-rules summary { list-style: none; }"
        ".phase1-rules summary::-webkit-details-marker { display: none; }"
        ".phase1-rules summary::marker { display: none; content: ''; }"
        ".phase1-rules summary:hover { background: #F9FAFB; }"
        ".phase1-rules details[open] > summary { background: #F3F4F6; }"
        "@media (max-width: 900px) { "
        ".phase1-rules { grid-template-columns:1fr !important; } "
        "}"
        "</style>"
    )

    full_html = (
        f"{style_block}"
        "<div class='phase1-rules' "
        "style='display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); "
        "gap:1rem; margin:0.25rem 0 1rem;'>" + "".join(section_html_parts) + "</div>"
    )
    st.markdown(full_html, unsafe_allow_html=True)


_RULE_DESCRIPTIONS_KR: dict[str, str] = {
    "L1-01": (
        "한 전표 안에서 차변 합계와 대변 합계가 일치하지 않는 케이스를 잡습니다. "
        "복식부기의 가장 기본 원칙을 깬 구조 오류로, 단순 반올림 오차부터 수기 분개 실수, "
        "횡령 은폐를 위한 의도적 차대 불일치까지 포함됩니다."
    ),
    "L1-02": (
        "전표일자·계정·금액 같이 회계 처리에 필수적인 필드가 비어 있는 라인을 탐지합니다. "
        "회계처리 자체가 불완전하거나 감사 추적이 불가능한 데이터 품질 이슈로, "
        "분석을 시작하기 전에 먼저 정리해야 합니다."
    ),
    "L1-03": (
        "회사 계정과목표(CoA)에 등록되지 않은 계정 코드로 기표된 라인을 잡습니다. "
        "미사용 placeholder 계정(예: 9999, 8888)을 악용한 가공 전표 또는 "
        "데이터 정합성 오류 신호입니다."
    ),
    "L1-04": (
        "결재권자(approved_by)의 위임전결 한도(approval_limit)를 넘는 금액인데도 "
        "그 사람이 승인한 전표입니다. 통제 실패 또는 승인권한 위반 가능성을 직접 가리킵니다."
    ),
    "L1-05": (
        "작성자(created_by)와 승인자(approved_by)가 동일한 전표입니다. "
        "직무 분리(SoD)의 가장 직접적인 위반으로, "
        "1인이 입력·승인을 함께 처리해 통제를 우회한 패턴 — "
        "오스템임플란트 횡령 사례 등에서 반복적으로 등장한 신호입니다."
    ),
    "L1-06": (
        "한 사용자가 충돌하는 권한(구매-지급, 매출-수금, IT 관리자-업무 처리 등)을 "
        "동시에 행사한 케이스입니다. 자기 승인은 L1-05가 따로 보고, "
        "여기서는 권한 결합 자체를 잡습니다."
    ),
    "L1-07": (
        "한도를 넘는 금액인데도 승인자가 비어 있거나, 정상 승인 단계를 거치지 않은 전표입니다. "
        "외감법 §8② 직접 위반으로, 한도초과 + 승인 없음 조합이 가장 강한 신호입니다."
    ),
    "L1-08": (
        "기표일이 속한 달과 전표에 적힌 회계기간(fiscal_period)이 어긋난 케이스입니다. "
        "회사의 회계연도 시작월(예: 1월/4월)을 반영해 환산한 기수와 비교하므로 "
        "단순 month != period 비교보다 정확합니다. "
        "기간귀속 조작, 결산 직전 끼워넣기 등의 신호."
    ),
    "L1-09": (
        "승인자는 있는데 승인 시각이 기록되지 않은 전표입니다. "
        "승인 절차의 추적 가능성을 깨뜨리는 신호이고, 사후 승인이나 위조 가능성이 의심되는 "
        "보강 근거가 됩니다."
    ),
    "L2-01": (
        "승인자의 한도 90% 이상 100% 미만 구간에 금액이 맞춰진 전표입니다. "
        "한도 회피(splitting/structuring)를 의식한 의도적 금액 설정 가능성을 봅니다. "
        "razor band(98% 이상)일수록 의심 강도가 높습니다."
    ),
    "L2-02": (
        "같은 거래처에 같은 금액을 다시 지급한 의심 전표입니다. "
        "reference(증빙번호)가 같으면 강한 신호, 없으면 거래처+금액+45일 이내 재지급으로 "
        "보수적으로 잡습니다. 정기 반복 지급(렌트 등)은 자동으로 제외됩니다."
    ),
    "L2-03": (
        "같은 거래가 여러 번 입력된 케이스 — exact 중복부터 reference 중복, "
        "near 중복(금액·날짜·적요 유사), split 중복(분할 입력)까지 잡습니다. "
        "가공 전표나 재입력 오류 모두 후보가 됩니다."
    ),
    "L2-04": (
        "비용으로 처리해야 할 항목이 자산 계정으로 분개된 케이스입니다. "
        "분식회계의 전형적 수법(예: 개발비 과대자산화)으로 손익을 부풀리는 신호입니다. "
        "자산/비용 계정 prefix 매칭으로 판정."
    ),
    "L2-05": (
        "기표 직후 동일 금액의 반대 분개로 취소된 전표 쌍을 잡습니다. "
        "결산 직전 일시적 손익 조정이나 분식회계 흔적을 지우려는 시도일 수 있고, "
        "정상적인 결산조정도 포함될 수 있어 맥락 검토가 필요합니다."
    ),
    "L3-01": (
        "계정 자체는 유효하지만 거래 성격이나 적요와 어색하게 매칭된 라인을 표시합니다. "
        "예: 매출 적요인데 비용 계정으로 처리된 경우. "
        "L1-03(존재하지 않는 계정)과 다르게 사용된 계정의 의미가 어색한 경우입니다."
    ),
    "L3-02": (
        "자동 인터페이스(SAP IF, 배치 등)로 처리되어야 할 거래가 수기(manual)로 직접 입력된 "
        "케이스입니다. 수기 입력은 자동화 통제를 우회하므로 부정의 출발점이 되기 쉽습니다."
    ),
    "L3-03": (
        "관계사·임원 등 특수관계자(IC) 거래로 추정되는 전표를 검토 대상으로 표시합니다. "
        "계열사 간 자금 이동이나 부당지원 의심이 있어 별도 공시·승인 대상이 됩니다."
    ),
    "L3-04": (
        "기초 또는 기말 5영업일 이내에 집중된 기표를 결산 검토 후보로 표시합니다. "
        "결산조정·이익조정·cutoff 조작이 발생하기 쉬운 시점입니다."
    ),
    "L3-05": (
        "토·일요일에 기표된 전표를 검토 대상으로 표시합니다. "
        "정상 영업일 외 처리이므로 통제 회피·사후 입력 가능성을 본 보조 신호입니다."
    ),
    "L3-06": (
        "영업시간 외(22~06시)에 기표된 전표를 잡습니다. "
        "주말 기표와 함께 비정상 시점 신호로 결합 평가됩니다."
    ),
    "L3-07": (
        "증빙일(document_date)과 기표일(posting_date)의 차이가 비정상적으로 큰 전표입니다. "
        "사후 끼워넣기(backdating), 늦은 cutoff 처리, 증빙 위조 의심의 보조 신호."
    ),
    "L3-08": (
        '적요(line_text)가 비어 있거나 의미 없는 문자열(예: "...", "테스트", '
        "동일 글자 반복)인 전표입니다. 감사 추적성을 깨뜨리는 데이터 품질 이슈이자 "
        "가공 전표의 신호입니다."
    ),
    "L3-09": (
        "가지급금·미결산·임시계정의 잔액이 장기간 해소되지 않은 케이스를 잡습니다. "
        "회계 정리가 누락됐거나, 횡령액을 임시계정에 묻어두는 수법의 신호."
    ),
    "L3-10": (
        "회사 정책상 고위험으로 분류된 계정(현금성 자산, 가지급금, 임원 차입금 등)이 "
        "사용된 라인을 표시합니다. 단독으로는 위반이 아니지만 다른 신호와 결합 시 "
        "우선순위가 올라갑니다."
    ),
    "L3-12": (
        "사용자의 일반 업무 범위(role/process) 밖의 계정·프로세스에 손을 댄 케이스입니다. "
        "L1-06이 직접 SoD 위반을 잡는다면, L3-12는 더 넓은 업무범위 검토 모집단을 표시합니다."
    ),
    "L4-01": (
        "매출 계정 분포에서 통계적으로 벗어난 금액(이상 고액·이상 저액)을 잡습니다. "
        "매출 분식·기말 매출 부풀리기 같은 손익 조작 신호입니다."
    ),
    "L4-02": (
        "첫 자리 숫자 분포가 벤포드 법칙(1이 30.1%, 2가 17.6% ...)과 유의미하게 다른 "
        "모집단을 잡습니다. MAD(평균절대편차) 기준으로 적합/경계/부적합을 판정하며, "
        "인위적 금액 조작의 통계적 증거가 됩니다."
    ),
    "L4-03": (
        "모집단 분포 대비 비정상적으로 큰 금액(상위 percentile)의 전표를 잡습니다. "
        "고액 자체가 위반은 아니지만 우선 검토가 필요한 모집단을 만듭니다."
    ),
    "L4-04": (
        "평소 짝지어지지 않는 차변·대변 계정 조합을 가진 전표입니다. "
        "비정상적인 회계 처리 경로로, 우회 분개나 가공 전표의 신호일 수 있습니다."
    ),
    "L4-05": (
        "특정 짧은 시간대(분 단위)에 다수 전표가 군집된 패턴입니다. "
        "봇/자동화 우회나 batch 처리 이상의 신호."
    ),
    "L4-06": (
        "한 사람이 짧은 시간 안에 다량 전표를 일괄 기표한 패턴입니다. "
        "정상 자동화는 system source로 식별되므로, 사람이 한 일괄 입력만 잡습니다."
    ),
    "D01": (
        "전기 대비 특정 계정의 거래 빈도·금액 분포가 급변한 신호를 잡습니다. "
        "계정 이동, 회계정책 변경, 비정상 거래 시작점을 포착합니다."
    ),
    "D02": (
        "주요 재무비율(매출원가율·인건비율 등)의 분포가 전기 대비 유의미하게 변동한 신호를 "
        "잡습니다. 거시적 손익 조작이나 회계 환경 변화의 신호."
    ),
}


def _badge_style_for_count(flag_count: int) -> tuple[str, str, str]:
    """flag_count → (아이콘, 배경, 글자) — 4단계: 초록 / 노랑 / 빨강 / 불.

    임계값:
      - 0: 초록 ✓
      - 1~99: 노랑 ⚠
      - 100~9,999: 빨강 ⚠
      - 10,000+: 불 🔥
    """
    if flag_count <= 0:
        return "✓", "#DCFCE7", "#15803D"
    if flag_count < 100:
        return "⚠", "#FEF3C7", "#A16207"
    if flag_count < 10_000:
        return "⚠", "#FECACA", "#991B1B"
    return "🔥", "#FFE4D6", "#C2410C"


def _rule_audit_row_html(rule: dict[str, Any]) -> str:
    """단일 룰 row — 좌측 룰명, 우측 상태 배지. 클릭 시 설명이 펼쳐짐."""
    rule_id_raw = str(rule.get("rule_id", ""))
    rule_id = html.escape(rule_id_raw)
    name = html.escape(str(rule.get("name_kr", "")))
    description = html.escape(
        _RULE_DESCRIPTIONS_KR.get(rule_id_raw, "설명이 준비되어 있지 않습니다.")
    )
    status = str(rule.get("status", ""))
    flag_count = int(rule.get("flag_count", 0) or 0)

    # Why: layer_d(D01/D02)는 phase1 본 실행에 통상 포함되지 않는 보조 트랙.
    #      generated 신호가 0 이라면 미실행으로 간주해 강제로 "스킵됨" 으로 표시.
    is_layer_d_unflagged = rule_id_raw in {"D01", "D02"} and flag_count == 0
    if status == "skipped" or is_layer_d_unflagged:
        badge_text = "스킵됨"
        badge_bg = "#F3F4F6"
        badge_color = "#6B7280"
        text_color = "#9CA3AF"
    else:  # generated 또는 no_match — 양쪽 모두 건수 기준 색상화
        icon, badge_bg, badge_color = _badge_style_for_count(flag_count)
        badge_text = f"{icon} {flag_count:,}건"
        text_color = "#111827"

    badge_html = ""
    if badge_text:
        badge_html = (
            f"<span style='background:{badge_bg}; color:{badge_color}; "
            "font-size:0.72rem; font-weight:600; padding:2px 8px; "
            f"border-radius:999px; white-space:nowrap;'>{badge_text}</span>"
        )

    summary_html = (
        "<summary class='rule-summary' "
        "style='display:flex; justify-content:space-between; align-items:center; "
        "padding:7px 0; cursor:pointer; list-style:none;'>"
        f"<span style='color:{text_color}; font-size:0.875rem;'>"
        f"{rule_id} · {name}</span>"
        f"{badge_html}"
        "</summary>"
    )
    detail_html = (
        "<div style='margin:4px 0 8px; padding:10px 12px; "
        "background:#F9FAFB; border:1px solid #F3F4F6; border-radius:8px; "
        "color:#374151; font-size:0.82rem; line-height:1.6;'>"
        f"<div style='color:#6B7280; font-size:0.72rem; margin-bottom:4px;'>"
        f"{rule_id} · {name}</div>"
        f"{description}</div>"
    )
    return f"<details style='border-top:1px solid #F3F4F6;'>{summary_html}{detail_html}</details>"


def _rule_audit_row_html_unused(rule: dict[str, Any]) -> str:
    """레거시 — 사용 안함. 참고용."""
    rule_id = html.escape(str(rule.get("rule_id", "")))
    name = html.escape(str(rule.get("name_kr", "")))
    status = str(rule.get("status", ""))
    flag_count = int(rule.get("flag_count", 0) or 0)

    if status == "generated":
        badge_text = f"Flag {flag_count:,}건"
        badge_bg = "#DCFCE7"
        badge_color = "#15803D"
        text_color = "#111827"
    elif status == "skipped":
        badge_text = "스킵됨"
        badge_bg = "#F3F4F6"
        badge_color = "#6B7280"
        text_color = "#9CA3AF"
    else:
        badge_text = "미생성"
        badge_bg = "#FAFAFA"
        badge_color = "#9CA3AF"
        text_color = "#9CA3AF"

    return (
        "<div style='display:flex; justify-content:space-between; align-items:center; "
        "padding:7px 0; border-top:1px solid #F3F4F6;'>"
        f"<span style='color:{text_color}; font-size:0.875rem;'>"
        f"{rule_id} · {name}</span>"
        f"<span style='background:{badge_bg}; color:{badge_color}; "
        f"font-size:0.72rem; font-weight:600; padding:2px 8px; "
        f"border-radius:999px; white-space:nowrap;'>{badge_text}</span>"
        "</div>"
    )


_RULE_LAYER_ORDER: list[str] = ["L1", "L3", "L2", "L4", "D"]
_RULE_LAYER_TITLES: dict[str, str] = {
    "L1": "L1 · 데이터 정합성 · 기본 통제",
    "L2": "L2 · 거래 패턴 이상",
    "L3": "L3 · 분류 · 시점 · 수기 검토",
    "L4": "L4 · 통계 이상치",
    "D": "D · 분포 변동 (Drift)",
}


def _rule_layer_prefix(rule_id: str) -> str:
    """룰 ID에서 레이어 prefix 추출 — 'L1-01' → 'L1', 'D01' → 'D'."""
    if rule_id.startswith("L") and len(rule_id) >= 2:
        return rule_id[:2]
    if rule_id.startswith("D"):
        return "D"
    return rule_id[:1] or "?"


def _render_rule_list(rows: list[dict[str, str]], *, empty_message: str) -> None:
    """Why: 레이어별로 분리된 dataframe들이 떨어져 보이는 문제 해결.
    한 개의 카드 컨테이너 안에 모든 레이어를 HTML로 렌더하고, 사이는 얇은 구분선만."""
    if not rows:
        st.info(empty_message)
        return

    # 레이어별 그룹화 — '룰' 컬럼 첫 토큰이 룰 ID
    groups: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for row in rows:
        rule_label = str(row.get("룰", ""))
        rule_id = rule_label.split(" ", 1)[0] if rule_label else ""
        prefix = _rule_layer_prefix(rule_id)
        groups.setdefault(prefix, []).append((rule_id, row))

    # 렌더 순서 — 정의된 레이어 순서 + 정의되지 않은 prefix는 마지막 "기타"로
    ordered_sections: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
    rendered_layers: set[str] = set()
    for layer in _RULE_LAYER_ORDER:
        items = groups.get(layer)
        if items:
            items.sort(key=lambda pair: pair[0])
            ordered_sections.append((_RULE_LAYER_TITLES[layer], items))
            rendered_layers.add(layer)
    leftover_items: list[tuple[str, dict[str, str]]] = []
    for prefix, items in groups.items():
        if prefix in rendered_layers:
            continue
        leftover_items.extend(items)
    if leftover_items:
        leftover_items.sort(key=lambda pair: pair[0])
        ordered_sections.append(("기타", leftover_items))

    # HTML 빌드 — 단일 카드 안에 모든 레이어 섹션 + 얇은 구분선
    section_html_parts: list[str] = []
    for index, (title, items) in enumerate(ordered_sections):
        rule_rows_html = "".join(
            f"<div style='padding:6px 0; color:#374151; font-size:0.875rem; "
            f"line-height:1.5; "
            f"border-top:1px solid #F3F4F6;'>{row.get('룰', '')}</div>"
            for _, row in items
        )
        section_margin_top = "0" if index == 0 else "1.25rem"
        section_html_parts.append(
            f"<div style='margin-top:{section_margin_top};'>"
            f"<div style='color:#18181B; font-size:0.95rem; font-weight:600; "
            f"margin-bottom:0.4rem;'>{title}"
            f" <span style='color:#71717A; font-weight:500; font-size:0.8rem;'>"
            f"· {len(items)}건</span></div>"
            f"{rule_rows_html}"
            f"</div>"
        )

    full_html = (
        "<div style='background:#FFFFFF; border:1px solid #E5E7EB; "
        "border-radius:12px; padding:1.1rem 1.4rem; "
        "box-shadow:0 1px 2px rgba(15,23,42,0.04); "
        "margin:0.25rem 0 1rem;'>" + "".join(section_html_parts) + "</div>"
    )
    st.markdown(full_html, unsafe_allow_html=True)


def _render_phase1_rule_audit_static(rule_audit: dict[str, Any]) -> None:
    """Client-side static switcher; changing the view does not rerun Streamlit."""
    widget_id = "phase1-rule-audit"
    views = [
        (
            "all",
            f"PHASE1 전체 룰 {rule_audit['target_count']:,}",
            rule_audit["target_rules"],
            "PHASE1 대상 룰이 없습니다.",
        ),
        (
            "generated",
            f"RuleFlag 생성 룰 {rule_audit['generated_count']:,}",
            rule_audit["generated_rules"],
            "이번 실행에서 RuleFlag가 생성된 룰이 없습니다.",
        ),
        (
            "skipped",
            f"SKIP 룰 {rule_audit['skipped_count']:,}",
            rule_audit["skipped_rules"],
            "SKIP된 룰이 없습니다.",
        ),
    ]

    inputs: list[str] = []
    labels: list[str] = []
    panels: list[str] = []
    checked_styles: list[str] = []
    panel_styles: list[str] = []
    for index, (slug, label, rows, empty_message) in enumerate(views):
        input_id = f"{widget_id}-{slug}"
        checked = " checked" if index == 0 else ""
        inputs.append(f"<input type='radio' name='{widget_id}' id='{input_id}'{checked}>")
        labels.append(f"<label for='{input_id}'>{html.escape(label)}</label>")
        panels.append(
            f"<div class='phase1-rule-panel phase1-rule-panel-{slug}'>"
            f"{_rule_list_html(rows, empty_message=empty_message)}"
            f"</div>"
        )
        checked_styles.append(f"#{input_id}:checked ~ .phase1-rule-labels label[for='{input_id}']")
        panel_styles.append(f"#{input_id}:checked ~ .phase1-rule-panels .phase1-rule-panel-{slug}")

    st.markdown(
        f"""
<style>
.phase1-rule-audit input {{
  position:absolute;
  opacity:0;
  pointer-events:none;
}}
.phase1-rule-labels {{
  display:flex;
  flex-wrap:wrap;
  gap:1rem;
  margin:0 0 1.25rem;
}}
.phase1-rule-labels label {{
  position:relative;
  cursor:pointer;
  color:#111827;
  font-size:0.92rem;
  line-height:1.4;
  padding-left:1.55rem;
  user-select:none;
}}
.phase1-rule-labels label::before {{
  content:"";
  position:absolute;
  left:0;
  top:0.05rem;
  width:0.9rem;
  height:0.9rem;
  border:1px solid #CBD5E1;
  border-radius:999px;
  background:#FFFFFF;
}}
.phase1-rule-labels label::after {{
  content:"";
  position:absolute;
  left:0.25rem;
  top:0.30rem;
  width:0.42rem;
  height:0.42rem;
  border-radius:999px;
  background:#334155;
  opacity:0;
}}
{", ".join(checked_styles)} {{
  font-weight:500;
}}
{", ".join(f"{selector}::before" for selector in checked_styles)} {{
  border-color:#334155;
}}
{", ".join(f"{selector}::after" for selector in checked_styles)} {{
  opacity:1;
}}
.phase1-rule-panel {{
  display:none;
}}
{", ".join(panel_styles)} {{
  display:block;
}}
</style>
<div class='phase1-rule-audit'>
  {"".join(inputs)}
  <div class='phase1-rule-labels'>{"".join(labels)}</div>
  <div class='phase1-rule-panels'>{"".join(panels)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _rule_list_html(rows: list[dict[str, str]], *, empty_message: str) -> str:
    if not rows:
        return (
            "<div style='background:#EFF6FF; color:#1D4ED8; border-radius:8px; "
            "padding:0.9rem 1rem; font-size:0.9rem;'>"
            f"{html.escape(empty_message)}</div>"
        )

    groups: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for row in rows:
        rule_label = str(row.get("룰", ""))
        rule_id = rule_label.split(" ", 1)[0] if rule_label else ""
        prefix = _rule_layer_prefix(rule_id)
        groups.setdefault(prefix, []).append((rule_id, row))

    ordered_sections: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
    rendered_layers: set[str] = set()
    for layer in _RULE_LAYER_ORDER:
        items = groups.get(layer)
        if items:
            items.sort(key=lambda pair: pair[0])
            ordered_sections.append((_RULE_LAYER_TITLES[layer], items))
            rendered_layers.add(layer)

    leftover_items: list[tuple[str, dict[str, str]]] = []
    for prefix, items in groups.items():
        if prefix in rendered_layers:
            continue
        leftover_items.extend(items)
    if leftover_items:
        leftover_items.sort(key=lambda pair: pair[0])
        ordered_sections.append(("기타", leftover_items))

    section_html_parts: list[str] = []
    for index, (title, items) in enumerate(ordered_sections):
        rule_rows_html = "".join(
            "<div style='padding:6px 0; color:#374151; font-size:0.875rem; "
            "line-height:1.5; border-top:1px solid #F3F4F6;'>"
            f"{html.escape(str(row.get('룰', '')))}</div>"
            for _, row in items
        )
        section_margin_top = "0" if index == 0 else "1.25rem"
        section_html_parts.append(
            f"<div style='margin-top:{section_margin_top};'>"
            f"<div style='color:#18181B; font-size:0.95rem; font-weight:600; "
            f"margin-bottom:0.4rem;'>{html.escape(title)}"
            f" <span style='color:#71717A; font-weight:500; font-size:0.8rem;'>"
            f"· {len(items)}건</span></div>"
            f"{rule_rows_html}"
            f"</div>"
        )

    return (
        "<div style='background:#FFFFFF; border:1px solid #E5E7EB; "
        "border-radius:12px; padding:1.1rem 1.4rem; "
        "box-shadow:0 1px 2px rgba(15,23,42,0.04); "
        "margin:0.25rem 0 1rem;'>" + "".join(section_html_parts) + "</div>"
    )


def _cached_phase1_build(pr, name: str, builder, *args, **kwargs):
    """페이지 rerun 사이 build 결과 캐싱 — pr 객체에 attach."""
    cache = getattr(pr, "_phase1_cache", None)
    if cache is None:
        cache = {}
        try:
            object.__setattr__(pr, "_phase1_cache", cache)
        except Exception:
            return builder(pr, *args, **kwargs)
    key = (name, args, tuple(sorted(kwargs.items())))
    if key not in cache:
        cache[key] = builder(pr, *args, **kwargs)
    return cache[key]


def _total_document_count(pr) -> int:
    df = _feature_frame(pr)
    if df is None or df.empty or "document_id" not in df.columns:
        return 0
    return int(df["document_id"].nunique())


def _format_violation_detail_value(item: dict[str, Any]) -> str:
    value = item.get("value")
    kind = str(item.get("kind") or "text")
    unit = item.get("unit")
    if value is None or value == "":
        text = "-"
    elif kind == "amount":
        try:
            text = f"{float(value):,.0f}"
        except (TypeError, ValueError):
            text = str(value)
    elif kind == "ratio":
        try:
            text = f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            text = str(value)
    elif kind in {"number", "delta", "score"}:
        try:
            number = float(value)
            text = f"{number:,.0f}" if abs(number) >= 1 else f"{number:.3f}"
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    if unit and text != "-":
        text = f"{text} {unit}"
    return text


def _render_violation_details(details: list[dict[str, Any]]) -> None:
    if not details:
        st.caption("표시할 상세 증거 항목이 없습니다.")
        return
    for start in range(0, len(details), 3):
        cols = st.columns(min(3, len(details) - start))
        for col, item in zip(cols, details[start : start + 3], strict=False):
            col.metric(
                str(item.get("label") or "상세"),
                _format_violation_detail_value(item),
            )


# Why: 룰마다 사용자가 즉시 봐야 할 핵심 비교 컬럼이 다르다. 공통 컬럼(전표번호/위반 요약/
#      거래금액/Case/Band) 위에 룰별 1~3개 보강 컬럼을 끼워 마스터 표만 봐도 본질이 보이게 한다.
# 형식: (row dict 키, 표시 라벨, kind). kind: amount | ratio | number | delta | score | date | text
_RULE_MASTER_EXTRAS: dict[str, list[tuple[str, str, str]]] = {
    "L1-01": [
        ("debit_amount", "차변", "amount"),
        ("credit_amount", "대변", "amount"),
        ("difference_value", "차이", "amount"),
    ],
    "L1-02": [("difference_value", "누락 개수", "number")],
    "L1-03": [("gl_account", "계정코드", "text")],
    "L1-04": [
        ("approval_limit", "승인한도", "amount"),
        ("difference_value", "초과액", "amount"),
    ],
    "L1-05": [
        ("created_by", "작성자", "text"),
        ("approved_by", "승인자", "text"),
    ],
    "L1-06": [
        ("created_by", "사용자", "text"),
        ("business_process", "프로세스", "text"),
    ],
    "L1-07": [("approved_by", "승인자", "text")],
    "L1-08": [
        ("expected_value", "전기 월", "month"),
        ("actual_value", "회계기간", "period"),
        ("difference_value", "차이(개월)", "delta_months"),
    ],
    "L1-09": [("approved_at", "승인일자", "date")],
    "L2-01": [
        ("approval_limit", "승인한도", "amount"),
        ("difference_value", "한도 사용률", "ratio"),
    ],
    "L2-02": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-03": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-03a": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-03b": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-03c": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-03d": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L2-04": [("gl_account", "계정코드", "text")],
    "L2-05": [("counterparty", "거래처", "text"), ("reference", "참조번호", "text")],
    "L3-01": [
        ("gl_account", "계정", "text"),
        ("business_process", "프로세스", "text"),
    ],
    "L3-02": [("source", "전표 출처", "text")],
    "L3-03": [("counterparty", "거래처", "text")],
    "L3-04": [("posting_date", "전기일", "date")],
    "L3-05": [("posting_date", "전기일", "date")],
    "L3-06": [("posting_date", "전기일", "date")],
    "L3-07": [("difference_value", "일자 차이(일)", "delta_days")],
    "L3-08": [("line_text", "적요", "text")],
    "L3-09": [("gl_account", "계정", "text")],
    "L3-10": [("gl_account", "계정", "text")],
    "L3-11": [("difference_value", "일자 차이(일)", "delta_days")],
    "L3-12": [("business_process", "프로세스", "text")],
    "L4-01": [
        ("gl_account", "계정", "text"),
        ("anomaly_score", "이상점수", "score"),
    ],
    "L4-02": [
        ("company_code", "회사", "text"),
        ("gl_account", "계정", "text"),
    ],
    "L4-03": [("anomaly_score", "이상점수", "score")],
    "L4-04": [
        ("gl_account", "계정", "text"),
        ("anomaly_score", "이상점수", "score"),
    ],
    "L4-05": [("created_by", "작성자", "text"), ("source", "출처", "text")],
    "L4-06": [("created_by", "작성자", "text"), ("source", "출처", "text")],
    "IC01": [("counterparty", "거래처", "text")],
    "IC02": [
        ("counterparty", "거래처", "text"),
        ("difference_value", "금액 차이", "amount"),
    ],
    "IC03": [
        ("counterparty", "거래처", "text"),
        ("difference_value", "시점 차이(일)", "delta_days"),
    ],
    "D01": [
        ("company_code", "회사", "text"),
        ("gl_account", "계정", "text"),
        ("anomaly_score", "변동 점수", "score"),
    ],
    "D02": [
        ("company_code", "회사", "text"),
        ("gl_account", "계정", "text"),
        ("anomaly_score", "분포 점수", "score"),
    ],
}

_RULE_SIGNATURES: dict[str, str] = {
    "L1-01": "전표 단위 차변 합계 = 대변 합계 검증",
    "L1-02": "필수 필드(전기일·계정·금액 등) 누락 검증",
    "L1-03": "전표 라인의 계정이 계정과목표(CoA)에 등록되어 있는지 검증",
    "L1-04": "전표 금액이 작성자/승인자의 승인 한도를 초과했는지 검증",
    "L1-05": "작성자와 승인자가 동일인인지(자기 승인) 검증",
    "L1-06": "사용자 역할·프로세스 직무 분리(SoD) 충돌 검증",
    "L1-07": "승인자(approved_by) 누락 검증",
    "L1-08": "전기일의 월(month)과 회계기간(fiscal_period) 일치 여부 검증",
    "L1-09": "승인일자(approval_date) 누락 검증",
    "L2-01": "전표 금액이 승인 한도 근접 구간(분할 의심)에 있는지 검증",
    "L2-02": "동일 거래처·참조·금액 중복 지급 패턴 검증",
    "L2-03": "동일 시그니처 중복 전표 검증",
    "L2-03a": "완전 일치 중복 전표 검증",
    "L2-03b": "유사 중복 전표 검증",
    "L2-03c": "분할 전표 패턴 검증",
    "L2-03d": "연속 번호 중복 전표 검증",
    "L2-04": "계정 분류 불일치(자산↔비용 등) 검증",
    "L2-05": "역분개(반대 부호 동일 금액) 패턴 검증",
    "L3-01": "프로세스(P2P/O2C 등) 대비 계정 사용 부합성 검증",
    "L3-02": "수기 입력 전표 비중 및 정당성 검증",
    "L3-03": "관계사·내부거래 신호 검증",
    "L3-04": "기말 경계 전기 집중 검증",
    "L3-05": "주말·공휴일 전기 검증",
    "L3-06": "야간·근무외 전기 검증",
    "L3-07": "전기일·증빙일 간격 이상 검증",
    "L3-08": "적요 누락·손상 검증",
    "L3-09": "장기 미해소 임시·반제 계정 검증",
    "L3-10": "민감 계정 사용 검증",
    "L3-11": "기말 컷오프 일자 차이 검증",
    "L3-12": "사용자 작업 범위(회사·프로세스) 광범위 검증",
    "L4-01": "매출 계정 금액 이상치 검증",
    "L4-02": "Benford 법칙 첫자리 분포 편차 검증",
    "L4-03": "고액 이상치(거액 거래) 검증",
    "L4-04": "드문 계정 조합 검증",
    "L4-05": "비정상 시간 클러스터 검증",
    "L4-06": "배치 전기 이상치 검증",
    "IC01": "내부거래 거래처 매칭 검증",
    "IC02": "내부거래 양면 금액 일치 검증",
    "IC03": "내부거래 양면 시점 일치 검증",
    "D01": "전기 대비 계정 활동 변동 검증",
    "D02": "전기 대비 월별 비율 분포 변동 검증",
}

# Why: 원본 전표 상세 내역에서 룰별 위반 컬럼/셀을 시각적으로 강조해 "어디를 봐야 하는지"
#      즉시 보이게 한다. 컬럼명은 raw row의 영문 키.
_RULE_RAW_HIGHLIGHTS: dict[str, set[str]] = {
    "L1-01": {"debit_amount", "credit_amount"},
    "L1-02": set(),  # 빈 셀(누락) 강조 — _render_raw_lines_table에서 special-case
    "L1-03": {"gl_account"},
    "L1-04": {"approval_limit"},
    "L1-05": {"created_by", "approved_by"},
    "L1-06": {"created_by", "business_process"},
    "L1-07": {"approved_by"},
    "L1-08": {"posting_date", "fiscal_period"},
    "L1-09": {"approval_date", "approved_at"},
    "L2-01": {"approval_limit", "amount", "debit_amount", "credit_amount"},
    "L2-02": {"counterparty", "reference"},
    "L2-03": {"counterparty", "reference"},
    "L2-03a": {"counterparty", "reference"},
    "L2-03b": {"counterparty", "reference"},
    "L2-03c": {"counterparty", "reference"},
    "L2-03d": {"counterparty", "reference"},
    "L2-04": {"gl_account"},
    "L2-05": {"counterparty", "reference"},
    "L3-01": {"gl_account", "business_process"},
    "L3-02": {"source"},
    "L3-03": {"counterparty"},
    "L3-04": {"posting_date"},
    "L3-05": {"posting_date"},
    "L3-06": {"posting_date"},
    "L3-07": {"posting_date", "document_date"},
    "L3-08": {"line_text"},
    "L3-09": {"gl_account"},
    "L3-10": {"gl_account"},
    "L3-11": {"posting_date", "document_date"},
    "L3-12": {"business_process", "company_code"},
    "L4-01": {"gl_account", "debit_amount", "credit_amount"},
    "L4-02": {"company_code", "gl_account"},
    "L4-03": {"debit_amount", "credit_amount", "local_amount"},
    "L4-04": {"gl_account"},
    "L4-05": {"created_by", "posting_date"},
    "L4-06": {"created_by", "posting_date"},
    "IC01": {"counterparty"},
    "IC02": {"counterparty", "debit_amount", "credit_amount"},
    "IC03": {"counterparty", "posting_date"},
    "D01": {"company_code", "gl_account"},
    "D02": {"company_code", "gl_account"},
}

_RAW_LINE_COLUMN_LABELS: dict[str, str] = {
    "gl_account": "계정코드",
    "debit_amount": "차변",
    "credit_amount": "대변",
    "line_text": "적요",
    "line_number": "라인",
    "posting_date": "전기일",
    "document_date": "증빙일",
    "fiscal_period": "회계기간",
    "company_code": "회사코드",
    "document_type": "전표유형",
    "business_process": "프로세스",
    "source": "출처",
    "counterparty": "거래처",
    "local_amount": "현지통화금액",
    "created_by": "작성자",
    "approved_by": "승인자",
    "approved_at": "승인시각",
    "approval_date": "승인일자",
    "approval_limit": "승인한도",
    "reference": "참조번호",
    "amount": "거래금액",
    "header_text": "전표적요",
    # §5-4: row Medium 봉우리(0.40)의 99% 가 policy floor 행. 어떤 floor 가 끌어올렸는지
    #       hover/툴팁으로 노출해 운영자가 raw 신호 vs floor escalation 을 구분할 수 있게 한다.
    "risk_level": "행 risk_level",
    "risk_floor_reasons": "행 floor 사유",
}


def _format_master_cell(value: Any, kind: str) -> Any:
    """마스터 표 셀 값을 룰 컬럼 kind에 맞춰 사람 친화 문자열로 변환."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        if kind == "amount":
            return f"{float(value):,.0f}"
        if kind == "ratio":
            return f"{float(value) * 100:.1f}%"
        if kind == "number":
            return f"{float(value):,.0f}"
        if kind == "month":
            return f"{int(float(value))}월"
        if kind == "period":
            return f"{int(float(value))}기"
        if kind == "delta_months":
            return f"{float(value):+.0f}개월"
        if kind == "delta_days":
            return f"{float(value):+.0f}일"
        if kind == "score":
            return f"{float(value):.3f}"
        if kind == "delta":
            return f"{float(value):+,.0f}"
    except (TypeError, ValueError):
        pass
    if kind == "date":
        text = str(value)
        return text[:10] if len(text) >= 10 else text
    return str(value)


def _render_rule_signature_card(
    rule_id: str,
    docs_df: pd.DataFrame,
    review_point: str | None,
) -> None:
    """룰 시그니처 카드 — '이 룰이 무엇을 본다' + 검토 포인트를 한 카드로 통합."""
    signature = _RULE_SIGNATURES.get(rule_id, "")

    parts: list[str] = []
    if signature:
        parts.append(
            f"<div style='font-size:0.95rem; color:#0F172A; margin-bottom:6px;'>"
            f"<span style='color:#0EA5E9; font-weight:700; margin-right:6px; "
            f"font-size:1rem; vertical-align:-1px;'>&#9432;</span>"
            f"{html.escape(signature)}</div>"
        )
    if review_point:
        parts.append(
            "<div style='color:#334155; font-size:0.85rem;'>"
            f"<b>검토 포인트</b> · {html.escape(review_point)}</div>"
        )
    if not parts:
        return
    st.markdown(
        "<div style='background:#F8FAFC; border:1px solid #E5E7EB; border-radius:8px; "
        "padding:10px 14px; margin:0 0 12px;'>" + "".join(parts) + "</div>",
        unsafe_allow_html=True,
    )


def _build_master_display(
    rule_id: str,
    master_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """공통 컬럼 + 룰별 보강 컬럼으로 마스터 표 구성."""
    if "violation_summary" not in master_df.columns:
        master_df["violation_summary"] = master_df.get("evidence_summary", "")
    extras = _RULE_MASTER_EXTRAS.get(rule_id, [])

    rename_map: dict[str, str] = {
        "document_id": "전표번호",
        "violation_summary": "위반 요약",
        "evidence_amount": "거래금액",
        # Why: §5-4 — case priority_band 는 case 우선순위 축. row risk_level 과 다른 축.
        #      라벨 "Case 우선순위" 로 명시해 운영자 혼동을 방지.
        "priority_band": "Case 우선순위",
    }
    ordered_keys: list[str] = ["document_id", "violation_summary"]
    extra_label_kind: list[tuple[str, str]] = []
    for field, label, kind in extras:
        if field not in master_df.columns:
            continue
        display_col = f"_display_{label}"
        master_df[display_col] = master_df[field].map(lambda v, k=kind: _format_master_cell(v, k))
        rename_map[display_col] = label
        ordered_keys.append(display_col)
        extra_label_kind.append((label, kind))

    for tail in ("evidence_amount", "priority_band"):
        if tail in master_df.columns:
            ordered_keys.append(tail)

    available_keys = [key for key in ordered_keys if key in master_df.columns]
    display_df = master_df[available_keys].rename(columns=rename_map)
    return display_df, [label for label, _ in extra_label_kind]


def _render_raw_lines_table(
    rule_id: str,
    raw_lines: list[dict],
    *,
    key_suffix: str = "",
) -> None:
    """원본 전표 라인을 룰별 위반 셀 강조 + 바닥 합계 행과 함께 AgGrid로 렌더링."""
    raw_df = pd.DataFrame(raw_lines)
    if raw_df.empty:
        st.caption("원본 전표 라인을 찾지 못했습니다.")
        return

    preferred = [
        "line_number",
        "gl_account",
        "debit_amount",
        "credit_amount",
        "line_text",
        "posting_date",
        "document_date",
        "fiscal_period",
        "company_code",
        "document_type",
        "business_process",
        "source",
        "counterparty",
        "local_amount",
        "created_by",
        "approved_by",
        "approved_at",
        "approval_date",
        "approval_limit",
        "reference",
        # §5-4: row risk_level 과 risk_floor_reasons 를 함께 노출. floor 가 끌어올린 행을
        #       감사인이 즉시 식별. raw_lines 에 컬럼이 있을 때만 채워진다.
        "risk_level",
        "risk_floor_reasons",
    ]
    # Why: DataSynth 라벨/감사 메타 컬럼(is_fraud, fraud_type, is_anomaly,
    #      anomaly_type, sod_violation, approval_violation 등)은 감사인 화면에
    #      노출할 필요가 없다. preferred 화이트리스트로만 표시하고, 그 외
    #      preferred 에 없는 알려지지 않은 컬럼은 제외한다.
    display_cols = [column for column in preferred if column in raw_df.columns]
    raw_view = raw_df[display_cols].copy()

    label_map = {col: _RAW_LINE_COLUMN_LABELS.get(col, col) for col in raw_view.columns}
    raw_view = raw_view.rename(columns=label_map)
    highlight_eng = _RULE_RAW_HIGHLIGHTS.get(rule_id, set())
    highlight_kor = {label_map.get(col, col) for col in highlight_eng}

    # 컬럼 분류 (영문 키 기준 — 폭/포맷 결정에 사용)
    numeric_eng_cols = ("debit_amount", "credit_amount", "local_amount", "approval_limit", "amount")
    numeric_kor_cols = {label_map[c] for c in numeric_eng_cols if c in display_cols}

    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

    amount_formatter = JsCode(
        "function(p){if(p.value==null||p.value===''||isNaN(p.value))return '';"
        "return Number(p.value).toLocaleString('ko-KR');}"
    )
    highlight_style = JsCode(
        "function(p){return {backgroundColor:'#FEF3C7', fontWeight:'600', color:'#92400E'};}"
    )
    missing_cell_style = JsCode(
        "function(p){"
        "if(p.value==null||p.value==='')"
        "return {backgroundColor:'#FEE2E2', fontStyle:'italic', color:'#991B1B'};"
        "return null;"
        "}"
    )

    gb = GridOptionsBuilder.from_dataframe(raw_view)
    gb.configure_default_column(resizable=True, filter=True, sortable=True, minWidth=70)

    # Why: 짧은 값 컬럼은 (min, max) 로 폭이 늘어남을 막고, 적요/line_text 는 flex 로
    #      잔여 공간을 차지해 그리드가 컨테이너 폭에 자연스럽게 맞도록 한다.
    width_overrides_eng = {
        "line_number": (55, 75),
        "gl_account": (80, 110),
        "fiscal_period": (70, 95),
        "company_code": (75, 105),
        "document_type": (75, 105),
        "business_process": (90, 120),
        "source": (70, 95),
        "counterparty": (110, 160),
        "created_by": (90, 120),
        "approved_by": (90, 120),
        "approved_at": (130, 170),
        "approval_date": (105, 135),
        "posting_date": (105, 135),
        "document_date": (105, 135),
        "reference": (100, 140),
    }

    for col in raw_view.columns:
        configure_kwargs: dict[str, Any] = {}
        eng_col = next((e for e, k in label_map.items() if k == col), col)
        is_numeric = col in numeric_kor_cols
        if is_numeric:
            configure_kwargs["type"] = ["numericColumn", "rightAligned"]
            configure_kwargs["valueFormatter"] = amount_formatter
            configure_kwargs["minWidth"] = 130
            configure_kwargs["maxWidth"] = 180
            configure_kwargs["cellClass"] = "ag-right-aligned-cell"
            configure_kwargs["headerClass"] = "ag-right-aligned-header"
        elif eng_col == "line_text":
            # Why: wrapText=True + autoHeight=True 이면 적요가 두 줄로 분리되어
            #      표 행 높이가 들쑥날쑥. 한 줄 + ellipsis 로 깔끔하게 표시.
            configure_kwargs["minWidth"] = 280
            configure_kwargs["flex"] = 2
            configure_kwargs["wrapText"] = False
            configure_kwargs["autoHeight"] = False
            configure_kwargs["tooltipField"] = col
        elif eng_col in width_overrides_eng:
            min_w, max_w = width_overrides_eng[eng_col]
            configure_kwargs["minWidth"] = min_w
            configure_kwargs["maxWidth"] = max_w

        if rule_id == "L1-02":
            configure_kwargs["cellStyle"] = missing_cell_style
        elif col in highlight_kor:
            configure_kwargs["cellStyle"] = highlight_style

        gb.configure_column(col, **configure_kwargs)

    legend = "  ".join(sorted(highlight_kor))
    if rule_id == "L1-02":
        st.caption("강조: 빈 셀 = 누락된 필수 필드")
    elif legend:
        st.caption(f"강조 컬럼: {legend}")

    aggrid_key = (
        f"phase1_rule_raw_{rule_id}_{key_suffix}" if key_suffix else f"phase1_rule_raw_{rule_id}"
    )
    AgGrid(
        raw_view,
        gridOptions=gb.build(),
        height=290,
        theme="streamlit",
        key=aggrid_key,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
        reload_data=False,
    )


# Why: row risk_level 과 다른 축임을 명시. row 는 ● 원형 + warm 톤, case 는 ◆ 다이아 + cool 톤.
#      audit §5-4 (artifacts/phase1_score_band_audit.md) 운영자 혼동 방지.
_BAND_LABELS = {"high": "◆ case High", "medium": "◆ case Medium", "low": "◆ case Low"}
_ROW_RISK_LABELS = {
    "High": "● 행 High",
    "Medium": "● 행 Medium",
    "Low": "● 행 Low",
    "Normal": "● 행 Normal",
}


def _format_band_cell(value: object) -> str:
    code = str(value or "low").lower()
    return _BAND_LABELS.get(code, code)


def _format_row_risk_cell(value: object) -> str:
    code = str(value or "Normal").strip().title()
    return _ROW_RISK_LABELS.get(code, code)


# §5-4 row risk_level 분포: case 안에 어떤 row risk 가 섞여 있는지 한 줄 막대로 노출.
# Why: v2 high case 229건 안의 row 68% 가 Normal/Low (audit §5-4). case 우선순위 = High
#      라고 해서 그 안 모든 행이 High 인 것이 아님을 시각적으로 즉시 보여준다.
_ROW_RISK_BAR_LEVELS: tuple[str, ...] = ("High", "Medium", "Low", "Normal")
_ROW_RISK_BAR_COLORS: dict[str, str] = {
    "High": "#E54D4D",
    "Medium": "#E09B3D",
    "Low": "#68A8D6",
    "Normal": "#CDD5DF",
}


def _case_row_risk_counts(pr: Any, drilldown: dict[str, Any]) -> dict[str, int]:
    """case raw_rule_hits → row_index 로 featured_data 의 risk_level 분포를 집계."""

    data = getattr(pr, "featured_data", None)
    if data is None:
        data = getattr(pr, "data", None)
    if data is None or "risk_level" not in getattr(data, "columns", []):
        return {}
    raw_hits = drilldown.get("raw_rule_hits") or []
    row_indices = sorted(
        {
            int(hit.get("row_index"))
            for hit in raw_hits
            if hit.get("row_index") is not None and isinstance(hit.get("row_index"), int)
        }
    )
    if not row_indices:
        return {}
    n = len(data)
    valid = [idx for idx in row_indices if 0 <= idx < n]
    if not valid:
        return {}
    subset = data.iloc[valid]
    counts = subset["risk_level"].fillna("Normal").astype(str).value_counts().to_dict()
    return {str(level): int(count) for level, count in counts.items()}


def _row_risk_bar_html(counts: dict[str, int]) -> str:
    """case 행 risk_level 분포 한 줄 막대 + 라벨."""

    total = sum(int(counts.get(level, 0)) for level in _ROW_RISK_BAR_LEVELS)
    if total <= 0:
        return (
            "<div style='font-size:0.78rem; color:#94A3B8;'>"
            "행 risk_level 데이터를 찾지 못했습니다.</div>"
        )
    segments_html: list[str] = []
    legend_html: list[str] = []
    for level in _ROW_RISK_BAR_LEVELS:
        count = int(counts.get(level, 0))
        if count <= 0:
            continue
        pct = count / total * 100.0
        color = _ROW_RISK_BAR_COLORS.get(level, "#CDD5DF")
        segments_html.append(
            f"<div title='{level} {count:,}건 ({pct:.1f}%)' "
            f"style='flex:{pct:.4f} 0 0; background:{color}; height:100%;'></div>"
        )
        legend_html.append(
            f"<span style='display:inline-flex; align-items:center; gap:4px; "
            f"font-size:0.74rem; color:#475569;'>"
            f"<span style='display:inline-block; width:8px; height:8px; "
            f"background:{color}; border-radius:2px;'></span>"
            f"행 {level} {count:,} ({pct:.0f}%)</span>"
        )
    bar = (
        "<div style='display:flex; width:100%; height:10px; border-radius:5px; "
        "overflow:hidden; background:#F1F5F9;'>" + "".join(segments_html) + "</div>"
    )
    legend = (
        "<div style='display:flex; gap:10px; flex-wrap:wrap; margin-top:6px;'>"
        + "".join(legend_html)
        + "</div>"
    )
    note = (
        "<div style='font-size:0.7rem; color:#94A3B8; margin-top:4px;'>"
        "case 우선순위(◆) 와 행 risk_level(●) 은 다른 축. "
        "case High 안에 행 Normal/Low 가 다수일 수 있습니다.</div>"
    )
    return bar + legend + note


def _format_amount_short(value: float) -> str:
    """case master 표 합계 컬럼용 한국식 단위 약어."""
    if not value:
        return "0"
    abs_v = abs(float(value))
    if abs_v >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.1f}조"
    if abs_v >= 100_000_000:
        return f"{value / 100_000_000:.1f}억"
    if abs_v >= 10_000:
        return f"{value / 10_000:.0f}만"
    return f"{value:,.0f}"


@st.fragment
def _render_rule_master_detail(
    rule_id: str,
    rows: list[dict],
    *,
    pr,
    key_suffix: str = "",
    topic_id: str | None = None,
) -> None:
    """Case-centric 3단 master/detail.

    Layer 1: 이 룰이 잡힌 case 목록 (자연어 라벨, 전표수, 합계, band, 사유)
    Layer 2: 선택된 case 안의 위반 전표 목록 (case_id 로 rows 필터)
    Layer 3: 선택된 전표의 위반 상세 + 원본 원장 라인 하이라이트

    Why: 같은 룰이 여러 토픽 탭에 등장할 수 있어 (예: L3-05는 approval_control과 closing_timing
         양쪽에 매핑) AgGrid key 충돌이 발생한다. key_suffix를 받아 토픽별로 고유화한다.
         topic_id: expander 헤더의 case 카운트는 토픽 단위(`_topic_summary_stats`)인데,
         case 목록도 같은 토픽 필터를 적용해야 단위가 일치한다. None 이면 전체 phase1
         case 에서 룰 매칭만 보는 fallback (DQ gate).
         @st.fragment: AgGrid 행 클릭 시 페이지 전체 rerun 으로 브라우저 스크롤이 점프하는
         문제를 막기 위해 master/detail 영역만 부분 rerun 한다.
    """
    # Why: 같은 cache namespace에 topic_id 다른 호출이 섞이지 않도록 key_suffix 가
    #      이미 토픽별로 고유. _cached_phase1_build 의 cache key 는 args+kwargs 해시.
    cases = _cached_phase1_build(
        pr, "rule_cases", build_phase1_rule_cases, rule_id, topic_id=topic_id
    )
    if not cases:
        st.info(f"{rule_id} 매칭 case 가 없습니다.")
        return

    # Why: case 클릭마다 phase1.cases 전체를 linear scan 하면 case 339건 환경에서
    #      체감 지연이 크다. 룰 진입 시 1회만 빌드하고 _cached_phase1_build 캐시에
    #      보관해 case 클릭은 dict lookup 으로 끝낸다.
    case_doc_map = _cached_phase1_build(
        pr,
        "rule_case_doc_map",
        build_phase1_rule_case_doc_map,
        rule_id,
        topic_id=topic_id,
    )

    docs_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    review_points: list[str] = []
    if not docs_df.empty:
        review_points = [
            str(value).strip()
            for value in docs_df.get("review_point", pd.Series(dtype=str)).dropna().unique()
            if str(value).strip()
        ]
    review_point = review_points[0] if review_points else None
    _render_rule_signature_card(rule_id, docs_df, review_point)

    selected_case_id = _render_rule_case_master(rule_id, cases, key_suffix=key_suffix)
    if not selected_case_id:
        st.caption("위 case 목록에서 한 줄을 선택하세요.")
        return

    selected_doc = _render_case_document_master(
        rule_id,
        selected_case_id,
        rows or [],
        case_doc_map=case_doc_map,
        key_suffix=key_suffix,
    )
    if not selected_doc:
        st.caption("위 위반 전표 목록에서 한 줄을 선택하세요.")
        return

    detail = _cached_phase1_build(
        pr,
        "rule_document_detail",
        build_phase1_rule_document_detail,
        rule_id,
        selected_doc,
    )
    if not detail:
        st.caption("선택된 전표의 상세를 찾지 못했습니다.")
        return

    st.markdown("##### 위반 전표 상세 내역")
    _render_violation_details(detail.get("violation_details") or [])
    raw_lines = detail.get("raw_lines") or []
    if not raw_lines:
        st.caption("원본 전표 라인을 찾지 못했습니다.")
        return
    _render_raw_lines_table(rule_id, raw_lines, key_suffix=key_suffix)


def _render_rule_case_master(
    rule_id: str,
    cases: list[dict],
    *,
    key_suffix: str = "",
) -> str | None:
    """Layer 1 — 룰별 case 목록 master. 선택된 case_id 반환."""
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    case_df = pd.DataFrame(
        [
            {
                "case_id": case["case_id"],
                "사례 요약": case["natural_label"],
                "전표 수": int(case["document_count"] or 0),
                "합계": _format_amount_short(float(case["total_amount"] or 0.0)),
                "_total_amount": float(case["total_amount"] or 0.0),
                "Band": _format_band_cell(case["priority_band"]),
                "위험 사유": (case.get("why") or "").strip(),
            }
            for case in cases
        ]
    )

    st.markdown("##### case 목록")
    st.caption(
        f"{len(cases):,}개의 case 가 묶여 있습니다. "
        "case 한 줄을 선택하면 그 묶음 안 위반 전표가 아래에 펼쳐집니다."
    )

    gb = GridOptionsBuilder.from_dataframe(case_df)
    gb.configure_default_column(resizable=True, filter=True, sortable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False, pre_selected_rows=[0])
    gb.configure_grid_options(
        rowSelection="single",
        suppressRowClickSelection=False,
        suppressCellFocus=True,
    )
    gb.configure_column("case_id", hide=True)
    gb.configure_column("_total_amount", hide=True)
    # Why: 사례 요약은 한 줄짜리 키 라벨(20~30자) 이라 좁아도 충분.
    #      위험 사유는 100자 이상 자연어 설명이라 더 넓게 잡아 wrap 줄 수를 줄인다.
    gb.configure_column("사례 요약", minWidth=240, flex=2, wrapText=True, autoHeight=True)
    gb.configure_column("전표 수", type=["numericColumn"], minWidth=70, maxWidth=90)
    gb.configure_column("합계", minWidth=90, maxWidth=120)
    gb.configure_column("Band", minWidth=80, maxWidth=110)
    gb.configure_column("위험 사유", minWidth=360, flex=5, wrapText=True, autoHeight=True)

    suffix = f"_{key_suffix}" if key_suffix else ""
    grid_key = f"phase1_rule_case_master_{rule_id}{suffix}"
    response = AgGrid(
        case_df,
        gridOptions=gb.build(),
        height=320,
        theme="streamlit",
        key=grid_key,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        reload_data=False,
        fit_columns_on_grid_load=True,
    )

    state_key = f"_phase1_case_selection_{grid_key}"
    selected_rows = response.get("selected_rows", [])
    if hasattr(selected_rows, "to_dict"):
        selected_rows = selected_rows.to_dict("records")
    selected_case_id = None
    if selected_rows:
        selected_case_id = str(selected_rows[0].get("case_id") or "")
    if selected_case_id:
        st.session_state[state_key] = selected_case_id
    else:
        selected_case_id = st.session_state.get(state_key)
        if not selected_case_id and not case_df.empty:
            selected_case_id = str(case_df.iloc[0]["case_id"])
    return selected_case_id or None


def _render_case_document_master(
    rule_id: str,
    case_id: str,
    rows: list[dict],
    *,
    case_doc_map: dict[str, dict[str, list[str]]],
    key_suffix: str = "",
) -> str | None:
    """Layer 2 — 선택된 case 안의 위반 전표 master. 선택된 document_id 반환.

    Why: 매번 phase1.cases 를 linear scan 하지 않도록, 룰 진입 시 1회 빌드해
         캐시한 case_id → {hit_documents, related_documents} 매핑을 받아 dict lookup
         으로 필터. hit_documents 는 raw_rule_hits 직접 매칭 doc, related_documents
         는 같은 case 컨텍스트 doc.
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

    if not rows:
        st.caption("이 case 의 위반 전표 데이터를 찾지 못했습니다.")
        return None
    docs_df = pd.DataFrame(rows)

    case_entry = case_doc_map.get(str(case_id), {}) or {}
    hit_doc_ids = set(case_entry.get("hit_documents", []) or [])
    related_doc_ids = set(case_entry.get("related_documents", []) or [])
    if not hit_doc_ids or "document_id" not in docs_df.columns:
        st.caption("이 case 안에 표시할 위반 전표가 없습니다.")
        if related_doc_ids:
            st.caption(f"(같은 case 안에 다른 룰만 잡힌 전표 {len(related_doc_ids):,}건 있음)")
        return None
    filtered = docs_df[docs_df["document_id"].astype(str).isin(hit_doc_ids)].copy()
    if filtered.empty:
        st.caption("이 case 안에 표시할 위반 전표가 없습니다.")
        return None

    cap = min(len(filtered), 500)
    master_df = filtered.head(cap).copy()
    master_display, extra_labels = _build_master_display(rule_id, master_df)
    # Why: 같은 case 안 전표는 모두 동일한 case band 라 컬럼이 중복 정보가 된다.
    if "Case Band" in master_display.columns:
        master_display = master_display.drop(columns=["Case Band"])

    st.markdown("##### 위반 전표 목록")
    if related_doc_ids:
        st.caption(
            f"이 룰로 직접 잡힌 전표 {cap:,}건 (거래금액 큰 순) · "
            f"같은 case 안 다른 룰만 잡힌 전표 {len(related_doc_ids):,}건은 "
            "해당 룰 expander 에서 확인"
        )
    else:
        st.caption(f"이 룰로 직접 잡힌 전표 {cap:,}건 (거래금액 큰 순)")

    amount_formatter = JsCode(
        "function(p){if(p.value==null||p.value===''||isNaN(p.value))return '';"
        "return Number(p.value).toLocaleString('ko-KR');}"
    )
    gb = GridOptionsBuilder.from_dataframe(master_display)
    gb.configure_default_column(resizable=True, filter=True, sortable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False, pre_selected_rows=[0])
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
    gb.configure_grid_options(
        rowSelection="single",
        suppressRowClickSelection=False,
        suppressCellFocus=True,
    )
    if "전표번호" in master_display.columns:
        gb.configure_column("전표번호", minWidth=140, maxWidth=200)
    if "위반 요약" in master_display.columns:
        gb.configure_column("위반 요약", minWidth=200, flex=3, wrapText=True, autoHeight=True)
    if "거래금액" in master_display.columns:
        gb.configure_column(
            "거래금액",
            type=["numericColumn"],
            valueFormatter=amount_formatter,
            minWidth=110,
            maxWidth=160,
        )
    for label in extra_labels:
        if label in master_display.columns:
            gb.configure_column(label, minWidth=70, maxWidth=110)

    suffix = f"_{key_suffix}" if key_suffix else ""
    safe_case_id = str(case_id).replace(" ", "_")
    grid_key = f"phase1_case_doc_master_{rule_id}_{safe_case_id}{suffix}"
    response = AgGrid(
        master_display,
        gridOptions=gb.build(),
        height=380,
        theme="streamlit",
        key=grid_key,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        reload_data=False,
        fit_columns_on_grid_load=True,
    )

    state_key = f"_phase1_case_doc_selection_{grid_key}"
    selected_rows = response.get("selected_rows", [])
    if hasattr(selected_rows, "to_dict"):
        selected_rows = selected_rows.to_dict("records")
    selected_doc = None
    if selected_rows:
        selected_doc = str(selected_rows[0].get("전표번호") or "")
    if selected_doc:
        st.session_state[state_key] = selected_doc
    else:
        selected_doc = st.session_state.get(state_key)
        if not selected_doc and not master_display.empty:
            selected_doc = str(master_display.iloc[0].get("전표번호") or "")
    return selected_doc or None


_DQ_MAIN_RULES: tuple[str, ...] = ("L1-01", "L1-02", "L1-08")
_DQ_MAIN_LABEL = "데이터 정합성 오류"
_DQ_MAIN_DESC = (
    "차대변 합계, 회계기간, 필수 식별자 등 원천 데이터·추출·매핑 단계에서 "
    "발생한 구조 오류 가능성이 큰 항목입니다."
)
_DQ_EXTENDED_CATEGORIES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "계정·마스터 정합성",
        ("L1-03", "L3-01"),
        "마스터 데이터(계정·거래처) 정합성 위반입니다. 무효 계정 코드 사용, "
        "계정 성격과 전표 맥락의 불일치 항목입니다.",
    ),
    (
        "일자·기간 흐름 정합성",
        ("L3-07", "L1-09", "L3-04"),
        "증빙일·기표일·승인일·월말 윈도우 간 흐름이 어색한 항목입니다.",
    ),
    (
        "승인·권한 데이터 정합성",
        ("L1-04", "L1-05", "L1-06", "L1-07"),
        "승인 한도 초과, 자기 승인, 직무 분리(SoD) 위반, 승인 절차 누락 등 "
        "통제 데이터 간 모순 항목입니다.",
    ),
)


@st.fragment
def _render_dq_rule_expanders(items_df: pd.DataFrame, *, pr) -> None:
    """룰별 expander — 헤더 클릭 시 해당 룰의 영향 전표 master/detail이 펼쳐짐.

    @st.fragment: expander on_change="rerun" 이 페이지 전체 rerun 으로 번지지 않도록
    DQ gate 룰 expander 영역만 부분 rerun 으로 한정한다.
    """
    if items_df is None or items_df.empty:
        st.info("표시할 룰이 없습니다.")
        return
    for _, row in items_df.iterrows():
        rule_id = str(row.get("rule_id", ""))
        rule_label = str(row.get("rule_label", ""))
        header = f"**{rule_id} : {rule_label}**"
        exp_key = f"phase1_dq_exp_{rule_id}"
        visited_key = f"{exp_key}__visited"
        with st.expander(header, expanded=False, key=exp_key, on_change="rerun"):
            is_open = bool(st.session_state.get(exp_key, False))
            already_visited = bool(st.session_state.get(visited_key, False))
            if is_open or already_visited:
                st.session_state[visited_key] = True
                rows = _cached_phase1_build(
                    pr, "rule_documents", build_phase1_rule_documents, rule_id
                )
                _render_rule_master_detail(rule_id, rows or [], pr=pr)
            else:
                st.caption("헤더를 클릭해 펼치면 case 목록과 위반 전표가 표시됩니다.")


def _render_dq_category_card(
    title: str,
    description: str,
    items_df: pd.DataFrame,
    *,
    pr,
) -> None:
    st.markdown(f"**{title}**")
    if description:
        st.caption(description)
    cat_docs = int(items_df["documents"].sum()) if not items_df.empty else 0
    st.caption(f"영향 전표 {cat_docs:,}건")
    _render_dq_rule_expanders(items_df, pr=pr)


def _render_data_quality_gate(pr) -> None:
    gate = _cached_phase1_build(pr, "dq_gate", build_phase1_data_quality_gate)
    if not gate["available"]:
        st.info("Data Quality Gate 결과가 없습니다.")
        return

    items_df = pd.DataFrame(gate["items"])
    main_df = (
        items_df[items_df["rule_id"].isin(_DQ_MAIN_RULES)].copy()
        if not items_df.empty
        else items_df
    )

    total_docs = _total_document_count(pr)
    main_docs = int(main_df["documents"].sum()) if not main_df.empty else 0
    impact_ratio = (main_docs / total_docs * 100) if total_docs else 0.0
    st.metric(
        "정합성 위반 전표",
        f"{main_docs:,}",
        delta=f"전체의 {impact_ratio:.2f}%",
        delta_color="inverse" if main_docs else "off",
    )
    st.divider()

    st.markdown("#### 데이터 정합성 오류")
    if main_df.empty:
        st.success("데이터 정합성 오류 룰이 없습니다.")
    else:
        with st.container(border=True):
            _render_dq_category_card(_DQ_MAIN_LABEL, _DQ_MAIN_DESC, main_df, pr=pr)

    st.markdown("#### 추가 정합성 점검 카테고리")
    st.caption(
        "메인 정합성 오류 외에 계정·일자·승인 데이터 영역의 정합성 점검 항목입니다. "
        "Topic score 평가 전에 데이터와 통제 정보의 일관성을 먼저 확인합니다."
    )
    # Why: expander(expanded=False)로 감싸면 펼치지 않은 카테고리는 사용자가 "안 뜬다"고
    #      느낀다. 4개 카테고리는 항상 카드로 펼쳐서 보여주고, 룰 매칭이 0인 경우만 빈 상태
    #      안내를 카드 안에 표시한다.
    extended_rendered = False
    for title, rule_ids, description in _DQ_EXTENDED_CATEGORIES:
        view = _cached_phase1_build(
            pr,
            f"integrity_rule_view::{','.join(rule_ids)}",
            build_phase1_integrity_rule_view,
            tuple(rule_ids),
        )
        cat_items = view.get("items", []) if isinstance(view, dict) else []
        cat_df = pd.DataFrame(cat_items)
        with st.container(border=True):
            if cat_df.empty:
                st.markdown(f"**{title}**")
                if description:
                    st.caption(description)
                st.caption(f"대상 룰: {', '.join(rule_ids)}")
                st.info(f"{title} 항목에 해당하는 위험 케이스가 없습니다.")
            else:
                extended_rendered = True
                _render_dq_category_card(title, description, cat_df, pr=pr)

    if main_df.empty and not extended_rendered:
        st.info("표시할 데이터 정합성 위험 케이스가 없습니다.")


@st.fragment
def _render_topic_top_n(pr, topic_id: str, topic_label: str) -> None:
    """Topic 탭 본체 — 안 1(룰별 master-detail) 전체 적용, 일부 Topic은 안 2/3 시제품 추가.

    Why: 기존에는 와이드 case 테이블 + selectbox 한 개만 있어 "어떤 위반이고 어디에서
         어떤 셀이 문제인지"가 한눈에 안 들어왔다. 데이터정합성 게이트가 쓰는
         _render_rule_master_detail (시그니처 카드 + 셀 강조 그리드 + 증거 칩) 패턴을
         7개 Topic 탭 전체로 확장한다. duplicate_outflow / revenue_statistical 두 곳에는
         What/Where/Why/Action 4분할 패널과 룰×Case 히트맵 시제품을 얹어 시각 비교용으로 둔다.
         @st.fragment: expander on_change="rerun" 이 페이지 전체 rerun 으로 번지면
         스크롤이 페이지 상단으로 점프한다. 토픽 탭 영역만 부분 rerun 되도록 격리.
    """
    st.markdown(f"### {topic_label}")

    rule_groups = _cached_phase1_build(
        pr, "topic_rule_groups", _topic_rule_groups_builder, topic_id
    )
    if not rule_groups:
        st.info(f"{topic_label} 영역에 매칭된 룰 위반이 없습니다.")
        return

    stats = _cached_phase1_build(pr, "topic_summary_stats", _topic_summary_stats, topic_id)
    _render_topic_summary_ribbon(
        case_count=stats["case_count"],
        doc_count=stats["doc_count"],
        rule_count=len(rule_groups),
        high=stats["high"],
        medium=stats["medium"],
        low=stats["low"],
    )

    if topic_id == "duplicate_outflow":
        _render_topic_case_quadrant(pr, topic_id, topic_label)
    elif topic_id == "revenue_statistical":
        _render_topic_rule_case_heatmap(pr, topic_id, rule_groups)

    st.markdown("##### 룰별 위반")
    for group in rule_groups:
        rule_id = group["rule_id"]
        # Why: 헤더는 case(시나리오) 단위 카운트, 아래 위반 전표 목록 표는 document
        #      (전표) 단위라 두 숫자가 일치하지 않는다. 'case'/'전표' 라벨을 명시해
        #      감사인이 단위 차이를 즉시 인지하게 한다.
        bands_chunks: list[str] = []
        if group["high_count"]:
            bands_chunks.append(f"High {group['high_count']}")
        if group["medium_count"]:
            bands_chunks.append(f"Med {group['medium_count']}")
        if group["low_count"]:
            bands_chunks.append(f"Low {group['low_count']}")
        bands_text = " · ".join(bands_chunks)
        doc_count = int(group.get("document_count") or 0)
        if bands_text and doc_count:
            meta = f"case {bands_text} · 전표 {doc_count:,}건"
        elif bands_text:
            meta = f"case {bands_text}"
        elif doc_count:
            meta = f"전표 {doc_count:,}건"
        else:
            meta = ""
        header_main = f"**{rule_id} : {group['rule_label']}**"
        header = f"{header_main}  ({meta})" if meta else header_main
        # Why: with st.expander(...) 안 코드는 collapsed 상태에서도 매번 실행되어
        #      토픽 안 룰 N개 × AgGrid N개를 첫 진입 시 한꺼번에 init 하느라 매우 느려진다.
        #      streamlit 1.55 의 expander key + on_change="rerun" 으로 펼침 상태를
        #      session_state 에 노출하고, 한 번이라도 펼친 룰만 콘텐츠 렌더링 한다.
        exp_key = f"phase1_rule_exp_{topic_id}_{rule_id}"
        visited_key = f"{exp_key}__visited"
        with st.expander(header, expanded=False, key=exp_key, on_change="rerun"):
            is_open = bool(st.session_state.get(exp_key, False))
            already_visited = bool(st.session_state.get(visited_key, False))
            if is_open or already_visited:
                st.session_state[visited_key] = True
                rows = _cached_phase1_build(
                    pr, "rule_documents", build_phase1_rule_documents, rule_id
                )
                _render_rule_master_detail(
                    rule_id, rows or [], pr=pr, key_suffix=topic_id, topic_id=topic_id
                )
            else:
                st.caption("헤더를 클릭해 펼치면 case 목록과 위반 전표가 표시됩니다.")


# Why: PHASE1_TOPIC_SCORING_V1_LOCK 기준 토픽-룰 화이트리스트.
#      RULE_SCORING_REGISTRY의 final/secondary는 priority/triage 점수 계산용이라 macro alias
#      (Benford↔L4-02), 그룹 매크로(GR01/GR03), L2-03 sub-rule(a/b/c/d)까지 포함된다. 대시보드
#      토픽 탭 expander에는 v1 lock 표 그대로만 보여 감사인 멘탈 모델과 1:1 일치시킨다.
#      registry 자체는 변경하지 않아 점수 계산 파급은 없다.
_TOPIC_RULE_WHITELIST: dict[str, set[str]] = {
    "ledger_integrity": {"L1-01", "L1-02", "L1-08", "L3-08"},
    "approval_control": {
        "L1-04",
        "L1-05",
        "L1-06",
        "L1-07",
        "L1-09",
        "L2-01",
        "L3-02",
        "L3-05",
        "L3-06",
        "L3-10",
        "L3-12",
        "L4-05",
    },
    "closing_timing": {
        "L1-08",
        "L3-04",
        "L3-05",
        "L3-06",
        "L3-07",
        "L3-08",
        "L3-11",
        "L4-05",
        "D02",
    },
    "account_logic": {
        "L1-03",
        "L2-04",
        "L3-01",
        "L3-03",
        "L3-09",
        "L3-10",
        "L4-04",
        "D01",
    },
    "duplicate_outflow": {
        "L1-05",
        "L1-07",
        "L2-01",
        "L2-02",
        "L2-03",
        "L2-05",
        "L3-12",
    },
    "intercompany_cycle": {
        "IC01",
        "IC02",
        "IC03",
        "L3-03",
        "L4-04",
        "D01",
        "D02",
    },
    "revenue_statistical": {
        "L3-10",
        "L4-01",
        "L4-02",
        "L4-03",
        "L4-06",
        "Benford",
        "D01",
        "D02",
    },
}


def _metadata_rule_label(rule_id: str) -> str:
    """대시보드 토픽 탭에서 보여줄 룰 라벨.

    Why: v1 lock에 따라 metadata display_copy 우선, legacy `_RULE_NAMES_KR` fallback,
         RULE_CODES fallback 순으로 해석한다. metadata가 없으면 raw rule_id 표시.
    """
    legacy = _RULE_NAMES_KR.get(rule_id)
    if legacy:
        return legacy
    try:
        meta = get_rule_detail_metadata(rule_id)
    except KeyError:
        return RULE_CODES.get(rule_id, rule_id)
    return meta.display_copy.display_title or rule_id


def _rules_for_topic(topic_id: str) -> set[str]:
    """Topic 탭에서 활성화할 룰 집합 (metadata canonical 기준).

    Why: legacy `_TOPIC_RULE_WHITELIST` 는 alias(Benford), macro(D01/D02), 그룹 매크로
         (GR01/03), 사이드카(IC01~03) 등 canonical L1-L4 32개에 포함되지 않는 ID 까지
         포함하고 있었다. metadata `include_in_l1_l4_transaction_count` 와 `allow_topic_seed`
         로 필터링해 사용자에게 보이는 활성 룰을 v1 lock 과 1:1 일치시킨다.
         legacy 화이트리스트는 후보 풀로만 사용한다 (전체 요약 탭 §2 와 무관).
    """
    legacy = set(_TOPIC_RULE_WHITELIST.get(topic_id, set()))
    cleaned: set[str] = set()
    for rule_id in legacy:
        canonical = _canonicalize_metadata_rule_id(rule_id)
        try:
            meta = get_rule_detail_metadata(canonical)
        except KeyError:
            continue
        if include_in_l1_l4_transaction_count(canonical):
            cleaned.add(canonical)
            continue
        # account_process_macro(D01/D02), graph_sidecar(GR01/03) 는 토픽 활성 룰에서 제외.
        # intercompany_sidecar(IC01-03) 만 final_topic 일치 시 sidecar topic seed 로 인정.
        if (
            meta.presenter_surface == PresenterSurface.INTERCOMPANY_SIDECAR
            and meta.final_topic == topic_id
        ):
            cleaned.add(canonical)
    return cleaned


def _topic_rule_groups_builder(pr, topic_id: str) -> list[dict[str, Any]]:
    """Topic 안에서 룰별 case·document·금액·band 집계."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    candidate_rules = _rules_for_topic(topic_id)
    if not candidate_rules:
        return []

    grouped: dict[str, dict[str, Any]] = {}
    for case in phase1.cases:
        # Why: case.topic_scores 만 보면 legacy 케이스(primary_topic 만 채워진)를 놓친다.
        #      build_phase1_topic_top_n이 쓰는 _case_topic_ids/_case_topic_score 와 동일하게
        #      primary/queue/theme/secondary fallback 까지 포함해서 멤버십 판정.
        if topic_id not in _case_topic_ids(case):
            continue
        if _case_topic_score(case, topic_id) <= 0:
            continue
        # Why: raw rule_id 가 alias(Benford) 또는 internal reason(L2-03a~d) 인 경우
        #      canonicalize 후 candidate_rules 와 비교해야 v1 lock 의 canonical 32 기준
        #      활성 룰 집합과 일치한다.
        case_rule_ids: set[str] = set()
        for hit in case.raw_rule_hits or []:
            raw = str(getattr(hit, "rule_id", "") or "")
            if not raw:
                continue
            canonical = _canonicalize_metadata_rule_id(raw)
            if canonical in candidate_rules:
                case_rule_ids.add(canonical)
        if not case_rule_ids:
            continue
        band = (case.priority_band or "low").lower()
        for rule_id in case_rule_ids:
            entry = grouped.setdefault(
                rule_id,
                {
                    "rule_id": rule_id,
                    "rule_label": _metadata_rule_label(rule_id),
                    "cases": set(),
                    "documents": set(),
                    "amount": 0.0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                },
            )
            entry["cases"].add(case.case_id)
            if band in {"high", "medium", "low"}:
                entry[band] += 1
            for doc in case.documents:
                # Why: doc.matched_rules 도 raw alias(Benford)/internal reason(L2-03a)
                #      을 포함할 수 있어 canonical 로 매핑한 뒤 멤버십 비교.
                matched_canonical = {
                    _canonicalize_metadata_rule_id(str(matched))
                    for matched in (doc.matched_rules or [])
                    if matched
                }
                if rule_id in matched_canonical:
                    if doc.document_id not in entry["documents"]:
                        entry["documents"].add(doc.document_id)
                        entry["amount"] += float(doc.amount or 0.0)

    out: list[dict[str, Any]] = []
    for rule_id in _sort_rule_ids(list(grouped.keys())):
        entry = grouped[rule_id]
        out.append(
            {
                "rule_id": rule_id,
                "rule_label": entry["rule_label"],
                "case_count": len(entry["cases"]),
                "document_count": len(entry["documents"]),
                "total_amount": float(entry["amount"]),
                "high_count": entry["high"],
                "medium_count": entry["medium"],
                "low_count": entry["low"],
            }
        )
    out.sort(
        key=lambda r: (
            -r["high_count"],
            -r["case_count"],
            -r["total_amount"],
        )
    )
    return out


def _topic_summary_stats(pr, topic_id: str) -> dict[str, Any]:
    """Topic 요약 리본용 stats — case/doc/금액/band 집계."""
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {
            "case_count": 0,
            "doc_count": 0,
            "total_amount": 0.0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }
    cases: set[str] = set()
    docs: set[str] = set()
    total_amount = 0.0
    high = medium = low = 0
    for case in phase1.cases:
        if topic_id not in _case_topic_ids(case):
            continue
        if _case_topic_score(case, topic_id) <= 0:
            continue
        cases.add(case.case_id)
        for doc in case.documents:
            if doc.document_id not in docs:
                docs.add(doc.document_id)
                total_amount += float(doc.amount or 0.0)
        band = (case.priority_band or "low").lower()
        if band == "high":
            high += 1
        elif band == "medium":
            medium += 1
        else:
            low += 1
    return {
        "case_count": len(cases),
        "doc_count": len(docs),
        "total_amount": total_amount,
        "high": high,
        "medium": medium,
        "low": low,
    }


def _render_topic_summary_ribbon(
    *,
    case_count: int,
    doc_count: int,
    rule_count: int,
    high: int,
    medium: int,
    low: int,
) -> None:
    """Topic 헤더 직하단 4분할 요약 리본."""
    block = "text-align:center; flex:1; padding:0 0.9rem; border-right:1px solid #E5E7EB;"
    last = "text-align:center; flex:1; padding:0 0.9rem;"
    label_style = "color:#6B7280; font-size:0.74rem; margin-bottom:4px; font-weight:500;"
    value_style = "font-size:1.4rem; font-weight:700; letter-spacing:-0.02em; line-height:1.2;"
    unit_style = "font-size:0.85rem; font-weight:500; color:#6B7280;"
    bands_html = (
        f"<span style='color:#DC2626;'>H {high}</span> · "
        f"<span style='color:#EA580C;'>M {medium}</span> · "
        f"<span style='color:#0EA5E9;'>L {low}</span>"
    )
    case_count_html = f'{case_count:,} <span style="{unit_style}">건</span>'
    doc_count_html = f'{doc_count:,} <span style="{unit_style}">건</span>'
    rule_count_html = f'{rule_count:,} <span style="{unit_style}">개</span>'
    ribbon = f"""
<div style="display:flex; align-items:center; background:#F9FAFB;
            border:1px solid #F3F4F6; border-radius:10px;
            padding:0.55rem 0.6rem; margin:0 0 0.9rem;">
  <div style="{block}"><div style="{label_style}">위반 케이스</div>
    <div style="color:#DC2626; {value_style}">{case_count_html}</div></div>
  <div style="{block}"><div style="{label_style}">영향 전표</div>
    <div style="color:#111827; {value_style}">{doc_count_html}</div></div>
  <div style="{block}"><div style="{label_style}">활성 룰</div>
    <div style="color:#111827; {value_style}">{rule_count_html}</div></div>
  <div style="{last}"><div style="{label_style}">위험도 분포</div>
    <div style="font-size:1.05rem; font-weight:700;">{bands_html}</div></div>
</div>"""
    st.markdown(ribbon, unsafe_allow_html=True)


def _render_topic_case_quadrant(pr, topic_id: str, topic_label: str) -> None:
    """안 2 시제품 — Top case의 What/Where/Why/Action 4분할 패널 (자금 위험 탭)."""
    rows = _cached_phase1_build(
        pr,
        "topic_top_n_quadrant",
        build_phase1_topic_top_n,
        topic_id=topic_id,
        top_n=8,
    )
    if not rows:
        return

    options: dict[str, str] = {}
    for row in rows:
        band = str(row.get("priority_band") or "low").upper()
        topic_text = row.get("topic_label") or topic_label
        options[f"{band} · {row.get('case_key', '')} · {topic_text}"] = row["case_id"]
    if not options:
        return

    st.markdown("##### Case 단위 4분할 검토 (시제품)")
    st.caption(
        "What / Where / Why / Action 4축으로 한 케이스를 한 화면에 정리합니다. "
        "선택지는 Topic Top 8 케이스입니다."
    )
    selected_label = st.selectbox(
        "검토할 Case",
        options=list(options.keys()),
        key=f"phase1_quadrant_select_{topic_id}",
    )
    case_id = options[selected_label]
    drilldown = _cached_phase1_build(pr, "case_drilldown", build_phase1_case_drilldown, case_id)
    if drilldown is None:
        return
    case = drilldown["case"]

    band = str(case.get("priority_band") or "low").lower()
    # §5-4: case priority_band 와 row risk_level 은 다른 축. row(warm) 와 색상이 겹치지
    #       않도록 case 축은 cool 톤(indigo/violet/slate) 으로 분리.
    band_color = {"high": "#4338CA", "medium": "#7C3AED", "low": "#94A3B8"}.get(band, "#64748B")
    band_label = {"high": "◆ case High", "medium": "◆ case Medium", "low": "◆ case Low"}.get(
        band, f"◆ case {band.upper()}"
    )

    quad_label_style = (
        "color:#6B7280; font-size:0.72rem; font-weight:600; "
        "letter-spacing:0.04em; text-transform:uppercase; margin-bottom:8px;"
    )
    quad_box_style = (
        "background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px; "
        "padding:14px 16px; min-height:170px;"
    )

    narrative = case.get("risk_narrative") or case.get("representative_explanation") or "—"
    main_reason = case.get("main_reason") or case.get("primary_topic_label") or topic_label

    docs = drilldown.get("documents") or []
    sample_docs = ", ".join(str(doc.get("document_id", "")) for doc in docs[:5])
    rules_hit = sorted(
        {
            str(hit.get("rule_id") or "")
            for hit in drilldown.get("raw_rule_hits", []) or []
            if hit.get("rule_id")
        }
    )
    rule_chip_html = (
        "".join(
            f"<span style='background:#EEF2FF; color:#3730A3; border-radius:6px; "
            f"padding:2px 8px; font-size:0.78rem; font-weight:600;'>"
            f"{html.escape(rule_id)}</span>"
            for rule_id in rules_hit
        )
        or "<span style='color:#94A3B8;'>—</span>"
    )

    score_chips = [
        ("Topic", f"{float(case.get('topic_score') or 0):.2f}"),
        ("Priority", f"{float(case.get('priority_score') or 0):.2f}"),
        ("Direct", f"{int(case.get('direct_risk_count') or 0)}"),
        ("Review", f"{int(case.get('review_context_count') or 0)}"),
        ("Blocker", f"{int(case.get('integrity_blocker_count') or 0)}"),
        ("Macro", f"{int(case.get('macro_finding_count') or 0)}"),
    ]
    chip_html = "".join(
        f"<div style='background:#F8FAFC; border:1px solid #E5E7EB; border-radius:8px; "
        f"padding:6px 10px;'>"
        f"<div style='font-size:0.7rem; color:#64748B;'>{label}</div>"
        f"<div style='font-size:0.95rem; font-weight:700; color:#0F172A;'>{value}</div>"
        f"</div>"
        for label, value in score_chips
    )
    tie_reasons = case.get("queue_tiebreaker_reasons") or case.get("triage_rank_reasons") or []
    tie_text = " / ".join(str(reason) for reason in tie_reasons[:5]) or "—"

    review_focus = case.get("review_focus") or []
    actions = case.get("recommended_audit_actions") or []
    focus_html = (
        "".join(f"<li>{html.escape(str(item))}</li>" for item in review_focus[:5])
        or "<li style='color:#94A3B8;'>—</li>"
    )
    actions_html = (
        "".join(f"<li>{html.escape(str(item))}</li>" for item in actions[:5])
        or "<li style='color:#94A3B8;'>—</li>"
    )

    main_reason_safe = html.escape(str(main_reason))
    narrative_safe = html.escape(str(narrative))
    sample_docs_safe = html.escape(sample_docs) or "—"
    tie_text_safe = html.escape(tie_text)

    panel_a = (
        f"<div style='{quad_box_style}'>"
        f"<div style='{quad_label_style}'>① What · 위반 요지</div>"
        f"<div style='font-size:1rem; color:{band_color}; font-weight:700; margin-bottom:8px;'>"
        f"{band_label} &nbsp;·&nbsp; {main_reason_safe}</div>"
        f"<div style='font-size:0.88rem; color:#334155; line-height:1.55;'>{narrative_safe}</div>"
        f"</div>"
    )
    row_risk_counts = _case_row_risk_counts(pr, drilldown)
    row_risk_bar = _row_risk_bar_html(row_risk_counts)
    panel_b = (
        f"<div style='{quad_box_style}'>"
        f"<div style='{quad_label_style}'>② Where · 발생 위치</div>"
        f"<div style='font-size:0.88rem; color:#334155; margin-bottom:10px;'>"
        f"전표 <b>{int(case.get('document_count') or 0):,}</b>건 · "
        f"라인 <b>{int(case.get('row_count') or 0):,}</b>건 · "
        f"금액 <b>{float(case.get('total_amount') or 0):,.0f}</b></div>"
        f"<div style='font-size:0.78rem; color:#64748B; margin-bottom:4px;'>대표 전표</div>"
        f"<div style='font-family:monospace; font-size:0.82rem; color:#0F172A; "
        f"margin-bottom:10px; word-break:break-all;'>{sample_docs_safe}</div>"
        f"<div style='font-size:0.78rem; color:#64748B; margin-bottom:4px;'>"
        f"이 case 의 행 risk_level 분포</div>"
        f"{row_risk_bar}"
        f"<div style='font-size:0.78rem; color:#64748B; margin:10px 0 4px;'>적중 룰</div>"
        f"<div style='display:flex; gap:6px; flex-wrap:wrap;'>{rule_chip_html}</div>"
        f"</div>"
    )
    panel_c = (
        f"<div style='{quad_box_style}'>"
        f"<div style='{quad_label_style}'>③ Why · 증거·점수</div>"
        f"<div style='display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;'>{chip_html}</div>"
        f"<div style='font-size:0.78rem; color:#64748B; margin-bottom:2px;'>가중치 사유</div>"
        f"<div style='font-size:0.82rem; color:#475569; line-height:1.5;'>{tie_text_safe}</div>"
        f"</div>"
    )
    panel_d = (
        f"<div style='{quad_box_style}'>"
        f"<div style='{quad_label_style}'>④ Action · 검토 포인트</div>"
        f"<div style='font-size:0.78rem; color:#64748B; "
        f"margin-bottom:2px;'>Review Focus</div>"
        f"<ul style='font-size:0.85rem; color:#334155; "
        f"margin:0 0 8px 1.1rem; line-height:1.5;'>{focus_html}</ul>"
        f"<div style='font-size:0.78rem; color:#64748B; "
        f"margin-bottom:2px;'>Recommended Actions</div>"
        f"<ul style='font-size:0.85rem; color:#334155; "
        f"margin:0 0 0 1.1rem; line-height:1.5;'>{actions_html}</ul>"
        f"</div>"
    )

    col_a, col_b = st.columns(2, gap="small")
    col_c, col_d = st.columns(2, gap="small")
    col_a.markdown(panel_a, unsafe_allow_html=True)
    col_b.markdown(panel_b, unsafe_allow_html=True)
    col_c.markdown(panel_c, unsafe_allow_html=True)
    col_d.markdown(panel_d, unsafe_allow_html=True)
    st.divider()


def _render_topic_rule_case_heatmap(
    pr,
    topic_id: str,
    rule_groups: list[dict[str, Any]],
) -> None:
    """안 3 시제품 — Top N case × Topic 룰 히트맵 (통계 이상 탭)."""
    if not rule_groups:
        return
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return

    members = [
        case
        for case in phase1.cases
        if topic_id in _case_topic_ids(case) and _case_topic_score(case, topic_id) > 0
    ]
    members.sort(
        key=lambda case: (
            _case_topic_score(case, topic_id),
            -_priority_band_rank(case.priority_band),
            case.total_amount,
        ),
        reverse=True,
    )
    members = members[:20]
    if not members:
        return

    rule_ids = [group["rule_id"] for group in rule_groups]
    rule_axis = [
        f"{rule_id}<br><span style='font-size:0.68rem;color:#64748B;'>"
        f"{_RULE_NAMES_KR.get(rule_id, '')}</span>"
        for rule_id in rule_ids
    ]

    z_matrix: list[list[float]] = []
    text_matrix: list[list[str]] = []
    case_axis: list[str] = []
    for case in members:
        rule_to_score: dict[str, float] = {}
        for hit in case.raw_rule_hits or []:
            if hit.rule_id in rule_ids:
                rule_to_score[hit.rule_id] = max(
                    rule_to_score.get(hit.rule_id, 0.0),
                    float(hit.signal_strength or 0.0),
                )
        z_row = [rule_to_score.get(rule_id, 0.0) for rule_id in rule_ids]
        text_row = [f"{value:.2f}" if value > 0 else "" for value in z_row]
        z_matrix.append(z_row)
        text_matrix.append(text_row)
        band = str(case.priority_band or "low").upper()[:1]
        key_text = (case.case_key or case.case_id)[:28]
        case_axis.append(f"[{band}] {key_text}")

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=rule_axis,
            y=case_axis,
            text=text_matrix,
            texttemplate="%{text}",
            textfont=dict(size=10, color="#0F172A"),
            colorscale=[
                [0.0, "#F8FAFC"],
                [0.001, "#FEF3C7"],
                [0.5, "#FB923C"],
                [1.0, "#DC2626"],
            ],
            zmin=0.0,
            zmax=1.0,
            hovertemplate=("<b>%{y}</b><br>%{x}<br>signal=%{z:.2f}<extra></extra>"),
            showscale=True,
            colorbar=dict(title="signal", thickness=12, len=0.6),
        )
    )
    fig.update_layout(
        height=max(320, 26 * len(members) + 100),
        margin=dict(l=10, r=10, t=20, b=80),
        xaxis=dict(side="top", tickangle=0, tickfont=dict(size=10)),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
    )
    st.markdown("##### Rule × Case 히트맵 (시제품)")
    st.caption(
        "행=Top 20 케이스(Topic score 정렬), 열=Topic 소속 룰, 셀 색=signal_strength. "
        "한 케이스가 여러 룰을 동시에 위반하는 패턴을 한눈에 확인합니다."
    )
    st.plotly_chart(fig, use_container_width=True, key=f"phase1_heatmap_{topic_id}")
    st.divider()


def _render_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="Topic Top N",
        title="Topic Top N",
        caption="High/Medium 우선순위이며 직접 위험 신호가 있는 case입니다.",
        key_prefix="phase1_priority_risk",
    )


def _render_low_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="Topic 보조 표시",
        title="Topic 보조 표시",
        caption=(
            "직접 위험 신호는 있지만 Low band이거나 timing/control 성격의 넓은 "
            "모집단으로 분류된 case입니다."
        ),
        key_prefix="phase1_low_priority_risk",
    )


def _render_context_review_candidates(pr) -> None:
    _render_category_case_queue(
        pr,
        category="Scenario badge",
        title="Scenario badge",
        caption="직접 위험 신호 없이 review/context/macro 근거만 있는 case입니다.",
        key_prefix="phase1_context_review",
    )


def _render_category_case_queue(
    pr,
    *,
    category: str,
    title: str,
    caption: str,
    key_prefix: str,
) -> None:
    st.markdown(f"### {title}")
    st.caption(caption)

    rows = _category_case_rows(pr, category)
    if not rows:
        st.info(f"{title} case가 없습니다.")
        return

    rule_groups = _category_rule_groups(pr, category)
    grouped_case_total = sum(group["case_count"] for group in rule_groups)
    c1, c2, c3 = st.columns([1, 1, 3])
    c1.metric("고유 Case", f"{len(rows):,}", border=True)
    c2.metric("룰별 Case", f"{grouped_case_total:,}", border=True)
    top_n = c3.slider(
        "룰별 표시 Case 수",
        min_value=10,
        max_value=min(max(len(rows), 10), 200),
        value=min(50, max(len(rows), 10)),
        step=10,
        key=f"{key_prefix}_top_n",
    )
    st.caption(
        "한 case가 여러 룰을 포함하면 각 룰 그룹에 중복 표시됩니다. "
        "상단 고유 Case는 중복 제거 기준입니다."
    )

    if not rule_groups:
        st.info("룰 hit가 연결된 case가 없습니다.")
        return

    for group in rule_groups:
        visible_rows = group["rows"][: int(top_n)]
        header = f"{group['rule_id']} · {group['rule_label']} · case {group['case_count']:,}건"
        with st.expander(header, expanded=False):
            _render_case_table(pd.DataFrame(visible_rows))
            _render_case_selector(
                pr,
                visible_rows,
                key_suffix=f"{key_prefix}_{group['rule_id']}",
            )


def _category_rule_groups(pr, category: str) -> list[dict[str, Any]]:
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    dq_case_ids = _data_quality_case_ids(pr)
    grouped: dict[str, list[Any]] = {}
    for case in phase1.cases:
        if _case_signal_category(case, dq_case_ids) != category:
            continue
        rule_ids = {
            str(getattr(hit, "rule_id", "") or "").strip()
            for hit in getattr(case, "raw_rule_hits", []) or []
        }
        for rule_id in _sort_rule_ids([rule for rule in rule_ids if rule]):
            grouped.setdefault(rule_id, []).append(case)

    groups: list[dict[str, Any]] = []
    for rule_id in _sort_rule_ids(list(grouped.keys())):
        cases = grouped[rule_id]
        # §9.3 composite_sort_score 우선 정렬. priority_score 단독 정렬은 components 토글로만 사용.
        cases.sort(
            key=lambda case: (
                _priority_band_rank(case.priority_band),
                case.composite_sort_score,
                case.priority_score,
                case.triage_rank_score,
                case.total_amount,
                case.rule_count,
                -case.document_count,
            ),
            reverse=True,
        )
        groups.append(
            {
                "rule_id": rule_id,
                "rule_label": _RULE_NAMES_KR.get(rule_id)
                or RULE_CODES.get(rule_id, "Unknown Rule"),
                "case_count": len(cases),
                "rows": [_case_row(case, phase1) for case in cases],
            }
        )
    return groups


def _render_review_candidates(pr) -> None:
    summary = build_phase1_review_candidate_summary(pr)
    if not summary["available"] or not summary["items"]:
        st.info("Review 후보가 없습니다.")
        return

    review_df = pd.DataFrame(summary["items"])
    review_df["Sample cases"] = review_df["sample_case_ids"].map(lambda values: ", ".join(values))
    review_df["Focus"] = review_df["review_focus"].map(lambda values: " / ".join(values))
    review_df["Actions"] = review_df["actions"].map(lambda values: " / ".join(values))
    display_df = review_df.rename(
        columns={
            "queue_label": "Review type",
            "cases": "Cases",
            "documents": "Documents",
            "review_hits": "Review hits",
            "direct_hits": "Direct hits",
            "high_cases": "High",
            "medium_cases": "Medium",
            "low_cases": "Low",
        }
    )
    st.dataframe(
        display_df[
            [
                "Review type",
                "Cases",
                "Documents",
                "Review hits",
                "Direct hits",
                "High",
                "Medium",
                "Low",
                "Focus",
                "Actions",
                "Sample cases",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_all_case_queue(pr, summary: dict) -> None:
    st.markdown("### 전체 Case Drill-down")
    st.caption("전체 PHASE1 case를 queue/theme으로 필터링해서 세부 근거를 확인합니다.")

    queue_options = [("전체", None)] + [
        (queue["queue_label"], queue["queue_id"]) for queue in summary.get("queues", [])
    ]
    selected_queue_label = st.selectbox(
        "Issue Queue",
        options=[label for label, _ in queue_options],
        index=0,
        key="phase1_queue_select",
    )
    selected_queue = next(
        queue_id for label, queue_id in queue_options if label == selected_queue_label
    )

    theme_options = [("전체 Theme", None)] + [
        (theme["theme_label"], theme["theme_id"]) for theme in summary["themes"]
    ]
    selected_theme_label = st.selectbox(
        "Theme 보조 필터",
        options=[label for label, _ in theme_options],
        index=0,
        key="phase1_theme_select",
    )
    selected_theme = next(
        theme_id for label, theme_id in theme_options if label == selected_theme_label
    )
    top_n = st.slider(
        "표시할 Case 수",
        min_value=5,
        max_value=50,
        value=10,
        step=5,
        key="phase1_top_n",
    )

    queue = build_phase1_case_queue(
        pr,
        queue_id=selected_queue,
        theme_id=selected_theme,
        top_n=top_n,
    )
    if not queue:
        st.info("선택한 조건에 해당하는 case가 없습니다.")
        return
    _render_case_table(pd.DataFrame(queue))
    _render_case_selector(pr, queue)


def _render_ai_conclusion(pr, summary: dict) -> None:
    gate = build_phase1_data_quality_gate(pr)
    audit = build_phase1_audit_risk_by_queue(pr, top_n_per_queue=1)
    review = build_phase1_review_candidate_summary(pr)
    high_count = sum(theme["high_count"] for theme in summary["themes"])
    medium_count = sum(theme["medium_count"] for theme in summary["themes"])

    st.markdown("#### 요약 판단")
    st.write(
        f"PHASE1은 총 {summary['case_count']:,}개 case를 생성했고, "
        f"High {high_count:,}개, Medium {medium_count:,}개를 우선 검토 대상으로 분류했습니다."
    )
    st.write(
        f"데이터정합성 Gate에는 {gate.get('document_count', 0):,}개 document가 걸렸습니다. "
        "이 항목은 감사위험 Top과 섞지 말고 먼저 데이터/계약 오류로 처리해야 합니다."
    )
    st.write(
        f"PHASE1 topic은 {len(audit.get('queues', [])):,}개 topic으로 나누어 표시됩니다. "
        "동점 case는 Queue Tie 점수와 Tie Reason으로 같은 queue 안에서 다시 정렬합니다."
    )
    st.write(
        f"Scenario detail은 {len(review.get('items', [])):,}개 유형으로 집계됩니다. "
        "확정 위험이 아니라 정책 판단, 샘플 검토, 보조 근거 확인 대상입니다."
    )

    queue_rows = []
    for queue in audit.get("queues", []):
        if not queue["items"]:
            continue
        top = queue["items"][0]
        queue_rows.append(
            {
                "Queue": queue["queue_label"],
                "대표 case": top["case_id"],
                "Queue Tie": top["queue_tiebreaker_score"],
                "Docs": top["document_count"],
                "Tie Reason": " / ".join(top["queue_tiebreaker_reasons"][:4]),
            }
        )
    if queue_rows:
        st.markdown("#### Queue별 대표 우선 검토 case")
        st.dataframe(pd.DataFrame(queue_rows), use_container_width=True, hide_index=True)

    st.divider()
    if st.button(
        "Phase 2 탭으로 이동",
        type="primary",
        key="ai_conclusion_goto_phase2",
    ):
        st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
        st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_PHASE2
        st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE2
        st.rerun()


def _render_case_table(queue_df: pd.DataFrame) -> None:
    display_df = queue_df.rename(
        columns={
            "topic_label": "Topic",
            "topic_score": "Topic Score",
            "primary_topic_label": "Primary Topic",
            "case_type": "Case Type",
            "main_reason": "Main Reason",
            "case_key": "Case Key",
            "priority_band": "Band",
            "priority_score": "Score",
            "composite_sort_score": "Sort",
            "triage_rank_score": "Triage",
            "queue_tiebreaker_score": "Queue Tie",
            "queue_tiebreaker_reasons": "Tie Reason",
            "document_count": "Docs",
            "row_count": "Rows",
            "direct_risk_count": "Direct",
            "review_context_count": "Review",
            "integrity_blocker_count": "Blocker",
            "macro_finding_count": "Macro",
            "total_amount": "Amount",
            "repeat_months": "Repeat Months",
            "risk_narrative": "Narrative",
        }
    )
    if "Tie Reason" in display_df.columns:
        display_df["Tie Reason"] = display_df["Tie Reason"].map(
            lambda values: " / ".join(values[:4]) if isinstance(values, list) else values
        )
    columns = [
        "Topic",
        "Topic Score",
        "Primary Topic",
        "Band",
        "Case Type",
        "Main Reason",
        "Sort",
        "Score",
        "Triage",
        "Queue Tie",
        "Tie Reason",
        "Docs",
        "Rows",
        "Direct",
        "Review",
        "Blocker",
        "Macro",
        "Amount",
        "Repeat Months",
        "Case Key",
        "Narrative",
    ]
    available = [column for column in columns if column in display_df.columns]
    st.dataframe(display_df[available], use_container_width=True, hide_index=True)


def _render_case_selector(
    pr,
    queue: list[dict],
    *,
    key_suffix: str | None = None,
) -> None:
    if not queue:
        return
    case_options = {
        (
            f"{row.get('topic_label') or row.get('primary_topic_label')} | "
            f"{row['priority_band']} | {row['case_key']}"
        ): row["case_id"]
        for row in queue
    }
    key_base = key_suffix or str(abs(hash(tuple(case_options.values()))))
    selected_case_label = st.selectbox(
        "Drill-down Case",
        options=list(case_options.keys()),
        key=f"phase1_case_select_{key_base}",
    )
    selected_case_id = case_options[selected_case_label]
    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is not None:
        _render_case_drilldown(drilldown)


def _render_case_drilldown(drilldown: dict) -> None:
    case = drilldown["case"]
    narrative = case["risk_narrative"] or case["representative_explanation"]
    st.markdown(f"**Case 설명**  \n{narrative}")

    meta1, meta2, meta3, meta4 = st.columns(4)
    meta1.metric("Topic Score", f"{case.get('topic_score', case['priority_score']):.2f}")
    meta2.metric("Priority", f"{case['priority_score']:.2f}")
    meta3.metric("Documents", f"{case['document_count']:,}")
    meta4.metric("Amount", f"{case['total_amount']:,.0f}")

    sig1, sig2, sig3, sig4 = st.columns(4)
    sig1.metric("Direct risk", f"{case['direct_risk_count']:,}")
    sig2.metric("Review context", f"{case['review_context_count']:,}")
    sig3.metric("Data blocker", f"{case['integrity_blocker_count']:,}")
    sig4.metric("Macro finding", f"{case['macro_finding_count']:,}")

    topic_caption = "Topic: " + str(
        case.get("topic_label") or case.get("primary_topic_label") or ""
    )
    if case.get("secondary_queue_labels"):
        topic_caption += " / " + ", ".join(case["secondary_queue_labels"])
    st.caption(topic_caption)
    if case.get("fraud_scenario_tags"):
        st.caption("Fraud scenario tags: " + ", ".join(case["fraud_scenario_tags"]))
    tie_reasons = case.get("queue_tiebreaker_reasons") or []
    if tie_reasons:
        st.caption("Tie-breaker: " + " / ".join(tie_reasons[:5]))
    if case["triage_rank_reasons"]:
        st.caption("Triage: " + ", ".join(case["triage_rank_reasons"][:6]))
    if case["review_focus"]:
        st.caption("Review Focus: " + ", ".join(case["review_focus"]))
    if case["recommended_audit_actions"]:
        st.caption("Recommended Actions: " + " / ".join(case["recommended_audit_actions"][:4]))

    documents_df = pd.DataFrame(drilldown["documents"])
    if not documents_df.empty:
        st.caption("Document drill-down")
        st.dataframe(documents_df, use_container_width=True, hide_index=True)

    _render_signal_sections(drilldown)


def _render_signal_sections(drilldown: dict) -> None:
    sections = drilldown.get("signal_sections", {})
    labels = [
        ("direct_risk", "Direct risk signals"),
        ("review_context", "Review/context signals"),
        ("integrity_blocker", "Data quality blockers"),
        ("macro_finding", "Macro findings"),
    ]
    display_columns = [
        "rule_id",
        "display_label",
        "score",
        "normalized_score",
        "evidence_strength",
        "scoring_role",
        "signal_status",
        "document_id",
        "detail",
    ]
    for key, label in labels:
        rows = sections.get(key, [])
        if not rows:
            continue
        with st.expander(f"{label} ({len(rows):,})", expanded=(key == "direct_risk")):
            section_df = pd.DataFrame(rows)
            available = [column for column in display_columns if column in section_df.columns]
            st.dataframe(section_df[available], use_container_width=True, hide_index=True)

    with st.expander("All raw rule hits", expanded=False):
        raw_df = pd.DataFrame(drilldown["raw_rule_hits"])
        st.dataframe(raw_df, use_container_width=True, hide_index=True)


def _feature_frame(pr) -> pd.DataFrame:
    featured = getattr(pr, "featured_data", None)
    if featured is not None:
        return featured
    return getattr(pr, "data", pd.DataFrame())


def _risk_distribution(pr, data: pd.DataFrame) -> pd.DataFrame:
    levels = ["High", "Medium", "Low", "Normal"]
    if getattr(pr, "risk_summary", None):
        counts = {str(key): int(value) for key, value in pr.risk_summary.items()}
    elif "risk_level" in data.columns:
        counts = data["risk_level"].fillna("Normal").astype(str).value_counts().to_dict()
    else:
        counts = {}
    total = sum(int(counts.get(level, 0)) for level in levels) or len(data) or 1
    return pd.DataFrame(
        {
            "risk_level": levels,
            "count": [int(counts.get(level, 0)) for level in levels],
            "ratio": [f"{int(counts.get(level, 0)) / total:.1%}" for level in levels],
        }
    )


def _direct_risk_case_count(pr) -> int:
    return int(_signal_category_counts(pr).get("Topic Top N", 0) or 0)


def _category_case_rows(pr, category: str) -> list[dict[str, Any]]:
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    dq_case_ids = _data_quality_case_ids(pr)
    cases = [case for case in phase1.cases if _case_signal_category(case, dq_case_ids) == category]
    # §9.3 composite_sort_score 우선 정렬. priority_score 는 보조 tiebreak.
    cases.sort(
        key=lambda case: (
            _priority_band_rank(case.priority_band),
            case.composite_sort_score,
            case.priority_score,
            case.triage_rank_score,
            case.total_amount,
            case.rule_count,
            -case.document_count,
        ),
        reverse=True,
    )
    return [_case_row(case, phase1) for case in cases]


def _signal_category_counts(pr) -> dict[str, int]:
    """위험신호를 배타적인 고유 case 수로 분해한다.

    Queue별 total_cases를 단순 합산하면 secondary queue 때문에 같은 case가 여러 번
    더해진다. 이 차트는 화면 요약용이므로 case를 한 번만 세고, 다음 우선순위로
    하나의 카테고리에만 배정한다.
    """
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return {
            "데이터정합성": 0,
            "Topic Top N": 0,
            "Topic 보조 표시": 0,
            "Scenario badge": 0,
        }

    counts = {
        "데이터정합성": 0,
        "Topic Top N": 0,
        "Topic 보조 표시": 0,
        "Scenario badge": 0,
    }
    dq_case_ids = _data_quality_case_ids(pr)
    for case in phase1.cases:
        counts[_case_signal_category(case, dq_case_ids)] += 1
    return counts


def _data_quality_case_ids(pr) -> set[str]:
    gate = build_phase1_data_quality_gate(pr)
    return {
        str(row.get("case_id"))
        for row in gate.get("cases", [])
        if isinstance(row, dict) and row.get("case_id")
    }


def _case_signal_category(case: Any, dq_case_ids: set[str]) -> str:
    signal_counts = _case_signal_counts(case)
    if (
        case.case_id in dq_case_ids
        or case.primary_queue == "data_integrity"
        or case.primary_theme == "data_integrity_failure"
        or float(getattr(case, "data_integrity_score", 0.0) or 0.0) > 0
    ):
        return "데이터정합성"

    has_review_signal = signal_counts["review_context"] > 0 or signal_counts["macro_finding"] > 0
    has_direct_risk = signal_counts["direct_risk"] > 0
    if not has_direct_risk:
        return "Scenario badge"

    if _is_broad_audit_population(case, signal_counts, has_review_signal):
        return "Topic 보조 표시"

    return "Topic Top N"


def _is_broad_audit_population(
    case: Any,
    signal_counts: dict[str, int],
    has_review_signal: bool,
) -> bool:
    """Return whether a direct-risk case is a broad population rather than priority risk."""

    if case.priority_band == "low":
        return True
    if case.primary_queue not in {"timing_close", "control_approval"}:
        return False
    context_count = signal_counts["review_context"] + signal_counts["macro_finding"]
    return has_review_signal and context_count >= signal_counts["direct_risk"]


def _priority_band_rank(band: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(band).lower(), 0)


def _render_risk_pie(risk_df: pd.DataFrame, topics: list[dict[str, Any]]) -> None:
    """좌우 독립 컬럼 — shadcn zinc 팔레트, flat 미니멀.

    좌: Normal vs 위험신호 도넛 (zinc-200 vs zinc-900 고대비)
    우: 7대 Audit Topic 분포 (상단 탭 7개와 1:1 매칭, Top1만 강조)
    Why: 우측을 카테고리 4분류(우선/보조/Scenario/정합성)에서 Topic 7분류로 전환해
         상단 7개 탭과 동일 축으로 연결, 1위 Topic만 다크 오렌지로 강조해 집중도 확보.
    """
    counts = {
        str(level): int(value) for level, value in zip(risk_df["risk_level"], risk_df["count"])
    }
    high = counts.get("High", 0)
    medium = counts.get("Medium", 0)
    low = counts.get("Low", 0)
    normal = counts.get("Normal", 0)
    review_total = high + medium + low
    grand_total = review_total + normal

    if grand_total == 0:
        st.info("표시할 위험도 데이터가 없습니다.")
        return

    review_pct = review_total / grand_total * 100

    # shadcn 팔레트
    color_normal = "#E4E4E7"  # zinc-200
    color_review = "#18181B"  # zinc-900
    color_text = "#18181B"  # zinc-900
    color_muted = "#71717A"  # zinc-500
    color_accent = "#C2410C"  # orange-700 (Top1 강조)
    color_neutral = "#475569"  # slate-600 (나머지 차분)
    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    # Why: 7개 막대가 들어가도록 카드 높이를 늘리고, 두 차트는 동일 높이로 정렬.
    chart_card_height = 360
    left_col, right_col = st.columns(2, gap="small")

    # ── 좌측: 전체 분포 도넛 ────────────────────────────────
    with left_col, st.container(border=True, height=chart_card_height):
        st.markdown(
            f"<div style='font-family:{typography};'>"
            f"<div style='color:{color_text}; font-size:0.875rem; "
            f"font-weight:600;'>전체 분포</div>"
            f"<div style='color:{color_muted}; font-size:0.75rem; "
            f"margin-top:2px;'>총 {grand_total:,}건 · 위험신호 "
            f"{review_pct:.1f}%</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        fig_donut = go.Figure(
            go.Pie(
                labels=["Normal", "위험신호"],
                values=[normal, review_total],
                hole=0.68,
                sort=False,
                direction="clockwise",
                rotation=90,
                marker={
                    "colors": [color_normal, color_review],
                    "line": {"color": "#FFFFFF", "width": 0},
                },
                textinfo="label+percent",
                textposition="outside",
                textfont={"size": 12, "color": color_text, "family": typography},
                hovertemplate="%{label}: %{value:,}건 (%{percent})<extra></extra>",
                showlegend=False,
            )
        )
        fig_donut.add_annotation(
            text=(
                f"<span style='font-size:1.25rem; font-weight:700; "
                f"color:{color_text};'>{review_pct:.1f}%</span>"
                f"<br><span style='font-size:0.7rem; color:{color_muted};'>"
                f"위험신호</span>"
            ),
            x=0.5,
            y=0.5,
            showarrow=False,
            align="center",
        )
        fig_donut.update_layout(
            height=260,
            margin={"l": 6, "r": 6, "t": 4, "b": 4},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"family": typography},
        )
        st.plotly_chart(
            fig_donut,
            use_container_width=True,
            config={"displayModeBar": False},
            key="phase1_risk_donut",
        )

    # ── 우측: 7대 Audit Topic 분포 ─────────────────────────
    # Why: 상단 탭 7개와 동일 축. case_count 내림차순 정렬 → 1위 Topic만
    #      다크 오렌지로 강조하고 나머지는 slate-600 으로 차분히 처리.
    with right_col, st.container(border=True, height=chart_card_height):
        topic_rows: list[dict[str, Any]] = []
        for topic_id, topic in TOPIC_REGISTRY.items():
            short_label = _TOPIC_SHORT_LABELS.get(topic_id, topic.label)
            match = next((t for t in topics if t.get("topic_id") == topic_id), None)
            if match is None:
                topic_rows.append(
                    {
                        "topic_id": topic_id,
                        "topic_label": short_label,
                        "case_count": 0,
                        "high_count": 0,
                    }
                )
                continue
            topic_rows.append(
                {
                    "topic_id": topic_id,
                    "topic_label": short_label,
                    "case_count": int(match.get("case_count", 0) or 0),
                    "high_count": int(match.get("high_count", 0) or 0),
                }
            )

        # case_count desc → high_count desc 보조정렬. 같은 0건이면 등록 순서 유지.
        topic_rows.sort(
            key=lambda row: (row["case_count"], row["high_count"]),
            reverse=True,
        )

        bar_labels = [row["topic_label"] for row in topic_rows]
        bar_values = [row["case_count"] for row in topic_rows]
        bar_total = sum(bar_values)
        bar_pcts = [v / bar_total * 100 if bar_total else 0.0 for v in bar_values]
        # Top1만 강조. 모든 case가 0이면 강조 없음(전부 차분 색).
        max_value = max(bar_values) if bar_values else 0
        bar_colors = [
            color_accent if max_value > 0 and v == max_value else color_neutral for v in bar_values
        ]
        # Top1은 단 1개만 강조 — 동률이어도 정렬 후 첫 번째만.
        first_top_seen = False
        for idx, color in enumerate(bar_colors):
            if color == color_accent:
                if first_top_seen:
                    bar_colors[idx] = color_neutral
                else:
                    first_top_seen = True

        bar_text = [f"  {v:,} 건  ·  {p:.1f}%" for v, p in zip(bar_values, bar_pcts)]

        st.markdown(
            f"<div style='font-family:{typography};'>"
            f"<div style='color:{color_text}; font-size:0.875rem; "
            f"font-weight:600;'>7대 Audit Topic 분포</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        fig_bar = go.Figure(
            go.Bar(
                y=bar_labels,
                x=bar_values,
                orientation="h",
                marker={"color": bar_colors, "line": {"width": 0}},
                text=bar_text,
                textposition="outside",
                textfont={"size": 11, "color": color_muted, "family": typography},
                cliponaxis=False,
                customdata=[[row["high_count"]] for row in topic_rows],
                hovertemplate=("%{y}<br>case %{x:,}건 · High %{customdata[0]:,}건<extra></extra>"),
                showlegend=False,
            )
        )
        fig_bar.update_layout(
            height=270,
            margin={"l": 6, "r": 120, "t": 4, "b": 4},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            bargap=0.62,
            font={"family": typography},
        )
        fig_bar.update_xaxes(visible=False)
        fig_bar.update_yaxes(
            autorange="reversed",
            tickfont={"size": 12, "color": color_text, "family": typography},
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            automargin=True,
        )
        st.plotly_chart(
            fig_bar,
            use_container_width=True,
            config={"displayModeBar": False},
            key="phase1_topic_bar",
        )


def _mapping_coverage(pr, data: pd.DataFrame) -> str:
    load_result = getattr(pr, "load_result", None)
    mapped = getattr(load_result, "mapped_columns", None) or getattr(pr, "mapped_columns", None)
    if isinstance(mapped, dict) and data is not None and len(data.columns) > 0:
        return f"{len(mapped) / len(data.columns):.1%}"
    required = {"document_id", "posting_date", "gl_account", "debit_amount", "credit_amount"}
    if data is not None and len(data.columns) > 0:
        coverage = len(required & set(data.columns)) / len(required)
        return f"{coverage:.1%}"
    return "-"


def _label_leak_status(data: pd.DataFrame) -> tuple[str, str]:
    leak_columns = {"is_fraud", "fraud_type", "is_anomaly", "anomaly_type"}
    present = sorted(leak_columns & set(data.columns))
    if present:
        return "발견", f"제거 필요: {', '.join(present)}"
    return "없음", "운영 실행 적합"


_LAYER_D_RULES = {"D01", "D02"}


def _phase1_rule_audit(pr) -> dict[str, Any]:
    """전체 33개 룰을 한 리스트로 반환 — 룰별 status/count 부여."""
    target = list(_PHASE1_RULE_IDS)
    case_counts = _phase1_rule_case_counts(pr)
    case_counts_available = resolve_phase1_case_result(pr) is not None
    generated_counts = {} if case_counts_available else _generated_rule_counts(pr)
    skipped = set(_skipped_rule_ids(pr))

    rules: list[dict[str, Any]] = []
    for rule_id in target:
        if rule_id in case_counts and case_counts[rule_id] > 0:
            status = "generated"
            count = case_counts[rule_id]
        elif rule_id in generated_counts:
            status = "generated"
            count = generated_counts[rule_id]
        elif rule_id in skipped:
            status = "skipped"
            count = 0
        else:
            status = "no_match"
            count = 0
        rules.append(
            {
                "rule_id": rule_id,
                "name_kr": _RULE_NAMES_KR.get(rule_id) or RULE_CODES.get(rule_id, "Unknown Rule"),
                "status": status,
                "flag_count": int(count),
            }
        )
    return {
        "target_count": len(target),
        "generated_count": sum(1 for r in rules if r["status"] == "generated"),
        "skipped_count": sum(1 for r in rules if r["status"] == "skipped"),
        "no_match_count": sum(1 for r in rules if r["status"] == "no_match"),
        "rules": rules,
    }


def _phase1_rule_case_counts(pr) -> dict[str, int]:
    """Rule count source for PHASE1 pills: risk cases, not raw review population."""
    return build_phase1_rule_document_counts(pr)


def _generated_rule_counts(pr) -> dict[str, int]:
    """룰별 RuleFlag 생성 건수."""
    results = getattr(pr, "results", None)
    if not results:
        return {}
    counts: dict[str, int] = {}
    for result in results:
        for rule_flag in getattr(result, "rule_flags", []) or []:
            rule_id = str(getattr(rule_flag, "rule_id", "") or "").strip()
            flagged_count = int(getattr(rule_flag, "flagged_count", 0) or 0)
            if rule_id and flagged_count > 0:
                counts[rule_id] = counts.get(rule_id, 0) + flagged_count
    return counts


def _generated_rule_ids(pr) -> list[str]:
    return _sort_rule_ids(_generated_rule_counts(pr).keys())


def _skipped_rule_ids(pr) -> list[str]:
    results = getattr(pr, "results", None)
    skipped: set[str] = set()
    for result in results or []:
        metadata = getattr(result, "metadata", {}) or {}
        for rule_id in metadata.get("skipped_rules", []) or []:
            rule_text = str(rule_id or "").strip()
            if rule_text:
                skipped.add(rule_text)
    for status in getattr(pr, "detector_statuses", []) or []:
        if (
            str(status.get("track_name", "")).strip() == "layer_d"
            and str(status.get("run_status", "")).strip() == "skipped"
        ):
            skipped.update({"D01", "D02"})
    return _sort_rule_ids(skipped)


_RULE_NAMES_KR: dict[str, str] = {
    "L1-01": "차대변 불일치",
    "L1-02": "필수 필드 누락",
    "L1-03": "무효 계정 사용",
    "L1-04": "승인 한도 초과",
    "L1-05": "자기 승인",
    "L1-06": "직무 분리(SoD) 위반",
    "L1-07": "승인 절차 누락",
    "L1-08": "회계기간 오류",
    "L1-09": "승인일 누락",
    "L2-01": "승인 한도 직전 분개",
    "L2-02": "중복 지급",
    "L2-03": "중복 분개",
    "L2-04": "비용 자산화 의심",
    "L2-05": "역분개 패턴",
    "L3-01": "계정 분류 오류",
    "L3-02": "수기 분개 우회",
    "L3-03": "특수관계자 거래 검토",
    "L3-04": "기초·기말 결산 검토",
    "L3-05": "주말 기표",
    "L3-06": "심야 기표",
    "L3-07": "기표일·증빙일 간격",
    "L3-08": "적요 누락·훼손",
    "L3-09": "미결 계정 장기화",
    "L3-10": "고위험 계정 사용",
    "L3-12": "업무범위 초과 검토",
    "L4-01": "매출 이상치",
    "L4-02": "벤포드 위반",
    "L4-03": "고액 이상치",
    "L4-04": "희귀 차·대 계정쌍",
    "L4-05": "이상 시간대 군집",
    "L4-06": "일괄 기표 이상",
    "D01": "계정 활동 변동",
    "D02": "비율 분포 변동",
}


def _rule_row(rule_id: str) -> dict[str, str]:
    title = _RULE_NAMES_KR.get(rule_id) or RULE_CODES.get(rule_id, "Unknown Rule")
    return {
        "룰": f"{rule_id} · {title}",
    }


def _sort_rule_ids(rule_ids: set[str] | list[str]) -> list[str]:
    order = {rule_id: idx for idx, rule_id in enumerate(_PHASE1_RULE_IDS)}
    return sorted(rule_ids, key=lambda rule_id: (order.get(rule_id, 999), rule_id))


def _phase1_case_rule_count(pr) -> int | None:
    phase1 = getattr(pr, "phase1_case_result", None)
    if phase1 is None:
        return None
    rule_ids: set[str] = set()
    for case in getattr(phase1, "cases", []) or []:
        for hit in getattr(case, "raw_rule_hits", []) or []:
            rule_id = str(getattr(hit, "rule_id", "") or "").strip()
            if rule_id:
                rule_ids.add(rule_id)
    return len(rule_ids)


def _format_risk_amount(value: float) -> str:
    """Phase1 case 총액 한국식 축약 — 조/억/만 단위."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    if v <= 0:
        return "0 원"
    abs_v = abs(v)
    if abs_v >= 1_0000_0000_0000:
        return f"{v / 1_0000_0000_0000:,.2f} 조"
    if abs_v >= 1_0000_0000:
        return f"{v / 1_0000_0000:,.2f} 억"
    if abs_v >= 1_0000:
        return f"{v / 1_0000:,.1f} 만"
    return f"{v:,.0f} 원"


def _available_rules(data: pd.DataFrame, *, pr=None) -> list[str]:
    truth = _phase1_truth_index(pr)
    if truth.get("available"):
        return list(truth.get("rules") or [])
    if data.empty:
        return []
    tokens: set[str] = set()
    for column in ("flagged_rules", "review_rules"):
        if column not in data.columns:
            continue
        sample = data[column].dropna().astype(str)
        for value in sample:
            tokens.update(_rule_tokens(value))
    return sorted(tokens)


def _review_case_document_ids(pr) -> set[str]:
    """추가검토 후보 case에 속한 document_id 집합 반환.

    Why: 추가검토 후보는 대부분 case-builder 단계에서 분류되므로 row-level review_rules
    컬럼이 비어 있을 수 있다. case의 documents에서 직접 ID를 모아야 grid 필터가 동작.
    """
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return set()
    document_ids: set[str] = set()
    for case in phase1.cases:
        signal_counts = _case_signal_counts(case)
        is_review = (
            signal_counts.get("review_context", 0) > 0
            or signal_counts.get("macro_finding", 0) > 0
            or case.primary_queue == "low_signal_candidate"
            or str(case.priority_band).lower() == "low"
        )
        if not is_review or case.primary_queue == "data_integrity":
            continue
        for doc in case.documents:
            doc_id = getattr(doc, "document_id", None)
            if doc_id:
                document_ids.add(str(doc_id))
    return document_ids


def _filter_master_data(
    data: pd.DataFrame,
    *,
    pr=None,
    rule_only: bool,
    selected_rules: list[str],
    data_quality_only: bool,
    audit_risk_only: bool,
    review_only: bool,
    review_document_ids: set[str] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=data.index)
    rule_text = _combined_rule_text(data)
    truth = _phase1_truth_index(pr)

    if rule_only:
        if truth.get("available"):
            selected = set(selected_rules or truth.get("rules") or [])
            mask &= _raw_truth_row_mask(data, truth, selected)
        elif selected_rules:
            selected = set(selected_rules)
            mask &= rule_text.map(lambda value: bool(_rule_tokens(value) & selected))
        else:
            mask &= rule_text.str.strip().ne("")
    if data_quality_only:
        if truth.get("available"):
            mask &= _raw_truth_row_mask(data, truth, _DATA_QUALITY_RULES)
        else:
            mask &= rule_text.map(lambda value: bool(_rule_tokens(value) & _DATA_QUALITY_RULES))
    if audit_risk_only:
        if "risk_level" in data.columns:
            mask &= data["risk_level"].astype(str).isin(["High", "Medium", "Low"])
        else:
            mask &= pd.Series(False, index=data.index)
    if review_only:
        # Why: review_rules 컬럼은 detector가 row 단위로 review-only flag를 남긴 경우만 채워진다.
        #      대부분 review case는 case-builder 단계에서 분류되므로 row-level 컬럼이 비어
        #      "0건" 표시 문제가 발생. → case 단위 review document_id 집합도 함께 매칭.
        review_mask = pd.Series(False, index=data.index)
        if "review_rules" in data.columns:
            review_mask |= data["review_rules"].fillna("").astype(str).str.strip().ne("")
        if review_document_ids and "document_id" in data.columns:
            review_mask |= data["document_id"].astype(str).isin(review_document_ids)
        mask &= review_mask
    return data.loc[mask].copy()


def _phase1_truth_index(pr) -> dict[str, Any]:
    if pr is None:
        return {"available": False}
    return build_phase1_raw_rule_truth_index(pr)


def _raw_truth_row_mask(
    data: pd.DataFrame,
    truth: dict[str, Any],
    selected_rules: set[str],
) -> pd.Series:
    if not selected_rules:
        return pd.Series(False, index=data.index)
    row_indices: set[int] = set()
    document_ids: set[str] = set()
    rule_row_indices = truth.get("rule_row_indices") or {}
    rule_document_ids = truth.get("rule_document_ids") or {}
    for rule_id in selected_rules:
        row_indices.update(int(idx) for idx in rule_row_indices.get(rule_id, set()))
        document_ids.update(str(doc_id) for doc_id in rule_document_ids.get(rule_id, set()))
    mask = pd.Series(False, index=data.index)
    valid_positions = [idx for idx in row_indices if 0 <= idx < len(data)]
    if valid_positions:
        mask.iloc[valid_positions] = True
    if document_ids and not valid_positions and "document_id" in data.columns:
        mask |= data["document_id"].astype(str).isin(document_ids)
    return mask


def _combined_rule_text(data: pd.DataFrame) -> pd.Series:
    result = pd.Series("", index=data.index, dtype="object")
    for column in ("flagged_rules", "review_rules"):
        if column in data.columns:
            result = result + "," + data[column].fillna("").astype(str)
    return result


def _rule_tokens(value: Any) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[,|;]", str(value or ""))
        if token.strip() and token.strip().lower() != "nan"
    }


def _start_phase1_analysis() -> None:
    """Run Phase 1 from the empty-result placeholder.

    Why: 분석 트리거 시점에 탭 widget state(KEY_TOP_LEVEL_NAV)를 phase1로
         고정해야 rerun 도중 st.tabs default 가 개요로 리셋되며 튕기는 현상을 막는다.
    """
    from dashboard.components.analysis_runner import run_phase_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
    st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_PHASE1

    with st.spinner("Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다."):
        try:
            run_phase_analysis(phase="phase1")
        except Exception as e:
            st.error(f"Phase 1 실행 실패: {e}")
            return
    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
    st.session_state[KEY_TOP_LEVEL_NAV] = PAGE_PHASE1
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
    st.rerun()
