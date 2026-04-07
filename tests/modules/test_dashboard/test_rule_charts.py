"""rule_violation_bar 차트 단위 테스트."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts import rule_violation_bar


def test_empty_df_returns_figure():
    """빈 DataFrame → 안내 Figure 반환."""
    fig = rule_violation_bar(pd.DataFrame())
    assert isinstance(fig, go.Figure)
    assert fig.layout.annotations


def test_all_normal_no_violations():
    """flagged_rules 전부 빈 문자열 → 안내 Figure."""
    df = pd.DataFrame({"flagged_rules": ["", "", ""]})
    fig = rule_violation_bar(df)
    assert isinstance(fig, go.Figure)
    assert fig.layout.annotations


def test_basic_violation_bar(sample_df):
    """sample_df에서 룰별 위반 건수 바 차트 정상 생성."""
    fig = rule_violation_bar(sample_df)
    assert isinstance(fig, go.Figure)
    # Why: 최소 1개 이상 trace(레이어별 Bar)가 생성되어야 함.
    assert len(fig.data) >= 1


def test_layer_colors_match(sample_df):
    """각 trace의 name이 Layer 라벨과 일치."""
    from dashboard.components.charts._theme import LAYER_LABELS
    fig = rule_violation_bar(sample_df)
    valid_labels = set(LAYER_LABELS.values())
    for trace in fig.data:
        assert trace.name in valid_labels


def test_large_df_no_error(large_df):
    """10,000행 DataFrame에서 에러 없이 차트 생성."""
    fig = rule_violation_bar(large_df)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1
