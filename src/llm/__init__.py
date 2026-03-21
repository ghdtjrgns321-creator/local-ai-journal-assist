"""LLM 연동 패키지 — Ollama + Qwen3-8B 기반 감사 AI 기능.

Phase 3 모듈:
- ollama_client: Ollama REST API 래퍼
- models: LLM 응답 Pydantic 스키마
- prompt_templates: EDAProfile → 프롬프트 변환
- preprocessing_advisor: 전처리 전략 추천 오케스트레이터
"""

from src.llm.models import PreprocessingAdvice

__all__ = ["PreprocessingAdvice"]


def __getattr__(name: str):
    """Lazy import — ollama 패키지 미설치 환경에서의 ImportError 방지.

    OllamaClient/PreprocessingAdvisor는 ollama 패키지를 런타임 import하므로
    최상위 import 시 예외가 발생하지 않도록 지연 로딩한다.
    """
    if name == "OllamaClient":
        from src.llm.ollama_client import OllamaClient

        return OllamaClient
    if name == "PreprocessingAdvisor":
        from src.llm.preprocessing_advisor import PreprocessingAdvisor

        return PreprocessingAdvisor
    raise AttributeError(f"module 'src.llm' has no attribute {name!r}")
