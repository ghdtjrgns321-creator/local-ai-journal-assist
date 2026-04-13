"""EV01~EV03 순수 룰 함수 단위 테스트 (WU-14)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detection.evidence_rules import (
    ev01_missing_evidence,
    ev02_cutoff_violation,
    ev03_amount_mismatch,
)


# ── 공용 헬퍼 ────────────────────────────────────────────────


def _base_df(**overrides) -> pd.DataFrame:
    """기본 4행 DataFrame. 키워드로 컬럼 오버라이드 가능."""
    data = {
        "debit_amount": [50_000.0, 20_000.0, 35_000.0, 10_000.0],
        "credit_amount": [0.0, 0.0, 0.0, 0.0],
        "posting_date": pd.to_datetime(["2025-03-01"] * 4),
    }
    data.update(overrides)
    return pd.DataFrame(data)


# ══════════════════════════════════════════════════════════════
# EV01: 증빙 존재 확인
# ══════════════════════════════════════════════════════════════


class TestEV01:
    """EV01 증빙 존재 확인 — 7개 테스트."""

    def test_missing_attachment_manual_high_amount(self):
        """S1: 증빙 미첨부 + 수기 + 고액 → 0.6."""
        df = _base_df(
            has_attachment=[False, True, False, False],
            is_manual_je=[True, True, True, False],
        )
        result = ev01_missing_evidence(df, tax_threshold=30_000)
        # 행 0: False+True+50k>30k → 0.6
        # 행 2: False+True+35k>30k → 0.6
        assert result.iloc[0] == pytest.approx(0.6)
        assert result.iloc[1] == 0.0  # has_attachment=True
        assert result.iloc[2] == pytest.approx(0.6)
        assert result.iloc[3] == 0.0  # not manual

    def test_unqualified_doc_type(self):
        """S2: 고액인데 적격증빙 유형 아님 → 0.5."""
        df = _base_df(
            supporting_doc_type=["receipt", "tax_invoice", None, "credit_card"],
        )
        result = ev01_missing_evidence(
            df,
            qualified_doc_types=["tax_invoice", "credit_card"],
            tax_threshold=30_000,
        )
        # 행 0: 50k>30k, "receipt" 부적격 → 0.5
        # 행 2: 35k>30k, None → 0.5
        assert result.iloc[0] == pytest.approx(0.5)
        assert result.iloc[1] == 0.0  # tax_invoice 적격
        assert result.iloc[2] == pytest.approx(0.5)
        assert result.iloc[3] == 0.0  # 10k < 30k

    def test_split_transaction_detection(self):
        """S3: 동일 거래처+동일일 분할 의심 → 0.8."""
        df = pd.DataFrame({
            "debit_amount": [25_000.0, 28_000.0, 29_000.0, 100_000.0],
            "credit_amount": [0.0, 0.0, 0.0, 0.0],
            "trading_partner": ["VENDOR_A", "VENDOR_A", "VENDOR_A", "VENDOR_B"],
            "posting_date": pd.to_datetime(["2025-03-01"] * 4),
        })
        result = ev01_missing_evidence(
            df,
            split_max_amount=29_000,
            split_min_count=3,
        )
        # 행 0~2: VENDOR_A 3건, max 29k ≤ 29k → 0.8
        assert result.iloc[0] == pytest.approx(0.8)
        assert result.iloc[1] == pytest.approx(0.8)
        assert result.iloc[2] == pytest.approx(0.8)
        assert result.iloc[3] == 0.0  # VENDOR_B 1건

    def test_no_has_attachment_column(self):
        """has_attachment 컬럼 부재 시 S1 스킵 → 에러 없이 실행."""
        df = _base_df()  # has_attachment 없음
        result = ev01_missing_evidence(df)
        assert len(result) == len(df)
        # S1 스킵, S2/S3도 컬럼 없어서 스킵 → 전체 0.0
        assert (result == 0.0).all()

    def test_no_supporting_doc_type_column(self):
        """supporting_doc_type 부재 시 S2 스킵."""
        df = _base_df(has_attachment=[False, False, False, False])
        result = ev01_missing_evidence(df, tax_threshold=30_000)
        # S1만 작동 (is_manual_je 부재 → 보수적 True)
        assert result.iloc[0] > 0  # 50k > 30k

    def test_no_partner_column(self):
        """trading_partner + auxiliary 모두 부재 시 S3 스킵."""
        df = _base_df(has_attachment=[False] * 4, supporting_doc_type=[None] * 4)
        result = ev01_missing_evidence(df, tax_threshold=30_000)
        assert len(result) == 4  # 에러 없이 반환

    def test_empty_dataframe(self):
        """빈 DataFrame → 빈 Series 반환."""
        df = pd.DataFrame(columns=["debit_amount", "credit_amount"])
        result = ev01_missing_evidence(df)
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════
# EV02: 컷오프 검증
# ══════════════════════════════════════════════════════════════


class TestEV02:
    """EV02 컷오프 검증 — 8개 테스트."""

    def test_revenue_cutoff_violation(self):
        """매출 계정: posting - delivery > 5일 → 점수 부여."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-15"]),
            "delivery_date": pd.to_datetime(["2025-03-01"]),
            "gl_account": ["4100"],
            "is_revenue_account": [True],
        })
        result = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=5,
            max_day_diff=30,
            use_business_days=False,
        )
        # 14일 차이 > 5일, score = 14/30 ≈ 0.467
        assert result.iloc[0] > 0.4

    def test_expense_cutoff_violation(self):
        """비용 계정: posting - delivery > 7일 → 점수 부여."""
        df = pd.DataFrame({
            "debit_amount": [500_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-20"]),
            "delivery_date": pd.to_datetime(["2025-03-01"]),
            "gl_account": ["5100"],
        })
        result = ev02_cutoff_violation(
            df,
            expense_cutoff_days=7,
            max_day_diff=30,
            use_business_days=False,
            expense_account_prefixes=["5"],
        )
        # 19일 > 7일, score = 19/30 ≈ 0.633
        assert result.iloc[0] > 0.5

    def test_period_end_weight(self):
        """기말 가중: is_period_end=True → 점수 × 1.5."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-30"]),
            "delivery_date": pd.to_datetime(["2025-03-15"]),
            "gl_account": ["4100"],
            "is_revenue_account": [True],
            "is_period_end": [True],
        })
        without_weight = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=5,
            period_end_weight=1.0,
            use_business_days=False,
        ).iloc[0]
        with_weight = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=5,
            period_end_weight=1.5,
            use_business_days=False,
        ).iloc[0]
        assert with_weight > without_weight

    def test_delivery_date_all_nat(self):
        """delivery_date 전체 NaT → 전체 0.0."""
        df = pd.DataFrame({
            "debit_amount": [100_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-01"]),
            "delivery_date": [pd.NaT],
            "gl_account": ["4100"],
        })
        result = ev02_cutoff_violation(df, use_business_days=False)
        assert result.iloc[0] == 0.0

    def test_partial_nat_no_crash(self):
        """부분 NaT 혼재 시 ValueError 없이 정상 실행."""
        df = pd.DataFrame({
            "debit_amount": [100_000.0, 200_000.0, 300_000.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-03-15", "2025-03-15", "2025-03-15"]),
            "delivery_date": pd.to_datetime(["2025-03-01", pd.NaT, "2025-03-10"]),
            "gl_account": ["4100", "4200", "4300"],
            "is_revenue_account": [True, True, True],
        })
        # Why: NaT 1개라도 있으면 np.busday_count가 ValueError → 마스킹 필수
        result = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=5,
            use_business_days=True,
        )
        assert len(result) == 3
        assert result.iloc[0] > 0   # 14일 차이
        assert result.iloc[1] == 0.0  # NaT → 0
        assert result.iloc[2] >= 0   # 5일 차이

    def test_business_days_vs_calendar(self):
        """영업일 vs 달력일 계산 결과 차이 확인."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-14"]),  # 금요일
            "delivery_date": pd.to_datetime(["2025-03-03"]),  # 월요일
            "gl_account": ["4100"],
            "is_revenue_account": [True],
        })
        biz = ev02_cutoff_violation(df, revenue_cutoff_days=5, use_business_days=True)
        cal = ev02_cutoff_violation(df, revenue_cutoff_days=5, use_business_days=False)
        # 달력일=11일, 영업일=9일 → 둘 다 임계 초과지만 수치 다름
        assert biz.iloc[0] != cal.iloc[0]

    def test_normal_within_threshold(self):
        """임계 이내 → 점수 0."""
        df = pd.DataFrame({
            "debit_amount": [100_000.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-03-05"]),
            "delivery_date": pd.to_datetime(["2025-03-03"]),
            "gl_account": ["4100"],
            "is_revenue_account": [True],
        })
        result = ev02_cutoff_violation(
            df,
            revenue_cutoff_days=5,
            use_business_days=False,
        )
        assert result.iloc[0] == 0.0  # 2일 ≤ 5일

    def test_empty_dataframe(self):
        """빈 DataFrame → 빈 Series."""
        df = pd.DataFrame(columns=["posting_date", "delivery_date"])
        result = ev02_cutoff_violation(df)
        assert len(result) == 0


# ══════════════════════════════════════════════════════════════
# EV03: 증빙 금액 불일치
# ══════════════════════════════════════════════════════════════


class TestEV03:
    """EV03 증빙 금액 불일치 — 6개 테스트."""

    def test_three_way_mismatch(self):
        """S1: 전기 금액 vs 세금계산서 금액 불일치."""
        df = pd.DataFrame({
            "debit_amount": [110_000.0, 100_000.0],
            "credit_amount": [0.0, 0.0],
            "invoice_amount": [100_000.0, 100_000.0],
        })
        result = ev03_amount_mismatch(df, amount_tolerance=1.0)
        # 행 0: |110k - 100k| = 10k > 1 → score = 10k/(100k*0.1) = 1.0
        assert result.iloc[0] == pytest.approx(1.0)
        # 행 1: |100k - 100k| = 0 → 0.0
        assert result.iloc[1] == 0.0

    def test_vat_error(self):
        """S2: 부가세 계산 오류 탐지."""
        df = pd.DataFrame({
            "debit_amount": [110_000.0, 110_000.0],
            "credit_amount": [0.0, 0.0],
            "supply_amount": [100_000.0, 100_000.0],
            "tax_amount": [15_000.0, 10_000.0],  # 첫 번째만 오류 (정상은 10k)
        })
        result = ev03_amount_mismatch(df, vat_rate=0.10, vat_tolerance=1.0)
        assert result.iloc[0] == pytest.approx(0.7)  # |15k - 10k| = 5k > 1
        assert result.iloc[1] == 0.0  # 정상

    def test_tax_exempt_excluded(self):
        """면세/영세율 거래(tax_amount=0) → S2 검증 대상에서 제외."""
        df = pd.DataFrame({
            "debit_amount": [1_000_000.0, 500_000.0],
            "credit_amount": [0.0, 0.0],
            "supply_amount": [1_000_000.0, 500_000.0],
            "tax_amount": [0.0, np.nan],  # 면세 + 영세율
        })
        result = ev03_amount_mismatch(df, vat_rate=0.10, vat_tolerance=1.0)
        # Why: tax_amount=0 또는 NaN → 면세/영세율 → S2 미적용
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 0.0

    def test_within_tolerance(self):
        """허용 오차 이내 → 0.0."""
        df = pd.DataFrame({
            "debit_amount": [100_001.0],
            "credit_amount": [0.0],
            "invoice_amount": [100_000.0],
        })
        result = ev03_amount_mismatch(df, amount_tolerance=5.0)
        # |100001 - 100000| = 1 ≤ 5 → 0.0
        assert result.iloc[0] == 0.0

    def test_missing_columns(self):
        """invoice_amount, supply_amount, tax_amount 모두 부재 → 전체 0.0."""
        df = pd.DataFrame({
            "debit_amount": [100_000.0],
            "credit_amount": [0.0],
        })
        result = ev03_amount_mismatch(df)
        assert result.iloc[0] == 0.0

    def test_zero_amount_defense(self):
        """invoice_amount=0 → 분모 clip(1.0)으로 나눗셈 오류 방지."""
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "invoice_amount": [0.0],
        })
        # invoice_amount=0 → has_invoice=False → S1 미적용
        result = ev03_amount_mismatch(df, amount_tolerance=1.0)
        assert result.iloc[0] == 0.0
