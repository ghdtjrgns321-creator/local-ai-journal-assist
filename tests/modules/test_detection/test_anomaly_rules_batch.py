"""L4-06 배치 전표 이상 패턴 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.detection.anomaly_rules_batch import c13_batch_anomaly


class TestL4-06:
    def test_batch_period_end_concentration(self) -> None:
        """배치 전표 중 기말 비율 > 임계 → 배치 전체 플래그."""
        df = pd.DataFrame({
            "source": ["batch"] * 10 + ["manual"] * 5,
            "is_period_end": [True] * 8 + [False] * 2 + [True] * 5,
            "debit_amount": [100.0] * 15,
            "credit_amount": [0.0] * 15,
            "posting_date": pd.date_range("2025-12-25", periods=15, freq="h"),
        })
        # Why: 배치 10건 중 기말 8건 = 80% > 50% 임계
        result = c13_batch_anomaly(df, period_end_ratio=0.5)
        assert result[:10].all()   # 배치 전체 플래그
        assert not result[10:].any()  # 수기 전표는 미플래그

    def test_batch_simultaneous_creation(self) -> None:
        """같은 날 배치 N건 이상 → 해당 일자 배치 플래그."""
        dates = (["2025-12-01"] * 60) + (["2025-12-02"] * 5)
        df = pd.DataFrame({
            "source": ["batch"] * 65,
            "is_period_end": [False] * 65,
            "debit_amount": [100.0] * 65,
            "credit_amount": [0.0] * 65,
            "posting_date": pd.to_datetime(dates),
        })
        result = c13_batch_anomaly(df, simultaneous_threshold=50, period_end_ratio=0.99)
        # Why: 12/01 60건 ≥ 50 → 플래그, 12/02 5건 < 50 → 미플래그
        assert result[:60].all()
        assert not result[60:].any()

    def test_batch_amount_outlier(self) -> None:
        """배치 내 Z-score 이상치 → 해당 행 플래그."""
        df = pd.DataFrame({
            "source": ["batch"] * 20,
            "is_period_end": [False] * 20,
            "debit_amount": [100.0] * 19 + [10000.0],  # 마지막 행 이상치
            "credit_amount": [0.0] * 20,
            "posting_date": pd.date_range("2025-01-01", periods=20),
        })
        result = c13_batch_anomaly(
            df, period_end_ratio=0.99, simultaneous_threshold=100, amount_zscore=2.0,
        )
        # Why: 마지막 행(10000)은 Z-score 크게 초과
        assert result[19]
        # Why: 이상치(idx=19) 외 정상 금액 행은 미플래그
        assert not result[:18].any()

    def test_non_batch_not_flagged(self) -> None:
        """비배치(manual) 전표는 어떤 조건에도 미플래그."""
        df = pd.DataFrame({
            "source": ["manual"] * 10,
            "is_period_end": [True] * 10,
            "debit_amount": [100.0] * 10,
            "credit_amount": [0.0] * 10,
            "posting_date": pd.date_range("2025-12-25", periods=10),
        })
        result = c13_batch_anomaly(df)
        assert not result.any()

    def test_no_source_column_returns_false(self) -> None:
        """source 컬럼 미존재 시 graceful skip."""
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        })
        result = c13_batch_anomaly(df)
        assert not result.any()

    def test_no_batch_entries_returns_false(self) -> None:
        """배치 전표 0건 시 전체 False."""
        df = pd.DataFrame({
            "source": ["manual", "api", "import"],
            "debit_amount": [100.0] * 3,
            "credit_amount": [0.0] * 3,
        })
        result = c13_batch_anomaly(df)
        assert not result.any()

    def test_uniform_amounts_std_zero_safe(self) -> None:
        """배치 전표 금액이 모두 동일(std=0) → Z-score 에러 없이 False."""
        df = pd.DataFrame({
            "source": ["batch"] * 10,
            "is_period_end": [False] * 10,
            "debit_amount": [500.0] * 10,
            "credit_amount": [0.0] * 10,
            "posting_date": pd.date_range("2025-06-01", periods=10),
        })
        result = c13_batch_anomaly(
            df, period_end_ratio=0.99, simultaneous_threshold=100,
        )
        # Why: std=0이므로 금액 이상치 없음, 다른 조건도 미충족
        assert not result.any()
