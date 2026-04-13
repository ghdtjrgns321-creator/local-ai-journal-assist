"""pattern_features 단위 테스트.

계층: 개별 피처 → orchestrator 순서로 검증.
B01(매출계정), B08(수기전표), B10(관계사), B11/C06(가계정), C07(Benford) 룰 대응.
"""

import numpy as np
import pandas as pd
import pytest

from src.feature.pattern_features import (
    add_all_pattern_features,
    add_first_digit,
    add_is_intercompany,
    add_is_manual_je,
    add_is_revenue_account,
    add_is_suspense_account,
)


# ── TestAddIsManualJe ────────────────────────────────────────────


class TestAddIsManualJe:
    """B08: 수기 전표 식별."""

    CODES = ["SA", "Manual", "수기"]

    def test_exact_match(self, pf_basic_df):
        """정확히 매칭되는 코드 → True."""
        result = add_is_manual_je(pf_basic_df, self.CODES)
        assert result["is_manual_je"].iloc[0] == True   # SA
        assert result["is_manual_je"].iloc[2] == True   # Manual
        assert result["is_manual_je"].iloc[3] == True   # 수기

    def test_non_match(self, pf_basic_df):
        """매칭되지 않는 코드 → False."""
        result = add_is_manual_je(pf_basic_df, self.CODES)
        assert result["is_manual_je"].iloc[1] == False   # AUTO

    def test_case_insensitive(self):
        """대소문자 무시 매칭."""
        df = pd.DataFrame({"source": ["sa", "MANUAL", "Sa"]})
        result = add_is_manual_je(df, self.CODES)
        assert result["is_manual_je"].tolist() == [True, True, True]

    def test_whitespace_trimmed(self):
        """앞뒤 공백 제거 후 매칭."""
        df = pd.DataFrame({"source": ["  SA  ", " Manual"]})
        result = add_is_manual_je(df, self.CODES)
        assert result["is_manual_je"].tolist() == [True, True]

    def test_nan_source(self, pf_basic_df):
        """source가 NaN → False (오탐 방지)."""
        result = add_is_manual_je(pf_basic_df, self.CODES)
        assert result["is_manual_je"].iloc[4] == False

    def test_empty_codes(self, pf_basic_df):
        """manual_codes 비어있으면 → 전부 False."""
        result = add_is_manual_je(pf_basic_df, [])
        assert not result["is_manual_je"].any()

    def test_missing_source_column(self, pf_minimal_df):
        """source 컬럼 없으면 → 전부 False."""
        result = add_is_manual_je(pf_minimal_df, self.CODES)
        assert not result["is_manual_je"].any()

    def test_all_nan_source(self):
        """source가 전부 NaN → 전부 False."""
        df = pd.DataFrame({"source": [None, None, None]})
        result = add_is_manual_je(df, self.CODES)
        assert not result["is_manual_je"].any()


# ── TestAddIsIntercompany ────────────────────────────────────────


class TestAddIsIntercompany:
    """B10: 관계사 거래 식별."""

    IDENTIFIERS = ["INTER", "99"]

    def test_gl_account_prefix(self):
        """gl_account가 식별자 prefix와 매칭."""
        df = pd.DataFrame({
            "gl_account": pd.array([9900, 1200], dtype="Int64"),
        })
        result = add_is_intercompany(df, self.IDENTIFIERS)
        assert result["is_intercompany"].iloc[0] == True
        assert result["is_intercompany"].iloc[1] == False

    def test_company_code_ignored(self):
        """company_code만 있고 gl_account 없으면 → 전부 False (GL 기반 식별)."""
        df = pd.DataFrame({
            "company_code": ["INTER_01", "HQ"],
        })
        result = add_is_intercompany(df, self.IDENTIFIERS)
        assert not result["is_intercompany"].any()

    def test_multiple_gl_prefixes(self):
        """여러 GL prefix 중 하나라도 매칭이면 True."""
        df = pd.DataFrame({
            "gl_account": pd.array([9900, 1200, 9901], dtype="Int64"),
        })
        result = add_is_intercompany(df, self.IDENTIFIERS)
        assert result["is_intercompany"].tolist() == [True, False, True]

    def test_empty_identifiers(self, pf_basic_df):
        """identifiers 비어있으면 → 전부 False."""
        result = add_is_intercompany(pf_basic_df, [])
        assert not result["is_intercompany"].any()

    def test_no_gl_account_column(self, pf_minimal_df):
        """gl_account 컬럼 없으면 → 전부 False."""
        result = add_is_intercompany(pf_minimal_df, self.IDENTIFIERS)
        assert not result["is_intercompany"].any()

    def test_gl_account_na(self):
        """gl_account가 NA → 매칭 안 됨 (정상)."""
        df = pd.DataFrame({
            "gl_account": pd.array([pd.NA, 9900], dtype="Int64"),
        })
        result = add_is_intercompany(df, self.IDENTIFIERS)
        assert result["is_intercompany"].iloc[0] == False
        assert result["is_intercompany"].iloc[1] == True


# ── TestAddIsRevenueAccount ──────────────────────────────────────


class TestAddIsRevenueAccount:
    """B01: 매출 계정 판별."""

    def test_single_prefix(self, pf_basic_df):
        """prefix '4' → 4100, 4200 매칭."""
        result = add_is_revenue_account(pf_basic_df, ["4"])
        assert result["is_revenue_account"].iloc[0] == True   # 4100
        assert result["is_revenue_account"].iloc[1] == False   # 1200
        assert result["is_revenue_account"].iloc[2] == True   # 4200

    def test_multiple_prefixes(self, pf_basic_df):
        """복수 prefix ['4', '9'] → 4100, 4200, 9100 매칭."""
        result = add_is_revenue_account(pf_basic_df, ["4", "9"])
        expected = [True, False, True, True, False]
        assert result["is_revenue_account"].tolist() == expected

    def test_no_gl_account(self, pf_minimal_df):
        """gl_account 컬럼 없으면 → 전부 False."""
        result = add_is_revenue_account(pf_minimal_df, ["4"])
        assert not result["is_revenue_account"].any()

    def test_empty_prefixes(self, pf_basic_df):
        """prefixes 비어있으면 → 전부 False."""
        result = add_is_revenue_account(pf_basic_df, [])
        assert not result["is_revenue_account"].any()

    def test_gl_account_na(self):
        """gl_account가 NA → False."""
        df = pd.DataFrame({"gl_account": pd.array([pd.NA, 4100], dtype="Int64")})
        result = add_is_revenue_account(df, ["4"])
        assert result["is_revenue_account"].iloc[0] == False
        assert result["is_revenue_account"].iloc[1] == True

    def test_string_gl_account(self):
        """gl_account가 문자열이어도 정상 동작."""
        df = pd.DataFrame({"gl_account": ["4100", "1200"]})
        result = add_is_revenue_account(df, ["4"])
        assert result["is_revenue_account"].tolist() == [True, False]


# ── TestAddFirstDigit ────────────────────────────────────────────


class TestAddFirstDigit:
    """C07: Benford용 첫 번째 유효숫자 추출."""

    def test_positive_integer(self):
        """양수 정수 → 첫 자리 추출."""
        df = pd.DataFrame({"debit_amount": [1500.0], "credit_amount": [0.0]})
        result = add_first_digit(df)
        assert result["first_digit"].iloc[0] == 1

    def test_negative_amount(self):
        """음수 → abs() 후 첫 자리 추출."""
        df = pd.DataFrame({"debit_amount": [-3000.0], "credit_amount": [0.0]})
        result = add_first_digit(df)
        assert result["first_digit"].iloc[0] == 3

    def test_decimal_leading_zero(self):
        """소수 0.005 → 첫 번째 non-zero digit = 5."""
        df = pd.DataFrame({"debit_amount": [0.005], "credit_amount": [0.0]})
        result = add_first_digit(df)
        assert result["first_digit"].iloc[0] == 5

    def test_zero_amount(self):
        """0원 → NaN (Benford 대상 외)."""
        df = pd.DataFrame({"debit_amount": [0.0], "credit_amount": [0.0]})
        result = add_first_digit(df)
        assert pd.isna(result["first_digit"].iloc[0])

    def test_nan_amount(self):
        """NaN → NaN."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [np.nan]})
        result = add_first_digit(df)
        assert pd.isna(result["first_digit"].iloc[0])

    def test_credit_larger(self):
        """credit이 debit보다 크면 credit 기준."""
        df = pd.DataFrame({"debit_amount": [100.0], "credit_amount": [5000.0]})
        result = add_first_digit(df)
        assert result["first_digit"].iloc[0] == 5

    def test_scientific_notation(self):
        """아주 작은 소수(과학표기법) → 첫 유효숫자."""
        df = pd.DataFrame({"debit_amount": [1.5e-05], "credit_amount": [0.0]})
        result = add_first_digit(df)
        assert result["first_digit"].iloc[0] == 1

    def test_dtype_is_int64(self):
        """결과 dtype이 nullable Int64."""
        df = pd.DataFrame({"debit_amount": [1000.0, 0.0], "credit_amount": [0.0, 0.0]})
        result = add_first_digit(df)
        assert result["first_digit"].dtype == pd.Int64Dtype()

    def test_various_digits(self):
        """1~9 모든 첫 자리 검증."""
        amounts = [1000, 2500, 3700, 4100, 5000, 6200, 7800, 8900, 9999]
        df = pd.DataFrame({"debit_amount": amounts, "credit_amount": [0] * 9})
        result = add_first_digit(df)
        expected = list(range(1, 10))
        assert result["first_digit"].tolist() == expected

    def test_both_nan_returns_nan(self):
        """debit, credit 모두 NaN → fillna(0) → 0 → NaN."""
        df = pd.DataFrame({"debit_amount": [np.nan], "credit_amount": [np.nan]})
        result = add_first_digit(df)
        assert pd.isna(result["first_digit"].iloc[0])

    def test_missing_amount_columns(self):
        """금액 컬럼 부재 → 전체 NaN + warning."""
        df = pd.DataFrame({"gl_account": ["4100"]})
        result = add_first_digit(df)
        assert pd.isna(result["first_digit"].iloc[0])
        assert result["first_digit"].dtype == pd.Int64Dtype()


# ── TestAddIsSuspenseAccount ─────────────────────────────────────


class TestAddIsSuspenseAccount:
    """B11/C06: 가계정·미결산 키워드 매칭."""

    KEYWORDS = ["가수금", "가지급", "미결산", "임시"]

    def test_line_text_match(self):
        """line_text에서 키워드 매칭."""
        df = pd.DataFrame({"line_text": ["가수금 정리", "매출 입금"]})
        result = add_is_suspense_account(df, self.KEYWORDS)
        assert result["is_suspense_account"].tolist() == [True, False]

    def test_header_text_match(self):
        """header_text에서 키워드 매칭."""
        df = pd.DataFrame({"header_text": ["임시 처리", "정상 거래"]})
        result = add_is_suspense_account(df, self.KEYWORDS)
        assert result["is_suspense_account"].tolist() == [True, False]

    def test_or_combination(self):
        """line_text OR header_text 중 하나라도 매칭이면 True."""
        df = pd.DataFrame({
            "line_text": ["일반 전표", "가지급금 반환"],
            "header_text": ["미결산 처리", "정상"],
        })
        result = add_is_suspense_account(df, self.KEYWORDS)
        assert result["is_suspense_account"].tolist() == [True, True]

    def test_empty_keywords(self):
        """keywords 비어있으면 → 전부 False."""
        df = pd.DataFrame({"line_text": ["가수금 정리"]})
        result = add_is_suspense_account(df, [])
        assert not result["is_suspense_account"].any()

    def test_no_text_columns(self, pf_minimal_df):
        """텍스트 컬럼 없으면 → 전부 False."""
        result = add_is_suspense_account(pf_minimal_df, self.KEYWORDS)
        assert not result["is_suspense_account"].any()

    def test_regex_keyword(self):
        """정규식 키워드도 동작."""
        df = pd.DataFrame({"line_text": ["가임시계정", "일반전표"]})
        result = add_is_suspense_account(df, [".*임시.*"])
        assert result["is_suspense_account"].tolist() == [True, False]

    def test_invalid_regex_fallback(self):
        """잘못된 정규식 → re.escape 폴백."""
        df = pd.DataFrame({"line_text": ["test[invalid", "normal"]})
        # "[invalid"는 잘못된 정규식 → escape 후 리터럴 매칭
        result = add_is_suspense_account(df, ["[invalid"])
        assert result["is_suspense_account"].iloc[0] == True

    def test_nan_text_no_match(self):
        """텍스트가 NaN → False (na=False)."""
        df = pd.DataFrame({"line_text": [None, "가수금"]})
        result = add_is_suspense_account(df, self.KEYWORDS)
        assert result["is_suspense_account"].iloc[0] == False
        assert result["is_suspense_account"].iloc[1] == True

    # ── GL 계정 코드 기반 판별 테스트 ──

    def test_gl_account_code_match(self):
        """gl_account prefix가 suspense_account_codes에 매칭 → True."""
        df = pd.DataFrame({
            "gl_account": pd.array([2190, 1200, 2900], dtype="Int64"),
            "line_text": ["일반 거래", "일반 거래", "일반 거래"],
        })
        codes = ["2190", "2900"]
        result = add_is_suspense_account(df, self.KEYWORDS, account_codes=codes)
        assert result["is_suspense_account"].tolist() == [True, False, True]

    def test_keyword_or_code_hybrid(self):
        """키워드 매칭 OR 코드 매칭 — 둘 중 하나라도 True."""
        df = pd.DataFrame({
            "gl_account": pd.array([2190, 1200, 4100], dtype="Int64"),
            "line_text": ["일반 거래", "가수금 정리", "일반 거래"],
        })
        codes = ["2190"]
        result = add_is_suspense_account(df, self.KEYWORDS, account_codes=codes)
        # 행0: 코드 매칭, 행1: 키워드 매칭, 행2: 둘 다 아님
        assert result["is_suspense_account"].tolist() == [True, True, False]

    def test_code_match_without_text_columns(self):
        """텍스트 컬럼 없어도 코드 매칭만으로 True."""
        df = pd.DataFrame({
            "gl_account": pd.array([2190, 1200], dtype="Int64"),
        })
        codes = ["2190"]
        result = add_is_suspense_account(df, [], account_codes=codes)
        assert result["is_suspense_account"].tolist() == [True, False]

    def test_empty_codes_no_effect(self):
        """account_codes 빈 리스트 → 기존 키워드 매칭만 동작."""
        df = pd.DataFrame({"line_text": ["가수금 정리", "일반"]})
        result = add_is_suspense_account(df, self.KEYWORDS, account_codes=[])
        assert result["is_suspense_account"].tolist() == [True, False]

    def test_no_gl_account_column_code_ignored(self):
        """gl_account 컬럼 없으면 코드 매칭 스킵, 키워드만 동작."""
        df = pd.DataFrame({"line_text": ["가수금 정리", "일반"]})
        result = add_is_suspense_account(df, self.KEYWORDS, account_codes=["2190"])
        assert result["is_suspense_account"].tolist() == [True, False]


# ── TestAddAllPatternFeatures ────────────────────────────────────


class TestAddAllPatternFeatures:
    """오케스트레이터: 5개 피처 일괄 생성."""

    RULES = {
        "manual_source_codes": ["SA", "Manual", "수기"],
        "revenue_account_prefixes": ["4"],
        "intercompany": {"pairs": []},
        "suspense_keywords": ["가수금", "가지급", "미결산", "임시"],
        "suspense_account_codes": ["2190", "2900"],
    }

    def test_all_columns_created(self, pf_basic_df):
        """5개 피처 컬럼 모두 생성."""
        result = add_all_pattern_features(pf_basic_df, self.RULES)
        expected_cols = [
            "is_manual_je", "is_intercompany", "is_revenue_account",
            "first_digit", "is_suspense_account",
        ]
        for col in expected_cols:
            assert col in result.columns, f"{col} 컬럼 누락"

    def test_returns_same_df(self, pf_basic_df):
        """in-place 수정 후 동일 객체 반환."""
        result = add_all_pattern_features(pf_basic_df, self.RULES)
        assert result is pf_basic_df

    def test_minimal_df(self, pf_minimal_df):
        """최소 컬럼 DataFrame에서도 에러 없이 동작."""
        result = add_all_pattern_features(pf_minimal_df, self.RULES)
        assert "is_manual_je" in result.columns
        assert "first_digit" in result.columns
