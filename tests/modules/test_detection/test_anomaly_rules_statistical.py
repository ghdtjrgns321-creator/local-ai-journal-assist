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
