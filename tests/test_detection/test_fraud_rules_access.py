"""B06, B07, B09, B10 접근통제 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_circular_intercompany,
)

# ── B06 자기 승인 ─────────────────────────────────────────


class TestB06:
    def test_same_creator_approver_flagged(self) -> None:
        """created_by == approved_by → flagged."""
        df = pd.DataFrame({
            "created_by": ["User1", "User2", "User1"],
            "approved_by": ["User1", "User3", "User1"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert not result[1]
        assert result[2]

    def test_fallback_manual_source(self) -> None:
        """approved_by 없음, source='manual' + created_by 존재 → flagged."""
        df = pd.DataFrame({
            "created_by": ["User1", "User2"],
            "source": ["Manual", "automated"],
        })
        result = b06_self_approval(df)
        assert result[0]
        assert not result[1]

    def test_no_created_by_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b06_self_approval(df).any()

    def test_null_created_by_not_flagged(self) -> None:
        """created_by가 NaN이면 자기승인 판정 불가 → not flagged."""
        df = pd.DataFrame({
            "created_by": [None, "User1"],
            "approved_by": [None, "User1"],
        })
        result = b06_self_approval(df)
        assert not result[0]
        assert result[1]


# ── B07 직무분리 위반 ─────────────────────────────────────


class TestB07:
    def test_violator_flagged(self) -> None:
        """1인이 3개 프로세스 → 해당 사용자의 모든 행 flagged."""
        df = pd.DataFrame({
            "created_by": ["A", "A", "A", "B"],
            "business_process": ["입력", "승인", "이체", "입력"],
        })
        result = b07_segregation_of_duties(df, sod_threshold=3)
        assert result[0]   # A: 3프로세스
        assert result[1]
        assert result[2]
        assert not result[3]  # B: 1프로세스

    def test_below_threshold_not_flagged(self) -> None:
        """2개 프로세스 (threshold=3) → not flagged."""
        df = pd.DataFrame({
            "created_by": ["A", "A"],
            "business_process": ["입력", "승인"],
        })
        result = b07_segregation_of_duties(df, sod_threshold=3)
        assert not result.any()

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"created_by": ["A"]})
        assert not b07_segregation_of_duties(df).any()


# ── B09 승인 생략 ─────────────────────────────────────────


class TestB09:
    def test_exceeds_non_automated_flagged(self) -> None:
        df = pd.DataFrame({
            "exceeds_threshold": [True, True, False],
            "source": ["Manual", "automated", "Manual"],
        })
        result = b09_skipped_approval(df)
        assert result[0]   # exceeds + manual
        assert not result[1]  # exceeds + automated
        assert not result[2]  # not exceeds

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b09_skipped_approval(df).any()


# ── B10 관계사 순환거래 ───────────────────────────────────


class TestB10:
    def test_intercompany_flagged(self) -> None:
        """관계사 전표 + 복수 회사 → flagged."""
        df = pd.DataFrame({
            "is_intercompany": [True, True, False],
            "company_code": ["A", "B", "A"],
        })
        result = b10_circular_intercompany(df)
        assert result[0]
        assert result[1]
        assert not result[2]

    def test_single_company_still_flagged(self) -> None:
        """단일 회사 관계사 전표 → 의심 flag."""
        df = pd.DataFrame({
            "is_intercompany": [True, False],
            "company_code": ["A", "A"],
        })
        result = b10_circular_intercompany(df)
        assert result[0]
        assert not result[1]

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        assert not b10_circular_intercompany(df).any()
