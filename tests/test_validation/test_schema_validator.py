"""L1 구조 검증 — schema_validator.validate_schema() 테스트.

커버리지:
  - 정상/최소/빈 DataFrame
  - 필수 컬럼 누락, dtype 불일치, NaN 존재
  - 금액 음수 (ge=0 위반) → 경고
  - 권장 컬럼 부재, dtype 불일치, 고null
  - 피처 컬럼 존재 시 무시
  - column_stats 수집 검증
  - Int64 nullable 호환성
"""

import numpy as np
import pandas as pd
import pytest

from src.validation.schema_validator import validate_schema


class TestValidateSchema:
    """validate_schema() 정상·경계·에러 케이스."""

    def test_valid_dataframe(self, sv_valid_df: pd.DataFrame) -> None:
        """정상 — is_valid=True, errors 빈 리스트."""
        result = validate_schema(sv_valid_df)

        assert result.is_valid is True
        assert result.errors == []
        assert isinstance(result.column_stats, dict)
        assert len(result.column_stats) > 0

    def test_minimal_dataframe(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 9개만 → is_valid=True, 권장 컬럼 없어도 통과."""
        result = validate_schema(sv_minimal_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_missing_required_column(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼(document_id) 누락 → is_valid=False."""
        df = sv_minimal_df.drop(columns=["document_id"])
        result = validate_schema(df)

        assert result.is_valid is False
        assert any(e["column"] == "document_id" for e in result.errors)

    def test_multiple_required_missing(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼 2개 동시 누락 → errors에 2건."""
        df = sv_minimal_df.drop(columns=["document_id", "gl_account"])
        result = validate_schema(df)

        assert result.is_valid is False
        missing_cols = {e["column"] for e in result.errors}
        assert "document_id" in missing_cols
        assert "gl_account" in missing_cols

    def test_wrong_dtype_required(self, sv_minimal_df: pd.DataFrame) -> None:
        """posting_date가 str → dtype 불일치 → is_valid=False."""
        df = sv_minimal_df.copy()
        df["posting_date"] = ["not-a-date"] * len(df)
        result = validate_schema(df)

        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_negative_amount_warning(self, sv_minimal_df: pd.DataFrame) -> None:
        """debit_amount 음수 → warnings에 포함, is_valid=True."""
        df = sv_minimal_df.copy()
        df.loc[0, "debit_amount"] = -500.0
        result = validate_schema(df)

        # Why: 금액 음수는 경고이지 치명적 에러가 아님
        assert result.is_valid is True
        assert len(result.warnings) > 0

    def test_nullable_required_nan(self, sv_minimal_df: pd.DataFrame) -> None:
        """필수 컬럼(fiscal_year)에 NaN → is_valid=False."""
        df = sv_minimal_df.copy()
        df.loc[0, "fiscal_year"] = pd.NA
        result = validate_schema(df)

        assert result.is_valid is False
        assert any(
            e["column"] == "fiscal_year" for e in result.errors
        )

    def test_optional_column_missing(self, sv_minimal_df: pd.DataFrame) -> None:
        """권장 컬럼(line_text) 없음 → is_valid=True, 에러 없음."""
        # sv_minimal_df에는 이미 line_text가 없음
        assert "line_text" not in sv_minimal_df.columns
        result = validate_schema(sv_minimal_df)

        assert result.is_valid is True

    def test_extra_feature_columns(self, sv_valid_df: pd.DataFrame) -> None:
        """피처 18개 컬럼 존재 → strict=False이므로 에러 없음."""
        assert "is_weekend" in sv_valid_df.columns
        assert "amount_zscore" in sv_valid_df.columns

        result = validate_schema(sv_valid_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_column_stats_collected(self, sv_valid_df: pd.DataFrame) -> None:
        """column_stats에 null_rate, unique_count 존재."""
        result = validate_schema(sv_valid_df)

        # Why: schema.yaml에 정의된 컬럼만 stats에 포함 (피처 컬럼 제외)
        assert "document_id" in result.column_stats
        assert "posting_date" in result.column_stats

        stats = result.column_stats["document_id"]
        assert "null_rate" in stats
        assert "unique_count" in stats
        assert "dtype" in stats
        assert "total_count" in stats
        assert stats["null_rate"] == 0.0

    def test_high_null_rate_warning(self, sv_valid_df: pd.DataFrame) -> None:
        """권장 컬럼 null 90%+ → warnings에 high_null_rate."""
        df = sv_valid_df.copy()
        # Why: 5행 중 5행을 NaN으로 → 100% null
        df["created_by"] = pd.array([None] * len(df))
        result = validate_schema(df)

        assert result.is_valid is True
        assert any(
            w["column"] == "created_by" and w["issue"] == "high_null_rate"
            for w in result.warnings
        )

    def test_empty_dataframe(self, sv_empty_df: pd.DataFrame) -> None:
        """행 0건 → is_valid=True (구조는 올바름)."""
        result = validate_schema(sv_empty_df)

        assert result.is_valid is True
        assert result.errors == []

    def test_int64_nullable_compat(self, sv_minimal_df: pd.DataFrame) -> None:
        """Int64 dtype(pandas nullable integer) 호환성 확인."""
        # Why: type_caster는 fiscal_year, gl_account를 Int64로 변환
        assert sv_minimal_df["fiscal_year"].dtype == pd.Int64Dtype()
        assert sv_minimal_df["gl_account"].dtype == pd.Int64Dtype()

        result = validate_schema(sv_minimal_df)
        assert result.is_valid is True

    def test_feature_columns_excluded_from_stats(
        self, sv_valid_df: pd.DataFrame
    ) -> None:
        """column_stats에 피처 컬럼(is_weekend 등)이 포함되지 않음."""
        result = validate_schema(sv_valid_df)

        assert "is_weekend" not in result.column_stats
        assert "amount_zscore" not in result.column_stats
        assert "has_risk_keyword" not in result.column_stats
