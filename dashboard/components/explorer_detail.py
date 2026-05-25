"""Detail panel for a selected document."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.charts._theme import (
    DEFAULT_LAYOUT,
    LAYER_COLORS,
    LAYER_LABELS,
    empty_figure,
)
from dashboard.components.shap_waterfall import render_shap_waterfall
from src.detection.constants import get_rule_level_label
from src.detection.explanations import build_document_explanation

if TYPE_CHECKING:
    import duckdb

    from src.detection.base import DetectionResult


def render_detail(
    doc_id: str,
    result_data: pd.DataFrame,
    conn: duckdb.DuckDBPyConnection | None = None,
    batch_id: str = "",
    results: list[DetectionResult] | None = None,
    shap_contributions: dict[str, dict[str, float]] | None = None,
    shap_base_value: float | None = None,
) -> None:
    """Render the document detail panel."""
    has_shap = shap_contributions is not None and shap_base_value is not None

    with st.expander(f"문서 상세: {doc_id}", expanded=True):
        explanation = build_document_explanation(doc_id, result_data, results)
        _render_explanation_block(explanation)
        _render_feedback_history(doc_id, conn, batch_id)

        if has_shap:
            col_chart, col_lines, col_shap = st.columns([3, 2, 3])
        else:
            col_chart, col_lines = st.columns([3, 2])
            col_shap = None

        with col_chart:
            st.subheader("탐지 룰 점수")
            rule_df = _get_rule_detail(doc_id, conn, batch_id)
            if rule_df.empty:
                st.plotly_chart(empty_figure("탐지 결과 없음"), width="stretch")
            else:
                st.plotly_chart(_build_rule_chart(rule_df), width="stretch")

        with col_lines:
            st.subheader("라인아이템")
            doc_lines = result_data[result_data["document_id"] == doc_id]
            if doc_lines.empty:
                st.info("라인아이템 없음")
            else:
                display_cols = [
                    "line_number",
                    "gl_account",
                    "debit_amount",
                    "credit_amount",
                    "line_text",
                ]
                visible = [col for col in display_cols if col in doc_lines.columns]
                st.dataframe(
                    doc_lines[visible].reset_index(drop=True),
                    width="stretch",
                    hide_index=True,
                )

        if col_shap is not None:
            with col_shap:
                render_shap_waterfall(doc_id, shap_contributions, shap_base_value)


def _render_explanation_block(explanation: dict) -> None:
    st.markdown("**탐지 설명**")
    st.write(explanation.get("headline", "-"))

    triggered_rules = explanation.get("triggered_rules", [])
    for rule in triggered_rules:
        ref_text = ""
        if rule.get("references"):
            ref_text = f" · 근거: {', '.join(rule['references'])}"
        st.caption(f"{rule['rule_id']} {rule['plain_reason']}{ref_text}")

    if explanation.get("auditor_focus_points"):
        st.markdown("**감사자 확인 포인트**")
        for item in explanation["auditor_focus_points"]:
            st.write(f"- {item}")

    if explanation.get("false_positive_risks"):
        st.markdown("**오탐 가능성**")
        for item in explanation["false_positive_risks"]:
            st.write(f"- {item}")

    if explanation.get("used_columns"):
        st.caption("사용 컬럼: " + ", ".join(explanation["used_columns"]))


def _render_feedback_history(
    doc_id: str,
    conn: duckdb.DuckDBPyConnection | None,
    batch_id: str,
) -> None:
    """Render recent HITL feedback for this document."""
    if conn is None or not batch_id:
        return
    try:
        from src.hitl.feedback_store import list_feedback_events

        feedback_df = list_feedback_events(conn, batch_id=batch_id, document_id=doc_id)
    except Exception:
        return

    if feedback_df.empty:
        return

    st.markdown("**HITL 피드백 이력**")
    preview = feedback_df.head(3).copy()
    if "created_at" in preview.columns:
        preview["created_at"] = preview["created_at"].astype(str).str[:19]
    if "payload_json" in preview.columns:
        preview["payload_json"] = preview["payload_json"].apply(
            lambda payload: ", ".join(f"{key}={value}" for key, value in payload.items())
            if payload else "-"
        )
    visible = [
        col
        for col in ["decision", "rule_code", "reason", "created_by", "created_at", "payload_json"]
        if col in preview.columns
    ]
    st.dataframe(preview[visible], width="stretch", hide_index=True)


def _get_rule_detail(
    doc_id: str,
    conn: duckdb.DuckDBPyConnection | None,
    batch_id: str,
) -> pd.DataFrame:
    if conn is None:
        return pd.DataFrame()

    from src.db.queries import execute_preset

    try:
        return execute_preset(conn, "document_rule_detail", params=(batch_id, doc_id))
    except Exception:
        return pd.DataFrame()


def _build_rule_chart(rule_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    rule_df = rule_df.copy()
    rule_df["rule_level"] = rule_df["rule_code"].map(get_rule_level_label)
    for rule_level, group in rule_df.groupby("rule_level", sort=False):
        color = LAYER_COLORS.get(rule_level, "#999")
        label = LAYER_LABELS.get(rule_level, rule_level)
        fig.add_trace(
            go.Bar(
                y=group["rule_code"],
                x=group["score"],
                orientation="h",
                name=label,
                marker_color=color,
                text=group["score"].apply(lambda value: f"{value:.3f}"),
                textposition="outside",
            )
        )

    fig.update_layout(
        **DEFAULT_LAYOUT,
        xaxis_title="점수",
        yaxis_title="룰 코드",
        barmode="group",
        showlegend=True,
        legend={"orientation": "h", "y": -0.15},
        height=300,
    )
    return fig
