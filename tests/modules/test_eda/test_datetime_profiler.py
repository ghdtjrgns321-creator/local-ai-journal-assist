"""datetime_profiler 단위 테스트 — 시간형 통계 산출."""

import pandas as pd
import pytest

from src.eda.datetime_profiler import profile_datetime


class TestProfileDatetime:
    """profile_datetime() 함수 테스트."""

    def test_min_max_dates(self):
        """min/max date ISO 형식 검증."""
        s = pd.to_datetime(["2025-01-01", "2025-01-15", "2025-01-31"])
        result = profile_datetime(s)

        assert result["min_date"].startswith("2025-01-01")
        assert result["max_date"].startswith("2025-01-31")

    def test_date_range_days(self):
        """range 계산 검증."""
        s = pd.to_datetime(["2025-01-01", "2025-01-11"])
        result = profile_datetime(s)

        assert result["date_range_days"] == 10

    def test_weekday_distribution(self):
        """요일 분포 — 키가 정수이고 sort_index 순서."""
        s = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-06"])  # Mon, Tue, Mon
        result = profile_datetime(s)

        dist = result["weekday_distribution"]
        assert dist[0] == 2  # Monday 2건
        assert dist[1] == 1  # Tuesday 1건

    def test_monthly_distribution(self):
        """월별 분포 — 키가 정수."""
        s = pd.to_datetime(["2025-01-01", "2025-02-01", "2025-01-15"])
        result = profile_datetime(s)

        dist = result["monthly_distribution"]
        assert dist[1] == 2  # January 2건
        assert dist[2] == 1  # February 1건

    def test_all_nat(self):
        """전체 NaT → 모든 값 None."""
        s = pd.to_datetime([None, None, None])
        result = profile_datetime(s)

        assert result["min_date"] is None
        assert result["max_date"] is None
        assert result["date_range_days"] is None
        assert result["weekday_distribution"] is None
