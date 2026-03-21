"""Ollama REST API 래퍼 — 모델 가용성, 채팅, 스트리밍.

Why: ollama Python 패키지를 래핑하여 프로젝트 설정(settings.py)과 통합하고,
format 파라미터로 Pydantic JSON Schema 직접 주입(Structured Output)을 지원한다.
Phase 3 전체 LLM 모듈(text_to_sql, insight_generator 등)의 기반 모듈.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama REST API 클라이언트.

    Parameters
    ----------
    base_url : Ollama 서버 주소 (기본: settings.ollama_base_url)
    model : 사용 모델명 (기본: settings.ollama_model)
    timeout : 요청 타임아웃 초 (기본: 120.0)
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        from config.settings import get_settings

        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout

    # ── 서버 상태 ──

    def is_available(self) -> bool:
        """Ollama 서버 접속 + 모델 존재 여부 확인.

        GET /api/tags → 모델 목록에서 self.model 검색.
        연결 실패·타임아웃 시 False 반환 (예외 발생 없음).
        """
        try:
            import ollama as _ollama

            client = _ollama.Client(host=self.base_url, timeout=self.timeout)
            response = client.list()
            # response.models는 Model 객체 리스트
            model_names = [m.model for m in response.models]
            # "qwen3:8b"와 "qwen3:8b-q4_K_M" 등 부분 매칭
            available = any(self.model in name for name in model_names)
            if not available:
                logger.warning(
                    "Ollama 서버 접속 성공, 모델 '%s' 미발견. 설치된 모델: %s",
                    self.model,
                    model_names,
                )
            return available
        except Exception:
            logger.warning("Ollama 서버 접속 불가: %s", self.base_url)
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
        temperature : 생성 temperature (기본: settings.ollama_temperature)
        format : 응답 형식 제약
            - dict → Pydantic model_json_schema() (Structured Output 강제)
            - "json" → 일반 JSON 모드
            - None → 자유 텍스트

        Returns
        -------
        str : LLM 응답 텍스트
        """
        import ollama as _ollama

        if temperature is None:
            from config.settings import get_settings

            temperature = get_settings().ollama_temperature

        client = _ollama.Client(host=self.base_url, timeout=self.timeout)

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if format is not None:
            kwargs["format"] = format

        response = client.chat(**kwargs)
        return response.message.content

    # ── 스트리밍 ──

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
    ) -> Iterator[str]:
        """스트리밍 채팅 — Streamlit Chat UI용 토큰 단위 출력.

        Parameters
        ----------
        messages : OpenAI 형식 메시지 리스트
        temperature : 생성 temperature

        Yields
        ------
        str : 토큰 단위 응답 텍스트
        """
        import ollama as _ollama

        if temperature is None:
            from config.settings import get_settings

            temperature = get_settings().ollama_temperature

        client = _ollama.Client(host=self.base_url, timeout=self.timeout)
        stream = client.chat(
            model=self.model,
            messages=messages,
            options={"temperature": temperature},
            stream=True,
        )
        for chunk in stream:
            content = chunk.message.content
            if content:
                yield content
