"""AnomalyDetector 오케스트레이터 통합 테스트."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.detection.anomaly_layer import AnomalyDetector
from src.detection.base import DetectionResult


@pytest.fixture
def full_anomaly_df() -> pd.DataFrame:
    """Layer C 룰 모두 테스트 가능한 종합 DataFrame (10행)."""
    n = 10
    # Why: Benford 분석에 최소 표본 필요 → first_digit 포함
    digits = []
    for d in range(1, 10):
        digits.append(d)
    digits.append(1)  # 10행 채우기

    return pd.DataFrame({
        "document_id": [f"D{i:03d}" for i in range(1, n + 1)],
        "debit_amount": [100.0, 50.0, 200.0, 30.0, 80.0, 150.0, 10.0, 90.0, 60.0, 40.0],
        "credit_amount": [0.0] * n,
        "gl_account": ["1000", "2000", "1000", "2000", "1000",
                        "2000", "3000", "1000", "2000", "4000"],
        "is_period_end": [True, False, False, False, True, False, False, False, False, False],
        "is_weekend": [True, False, False, False, False, False, True, False, False, False],
        "is_holiday": [False, False, False, False, False, False, False, False, False, False],
        "is_after_hours": [False, True, False, False, False, False, False, False, True, False],
        "days_backdated": [0, 45, 0, 0, 0, 0, -35, 0, 0, 31],
        "fiscal_period_mismatch": [False, False, True, False, False, False, False, False, False, True],
        "description_quality": ["normal", "missing", "normal", "poor", "normal",
                                 "normal", "normal", "normal", "normal", "normal"],
        "has_risk_keyword": ["low", "high", "low", "low", "low",
                              "medium", "low", "low", "low", "low"],
        "amount_zscore": [1.0, 0.5, 0.3, 3.5, 0.2, 0.8, 0.1, 0.4, -4.0, 0.6],
        "first_digit": pd.array(digits, dtype=pd.Int64Dtype()),
        # Why: C11 역분개 + C12 비정상시간대에 필요
        "posting_date": pd.to_datetime([
            "2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05",
            "2025-06-06", "2025-06-07", "2025-06-08", "2025-06-09", "2025-06-10",
        ]),
        "source": ["manual", "automated", "manual", "automated", "manual",
                    "automated", "manual", "automated", "manual", "automated"],
        "created_by": ["user_a", "user_b", "user_a", "user_b", "user_a",
                        "user_b", "user_a", "user_b", "user_a", "user_b"],
    })


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """최소 필수 컬럼만 있는 DataFrame — graceful degradation 확인."""
    return pd.DataFrame({
        "debit_amount": [100.0, 200.0],
        "credit_amount": [0.0, 0.0],
    })


class TestAnomalyDetectorIntegration:
    def test_returns_detection_result(self, full_anomaly_df: pd.DataFrame) -> None:
        """DetectionResult 타입 반환."""
        detector = AnomalyDetector()
        result = detector.detect(full_anomaly_df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "layer_c"

    def test_scores_range_0_to_1(self, full_anomaly_df: pd.DataFrame) -> None:
        """모든 scores가 0.0~1.0 범위."""
        result = AnomalyDetector().detect(full_anomaly_df)
        assert result.scores.min() >= 0.0
        assert result.scores.max() <= 1.0

    def test_scores_no_nan(self, full_anomaly_df: pd.DataFrame) -> None:
        """scores에 NaN 없음."""
        result = AnomalyDetector().detect(full_anomaly_df)
        assert not result.scores.isna().any()

    def test_details_columns_c_prefix(self, full_anomaly_df: pd.DataFrame) -> None:
        """details 컬럼이 C prefix."""
        result = AnomalyDetector().detect(full_anomaly_df)
        for col in result.details.columns:
            assert col.startswith("C"), f"컬럼 {col}은 C prefix가 아님"

    def test_rule_flags_count(self, full_anomaly_df: pd.DataFrame) -> None:
        """rule_flags 수는 실행된 룰 수와 일치 (C07은 BenfordDetector로 분리)."""
        result = AnomalyDetector().detect(full_anomaly_df)
        skipped = result.metadata.get("skipped_rules", [])
        expected_count = 12 - len(skipped)  # C01~C06, C08~C13 (C07 제외)
        assert len(result.rule_flags) == expected_count

    def test_flagged_indices_valid(self, full_anomaly_df: pd.DataFrame) -> None:
        """flagged_indices가 원본 인덱스 범위 내."""
        result = AnomalyDetector().detect(full_anomaly_df)
        for idx in result.flagged_indices:
            assert idx in full_anomaly_df.index

    def test_elapsed_recorded(self, full_anomaly_df: pd.DataFrame) -> None:
        """elapsed가 0 이상."""
        result = AnomalyDetector().detect(full_anomaly_df)
        assert result.metadata["elapsed"] >= 0.0

    def test_minimal_df_graceful(self, minimal_df: pd.DataFrame) -> None:
        """최소 컬럼만 있어도 에러 없이 실행 — 대부분 룰이 0점."""
        result = AnomalyDetector().detect(minimal_df)
        assert isinstance(result, DetectionResult)
        assert result.scores.max() <= 1.0

    def test_empty_df_raises_value_error(self) -> None:
        """빈 DataFrame → ValueError (base.validate_input 설계)."""
        df = pd.DataFrame({"debit_amount": pd.Series(dtype=float),
                           "credit_amount": pd.Series(dtype=float)})
        with pytest.raises(ValueError):
            AnomalyDetector().detect(df)

    def test_benford_not_in_anomaly_detector(self, full_anomaly_df: pd.DataFrame) -> None:
        """C07은 BenfordDetector로 분리 — AnomalyDetector에 포함되지 않음."""
        result = AnomalyDetector().detect(full_anomaly_df)
        assert "C07" not in result.details.columns
        assert "benford_result" not in result.metadata
