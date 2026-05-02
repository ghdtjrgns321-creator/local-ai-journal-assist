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
        assert result.attrs["score_series"].tolist() == [0.0, 0.9]
        assert result.attrs["breakdown"]["reference_match_docs"] == 1
        assert result.attrs["row_annotations"][1]["reason_code"] == "reference_match"
        assert result.attrs["row_annotations"][1]["matched_document_id"] == "D001"

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

    def test_reference_revision_suffix_normalization_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [2_950_000, 2_950_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-10", "2025-01-16"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PO-C001-2025-001184", "PO-C001-2025-001184-R"],
        })

        result = b04_duplicate_payment(df, reference_amount_tolerance=0.01)

        assert not result[0]
        assert result[1]
        assert result.attrs["breakdown"]["reference_match_docs"] == 1
        assert result.attrs["row_annotations"][1]["reason_code"] == "reference_match"

    def test_payment_reference_zero_padding_normalization_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [2_950_000, 2_950_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-10", "2025-01-16"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C002-0000000009", "PAY-C002-000000009"],
        })

        result = b04_duplicate_payment(df, reference_amount_tolerance=0.01)

        assert not result[0]
        assert result[1]
        assert result.attrs["breakdown"]["reference_match_docs"] == 1

    def test_payment_reference_typo_normalization_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [2_950_000, 2_950_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-10", "2025-01-16"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY-C002-0000000047", "PAY-C00z-0000000047"],
        })

        result = b04_duplicate_payment(df, reference_amount_tolerance=0.01)

        assert not result[0]
        assert result[1]
        assert result.attrs["breakdown"]["reference_match_docs"] == 1

    def test_reference_mismatch_same_partner_amount_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KR", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [760_014, 760_014],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-27"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["VI:VI-C002-0000000044", "PAY:PAY-C002-0000000047"],
        })

        result = b04_duplicate_payment(df, window_days=45)

        assert not result[0]
        assert result[1]
        assert result.attrs["breakdown"]["amount_partner_fallback_docs"] == 1
        assert result.attrs["row_annotations"][1]["reason_code"] == "amount_partner_fallback"

    def test_document_amount_uses_debit_credit_totals(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "document_type": ["KR", "KR", "KR", "KR"],
            "auxiliary_account_number": ["V001", "V001", "V001", "V001"],
            "debit_amount": [18_984, 51_016, 70_000, 0.0],
            "credit_amount": [0.0, 70_000, 0.0, 70_000],
            "posting_date": pd.to_datetime([
                "2025-05-03",
                "2025-05-03",
                "2025-06-05",
                "2025-06-05",
            ]),
            "business_process": ["P2P", "P2P", "P2P", "P2P"],
            "reference": [
                "PO-C002-2025-001493",
                "PO-C002-2025-001493",
                "PO-C002-2025-000260",
                "PO-C002-2025-000260",
            ],
        })

        result = b04_duplicate_payment(df, window_days=45)

        assert not result.iloc[:2].any()
        assert result.iloc[2:].all()
        assert result.attrs["breakdown"]["amount_partner_fallback_docs"] == 1

    def test_same_reference_near_amount_flagged_by_default(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [2_334_000, 2_366_676],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-11", "2025-01-21"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C001-2025-005", "PAY:PAY-C001-2025-005"],
        })
        result = b04_duplicate_payment(df)
        assert not result[0]
        assert result[1]

    def test_same_reference_near_amount_cap_prevents_large_gap(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [1_000_000_000, 1_010_000_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-11", "2025-01-21"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C001-2025-005", "PAY:PAY-C001-2025-005"],
        })
        assert not b04_duplicate_payment(df).any()

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
        assert result.attrs["score_series"].tolist() == [0.0, 0.7]
        assert result.attrs["breakdown"]["mixed_reference_fallback_docs"] == 1
        assert result.attrs["row_annotations"][1]["reason_code"] == "mixed_reference_fallback"

    def test_blank_reference_uses_line_text_reference(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [636_680, 636_680],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-05", "2025-01-09"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["PAY:PAY-C003-0000000004", ""],
            "line_text": ["original payment", "duplicate PAY-x003-0000000004"],
        })

        result = b04_duplicate_payment(df, window_days=45)

        assert not result[0]
        assert result[1]
        assert result.attrs["breakdown"]["reference_match_docs"] == 1

    def test_blank_reference_fallback_exposes_weaker_score(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["KZ", "KZ"],
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [1_000_000, 1_000_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-05", "2025-01-09"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["", ""],
        })
        result = b04_duplicate_payment(df, window_days=45)
        assert not result[0]
        assert result[1]
        assert result.attrs["score_series"].tolist() == [0.0, 0.6]
        assert result.attrs["breakdown"]["blank_reference_fallback_docs"] == 1
        assert result.attrs["row_annotations"][1]["confidence_band"] == "medium"

    def test_kr_p2p_documents_included(self) -> None:
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
        result = b04_duplicate_payment(df)
        assert not result[0]
        assert result[1]

    def test_non_payment_documents_excluded(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["SA", "SA"],
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

    def test_recurring_exact_duplicate_stays_flagged_with_zero_score(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "document_type": ["HR", "HR"],
            "business_process": ["H2R", "H2R"],
            "source": ["recurring", "recurring"],
            "gl_account": [6200, 6200],
            "debit_amount": [1_000_000.0, 1_000_000.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-15", "2025-01-15"]),
        })

        result = b05_duplicate_entry(df)

        assert result.all()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["breakdown"]["zero_score_rows"] == 2
        assert result.attrs["row_annotations"][0]["raw_confidence"] == pytest.approx(0.95)
        assert result.attrs["row_annotations"][0]["queue_label"] == "normal_duplicate_population"

    def test_ic_r2r_automated_split_duplicate_stays_zero_score(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "company_code": ["C001", "C001", "C001"],
            "document_type": ["IC", "IC", "IC"],
            "business_process": ["R2R", "R2R", "R2R"],
            "source": ["automated", "automated", "automated"],
            "auxiliary_account_number": ["IC-C002", "IC-C002", "IC-C002"],
            "gl_account": [115001, 115001, 115001],
            "debit_amount": [100_000.0, 60_000.0, 40_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-07-19", "2025-07-20", "2025-07-21"]),
        })

        result = b05_duplicate_entry(df, split_window_days=3)

        assert result.all()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0]
        assert result.attrs["breakdown"]["zero_score_rows"] == 3
        assert result.attrs["row_annotations"][0]["reason_code"] == "split_duplicate"
        assert result.attrs["row_annotations"][0]["queue_label"] == "normal_duplicate_population"

    def test_annotations_preserve_non_integer_index(self, dup_entry_df: pd.DataFrame) -> None:
        df = dup_entry_df.iloc[:2].copy()
        df.index = ["row-a", "row-b"]

        result = b05_duplicate_entry(df)

        assert result["row-a"]
        assert result.attrs["row_annotations"]["row-a"]["confidence"] >= 0.9

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
        assert result.attrs["row_annotations"][0]["reason_code"] == "document_duplicate"
        assert "reference_duplicate" in result.attrs["row_annotations"][0]["matched_reason_codes"]
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
        assert "near_duplicate" in result.attrs["row_annotations"][0]["matched_reason_codes"]
        assert result.attrs["row_annotations"][0]["confidence_band"] in {"medium", "low"}

    def test_document_reference_variant_flagged(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "document_type": ["SA", "SA", "SA", "SA"],
            "business_process": ["R2R", "R2R", "R2R", "R2R"],
            "company_code": ["C003", "C003", "C003", "C003"],
            "reference": [
                "DOC-C003-2022-001188",
                "DOC-C003-2022-001188",
                "DOC / C003-2022-001188",
                "DOC / C003-2022-001188",
            ],
            "line_text": ["원가 배부 - Q1 2022", "원가 배부 - Q1 2022"] * 2,
            "gl_account": [500230, 200240, 500230, 200240],
            "debit_amount": [9_774_584.0, 0.0, 9_774_584.0, 0.0],
            "credit_amount": [0.0, 9_774_584.0, 0.0, 9_774_584.0],
            "posting_date": pd.to_datetime([
                "2022-01-01",
                "2022-01-01",
                "2022-01-03",
                "2022-01-03",
            ]),
        })
        result = b05_duplicate_entry(df)
        assert result.all()
        assert result.attrs["row_annotations"][2]["reason_code"] == "document_duplicate"

    def test_document_line_text_variant_flagged_beyond_row_window(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "document_type": ["SA", "SA", "SA", "SA"],
            "business_process": ["R2R", "R2R", "R2R", "R2R"],
            "company_code": ["C003", "C003", "C003", "C003"],
            "reference": ["DOC-C003-2022-001068"] * 4,
            "line_text": [
                "이자수익 계상",
                "판관비 재분류",
                "이자수익 계상 - 재전기",
                "판관비 재분류 - 재전기",
            ],
            "gl_account": [7100, 6300, 7100, 6300],
            "debit_amount": [71_339.0, 0.0, 71_339.0, 0.0],
            "credit_amount": [0.0, 71_339.0, 0.0, 71_339.0],
            "posting_date": pd.to_datetime([
                "2022-01-01",
                "2022-01-01",
                "2022-01-12",
                "2022-01-12",
            ]),
        })
        result = b05_duplicate_entry(df, window_days=7)
        assert result.all()
        assert result.attrs["row_annotations"][2]["reason_code"] == "document_duplicate"

    def test_document_duplicate_accepts_string_posting_dates(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D010", "D010", "D011", "D011"],
            "document_type": ["SA", "SA", "SA", "SA"],
            "business_process": ["R2R", "R2R", "R2R", "R2R"],
            "company_code": ["C003", "C003", "C003", "C003"],
            "reference": ["DOC-C003-2022-009999"] * 4,
            "line_text": ["interest accrual", "accrued revenue"] * 2,
            "gl_account": [7100, 2200, 7100, 2200],
            "debit_amount": [125_000.0, 0.0, 125_000.0, 0.0],
            "credit_amount": [0.0, 125_000.0, 0.0, 125_000.0],
            "posting_date": ["2022-01-01", "2022-01-01", "2022-01-11", "2022-01-11"],
        })
        result = b05_duplicate_entry(df, window_days=7)
        assert result.all()
        assert result.attrs["row_annotations"][2]["reason_code"] == "document_duplicate"

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

    def test_document_id_is_required(self) -> None:
        df = pd.DataFrame({
            "gl_account": [5100, 5100],
            "debit_amount": [1_000_000, 1_000_000],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
        })
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

    def test_current_asset_prefixes_are_included(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "gl_account": ["1200", "7200", "1290", "6200"],
            "debit_amount": [1_244_983_850.0, 0.0, 7_453_510.0, 0.0],
            "credit_amount": [0.0, 1_244_983_850.0, 0.0, 7_453_510.0],
            "line_text": [
                "선급비용 자산 계상",
                "유형자산 처분손실",
                "대여금 지급 단기자금 운용 계정 대체 입력",
                "세금과공과 차량유지비",
            ],
        })

        result = b11_expense_capitalization(df)

        assert result.all()
        assert result.attrs["row_annotations"][0]["reason_code"] == "line_amount_match"
        assert result.attrs["row_annotations"][2]["reason_code"] == "line_amount_match"

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

    def test_large_amount_gap_stays_flagged_with_zero_score(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 3_000_000.0],
        })
        result = b11_expense_capitalization(df)
        assert result.all()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["row_annotations"][0]["reason_code"] == "asset_expense_combo"
        assert result.attrs["row_annotations"][0]["queue_label"] == "population"

    def test_split_expense_lines_flagged_by_subtotal_match(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D001"],
            "gl_account": ["1500", "6100", "6300"],
            "debit_amount": [5_000_000.0, 0.0, 0.0],
            "credit_amount": [0.0, 2_000_000.0, 3_000_000.0],
        })
        result = b11_expense_capitalization(df)
        assert result.all()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0, 0.0]
        assert result.attrs["review_score_series"].tolist() == [0.35, 0.35, 0.35]
        assert result.attrs["row_annotations"][0]["review_score"] == pytest.approx(0.35)

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

    def test_normal_capex_context_stays_flagged_with_zero_score(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 5_000_000.0],
            "document_type": ["AA", "AA"],
            "line_text": ["software development project", "software development project"],
            "header_text": ["capital project", "capital project"],
        })
        result = b11_expense_capitalization(df)
        assert result.all()
        assert result.attrs["score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["breakdown"]["zero_score_docs"] == 1
        assert result.attrs["row_annotations"][0]["queue_label"] == "population"

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
        assert result.attrs["score_series"].tolist() == pytest.approx([0.85, 0.85])
        assert result.attrs["review_score_series"].tolist() == [0.0, 0.0]
        assert result.attrs["row_annotations"][0]["score"] == pytest.approx(0.85)
        assert result.attrs["breakdown"]["immediate_rows"] == 2
        assert result.attrs["breakdown"]["queue_counts"] == {
            "immediate": 2,
            "review": 0,
            "low_review": 0,
            "population": 0,
        }
        assert result.attrs["breakdown"]["confidence_band_counts"] == {
            "high": 2,
            "medium": 0,
            "low": 0,
            "population": 0,
        }
        assert result.attrs["breakdown"]["immediate_docs"] == 1
        assert result.attrs["breakdown"]["review_docs"] == 0
        assert result.attrs["breakdown"]["reason_doc_counts"] == {"line_amount_match": 1}
        assert result.attrs["breakdown"]["modifier_row_counts"] == {
            "suspicious_expense_keyword": 2,
            "manual_source": 2,
            "suspicious_process": 2,
        }

    def test_normal_context_zero_score_is_counted(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "6100"],
            "debit_amount": [5_000_000.0, 0.0],
            "credit_amount": [0.0, 5_000_000.0],
            "document_type": ["AA", "AA"],
            "line_text": ["software development project", "software development project"],
            "header_text": ["capital project", "capital project"],
        })
        result = b11_expense_capitalization(df)
        assert result.all()
        assert result.attrs["breakdown"]["normal_context_suppressed_docs"] == 1
        assert result.attrs["breakdown"]["zero_score_docs"] == 1
        assert result.attrs["breakdown"]["queue_counts"] == {
            "immediate": 0,
            "review": 0,
            "low_review": 0,
            "population": 2,
        }
        assert result.attrs["breakdown"]["confidence_band_counts"] == {
            "high": 0,
            "medium": 0,
            "low": 0,
            "population": 2,
        }

    def test_missing_column_skip(self) -> None:
        df = pd.DataFrame({
            "gl_account": ["1500"],
            "debit_amount": [1e6],
            "credit_amount": [0.0],
        })
        assert not b11_expense_capitalization(df).any()
