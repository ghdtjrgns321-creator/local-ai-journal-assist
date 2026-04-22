"""Unit tests for groupby-based rules."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.fraud_rules_groupby import (
    b04_duplicate_payment,
    b05_duplicate_entry,
    b11_expense_capitalization,
)


@pytest.fixture
def dup_payment_df() -> pd.DataFrame:
    """Baseline L2-02 fixture with same partner and amount."""

    return pd.DataFrame({
        "document_id": ["D001", "D002", "D003", "D004"],
        "document_type": ["KZ", "KZ", "KZ", "KZ"],
        "auxiliary_account_number": ["V001", "V001", "V001", "V002"],
        "debit_amount": [1e6, 1e6, 1e6, 2e6],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-01-01",
            "2025-01-10",
            "2025-03-01",
            "2025-01-05",
        ]),
        "business_process": ["P2P", "P2P", "P2P", "P2P"],
    })


@pytest.fixture
def dup_entry_df() -> pd.DataFrame:
    """Baseline L2-03 fixture."""

    return pd.DataFrame({
        "document_id": ["D001", "D002", "D003", "D004"],
        "auxiliary_account_number": ["V001", "V001", "V001", "V002"],
        "line_text": ["Laptop purchase", "Laptop purchase", "Office chair", "Office chair"],
        "reference": ["REF-1", "REF-1", "", ""],
        "gl_account": [1000, 1000, 1000, 2000],
        "debit_amount": [500.0, 500.0, 500.0, 500.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-01-01",
            "2025-01-01",
            "2025-01-02",
            "2025-01-01",
        ]),
    })


class TestL2_02:
    def test_within_window_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        result = b04_duplicate_payment(dup_payment_df, window_days=45)
        assert result[1]
        assert not result[0]

    def test_outside_window_not_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        result = b04_duplicate_payment(dup_payment_df, window_days=45)
        assert not result[2]

    def test_different_vendor_not_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        result = b04_duplicate_payment(dup_payment_df, window_days=45)
        assert not result[3]

    def test_missing_partner_columns_skip(self) -> None:
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-01-01"]),
        })
        assert not b04_duplicate_payment(df).any()

    def test_triple_duplicate_all_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "document_type": ["KZ"] * 3,
            "auxiliary_account_number": ["V001"] * 3,
            "debit_amount": [1e6] * 3,
            "credit_amount": [0.0] * 3,
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-20"]),
            "business_process": ["P2P"] * 3,
        })
        result = b04_duplicate_payment(df, window_days=45)
        assert not result[0]
        assert result[1]
        assert result[2]

    def test_exactly_window_boundary_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-02-15"]),
            "business_process": ["P2P", "P2P"],
        })
        result = b04_duplicate_payment(df, window_days=45)
        assert not result[0]
        assert result[1]

    def test_o2c_excluded(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["C001", "C001"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-05"]),
            "business_process": ["O2C", "O2C"],
        })
        assert not b04_duplicate_payment(df).any()

    def test_same_reference_different_doc_flagged(self) -> None:
        df = pd.DataFrame({
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [5_000_000, 5_020_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-15"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "document_id": ["D001", "D002"],
        })
        result = b04_duplicate_payment(df, reference_amount_tolerance=0.01)
        assert not result[0]
        assert result[1]

    def test_same_reference_same_doc_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [5e6, 0.0],
            "credit_amount": [0.0, 5e6],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "document_id": ["D001", "D001"],
        })
        assert not b04_duplicate_payment(df).any()

    def test_trading_partner_fallback_used(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "trading_partner": ["VEND-A", "VEND-A"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-03", "2025-01-25"]),
            "business_process": ["P2P", "P2P"],
        })
        result = b04_duplicate_payment(df, window_days=45)
        assert not result[0]
        assert result[1]

    def test_monthly_recurring_payments_suppressed(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "document_type": ["KZ", "KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001", "V001"],
            "debit_amount": [2_500_000, 2_500_000, 2_500_000],
            "credit_amount": [0.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"]),
            "business_process": ["P2P", "P2P", "P2P"],
            "reference": [None, None, None],
        })
        assert not b04_duplicate_payment(df, window_days=45).any()

    def test_reference_variant_normalization_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [2_950_000, 2_950_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-10", "2025-01-16"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C001-2025-001", "PAY / PAY-C001-2025-001"],
        })
        result = b04_duplicate_payment(df, reference_amount_tolerance=0.01)
        assert not result[0]
        assert result[1]

    def test_blank_reference_duplicate_flagged_against_original_reference(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [636_680, 636_680],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-05", "2025-01-09"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C001-2025-002", ""],
        })
        result = b04_duplicate_payment(df, window_days=45)
        assert not result[0]
        assert result[1]

    def test_non_kz_documents_excluded(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KR", "KR"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-10"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["INV-1", "INV-1"],
        })
        assert not b04_duplicate_payment(df).any()


class TestL2_03:
    def test_exact_match_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        result = b05_duplicate_entry(dup_entry_df)
        assert result[0]
        assert result[1]
        assert result.attrs["row_annotations"][0]["reason_code"] in {
            "exact_duplicate",
            "reference_duplicate",
        }
        assert result.attrs["row_annotations"][0]["confidence"] >= 0.9

    def test_different_date_not_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        result = b05_duplicate_entry(dup_entry_df)
        assert not result[2]

    def test_different_gl_not_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        result = b05_duplicate_entry(dup_entry_df)
        assert not result[3]

    def test_same_document_same_day_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": [1000, 1000],
            "debit_amount": [500.0, 500.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
        })
        assert not b05_duplicate_entry(df).any()

    def test_same_reference_different_documents_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D100", "D101"],
            "auxiliary_account_number": ["V001", "V001"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "gl_account": [5100, 5100],
            "debit_amount": [5_000_000, 5_020_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-04"]),
        })
        result = b05_duplicate_entry(df, amount_tolerance=0.01)
        assert result.all()
        assert result.attrs["row_annotations"][0]["reason_code"] == "reference_duplicate"
        assert result.attrs["row_annotations"][0]["confidence_band"] == "high"

    def test_fuzzy_text_within_window_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D200", "D201"],
            "auxiliary_account_number": ["V001", "V001"],
            "line_text": ["Cloud hosting Jan invoice", "Invoice for January cloud hosting"],
            "gl_account": [6200, 6200],
            "debit_amount": [1_000_000, 1_010_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-05"]),
        })
        result = b05_duplicate_entry(df, amount_tolerance=0.02, fuzzy_threshold=80, window_days=7)
        assert result.all()
        assert result.attrs["row_annotations"][0]["reason_code"] == "near_duplicate"
        assert result.attrs["row_annotations"][0]["confidence_band"] in {"medium", "low"}

    def test_split_entries_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D300", "D301", "D302"],
            "auxiliary_account_number": ["V001", "V001", "V001"],
            "gl_account": [7000, 7000, 7000],
            "debit_amount": [1_000_000, 600_000, 400_000],
            "credit_amount": [0.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03"]),
        })
        result = b05_duplicate_entry(df, split_window_days=3, amount_tolerance=0.02)
        assert result.all()
        assert result.attrs["row_annotations"][0]["reason_code"] == "split_duplicate"
        assert result.attrs["row_annotations"][0]["confidence"] == pytest.approx(0.75)

    def test_missing_column_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not b05_duplicate_entry(df).any()


class TestL2_04:
    def test_expense_to_asset_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "gl_account": ["1500", "6100", "1010", "2000"],
            "debit_amount": [5e6, 0.0, 1e6, 0.0],
            "credit_amount": [0.0, 5e6, 0.0, 1e6],
        })
        result = b11_expense_capitalization(df)
        assert result[0]
        assert result[1]
        assert not result[2]
        assert not result[3]

    def test_expense_prefixes_broadened_beyond_6xxx(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1520", "5200"],
            "debit_amount": [3_000_000.0, 0.0],
            "credit_amount": [0.0, 3_000_000.0],
        })
        result = b11_expense_capitalization(df)
        assert result.all()

    def test_no_match_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1010", "2000"],
            "debit_amount": [1e6, 0.0],
            "credit_amount": [0.0, 1e6],
        })
        assert not b11_expense_capitalization(df).any()

    def test_asset_debit_only_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "1010"],
            "debit_amount": [5e6, 0.0],
            "credit_amount": [0.0, 5e6],
        })
        assert not b11_expense_capitalization(df).any()

    def test_expense_credit_only_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["6100", "1010"],
            "debit_amount": [0.0, 5e6],
            "credit_amount": [5e6, 0.0],
        })
        assert not b11_expense_capitalization(df).any()

    def test_large_amount_gap_not_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 3_000_000.0],
        })
        assert not b11_expense_capitalization(df).any()

    def test_split_expense_lines_flagged_by_subtotal_match(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D001"],
            "gl_account": ["1500", "6100", "6300"],
            "debit_amount": [5_000_000.0, 0.0, 0.0],
            "credit_amount": [0.0, 2_000_000.0, 3_000_000.0],
        })
        result = b11_expense_capitalization(df)
        assert result.all()

    def test_custom_account_prefix_config_used(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1600", "9100"],
            "debit_amount": [1_500_000.0, 0.0],
            "credit_amount": [0.0, 1_500_000.0],
        })
        audit_rules = {
            "patterns": {
                "expense_capitalization": {
                    "asset_account_prefixes": ["16"],
                    "expense_account_prefixes": ["9"],
                }
            }
        }
        result = b11_expense_capitalization(df, audit_rules=audit_rules)
        assert result.all()

    def test_normal_capex_context_suppresses_flag(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 5_000_000.0],
            "document_type": ["AA", "AA"],
            "line_text": ["software development project", "software development project"],
            "header_text": ["capital project", "capital project"],
        })
        assert not b11_expense_capitalization(df).any()

    def test_manual_expense_context_elevates_to_immediate(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 5_000_000.0],
            "source": ["manual", "manual"],
            "business_process": ["P2P", "P2P"],
            "line_text": ["office repair expense", "office repair expense"],
        })
        result = b11_expense_capitalization(df)
        assert result.all()
        assert result.attrs["row_annotations"][0]["confidence_band"] == "high"
        assert result.attrs["row_annotations"][0]["queue_label"] == "immediate"
        assert result.attrs["breakdown"]["immediate_rows"] == 2

    def test_missing_column_skip(self) -> None:
        df = pd.DataFrame({
            "gl_account": ["1500"],
            "debit_amount": [1e6],
            "credit_amount": [0.0],
        })
        assert not b11_expense_capitalization(df).any()
