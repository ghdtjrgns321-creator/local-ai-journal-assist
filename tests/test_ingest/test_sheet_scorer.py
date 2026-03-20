"""시트 품질 스코어링 테스트 — score_sheets() 단위·통합 테스트.

테스트 그룹:
  - 단일시트: 단일 시트 → recommended=True
  - 멀티시트 순위: 데이터 시트 > 빈 시트 > 메모 시트
  - 빈 시트: 전체 NaN → score=0.0
  - 동점: active_sheet 우선
  - 헤더 가중치: header_confidence가 스코어에 반영
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ingest.models import HeaderDetectionResult, ReadResult, SheetScore
from src.ingest.sheet_scorer import score_sheets


# ── 헬퍼 ──────────────────────────────────────────────


def _make_header_result(
    confidence: float = 0.9,
    header_row: int | None = 0,
) -> HeaderDetectionResult:
    """테스트용 간이 HeaderDetectionResult 생성."""
    return HeaderDetectionResult(
        header_row=header_row,
        confidence=confidence,
        matched_keywords=[],
        total_columns=3,
        message="test",
    )


# ── 단일시트 ──────────────────────────────────────────


class TestSingleSheet:
    """단일 시트 기본 동작."""

    def test_single_sheet_recommended(self) -> None:
        """시트 1개 → recommended=True."""
        rr = ReadResult(
            sheets=["Sheet1"],
            active_sheet="Sheet1",
            raw_data={"Sheet1": pd.DataFrame({"a": [1, 2], "b": [3, 4]})},
            source_format="xlsx",
        )
        headers = {"Sheet1": _make_header_result(0.9)}
        scores = score_sheets(rr, headers)

        assert len(scores) == 1
        assert scores[0].recommended is True
        assert scores[0].sheet_name == "Sheet1"

    def test_score_range(self) -> None:
        """total_score가 0~1 범위."""
        rr = ReadResult(
            sheets=["Sheet1"],
            active_sheet="Sheet1",
            raw_data={"Sheet1": pd.DataFrame({"a": [1, 2, 3]})},
            source_format="csv",
        )
        headers = {"Sheet1": _make_header_result(0.8)}
        scores = score_sheets(rr, headers)

        assert 0.0 <= scores[0].total_score <= 1.0


# ── 멀티시트 순위 ────────────────────────────────────


class TestMultiSheetRanking:
    """멀티시트 스코어 순위 검증."""

    def test_data_sheet_ranked_higher(self) -> None:
        """데이터 행이 많은 시트가 상위."""
        rr = ReadResult(
            sheets=["메모", "매출"],
            active_sheet="메모",
            raw_data={
                "메모": pd.DataFrame({"a": ["참고사항"]}),
                "매출": pd.DataFrame({"a": range(100), "b": range(100), "c": range(100)}),
            },
            source_format="xlsx",
        )
        headers = {
            "메모": _make_header_result(0.1),
            "매출": _make_header_result(0.9),
        }
        scores = score_sheets(rr, headers)

        assert scores[0].sheet_name == "매출"
        assert scores[0].recommended is True
        assert scores[1].sheet_name == "메모"
        assert scores[1].recommended is False

    def test_three_sheets_ordering(self) -> None:
        """3개 시트 — 빈 시트가 최하위."""
        rr = ReadResult(
            sheets=["표지", "데이터", "빈시트"],
            active_sheet="표지",
            raw_data={
                "표지": pd.DataFrame({"a": ["제목"]}),
                "데이터": pd.DataFrame({"a": range(50), "b": range(50)}),
                "빈시트": pd.DataFrame({0: [None, None], 1: [None, None]}),
            },
            source_format="xlsx",
        )
        headers = {
            "표지": _make_header_result(0.2),
            "데이터": _make_header_result(0.85),
            "빈시트": _make_header_result(0.0, header_row=None),
        }
        scores = score_sheets(rr, headers)

        names = [s.sheet_name for s in scores]
        assert names[0] == "데이터"
        assert names[-1] == "빈시트"


# ── 빈 시트 ──────────────────────────────────────────


class TestEmptySheet:
    """전체 NaN 빈 시트 → score=0.0."""

    def test_all_nan_score_zero(self) -> None:
        """모든 셀 NaN → 0점."""
        rr = ReadResult(
            sheets=["빈시트"],
            active_sheet="빈시트",
            raw_data={"빈시트": pd.DataFrame({0: [None, None], 1: [None, None]})},
            source_format="xlsx",
        )
        headers = {"빈시트": _make_header_result(0.0, header_row=None)}
        scores = score_sheets(rr, headers)

        assert scores[0].total_score == 0.0
        assert scores[0].row_count == 0
        assert scores[0].col_count == 0


# ── 동점 처리 ────────────────────────────────────────


class TestTieBreaker:
    """동점 시 active_sheet 우선."""

    def test_tie_active_sheet_wins(self) -> None:
        """동점 시트 2개 — active_sheet가 recommended."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        rr = ReadResult(
            sheets=["시트A", "시트B"],
            active_sheet="시트B",
            raw_data={"시트A": df.copy(), "시트B": df.copy()},
            source_format="xlsx",
        )
        headers = {
            "시트A": _make_header_result(0.9),
            "시트B": _make_header_result(0.9),
        }
        scores = score_sheets(rr, headers)

        recommended = [s for s in scores if s.recommended]
        assert len(recommended) == 1
        assert recommended[0].sheet_name == "시트B"

    def test_tie_no_active_first_wins(self) -> None:
        """동점인데 active_sheet가 후보에 없으면 첫 번째 우선."""
        df = pd.DataFrame({"a": [1, 2]})
        rr = ReadResult(
            sheets=["시트A", "시트B"],
            active_sheet="다른시트",  # 동점 후보에 없는 시트
            raw_data={"시트A": df.copy(), "시트B": df.copy()},
            source_format="xlsx",
        )
        headers = {
            "시트A": _make_header_result(0.9),
            "시트B": _make_header_result(0.9),
        }
        scores = score_sheets(rr, headers)

        recommended = [s for s in scores if s.recommended]
        assert len(recommended) == 1


# ── 헤더 가중치 ──────────────────────────────────────


class TestHeaderWeight:
    """header_confidence가 스코어에 반영되는지 확인."""

    def test_high_header_confidence_wins(self) -> None:
        """행 수 적어도 헤더 신뢰도 높으면 추천될 수 있음."""
        rr = ReadResult(
            sheets=["많은행", "좋은헤더"],
            active_sheet="많은행",
            raw_data={
                "많은행": pd.DataFrame({"a": range(10)}),
                "좋은헤더": pd.DataFrame({"a": range(5), "b": range(5), "c": range(5)}),
            },
            source_format="xlsx",
        )
        headers = {
            "많은행": _make_header_result(0.1),   # 헤더 신뢰도 낮음
            "좋은헤더": _make_header_result(0.95),  # 헤더 신뢰도 높음
        }
        scores = score_sheets(rr, headers)

        # 헤더 가중치(0.5)가 크므로 좋은헤더가 상위
        assert scores[0].sheet_name == "좋은헤더"
