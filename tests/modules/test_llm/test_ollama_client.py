"""ollama_client.py 테스트 — ollama 패키지 미설치 환경에서도 동작.

Why: llm dependency group이 설치되지 않은 환경(CI, dev)에서도
테스트가 통과해야 하므로 sys.modules에 mock 모듈을 주입한다.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── ollama mock 모듈 주입 ──


def _make_mock_ollama():
    """mock ollama 모듈 생성."""
    mock_module = MagicMock()
    mock_module.Client = MagicMock
    return mock_module


# ollama가 설치되지 않은 환경을 위해 sys.modules에 mock 주입
_MOCK_OLLAMA = _make_mock_ollama()


@pytest.fixture(autouse=True)
def _inject_ollama_mock():
    """모든 테스트에 ollama mock 모듈 주입."""
    with patch.dict(sys.modules, {"ollama": _MOCK_OLLAMA}):
        yield


from src.llm.ollama_client import OllamaClient  # noqa: E402


# ── Fixtures ──


@pytest.fixture()
def lm_client() -> OllamaClient:
    """설정 기본값으로 생성한 OllamaClient."""
    return OllamaClient(base_url="http://localhost:11434", model="qwen3:8b")


def _make_model(name: str) -> SimpleNamespace:
    """ollama list() 응답의 Model 객체 시뮬레이션."""
    return SimpleNamespace(model=name)


def _mock_chat_response(content: str) -> SimpleNamespace:
    """ollama chat() 응답 시뮬레이션."""
    return SimpleNamespace(message=SimpleNamespace(content=content))


# ── is_available ──


class TestIsAvailable:
    def test_available_when_model_exists(self, lm_client):
        """모델이 목록에 있으면 True."""
        mock_client = MagicMock()
        mock_client.list.return_value = SimpleNamespace(
            models=[_make_model("qwen3:8b"), _make_model("llama3:8b")],
        )
        with patch("ollama.Client", return_value=mock_client):
            assert lm_client.is_available() is True

    def test_unavailable_when_connection_fails(self, lm_client):
        """서버 접속 불가 시 False (예외 발생 없음)."""
        with patch("ollama.Client", side_effect=ConnectionError("refused")):
            assert lm_client.is_available() is False

    def test_unavailable_when_model_missing(self, lm_client):
        """서버 접속 성공이지만 모델 미설치 시 False."""
        mock_client = MagicMock()
        mock_client.list.return_value = SimpleNamespace(
            models=[_make_model("llama3:8b")],
        )
        with patch("ollama.Client", return_value=mock_client):
            assert lm_client.is_available() is False

    def test_partial_model_name_match(self, lm_client):
        """모델명 부분 매칭 (qwen3:8b-q4_K_M 등)."""
        mock_client = MagicMock()
        mock_client.list.return_value = SimpleNamespace(
            models=[_make_model("qwen3:8b-q4_K_M")],
        )
        with patch("ollama.Client", return_value=mock_client):
            assert lm_client.is_available() is True


# ── chat ──


class TestChat:
    def test_chat_returns_content(self, lm_client):
        """정상 응답 시 message.content 반환."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_chat_response('{"columns": []}')

        with patch("ollama.Client", return_value=mock_client):
            result = lm_client.chat(
                messages=[{"role": "user", "content": "hello"}],
            )
        assert result == '{"columns": []}'

    def test_chat_passes_format_schema(self, lm_client):
        """format=dict 시 Ollama에 JSON Schema가 전달되는지 확인."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_chat_response("{}")
        schema = {"type": "object", "properties": {"columns": {"type": "array"}}}

        with patch("ollama.Client", return_value=mock_client):
            lm_client.chat(
                messages=[{"role": "user", "content": "test"}],
                format=schema,
            )

        call_kwargs = mock_client.chat.call_args
        assert call_kwargs.kwargs.get("format") == schema

    def test_chat_passes_json_string_format(self, lm_client):
        """format="json" 시 문자열로 전달."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_chat_response("{}")

        with patch("ollama.Client", return_value=mock_client):
            lm_client.chat(
                messages=[{"role": "user", "content": "test"}],
                format="json",
            )
        call_kwargs = mock_client.chat.call_args
        assert call_kwargs.kwargs.get("format") == "json"

    def test_chat_no_format_omits_key(self, lm_client):
        """format=None 시 kwargs에 format 키 없음."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_chat_response("free text")

        with patch("ollama.Client", return_value=mock_client):
            lm_client.chat(
                messages=[{"role": "user", "content": "test"}],
                format=None,
            )
        call_kwargs = mock_client.chat.call_args
        assert "format" not in call_kwargs.kwargs

    def test_chat_uses_custom_temperature(self, lm_client):
        """temperature 파라미터가 options에 반영."""
        mock_client = MagicMock()
        mock_client.chat.return_value = _mock_chat_response("ok")

        with patch("ollama.Client", return_value=mock_client):
            lm_client.chat(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
            )
        call_kwargs = mock_client.chat.call_args
        assert call_kwargs.kwargs["options"]["temperature"] == 0.5

    def test_chat_timeout_raises(self, lm_client):
        """타임아웃 시 예외 전파."""
        mock_client = MagicMock()
        mock_client.chat.side_effect = TimeoutError("request timed out")

        with patch("ollama.Client", return_value=mock_client):
            with pytest.raises(TimeoutError):
                lm_client.chat(
                    messages=[{"role": "user", "content": "test"}],
                )


# ── stream_chat ──


class TestStreamChat:
    def test_stream_yields_tokens(self, lm_client):
        """스트리밍 응답이 토큰 단위로 yield."""
        chunks = [
            SimpleNamespace(message=SimpleNamespace(content="Hello")),
            SimpleNamespace(message=SimpleNamespace(content=" world")),
            SimpleNamespace(message=SimpleNamespace(content="")),
            SimpleNamespace(message=SimpleNamespace(content="!")),
        ]
        mock_client = MagicMock()
        mock_client.chat.return_value = iter(chunks)

        with patch("ollama.Client", return_value=mock_client):
            tokens = list(lm_client.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
            ))

        # 빈 문자열은 yield되지 않아야 함
        assert tokens == ["Hello", " world", "!"]

    def test_stream_passes_stream_flag(self, lm_client):
        """stream=True가 ollama.Client.chat에 전달."""
        mock_client = MagicMock()
        mock_client.chat.return_value = iter([])

        with patch("ollama.Client", return_value=mock_client):
            list(lm_client.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
            ))

        call_kwargs = mock_client.chat.call_args
        assert call_kwargs.kwargs.get("stream") is True


# ── 초기화 ──


class TestInit:
    def test_default_settings(self):
        """settings.py 기본값으로 초기화."""
        client = OllamaClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "qwen3:8b"

    def test_custom_params(self):
        """커스텀 파라미터 우선."""
        client = OllamaClient(
            base_url="http://custom:1234/",
            model="llama3:8b",
            timeout=30.0,
        )
        assert client.base_url == "http://custom:1234"
        assert client.model == "llama3:8b"
        assert client.timeout == 30.0
