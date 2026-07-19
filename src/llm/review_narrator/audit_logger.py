"""Phase 3 v2 Review Narrator — Audit Trail 통합 (Sprint F).

각 narrate() 호출 결과를 `audit_log` 테이블에 기록한다.
- event_type: `analysis_run` (AuditTrail.VALID_EVENT_TYPES에 이미 등록됨)
- details JSON에 candidate_id, model_tier, citation_valid, confidence, 토큰·비용 포함

호출부 책임 (PII 계약 — 반드시 준수)
-----------------------------------
- 본 함수는 candidate dict가 **이미 sanitizer를 통과한 비식별 상태**임을 전제한다.
- candidate_id / journal_id는 시스템 생성 토큰(`CAND-*`, `JE-*`)이어야 하며 PII를
  내포해선 안 된다 (이름·계좌·사업자번호 등 원본 식별자는 sanitizer에서 마스킹됨).
- 호출자가 sanitizer 우회로 원본을 넘기면 audit_log에 PII가 영구 저장되어
  CONSTRAINTS.md §데이터 비식별화 위반 위험.

기타 호출 규약:
- AuditTrail 인스턴스 생성 (engagement DB 커넥션 필요)
- narrate() 결과 받은 직후 본 헬퍼 호출
- AuditTrail.log()의 graceful 동작에 의존 (실패 시 호출부 비차단)
"""

from __future__ import annotations

import logging

from src.export.audit_trail import AuditEvent, AuditTrailProtocol
from src.llm.review_narrator.narrator import NarratorResult

logger = logging.getLogger(__name__)


def log_narrate_event(
    audit_trail: AuditTrailProtocol,
    *,
    candidate: dict,
    narrator_result: NarratorResult,
    batch_id: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: float | None = None,
    company_id: str | None = None,
    engagement_id: str | None = None,
) -> None:
    """단일 candidate의 narrate 결과를 audit_log에 기록.

    Args:
        audit_trail: `AuditTrail` 인스턴스 또는 호환 fake.
        candidate: candidate_builder가 생성한 dict (candidate_id, journal_ref).
        narrator_result: narrate() 반환값.
        batch_id: 업로드 배치 식별자.
        prompt_tokens/completion_tokens/cost_usd: 호출자가 측정한 메타.
        company_id/engagement_id: 다중 회사 환경 컨텍스트 (옵션).
    """
    candidate_id = candidate.get("candidate_id", "UNKNOWN")
    journal_id = candidate.get("journal_ref", {}).get("journal_id", "")
    narrative = narrator_result.narrative

    details: dict = {
        "candidate_id": candidate_id,
        "journal_id": journal_id,
        "model_tier": narrator_result.model_tier,
        "call_status": narrator_result.call_status,
        "citation_valid": narrator_result.citation_result.is_valid,
        "confidence": str(narrative.confidence),
        "priority_rank": narrative.priority_rank,
        "priority_score": narrative.priority_score,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost_usd,
    }
    if narrator_result.error:
        details["error"] = narrator_result.error
    invalid_citations = narrator_result.citation_result.invalid_citations
    if invalid_citations:
        # Why: 강등 사유 분포를 사후 분석할 수 있도록 첫 5건만 보존 (로그 폭주 방지)
        details["invalid_citations_preview"] = invalid_citations[:5]
        details["invalid_citations_total"] = len(invalid_citations)

    user_action = (
        f"Review Narrator 호출 — {candidate_id} "
        f"(tier={narrator_result.model_tier}, status={narrator_result.call_status})"
    )

    try:
        audit_trail.log(
            AuditEvent(
                event_type="analysis_run",
                user_action=user_action,
                details=details,
                batch_id=batch_id,
                company_id=company_id,
                engagement_id=engagement_id,
            )
        )
    except Exception:  # noqa: BLE001 — 감사 로그 기록 실패는 본 흐름 비차단
        logger.warning(
            "review_narrator audit_log 기록 실패 — candidate=%s",
            candidate_id,
            exc_info=True,
        )
