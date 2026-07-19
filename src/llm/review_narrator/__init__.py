"""Phase 3 v2 — Review Queue Narrator (WU-31).

PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 입력받아 LLM이
(a) 후보 Top-N 재정렬 (b) 의심 근거 서술 + 인용 (c) 감사인 다음 행동 제안.

Sprint A 산출물: models.py (Pydantic 스키마) + citation_validator.py.
나머지 모듈은 후속 Sprint(B~F)에서 추가된다.

단일 출처: docs/archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md
"""

from src.llm.review_narrator.audit_logger import log_narrate_event
from src.llm.review_narrator.budget_guard import BudgetGuard
from src.llm.review_narrator.cache import (
    compute_input_hash,
    read_narrative,
    upsert_narrative,
)
from src.llm.review_narrator.candidate_builder import build_candidates
from src.llm.review_narrator.citation_validator import (
    CitationValidationResult,
    validate_citations,
)
from src.llm.review_narrator.eval_harness import (
    CallSample,
    EvalReport,
    evaluate_samples,
    save_eval_report,
)
from src.llm.review_narrator.models import (
    ConfidenceLevel,
    EvidenceType,
    ReasoningEvidence,
    ReasoningItem,
    ReviewNarrative,
    SuggestedAction,
    SuggestedActionType,
    build_review_narrative_schema,
)
from src.llm.review_narrator.narrator import (
    DEFAULT_SYSTEM_PROMPT,
    NarratorResult,
    narrate,
)
from src.llm.review_narrator.sanitizer import Sanitizer

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "BudgetGuard",
    "CallSample",
    "CitationValidationResult",
    "ConfidenceLevel",
    "EvalReport",
    "EvidenceType",
    "NarratorResult",
    "ReasoningEvidence",
    "ReasoningItem",
    "ReviewNarrative",
    "Sanitizer",
    "SuggestedAction",
    "SuggestedActionType",
    "build_candidates",
    "build_review_narrative_schema",
    "compute_input_hash",
    "evaluate_samples",
    "log_narrate_event",
    "narrate",
    "read_narrative",
    "save_eval_report",
    "upsert_narrative",
    "validate_citations",
]
