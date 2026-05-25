# Phase 3 — Review Queue Narrator (v2 Spec)

> 작성일: 2026-05-14
> 상태: v2 정의 확정 · Sprint A~G 구현 완료 (2026-05-15). 구현 완료 리포트: [completed/phase3_review_narrator_completion.md](completed/phase3_review_narrator_completion.md), 재코딩 계획서: [completed/PHASE3_REWORK_PLAN.md](completed/PHASE3_REWORK_PLAN.md).
> 단일 출처(SoT): 본 문서. CLAUDE.md / README.md / completed/raw-plan/08-llm.md 는 본 문서로 링크한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## PHASE1 역할 원칙 (재확인)

PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 출력은 **감사인이 봐야 할 후보와 우선순위**다. Phase 3은 그 후보 집합을 LLM이 읽고 정렬·서술하는 단계이며, **새로운 fraud 패턴을 발견하지 않는다.**

## 목적

PHASE1 룰 히트와 PHASE2 ML 스코어, 전표 메타데이터를 입력받아 LLM이:

1. 감사인이 우선 검토할 **후보 Top-N을 재정렬**한다.
2. 각 후보에 대해 **"왜 의심되는가"를 서술**한다 (rule_id / feature_id / evidence_row_ref 인용 필수).
3. **다음 감사 행동**을 제안한다 (증빙 요청, 계정 분석, 관련자 인터뷰 등).

## 비범위 (Out of Scope)

다음은 Phase 3 v2에서 **신규 작업 대상이 아니다**. 기존 구현물은 보존하되 신규 기능 추가·확장은 하지 않는다.

| 항목 | 결정 | 비고 |
|------|-----|------|
| Text-to-SQL (자연어 질의 → SQL) | 비범위 | WU-20 구현물은 코드 보존, 신규 작업 없음. 대시보드 노출 여부는 별도 결정. |
| Export (Excel/PDF/감사 증적 CSV) | 비범위 | WU-24/27 구현물은 코드 보존, 신규 작업 없음. |
| LLM 자유 가설 생성 (새 패턴 발견) | 비범위 | 환각 위험 + 감사 신뢰성 부족. 룰/ML 출력 해석에 한정한다. |
| LLM 추론으로 룰 추가/수정 자동화 | 비범위 | 룰 정의는 사람이 결정한다. |

## 입력 계약

LLM에 전달되는 단위는 **review candidate** 1건이다. Candidate는 PHASE1 룰 히트와 PHASE2 스코어로 식별된 전표(또는 전표 그룹)다.

| 필드 | 타입 | 출처 | 설명 |
|------|------|-----|------|
| `candidate_id` | str | 시스템 | review queue 내 고유 ID |
| `journal_ref` | obj | DuckDB | `batch_id`, `journal_id`, `posting_date`, `period`, `process` |
| `rule_hits` | list[obj] | PHASE1 | `[{rule_id, severity, score, fields_triggered, rule_meta_ref}]` |
| `ml_scores` | list[obj] | PHASE2 | `[{model_id, score, percentile, top_features: [{feature_id, value, contribution}]}]` |
| `journal_meta` | obj | DuckDB | 금액·계정·거래처·승인자·적요 요약 (PII 비식별 후) |
| `peer_context` | obj | DuckDB | 동일 process / 동일 계정의 분포 요약 (median, p95 등) |

PII는 입력 단계에서 비식별 처리한다. 원본 식별자(이름, 사업자번호 등)는 LLM에 직접 노출하지 않는다.

## 출력 계약

LLM 응답은 OpenAI Structured Output(JSON Schema, `strict: True`)으로 강제한다.

```jsonc
{
  "candidate_id": "string",
  "priority_rank": 0,                  // 1=highest
  "priority_score": 0.0,               // [0,1]
  "summary": "string",                 // 1~2줄 한국어 요약
  "reasoning": [                       // 의심 근거 (인용 필수)
    {
      "claim": "string",
      "evidence": [
        { "type": "rule_hit",   "rule_id": "string" },
        { "type": "ml_feature", "model_id": "string", "feature_id": "string" },
        { "type": "row",        "journal_id": "string", "line_no": 0 }
      ]
    }
  ],
  "suggested_actions": [               // 감사인 다음 행동
    { "action_type": "request_evidence|account_analysis|interview|further_test",
      "description": "string",
      "target": "string" }
  ],
  "confidence": "low|medium|high"
}
```

### 인용 계약 (Citation Contract)

- `reasoning[].evidence` 배열은 **비어 있을 수 없다**.
- `evidence.rule_id` / `feature_id` / `journal_id`는 입력에 실제 존재하는 값이어야 한다.
- **1차 방어선 (strict 단계)**: candidate별 입력 ID set으로 동적으로 채워진 JSON Schema enum으로 LLM 응답을 strict reject한다. LLM은 입력에 없는 ID를 응답으로 만들 수 없다. 구현 상세: [completed/PHASE3_REWORK_PLAN.md §4.2](completed/PHASE3_REWORK_PLAN.md).
- **2차 방어선 (citation_validator)**: 응답 후 ID 존재 검증. 어떤 사유로든 통과 못 한 건은 자동으로 `confidence=low` + `priority_rank` 후순위 처리한다.

## 흐름

```
PHASE1 rule hits ─┐
PHASE2 ml scores ─┼─► Candidate Builder ─► PII Sanitizer ─► LLM (Structured Output)
journal meta ─────┤                                          │
peer context ─────┘                                          ▼
                                                Citation Validator
                                                             │
                                                             ▼
                                               Review Queue (UI: RC-4 대시보드)
```

## 모델 정책

| 용도 | 모델 티어 | 근거 |
|------|----------|------|
| Candidate 서술 + 우선순위 | reasoning (`gpt-5.4`) | 다단 근거 통합 필요 |
| 단순 요약 / 필터 후보 정리 | light (`gpt-5.4-mini`) | 비용 절감 |

기존 `src/llm/api_client.py`의 2티어 추상화(`get_chat_client(tier)`)를 그대로 사용한다.

**Provider 결정 (2026-05-14)**: GPT-5.4 / GPT-5.4-mini 단일 provider 유지. Claude Sonnet 4.6, Gemini 2.5 Flash 등과의 multi-provider A/B는 수행하지 않는다. 근거 4가지(citation 정합성 차이 실효 없음 + 자산 완성도 + 성능 차이 미미 + 비용 가드 충분)는 [completed/PHASE3_REWORK_PLAN.md §4.1](completed/PHASE3_REWORK_PLAN.md)에 기록. ChatClient Protocol은 ISP 설계라 향후 운영 데이터로 재평가 가능.

## 평가 기준

| 항목 | 측정 | 기준 |
|------|-----|------|
| 인용 정합성 | citation validator 통과율 | ≥ 99% |
| 우선순위 일치도 | 감사인 라벨링 샘플 N=50 vs LLM rank 상관 | Spearman ρ ≥ 0.6 |
| 응답 latency | candidate 1건당 p95 | ≤ 8s (reasoning), ≤ 2s (light) |
| 비용 | candidate 1건당 평균 토큰 비용 | 별도 budget 문서에서 관리 |

## 구현 매핑

기존 Phase 3 자산 중 본 spec과 연결되는 것:

| 자산 | 역할 변경 |
|------|----------|
| `src/llm/api_client.py` (WU-18) | 그대로 사용 |
| `src/llm/insight_generator.py` (WU-25) | Review Narrator의 기반 모듈로 흡수 검토 |
| `src/llm/narrative_report.py` (WU-25) | 보고서 서술 → candidate 서술로 재포커싱 |
| `src/llm/text_to_sql.py` (WU-20) | 비범위. 코드 보존 |
| `src/export/*` (WU-24/27) | 비범위. 코드 보존 |
| `dashboard/tab_export.py` (WU-27) | 비범위. 코드 보존 |

신규 WU 슬롯은 `dev/active/<phase3-*>/` plan 문서에서 정의한다 (구 docs/TASKS.md 삭제).

## 변경 이력

- 2026-05-14: v2 정의 확정 (Text-to-SQL/Export 비범위, Review Queue Narrator로 좁힘).
- 2026-05-14: Sprint A 완료 — `src/db/schema.py` `review_narratives` DDL + 인덱스 2종, `src/llm/review_narrator/models.py` (`ReviewNarrative` / `ReasoningItem` / `ReasoningEvidence` / `SuggestedAction`), `src/llm/review_narrator/citation_validator.py`. 단위 테스트 28건 PASS + schema DDL 정합 회귀 통과.
- 2026-05-14: 인용 계약을 1차(strict schema enum) + 2차(citation_validator) 2계층으로 명시. 모델 정책에 GPT-5.4 단일 provider 유지 결정 기록. 상세 근거는 completed/PHASE3_REWORK_PLAN.md §4.1 / §4.2.
- 2026-05-14: Sprint B 완료 — `src/llm/review_narrator/sanitizer.py` (이름/계좌/사업자번호 해시 + 금액 7단계 범위화 + 적요 패턴 마스킹) + `src/llm/review_narrator/candidate_builder.py` (PHASE1 case priority 상위 N + ML percentile ≥0.99 단독 보충, N/hard_limit 클램프). 단위 테스트 51건 추가 (sanitizer 25 + builder 26) → 누적 81 PASS.
- 2026-05-14: Sprint C 완료 — `src/llm/review_narrator/models.py`에 `build_review_narrative_schema()` 추가 (1차 방어선 strict enum 동적 주입), `narrator.py` (reasoning→light fallback→failure narrative + citation 2차 강등), `cache.py` (canonical JSON SHA-256 `input_hash` + UPSERT/UPDATE/reuse 3-state). 단위 테스트 22건 + E2E 통합 5건 추가 → 누적 108 PASS.
- 2026-05-15: Sprint D 완료 — WU-25 자산 흡수 후 폐기. `src/llm/insight_generator.py`, `src/llm/narrative_report.py`, `src/db/batch_insight_store.py`, 관련 테스트 2건 `git rm`. `BatchInsight` / `SignificantTxOpinion` / `EntryNarrative` / `NarrativeBatch` Pydantic 모델 4종을 `src/llm/models.py`에서 제거. `dashboard/tab_overview.py::_render_batch_insight()`를 Sprint E placeholder(안내 메시지)로 교체. `src/llm/__init__.py` lazy import 정리. 전체 회귀 **2991 PASS, 0 fail** (env-의존 E2E 2건 제외).
- 2026-05-15: Sprint E1+E2 완료 — 대시보드 통합. E1에서 `dashboard/tab_review_queue.py` + `components/review_narrator{,_jump}.py` 분리(카드 + citation 점프 패널, 5탭 구조 안착, `KEY_REVIEW_QUEUE_*` 세션 키 5종). E2에서 idempotent ALTER 4컬럼(`audit_decision`/`audit_note`/`reviewed_by`/`reviewed_at`) + `idx_review_narratives_decision` 적용, `cache.update_audit_decision`·`read_audit_decision` 헬퍼, `EventType` Literal에 `analysis_run` / `review_decision_change` 추가, `components/review_queue_workflow.py` 순수 함수 5종(필터·검색·실행 계획·분류 저장), `tab_review_queue.py` 확장(사이드바 6종 필터 + candidate_id 검색 + N·예산·재생성 트리거 + 분류 라디오·메모 + AuditTrail 기록). 테스트 47건 추가 — workflow 29 / cache 9 / E1 회귀 호환 패치 2 / E1 신규 9 → review_narrator 모듈 누적 117 / dashboard 회귀 204 / 종합 279 PASS.
- 2026-05-15: Sprint F 완료 — 평가 하니스 + 비용 가드 도입. 신규 모듈 3종: `review_narrator/budget_guard.py` (BudgetGuard — N 자동 축소 20→10→5 + exhausted 가드), `audit_logger.py` (`log_narrate_event` — narrate 결과를 `audit_log.action='analysis_run'` 이벤트로 기록), `eval_harness.py` (`CallSample`/`EvalReport`/`evaluate_samples` — citation 통과율·Spearman ρ·tier별 latency p50/p95·비용 집계 + `save_eval_report` 결과 저장). 테스트 22건(BudgetGuard 8 + AuditLogger 3 + EvaluateSamples 7 + SaveReport 1 + SchemaEnumGuard 2 + opt-in 1) 추가. 실제 OpenAI 호출 평가는 `RUN_LLM_EVAL=1` 환경변수로만 활성화. §4.2 schema enum 회귀(mock invalid ID 우회 → citation_validator 강등)로 1+2차 방어선 통합 검증.
- 2026-05-15: **Sprint G 완료 — Phase 3 v2 릴리스**. WU-31 7개 항목(Candidate Builder / PII Sanitizer / Narrator / Citation Validator / DDL / Pydantic 모델 / 대시보드 통합 E1+E2 / 단위 테스트 / 평가 하니스+비용 가드) 전부 ✅. `docs/completed/phase3_review_narrator_completion.md` 신규(흡수·폐기 내역, Sprint 산출물, 평가 결과, 운영 가이드). `docs/DECISION.md` D043 (Phase 3 v2 안착 — provider 단일화 잠정 유지·재평가 트리거 조건 명시). 문서 정합성은 `documentation-architect` 에이전트로 검증.
