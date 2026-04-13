"""LLM 연동 패키지 — OpenAI 상용 API 기반 감사 AI 기능.

Phase 3 모듈:
- api_client: ChatClient/EmbeddingClient Protocol + OpenAIClient + 팩토리 2종
- models: LLM 응답 Pydantic 스키마
- prompt_templates: EDAProfile → 프롬프트 변환
- preprocessing_advisor: 전처리 전략 추천 오케스트레이터
"""

from src.llm.models import PreprocessingAdvice

__all__ = ["PreprocessingAdvice"]


def __getattr__(name: str):
    """Lazy import — 상용 SDK(openai) 미설치 환경에서의 ImportError 방지.

    api_client/PreprocessingAdvisor는 openai 패키지를 런타임 import하므로
    최상위 import 시 예외가 발생하지 않도록 지연 로딩한다.
    """
    if name == "PreprocessingAdvisor":
        from src.llm.preprocessing_advisor import PreprocessingAdvisor

        return PreprocessingAdvisor
    if name in {
        "ChatClient",
        "EmbeddingClient",
        "OpenAIClient",
        "get_chat_client",
        "get_embedding_client",
    }:
        from src.llm import api_client

        return getattr(api_client, name)
    raise AttributeError(f"module 'src.llm' has no attribute {name!r}")
