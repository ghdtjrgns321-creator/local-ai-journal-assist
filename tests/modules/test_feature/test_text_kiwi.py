"""WU-19: kiwipiepy 형태소 분석 테스트.

_has_korean 분기 / _tokenize_kiwi 배치 호출 / add_morpheme_features DataFrame 함수 /
싱글톤 보장 / Kiwi iterable 호출 검증.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.feature import text_features as tf
from src.feature.text_features import (
    _MORPHEME_TAGS,
    _get_kiwi,
    _has_korean,
    _tokenize_kiwi,
    add_morpheme_features,
)

# ── 모듈 공용 fixture ─────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _kiwi_ready():
    """Kiwi 인스턴스를 모듈 시작 시 1회 미리 로드.

    Why: test_batch_call_single_invocation은 `_get_kiwi()`로 싱글톤 인스턴스의
    tokenize 메서드를 patch하는데, 테스트 순서에 따라 싱글톤이 미초기화 상태일 수
    있다. module-scope로 먼저 로드해 모든 테스트가 동일한 인스턴스를 공유하도록
    보장하고, 테스트 실행 시간도 절약한다.
    """
    _get_kiwi()
    yield


# ── _has_korean ───────────────────────────────────────────────────


class TestHasKorean:
    """한국어 판별 분기 로직."""

    @pytest.mark.parametrize("text", ["식대", "3월 영업부", "ABC가나다", "회사에서"])
    def test_contains_hangul(self, text):
        """한글 음절이 하나라도 있으면 True."""
        assert _has_korean(text) is True

    @pytest.mark.parametrize("text", ["XYZ Corp", "invoice", "12345", "!@#$%"])
    def test_no_hangul(self, text):
        """영문/숫자/기호만 → False."""
        assert _has_korean(text) is False

    @pytest.mark.parametrize("text", ["ㅋㅋㅋ", "ㅏㅏ"])
    def test_jamo_only_is_not_hangul(self, text):
        """자모만 있는 경우는 한글 음절이 아니므로 False (Kiwi 호출 회피)."""
        assert _has_korean(text) is False

    def test_empty_string(self):
        """빈 문자열 → False."""
        assert _has_korean("") is False

    def test_none(self):
        """None → False (NaN 방어)."""
        assert _has_korean(None) is False

    def test_nan(self):
        """float NaN → False."""
        import numpy as np
        assert _has_korean(np.nan) is False


# ── _tokenize_kiwi ────────────────────────────────────────────────


class TestTokenizeKiwi:
    """배치 토큰화 — Kiwi iterable 입력 + 인덱스 역매핑."""

    def test_korean_text_extracts_content_morphemes(self):
        """한국어 적요 → NNG/NNP/VV/VA 형태소만 추출."""
        result = _tokenize_kiwi(["상품권 구매 정산"])
        assert len(result) == 1
        # 모든 토큰이 의미 형태소여야 함
        assert set(result[0]) == {"상품권", "구매", "정산"}

    def test_particles_and_endings_excluded(self):
        """조사(JKB)·어미(EF)는 제외."""
        result = _tokenize_kiwi(["회사에서"])
        # "회사"(NNG)만 통과, "에서"(JKB)는 제외
        assert result[0] == ["회사"]

    def test_dependent_noun_excluded(self):
        """의존명사(NNB)는 현재 정책상 제외 — "3월"의 "월"은 NNB라 빠진다."""
        result = _tokenize_kiwi(["3월 영업부 식대"])
        # "영업부"(NNG), "식대"(NNG)만 통과
        assert result[0] == ["영업부", "식대"]

    def test_english_returns_empty(self):
        """영문 입력 → [] (Kiwi 호출 자체를 회피)."""
        result = _tokenize_kiwi(["XYZ Corp invoice"])
        assert result == [[]]

    def test_empty_string_returns_empty(self):
        """빈 문자열 → []."""
        result = _tokenize_kiwi([""])
        assert result == [[]]

    def test_mixed_batch_preserves_index_mapping(self):
        """혼합 배치 — 한글/영문/빈값 섞여도 입력 인덱스 순서 보존."""
        texts = [
            "XYZ invoice",        # 0: 영문 → []
            "상품권 구매 정산",    # 1: 한글 → 3개 토큰
            "",                   # 2: 빈값 → []
            "일반 매출 거래",      # 3: 한글 → 3개 토큰
            "ABC",                # 4: 영문 → []
        ]
        result = _tokenize_kiwi(texts)

        assert len(result) == 5
        assert result[0] == []
        assert set(result[1]) == {"상품권", "구매", "정산"}
        assert result[2] == []
        assert set(result[3]) == {"일반", "매출", "거래"}
        assert result[4] == []

    def test_all_english_skips_kiwi_call(self, monkeypatch):
        """전체 입력이 영문이면 Kiwi가 전혀 호출되지 않아야 한다 (싱글톤 lazy-load).

        Why _KIWI_INSTANCE 초기화: 이전 테스트가 싱글톤을 채워 놓으면 spy가 우연히
        실제 Kiwi 인스턴스를 반환해 tokenize까지 이어질 수 있다. 명시적으로 None
        으로 되돌려 spy 동작을 독립적으로 검증한다.
        """
        monkeypatch.setattr(tf, "_KIWI_INSTANCE", None)

        call_count = {"n": 0}

        def _spy_get_kiwi():
            call_count["n"] += 1
            raise AssertionError("_get_kiwi가 호출되면 안 됨")

        monkeypatch.setattr(tf, "_get_kiwi", _spy_get_kiwi)
        result = _tokenize_kiwi(["ABC", "XYZ", ""])

        assert result == [[], [], []]
        assert call_count["n"] == 0  # _get_kiwi 호출조차 없어야 함

    def test_batch_call_single_invocation(self, monkeypatch):
        """Kiwi iterable 입력 검증 — 한국어 행은 **단일 tokenize 호출로 배치 처리**.

        Why: 개별 문자열로 N회 호출되면 C++ 레이어 멀티스레딩 이점을 잃는다.
        """
        # 실제 Kiwi 인스턴스 확보
        kiwi = _get_kiwi()

        call_args: list = []
        original_tokenize = kiwi.tokenize

        def _spy_tokenize(arg, *args, **kwargs):
            call_args.append(arg)
            return original_tokenize(arg, *args, **kwargs)

        monkeypatch.setattr(kiwi, "tokenize", _spy_tokenize)

        texts = ["ABC", "상품권 구매", "XYZ", "일반 매출", "def"]
        _tokenize_kiwi(texts)

        # tokenize는 정확히 1회, 한국어 2건이 담긴 리스트로 호출되어야 함
        assert len(call_args) == 1
        batched_input = call_args[0]
        assert isinstance(batched_input, list)
        assert batched_input == ["상품권 구매", "일반 매출"]


# ── add_morpheme_features ─────────────────────────────────────────


class TestAddMorphemeFeatures:
    """DataFrame 레벨 피처 함수."""

    def test_creates_column(self):
        """morpheme_tokens 컬럼 생성."""
        df = pd.DataFrame({
            "line_text": ["상품권 구매"],
            "header_text": ["월말 정리"],
        })
        result = add_morpheme_features(df)
        assert "morpheme_tokens" in result.columns

    def test_combines_line_and_header(self):
        """line_text + header_text concat 후 토큰화 (_combine_text 재사용 확인)."""
        df = pd.DataFrame({
            "line_text": ["상품권"],
            "header_text": ["구매 정산"],
        })
        result = add_morpheme_features(df)
        tokens = result["morpheme_tokens"].iloc[0]
        # concat 결과 "상품권 구매 정산" → 3개 토큰 모두 추출
        assert set(tokens) == {"상품권", "구매", "정산"}

    def test_mixed_rows(self):
        """한국어/영문/NaN 혼재 — 각 행별 적절히 분기."""
        df = pd.DataFrame({
            "line_text": ["상품권 구매", "XYZ invoice", None, "일반 매출 거래"],
            "header_text": [None, None, None, None],
        })
        result = add_morpheme_features(df)
        tokens = result["morpheme_tokens"]

        assert set(tokens.iloc[0]) == {"상품권", "구매"}
        assert tokens.iloc[1] == []  # 영문
        assert tokens.iloc[2] == []  # NaN
        assert set(tokens.iloc[3]) == {"일반", "매출", "거래"}

    def test_no_text_columns(self):
        """텍스트 컬럼이 전혀 없는 DataFrame — 에러 없이 빈 리스트 생성."""
        df = pd.DataFrame({"debit_amount": [1000.0, 2000.0]})
        result = add_morpheme_features(df)
        assert "morpheme_tokens" in result.columns
        assert result["morpheme_tokens"].tolist() == [[], []]

    def test_inplace_returns_same_object(self):
        """in-place 수정 + 동일 객체 반환 (기존 피처 함수와 동일 계약)."""
        df = pd.DataFrame({"line_text": ["매출"], "header_text": [None]})
        result = add_morpheme_features(df)
        assert result is df


# ── _get_kiwi 싱글톤 ──────────────────────────────────────────────


class TestKiwiSingleton:
    """Kiwi 인스턴스 싱글톤 보장."""

    def test_returns_same_instance(self):
        """_get_kiwi() 반복 호출 → 동일 객체 (is 비교)."""
        k1 = _get_kiwi()
        k2 = _get_kiwi()
        assert k1 is k2

    def test_morpheme_tags_is_frozenset(self):
        """_MORPHEME_TAGS는 불변 집합 — 런타임 변조 방지."""
        assert isinstance(_MORPHEME_TAGS, frozenset)
        assert _MORPHEME_TAGS == frozenset({"NNG", "NNP", "VV", "VA"})


# ── add_all_text_features 오케스트레이터 통합 ────────────────────


class TestOrchestratorIntegration:
    """add_all_text_features에 morpheme_tokens가 함께 생성되는지 회귀 방지."""

    def test_all_three_columns_created(self, xt_base_df):
        """description_quality + has_risk_keyword + morpheme_tokens 3개 컬럼."""
        from src.feature.text_features import add_all_text_features

        result = add_all_text_features(xt_base_df)
        assert "description_quality" in result.columns
        assert "has_risk_keyword" in result.columns
        assert "morpheme_tokens" in result.columns

    def test_korean_row_has_tokens(self, xt_base_df):
        """한국어 적요 행은 형태소 토큰이 1개 이상 추출되어야 함."""
        from src.feature.text_features import add_all_text_features

        result = add_all_text_features(xt_base_df)
        # idx 0: "상품권 구매" + "월말 정리" → 토큰 존재
        assert len(result["morpheme_tokens"].iloc[0]) >= 2

    def test_missing_text_row_has_empty_tokens(self, xt_base_df):
        """텍스트 없는 행은 [] 반환."""
        from src.feature.text_features import add_all_text_features

        result = add_all_text_features(xt_base_df)
        # idx 4: line/header 모두 None → []
        assert result["morpheme_tokens"].iloc[4] == []
