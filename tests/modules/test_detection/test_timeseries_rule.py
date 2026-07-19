"""Timeseries family — sub-signal continuous score + TimeseriesDetector 통합 테스트.

Why: rule-style boolean → robust z-score + zero-preserving ECDF + period-end
     concentration 결합으로 격상. 본 테스트는 legacy boolean 함수 호환과 신규
     sub-signal continuous score / detector contract 양쪽을 모두 잠근다.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.detection.timeseries_rules import (
    daily_burst_positive_robust_z_score,
    group_frequency_positive_robust_z_score,
    period_end_concentration_score,
    ts01_transaction_burst,
    ts02_unusual_frequency,
    zero_preserving_ecdf,
)

__all__ = (
    "json",
    "daily_burst_positive_robust_z_score",
    "group_frequency_positive_robust_z_score",
    "period_end_concentration_score",
    "ts01_transaction_burst",
    "ts02_unusual_frequency",
    "zero_preserving_ecdf",
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
        rows.append(
            {
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "auxiliary_account_number": "V_A",
            }
        )
    # vendor B: 30일에 걸쳐 6건 분산
    for day in [1, 6, 12, 18, 24, 30]:
        rows.append(
            {
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "auxiliary_account_number": "V_B",
            }
        )
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
        df = pd.DataFrame(
            {
                "posting_date": [pd.Timestamp("2025-01-01")] * 10,
            }
        )
        result = ts01_transaction_burst(df)
        assert not result.any()

    def test_nat_handling(self):
        """NaT 행은 False 처리."""
        df = pd.DataFrame(
            {
                "posting_date": [pd.Timestamp("2025-01-01"), pd.NaT, pd.Timestamp("2025-01-01")],
            }
        )
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
            frequency_df,
            group_col="auxiliary_account_number",
            window_days=7,
            min_count=5,
        )
        va_mask = frequency_df["auxiliary_account_number"] == "V_A"
        assert result[va_mask].any()

    def test_normal_frequency(self, frequency_df: pd.DataFrame):
        """vendor B는 30일에 분산 → 미플래그."""
        result = ts02_unusual_frequency(
            frequency_df,
            group_col="auxiliary_account_number",
            window_days=7,
            min_count=5,
        )
        vb_mask = frequency_df["auxiliary_account_number"] == "V_B"
        assert not result[vb_mask].any()

    def test_missing_group_col(self):
        """group_col 없으면 전체 False."""
        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=5),
            }
        )
        result = ts02_unusual_frequency(df, group_col="auxiliary_account_number")
        assert not result.any()

    def test_few_entries(self):
        """min_count 미달 → False."""
        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=3),
                "auxiliary_account_number": ["V_A"] * 3,
            }
        )
        result = ts02_unusual_frequency(df, min_count=5)
        assert not result.any()

    def test_unsorted_dates(self):
        """날짜 역순 입력해도 정렬 후 정확히 탐지 — sort 방어 코드 검증.

        Why: sort_values 없이 groupby+rolling하면 미래 날짜와 계산이 섞임.
        """
        rows = []
        # vendor A: 1/10~1/16에 6건 집중 (역순 입력)
        for day in [16, 14, 12, 10, 15, 13, 11]:
            rows.append(
                {
                    "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                    "auxiliary_account_number": "V_A",
                }
            )
        df = pd.DataFrame(rows)
        result = ts02_unusual_frequency(df, window_days=7, min_count=5)
        assert result.any()

    def test_missing_posting_date(self):
        """posting_date 없으면 전체 False."""
        df = pd.DataFrame(
            {
                "auxiliary_account_number": ["V_A", "V_B"],
            }
        )
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
        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=10),
            }
        )
        detector = TimeseriesDetector()
        result = detector.detect(df)
        assert "TS01" in result.details.columns or "TS02" in result.details.columns


# ── Sub-signal continuous score ─────────────────────────


@pytest.fixture
def long_uniform_df() -> pd.DataFrame:
    """90일 균일 분포 — baseline 안정."""
    rows = []
    for day in range(90):
        date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day)
        for _ in range(5):
            rows.append({"posting_date": date, "amount": 100.0})
    return pd.DataFrame(rows)


@pytest.fixture
def long_burst_df(long_uniform_df: pd.DataFrame) -> pd.DataFrame:
    """균일 + 강도 다른 3개 burst (분해능 검증용)."""
    extra_rows: list[dict] = []
    # 강한 burst — 단일일 60건
    extra_rows.extend(
        {"posting_date": pd.Timestamp("2025-02-15"), "amount": 100.0} for _ in range(60)
    )
    # 중간 burst — 단일일 25건
    extra_rows.extend(
        {"posting_date": pd.Timestamp("2025-01-30"), "amount": 100.0} for _ in range(25)
    )
    # 약한 burst — 단일일 12건
    extra_rows.extend(
        {"posting_date": pd.Timestamp("2025-03-10"), "amount": 100.0} for _ in range(12)
    )
    return pd.concat([long_uniform_df, pd.DataFrame(extra_rows)], ignore_index=True)


@pytest.fixture
def long_drop_df(long_uniform_df: pd.DataFrame) -> pd.DataFrame:
    """80일 균일 데이터에서 특정 날짜만 0건 (burst가 아닌 drop)."""
    drop_date = pd.Timestamp("2025-02-15")
    return long_uniform_df[long_uniform_df["posting_date"] != drop_date].reset_index(drop=True)


class TestZeroPreservingEcdf:
    """zero-preserving ECDF — 0점 행은 0 유지."""

    def test_zero_rows_stay_zero(self):
        scores = pd.Series([0.0, 0.0, 0.5, 1.2, 0.0, 3.7])
        ecdf = zero_preserving_ecdf(scores)
        assert ecdf.iloc[0] == 0.0
        assert ecdf.iloc[1] == 0.0
        assert ecdf.iloc[4] == 0.0
        # 양수 행은 0보다 큰 percentile 부여
        assert (ecdf.iloc[[2, 3, 5]] > 0).all()

    def test_nan_treated_as_zero(self):
        scores = pd.Series([float("nan"), 0.5, float("nan"), 1.5])
        ecdf = zero_preserving_ecdf(scores)
        assert ecdf.iloc[0] == 0.0
        assert ecdf.iloc[2] == 0.0
        assert ecdf.iloc[1] > 0
        assert ecdf.iloc[3] > 0

    def test_all_zero_returns_all_zero(self):
        scores = pd.Series([0.0, 0.0, 0.0])
        ecdf = zero_preserving_ecdf(scores)
        assert (ecdf == 0.0).all()


class TestDailyBurstPositiveRobustZScore:
    """S1 — 일별 burst robust z-score (positive only)."""

    def test_burst_produces_positive_score(self, long_burst_df: pd.DataFrame):
        result = daily_burst_positive_robust_z_score(long_burst_df, window_days=14)
        assert result.active is True
        burst_date = pd.Timestamp("2025-02-15")
        burst_mask = pd.to_datetime(long_burst_df["posting_date"]).dt.normalize() == burst_date
        assert (result.score[burst_mask] > 0).all()
        # 정상 baseline 행은 0 또는 매우 낮은 score
        assert result.score[~burst_mask].max() < result.score[burst_mask].max()

    def test_uniform_baseline_low_score(self, long_uniform_df: pd.DataFrame):
        """균일 분포 → robust z ≈ 0 → 양수 score 거의 없음."""
        result = daily_burst_positive_robust_z_score(long_uniform_df, window_days=14)
        assert result.active is True
        # 균일 분포에서 일부 미세 변동이 양수 z를 만들 수 있으나 최대값이 매우 낮음
        assert result.meta["raw_max_positive_z"] < 1.0

    def test_drop_is_not_burst(self, long_drop_df: pd.DataFrame):
        """거래량 급감 (음의 z) 은 burst 가 아니므로 score 0."""
        result = daily_burst_positive_robust_z_score(long_drop_df, window_days=14)
        # drop 날짜는 행 자체가 없음. 남은 행들은 정상 baseline → 양수 z 거의 없음.
        assert result.meta["raw_max_positive_z"] < 1.5

    def test_missing_posting_date(self):
        df = pd.DataFrame({"amount": [100.0, 200.0]})
        result = daily_burst_positive_robust_z_score(df)
        assert result.active is False
        assert result.meta["reason"] == "missing_posting_date"
        assert (result.score == 0).all()

    def test_single_day_returns_inactive(self):
        df = pd.DataFrame({"posting_date": [pd.Timestamp("2025-01-01")] * 5})
        result = daily_burst_positive_robust_z_score(df)
        assert result.active is False


class TestGroupFrequencyPositiveRobustZScore:
    """S2 — 그룹 단기 빈도 robust z-score (positive only)."""

    def test_concentration_produces_positive_score(self):
        rows = []
        # vendor A: 60일 동안 매 20일마다 1건 (sparse baseline) + 1/10~1/16에 6건 집중
        for day in [1, 21, 41, 61]:
            rows.append(
                {
                    "posting_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=day),
                    "auxiliary_account_number": "V_A",
                }
            )
        for day in range(10, 17):
            rows.append(
                {
                    "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                    "auxiliary_account_number": "V_A",
                }
            )
        # vendor B: 60일에 걸쳐 균일 분산
        for day in [1, 8, 15, 22, 29, 36, 43, 50, 57]:
            rows.append(
                {
                    "posting_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=day),
                    "auxiliary_account_number": "V_B",
                }
            )
        df = pd.DataFrame(rows)
        result = group_frequency_positive_robust_z_score(df, window_days=7, min_support=5)
        assert result.active is True
        va_mask = df["auxiliary_account_number"] == "V_A"
        vb_mask = df["auxiliary_account_number"] == "V_B"
        assert result.score[va_mask].max() > result.score[vb_mask].max()
        assert result.meta["group_col"] == "auxiliary_account_number"

    def test_small_support_groups_skipped(self):
        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=3),
                "auxiliary_account_number": ["V_A"] * 3,
            }
        )
        result = group_frequency_positive_robust_z_score(df, min_support=5)
        # min_support 미달 → 모두 0
        assert (result.score == 0).all()

    def test_no_group_column_inactive(self):
        df = pd.DataFrame({"posting_date": pd.date_range("2025-01-01", periods=10)})
        result = group_frequency_positive_robust_z_score(df)
        assert result.active is False
        assert result.meta["reason"] == "no_group_column"

    def test_fallback_to_trading_partner(self):
        df = pd.DataFrame(
            {
                "posting_date": list(pd.date_range("2025-01-10", periods=7))
                + list(pd.date_range("2025-02-01", periods=7, freq="3D")),
                "trading_partner": ["TP_A"] * 7 + ["TP_B"] * 7,
            }
        )
        result = group_frequency_positive_robust_z_score(df, window_days=7, min_support=5)
        assert result.active is True
        assert result.meta["group_col"] == "trading_partner"


class TestPeriodEndConcentrationScore:
    """S3 — 월말/분기말/연말 근접도 × 일자 거래량 percentile."""

    def test_month_end_concentration_emits_score(self):
        """월말 ±3일 집중 + 해당 일자 거래량 percentile 상위 → 양수 score."""
        rows = []
        # 1월 평상시: 매일 2건
        for day in range(1, 28):
            for _ in range(2):
                rows.append({"posting_date": pd.Timestamp(f"2025-01-{day:02d}")})
        # 1월 말 (28~31) 집중 — 일자별 거래량 모집단 상위 percentile.
        for day in [28, 29, 30, 31]:
            for _ in range(30):
                rows.append({"posting_date": pd.Timestamp(f"2025-01-{day:02d}")})
        df = pd.DataFrame(rows)
        result = period_end_concentration_score(df, proximity_window_days=3)
        assert result.active is True
        period_end_mask = pd.to_datetime(df["posting_date"]).dt.day >= 28
        assert (result.score[period_end_mask] > 0).any()
        # 월 중반 행은 proximity=0 → score=0
        mid_mask = pd.to_datetime(df["posting_date"]).dt.day == 15
        assert (result.score[mid_mask] == 0).all()

    def test_missing_posting_date_inactive(self):
        df = pd.DataFrame({"amount": [1.0, 2.0]})
        result = period_end_concentration_score(df)
        assert result.active is False
        assert result.meta["reason"] == "missing_posting_date"

    def test_sub_signal_only_marker(self):
        rows = [{"posting_date": pd.Timestamp(f"2025-01-{day:02d}")} for day in range(1, 31)]
        result = period_end_concentration_score(pd.DataFrame(rows))
        assert result.meta.get("sub_signal_only") is True

    def test_proximity_within_window_all_positive(self):
        """D-3 ~ D0 모두 양수 가중치 — 1 - distance/(window+1) 분모 보정 검증.

        Why: 이전 식 1 - distance/window 는 D-window 일자 score 가 0 으로 떨어졌다.
             감사 도메인상 "D-3 이내 결산 집중"은 D-3 도 신호여야 하므로 분모를
             (window+1) 로 두어 단조 감소 + window 끝도 양수가 되도록 잠근다.
        """
        rows: list[dict] = []
        for day in [28, 29, 30, 31]:  # 1월 D-3, D-2, D-1, D0
            for _ in range(20):  # daily_pctile_tail 도 양수가 되도록 충분히 큰 일일 거래량
                rows.append({"posting_date": pd.Timestamp(f"2025-01-{day:02d}")})
        # 정상 baseline (1~27일, 매일 2건)
        for day in range(1, 28):
            for _ in range(2):
                rows.append({"posting_date": pd.Timestamp(f"2025-01-{day:02d}")})
        df = pd.DataFrame(rows)
        result = period_end_concentration_score(df, proximity_window_days=3)
        dates = pd.to_datetime(df["posting_date"])

        # D-3, D-2, D-1, D0 모두 양수 (이전 식에서는 D-3 이 0 이었음).
        for day, label in [(28, "D-3"), (29, "D-2"), (30, "D-1"), (31, "D0")]:
            mask = dates.dt.day == day
            assert result.score[mask].max() > 0, f"{label} (day={day}) 가 0 입니다"

        # 단조성: D0 ≥ D-1 ≥ D-2 ≥ D-3
        scores_by_day = {
            day: float(result.score[dates.dt.day == day].max()) for day in [28, 29, 30, 31]
        }
        assert scores_by_day[31] >= scores_by_day[30]
        assert scores_by_day[30] >= scores_by_day[29]
        assert scores_by_day[29] >= scores_by_day[28]

        # window+1 (= D-4) 는 0
        d_minus_4_mask = dates.dt.day == 27
        assert result.score[d_minus_4_mask].max() == 0


# ── TimeseriesDetector statistical anomaly contract ─────


class TestTimeseriesDetectorStatistical:
    """Detector contract — continuous score + ECDF threshold + metadata 직렬화."""

    def test_burst_emits_ts01_flag_and_continuous_score(self, long_burst_df: pd.DataFrame):
        from src.detection.timeseries_detector import TimeseriesDetector

        detector = TimeseriesDetector()
        result = detector.detect(long_burst_df)

        # Why: row score 가 기존 0/0.4/0.8 3 값 이산에서 탈출했는지 검증.
        #      burst 강도 다른 3 일을 fixture 에 둬서 score 분해능 확보.
        nonzero_scores = result.scores[result.scores > 0]
        unique_levels = sorted(float(x) for x in nonzero_scores.unique())
        assert len(unique_levels) >= 3
        # 분해능 — 강한 burst 는 약한 burst 보다 더 큰 row score
        assert unique_levels[-1] > unique_levels[0]
        # burst 날짜에 TS01 flag 발생
        burst_date = pd.Timestamp("2025-02-15")
        burst_idx = long_burst_df.index[
            pd.to_datetime(long_burst_df["posting_date"]).dt.normalize() == burst_date
        ]
        assert (result.details.loc[burst_idx, "TS01"] > 0).any()

    def test_uniform_baseline_minimal_flags(self, long_uniform_df: pd.DataFrame):
        from src.detection.timeseries_detector import TimeseriesDetector

        detector = TimeseriesDetector()
        result = detector.detect(long_uniform_df)

        # 균일 분포에서 TS01/TS02 flag 매우 적음 (false positive 위험 최소)
        ts01_rate = (result.details.get("TS01", pd.Series(dtype=float)) > 0).mean()
        assert ts01_rate < 0.10

    def test_skipped_when_posting_date_missing(self):
        from src.detection.timeseries_detector import TimeseriesDetector

        df = pd.DataFrame({"amount": [100.0, 200.0, 300.0]})
        detector = TimeseriesDetector()
        result = detector.detect(df)
        assert result.metadata.get("run_status") == "skipped"
        assert (result.scores == 0).all()
        assert (
            result.metadata.get("skip_reason")
            in {
                "no_active_sub_signals",
                None,
            }
            or result.warnings
        )

    def test_metadata_sub_signals_json_serializable(self, long_burst_df: pd.DataFrame):
        from src.detection.timeseries_detector import TimeseriesDetector

        detector = TimeseriesDetector()
        result = detector.detect(long_burst_df)

        # metadata.sub_signals 는 DataFrame/Series 없이 JSON 직렬화 가능해야 함
        payload = {
            "sub_signals": result.metadata["sub_signals"],
            "score_distribution": result.metadata["score_distribution"],
        }
        encoded = json.dumps(payload, default=str)
        assert "sub_signals" in encoded
        # 각 sub-signal 항목은 name/active/meta 키 보유
        for entry in result.metadata["sub_signals"]:
            assert {"name", "active", "meta"}.issubset(entry.keys())

    def test_no_phase1_dependency(self):
        """flagged_rules/review_rules 컬럼 없이도 정상 동작."""
        from src.detection.timeseries_detector import TimeseriesDetector

        rows = []
        for day in range(60):
            date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day)
            for _ in range(4):
                rows.append({"posting_date": date, "auxiliary_account_number": "V_A"})
        df = pd.DataFrame(rows)
        assert "flagged_rules" not in df.columns
        assert "review_rules" not in df.columns

        detector = TimeseriesDetector()
        result = detector.detect(df)
        assert result.track_name == "timeseries"
        # 정상 baseline → flag 비율 낮음
        assert len(result.flagged_indices) < len(df) * 0.10

    def test_zero_rows_stay_zero_in_row_score(self):
        """양수 z 가 없는 행은 ECDF 후에도 score=0 유지."""
        from src.detection.timeseries_detector import TimeseriesDetector

        # 매우 단조로운 데이터 → s1, s2, s3 모두 거의 0
        rows = [
            {
                "posting_date": pd.Timestamp("2025-06-15") + pd.Timedelta(days=d),
                "auxiliary_account_number": "V_A",
            }
            for d in range(20)
            for _ in range(3)
        ]
        df = pd.DataFrame(rows)
        detector = TimeseriesDetector()
        result = detector.detect(df)
        zero_rate = float((result.scores == 0).mean())
        # 절반 이상 행은 0 score 유지 (zero-preserving 검증)
        assert zero_rate >= 0.5


# ── period_end context gating ──────────────────────────


class TestPeriodEndContextGating:
    """period_end_concentration 이 단독 strong anomaly 가 되지 않는지 검증.

    Why: ISA 240 ¶A41 의 routine 결산기 거래는 unusual 아님. unusual 로 격상하려면
         amount/frequency/volume baseline 이상 신호가 함께 있어야 한다.
         settings: ts_period_end_context_cap=0.30, ts_period_end_context_threshold=0.50.
    """

    @staticmethod
    def _routine_period_end_df() -> pd.DataFrame:
        """모든 일자 5건 + 동일 금액 — context 신호(s1/s2/amount_tail) 모두 zero.

        period_end_concentration 만 활성, 단독 strong 진입을 cap 으로 차단하는지 검증.
        """
        rows: list[dict] = []
        for day in range(1, 32):
            for _ in range(5):
                rows.append(
                    {
                        "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                        "auxiliary_account_number": "V_A",
                        "debit_amount": 1_000_000.0,
                        "credit_amount": 0.0,
                    }
                )
        return pd.DataFrame(rows)

    def test_period_end_only_routine_capped_below_threshold(self):
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._routine_period_end_df()
        detector = TimeseriesDetector()
        result = detector.detect(df)

        period_end_mask = pd.to_datetime(df["posting_date"]).dt.day >= 28
        cap = 0.30
        # period-end routine row 의 row_score 가 cap 이하로 제한됨
        capped_max = float(result.scores[period_end_mask].max())
        assert capped_max <= cap + 1e-9, (
            f"period-end-only routine row_score={capped_max} 이 cap={cap} 보다 큼"
        )
        # TS01 boolean 도 발생하지 않음 (단독 strong 진입 차단)
        assert int(result.rule_flags[0].flagged_count) == 0
        # gating 메타데이터에 capped row 기록
        gating = result.metadata["period_end_gating"]
        assert gating["period_end_only_capped_rows"] > 0

    def test_period_end_plus_daily_burst_exceeds_cap(self):
        """period-end + 강한 daily burst → context 충족 → cap 미적용 → row_score > cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._routine_period_end_df()
        # 1/30 (월말 D-1) 에 60 건 burst 추가
        burst_extra = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-01-30"),
                    "auxiliary_account_number": "V_A",
                    "debit_amount": 1_000_000.0,
                    "credit_amount": 0.0,
                }
            ]
            * 60
        )
        df = pd.concat([df, burst_extra], ignore_index=True)
        detector = TimeseriesDetector()
        result = detector.detect(df)

        burst_mask = pd.to_datetime(df["posting_date"]).dt.day == 30
        burst_max = float(result.scores[burst_mask].max())
        assert burst_max > 0.30, f"burst+period-end row_score={burst_max} 이 cap 이하"
        # TS01 boolean 발생 (gated period_end + s1 ECDF 가 high threshold 초과)
        assert int(result.rule_flags[0].flagged_count) > 0

    def test_period_end_plus_amount_tail_alone_remains_capped(self):
        """period-end (context=1) + amount_tail (rarity=1) → evidence=2 → cap.

        Why: 새 결합식 (context_count + rarity_high_count >= 3 + context >= 1) 하에서
        period_end 단독 context + amount_tail 단독 rarity 는 evidence=2 → composite 미진입.
        is_round_number=False 명시로 round_amount context 산입 차단 (1M 배수 fallback 방지).
        """
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._routine_period_end_df()
        df["is_round_number"] = False
        variety_rows = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-01-15"),
                    "auxiliary_account_number": "V_A",
                    "debit_amount": amount,
                    "credit_amount": 0.0,
                    "is_round_number": False,
                }
                for amount in (500_321.0, 2_001_234.0, 3_002_345.0, 4_003_456.0)
            ]
        )
        large_amount = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-01-30"),
                    "auxiliary_account_number": "V_A",
                    "debit_amount": 1_234_567_890.0,
                    "credit_amount": 0.0,
                    "is_round_number": False,
                }
            ]
        )
        df = pd.concat([df, variety_rows, large_amount], ignore_index=True)
        detector = TimeseriesDetector()
        result = detector.detect(df)

        # period_end + amount_tail (context=1, rarity=1) → evidence=2 → cap.
        last_idx = df.index[-1]
        last_score = float(result.scores.loc[last_idx])
        cap = 0.30
        assert last_score <= cap + 1e-9, (
            f"period-end + amount_tail alone row_score={last_score} 이 cap={cap} 초과 — "
            f"evidence role gating 실패 (단독 결합 strong 진입 차단 안 됨)"
        )

    def test_non_period_burst_remains_strong(self):
        """월 중반 burst (period_end 무관) 는 기존처럼 strong → s1 ECDF 가 row_score 결정."""
        from src.detection.timeseries_detector import TimeseriesDetector

        rows: list[dict] = []
        for day in range(1, 31):
            for _ in range(4):
                rows.append(
                    {
                        "posting_date": pd.Timestamp(f"2025-06-{day:02d}"),
                        "auxiliary_account_number": "V_A",
                        "debit_amount": 1_000_000.0,
                        "credit_amount": 0.0,
                    }
                )
        # 6/15 (월 중반) 50건 burst — period_end 무관
        burst_extra = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-06-15"),
                    "auxiliary_account_number": "V_A",
                    "debit_amount": 1_000_000.0,
                    "credit_amount": 0.0,
                }
            ]
            * 50
        )
        df = pd.concat([pd.DataFrame(rows), burst_extra], ignore_index=True)
        detector = TimeseriesDetector()
        result = detector.detect(df)

        burst_mask = pd.to_datetime(df["posting_date"]).dt.day == 15
        burst_max = float(result.scores[burst_mask].max())
        # 6/15 는 월말 무관이라 period_end_concentration 기여 없음 — s1 단독으로 strong
        assert burst_max >= 0.95, f"non-period burst row_score={burst_max} 가 약함"

    def test_small_sample_period_end_zero_or_graceful(self):
        """행 수가 매우 적으면 graceful — 0 또는 cap 이하."""
        from src.detection.timeseries_detector import TimeseriesDetector

        rows = [
            {
                "posting_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "auxiliary_account_number": "V_A",
                "debit_amount": 1_000_000.0,
                "credit_amount": 0.0,
            }
            for day in [29, 30, 31]
        ]
        df = pd.DataFrame(rows)
        detector = TimeseriesDetector()
        result = detector.detect(df)
        assert float(result.scores.max()) <= 0.30 + 1e-9

    def test_no_phase1_or_label_leakage_in_gating(self):
        """Phase 1 rule hit / DataSynth 라벨 컬럼이 없어도 정상 동작 + 라벨 컬럼 무참조."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._routine_period_end_df()
        # 명시적으로 라벨/Phase1 컬럼 없음
        for forbidden in ("is_fraud", "is_anomaly", "mutation_type", "flagged_rules"):
            assert forbidden not in df.columns

        detector = TimeseriesDetector()
        result = detector.detect(df)

        # detector 출력에도 위 컬럼 흔적 없음
        assert all("mutation" not in str(k) for k in result.metadata)
        assert all("fraud" not in str(k) for k in result.metadata)
        assert all("anomaly" not in str(s["name"]) for s in result.metadata["sub_signals"])

    def test_gating_metadata_shape(self):
        """period_end_gating metadata 구조 잠금 (JSON-serializable + 필수 키)."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._routine_period_end_df()
        detector = TimeseriesDetector()
        result = detector.detect(df)
        gating = result.metadata["period_end_gating"]
        for key in (
            "context_threshold",
            "context_cap",
            "context_axes",
            "amount_tail_active",
            "period_end_only_capped_rows",
            "period_end_with_context_rows",
            "context_present_row_count",
            "gated_period_end_q95",
            "raw_period_end_q95",
        ):
            assert key in gating, f"missing key in period_end_gating: {key}"
        assert gating["context_cap"] == 0.30
        assert gating["context_threshold"] == 0.50
        # JSON serializable
        json.dumps(gating, default=str)


# ── Evidence role separation (strong vs context) — TS02 redefinition ─────


class TestTS02EvidenceRoleSeparation:
    """TS02 = group_spike-only 재정의 검증.

    Why: broad activity / cold-start / routine frequency 는 strong anomaly 가 아니라
    context 신호로만 분류한다. ts_group_min_active_days + ts_group_min_excess_count +
    ts_group_spike_ratio_min 가드를 통과한 group-level spike 만 양수 score.
    settings: ts_group_min_support=10, min_active_days=3, min_excess_count=3,
    spike_ratio_min=2.0, cold_start_score_cap=0.30, strong_present_threshold=0.30.
    """

    @staticmethod
    def _steady_recurring_df() -> pd.DataFrame:
        """vendor A: 매일 1~2 건 routine — broad activity. spike 아님.

        90 일 × 2 건/일 = 180 행 (충분한 support + 충분한 active_days).
        그러나 routine 이라 current vs baseline 비율 ≈ 1.0 → spike 가드 미통과.
        """
        rows: list[dict] = []
        for day_offset in range(90):
            date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day_offset)
            for _ in range(2):
                rows.append({"posting_date": date, "auxiliary_account_number": "V_A"})
        return pd.DataFrame(rows)

    @staticmethod
    def _cold_start_df() -> pd.DataFrame:
        """vendor X: 데이터셋 끝에 처음 등장, 단일 일자 12 건 (active_days=1).

        min_support=10 가드를 통과시킨 뒤 active_days=1 < min_active_days=3 가드에서
        suppressed_low_active_days 로 분기되는지 검증.
        """
        rows: list[dict] = []
        # vendor A baseline: 60 일 routine
        for day_offset in range(60):
            date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day_offset)
            for _ in range(2):
                rows.append({"posting_date": date, "auxiliary_account_number": "V_A"})
        # vendor X cold-start: 단일 일자 12 건 (support 통과, active_days 미통과)
        for _ in range(12):
            rows.append(
                {
                    "posting_date": pd.Timestamp("2025-03-15"),
                    "auxiliary_account_number": "V_X",
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _true_group_spike_df() -> pd.DataFrame:
        """vendor B: 60 일 sparse baseline (월 2~3 건) + 마지막 7 일 동안 30 건 burst."""
        rows: list[dict] = []
        # baseline: 60 일 동안 2~3 건/주 sparse
        for day_offset in range(0, 60, 4):
            date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day_offset)
            rows.append({"posting_date": date, "auxiliary_account_number": "V_B"})
        # spike: 마지막 7 일에 30 건 집중 (excess 충분, ratio 충분)
        for day_offset in range(60, 67):
            date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day_offset)
            for _ in range(5):  # 일자 5건 × 7일 = 35건 burst (active_days=7)
                rows.append({"posting_date": date, "auxiliary_account_number": "V_B"})
        return pd.DataFrame(rows)

    def test_steady_recurring_activity_is_low_or_zero(self):
        """routine vendor (매일 1~2건) → TS02 score 0 또는 매우 낮음."""
        from src.detection.timeseries_rules import group_frequency_positive_robust_z_score

        df = self._steady_recurring_df()
        result = group_frequency_positive_robust_z_score(df)
        # routine 은 spike 가드(절대 excess≥3, 비율≥2.0) 미통과 → score 0
        assert float(result.score.max()) == 0.0, (
            f"steady routine 이 spike 로 잡힘: max={result.score.max()}"
        )
        # broad activity 가 카운터에 기록됨
        assert result.meta["suppressed_broad_activity_rows"] >= 0
        assert result.meta["spike_row_count"] == 0

    def test_cold_start_group_first_activity_not_strong(self):
        """cold-start group 단일 일자 첫 활동 → score 0 또는 cap 이하."""
        from src.detection.timeseries_rules import group_frequency_positive_robust_z_score

        df = self._cold_start_df()
        result = group_frequency_positive_robust_z_score(df)
        # vendor X 행은 active_days=1 (< min_active_days=3) → 가드 2 미통과 → score 0
        x_mask = df["auxiliary_account_number"] == "V_X"
        x_scores = result.score[x_mask]
        assert float(x_scores.max()) == 0.0, (
            f"cold-start single-day group 이 strong score: max={x_scores.max()}"
        )
        # suppressed_low_active_days 카운터 증가
        assert result.meta["suppressed_low_active_days_group_count"] >= 1

    def test_true_group_spike_emits_high_score(self):
        """sparse baseline 후 단기 burst → score > 0 (spike 인정)."""
        from src.detection.timeseries_rules import group_frequency_positive_robust_z_score

        df = self._true_group_spike_df()
        result = group_frequency_positive_robust_z_score(df)
        # vendor B 의 burst 영역 (1/1 + 60일~) 에서 양수 score 발생
        b_mask = df["auxiliary_account_number"] == "V_B"
        b_burst_dates = pd.to_datetime(df.loc[b_mask, "posting_date"]) >= pd.Timestamp("2025-03-02")
        b_burst_mask = b_mask & b_burst_dates.reindex(df.index, fill_value=False)
        assert float(result.score[b_burst_mask].max()) > 0.0, (
            f"true spike 가 인정되지 않음: burst max={result.score[b_burst_mask].max()}"
        )
        assert result.meta["spike_group_count"] >= 1
        assert result.meta["spike_row_count"] >= 1

    def test_cold_start_group_capped_at_cold_start_cap(self):
        """cold-start group (baseline_median=0) 의 활동은 cold_start_cap (0.30) 이하로 제한.

        Why: baseline 정보가 없는 group 은 strong anomaly 로 격상하지 않고 context-only
        cap 이하 score 만 부여한다 — broad context detector 의 단독 strong 진입 차단.
        """
        from src.detection.timeseries_rules import group_frequency_positive_robust_z_score

        rows: list[dict] = []
        # vendor Y: 1/1 anchor row 1 건 + 4/1~4/5 burst (3 활성일, 각 4 건).
        # 1/1 anchor 로 daily_grp_counts 범위가 1/1 ~ 4/5 (95 일) 확장된다.
        # 대부분의 rolling window (7일) 가 0 → baseline_median=0 → cold-start 분기.
        # 가드 1 (support=13≥10) + 가드 2 (active_days=4≥3) 통과.
        rows.append({"posting_date": pd.Timestamp("2025-01-01"), "auxiliary_account_number": "V_Y"})
        for day, count in [("2025-04-01", 4), ("2025-04-03", 4), ("2025-04-05", 4)]:
            for _ in range(count):
                rows.append({"posting_date": pd.Timestamp(day), "auxiliary_account_number": "V_Y"})
        df = pd.DataFrame(rows)
        result = group_frequency_positive_robust_z_score(df)
        y_max = float(result.score.max())
        # cold-start cap = 0.30 으로 제한 (strong band 진입 차단)
        assert y_max <= 0.30 + 1e-9, f"cold-start group 이 cap 초과: max={y_max} > 0.30"
        assert result.meta["cold_start_group_count"] >= 1

    def test_period_end_plus_group_spike_exceeds_cap(self):
        """period-end + group spike → strong present → row_score > cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._true_group_spike_df()
        # period-end (3/3~3/8 — month-end 근접) 에 spike 가 걸치도록 데이터 조정
        # _true_group_spike_df 는 60일 후 7일 burst → 약 3/2~3/8 사이.
        # 3/8 (월 초반) 은 period_end 무관, 3/31 (월말) 에 추가 spike 보강.
        period_end_burst = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-03-31"),
                    "auxiliary_account_number": "V_B",
                }
            ]
            * 10
        )
        df = pd.concat([df, period_end_burst], ignore_index=True)
        detector = TimeseriesDetector()
        result = detector.detect(df)
        # 3/31 (월말 + group spike) row 가 cap 초과
        mar31_mask = pd.to_datetime(df["posting_date"]).dt.normalize() == pd.Timestamp("2025-03-31")
        mar31_max = float(result.scores[mar31_mask].max())
        assert mar31_max > 0.30, f"period-end + group spike row_score={mar31_max} 이 cap 이하"

    def test_amount_tail_alone_remains_capped(self):
        """대형 금액 단독 (strong 부재) → row_score ≤ cap.

        Why: evidence role 분리에서 amount_tail 은 context. strong (burst/spike) 없으면
        cap 이하로 제한된다.
        """
        from src.detection.timeseries_detector import TimeseriesDetector

        rows: list[dict] = []
        # 60일 routine + 6/15 (월 중반) 에 1건 큰 금액. period-end 무관.
        for day_offset in range(60):
            date = pd.Timestamp("2025-06-01") + pd.Timedelta(days=day_offset)
            for amount in (500_000.0, 800_000.0, 1_200_000.0):
                rows.append(
                    {
                        "posting_date": date,
                        "auxiliary_account_number": "V_A",
                        "debit_amount": amount,
                        "credit_amount": 0.0,
                    }
                )
        rows.append(
            {
                "posting_date": pd.Timestamp("2025-06-15"),
                "auxiliary_account_number": "V_Z",
                "debit_amount": 1_000_000_000.0,
                "credit_amount": 0.0,
            }
        )
        df = pd.DataFrame(rows)
        detector = TimeseriesDetector()
        result = detector.detect(df)
        last_idx = df.index[-1]
        last_score = float(result.scores.loc[last_idx])
        assert last_score <= 0.30 + 1e-9, (
            f"amount_tail alone row_score={last_score} 이 cap 초과 — "
            f"context 단독 strong 진입 차단 실패"
        )

    def test_phase1_columns_injection_no_effect(self):
        """Phase1 결과 컬럼 주입해도 결과 동일 (입력 미사용 보장)."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df_base = self._true_group_spike_df()
        df_with_phase1 = df_base.copy()
        df_with_phase1["flagged_rules"] = "L3-04,C03"
        df_with_phase1["priority_score"] = 4.2
        df_with_phase1["review_rules"] = "C01"

        detector = TimeseriesDetector()
        result_base = detector.detect(df_base)
        result_phase1 = detector.detect(df_with_phase1)

        # 동일 score (Phase1 컬럼 입력 미사용)
        assert (result_base.scores.fillna(0.0) == result_phase1.scores.fillna(0.0)).all(), (
            "Phase1 결과 컬럼 주입이 timeseries score 에 영향을 줌 (leakage)"
        )

    def test_synthetic_label_columns_injection_no_effect(self):
        """DataSynth synthetic label 컬럼 주입해도 결과 동일."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df_base = self._true_group_spike_df()
        df_with_labels = df_base.copy()
        df_with_labels["is_fraud"] = True
        df_with_labels["is_anomaly"] = 1
        df_with_labels["mutation_type"] = "circular_related_party_transaction"

        detector = TimeseriesDetector()
        result_base = detector.detect(df_base)
        result_labels = detector.detect(df_with_labels)

        assert (result_base.scores.fillna(0.0) == result_labels.scores.fillna(0.0)).all(), (
            "synthetic label 컬럼 주입이 timeseries score 에 영향을 줌 (leakage)"
        )

    def test_metadata_has_evidence_role_gating_summary(self):
        """metadata.evidence_role_gating + group_spike suppression 카운터 노출."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._true_group_spike_df()
        detector = TimeseriesDetector()
        result = detector.detect(df)

        # evidence_role_gating metadata 잠금
        gating = result.metadata.get("evidence_role_gating")
        assert gating is not None, "evidence_role_gating metadata 누락"
        for key in (
            "strong_present_threshold",
            "context_cap",
            "strong_axes",
            "context_axes",
            "strong_present_row_count",
            "context_boost_rows",
            "context_capped_by_strong_absent_rows",
        ):
            assert key in gating, f"evidence_role_gating 에 키 누락: {key}"
        assert gating["context_cap"] == 0.30
        assert gating["strong_present_threshold"] == 0.30
        # JSON serializable
        json.dumps(gating, default=str)

        # group_frequency sub-signal 의 suppression 카운터 노출
        sub_signals = result.metadata["sub_signals"]
        group_sig = next(
            (s for s in sub_signals if s["name"] == "group_frequency_positive_robust_z"), None
        )
        assert group_sig is not None
        meta = group_sig["meta"]
        for key in (
            "evaluated_group_count",
            "spike_group_count",
            "cold_start_group_count",
            "suppressed_low_support_group_count",
            "suppressed_low_active_days_group_count",
            "suppressed_broad_activity_rows",
            "spike_row_count",
            "cold_start_row_count",
        ):
            assert key in meta, f"group_frequency meta 에 키 누락: {key}"

    def test_min_excess_and_ratio_guards_block_marginal_spike(self):
        """절대 excess 또는 비율 미달 → suppressed_broad. score 0.

        Why: baseline=2, current=3 (excess=1, ratio=1.5) → 양쪽 미달 → 차단.
        baseline=2, current=5 (excess=3, ratio=2.5) → 양쪽 통과 → 인정.
        """
        from src.detection.timeseries_rules import group_frequency_positive_robust_z_score

        rows: list[dict] = []
        # vendor M: baseline median≈2 — 매주 2건씩 30주
        # 그리고 한 일자에만 3건 (excess=1, marginal — 가드 미통과 기대)
        for week in range(30):
            date = pd.Timestamp("2025-01-06") + pd.Timedelta(days=week * 7)
            for _ in range(2):
                rows.append({"posting_date": date, "auxiliary_account_number": "V_M"})
        # marginal spike: 30주차 마지막에 1건만 추가 (window 합 3)
        rows.append(
            {
                "posting_date": pd.Timestamp("2025-08-03"),
                "auxiliary_account_number": "V_M",
            }
        )
        df = pd.DataFrame(rows)
        result = group_frequency_positive_robust_z_score(df)
        # marginal — spike 아님 (broad activity 차단)
        assert float(result.score.max()) == 0.0, (
            f"marginal increment 이 spike 로 잡힘: max={result.score.max()}"
        )

    def test_group_spike_drives_ts02_high_in_detector(self):
        """group spike 가 detector 통합에서 TS02 high 진입 + ts02_signal_q95 양수."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = self._true_group_spike_df()
        detector = TimeseriesDetector()
        result = detector.detect(df)

        ts02_q95 = result.metadata["score_distribution"]["ts02_signal_q95"]
        assert ts02_q95 > 0.0, f"true group spike 데이터에서 TS02 q95={ts02_q95} (양수 아님)"
        ts02_flagged = int(result.rule_flags[1].flagged_count)
        assert ts02_flagged > 0, "true group spike 가 TS02 boolean flag 를 만들지 못함"


# ── Composite temporal anomaly (3-axis 결합) ─────────────────


def _build_composite_base_df(
    *,
    n_rows: int = 400,
    n_partners: int = 60,
    n_accounts: int = 60,
) -> pd.DataFrame:
    """rarity sub-signal min_pair_population=50 가드를 통과시키는 base normal df.

    Why: rarity ECDF 산출에는 unique pair 수가 충분해야 한다. 60 partner * 60 account 풀에서
         routine random pair 를 만들어 unique pair >= 50 보장. 모든 행은 정상 (cap 이하 score)
         이어야 함 — composite path 입력 신호가 모두 미충족.
    """
    import random

    random.seed(42)
    rows: list[dict] = []
    base_date = pd.Timestamp("2025-01-01")
    for i in range(n_rows):
        rows.append(
            {
                "posting_date": base_date + pd.Timedelta(days=i % 60),
                "auxiliary_account_number": f"V_{i % n_partners:03d}",
                "trading_partner": f"P_{i % n_partners:03d}",
                "gl_account": f"ACC_{i % n_accounts:03d}",
                "business_process": f"PROC_{i % 8:03d}",
                "created_by": f"USR_{i % 12:03d}",
                "debit_amount": 100_000.0 + (i % 200) * 1_000.0,
                "credit_amount": 0.0,
                "is_after_hours": False,
                "is_weekend": False,
                "is_manual_je": False,
                "is_round_number": False,
                "source": "system",
            }
        )
    return pd.DataFrame(rows)


def _inject_anomaly_row(df: pd.DataFrame, **overrides: object) -> tuple[pd.DataFrame, int]:
    """단일 anomaly row 를 base df 에 주입하고 (df, idx) 반환.

    Why: 기본값은 routine vendor/account (P_000, ACC_000 등) — rarity 신호 미활성.
         "_only_capped" 단독 신호 테스트에서 rarity 가 의도치 않게 동반되지 않도록 한다.
         rare 값을 원하는 테스트는 overrides 로 명시.
    """
    new_row = {
        "posting_date": pd.Timestamp("2025-01-31"),
        "auxiliary_account_number": "V_000",
        "trading_partner": "P_000",
        "gl_account": "ACC_000",
        "business_process": "PROC_000",
        "created_by": "USR_000",
        "debit_amount": 100_000.0,
        "credit_amount": 0.0,
        "is_after_hours": False,
        "is_weekend": False,
        "is_manual_je": False,
        "is_round_number": False,
        "source": "system",
    }
    new_row.update(overrides)
    out = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return out, int(out.index[-1])


class TestCompositeTemporalAnomaly:
    """3-axis composite path 검증.

    Why: strong axis (daily_burst/group_spike) 가 단일 사건 fraud 패턴을 우회할 때,
         context (period_end/after_hours/manual/round) 결합 + rarity tail (amount/account/
         user/partner rarity) 동반 시 cap 초과 허용. 단독 신호는 cap 유지.
    """

    def test_period_end_plus_amount_tail_plus_manual_exceeds_cap(self):
        """period-end + manual (ctx=2) + amount_tail (rarity=1) → evidence=3 → composite."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=999_999_999.0,
            is_manual_je=True,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score > cap + 1e-6, (
            f"period_end + amount_tail + manual 행 row_score={score} 이 cap={cap} 초과 못함 — "
            f"composite path 진입 실패"
        )

    def test_after_hours_plus_amount_tail_plus_rare_account_exceeds_cap(self):
        """after-hours (context=1) + amount_tail + rare user/account (rarity=2~) → evidence=3."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            is_after_hours=True,
            debit_amount=900_000_000.0,
            # Why: rare user-account + account-process 명시. base routine 과 unique combination.
            created_by="USR_RARE",
            gl_account="ACC_RARE",
            business_process="PROC_RARE",
            trading_partner="P_RARE",
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score > cap + 1e-6, (
            f"after_hours + amount_tail + rare_account row_score={score} 이 cap={cap} 초과 못함"
        )

    def test_three_context_plus_rarity_q90_moderate_path(self):
        """context 3 (period_end + manual + round) + rarity 1 (amount_tail q90~) → moderate."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=999_000_000.0,
            is_manual_je=True,
            is_round_number=True,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score > cap + 1e-6, (
            f"period_end + manual + round + amount_tail row_score={score} 이 cap={cap} 초과 못함"
        )

    def test_period_end_only_capped(self):
        """period-end 단독 (no context 결합, no rarity) → cap 이하."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=100_000.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, (
            f"period_end only row_score={score} 이 cap={cap} 초과 — 단독 high 차단 실패"
        )

    def test_after_hours_only_capped(self):
        """after-hours 단독 → cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            is_after_hours=True,
            debit_amount=100_000.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, f"after_hours only row_score={score} 이 cap={cap} 초과"

    def test_manual_only_capped(self):
        """manual 단독 → cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            is_manual_je=True,
            debit_amount=100_000.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, f"manual only row_score={score} 이 cap={cap} 초과"

    def test_round_amount_only_capped(self):
        """round_amount 단독 → cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            is_round_number=True,
            debit_amount=10_000_000.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, f"round_amount only row_score={score} 이 cap={cap} 초과"

    def test_rare_account_only_capped(self):
        """rare account/process 단독 (no context) → cap."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            gl_account="ACC_RARE",
            business_process="PROC_RARE",
            trading_partner="P_RARE",
            created_by="USR_RARE",
            debit_amount=100_000.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, f"rare_account only row_score={score} 이 cap={cap} 초과"

    def test_amount_tail_only_capped(self):
        """amount_tail 단독 (no context, no other rarity) → cap.

        Why: 사용자 결정 명시 — amount_tail 단독은 row_score 직접 max 기여 금지.
        """
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, idx = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-15"),
            debit_amount=999_999_999.0,
        )
        result = TimeseriesDetector().detect(df)
        score = float(result.scores.loc[idx])
        cap = 0.30
        assert score <= cap + 1e-6, f"amount_tail alone row_score={score} 이 cap={cap} 초과"

    def test_strong_burst_alone_high_unchanged(self):
        """daily_burst 단독 high → composite path 무관, strong path 통해 cap 초과."""
        from src.detection.timeseries_detector import TimeseriesDetector

        rows: list[dict] = []
        for day in range(1, 31):
            for _ in range(4):
                rows.append(
                    {
                        "posting_date": pd.Timestamp(f"2025-06-{day:02d}"),
                        "auxiliary_account_number": "V_A",
                        "debit_amount": 1_000_000.0,
                        "credit_amount": 0.0,
                    }
                )
        # 6/15 중반 burst — period_end 무관
        burst_extra = pd.DataFrame(
            [
                {
                    "posting_date": pd.Timestamp("2025-06-15"),
                    "auxiliary_account_number": "V_A",
                    "debit_amount": 1_000_000.0,
                    "credit_amount": 0.0,
                }
            ]
            * 60
        )
        df = pd.concat([pd.DataFrame(rows), burst_extra], ignore_index=True)
        result = TimeseriesDetector().detect(df)
        burst_mask = pd.to_datetime(df["posting_date"]).dt.day == 15
        burst_max = float(result.scores[burst_mask].max())
        assert burst_max >= 0.95, f"daily burst alone row_score={burst_max} 이 strong band 미진입"

    def test_phase1_column_invariance_composite(self):
        """Phase1 결과 컬럼 주입 시 composite path 결과 동일."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df_base = _build_composite_base_df()
        df_base, idx = _inject_anomaly_row(
            df_base,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=999_999_999.0,
            is_manual_je=True,
        )
        df_p1 = df_base.copy()
        df_p1["flagged_rules"] = "L3-04,C03"
        df_p1["priority_score"] = 4.2
        df_p1["review_rules"] = "C01"
        df_p1["anomaly_score"] = 0.85
        df_p1["risk_level"] = "High"

        r0 = TimeseriesDetector().detect(df_base)
        r1 = TimeseriesDetector().detect(df_p1)
        assert (r0.scores.fillna(0.0) == r1.scores.fillna(0.0)).all(), (
            "Phase1 컬럼 주입이 composite path 결과에 영향을 줌"
        )

    def test_synthetic_label_invariance_composite(self):
        """DataSynth synthetic label 주입 시 composite path 결과 동일."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df_base = _build_composite_base_df()
        df_base, idx = _inject_anomaly_row(
            df_base,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=999_999_999.0,
            is_manual_je=True,
        )
        df_labels = df_base.copy()
        df_labels["is_fraud"] = True
        df_labels["is_anomaly"] = 1
        df_labels["mutation_type"] = "fictitious_entry"
        df_labels["manipulation_scenario"] = "fictitious_entry"
        df_labels["manipulated_entry_truth"] = 1

        r0 = TimeseriesDetector().detect(df_base)
        r1 = TimeseriesDetector().detect(df_labels)
        assert (r0.scores.fillna(0.0) == r1.scores.fillna(0.0)).all(), (
            "synthetic label 주입이 composite path 결과에 영향을 줌"
        )

    def test_composite_metadata_exposed(self):
        """composite_temporal_gating metadata 노출 + JSON serializable."""
        from src.detection.timeseries_detector import TimeseriesDetector

        df = _build_composite_base_df()
        df, _ = _inject_anomaly_row(
            df,
            posting_date=pd.Timestamp("2025-01-31"),
            debit_amount=999_999_999.0,
            is_manual_je=True,
        )
        result = TimeseriesDetector().detect(df)
        gating = result.metadata.get("composite_temporal_gating")
        assert gating is not None, "composite_temporal_gating metadata 누락"
        for key in (
            "min_evidence_count",
            "tail_q",
            "strong_tail_q",
            "context_boost_max",
            "strong_composite_row_count",
            "moderate_composite_row_count",
            "composite_nonzero_row_count",
            "context_count_distribution",
            "rarity_high_count_q95_distribution",
            "rarity_tail_q95",
        ):
            assert key in gating, f"composite_temporal_gating 키 누락: {key}"
        # JSON serializable
        json.dumps(gating, default=str)

        # evidence_role_gating 신규 키 (rarity_axes / composite_*)
        evidence = result.metadata["evidence_role_gating"]
        assert "rarity_axes" in evidence
        assert "composite_boost_max" in evidence
        assert "composite_min_evidence_count" in evidence


# ── 신규 sub-signal unit tests ─────────────────────────


class TestAfterHoursOrWeekendScore:
    def test_missing_flags_inactive(self):
        from src.detection.timeseries_rules import after_hours_or_weekend_score

        df = pd.DataFrame({"posting_date": pd.date_range("2025-01-01", periods=5)})
        result = after_hours_or_weekend_score(df)
        assert result.active is False
        assert result.meta["reason"] == "no_temporal_flag"

    def test_after_hours_flag(self):
        from src.detection.timeseries_rules import after_hours_or_weekend_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=4),
                "is_after_hours": [True, False, True, False],
            }
        )
        result = after_hours_or_weekend_score(df)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2

    def test_either_flag_present(self):
        from src.detection.timeseries_rules import after_hours_or_weekend_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=3),
                "is_after_hours": [False, False, False],
                "is_weekend": [True, False, True],
            }
        )
        result = after_hours_or_weekend_score(df)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2


class TestManualOrAdjustmentScore:
    def test_missing_flags_inactive(self):
        from src.detection.timeseries_rules import manual_or_adjustment_score

        df = pd.DataFrame({"posting_date": pd.date_range("2025-01-01", periods=3)})
        result = manual_or_adjustment_score(df)
        assert result.active is False
        assert result.meta["reason"] == "no_manual_flag"

    def test_is_manual_je_flag(self):
        from src.detection.timeseries_rules import manual_or_adjustment_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=4),
                "is_manual_je": [True, False, True, False],
            }
        )
        result = manual_or_adjustment_score(df)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2

    def test_source_value_match(self):
        from src.detection.timeseries_rules import manual_or_adjustment_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=4),
                "source": ["manual", "system", "adjustment", "batch"],
            }
        )
        result = manual_or_adjustment_score(df)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2


class TestRoundAmountScore:
    def test_is_round_number_flag(self):
        from src.detection.timeseries_rules import round_amount_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=3),
                "is_round_number": [True, False, True],
            }
        )
        result = round_amount_score(df)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2
        assert result.meta["source"] == "is_round_number"

    def test_debit_credit_modulo_fallback(self):
        from src.detection.timeseries_rules import round_amount_score

        df = pd.DataFrame(
            {
                "posting_date": pd.date_range("2025-01-01", periods=3),
                "debit_amount": [1_000_000.0, 1_234_567.0, 5_000_000.0],
                "credit_amount": [0.0, 0.0, 0.0],
            }
        )
        result = round_amount_score(df, max_significant_digits=2, min_digits=3)
        assert result.active is True
        assert int(result.meta["nonzero_row_count"]) == 2

    def test_no_amount_column_inactive(self):
        from src.detection.timeseries_rules import round_amount_score

        df = pd.DataFrame({"posting_date": pd.date_range("2025-01-01", periods=3)})
        result = round_amount_score(df)
        assert result.active is False


class TestPairRarityScore:
    def test_missing_columns_inactive(self):
        from src.detection.timeseries_rules import account_process_rarity_score

        df = pd.DataFrame({"posting_date": pd.date_range("2025-01-01", periods=3)})
        result = account_process_rarity_score(df)
        assert result.active is False
        assert result.meta["reason"] == "missing_columns"

    def test_insufficient_unique_pairs_inactive(self):
        from src.detection.timeseries_rules import account_process_rarity_score

        df = pd.DataFrame(
            {
                "gl_account": ["A"] * 100,
                "business_process": ["P"] * 100,
            }
        )
        result = account_process_rarity_score(df, min_pair_population=50)
        assert result.active is False
        assert result.meta["reason"] == "insufficient_unique_pairs"

    def test_rare_pair_higher_score(self):
        from src.detection.timeseries_rules import account_process_rarity_score

        rows: list[dict] = []
        # 60 unique pair (50 가드 통과). 49 pair 가 freq=10, 1 pair 가 freq=1.
        for i in range(49):
            for _ in range(10):
                rows.append({"gl_account": f"A{i:03d}", "business_process": f"P{i:03d}"})
        # 11 rare pair freq=1
        for j in range(11):
            rows.append({"gl_account": f"R{j:03d}", "business_process": f"X{j:03d}"})
        df = pd.DataFrame(rows)
        result = account_process_rarity_score(df, min_pair_population=50)
        assert result.active is True
        # rare pair (freq=1) 가 routine pair (freq=10) 보다 높은 score
        rare_mask = df["gl_account"].astype(str).str.startswith("R")
        routine_mask = df["gl_account"].astype(str).str.startswith("A")
        assert float(result.score[rare_mask].max()) > float(result.score[routine_mask].max())
