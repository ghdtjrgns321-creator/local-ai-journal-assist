"""§9.4 §5-4 회귀 — row risk_level 과 case priority_band 의 라벨/색상 분리 smoke.

검증 대상:
- `dashboard.components.charts._theme` 의 RISK_COLORS / CASE_BAND_COLORS / ROW_RISK_LABELS /
  CASE_BAND_LABELS 가 모두 정의되어 있고 색상 / 라벨 접두사가 서로 겹치지 않는다.
- `dashboard.tab_phase1` 의 `_format_band_cell` (case priority_band) 와
  `_format_row_risk_cell` (row risk_level) 가 다른 접두사를 사용한다.
- `_case_row_risk_counts` 가 None pr/data 입력에 대해 안전하게 빈 dict 반환.
- `_row_risk_bar_html` 가 빈 카운트에 대해 안내 문자열을 반환한다.
- tab_phase1 모듈이 import 가능 (라벨/색상 분리 변경 후 import 회귀가 없다).
"""

from __future__ import annotations

import importlib

import pandas as pd


def test_theme_module_separates_row_and_case_palettes() -> None:
    theme = importlib.import_module("dashboard.components.charts._theme")
    risk_colors = theme.RISK_COLORS
    case_band_colors = theme.CASE_BAND_COLORS
    case_band_labels = theme.CASE_BAND_LABELS
    row_risk_labels = theme.ROW_RISK_LABELS

    # 색상 분리: 두 팔레트의 16진 코드 교집합이 없어야 한다 (워온 톤 vs 쿨 톤).
    assert set(risk_colors.values()).isdisjoint(set(case_band_colors.values()))

    # 라벨 접두사 분리: row 는 ● 원형, case 는 ◆ 다이아.
    for label in case_band_labels.values():
        assert label.startswith("◆"), label
    for label in row_risk_labels.values():
        assert label.startswith("●"), label


def test_format_band_helpers_use_distinct_prefix() -> None:
    tab_phase1 = importlib.import_module("dashboard.tab_phase1")

    for band in ("high", "medium", "low"):
        assert tab_phase1._format_band_cell(band).startswith("◆")
    # 기본값(None) 도 case Low ◆ 로 안전 fallback.
    assert tab_phase1._format_band_cell(None).startswith("◆")

    for risk in ("High", "Medium", "Low", "Normal"):
        assert tab_phase1._format_row_risk_cell(risk).startswith("●")
    # None 입력은 Normal 로 처리.
    assert tab_phase1._format_row_risk_cell(None).startswith("●")
    # 카드/표시에서 case 와 row 라벨이 동일 접두사를 가지면 운영자가 혼동 — 분리 보증.
    assert tab_phase1._format_band_cell("high")[0] != tab_phase1._format_row_risk_cell("High")[0]


class _StubPR:
    def __init__(self, df: pd.DataFrame | None) -> None:
        self.featured_data = df


def test_case_row_risk_counts_handles_missing_data() -> None:
    tab_phase1 = importlib.import_module("dashboard.tab_phase1")
    drilldown = {"raw_rule_hits": [{"row_index": 0}, {"row_index": 1}]}

    # 데이터 없음 → 빈 dict
    assert tab_phase1._case_row_risk_counts(_StubPR(None), drilldown) == {}

    # risk_level 컬럼 없는 DataFrame
    df_no_risk = pd.DataFrame({"document_id": ["A", "B"]})
    assert tab_phase1._case_row_risk_counts(_StubPR(df_no_risk), drilldown) == {}


def test_case_row_risk_counts_aggregates_by_row_index() -> None:
    tab_phase1 = importlib.import_module("dashboard.tab_phase1")
    df = pd.DataFrame(
        {
            "document_id": [f"DOC{i}" for i in range(5)],
            "risk_level": ["High", "Medium", "Low", "Normal", "Normal"],
        }
    )
    drilldown = {
        "raw_rule_hits": [
            {"row_index": 0},
            {"row_index": 1},
            {"row_index": 3},
            {"row_index": 3},  # 같은 row 중복 제거되어야 한다.
        ]
    }
    counts = tab_phase1._case_row_risk_counts(_StubPR(df), drilldown)
    assert counts == {"High": 1, "Medium": 1, "Normal": 1}


def test_row_risk_bar_html_returns_placeholder_for_empty_counts() -> None:
    tab_phase1 = importlib.import_module("dashboard.tab_phase1")
    html = tab_phase1._row_risk_bar_html({})
    assert "행 risk_level" in html
    assert "찾지 못했습니다" in html


def test_row_risk_bar_html_renders_segments_for_each_level() -> None:
    tab_phase1 = importlib.import_module("dashboard.tab_phase1")
    html = tab_phase1._row_risk_bar_html({"High": 2, "Normal": 3})
    # case 와 row 가 다른 축임을 명시하는 안내 문구가 포함되어야 한다.
    assert "case 우선순위" in html and "행 risk_level" in html
    # 두 레벨 모두 색상 / 카운트 라벨이 들어가야 한다.
    assert "행 High 2" in html
    assert "행 Normal 3" in html


def test_tab_phase1_module_imports_after_label_color_split() -> None:
    """tab_phase1 모듈 import 가 라벨/색상 분리 변경 후에도 정상 동작."""

    module = importlib.import_module("dashboard.tab_phase1")
    # 핵심 helper 가 모듈 attribute 로 노출되어 있어야 한다.
    for name in (
        "_format_band_cell",
        "_format_row_risk_cell",
        "_case_row_risk_counts",
        "_row_risk_bar_html",
    ):
        assert hasattr(module, name), f"{name} missing after label/color split"
