"""WU-28 — LLM 헤더 탐지 보조 테스트.

구조 스코어가 effective_threshold 미만일 때 LLM이 confidence를 복원하는지,
LLM 미가용/JSON 실패/설정 off 시 기존 폴백이 유지되는지 검증한다.
모든 케이스에서 OpenAI SDK는 MagicMock으로 차단 — 네트워크 호출 0건.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from config.settings import get_keywords, get_settings
from src.ingest import header_detector
from src.ingest.header_detector import (
    _serialize_context,
    detect_header_row,
)


# ── 공용 헬퍼 ─────────────────────────────────────────────


@pytest.fixture
def keywords() -> dict:
    """keywords.yaml 로드."""
    return get_keywords()


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """각 테스트마다 get_settings 캐시 초기화 — 설정 변경 테스트 간섭 방지."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def low_conf_df() -> pd.DataFrame:
    """키워드 0개 + 구조 스코어가 effective_threshold(0.7) 미만인 DataFrame.

    모든 셀이 숫자라 type_diversity=0 / string_ratio=0 / uniqueness 낮음 →
    structural score ≈ 0.23. 키워드 0개로 effective_threshold=0.7 승격 → LLM 분기 진입.
    LLM이 0.0 반환 시 여전히 0.7 미만이므로 header_row=None,
    0.85 반환 시 max()로 0.85 → header_row=0으로 복원된다.
    """
    return pd.DataFrame([
        [1, 1, 1],
        [2, 2, 2],
        [3, 3, 3],
    ])


@pytest.fixture
def high_conf_df() -> pd.DataFrame:
    """키워드 완벽 매칭 + 구조 스코어 >= 0.7 DataFrame — LLM 미호출 대상."""
    return pd.DataFrame([
        ["전표번호", "전표일자", "계정코드", "차변금액", "대변금액"],
        ["JE001", "2025-01-01", "101", 10000, 0],
        ["JE002", "2025-01-02", "102", 0, 5000],
    ])


def _mock_client(chat_response: str) -> MagicMock:
    """ChatClient Protocol을 만족하는 MagicMock."""
    client = MagicMock()
    client.is_available.return_value = True
    client.chat.return_value = chat_response
    return client


# ── 테스트 1: LLM 보정 성공 → header_row 복원 ─────────────


def test_llm_boost_recovers_header(low_conf_df, keywords, monkeypatch):
    """is_header=True + confidence=0.85 → LLM 값으로 직접 대체되어 threshold 통과.

    구조 스코어(0.23)가 아닌 LLM confidence(0.85)가 그대로 반영되고,
    llm_assisted=True로 출처가 구분되며, UI 메시지에 "LLM 보조" 문구가 포함된다.
    """
    chat_response = json.dumps({
        "is_header": True,
        "confidence": 0.85,
        "reason": "상위 행이 영문 컬럼명 패턴",
    })
    mock_client = _mock_client(chat_response)
    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        lambda tier="light": mock_client,
    )

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row == 0
    assert result.confidence == pytest.approx(0.85)
    assert result.llm_assisted is True
    assert "LLM 보조" in result.message
    mock_client.chat.assert_called_once()


# ── 테스트 2: LLM 보정 실패(is_header=False) → 기존 폴백 ─────


def test_llm_boost_rejects_header(low_conf_df, keywords, monkeypatch):
    """is_header=False면 LLM 기여 0.0 → 구조 스코어만으로는 threshold 미달 → 실패."""
    chat_response = json.dumps({
        "is_header": False,
        "confidence": 0.1,
        "reason": "모든 행이 데이터 값에 가까움",
    })
    mock_client = _mock_client(chat_response)
    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        lambda tier="light": mock_client,
    )

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row is None
    assert result.llm_assisted is False
    mock_client.chat.assert_called_once()


def test_llm_rejects_ignores_high_confidence(low_conf_df, keywords, monkeypatch):
    """is_header=False이면 confidence 값이 높아도 0.0으로 반환되어야 한다.

    _llm_header_check 분기 로직 단위 검증 — is_header 플래그가 우선이다.
    """
    chat_response = json.dumps({
        "is_header": False,
        "confidence": 0.9,  # False라면 값이 높아도 무시되어야 함
        "reason": "헤더 아님",
    })
    mock_client = _mock_client(chat_response)
    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        lambda tier="light": mock_client,
    )

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row is None
    assert result.llm_assisted is False


# ── 테스트 3: 구조 스코어 충분 → LLM 미호출 ────────────────


def test_high_structural_skips_llm(high_conf_df, keywords, monkeypatch):
    """이미 confidence >= effective_threshold이면 LLM 호출 0회."""
    mock_client = _mock_client("SHOULD_NOT_BE_CALLED")
    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        lambda tier="light": mock_client,
    )

    result = detect_header_row(high_conf_df, keywords)

    assert result.header_row == 0
    assert result.confidence >= 0.7
    mock_client.chat.assert_not_called()


# ── 테스트 4: LLM 미가용(RuntimeError) → 기존 폴백 ────────


def test_llm_unavailable_falls_back(low_conf_df, keywords, monkeypatch):
    """get_chat_client RuntimeError → 기존 동작(header_row=None) 유지.

    메시지 단언은 구조적 필드로 대체 — 한국어 리터럴 변경에 독립적.
    """

    def _raise_runtime(tier="light"):
        raise RuntimeError("openai_api_key 미설정")

    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        _raise_runtime,
    )

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row is None
    assert result.llm_assisted is False


# ── 테스트 5: 설정 off → LLM 호출 자체를 생략 ─────────────


def test_feature_flag_disables_llm(low_conf_df, keywords, monkeypatch):
    """enable_llm_header_fallback=False면 get_chat_client 호출 없이 즉시 실패."""
    monkeypatch.setenv("AUDIT_ENABLE_LLM_HEADER_FALLBACK", "False")
    get_settings.cache_clear()

    # get_chat_client가 호출되면 테스트 실패하도록 sentinel
    sentinel = MagicMock(side_effect=AssertionError("LLM should not be called"))
    monkeypatch.setattr("src.llm.api_client.get_chat_client", sentinel)

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row is None
    sentinel.assert_not_called()


# ── 테스트 6: JSON 파싱 실패 → 폴백 ──────────────────────


def test_llm_invalid_json_falls_back(low_conf_df, keywords, monkeypatch):
    """LLM이 잘못된 JSON 반환 시 예외 흡수 + 기존 실패 경로."""
    mock_client = _mock_client("not-a-valid-json{{")
    monkeypatch.setattr(
        "src.llm.api_client.get_chat_client",
        lambda tier="light": mock_client,
    )

    result = detect_header_row(low_conf_df, keywords)

    assert result.header_row is None
    mock_client.chat.assert_called_once()


# ── 테스트 7: _serialize_context 직렬화 규약 ─────────────


class TestSerializeContext:
    """환각 방지 직렬화 헬퍼 단위 검증."""

    def test_nan_replaced_with_empty_string(self):
        """NaN 셀이 'nan' 문자열로 누출되지 않고 빈 문자열로 치환된다."""
        df = pd.DataFrame([
            ["전표번호", None, "차변"],
            [1, 2, 3],
        ])
        serialized = _serialize_context(df)
        assert "nan" not in serialized.lower().split("\t")
        # NaN 위치가 빈 문자열이 되어 탭이 연속으로 나타남
        assert "전표번호\t\t차변" in serialized

    def test_row_label_prefix(self):
        """각 행이 [Row N] 라벨로 시작 — pandas 0-based 인덱스 고정."""
        df = pd.DataFrame([
            ["a", "b"],
            ["c", "d"],
            ["e", "f"],
        ])
        serialized = _serialize_context(df)
        lines = serialized.split("\n")
        assert lines[0].startswith("[Row 0]")
        assert lines[1].startswith("[Row 1]")
        assert lines[2].startswith("[Row 2]")

    def test_tab_separator_and_strip(self):
        """셀은 탭 구분, 좌우 공백은 strip."""
        df = pd.DataFrame([["  foo  ", "bar"]])
        serialized = _serialize_context(df)
        assert serialized == "[Row 0] foo\tbar"

    def test_max_rows_cap(self):
        """max_rows를 초과하는 DataFrame도 상위 N행만 직렬화."""
        df = pd.DataFrame([[i, i + 1] for i in range(20)])
        serialized = _serialize_context(df, max_rows=3)
        assert len(serialized.split("\n")) == 3
