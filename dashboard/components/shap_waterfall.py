"""SHAP Waterfall 차트 — 선택 전표의 피처 기여도 시각화.

Why: 감사인이 "왜 이 전표가 이상으로 판정됐는가?"를 이해하려면
     각 피처가 최종 예측 점수에 얼마나 기여했는지 분해해 보여야 한다.
     Waterfall 차트는 base_value(평균 예측)에서 시작해 각 피처의 기여도를
     계단식으로 누적하여 최종 예측값에 도달하는 과정을 시각화한다.

참고: docs/pre-plan/07-dashboard.md §346 (Phase 2 확장)
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from dashboard.components.charts._theme import (
    COLOR_PRIMARY,
    COLOR_TEXT,
    DEFAULT_LAYOUT,
)
from dashboard.components.ml_tooltips import ML_TOOLTIPS


def render_shap_waterfall(
    doc_id: str,
    shap_contributions: dict[str, dict[str, float]] | None,
    base_value: float | None,
) -> None:
    """선택 전표의 SHAP 피처 기여도를 Waterfall 차트로 렌더링.

    Args:
        doc_id: 선택된 document_id.
        shap_contributions: {doc_id: {feature: shap_value}} 매핑.
            Cold Start(ML 모델 없음) 시 None.
        base_value: 모델 expected_value — Waterfall 시작점. None이면 SHAP 미산출.
    """
    st.subheader("피처 기여도 (SHAP)", help=ML_TOOLTIPS["shap_value"])

    # Why: ML 모델 자체가 없는 Cold Start — 전체 대시보드는 정상 동작
    if shap_contributions is None or base_value is None:
        st.info("ML 모델 학습 후 피처 기여도를 확인할 수 있습니다.")
        return

    # Why: SHAP은 flagged rows(anomaly_score ≥ threshold)만 계산 — 정상 전표 조회 시 안내
    contribution = shap_contributions.get(str(doc_id))
    if contribution is None:
        st.info("이 전표는 이상 임계치 미만이라 피처 기여도가 생성되지 않았습니다.")
        return

    fig = _build_waterfall(contribution, base_value)
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"기준값(base) {base_value:.3f} → 최종 예측값 "
        f"{base_value + sum(contribution.values()):.3f}",
    )


def _build_waterfall(
    contribution: dict[str, float],
    base_value: float,
) -> go.Figure:
    """Plotly go.Waterfall Figure 생성.

    Args:
        contribution: {feature_name: shap_value} — top-k 피처 기여도.
        base_value: 모델 expected_value (Waterfall 시작점).
    """
    # Why: |shap_value| 내림차순 정렬 — 영향력 큰 피처가 위에서부터 표시
    sorted_items = sorted(
        contribution.items(),
        key=lambda kv: abs(kv[1]),
        reverse=True,
    )
    features = [name for name, _ in sorted_items]
    values = [val for _, val in sorted_items]
    final_value = base_value + sum(values)

    # Why: measure=["absolute", "relative", ..., "total"]
    #      absolute = base_value 고정점, relative = 누적 기여, total = 최종값
    measures = ["absolute"] + ["relative"] * len(features) + ["total"]
    x_labels = ["base_value"] + features + ["최종 예측"]
    y_values = [base_value] + values + [final_value]

    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=measures,
        x=x_labels,
        y=y_values,
        text=[f"{v:+.3f}" if m == "relative" else f"{v:.3f}"
              for v, m in zip(y_values, measures)],
        textposition="outside",
        connector={"line": {"color": "rgba(107,114,128,0.5)", "width": 1}},
        increasing={"marker": {"color": "#E54D4D"}},   # 부정 방향 — red
        decreasing={"marker": {"color": "#68A8D6"}},   # 정상 방향 — blue
        totals={"marker": {"color": COLOR_PRIMARY}},   # 시작점/최종값 — brand primary
    ))

    fig.update_layout(
        **DEFAULT_LAYOUT,
        height=320,
        showlegend=False,
        yaxis={"title": "예측 점수", "gridcolor": "rgba(226,229,233,0.5)"},
        xaxis={"title": "", "tickangle": -25},
    )
    fig.update_traces(
        textfont={"size": 11, "color": COLOR_TEXT},
    )
    return fig


def render_vae_waterfall(row, top_k: int = 3) -> None:
    """VAE 피처별 재구성 오차 Top-K를 Waterfall 차트로 시각화 (P0-1 소비).

    Why: P0-1에서 `UnsupervisedDetector.detect()`가 DataFrame에
         `ML02_top_feature_{1..K}` + `_contrib` 컬럼을 첨부한다.
         SHAP과 달리 VAE 오차는 항상 양수(MSE)이므로 단순 누적 차트로 표시.
         선택 전표 row(pd.Series)만 받으면 되므로 대시보드 `explorer_detail`에서
         바로 호출할 수 있다.

    Args:
        row: 선택된 전표의 pd.Series (ML02_top_feature_* 컬럼 포함)
        top_k: Top-K 피처 수 (기본 3)
    """
    import pandas as pd

    st.subheader(
        "VAE 재구성 오차 기여도",
        help="비지도 탐지기(VAE)가 재구성에 실패한 피처 Top-K. 오차가 클수록 해당 피처에서 이상.",
    )

    # Why: P0-1에서 첨부한 컬럼이 없으면 VAE가 학습/적용되지 않은 상태
    if "ML02_top_feature_1" not in row.index:
        st.info("VAE 기여도가 생성되지 않았습니다. ML 모델 학습 후 재탐지하세요.")
        return

    items: list[tuple[str, float]] = []
    for i in range(1, top_k + 1):
        feat_col = f"ML02_top_feature_{i}"
        contrib_col = f"ML02_top_feature_{i}_contrib"
        if feat_col not in row.index:
            continue
        feat_name = row[feat_col]
        contrib = row[contrib_col]
        if pd.isna(feat_name) or pd.isna(contrib):
            continue
        items.append((str(feat_name), float(contrib)))

    if not items:
        st.info("이 전표에는 유효한 VAE 기여도가 없습니다.")
        return

    fig = _build_vae_waterfall(items)
    st.plotly_chart(fig, width="stretch")
    total = sum(c for _, c in items)
    st.caption(f"Top-{len(items)} 피처 기여 합계: {total:.4f}")


def _build_vae_waterfall(items: list[tuple[str, float]]) -> go.Figure:
    """VAE Top-K Waterfall Figure — 0에서 시작해 각 피처 기여 누적.

    Why: SHAP과 달리 VAE 기여는 항상 양수(MSE)이므로 `measure=relative`만 사용.
    """
    features = [name for name, _ in items]
    values = [val for _, val in items]
    total_value = sum(values)

    measures = ["relative"] * len(features) + ["total"]
    x_labels = features + ["누적 MSE"]
    y_values = values + [total_value]

    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=measures,
        x=x_labels,
        y=y_values,
        text=[f"{v:+.4f}" if m == "relative" else f"{v:.4f}"
              for v, m in zip(y_values, measures)],
        textposition="outside",
        connector={"line": {"color": "rgba(107,114,128,0.5)", "width": 1}},
        increasing={"marker": {"color": "#E54D4D"}},
        totals={"marker": {"color": COLOR_PRIMARY}},
    ))

    fig.update_layout(
        **DEFAULT_LAYOUT,
        height=320,
        showlegend=False,
        yaxis={"title": "재구성 오차 (MSE)", "gridcolor": "rgba(226,229,233,0.5)"},
        xaxis={"title": "", "tickangle": -25},
    )
    fig.update_traces(
        textfont={"size": 11, "color": COLOR_TEXT},
    )
    return fig
