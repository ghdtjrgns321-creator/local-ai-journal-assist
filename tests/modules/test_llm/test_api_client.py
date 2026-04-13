"""api_client.py 테스트 — openai 패키지 미설치 환경에서도 동작.

Why: llm dependency group이 설치되지 않은 환경(CI, dev)에서도
테스트가 통과해야 하므로 sys.modules에 mock 모듈을 주입한다.
"""

from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── openai mock 모듈 주입 ──


def _make_mock_openai():
    """mock openai 모듈 생성 — openai.OpenAI 생성자 + 메서드 호출 시뮬레이션."""
    mock_module = MagicMock()
    mock_module.OpenAI = MagicMock
    return mock_module


_MOCK_OPENAI = _make_mock_openai()


@pytest.fixture(autouse=True)
def _inject_openai_mock():
    """모든 테스트에 openai mock 모듈 주입."""
    with patch.dict(sys.modules, {"openai": _MOCK_OPENAI}):
        yield


from src.llm.api_client import (  # noqa: E402
    ChatClient,
    EmbeddingClient,
    OpenAIClient,
    _enforce_strict_schema,
    get_chat_client,
    get_embedding_client,
)


# ── Helpers ──


def _mock_chat_response(content: str) -> SimpleNamespace:
    """openai chat.completions.create() 응답 시뮬레이션."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            ),
        ],
    )


def _mock_stream_chunk(content: str) -> SimpleNamespace:
    """openai 스트리밍 chunk 시뮬레이션."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
            ),
        ],
    )


def _mock_embedding_response(vectors: list[list[float]]) -> SimpleNamespace:
    """openai embeddings.create() 응답 시뮬레이션."""
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=v) for v in vectors],
    )


def _make_available_mock_client() -> MagicMock:
    """is_available()이 True로 나오도록 models.list() 성공하는 mock OpenAI 인스턴스."""
    mock_client = MagicMock()
    mock_client.models.list.return_value = SimpleNamespace(data=[])
    return mock_client


@pytest.fixture()
def lm_api_client() -> OpenAIClient:
    """키/타임아웃이 주어진 OpenAIClient — is_available() 호출은 각 테스트에서 patch."""
    return OpenAIClient(
        api_key="sk-test-1234",
        model="gpt-5.4-mini",
        embedding_model="text-embedding-3-small",
        timeout=30.0,
    )


# ── Protocol 런타임 준수 ──


class TestProtocolRuntime:
    def test_openai_client_is_chat_client(self, lm_api_client):
        """OpenAIClient는 ChatClient Protocol을 만족한다."""
        assert isinstance(lm_api_client, ChatClient)

    def test_openai_client_is_embedding_client(self, lm_api_client):
        """OpenAIClient는 EmbeddingClient Protocol도 만족한다(ISP 두 계약 모두 구현)."""
        assert isinstance(lm_api_client, EmbeddingClient)

    def test_openai_client_has_provider(self, lm_api_client):
        """provider 속성은 'openai'."""
        assert lm_api_client.provider == "openai"


# ── 초기화 ──


class TestInit:
    def test_default_from_settings(self):
        """settings 기본값으로 인스턴스화."""
        client = OpenAIClient()
        # settings 기본값
        assert client.model == "gpt-5.4-mini"
        assert client.embedding_model == "text-embedding-3-small"
        assert client.timeout == 60.0

    def test_custom_params(self):
        """커스텀 파라미터 우선."""
        client = OpenAIClient(
            api_key="sk-custom",
            model="gpt-5.4",
            embedding_model="text-embedding-3-large",
            timeout=15.0,
        )
        assert client.api_key == "sk-custom"
        assert client.model == "gpt-5.4"
        assert client.embedding_model == "text-embedding-3-large"
        assert client.timeout == 15.0


# ── is_available ──


class TestIsAvailable:
    def test_unavailable_when_key_missing(self):
        """키 없음 → False."""
        client = OpenAIClient(api_key="")
        assert client.is_available() is False

    def test_available_when_models_list_succeeds(self, lm_api_client):
        """models.list() 성공 → True."""
        mock_client = _make_available_mock_client()
        with patch("openai.OpenAI", return_value=mock_client):
            assert lm_api_client.is_available() is True

    def test_unavailable_when_exception_raised(self, lm_api_client):
        """예외 발생 → False (예외 미전파)."""
        with patch("openai.OpenAI", side_effect=ConnectionError("refused")):
            assert lm_api_client.is_available() is False

    def test_unavailable_when_models_list_fails(self, lm_api_client):
        """models.list()에서 예외 → False."""
        mock_client = MagicMock()
        mock_client.models.list.side_effect = RuntimeError("quota exceeded")
        with patch("openai.OpenAI", return_value=mock_client):
            assert lm_api_client.is_available() is False


# ── chat ──


class TestChat:
    def test_chat_returns_content(self, lm_api_client):
        """정상 응답 → choices[0].message.content 반환."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_chat_response("hello world")

        with patch("openai.OpenAI", return_value=mock_client):
            result = lm_api_client.chat(
                messages=[{"role": "user", "content": "ping"}],
            )
        assert result == "hello world"

    def test_chat_passes_json_schema_with_strict(self, lm_api_client):
        """format=dict → response_format에 json_schema + strict=True 전달."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_chat_response("{}")
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        }

        with patch("openai.OpenAI", return_value=mock_client):
            lm_api_client.chat(
                messages=[{"role": "user", "content": "ping"}],
                format=schema,
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        rf = call_kwargs["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["name"] == "response"
        # strict 모드 정규화: additionalProperties=False, required 주입
        norm = rf["json_schema"]["schema"]
        assert norm["additionalProperties"] is False
        assert norm["required"] == ["answer"]

    def test_chat_passes_json_object_mode(self, lm_api_client):
        """format='json' → response_format={'type': 'json_object'}."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_chat_response("{}")

        with patch("openai.OpenAI", return_value=mock_client):
            lm_api_client.chat(
                messages=[{"role": "user", "content": "ping"}],
                format="json",
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_chat_no_format_omits_response_format(self, lm_api_client):
        """format=None → response_format 키 부재."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_chat_response("free text")

        with patch("openai.OpenAI", return_value=mock_client):
            lm_api_client.chat(
                messages=[{"role": "user", "content": "ping"}],
                format=None,
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in call_kwargs

    def test_chat_uses_custom_temperature(self, lm_api_client):
        """temperature 오버라이드 반영."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_chat_response("ok")

        with patch("openai.OpenAI", return_value=mock_client):
            lm_api_client.chat(
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.7,
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7

    def test_chat_timeout_raises(self, lm_api_client):
        """타임아웃 예외 전파."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("timed out")

        with patch("openai.OpenAI", return_value=mock_client):
            with pytest.raises(TimeoutError):
                lm_api_client.chat(messages=[{"role": "user", "content": "ping"}])


# ── _enforce_strict_schema ──


class TestEnforceStrictSchema:
    def test_flat_object_injection(self):
        """평탄한 object → additionalProperties=False + required 주입."""
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
        }
        out = _enforce_strict_schema(schema)
        assert out["additionalProperties"] is False
        assert set(out["required"]) == {"a", "b"}

    def test_nested_object_injection(self):
        """properties 내부 중첩 object도 재귀 적용."""
        schema = {
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {"inner": {"type": "string"}},
                },
            },
        }
        out = _enforce_strict_schema(schema)
        inner_obj = out["properties"]["outer"]
        assert inner_obj["additionalProperties"] is False
        assert inner_obj["required"] == ["inner"]

    def test_defs_block_injection(self):
        """$defs 내부 object 재귀 적용."""
        schema = {
            "type": "object",
            "properties": {"x": {"$ref": "#/$defs/Item"}},
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
        out = _enforce_strict_schema(schema)
        item = out["$defs"]["Item"]
        assert item["additionalProperties"] is False
        assert item["required"] == ["name"]

    def test_items_array_object(self):
        """배열 요소 타입(object in items) 재귀 적용."""
        schema = {
            "type": "object",
            "properties": {
                "list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"v": {"type": "number"}},
                    },
                },
            },
        }
        out = _enforce_strict_schema(schema)
        items = out["properties"]["list"]["items"]
        assert items["additionalProperties"] is False
        assert items["required"] == ["v"]

    def test_anyof_oneof_injection(self):
        """anyOf / oneOf 내부 object 재귀 적용."""
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}},
                {"type": "object", "properties": {"b": {"type": "integer"}}},
            ],
        }
        out = _enforce_strict_schema(schema)
        for branch in out["anyOf"]:
            assert branch["additionalProperties"] is False
            assert len(branch["required"]) == 1

    def test_original_not_mutated(self):
        """deepcopy 보장 — 원본 dict는 변경되지 않음."""
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        _enforce_strict_schema(schema)
        assert "additionalProperties" not in schema
        assert "required" not in schema


# ── stream_chat ──


class TestStreamChat:
    def test_stream_yields_tokens(self, lm_api_client):
        """스트리밍 응답이 토큰 단위로 yield."""
        chunks = [
            _mock_stream_chunk("Hello"),
            _mock_stream_chunk(" world"),
            _mock_stream_chunk(""),     # 빈 delta는 skip
            _mock_stream_chunk("!"),
            _mock_stream_chunk(None),   # None delta도 skip
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter(chunks)

        with patch("openai.OpenAI", return_value=mock_client):
            tokens = list(lm_api_client.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
            ))

        assert tokens == ["Hello", " world", "!"]

    def test_stream_passes_stream_flag(self, lm_api_client):
        """stream=True가 API에 전달."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = iter([])

        with patch("openai.OpenAI", return_value=mock_client):
            list(lm_api_client.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
            ))

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["stream"] is True


# ── embed ──


class TestEmbed:
    def test_embed_returns_vectors(self, lm_api_client):
        """배치 입력 → 벡터 리스트 반환."""
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = _mock_embedding_response([
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ])

        with patch("openai.OpenAI", return_value=mock_client):
            result = lm_api_client.embed(["first", "second"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    def test_embed_passes_batch_input(self, lm_api_client):
        """input=list[str] 그대로 API에 전달(1회 호출)."""
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = _mock_embedding_response([[0.0]])

        with patch("openai.OpenAI", return_value=mock_client):
            lm_api_client.embed(["a"])

        assert mock_client.embeddings.create.call_count == 1
        call_kwargs = mock_client.embeddings.create.call_args.kwargs
        assert call_kwargs["input"] == ["a"]
        assert call_kwargs["model"] == "text-embedding-3-small"


# ── 팩토리 ──


class TestGetChatClient:
    def test_light_tier_uses_light_model(self):
        """tier='light' → settings.openai_light_model 사용."""
        with (
            patch("src.llm.api_client.OpenAIClient.is_available", return_value=True),
            patch.object(OpenAIClient, "api_key", "sk-test", create=True),
        ):
            # settings 로드를 위한 환경 보강
            client = get_chat_client("light")
            assert client.model == "gpt-5.4-mini"

    def test_reasoning_tier_uses_reasoning_model(self):
        """tier='reasoning' → settings.openai_reasoning_model."""
        with patch("src.llm.api_client.OpenAIClient.is_available", return_value=True):
            client = get_chat_client("reasoning")
            assert client.model == "gpt-5.4"

    def test_default_tier_is_light(self):
        """기본 tier는 light."""
        with patch("src.llm.api_client.OpenAIClient.is_available", return_value=True):
            client = get_chat_client()
            assert client.model == "gpt-5.4-mini"

    def test_invalid_tier_raises_value_error(self):
        """지원하지 않는 tier → ValueError."""
        with pytest.raises(ValueError, match="tier"):
            get_chat_client("heavy")  # type: ignore[arg-type]

    def test_unavailable_raises_runtime_error(self):
        """is_available=False → RuntimeError."""
        with patch("src.llm.api_client.OpenAIClient.is_available", return_value=False):
            with pytest.raises(RuntimeError, match="OpenAI LLM unavailable"):
                get_chat_client("light")


class TestGetEmbeddingClient:
    def test_returns_openai_client(self):
        """get_embedding_client → OpenAIClient with embedding_model."""
        with patch("src.llm.api_client.OpenAIClient.is_available", return_value=True):
            client = get_embedding_client()
            assert isinstance(client, OpenAIClient)
            assert client.embedding_model == "text-embedding-3-small"

    def test_unavailable_raises_runtime_error(self):
        """is_available=False → RuntimeError."""
        with patch("src.llm.api_client.OpenAIClient.is_available", return_value=False):
            with pytest.raises(RuntimeError, match="OpenAI embedding unavailable"):
                get_embedding_client()


# ── settings validator 경고 로그 ──


class TestSettingsWarning:
    def test_empty_api_key_emits_warning(self, caplog):
        """openai_api_key가 빈 문자열이면 경고 로그 발생, 인스턴스화는 성공."""
        from config.settings import AuditSettings

        with caplog.at_level(logging.WARNING):
            AuditSettings(openai_api_key="")

        assert any(
            "openai_api_key 미설정" in rec.message for rec in caplog.records
        )
