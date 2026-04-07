"""time_features.py 단위 테스트.

6개 시간 파생변수 + 헬퍼 함수 + 오케스트레이터 검증.
numpy bool과 Python bool 비교 이슈 → == 연산자 사용.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.feature.time_features import (
    _build_holiday_set,
    _has_time_info,
    add_all_time_features,
    add_days_backdated,
    add_fiscal_period_mismatch,
    add_is_after_hours,
    add_is_holiday,
    add_is_period_end,
    add_is_weekend,
)


# ══════════════════════════════════════════════════════════════════
# Helper tests
# ══════════════════════════════════════════════════════════════════


class TestBuildHolidaySet:
    """_build_holiday_set 헬퍼 테스트."""

    def test_kr_holidays_included(self):
        """2025년 신정(1/1)이 포함되어야 한다."""
        result = _build_holiday_set({2025}, [])
        assert date(2025, 1, 1) in result

    def test_custom_holidays_merged(self):
        """회사 지정 휴일이 병합되어야 한다."""
        result = _build_holiday_set({2025}, ["2025-07-01"])
        assert date(2025, 7, 1) in result

    def test_invalid_custom_date_skipped(self):
        """잘못된 날짜 형식은 건너뛰고 경고만."""
        result = _build_holiday_set({2025}, ["not-a-date", "2025-12-25"])
        assert date(2025, 12, 25) in result


class TestHasTimeInfo:
    """_has_time_info 헬퍼 테스트."""

    def test_with_time(self):
        """시간 정보가 있는 Series → True."""
        s = pd.Series(pd.to_datetime(["2025-01-01 10:00", "2025-01-02 14:30"]))
        assert _has_time_info(s) is True

    def test_without_time(self):
        """모두 00:00:00 → False."""
        s = pd.Series(pd.to_datetime(["2025-01-01", "2025-01-02"]))
        assert _has_time_info(s) is False

    def test_empty_series(self):
        """빈 Series → False."""
        s = pd.Series(dtype="datetime64[ns]")
        assert _has_time_info(s) is False

    def test_all_nat(self):
        """전부 NaT → False."""
        s = pd.Series(pd.to_datetime([None, None]))
        assert _has_time_info(s) is False


# ══════════════════════════════════════════════════════════════════
# is_weekend
# ══════════════════════════════════════════════════════════════════


class TestIsWeekend:
    """add_is_weekend 테스트."""

    def test_saturday_true(self, tf_base_df):
        """토요일(idx=1: 2025-01-04) → True."""
        add_is_weekend(tf_base_df)
        assert tf_base_df.loc[1, "is_weekend"] == True  # noqa: E712

    def test_sunday_true(self, tf_base_df):
        """일요일(idx=2: 2025-01-05) → True."""
        add_is_weekend(tf_base_df)
        assert tf_base_df.loc[2, "is_weekend"] == True  # noqa: E712

    def test_weekday_false(self, tf_base_df):
        """월~금(idx=0,3,4,5) → False."""
        add_is_weekend(tf_base_df)
        for idx in [0, 3, 4, 5]:
            assert tf_base_df.loc[idx, "is_weekend"] == False  # noqa: E712

    def test_nat_false(self, tf_nat_df):
        """NaT → False (fillna)."""
        add_is_weekend(tf_nat_df)
        assert (tf_nat_df["is_weekend"] == False).all()  # noqa: E712


# ══════════════════════════════════════════════════════════════════
# is_after_hours
# ══════════════════════════════════════════════════════════════════


class TestIsAfterHours:
    """add_is_after_hours 테스트."""

    def test_23h_true(self, tf_base_df):
        """23:30(idx=1) → True (기본 22~6)."""
        add_is_after_hours(tf_base_df)
        assert tf_base_df.loc[1, "is_after_hours"] == True  # noqa: E712

    def test_03h_true(self, tf_base_df):
        """03:00(idx=2) → True."""
        add_is_after_hours(tf_base_df)
        assert tf_base_df.loc[2, "is_after_hours"] == True  # noqa: E712

    def test_10h_false(self, tf_base_df):
        """10:00(idx=0) → False."""
        add_is_after_hours(tf_base_df)
        assert tf_base_df.loc[0, "is_after_hours"] == False  # noqa: E712

    def test_14h_false(self, tf_base_df):
        """14:00(idx=3) → False."""
        add_is_after_hours(tf_base_df)
        assert tf_base_df.loc[3, "is_after_hours"] == False  # noqa: E712

    def test_no_time_info_all_false(self, tf_no_time_df):
        """시간정보 없으면 전체 False + 경고."""
        add_is_after_hours(tf_no_time_df)
        assert (tf_no_time_df["is_after_hours"] == False).all()  # noqa: E712

    def test_start_less_than_end(self):
        """start < end (예: 1~5) — 단순 구간 테스트."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime([
                "2025-01-01 02:00",  # True (1 ≤ 2 < 5)
                "2025-01-01 05:00",  # False (5 not < 5)
                "2025-01-01 00:30",  # False (0 < 1)
                "2025-01-01 10:00",  # False
            ]),
        })
        add_is_after_hours(df, start=1, end=5)
        assert list(df["is_after_hours"]) == [True, False, False, False]

    def test_start_equals_end_all_false(self):
        """start == end → 전체 False (구간 없음)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01 06:00", "2025-01-01 22:00"]),
        })
        add_is_after_hours(df, start=6, end=6)
        assert (df["is_after_hours"] == False).all()  # noqa: E712


# ══════════════════════════════════════════════════════════════════
# is_period_end
# ══════════════════════════════════════════════════════════════════


class TestIsPeriodEnd:
    """add_is_period_end 테스트 (양방향: 월말 전 + 익월 초)."""

    def test_month_end_day_true(self, tf_base_df):
        """월말 당일(idx=5: 1/31) → True."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[5, "is_period_end"] == True  # noqa: E712

    def test_month_end_minus4_true(self, tf_base_df):
        """월말 3일전(idx=4: 1/28, 31-28=3) → True (margin=5 이내)."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[4, "is_period_end"] == True  # noqa: E712

    def test_next_month_day1_true(self, tf_base_df):
        """익월 1일(idx=0: 1/1, day=1) → True (margin=5 이내)."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[0, "is_period_end"] == True  # noqa: E712

    def test_next_month_day3_true(self, tf_base_df):
        """익월 초(idx=7: 3/1, day=1) → True."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[7, "is_period_end"] == True  # noqa: E712

    def test_mid_month_false(self, tf_base_df):
        """월 중순(idx=3: 1/6, day=6, 31-6=25) → False (margin=5 밖)."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[3, "is_period_end"] == False  # noqa: E712

    def test_feb28_true(self, tf_base_df):
        """2월 28일 평년 말일(idx=6) → True."""
        add_is_period_end(tf_base_df, margin=5)
        assert tf_base_df.loc[6, "is_period_end"] == True  # noqa: E712

    def test_leap_year_feb29(self):
        """윤년 2/29 → True (월말 당일)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2024-02-29 12:00"]),
        })
        add_is_period_end(df, margin=5)
        assert df.loc[0, "is_period_end"] == True  # noqa: E712

    def test_margin_zero_only_month_end(self):
        """margin=0 → 월말 당일만 True, 익월 초(day≥1)는 False."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime([
                "2025-01-31",  # 월말 당일 → True
                "2025-02-01",  # 익월 1일 → False (day=1 > 0)
                "2025-01-15",  # 중순 → False
            ]),
        })
        add_is_period_end(df, margin=0)
        assert list(df["is_period_end"]) == [True, False, False]

    def test_nat_false(self, tf_nat_df):
        """NaT → False."""
        add_is_period_end(tf_nat_df, margin=5)
        assert (tf_nat_df["is_period_end"] == False).all()  # noqa: E712


# ══════════════════════════════════════════════════════════════════
# days_backdated
# ══════════════════════════════════════════════════════════════════


class TestDaysBackdated:
    """add_days_backdated 테스트 — 부호 유지."""

    def test_positive_late_recording(self, tf_base_df):
        """posting > document → 양수 (지연전기). idx=1: 1/4 - 12/30 = +5."""
        add_days_backdated(tf_base_df)
        assert tf_base_df.loc[1, "days_backdated"] == 5

    def test_negative_forward_recording(self, tf_base_df):
        """posting < document → 음수 (선전기). idx=2: 1/5 - 1/10 = -5."""
        add_days_backdated(tf_base_df)
        assert tf_base_df.loc[2, "days_backdated"] == -5

    def test_zero_same_day(self, tf_base_df):
        """당일 → 0. idx=0: 1/1 - 1/1 = 0."""
        add_days_backdated(tf_base_df)
        assert tf_base_df.loc[0, "days_backdated"] == 0

    def test_nat_document_date_nan(self, tf_base_df):
        """document_date NaT → NaN. idx=6."""
        add_days_backdated(tf_base_df)
        assert pd.isna(tf_base_df.loc[6, "days_backdated"])

    def test_no_document_date_column(self):
        """document_date 컬럼 없으면 전체 NaN."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-01"]),
        })
        add_days_backdated(df)
        assert pd.isna(df.loc[0, "days_backdated"])

    def test_dtype_int64(self, tf_base_df):
        """결과 dtype이 Int64(nullable)여야 한다."""
        add_days_backdated(tf_base_df)
        assert tf_base_df["days_backdated"].dtype == "Int64"


# ══════════════════════════════════════════════════════════════════
# fiscal_period_mismatch
# ══════════════════════════════════════════════════════════════════


class TestFiscalPeriodMismatch:
    """add_fiscal_period_mismatch 테스트."""

    def test_standard_match_false(self, tf_base_df):
        """표준(start=1): 1월, period=1 → False. idx=0."""
        add_fiscal_period_mismatch(tf_base_df, fiscal_year_start=1)
        assert tf_base_df.loc[0, "fiscal_period_mismatch"] == False  # noqa: E712

    def test_standard_mismatch_true(self):
        """표준(start=1): 1월, period=5 → True."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-15"]),
            "fiscal_period": pd.array([5], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=1)
        assert df.loc[0, "fiscal_period_mismatch"] == True  # noqa: E712

    def test_nonstandard_april_match(self):
        """비표준(start=4): 4월, period=1 → False (기대 기수=1)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-04-15"]),
            "fiscal_period": pd.array([1], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=4)
        assert df.loc[0, "fiscal_period_mismatch"] == False  # noqa: E712

    def test_nonstandard_march_period12(self):
        """비표준(start=4): 3월, period=12 → False."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-03-15"]),
            "fiscal_period": pd.array([12], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=4)
        assert df.loc[0, "fiscal_period_mismatch"] == False  # noqa: E712

    def test_nonstandard_mismatch(self):
        """비표준(start=4): 1월, period=5 → True (기대=10, 실제=5)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-15"]),
            "fiscal_period": pd.array([5], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=4)
        assert df.loc[0, "fiscal_period_mismatch"] == True  # noqa: E712

    def test_nat_posting_returns_na(self):
        """posting_date NaT → pd.NA (오탐 방지)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime([None]),
            "fiscal_period": pd.array([1], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=1)
        assert pd.isna(df.loc[0, "fiscal_period_mismatch"])

    def test_nan_fiscal_period_returns_na(self):
        """fiscal_period NaN → pd.NA (오탐 방지)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-15"]),
            "fiscal_period": pd.array([pd.NA], dtype="Int64"),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=1)
        assert pd.isna(df.loc[0, "fiscal_period_mismatch"])

    def test_no_fiscal_period_column(self):
        """fiscal_period 컬럼 없으면 전체 pd.NA."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-01-15"]),
        })
        add_fiscal_period_mismatch(df, fiscal_year_start=1)
        assert pd.isna(df.loc[0, "fiscal_period_mismatch"])

    def test_dtype_boolean(self, tf_base_df):
        """결과 dtype이 boolean(nullable)이어야 한다."""
        add_fiscal_period_mismatch(tf_base_df, fiscal_year_start=1)
        assert tf_base_df["fiscal_period_mismatch"].dtype == "boolean"


# ══════════════════════════════════════════════════════════════════
# is_holiday
# ══════════════════════════════════════════════════════════════════


class TestIsHoliday:
    """add_is_holiday 테스트."""

    def test_new_year_true(self, tf_base_df):
        """신정(1/1, idx=0) → True."""
        add_is_holiday(tf_base_df)
        assert tf_base_df.loc[0, "is_holiday"] == True  # noqa: E712

    def test_march1_true(self, tf_base_df):
        """삼일절(3/1, idx=7) → True."""
        add_is_holiday(tf_base_df)
        assert tf_base_df.loc[7, "is_holiday"] == True  # noqa: E712

    def test_weekday_false(self, tf_base_df):
        """평일·비공휴일(idx=3: 1/6 월요일) → False."""
        add_is_holiday(tf_base_df)
        assert tf_base_df.loc[3, "is_holiday"] == False  # noqa: E712

    def test_custom_holiday_added(self, tf_base_df):
        """회사 지정 휴일(1/6) → True."""
        add_is_holiday(tf_base_df, custom=["2025-01-06"])
        assert tf_base_df.loc[3, "is_holiday"] == True  # noqa: E712

    def test_nat_false(self, tf_nat_df):
        """NaT → False."""
        add_is_holiday(tf_nat_df)
        assert (tf_nat_df["is_holiday"] == False).all()  # noqa: E712


# ══════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════


class TestAddAllTimeFeatures:
    """add_all_time_features 통합 테스트."""

    def test_all_columns_created(self, tf_base_df):
        """6개 컬럼이 모두 생성되어야 한다."""
        add_all_time_features(tf_base_df)
        expected = {
            "is_weekend", "is_after_hours", "is_period_end",
            "days_backdated", "fiscal_period_mismatch", "is_holiday",
        }
        assert expected.issubset(set(tf_base_df.columns))

    def test_with_custom_settings(self, tf_base_df):
        """settings 파라미터로 커스텀 값 전달."""
        from config.settings import AuditSettings

        s = AuditSettings(
            midnight_start=20,
            midnight_end=8,
            period_end_margin_days=3,
            fiscal_year_start=4,
            custom_holidays=["2025-01-06"],
        )
        add_all_time_features(tf_base_df, settings=s)
        # margin=3이면 1/6(day=6)은 period_end가 아님
        assert tf_base_df.loc[3, "is_period_end"] == False  # noqa: E712
        # custom_holidays에 1/6 추가했으므로 공휴일
        assert tf_base_df.loc[3, "is_holiday"] == True  # noqa: E712
