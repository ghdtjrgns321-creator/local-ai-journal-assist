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
        "approved_by": ["Kim", "Kim", "Park", "Lee", "SYS"],
        "source": ["Manual", "automated", "SA", "Manual", "automated"],
        "business_process": ["O2C", "R2R", "TRE", "A2R", "R2R"],
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
        with pytest.raises(ValueError, match="empty"):
            layer.detect(pd.DataFrame())

    def test_rule_flags_count(self, full_df: pd.DataFrame) -> None:
        """실행된 룰 수 확인."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        # 11개 룰 중 일부는 피처/컬럼 부재로 skip될 수 있음
        assert len(result.rule_flags) > 0
        assert len(result.rule_flags) <= 10

    def test_b01_flags_revenue_outlier(self, full_df: pd.DataFrame) -> None:
        """L4-01: 매출+zscore>3 행이 flagged."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        # 행0: revenue=True, zscore=4.0 → L4-01 flagged
        assert result.details.loc[0, "L4-01"] > 0
        # 행2: revenue=False → L4-01 not flagged
        assert result.details.loc[2, "L4-01"] == 0.0

    def test_details_columns_are_rule_ids(self, full_df: pd.DataFrame) -> None:
        """details DataFrame의 컬럼이 룰 ID."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        for col in result.details.columns:
            assert "-" in col

    def test_l105_breakdown_metadata_exposes_immediate_and_review(self, full_df: pd.DataFrame) -> None:
        layer = FraudLayer()
        result = layer.detect(full_df)

        breakdown = result.metadata["rule_breakdowns"]["L1-05"]
        assert breakdown["immediate_rows"] == 1
        assert breakdown["review_rows"] == 1
        assert breakdown["override_counts"]["escalated_rows"] == 0
        assert breakdown["observed_summary"]["group_key"] == [
            "created_by",
            "business_process",
            "posting_month",
        ]
        assert isinstance(breakdown["observed_summary"]["top_groups"], list)

        l105_flag = next(flag for flag in result.rule_flags if flag.rule_id == "L1-05")
        assert l105_flag.detail == "immediate=1, review=1"

    def test_l107_breakdown_metadata_exposes_immediate_and_review(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame({
            "debit_amount": [20_000_000.0, 20_000_000.0],
            "credit_amount": [0.0, 0.0],
            "exceeds_threshold": [True, True],
            "source": ["Manual", "recurring"],
            "approved_by": ["", ""],
            "approval_date": [None, None],
        })

        result = layer.detect(df)
        breakdown = result.metadata["rule_breakdowns"]["L1-07"]
        assert breakdown["immediate_rows"] == 1
        assert breakdown["review_rows"] == 1

        l107_flag = next(flag for flag in result.rule_flags if flag.rule_id == "L1-07")
        assert l107_flag.detail == "immediate=1, review=1"
        assert result.details["L1-07"].tolist() == [0.8, 0.4]

    def test_flagged_indices_match_scores(self, full_df: pd.DataFrame) -> None:
        """flagged_indices와 scores > 0 일치 확인."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        expected = result.scores[result.scores > 0].index.tolist()
        assert sorted(result.flagged_indices) == sorted(expected)

    def test_l203_row_annotations_expose_reason_code_and_confidence(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame({
            "document_id": ["D100", "D101"],
            "auxiliary_account_number": ["V001", "V001"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "gl_account": [5100, 5100],
            "debit_amount": [5_000_000.0, 5_020_000.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-04"]),
        })

        result = layer.detect(df)
        annotations = result.metadata["row_annotations"]["L2-03"]
        assert annotations[0]["reason_code"] == "reference_duplicate"
        assert annotations[0]["confidence"] >= 0.9
        assert annotations[0]["confidence_band"] == "high"
        assert result.details["L2-03"].iloc[0] >= 0.9

    def test_l204_breakdown_and_annotations_expose_review_queue(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 5_000_000.0],
        })

        result = layer.detect(df)
        breakdown = result.metadata["rule_breakdowns"]["L2-04"]
        assert breakdown["immediate_rows"] == 0
        assert breakdown["review_rows"] == 2
        annotations = result.metadata["row_annotations"]["L2-04"]
        assert annotations[0]["reason_code"] == "line_amount_match"
        assert annotations[0]["queue_label"] == "review"
        assert result.details["L2-04"].iloc[0] == pytest.approx(0.65)
