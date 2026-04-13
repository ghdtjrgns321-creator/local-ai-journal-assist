"""L2 대차불일치 fatal 처리 테스트.

검증 항목:
1. 정상 데이터 → 통과
2. 비율 작음(< balance_fatal_ratio) → warns만 추가, 통과
3. 비율 큼(> balance_fatal_ratio) → ValueError 발생
4. 불일치 전표 비중 큼(> balance_fatal_doc_ratio) → ValueError 발생
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.pipeline import AuditPipeline


def _make_df(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """헬퍼 — (document_id, debit, credit) 튜플 리스트로 GL DF 생성."""
    n = len(rows)
    return pd.DataFrame({
        "document_id": [r[0] for r in rows],
        "debit_amount": [r[1] for r in rows],
        "credit_amount": [r[2] for r in rows],
        "gl_account": ["1000"] * n,
        "company_code": ["C1"] * n,
        "fiscal_year": [2025] * n,
        "fiscal_period": [6] * n,
        "posting_date": pd.to_datetime(["2025-06-15"] * n),
        "document_date": pd.to_datetime(["2025-06-15"] * n),
        "document_type": ["SA"] * n,
        "line_number": list(range(1, n + 1)),
    })


class TestL2BalancePassThrough:
    """정상/경미한 불일치는 통과."""

    def test_balanced_passes(self, small_gl_df):
        """완벽한 대차일치 → 정상 완료."""
        result = AuditPipeline(skip_db=True).run_from_dataframe(small_gl_df)
        # Why: 대차불일치 메시지가 warnings에 없어야 함
        assert not any("대차불일치" in w for w in result.warnings)

    def test_minor_imbalance_warns(self):
        """경미한 불일치 → fatal이 아니고 warns에 메시지.

        Why: diff_ratio < 1% AND doc_ratio < 10% 두 조건 모두 충족해야 비-fatal.
             12개 전표 중 1개만 1원 불일치 → diff_ratio≈0.08%, doc_ratio≈8.3%.
        """
        rows = [(f"D{i:03d}", 100.0, 100.0) for i in range(11)]  # 11개 일치
        rows.append(("D011", 100.0, 99.0))  # 1개 불일치 (1원)
        df = _make_df(rows)
        result = AuditPipeline(skip_db=True).run_from_dataframe(df)
        assert any("대차불일치" in w for w in result.warnings)


class TestL2BalanceFatal:
    """심각한 불일치는 ValueError로 차단."""

    def test_high_diff_ratio_raises(self):
        """차이 비율이 1%를 크게 초과 → ValueError."""
        # Why: 차변 합 100원, 차이 50원 → 50% (> 1%)
        rows = [
            ("D001", 100.0, 50.0),   # 50원 불일치
        ]
        df = _make_df(rows)
        with pytest.raises(ValueError, match="L2 대차불일치 치명"):
            AuditPipeline(skip_db=True).run_from_dataframe(df)

    def test_high_doc_ratio_raises(self):
        """불일치 전표 비중이 10% 초과 → ValueError."""
        # Why: 5개 전표 중 4개가 1원씩 불일치 → 80% > 10%
        # 그러나 전체 비율은 작도록 큰 금액 부풀림
        rows = [
            ("D001", 1_000_000.0, 1_000_000.0),  # 일치
            ("D002", 100.0, 99.0),                # 불일치
            ("D003", 100.0, 99.0),                # 불일치
            ("D004", 100.0, 99.0),                # 불일치
            ("D005", 100.0, 99.0),                # 불일치
        ]
        df = _make_df(rows)
        with pytest.raises(ValueError, match="L2 대차불일치 치명"):
            AuditPipeline(skip_db=True).run_from_dataframe(df)

    def test_fatal_message_includes_ratios(self):
        """ValueError 메시지에 차이 비율과 전표 비중이 포함된다."""
        rows = [("D001", 100.0, 50.0)]
        df = _make_df(rows)
        with pytest.raises(ValueError) as exc_info:
            AuditPipeline(skip_db=True).run_from_dataframe(df)
        msg = str(exc_info.value)
        assert "차이" in msg and "비중" in msg
