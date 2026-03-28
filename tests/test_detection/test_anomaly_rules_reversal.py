"""C11 역분개 패턴 탐지 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.anomaly_rules_reversal import (
    _s1_one_to_one_match,
    _s2_rolling_zero_out,
    _s3_reversal_type,
    _s4_keyword_match,
    _s5_period_end_boost,
    c11_reversal_entry,
)


# ── 공통 fixture ──────────────────────────────────────────────


@pytest.fixture
def reversal_pair_df() -> pd.DataFrame:
    """1:1 역분개 쌍이 포함된 DataFrame (4행).

    D001: 1000 계정에 100만 차변
    D002: 1000 계정에 100만 대변 (D001의 역분개, 익일)
    D003: 2000 계정에 50만 차변 (무관)
    D004: 3000 계정에 200만 차변 (무관)
    """
    return pd.DataFrame({
        "document_id": ["D001", "D002", "D003", "D004"],
        "gl_account": ["1000", "1000", "2000", "3000"],
        "debit_amount": [1_000_000.0, 0.0, 500_000.0, 2_000_000.0],
        "credit_amount": [0.0, 1_000_000.0, 0.0, 0.0],
        "posting_date": pd.to_datetime([
            "2025-12-15", "2025-12-16", "2025-12-15", "2025-12-15",
        ]),
        "created_by": ["user_a", "user_a", "user_b", "user_c"],
        "source": ["manual", "manual", "automated", "manual"],
        "line_text": ["매출 기록", "수정 전표", "재료비", "투자"],
        "header_text": ["", "", "", ""],
        "fiscal_period": [12, 12, 12, 12],
        "is_period_end": [False, False, False, False],
    })


# ── S1: 1:1 매칭 테스트 ──────────────────────────────────────


class TestS1OneToOneMatch:
    """S1 서브 신호 — 1:1 역분개 매칭."""

    def test_exact_reversal_flagged(self, reversal_pair_df: pd.DataFrame) -> None:
        """동일 계정 + 동일 금액 + 반대 방향 + 익일 → 양쪽 모두 플래그."""
        result = _s1_one_to_one_match(reversal_pair_df, match_window_days=1)
        # D001, D002는 역분개 쌍
        assert bool(result.iloc[0])
        assert bool(result.iloc[1])
        # D003, D004는 무관
        assert not result.iloc[2]
        assert not result.iloc[3]

    def test_same_document_not_flagged(self) -> None:
        """같은 document_id 내 차/대변 = 정상 복합분개 → 미플래그."""
        df = pd.DataFrame({
            "document_id": ["D001", "D001"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
        })
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_different_account_not_matched(self) -> None:
        """다른 gl_account → 역분개 아님."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "2000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
        })
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_amount_mismatch_not_matched(self) -> None:
        """금액 불일치 → 매칭 안 됨."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 200.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
        })
        result = _s1_one_to_one_match(df)
        assert not result.any()

    def test_date_outside_window_not_matched(self) -> None:
        """일수 초과 (±1일 밖) → 미매칭."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-05"]),
        })
        result = _s1_one_to_one_match(df, match_window_days=1)
        assert not result.any()

    def test_clearing_account_excluded(self) -> None:
        """GR/IR 청산계정(2900)은 정상 반제이므로 S1 제외."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["2900", "2900"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-01"]),
        })
        result = _s1_one_to_one_match(df)
        assert not result.any(), "청산계정은 역분개 탐지 대상 아님"


# ── S2: N:M 롤링 제로아웃 테스트 ──────────────────────────────


class TestS2RollingZeroOut:
    """S2 서브 신호 — 분할 역분개 탐지."""

    def test_three_entries_sum_zero_flagged(self) -> None:
        """100 DR + 60 CR + 40 CR (7일 내, 같은 user) → 순액 0 → 플래그."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "gl_account": ["1000", "1000", "1000"],
            "debit_amount": [100_000.0, 0.0, 0.0],
            "credit_amount": [0.0, 60_000.0, 40_000.0],
            "posting_date": pd.to_datetime([
                "2025-06-01", "2025-06-03", "2025-06-05",
            ]),
            "created_by": ["user_a", "user_a", "user_a"],
        })
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert result.any(), "3건 합산 0인 분할 역분개가 탐지되어야 함"

    def test_nonzero_sum_not_flagged(self) -> None:
        """합산 ≠ 0 → 미플래그."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [100_000.0, 0.0],
            "credit_amount": [0.0, 30_000.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-03"]),
            "created_by": ["user_a", "user_a"],
        })
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert not result.any()

    def test_different_user_separate_group(self) -> None:
        """다른 created_by → 별도 그룹 → 매칭 안 됨."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "gl_account": ["1000", "1000", "1000"],
            "debit_amount": [100_000.0, 0.0, 0.0],
            "credit_amount": [0.0, 60_000.0, 40_000.0],
            "posting_date": pd.to_datetime([
                "2025-06-01", "2025-06-03", "2025-06-05",
            ]),
            "created_by": ["user_a", "user_b", "user_c"],
        })
        result = _s2_rolling_zero_out(df, rolling_window_days=7, zero_threshold=1000)
        assert not result.any()

    def test_missing_created_by_returns_false(self) -> None:
        """created_by 컬럼 없으면 전원 False (graceful degradation)."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-02"]),
        })
        result = _s2_rolling_zero_out(df)
        assert not result.any()


# ── S3: 정상/수정 구분 테스트 ──────────────────────────────────


class TestS3ReversalType:
    """S3 서브 신호 — 월초 자동 감점, 수동 가중."""

    def test_auto_january_discounted(self) -> None:
        """source=auto + 1월 1일 → 음수 조정 (정상 역분개 감점)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2026-01-03"]),
            "source": ["automated"],
            "fiscal_period": [1],
        })
        result = _s3_reversal_type(df)
        assert result.iloc[0] < 0, "자동+1월초는 감점이어야 함"

    def test_auto_other_month_start_discounted(self) -> None:
        """source=auto + 3월 2일 → 소폭 감점."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2026-03-02"]),
            "source": ["recurring"],
            "fiscal_period": [3],
        })
        result = _s3_reversal_type(df)
        assert result.iloc[0] < 0, "자동+월초는 소폭 감점이어야 함"

    def test_manual_midmonth_boosted(self) -> None:
        """source=manual + 6월 15일 → 양수 조정 (수정 전표 가중)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15"]),
            "source": ["manual"],
            "fiscal_period": [6],
        })
        result = _s3_reversal_type(df)
        assert result.iloc[0] > 0, "수동+월중은 가중이어야 함"

    def test_missing_source_zero(self) -> None:
        """source 컬럼 없으면 조정값 0 (neutral)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15"]),
        })
        result = _s3_reversal_type(df)
        assert result.iloc[0] == 0.0


# ── S4: 적요 키워드 테스트 ────────────────────────────────────


class TestS4KeywordMatch:
    """S4 서브 신호 — 역분개 키워드 매칭."""

    def test_korean_keyword_matched(self) -> None:
        """한글 키워드 '수정' 포함 → True."""
        df = pd.DataFrame({"line_text": ["수정 전표 입력"]})
        result = _s4_keyword_match(df)
        assert result.iloc[0]

    def test_english_keyword_matched(self) -> None:
        """영문 키워드 'Reversal' 포함 → True."""
        df = pd.DataFrame({"line_text": ["Reversal of accrual"]})
        result = _s4_keyword_match(df)
        assert result.iloc[0]

    def test_no_keyword_not_matched(self) -> None:
        """키워드 없는 일반 텍스트 → False."""
        df = pd.DataFrame({"line_text": ["재료비 구매 대금"]})
        result = _s4_keyword_match(df)
        assert not result.iloc[0]

    def test_header_text_ignored(self) -> None:
        """header_text의 키워드는 무시 — SAP BKTXT는 시스템 자동 기입 노이즈."""
        df = pd.DataFrame({
            "line_text": ["재료비 구매"],
            "header_text": ["Reversal batch job"],
        })
        result = _s4_keyword_match(df)
        assert not result.iloc[0], "header_text 키워드만으로는 매칭 안 됨"

    def test_missing_line_text(self) -> None:
        """line_text 컬럼 없으면 전원 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        result = _s4_keyword_match(df)
        assert not result.any()


# ── S5: 기말 부스트 테스트 ────────────────────────────────────


class TestS5PeriodEndBoost:
    """S5 서브 신호 — 결산 전후 15일 배율."""

    def test_december_end_boosted(self) -> None:
        """12월 25일 → 배율 1.5."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-12-25"]),
        })
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.5

    def test_january_start_boosted(self) -> None:
        """1월 3일 → 배율 1.5."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2026-01-03"]),
        })
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.5

    def test_midyear_no_boost(self) -> None:
        """6월 15일 → 배율 1.0 (부스트 없음)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-06-15"]),
        })
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.0

    def test_december_early_no_boost(self) -> None:
        """12월 10일 → 배율 1.0 (12/20 이전)."""
        df = pd.DataFrame({
            "posting_date": pd.to_datetime(["2025-12-10"]),
        })
        result = _s5_period_end_boost(df)
        assert result.iloc[0] == 1.0


# ── 종합 C11 테스트 ───────────────────────────────────────────


class TestC11ReversalEntry:
    """c11_reversal_entry() 통합 테스트."""

    def test_reversal_pair_flagged(self, reversal_pair_df: pd.DataFrame) -> None:
        """역분개 쌍 + 키워드 + 수동 → 플래그."""
        result = c11_reversal_entry(reversal_pair_df, score_threshold=0.3)
        # D001, D002는 S1(1:1 매칭) + S4(키워드 "수정") + S3(manual 가중)
        assert result.iloc[0] or result.iloc[1], "역분개 쌍 중 최소 하나는 플래그"

    def test_normal_entries_not_flagged(self) -> None:
        """역분개 없는 정상 전표 → 미플래그."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002", "D003"],
            "gl_account": ["1000", "2000", "3000"],
            "debit_amount": [100.0, 200.0, 300.0],
            "credit_amount": [0.0, 0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-06-01", "2025-06-02", "2025-06-03"]),
            "source": ["automated", "automated", "automated"],
            "line_text": ["매출", "재료비", "투자"],
        })
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_keyword_only_without_amount_match_not_flagged(self) -> None:
        """S1/S2 매칭 없이 키워드+수동+기말만으로는 플래그 불가 (필수 전제 조건)."""
        df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "2000"],
            "debit_amount": [100.0, 200.0],
            "credit_amount": [0.0, 0.0],
            "posting_date": pd.to_datetime(["2025-12-25", "2025-12-26"]),
            "source": ["manual", "manual"],
            "line_text": ["수정 전표", "역분개 처리"],
        })
        result = c11_reversal_entry(df, score_threshold=0.3)
        assert not result.any(), "금액적 매칭(S1/S2) 없이는 역분개 플래그 불가"

    def test_missing_core_columns_returns_false(self) -> None:
        """핵심 컬럼 누락 → 전원 False."""
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [0.0],
        })
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_single_row_returns_false(self) -> None:
        """1행 → 매칭 불가 → 전원 False."""
        df = pd.DataFrame({
            "document_id": ["D001"],
            "gl_account": ["1000"],
            "debit_amount": [100.0],
            "credit_amount": [0.0],
            "posting_date": pd.to_datetime(["2025-06-01"]),
        })
        result = c11_reversal_entry(df)
        assert not result.any()

    def test_period_end_boost_increases_score(self) -> None:
        """기말 역분개는 점수가 높아져서 더 쉽게 플래그."""
        # Why: 동일 역분개 쌍이지만 12월 말 vs 6월로 점수 차이 확인
        base_df = pd.DataFrame({
            "document_id": ["D001", "D002"],
            "gl_account": ["1000", "1000"],
            "debit_amount": [1_000_000.0, 0.0],
            "credit_amount": [0.0, 1_000_000.0],
            "posting_date": pd.to_datetime(["2025-06-15", "2025-06-16"]),
            "source": ["manual", "manual"],
            "line_text": ["매출", "매출 수정"],
        })
        yearend_df = base_df.copy()
        yearend_df["posting_date"] = pd.to_datetime(["2025-12-25", "2025-12-26"])

        # Why: 기말 부스트로 더 많이/쉽게 플래그되는지 확인
        result_mid = c11_reversal_entry(base_df, score_threshold=0.5)
        result_end = c11_reversal_entry(yearend_df, score_threshold=0.5)
        # 기말은 ×1.5이므로 임계값 0.5에서도 플래그 가능성 높음
        midyear_flagged = result_mid.sum()
        yearend_flagged = result_end.sum()
        assert yearend_flagged >= midyear_flagged, "기말 역분개가 더 많이 플래그되어야 함"
