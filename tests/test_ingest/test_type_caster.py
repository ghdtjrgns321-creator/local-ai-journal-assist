"""타입 캐스팅 모듈 테스트 — cast_amount, cast_date, cast_dataframe 등."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ingest.type_caster import (
    _cast_bool,
    _cast_int,
    cast_amount,
    cast_dataframe,
    cast_date,
    unify_debit_credit,
)


# ── TestCastAmount ───────────────────────────────────────────


class TestCastAmount:
    """금액 캐스팅 — 쉼표, 통화기호, 괄호음수, 빈값 등."""

    def test_comma_separated(self):
        s = pd.Series(["1,234,567", "10,000", "500"])
        result = cast_amount(s)
        assert result.tolist() == [1234567.0, 10000.0, 500.0]

    def test_won_symbol(self):
        s = pd.Series(["₩10,000", "₩5,000", "1000원"])
        result = cast_amount(s)
        assert result.tolist() == [10000.0, 5000.0, 1000.0]

    def test_dollar_symbol(self):
        s = pd.Series(["$5,000.50", "$100"])
        result = cast_amount(s)
        assert result.tolist() == [5000.50, 100.0]

    def test_parenthesis_negative(self):
        s = pd.Series(["(1,234)", "(500)", "(0)"])
        result = cast_amount(s)
        assert result.tolist() == [-1234.0, -500.0, 0.0]

    def test_empty_and_dash(self):
        s = pd.Series(["", "-", "—", "–"])
        result = cast_amount(s)
        assert result.isna().all()

    def test_none_and_nan(self):
        s = pd.Series([None, np.nan, "nan", "None"])
        result = cast_amount(s)
        assert result.isna().all()

    def test_zero(self):
        s = pd.Series(["0", "0.0", "0.00"])
        result = cast_amount(s)
        assert (result == 0.0).all()

    def test_plain_number(self):
        s = pd.Series(["12345.67", "-999", "0.5"])
        result = cast_amount(s)
        assert result.tolist() == [12345.67, -999.0, 0.5]

    def test_already_numeric(self):
        """이미 numeric dtype이면 float64로만 변환."""
        s = pd.Series([100, 200, 300], dtype="int64")
        result = cast_amount(s)
        assert result.dtype == np.float64
        assert result.tolist() == [100.0, 200.0, 300.0]


# ── TestCastDate ─────────────────────────────────────────────


class TestCastDate:
    """날짜 캐스팅 — ISO, 슬래시, 한국어, 8자리, Excel serial 등."""

    def test_iso(self):
        s = pd.Series(["2025-01-15", "2025-03-19"])
        result = cast_date(s)
        assert result.iloc[0] == pd.Timestamp("2025-01-15")
        assert result.iloc[1] == pd.Timestamp("2025-03-19")

    def test_slash(self):
        s = pd.Series(["2025/01/15", "2025/03/19"])
        result = cast_date(s)
        assert result.iloc[0] == pd.Timestamp("2025-01-15")

    def test_dot(self):
        s = pd.Series(["2025.01.15", "2025.03.19"])
        result = cast_date(s)
        assert result.iloc[0] == pd.Timestamp("2025-01-15")

    def test_compact_yyyymmdd(self):
        s = pd.Series(["20250115", "20250319"])
        result = cast_date(s)
        assert result.iloc[0] == pd.Timestamp("2025-01-15")
        assert result.iloc[1] == pd.Timestamp("2025-03-19")

    def test_korean(self):
        s = pd.Series(["2025년 1월 5일", "2025년 12월 31일"])
        result = cast_date(s)
        assert result.iloc[0] == pd.Timestamp("2025-01-05")
        assert result.iloc[1] == pd.Timestamp("2025-12-31")

    def test_excel_serial(self):
        """Excel serial number (45678 ≈ 2025-01-12)."""
        s = pd.Series(["45678"])
        result = cast_date(s)
        assert pd.notna(result.iloc[0])
        assert result.iloc[0].year == 2025

    def test_empty_and_none(self):
        s = pd.Series(["", None, np.nan])
        result = cast_date(s)
        # 빈문자열은 NaT, None/NaN도 NaT
        assert result.isna().sum() >= 2

    def test_already_datetime(self):
        s = pd.to_datetime(pd.Series(["2025-01-15", "2025-03-19"]))
        result = cast_date(s)
        assert pd.api.types.is_datetime64_any_dtype(result)


# ── TestCastInt ──────────────────────────────────────────────


class TestCastInt:
    """정수 캐스팅."""

    def test_string_to_int64(self):
        s = pd.Series(["2025", "1110", "42"])
        result = _cast_int(s)
        assert result.dtype == pd.Int64Dtype()
        assert result.tolist() == [2025, 1110, 42]

    def test_float_string(self):
        """소수점 문자열 → 반올림 후 Int64."""
        s = pd.Series(["2025.0", "1110.7"])
        result = _cast_int(s)
        assert result.iloc[0] == 2025
        assert result.iloc[1] == 1111

    def test_nan(self):
        s = pd.Series([None, "", "nan"])
        result = _cast_int(s)
        assert result.isna().all()

    def test_already_int(self):
        s = pd.Series([1, 2, 3], dtype="int64")
        result = _cast_int(s)
        assert result.dtype == pd.Int64Dtype()


# ── TestCastBool ─────────────────────────────────────────────


class TestCastBool:
    """불리언 캐스팅."""

    def test_true_variants(self):
        s = pd.Series(["true", "True", "1", "yes", "Y", "t"])
        result = _cast_bool(s)
        assert result.all()

    def test_false_variants(self):
        s = pd.Series(["false", "False", "0", "no", "N", "f"])
        result = _cast_bool(s)
        assert not result.any()

    def test_nan(self):
        s = pd.Series([None, "", "nan"])
        result = _cast_bool(s)
        assert result.isna().all()


# ── TestUnifyDebitCredit ─────────────────────────────────────


class TestUnifyDebitCredit:
    """차/대변 통합 로직."""

    def test_case_a_already_split(self):
        """debit_amount + credit_amount 이미 존재 → 그대로 통과."""
        df = pd.DataFrame({
            "debit_amount": [10000.0, 0.0],
            "credit_amount": [0.0, 5000.0],
        })
        result, warnings = unify_debit_credit(df)
        assert "debit_amount" in result.columns
        assert len(warnings) == 0

    def test_case_b_dc_indicator(self, tc_unified_amount_df):
        """amount + dc_indicator → 차/대변 분리."""
        result, warnings = unify_debit_credit(tc_unified_amount_df)
        assert result["debit_amount"].tolist() == [10000.0, 0.0, 3000.0, 0.0]
        assert result["credit_amount"].tolist() == [0.0, 5000.0, 0.0, 7000.0]
        assert len(warnings) == 0

    def test_case_c_sign_based(self):
        """amount만 (양수=차변, 음수=대변) → 부호 기반 분리."""
        df = pd.DataFrame({
            "document_id": ["JE001", "JE002"],
            "amount": [10000.0, -5000.0],
        })
        result, warnings = unify_debit_credit(df)
        assert result["debit_amount"].tolist() == [10000.0, 0.0]
        assert result["credit_amount"].tolist() == [0.0, 5000.0]
        assert len(warnings) == 1  # 추정값 경고

    def test_no_amount_column(self):
        """amount 컬럼 없음 → 원본 반환 + warning."""
        df = pd.DataFrame({"document_id": ["JE001"], "memo": ["test"]})
        result, warnings = unify_debit_credit(df)
        assert "debit_amount" not in result.columns
        assert len(warnings) == 1


# ── TestCastDataframe ────────────────────────────────────────


class TestCastDataframe:
    """cast_dataframe 퍼사드 통합 테스트."""

    def _get_test_schema(self):
        """테스트용 축소 스키마."""
        return {
            "columns": [
                {"name": "document_id", "type": "str", "required": True},
                {"name": "fiscal_year", "type": "int", "required": True},
                {"name": "posting_date", "type": "date", "required": True},
                {"name": "document_date", "type": "date", "required": True},
                {"name": "gl_account", "type": "int", "required": True},
                {"name": "debit_amount", "type": "float", "required": True},
                {"name": "credit_amount", "type": "float", "required": True},
                {"name": "company_code", "type": "str", "required": True},
                {"name": "document_type", "type": "str", "required": True},
                {"name": "created_by", "type": "str", "required": False},
                {"name": "source", "type": "str", "required": False},
                {"name": "line_text", "type": "str", "required": False},
            ],
        }

    def test_full_casting(self, tc_standard_df):
        """object → 적절한 타입으로 전체 캐스팅."""
        result = cast_dataframe(tc_standard_df, schema=self._get_test_schema())
        assert result.success is True
        assert len(result.errors) == 0
        # 금액 컬럼이 float64로 변환되었는지
        assert result.data["debit_amount"].dtype == np.float64
        assert result.data["credit_amount"].dtype == np.float64
        # 날짜가 datetime으로 변환되었는지
        assert pd.api.types.is_datetime64_any_dtype(result.data["posting_date"])
        # 정수가 Int64로 변환되었는지
        assert result.data["fiscal_year"].dtype == pd.Int64Dtype()
        # cast_summary에 변환 기록이 있는지
        assert len(result.cast_summary) > 0

    def test_parquet_skip(self, tc_parquet_df):
        """이미 올바른 타입이면 스킵."""
        result = cast_dataframe(tc_parquet_df, schema=self._get_test_schema())
        assert result.success is True
        assert len(result.skipped_columns) > 0
        assert "posting_date" in result.skipped_columns

    def test_missing_required_error(self):
        """필수 컬럼 캐스팅 실패 → errors."""
        df = pd.DataFrame({
            "document_id": ["JE001"],
            "posting_date": ["not-a-date-at-all-!!!"],
            "document_date": ["2025-01-15"],
            "fiscal_year": ["abc"],  # int 캐스팅 → NaN → 100% 결측
            "gl_account": ["1110"],
            "debit_amount": ["1000"],
            "credit_amount": ["0"],
            "company_code": ["1000"],
            "document_type": ["SA"],
        })
        result = cast_dataframe(df, schema=self._get_test_schema())
        # fiscal_year가 전부 NaN이면 결측률 100% → warning
        assert len(result.warnings) > 0

    def test_partial_nan_warning(self):
        """캐스팅 후 결측률 > 10% → warning 발생."""
        # 10개 중 5개가 변환 불가 → 50% 결측
        amounts = ["1000", "invalid", "invalid", "invalid", "invalid",
                    "invalid", "2000", "3000", "invalid", "invalid"]
        df = pd.DataFrame({
            "debit_amount": amounts,
            "credit_amount": ["0"] * 10,
        })
        schema = {
            "columns": [
                {"name": "debit_amount", "type": "float", "required": True},
                {"name": "credit_amount", "type": "float", "required": True},
            ],
        }
        result = cast_dataframe(df, schema=schema)
        assert any("결측률" in w for w in result.warnings)

    def test_empty_dataframe(self):
        """빈 DataFrame → 에러 없이 통과."""
        df = pd.DataFrame(columns=["document_id", "posting_date", "debit_amount"])
        schema = {
            "columns": [
                {"name": "document_id", "type": "str", "required": True},
                {"name": "posting_date", "type": "date", "required": True},
                {"name": "debit_amount", "type": "float", "required": True},
            ],
        }
        result = cast_dataframe(df, schema=schema)
        assert result.success is True
        assert len(result.data) == 0

    def test_unify_called_when_amount_exists(self):
        """amount 컬럼만 있고 debit/credit 없으면 unify_debit_credit 호출."""
        df = pd.DataFrame({
            "document_id": ["JE001", "JE002"],
            "amount": ["10000", "-5000"],
        })
        schema = {
            "columns": [
                {"name": "document_id", "type": "str", "required": True},
                {"name": "amount", "type": "float", "required": False},
            ],
        }
        result = cast_dataframe(df, schema=schema)
        assert result.success is True
        assert "debit_amount" in result.data.columns
        assert "credit_amount" in result.data.columns
