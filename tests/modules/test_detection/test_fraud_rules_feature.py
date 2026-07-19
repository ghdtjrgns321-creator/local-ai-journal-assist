"""Unit tests for feature-based fraud rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.fraud_rules_feature import (
    b01_revenue_manipulation,
    b02_near_threshold,
    b03_exceeds_threshold,
    b08_manual_override,
)


@pytest.fixture
def feature_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "debit_amount": [60e6, 40e6, 10e6, 80e6, 30e6, 55e6],
            "credit_amount": [0.0] * 6,
            "is_revenue_account": [True, True, False, True, False, True],
            "amount_zscore_log": [4.0, 2.0, 5.0, 3.5, 1.0, 0.5],
            "is_near_threshold": [False, True, False, False, True, False],
            "exceeds_threshold": [True, False, False, True, False, True],
            "is_manual_je": [True, False, False, True, True, False],
        }
    )


class TestL4_01:
    def test_revenue_high_zscore_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert result[0]
        assert result[3]

    def test_revenue_low_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[1]
        assert not result[5]

    def test_non_revenue_high_zscore_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b01_revenue_manipulation(feature_df, zscore_threshold=3.0)
        assert not result[2]

    def test_document_with_non_revenue_outlier_does_not_backfill_revenue_row(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001"],
                "gl_account": ["4000", "5000"],
                "is_revenue_account": [True, False],
                "amount_zscore_log": [2.8, 9.0],
            }
        )

        result = b01_revenue_manipulation(df, zscore_threshold=3.0)

        assert result.tolist() == [False, False]
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]

    def test_missing_features_returns_all_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        result = b01_revenue_manipulation(df)
        assert not result.any()

    def test_exposes_binary_scores_and_annotations(self) -> None:
        df = pd.DataFrame(
            {
                "gl_account": ["4100", "4100", "4100", "5100"],
                "is_revenue_account": [True, True, True, False],
                "amount_zscore_log": [3.2, 4.5, 6.2, 8.0],
            }
        )

        result = b01_revenue_manipulation(df, zscore_threshold=3.0)

        assert result.tolist() == [True, True, True, False]
        # binary: z-score 폭과 무관하게 발화=1.0/미발화=0.0 (구 0.45/0.60/0.75 bucket 폐기)
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 0.0]
        assert sorted(set(result.attrs["score_series"].tolist())) == [0.0, 1.0]
        assert result.attrs["breakdown"]["flagged_rows"] == 3
        assert "bucket_counts" not in result.attrs["breakdown"]
        assert "score_bands" not in result.attrs["breakdown"]
        assert "bucket" not in result.attrs["row_annotations"][0]
        assert result.attrs["row_annotations"][0]["score"] == 1.0
        assert result.attrs["row_annotations"][2]["interpretation"] == (
            "relative_high_value_revenue"
        )


class TestL2_01:
    def test_near_threshold_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert result[1]
        assert result[4]

    def test_not_near_threshold(self, feature_df: pd.DataFrame) -> None:
        result = b02_near_threshold(feature_df)
        assert not result[0]

    def test_missing_feature(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b02_near_threshold(df).any()

    def test_exposes_binary_scores_and_annotations(self) -> None:
        df = pd.DataFrame(
            {
                "is_near_threshold": [True, True, True, False, False],
                "source": ["manual", "manual", "manual", "manual", "manual"],
                "near_threshold_bucket": [
                    "lower_band",
                    "close_band",
                    "razor_band",
                    "none",
                    "unresolved_limit",
                ],
                "near_threshold_amount": [91.0, 96.0, 99.0, 80.0, 95.0],
                "near_threshold_limit_amount": [100.0, 100.0, 100.0, 100.0, pd.NA],
                "near_threshold_ratio_to_limit": [0.91, 0.96, 0.99, 0.80, pd.NA],
                "near_threshold_gap_amount": [9.0, 4.0, 1.0, 20.0, pd.NA],
                "near_threshold_gap_ratio": [0.09, 0.04, 0.01, 0.20, pd.NA],
                "near_threshold_limit_resolved": [True, True, True, True, False],
            }
        )

        result = b02_near_threshold(df)

        assert result.tolist() == [True, True, True, False, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["bucket_counts"] == {
            "lower_band": 1,
            "close_band": 1,
            "razor_band": 1,
        }
        assert result.attrs["breakdown"]["scored_rows"] == 3
        assert result.attrs["breakdown"]["zero_score_rows"] == 0
        assert result.attrs["breakdown"]["unresolved_limit_rows"] == 1
        assert result.attrs["row_annotations"][2]["bucket"] == "razor_band"
        assert result.attrs["row_annotations"][2]["queue_label"] == "priority_review"
        assert result.attrs["row_annotations"][2]["near_threshold_gap_ratio"] == 0.01

    def test_routine_source_hits_are_binary_flags(self) -> None:
        df = pd.DataFrame(
            {
                "is_near_threshold": [True, True, True, True],
                "source": ["automated", "recurring", "automated", "manual"],
                "near_threshold_bucket": ["lower_band", "close_band", "razor_band", "close_band"],
            }
        )

        result = b02_near_threshold(df)

        assert result.tolist() == [True, True, True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 1.0]
        assert result.attrs["breakdown"]["flagged_rows"] == 4
        assert result.attrs["breakdown"]["scored_rows"] == 4
        assert result.attrs["breakdown"]["zero_score_rows"] == 0
        assert result.attrs["row_annotations"][0]["queue_label"] == "priority_review"
        assert result.attrs["row_annotations"][2]["queue_label"] == "priority_review"

    def test_annotations_preserve_non_integer_index(self) -> None:
        df = pd.DataFrame(
            {
                "is_near_threshold": [True],
                "near_threshold_bucket": ["razor_band"],
            },
            index=["row-a"],
        )

        result = b02_near_threshold(df)

        assert result.attrs["row_annotations"]["row-a"]["bucket"] == "razor_band"


class TestL1_04:
    def test_exceeds_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert result[0]
        assert result[3]
        assert result[5]

    def test_not_exceeds(self, feature_df: pd.DataFrame) -> None:
        result = b03_exceeds_threshold(feature_df)
        assert not result[1]

    def test_exposes_bucket_scores_and_annotations(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [True, True, True, False],
                "approval_excess_bucket": ["boundary", "severe", "non_approver", "none"],
                "document_approval_amount": [105.0, 175.0, 50.0, 90.0],
                "approver_limit_amount": [100.0, 100.0, 0.0, 100.0],
                "approval_excess_amount": [5.0, 75.0, 50.0, 0.0],
                "approval_excess_ratio": [0.05, 0.75, pd.NA, pd.NA],
                "approval_limit_resolved": [True, True, True, True],
                "approver_can_approve_je": [True, True, False, True],
                "approval_level": [1, 2, 1, 0],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True, True, True, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.0, 0.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["bucket_counts"] == {
            "boundary": 1,
            "severe": 1,
            "non_approver": 1,
        }
        assert result.attrs["breakdown"]["immediate_rows"] == 3
        assert result.attrs["breakdown"]["review_rows"] == 0
        assert result.attrs["row_annotations"][0]["queue_label"] == "binary_flag"
        assert result.attrs["row_annotations"][1]["bucket"] == "severe"
        assert result.attrs["row_annotations"][1]["approval_excess_ratio"] == 0.75

    def test_unresolved_limit_with_approver_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [True, True],
                "approval_excess_bucket": ["boundary", "unresolved_limit"],
                "approval_limit_resolved": [True, False],
                "approved_by": ["APR1", "APR2"],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True, True]
        assert result.attrs["breakdown"]["bucket_counts"] == {"boundary": 1, "unresolved_limit": 1}
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_blank_approver_is_not_l104(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [True],
                "approval_limit_resolved": [False],
                "approved_by": [""],
            }
        )

        assert not b03_exceeds_threshold(df).any()

    def test_unknown_approver_is_not_l104_even_when_limit_unresolved(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [False],
                "approval_limit_resolved": [False],
                "approved_by": ["APR-GHOST"],
                "approver_in_master": pd.Series([False], dtype="boolean"),
                "approver_can_approve_je": pd.Series([pd.NA], dtype="boolean"),
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [False]

    def test_real_approver_over_limit_remains_l104(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [True],
                "approval_excess_bucket": ["severe"],
                "approval_limit_resolved": [True],
                "approved_by": ["APR-REAL"],
                "approver_in_master": pd.Series([True], dtype="boolean"),
                "approver_can_approve_je": pd.Series([True], dtype="boolean"),
                "document_approval_amount": [1_500.0],
                "approver_limit_amount": [1_000.0],
                "approval_excess_amount": [500.0],
                "approval_excess_ratio": [0.5],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]

    def test_automated_context_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "exceeds_threshold": [True, True],
                "approval_excess_bucket": ["severe", "critical"],
                "approval_limit_resolved": [True, True],
                "source": ["automated", "Manual"],
                "user_persona": ["automated_system", "senior_accountant"],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True, True]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["breakdown"]["immediate_rows"] == 2
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_lone_automated_source_approval_excess_keeps_original_bucket(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "exceeds_threshold": [True],
                "approval_excess_bucket": ["critical"],
                "approval_limit_resolved": [True],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
                "batch_id": [None],
                "job_id": [None],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_batched_automated_source_approval_excess_is_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "exceeds_threshold": [True],
                "approval_excess_bucket": ["critical"],
                "approval_limit_resolved": [True],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
                "batch_id": ["BATCH-1"],
                "job_id": [None],
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["immediate_rows"] == 1
        assert result.attrs["breakdown"]["review_rows"] == 0

    def test_missing_identity_columns_still_binary_flag(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1"],
                "exceeds_threshold": [True],
                "approval_excess_bucket": ["critical"],
                "approval_limit_resolved": [True],
                "source": ["automated"],
                "posting_date": pd.to_datetime(["2025-01-02"]),
            }
        )

        result = b03_exceeds_threshold(df)

        assert result.tolist() == [True]
        assert result.attrs["score_series"].tolist() == [1.0]
        assert result.attrs["review_score_series"].tolist() == [0.0]
        assert result.attrs["breakdown"]["review_rows"] == 0


class TestL3_02:
    def test_manual_entry_scores_binary(
        self,
        feature_df: pd.DataFrame,
    ) -> None:
        result = b08_manual_override(feature_df)
        assert result[0]
        assert result[3]
        assert result[4]
        assert result.attrs["score_series"].tolist() == [1.0, 0.0, 0.0, 1.0, 1.0, 0.0]
        assert "review_score_series" not in result.attrs
        assert result.attrs["breakdown"]["flagged_rows"] == 3
        assert result.attrs["breakdown"]["manual_rows"] == 3
        assert result.attrs["breakdown"]["adjustment_rows"] == 0

    def test_non_manual_not_flagged(self, feature_df: pd.DataFrame) -> None:
        result = b08_manual_override(feature_df)
        assert not result[1]
        assert not result[2]
        assert not result[5]

    def test_source_fallback_uses_manual_source_codes(self) -> None:
        df = pd.DataFrame({"source": ["Manual", "Adjustment", "automated", None]})
        result = b08_manual_override(df)
        assert result.tolist() == [True, True, False, False]
        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["manual_rows"] == 1
        assert result.attrs["breakdown"]["adjustment_rows"] == 1
        assert result.attrs["breakdown"]["flagged_rows"] == 2

    def test_source_fallback_uses_injected_manual_source_codes(self) -> None:
        df = pd.DataFrame({"source": ["LegacyManual", "Manual", "Adjustment"]})
        result = b08_manual_override(
            df,
            audit_rules={"patterns": {"manual_source_codes": ["LegacyManual"]}},
        )
        assert result.tolist() == [True, False, False]
        assert result.attrs["score_series"].tolist() == [1.0, 0.0, 0.0]

    def test_annotations_keep_fact_values_only(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D2", "D3"],
                "source": ["Manual", "Adjustment", "Manual"],
                "is_manual_je": [True, True, True],
                "created_by": ["u1", "u2", "u3"],
                "approved_by": ["u1", "manager", ""],
                "approval_date": ["2025-01-02", "", ""],
                "exceeds_threshold": [False, False, True],
                "is_period_end": [False, True, False],
                "description_quality": ["good", "poor", "good"],
                "gl_account": ["5100", "1190", "4100"],
            }
        )

        result = b08_manual_override(df)

        assert result.attrs["score_series"].tolist() == [1.0, 1.0, 1.0]
        assert result.attrs["breakdown"]["flagged_rows"] == 3
        assert result.attrs["breakdown"]["adjustment_rows"] == 1
        assert result.attrs["row_annotations"][0]["score"] == 1.0
        assert result.attrs["row_annotations"][0]["document_id"] == "D1"
        assert "bucket" not in result.attrs["row_annotations"][0]
        assert "priority_reasons" not in result.attrs["row_annotations"][1]
