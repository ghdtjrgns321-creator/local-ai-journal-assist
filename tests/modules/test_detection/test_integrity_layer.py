"""IntegrityDetector 단위·통합 테스트 — L1-01, L1-02, L1-03."""

from __future__ import annotations

import pandas as pd
import pytest

from src.detection.base import DetectionResult
from src.detection.integrity_layer import IntegrityDetector

# ── L1-01: 차대변 균형 ──────────────────────────────────────────


class TestA01UnbalancedEntry:
    """L1-01 차대변 균형 검사."""

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
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D2"],
                "debit_amount": [100.0, 0.0, 100.0, 0.0],
                "credit_amount": [0.0, 99.0, 0.0, 98.99],
                "gl_account": [1000, 2000, 1000, 2000],
                "company_code": ["C1"] * 4,
                "fiscal_year": [2025] * 4,
                "posting_date": pd.to_datetime(["2025-01-01"] * 4),
                "document_date": pd.to_datetime(["2025-01-01"] * 4),
                "document_type": ["SA"] * 4,
            }
        )
        detector = IntegrityDetector(tolerance=1.0)
        result = detector.detect(df)

        # D1: diff=1.0 → tolerance 이하, 미플래그
        assert result.scores.iloc[0] == 0.0
        # D2: diff=1.01 → tolerance 초과, 플래그
        assert result.scores.iloc[2] > 0.0

    def test_flagged_rows_have_uniform_score_and_sort_annotations(self):
        """L1-01 keeps only uniform data-integrity score plus sorting fields."""
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1", "D2", "D2", "D3", "D3"],
                "debit_amount": [100_000.0, 0.0, 100_000.0, 0.0, 100_000.0, 0.0],
                "credit_amount": [0.0, 99_950.0, 0.0, 99_000.0, 0.0, 50_000.0],
                "gl_account": [1000, 2000, 1000, 2000, 1000, 2000],
                "company_code": ["C1"] * 6,
                "fiscal_year": [2025] * 6,
                "posting_date": pd.to_datetime(["2025-01-01"] * 6),
                "document_date": pd.to_datetime(["2025-01-01"] * 6),
                "document_type": ["SA"] * 6,
            }
        )
        detector = IntegrityDetector(tolerance=1.0)
        result = detector.detect(df)

        assert result.details["L1-01"].iloc[[0, 2, 4]].tolist() == pytest.approx(
            [1.0, 1.0, 1.0]
        )
        annotations = result.metadata["row_annotations"]["L1-01"]
        assert annotations[0] == {
            "imbalance_amount": pytest.approx(50.0),
            "debit_sum": pytest.approx(100_000.0),
            "credit_sum": pytest.approx(99_950.0),
        }
        assert "bucket" not in annotations[0]
        assert "score" not in annotations[0]

    def test_nan_debit_treated_as_zero(self):
        """debit NaN → fillna(0) 처리."""
        df = pd.DataFrame(
            {
                "document_id": ["D1", "D1"],
                "debit_amount": [float("nan"), 0.0],
                "credit_amount": [0.0, 100.0],
                "gl_account": [1000, 2000],
                "company_code": ["C1"] * 2,
                "fiscal_year": [2025] * 2,
                "posting_date": pd.to_datetime(["2025-01-01"] * 2),
                "document_date": pd.to_datetime(["2025-01-01"] * 2),
                "document_type": ["SA"] * 2,
            }
        )
        detector = IntegrityDetector()
        result = detector.detect(df)
        # diff = (0-0) + (0-100) = -100 → 플래그
        assert result.scores.iloc[0] > 0.0

    def test_nan_document_id_individual_rows(self):
        """NaN document_id → 각 행이 개별 취급 (합산 방지)."""
        df = pd.DataFrame(
            {
                "document_id": [None, None, "D1", "D1"],
                "debit_amount": [100.0, 200.0, 50.0, 0.0],
                "credit_amount": [0.0, 0.0, 0.0, 50.0],
                "gl_account": [1000, 2000, 1000, 2000],
                "company_code": ["C1"] * 4,
                "fiscal_year": [2025] * 4,
                "posting_date": pd.to_datetime(["2025-01-01"] * 4),
                "document_date": pd.to_datetime(["2025-01-01"] * 4),
                "document_type": ["SA"] * 4,
            }
        )
        detector = IntegrityDetector()
        result = detector.detect(df)

        # NaN 행들은 각각 독립 — 단일 라인 diff > tolerance면 플래그
        assert result.scores.iloc[0] > 0.0  # 100-0=100 > 1.0
        assert result.scores.iloc[1] > 0.0  # 200-0=200 > 1.0
        # D1은 균형
        assert result.scores.iloc[2] == 0.0

    def test_no_document_id_skips(self):
        """document_id 컬럼 없는 DF → L1-01 skipped."""
        df = pd.DataFrame(
            {
                "debit_amount": [100.0],
                "credit_amount": [100.0],
                "gl_account": [1000],
                "company_code": ["C1"],
                "fiscal_year": [2025],
                "posting_date": pd.to_datetime(["2025-01-01"]),
                "document_date": pd.to_datetime(["2025-01-01"]),
                "document_type": ["SA"],
            }
        )
        detector = IntegrityDetector()
        result = detector.detect(df)
        assert "L1-01" in result.metadata["skipped_rules"]


# ── L1-02: 필수필드 누락 ────────────────────────────────────────


class TestA02MissingRequired:
    """L1-02 필수필드 누락 검사."""

    def test_no_nulls_all_zero(self, dt_balanced_df):
        """필수 필드 모두 채움 → 0.0."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        # L1-02 uses uniform data-integrity scores when flagged.
        a02_scores = result.details.get("L1-02", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a02_scores == 0.0).all()

    def test_null_gl_account_flagged(self, dt_missing_fields_df):
        """gl_account NULL → 해당 행 플래그."""
        detector = IntegrityDetector()
        result = detector.detect(dt_missing_fields_df)
        # idx 1: gl_account=None → L1-02 플래그
        assert result.details["L1-02"].iloc[1] > 0.0
        # idx 0: 정상
        assert result.details["L1-02"].iloc[0] == 0.0

    def test_multiple_nulls_keep_uniform_score(self, dt_missing_fields_df):
        """Multiple missing required fields do not change the uniform score."""
        detector = IntegrityDetector()
        single = dt_missing_fields_df.copy()
        single.loc[1, "posting_date"] = pd.Timestamp("2025-01-02")

        single_result = detector.detect(single)
        multi_result = detector.detect(dt_missing_fields_df)
        assert single_result.details["L1-02"].iloc[1] == pytest.approx(1.0)
        assert multi_result.details["L1-02"].iloc[1] == pytest.approx(1.0)

    def test_missing_field_category_tags_cat1_before_cat2(self, dt_missing_fields_df):
        cat2 = dt_missing_fields_df.copy()
        cat1 = dt_missing_fields_df.copy()
        cat2.loc[1, ["gl_account", "posting_date"]] = [2000, pd.Timestamp("2025-01-02")]
        cat1.loc[1, ["gl_account", "posting_date"]] = [2000, pd.Timestamp("2025-01-02")]
        cat2.loc[1, "document_date"] = pd.NaT
        cat1.loc[1, "document_id"] = None

        detector = IntegrityDetector()
        cat2_result = detector.detect(cat2)
        cat1_result = detector.detect(cat1)

        assert cat2_result.details["L1-02"].iloc[1] == pytest.approx(1.0)
        assert cat1_result.details["L1-02"].iloc[1] == pytest.approx(1.0)
        assert cat2_result.metadata["row_annotations"]["L1-02"][1]["missing_category"] == 2
        assert cat1_result.metadata["row_annotations"]["L1-02"][1]["missing_category"] == 1

    def test_blank_string_required_field_counts_as_missing(self, dt_missing_fields_df):
        df = dt_missing_fields_df.copy()
        df.loc[1, ["gl_account", "posting_date"]] = [2000, pd.Timestamp("2025-01-02")]
        df.loc[1, "document_type"] = "  "

        result = IntegrityDetector().detect(df)

        assert result.details["L1-02"].iloc[1] == pytest.approx(1.0)
        annotation = result.metadata["row_annotations"]["L1-02"][1]
        assert annotation["missing_fields"] == ["document_type"]
        assert annotation["missing_category"] == 2


# ── L1-03: 무효 계정 ────────────────────────────────────────────


class TestA03InvalidAccount:
    """L1-03 무효 계정 검사."""

    def test_valid_accounts_not_flagged(self, dt_balanced_df, dt_coa):
        """CoA에 있는 계정 → 0.0."""
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(dt_balanced_df)
        a03_scores = result.details.get("L1-03", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a03_scores == 0.0).all()

    def test_invalid_account_scores_are_uniform(self, dt_balanced_df):
        """L1-03 no longer separates account quality buckets."""
        df = pd.concat([dt_balanced_df.iloc[[0]]] * 4, ignore_index=True)
        df["document_id"] = ["D1", "D2", "D3", "D4"]
        df["gl_account"] = ["1999", "9000", "ABC", "9999"]
        detector = IntegrityDetector(chart_of_accounts={"1000", "2000"})
        result = detector.detect(df)

        assert result.details["L1-03"].tolist() == pytest.approx([1.0, 1.0, 1.0, 1.0])
        annotations = result.metadata["row_annotations"]["L1-03"]
        assert annotations[0] == {"gl_account": "1999"}
        assert annotations[1] == {"gl_account": "9000"}
        assert annotations[2] == {"gl_account": "ABC"}
        assert annotations[3] == {"gl_account": "9999"}
        assert "score_bands" not in result.metadata["rule_breakdowns"]["L1-03"]

    def test_invalid_account_context_does_not_change_score(self, dt_balanced_df):
        """High amount/manual/period-end context does not alter L1-03 score."""
        df = pd.concat([dt_balanced_df.iloc[[0]]] * 3, ignore_index=True)
        df["document_id"] = ["D1", "D2", "D3"]
        df["gl_account"] = ["1999", "9999", "9999"]
        df["debit_amount"] = [10.0, 20.0, 1_000_000.0]
        df["credit_amount"] = [0.0, 0.0, 0.0]
        df["source"] = ["system", "system", "manual"]
        df["posting_date"] = pd.to_datetime(["2025-01-10", "2025-01-10", "2025-01-31"])

        detector = IntegrityDetector(chart_of_accounts={"1000", "2000"})
        result = detector.detect(df)

        assert result.details["L1-03"].iloc[0] == pytest.approx(1.0)
        assert result.details["L1-03"].iloc[2] == pytest.approx(1.0)
        annotations = result.metadata["row_annotations"]["L1-03"]
        assert annotations[2] == {"gl_account": "9999"}

    def test_invalid_account_flagged(self, dt_balanced_df, dt_coa):
        """CoA에 없는 계정 → 플래그."""
        # gl_account 9999는 CoA에 없음
        df = dt_balanced_df.copy()
        df.loc[0, "gl_account"] = 1999
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(df)
        assert result.details["L1-03"].iloc[0] == pytest.approx(1.0)

    def test_no_coa_skips_with_warning(self, dt_balanced_df):
        """CoA=None + settings 경로 비활성 → L1-03 skipped."""
        from config.settings import AuditSettings

        settings = AuditSettings(chart_of_accounts_path="")
        detector = IntegrityDetector(settings=settings, chart_of_accounts=None)
        result = detector.detect(dt_balanced_df)
        assert "L1-03" in result.metadata["skipped_rules"]

    def test_int_str_type_mismatch(self, dt_balanced_df, dt_coa):
        """gl_account=1000(int), CoA={"1000"}(str) → 정상 매칭."""
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(dt_balanced_df)
        a03_scores = result.details.get("L1-03", pd.Series(0.0, index=dt_balanced_df.index))
        assert (a03_scores == 0.0).all()

    # ── 통합 테스트 ────────────────────────────────────────────────

    def test_decimal_string_account_matches_coa(self, dt_balanced_df):
        """CSV ingest의 '.0' 포맷 계정도 CoA와 동일 취급."""
        df = dt_balanced_df.copy()
        df["gl_account"] = ["1000.0", "2000.0", "1000.0", "2000.0"]
        detector = IntegrityDetector(chart_of_accounts={"1000", "2000"})
        result = detector.detect(df)
        a03_scores = result.details.get("L1-03", pd.Series(0.0, index=df.index))
        assert (a03_scores == 0.0).all()

    def test_decimal_string_invalid_account_still_flagged(self, dt_balanced_df):
        """정규화 이후에도 실제 미등록 계정은 계속 검출."""
        df = dt_balanced_df.copy()
        df["gl_account"] = df["gl_account"].astype(object)
        df.loc[0, "gl_account"] = "9999.0"
        detector = IntegrityDetector(chart_of_accounts={"1000", "2000"})
        result = detector.detect(df)
        assert result.details["L1-03"].iloc[0] == pytest.approx(1.0)

    def test_blank_account_is_not_l103(self, dt_balanced_df):
        """빈 계정은 L1-03이 아니라 L1-02에서 처리한다."""
        df = dt_balanced_df.copy()
        df["gl_account"] = df["gl_account"].astype(object)
        df.loc[0, "gl_account"] = None
        detector = IntegrityDetector(chart_of_accounts={"1000", "2000"})
        result = detector.detect(df)
        assert result.details["L1-03"].iloc[0] == 0.0
        assert result.details["L1-02"].iloc[0] > 0.0


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
        # D002 불균형(L1-01) + 9999 무효계정(L1-03) 동시 위반
        df = dt_unbalanced_df.copy()
        df.loc[2, "gl_account"] = 9999
        detector = IntegrityDetector(chart_of_accounts=dt_coa)
        result = detector.detect(df)

        a01_score = 1.0
        a03_score = 1.0
        # idx 2: L1-01+L1-03 동시 위반 → uniform max = 1.0
        assert result.scores.iloc[2] == pytest.approx(max(a01_score, a03_score))

    def test_skipped_rules_in_metadata(self, dt_balanced_df):
        """CoA=None + settings 경로 비활성 → L1-03 skipped, metadata에 기록."""
        from config.settings import AuditSettings

        settings = AuditSettings(chart_of_accounts_path="")
        detector = IntegrityDetector(settings=settings)
        result = detector.detect(dt_balanced_df)
        assert "skipped_rules" in result.metadata
        assert "L1-03" in result.metadata["skipped_rules"]

    def test_elapsed_in_metadata(self, dt_balanced_df):
        """elapsed 시간 기록."""
        detector = IntegrityDetector()
        result = detector.detect(dt_balanced_df)
        assert result.metadata["elapsed"] >= 0

    def test_empty_df_raises(self):
        """빈 DF → ValueError."""
        detector = IntegrityDetector()
        with pytest.raises(ValueError, match="empty"):
            detector.detect(pd.DataFrame())
