"""Unit tests for the L2-06 reversal-pattern helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_reversal import (
    _s1_one_to_one_match,
    _s2_rolling_zero_out,
    _s2b_line_swap_signature,
    _s3_reversal_type,
    _s4_keyword_match,
    _s5_period_end_boost,
    c11_reversal_entry,
)


@pytest.fixture
def reversal_pair_df() -> pd.DataFrame:
    """Return a simple one-to-one reversal pair plus control rows."""

    return pd.DataFrame(
        {
            "document_id": ["D001", "D002", "D003", "D004"],
            "gl_account": ["1000", "1000", "2000", "3000"],
            "debit_amount": [1_000_000.0, 0.0, 500_000.0, 2_000_000.0],
            "credit_amount": [0.0, 1_000_000.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(
                ["2025-12-15", "2025-12-16", "2025-12-15", "2025-12-15"]
            ),
            "created_by": ["user_a", "user_a", "user_b", "user_c"],
            "source": ["manual", "manual", "automated", "manual"],
            "line_text": ["sales entry", "reversal entry", "normal expense", "asset entry"],
            "header_text": ["", "", "", ""],
            "fiscal_period": [12, 12, 12, 12],
            "is_period_end": [False, False, False, False],
        }
    )


class TestS1OneToOneMatch:
    def test_exact_reversal_flagged(self, reversal_pair_df: pd.DataFrame) -> None:
        result = _s1_one_to_one_match(reversal_pair_df, match_window_days=1)
        assert bool(result.iloc[0])
        assert bool(result.iloc[1])
        assert not result.iloc[2]
        assert not result.iloc[3]

    def test_same_document_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 100.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
            }
        )
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_different_account_not_matched(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "2000"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 100.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
            }
        )
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_amount_mismatch_not_matched(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 200.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
            }
        )
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_date_outside_window_not_matched(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 100.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-05"]),
            }
        )
        result = _s1_one_to_one_match(df, match_window_days=1)
        assert not result.any()

    def test_clearing_account_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["2900", "2900"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 100.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
            }
        )
        result = _s1_one_to_one_match(df)
        assert not result.any()


class TestS2RollingZeroOut:
    def test_three_entries_sum_zero_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002", "D003"],
                "gl_account": ["1000", "1000", "1000"],
                "debit_amount": [100_000.0, 0.0, 0.0],
                "credit_amount": [0.0, 60_000.0, 40_000.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-03", "2025-06-05"]),
                "created_by": ["user_a", "user_a", "user_a"],
            }
        )
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert result.any()

    def test_nonzero_sum_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [100_000.0, 0.0],
                "credit_amount": [0.0, 30_000.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-03"]),
                "created_by": ["user_a", "user_a"],
            }
        )
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert not result.any()

    def test_different_user_separate_group(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002", "D003"],
                "gl_account": ["1000", "1000", "1000"],
                "debit_amount": [100_000.0, 0.0, 0.0],
                "credit_amount": [0.0, 60_000.0, 40_000.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-03", "2025-06-05"]),
                "created_by": ["user_a", "user_b", "user_c"],
            }
        )
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert not result.any()

    def test_missing_created_by_returns_false(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [100.0, 0.0],
                "credit_amount": [0.0, 100.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-02"]),
            }
        )
        result = _s2_rolling_zero_out(df)
        assert not result.any()


class TestS2bLineSwapSignature:
    def test_single_swapped_line_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001", "D001", "D001"],
                "gl_account": ["500260", "500530", "2100", "2000"],
                "debit_amount": [72_000.0, 3_523.0, 51_421.0, 0.0],
                "credit_amount": [0.0, 0.0, 0.0, 24_102.0],
                "posting_date": pd.to_datetime(["2025-12-27"] * 4),
            }
        )
        result = _s2b_line_swap_signature(df)
        assert result.all()

    def test_regular_unbalanced_document_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001", "D001"],
                "gl_account": ["1000", "2000", "3000"],
                "debit_amount": [100.0, 40.0, 0.0],
                "credit_amount": [0.0, 0.0, 70.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01", "2025-06-01"]),
            }
        )
        result = _s2b_line_swap_signature(df)
        assert not result.any()


class TestS3ReversalType:
    def test_auto_january_discounted(self) -> None:
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2026-01-03"]),
                "source": ["automated"],
                "fiscal_period": [1],
            }
        )
        result = _s3_reversal_type(df)
        assert result.iloc[0] < 0

    def test_auto_other_month_start_discounted(self) -> None:
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2026-03-02"]),
                "source": ["recurring"],
                "fiscal_period": [3],
            }
        )
        result = _s3_reversal_type(df)
        assert result.iloc[0] < 0

    def test_manual_midmonth_boosted(self) -> None:
        df = pd.DataFrame(
            {
                "posting_date": pd.to_datetime(["2025-06-15"]),
                "source": ["manual"],
                "fiscal_period": [6],
            }
        )
        result = _s3_reversal_type(df)
        assert result.iloc[0] > 0

    def test_missing_source_zero(self) -> None:
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2025-06-15"])})
        result = _s3_reversal_type(df)
        assert result.iloc[0] == 0.0


class TestS4KeywordMatch:
    def test_korean_keyword_matched(self) -> None:
        df = pd.DataFrame({"line_text": ["수정 전표 입력"]})
        result = _s4_keyword_match(df)
        assert result.iloc[0]

    def test_english_keyword_matched(self) -> None:
        df = pd.DataFrame({"line_text": ["Reversal of accrual"]})
        result = _s4_keyword_match(df)
        assert result.iloc[0]

    def test_no_keyword_not_matched(self) -> None:
        df = pd.DataFrame({"line_text": ["normal purchase expense"]})
        result = _s4_keyword_match(df)
        assert not result.iloc[0]

    def test_header_text_ignored(self) -> None:
        df = pd.DataFrame(
            {
                "line_text": ["normal expense"],
                "header_text": ["Reversal batch job"],
            }
        )
        result = _s4_keyword_match(df)
        assert not result.iloc[0]

    def test_missing_line_text(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        result = _s4_keyword_match(df)
        assert not result.any()


class TestS5PeriodEndBoost:
    def test_december_end_boosted(self) -> None:
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2025-12-25"])})
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.5

    def test_january_start_boosted(self) -> None:
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2026-01-03"])})
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.5

    def test_midyear_no_boost(self) -> None:
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2025-06-15"])})
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.0

    def test_december_early_no_boost(self) -> None:
        df = pd.DataFrame({"posting_date": pd.to_datetime(["2025-12-10"])})
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.0


class TestC11ReversalEntry:
    def test_reversal_pair_flagged(self, reversal_pair_df: pd.DataFrame) -> None:
        result = c11_reversal_entry(reversal_pair_df, score_threshold=0.3)
        assert result.iloc[0] or result.iloc[1]

    def test_swapped_line_document_flagged_without_pair_match(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D001", "D001", "D001"],
                "gl_account": ["500260", "500530", "2100", "2000"],
                "debit_amount": [72_000.0, 3_523.0, 51_421.0, 0.0],
                "credit_amount": [0.0, 0.0, 0.0, 24_102.0],
                "posting_date": pd.to_datetime(["2025-12-27"] * 4),
                "source": ["manual"] * 4,
                "line_text": [
                    "invoice expense",
                    "temporary expense",
                    "vat receivable",
                    "ap clearing",
                ],
            }
        )
        result = c11_reversal_entry(df, score_threshold=0.3)
        assert result.all()

    def test_normal_entries_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002", "D003"],
                "gl_account": ["1000", "2000", "3000"],
                "debit_amount": [100.0, 200.0, 300.0],
                "credit_amount": [0.0, 0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-06-01", "2025-06-02", "2025-06-03"]),
                "source": ["automated", "automated", "automated"],
                "line_text": ["sales", "expense", "asset"],
            }
        )
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_keyword_only_without_amount_match_not_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "2000"],
                "debit_amount": [100.0, 200.0],
                "credit_amount": [0.0, 0.0],
                "posting_date": pd.to_datetime(["2025-12-25", "2025-12-26"]),
                "source": ["manual", "manual"],
                "line_text": ["수정 전표", "역분개 처리"],
            }
        )
        result = c11_reversal_entry(df, score_threshold=0.3)
        assert not result.any()

    def test_missing_core_columns_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_single_row_returns_false(self) -> None:
        df = pd.DataFrame(
            {
                "document_id": ["D001"],
                "gl_account": ["1000"],
                "debit_amount": [100.0],
                "credit_amount": [0.0],
                "posting_date": pd.to_datetime(["2025-06-01"]),
            }
        )
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_period_end_boost_increases_score(self) -> None:
        base_df = pd.DataFrame(
            {
                "document_id": ["D001", "D002"],
                "gl_account": ["1000", "1000"],
                "debit_amount": [1_000_000.0, 0.0],
                "credit_amount": [0.0, 1_000_000.0],
                "posting_date": pd.to_datetime(["2025-06-15", "2025-06-16"]),
                "source": ["manual", "manual"],
                "line_text": ["sales", "sales reversal"],
            }
        )
        yearend_df = base_df.copy()
        yearend_df["posting_date"] = pd.to_datetime(["2025-12-25", "2025-12-26"])

        result_mid = c11_reversal_entry(base_df, score_threshold=0.5)
        result_end = c11_reversal_entry(yearend_df, score_threshold=0.5)
        assert result_end.sum() >= result_mid.sum()
