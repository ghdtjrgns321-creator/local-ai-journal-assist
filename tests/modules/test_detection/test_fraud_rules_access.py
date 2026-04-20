"""L1-05, L1-06, L1-07, L3-03 접근통제 룰 단위 테스트."""

from __future__ import annotations

import pandas as pd

from src.detection.fraud_rules_access import (
    b06_self_approval,
    b07_segregation_of_duties,
    b09_skipped_approval,
    b10_circular_intercompany,
)

# ── L1-05 자기 승인 ─────────────────────────────────────────


class TestL1-05:
    def test_human_high_amount_flagged(self) -> None:
        """TP: 일반 사용자 + 1천만 초과 + 자기 승인 → flagged."""
        df = pd.DataFrame({
            "created_by": ["USR-JA-001"],
            "approved_by": ["USR-JA-001"],
            "user_persona": ["junior_accountant"],
            "debit_amount": [50_000_000.0],  # 5천만
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df, min_amount=10_000_000)
        assert result[0]

    def test_automated_system_excluded(self) -> None:
        """TN: automated_system 자기승인 → not flagged."""
        df = pd.DataFrame({
            "created_by": ["SYSTEM"],
            "approved_by": ["SYSTEM"],
            "user_persona": ["automated_system"],
            "debit_amount": [100_000_000.0],  # 1억 (고액이어도 제외)
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df, min_amount=10_000_000)
        assert not result[0]

    def test_small_amount_excluded(self) -> None:
        """TN: 일반 사용자 + 1천만 이하 정상 전결 → not flagged."""
        df = pd.DataFrame({
            "created_by": ["USR-JA-002"],
            "approved_by": ["USR-JA-002"],
            "user_persona": ["junior_accountant"],
            "debit_amount": [5_000_000.0],  # 5백만
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df, min_amount=10_000_000)
        assert not result[0]

    def test_credit_only_amount_evaluated(self) -> None:
        """대변 전용 전표: max(debit, credit)로 금액 평가."""
        df = pd.DataFrame({
            "created_by": ["USR-SA-001"],
            "approved_by": ["USR-SA-001"],
            "user_persona": ["senior_accountant"],
            "debit_amount": [0.0],
            "credit_amount": [50_000_000.0],  # 대변 5천만
        })
        result = b06_self_approval(df, min_amount=10_000_000)
        assert result[0]

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

    def test_null_persona_still_evaluated(self) -> None:
        """user_persona NULL → automated 제외 안 됨 → 평가 대상."""
        df = pd.DataFrame({
            "created_by": ["User1"],
            "approved_by": ["User1"],
            "user_persona": [None],
            "debit_amount": [50_000_000.0],
            "credit_amount": [0.0],
        })
        result = b06_self_approval(df, min_amount=10_000_000)
        assert result[0]


# ── L1-06 직무분리 위반 ─────────────────────────────────────


class TestL1-06:
    """L1-06 하이브리드 SoD: Toxic Pair + In-Process + Role-based."""

    def test_toxic_pair_flagged(self) -> None:
        """TRE+P2P 겸직 → 직급 불문 즉시 flagged."""
        df = pd.DataFrame({
            "created_by": ["A", "A", "B"],
            "business_process": ["TRE", "P2P", "R2R"],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]       # A: TRE+P2P toxic pair
        assert result[1]
        assert not result[2]   # B: R2R 단독

    def test_in_process_conflict_flagged(self) -> None:
        """sod_conflict_type이 있는 행 → flagged."""
        df = pd.DataFrame({
            "created_by": ["A", "A"],
            "business_process": ["R2R", "R2R"],
            "sod_conflict_type": ["preparer_approver", None],
        })
        result = b07_segregation_of_duties(df)
        assert result[0]       # 자기승인 충돌
        assert not result[1]   # 충돌 없음

    def test_junior_exceeds_role_threshold(self) -> None:
        """junior가 2개 프로세스 → flagged (허용 1개)."""
        df = pd.DataFrame({
            "created_by": ["J1", "J1"],
            "business_process": ["P2P", "O2C"],
            "user_persona": ["junior_accountant", "junior_accountant"],
        })
        result = b07_segregation_of_duties(df)
        assert result.all()

    def test_controller_multi_process_pass(self) -> None:
        """controller가 4개 프로세스 → toxic pair 아니면 통과."""
        df = pd.DataFrame({
            "created_by": ["C1"] * 4,
            "business_process": ["R2R", "A2R", "P2P", "H2R"],
            "user_persona": ["controller"] * 4,
        })
        result = b07_segregation_of_duties(df)
        # H2R+P2P는 toxic pair → flagged
        assert result.all()

    def test_controller_safe_processes_pass(self) -> None:
        """controller가 R2R+A2R+TRE → toxic pair 아님 → 통과."""
        df = pd.DataFrame({
            "created_by": ["C1"] * 3,
            "business_process": ["R2R", "A2R", "TRE"],
            "user_persona": ["controller"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_fallback_without_persona(self) -> None:
        """user_persona 없으면 기존 threshold fallback."""
        df = pd.DataFrame({
            "created_by": ["A", "A", "A", "B"],
            "business_process": ["P2P", "O2C", "R2R", "R2R"],
        })
        result = b07_segregation_of_duties(df, sod_threshold=3)
        # A: 3프로세스 + O2C+P2P toxic pair → flagged
        assert result[0]
        assert not result[3]   # B: 1프로세스

    def test_automated_system_excluded(self) -> None:
        """automated_system은 SoD 판정 대상에서 제외."""
        df = pd.DataFrame({
            "created_by": ["SYS1", "SYS1", "SYS1"],
            "business_process": ["TRE", "P2P", "O2C"],
            "user_persona": ["automated_system"] * 3,
        })
        result = b07_segregation_of_duties(df)
        assert not result.any()

    def test_missing_columns_skip(self) -> None:
        df = pd.DataFrame({"created_by": ["A"]})
        assert not b07_segregation_of_duties(df).any()


# ── L1-07 승인 생략 ─────────────────────────────────────────


class TestL1-07:
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


# ── L3-03 관계사 순환거래 ───────────────────────────────────


class TestL3-03:
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
