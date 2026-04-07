"""텍스트 파생변수 테스트.

private helper 4개 + public feature 2개 + orchestrator 1개.
"""

import pandas as pd
import pytest

from src.feature.text_features import (
    _clean_for_keyword,
    _combine_text,
    _is_noise_pattern,
    _match_risk_level,
    add_all_text_features,
    add_description_quality,
    add_has_risk_keyword,
)


# ── _combine_text ────────────────────────────────────────────────


class TestCombineText:
    """line_text + header_text 결합 로직."""

    def test_both_present(self):
        """둘 다 있으면 공백으로 concat."""
        df = pd.DataFrame({
            "line_text": ["식대"],
            "header_text": ["3월 영업부"],
        })
        result = _combine_text(df)
        assert result.iloc[0] == "식대 3월 영업부"

    def test_only_line(self):
        """line만 있으면 line 사용."""
        df = pd.DataFrame({
            "line_text": ["매출"],
            "header_text": [None],
        })
        result = _combine_text(df)
        assert result.iloc[0] == "매출"

    def test_only_header(self):
        """header만 있으면 header 사용."""
        df = pd.DataFrame({
            "line_text": [None],
            "header_text": ["결산"],
        })
        result = _combine_text(df)
        assert result.iloc[0] == "결산"

    def test_both_none(self):
        """둘 다 None이면 NaN."""
        df = pd.DataFrame({
            "line_text": [None],
            "header_text": [None],
        })
        result = _combine_text(df)
        assert pd.isna(result.iloc[0])

    def test_no_text_columns(self):
        """텍스트 컬럼 자체가 없으면 전체 NaN."""
        df = pd.DataFrame({"debit_amount": [1000.0]})
        result = _combine_text(df)
        assert pd.isna(result.iloc[0])


# ── _clean_for_keyword ───────────────────────────────────────────


class TestCleanText:
    """키워드 매칭 전용 정제."""

    def test_remove_spaces(self):
        """공백 제거."""
        s = pd.Series(["상 품 권"])
        assert _clean_for_keyword(s).iloc[0] == "상품권"

    def test_remove_special_chars(self):
        """특수문자 제거."""
        s = pd.Series(["[상품권]", "상품/권"])
        result = _clean_for_keyword(s)
        assert result.iloc[0] == "상품권"
        assert result.iloc[1] == "상품권"

    def test_preserve_hangul_alnum(self):
        """한글+영숫자 보존."""
        s = pd.Series(["ABC가나다123"])
        assert _clean_for_keyword(s).iloc[0] == "ABC가나다123"

    def test_none_to_empty(self):
        """None → 빈 문자열."""
        s = pd.Series([None])
        assert _clean_for_keyword(s).iloc[0] == ""


# ── _is_noise_pattern ────────────────────────────────────────────


class TestIsNoisePattern:
    """노이즈 패턴 탐지."""

    @pytest.mark.parametrize("text", ["ㅋㅋㅋ", "ㅎㅎ", "ㅏㅏ"])
    def test_jamo_only(self, text):
        """자음/모음만으로 이루어진 문자열."""
        assert _is_noise_pattern(text) is True

    @pytest.mark.parametrize("text", ["...", "---", "!!!"])
    def test_special_only(self, text):
        """특수문자만."""
        assert _is_noise_pattern(text) is True

    @pytest.mark.parametrize("text", ["aaa", "zzz", "111"])
    def test_repeat_char(self, text):
        """동일 문자 3회+ 반복."""
        assert _is_noise_pattern(text) is True

    def test_normal_text(self):
        """정상 텍스트는 False."""
        assert _is_noise_pattern("일반 매출") is False

    def test_empty_string(self):
        """빈 문자열은 False (NaN 판정은 상위 함수)."""
        assert _is_noise_pattern("") is False


# ── _match_risk_level ────────────────────────────────────────────


class TestMatchRiskLevel:
    """키워드 매칭 등급."""

    def test_high_priority(self):
        """high 키워드가 있으면 high."""
        assert _match_risk_level("상품권구매", ["상품권"], ["잡손실"]) == "high"

    def test_medium(self):
        """medium 키워드만 있으면 medium."""
        assert _match_risk_level("잡손실처리", ["상품권"], ["잡손실"]) == "medium"

    def test_low(self):
        """매칭 없으면 low."""
        assert _match_risk_level("일반매출", ["상품권"], ["잡손실"]) == "low"

    def test_high_over_medium(self):
        """high와 medium 모두 포함 → high 우선."""
        assert _match_risk_level("상품권잡손실", ["상품권"], ["잡손실"]) == "high"

    def test_empty_text(self):
        """빈 문자열 → low."""
        assert _match_risk_level("", ["상품권"], ["잡손실"]) == "low"


# ── add_description_quality ──────────────────────────────────────


class TestDescriptionQuality:
    """적요 품질 3단계 판정."""

    def test_basic_cases(self, xt_base_df):
        """normal/missing/poor 기본 판정."""
        result = add_description_quality(xt_base_df)
        q = result["description_quality"]
        # idx 0: "상품권 구매 월말 정리" → normal
        assert q.iloc[0] == "normal"
        # idx 4: 둘 다 None → missing
        assert q.iloc[4] == "missing"
        # idx 5: "AB" (len=2 < 3) → poor
        assert q.iloc[5] == "poor"

    def test_concat_rescue(self, xt_base_df):
        """line만으로는 poor이지만, header와 concat → normal로 구제."""
        result = add_description_quality(xt_base_df)
        q = result["description_quality"]
        # idx 6: "식대"(2글자) + "3월 영업부 법인카드" → concat → normal
        assert q.iloc[6] == "normal"

    def test_header_only_rescue(self, xt_base_df):
        """line=None이어도 header만으로 normal 가능."""
        result = add_description_quality(xt_base_df)
        q = result["description_quality"]
        # idx 3: line=None, header="3월 영업부 법인카드" → normal
        assert q.iloc[3] == "normal"

    def test_noise_is_poor(self, xt_noise_df):
        """노이즈 패턴은 poor로 분류."""
        result = add_description_quality(xt_noise_df)
        q = result["description_quality"]
        # "ㅋㅋㅋ", "...", "aaa" → poor
        assert q.iloc[0] == "poor"
        assert q.iloc[1] == "poor"
        assert q.iloc[2] == "poor"
        # "ㅎㅎ" → jamo + len=2 → poor
        assert q.iloc[3] == "poor"
        # "정상 적요" → normal
        assert q.iloc[4] == "normal"

    def test_custom_min_length(self):
        """min_length 커스텀 값."""
        df = pd.DataFrame({"line_text": ["ABCD"], "header_text": [None]})
        result = add_description_quality(df, min_length=5)
        assert result["description_quality"].iloc[0] == "poor"

    def test_strip_length_not_cleaned(self):
        """strip 원본 길이 사용 — 공백 포함."""
        df = pd.DataFrame({"line_text": ["A B"], "header_text": [None]})
        # "A B" → strip → len=3 → normal (cleaned면 "AB" len=2 → poor)
        result = add_description_quality(df, min_length=3)
        assert result["description_quality"].iloc[0] == "normal"


# ── add_has_risk_keyword ─────────────────────────────────────────


class TestHasRiskKeyword:
    """위험 키워드 등급 판정."""

    def test_basic_cases(self, xt_base_df):
        """high/medium/low 기본 매칭."""
        kw = {"high_risk": ["상품권"], "medium_risk": ["잡손실"]}
        result = add_has_risk_keyword(xt_base_df, risk_kw=kw)
        r = result["has_risk_keyword"]
        # idx 0: "상품권 구매" → high
        assert r.iloc[0] == "high"
        # idx 1: "잡손실 처리" → medium
        assert r.iloc[1] == "medium"
        # idx 2: "일반 매출" → low
        assert r.iloc[2] == "low"

    def test_obfuscated_patterns(self, xt_obfuscated_df):
        """은폐 패턴 — cleaned 텍스트로 관통."""
        kw = {"high_risk": ["상품권", "가수금"], "medium_risk": []}
        result = add_has_risk_keyword(xt_obfuscated_df, risk_kw=kw)
        r = result["has_risk_keyword"]
        # "상 품 권" → "상품권" → high
        assert r.iloc[0] == "high"
        # "[상품권]" → "상품권" → high
        assert r.iloc[1] == "high"
        # "상품/권" → "상품권" → high
        assert r.iloc[2] == "high"
        # "가 수 금" → "가수금" → high
        assert r.iloc[3] == "high"
        # "일반매출" → low
        assert r.iloc[4] == "low"

    def test_none_text_is_low(self):
        """텍스트 없으면 low."""
        df = pd.DataFrame({"line_text": [None], "header_text": [None]})
        kw = {"high_risk": ["상품권"], "medium_risk": []}
        result = add_has_risk_keyword(df, risk_kw=kw)
        assert result["has_risk_keyword"].iloc[0] == "low"

    def test_custom_keywords(self):
        """커스텀 키워드 주입."""
        df = pd.DataFrame({"line_text": ["테스트용키워드"], "header_text": [None]})
        kw = {"high_risk": ["테스트용"], "medium_risk": []}
        result = add_has_risk_keyword(df, risk_kw=kw)
        assert result["has_risk_keyword"].iloc[0] == "high"


# ── add_all_text_features ────────────────────────────────────────


class TestAddAllTextFeatures:
    """orchestrator — 2개 컬럼 동시 생성."""

    def test_creates_both_columns(self, xt_base_df):
        """description_quality + has_risk_keyword 컬럼 생성."""
        result = add_all_text_features(xt_base_df)
        assert "description_quality" in result.columns
        assert "has_risk_keyword" in result.columns

    def test_no_text_columns(self, xt_no_text_cols_df):
        """텍스트 컬럼 없어도 에러 없이 동작."""
        result = add_all_text_features(xt_no_text_cols_df)
        assert "description_quality" in result.columns
        assert "has_risk_keyword" in result.columns
        # 모두 missing/low
        assert (result["description_quality"] == "missing").all()
        assert (result["has_risk_keyword"] == "low").all()

    def test_inplace_returns_same_object(self, xt_base_df):
        """in-place 수정 + 동일 객체 반환."""
        result = add_all_text_features(xt_base_df)
        assert result is xt_base_df
