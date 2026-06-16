"""Phase 3 v2 Review Narrator — Candidate Builder.

PHASE1 case 결과 + 전표 메타 + PHASE2 ML 스코어 + peer_context를 조립해
LLM 입력 candidate dict 리스트를 생성한다. 스펙 §입력 계약 형식과 1:1.

설계:
- 순수 데이터 조립 함수. DuckDB 연결은 의존하지 않는다 (테스트·재사용 용이).
  DB 조회 어댑터는 Sprint C narrator/cache 또는 호출부에서 담당.
- 입력은 plain dict 인터페이스. Phase1CaseResult 등 무거운 Pydantic 모델 의존 회피.
- 우선순위 정책 (스펙 §3.3):
  1. PHASE1 case priority_score 상위 N건이 1차 후보.
  2. PHASE1 case에 포함되지 않은 journal 중 ML percentile ≥ threshold(기본 0.99)는
     남은 슬롯에 보충 (case 단독 N 초과 시 ML-only는 잘림).
  3. 총 후보 수는 max(min(n, hard_limit), 0) 이내.

단일 출처: docs/archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md §입력 계약, §흐름.
"""

from __future__ import annotations

from src.llm.review_narrator.sanitizer import Sanitizer


def _normalize_n(n: int, hard_limit: int) -> int:
    """N을 [0, hard_limit] 범위로 클램프."""
    if n <= 0:
        return 0
    return min(n, hard_limit)


def _select_ml_only_journals(
    ml_scores: dict[str, list[dict]],
    excluded_journal_ids: set[str],
    threshold: float,
) -> list[str]:
    """case에 포함되지 않은 journal 중 ML percentile ≥ threshold인 ID 정렬 반환.

    정렬 기준: 해당 journal의 최대 percentile 내림차순 → 결정론적 tie-break(journal_id).
    """
    candidates: list[tuple[str, float]] = []
    for journal_id, scores in ml_scores.items():
        if journal_id in excluded_journal_ids:
            continue
        max_pct = max((s.get("percentile", 0.0) for s in scores), default=0.0)
        if max_pct >= threshold:
            candidates.append((journal_id, max_pct))
    candidates.sort(key=lambda x: (-x[1], x[0]))
    return [jid for jid, _ in candidates]


def _build_candidate(
    candidate_id: str,
    journal_id: str,
    journal_meta: dict,
    rule_hits: list[dict],
    ml_score_entries: list[dict],
    peer_context: dict,
    sanitizer: Sanitizer,
) -> dict:
    """단일 candidate dict 조립 — 스펙 §입력 계약 형식."""
    return {
        "candidate_id": candidate_id,
        "journal_ref": {
            "batch_id": journal_meta.get("batch_id") or "",
            "journal_id": journal_id,
            "posting_date": journal_meta.get("posting_date") or "",
            "period": journal_meta.get("period") or "",
            "process": journal_meta.get("process") or "",
        },
        "rule_hits": rule_hits,
        "ml_scores": ml_score_entries,
        "journal_meta": sanitizer.sanitize_journal_meta(journal_meta),
        "peer_context": peer_context or {},
    }


def build_candidates(
    phase1_cases: list[dict],
    journal_metas: dict[str, dict],
    ml_scores: dict[str, list[dict]],
    peer_contexts: dict[str, dict],
    *,
    n: int = 20,
    hard_limit: int = 100,
    ml_percentile_threshold: float = 0.99,
    sanitizer: Sanitizer | None = None,
) -> list[dict]:
    """후보 N건 dict 리스트 생성.

    Args:
        phase1_cases: [{case_id, priority_score, journal_id, rule_hits: [...]}] —
            PHASE1 case-level 결과. journal_id는 대표 전표 ID.
        journal_metas: journal_id → 전표 메타 dict (batch_id, posting_date, period,
            process, amount, gl_account, counterparty, approver, description 등).
        ml_scores: journal_id → ML 점수 entry 리스트
            [{model_id, score, percentile, top_features: [...]}].
        peer_contexts: journal_id → peer 분포 요약 dict (없으면 빈 dict).
        n: 후보 목표 수. 기본 20.
        hard_limit: 절대 상한. 기본 100. n > hard_limit이면 hard_limit로 클램프.
        ml_percentile_threshold: ML 단독 후보 보충 임계. 기본 0.99.
        sanitizer: PII 마스킹 전담. None이면 기본 salt로 생성.

    Returns:
        스펙 §입력 계약 형식의 candidate dict 리스트. 빈 입력은 빈 리스트.
    """
    effective_n = _normalize_n(n, hard_limit)
    if effective_n == 0:
        return []
    san = sanitizer or Sanitizer()

    # 1차: PHASE1 case priority_score 상위 (정렬 후 N 컷)
    sorted_cases = sorted(
        phase1_cases,
        key=lambda c: (-float(c.get("priority_score", 0.0)), c.get("case_id", "")),
    )

    candidates: list[dict] = []
    case_journal_ids: set[str] = set()
    for case in sorted_cases:
        if len(candidates) >= effective_n:
            break
        journal_id = case.get("journal_id") or ""
        if not journal_id:
            continue
        meta = journal_metas.get(journal_id, {})
        candidate_id = f"CAND-{case.get('case_id', journal_id)}"
        candidates.append(
            _build_candidate(
                candidate_id=candidate_id,
                journal_id=journal_id,
                journal_meta=meta,
                rule_hits=list(case.get("rule_hits", [])),
                ml_score_entries=list(ml_scores.get(journal_id, [])),
                peer_context=peer_contexts.get(journal_id, {}),
                sanitizer=san,
            )
        )
        case_journal_ids.add(journal_id)

    # 2차: ML 단독 고위험 보충 (남은 슬롯만큼)
    remaining = effective_n - len(candidates)
    if remaining > 0:
        ml_only_ids = _select_ml_only_journals(ml_scores, case_journal_ids, ml_percentile_threshold)
        for journal_id in ml_only_ids[:remaining]:
            meta = journal_metas.get(journal_id, {})
            candidates.append(
                _build_candidate(
                    candidate_id=f"CAND-ML-{journal_id}",
                    journal_id=journal_id,
                    journal_meta=meta,
                    rule_hits=[],
                    ml_score_entries=list(ml_scores.get(journal_id, [])),
                    peer_context=peer_contexts.get(journal_id, {}),
                    sanitizer=san,
                )
            )

    return candidates
