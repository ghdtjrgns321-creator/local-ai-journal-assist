from __future__ import annotations

import pandas as pd
import streamlit as st

from src.export.phase1_case_view import (
    build_phase1_case_drilldown,
    build_phase1_case_queue,
    summarize_phase1_case_result,
)


def render(prep_result, phase1_result) -> None:
    st.subheader("Phase 1 케이스 리뷰")
    st.caption(
        "룰 목록 대신 감사 케이스 단위로 결과를 보여줍니다. "
        "직접 위험, 리뷰/맥락, 정합성 문제, 계정/모집단 finding을 분리해 확인합니다."
    )

    if phase1_result is None:
        st.info(
            "아직 Phase 1 분석이 실행되지 않았습니다. "
            "준비 단계에서 데이터를 확인한 뒤 케이스 기반 리뷰를 생성하세요."
        )
        _render_prep_summary(prep_result)
        if st.button("Phase 1 분석 시작", type="primary", key="run_phase1"):
            from dashboard.components.analysis_runner import run_phase_analysis

            with st.spinner("Phase 1 분석 중..."):
                run_phase_analysis(phase="phase1")
            st.rerun()
        return

    summary = summarize_phase1_case_result(phase1_result)
    if not summary["available"]:
        st.warning("PHASE1 케이스 결과를 불러오지 못했습니다.")
        return

    _render_case_summary(summary)
    st.divider()
    _render_theme_queue(phase1_result, summary)


def _render_prep_summary(prep_result) -> None:
    data = prep_result.featured_data if prep_result.featured_data is not None else prep_result.data
    c1, c2, c3 = st.columns(3)
    c1.metric("준비 문서", f"{len(data):,}", border=True)
    c2.metric("준비 컬럼", f"{len(data.columns):,}", border=True)
    c3.metric("준비 경고", f"{len(prep_result.warnings):,}", border=True)


def _render_case_summary(summary: dict) -> None:
    high_count = sum(theme["high_count"] for theme in summary["themes"])
    medium_count = sum(theme["medium_count"] for theme in summary["themes"])
    total_amount = sum(theme["total_amount"] for theme in summary["themes"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Case", f"{summary['case_count']:,}", border=True)
    c2.metric("High", f"{high_count:,}", border=True)
    c3.metric("Medium", f"{medium_count:,}", border=True)
    c4.metric("Exposure", f"{total_amount:,.0f}", border=True)

    theme_df = pd.DataFrame(summary["themes"])
    if not theme_df.empty:
        theme_df = theme_df.rename(
            columns={
                "theme_label": "Theme",
                "case_count": "Cases",
                "high_count": "High",
                "medium_count": "Medium",
                "low_count": "Low",
                "total_amount": "Amount",
            }
        )[["Theme", "Cases", "High", "Medium", "Low", "Amount"]]
        st.caption("Theme Queue 요약")
        st.dataframe(theme_df, use_container_width=True, hide_index=True)


def _render_theme_queue(pr, summary: dict) -> None:
    theme_options = [("전체", None)] + [
        (theme["theme_label"], theme["theme_id"]) for theme in summary["themes"]
    ]
    selected_label = st.selectbox(
        "Theme 선택",
        options=[label for label, _ in theme_options],
        index=0,
        key="phase1_theme_select",
    )
    selected_theme = next(theme_id for label, theme_id in theme_options if label == selected_label)
    top_n = st.slider(
        "표시할 Case 수",
        min_value=5,
        max_value=50,
        value=10,
        step=5,
        key="phase1_top_n",
    )

    queue = build_phase1_case_queue(pr, theme_id=selected_theme, top_n=top_n)
    if not queue:
        st.info("선택한 조건에 해당하는 케이스가 없습니다.")
        return

    queue_df = pd.DataFrame(queue)
    display_df = queue_df.rename(
        columns={
            "primary_theme_label": "Theme",
            "case_type": "Case Type",
            "main_reason": "Main Reason",
            "case_key": "Case Key",
            "priority_band": "Band",
            "priority_score": "Score",
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
    )[
        [
            "Theme",
            "Band",
            "Case Type",
            "Main Reason",
            "Score",
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
    ]

    st.caption("Case Queue")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    case_options = {
        f"{row['primary_theme_label']} | {row['priority_band']} | {row['case_key']}": row[
            "case_id"
        ]
        for row in queue
    }
    selected_case_label = st.selectbox(
        "Drill-down Case 선택",
        options=list(case_options.keys()),
        key="phase1_case_select",
    )
    selected_case_id = case_options[selected_case_label]
    drilldown = build_phase1_case_drilldown(pr, selected_case_id)
    if drilldown is not None:
        _render_case_drilldown(drilldown)


def _render_case_drilldown(drilldown: dict) -> None:
    case = drilldown["case"]
    narrative = case["risk_narrative"] or case["representative_explanation"]
    st.markdown(f"**검토 설명**  \n{narrative}")

    meta1, meta2, meta3, meta4 = st.columns(4)
    meta1.metric("Priority", f"{case['priority_score']:.2f}")
    meta2.metric("Documents", f"{case['document_count']:,}")
    meta3.metric("Amount", f"{case['total_amount']:,.0f}")
    meta4.metric("Repeat Months", f"{case['repeat_months']:,}")

    sig1, sig2, sig3, sig4 = st.columns(4)
    sig1.metric("직접 위험", f"{case['direct_risk_count']:,}", border=True)
    sig2.metric("리뷰/맥락", f"{case['review_context_count']:,}", border=True)
    sig3.metric("정합성/탐지제약", f"{case['integrity_blocker_count']:,}", border=True)
    sig4.metric("계정/모집단", f"{case['macro_finding_count']:,}", border=True)

    if case["secondary_tags"]:
        st.caption("Secondary Tags: " + ", ".join(case["secondary_tags"]))
    if case["evidence_tags"]:
        st.caption("Evidence Tags: " + ", ".join(case["evidence_tags"]))
    if case["review_focus"]:
        st.caption("Review Focus: " + ", ".join(case["review_focus"]))
    if case["recommended_audit_actions"]:
        st.caption("Recommended Actions: " + " / ".join(case["recommended_audit_actions"][:4]))

    documents_df = pd.DataFrame(drilldown["documents"])
    if not documents_df.empty:
        st.caption("문서 Drill-down")
        st.dataframe(documents_df, use_container_width=True, hide_index=True)

    _render_signal_sections(drilldown)


def _render_signal_sections(drilldown: dict) -> None:
    sections = drilldown.get("signal_sections", {})
    labels = [
        ("direct_risk", "직접 위험 신호"),
        ("review_context", "리뷰/맥락 신호"),
        ("integrity_blocker", "정합성/탐지제약"),
        ("macro_finding", "계정/모집단 Finding"),
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

    with st.expander("전체 Raw Rule Hits", expanded=False):
        raw_df = pd.DataFrame(drilldown["raw_rule_hits"])
        st.dataframe(raw_df, use_container_width=True, hide_index=True)
