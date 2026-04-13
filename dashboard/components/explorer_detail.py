"""행 상세 패널 — 선택 전표의 룰별 점수 차트 + 라인아이템 + SHAP 기여도.

Why: Explorer 그리드에서 행 선택 시 해당 전표의 탐지 근거를
     시각적으로 확인할 수 있도록 드릴다운 패널 제공.
     WU-17: ML 모델이 학습되어 있으면 SHAP waterfall로 피처 기여도까지 표시.
"""

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

if TYPE_CHECKING:
    import duckdb


def render_detail(
    doc_id: str,
    result_data: pd.DataFrame,
    conn: "duckdb.DuckDBPyConnection | None",
    batch_id: str,
    shap_contributions: dict[str, dict[str, float]] | None = None,
    shap_base_value: float | None = None,
) -> None:
    """선택된 전표의 상세 정보 패널 렌더링.

    Args:
        doc_id: 선택된 document_id.
        result_data: PipelineResult.data (인메모리 DataFrame).
        conn: DuckDB 연결 (None이면 인메모리 전용).
        batch_id: 현재 배치 식별자.
        shap_contributions: SHAP 기여도 매핑 (ML 모델 없을 시 None).
        shap_base_value: SHAP Waterfall 시작점 (None이면 SHAP 미표시).
    """
    # Why: SHAP 데이터 존재 여부에 따라 2컬럼 ↔ 3컬럼 동적 전환.
    #      Cold Start(ML 미학습)에서는 기존 2컬럼 레이아웃 유지.
    has_shap = shap_contributions is not None and shap_base_value is not None

    with st.expander(f"문서 상세: {doc_id}", expanded=True):
        if has_shap:
            col_chart, col_lines, col_shap = st.columns([3, 2, 3])
        else:
            col_chart, col_lines = st.columns([3, 2])
            col_shap = None

        # ── 좌측: 룰별 점수 바 차트 ──
        with col_chart:
            st.subheader("탐지 룰 점수")
            rule_df = _get_rule_detail(doc_id, conn, batch_id)
            if rule_df.empty:
                st.plotly_chart(empty_figure("탐지 결과 없음"), use_container_width=True)
            else:
                fig = _build_rule_chart(rule_df)
                st.plotly_chart(fig, use_container_width=True)

        # ── 중앙: 해당 전표 라인아이템 ──
        with col_lines:
            st.subheader("라인아이템")
            doc_lines = result_data[result_data["document_id"] == doc_id]
            if doc_lines.empty:
                st.info("라인아이템 없음")
            else:
                # Why: 상세 패널에서 핵심 컬럼만 표시하여 가독성 확보
                display_cols = [
                    "line_number", "gl_account", "debit_amount",
                    "credit_amount", "line_text",
                ]
                available = [c for c in display_cols if c in doc_lines.columns]
                st.dataframe(
                    doc_lines[available].reset_index(drop=True),
                    use_container_width=True,
                    hide_index=True,
                )

        # ── 우측: SHAP 피처 기여도 (ML 학습된 경우에만) ──
        if col_shap is not None:
            with col_shap:
                render_shap_waterfall(doc_id, shap_contributions, shap_base_value)


def _get_rule_detail(
    doc_id: str,
    conn: "duckdb.DuckDBPyConnection | None",
    batch_id: str,
) -> pd.DataFrame:
    """document_rule_detail 쿼리 실행. DB 없으면 빈 DataFrame."""
    if conn is None:
        return pd.DataFrame()

    from src.db.queries import execute_preset

    try:
        return execute_preset(conn, "document_rule_detail", params=(batch_id, doc_id))
    except Exception:
        return pd.DataFrame()


def _build_rule_chart(rule_df: pd.DataFrame) -> go.Figure:
    """룰별 점수 수평 바 차트 생성."""
    fig = go.Figure()

    # Why: track_name별로 그룹핑하여 레이어 색상 구분
    for track, group in rule_df.groupby("track_name"):
        color = LAYER_COLORS.get(track, "#999")
        label = LAYER_LABELS.get(track, track)
        fig.add_trace(go.Bar(
            y=group["rule_code"],
            x=group["score"],
            orientation="h",
            name=label,
            marker_color=color,
            text=group["score"].apply(lambda v: f"{v:.3f}"),
            textposition="outside",
        ))

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
