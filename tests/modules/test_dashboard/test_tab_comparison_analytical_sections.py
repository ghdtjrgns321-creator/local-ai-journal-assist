"""전기 비교 탭에 편입된 분석적 검토 신호(D01/D02) 표시 로직 테스트.

화면 렌더가 아니라 표에 들어갈 값을 만드는 순수 함수만 검증한다.
"""

from __future__ import annotations

import pandas as pd
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


class TestHasClosingRatio:
    def test_결산월_비중이_있으면_True(self):
        assert tc._has_closing_ratio([{"metrics": {"current_closing_ratio": 0.4}}])

    def test_구_Phase1_결과처럼_없으면_False(self):
        # 2026-07-25 전에 실행한 결과에는 이 진단값이 없다 → 빈 표 대신 재실행 안내.
        assert not tc._has_closing_ratio([{"metrics": {"prior_top_ratio": 0.3}}])

    def test_finding_이_없으면_False(self):
        assert not tc._has_closing_ratio([])


class TestClosingShiftFromLedger:
    """Phase 1 재실행 없이, 탭이 붙인 원장 집계로 결산월 비중을 채운다."""

    @staticmethod
    def _account_monthly() -> pd.DataFrame:
        rows = []
        for month in range(1, 13):
            # 전기: 12개월 균등. 당기: 12월에 절반이 몰린다.
            rows.append(
                {
                    "period": "prior",
                    "gl_account": "410000",
                    "fiscal_period": month,
                    "amount": 100.0,
                }
            )
            rows.append(
                {
                    "period": "current",
                    "gl_account": "410000",
                    "fiscal_period": month,
                    "amount": 1100.0 if month == 12 else 100.0,
                }
            )
        return pd.DataFrame(rows)

    def test_원장_집계로_결산월_비중을_계산한다(self):
        findings = tc._closing_shift_findings_from_ledger(self._account_monthly())

        assert len(findings) == 1
        metrics = findings[0]["metrics"]
        assert metrics["closing_period"] == 12
        assert metrics["prior_closing_ratio"] == pytest.approx(1 / 12)
        assert metrics["current_closing_ratio"] == pytest.approx(0.5)

    def test_표_행까지_그대로_흘러간다(self):
        rows = tc._d02_table_rows(tc._closing_shift_findings_from_ledger(self._account_monthly()))

        assert rows[0]["증가분(%p)"] == pytest.approx((0.5 - 1 / 12) * 100)

    def test_전기_집계가_없으면_빈_목록(self):
        current_only = self._account_monthly()
        current_only = current_only[current_only["period"] == "current"]
        assert tc._closing_shift_findings_from_ledger(current_only) == []
        assert tc._closing_shift_findings_from_ledger(pd.DataFrame()) == []
        assert tc._closing_shift_findings_from_ledger(None) == []

    def test_구_탐지모듈이면_결산월_비중이_비어_표를_그리지_않는다(self):
        # 변경 전 variance_rules 가 sys.modules 에 남아 있으면 진단에 이 컬럼이 없다.
        # 그 상태를 표에 흘리면 전부 None 인 표가 "변동 없음" 으로 읽힌다.
        stale = [{"gl_account": "1000", "metrics": {"current_annual_amount": 100.0}}]
        assert not tc._has_closing_ratio(stale)

    def test_거래월이_한두_달이면_비교하지_않는다(self):
        rows = [
            {"period": "prior", "gl_account": "410000", "fiscal_period": 12, "amount": 100.0},
            {"period": "current", "gl_account": "410000", "fiscal_period": 12, "amount": 500.0},
        ]
        assert tc._closing_shift_findings_from_ledger(pd.DataFrame(rows)) == []


class TestSortKeyNaN:
    """NaN 은 모든 비교에 False 를 돌려줘 정렬을 조용히 망친다 — 값 없음과 같이 취급."""

    def test_NaN_은_맨_뒤로_보낸다(self):
        assert tc._signed_desc_sort_key(float("nan")) == float("inf")
        assert tc._desc_sort_key(float("nan")) == float("inf")

    def test_NaN_이_섞여도_나머지_순서가_어긋나지_않는다(self):
        findings = [
            _d02_finding("1100", 0.30, 0.35),  # +5.0%p
            _d02_finding("9900", float("nan"), float("nan")),  # 정렬 불가
            _d02_finding("2200", 0.20, 0.62),  # +42.0%p
            _d02_finding("3300", 0.40, 0.25),  # -15.0%p
        ]
        rows = tc._d02_table_rows(findings)

        assert [row["계정"].split()[0] for row in rows] == ["2200", "1100", "3300", "9900"]


class TestRemovedSurfaces:
    def test_달_이름_이동_표기는_폐지됐다(self):
        # "11월 → 12월" 은 몰림의 크기·방향을 말해주지 않아 2026-07-25 제거.
        assert not hasattr(tc, "_month_shift_label")
        assert not hasattr(tc, "_ratio_gap_pp")

    def test_결산월_안내_캡션은_폐지됐다(self):
        # 표 설명은 한 줄만 남긴다(2026-07-25).
        assert not hasattr(tc, "_closing_period_note")


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


class TestRatioDeltaPp:
    def test_비중_증가분을_퍼센트포인트로(self):
        assert tc._ratio_delta_pp(0.2081, 0.6213) == pytest.approx(41.32, abs=0.01)

    def test_줄어들면_음수다(self):
        # 결산월 몰림이 풀린 계정은 아래로 내려가야 하므로 부호를 지우지 않는다.
        assert tc._ratio_delta_pp(0.6, 0.2) == pytest.approx(-40.0)

    def test_값이_없으면_None(self):
        assert tc._ratio_delta_pp(None, 0.5) is None


class TestD02ExclusionNote:
    def test_비교불가로_빠진_계정이_있으면_그_사실만_밝힌다(self):
        diagnostics = [
            {"gl_account": "2600", "skip_reason": ""},
            {"gl_account": "1100", "skip_reason": "insufficient_current_docs"},
            {"gl_account": "1300", "skip_reason": "small_top_month_delta"},
            {"gl_account": "1400", "skip_reason": "insufficient_prior_months"},
        ]
        text = tc._format_d02_exclusion_note(diagnostics)
        assert text == "거래한 달이 너무 적어 분포를 비교할 수 없는 계정은 제외"
        # 세운 계정 수·사유 내역은 화면에서 뺐다(2026-07-25).
        assert "잘라내지 않음" not in text
        assert "전기 거래월 부족" not in text

    def test_폐지된_신호강도_컷은_제외_사유로_쓰지_않는다(self):
        # 전표수·금액·비중변화 하한은 2026-07-25 에 폐지됐다. 목록에 남아야 하므로
        # "제외됐다"고 말하면 거짓 설명이 된다.
        diagnostics = [
            {"gl_account": "1100", "skip_reason": "insufficient_current_docs"},
            {"gl_account": "1200", "skip_reason": "insufficient_current_amount"},
            {"gl_account": "1300", "skip_reason": "small_top_month_delta"},
        ]
        assert tc._format_d02_exclusion_note(diagnostics) == ""

    def test_판정_근거가_없으면_문장을_만들지_않는다(self):
        assert tc._format_d02_exclusion_note([]) == ""


def _d02_finding(account: str, prior_ratio: float | None, current_ratio: float) -> dict:
    return {
        "gl_account": account,
        "metrics": {
            "prior_closing_ratio": prior_ratio,
            "current_closing_ratio": current_ratio,
            "closing_period": 12,
            "current_annual_amount": 1000.0,
        },
    }


class TestTableRowOrder:
    """macro finding 큐가 넘겨준 순서(macro_priority_score)를 표가 그대로 쓰면 안 된다."""

    def test_D02_는_결산월_비중_증가분_순으로_세운다(self):
        # 큐 순서는 증가분과 무관하게 섞여서 온다.
        findings = [
            _d02_finding("1100", 0.30, 0.35),  # +5.0%p
            _d02_finding("2200", 0.20, 0.62),  # +42.0%p
            _d02_finding("3300", 0.40, 0.25),  # -15.0%p
        ]
        rows = tc._d02_table_rows(findings)
        assert [row["계정"].split()[0] for row in rows] == ["2200", "1100", "3300"]
        deltas = [row["증가분(%p)"] for row in rows]
        assert deltas == sorted(deltas, reverse=True)

    def test_D02_결산월_몰림이_풀린_계정은_증가분이_큰_계정보다_아래다(self):
        # 절대값 정렬이면 -40%p 가 +5%p 를 제치고 올라온다. 감사에서 보는 방향은 증가 쪽이다.
        findings = [
            _d02_finding("1100", 0.60, 0.20),  # -40.0%p
            _d02_finding("2200", 0.30, 0.35),  # +5.0%p
        ]
        rows = tc._d02_table_rows(findings)
        assert [row["계정"].split()[0] for row in rows] == ["2200", "1100"]

    def test_D02_증가분을_못_구한_계정은_맨_뒤로(self):
        findings = [
            _d02_finding("1100", None, 0.35),
            _d02_finding("2200", 0.20, 0.62),
        ]
        rows = tc._d02_table_rows(findings)
        assert rows[-1]["증가분(%p)"] is None

    def test_D01_기본_정렬은_금액_변동_절대값_큰_순(self):
        findings = [
            {"gl_account": "1100", "metrics": {"amount_delta": 500.0}},
            {"gl_account": "2200", "metrics": {"amount_delta": -9000.0}},
            {"gl_account": "3300", "metrics": {"amount_delta": 3000.0}},
            {"gl_account": "4400", "metrics": {}},
        ]
        rows = tc._d01_table_rows(findings)
        assert [row["금액 변동"] for row in rows] == [-9000.0, 3000.0, 500.0, None]


def _d01_finding(account: str, amount: tuple, count: tuple) -> dict:
    """(전기, 당기) 쌍으로 D01 finding 을 만든다. 건당 금액은 금액÷건수."""
    prior_amt, current_amt = amount
    prior_cnt, current_cnt = count
    return {
        "gl_account": account,
        "metrics": {
            "reason": "activity_variance",
            "prior_total_amount": prior_amt,
            "current_total_amount": current_amt,
            "amount_delta": current_amt - prior_amt,
            "prior_count": prior_cnt,
            "current_count": current_cnt,
            "prior_avg_amount": prior_amt / prior_cnt,
            "current_avg_amount": current_amt / current_cnt,
        },
    }


class TestD01Axis:
    """세 축을 합성하지 않는다. 고른 축의 열만 내보내고 그 축으로 센다."""

    # 금액 변동은 큰데 건수·건당은 거의 안 변한 계정 vs 그 반대 계정.
    BIG_AMOUNT = _d01_finding("410000", amount=(12_000.0, 31_000.0), count=(1_200, 1_250))
    BIG_COUNT_DROP = _d01_finding("520100", amount=(8_000.0, 7_900.0), count=(2_400, 240))

    def test_금액_축은_금액_변동_큰_계정을_올린다(self):
        rows = tc._d01_table_rows([self.BIG_COUNT_DROP, self.BIG_AMOUNT], "금액")
        assert rows[0]["계정"].split()[0] == "410000"

    def test_건수_축은_건수_급감_계정을_올린다(self):
        # 금액 정렬로는 아래로 밀리던 계정이 건수 축에서는 1위여야 한다.
        rows = tc._d01_table_rows([self.BIG_AMOUNT, self.BIG_COUNT_DROP], "건수")
        assert rows[0]["계정"].split()[0] == "520100"
        assert rows[0]["건수 변동"] == -2160.0

    def test_건당_축은_건당_금액_급등_계정을_올린다(self):
        rows = tc._d01_table_rows([self.BIG_AMOUNT, self.BIG_COUNT_DROP], "건당 금액")
        assert rows[0]["계정"].split()[0] == "520100"

    def test_모르는_축은_기본_축으로_떨어진다(self):
        rows = tc._d01_table_rows([self.BIG_COUNT_DROP, self.BIG_AMOUNT], "없는 축")
        assert rows[0]["계정"].split()[0] == "410000"

    def test_고른_축의_열만_내보낸다(self):
        # 세 축 12열을 한꺼번에 늘어놓으면 어느 숫자가 어느 축인지 읽히지 않는다(2026-07-25).
        row = tc._d01_table_rows([self.BIG_COUNT_DROP], "건수")[0]
        assert list(row) == ["계정", "전기 건수", "당기 건수", "건수 변동", "건수 증감률(%)"]
        # 폐지된 열: 구분(신규 여부는 전기 칸 빈칸으로 읽는다).
        assert "구분" not in row

    def test_축마다_전기_당기_변동_증감률이_모두_채워진다(self):
        # 구 표는 건수에 증감률이 없고 건당에 원값이 없어 "건수 변동 순"을 만들 수 없었다.
        for axis, prefix in (("금액", "금액"), ("건수", "건수"), ("건당 금액", "건당")):
            row = tc._d01_table_rows([self.BIG_COUNT_DROP], axis)[0]
            for column in (
                f"전기 {prefix}",
                f"당기 {prefix}",
                f"{prefix} 변동",
                f"{prefix} 증감률(%)",
            ):
                assert row[column] is not None, f"{column} 이 비어 있다"

    def test_신규_계정은_전기_칸이_비고_변동은_당기_전액(self):
        findings = [
            {
                "gl_account": "999999",
                "metrics": {
                    "reason": "new_account",
                    "current_total_amount": 5_000.0,
                    "prior_total_amount": None,
                    "amount_delta": 5_000.0,
                    "current_count": 10,
                    "prior_count": None,
                    "current_avg_amount": 500.0,
                    "prior_avg_amount": None,
                },
            }
        ]
        amount_row = tc._d01_table_rows(findings, "금액")[0]
        assert amount_row["전기 금액"] is None
        assert amount_row["금액 변동"] == 5_000.0
        # 전기가 없으면 증감률은 정의되지 않는다.
        assert amount_row["금액 증감률(%)"] is None
        count_row = tc._d01_table_rows(findings, "건수")[0]
        assert count_row["건수 변동"] == 10.0
        assert count_row["건수 증감률(%)"] is None


class TestSubtabStructure:
    def test_PHASE2_보조_신호_소분류는_제거됐다(self):
        assert not hasattr(tc, "_render_phase2_subtab")
        assert not hasattr(tc, "_collect_phase2_signal_data")

    def test_검토_후보_등급_도넛은_제거됐다(self):
        assert not hasattr(tc, "_query_risk_dist")
