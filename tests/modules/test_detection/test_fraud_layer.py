"""FraudLayer.detect() 통합 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.constants import RiskLevel
from src.detection.fraud_layer import FraudLayer
from src.detection.score_aggregator import aggregate_scores


@pytest.fixture
def full_df() -> pd.DataFrame:
    """18개 피처 포함 DataFrame — 다양한 부정 패턴 혼합."""
    return pd.DataFrame(
        {
            # 필수 컬럼
            "debit_amount": [60e6, 45e6, 1e6, 80e6, 500.0],
            "credit_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            # 원본 컬럼
            "gl_account": [4100, 4200, 1000, 4100, 1000],
            "posting_date": pd.to_datetime(
                [
                    "2025-01-01",
                    "2025-01-01",
                    "2025-01-15",
                    "2025-02-01",
                    "2025-01-01",
                ]
            ),
            "auxiliary_account_number": ["V001", "V002", "V001", "V001", "V003"],
            "company_code": ["A", "B", "A", "B", "A"],
            "created_by": ["Kim", "Kim", "Kim", "Lee", "Lee"],
            "approved_by": ["Kim", "Kim", "Park", "Lee", "SYS"],
            "source": ["Manual", "automated", "SA", "Manual", "automated"],
            "business_process": ["O2C", "R2R", "TRE", "A2R", "R2R"],
            # 피처 컬럼
            "is_revenue_account": [True, True, False, True, False],
            "amount_zscore": [4.0, 1.5, 0.2, 3.5, 0.1],
            "amount_zscore_log": [4.0, 1.5, 0.2, 3.5, 0.1],
            "is_near_threshold": [False, True, False, False, False],
            "exceeds_threshold": [True, False, False, True, False],
            "is_manual_je": [True, False, False, True, False],
            "is_intercompany": [True, True, False, False, False],
        }
    )


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """필수 컬럼만 있는 DataFrame — graceful degradation 테스트."""
    return pd.DataFrame(
        {
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
        }
    )


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

    def test_l303_derives_intercompany_from_gl_prefix(self) -> None:
        """is_intercompany shortcut 없이도 L3-03은 GL prefix로 binary flag를 산출."""
        df = pd.DataFrame(
            {
                "debit_amount": [100.0, 200.0],
                "credit_amount": [0.0, 0.0],
                "gl_account": ["1150-001", "4100"],
            }
        )

        result = FraudLayer().detect(df)

        assert "L3-03" not in result.metadata["skipped_rules"]
        assert result.details["L3-03"].tolist() == [1.0, 0.0]

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
        assert len(result.rule_flags) <= 14

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

    def test_l105_breakdown_metadata_exposes_binary_flags(
        self,
        full_df: pd.DataFrame,
    ) -> None:
        layer = FraudLayer()
        result = layer.detect(full_df)

        breakdown = result.metadata["rule_breakdowns"]["L1-05"]
        assert breakdown["immediate_rows"] == 3
        assert breakdown["review_rows"] == 0
        assert breakdown["allowed_system_rows"] == 0
        assert breakdown["bucket_counts"] == {
            "binary_flag": 3,
        }
        assert breakdown["override_counts"] == {}
        assert breakdown["observed_summary"]["group_key"] == [
            "created_by",
            "business_process",
            "posting_month",
        ]
        assert isinstance(breakdown["observed_summary"]["top_groups"], list)
        assert result.details["L1-05"].tolist() == [1.0, 1.0, 0.0, 1.0, 0.0]
        assert result.metadata["review_score_series"]["L1-05"].tolist() == [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ]
        assert breakdown["observed_summary"]["queue_counts"] == {
            "general_immediate": 3,
        }
        assert result.metadata["row_annotations"]["L1-05"][0]["bucket"] == "binary_flag"
        assert result.metadata["row_annotations"]["L1-05"][1]["bucket"] == "binary_flag"
        assert result.metadata["row_annotations"]["L1-05"][1]["score"] == 1.0
        assert result.metadata["row_annotations"]["L1-05"][1]["review_score"] == 0.0
        assert result.metadata["row_annotations"]["L1-05"][3]["bucket"] == "binary_flag"
        assert result.metadata["row_annotations"]["L1-05"][3]["review_score"] == 0.0

        l105_flag = next(flag for flag in result.rule_flags if flag.rule_id == "L1-05")
        assert l105_flag.detail == "immediate=3, review=0"
        assert l105_flag.flagged_count == 3

    def test_l105_binary_flags_and_trusted_system_exclusion(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "debit_amount": [100.0, 100.0, 100.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "created_by": ["U1", "U2", "SYS"],
                "approved_by": ["U1", "U2", "SYS"],
                "business_process": ["R2R", "O2C", "R2R"],
                "user_persona": ["controller", "controller", "automated_system"],
                "source": ["interface", "interface", "automated"],
            }
        )

        detection = FraudLayer().detect(df)
        result = aggregate_scores(df, [detection])

        assert result["flagged_rules"].tolist() == ["L1-05", "L1-05", ""]
        assert result["review_rules"].tolist() == ["", "", ""]
        assert result["risk_level"].iloc[0] == RiskLevel.LOW
        assert result["risk_level"].iloc[1] == RiskLevel.LOW
        assert result["risk_level"].iloc[2] == RiskLevel.NORMAL

    def test_l107_breakdown_metadata_exposes_binary_blank_approver(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "debit_amount": [20_000_000.0, 20_000_000.0],
                "credit_amount": [0.0, 0.0],
                "exceeds_threshold": [True, True],
                "source": ["Manual", "recurring"],
                "approved_by": ["", ""],
                "approval_date": [None, None],
            }
        )

        result = layer.detect(df)
        breakdown = result.metadata["rule_breakdowns"]["L1-07"]
        assert breakdown["blank_approved_by_rows"] == 2
        assert breakdown["candidate_rows"] == 2
        assert breakdown["score_bands"] == {"binary_flag": 2}

        l107_flag = next(flag for flag in result.rule_flags if flag.rule_id == "L1-07")
        assert l107_flag.flagged_count == 2
        assert result.details["L1-07"].tolist() == [1.0, 1.0]
        assert result.metadata["review_score_series"]["L1-07"].eq(0.0).all()
        assert result.metadata["row_annotations"]["L1-07"][0]["queue_label"] == "binary_flag"
        assert result.metadata["row_annotations"]["L1-07"][1]["reason_code"] == "blank_approved_by"

    def test_l302_breakdown_metadata_exposes_manual_buckets(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "document_id": ["M1", "M2", "M3", "A1"],
                "debit_amount": [100.0, 200.0, 300.0, 400.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "source": ["Manual", "Adjustment", "Manual", "automated"],
                "is_manual_je": [True, True, True, False],
                "created_by": ["u1", "u2", "u3", "sys"],
                "approved_by": ["mgr", "mgr", "u3", "sys"],
                "approval_date": ["2025-01-02", "", "2025-01-03", "2025-01-01"],
                "exceeds_threshold": [False, False, False, False],
                "is_period_end": [False, True, False, False],
                "description_quality": ["good", "poor", "good", "good"],
            }
        )

        result = layer.detect(df)

        breakdown = result.metadata["rule_breakdowns"]["L3-02"]
        assert breakdown["flagged_rows"] == 3
        assert breakdown["manual_rows"] == 2
        assert breakdown["adjustment_rows"] == 1
        assert result.details["L3-02"].tolist() == [1.0, 1.0, 1.0, 0.0]
        assert "L3-02" not in result.metadata["review_score_series"].columns
        assert result.metadata["row_annotations"]["L3-02"][1]["score"] == 1.0
        assert "bucket" not in result.metadata["row_annotations"]["L3-02"][1]
        assert "priority_reasons" not in result.metadata["row_annotations"]["L3-02"][1]

    def test_l302_uses_injected_manual_source_codes(self) -> None:
        layer = FraudLayer(audit_rules={"patterns": {"manual_source_codes": ["LegacyManual"]}})
        df = pd.DataFrame(
            {
                "document_id": ["M1", "M2"],
                "debit_amount": [100.0, 200.0],
                "credit_amount": [0.0, 0.0],
                "source": ["LegacyManual", "Manual"],
            }
        )

        result = layer.detect(df)

        assert result.details["L3-02"].tolist() == [1.0, 0.0]
        assert "L3-02" not in result.metadata["review_score_series"].columns
        assert result.metadata["rule_breakdowns"]["L3-02"]["manual_rows"] == 1

    def test_l312_work_scope_excess_is_registered(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "debit_amount": [100.0, 200.0, 300.0, 400.0],
                "credit_amount": [0.0, 0.0, 0.0, 0.0],
                "created_by": ["u1", "u1", "u1", "u1"],
                "user_persona": ["accountant"] * 4,
                "business_process": ["P2P", "O2C", "R2R", "TRE"],
                "company_code": ["1000", "2000", "3000", "3000"],
                "source": ["manual", "automated", "automated", "automated"],
                "gl_account": ["1190", "5100", "4100", "1100"],
                "is_period_end": [True, False, False, False],
            }
        )

        result = layer.detect(df)

        assert result.details["L3-12"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.metadata["review_score_series"]["L3-12"].tolist() == [
            0.65,
            0.65,
            0.65,
            0.65,
        ]
        assert result.metadata["rule_breakdowns"]["L3-12"]["candidate_users"] == 1
        assert result.metadata["row_annotations"]["L3-12"][0]["review_score"] == 0.65
        assert result.metadata["row_annotations"]["L3-12"][0]["rule_boundary"].startswith("L1-06")

    def test_flagged_indices_match_scores(self, full_df: pd.DataFrame) -> None:
        """flagged_indices와 scores > 0 일치 확인."""
        layer = FraudLayer()
        result = layer.detect(full_df)
        expected = result.scores[result.scores > 0].index.tolist()
        assert sorted(result.flagged_indices) == sorted(expected)

    def test_l203_row_annotations_expose_reason_code_and_confidence(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "document_id": ["D100", "D101"],
                "auxiliary_account_number": ["V001", "V001"],
                "reference": ["INV-2025-001", "INV-2025-001"],
                "gl_account": [5100, 5100],
                "debit_amount": [5_000_000.0, 5_020_000.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-01-01", "2025-01-04"]),
            }
        )

        result = layer.detect(df)
        annotations = result.metadata["row_annotations"]["L2-03"]
        assert annotations[0]["reason_code"] == "reference_duplicate"
        assert annotations[0]["matched_reason_codes"] == ["reference_duplicate"]
        assert annotations[0]["confidence"] == pytest.approx(1.0)
        assert annotations[0]["confidence_band"] == "binary"
        assert result.details["L2-03"].iloc[0] == pytest.approx(1.0)

    def test_l202_breakdown_and_annotations_expose_match_strength(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002", "D003"],
                "document_type": ["KZ", "KZ", "KZ"],
                "auxiliary_account_number": ["V001", "V001", ""],
                "debit_amount": [5_000_000.0, 5_010_000.0, 1_000_000.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-01-01", "2025-01-10", "2025-01-12"]),
                "business_process": ["P2P", "P2P", "P2P"],
                "reference": ["INV-001", "INV-001", ""],
            }
        )

        result = layer.detect(df)

        breakdown = result.metadata["rule_breakdowns"]["L2-02"]
        assert breakdown["reference_match_docs"] == 1
        assert breakdown["partner_key_coverage_ratio"] == pytest.approx(2 / 3)
        annotations = result.metadata["row_annotations"]["L2-02"]
        assert annotations[1]["reason_code"] == "reference_match"
        assert annotations[1]["confidence_band"] == "binary"
        assert result.details["L2-02"].tolist() == [0.0, 1.0, 0.0]

    def test_l204_breakdown_and_annotations_expose_binary_match(self) -> None:
        layer = FraudLayer()
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001"],
                "gl_account": ["1500", "6100"],
                "debit_amount": [5_000_000.0, 0.0],
                "credit_amount": [0.0, 5_000_000.0],
            }
        )

        result = layer.detect(df)
        breakdown = result.metadata["rule_breakdowns"]["L2-04"]
        assert breakdown == {"flagged_rows": 2, "matched_docs": 1}
        annotations = result.metadata["row_annotations"]["L2-04"]
        assert annotations[0]["match_type"] == "line_amount_match"
        assert annotations[0]["score"] == pytest.approx(1.0)
        assert "queue_label" not in annotations[0]
        assert "confidence_band" not in annotations[0]
        assert result.details["L2-04"].iloc[0] == pytest.approx(1.0)
        assert result.metadata["review_score_series"]["L2-04"].iloc[0] == pytest.approx(0.0)
