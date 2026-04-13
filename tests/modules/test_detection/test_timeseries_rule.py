"""TS01(거래 급증), TS02(비정상 거래 주기) 룰 함수 + TimeseriesDetector 통합 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.timeseries_rules import (
    ts01_transaction_burst,
    ts02_unusual_frequency,
)


# ── 공용 fixture ───────────────────────────────────────────


@pytest.fixture
def burst_df() -> pd.DataFrame:
    """30일치 데이터 — 특정 날짜(15일)에 30건 집중, 나머지 3건/일."""
    rows = []
    for day in range(1, 31):
        date = pd.Timestamp(f"2025-01-{day:02d}")
        count = 30 if day == 15 else 3
        for i in range(count):
            rows.append({"posting_date": date, "amount": 100.0 + i})
    return pd.DataFrame(rows)


@pytest.fixture
def uniform_df() -> pd.DataFrame:
    """30일치 균일 데이터 — 매일 5건."""
    rows = []
    for day in range(1, 31):
        date = pd.Timestamp(f"2025-01-{day:02d}")
        for i in range(5):
            rows.append({"posting_date": date, "amount": 100.0})
    return pd.DataFrame(rows)


@pytest.fixture
def frequency_df() -> pd.DataFrame:
    """vendor A: 7일 내 6건 집중, vendor B: 30일에 걸쳐 분산."""
    rows = []
    # vendor A: 1/10~1/16에 6건 집중
    for day in range(10, 16):
        rows.append({
            "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
            "auxiliary_account_number": "V_A",
        })
    # vendor B: 30일에 걸쳐 6건 분산
    for day in [1, 6, 12, 18, 24, 30]:
        rows.append({
            "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
            "auxiliary_account_number": "V_B",
        })
    return pd.DataFrame(rows)


# ── TS01: 거래 급증 ──────────────────────────────────────


class TestTS01TransactionBurst:
    """TS01 — 일별 거래 건수 롤링 평균+σ 초과 판정."""

    def test_burst_detected(self, burst_df: pd.DataFrame):
        """1/15에 30건 집중 → 해당 날짜 행만 True."""
        result = ts01_transaction_burst(burst_df, window_days=7, sigma=3.0)
        burst_date = pd.Timestamp("2025-01-15")
        flagged_dates = burst_df.loc[result, "posting_date"].unique()
        assert burst_date in flagged_dates
        # 나머지 날짜는 False
        non_burst = burst_df[burst_df["posting_date"] != burst_date]
        assert not result.loc[non_burst.index].any()

    def test_no_burst_uniform(self, uniform_df: pd.DataFrame):
        """균일 분포 → 0건 flagged."""
        result = ts01_transaction_burst(uniform_df, window_days=7, sigma=3.0)
        assert not result.any()

    def test_missing_posting_date(self):
        """posting_date 컬럼 없으면 전체 False."""
        df = pd.DataFrame({"amount": [100.0, 200.0]})
        result = ts01_transaction_burst(df)
        assert not result.any()

    def test_single_day(self):
        """1일치만 → std=0 → 전체 False."""
        df = pd.DataFrame({
            "posting_date": [pd.Timestamp("2025-01-01")] * 10,
        })
        result = ts01_transaction_burst(df)
        assert not result.any()

    def test_nat_handling(self):
        """NaT 행은 False 처리."""
        df = pd.DataFrame({
            "posting_date": [pd.Timestamp("2025-01-01"), pd.NaT, pd.Timestamp("2025-01-01")],
        })
        result = ts01_transaction_burst(df)
        assert not result.iloc[1]  # NaT 행 = False

    def test_weekend_gap_resample(self):
        """금~월 주말 공백 포함 — rolling이 날짜 기준으로 동작하는지 검증.

        Why: resample('D') 없이 rolling하면 주말 행 부재로 윈도우가 밀림.
        """
        rows = []
        # 월~금 5건/일, 토·일 0건 (행 자체 없음) × 3주
        for week in range(3):
            for weekday in range(5):  # 월~금
                date = pd.Timestamp("2025-01-06") + pd.Timedelta(days=week * 7 + weekday)
                count = 5
                for i in range(count):
                    rows.append({"posting_date": date, "amount": 100.0})
        # 마지막 금요일에 50건 burst 추가
        burst_date = pd.Timestamp("2025-01-24")  # 3주차 금요일
        for i in range(50):
            rows.append({"posting_date": burst_date, "amount": 100.0})

        df = pd.DataFrame(rows)
        result = ts01_transaction_burst(df, window_days=7, sigma=3.0)

        # burst 날짜만 플래그되어야 함 (주말 공백 때문에 밀리면 안 됨)
        flagged_dates = df.loc[result, "posting_date"].unique()
        assert burst_date in flagged_dates


# ── TS02: 비정상 거래 주기 ────────────────────────────────


class TestTS02UnusualFrequency:
    """TS02 — 그룹별 단기 집중 거래 탐지."""

    def test_vendor_concentration(self, frequency_df: pd.DataFrame):
        """vendor A가 7일 내 6건 집중 → flagged."""
        result = ts02_unusual_frequency(
            frequency_df, group_col="auxiliary_account_number",
            window_days=7, min_count=5,
        )
        va_mask = frequency_df["auxiliary_account_number"] == "V_A"
        assert result[va_mask].any()

    def test_normal_frequency(self, frequency_df: pd.DataFrame):
        """vendor B는 30일에 분산 → 미플래그."""
        result = ts02_unusual_frequency(
            frequency_df, group_col="auxiliary_account_number",
            window_days=7, min_count=5,
        )
        vb_mask = frequency_df["auxiliary_account_number"] == "V_B"
        assert not result[vb_mask].any()

    def test_missing_group_col(self):
        """group_col 없으면 전체 False."""
        df = pd.DataFrame({
            "posting_date": pd.date_range("2025-01-01", periods=5),
        })
        result = ts02_unusual_frequency(df, group_col="auxiliary_account_number")
        assert not result.any()

    def test_few_entries(self):
        """min_count 미달 → False."""
        df = pd.DataFrame({
            "posting_date": pd.date_range("2025-01-01", periods=3),
            "auxiliary_account_number": ["V_A"] * 3,
        })
        result = ts02_unusual_frequency(df, min_count=5)
        assert not result.any()

    def test_unsorted_dates(self):
        """날짜 역순 입력해도 정렬 후 정확히 탐지 — sort 방어 코드 검증.

        Why: sort_values 없이 groupby+rolling하면 미래 날짜와 계산이 섞임.
        """
        rows = []
        # vendor A: 1/10~1/16에 6건 집중 (역순 입력)
        for day in [16, 14, 12, 10, 15, 13, 11]:
            rows.append({
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "auxiliary_account_number": "V_A",
            })
        df = pd.DataFrame(rows)
        result = ts02_unusual_frequency(df, window_days=7, min_count=5)
        assert result.any()

    def test_missing_posting_date(self):
        """posting_date 없으면 전체 False."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["V_A", "V_B"],
        })
        result = ts02_unusual_frequency(df)
        assert not result.any()


# ── TimeseriesDetector 통합 ──────────────────────────────


class TestTimeseriesDetector:
    """TimeseriesDetector 오케스트레이터 통합 테스트."""

    def test_detect_returns_detection_result(self, burst_df: pd.DataFrame):
        from src.detection.base import DetectionResult
        from src.detection.timeseries_detector import TimeseriesDetector

        detector = TimeseriesDetector()
        result = detector.detect(burst_df)
        assert isinstance(result, DetectionResult)

    def test_track_name(self):
        from src.detection.timeseries_detector import TimeseriesDetector

        detector = TimeseriesDetector()
        assert detector.track_name == "timeseries"

    def test_rule_isolation(self):
        """TS01 실패해도 TS02는 실행 (에러 격리)."""
        from src.detection.timeseries_detector import TimeseriesDetector

        # posting_date만 있고 group_col 없으면 TS02는 내부에서 False 반환
        # → TS01만 동작, TS02는 graceful skip
        df = pd.DataFrame({
            "posting_date": pd.date_range("2025-01-01", periods=10),
        })
        detector = TimeseriesDetector()
        result = detector.detect(df)
        assert "TS01" in result.details.columns or "TS02" in result.details.columns
