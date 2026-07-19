"""LLM 연동 패키지 — OpenAI 상용 API 기반 감사 AI 기능.

Phase 3 모듈:
- api_client: ChatClient/EmbeddingClient Protocol + OpenAIClient + 팩토리 2종
- models: LLM 응답 Pydantic 스키마
- prompt_templates: EDAProfile → 프롬프트 변환
- preprocessing_advisor: 전처리 전략 추천 오케스트레이터
- sql_validator: LLM 생성 SQL 5단계 보안 검증
- prompt_presets: 감사 프리셋 12종 (Text-to-SQL 템플릿)
- text_to_sql: 하이브리드 Text-to-SQL 엔진 (프리셋 + LLM)
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
    if name in {"validate_sql", "ValidationResult"}:
        from src.llm import sql_validator

        return getattr(sql_validator, name)
    if name in {
        "AuditPreset",
        "AUDIT_PRESETS",
        "match_preset",
        "get_presets_by_category",
    }:
        from src.llm import prompt_presets

        return getattr(prompt_presets, name)
    if name in {"SQLResult", "AuditTextToSQL", "create_text_to_sql"}:
        from src.llm import text_to_sql

        return getattr(text_to_sql, name)
    if name in {"EmbeddingService", "get_embedding_service", "sanitize_for_embedding"}:
        from src.llm import embedding_service

        return getattr(embedding_service, name)
    if name == "CaseNarrativeGenerator":
        from src.llm.case_narrative_generator import CaseNarrativeGenerator

        return CaseNarrativeGenerator
    if name == "RuleFeedbackEngine":
        from src.llm.rule_feedback import RuleFeedbackEngine

        return RuleFeedbackEngine
    raise AttributeError(f"module 'src.llm' has no attribute {name!r}")
