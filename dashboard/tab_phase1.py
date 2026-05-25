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
    PAGE_PHASE1,
    PAGE_PHASE2,
)
from dashboard.phase1_display import (
    CASE_IMMEDIATE_REVIEW_RATIO as _CASE_IMMEDIATE_REVIEW_RATIO,
)
from dashboard.phase1_display import (
    display_priority_band_from_score as _display_priority_band_from_score,
)
from dashboard.phase1_display import (
    format_band_cell as _format_band_cell,
)
from dashboard.phase1_display import (
    format_row_risk_cell as _format_row_risk_cell,  # noqa: F401 - legacy test/API hook
)
from src.detection.constants import RULE_CODES
from src.detection.phase1_rule_catalog import (
    PHASE1_RULE_IDS as _PHASE1_RULE_IDS,
)
from src.detection.phase1_rule_catalog import (
    TOPIC_RULE_WHITELIST as _TOPIC_RULE_WHITELIST,
)
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
from src.formatting import format_krw_compact

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


def _render_phase1_case_unavailable_diagnostics(phase1_result) -> None:
    """summary['available']==False 일 때 어디서 막혔는지 한 화면에 노출.

    Why: ``PHASE1 case 결과를 불러오지 못했습니다`` 만으로는 in-memory case 손실,
    artifact 경로 미존재, build 예외 중 어느 사유인지 알 수 없다. phase1_result 의
    case 관련 필드와 warnings 를 그 자리에서 보여 root cause 추적을 즉시 가능하게 한다.
    """
    from pathlib import Path

    if phase1_result is None:
        st.caption("세션에 Phase 1 결과 객체가 없습니다.")
        return

    case_result = getattr(phase1_result, "phase1_case_result", None)
    cases = getattr(case_result, "cases", None) if case_result is not None else None
    artifact_path = getattr(phase1_result, "phase1_case_path", None)
    run_id = getattr(phase1_result, "phase1_case_run_id", None)
    case_count = int(getattr(phase1_result, "phase1_case_count", 0) or 0)
    detector_count = len(getattr(phase1_result, "results", None) or [])

    artifact_status: str
    if artifact_path is None:
        artifact_status = "없음"
    else:
        try:
            artifact_status = "존재" if Path(str(artifact_path)).exists() else "경로있음·파일없음"
        except Exception:
            artifact_status = "경로있음·확인실패"

    # Why: artifact 가 존재한다고 표시되더라도 resolve 가 None 반환하는 경우의 근원을
    #      잡으려면 load 를 직접 시도해 예외 메시지 또는 cases 길이를 보여줘야 한다.
    load_status = "-"
    load_cases_len = "-"
    if artifact_path and Path(str(artifact_path)).exists():
        try:
            from src.detection.phase1_case_builder import load_phase1_case_result

            loaded_obj = load_phase1_case_result(str(artifact_path))
            loaded_cases = getattr(loaded_obj, "cases", None)
            load_status = "성공"
            load_cases_len = str(len(loaded_cases)) if loaded_cases is not None else "None"
        except Exception as exc:
            load_status = f"실패: {type(exc).__name__}: {exc}"

    # Why: phase1 슬롯이 phase2 추론 결과로 덮였는지 확인 — 핵심 root cause 단서.
    from dashboard._state import KEY_LOADED_FROM_DB, KEY_PHASE2_RESULT

    phase2_result = st.session_state.get(KEY_PHASE2_RESULT)
    same_as_phase2 = phase2_result is phase1_result
    loaded_from_db = bool(st.session_state.get(KEY_LOADED_FROM_DB, False))
    detection_results = list(getattr(phase1_result, "results", None) or [])
    track_names = [str(getattr(r, "track_name", "") or "?") for r in detection_results]

    rows = [
        ("결과 객체", type(phase1_result).__name__),
        ("KEY_PHASE2_RESULT 와 동일 객체", "예 (덮어쓰기 의심)" if same_as_phase2 else "아니오"),
        ("KEY_LOADED_FROM_DB", "True" if loaded_from_db else "False"),
        ("in-memory case_result", "있음" if case_result is not None else "None"),
        ("cases 길이", str(len(cases)) if cases is not None else "None"),
        ("phase1_case_count(meta)", str(case_count)),
        ("phase1_case_path", str(artifact_path) if artifact_path else "None"),
        ("artifact 파일", artifact_status),
        ("artifact load 시도", load_status),
        ("artifact load cases 길이", load_cases_len),
        ("phase1_case_run_id", str(run_id) if run_id else "None"),
        ("detection_results 트랙 수", str(detector_count)),
        ("detection_results 트랙 이름", ", ".join(track_names) if track_names else "(없음)"),
    ]
    st.caption("진단 정보")
    st.dataframe(
        pd.DataFrame(rows, columns=["항목", "값"]),
        width="stretch",
        hide_index=True,
    )

    case_warnings = [
        warn
        for warn in (getattr(phase1_result, "warnings", None) or [])
        if "PHASE1 case" in warn or "phase1_case" in warn
    ]
    if case_warnings:
        st.caption("PHASE1 case 관련 warnings")
        for warn in case_warnings:
            st.code(warn, language="text")


def render(prep_result, phase1_result) -> None:
    st.subheader("PHASE1 결과")

    if phase1_result is None:
        st.info("아직 Phase 1 분석 결과가 없습니다.")
        if prep_result is None:
            return
        # Why: spinner 는 _start_phase1_analysis 내부에 한 번만 띄운다.
        #      호출부에서 또 감싸면 동일 메시지가 두 줄로 표시된다.
        if st.button("Phase 1 분석 시작", type="primary", key="run_phase1"):
            _start_phase1_analysis()
        return

    summary = summarize_phase1_case_result(phase1_result)
    if summary.get("available"):
        # Why: PHASE1 위반은 수만 건이라 7-Topic + AI 결론을 펼쳐 두면 감사인이
        #      "어디부터 봐야 할지" 잃는다. 4-tab으로 압축:
        #        전체 요약 → 한눈 인사이트
        #        데이터 정합성 → L1-01/02/03/08 데이터 결함(이미 case skip)
        #        검토 케이스 → Top 50/100/200 우선순위 큐(핵심 메시지 포함)
        #        통계결과 → 7-Topic 분포/드릴다운 통합
        #      전기 비교는 최상위 탭(Phase2 결과 우측)으로 분리되었다.
        section_tabs = st.tabs(["전체 요약", "데이터 정합성", "검토 케이스", "통계결과"])
        with section_tabs[0]:
            _render_overview(phase1_result, summary)
        with section_tabs[1]:
            _render_data_quality_gate(phase1_result)
        with section_tabs[2]:
            _render_violation_cases_tab(phase1_result, summary)
        with section_tabs[3]:
            _render_statistics_tab(phase1_result, summary)
        return
    if not summary["available"]:
        st.warning("PHASE1 case 결과를 불러오지 못했습니다.")
        _render_phase1_case_unavailable_diagnostics(phase1_result)
        if prep_result is None:
            st.caption(
                "준비 데이터가 없어 재진행할 수 없습니다. 먼저 데이터 업로드/매핑을 완료하세요."
            )
        elif st.button(
            "Phase 1 분석 재진행",
            type="primary",
            key="rerun_phase1_unavailable",
        ):
            _start_phase1_analysis()
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
    case_count: int,
    direct_risk_case_count: int,
    data_integrity_case_count: int,
    triggered_rule_count: int,
    total_rule_count: int,
    l1_triggered_count: int,
    top_rule_id: str | None,
    top_rule_count: int,
) -> None:
    """KPI 4개를 단일 리본 배너로 표시 — flex 레이아웃 + 세로 구분선.

    Why: 4개 카드가 분리되면 시선이 흩어진다. 하나의 패널로 묶어 '요약 배너'로 인식되게.
         전체 4개 카드 모두 case 단위로 통일해 분모 일관성을 확보.
    """
    sub_style = "color:#9CA3AF; font-size:0.72rem; margin-top:3px;"
    case_sub_html = (
        f"<div style='{sub_style}'>전표 검사 후 생성된 케이스</div>" if case_count else ""
    )
    direct_risk_ratio = direct_risk_case_count / case_count if case_count else 0.0
    high_sub_html = (
        f"<div style='{sub_style}'>전체 케이스의 {direct_risk_ratio:.1%}</div>"
        if case_count
        else ""
    )
    data_integrity_ratio = data_integrity_case_count / case_count if case_count else 0.0
    data_integrity_sub_html = (
        f"<div style='{sub_style}'>전체 케이스의 {data_integrity_ratio:.1%}</div>"
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
        <div style="{label_style}">생성된 검토 후보 케이스</div>
        <div style="color:#111827; {value_base}">
            {case_count:,} <span style="{unit_style}">건</span>
        </div>
        {case_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}"
             title="즉시검토 기준: priority_score &gt;= 0.90">
            즉시검토 케이스
        </div>
        <div style="color:#DC2626; {value_base}">
            {direct_risk_case_count:,} <span style="{unit_style}">건</span>
        </div>
        {high_sub_html}
    </div>
    <div style="{block_style}">
        <div style="{label_style}">데이터 정합성 케이스</div>
        <div style="color:#EA580C; {value_base}">
            {data_integrity_case_count:,} <span style="{unit_style}">건</span>
        </div>
        {data_integrity_sub_html}
    </div>
    <div style="{last_block_style}">
        <div style="{label_style}">발동된 검토 시나리오</div>
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
    doc_band_df = _doc_band_distribution(pr, data)
    case_count = int(summary.get("case_count", 0) or 0)
    direct_risk_case_count = _direct_risk_case_count(pr)
    data_integrity_case_count = int(_signal_category_counts(pr).get("데이터정합성", 0) or 0)

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
        case_count=case_count,
        direct_risk_case_count=direct_risk_case_count,
        data_integrity_case_count=data_integrity_case_count,
        triggered_rule_count=triggered_rule_count,
        total_rule_count=total_rule_count,
        l1_triggered_count=l1_triggered_count,
        top_rule_id=top_rule_id,
        top_rule_count=top_rule_count,
    )

    if not doc_band_df.empty:
        st.markdown(
            "<div style='color:#18181B; font-size:1rem; font-weight:600; "
            "margin:1.5rem 0 0.75rem;'>검토 등급 분포</div>",
            unsafe_allow_html=True,
        )
        _render_risk_pie(doc_band_df, summary.get("topics", []))

    st.markdown("#### 2. 분석 룰 요약")
    _render_phase1_rule_audit(rule_audit)

    # Why: AgGrid 가 무거워 펼친 상태로 default 두면 탭 진입이 느려진다.
    #      expander 로 닫아 두고 사용자가 펼칠 때만 렌더하게 한다.
    with st.expander("3. 전체 데이터 탐색기", expanded=False):
        _render_master_data_grid(pr, data)


_VIEW_MODES: list[tuple[str, str]] = [
    ("전체", "all"),
    ("룰 신호 전표", "rule"),
    ("데이터 정합성 이슈", "data_quality"),
    ("Topic score", "audit_risk"),
    ("Scenario detail", "review"),
]
_GRID_ROW_CAP = 10_000
_GRID_PAGE_SIZE = 50


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
                "룰 선택 (비워두면 모든 룰 신호 전표)",
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
        paginationPageSize=_GRID_PAGE_SIZE,
    )
    # Why: 컬럼/행 가상화로 viewport 밖 DOM 노드를 제거해 초기 렌더 비용을 낮춘다.
    gb.configure_grid_options(
        domLayout="normal",
        suppressColumnVirtualisation=False,
        rowBuffer=10,
    )
    AgGrid(
        show_df,
        gridOptions=gb.build(),
        height=520,
        theme="streamlit",
        key=f"phase1_master_grid_{view_mode}",
        allow_unsafe_jscode=True,
        update_mode=GridUpdateMode.NO_UPDATE,
        # Why: NO_UPDATE 모드라 결과 round-trip이 필요 없으니 타입 복원도 건너뛴다.
        try_to_convert_back_to_original_types=False,
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
    #      정렬. "검토대상수"는 옅은 회색 코드형 칩. 통계 줄 없음.
    info_html = (
        "<div style='background:#F8FAFC; border:1px solid #E5E7EB; border-radius:8px; "
        "padding:12px 16px 12px 36px; position:relative; margin:0.25rem 0 0.9rem; "
        "color:#475569; font-size:0.85rem; line-height:1.7;'>"
        "<span style='position:absolute; left:14px; top:12px; color:#64748B; "
        "font-size:0.95rem;'>&#9432;</span>"
        "<div>우측 배지는 "
        "<span style='display:inline-block; padding:1px 6px; background:#F1F5F9; "
        "color:#334155; border:1px solid #E2E8F0; border-radius:4px; font-size:0.78rem; "
        "font-weight:500; margin:0 0.15rem;'>검토대상수</span>"
        " (중복 케이스는 중복 카운트).</div>"
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
        "한 전표 안에서 차변 합계와 대변 합계가 일치하지 않는 케이스를 검토 후보로 올립니다. "
        "복식부기의 가장 기본 원칙을 깬 구조 오류로, 단순 반올림 오차부터 수기 분개 실수, "
        "의도적 차대 불일치 가능성까지 검토 범위에 포함됩니다."
    ),
    "L1-02": (
        "전표일자·계정·금액 같이 회계 처리에 필수적인 필드가 비어 있는 라인을 검토 후보로 표시합니다. "
        "회계처리 자체가 불완전하거나 감사 추적이 불가능한 데이터 품질 이슈로, "
        "분석을 시작하기 전에 먼저 정리해야 합니다."
    ),
    "L1-03": (
        "회사 계정과목표(CoA)에 등록되지 않은 계정 코드로 기표된 라인을 검토 후보로 올립니다. "
        "미사용 placeholder 계정(예: 9999, 8888)을 악용한 가공 전표 또는 "
        "데이터 정합성 오류 신호입니다."
    ),
    "L1-04": (
        "결재권자(approved_by)의 위임전결 한도(approval_limit)를 넘는 금액인데도 "
        "그 사람이 승인한 전표입니다. 통제 실패 또는 승인권한 초과 가능성을 검토할 근거가 됩니다."
    ),
    "L1-05": (
        "작성자(created_by)와 승인자(approved_by)가 동일한 전표입니다. "
        "직무 분리(SoD)의 가장 직접적인 통제 충돌 신호로, "
        "1인이 입력·승인을 함께 처리해 통제를 우회한 패턴 — "
        "대형 자금 유용 사례에서 반복적으로 관찰되는 통제 신호입니다."
    ),
    "L1-06": (
        "한 사용자가 충돌하는 권한(구매-지급, 매출-수금, IT 관리자-업무 처리 등)을 "
        "동시에 행사한 케이스입니다. 자기 승인은 L1-05가 따로 보고, "
        "여기서는 권한 결합 자체를 검토 후보로 올립니다."
    ),
    "L1-07": (
        "한도를 넘는 금액인데도 승인자가 비어 있거나, 정상 승인 단계를 거치지 않은 전표입니다. "
        "외감법 §8② 관점에서 직접 검토할 통제 신호로, 한도초과 + 승인 없음 조합이 가장 강한 신호입니다."
    ),
    "L1-08": (
        "기표일이 속한 달과 전표에 적힌 회계기간(fiscal_period)이 어긋난 케이스입니다. "
        "회사의 회계연도 시작월(예: 1월/4월)을 반영해 환산한 기수와 비교하므로 "
        "단순 month != period 비교보다 회계연도 설정을 더 잘 반영합니다. "
        "기간귀속 조작, 결산 직전 끼워넣기 등의 신호."
    ),
    "L1-09": (
        "승인자는 있는데 승인 시각이 기록되지 않은 전표입니다. "
        "승인 절차의 추적 가능성을 깨뜨리는 신호이고, 사후 승인이나 기록 신뢰성 저하 가능성을 검토할 "
        "보강 근거가 됩니다."
    ),
    "L2-01": (
        "승인자의 한도 90% 이상 100% 미만 구간에 금액이 맞춰진 전표입니다. "
        "한도 회피(splitting/structuring)를 의식한 의도적 금액 설정 가능성을 봅니다. "
        "razor band(98% 이상)일수록 검토 우선순위가 높습니다."
    ),
    "L2-02": (
        "같은 거래처에 같은 금액이 반복 지급된 검토 후보 전표입니다. "
        "reference(증빙번호)가 같으면 강한 신호, 없으면 거래처+금액+45일 이내 재지급으로 "
        "보수적으로 검토 후보로 올립니다. 정기 반복 지급(렌트 등)은 자동으로 제외됩니다."
    ),
    "L2-03": (
        "같은 거래가 여러 번 입력된 케이스 — exact 중복부터 reference 중복, "
        "near 중복(금액·날짜·적요 유사), split 중복(분할 입력)까지 검토 후보로 올립니다. "
        "가공 전표나 재입력 오류 모두 후보가 됩니다."
    ),
    "L2-04": (
        "비용으로 처리해야 할 항목이 자산 계정으로 분개된 케이스입니다. "
        "비용 자산화나 손익 표시 적정성을 검토할 신호입니다. "
        "자산/비용 계정 prefix 매칭으로 검토 후보를 분류합니다."
    ),
    "L2-05": (
        "기표 직후 동일 금액의 반대 분개로 취소된 전표 쌍을 검토 후보로 올립니다. "
        "결산 직전 일시적 손익 조정이나 회계처리 변경 흔적일 수 있고, "
        "정상적인 결산조정도 포함될 수 있어 맥락 검토가 필요합니다."
    ),
    "L3-01": (
        "계정 자체는 유효하지만 거래 성격이나 적요와 어색하게 매칭된 라인을 표시합니다. "
        "예: 매출 적요인데 비용 계정으로 처리된 경우. "
        "L1-03(존재하지 않는 계정)과 다르게 사용된 계정의 의미가 어색한 경우입니다."
    ),
    "L3-02": (
        "자동 인터페이스(SAP IF, 배치 등)로 처리되어야 할 거래가 수기(manual)로 직접 입력된 "
        "케이스입니다. 수기 입력은 자동화 통제 우회 가능성이 있어 다른 신호와 함께 검토합니다."
    ),
    "L3-03": (
        "관계사·임원 등 특수관계자(IC) 거래로 추정되는 전표를 검토 대상으로 표시합니다. "
        "계열사 간 자금 이동이나 부당지원 리스크와 관련되어 별도 공시·승인 대상이 됩니다."
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
        "영업시간 외(22~06시)에 기표된 전표를 검토 후보로 올립니다. "
        "주말 기표와 함께 비정상 시점 신호로 결합 평가됩니다."
    ),
    "L3-07": (
        "증빙일(document_date)과 기표일(posting_date)의 차이가 비정상적으로 큰 전표입니다. "
        "사후 끼워넣기(backdating), 늦은 cutoff 처리, 증빙 신뢰성 검토의 보조 신호."
    ),
    "L3-08": (
        '적요(line_text)가 비어 있거나 의미 없는 문자열(예: "...", "테스트", '
        "동일 글자 반복)인 전표입니다. 감사 추적성을 깨뜨리는 데이터 품질 이슈이자 "
        "가공 전표의 신호입니다."
    ),
    "L3-09": (
        "가지급금·미결산·임시계정의 잔액이 장기간 해소되지 않은 케이스를 검토 후보로 올립니다. "
        "회계 정리가 누락됐거나, 자금 유용 리스크가 임시계정에 장기 잔류하는지 검토할 신호."
    ),
    "L3-10": (
        "회사 정책상 고위험으로 분류된 계정(현금성 자산, 가지급금, 임원 차입금 등)이 "
        "사용된 라인을 표시합니다. 단독으로는 확정 이슈가 아니지만 다른 신호와 결합 시 "
        "우선순위가 올라갑니다."
    ),
    "L3-12": (
        "사용자의 일반 업무 범위(role/process) 밖의 계정·프로세스에 손을 댄 케이스입니다. "
        "L1-06이 직접 SoD 충돌을 보지만, L3-12는 더 넓은 업무범위 검토 모집단을 표시합니다."
    ),
    "L4-01": (
        "매출 계정 분포에서 통계적으로 벗어난 금액(이상 고액·이상 저액)을 검토 후보로 올립니다. "
        "매출 기말 매출·손익 표시 적정성을 검토할 신호입니다."
    ),
    "L4-02": (
        "첫 자리 숫자 분포가 벤포드 법칙(1이 30.1%, 2가 17.6% ...)과 유의미하게 다른 "
        "모집단을 검토 후보로 올립니다. MAD(평균절대편차) 기준으로 적합/경계/부적합을 평가하며, "
        "인위적 금액 패턴 가능성을 검토할 통계 신호가 됩니다."
    ),
    "L4-03": (
        "모집단 분포 대비 비정상적으로 큰 금액(상위 percentile)의 전표를 검토 후보로 올립니다. "
        "고액 자체가 확정 이슈는 아니지만 우선 검토가 필요한 모집단을 만듭니다."
    ),
    "L4-04": (
        "평소 짝지어지지 않는 차변·대변 계정 조합을 가진 전표입니다. "
        "비정상적인 회계 처리 경로로, 우회 분개나 비정상 처리 경로의 검토 신호일 수 있습니다."
    ),
    "L4-05": (
        "특정 짧은 시간대(분 단위)에 다수 전표가 군집된 패턴입니다. "
        "자동화 우회나 batch 처리 이상 여부를 검토할 신호."
    ),
    "L4-06": (
        "한 사람이 짧은 시간 안에 다량 전표를 일괄 기표한 패턴입니다. "
        "정상 자동화는 system source로 식별되므로, 사람이 한 일괄 입력만 검토 후보로 올립니다."
    ),
    "D01": (
        "전기 대비 특정 계정의 거래 빈도·금액 분포가 급변한 신호를 검토 후보로 올립니다. "
        "계정 이동, 회계정책 변경, 비정상 거래 시작점을 포착합니다."
    ),
    "D02": (
        "주요 재무비율(매출원가율·인건비율 등)의 분포가 전기 대비 유의미하게 변동한 신호를 "
        "검토 후보로 올립니다. 거시적 손익 변동이나 회계 환경 변화의 검토 신호."
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
        st.caption("표시할 상세 근거 항목이 없습니다.")
        return
    for start in range(0, len(details), 3):
        cols = st.columns(min(3, len(details) - start))
        for col, item in zip(cols, details[start : start + 3], strict=False):
            col.metric(
                str(item.get("label") or "상세"),
                _format_violation_detail_value(item),
            )


# Why: 룰마다 사용자가 즉시 봐야 할 핵심 비교 컬럼이 다르다. 공통 컬럼(전표번호/검토 신호 요약/
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
    "L2-01": "전표 금액이 승인 한도 근접 구간(분할 검토 신호)에 있는지 검증",
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

# Why: 원본 전표 상세 내역에서 룰별 검토 신호 컬럼/셀을 시각적으로 강조해 "어디를 봐야 하는지"
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
            f"<b>검토 포인트</b> : {html.escape(review_point)}</div>"
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
        "violation_summary": "검토 신호 요약",
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
    """원본 전표 라인을 룰별 검토 신호 셀 강조 + 바닥 합계 행과 함께 AgGrid로 렌더링."""
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

    # Why: 강조 컬럼 안내 캡션은 표 안에서 시각적 강조로 이미 전달되므로
    #      부차 설명을 제거하고 표만 노출한다 (모든 룰 공통).

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


def _case_display_priority_band(case: Any) -> str:
    return _display_priority_band_from_score(
        getattr(case, "priority_score", None),
        getattr(case, "priority_band", "low"),
    )


def _row_display_priority_band(row: dict[str, Any]) -> str:
    return _display_priority_band_from_score(
        row.get("priority_score"),
        row.get("priority_band", "low"),
    )


def _case_display_priority_band_rank(case: Any) -> int:
    return _priority_band_rank(_case_display_priority_band(case))


def _display_case_row(case: Any, phase1: Any) -> dict[str, Any]:
    row = _case_row(case, phase1)
    row["priority_band"] = _case_display_priority_band(case)
    return row


def _immediate_review_case_ids(phase1: Any) -> set[str]:
    cases = list(getattr(phase1, "cases", []) or [])
    if not cases:
        return set()
    ranked = sorted(
        cases,
        key=lambda case: (
            float(getattr(case, "priority_score", 0.0) or 0.0),
            float(getattr(case, "composite_sort_score", 0.0) or 0.0),
            float(getattr(case, "triage_rank_score", 0.0) or 0.0),
            float(getattr(case, "total_amount", 0.0) or 0.0),
        ),
        reverse=True,
    )
    target_count = max(1, round(len(ranked) * _CASE_IMMEDIATE_REVIEW_RATIO))
    return {str(getattr(case, "case_id", "")) for case in ranked[:target_count]}


def _display_priority_band_for_case(case: Any, immediate_case_ids: set[str]) -> str:
    if str(getattr(case, "case_id", "")) in immediate_case_ids:
        return "high"
    return _display_priority_band_from_score(
        getattr(case, "priority_score", None),
        getattr(case, "priority_band", "low"),
    )
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
        "즉시검토 case 안에 행 Normal/Low 가 다수일 수 있습니다.</div>"
    )
    return bar + legend + note


def _format_amount_short(value: float) -> str:
    """case master 표 합계 컬럼용 한국식 단위 약어."""
    return format_krw_compact(value, zero="0", grouped=False)


# Why: 데이터 정합성/구조 결함 룰은 전표 단위 결함이라 case 묶음(회사·기간·계정 그룹화)
#      에 묶을 의미가 없다. 감사인이 곧장 "어느 전표가 어떤 필드를 어겼느냐"로 진입하도록
#      case master 단계를 생략하고 검토 신호 전표 목록을 바로 master로 렌더한다.
#      L1-01 차대변 불일치, L1-02 필수필드 누락, L1-03 무효계정 사용, L1-08 회계기간 오류.
RULES_WITHOUT_CASE_GROUPING: frozenset[str] = frozenset({"L1-01", "L1-02", "L1-03", "L1-08"})

# Why: case 생략 컨텍스트(DQ 탭 + RULES_WITHOUT_CASE_GROUPING)의 master 정렬 키.
#      룰별 핵심 비교 지표(차이/초과액/일수)를 우선 정렬해 감사인이 "더 심각한 결함"
#      부터 보게 한다. 비교 지표가 없는 룰은 evidence_amount(거래금액) 기본 fallback.
_NO_CASE_SORT_OVERRIDE: dict[str, tuple[str, str]] = {
    # (정렬 컬럼명, 캡션 라벨)
    "L1-01": ("difference_value", "차이 큰 순"),
    "L1-02": ("difference_value", "누락 필드 많은 순"),
    "L1-04": ("difference_value", "초과액 큰 순"),
    "L1-08": ("difference_value", "차이(개월) 큰 순"),
    "L3-07": ("difference_value", "일자 차이 큰 순"),
    # L1-05/L1-07/L1-09/L3-04는 거래금액 fallback (별도 비교 지표 없음).
}


@st.fragment
def _render_rule_master_detail(
    rule_id: str,
    rows: list[dict],
    *,
    pr,
    key_suffix: str = "",
    topic_id: str | None = None,
    force_no_case: bool = False,
) -> None:
    """Case-centric 3단 master/detail (데이터 정합성 룰은 2단으로 단축).

    Layer 1: 이 룰이 잡힌 case 목록 (자연어 라벨, 전표수, 합계, band, 사유)
    Layer 2: 선택된 case 안의 검토 신호 전표 목록 (case_id 로 rows 필터)
    Layer 3: 선택된 전표의 검토 신호 상세 + 원본 원장 라인 하이라이트

    `RULES_WITHOUT_CASE_GROUPING`에 속하는 룰은 Layer 1을 건너뛰고 Layer 2의
    전표 목록을 직접 master로 렌더한다(case 묶음이 무의미한 데이터 결함 룰).

    Why: 같은 룰이 여러 토픽 탭에 등장할 수 있어 (예: L3-05는 approval_control과 closing_timing
         양쪽에 매핑) AgGrid key 충돌이 발생한다. key_suffix를 받아 토픽별로 고유화한다.
         topic_id: expander 헤더의 case 카운트는 토픽 단위(`_topic_summary_stats`)인데,
         case 목록도 같은 토픽 필터를 적용해야 단위가 일치한다. None 이면 전체 phase1
         case 에서 룰 매칭만 보는 fallback (DQ gate).
         @st.fragment: AgGrid 행 클릭 시 페이지 전체 rerun 으로 브라우저 스크롤이 점프하는
         문제를 막기 위해 master/detail 영역만 부분 rerun 한다.
         force_no_case: 데이터 정합성 탭처럼 컨텍스트 단위로 case 묶음을 끄고 싶을 때
         호출부에서 True 로 강제한다(통계결과 탭 Topic Top-N에서는 False 기본).
    """
    skip_case_layer = force_no_case or rule_id in RULES_WITHOUT_CASE_GROUPING

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

    if skip_case_layer:
        selected_doc = _render_rule_document_master_no_case(
            rule_id, rows or [], key_suffix=key_suffix
        )
    else:
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
        st.caption("위 검토 신호 전표 목록에서 한 줄을 선택하세요.")
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

    st.markdown("##### 검토 신호 전표 상세 내역")
    # Why: violation_details(차변/대변/불일치 등 메트릭 카드)는 표 안에 같은
    #      정보가 이미 보이므로 부차 설명을 제거하고 표만 노출한다 (모든 룰 공통).
    raw_lines = detail.get("raw_lines") or []
    if not raw_lines:
        st.caption("원본 전표 라인을 찾지 못했습니다.")
        return
    _render_raw_lines_table(rule_id, raw_lines, key_suffix=key_suffix)


def _render_rule_document_master_no_case(
    rule_id: str,
    rows: list[dict],
    *,
    key_suffix: str = "",
) -> str | None:
    """Case 단계를 생략하고 룰 신호 전표 목록을 직접 master로 렌더.

    Why: `RULES_WITHOUT_CASE_GROUPING` 룰(L1-01/02/03/08)은 전표 단위 데이터
         결함이라 case 묶음이 무의미하다. 묶음 단계를 제거해 감사인이 곧장
         "어느 전표가 어떤 필드를 어겼느냐"로 진입하도록 한다.
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

    if not rows:
        st.caption("이 룰의 검토 신호 전표 데이터를 찾지 못했습니다.")
        return None
    docs_df = pd.DataFrame(rows)
    if "document_id" not in docs_df.columns:
        st.caption("이 룰의 표시할 검토 신호 전표가 없습니다.")
        return None

    # Why: 룰의 핵심 비교 지표가 있으면 그 지표(절댓값 기준)로 내림차순 재정렬한다.
    #      L1-01은 차이 금액이 클수록 즉시 검토 우선순위가 높다.
    sort_override = _NO_CASE_SORT_OVERRIDE.get(rule_id)
    if sort_override and sort_override[0] in docs_df.columns:
        sort_col = sort_override[0]
        sort_label = sort_override[1]
        sort_series = pd.to_numeric(docs_df[sort_col], errors="coerce").abs()
        docs_df = (
            docs_df.assign(_sort_key=sort_series)
            .sort_values(by="_sort_key", ascending=False, na_position="last")
            .drop(columns=["_sort_key"])
            .reset_index(drop=True)
        )
    else:
        sort_label = "거래금액 큰 순"

    cap = min(len(docs_df), 500)
    master_df = docs_df.head(cap).copy()
    master_display, extra_labels = _build_master_display(rule_id, master_df)
    # Why: case를 생략했으므로 case band 컬럼은 정보가치가 없다.
    if "Case Band" in master_display.columns:
        master_display = master_display.drop(columns=["Case Band"])

    st.markdown("##### 검토 신호 전표 목록")
    total = len(docs_df)
    if total > cap:
        st.caption(f"검토 신호 전표 {total:,}건 중 상위 {cap:,}건 표시 ({sort_label})")
    else:
        st.caption(f"검토 신호 전표 {cap:,}건 ({sort_label})")

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
    if "검토 신호 요약" in master_display.columns:
        gb.configure_column("검토 신호 요약", minWidth=200, flex=3, wrapText=True, autoHeight=True)
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
    grid_key = f"phase1_rule_doc_master_nocase_{rule_id}{suffix}"
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

    state_key = f"_phase1_rule_doc_selection_{grid_key}"
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


def _render_rule_case_master(
    rule_id: str,
    cases: list[dict],
    *,
    key_suffix: str = "",
    hide_columns: set[str] | None = None,
    caption_override: str | None = None,
    show_header: bool = True,
    preserve_order: bool = False,
    rank_column: bool = False,
) -> str | None:
    """Layer 1 — 룰별 case 목록 master. 선택된 case_id 반환.

    hide_columns: 표시 컬럼에서 제외할 라벨(예: {"전표 수", "Band"}). 검토 케이스
                  탭처럼 일부 컬럼을 슬림화하고 싶을 때 호출부에서 지정한다.
    caption_override: 기본 캡션("N개의 case 가 묶여…") 대신 노출할 안내 문구.
                  빈 문자열을 넘기면 캡션 자체를 생략한다.
    show_header: "##### case 목록" 헤더 표시 여부. False이면 헤더 생략.
    preserve_order: True이면 내부 (band, -amount) 재정렬을 건너뛰고 호출부에서
                  넘긴 cases 순서를 그대로 유지한다. 검토 케이스 탭처럼 호출부가
                  priority composite_sort_score 같은 별도 기준으로 정렬했을 때
                  표시 순서를 깨뜨리지 않게 한다.
    rank_column: True 이면 최종 표시 순서 기준 "순위" 컬럼(1부터)을 사례 요약
                  왼쪽 pinned 컬럼으로 추가. preserve_order=True 와 함께 써야
                  의미가 있다(정렬이 다시 일어나면 순위가 깨짐).
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    # Why: case 수가 룰당 1만 건을 넘어가면 AgGrid client-side 렌더가 수 초~수십 초로
    #      체감 정지가 생긴다. priority band → 금액 내림차순으로 정렬한 뒤 상위 N건만
    #      클라이언트로 보내고, 페이지네이션으로 viewport DOM 노드도 제한한다.
    _CASE_MASTER_CAP = 1_000
    _CASE_MASTER_PAGE_SIZE = 50
    _BAND_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    hide_columns = hide_columns or set()

    case_rows = [
        {
            "case_id": case["case_id"],
            "사례 요약": case["natural_label"],
            "전표 수": int(case["document_count"] or 0),
            "합계": _format_amount_short(float(case["total_amount"] or 0.0)),
            "_total_amount": float(case["total_amount"] or 0.0),
            "Band": _format_band_cell(_row_display_priority_band(case)),
            "_band_rank": _BAND_RANK.get(_row_display_priority_band(case).upper(), 9),
            "위험 사유": (case.get("why") or "").strip(),
        }
        for case in cases
    ]
    if not preserve_order:
        case_rows.sort(key=lambda row: (row["_band_rank"], -row["_total_amount"]))
    if rank_column:
        # Why: 최종 표시 순서가 곧 위험도 순위. 정렬이 끝난 뒤에 1부터 매겨야
        #      preserve_order=False 인 경우에도 보이는 순서와 일치한다.
        for idx, row in enumerate(case_rows, start=1):
            row["순위"] = idx
    total_cases = len(case_rows)
    truncated_cases = total_cases > _CASE_MASTER_CAP
    case_df = pd.DataFrame(case_rows[:_CASE_MASTER_CAP]).drop(columns=["_band_rank"])
    if rank_column and "순위" in case_df.columns:
        # 사례 요약 왼쪽으로 끌어와 다른 컬럼 순서 유지.
        ordered = ["순위"] + [col for col in case_df.columns if col != "순위"]
        case_df = case_df[ordered]
    if hide_columns:
        case_df = case_df.drop(columns=[col for col in hide_columns if col in case_df.columns])

    if show_header:
        st.markdown("##### case 목록")
    if caption_override is None:
        caption = (
            f"{total_cases:,}개의 case 가 묶여 있습니다. "
            "case 한 줄을 선택하면 그 묶음 안 검토 신호 전표가 아래에 펼쳐집니다."
        )
        if truncated_cases:
            caption += (
                f" · 표시 상한 {_CASE_MASTER_CAP:,}건 적용 (priority band → 합계 내림차순 상위)"
            )
        st.caption(caption)
    elif caption_override:
        st.caption(caption_override)

    gb = GridOptionsBuilder.from_dataframe(case_df)
    gb.configure_default_column(resizable=True, filter=True, sortable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False, pre_selected_rows=[0])
    gb.configure_pagination(
        paginationAutoPageSize=False,
        paginationPageSize=_CASE_MASTER_PAGE_SIZE,
    )
    gb.configure_grid_options(
        rowSelection="single",
        suppressRowClickSelection=False,
        suppressCellFocus=True,
        rowBuffer=10,
    )
    gb.configure_column("case_id", hide=True)
    gb.configure_column("_total_amount", hide=True)
    if "순위" in case_df.columns:
        gb.configure_column(
            "순위",
            type=["numericColumn"],
            minWidth=44,
            maxWidth=56,
            pinned="left",
            headerTooltip="검토 우선순위 (priority composite 큰 순)",
        )
    # Why: 검토 케이스 탭에서는 자연어 case key가 바로 식별 정보다. 사례 요약은
    #      줄바꿈으로 모두 보이게 하고, 남는 폭은 위험 사유에 양보(flex 비중 차이)한다.
    gb.configure_column(
        "사례 요약",
        minWidth=280,
        flex=1,
        wrapText=True,
        autoHeight=True,
        tooltipField="사례 요약",
    )
    if "전표 수" in case_df.columns:
        gb.configure_column("전표 수", type=["numericColumn"], minWidth=70, maxWidth=90)
    if "합계" in case_df.columns:
        gb.configure_column("합계", minWidth=90, maxWidth=120)
    if "Band" in case_df.columns:
        gb.configure_column(
            "Band",
            minWidth=80,
            maxWidth=110,
            headerTooltip=(
                "축: case priority_band (즉시검토 high >= 0.90, "
                "검토 후보 medium >= 0.75, 참고 후보 low < 0.75). "
                "행 risk_level 과는 다른 축."
            ),
        )
    if "위험 사유" in case_df.columns:
        gb.configure_column(
            "위험 사유",
            minWidth=360,
            flex=3,
            wrapText=True,
            autoHeight=True,
            tooltipField="위험 사유",
        )

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
        st.caption("이 case 의 검토 신호 전표 데이터를 찾지 못했습니다.")
        return None
    docs_df = pd.DataFrame(rows)

    case_entry = case_doc_map.get(str(case_id), {}) or {}
    hit_doc_ids = set(case_entry.get("hit_documents", []) or [])
    related_doc_ids = set(case_entry.get("related_documents", []) or [])
    if not hit_doc_ids or "document_id" not in docs_df.columns:
        st.caption("이 case 안에 표시할 검토 신호 전표가 없습니다.")
        if related_doc_ids:
            st.caption(f"(같은 case 안에 다른 룰만 잡힌 전표 {len(related_doc_ids):,}건 있음)")
        return None
    filtered = docs_df[docs_df["document_id"].astype(str).isin(hit_doc_ids)].copy()
    if filtered.empty:
        st.caption("이 case 안에 표시할 검토 신호 전표가 없습니다.")
        return None

    cap = min(len(filtered), 500)
    master_df = filtered.head(cap).copy()
    master_display, extra_labels = _build_master_display(rule_id, master_df)
    # Why: 같은 case 안 전표는 모두 동일한 case band 라 컬럼이 중복 정보가 된다.
    if "Case Band" in master_display.columns:
        master_display = master_display.drop(columns=["Case Band"])

    st.markdown("##### 검토 신호 전표 목록")
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
    if "검토 신호 요약" in master_display.columns:
        gb.configure_column("검토 신호 요약", minWidth=200, flex=3, wrapText=True, autoHeight=True)
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
        ("L1-03", "L3-01", "L3-08"),
        "마스터 데이터(계정·거래처) 정합성 이슈와 필수 메타데이터(적요) 누락 ·훼손 항목입니다.",
    ),
    (
        "일자·기간 흐름 정합성",
        ("L3-07", "L1-09"),
        "증빙일·기표일·승인일·월말 윈도우 간 흐름이 어색한 항목입니다.",
    ),
    (
        "승인·권한 데이터 정합성",
        ("L1-04", "L1-05", "L1-06", "L1-07"),
        "승인 한도 초과, 자기 승인, 직무 분리(SoD) 충돌, 승인 절차 누락 등 "
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
    # Why: 위반 전표가 0건인 룰은 expander 자체를 그리지 않는다. 사용자는 펼치기 전엔
    #      해당 룰이 잡혔는지 알 수 없고, 펼친 뒤 "데이터를 찾지 못했습니다" 안내만
    #      보여 노이즈가 된다. documents 컬럼이 있을 때만 필터링하고 없으면 원본 유지.
    if "documents" in items_df.columns:
        items_df = items_df[items_df["documents"].fillna(0).astype(int) > 0]
        if items_df.empty:
            st.info("검토 신호 전표가 없습니다.")
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
                # Why: 데이터 정합성 탭은 컨텍스트 단위로 case 묶음을 생략하여
                #      바로 검토 신호 전표 목록을 노출한다(룰 종류와 무관). 통계결과 탭의
                #      Topic Top-N에서는 case-centric 동작이 유지된다.
                _render_rule_master_detail(rule_id, rows or [], pr=pr, force_no_case=True)
            else:
                st.caption("헤더를 클릭해 펼치면 검토 신호 전표 목록이 표시됩니다.")


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

    # Why: 상단 "정합성 위반 전표" 메트릭 + divider 제거. 룰별 카드에 동일 카운트가
    #      이미 표시되므로 부차 KPI 카드가 불필요.

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
         _render_rule_master_detail (시그니처 카드 + 셀 강조 그리드 + 근거 칩) 패턴을
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
        st.info(f"{topic_label} 영역에 매칭된 룰 신호가 없습니다.")
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

    st.markdown("##### 룰별 검토 신호")
    for group in rule_groups:
        rule_id = group["rule_id"]
        # Why: 헤더는 case(시나리오) 단위 카운트, 아래 검토 신호 전표 목록 표는 document
        #      (전표) 단위라 두 숫자가 일치하지 않는다. 'case'/'전표' 라벨을 명시해
        #      감사인이 단위 차이를 즉시 인지하게 한다.
        #      단, RULES_WITHOUT_CASE_GROUPING(L1-01/02/03/08)은 case 단계 자체를
        #      생략하므로 헤더에도 case 정보를 표시하지 않고 전표 수만 노출한다.
        skip_case_layer = rule_id in RULES_WITHOUT_CASE_GROUPING
        doc_count = int(group.get("document_count") or 0)
        if skip_case_layer:
            meta = f"전표 {doc_count:,}건" if doc_count else ""
        else:
            bands_chunks: list[str] = []
            if group["high_count"]:
                bands_chunks.append(f"High {group['high_count']}")
            if group["medium_count"]:
                bands_chunks.append(f"Med {group['medium_count']}")
            if group["low_count"]:
                bands_chunks.append(f"Low {group['low_count']}")
            bands_text = " · ".join(bands_chunks)
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
            elif skip_case_layer:
                st.caption("헤더를 클릭해 펼치면 검토 신호 전표 목록이 표시됩니다.")
            else:
                st.caption("헤더를 클릭해 펼치면 case 목록과 검토 신호 전표가 표시됩니다.")


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
        band = _case_display_priority_band(case)
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
        band = _case_display_priority_band(case)
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
        "<span style='color:#DC2626;' "
        f"title='priority_score &gt;= 0.90'>즉시검토 {high}</span> · "
        "<span style='color:#EA580C;' "
        f"title='priority_score &gt;= 0.75'>검토대상 {medium}</span> · "
        "<span style='color:#0EA5E9;' "
        f"title='priority_score &lt; 0.75'>참고후보 {low}</span>"
    )
    case_count_html = f'{case_count:,} <span style="{unit_style}">건</span>'
    doc_count_html = f'{doc_count:,} <span style="{unit_style}">건</span>'
    rule_count_html = f'{rule_count:,} <span style="{unit_style}">개</span>'
    ribbon = f"""
<div style="display:flex; align-items:center; background:#F9FAFB;
            border:1px solid #F3F4F6; border-radius:10px;
            padding:0.55rem 0.6rem; margin:0 0 0.9rem;">
  <div style="{block}"><div style="{label_style}">검토 케이스</div>
    <div style="color:#DC2626; {value_style}">{case_count_html}</div></div>
  <div style="{block}"><div style="{label_style}">영향 전표</div>
    <div style="color:#111827; {value_style}">{doc_count_html}</div></div>
  <div style="{block}"><div style="{label_style}">활성 룰</div>
    <div style="color:#111827; {value_style}">{rule_count_html}</div></div>
  <div style="{last}"><div style="{label_style}">검토 등급 분포</div>
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
        band = _row_display_priority_band(row).upper()
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
        help=("옵션 앞 등급 = 즉시검토 >= 0.90 / 검토대상 >= 0.75 / 참고후보"),
    )
    case_id = options[selected_label]
    drilldown = _cached_phase1_build(pr, "case_drilldown", build_phase1_case_drilldown, case_id)
    if drilldown is None:
        return
    case = drilldown["case"]

    band = _row_display_priority_band(case)
    # §5-4: case priority_band 와 row risk_level 은 다른 축. row(warm) 와 색상이 겹치지
    #       않도록 case 축은 cool 톤(indigo/violet/slate) 으로 분리.
    band_color = {"high": "#4338CA", "medium": "#7C3AED", "low": "#94A3B8"}.get(band, "#64748B")
    band_label = {"high": "◆ 즉시검토", "medium": "◆ 검토대상", "low": "◆ 참고후보"}.get(
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

    band_axis_tooltip = (
        f"축: case priority_band ({band_label.replace('◆ case ', 'priority ').lower()}). "
        "행 risk_level 과 다른 축."
    )
    panel_a = (
        f"<div style='{quad_box_style}'>"
        f"<div style='{quad_label_style}'>① What · 검토 요지</div>"
        f"<div style='font-size:1rem; color:{band_color}; font-weight:700; margin-bottom:8px;'>"
        f"<span title='{html.escape(band_axis_tooltip)}'>{band_label}</span>"
        f" &nbsp;·&nbsp; {main_reason_safe}</div>"
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
        f"<div style='{quad_label_style}'>③ Why · 근거·점수</div>"
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
            -_case_display_priority_band_rank(case),
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
    band_matrix: list[list[str]] = []
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
        band_full = _case_display_priority_band(case)
        band = band_full.upper()[:1]
        key_text = (case.case_key or case.case_id)[:28]
        case_axis.append(f"[{band}] {key_text}")
        # Why: y축은 폭상 [H]/[M]/[L] 약자만 노출하고, hover에서 priority {band} 정책 표기.
        band_matrix.append([f"priority {band_full}"] * len(rule_ids))

    fig = go.Figure(
        data=go.Heatmap(
            z=z_matrix,
            x=rule_axis,
            y=case_axis,
            text=text_matrix,
            texttemplate="%{text}",
            textfont=dict(size=10, color="#0F172A"),
            customdata=band_matrix,
            colorscale=[
                [0.0, "#F8FAFC"],
                [0.001, "#FEF3C7"],
                [0.5, "#FB923C"],
                [1.0, "#DC2626"],
            ],
            zmin=0.0,
            zmax=1.0,
            hovertemplate=(
                "<b>%{y}</b><br>%{customdata} (case priority_band)<br>"
                "%{x}<br>signal=%{z:.2f}<extra></extra>"
            ),
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
        "한 케이스에 여러 룰 신호가 동시에 모이는 패턴을 한눈에 확인합니다."
    )
    st.plotly_chart(fig, width="stretch", key=f"phase1_heatmap_{topic_id}")
    st.divider()


def _render_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="Topic Top N",
        title="Topic Top N",
        caption="priority high/medium 우선순위이며 직접 위험 신호가 있는 case입니다.",
        key_prefix="phase1_priority_risk",
    )


def _render_low_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="Topic 보조 표시",
        title="Topic 보조 표시",
        caption=(
            "직접 위험 신호는 있지만 priority low이거나 timing/control 성격의 넓은 "
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
                _case_display_priority_band_rank(case),
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
                "rows": [_display_case_row(case, phase1) for case in cases],
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
        width="stretch",
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


_VIOLATION_CASES_CAP = 200


@st.fragment
def _render_violation_cases_tab(pr, summary: dict) -> None:
    """검토 케이스 탭 — 핵심 메시지 + Top 200 case master + 클릭 시 drilldown.

    Why: PHASE1 전체 위반은 수만 건이지만 감사인이 1주 풀타임으로 검토 가능한
         양은 Top 50~100건이 한계. 핵심 메시지로 검토 한계를 안내하고
         priority composite_sort_score 큰 순으로 Top 200까지 master에 보내고,
         AgGrid 페이지네이션(50건/페이지)로 넘기게 한다. 행 클릭 시 case
         drilldown(설명·메트릭·문서 목록·signal section)이 아래에 펼쳐진다.

         @st.fragment: AgGrid SELECTION_CHANGED 가 페이지 전체 rerun 으로 번지면
         st.tabs 활성 탭 상태가 초기화돼 "케이스 선택 시 개요 탭으로 튕기는"
         버그가 난다. fragment 로 격리해 검토 케이스 탭 영역만 부분 rerun.
    """
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None or not phase1.cases:
        st.info("PHASE1 case 결과가 없습니다.")
        return

    # Why: streamlit st.info()는 파란 강조 박스라 화면 톤이 과하다. 회색 컨테이너
    #      + ℹ 아이콘으로 부드럽게 처리하고, 본문은 priority cohort별 회수율을
    #      간결한 dash 형식으로 정리한다.
    st.markdown(
        """
<div style="background:#F3F4F6; border:1px solid #E5E7EB; border-radius:8px;
            padding:0.75rem 1rem; margin:0.25rem 0 1rem; color:#374151;">
  <div style="font-weight:600; margin-bottom:0.45rem; color:#111827;">
    ℹ 검토 우선순위 안내
  </div>
  <ul style="margin:0; padding-left:1.2rem; font-size:0.88rem; line-height:1.6;">
    <li><strong>Top 50 우선 조회</strong> — 감사인이 먼저 확인할 이상 징후가 상위 구간에 집중되어 있습니다.</li>
    <li><strong>Top 100 ~ 200 확장</strong> — 회수율 약 40 ~ 50%까지 상승.</li>
    <li><strong>Top 500 이후</strong> — 추가 발견의 한계 효익 급감.</li>
  </ul>
</div>
""",
        unsafe_allow_html=True,
    )

    # Why: priority band → composite_sort_score → tie-breakers 순으로 내림차순 정렬.
    #      _category_rule_groups 의 정렬 기준과 동일해 운영 해석 일관성을 유지한다.
    cases = sorted(
        phase1.cases,
        key=lambda c: (
            _case_display_priority_band_rank(c),
            c.composite_sort_score,
            c.priority_score,
            c.triage_rank_score,
            c.total_amount,
            c.rule_count,
        ),
        reverse=True,
    )
    total_cases = len(cases)
    top_cap = min(_VIOLATION_CASES_CAP, total_cases)
    case_rows = _violation_case_master_rows(cases[:top_cap])

    selected_case_id = _render_rule_case_master(
        "violation_cases",
        case_rows,
        key_suffix="violation_cases",
        hide_columns={"전표 수", "Band"},
        # Why: 안내 박스에 우선순위·검토 분량이 모두 정리돼 있으므로 캡션은 생략.
        caption_override="",
        show_header=False,
        # Why: 호출부에서 priority_band → composite_sort_score → ... 순으로 이미
        #      정렬했으므로 내부 (band, -amount) 재정렬을 끈다. 그렇지 않으면
        #      Top 200을 amount 순으로 다시 정렬해 priority 순서가 깨진다.
        preserve_order=True,
        # Why: 사례 요약 왼쪽에 위험도 순위(1~200)를 pinned 컬럼으로 노출.
        rank_column=True,
    )
    if not selected_case_id:
        st.caption("위 case 목록에서 한 줄을 선택하세요.")
        return

    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is None:
        st.caption("선택된 case의 상세를 찾지 못했습니다.")
        return
    _render_case_drilldown(drilldown, pr=pr)


_VIOLATION_PART_LABELS: dict[str, str] = {
    "company_code": "회사",
    "created_by": "작성자",
    "business_process": "프로세스",
    "period_month": "월",
    "fiscal_period": "기간",
    "counterparty": "거래처",
    "account_family": "계정",
    "document_type": "전표",
    "amount_band": "금액대",
    "user_persona": "권한",
    "period_window": "시점",
    "company_pair": "회사쌍",
    "near_period": "기말근접",
}

_VIOLATION_LABELED_THEMES = frozenset(
    {
        "logic_mismatch",
        "control_failure",
        "access_scope_review",
        "timing_anomaly",
        "duplicate_or_outflow",
        "intercompany_structure",
        "statistical_outlier",
        "data_integrity_failure",
    }
)


def _violation_natural_label(case) -> str:
    """검토 케이스 탭 전용 사례 요약 라벨.

    Why: case_natural_label 은 theme 매칭 시 자연어 문장을 만들지만, theme이 빈
         경우 case_key_parts.values() 를 단순 join 한다("R2R · 1 · 2022-01" 처럼
         모호함). 매칭 실패 시 한글 prefix("프로세스 R2R", "월 2022-01") 를 붙여
         감사인이 한눈에 키 의미를 알 수 있게 한다.
    """
    from src.export.phase1_case_label import case_natural_label

    theme = str(case.primary_theme or case.primary_topic or "").strip().lower()
    parts = case.case_key_parts or {}
    natural = case_natural_label(theme, parts).strip()
    if theme in _VIOLATION_LABELED_THEMES and natural:
        return natural

    chunks: list[str] = []
    for key, val in parts.items():
        if not val:
            continue
        label = _VIOLATION_PART_LABELS.get(key, key)
        chunks.append(f"{label} {val}")
    if chunks:
        return " · ".join(chunks[:4])
    return natural or case.case_key or case.case_id


def _violation_case_master_rows(cases) -> list[dict[str, Any]]:
    """case 객체 리스트를 _render_rule_case_master 입력 형식으로 변환.

    Why: _render_rule_case_master는 build_phase1_rule_cases 가 만든 dict 입력을
         기대한다. 검토 케이스 탭은 룰 필터 없이 phase1.cases 전체를 다루므로
         같은 키 구조(case_id/natural_label/priority_band/document_count/
         total_amount/why)로 dict 를 만든다.
    """
    rows: list[dict[str, Any]] = []
    for case in cases:
        why = str(case.risk_narrative or case.representative_explanation or "").strip()
        rows.append(
            {
                "case_id": case.case_id,
                "natural_label": _violation_natural_label(case),
                "priority_band": _case_display_priority_band(case),
                "priority_score": float(case.priority_score or 0.0),
                "document_count": int(case.document_count or 0),
                "total_amount": float(case.total_amount or 0.0),
                "why": why,
            }
        )
    return rows


def _render_statistics_tab(pr, summary: dict) -> None:
    """통계결과 탭 — PHASE1 결과 분포 6종.

    Why: 룰 위반 건수가 아니라 PHASE1 case 의 score/band/topic/시계열/엔티티
         분포를 한 화면에 압축. Topic 드릴다운은 검토 케이스 탭의 master/detail
         로 일원화했으므로 통계 탭은 분포 차트 전용.
    """
    case_result = getattr(pr, "phase1_case_result", None)
    cases = list(getattr(case_result, "cases", []) or []) if case_result else []

    if not cases:
        st.info("통계를 계산할 case 데이터가 없습니다.")
        return
    _render_phase1_summary_charts(pr, cases)


# ── PHASE1 결과 통계 차트 ─────────────────────────────────────────


@st.cache_resource(show_spinner=False)
def _account_name_lookup() -> dict[str, str]:
    """gl_account → 한국어 계정명 매핑 (config/chart_of_accounts.csv 캐시).

    Why: Top 10 계정 차트에 코드만 노출되면 감사인이 직관 파악이 어렵다.
         글로벌 COA CSV 를 한 번 읽어 dict 로 캐시한다.
    """
    import csv
    from pathlib import Path

    coa_path = Path(__file__).resolve().parent.parent / "config" / "chart_of_accounts.csv"
    if not coa_path.exists():
        return {}
    lookup: dict[str, str] = {}
    with open(coa_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("gl_account") or "").strip()
            name = (row.get("account_name_kr") or "").strip()
            if code and name:
                lookup[code] = name
    return lookup


def _render_phase1_summary_charts(pr, cases: list) -> None:
    """6종 통계 — Plotly 시각화.

    1) priority_score 히스토그램 + band 경계선 + 설명
    2) priority_band × topic heatmap (compact) | 3) Topic 평균 priority (2-col)
    4) 월별 검토 신호 전표 추이 (line)
    5) 요일 × 시간 히트맵 (심야·주말 점선 박스)
    6) 작성자 / 계정 Top 10 (계정은 한국어 명칭 동반)
    """
    from dashboard.components.charts._theme import (
        AXIS_STYLE,
        CASE_BAND_COLORS,
        COLOR_BORDER,
        COLOR_PRIMARY,
        COLOR_TEXT_MUTED,
        DEFAULT_LAYOUT,
        RISK_COLORS,
    )

    # 데이터 준비 (한 번 순회)
    scores: list[float] = []
    band_topic: dict[tuple[str, str], int] = {}
    topic_scores_sum: dict[str, float] = {}
    topic_scores_n: dict[str, int] = {}
    # Why: 외부 변경/기존 차트가 case별 룰 수 분포(rule_count_per_case)를 참조할 수
    #      있어 사전에 채워 둔다. 차트가 안 쓰면 무해, NameError 만 차단.
    rule_count_per_case: list[int] = []
    flat_docs: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()

    for case in cases:
        score = float(getattr(case, "priority_score", 0.0) or 0.0)
        band = _case_display_priority_band(case)
        topic = str(getattr(case, "primary_topic", "") or "")
        scores.append(score)
        if topic:
            band_topic[(band, topic)] = band_topic.get((band, topic), 0) + 1
            topic_scores_sum[topic] = topic_scores_sum.get(topic, 0.0) + score
            topic_scores_n[topic] = topic_scores_n.get(topic, 0) + 1

        rule_ids = {
            str(getattr(hit, "rule_id", "") or "")
            for hit in getattr(case, "raw_rule_hits", []) or []
        }
        rule_ids.discard("")
        rule_count_per_case.append(len(rule_ids))

        for doc in getattr(case, "documents", []) or []:
            doc_id = str(getattr(doc, "document_id", "") or "")
            if not doc_id or doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            flat_docs.append(
                {
                    "document_id": doc_id,
                    "posting_date": getattr(doc, "posting_date", None),
                    "created_by": getattr(doc, "created_by", None),
                    "gl_account": getattr(doc, "gl_account", None),
                }
            )

    docs_df = pd.DataFrame(flat_docs)

    # ── 1) 위험 우선순위 점수 분포 — 좌(설명 카드) · 우(차트) ─────
    section_1 = st.container(border=True)
    section_1.markdown("##### 위험 우선순위 점수 분포")
    # Why: 1:2 비율에서 마지막 bullet 끝 "사 용" 이 두 줄로 줄바꿈됨. 설명 칸 폭을
    #      살짝 넓혀(1:1.5) 한 줄에 들어오게.
    col_desc, col_chart = section_1.columns([1, 1.5])
    with col_desc:
        # Why: 우측 차트(height=240) 와 시각 균형을 맞추기 위해 동일 높이 컨테이너에
        #      회색 배경 카드. flex column + justify-center 로 상하 중앙 정렬.
        st.markdown(
            """
            <div style="
                background:#F8F9FA;
                border:1px solid #E5E7EB;
                border-radius:10px;
                padding:1.1rem 1.4rem;
                height:240px;
                display:flex;
                flex-direction:column;
                justify-content:center;
                box-shadow:0 1px 2px rgba(15,23,42,0.03);
            ">
                <ul style="
                    margin:0;
                    padding-left:1.1rem;
                    color:#374151;
                    font-size:0.92rem;
                    line-height:1.85;
                ">
                    <li>각 검토 케이스의 <b style="color:#111827;">위험 우선순위 점수(0~1)</b> 분포</li>
                    <li>룰 신호 강도 · 금액 · 통제 신호 합산으로 등급화</li>
                    <li>즉시검토(≥ 0.90) · 검토대상(≥ 0.75) · 참고후보(&lt; 0.75)</li>
                    <li>점수가 한 구간에 몰리면 그 경계를 검토 컷오프로 사용</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_chart:
        hist_fig = go.Figure(
            go.Histogram(
                x=scores,
                nbinsx=20,
                marker={"color": COLOR_PRIMARY, "line": {"color": "#FFFFFF", "width": 1}},
                hovertemplate="구간: %{x}<br>케이스 수: %{y}<extra></extra>",
            )
        )
        hist_fig.add_vline(
            x=0.75,
            line_dash="dot",
            line_color=CASE_BAND_COLORS["medium"],
            annotation_text="검토대상 ≥ 0.75",
            annotation_position="top",
            annotation_font={"size": 10, "color": CASE_BAND_COLORS["medium"]},
        )
        hist_fig.add_vline(
            x=0.90,
            line_dash="dot",
            line_color=CASE_BAND_COLORS["high"],
            annotation_text="즉시검토 ≥ 0.90",
            annotation_position="top",
            annotation_font={"size": 10, "color": CASE_BAND_COLORS["high"]},
        )
        hist_fig.update_layout(
            **DEFAULT_LAYOUT,
            height=240,
            xaxis_title="위험 우선순위 점수",
            yaxis_title="케이스 수",
        )
        hist_fig.update_xaxes(**AXIS_STYLE, range=[0.0, 1.0])
        hist_fig.update_yaxes(**AXIS_STYLE)
        st.plotly_chart(
            hist_fig,
            width="stretch",
            key="phase1_stats_priority_hist",
            config={"displayModeBar": False},
        )

    # ── 2) band × topic heatmap + 3) Topic 별 평균 priority (균형 잡힌 폭) ─
    # Why: heatmap 3 행이 너무 납작해서 셀이 길게 늘어남. 비율 1:1 로 두고 양쪽 height 도 320 으로 동일하게 키움.
    section_2 = st.container(border=True)
    col_heat, col_avg = section_2.columns([1, 1])
    topic_ids = [tid for tid in TOPIC_REGISTRY]
    topic_labels = [_TOPIC_SHORT_LABELS.get(tid, TOPIC_REGISTRY[tid].label) for tid in topic_ids]

    band_kor = {"high": "상", "medium": "중", "low": "하"}
    with col_heat:
        st.markdown("##### 위험등급 × 검토 영역 분포")
        band_order = ["high", "medium", "low"]
        z = [[band_topic.get((band, tid), 0) for tid in topic_ids] for band in band_order]
        text = [[f"{v:,}" if v else "" for v in row] for row in z]
        heat = go.Figure(
            go.Heatmap(
                z=z,
                x=topic_labels,
                y=[band_kor[b] for b in band_order],
                text=text,
                texttemplate="%{text}",
                textfont={"size": 12},
                colorscale="Purples",
                hovertemplate="등급: %{y}<br>영역: %{x}<br>케이스: %{z:,}<extra></extra>",
                colorbar={"title": "케이스", "thickness": 10, "len": 0.75},
            )
        )
        heat.update_layout(
            **{**DEFAULT_LAYOUT, "margin": {"l": 50, "r": 10, "t": 10, "b": 90}},
            height=320,
            xaxis_title="",
            yaxis_title="위험등급",
        )
        heat.update_xaxes(tickangle=-30, tickfont={"size": 10})
        heat.update_yaxes(tickfont={"size": 11})
        st.plotly_chart(
            heat,
            width="stretch",
            key="phase1_stats_band_topic_heat",
            config={"displayModeBar": False},
        )

    with col_avg:
        st.markdown("##### 검토 영역별 평균 위험 점수")
        avg_pairs = [
            (
                _TOPIC_SHORT_LABELS.get(tid, TOPIC_REGISTRY[tid].label),
                topic_scores_sum.get(tid, 0.0) / topic_scores_n[tid]
                if topic_scores_n.get(tid)
                else 0.0,
            )
            for tid in topic_ids
        ]
        avg_pairs.sort(key=lambda x: x[1])
        avg_labels, avg_values = zip(*avg_pairs, strict=False) if avg_pairs else ([], [])
        from dashboard.components.charts.comparison_charts import (
            _TICK_FONT_MONO,
            _left_align_labels,
        )

        aligned_avg_labels = _left_align_labels(list(avg_labels))
        avg_fig = go.Figure(
            go.Bar(
                x=list(avg_values),
                y=aligned_avg_labels,
                orientation="h",
                marker={"color": CASE_BAND_COLORS["high"]},
                text=[f"{v:.2f}" for v in avg_values],
                textposition="outside",
                hovertemplate="%{y}<br>평균 점수: %{x:.3f}<extra></extra>",
            )
        )
        # Why: 우측 여백이 너무 많이 남던 비율 문제 — x 축 범위를 최댓값 약간 위로 타이트하게 조정.
        max_v = max(list(avg_values) + [0.0])
        avg_fig.update_layout(
            **{**DEFAULT_LAYOUT, "margin": {"l": 100, "r": 40, "t": 10, "b": 40}},
            height=320,
            xaxis_title="평균 위험 점수",
            yaxis_title="",
        )
        avg_fig.update_xaxes(
            **AXIS_STYLE, range=[0, min(1.0, max_v * 1.25 + 0.05)], tickfont={"size": 10}
        )
        avg_fig.update_yaxes(automargin=True, tickfont=_TICK_FONT_MONO)
        st.plotly_chart(
            avg_fig,
            width="stretch",
            key="phase1_stats_topic_avg",
            config={"displayModeBar": False},
        )

    # ── 4) 월별 검토 신호 전표 추이 + 5) 요일 × 시간 히트맵 ─────────
    dt = (
        pd.to_datetime(docs_df["posting_date"], errors="coerce").dropna()
        if not docs_df.empty and "posting_date" in docs_df.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    if not dt.empty:
        section_3 = st.container(border=True)
        section_3.markdown("##### 월별 검토 신호 전표 추이")
        section_3.caption(
            "검토 신호 전표(중복 제거 기준)의 회계 월별 분포. "
            "분기말(3·6·9·12월)에 결산조정·이익조정이 집중되는지 확인."
        )
        monthly = dt.dt.month.value_counts().reindex(range(1, 13), fill_value=0).sort_index()
        line_fig = go.Figure(
            go.Scatter(
                x=list(monthly.index),
                y=list(monthly.values),
                mode="lines+markers+text",
                line={"color": COLOR_PRIMARY, "width": 2.5, "shape": "spline"},
                marker={"size": 8, "color": COLOR_PRIMARY},
                text=[f"{v:,}" for v in monthly.values],
                textposition="top center",
                textfont={"size": 10, "color": COLOR_TEXT_MUTED},
                hovertemplate="%{x}월: %{y:,}건<extra></extra>",
            )
        )
        for q in (3, 6, 9, 12):
            line_fig.add_vline(x=q, line_dash="dot", line_color=COLOR_BORDER, opacity=0.6)
        line_fig.update_layout(
            **DEFAULT_LAYOUT, height=260, xaxis_title="회계 월", yaxis_title="검토 신호 전표 건수"
        )
        line_fig.update_xaxes(
            **AXIS_STYLE,
            tickmode="array",
            tickvals=list(range(1, 13)),
            ticktext=[f"{m}월" for m in range(1, 13)],
        )
        line_fig.update_yaxes(**AXIS_STYLE, rangemode="tozero")
        section_3.plotly_chart(
            line_fig,
            width="stretch",
            key="phase1_stats_monthly_trend",
            config={"displayModeBar": False},
        )

        # ── 5) 요일별 분포 (시간 정보 있으면 요일×시간 히트맵으로 자동 전환) ─
        section_4 = st.container(border=True)
        weekday = dt.dt.dayofweek
        hour = dt.dt.hour
        day_labels = ["월", "화", "수", "목", "금", "토", "일"]

        if hour.nunique() > 1:
            section_4.markdown("##### 요일·시간대 분포")
            section_4.caption(
                "검토 신호 전표의 기표 시점. 빨강 점선=심야(0~6·22~23시), 주황 점선=주말."
            )
            temp = pd.DataFrame({"weekday": weekday.values, "hour": hour.values})
            grouped = temp.groupby(["weekday", "hour"]).size().reset_index(name="cnt")
            pivot = pd.DataFrame(0, index=range(7), columns=range(24))
            for _, row in grouped.iterrows():
                pivot.at[int(row["weekday"]), int(row["hour"])] = int(row["cnt"])
            heat_time = go.Figure(
                go.Heatmap(
                    z=pivot.values,
                    x=list(range(24)),
                    y=day_labels,
                    colorscale="YlOrRd",
                    hovertemplate="시간: %{x}시<br>요일: %{y}<br>건수: %{z}<extra></extra>",
                    colorbar={"title": "건수", "thickness": 10, "len": 0.8},
                )
            )
            for x0, x1 in [(-0.5, 6.5), (21.5, 23.5)]:
                heat_time.add_shape(
                    type="rect",
                    x0=x0,
                    x1=x1,
                    y0=-0.5,
                    y1=6.5,
                    line={"dash": "dash", "color": "#DC2626", "width": 2},
                )
            heat_time.add_shape(
                type="rect",
                x0=-0.5,
                x1=23.5,
                y0=4.5,
                y1=6.5,
                line={"dash": "dash", "color": "#D97706", "width": 2},
            )
            heat_time.update_layout(
                **{**DEFAULT_LAYOUT, "margin": {"l": 30, "r": 10, "t": 10, "b": 40}},
                height=240,
                xaxis_title="시간",
                yaxis_title="요일",
            )
            section_4.plotly_chart(
                heat_time,
                width="stretch",
                key="phase1_stats_weekday_hour_heat",
                config={"displayModeBar": False},
            )
        else:
            # Why: posting_date 에 시간 정보가 없으면(전표 모두 00:00) 24칸 가로 히트맵은
            #      대부분 빈칸으로 보여 정보 가치가 없다. 요일 단위 콤보 차트로 전환.
            #      막대=요일별 전체 거래 건수, 라인=위반 전표 비율(%) — 검토 신호의 절대량과
            #      상대 비율을 한 화면에 비교해야 "토·일은 전체가 적지만 비율이 높다"
            #      같은 인사이트를 즉시 인지할 수 있다.
            section_4.markdown("##### 요일별 전체 거래 대비 검토 신호 비율")
            section_4.caption(
                "막대=요일별 전체 전표 건수 · 선=검토 신호 전표 비율(%). 통제 약한 토·일은 "
                "건수가 적어도 비율이 솟아오르면 즉시 검토 신호."
            )
            # 전체 거래 — pr.data 의 distinct document_id × posting_date 기준 요일 분포
            total_weekday = _total_weekday_distribution(pr)
            viol_weekday = (
                pd.Series(weekday.values)
                .value_counts()
                .reindex(range(7), fill_value=0)
                .sort_index()
            )
            # 비율(%) — 분모 0 이면 0
            ratio = []
            for i in range(7):
                total_v = int(total_weekday.get(i, 0))
                viol_v = int(viol_weekday.get(i, 0))
                ratio.append((viol_v / total_v * 100) if total_v else 0.0)

            from plotly.subplots import make_subplots

            combo = make_subplots(specs=[[{"secondary_y": True}]])
            # Why: 색상 톤을 위 차트들과 일치 — 막대는 모집단(CASE low slate),
            #      선은 위험 신호 (RISK_COLORS["High"] 채도 낮춘 red).
            #      라벨 겹침 해소: 막대 위 숫자는 hover 로만 노출하고, 검토 신호 비율
            #      라인 위의 % 텍스트만 시각 노출(요일 차트의 핵심 인사이트).
            combo.add_trace(
                go.Bar(
                    x=day_labels,
                    y=[int(total_weekday.get(i, 0)) for i in range(7)],
                    name="전체 전표",
                    # Why: case low(slate-400)는 톤이 무거워 막대가 라인을 압도한다.
                    #      RISK_COLORS["Low"](sky-9 desaturated) 계열의 더 연한 sky 톤으로
                    #      낮춰 도넛/위반 라인과 동일한 cool 팔레트로 조화.
                    marker={"color": "#A5C8E6", "line": {"width": 0}},
                    hovertemplate="%{x}요일 전체: %{y:,}건<extra></extra>",
                ),
                secondary_y=False,
            )
            risk_color = RISK_COLORS["High"]
            combo.add_trace(
                go.Scatter(
                    x=day_labels,
                    y=ratio,
                    name="검토 신호 비율",
                    mode="lines+markers+text",
                    line={"color": risk_color, "width": 2.5},
                    marker={"size": 8, "color": risk_color},
                    text=[f"{v:.1f}%" for v in ratio],
                    textposition="top center",
                    textfont={"size": 10, "color": risk_color},
                    cliponaxis=False,
                    hovertemplate="%{x}요일 검토 신호 비율: %{y:.2f}%<extra></extra>",
                ),
                secondary_y=True,
            )
            combo.update_layout(
                **DEFAULT_LAYOUT,
                height=320,
                xaxis_title="요일",
                legend={
                    "orientation": "h",
                    "yanchor": "bottom",
                    "y": 1.02,
                    "xanchor": "right",
                    "x": 1,
                },
            )
            combo.update_xaxes(**AXIS_STYLE)
            combo.update_yaxes(
                title_text="전체 전표 건수", rangemode="tozero", secondary_y=False, **AXIS_STYLE
            )
            # Why: 라인 위 % 텍스트가 상단에 잘리지 않도록 secondary y축 max 에
            #      약 20% 여유. min=0 고정.
            max_ratio = max(ratio) if ratio else 0.0
            combo.update_yaxes(
                title_text="검토 신호 비율 (%)",
                range=[0, max(max_ratio * 1.2, 1.0)],
                secondary_y=True,
                showgrid=False,
            )
            section_4.plotly_chart(
                combo,
                width="stretch",
                key="phase1_stats_weekday_combo",
                config={"displayModeBar": False},
            )

    # ── 6) 작성자 / 계정과목 상위 10 (계정은 한국어 명칭 동반) ─────
    if not docs_df.empty:
        section_6 = st.container(border=True)
        col_u, col_g = section_6.columns(2)
        with col_u:
            st.markdown("##### 작성자별 검토 신호 전표 상위 10")
            _render_topn_hbar(
                docs_df.get("created_by"),
                key="phase1_stats_user_topn",
                color=CASE_BAND_COLORS["high"],
                empty_msg="작성자 정보가 없습니다.",
            )
        with col_g:
            st.markdown("##### 계정과목별 검토 신호 전표 상위 10")
            _render_topn_hbar(
                docs_df.get("gl_account"),
                key="phase1_stats_account_topn",
                color=CASE_BAND_COLORS["medium"],
                empty_msg="계정과목 정보가 없습니다.",
                label_map=_account_name_lookup(),
            )


def _total_weekday_distribution(pr) -> pd.Series:
    """pr.data 에서 distinct document_id 기준 요일별 분포 산출.

    Why: 위반 전표(flat_docs) 와 같은 단위(전표=문서 1건)로 분모를 맞춰야 비율이
         정확. line 단위 합계는 분개 라인 수가 많은 전표가 과대평가되어 비율 왜곡.
    """
    data = getattr(pr, "data", None)
    if data is None or not hasattr(data, "columns"):
        return pd.Series([0] * 7, index=range(7))
    if "posting_date" not in data.columns:
        return pd.Series([0] * 7, index=range(7))
    if "document_id" in data.columns:
        sub = data[["document_id", "posting_date"]].drop_duplicates(subset=["document_id"])
        dates = pd.to_datetime(sub["posting_date"], errors="coerce").dropna()
    else:
        dates = pd.to_datetime(data["posting_date"], errors="coerce").dropna()
    if dates.empty:
        return pd.Series([0] * 7, index=range(7))
    return dates.dt.dayofweek.value_counts().reindex(range(7), fill_value=0).sort_index()


def _render_topn_hbar(
    series: pd.Series | None,
    *,
    key: str,
    color: str,
    empty_msg: str,
    top_n: int = 10,
    label_map: dict[str, str] | None = None,
) -> None:
    """Top N horizontal bar — 위반 전표 distinct 수 기준.

    label_map: {code: 표시명} 매핑이 있으면 "code · 표시명" 으로 y 축 라벨 보강.
    """
    from dashboard.components.charts._theme import AXIS_STYLE, DEFAULT_LAYOUT
    from dashboard.components.charts.comparison_charts import (
        _TICK_FONT_MONO,
        _left_align_labels,
    )

    if series is None or series.dropna().empty:
        st.caption(empty_msg)
        return
    counts = series.dropna().astype(str).value_counts().head(top_n).iloc[::-1]
    if label_map:
        y_labels = [
            f"{code} · {label_map[code]}" if code in label_map else code for code in counts.index
        ]
    else:
        y_labels = list(counts.index)
    aligned_labels = _left_align_labels(y_labels)
    fig = go.Figure(
        go.Bar(
            x=counts.values,
            y=aligned_labels,
            orientation="h",
            marker={"color": color},
            text=[f"{v:,}" for v in counts.values],
            textposition="outside",
            hovertemplate="%{y}: %{x:,}건<extra></extra>",
        )
    )
    fig.update_layout(
        **DEFAULT_LAYOUT,
        height=max(260, 32 * len(counts) + 80),
        xaxis_title="검토 신호 전표 건수",
        yaxis_title="",
    )
    fig.update_xaxes(**AXIS_STYLE, rangemode="tozero")
    fig.update_yaxes(automargin=True, tickfont=_TICK_FONT_MONO)
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})


def _render_ai_conclusion(pr, summary: dict) -> None:
    gate = build_phase1_data_quality_gate(pr)
    audit = build_phase1_audit_risk_by_queue(pr, top_n_per_queue=1)
    review = build_phase1_review_candidate_summary(pr)
    phase1 = resolve_phase1_case_result(pr)
    high_count = 0
    medium_count = 0
    if phase1 is not None:
        high_count = sum(1 for case in phase1.cases if _case_display_priority_band(case) == "high")
        medium_count = sum(
            1 for case in phase1.cases if _case_display_priority_band(case) == "medium"
        )

    st.markdown("#### 요약 판단")
    st.write(
        f"PHASE1은 총 {summary['case_count']:,}개 case를 생성했고, "
        f"즉시검토 {high_count:,}개, 검토대상 {medium_count:,}개로 분류했습니다."
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
        st.dataframe(pd.DataFrame(queue_rows), width="stretch", hide_index=True)

    st.divider()
    if st.button(
        "Phase 2 탭으로 이동",
        type="primary",
        key="ai_conclusion_goto_phase2",
    ):
        # KEY_TOP_LEVEL_NAV 는 widget key — _consume_pending_page 가 다음 run
        # widget 렌더 전에 KEY_PENDING_RESULT_TAB 를 옮긴다.
        st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE2
        st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE2
        st.rerun()


def _render_case_table(queue_df: pd.DataFrame) -> None:
    if {"priority_score", "priority_band"}.issubset(queue_df.columns):
        queue_df = queue_df.copy()
        queue_df["priority_band"] = queue_df.apply(
            lambda row: _display_priority_band_from_score(
                row.get("priority_score"),
                row.get("priority_band", "low"),
            ),
            axis=1,
        )
    display_df = queue_df.rename(
        columns={
            "topic_label": "Topic",
            "topic_score": "Topic Score",
            "primary_topic_label": "Primary Topic",
            "case_type": "Case Type",
            "main_reason": "Main Reason",
            "case_key": "Case Key",
            "priority_band": "Priority band",
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
        "Priority band",
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
    st.dataframe(display_df[available], width="stretch", hide_index=True)


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
        help=(
            "옵션 포맷: topic | case priority_band | case_key. "
            "가운데 등급은 즉시검토/검토대상/참고후보 "
            "(priority_score 기준, 행 risk_level 과 다른 축)."
        ),
    )
    selected_case_id = case_options[selected_case_label]
    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is not None:
        _render_case_drilldown(drilldown, pr=pr)


def _render_case_drilldown(drilldown: dict, *, pr=None) -> None:
    # Why: case 메타 메트릭/영문 캡션/signal section expander 를 모두 제거하고
    #      Case 설명 + 문서 master(AgGrid) + 선택된 문서의 원장 라인 표 만 남긴다.
    #      위반 document 행을 클릭하면 그 밑에 raw 분개 라인이 즉시 펼쳐진다.
    case = drilldown["case"]
    narrative = case["risk_narrative"] or case["representative_explanation"]
    st.markdown(f"**Case 설명**  \n{narrative}")

    documents = drilldown.get("documents") or []
    if not documents:
        return

    selected_doc = _render_case_drilldown_document_master(
        documents, key_suffix=str(case.get("case_id", ""))
    )
    if not selected_doc or pr is None:
        return

    raw_lines = _case_document_raw_lines(pr, selected_doc)
    if not raw_lines:
        st.caption("선택된 전표의 원장 라인을 찾지 못했습니다.")
        return
    _render_raw_lines_table("", raw_lines, key_suffix=f"case_drilldown_{case.get('case_id', '')}")


_CASE_DRILLDOWN_DOC_COLUMNS = (
    "document_id",
    "posting_date",
    "created_by",
    "approved_by",
    "gl_account",
    "debit_amount",
    "credit_amount",
    "evidence_amount",
    "matched_rules",
)


def _serialize_cell(value):
    """AgGrid 직렬화용 — list/tuple/dict 셀을 사람이 읽을 수 있는 문자열로 변환.

    Why: drilldown documents 에 matched_rules 같은 list 컬럼이 그대로 들어가면
         AgGrid 가 "[object Object]" 로 표시한다. join 으로 평탄화한다.
    """
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items() if v not in (None, ""))
    return value


def _matched_rules_to_kr(value) -> str:
    """matched_rules 셀(L3-02 등 rule_id 목록)을 짧은 한국어 라벨로 변환.

    Why: case 드릴다운 표에 "L3-02, L3-04" 처럼 코드만 노출되면 감사인이 즉시
         의미를 파악할 수 없다. canonical 정규화 후 `_RULE_NAMES_KR` 한국어 라벨로
         치환하고, 매핑이 없으면 원본 코드를 그대로 둔다.
    """
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    elif isinstance(value, str) and value:
        items = [token.strip() for token in value.split(",") if token.strip()]
    elif value in (None, ""):
        return ""
    else:
        items = [value]

    labels: list[str] = []
    seen: set[str] = set()
    for item in items:
        raw = str(item).strip()
        if not raw:
            continue
        canonical = _canonicalize_metadata_rule_id(raw)
        label = _RULE_NAMES_KR.get(canonical) or _RULE_NAMES_KR.get(raw) or raw
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return ", ".join(labels)


def _render_case_drilldown_document_master(
    documents: list[dict], *, key_suffix: str = ""
) -> str | None:
    """Case drilldown 문서 master — 행 선택 시 document_id 반환.

    Why: 단순 st.dataframe 은 행 클릭이 안 돼 분개 라인까지 들어가는 흐름이
         끊긴다. AgGrid 단일 선택으로 바꿔 클릭 즉시 raw 분개가 펼쳐지게 한다.
         핵심 컬럼만 화이트리스트로 노출하고 list/dict 셀은 문자열로 직렬화.
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    docs_df = pd.DataFrame(documents)
    if docs_df.empty or "document_id" not in docs_df.columns:
        st.dataframe(docs_df, width="stretch", hide_index=True)
        return None

    # 의미있는 컬럼만 화이트리스트로 노출 (matched_rules 등 list 메타는 직렬화).
    available_cols = [col for col in _CASE_DRILLDOWN_DOC_COLUMNS if col in docs_df.columns]
    if available_cols:
        docs_df = docs_df[available_cols].copy()
    # Why: matched_rules 는 코드(L3-02) 대신 한국어 짧은 라벨로 보여 감사인이 즉시 읽도록.
    if "matched_rules" in docs_df.columns:
        docs_df["matched_rules"] = docs_df["matched_rules"].map(_matched_rules_to_kr)
    for col in docs_df.columns:
        if docs_df[col].dtype == object:
            docs_df[col] = docs_df[col].map(_serialize_cell)

    gb = GridOptionsBuilder.from_dataframe(docs_df)
    gb.configure_default_column(resizable=True, filter=True, sortable=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False, pre_selected_rows=[0])
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
    gb.configure_grid_options(
        rowSelection="single",
        suppressRowClickSelection=False,
        suppressCellFocus=True,
    )
    if "document_id" in docs_df.columns:
        gb.configure_column("document_id", minWidth=170, maxWidth=220, tooltipField="document_id")
    if "posting_date" in docs_df.columns:
        gb.configure_column("posting_date", minWidth=110, maxWidth=130)
    if "created_by" in docs_df.columns:
        gb.configure_column("created_by", minWidth=110, maxWidth=140)
    if "approved_by" in docs_df.columns:
        gb.configure_column("approved_by", minWidth=110, maxWidth=140)
    if "gl_account" in docs_df.columns:
        gb.configure_column("gl_account", minWidth=90, maxWidth=120)
    for amount_col in ("debit_amount", "credit_amount", "evidence_amount"):
        if amount_col in docs_df.columns:
            gb.configure_column(amount_col, minWidth=100, maxWidth=130)
    if "matched_rules" in docs_df.columns:
        gb.configure_column(
            "matched_rules",
            minWidth=420,
            flex=3,
            wrapText=True,
            autoHeight=True,
            tooltipField="matched_rules",
        )

    safe_suffix = (key_suffix or "default").replace(" ", "_")
    grid_key = f"phase1_case_drilldown_docs_{safe_suffix}"
    response = AgGrid(
        docs_df,
        gridOptions=gb.build(),
        height=min(320, (len(docs_df) + 1) * 36),
        theme="streamlit",
        key=grid_key,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        reload_data=False,
        fit_columns_on_grid_load=True,
    )

    state_key = f"_phase1_case_drilldown_doc_selection_{grid_key}"
    selected_rows = response.get("selected_rows", [])
    if hasattr(selected_rows, "to_dict"):
        selected_rows = selected_rows.to_dict("records")
    selected_doc = None
    if selected_rows:
        selected_doc = str(selected_rows[0].get("document_id") or "")
    if selected_doc:
        st.session_state[state_key] = selected_doc
    else:
        selected_doc = st.session_state.get(state_key)
        if not selected_doc and not docs_df.empty:
            selected_doc = str(docs_df.iloc[0].get("document_id") or "")
    return selected_doc or None


def _case_document_raw_lines(pr, document_id: str) -> list[dict]:
    """선택된 document_id 의 원장 라인을 pr.data / featured_data 에서 조회.

    Why: build_phase1_rule_document_detail 은 rule_id 컨텍스트가 필요한데, case
         drilldown 에서는 case 안에 여러 룰이 섞일 수 있어 단일 rule_id 가 없다.
         원본 데이터에서 document_id 로 단순 필터해 라인 목록을 만든다.
    """
    df = getattr(pr, "featured_data", None)
    if df is None or getattr(df, "empty", True):
        df = getattr(pr, "data", None)
    if df is None or df.empty or "document_id" not in df.columns:
        return []
    subset = df[df["document_id"].astype(str) == str(document_id)]
    if subset.empty:
        return []
    return subset.to_dict("records")


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
            st.dataframe(section_df[available], width="stretch", hide_index=True)

    with st.expander("All raw rule hits", expanded=False):
        raw_df = pd.DataFrame(drilldown["raw_rule_hits"])
        st.dataframe(raw_df, width="stretch", hide_index=True)


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


def _case_band_distribution(pr) -> pd.DataFrame:
    """Case priority_band distribution for the overview donut."""

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return pd.DataFrame(columns=["band", "label", "count", "ratio"])

    levels = [("high", "즉시검토"), ("medium", "검토대상"), ("low", "참고후보")]
    counts = {band: 0 for band, _label in levels}
    for case in phase1.cases:
        band = _case_display_priority_band(case)
        if band not in counts:
            band = "low"
        counts[band] += 1

    total = sum(counts.values())
    if total == 0:
        return pd.DataFrame(columns=["band", "label", "count", "ratio"])

    return pd.DataFrame(
        {
            "band": [band for band, _label in levels],
            "label": [label for _band, label in levels],
            "count": [counts[band] for band, _label in levels],
            "ratio": [f"{counts[band] / total:.1%}" for band, _label in levels],
        }
    )


def _doc_band_distribution(pr, data: pd.DataFrame) -> pd.DataFrame:
    """전표(document) 단위 priority_band 분포.

    Why: 같은 전표가 여러 case 에 등장하면 가장 높은 band 하나에만 귀속한다
         (즉시검토 > 검토대상 > 참고후보). 분모는 전체 GL 전표 모집단으로 두어
         '신호 없음' 비율까지 4 분할로 노출, '모집단 대비 검토 노출률' 의미를
         살린다.
    """
    levels = [
        ("high", "즉시검토"),
        ("medium", "검토대상"),
        ("low", "참고후보"),
        ("none", "신호 없음"),
    ]

    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return pd.DataFrame(columns=["band", "label", "count", "ratio"])

    band_rank = {"high": 3, "medium": 2, "low": 1}
    doc_max_band: dict[str, str] = {}
    for case in phase1.cases:
        band = _case_display_priority_band(case)
        if band not in band_rank:
            band = "low"
        for doc in case.documents:
            doc_id = str(doc.document_id)
            current = doc_max_band.get(doc_id)
            if current is None or band_rank[band] > band_rank[current]:
                doc_max_band[doc_id] = band

    counts = {band: 0 for band, _label in levels}
    for band in doc_max_band.values():
        counts[band] += 1

    if "document_id" in data.columns:
        total_docs = int(data["document_id"].nunique())
    else:
        total_docs = int(len(data))
    signal_docs = counts["high"] + counts["medium"] + counts["low"]
    counts["none"] = max(total_docs - signal_docs, 0)

    if total_docs == 0:
        return pd.DataFrame(columns=["band", "label", "count", "ratio"])

    return pd.DataFrame(
        {
            "band": [band for band, _label in levels],
            "label": [label for _band, label in levels],
            "count": [counts[band] for band, _label in levels],
            "ratio": [f"{counts[band] / total_docs:.1%}" for band, _label in levels],
        }
    )


def _direct_risk_case_count(pr) -> int:
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return 0
    return sum(1 for case in phase1.cases if _case_display_priority_band(case) == "high")


def _category_case_rows(pr, category: str) -> list[dict[str, Any]]:
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    dq_case_ids = _data_quality_case_ids(pr)
    cases = [case for case in phase1.cases if _case_signal_category(case, dq_case_ids) == category]
    # §9.3 composite_sort_score 우선 정렬. priority_score 는 보조 tiebreak.
    cases.sort(
        key=lambda case: (
            _case_display_priority_band_rank(case),
            case.composite_sort_score,
            case.priority_score,
            case.triage_rank_score,
            case.total_amount,
            case.rule_count,
            -case.document_count,
        ),
        reverse=True,
    )
    return [_display_case_row(case, phase1) for case in cases]


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

    if _case_display_priority_band(case) == "low":
        return True
    if case.primary_queue not in {"timing_close", "control_approval"}:
        return False
    context_count = signal_counts["review_context"] + signal_counts["macro_finding"]
    return has_review_signal and context_count >= signal_counts["direct_risk"]


def _priority_band_rank(band: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(band).lower(), 0)


def _render_risk_pie(doc_band_df: pd.DataFrame, topics: list[dict[str, Any]]) -> None:
    """좌우 독립 컬럼 — shadcn zinc 팔레트, flat 미니멀.

    좌: 전표 priority_band 즉시검토/검토대상/참고후보/신호없음 도넛
    우: Topic별 케이스 수(중복 포함)
    Why: 좌측 도넛을 case 단위(중복 없음)에서 전표 max-band 단위로 전환해
         전체 GL 전표 모집단 대비 검토 노출률을 직관적으로 보이게 한다. 우측은
         Top1 Topic만 다크 오렌지로 강조해 집중도 확보.
    """

    rows = [
        {
            "band": str(row.get("band") or "").lower(),
            "label": str(row.get("label") or "").title(),
            "count": int(row.get("count", 0) or 0),
        }
        for row in doc_band_df.to_dict("records")
    ]
    rows = [row for row in rows if row["count"] > 0]
    doc_total = sum(row["count"] for row in rows)

    if doc_total == 0:
        st.info("표시할 전표 데이터가 없습니다.")
        return

    # shadcn 팔레트
    color_text = "#18181B"  # zinc-900
    color_muted = "#71717A"  # zinc-500
    color_accent = "#C2410C"  # orange-700 (Top1 강조)
    color_neutral = "#475569"  # slate-600 (나머지 차분)
    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    # Why: 전체 개요(tab_overview)의 도넛 카드와 동일 규격 — 카드 380, 좌:우 1:1.5.
    chart_card_height = 380
    left_col, right_col = st.columns([1, 1.5], gap="small")

    # ── 좌측: 전체 분포 도넛 ────────────────────────────────
    # Why: 단일 hue 그라데이션으로 segment 우선순위(즉시검토 > 검토대상
    #      > 참고후보 > 신호없음)를 명도로만 표현. 채도를 낮춘 slate 모노톤으로
    #      zinc-900/zinc-500 텍스트와 동일 계열을 유지해 기존 대시보드와 통일.
    risk_gradient = {
        "high": "#1E293B",  # slate-800 — 가장 짙음
        "medium": "#475569",  # slate-600
        "low": "#94A3B8",  # slate-400
        "none": "#E2E8F0",  # slate-200 — 가장 옅음
    }
    with left_col, st.container(border=True, height=chart_card_height):
        doc_axis_tooltip_html = html.escape(
            "축: 전표(document) priority_band. 동일 전표가 여러 case 에 등장하면 "
            "가장 높은 band 로 단일 카운트(즉시검토 > 검토대상 > 참고후보). "
            "분모는 전체 GL 전표 모집단."
        )
        st.markdown(
            f"<div style='font-family:{typography};'>"
            f"<div style='color:{color_text}; font-size:0.875rem; "
            f"font-weight:700; letter-spacing:-0.01em;' "
            f"title='{doc_axis_tooltip_html}'>전체 분포</div>"
            f"<div style='color:{color_muted}; font-size:0.72rem; "
            f"margin-top:2px; letter-spacing:0.01em;'>총 {doc_total:,} 전표</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        labels = [row["label"] for row in rows]
        values = [row["count"] for row in rows]
        colors = [risk_gradient.get(row["band"], "#E2E8F0") for row in rows]
        customdata = [[f"전표 priority_{row['band']} {row['count']:,}건"] for row in rows]

        fig_donut = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                sort=False,
                direction="clockwise",
                rotation=90,
                marker={
                    "colors": colors,
                    "line": {"color": "#FFFFFF", "width": 2},
                },
                textinfo="label+percent",
                textposition="outside",
                textfont={"color": color_text, "size": 11, "family": typography},
                customdata=customdata,
                hovertemplate=(
                    "%{label}: %{value:,}건 (%{percent})<br>%{customdata[0]}<extra></extra>"
                ),
                showlegend=False,
                # Why: outside 라벨이 잘리지 않도록 도넛 영역을 안쪽으로 압축.
                #      전체 개요(tab_overview)의 _render_document_type_donut 와 동일.
                domain={"x": [0.12, 0.88], "y": [0.05, 0.95]},
                automargin=True,
            )
        )
        fig_donut.update_layout(
            height=280,
            margin={"l": 0, "r": 0, "t": 4, "b": 4},
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font={"family": typography},
        )
        st.plotly_chart(
            fig_donut,
            width="stretch",
            config={"displayModeBar": False},
            key="phase1_risk_donut",
        )
        st.markdown(
            f"<div style='color:{color_muted}; font-size:0.75rem; "
            f"text-align:center; padding:0 0.75rem 0.5rem; "
            f"font-family:{typography};'>"
            "생성 Case 내 전표의 갯수 분포"
            "</div>",
            unsafe_allow_html=True,
        )

    # ── 우측: Topic별 케이스 수(중복 포함) ─────────────────
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
            f"font-weight:600;'>Topic별 케이스 수(중복 포함)</div>"
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
                customdata=[[row["high_count"], row["topic_id"]] for row in topic_rows],
                hovertemplate=(
                    "%{y}<br>case %{x:,}건 · "
                    "%{customdata[1]} topic high %{customdata[0]:,}건"
                    "<extra></extra>"
                ),
                showlegend=False,
            )
        )
        fig_bar.update_layout(
            height=300,
            margin={"l": 6, "r": 120, "t": 4, "b": 4},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            bargap=0.42,
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
            width="stretch",
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
    "L1-06": "직무 분리(SoD) 충돌",
    "L1-07": "승인 절차 누락",
    "L1-08": "회계기간 오류",
    "L1-09": "승인일 누락",
    "L2-01": "승인 한도 직전 분개",
    "L2-02": "중복 지급",
    "L2-03": "중복 분개",
    "L2-04": "비용 자산화 검토",
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
    "L4-02": "벤포드 편차",
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
            or _case_display_priority_band(case) == "low"
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

    Why: KEY_TOP_LEVEL_NAV 는 widget key 라 인스턴스화 후 직접 쓰지 못한다.
         KEY_PENDING_RESULT_TAB 로 다음 run 의 _consume_pending_page 에 위임.
    """
    from dashboard.components.analysis_runner import run_phase_analysis

    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1

    with st.spinner("Phase 1 룰 기반 탐지 실행 중... 약 5분 정도 소요됩니다."):
        try:
            run_phase_analysis(phase="phase1")
        except Exception as e:
            st.error(f"Phase 1 실행 실패: {e}")
            return
    st.session_state[KEY_ACTIVE_RESULT_TAB] = PAGE_PHASE1
    st.session_state[KEY_PENDING_RESULT_TAB] = PAGE_PHASE1
    st.rerun()
