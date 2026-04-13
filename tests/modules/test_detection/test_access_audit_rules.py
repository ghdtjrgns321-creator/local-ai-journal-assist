"""Access Audit (WU-15) 룰 함수 + 오케스트레이터 단위 테스트.

AA01: 전표 수정이력 | AA02: IP(스켈레톤) | AA03: 전표번호 갭 | AA04: 승인 프로세스
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.access_audit_rules import (
    aa01_document_modification,
    aa02_abnormal_ip_access,
    aa03_document_number_gap,
    aa04_approval_process,
)
from src.detection.access_audit_layer import AccessAuditDetector


# ── Fixture ──────────────────────────────────────────────────


@pytest.fixture
def base_df() -> pd.DataFrame:
    """기본 GL DataFrame — 10행, 기말 2행 포함."""
    return pd.DataFrame({
        "document_id": [f"D{i:03d}" for i in range(10)],
        "created_by": ["user_A"] * 5 + ["user_B"] * 5,
        "debit_amount": [1e7, 2e8, 5e6, 3e9, 1e6, 1e8, 2e7, 4e6, 5e9, 7e6],
        "credit_amount": [0.0] * 10,
        "is_period_end": [False] * 8 + [True, True],
        "posting_date": pd.to_datetime(["2025-06-15"] * 8 + ["2025-12-30", "2025-12-31"]),
        "approved_by": ["mgr_A"] * 3 + [None, "mgr_A", "mgr_B", None, "mgr_B", None, "mgr_B"],
        "approval_date": pd.to_datetime(
            ["2025-06-15", "2025-06-16", "2025-06-15", None, "2025-06-20",
             "2025-06-15", None, "2025-06-15", None, "2025-12-31"]
        ),
        "approval_level": [1, 2, 1, 0, 1, 2, 0, 1, 0, 1],
        "user_persona": ["senior_accountant"] * 8 + ["junior_accountant"] * 2,
        "source": ["manual"] * 10,
        "company_code": ["C1"] * 10,
        "fiscal_year": [2025] * 10,
        "document_type": ["SA"] * 10,
    })


@pytest.fixture
def change_log_df() -> pd.DataFrame:
    """change_log 테스트 데이터 — D008(기말) 적요 수정, D001 빈번 수정."""
    return pd.DataFrame({
        "document_id": ["D008", "D008", "D001", "D001", "D001"],
        "changed_by": ["user_X", "user_X", "user_A", "user_B", "user_A"],
        "change_date": pd.to_datetime(
            ["2025-12-30", "2025-12-30", "2025-06-15", "2025-06-16", "2025-06-17"]
        ),
        "changed_field": ["line_text", "debit_amount", "header_text", "line_text", "cost_center"],
    })


# ── AA01: 전표 수정이력 ─────────────────────────────────────


class TestAA01DocumentModification:
    """AA01 전표 수정이력 이상 탐지."""

    def test_period_end_text_change(self, base_df, change_log_df):
        """기말 + 감시 대상 필드 수정 → 플래그."""
        result = aa01_document_modification(base_df, change_log_df)
        # D008 (idx=8): 기말 + line_text 변경 → S1 플래그
        assert result.iloc[8] > 0, "기말 적요 수정 미탐지"

    def test_unauthorized_change(self, base_df, change_log_df):
        """created_by ≠ changed_by + 고액 → 플래그."""
        result = aa01_document_modification(base_df, change_log_df)
        # D001 (idx=1): changed_by에 user_B 포함 ≠ created_by(user_A)
        # S2 또는 S3 둘 중 하나라도 발동해야 함
        assert result.iloc[1] > 0, "D001 무단 수정 또는 빈번 수정 미탐지"

    def test_frequent_changes(self, base_df, change_log_df):
        """change_log 3건 이상 → S3 플래그."""
        result = aa01_document_modification(base_df, change_log_df)
        # D001 (idx=1): change_log 3건 → S3 0.2
        assert result.iloc[1] > 0, "빈번 수정 미탐지"

    def test_no_change_log(self, base_df):
        """change_log_df=None → 전부 0.0."""
        result = aa01_document_modification(base_df, None)
        assert (result == 0.0).all()

    def test_unmatched_document(self, base_df):
        """change_log에 미매칭 document_id → not flagged."""
        unmatched = pd.DataFrame({
            "document_id": ["UNKNOWN"],
            "changed_by": ["x"],
            "change_date": pd.to_datetime(["2025-01-01"]),
            "changed_field": ["line_text"],
        })
        result = aa01_document_modification(base_df, unmatched)
        assert (result == 0.0).all()


# ── AA02: IP 비정상 접근 (스켈레톤) ─────────────────────────


class TestAA02AbnormalIp:

    def test_no_ip_column(self, base_df):
        """ip_address 없으면 Series(0.0)."""
        result = aa02_abnormal_ip_access(base_df)
        assert (result == 0.0).all()

    def test_empty_df(self):
        """빈 DF → Series(0.0)."""
        empty = pd.DataFrame(columns=["document_id"])
        result = aa02_abnormal_ip_access(empty)
        assert len(result) == 0


# ── AA03: 전표번호 연속성 갭 ─────────────────────────────────


class TestAA03DocumentNumberGap:

    def test_gap_detected(self):
        """번호 1,2,5,6 → gap=3 플래그."""
        df = pd.DataFrame({
            "document_number": ["1", "2", "5", "6"],
            "company_code": ["C1"] * 4,
            "fiscal_year": [2025] * 4,
            "document_type": ["SA"] * 4,
            "debit_amount": [100.0] * 4,
            "credit_amount": [0.0] * 4,
        })
        result = aa03_document_number_gap(df)
        assert result.sum() > 0, "갭 미탐지"
        # Why: 정렬 후 diff → 번호5(idx=2)에 gap=3 기록
        assert result.iloc[2] > 0

    def test_no_gap(self):
        """연속 1,2,3,4 → not flagged."""
        df = pd.DataFrame({
            "document_number": ["1", "2", "3", "4"],
            "company_code": ["C1"] * 4,
            "fiscal_year": [2025] * 4,
            "document_type": ["SA"] * 4,
        })
        result = aa03_document_number_gap(df)
        assert (result == 0.0).all()

    def test_exclude_cancelled(self):
        """ST(Storno) 유형 갭 → 제외."""
        df = pd.DataFrame({
            "document_number": ["1", "2", "5", "6"],
            "company_code": ["C1"] * 4,
            "fiscal_year": [2025] * 4,
            "document_type": ["ST", "ST", "ST", "ST"],
        })
        result = aa03_document_number_gap(df, exclude_doc_types=("ST",))
        assert (result == 0.0).all()

    def test_no_column(self, base_df):
        """document_number 없으면 Series(0.0)."""
        result = aa03_document_number_gap(base_df)
        assert (result == 0.0).all()

    def test_multi_partition(self):
        """회사코드별 독립 번호범위 검증."""
        df = pd.DataFrame({
            "document_number": ["1", "2", "1", "5"],
            "company_code": ["C1", "C1", "C2", "C2"],
            "fiscal_year": [2025] * 4,
            "document_type": ["SA"] * 4,
        })
        result = aa03_document_number_gap(df)
        # C1: 1,2 연속 → 0.0
        # C2: 1,5 갭 → 플래그
        assert result.iloc[2] > 0 or result.iloc[3] > 0, "파티션 내 갭 미탐지"

    def test_leading_zeros(self):
        """선행0 포함 번호 정상 처리."""
        df = pd.DataFrame({
            "document_number": ["001", "002", "005"],
            "company_code": ["C1"] * 3,
            "fiscal_year": [2025] * 3,
            "document_type": ["SA"] * 3,
        })
        result = aa03_document_number_gap(df)
        assert result.sum() > 0, "선행0 번호 갭 미탐지"

    def test_alphanumeric_number(self):
        """알파벳 혼합 번호에서 숫자 추출."""
        df = pd.DataFrame({
            "document_number": ["RV-001", "RV-002", "RV-010"],
            "company_code": ["C1"] * 3,
            "fiscal_year": [2025] * 3,
            "document_type": ["SA"] * 3,
        })
        result = aa03_document_number_gap(df)
        assert result.sum() > 0, "알파벳 혼합 번호 갭 미탐지"


# ── AA04: 승인 프로세스 검증 ──────────────────────────────────


class TestAA04ApprovalProcess:

    def test_missing_approval(self, base_df):
        """고액 + approved_by NULL → S1 플래그."""
        result = aa04_approval_process(base_df)
        # D003 (idx=3): 3B + approved_by=None → S1
        assert result.iloc[3] > 0, "승인 누락 미탐지"

    def test_delayed_approval(self, base_df):
        """승인 지연 > 3일 → S2 플래그."""
        result = aa04_approval_process(base_df, max_delay_days=3)
        # D004 (idx=4): posting 06-15, approval 06-20 → 5일 지연
        assert result.iloc[4] > 0, "승인 지연 미탐지"

    def test_level_skip(self):
        """1B 전표 + level=1 → 레벨 부족 (Level 3 필요)."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000_000.0],  # 1B → Level 3 필요
            "credit_amount": [0.0],
            "approved_by": ["mgr_A"],
            "approval_date": pd.to_datetime(["2025-06-15"]),
            "posting_date": pd.to_datetime(["2025-06-15"]),
            "approval_level": [1],  # Level 1 < Level 3
            "user_persona": ["senior_accountant"],
            "source": ["manual"],
        })
        result = aa04_approval_process(df)
        assert result.iloc[0] > 0, "레벨 건너뜀 미탐지"

    def test_normal_approval(self):
        """정상 승인 → not flagged."""
        df = pd.DataFrame({
            "debit_amount": [5_000_000.0],  # Level 1 이하 (자동승인 범위)
            "credit_amount": [0.0],
            "approved_by": ["mgr_A"],
            "approval_date": pd.to_datetime(["2025-06-15"]),
            "posting_date": pd.to_datetime(["2025-06-15"]),
            "approval_level": [1],
            "user_persona": ["senior_accountant"],
            "source": ["manual"],
        })
        result = aa04_approval_process(df)
        assert result.iloc[0] == 0.0

    def test_automated_excluded(self):
        """automated_system → not flagged."""
        df = pd.DataFrame({
            "debit_amount": [5_000_000_000.0],
            "credit_amount": [0.0],
            "approved_by": [None],
            "approval_date": [None],
            "posting_date": pd.to_datetime(["2025-06-15"]),
            "approval_level": [0],
            "user_persona": ["automated_system"],
            "source": ["automated"],
        })
        result = aa04_approval_process(df)
        assert result.iloc[0] == 0.0


# ── 오케스트레이터 ────────────────────────────────────────────


class TestAccessAuditDetector:

    def test_detector_e2e(self, base_df, change_log_df):
        """4룰 전체 실행 + DetectionResult 구조 검증."""
        det = AccessAuditDetector(change_log_df=change_log_df)
        result = det.detect(base_df)

        assert result.track_name == "access_audit"
        assert len(result.scores) == len(base_df)
        assert len(result.rule_flags) >= 3  # AA01, AA02(0건), AA03(0건), AA04
        assert "elapsed" in result.metadata

    def test_detector_graceful_no_log(self, base_df):
        """change_log=None → AA01 graceful 스킵, 나머지 정상."""
        det = AccessAuditDetector(change_log_df=None)
        result = det.detect(base_df)

        assert result.track_name == "access_audit"
        # AA01은 0점이지만 AA04는 점수 산출
        aa04_flags = [f for f in result.rule_flags if f.rule_id == "AA04"]
        assert len(aa04_flags) == 1

    def test_detector_rule_exception(self, base_df):
        """한 룰 예외 발생 → skipped 기록, 나머지 계속."""
        det = AccessAuditDetector(change_log_df=None)
        # Why: _build_registry를 monkey-patch하여 AA03에 예외 주입
        original_registry = det._build_registry

        def patched_registry():
            reg = original_registry()
            # AA03 함수를 예외 발생 함수로 교체
            return [
                (rid, (lambda df, **kw: (_ for _ in ()).throw(ValueError("test")))
                 if rid == "AA03" else func, kw)
                for rid, func, kw in reg
            ]

        det._build_registry = patched_registry
        result = det.detect(base_df)

        assert "AA03" in result.metadata["skipped_rules"]
        assert any("AA03" in w for w in result.warnings)
