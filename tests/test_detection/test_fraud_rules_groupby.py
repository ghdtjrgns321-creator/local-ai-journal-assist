"""B04, B05, B11 groupby 기반 룰 단위 테스트."""

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
    """B04 테스트: P2P 프로세스, 동일 거래처+금액, reference 있음/없음."""
    return pd.DataFrame({
        "auxiliary_account_number": ["V001", "V001", "V001", "V002"],
        "debit_amount": [1e6, 1e6, 1e6, 2e6],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-01-01",
            "2025-01-10",  # 9일 후
            "2025-03-01",  # 50일 후
            "2025-01-05",
        ]),
        "business_process": ["P2P", "P2P", "P2P", "P2P"],
        # reference NULL → fallback 경로
    })


@pytest.fixture
def dup_entry_df() -> pd.DataFrame:
    """B05 테스트: 동일 GL+금액+날짜 exact match."""
    return pd.DataFrame({
        "gl_account": [1000, 1000, 1000, 2000],
        "debit_amount": [500.0, 500.0, 500.0, 500.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-01-01",  # 중복 1
            "2025-01-01",  # 중복 2
            "2025-01-02",  # 날짜 다름 → 비중복
            "2025-01-01",  # GL 다름 → 비중복
        ]),
    })


# ── B04 중복 지급 ─────────────────────────────────────────


class TestB04:
    def test_within_window_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        """30일 내 동일 거래처+금액 → 양쪽 모두 flagged."""
        result = b04_duplicate_payment(dup_payment_df, window_days=30)
        assert result[0]   # 첫 번째 (backward diff로 포착)
        assert result[1]   # 두 번째 (forward diff로 포착)

    def test_outside_window_not_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        """30일 초과 간격 → not flagged."""
        result = b04_duplicate_payment(dup_payment_df, window_days=30)
        assert not result[2]  # 45일 간격

    def test_different_vendor_not_flagged(self, dup_payment_df: pd.DataFrame) -> None:
        """다른 거래처 → not flagged."""
        result = b04_duplicate_payment(dup_payment_df, window_days=30)
        assert not result[3]  # V002 단독

    def test_missing_column_skip(self) -> None:
        """auxiliary_account_number 미존재 → 모두 False."""
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-01-01"]),
        })
        assert not b04_duplicate_payment(df).any()

    def test_triple_duplicate_all_flagged(self) -> None:
        """3건 중복 (P2P, NULL reference) → 3건 모두 flagged."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["V001"] * 3,
            "debit_amount": [1e6] * 3,
            "credit_amount": [0.0] * 3,
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-20"]),
            "business_process": ["P2P"] * 3,
        })
        result = b04_duplicate_payment(df, window_days=30)
        assert result.all()

    def test_exactly_window_boundary_flagged(self) -> None:
        """정확히 30일 간격 → flagged (<= 이므로 경계 포함)."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-31"]),
            "business_process": ["P2P", "P2P"],
        })
        result = b04_duplicate_payment(df, window_days=30)
        assert result.all()

    def test_o2c_excluded(self) -> None:
        """O2C 반복 매출은 B04 대상 아님."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["C001", "C001"],
            "debit_amount": [1e6, 1e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-05"]),
            "business_process": ["O2C", "O2C"],
        })
        assert not b04_duplicate_payment(df).any()

    def test_same_reference_different_doc_flagged(self) -> None:
        """같은 reference + 다른 document_id → 이중 지급 의심."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [5e6, 5e6],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-15"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "document_id": ["D001", "D002"],
        })
        result = b04_duplicate_payment(df)
        assert result.all()

    def test_same_reference_same_doc_not_flagged(self) -> None:
        """같은 reference + 같은 document_id → 같은 전표의 라인 (정상)."""
        df = pd.DataFrame({
            "auxiliary_account_number": ["V001", "V001"],
            "debit_amount": [5e6, 0.0],
            "credit_amount": [0.0, 5e6],
            "posting_date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "business_process": ["P2P", "P2P"],
            "reference": ["INV-2025-001", "INV-2025-001"],
            "document_id": ["D001", "D001"],
        })
        assert not b04_duplicate_payment(df).any()


# ── B05 중복 전표 ─────────────────────────────────────────


class TestB05:
    def test_exact_match_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        """GL+금액+날짜 동일 → 양쪽 flagged."""
        result = b05_duplicate_entry(dup_entry_df)
        assert result[0]
        assert result[1]

    def test_different_date_not_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        """날짜만 다름 → not flagged."""
        result = b05_duplicate_entry(dup_entry_df)
        assert not result[2]

    def test_different_gl_not_flagged(self, dup_entry_df: pd.DataFrame) -> None:
        """GL 다름 → not flagged."""
        result = b05_duplicate_entry(dup_entry_df)
        assert not result[3]

    def test_missing_column_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not b05_duplicate_entry(df).any()


# ── B11 비용 자산화 ──────────────────────────────────────────


class TestB11:
    def test_expense_to_asset_flagged(self) -> None:
        """동일 전표 내 차변=자산(15xx) + 대변=비용(6xxx) → 전표 전체 flagged."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "gl_account": ["1500", "6100", "1010", "2000"],
            "debit_amount": [5e6, 0.0, 1e6, 0.0],
            "credit_amount": [0.0, 5e6, 0.0, 1e6],
        })
        result = b11_expense_capitalization(df)
        # D001: 차변 1500(자산) + 대변 6100(비용) → flagged
        assert result[0]
        assert result[1]
        # D002: 1010(은행) + 2000(매입채무) → not flagged
        assert not result[2]
        assert not result[3]

    def test_no_match_not_flagged(self) -> None:
        """자산↔비용 조합 없음 → 전체 False."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1010", "2000"],
            "debit_amount": [1e6, 0.0],
            "credit_amount": [0.0, 1e6],
        })
        assert not b11_expense_capitalization(df).any()

    def test_asset_debit_only_not_flagged(self) -> None:
        """차변 자산만 있고 대변 비용 없음 → not flagged."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1500", "1010"],
            "debit_amount": [5e6, 0.0],
            "credit_amount": [0.0, 5e6],
        })
        assert not b11_expense_capitalization(df).any()

    def test_expense_credit_only_not_flagged(self) -> None:
        """대변 비용만 있고 차변 자산 없음 → not flagged."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["6100", "1010"],
            "debit_amount": [0.0, 5e6],
            "credit_amount": [5e6, 0.0],
        })
        assert not b11_expense_capitalization(df).any()

    def test_missing_column_skip(self) -> None:
        """document_id 미존재 → 전체 False."""
        df = pd.DataFrame({
            "gl_account": ["1500"],
            "debit_amount": [1e6],
            "credit_amount": [0.0],
        })
        assert not b11_expense_capitalization(df).any()

    def test_multiple_docs_partial_flag(self) -> None:
        """여러 전표 중 일부만 해당 → 해당 전표만 flagged."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002", "D003", "D003"],
            "gl_account": ["1500", "6200", "4000", "1100", "1510", "6000"],
            "debit_amount": [10e6, 0.0, 0.0, 5e6, 3e6, 0.0],
            "credit_amount": [0.0, 10e6, 5e6, 0.0, 0.0, 3e6],
        })
        result = b11_expense_capitalization(df)
        # D001: 1500(자산)+6200(비용) → flagged
        assert result[0]
        assert result[1]
        # D002: 4000(매출)+1100(채권) → not
        assert not result[2]
        assert not result[3]
        # D003: 1510(자산)+6000(비용) → flagged
        assert result[4]
        assert result[5]
