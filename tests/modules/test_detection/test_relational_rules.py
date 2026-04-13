"""Relational 룰 함수 단위 테스트 — WU-08 관계 기반 이상 탐지.

23개 테스트: R01(5) + R02(8) + R03(5) + R04(5)
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from src.detection.relational_rules import (
    r01_new_counterparty,
    r02_dormant_account_activity,
    r03_transfer_pricing_anomaly,
    r04_missing_relationship,
)


# ── 공용 헬퍼 ──────────────────────────────────────────────────


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """테스트용 DataFrame 생성 — posting_date 자동 변환."""
    df = pd.DataFrame(rows)
    if "posting_date" in df.columns:
        df["posting_date"] = pd.to_datetime(df["posting_date"])
    for col in ["debit_amount", "credit_amount"]:
        if col not in df.columns:
            df[col] = 0.0
    return df


# ── R01 NewCounterparty (5개) ──────────────────────────────────


class TestR01NewCounterparty:
    """R01: 신규 거래처 + 대액 지급 탐지."""

    def test_flags_new_large(self):
        """#1: 신규 거래처(lookback 내 첫 등장) + 대액 → score > 0."""
        base_date = pd.Timestamp("2024-01-15")
        rows = [
            # 기존 거래처 V01: 오래전부터 거래
            {"trading_partner": "V01", "posting_date": "2023-06-01", "debit_amount": 500_000, "credit_amount": 0},
            {"trading_partner": "V01", "posting_date": "2024-01-10", "debit_amount": 500_000, "credit_amount": 0},
            # 신규 거래처 V99: 최근 첫 등장 + 대액
            {"trading_partner": "V99", "posting_date": "2024-01-15", "debit_amount": 50_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r01_new_counterparty(df, lookback_days=90, large_quantile=0.80)
        # V99(idx=2)만 신규+대액이므로 score > 0
        assert scores.iloc[2] > 0, "신규 거래처 대액 미탐지"

    def test_skips_old_partner(self):
        """#2: lookback 초과 기존 거래처 → score = 0."""
        rows = [
            {"trading_partner": "V01", "posting_date": "2023-01-01", "debit_amount": 100_000_000, "credit_amount": 0},
            {"trading_partner": "V01", "posting_date": "2024-01-01", "debit_amount": 100_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r01_new_counterparty(df, lookback_days=90, large_quantile=0.50)
        # V01의 first_seen은 2023-01-01 → 2024-01-01 기준 lookback(90일) 초과
        assert scores.iloc[1] == 0.0, "기존 거래처가 플래그됨"

    def test_skips_small_amount(self):
        """#3: 신규 거래처 + 소액 → score = 0."""
        rows = [
            {"trading_partner": "V99", "posting_date": "2024-01-15", "debit_amount": 100, "credit_amount": 0},
            {"trading_partner": "V01", "posting_date": "2024-01-15", "debit_amount": 50_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r01_new_counterparty(df, lookback_days=90, large_quantile=0.80)
        # V99(idx=0)는 신규지만 소액 → 0
        assert scores.iloc[0] == 0.0, "소액 거래가 플래그됨"

    def test_graceful_missing_trading_partner(self):
        """#4: trading_partner 컬럼 없음 → Series(0.0)."""
        df = _make_df([{"posting_date": "2024-01-15", "debit_amount": 1_000_000}])
        scores = r01_new_counterparty(df, lookback_days=90, large_quantile=0.90)
        assert (scores == 0.0).all()

    def test_empty_dataframe(self):
        """#5: 빈 DataFrame → Series(0.0)."""
        df = pd.DataFrame(columns=["trading_partner", "posting_date", "debit_amount", "credit_amount"])
        scores = r01_new_counterparty(df, lookback_days=90, large_quantile=0.90)
        assert len(scores) == 0


# ── R02 DormantAccountActivity (8개) ───────────────────────────


class TestR02DormantAccountActivity:
    """R02: 휴면 계정 재활성화 탐지 + 연좌 플래깅."""

    def test_flags_reactivated_first(self):
        """#6: 180일+ 미사용 후 재활성화 첫 건 → score > 0."""
        rows = [
            {"gl_account": "5100", "posting_date": "2023-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            # 200일 후 재활성화
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 5_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert scores.iloc[1] > 0, "재활성화 첫 건 미탐지"

    def test_flags_same_day_followup(self):
        """#7: 재활성화 당일 후속 전표 → 연좌 플래그 (쪼개기 방어)."""
        rows = [
            {"gl_account": "5100", "posting_date": "2023-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            # 200일 후 재활성화 — 같은 날 3건 (쪼개기 송금)
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 3_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 3_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 4_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        # idx 1, 2, 3 모두 플래그되어야 함 (연좌)
        assert scores.iloc[1] > 0, "재활성화 첫 건 미탐지"
        assert scores.iloc[2] > 0, "같은 날 후속 전표 미탐지 (연좌 실패)"
        assert scores.iloc[3] > 0, "같은 날 후속 전표 미탐지 (연좌 실패)"

    def test_flags_window_followup(self):
        """#8: 재활성화 후 윈도우(7일) 내 후속 전표 → 플래그."""
        rows = [
            {"gl_account": "5100", "posting_date": "2023-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 5_000_000, "credit_amount": 0},  # 재활성화
            {"gl_account": "5100", "posting_date": "2023-08-07", "debit_amount": 2_000_000, "credit_amount": 0},  # 윈도우 내
        ]
        df = _make_df(rows)
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert scores.iloc[2] > 0, "윈도우 내 후속 전표 미탐지"

    def test_skips_outside_window(self):
        """#9: 재활성화 윈도우 밖 정상 거래 → score = 0."""
        rows = [
            {"gl_account": "5100", "posting_date": "2023-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2023-08-03", "debit_amount": 5_000_000, "credit_amount": 0},  # 재활성화
            {"gl_account": "5100", "posting_date": "2023-09-15", "debit_amount": 1_000_000, "credit_amount": 0},  # 윈도우 밖
        ]
        df = _make_df(rows)
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert scores.iloc[2] == 0.0, "윈도우 밖 거래가 플래그됨"

    def test_skips_active_account(self):
        """#10: 연속 거래 (gap < threshold) → score = 0."""
        rows = [
            {"gl_account": "5100", "posting_date": "2024-01-01", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2024-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "5100", "posting_date": "2024-02-01", "debit_amount": 1_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert (scores == 0.0).all(), "활성 계정이 플래그됨"

    def test_skips_first_entry(self):
        """#11: 첫 거래 (diff NaN) → score = 0."""
        df = _make_df([
            {"gl_account": "5100", "posting_date": "2024-01-15", "debit_amount": 10_000_000, "credit_amount": 0},
        ])
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert scores.iloc[0] == 0.0, "첫 거래가 플래그됨"

    def test_graceful_missing_gl_account(self):
        """#12: gl_account 컬럼 없음 → Series(0.0)."""
        df = _make_df([{"posting_date": "2024-01-15", "debit_amount": 1_000_000}])
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert (scores == 0.0).all()

    def test_single_entry_account(self):
        """#13: 계정에 거래 1건만 → score = 0 (비교 대상 없음)."""
        df = _make_df([
            {"gl_account": "5100", "posting_date": "2024-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
            {"gl_account": "5200", "posting_date": "2024-01-15", "debit_amount": 1_000_000, "credit_amount": 0},
        ])
        scores = r02_dormant_account_activity(df, inactive_days=180, reactivation_window_days=7)
        assert (scores == 0.0).all()


# ── R03 TransferPricingAnomaly (5개) ───────────────────────────


class TestR03TransferPricingAnomaly:
    """R03: IC 이전가격 이상 탐지."""

    def test_flags_ic_outlier(self):
        """#14: IC 거래 금액 편차 초과 → score > 0."""
        rows = [
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            # 동일 그룹에서 크게 벗어난 금액
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 50_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r03_transfer_pricing_anomaly(df, deviation_threshold=0.15, min_ic_pairs=3)
        assert scores.iloc[3] > 0, "IC 이상 금액 미탐지"

    def test_skips_within_threshold(self):
        """#15: 편차 범위 내 → score = 0."""
        rows = [
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_500_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_200_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r03_transfer_pricing_anomaly(df, deviation_threshold=0.15, min_ic_pairs=3)
        assert (scores == 0.0).all(), "정상 범위 IC가 플래그됨"

    def test_non_ic_zero(self):
        """#16: 비IC 거래 → score = 0."""
        rows = [
            {"is_intercompany": False, "trading_partner": "EXT01", "gl_account": "5100", "debit_amount": 100_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        scores = r03_transfer_pricing_anomaly(df, deviation_threshold=0.15, min_ic_pairs=3)
        assert scores.iloc[0] == 0.0, "비IC 거래가 플래그됨"

    def test_graceful_missing_is_intercompany(self):
        """#17: is_intercompany 컬럼 없음 → Series(0.0)."""
        df = _make_df([{"trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000}])
        scores = r03_transfer_pricing_anomaly(df, deviation_threshold=0.15, min_ic_pairs=3)
        assert (scores == 0.0).all()

    def test_min_pairs_guard(self):
        """#18: min_ic_pairs 미달 그룹 → score = 0."""
        rows = [
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 10_000_000, "credit_amount": 0},
            {"is_intercompany": True, "trading_partner": "SUB01", "gl_account": "4500", "debit_amount": 50_000_000, "credit_amount": 0},
        ]
        df = _make_df(rows)
        # min_ic_pairs=3이지만 그룹에 2건만 → 스킵
        scores = r03_transfer_pricing_anomaly(df, deviation_threshold=0.15, min_ic_pairs=3)
        assert (scores == 0.0).all(), "소그룹이 플래그됨"


# ── R04 MissingRelationship (5개) ──────────────────────────────


class TestR04MissingRelationship:
    """R04: 문서 흐름 누락 탐지."""

    @staticmethod
    def _make_doc_flow_df(rows: list[dict]) -> pd.DataFrame:
        """doc_flow_df 테스트 헬퍼."""
        return pd.DataFrame(rows)

    def test_flags_partial_p2p(self):
        """#19: P2P 체인 1단계 누락 → score ≈ 0.33."""
        df = _make_df([
            {"document_id": "JE-001", "posting_date": "2024-01-15", "debit_amount": 1_000_000},
            {"document_id": "JE-002", "posting_date": "2024-01-15", "debit_amount": 2_000_000},
        ])
        doc_flow = self._make_doc_flow_df([
            {"journal_entry_id": "JE-001", "chain": "P2P", "total": 3, "present": 2},  # 1 누락
        ])
        scores = r04_missing_relationship(df, doc_flow_df=doc_flow)
        assert 0.3 <= scores.iloc[0] <= 0.4, f"P2P 1단계 누락 점수 이상: {scores.iloc[0]}"
        assert scores.iloc[1] == 0.0, "비매칭 행이 플래그됨"

    def test_flags_multiple_missing(self):
        """#20: P2P 체인 2단계 누락 → score ≈ 0.67."""
        df = _make_df([
            {"document_id": "JE-001", "posting_date": "2024-01-15", "debit_amount": 1_000_000},
        ])
        doc_flow = self._make_doc_flow_df([
            {"journal_entry_id": "JE-001", "chain": "P2P", "total": 3, "present": 1},
        ])
        scores = r04_missing_relationship(df, doc_flow_df=doc_flow)
        assert 0.6 <= scores.iloc[0] <= 0.7, f"P2P 2단계 누락 점수 이상: {scores.iloc[0]}"

    def test_complete_chain_zero(self):
        """#21: 체인 완전 → doc_flow_df에 미포함 → score = 0."""
        df = _make_df([
            {"document_id": "JE-001", "posting_date": "2024-01-15", "debit_amount": 1_000_000},
        ])
        # 완전한 체인은 build_doc_flow_df에서 제외되므로 빈 결과
        doc_flow = self._make_doc_flow_df([])
        scores = r04_missing_relationship(df, doc_flow_df=doc_flow)
        assert scores.iloc[0] == 0.0

    def test_graceful_none_doc_flow(self):
        """#22: doc_flow_df=None → Series(0.0)."""
        df = _make_df([
            {"document_id": "JE-001", "posting_date": "2024-01-15", "debit_amount": 1_000_000},
        ])
        scores = r04_missing_relationship(df, doc_flow_df=None)
        assert (scores == 0.0).all()

    def test_unmatched_document_id(self):
        """#23: document_id 미매칭 → score = 0."""
        df = _make_df([
            {"document_id": "JE-999", "posting_date": "2024-01-15", "debit_amount": 1_000_000},
        ])
        doc_flow = self._make_doc_flow_df([
            {"journal_entry_id": "JE-001", "chain": "P2P", "total": 3, "present": 1},
        ])
        scores = r04_missing_relationship(df, doc_flow_df=doc_flow)
        assert scores.iloc[0] == 0.0
