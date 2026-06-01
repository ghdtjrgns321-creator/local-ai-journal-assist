# Phase 3 v2 — Review Queue Narrator 구현 완료 리포트

> **Historical/deprecated only (2026-05-26)**: This completion report records a removed implementation. PHASE3 LLM Narrator, LLM reranking, AI review memo, Text-to-SQL, and LLM rule feedback are not active product capability. Current policy is [LOCAL_FIRST_EVIDENCE_POLICY.md](../LOCAL_FIRST_EVIDENCE_POLICY.md) and [DECISION.md §D068](../DECISION.md).

> 작성일: 2026-05-15
> 단일 출처 스펙: [PHASE3_REVIEW_NARRATOR_SPEC.md](../PHASE3_REVIEW_NARRATOR_SPEC.md)
> 재코딩 계획: [PHASE3_REWORK_PLAN.md](../PHASE3_REWORK_PLAN.md)
> 결정 로그: [DECISION.md §D041](../DECISION.md) + §D043
> Sprint G 마감 — 모든 산출물이 v2 구현 상태와 일치한다.

---

## 1. 범위 요약

### 목적
PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 LLM이 읽고 (a) 후보 Top-N 재정렬, (b) 의심 근거 서술 + 인용, (c) 감사인 다음 행동 제안.

### 비범위 (재코딩 시 다시 만들지 않음)
- 자연어 → SQL 변환 (Text-to-SQL)
- 자유 가설 생성 (새 fraud 패턴 발견)
- LLM이 룰 자동 추가/수정 제안 (룰 피드백 루프)
- Excel/PDF 감사조서 생성, 감사 증적 CSV 다운로드
- Chat 형식 자연어 UI

---

## 2. 자산 처리 결과

| 구분 | 자산 | 결과 |
|------|------|------|
| 재사용 (그대로) | `src/llm/api_client.py` (OpenAIClient + ChatClient/EmbeddingClient Protocol + 2티어 팩토리) | Narrator의 LLM 호출 기반으로 유지. 회귀 33건 PASS. |
| 재사용 | `src/feature/text_features.py::add_morpheme_features`, `src/llm/embedding_service.py` | Narrator 입력 적요 처리·동의어 매칭 보조 |
| 재사용 | `src/detection/nlp_analyzer.py`, `graph_detector.py` | `rule_hits` 신호원 |
| 재사용 | `src/export/audit_trail.py` | `EventType` Literal에 `analysis_run` / `review_decision_change` 2종 확장 (Sprint E2/F) |
| 재사용 | `src/ingest/header_detector.py::_llm_header_check` | Ingest 영역, 변경 없음 |
| 흡수 후 폐기 (Sprint D) | `src/llm/insight_generator.py`, `narrative_report.py`, `src/db/batch_insight_store.py` | `git rm`. 관련 테스트 2건 삭제. Pydantic 모델 `BatchInsight` / `SignificantTxOpinion` / `EntryNarrative` / `NarrativeBatch` 4종을 `src/llm/models.py`에서 제거. |
| 동결 (보존) | Text-to-SQL (`text_to_sql.py`, `sql_validator.py`, `prompt_presets.py`), Chat UI (`tab_chat.py`), Excel/PDF Export (`excel_exporter.py`, `pdf_exporter.py`, `masking.py`, `models.py`), Export 탭 (`tab_export.py`), 룰 피드백 루프 (`rule_feedback.py`, `rule_feedback_panel.py`) | 코드 변경 금지, 회귀 테스트 그대로 통과. `vanna[duckdb,chromadb]` / `fpdf2` 의존성 유지. |

**원칙 검증**: "흡수 후 폐기" 자산은 Narrator의 candidate-level 흐름으로 재포커싱되었다. `InsightGenerator`의 배치 단위 요약은 Sprint B `candidate_builder` + Sprint C `narrator`의 candidate별 summary/reasoning 생성으로 대체된다.

---

## 3. Sprint 산출물

| Sprint | 핵심 산출물 | 단위 테스트 | 상태 |
|--------|-------------|------------|------|
| A | `src/db/schema.py::review_narratives` DDL + 인덱스 2종, `review_narrator/models.py` (`ReviewNarrative` / `ReasoningItem` / `ReasoningEvidence` / `SuggestedAction` + `build_review_narrative_schema()`), `review_narrator/citation_validator.py` | 28 PASS | ✅ |
| B | `review_narrator/sanitizer.py` (해시 마스킹 + 7단계 금액 범위화 + 적요 패턴 마스킹), `review_narrator/candidate_builder.py` (PHASE1 priority 상위 N + ML percentile ≥0.99 보충) | 51 PASS (sanitizer 25 / builder 26) → 누적 81 | ✅ |
| C | `review_narrator/narrator.py` (reasoning→light fallback→failure narrative + citation 2차 강등), `review_narrator/cache.py` (canonical JSON SHA-256 input_hash + UPSERT/UPDATE/reuse 3-state), `models.py` strict enum 동적 주입 | 27 PASS (narrator 12 / cache 10 / 통합 5) → 누적 108 | ✅ |
| D | `insight_generator.py`/`narrative_report.py`/`batch_insight_store.py` 흡수 후 폐기. `BatchInsight` 등 모델 4종 제거. `tab_overview.py::_render_batch_insight()` placeholder 교체. | 전체 회귀 2991 PASS, 0 fail | ✅ |
| E1 | `dashboard/tab_review_queue.py` + `components/review_narrator{,_jump}.py` (카드 + citation 점프), `app.py` 5탭 등록, `_state.py` `KEY_REVIEW_QUEUE_*` 5종 | 9 신규 + dashboard 175 회귀 PASS | ✅ |
| E2 | `dashboard/components/review_queue_workflow.py` (필터·검색·실행 계획·분류 저장 순수 함수), `tab_review_queue.py` 확장 (사이드바 6종 필터 + candidate_id 검색 + 실행 트리거 + 분류 라디오·메모), `schema.py` idempotent ALTER 4컬럼 + `idx_review_narratives_decision`, `cache.py::update_audit_decision`/`read_audit_decision`, `EventType` 2종 확장 | 38 신규 (cache 9 + workflow 29) + E1 호환 패치 2 → 누적 171 PASS | ✅ |
| F | `review_narrator/budget_guard.py` (BudgetGuard — N 자동 축소 20→10→5 + exhausted), `audit_logger.py` (`log_narrate_event` — `audit_log.action='analysis_run'`), `eval_harness.py` (`CallSample`/`EvalReport`/`evaluate_samples`/`save_eval_report`) | 22 PASS (BudgetGuard 8 + AuditLogger 3 + EvaluateSamples 7 + SaveReport 1 + SchemaEnumGuard 2 + opt-in 1) | ✅ |
| G | 본 리포트, `PHASE3_REVIEW_NARRATOR_SPEC.md` 변경 이력 갱신, `DECISION.md` D043, `documentation-architect` 정합성 검증 | — | ✅ |

---

## 4. 평가 기준 충족 여부

스펙 §평가 기준 4종은 Sprint F의 평가 하니스를 통해 측정한다.

| 항목 | 기준 | 측정 도구 | 회귀 검증 |
|------|------|-----------|----------|
| 인용 정합성 (citation_pass_rate) | ≥ 99% | `evaluate_samples` + §4.2 strict enum 1차 방어선 | mock 100% PASS — strict enum reject + citation_validator 강등 2단 |
| 우선순위 일치도 (Spearman ρ) | ≥ 0.6 (감사인 라벨 N=50 vs LLM rank) | `evaluate_samples` scipy.stats.spearmanr | 임계값 메서드 회귀 PASS (실제 LLM은 `RUN_LLM_EVAL=1` opt-in) |
| Latency p95 (reasoning / light) | ≤ 8s / ≤ 2s | `_percentile(reasoning_latencies, 95)` / light | mock 측정 회귀 PASS |
| 비용 (candidate 1건당 평균) | 운영 추적 | `EvalReport.avg_cost_usd` + budget_guard | mock 호출 비용 누적 PASS |

실제 OpenAI API 호출 평가는 `RUN_LLM_EVAL=1` 환경변수로만 활성화되며, 결과는 `test-results/phase3_review_narrator_eval/YYYYMMDD/eval_<label>_<HHMMSS>_<uuid6>.json`에 저장된다. CI 기본 실행은 mock 기반 단위 테스트만 수행한다.

---

## 5. DB 스키마 변화 요약

```sql
-- Sprint A (CREATE)
CREATE TABLE IF NOT EXISTS review_narratives (
    candidate_id      VARCHAR PRIMARY KEY NOT NULL,
    batch_id          VARCHAR NOT NULL,
    journal_id        VARCHAR,
    priority_rank     INTEGER,
    priority_score    DOUBLE,
    confidence        VARCHAR,
    narrative_json    JSON NOT NULL,
    citation_valid    BOOLEAN NOT NULL,
    input_hash        VARCHAR NOT NULL,
    model_tier        VARCHAR NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          DOUBLE,
    created_at        TIMESTAMP DEFAULT current_timestamp
);
CREATE INDEX IF NOT EXISTS idx_review_narratives_batch ON review_narratives(batch_id);
CREATE INDEX IF NOT EXISTS idx_review_narratives_rank  ON review_narratives(priority_rank);

-- Sprint E2 (idempotent ALTER)
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS audit_decision VARCHAR;
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS audit_note     VARCHAR;
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS reviewed_by    VARCHAR;
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS reviewed_at    TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_review_narratives_decision ON review_narratives(audit_decision);
```

`audit_decision` 허용 값: `confirmed_high_risk` / `under_review` / `normal_exception` / `false_positive` / NULL (미분류). CHECK 제약은 두지 않고 애플리케이션 레이어(`cache.update_audit_decision` + `AUDIT_DECISION_VALUES` frozenset)에서 enum을 강제한다.

---

## 6. 운영 가이드

### 6.1 회귀 실행
- 전체 단위 회귀: `uv run pytest tests/ -v`
- Review Narrator 모듈만: `uv run pytest tests/modules/test_llm/test_review_narrator/ -v`
- 대시보드 통합: `uv run pytest tests/modules/test_dashboard/ -v`

### 6.2 실제 LLM 평가
1. `OPENAI_API_KEY` 환경변수 설정 (Anthropic 또는 OpenAI 호환 키)
2. 감사인 라벨 데이터 준비 — 후속 작업 (별도 디렉토리 신설 시 `data/eval/phase3_review_narrator/`)
3. `RUN_LLM_EVAL=1 uv run pytest tests/modules/test_llm/test_review_narrator/test_eval.py -v`
4. 결과 JSON은 `test-results/phase3_review_narrator_eval/YYYYMMDD/` 누적

### 6.3 비용·감사 추적
- 호출 메타는 `review_narratives.prompt_tokens` / `completion_tokens` / `cost_usd` 컬럼에 UPSERT 저장.
- 사용자 이벤트는 `audit_log` 테이블의 `analysis_run` / `review_decision_change` action으로 누적.
- 일일 예산 가드: `BudgetGuard(initial_n=20, max_usd=1.0)` 인스턴스 1개를 배치 단위로 유지하고, candidate 호출마다 `guard.record(cost_usd=...)` 후 `guard.current_n()`로 다음 N 결정.

### 6.4 대시보드 워크플로우
1. 회사·연도 선택 → 전표 업로드 / DB 로드
2. Phase 1·Phase 2 분석 완료 후 **Review Queue** 탭 진입
3. 사이드바 필터 + candidate_id 검색으로 후보 좁힘
4. "분석 실행"으로 narrate 호출 (N·예산 조절 가능), input_hash 변경 시 "재생성" 활성
5. 각 카드에서 reasoning citation 클릭 → 우측 점프 패널에서 원본 룰 메타·feature 값·전표 라인 확인
6. 분류 라디오 (`고위험 확정` / `검토 중` / `정상 예외` / `오탐 (FP)`) + 메모 작성 → "저장"

---

## 7. 후속 로드맵

| 항목 | 우선순위 | 비고 |
|------|---------|------|
| Multi-provider A/B 평가 (Anthropic / Gemini) | Low | candidate 수가 수천 건 규모로 늘면 재평가. 현 시점 미실시 — DECISION.md §D043 |
| OpenAI Batch API 적용 | Mid | 비용 30~50% 절감 가능. `narrate()` 1건당 호출을 `narrate_batch()`로 묶기. 캐시·citation_validator 흐름은 동일. |
| 감사인 라벨 데이터셋 N=50 구축 | Mid | Spearman ρ 측정 회귀 정상 가동을 위한 ground truth. PHASE1 case priority 상위 50건 ↔ 감사인 우선순위 매칭. |
| `process` 컬럼 review_narratives 직접 컬럼화 | Low | 현재 `dashboard/tab_review_queue.py`에서 빈 문자열로 두고 있음. peer_context 확장 시 review queue 컬럼화. |
| RC-4 review queue 탭 통합 (현재 임시 탭) | Low | RC-4 회사-centric 아키텍처 완료 시 본 탭 컴포넌트 이식. 컴포넌트는 이미 분리되어 있어 이식 비용 낮음. |

---

## 8. 변경 이력

- 2026-05-15: 최초 작성. Sprint A~G 산출물 종합. WU-31 전체 ✅ 마감.
- 2026-05-15: Sprint G 완료 기록 — `documentation-architect` 에이전트 정합성 검증, `docs/DECISION.md` D043 신규(provider 단일화 잠정 유지 + 재평가 트리거 4종), `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` §변경 이력에 Sprint E1+E2 / F / G 줄 추가 및 순서 정합화, `docs/PHASE3_REWORK_PLAN.md` §11 변경 이력에 Sprint E2 / G 갱신.
