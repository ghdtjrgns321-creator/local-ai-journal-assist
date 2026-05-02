"""L4-06 배치 전표 이상 패턴 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.detection.anomaly_rules_batch import c13_batch_anomaly


class TestL4_06:
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
        assert result.attrs["score_series"].loc[result].eq(0.45).all()
        assert result.attrs["breakdown"]["period_end_concentration_rows"] == 10
        assert result.attrs["breakdown"]["period_end_only_rows"] == 10
        assert result.attrs["row_annotations"][0]["reason_codes"] == [
            "period_end_concentration",
        ]
        assert result.attrs["row_annotations"][0]["score_bucket"] == (
            "period_end_concentration"
        )
        assert result[:10].all()   # 배치 전체 플래그
        assert not result[10:].any()  # 수기 전표는 미플래그

    def test_batch_simultaneous_creation(self) -> None:
        """같은 날 배치 N건 이상 → 해당 일자 배치 플래그."""
        dates = (["2025-12-01"] * 60) + (["2025-12-02"] * 5)
        df = pd.DataFrame({
            "source": ["batch"] * 65,
            "document_id": [f"D{i:03d}" for i in range(65)],
            "is_period_end": [False] * 65,
            "debit_amount": [100.0] * 65,
            "credit_amount": [0.0] * 65,
            "posting_date": pd.to_datetime(dates),
        })
        result = c13_batch_anomaly(df, simultaneous_threshold=50, period_end_ratio=0.99)
        # Why: 12/01 60건 ≥ 50 → 플래그, 12/02 5건 < 50 → 미플래그
        assert result[:60].all()
        assert not result[60:].any()

    def test_batch_simultaneous_creation_uses_document_count_not_line_count(self) -> None:
        """동일 timestamp의 multi-line 전표 1건은 대량 동시 생성으로 보지 않는다."""
        df = pd.DataFrame({
            "source": ["automated"] * 60,
            "document_id": ["DOC001"] * 60,
            "is_period_end": [False] * 60,
            "debit_amount": [100.0] * 60,
            "credit_amount": [0.0] * 60,
            "posting_date": [pd.Timestamp("2025-12-01 09:00:00")] * 60,
        })
        result = c13_batch_anomaly(df, simultaneous_threshold=50, period_end_ratio=0.99)
        assert not result.any()

    def test_batch_simultaneous_creation_falls_back_to_row_count_without_document_id(self) -> None:
        """document_id가 없으면 기존처럼 row count 기준으로 graceful fallback."""
        df = pd.DataFrame({
            "source": ["automated"] * 60,
            "is_period_end": [False] * 60,
            "debit_amount": [100.0] * 60,
            "credit_amount": [0.0] * 60,
            "posting_date": [pd.Timestamp("2025-12-01 09:00:00")] * 60,
        })
        result = c13_batch_anomaly(df, simultaneous_threshold=50, period_end_ratio=0.99)
        assert result.all()

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
        assert result.attrs["score_series"].iloc[19] == 0.25
        assert result.attrs["row_annotations"][19]["score_bucket"] == (
            "amount_outlier_only"
        )
        # Why: 이상치(idx=19) 외 정상 금액 행은 미플래그
        assert not result[:18].any()

    def test_batch_amount_outlier_uses_document_amount_when_document_id_exists(self) -> None:
        """Multi-line documents are scored by document-level max amount."""
        rows = []
        for i in range(19):
            rows.extend([
                {
                    "source": "batch",
                    "document_id": f"D{i:03d}",
                    "is_period_end": False,
                    "debit_amount": 100.0,
                    "credit_amount": 0.0,
                    "posting_date": pd.Timestamp("2025-01-01"),
                },
                {
                    "source": "batch",
                    "document_id": f"D{i:03d}",
                    "is_period_end": False,
                    "debit_amount": 100.0,
                    "credit_amount": 0.0,
                    "posting_date": pd.Timestamp("2025-01-01"),
                },
            ])
        rows.extend([
            {
                "source": "batch",
                "document_id": "D_OUT",
                "is_period_end": False,
                "debit_amount": 10_000.0,
                "credit_amount": 0.0,
                "posting_date": pd.Timestamp("2025-01-01"),
            },
            {
                "source": "batch",
                "document_id": "D_OUT",
                "is_period_end": False,
                "debit_amount": 10.0,
                "credit_amount": 0.0,
                "posting_date": pd.Timestamp("2025-01-01"),
            },
        ])
        df = pd.DataFrame(rows)

        result = c13_batch_anomaly(
            df,
            period_end_ratio=0.99,
            simultaneous_threshold=100,
            amount_zscore=2.0,
        )

        assert result[df["document_id"].eq("D_OUT")].all()
        assert not result[~df["document_id"].eq("D_OUT")].any()

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

    def test_interface_source_is_batch_like_case_insensitive(self) -> None:
        """interface/IF/automated 계열 source도 배치성 자동 전표로 취급."""
        df = pd.DataFrame({
            "source": ["INTERFACE"] * 3 + ["if"] * 3 + ["automated"] * 3,
            "is_period_end": [True] * 9,
            "debit_amount": [100.0] * 9,
            "credit_amount": [0.0] * 9,
            "posting_date": pd.date_range("2025-12-25", periods=9),
        })
        result = c13_batch_anomaly(df, period_end_ratio=0.5)
        assert result.all()

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
        assert not result.any()

    def test_batch_annotations_keep_multiple_reasons(self) -> None:
        """Same row can carry multiple batch-review reasons."""
        df = pd.DataFrame({
            "source": ["batch"] * 4,
            "document_id": [f"D{i}" for i in range(4)],
            "is_period_end": [True] * 4,
            "debit_amount": [100.0, 100.0, 100.0, 10000.0],
            "credit_amount": [0.0] * 4,
            "posting_date": [pd.Timestamp("2025-12-31")] * 4,
        })

        result = c13_batch_anomaly(
            df,
            period_end_ratio=0.5,
            simultaneous_threshold=4,
            amount_zscore=1.0,
        )

        assert result.all()
        assert result.attrs["breakdown"]["batch_review_docs"] == 4
        assert result.attrs["breakdown"]["amount_outlier_docs"] == 1
        assert result.attrs["breakdown"]["multi_signal_batch_docs"] == 4
        assert result.attrs["score_series"].loc[result].eq(0.65).all()
        reasons = result.attrs["row_annotations"][3]["reason_codes"]
        assert "period_end_concentration" in reasons
        assert "simultaneous_creation" in reasons
        assert "amount_outlier" in reasons
        assert result.attrs["row_annotations"][3]["score_bucket"] == "multi_signal_batch"

    def test_batch_simultaneous_creation_uses_exact_timestamp_not_calendar_day(self) -> None:
        """Batch runs are grouped by exact posting timestamp, not the whole day."""
        df = pd.DataFrame({
            "source": ["automated"] * 55 + ["automated"] * 5,
            "document_id": [f"D{i:03d}" for i in range(60)],
            "is_period_end": [False] * 60,
            "debit_amount": [100.0] * 60,
            "credit_amount": [0.0] * 60,
            "posting_date": (
                [
                    pd.Timestamp("2025-12-01 09:00:00") + pd.Timedelta(minutes=i)
                    for i in range(55)
                ]
                + [
                    pd.Timestamp("2025-12-02 09:00:00") + pd.Timedelta(minutes=i)
                    for i in range(5)
                ]
            ),
        })

        result = c13_batch_anomaly(df, simultaneous_threshold=50, period_end_ratio=0.99)

        assert not result.any()
        assert result.attrs["breakdown"]["simultaneous_creation_docs"] == 0
