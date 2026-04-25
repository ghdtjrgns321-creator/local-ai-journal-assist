"""EvidenceDetector 오케스트레이터 통합 테스트 (WU-14)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.evidence_detector import EvidenceDetector


@pytest.fixture
def full_evidence_df() -> pd.DataFrame:
    """EV01~EV03 모두 활성화 가능한 컬럼 세트."""
    return pd.DataFrame({
        "debit_amount": [50_000.0, 20_000.0, 110_000.0, 100_000.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-03-15", "2025-03-01", "2025-03-20", "2025-03-05",
        ]),
        "delivery_date": pd.to_datetime([
            "2025-03-01", "2025-03-01", "2025-03-01", "2025-03-03",
        ]),
        "has_attachment": [False, True, False, True],
        "is_manual_je": [True, False, True, False],
        "supporting_doc_type": ["receipt", "tax_invoice", None, "credit_card"],
        "gl_account": ["4100", "5200", "4300", "5100"],
        "is_revenue_account": [True, False, True, False],
        "invoice_amount": [50_000.0, 20_000.0, 100_000.0, 100_000.0],
        "supply_amount": [45_000.0, 18_000.0, 90_000.0, 90_909.0],
        "tax_amount": [5_000.0, 2_000.0, 15_000.0, 9_091.0],
        "trading_partner": ["V1", "V2", "V3", "V4"],
    })


@pytest.fixture
def audit_rules() -> dict:
    return {
        "evidence": {
            "qualified_doc_types": [
                "tax_invoice", "credit_card", "cash_receipt",
            ],
            "expense_account_prefixes": ["5"],
        },
        "patterns": {
            "revenue_account_prefixes": ["4"],
        },
    }


class TestEvidenceDetector:
    """EvidenceDetector 오케스트레이터 — 5개 테스트."""

    def test_detect_returns_all_rules(self, full_evidence_df, audit_rules):
        """3개 룰 모두 결과에 포함."""
        det = EvidenceDetector(audit_rules=audit_rules)
        result = det.detect(full_evidence_df)
        assert "EV01" in result.details.columns
        assert "L3-11" in result.details.columns
        assert "EV03" in result.details.columns

    def test_track_name(self):
        """track_name이 'evidence'."""
        det = EvidenceDetector()
        assert det.track_name == "evidence"

    def test_partial_columns_graceful(self, audit_rules):
        """증빙 컬럼 일부 부재 시 해당 룰만 스킵, 나머지 정상."""
        df = pd.DataFrame({
            "debit_amount": [110_000.0],
            "credit_amount": [0.0],
            "invoice_amount": [100_000.0],
            # has_attachment, delivery_date 없음 → EV01.S1, L3-11 비활성
        })
        det = EvidenceDetector(audit_rules=audit_rules)
        result = det.detect(df)
        # EV03만 실행 → 금액 불일치 탐지
        assert result.details["EV03"].iloc[0] > 0

    def test_empty_dataframe(self):
        """빈 DataFrame → 빈 결과."""
        df = pd.DataFrame(columns=[
            "debit_amount", "credit_amount", "posting_date",
        ])
        det = EvidenceDetector()
        result = det.detect(df)
        assert len(result.scores) == 0
        assert len(result.flagged_indices) == 0

    def test_scores_range(self, full_evidence_df, audit_rules):
        """scores 범위가 0~1."""
        det = EvidenceDetector(audit_rules=audit_rules)
        result = det.detect(full_evidence_df)
        assert (result.scores >= 0).all()
        assert (result.scores <= 1).all()
