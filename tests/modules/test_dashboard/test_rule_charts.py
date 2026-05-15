"""rule_violation_bar 차트 단위 테스트."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.charts import phase1_rule_violation_bar, rule_violation_bar
from src.models.phase1_case import CaseGroupResult, RawRuleHitRef


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
    # Why: 최소 1개 이상 trace(L1~L4 Bar)가 생성되어야 함.
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


def test_phase1_rule_violation_bar_counts_raw_truth_not_stale_flags():
    case = CaseGroupResult(
        case_id="CASE-L1-03",
        primary_topic="account_logic",
        primary_theme="account_logic",
        primary_queue="account_logic",
        primary_queue_label="",
        topic_scores={"account_logic": 0.9},
        secondary_topics=[],
        secondary_queues=[],
        secondary_queue_labels=[],
        fraud_scenario_tags=[],
        case_key="CASE-L1-03",
        priority_score=0.9,
        priority_band="high",
        triage_rank_score=0.9,
        document_count=1,
        row_count=1,
        rule_count=1,
        total_amount=250.0,
        representative_explanation="truth-only row",
        raw_rule_hits=[
            RawRuleHitRef(
                rule_id="L1-03",
                severity=5,
                document_id="DOC-TRUTH",
                row_index=1,
                score=0.9,
                normalized_score=0.9,
                evidence_type="account_logic",
            )
        ],
    )
    pr = type(
        "PipelineLike",
        (),
        {
            "phase1_case_result": type("Phase1Like", (), {"cases": [case]})(),
            "featured_data": pd.DataFrame(
                {"document_id": ["DOC-TRUTH", "DOC-STALE"], "flagged_rules": ["", "L1-03"]}
            ),
        },
    )()

    fig = phase1_rule_violation_bar(pr)
    compat_fig = rule_violation_bar(pr.featured_data, pr=pr)

    assert isinstance(fig, go.Figure)
    assert sum(sum(trace.x) for trace in fig.data) == 1
    assert sum(sum(trace.x) for trace in compat_fig.data) == 1
