"""AnomalyDetector 오케스트레이터 통합 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_layer import AnomalyDetector
from src.detection.base import DetectionResult


@pytest.fixture
def full_anomaly_df() -> pd.DataFrame:
    """L3/L4 룰 모두 테스트 가능한 종합 DataFrame (10행)."""
    n = 10
    # Why: Benford 분석에 최소 표본 필요 → first_digit 포함
    digits = []
    for d in range(1, 10):
        digits.append(d)
    digits.append(1)  # 10행 채우기

    return pd.DataFrame(
        {
            "document_id": [f"D{i:03d}" for i in range(1, n + 1)],
            "debit_amount": [100.0, 50.0, 200.0, 30.0, 80.0, 150.0, 10.0, 90.0, 60.0, 40.0],
            "credit_amount": [0.0] * n,
            "gl_account": [
                "1000",
                "2000",
                "1000",
                "2000",
                "1000",
                "2000",
                "3000",
                "1000",
                "2000",
                "4000",
            ],
            "is_period_end": [True, False, False, False, True, False, False, False, False, False],
            "is_weekend": [True, False, False, False, False, False, True, False, False, False],
            "is_holiday": [False, False, False, False, False, False, False, False, False, False],
            "is_after_hours": [False, True, False, False, False, False, False, False, True, False],
            "days_backdated": [0, 45, 0, 0, 0, 0, -35, 0, 0, 31],
            "fiscal_period_mismatch": [
                False,
                False,
                True,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
            ],
            "description_quality": [
                "normal",
                "missing",
                "normal",
                "corrupted",
                "normal",
                "normal",
                "normal",
                "normal",
                "normal",
                "normal",
            ],
            "has_risk_keyword": [
                "low",
                "high",
                "low",
                "low",
                "low",
                "medium",
                "low",
                "low",
                "low",
                "low",
            ],
            "amount_zscore": [1.0, 0.5, 0.3, 3.5, 0.2, 0.8, 0.1, 0.4, -4.0, 0.6],
            "first_digit": pd.array(digits, dtype=pd.Int64Dtype()),
            # Why: L2-05 역분개 + L4-05 비정상시간대에 필요
            "posting_date": pd.to_datetime(
                [
                    "2025-06-01",
                    "2025-06-02",
                    "2025-06-03",
                    "2025-06-04",
                    "2025-06-05",
                    "2025-06-06",
                    "2025-06-07",
                    "2025-06-08",
                    "2025-06-09",
                    "2025-06-10",
                ]
            ),
            "source": [
                "manual",
                "automated",
                "manual",
                "automated",
                "manual",
                "automated",
                "manual",
                "automated",
                "manual",
                "automated",
            ],
            "created_by": [
                "user_a",
                "user_b",
                "user_a",
                "user_b",
                "user_a",
                "user_b",
                "user_a",
                "user_b",
                "user_a",
                "user_b",
            ],
        }
    )


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """최소 필수 컬럼만 있는 DataFrame — graceful degradation 확인."""
    return pd.DataFrame(
        {
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
        }
    )


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

    def test_details_columns_rule_ids(self, full_anomaly_df: pd.DataFrame) -> None:
        """details columns use canonical rule IDs."""
        result = AnomalyDetector().detect(full_anomaly_df)
        for col in result.details.columns:
            assert col.startswith(("L1-", "L2-", "L3-", "L4-")), f"Unexpected rule id {col}"

    def test_rule_flags_count(self, full_anomaly_df: pd.DataFrame) -> None:
        """rule_flags 수는 실행된 룰 수와 일치 (L4-02은 BenfordDetector로 분리)."""
        result = AnomalyDetector().detect(full_anomaly_df)
        skipped = result.metadata.get("skipped_rules", [])
        expected_count = 11 - len(skipped)  # L3-04~L3-07, L4-03~L4-06 (L4-02 제외)
        assert len(result.rule_flags) == expected_count

    def test_l307_rule_flag_detail_exposes_threshold(
        self,
        full_anomaly_df: pd.DataFrame,
    ) -> None:
        """L3-07 binary 전환: 방향 요약 폐기, threshold_days만 detail로 노출."""
        result = AnomalyDetector().detect(full_anomaly_df)
        flag = next(item for item in result.rule_flags if item.rule_id == "L3-07")

        assert flag.detail == "threshold_days=30"

    def test_l309_surfaces_threshold_metadata(self) -> None:
        """L3-09 fixed threshold info is surfaced in metadata and rule detail."""
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "debit_amount": [100.0, 100.0],
                "credit_amount": [0.0, 0.0],
                "gl_account": ["2190", "2190"],
                "posting_date": pd.to_datetime(["2025-01-01", "2025-03-25"]),
                "amount_open": [100000.0, 100000.0],
                "is_suspense_account": [True, True],
            }
        )
        result = AnomalyDetector().detect(df)
        flag = next(item for item in result.rule_flags if item.rule_id == "L3-09")

        assert flag.detail == "threshold_days=30"
        breakdown = result.metadata["rule_breakdowns"]["L3-09"]
        assert breakdown["base_threshold_days"] == 30
        ann = result.metadata["row_annotations"]["L3-09"][0]
        assert ann["threshold_days"] == 30

    def test_l305_surfaces_calendar_review_metadata(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002", "D003", "D004"],
                "debit_amount": [100.0, 100.0, 100.0, 100.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "is_weekend": [True, False, True, False],
                "is_holiday": [False, True, True, False],
                "source": ["batch", "manual", "system", "manual"],
            }
        )
        result = AnomalyDetector().detect(df)

        assert result.details["L3-05"].tolist() == [1.0, 1.0, 1.0, 0.0]
        breakdown = result.metadata["rule_breakdowns"]["L3-05"]
        assert breakdown["flagged_docs"] == 3
        assert breakdown["source_counts"] == {"batch": 1, "manual": 1, "system": 1}
        annotations = result.metadata["row_annotations"]["L3-05"]
        assert annotations[0]["score"] == 1.0
        assert annotations[0]["source"] == "batch"
        assert annotations[1]["is_holiday"] is True
        assert annotations[2]["is_weekend"] is True

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
        df = pd.DataFrame(
            {"debit_amount": pd.Series(dtype=float), "credit_amount": pd.Series(dtype=float)}
        )
        with pytest.raises(ValueError):
            AnomalyDetector().detect(df)

    def test_benford_not_in_anomaly_detector(self, full_anomaly_df: pd.DataFrame) -> None:
        """L4-02은 BenfordDetector로 분리 — AnomalyDetector에 포함되지 않음."""
        result = AnomalyDetector().detect(full_anomaly_df)
        assert "L4-02" not in result.details.columns
        assert "benford_result" not in result.metadata

    def test_l304_binary_score_ignores_amount_and_sensitive_account_bonus(self) -> None:
        """L3-04는 기말/기초 여부만 1/0으로 점수화한다."""
        df = pd.DataFrame(
            {
                "debit_amount": [1000.0, 10.0, 900.0, 20.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "is_period_end": [True, True, False, True],
                "is_manual_je": [False, False, False, False],
                "gl_account": ["4000", "4000", "4000", "1200"],
                "account_group": ["revenue", "revenue", "revenue", "inventory"],
            }
        )
        detector = AnomalyDetector(
            audit_rules={
                "patterns": {},
            },
        )

        result = detector.detect(df)

        assert result.details["L3-04"].tolist() == [1.0, 1.0, 0.0, 1.0]
        assert set(result.details["L3-04"].unique()) == {0.0, 1.0}
        assert result.details["L3-04"].iloc[2] == 0.0
