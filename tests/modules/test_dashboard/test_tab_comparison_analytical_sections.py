"""전기 비교 탭에 편입된 분석적 검토 신호(D01/D02) 표시 로직 테스트.

화면 렌더가 아니라 표에 들어갈 값을 만드는 순수 함수만 검증한다.
"""

from __future__ import annotations

import pytest

from dashboard import tab_comparison as tc


class TestPctChange:
    def test_증가율을_퍼센트로_돌려준다(self):
        assert tc._pct_change(300, 100) == 200.0

    def test_감소율은_음수다(self):
        assert tc._pct_change(50, 100) == -50.0

    def test_전기가_0이면_계산하지_않는다(self):
        # 신규 계정처럼 전기 값이 없으면 증감률은 정의되지 않는다.
        assert tc._pct_change(100, 0) is None

    def test_값이_없으면_None(self):
        assert tc._pct_change(None, 100) is None
        assert tc._pct_change(100, None) is None


class TestMonthShiftLabel:
    def test_몰린_달이_바뀌면_화살표(self):
        assert tc._month_shift_label(11, 12) == "11월 → 12월"

    def test_같은_달이면_변동_없음(self):
        assert tc._month_shift_label(3, 3) == "3월 (변동 없음)"

    def test_값이_없으면_대시(self):
        assert tc._month_shift_label(None, 5) == "-"


class TestPriorYearNote:
    def test_고른_전기와_finding_전기가_같으면_기준만_밝힌다(self):
        note = tc._prior_year_note(
            [{"prior_fiscal_year": 2022}],
            {"selected_prior_fiscal_year": 2022},
        )
        assert note == "비교 기준 전기: FY 2022"

    def test_연도가_어긋나면_경고_문장을_낸다(self):
        note = tc._prior_year_note(
            [{"prior_fiscal_year": 2022}],
            {"selected_prior_fiscal_year": 2021},
        )
        assert "FY 2022" in note
        assert "FY 2021" in note
        assert "다른 연도" in note

    def test_전기_정보가_없으면_빈_문자열(self):
        assert tc._prior_year_note([{"prior_fiscal_year": None}], {}) == ""


class TestRatioGapPp:
    def test_두_비중의_차이를_퍼센트포인트로(self):
        assert tc._ratio_gap_pp(0.2081, 0.6213) == pytest.approx(41.32, abs=0.01)

    def test_방향과_무관하게_절대값(self):
        assert tc._ratio_gap_pp(0.6, 0.2) == pytest.approx(40.0)

    def test_값이_없으면_None(self):
        assert tc._ratio_gap_pp(None, 0.5) is None


class TestD02Coverage:
    def test_세운_계정_수와_비교불가_제외를_밝힌다(self):
        diagnostics = [
            {"gl_account": "2600", "skip_reason": ""},
            {"gl_account": "1100", "skip_reason": "insufficient_current_docs"},
            {"gl_account": "1300", "skip_reason": "small_top_month_delta"},
            {"gl_account": "1400", "skip_reason": "insufficient_prior_months"},
            {"gl_account": "1500", "skip_reason": "insufficient_current_months"},
        ]
        text = tc._format_d02_coverage(3, diagnostics)
        assert "계정 3개" in text
        assert "잘라내지 않음" in text
        # 분포를 비교할 수 없는 두 건만 제외 사유로 밝힌다.
        assert "전기 거래월 부족 1개" in text
        assert "당기 거래월 부족 1개" in text

    def test_폐지된_신호강도_컷은_제외_사유로_쓰지_않는다(self):
        # 전표수·금액·비중변화 하한은 2026-07-25 에 폐지됐다. 목록에 남아야 하므로
        # "제외됐다"고 말하면 거짓 설명이 된다.
        diagnostics = [
            {"gl_account": "1100", "skip_reason": "insufficient_current_docs"},
            {"gl_account": "1200", "skip_reason": "insufficient_current_amount"},
            {"gl_account": "1300", "skip_reason": "small_top_month_delta"},
        ]
        text = tc._format_d02_coverage(3, diagnostics)
        assert "제외" not in text

    def test_판정_근거가_없으면_문장을_만들지_않는다(self):
        assert tc._format_d02_coverage(0, []) == ""


class TestSubtabStructure:
    def test_PHASE2_보조_신호_소분류는_제거됐다(self):
        assert not hasattr(tc, "_render_phase2_subtab")
        assert not hasattr(tc, "_collect_phase2_signal_data")

    def test_검토_후보_등급_도넛은_제거됐다(self):
        assert not hasattr(tc, "_query_risk_dist")
