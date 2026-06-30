"""텍스트 파생변수 테스트.

private helper 4개 + public feature 2개 + orchestrator 1개.
"""

import pandas as pd
import pytest

from src.feature.text_features import (
    _clean_for_keyword,
    _combine_text,
    _compute_entropy,
    _compute_ttr,
    _is_noise_pattern,
    _match_risk_level,
    add_all_text_features,
    add_description_quality,
    add_has_risk_keyword,
    build_description_quality_profile,
)

# ── _combine_text ────────────────────────────────────────────────


class TestCombineText:
    """line_text + header_text 결합 로직."""

    def test_both_present(self):
        """둘 다 있으면 공백으로 concat."""
        df = pd.DataFrame(
            {
                "line_text": ["식대"],
                "header_text": ["3월 영업부"],
            }
        )
        result = _combine_text(df)
        assert result.iloc[0] == "식대 3월 영업부"

    def test_only_line(self):
        """line만 있으면 line 사용."""
        df = pd.DataFrame(
            {
                "line_text": ["매출"],
                "header_text": [None],
            }
        )
        result = _combine_text(df)
        assert result.iloc[0] == "매출"

    def test_only_header(self):
        """header만 있으면 header 사용."""
        df = pd.DataFrame(
            {
                "line_text": [None],
                "header_text": ["결산"],
            }
        )
        result = _combine_text(df)
        assert result.iloc[0] == "결산"

    def test_both_none(self):
        """둘 다 None이면 NaN."""
        df = pd.DataFrame(
            {
                "line_text": [None],
                "header_text": [None],
            }
        )
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

    @pytest.mark.parametrize("text", ["비품비품비품", "ABCABCABC"])
    def test_repeat_word(self, text):
        """다문자 패턴 3회+ 반복."""
        assert _is_noise_pattern(text) is True

    @pytest.mark.parametrize("text", ["x", "X", "n/a", "NA", "null"])
    def test_placeholder_garbage(self, text):
        """명백한 placeholder garbage."""
        assert _is_noise_pattern(text) is True

    def test_two_repeat_not_noise(self):
        """2회 반복은 허용 (실무 오타/복붙 가능)."""
        assert _is_noise_pattern("비품비품") is False

    def test_mixed_repeat_normal(self):
        """반복이 아닌 비슷한 텍스트는 정상."""
        assert _is_noise_pattern("비품구매비품") is False

    def test_normal_text(self):
        """정상 텍스트는 False."""
        assert _is_noise_pattern("일반 매출") is False

    def test_empty_string(self):
        """빈 문자열은 False (NaN 판정은 상위 함수)."""
        assert _is_noise_pattern("") is False


# ── _compute_ttr ─────────────────────────────────────────────────


class TestComputeTtr:
    """어휘 다양성 (Type-Token Ratio)."""

    def test_all_unique(self):
        """모든 토큰이 고유 → TTR=1.0."""
        assert _compute_ttr("가 나 다 라") == 1.0

    def test_all_same(self):
        """모든 토큰 동일(4개) → TTR=1/4=0.25."""
        assert _compute_ttr("가 가 가 가") == 0.25

    def test_empty_string(self):
        """빈 문자열 → 0.0."""
        assert _compute_ttr("") == 0.0

    def test_single_token(self):
        """토큰 1개 → TTR=1.0."""
        assert _compute_ttr("매출") == 1.0

    def test_below_threshold(self):
        """동일 단어 5회 반복 → TTR=0.2 < 0.3."""
        assert _compute_ttr("비품 비품 비품 비품 비품") == pytest.approx(0.2)

    def test_whitespace_only(self):
        """공백만 → split() 결과 빈 리스트 → 0.0."""
        assert _compute_ttr("   ") == 0.0


# ── _compute_entropy ─────────────────────────────────────────────


class TestComputeEntropy:
    """문자 단위 Shannon Entropy."""

    def test_single_char_repeat(self):
        """동일 문자 반복 → entropy=0.0."""
        assert _compute_entropy("aaaa") == 0.0

    def test_empty_string(self):
        """빈 문자열 → 0.0."""
        assert _compute_entropy("") == 0.0

    def test_high_entropy(self):
        """다양한 문자 → entropy > 1.0."""
        assert _compute_entropy("abcdefgh") > 1.0

    def test_two_chars_equal(self):
        """2종 문자 균등 분포 → entropy=1.0."""
        assert _compute_entropy("aabb") == pytest.approx(1.0)

    def test_single_char(self):
        """단일 문자 → entropy=0.0."""
        assert _compute_entropy("a") == 0.0


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
    """적요 결손/파손 3단계 판정."""

    def test_basic_cases(self, xt_base_df):
        """normal/missing/corrupted 기본 판정."""
        result = add_description_quality(xt_base_df)
        q = result["description_quality"]
        # idx 0: "상품권 구매 월말 정리" → normal
        assert q.iloc[0] == "normal"
        # idx 4: 둘 다 None → missing
        assert q.iloc[4] == "missing"
        # idx 5: "AB" → 의미 판단 대상이 아니므로 normal
        assert q.iloc[5] == "normal"

    def test_concat_rescue(self, xt_base_df):
        """line과 header를 concat해서 결손 여부를 판단."""
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
        """노이즈 패턴은 corrupted로 분류."""
        result = add_description_quality(xt_noise_df)
        q = result["description_quality"]
        # "ㅋㅋㅋ", "...", "aaa", "ㅎㅎ" → corrupted
        assert q.iloc[0] == "corrupted"
        assert q.iloc[1] == "corrupted"
        assert q.iloc[2] == "corrupted"
        assert q.iloc[3] == "corrupted"
        # "정상 적요" → normal
        assert q.iloc[4] == "normal"

    def test_custom_min_length(self):
        """min_length는 과거 API 호환용이며 적요 품질 판정에 쓰지 않는다."""
        df = pd.DataFrame({"line_text": ["ABCD"], "header_text": [None]})
        result = add_description_quality(df, min_length=5)
        assert result["description_quality"].iloc[0] == "normal"

    def test_strip_length_not_cleaned(self):
        """strip 원본 길이 사용 — 공백 포함."""
        df = pd.DataFrame({"line_text": ["A B"], "header_text": [None]})
        # "A B" → strip → len=3 → normal (cleaned면 "AB" len=2 → poor)
        result = add_description_quality(df, min_length=3)
        assert result["description_quality"].iloc[0] == "normal"

    # ── Phase 1 scope: 의미적 충분성 판정 제외 ────────────────

    def test_low_ttr_is_not_flagged_by_phase1(self):
        """동일 단어 반복은 Phase 1 적요 품질 판정에서 의미 판단하지 않는다."""
        df = pd.DataFrame(
            {
                "line_text": ["비품 비품 비품 비품 비품"],
                "header_text": [None],
            }
        )
        result = add_description_quality(df, ttr_threshold=0.3)
        assert result["description_quality"].iloc[0] == "normal"

    def test_low_entropy_is_not_flagged_by_phase1(self):
        """저엔트로피라도 명백한 garbage가 아니면 normal."""
        df = pd.DataFrame(
            {
                "line_text": ["aaab"],
                "header_text": [None],
            }
        )
        result = add_description_quality(df, entropy_threshold=1.0)
        assert result["description_quality"].iloc[0] == "normal"

    def test_normal_ttr_and_entropy(self):
        """정상 적요는 TTR/entropy 체크를 통과하여 여전히 normal."""
        df = pd.DataFrame(
            {
                "line_text": ["3월 영업부 법인카드 결산 정리"],
                "header_text": [None],
            }
        )
        result = add_description_quality(df)
        assert result["description_quality"].iloc[0] == "normal"

    def test_multi_char_repeat_noise_is_poor(self):
        """공백 없는 다문자 반복 → corrupted."""
        df = pd.DataFrame(
            {
                "line_text": ["비품비품비품"],
                "header_text": [None],
            }
        )
        result = add_description_quality(df)
        assert result["description_quality"].iloc[0] == "corrupted"

    def test_diagnostic_flags(self):
        """line/header 결손 상태를 rule flag와 별도로 남긴다."""
        df = pd.DataFrame(
            {
                "line_text": [None, None, "x", "정상"],
                "header_text": [None, "헤더 설명", None, None],
            }
        )
        result = add_description_quality(df)

        assert result["description_both_missing"].tolist() == [True, False, False, False]
        assert result["description_line_missing_header_present"].tolist() == [
            False,
            True,
            False,
            False,
        ]
        assert result["description_is_missing_or_corrupted"].tolist() == [
            True,
            False,
            True,
            False,
        ]

    def test_description_quality_profile(self):
        """source/process/document_type별 결손률 프로파일 생성."""
        df = pd.DataFrame(
            {
                "source": ["manual", "manual", "batch", "batch"],
                "business_process": ["R2R", "R2R", "P2P", "P2P"],
                "document_type": ["SA", "SA", "KR", "KR"],
                "line_text": [None, "정상", None, None],
                "header_text": [None, None, "헤더 설명", None],
            }
        )
        add_description_quality(df)
        profile = build_description_quality_profile(df)

        manual = profile[profile["source"].eq("manual")].iloc[0]
        batch = profile[profile["source"].eq("batch")].iloc[0]
        assert manual["row_count"] == 2
        assert manual["missing_or_corrupted_rows"] == 1
        assert manual["missing_or_corrupted_rate"] == pytest.approx(0.5)
        assert batch["line_missing_header_present_rows"] == 1


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
        """description_quality + diagnostics + has_risk_keyword 컬럼 생성."""
        result = add_all_text_features(xt_base_df)
        assert "description_quality" in result.columns
        assert "description_both_missing" in result.columns
        assert "description_is_missing_or_corrupted" in result.columns
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
