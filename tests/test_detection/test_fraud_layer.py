"""FraudLayer.detect() 통합 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.fraud_layer import FraudLayer


@pytest.fixture
def full_df() -> pd.DataFrame:
    """18개 피처 포함 DataFrame — 다양한 부정 패턴 혼합."""
    return pd.DataFrame({
        # 필수 컬럼
        "debit_amount": [60e6, 45e6, 1e6, 80e6, 500.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
        # 원본 컬럼
        "gl_account": [4100, 4200, 1000, 4100, 1000],
        "posting_date": pd.to_datetime([
            "2025-01-01", "2025-01-01", "2025-01-15", "2025-02-01", "2025-01-01",
        ]),
        "auxiliary_account_number": ["V001", "V002", "V001", "V001", "V003"],
        "company_code": ["A", "B", "A", "B", "A"],
        "created_by": ["Kim", "Kim", "Kim", "Lee", "Lee"],
        "source": ["Manual", "automated", "SA", "Manual", "automated"],
        "business_process": ["입력", "승인", "이체", "입력", "승인"],
        # 피처 컬럼
        "is_revenue_account": [True, True, False, True, False],
        "amount_zscore": [4.0, 1.5, 0.2, 3.5, 0.1],
        "is_near_threshold": [False, True, False, False, False],
        "exceeds_threshold": [True, False, False, True, False],
        "is_manual_je": [True, False, False, True, False],
        "is_intercompany": [True, True, False, False, False],
    })


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """필수 컬럼만 있는 DataFrame — graceful degradation 테스트."""
    return pd.DataFrame({
        "debit_amount": [100.0, 200.0],
        "credit_amount": [0.0, 0.0],
    })


class TestFraudLayerDetect:
    def test_returns_detection_result(self, full_df: pd.DataFrame) -> None:
        """DetectionResult 구조 검증."""
        layer = FraudLayer()
        result = layer.detect(full_df)

        assert result.track_name == "layer_b"
        assert len(result.scores) == len(full_df)
        assert result.scores.between(0.0, 1.0).all()
        assert isinstance(result.rule_flags, list)
        assert isinstance(result.details, pd.DataFrame)
        assert result.metadata["elapsed"] > 0

    def test_scores_max_not_sum(self, full_df: pd.DataFrame) -> None:
        """한 행이 여러 룰에 걸릴 때 합산 아닌 최대값 사용."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        # 모든 scores가 1.0 이하여야 함 (합산이면 1.0 초과 가능)
        assert result.scores.max() <= 1.0

    def test_minimal_df_graceful(self, minimal_df: pd.DataFrame) -> None:
        """필수 컬럼만 있어도 에러 없이 실행."""
        layer = FraudLayer()
        result = layer.detect(minimal_df)
        assert result.track_name == "layer_b"
        assert len(result.scores) == 2

    def test_empty_df_raises(self) -> None:
        """빈 DataFrame → ValueError."""
        layer = FraudLayer()
        with pytest.raises(ValueError, match="비어"):
            layer.detect(pd.DataFrame())

    def test_rule_flags_count(self, full_df: pd.DataFrame) -> None:
        """실행된 룰 수 확인."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        # 10개 룰 중 일부는 피처/컬럼 부재로 skip될 수 있음
        assert len(result.rule_flags) > 0
        assert len(result.rule_flags) <= 10

    def test_b01_flags_revenue_outlier(self, full_df: pd.DataFrame) -> None:
        """B01: 매출+zscore>3 행이 flagged."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        # 행0: revenue=True, zscore=4.0 → B01 flagged
        assert result.details.loc[0, "B01"] > 0
        # 행2: revenue=False → B01 not flagged
        assert result.details.loc[2, "B01"] == 0.0

    def test_details_columns_are_rule_ids(self, full_df: pd.DataFrame) -> None:
        """details DataFrame의 컬럼이 룰 ID."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        for col in result.details.columns:
            assert col.startswith("B")

    def test_flagged_indices_match_scores(self, full_df: pd.DataFrame) -> None:
        """flagged_indices와 scores > 0 일치 확인."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        expected = result.scores[result.scores > 0].index.tolist()
        assert sorted(result.flagged_indices) == sorted(expected)
