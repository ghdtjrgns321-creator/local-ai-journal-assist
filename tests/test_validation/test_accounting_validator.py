"""accounting_validator L2 회계 검증 테스트.

검증 대상:
- check_balance: 대차일치 (document_id별 + 전체)
- check_date_continuity: 영업일 연속성
- check_duplicates: 완전 중복 행 (피처 컬럼 제외)
- validate_accounting: 오케스트레이터 통합
"""

import pandas as pd
import pytest

from src.validation.accounting_validator import (
    check_balance,
    check_date_continuity,
    check_duplicates,
    validate_accounting,
)
from src.validation.models import AccountingResult


# ── check_balance ─────────────────────────────────────────────


class TestCheckBalance:
    """대차일치 검증 테스트."""

    def test_balanced_all(self, av_balanced_df: pd.DataFrame) -> None:
        """모든 document 대차일치 → True."""
        ok, diff, docs = check_balance(av_balanced_df)
        assert ok is True
        assert diff < 0.01
        assert docs == []

    def test_unbalanced_one_doc(self, av_unbalanced_df: pd.DataFrame) -> None:
        """D002 불일치(100원) → False, D002 포함."""
        ok, diff, docs = check_balance(av_unbalanced_df)
        assert ok is False
        assert "D002" in docs
        assert "D001" not in docs

    def test_within_tolerance(self) -> None:
        """허용오차 내 차이(0.005) → True."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "debit_amount": [100.005, 0.0],
            "credit_amount": [0.0, 100.0],
        })
        ok, diff, docs = check_balance(df, tolerance=0.01)
        assert ok is True
        assert docs == []

    def test_exceeds_tolerance(self) -> None:
        """허용오차 초과(0.02) → False."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "debit_amount": [100.02, 0.0],
            "credit_amount": [0.0, 100.0],
        })
        ok, diff, docs = check_balance(df, tolerance=0.01)
        assert ok is False
        assert "D001" in docs

    def test_nan_amounts(self, av_nan_amounts_df: pd.DataFrame) -> None:
        """NaN → fillna(0.0) 처리, 합산 정상 동작."""
        ok, diff, docs = check_balance(av_nan_amounts_df)
        # D001: debit=100000+0+0=100000, credit=0+50000+0=50000 → 차이 50000
        assert ok is False
        assert abs(diff - 50_000.0) < 0.01
        assert docs == ["D001"]

    def test_no_document_id(self) -> None:
        """document_id 컬럼 없음 → 전체 합계만 검증."""
        df = pd.DataFrame({
            "debit_amount": [100.0, 200.0],
            "credit_amount": [100.0, 200.0],
        })
        ok, diff, docs = check_balance(df)
        assert ok is True
        assert docs == []  # document_id 없으면 빈 리스트

    def test_empty_df(self, av_empty_df: pd.DataFrame) -> None:
        """0행 → True, 0.0, []."""
        ok, diff, docs = check_balance(av_empty_df)
        assert ok is True
        assert diff == 0.0
        assert docs == []


# ── check_date_continuity ────────────────────────────────────


class TestCheckDateContinuity:
    """영업일 연속성 검증 테스트."""

    def test_continuous(self, av_continuous_df: pd.DataFrame) -> None:
        """월~금 연속 → True, missing=[]."""
        ok, missing = check_date_continuity(av_continuous_df)
        assert ok is True
        assert missing == []

    def test_gap_one_day(self, av_gap_df: pd.DataFrame) -> None:
        """수요일(2025-01-08) 누락 → False."""
        ok, missing = check_date_continuity(av_gap_df)
        assert ok is False
        assert "2025-01-08" in missing

    def test_all_nat(self) -> None:
        """posting_date 전부 NaT → True (검증 불가)."""
        df = pd.DataFrame({
            "posting_date": pd.Series([pd.NaT, pd.NaT, pd.NaT]),
        })
        ok, missing = check_date_continuity(df)
        assert ok is True
        assert missing == []

    def test_single_date(self, av_single_date_df: pd.DataFrame) -> None:
        """모든 행 동일 날짜 → True (범위 1일, 누락 없음)."""
        ok, missing = check_date_continuity(av_single_date_df)
        assert ok is True
        assert missing == []

    def test_no_posting_date_column(self) -> None:
        """posting_date 컬럼 없음 → True (건너뜀)."""
        df = pd.DataFrame({"document_id": ["D001"]})
        ok, missing = check_date_continuity(df)
        assert ok is True
        assert missing == []


# ── check_duplicates ─────────────────────────────────────────


class TestCheckDuplicates:
    """완전 중복 행 탐지 테스트."""

    def test_no_duplicates(self, av_balanced_df: pd.DataFrame) -> None:
        """중복 없음 → 0."""
        assert check_duplicates(av_balanced_df) == 0

    def test_two_pairs(self, av_duplicate_df: pd.DataFrame) -> None:
        """동일 행 2쌍 → 중복 2건."""
        assert check_duplicates(av_duplicate_df) == 2

    def test_feature_columns_excluded(
        self, av_with_features_df: pd.DataFrame
    ) -> None:
        """피처 컬럼(is_weekend, amount_zscore) 제외 → 원본 기준 중복 1건."""
        assert check_duplicates(av_with_features_df) == 1

    def test_empty_df(self, av_empty_df: pd.DataFrame) -> None:
        """0행 → 0."""
        assert check_duplicates(av_empty_df) == 0


# ── validate_accounting (오케스트레이터) ─────────────────────


class TestValidateAccounting:
    """L2 검증 오케스트레이터 통합 테스트."""

    def test_all_pass(self, av_balanced_df: pd.DataFrame) -> None:
        """정상 데이터 → 모든 필드 통과."""
        result = validate_accounting(av_balanced_df)
        assert isinstance(result, AccountingResult)
        assert result.balance_check is True
        assert result.balance_diff < 0.01
        assert result.unbalanced_docs == []
        assert result.duplicate_entries == 0

    def test_combined_issues(self) -> None:
        """불일치 + 중복 복합 케이스."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D001", "D001"],
            "posting_date": pd.to_datetime(["2025-01-06"] * 4),
            "debit_amount": [100_000.0, 0.0, 100_000.0, 0.0],
            "credit_amount": [0.0, 90_000.0, 0.0, 90_000.0],
            "gl_account": pd.array([1110, 2110, 1110, 2110], dtype="Int64"),
            "document_type": ["SA", "SA", "SA", "SA"],
            "company_code": ["1000"] * 4,
            "fiscal_year": pd.array([2025] * 4, dtype="Int64"),
            "document_date": pd.to_datetime(["2025-01-06"] * 4),
        })
        result = validate_accounting(df)
        assert result.balance_check is False
        assert result.duplicate_entries == 2

    def test_return_types(self, av_balanced_df: pd.DataFrame) -> None:
        """반환 타입이 Python 네이티브인지 확인 (JSON 직렬화 보장)."""
        result = validate_accounting(av_balanced_df)
        assert isinstance(result.balance_check, bool)
        assert isinstance(result.balance_diff, float)
        assert isinstance(result.unbalanced_docs, list)
        assert isinstance(result.date_continuity, bool)
        assert isinstance(result.missing_dates, list)
        assert isinstance(result.duplicate_entries, int)

    def test_graceful_degradation(self, av_minimal_df: pd.DataFrame) -> None:
        """금액 컬럼 없음 → crash 대신 기본값 반환."""
        result = validate_accounting(av_minimal_df)
        assert result.balance_check is True
        assert result.balance_diff == 0.0
        assert result.unbalanced_docs == []
