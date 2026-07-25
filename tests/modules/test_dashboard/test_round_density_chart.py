"""Round Number 밀집 차트 — 정렬·라벨·기준선·상한 검증.

Why: 표를 차트로 바꾸면서 "정렬이 곧 검토 우선순위"가 되었다(2026-07-25). 정렬 방향과
     기준선 표시가 깨지면 감사인이 우선순위를 거꾸로 읽는다.
"""

from __future__ import annotations

from dashboard.components.charts.round_density_charts import (
    SCOPE_LABELS,
    round_density_bar,
    scope_label,
)
from dashboard.tab_analytical import _round_density_table

_BASELINE = 0.04


def _finding(scope: str, key: str, ratio: float, n: int = 500, sev: str = "moderate") -> dict:
    return {
        "rule_id": "ROUND-DENSITY",
        "scope": scope,
        "group_key": key,
        "sample_size": n,
        "candidate_rows": int(n * ratio),
        "finding_severity": sev,
        "metrics": {
            "round_ratio": ratio,
            "baseline_ratio": _BASELINE,
            "excess": ratio - _BASELINE,
            "p_value": 0.001,
        },
    }


def test_bar_sorted_by_excess_descending_top_first():
    """plotly 수평 막대는 y 뒤쪽이 위 — 초과분 최대 finding 이 배열 마지막에 와야 맨 위에 보인다."""
    fig = round_density_bar(
        [
            _finding("gl_account", "A", 0.09),
            _finding("created_by", "B", 0.21),
            _finding("posting_month", "2023-12", 0.15),
        ]
    )
    labels = list(fig.data[0].y)
    assert labels[-1] == "작성자 · B"
    assert labels[0] == "계정 · A"


def test_bar_draws_ledger_baseline_line():
    fig = round_density_bar([_finding("gl_account", "A", 0.09)])
    vlines = [s for s in fig.layout.shapes if s.type == "line"]
    assert vlines and vlines[0].x0 == _BASELINE


def test_bar_respects_top_n():
    findings = [_finding("gl_account", f"A{i}", 0.30 - i * 0.01) for i in range(30)]
    fig = round_density_bar(findings, top_n=5)
    assert len(fig.data[0].y) == 5
    # 상위 5개(초과분 큰 순)만 남는다.
    assert set(fig.data[0].y) == {f"계정 · A{i}" for i in range(5)}


def test_bar_empty_findings_returns_placeholder_figure():
    fig = round_density_bar([])
    assert not fig.data
    assert "finding 이 없습니다" in fig.layout.annotations[0].text


def test_bar_skips_finding_without_metrics():
    """metrics 없는 항목이 섞여도 차트가 죽지 않는다(구 아티팩트 호환)."""
    fig = round_density_bar(
        [{"scope": "gl_account", "group_key": "X"}, _finding("gl_account", "A", 0.09)]
    )
    assert list(fig.data[0].y) == ["계정 · A"]


def test_scope_label_falls_back_to_code():
    assert scope_label("gl_account") == "계정"
    assert scope_label("unknown_axis") == "unknown_axis"


def test_table_uses_korean_scope_and_same_order_as_chart():
    table = _round_density_table(
        [
            _finding("gl_account", "A", 0.09),
            _finding("created_by", "B", 0.21, sev="strong"),
        ]
    )
    assert list(table["축"]) == ["작성자", "계정"]
    assert table.iloc[0]["신호"] == "뚜렷"


def test_detector_axes_all_have_korean_labels():
    """detector 가 내는 축(_axis_keys)이 전부 라벨을 갖는지 — 영문 코드 노출 방지."""
    import pandas as pd

    from src.detection.round_density_rules import _axis_keys

    df = pd.DataFrame(
        {
            "gl_account": ["1000"],
            "posting_date": ["2023-01-05"],
            "created_by": ["kim"],
        }
    )
    assert set(_axis_keys(df)) <= set(SCOPE_LABELS)
