"""Tests for statistical anomaly rules: L4-02 Benford and L4-04 rare pairs."""

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
    return AuditSettings(benford_min_sample=10)


class TestL4_02:
    def _make_conforming_df(self, n: int = 200) -> pd.DataFrame:
        digits: list[int] = []
        for digit in range(1, 10):
            count = round(n * math.log10(1 + 1 / digit))
            digits.extend([digit] * count)
        while len(digits) < n:
            digits.append(1)
        return pd.DataFrame({
            "first_digit": pd.array(digits[:n], dtype=pd.Int64Dtype()),
            "company_code": ["C01"] * n,
            "gl_account": ["1000"] * n,
            "debit_amount": [100.0] * n,
            "credit_amount": [0.0] * n,
        })

    def _make_nonconforming_df(self, n: int = 200) -> pd.DataFrame:
        per_digit = n // 9
        digits: list[int] = []
        for digit in range(1, 10):
            digits.extend([digit] * per_digit)
        while len(digits) < n:
            digits.append(9)
        return pd.DataFrame({
            "first_digit": pd.array(digits[:n], dtype=pd.Int64Dtype()),
            "company_code": ["C01"] * n,
            "gl_account": ["1000"] * n,
            "debit_amount": [100.0] * n,
            "credit_amount": [0.0] * n,
        })

    def test_conforming_returns_all_false(self, benford_settings: AuditSettings) -> None:
        df = self._make_conforming_df(300)
        result, meta = c07_benford_violation(df, settings=benford_settings)
        assert not result.any()
        assert "benford_result" in meta
        assert meta["benford_result"].is_conforming

    def test_nonconforming_returns_drilldown_candidates(
        self,
        benford_settings: AuditSettings,
    ) -> None:
        df = self._make_nonconforming_df(600)
        result, meta = c07_benford_violation(df, settings=benford_settings)
        assert result.any()
        assert not meta["benford_result"].is_conforming
        assert meta["benford_findings"]

    def test_missing_feature_returns_false(self, benford_settings: AuditSettings) -> None:
        df = pd.DataFrame({"debit_amount": [100.0]})
        result, _meta = c07_benford_violation(df, settings=benford_settings)
        assert not result.any()

    def test_returns_tuple_format(self, benford_settings: AuditSettings) -> None:
        df = self._make_conforming_df(100)
        result = c07_benford_violation(df, settings=benford_settings)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], pd.Series)
        assert isinstance(result[1], dict)

    def test_no_document_level_propagation(self, benford_settings: AuditSettings) -> None:
        digits = 2 * (
            ([1] * 110)
            + ([2] * 50)
            + ([3] * 37)
            + ([4] * 29)
            + ([5] * 24)
            + ([6] * 20)
            + ([7] * 15)
            + ([8] * 9)
            + ([9] * 6)
        )
        df = pd.DataFrame({
            "first_digit": pd.array(digits, dtype=pd.Int64Dtype()),
            "company_code": ["C01"] * 600,
            "gl_account": ["1000"] * 600,
            "document_id": [f"DOC-{i % 3}" for i in range(600)],
            "debit_amount": [100.0] * 600,
            "credit_amount": [0.0] * 600,
        })

        scores, _meta = c07_benford_violation(df, settings=benford_settings)

        flagged_mask = scores > 0
        assert flagged_mask.any()
        assert not flagged_mask.all()
        flagged_docs = df.loc[flagged_mask, "document_id"].unique()
        assert len(flagged_docs) > 0
        assert not (scores[df["document_id"] == flagged_docs[0]] > 0).all()

    def test_no_document_id_still_returns_row_indexed_scores(
        self,
        benford_settings: AuditSettings,
    ) -> None:
        df = self._make_nonconforming_df(600)
        assert "document_id" not in df.columns
        result, _meta = c07_benford_violation(df, settings=benford_settings)
        assert result.any()
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_returns_float_scores_in_range(self, benford_settings: AuditSettings) -> None:
        df = self._make_nonconforming_df(600)
        scores, _meta = c07_benford_violation(df, settings=benford_settings)
        assert scores.dtype == float
        assert scores.min() >= 0.0
        assert scores.max() <= 0.8 + 1e-9
        nonzero = scores[scores > 0]
        if not nonzero.empty:
            assert nonzero.min() >= 0.2 - 1e-9

    def test_higher_deviation_higher_score(self, benford_settings: AuditSettings) -> None:
        weak: list[int] = []
        n = 600
        for digit in range(1, 10):
            target_freq = math.log10(1 + 1 / digit)
            count = round(n * target_freq)
            weak.extend([digit] * count)
        weak += [1] * 60
        df_weak = pd.DataFrame({
            "first_digit": pd.array(weak[:n], dtype=pd.Int64Dtype()),
            "company_code": ["C01"] * n,
            "gl_account": ["1000"] * n,
            "debit_amount": [100.0] * n,
            "credit_amount": [0.0] * n,
        })
        scores_weak, _meta_weak = c07_benford_violation(df_weak, settings=benford_settings)

        df_strong = self._make_nonconforming_df(n)
        scores_strong, _meta_strong = c07_benford_violation(
            df_strong,
            settings=benford_settings,
        )

        if scores_weak.max() > 0 and scores_strong.max() > 0:
            assert scores_strong.max() >= scores_weak.max()

    def test_company_account_finding_metadata(self, benford_settings: AuditSettings) -> None:
        df = self._make_nonconforming_df(600)
        scores, meta = c07_benford_violation(df, settings=benford_settings)

        assert scores.any()
        assert meta["benford_findings"]
        finding = meta["benford_findings"][0]
        assert finding["scope"] == "company_gl_account"
        assert finding["company_code"] == "C01"
        assert finding["gl_account"] == "1000"
        assert finding["finding_severity"] in {"moderate", "strong"}


class TestL4_04:
    @pytest.fixture
    def pair_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "document_id": [
                "D001", "D001", "D002", "D002", "D003", "D003", "D004", "D004",
                "D005", "D005", "D006", "D006",
                "D007", "D007", "D007",
            ],
            "gl_account": [
                "1000", "2000", "1000", "2000", "1000", "2000", "1000", "2000",
                "3000", "4000", "5000", "6000",
                "1000", "3000", "2000",
            ],
            "debit_amount": [
                100.0, 0.0, 200.0, 0.0, 150.0, 0.0, 300.0, 0.0,
                50.0, 0.0, 80.0, 0.0,
                60.0, 40.0, 0.0,
            ],
            "credit_amount": [
                0.0, 100.0, 0.0, 200.0, 0.0, 150.0, 0.0, 300.0,
                0.0, 50.0, 0.0, 80.0,
                0.0, 0.0, 100.0,
            ],
        })

    def test_rare_pair_flagged(self, pair_df: pd.DataFrame) -> None:
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        assert result[8]
        assert result[9]
        assert result[10]
        assert result[11]
        assert result.attrs["score_series"].loc[result].eq(0.40).all()
        assert result.attrs["breakdown"]["rare_pair_review_docs"] == 3
        assert "rare_account_pair" in result.attrs["row_annotations"][8]["reason_codes"]
        assert result.attrs["row_annotations"][8]["sample_pairs"]

    def test_frequent_pair_not_flagged(self, pair_df: pd.DataFrame) -> None:
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        assert not result[0]
        assert not result[1]

    def test_complex_entry_nm_handled(self, pair_df: pd.DataFrame) -> None:
        result = c09_rare_account_pair(pair_df, percentile=0.2)
        assert isinstance(result, pd.Series)
        assert len(result) == len(pair_df)

    def test_missing_columns_returns_false(self) -> None:
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [0.0]})
        assert not c09_rare_account_pair(df).any()

    def test_empty_debits_returns_false(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001"],
            "gl_account": ["1000"],
            "debit_amount": [0.0],
            "credit_amount": [100.0],
        })
        assert not c09_rare_account_pair(df).any()

    def test_null_account_pairs_excluded_from_l404(self) -> None:
        df = pd.DataFrame({
            "document_id": ["D001", "D001", "D002", "D002"],
            "gl_account": [None, "2100", "1000", "2000"],
            "debit_amount": [100.0, 0.0, 100.0, 0.0],
            "credit_amount": [0.0, 100.0, 0.0, 100.0],
        })

        result = c09_rare_account_pair(df)

        assert not result.iloc[0]
        assert not result.iloc[1]
        assert result.attrs["breakdown"]["excluded_null_account_debit_lines"] == 1
        assert result.attrs["breakdown"]["excluded_null_account_document_count"] == 1

    def test_large_document_is_evaluated_with_distinct_account_pairs(self) -> None:
        rows = []
        for i in range(5):
            rows.extend([
                {
                    "document_id": f"D{i}",
                    "gl_account": "1000",
                    "debit_amount": 100.0,
                    "credit_amount": 0.0,
                },
                {
                    "document_id": f"D{i}",
                    "gl_account": "2000",
                    "debit_amount": 0.0,
                    "credit_amount": 100.0,
                },
            ])
        rows.extend(
            {
                "document_id": "D_BIG",
                "gl_account": "9000",
                "debit_amount": 1.0,
                "credit_amount": 0.0,
            }
            for _ in range(101)
        )
        rows.append({
            "document_id": "D_BIG",
            "gl_account": "9999",
            "debit_amount": 0.0,
            "credit_amount": 101.0,
        })
        df = pd.DataFrame(rows)

        result = c09_rare_account_pair(df, percentile=0.2)

        assert result[df["document_id"].eq("D_BIG")].all()
        assert result.attrs["breakdown"]["pair_generation_mode"] == (
            "line_pairs_with_large_doc_distinct_account_pairs"
        )
        assert result.attrs["breakdown"]["large_document_count"] == 1
        assert result.attrs["breakdown"]["deduplicated_large_debit_account_rows"] == 100
