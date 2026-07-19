"""상용 LLM API 클라이언트 — OpenAI (GPT-5.4 / GPT-5.4-mini 2티어).

Phase 3 LLM 기능의 토대. ChatClient / EmbeddingClient Protocol로
호출부가 필요한 계약만 의존하도록 분리한다(ISP).

2티어 모델 정책
---------------
- light(gpt-5.4-mini)   : 전처리 제안, 헤더 보정, Text-to-SQL, NLP 탐지 등 일상 호출
- reasoning(gpt-5.4)    : 최종 감사 보고서, 복잡 인사이트, XAI 내러티브 등 심층 추론

팩토리
------
- get_chat_client(tier) : 티어에 맞는 채팅 모델로 OpenAIClient 구성
- get_embedding_client(): 임베딩 모델로 OpenAIClient 구성 (ISP상 별도 타입)
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Iterator, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

Tier = Literal["light", "reasoning"]


# ── Protocol 정의 (ISP로 Chat과 Embedding 분리) ──


@runtime_checkable
class ChatClient(Protocol):
    """자연어 추론/생성 전용 계약.

    provider/model은 클래스 속성 또는 인스턴스 속성으로 접근 가능해야 한다.
    """

    provider: str
    model: str

    def is_available(self) -> bool: ...

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        format: dict | str | None = None,
    ) -> str: ...

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
    ) -> Iterator[str]: ...


@runtime_checkable
class EmbeddingClient(Protocol):
    """텍스트 → 벡터 변환 전용 계약."""

    provider: str

    def is_available(self) -> bool: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ── Strict JSON Schema 정규화 헬퍼 ──


def _enforce_strict_schema(schema: dict) -> dict:
    """OpenAI Structured Outputs strict 모드 호환 정규화.

    Why
    ----
    strict: True는 모든 object 노드에서
      - additionalProperties: False
      - required = list(properties)
    를 강제한다. Pydantic model_json_schema() 결과는 이 조건을
    자동 충족하지 않으므로, API 호출 직전에 재귀적으로 주입해야 한다.

    재귀 범위: properties, $defs, definitions, anyOf, oneOf, items 전체.

    선택적 필드가 필요하면 호출자 Pydantic 모델에서 `field: str | None = None`
    패턴으로 선언해 JSON Schema 타입이 ["string", "null"]이 되도록 할 것.

    원본 dict는 변경하지 않는다(deepcopy).
    """
    normalized = deepcopy(schema)

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(normalized)
    return normalized


# ── OpenAIClient — ChatClient + EmbeddingClient 동시 구현 ──


class OpenAIClient:
    """OpenAI 상용 API 래퍼.

    ChatClient와 EmbeddingClient Protocol을 모두 만족한다.
    티어 선택은 팩토리(get_chat_client)가 담당하며, 직접 생성 시
    model 인자로 임의 OpenAI 모델명을 지정할 수 있다.
    """

    provider: str = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        from config.settings import get_settings

        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.model = model or settings.openai_light_model
        self.embedding_model = embedding_model or settings.openai_embedding_model
        self.timeout = timeout if timeout is not None else settings.openai_timeout

    # ── 서버/키 상태 ──

    def is_available(self) -> bool:
        """키 존재 + models.list() 1회 호출 성공 여부.

        연결 실패·타임아웃 시 False 반환(예외 미전파).
        """
        if not self.api_key:
            return False
        try:
            import openai

            client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
            client.models.list()
            return True
        except Exception as exc:
            logger.warning("OpenAI 접속 불가: %s", exc)
            return False

    # ── 채팅 ──

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        format: dict | str | None = None,
    ) -> str:
        """동기 채팅 완료 호출.

        Parameters
        ----------
        messages : OpenAI 형식 메시지 리스트 [{"role": ..., "content": ...}]
        temperature : 생성 temperature (기본: settings.openai_temperature)
        format :
            - dict → JSON Schema Structured Output (strict=True, 자동 정규화)
            - "json" → JSON 모드 (스키마 강제 없음)
            - None → 자유 텍스트

        Returns
        -------
        str : LLM 응답 텍스트
        """
        import openai

        if temperature is None:
            from config.settings import get_settings

            temperature = get_settings().openai_temperature

        client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if isinstance(format, dict):
            # strict 모드 호환 스키마로 정규화
            normalized = _enforce_strict_schema(format)
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": normalized,
                    "strict": True,
                },
            }
        elif format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    # ── 스트리밍 ──

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
    ) -> Iterator[str]:
        """스트리밍 채팅 — Streamlit Chat UI용 토큰 단위 출력."""
        import openai

        if temperature is None:
            from config.settings import get_settings

            temperature = get_settings().openai_temperature

        client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
        stream = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    # ── 임베딩 ──

    def embed(self, texts: list[str]) -> list[list[float]]:
        """배치 임베딩 — OpenAI는 input=list[str] 네이티브 지원.

        Parameters
        ----------
        texts : 임베딩 대상 문자열 리스트

        Returns
        -------
        list[list[float]] : 각 입력에 대응하는 벡터 리스트 (입력 순서 보존)
        """
        import openai

        client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
        response = client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]


# ── 팩토리 ──


def get_chat_client(tier: Tier = "light") -> ChatClient:
    """티어에 맞는 OpenAI 채팅 클라이언트.

    - light    : settings.openai_light_model (gpt-5.4-mini)
    - reasoning: settings.openai_reasoning_model (gpt-5.4)

    Raises
    ------
    ValueError   : 지원하지 않는 tier
    RuntimeError : is_available() False (키 없음/연결 실패)
    """
    if tier not in ("light", "reasoning"):
        raise ValueError(f"tier는 'light' 또는 'reasoning'만 허용: {tier!r}")

    from config.settings import get_settings

    settings = get_settings()
    model = settings.openai_reasoning_model if tier == "reasoning" else settings.openai_light_model
    client = OpenAIClient(api_key=settings.openai_api_key, model=model)
    if not client.is_available():
        raise RuntimeError(
            f"OpenAI LLM unavailable — check openai_api_key / connectivity (tier={tier})"
        )
    return client


def get_embedding_client() -> EmbeddingClient:
    """OpenAI 임베딩 전용 클라이언트 (기본 text-embedding-3-small).

    Raises
    ------
    RuntimeError : is_available() False
    """
    from config.settings import get_settings

    settings = get_settings()
    client = OpenAIClient(
        api_key=settings.openai_api_key,
        embedding_model=settings.openai_embedding_model,
    )
    if not client.is_available():
        raise RuntimeError("OpenAI embedding unavailable — check openai_api_key / connectivity")
    return client
