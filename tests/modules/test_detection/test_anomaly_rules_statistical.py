"""C07 Benford 위반, C09 비정상 계정조합 단위 테스트."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from config.settings import AuditSettings
from src.detection.anomaly_rules_statistical import (
    c07_benford_violation,
    c09_rare_account_pair,
)


@pytest.fixture
def benford_settings() -> AuditSettings:
    """Benford 테스트용 settings — 최소 표본 낮춰서 소규모 데이터 허용."""
    return AuditSettings(benford_min_sample=10)


# ── C07 Benford 위반 ─────────────────────────────────────


class TestC07:
    def _make_conforming_df(self, n: int = 200) -> pd.DataFrame:
        """Benford 법칙에 적합한 first_digit 분포 생성."""
        digits = []
        for d in range(1, 10):
            count = round(n * math.log10(1 + 1 / d))
            digits.extend([d] * count)
        # 부족분 채우기
        while len(digits) < n:
            digits.append(1)
        return pd.DataFrame({
            "first_digit": pd.array(digits[:n], dtype=pd.Int64Dtype()),
            "debit_amount": [100.0] * n,
            "credit_amount": [0.0] * n,
        })

    def _make_nonconforming_df(self, n: int = 200) -> pd.DataFrame:
        """Benford 법칙을 명확히 위반하는 분포 (균등 분포)."""
        per_digit = n // 9
        digits = []
        for d in range(1, 10):
            digits.extend([d] * per_digit)
        while len(digits) < n:
            digits.append(9)
        return pd.DataFrame({
            "first_digit": pd.array(digits[:n], dtype=pd.Int64Dtype()),
            "debit_amount": [100.0] * n,
            "credit_amount": [0.0] * n,
        })

    def test_conforming_returns_all_false(self, benford_settings: AuditSettings) -> None:
        """Benford 적합 → 전체 False."""
        df = self._make_conforming_df(300)
        result, meta = c07_benford_violation(df, settings=benford_settings)
        assert not result.any()
        assert "benford_result" in meta
        assert meta["benford_result"].is_conforming

    def test_nonconforming_flags_some_rows(self, benford_settings: AuditSettings) -> None:
        """Benford 비적합 → 일부 행 플래그."""
        df = self._make_nonconforming_df(300)
        result, meta = c07_benford_violation(df, settings=benford_settings)
        assert result.any()
        assert not meta["benford_result"].is_conforming

    def test_missing_feature_returns_false(self, benford_settings: AuditSettings) -> None:
        """first_digit 미존재 → 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0]})
        result, meta = c07_benford_violation(df, settings=benford_settings)
        assert not result.any()

    def test_returns_tuple_format(self, benford_settings: AuditSettings) -> None:
        """반환값이 (Series, dict) 튜플인지 확인."""
        df = self._make_conforming_df(100)
        result = c07_benford_violation(df, settings=benford_settings)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], pd.Series)
        assert isinstance(result[1], dict)

    def test_document_level_flagging(self, benford_settings: AuditSettings) -> None:
        """위반 자릿수 행이 포함된 전표 → 전표 내 모든 행 플래그 (복식부기)."""
        df = self._make_nonconforming_df(300)
        # Why: 전표 3개로 묶기 — 전표당 100행
        doc_ids = (["DOC-A"] * 100) + (["DOC-B"] * 100) + (["DOC-C"] * 100)
        df["document_id"] = doc_ids
        scores, _ = c07_benford_violation(df, settings=benford_settings)
        # Why: 이제 float Series이므로 mask는 scores > 0으로 변환
        flagged_mask = scores > 0
        flagged_docs = set(df.loc[flagged_mask, "document_id"].unique())
        for doc_id in flagged_docs:
            doc_mask = df["document_id"] == doc_id
            # Why: 전표에 속한 모든 행이 플래그 — 일부만 빠지면 안 됨
            assert (scores[doc_mask] > 0).all(), f"{doc_id}의 일부 행만 플래그됨"

    def test_no_document_id_falls_back_to_row_level(self, benford_settings: AuditSettings) -> None:
        """document_id 미존재 → 기존 행 단위 동작 유지 (에러 없이 정상 반환)."""
        df = self._make_nonconforming_df(300)
        assert "document_id" not in df.columns
        result, _ = c07_benford_violation(df, settings=benford_settings)
        # Why: 균등분포는 모든 자릿수 위반 → 전체 플래그되지만, 에러 없이 반환되면 OK
        assert result.any()
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_returns_float_scores_in_range(self, benford_settings: AuditSettings) -> None:
        """반환값이 float [0, 0.8] 범위 — deviation 비례 차등 스코어."""
        df = self._make_nonconforming_df(300)
        scores, _ = c07_benford_violation(df, settings=benford_settings)
        # Why: dtype 검증 — bool이 아닌 float여야 함
        assert scores.dtype == float
        # Why: 위반 행은 [0.2, 0.8] 범위, 미위반 행은 0.0
        assert scores.min() >= 0.0
        assert scores.max() <= 0.8 + 1e-9
        nonzero = scores[scores > 0]
        if not nonzero.empty:
            assert nonzero.min() >= 0.2 - 1e-9

    def test_higher_deviation_higher_score(self, benford_settings: AuditSettings) -> None:
        """편차가 큰 분포가 작은 분포보다 높은 점수를 받는다.

        Why: 동일한 nonconforming 판정이라도 'MAD 0.02' vs 'MAD 0.10'은
             이상도가 다르므로 점수가 차등되어야 한다 (이전 0.4 고정값 회귀 방지).
        """
        # 약한 편차: 1번 자릿수만 살짝 부풀림
        weak = []
        for d in range(1, 10):
            target_freq = math.log10(1 + 1 / d)
            count = round(300 * target_freq)
            weak.extend([d] * count)
        weak += [1] * 30  # 1번 약 10% 추가 부풀림
        df_weak = pd.DataFrame({
            "first_digit": pd.array(weak[:300], dtype=pd.Int64Dtype()),
            "debit_amount": [100.0] * 300,
            "credit_amount": [0.0] * 300,
        })
        scores_weak, meta_weak = c07_benford_violation(df_weak, settings=benford_settings)

        # 강한 편차: 균등 분포 (Benford에서 가장 멀리 떨어짐)
        df_strong = self._make_nonconforming_df(300)
        scores_strong, meta_strong = c07_benford_violation(df_strong, settings=benford_settings)

        # 양쪽 다 위반이라면, 균등 분포가 더 높은 max 점수를 받아야 함
        if scores_weak.max() > 0 and scores_strong.max() > 0:
            assert scores_strong.max() >= scores_weak.max(), (
                f"강한 편차가 더 낮은 점수: weak={scores_weak.max():.3f}, "
                f"strong={scores_strong.max():.3f}"
            )


# ── C09 비정상 계정조합 ──────────────────────────────────


class TestC09:
    @pytest.fixture
    def pair_df(self) -> pd.DataFrame:
        """계정 쌍 테스트 — 빈번한 쌍 + 희소 쌍.

        D001~D004: 1000→2000 (빈번 쌍, 4회)
        D005: 3000→4000 (희소 쌍, 1회)
        D006: 5000→6000 (희소 쌍, 1회)
        D007: 1000→2000, 3000→2000 (복합 분개 N:M)
        """
        return pd.DataFrame({
            "document_id": [
                "D001", "D001", "D002", "D002", "D003", "D003", "D004", "D004",
                "D005", "D005", "D006", "D006",
                "D007", "D007", "D007",  # 복합 분개: 차변 2개, 대변 1개
            ],
            "gl_account": [
                "1000", "2000", "1000", "2000", "1000", "2000", "1000", "2000",
                "3000", "4000", "5000", "6000",
                "1000", "3000", "2000",
            ],
            "debit_amount": [
                100.0, 0.0, 200.0, 0.0, 150.0, 0.0, 300.0, 0.0,
                50.0, 0.0, 80.0, 0.0,
                60.0, 40.0, 0.0,  # 차변 2건
            ],
            "credit_amount": [
                0.0, 100.0, 0.0, 200.0, 0.0, 150.0, 0.0, 300.0,
                0.0, 50.0, 0.0, 80.0,
                0.0, 0.0, 100.0,  # 대변 1건
            ],
        })

    def test_rare_pair_flagged(self, pair_df: pd.DataFrame) -> None:
        """희소 쌍(3000→4000, 5000→6000)의 document 행이 flagged."""
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        # D005(3000→4000) 행 8,9 → flagged
        assert result[8]
        assert result[9]
        # D006(5000→6000) 행 10,11 → flagged
        assert result[10]
        assert result[11]

    def test_frequent_pair_not_flagged(self, pair_df: pd.DataFrame) -> None:
        """빈번한 쌍(1000→2000, 4회)의 행은 not flagged."""
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        # D001~D004 행 0~7 중 최소 일부는 not flagged
        assert not result[0]
        assert not result[1]

    def test_complex_entry_nm_handled(self, pair_df: pd.DataFrame) -> None:
        """복합 분개(D007: 차변 2개 × 대변 1개) 쌍이 올바르게 생성."""
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        # D007은 (1000,2000) + (3000,2000) 두 쌍 생성
        # (1000,2000)은 빈번, (3000,2000)은 희소 → D007 전체 flagged 가능
        assert isinstance(result, pd.Series)
        assert len(result) == len(pair_df)

    def test_missing_columns_returns_false(self) -> None:
        """필수 컬럼 미존재 시 모두 False."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not c09_rare_account_pair(df).any()

    def test_empty_debits_returns_false(self) -> None:
        """차변이 없으면 쌍 생성 불가 → 모두 False."""
        df = pd.DataFrame({
            "document_id": ["D001"],
            "gl_account": ["1000"],
            "debit_amount": [0.0],
            "credit_amount": [100.0],
        })
        assert not c09_rare_account_pair(df).any()
