from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.detection.constants import RULE_CODES
from src.export.phase1_case_view import (
    _case_row,
    _case_signal_counts,
    build_phase1_audit_risk_by_queue,
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    build_phase1_data_quality_gate,
    build_phase1_review_candidate_summary,
    resolve_phase1_case_result,
    summarize_phase1_case_result,
)

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
    st.caption(
        "결과는 데이터정합성, Audit Risk, 추가검토사항으로 분리해서 보고 "
        "전체데이터 탭에서 원본 전표까지 확인합니다."
    )

    if phase1_result is None:
        st.info("아직 Phase 1 분석 결과가 없습니다.")
        _render_prep_summary(prep_result)
        if st.button("Phase 1 분석 시작", type="primary", key="run_phase1"):
            from dashboard.components.analysis_runner import run_phase_analysis

            with st.spinner("Phase 1 분석 중..."):
                run_phase_analysis(phase="phase1")
            st.rerun()
        return

    summary = summarize_phase1_case_result(phase1_result)
    if not summary["available"]:
        st.warning("PHASE1 case 결과를 불러오지 못했습니다.")
        return

    with st.container(key="phase1_section_nav_wrap"):
        section = st.radio(
            "Phase1 결과 섹션",
            [
                "전체데이터",
                "데이터정합성",
                "우선 위험신호",
                "저우선 위험신호",
                "맥락 검토대상",
                "AI결론",
            ],
            horizontal=True,
            key="phase1_section_nav",
            label_visibility="collapsed",
        )

    if section == "전체데이터":
        _render_overview(phase1_result, summary)
    elif section == "데이터정합성":
        _render_data_quality_gate(phase1_result)
    elif section == "우선 위험신호":
        _render_priority_risk_queue(phase1_result)
    elif section == "저우선 위험신호":
        _render_low_priority_risk_queue(phase1_result)
    elif section == "맥락 검토대상":
        _render_context_review_candidates(phase1_result)
    elif section == "AI결론":
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
    elapsed_text: str,
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
    priority_audit_delta_html = (
        "<div style='color:#9CA3AF; font-size:0.72rem; margin-top:3px;'>"
        "High/Medium + 직접 위험</div>"
        if direct_risk_case_count
        else ""
    )

    block_style = (
        "text-align:center; flex:1; padding:0 1rem; "
        "border-right:1px solid #E5E7EB;"
    )
    last_block_style = "text-align:center; flex:1; padding:0 1rem;"
    label_style = (
        "color:#6B7280; font-size:0.78rem; margin-bottom:6px; "
        "font-weight:500; letter-spacing:0.01em;"
    )
    value_base = (
        "font-size:1.7rem; font-weight:700; letter-spacing:-0.02em; "
        "line-height:1.2;"
    )
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
        <div style="{label_style}">우선 위험신호</div>
        <div style="color:#EA580C; {value_base}">
            {direct_risk_case_count:,} <span style="{unit_style}">건</span>
        </div>
        {priority_audit_delta_html}
    </div>
    <div style="{last_block_style}">
        <div style="{label_style}">분석 소요시간</div>
        <div style="color:#111827; {value_base}">
            {elapsed_text}
        </div>
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

    st.markdown("#### 1. PHASE 1 실행 요약")
    elapsed_text = _format_elapsed(getattr(pr, "elapsed", None))
    _render_phase1_summary_ribbon(
        row_count=row_count,
        case_count=case_count,
        case_ratio=case_ratio,
        direct_risk_case_count=direct_risk_case_count,
        elapsed_text=elapsed_text,
    )

    if not risk_df.empty:
        st.markdown(
            "<div style='color:#18181B; font-size:1rem; font-weight:600; "
            "margin:1.5rem 0 0.75rem;'>위험도 분포</div>",
            unsafe_allow_html=True,
        )
        category_counts = _signal_category_counts(pr)
        _render_risk_pie(risk_df, category_counts)

    st.markdown("#### 2. 분석 룰 요약")
    rule_audit = _phase1_rule_audit(pr)
    _render_phase1_rule_audit(rule_audit)

    st.markdown("#### 3. 전체 데이터 탐색기")
    _render_master_data_grid(pr, data)


_VIEW_MODES: list[tuple[str, str]] = [
    ("전체", "all"),
    ("룰 위반 전표", "rule"),
    ("데이터 정합성 위반", "data_quality"),
    ("AUDIT RISK 위반", "audit_risk"),
    ("추가검토 필요", "review"),
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
        rule_options = _available_rules(data)
        if rule_options:
            selected_rules = st.multiselect(
                "룰 선택 (비워두면 모든 룰 위반 전표)",
                options=rule_options,
                default=[],
                key="phase1_grid_rule_select",
            )

    # 3. 필터 적용 — review case의 document_id 집합도 함께 전달해 case-level 매칭 보강
    review_document_ids = (
        _review_case_document_ids(pr) if view_mode == "review" else None
    )
    filtered = _filter_master_data(
        data,
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

    display_columns = [
        column for column in _MASTER_GRID_COLUMNS if column in show_df_full.columns
    ]
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
        count_html += (
            f" · 표시 상한 {_GRID_ROW_CAP:,}건 적용"
        )
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

    target_count = rule_audit.get("target_count", len(rules))
    generated_count = rule_audit.get("generated_count", 0)
    skipped_count = rule_audit.get("skipped_count", 0)

    # 상단 요약 — 전체 / 생성 / 스킵 / 미생성
    summary_html = (
        f"<div style='display:flex; gap:1rem; align-items:center; "
        f"margin:0.25rem 0 0.6rem; font-size:0.85rem;'>"
        f"<span style='color:#18181B; font-weight:600;'>전체 {target_count:,}개 룰</span>"
        f"<span style='color:#16A34A;'>· Flag 생성 {generated_count:,}</span>"
        f"<span style='color:#71717A;'>· 스킵 {skipped_count:,}</span>"
        f"<span style='color:#9CA3AF;'>(클릭 시 상세설명)</span>"
        f"</div>"
    )
    st.markdown(summary_html, unsafe_allow_html=True)

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
    section_html_parts: list[str] = []
    for title, items in ordered_sections:
        rows_html = "".join(_rule_audit_row_html(rule) for rule in items)
        section_html_parts.append(
            "<div style='background:#FFFFFF; border:1px solid #E5E7EB; "
            "border-radius:12px; padding:1rem 1.25rem; "
            "box-shadow:0 1px 2px rgba(15,23,42,0.04);'>"
            f"<div style='color:#18181B; font-size:0.95rem; font-weight:600; "
            f"margin-bottom:0.4rem;'>{title}"
            f" <span style='color:#71717A; font-weight:500; font-size:0.8rem;'>"
            f"· {len(items)}건</span></div>"
            f"{rows_html}"
            f"</div>"
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
        "gap:1rem; margin:0.25rem 0 1rem;'>"
        + "".join(section_html_parts)
        + "</div>"
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
        "적요(line_text)가 비어 있거나 의미 없는 문자열(예: \"...\", \"테스트\", "
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
    else:  # no_match
        badge_text = ""
        badge_bg = ""
        badge_color = ""
        text_color = "#9CA3AF"

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
    return (
        "<details style='border-top:1px solid #F3F4F6;'>"
        f"{summary_html}{detail_html}"
        "</details>"
    )


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
        "margin:0.25rem 0 1rem;'>"
        + "".join(section_html_parts)
        + "</div>"
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
        inputs.append(
            f"<input type='radio' name='{widget_id}' id='{input_id}'{checked}>"
        )
        labels.append(f"<label for='{input_id}'>{html.escape(label)}</label>")
        panels.append(
            f"<div class='phase1-rule-panel phase1-rule-panel-{slug}'>"
            f"{_rule_list_html(rows, empty_message=empty_message)}"
            f"</div>"
        )
        checked_styles.append(
            f"#{input_id}:checked ~ .phase1-rule-labels label[for='{input_id}']"
        )
        panel_styles.append(
            f"#{input_id}:checked ~ .phase1-rule-panels .phase1-rule-panel-{slug}"
        )

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
        "margin:0.25rem 0 1rem;'>"
        + "".join(section_html_parts)
        + "</div>"
    )


def _render_data_quality_gate(pr) -> None:
    gate = build_phase1_data_quality_gate(pr)
    if not gate["available"]:
        st.info("Data Quality Gate 결과가 없습니다.")
        return

    c1, c2 = st.columns(2)
    c1.metric("영향 document", f"{gate['document_count']:,}")
    c2.metric("관련 case", f"{gate['case_count']:,}")

    items_df = pd.DataFrame(gate["items"])
    if not items_df.empty:
        display_df = items_df.rename(
            columns={
                "rule_id": "Rule",
                "rule_label": "Issue",
                "documents": "Documents",
                "cases": "Cases",
                "score_only_documents": "Score-only docs",
                "normal_score_only_documents": "Normal score-only",
                "high_cases": "High cases",
                "medium_cases": "Medium cases",
                "review_focus": "Auditor focus",
                "actions": "Required action",
            }
        )
        display_df["Required action"] = display_df["Required action"].map(
            lambda actions: " / ".join(actions[:3]) if isinstance(actions, list) else ""
        )
        st.markdown("#### 반드시 먼저 봐야 하는 데이터/계약 오류")
        st.dataframe(
            display_df[
                [
                    "Rule",
                    "Issue",
                    "Documents",
                    "Cases",
                    "Score-only docs",
                    "Normal score-only",
                    "High cases",
                    "Medium cases",
                    "Auditor focus",
                    "Required action",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    case_df = pd.DataFrame(gate["cases"])
    if not case_df.empty:
        st.markdown("#### 관련 case")
        _render_case_table(case_df.head(50))


def _render_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="우선 위험신호",
        title="우선 위험신호",
        caption="High/Medium 우선순위이며 직접 위험 신호가 있는 case입니다.",
        key_prefix="phase1_priority_risk",
    )


def _render_low_priority_risk_queue(pr) -> None:
    _render_category_case_queue(
        pr,
        category="저우선 위험신호",
        title="저우선 위험신호",
        caption=(
            "직접 위험 신호는 있지만 Low band이거나 timing/control 성격의 넓은 "
            "모집단으로 분류된 case입니다."
        ),
        key_prefix="phase1_low_priority_risk",
    )


def _render_context_review_candidates(pr) -> None:
    _render_category_case_queue(
        pr,
        category="맥락 검토대상",
        title="맥락 검토대상",
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

    c1, c2 = st.columns([1, 3])
    c1.metric("Case", f"{len(rows):,}", border=True)
    top_n = c2.slider(
        "표시할 Case 수",
        min_value=10,
        max_value=min(max(len(rows), 10), 200),
        value=min(50, max(len(rows), 10)),
        step=10,
        key=f"{key_prefix}_top_n",
    )
    visible_rows = rows[: int(top_n)]
    _render_case_table(pd.DataFrame(visible_rows))
    _render_case_selector(pr, visible_rows)


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
        f"Audit Risk는 {len(audit.get('queues', [])):,}개 업무 queue로 나누어 표시됩니다. "
        "동점 case는 Queue Tie 점수와 Tie Reason으로 같은 queue 안에서 다시 정렬합니다."
    )
    st.write(
        f"추가검토사항은 {len(review.get('items', [])):,}개 유형으로 집계됩니다. "
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


def _render_case_table(queue_df: pd.DataFrame) -> None:
    display_df = queue_df.rename(
        columns={
            "primary_theme_label": "Theme",
            "primary_queue_label": "Queue",
            "case_type": "Case Type",
            "main_reason": "Main Reason",
            "case_key": "Case Key",
            "priority_band": "Band",
            "priority_score": "Score",
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
        "Theme",
        "Queue",
        "Band",
        "Case Type",
        "Main Reason",
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


def _render_case_selector(pr, queue: list[dict]) -> None:
    case_options = {
        f"{row['primary_queue_label']} | {row['priority_band']} | {row['case_key']}": row[
            "case_id"
        ]
        for row in queue
    }
    selected_case_label = st.selectbox(
        "Drill-down Case",
        options=list(case_options.keys()),
        key="phase1_case_select_" + str(abs(hash(tuple(case_options.values())))),
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
    meta1.metric("Priority", f"{case['priority_score']:.2f}")
    meta2.metric("Queue Tie", f"{case.get('queue_tiebreaker_score', 0):.2f}")
    meta3.metric("Documents", f"{case['document_count']:,}")
    meta4.metric("Amount", f"{case['total_amount']:,.0f}")

    sig1, sig2, sig3, sig4 = st.columns(4)
    sig1.metric("Direct risk", f"{case['direct_risk_count']:,}")
    sig2.metric("Review context", f"{case['review_context_count']:,}")
    sig3.metric("Data blocker", f"{case['integrity_blocker_count']:,}")
    sig4.metric("Macro finding", f"{case['macro_finding_count']:,}")

    st.caption(
        "Queue: "
        + case["primary_queue_label"]
        + (
            " / " + ", ".join(case["secondary_queue_labels"])
            if case["secondary_queue_labels"]
            else ""
        )
    )
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
    return int(_signal_category_counts(pr).get("우선 위험신호", 0) or 0)


def _category_case_rows(pr, category: str) -> list[dict[str, Any]]:
    phase1 = resolve_phase1_case_result(pr)
    if phase1 is None:
        return []
    dq_case_ids = _data_quality_case_ids(pr)
    cases = [
        case
        for case in phase1.cases
        if _case_signal_category(case, dq_case_ids) == category
    ]
    cases.sort(
        key=lambda case: (
            _priority_band_rank(case.priority_band),
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
            "우선 위험신호": 0,
            "저우선 위험신호": 0,
            "맥락 검토대상": 0,
        }

    counts = {
        "데이터정합성": 0,
        "우선 위험신호": 0,
        "저우선 위험신호": 0,
        "맥락 검토대상": 0,
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

    has_review_signal = (
        signal_counts["review_context"] > 0
        or signal_counts["macro_finding"] > 0
    )
    has_direct_risk = signal_counts["direct_risk"] > 0
    if not has_direct_risk:
        return "맥락 검토대상"

    if _is_broad_audit_population(case, signal_counts, has_review_signal):
        return "저우선 위험신호"

    return "우선 위험신호"


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


def _render_risk_pie(
    risk_df: pd.DataFrame, category_counts: dict[str, int]
) -> None:
    """좌우 독립 컬럼 — shadcn zinc 팔레트, flat 미니멀.

    좌: Normal vs 위험신호 도넛 (zinc-200 vs zinc-900 고대비)
    우: 우선 위험신호/저우선 위험신호/맥락 검토대상/데이터정합성 가로 막대
    Why: 연결선과 subplot 강제 정렬을 버리고 두 차트를 독립 축으로 분리.
         shadcn UI 톤(중립 회색 + 1 액센트)으로 노이즈 제거.
    """
    counts = {
        str(level): int(value)
        for level, value in zip(risk_df["risk_level"], risk_df["count"])
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
    color_normal = "#E4E4E7"      # zinc-200
    color_review = "#18181B"      # zinc-900
    color_text = "#18181B"        # zinc-900
    color_muted = "#71717A"       # zinc-500
    color_high = "#DC2626"        # red-600
    color_medium = "#F59E0B"      # amber-500
    color_low = "#3B82F6"         # blue-500
    typography = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

    # Why: 두 차트가 동일 높이의 카드 컨테이너 안에 고정되어 '둥둥 떠 보이는' 느낌 제거.
    #      shadcn 카드 톤 — border + 살짝의 그림자 + 동일 height.
    chart_card_height = 270
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
            height=180,
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

    # ── 우측: 위험신호 카테고리 분해 막대 ───────────────────
    with right_col, st.container(border=True, height=chart_card_height):
        bar_labels = ["우선 위험신호", "저우선 위험신호", "맥락 검토대상", "데이터정합성"]
        bar_values = [int(category_counts.get(label, 0) or 0) for label in bar_labels]
        bar_total = sum(bar_values)
        # 카테고리별 색: shadcn 톤 — 우선위험(red)·넓은모집단(amber)·검토(blue)·정합성(zinc)
        bar_colors = [color_high, color_medium, color_low, "#71717A"]
        bar_pcts = [
            v / bar_total * 100 if bar_total else 0.0 for v in bar_values
        ]
        bar_text = [
            f"  {v:,} 건  ·  {p:.1f}%"
            for v, p in zip(bar_values, bar_pcts)
        ]

        st.markdown(
            f"<div style='font-family:{typography};'>"
            f"<div style='color:{color_text}; font-size:0.875rem; "
            f"font-weight:600;'>위험신호 내부 구성</div>"
            f"<div style='color:{color_muted}; font-size:0.75rem; "
            f"margin-top:2px;'>총 {bar_total:,}건의 case를 카테고리별 분해</div>"
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
                textfont={"size": 12, "color": color_muted, "family": typography},
                cliponaxis=False,
                hovertemplate="%{y}: %{x:,}건<extra></extra>",
                showlegend=False,
            )
        )
        fig_bar.update_layout(
            height=180,
            margin={"l": 6, "r": 110, "t": 4, "b": 4},
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            bargap=0.45,
            font={"family": typography},
        )
        fig_bar.update_xaxes(visible=False)
        fig_bar.update_yaxes(
            autorange="reversed",
            tickfont={"size": 13, "color": color_text, "family": typography},
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
            key="phase1_signal_bar",
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


def _phase1_rule_audit(pr) -> dict[str, Any]:
    """전체 33개 룰을 한 리스트로 반환 — 룰별 status/count 부여."""
    target = list(_PHASE1_RULE_IDS)
    generated_counts = _generated_rule_counts(pr)
    skipped = set(_skipped_rule_ids(pr))

    rules: list[dict[str, Any]] = []
    for rule_id in target:
        if rule_id in generated_counts:
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
                "name_kr": _RULE_NAMES_KR.get(rule_id)
                or RULE_CODES.get(rule_id, "Unknown Rule"),
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


def _generated_rule_counts(pr) -> dict[str, int]:
    """룰별 RuleFlag 생성 건수."""
    results = getattr(pr, "results", None)
    if not results:
        return {}
    counts: dict[str, int] = {}
    for result in results:
        for rule_flag in getattr(result, "rule_flags", []) or []:
            rule_id = str(getattr(rule_flag, "rule_id", "") or "").strip()
            if rule_id:
                counts[rule_id] = counts.get(rule_id, 0) + 1
    return counts


def _generated_rule_ids(pr) -> list[str]:
    return _sort_rule_ids(_generated_rule_counts(pr).keys())


def _skipped_rule_ids(pr) -> list[str]:
    results = getattr(pr, "results", None)
    if not results:
        return []
    skipped: set[str] = set()
    for result in results:
        metadata = getattr(result, "metadata", {}) or {}
        for rule_id in metadata.get("skipped_rules", []) or []:
            rule_text = str(rule_id or "").strip()
            if rule_text:
                skipped.add(rule_text)
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


def _format_elapsed(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "-"
    return f"{seconds:,.1f}초"


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


def _available_rules(data: pd.DataFrame) -> list[str]:
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
    rule_only: bool,
    selected_rules: list[str],
    data_quality_only: bool,
    audit_risk_only: bool,
    review_only: bool,
    review_document_ids: set[str] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=data.index)
    rule_text = _combined_rule_text(data)

    if rule_only:
        if selected_rules:
            selected = set(selected_rules)
            mask &= rule_text.map(lambda value: bool(_rule_tokens(value) & selected))
        else:
            mask &= rule_text.str.strip().ne("")
    if data_quality_only:
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
