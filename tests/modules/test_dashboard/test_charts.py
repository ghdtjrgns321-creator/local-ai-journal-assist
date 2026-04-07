"""Plotly 차트 래퍼 11종 단위 테스트 — go.Figure 반환 + 빈 데이터 방어."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from dashboard.components.charts import (
    anomaly_scatter,
    benford_overlay,
    company_comparison,
    fraud_type_treemap,
    hourly_heatmap,
    layer_score_radar,
    monthly_trend,
    persona_risk_matrix,
    process_distribution_bar,
    risk_donut,
    risk_heatmap,
)

# ── 빈 데이터 방어 테스트 ──────────────────────────────────────


_EMPTY = pd.DataFrame()

# Why: 모든 차트가 빈 DataFrame에서 에러 없이 안내 Figure를 반환해야 함.
_DF_CHARTS = [
    risk_heatmap, risk_donut, anomaly_scatter, monthly_trend,
    hourly_heatmap, process_distribution_bar, persona_risk_matrix,
    company_comparison, fraud_type_treemap,
]


@pytest.mark.parametrize("chart_fn", _DF_CHARTS, ids=lambda f: f.__name__)
def test_empty_df_returns_figure(chart_fn):
    fig = chart_fn(_EMPTY)
    assert isinstance(fig, go.Figure)
    assert fig.layout.annotations  # 빈 안내 메시지 annotation 존재


def test_benford_overlay_empty():
    fig = benford_overlay(_EMPTY)
    assert isinstance(fig, go.Figure)


def test_layer_score_radar_empty():
    fig = layer_score_radar({})
    assert isinstance(fig, go.Figure)


# ── 정상 데이터 반환 테스트 ────────────────────────────────────


def test_risk_heatmap(sample_df):
    fig = risk_heatmap(sample_df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_risk_donut(sample_df):
    fig = risk_donut(sample_df)
    assert isinstance(fig, go.Figure)
    assert fig.data[0].hole == 0.4


def test_anomaly_scatter(sample_df):
    fig = anomaly_scatter(sample_df, max_points=10)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_monthly_trend(sample_df):
    fig = monthly_trend(sample_df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # 전체 + 이상


def test_hourly_heatmap(sample_df):
    fig = hourly_heatmap(sample_df)
    assert isinstance(fig, go.Figure)


def test_process_distribution_bar(sample_df):
    fig = process_distribution_bar(sample_df)
    assert isinstance(fig, go.Figure)


def test_persona_risk_matrix(sample_df):
    fig = persona_risk_matrix(sample_df)
    assert isinstance(fig, go.Figure)


def test_company_comparison(sample_df):
    fig = company_comparison(sample_df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 3  # 전표수 바, 이상수 바, 평균점수 라인


def test_fraud_type_treemap(sample_df):
    fig = fraud_type_treemap(sample_df)
    assert isinstance(fig, go.Figure)


def test_benford_overlay_normal(benford_digits_df):
    fig = benford_overlay(benford_digits_df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # 바 + 라인


def test_layer_score_radar_normal():
    scores = {"layer_a": 0.1, "layer_b": 0.8, "layer_c": 0.3, "benford": 0.2}
    fig = layer_score_radar(scores)
    assert isinstance(fig, go.Figure)
    assert len(fig.data[0].r) == 5  # 4 + 닫기용 1


# ── 단일 행 경계값 테스트 ──────────────────────────────────────


@pytest.mark.parametrize("chart_fn", _DF_CHARTS, ids=lambda f: f.__name__)
def test_single_row_df(chart_fn, single_row_df):
    """1행 DataFrame에서도 에러 없이 Figure 반환."""
    fig = chart_fn(single_row_df)
    assert isinstance(fig, go.Figure)


# ── 대용량 + 계층적 샘플링 테스트 ──────────────────────────────


def test_anomaly_scatter_priority_sampling(large_df):
    """10,000행에서 max_points=500 → High/Medium 우선 보존 확인."""
    fig = anomaly_scatter(large_df, max_points=500)
    assert isinstance(fig, go.Figure)

    # Why: 계층적 샘플링이 총 포인트 수를 max_points 이하로 제한하는지 검증.
    total_points = sum(len(trace.x) for trace in fig.data)
    assert total_points <= 500

    # Why: High/Medium 전수 보존 → High trace 건수가 원본과 동일해야 함.
    high_in_original = (large_df["risk_level"] == "High").sum()
    medium_in_original = (large_df["risk_level"] == "Medium").sum()
    priority_total = high_in_original + medium_in_original
    # priority가 max_points 미만이면 전수 보존됨
    if priority_total < 500:
        for trace in fig.data:
            if trace.name == "High":
                assert len(trace.x) == high_in_original
            elif trace.name == "Medium":
                assert len(trace.x) == medium_in_original


def test_large_df_charts_no_error(large_df):
    """10,000행에서 주요 차트 에러 없이 동작."""
    for fn in [risk_heatmap, risk_donut, monthly_trend, process_distribution_bar]:
        fig = fn(large_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0
