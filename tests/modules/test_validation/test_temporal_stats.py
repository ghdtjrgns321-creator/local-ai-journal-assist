"""시간 패턴 통계 단위 테스트."""

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.validation.temporal_stats import analyze_temporal_patterns


@pytest.fixture()
def settings() -> AuditSettings:
    return AuditSettings()


class TestTemporalPatterns:

    def test_weekend_ratio(self, settings):
        """주말 거래 30% → weekend_ratio ≈ 0.3."""
        # 7일: 5 평일 + 2 주말
        dates = pd.to_datetime([
            "2025-01-06", "2025-01-07", "2025-01-08",  # 월화수
            "2025-01-09", "2025-01-10",                 # 목금
            "2025-01-11", "2025-01-12",                 # 토일
            "2025-01-06", "2025-01-07", "2025-01-11",   # 추가: 월,화,토
        ])
        df = pd.DataFrame({
            "posting_date": dates,
            "debit_amount": [100.0] * 10,
            "credit_amount": [0.0] * 10,
        })
        result, _ = analyze_temporal_patterns(df, settings=settings)

        assert abs(result.weekend_ratio - 0.3) < 0.01
        assert 5 in result.weekday_volume or 6 in result.weekday_volume

    def test_period_end_concentration(self, settings):
        """월말 5일 집중 → period_end_concentration 높음."""
        # 모두 월말 근처
        dates = pd.to_datetime([
            "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
            "2025-02-26", "2025-02-27", "2025-02-28",
        ])
        df = pd.DataFrame({
            "posting_date": dates,
            "debit_amount": [100.0] * 7,
            "credit_amount": [0.0] * 7,
        })
        result, _ = analyze_temporal_patterns(df, settings=settings)

        assert result.period_end_concentration > 0.8

    def test_no_posting_date(self, settings):
        """posting_date 없음 → 빈 결과 + 경고."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        result, warnings = analyze_temporal_patterns(df, settings=settings)

        assert result.weekday_volume == {}
        assert result.weekend_ratio == 0.0
        assert any("posting_date" in w for w in warnings)

    def test_yoy_single_year_none(self, settings):
        """단일 연도 → yoy_change=None."""
        dates = pd.to_datetime(["2025-01-15", "2025-02-15", "2025-03-15"])
        df = pd.DataFrame({
            "posting_date": dates,
            "debit_amount": [100.0, 200.0, 150.0],
            "credit_amount": [0.0] * 3,
        })
        result, _ = analyze_temporal_patterns(df, settings=settings)

        assert result.yoy_change is None

    def test_yoy_multi_year(self, settings):
        """2개 연도 → yoy_change 산출."""
        dates = pd.to_datetime([
            "2024-01-15", "2024-02-15", "2024-03-15",
            "2025-01-15", "2025-02-15", "2025-03-15",
        ])
        df = pd.DataFrame({
            "posting_date": dates,
            "debit_amount": [100.0, 200.0, 150.0, 120.0, 220.0, 180.0],
            "credit_amount": [0.0] * 6,
        })
        result, _ = analyze_temporal_patterns(df, settings=settings)

        assert result.yoy_change is not None
        assert "01" in result.yoy_change
        # 1월: 100→120, YoY = 0.2
        assert abs(result.yoy_change["01"] - 0.2) < 0.01

    def test_weekday_volume_keys(self, settings):
        """weekday_volume 키가 0~6 범위 int."""
        dates = pd.date_range("2025-01-06", periods=7, freq="D")
        df = pd.DataFrame({
            "posting_date": dates,
            "debit_amount": [100.0] * 7,
        })
        result, _ = analyze_temporal_patterns(df, settings=settings)

        for key in result.weekday_volume:
            assert 0 <= key <= 6
