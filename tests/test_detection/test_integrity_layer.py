"""IntegrityDetector 단위·통합 테스트 — A01, A02, A03."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.constants import SEVERITY_MAP
from src.detection.integrity_layer import IntegrityDetector


# ── A01: 차대변 균형 ──────────────────────────────────────────


class TestA01UnbalancedEntry:
    """A01 차대변 균형 검사."""

    def test_balanced_all_zero_scores(self, dt_balanced_df):
        """균형 전표 → 모든 score = 0."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        assert (result.scores == 0.0).all()

    def test_unbalanced_flags_all_lines(self, dt_unbalanced_df):
        """D002 불균형 → D002의 2개 라인(idx 2, 3) 모두 플래그."""
        detector = IntegrityDetector()
        result = detector.detect(dt_unbalanced_df)

        # D002 행(idx 2, 3)만 플래그
        assert 2 in result.flagged_indices
        assert 3 in result.flagged_indices
        # D001 행(idx 0, 1)은 미플래그
        assert 0 not in result.flagged_indices
        assert 1 not in result.flagged_indices

    def test_tolerance_boundary(self):
        """diff=1.0 → 미플래그, diff=1.01 → 플래그."""
        df = pd.DataFrame({
            "document_id": ["D1", "D1", "D2", "D2"],
            "debit_amount": [100.0, 0.0, 100.0, 0.0],
            "credit_amount": [0.0, 99.0, 0.0, 98.99],
            "gl_account": [1000, 2000, 1000, 2000],
            "company_code": ["C1"] * 4,
            "fiscal_year": [2025] * 4,
            "posting_date": pd.to_datetime(["2025-01-01"] * 4),
            "document_date": pd.to_datetime(["2025-01-01"] * 4),
            "document_type": ["SA"] * 4,
        })
        detector = IntegrityDetector(tolerance=1.0)
        result = detector.detect(df)

        # D1: diff=1.0 → tolerance 이하, 미플래그
        assert result.scores.iloc[0] == 0.0
        # D2: diff=1.01 → tolerance 초과, 플래그
        assert result.scores.iloc[2] > 0.0

    def test_nan_debit_treated_as_zero(self):
        """debit NaN → fillna(0) 처리."""
        df = pd.DataFrame({
            "document_id": ["D1", "D1"],
            "debit_amount": [float("nan"), 0.0],
            "credit_amount": [0.0, 100.0],
            "gl_account": [1000, 2000],
            "company_code": ["C1"] * 2,
            "fiscal_year": [2025] * 2,
            "posting_date": pd.to_datetime(["2025-01-01"] * 2),
            "document_date": pd.to_datetime(["2025-01-01"] * 2),
            "document_type": ["SA"] * 2,
        })
        detector = IntegrityDetector()
        result = detector.detect(df)
        # diff = (0-0) + (0-100) = -100 → 플래그
        assert result.scores.iloc[0] > 0.0

    def test_nan_document_id_individual_rows(self):
        """NaN document_id → 각 행이 개별 취급 (합산 방지)."""
        df = pd.DataFrame({
            "document_id": [None, None, "D1", "D1"],
            "debit_amount": [100.0, 200.0, 50.0, 0.0],
            "credit_amount": [0.0, 0.0, 0.0, 50.0],
            "gl_account": [1000, 2000, 1000, 2000],
            "company_code": ["C1"] * 4,
            "fiscal_year": [2025] * 4,
            "posting_date": pd.to_datetime(["2025-01-01"] * 4),
            "document_date": pd.to_datetime(["2025-01-01"] * 4),
            "document_type": ["SA"] * 4,
        })
        detector = IntegrityDetector()
        result = detector.detect(df)

        # NaN 행들은 각각 독립 — 단일 라인 diff > tolerance면 플래그
        assert result.scores.iloc[0] > 0.0  # 100-0=100 > 1.0
        assert result.scores.iloc[1] > 0.0  # 200-0=200 > 1.0
        # D1은 균형
        assert result.scores.iloc[2] == 0.0

    def test_no_document_id_skips(self):
        """document_id 컬럼 없는 DF → A01 skipped."""
        df = pd.DataFrame({
            "debit_amount": [100.0],
            "credit_amount": [100.0],
            "gl_account": [1000],
            "company_code": ["C1"],
            "fiscal_year": [2025],
            "posting_date": pd.to_datetime(["2025-01-01"]),
            "document_date": pd.to_datetime(["2025-01-01"]),
            "document_type": ["SA"],
        })
        detector = IntegrityDetector()
        result = detector.detect(df)
        assert "A01" in result.metadata["skipped_rules"]


# ── A02: 필수필드 누락 ────────────────────────────────────────


class TestA02MissingRequired:
    """A02 필수필드 누락 검사."""

    def test_no_nulls_all_zero(self, dt_balanced_df):
        """필수 필드 모두 채움 → 0.0."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        # A02 score (severity=2 → 2/5=0.4 if flagged)
        a02_scores = result.details.get("A02", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a02_scores == 0.0).all()

    def test_null_gl_account_flagged(self, dt_missing_fields_df):
        """gl_account NULL → 해당 행 플래그."""
        detector = IntegrityDetector()
        result = detector.detect(dt_missing_fields_df)
        # idx 1: gl_account=None → A02 플래그
        assert result.details["A02"].iloc[1] > 0.0
        # idx 0: 정상
        assert result.details["A02"].iloc[0] == 0.0

    def test_multiple_nulls_still_binary(self, dt_missing_fields_df):
        """여러 필수 필드 NULL도 binary (0.0 또는 severity/5)."""
        detector = IntegrityDetector()
        result = detector.detect(dt_missing_fields_df)
        expected_score = SEVERITY_MAP["A02"] / 5
        # idx 1: posting_date NaT + gl_account None → 여전히 단일 score
        assert result.details["A02"].iloc[1] == pytest.approx(expected_score)


# ── A03: 무효 계정 ────────────────────────────────────────────


class TestA03InvalidAccount:
    """A03 무효 계정 검사."""

    def test_valid_accounts_not_flagged(self, dt_balanced_df, dt_coa):
        """CoA에 있는 계정 → 0.0."""
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(dt_balanced_df)
        a03_scores = result.details.get("A03", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a03_scores == 0.0).all()

    def test_invalid_account_flagged(self, dt_balanced_df, dt_coa):
        """CoA에 없는 계정 → 플래그."""
        # gl_account 9999는 CoA에 없음
        df = dt_balanced_df.copy()
        df.loc[0, "gl_account"] = 9999
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(df)
        expected_score = SEVERITY_MAP["A03"] / 5
        assert result.details["A03"].iloc[0] == pytest.approx(expected_score)

    def test_no_coa_skips_with_warning(self, dt_balanced_df):
        """CoA=None → A03 skipped."""
        detector = IntegrityDetector(chart_of_accounts=None)
        result = detector.detect(dt_balanced_df)
        assert "A03" in result.metadata["skipped_rules"]

    def test_int_str_type_mismatch(self, dt_balanced_df, dt_coa):
        """gl_account=1000(int), CoA={"1000"}(str) → 정상 매칭."""
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(dt_balanced_df)
        a03_scores = result.details.get("A03", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a03_scores == 0.0).all()


# ── 통합 테스트 ────────────────────────────────────────────────


class TestDetectIntegration:
    """detect() 오케스트레이션 통합 테스트."""

    def test_detect_returns_detection_result(self, dt_balanced_df):
        """반환 타입 = DetectionResult."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        assert isinstance(result, DetectionResult)
        assert result.track_name == "layer_a"

    def test_scores_max_of_rules(self, dt_unbalanced_df, dt_coa):
        """여러 룰 위반 시 max score 적용."""
        # D002 불균형(A01) + 9999 무효계정(A03) 동시 위반
        df = dt_unbalanced_df.copy()
        df.loc[2, "gl_account"] = 9999
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(df)

        a01_score = SEVERITY_MAP["A01"] / 5  # 1.0
        a03_score = SEVERITY_MAP["A03"] / 5  # 0.6
        # idx 2: A01+A03 동시 위반 → max(1.0, 0.6) = 1.0
        assert result.scores.iloc[2] == pytest.approx(max(a01_score, a03_score))

    def test_skipped_rules_in_metadata(self, dt_balanced_df):
        """CoA=None → A03 skipped, metadata에 기록."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        assert "skipped_rules" in result.metadata
        assert "A03" in result.metadata["skipped_rules"]

    def test_elapsed_in_metadata(self, dt_balanced_df):
        """elapsed 시간 기록."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        assert result.metadata["elapsed"] >= 0

    def test_empty_df_raises(self):
        """빈 DF → ValueError."""
        detector = IntegrityDetector()
        with pytest.raises(ValueError, match="비어"):
            detector.detect(pd.DataFrame())
