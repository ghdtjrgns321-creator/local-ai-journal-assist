# Phase 3 Rework Plan — Review Queue Narrator 재코딩 계획

> 작성일: 2026-05-14
> Spec 단일 출처: [PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md)
> 결정: [DECISION.md §D041](DECISION.md)
> 본 문서는 **재코딩 실행 계획서**다. 무엇을, 어떤 순서로, 어떤 테스트를 두고 만들지 정의한다.

---

## 0. 목적과 비목적

### 목적
PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타 → LLM이 읽고 (a) 후보 Top-N 재정렬, (b) 의심 근거 서술 + 인용, (c) 감사인 다음 행동 제안.

### 비목적 (재코딩 시 다시 만들지 않음)
- 자연어 → SQL 변환 (Text-to-SQL)
- 자유 가설 생성 (새 fraud 패턴 발견)
- LLM이 룰 자동 추가/수정 제안 (룰 피드백 루프)
- Excel/PDF 감사조서 생성, 감사 증적 CSV 다운로드
- Chat 형식 자연어 UI

---

## 1. 기존 자산 처리 매트릭스

| 영역 | 기존 파일 | v2 처리 | 비고 |
|------|----------|---------|------|
| API 클라이언트 (ChatClient/EmbeddingClient Protocol, OpenAIClient, 2티어 팩토리) | `src/llm/api_client.py` | **재사용 (그대로)** | Narrator의 LLM 호출 기반 |
| Pydantic 응답 모델 | `src/llm/models.py` | **재사용 (확장)** | `ReviewNarrative`, `ReasoningEvidence`, `SuggestedAction` 추가 |
| NLP kiwipiepy 전처리 | `src/feature/text_features.py::add_morpheme_features` | **재사용** | Narrator의 적요 요약 입력 |
| Embedding 서비스 (O(U) 캐시, 행렬 코사인) | `src/llm/embedding_service.py` | **재사용** | Narrator의 적요 동의어 매칭 보조 |
| NLP 탐지기 (NLP01~05) | `src/detection/nlp_analyzer.py` + `nlp_rules.py` | **재사용** | Narrator 입력의 `rule_hits` 신호원 |
| 그래프 탐지기 (GR01/GR03) | `src/detection/graph_detector.py` + `graph_rules.py` | **재사용** | Narrator 입력의 `rule_hits` 신호원 |
| Insight Generator (배치) | `src/llm/insight_generator.py` | **흡수 후 폐기** | Narrator로 통합 |
| Narrative Report (XAI) | `src/llm/narrative_report.py` | **흡수 후 폐기** | Narrator로 통합 |
| Audit Trail 기록기 | `src/export/audit_trail.py` | **재사용** | Narrator 호출 이벤트 로깅 |
| LLM 헤더 탐지 보강 | `src/ingest/header_detector.py::_llm_header_check` | **재사용 (그대로)** | Ingest 영역, Narrator와 독립 |
| Text-to-SQL 엔진 | `src/llm/text_to_sql.py`, `sql_validator.py`, `prompt_presets.py` | **동결 (보존)** | 신규 작업 없음. 대시보드 노출 여부는 별도 결정 |
| Chat UI 탭 | `dashboard/tab_chat.py` | **동결 (보존)** | 동상 |
| Excel/PDF Export | `src/export/excel_exporter.py`, `pdf_exporter.py`, `masking.py`, `models.py` | **동결 (보존)** | 동상 |
| Export 탭 | `dashboard/tab_export.py` | **동결 (보존)** | 동상 |
| 룰 피드백 루프 | `src/llm/rule_feedback.py` + `dashboard/components/rule_feedback_panel.py` | **동결 (보존)** | 자유 가설 영역, 비범위 |
| `vanna[duckdb,chromadb]` 의존성 | `pyproject.toml` llm 그룹 | **유지** | Text-to-SQL 보존을 위해 유지 |
| `fpdf2` 의존성 | `pyproject.toml` export 그룹 | **유지** | Export 보존을 위해 유지 |

**원칙**: "흡수 후 폐기" 자산은 Narrator 모듈로 로직을 옮긴 뒤 원본을 삭제한다. "동결 (보존)" 자산은 코드 그대로 두되 회귀 테스트만 통과시킨다.

---

## 2. 신규 모듈 구조

```
src/llm/review_narrator/
├── __init__.py
├── candidate_builder.py     # review queue + rule_hits + ml_scores + meta → LLM 입력 dict
├── sanitizer.py             # PII 비식별 (식별자 마스킹·금액 범위화)
├── narrator.py              # LLM 호출 (Structured Output) + 응답 파싱
├── citation_validator.py    # rule_id / feature_id / journal_id 존재 검증
├── cache.py                 # review_narratives 테이블 UPSERT 헬퍼
└── models.py                # ReviewNarrative, ReasoningEvidence, SuggestedAction (Pydantic)

src/db/
└── schema.py                # review_narratives DDL 추가

tests/modules/test_llm/test_review_narrator/
├── test_candidate_builder.py
├── test_sanitizer.py
├── test_narrator.py
├── test_citation_validator.py
├── test_cache.py
└── test_eval.py             # 평가 하니스 (정합성 ≥99%, Spearman ≥0.6)

dashboard/
└── tab_review_queue.py      # (RC-4 통합 전 임시 탭, 또는 RC-4 review queue 탭 안에서 narrative 표시)
```

각 모듈은 100줄 내외 단일 책임 원칙. `narrator.py`는 `get_chat_client(tier)`만 의존하고, candidate/sanitizer/citation은 LLM 호출 없이 단위 테스트 가능하게 한다.

---

## 3. 입력 데이터 조립

### 3.1 어디서 가져오는가
- `rule_hits`: PHASE1 결과 — DuckDB `detection_results` + `phase1_cases` (case-level priority 포함)
- `ml_scores`: PHASE2 결과 — DuckDB `ml_scores` (VAE / Isolation Forest / supervised) + top features
- `journal_meta`: DuckDB `general_ledger` + `phase1_cases.metadata`
- `peer_context`: DuckDB on-demand 쿼리 (process / 계정 단위 분포 요약)

### 3.2 candidate_builder 책임
1. PHASE1/PHASE2 결과 조인 → review queue 후보 N건 선정 (기본 N=20, 하드 리밋 100)
2. 후보당 rule_hits / ml_scores / journal_meta / peer_context 채움
3. PII 식별자(거래처명·임직원명·계좌·사업자번호 등)는 `sanitizer`로 마스킹
4. LLM 입력 dict 생성 (스펙 §입력 계약 형식)

### 3.3 우선순위 정책
candidate 1건당 LLM 호출 비용을 고려해, 후보 선정은 PHASE1 case `priority_score` 상위 N개로 한정한다. ML 단독 고위험(룰 미히트)은 PHASE2 percentile ≥ 0.99 또는 평가용으로만 포함.

---

## 4. LLM 호출 전략

| 항목 | 정책 |
|------|-----|
| 모델 티어 | `reasoning` (`gpt-5.4`) 기본. fallback에 `light` (`gpt-5.4-mini`) |
| 응답 강제 | OpenAI Structured Output (`strict: True`) — `ReviewNarrative` JSON Schema |
| 배치 | candidate 1건씩 호출 (재시도·복구 단순). 향후 batch API 고려 가능 |
| 재시도 | 1회 light로 폴백. 2회 실패 시 `confidence=low` + 후순위 |
| Citation 실패 | `citation_validator` 실패 → `confidence=low` + 후순위 (재호출 안 함) |
| 캐시 | `review_narratives` 테이블에 `candidate_id` PK로 UPSERT. 입력 hash가 같으면 재사용 |

비용 가드: 호출당 토큰 사용량 + 비용을 `audit_log`에 기록. budget 초과 시 candidate 선정 N을 자동 축소.

### 4.1 Provider 결정 (2026-05-14)

**결론**: GPT-5.4 / GPT-5.4-mini 2티어를 단일 provider로 유지. Sprint F에서 multi-provider A/B 평가는 하지 않는다.

근거:
1. **citation 정합성 차이가 실효 없음**: 본 프로젝트 citation은 `rule_id` / `feature_id` / `journal_id` **enum 인용**이다. 아래 §4.2 schema enum 제약으로 입력 ID set만 선택하도록 strict mode에서 차단하면, 모든 주요 모델의 통과율이 자연스럽게 ≥99%에 수렴한다. 공개 벤치마크의 hallucination 3%(Claude) vs 6%(GPT/Gemini)는 자유 텍스트 factual 인용 기준이라 본 프로젝트의 ID enum 인용에 직접 적용되지 않는다.
2. **자산 완성도**: `src/llm/api_client.py`의 OpenAIClient + ChatClient/EmbeddingClient Protocol + `_enforce_strict_schema()` + 2티어 팩토리는 WU-18에서 단위 테스트 33건 PASS로 검증 완료. Sprint A에서 `ReviewNarrative` 모델·DDL·citation_validator도 28건 PASS로 안착했다. 여기서 provider 갈아타면 추가 마찰만 발생한다.
3. **성능 차이 미미**: SWE-bench Verified 79.6%(Sonnet 4.6) vs ~80%(GPT-5.4) vs 80.6%(Gemini 3.1 Pro). Structured Output strict 성숙도는 OpenAI가 가장 앞서며, 한국어 회계 도메인은 세 후보가 동등 수준이다.
4. **비용 가드 충분**: 후보 N 자동 축소(20→10→5)와 `input_hash` 기반 캐시로 비용 폭증 위험은 GPT-5.4로도 통제 가능. candidate 수가 향후 수천 건 규모로 늘면 그 시점에 Gemini 2.5 Flash 등 저비용 provider를 재평가한다 (현 시점에서는 평가 미실시).

ChatClient Protocol은 ISP 설계라 향후 다른 provider 추가가 필요할 때 `src/llm/anthropic_client.py` 또는 `gemini_client.py` 신규 파일만으로 가능. 본 결정은 v2 구현 안착 시점의 잠정 결정이며, 운영 데이터로 재평가 가능하다.

### 4.2 Schema enum 제약 (Citation 1차 방어선)

`ReasoningEvidence`의 `rule_id` / `feature_id` / `journal_id` / `line_no` 등 ID 필드는 candidate 입력에 실제 존재하는 ID set으로 동적으로 좁힌 JSON Schema enum으로 제약한다.

```python
# narrator.py — 호출 직전 동적으로 schema enum 채움
rule_id_enum    = [hit["rule_id"]     for hit  in candidate["rule_hits"]]
feature_id_enum = [feat["feature_id"] for ml   in candidate["ml_scores"]
                                       for feat in ml["top_features"]]
journal_id_enum = [candidate["journal_ref"]["journal_id"]]  # 또는 그룹 ID 다수

schema = build_review_narrative_schema(
    rule_id_enum=rule_id_enum,
    feature_id_enum=feature_id_enum,
    journal_id_enum=journal_id_enum,
)
# OpenAI Structured Output strict: True 호출 시 위 schema 전달
```

효과:
- LLM이 입력에 없는 ID 를 생성하지 못하도록 **strict 단계에서 차단**한다. citation_validator는 안전망(2차)으로 남는다.
- citation 통과율이 본질적으로 ≥99% 보장. Sprint F 평가의 인용 정합성 기준이 자동으로 충족된다.
- LLM 입장에서는 "이 candidate 안에서만 인용 가능한 ID 목록"이 명시되어 reasoning 품질도 안정된다.

구현 위치: `src/llm/review_narrator/models.py`의 `ReviewNarrative` 스키마 빌더(`build_review_narrative_schema(...)`)를 추가하고, `narrator.py`가 호출 직전 candidate별로 enum을 주입한다. 단위 테스트는 입력에 없는 ID 가 LLM 응답에 들어가는 시나리오를 mock으로 만들고, schema validator(strict)가 즉시 reject하는지 확인한다.

---

## 5. DDL — review_narratives

```sql
-- Sprint A에서 생성된 부분
CREATE TABLE IF NOT EXISTS review_narratives (
    candidate_id          TEXT PRIMARY KEY,
    batch_id              TEXT NOT NULL,
    journal_id            TEXT,
    priority_rank         INTEGER,
    priority_score        DOUBLE,
    confidence            TEXT,            -- low|medium|high
    narrative_json        JSON NOT NULL,   -- 전체 ReviewNarrative 직렬화
    citation_valid        BOOLEAN NOT NULL,
    input_hash            TEXT NOT NULL,
    model_tier            TEXT NOT NULL,
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    cost_usd              DOUBLE,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_review_narratives_batch ON review_narratives(batch_id);
CREATE INDEX IF NOT EXISTS idx_review_narratives_rank  ON review_narratives(priority_rank);

-- Sprint E2에서 idempotent 마이그레이션으로 추가 (감사인 분류·메모)
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS audit_decision TEXT;
    -- 허용 값: 'confirmed_high_risk' | 'under_review' | 'normal_exception' | 'false_positive' | NULL
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS audit_note     TEXT;
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS reviewed_by    TEXT;
ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS reviewed_at    TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_review_narratives_decision ON review_narratives(audit_decision);
```

**구현 위치**: Sprint A는 본 DDL의 상단(`CREATE TABLE` 블록)을 `src/db/schema.py`에 안착시켰다. Sprint E2는 하단의 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 블록과 인덱스를 동일 파일에 idempotent하게 추가한다. 이미 생성된 DB에서도 안전하게 재실행되도록 모든 마이그레이션은 `IF NOT EXISTS`를 사용한다.

---

## 6. 테스트 전략 (TDD 사이클 강제)

각 모듈은 RED-GREEN-REFACTOR. 테스트는 LLM Mock 기반으로 작성하고, 실제 OpenAI 호출은 평가 하니스에서만 사용한다.

### 6.1 단위 테스트 (mock LLM)
| 모듈 | 테스트 케이스 |
|------|--------------|
| `candidate_builder` | (1) 룰만 히트 / (2) ML만 히트 / (3) 둘 다 히트 / (4) N=0 빈 큐 / (5) peer_context 결측 / (6) 후보 선정 우선순위 |
| `sanitizer` | (1) 거래처명 마스킹 / (2) 임직원명 / (3) 사업자번호 / (4) 금액 범위화 / (5) PII 결측 안전 처리 |
| `narrator` | (1) Mock Structured Output 성공 / (2) JSON 파싱 실패 → light 폴백 / (3) 2회 실패 → confidence=low / (4) 빈 응답 |
| `citation_validator` | (1) 모든 인용 valid / (2) rule_id 미존재 → 강등 / (3) feature_id 미존재 → 강등 / (4) journal_id 미존재 → 강등 / (5) reasoning 배열 비어있음 → 강등 |
| `cache` | (1) 신규 UPSERT / (2) 동일 input_hash 재사용 / (3) input 변경 시 재호출 |

### 6.2 통합 테스트 (mock LLM)
- review queue N=10 candidate → Builder → Sanitizer → Narrator → Citation → Cache → DB read 회왕복.
- 입력 데이터에 의도적으로 비식별 누락 케이스를 넣어 sanitizer 회귀 방어.

### 6.3 평가 하니스 (실제 LLM 사용, opt-in)
- 인용 정합성: random 100 candidate × 3 회 호출 → citation validator 통과율 ≥ 99%
- 우선순위 일치도: 감사인 라벨 N=50 vs LLM `priority_rank` Spearman ρ ≥ 0.6
- Latency: p95 ≤ 8s (reasoning), ≤ 2s (light)
- 비용: candidate 1건당 평균 토큰·USD 비용 기록 → 회귀 추적

### 6.4 회귀 (보존 자산)
- WU-20 (Text-to-SQL), WU-24 (Export), WU-26 (Chat UI), WU-27 (Export 탭), WU-30 (룰 피드백)의 기존 테스트는 그대로 통과해야 한다. 코드 변경 금지.

---

## 7. Sprint 계획

각 Sprint는 1회 대화 단위 작업량 기준 S/M/L 복잡도 표기.

### Sprint A — DDL + Pydantic 모델 + Citation Validator `[M]`
**선행**: 없음
**산출물**:
- `src/db/schema.py` `review_narratives` DDL 추가
- `src/llm/review_narrator/models.py` (`ReviewNarrative`, `ReasoningEvidence`, `SuggestedAction`)
- `src/llm/review_narrator/citation_validator.py`
- 단위 테스트 (`test_models.py`, `test_citation_validator.py`)

**완료 조건**: Citation validator가 mock 응답으로 100% 통과. DDL은 빈 DB에서 마이그레이션 성공.

### Sprint B — Candidate Builder + PII Sanitizer `[M]`
**선행**: Sprint A
**산출물**:
- `src/llm/review_narrator/candidate_builder.py`
- `src/llm/review_narrator/sanitizer.py`
- 단위 테스트 (`test_candidate_builder.py`, `test_sanitizer.py`)

**완료 조건**: PHASE1/PHASE2 mock 결과로 candidate dict 생성 + sanitizer가 PII 비식별 통과.

### Sprint C — Narrator 본체 + Cache `[L]`
**선행**: Sprint B
**산출물**:
- `src/llm/review_narrator/narrator.py` (Structured Output 호출 + fallback)
- `src/llm/review_narrator/cache.py` (UPSERT + input_hash)
- 단위 테스트 (`test_narrator.py`, `test_cache.py`)
- 통합 테스트 (`test_review_narrator/test_integration.py`)

**완료 조건**: mock LLM 기반 E2E 회왕복 (Builder → Sanitizer → Narrator → Citation → Cache → DB read) 성공.

### Sprint D — 흡수: insight_generator / narrative_report → Narrator로 통합 `[M]`
**선행**: Sprint C
**작업**:
- `insight_generator.py`의 배치 인사이트 로직과 `narrative_report.py`의 사유서 로직을 Narrator의 reasoning/summary 생성으로 흡수
- 호출부 (`dashboard`, `pipeline.py` 등)를 Narrator API로 교체
- 흡수 후 두 파일 삭제 + 테스트 제거

**완료 조건**: 기존 호출부 회귀 테스트 통과. 두 파일이 `git rm`된 상태.

### Sprint E1 — 대시보드 렌더링 (카드 + citation 점프) `[M]`
**선행**: Sprint C
**산출물**:
- RC-4 review queue 탭(또는 임시 `dashboard/tab_review_queue.py`)에 Narrator 출력 표시:
  - candidate 카드: priority_rank + summary + reasoning(인용 링크) + suggested_actions + confidence 뱃지
  - citation 클릭 → 원본 룰 메타데이터 / feature 값 / 전표 라인으로 점프 (explorer 컴포넌트 재사용)
- Streamlit 캐시 키 + 세션 상태 (`dashboard/_state.py` 확장) — `KEY_REVIEW_QUEUE_*` 신규
- `app.py` 탭 등록 (RC-4 진행 중이면 임시 탭으로 우회)
- 단위 테스트 (`tests/modules/test_dashboard/test_tab_review_queue_render.py`)

**완료 조건**: `uv run streamlit run dashboard/app.py` 실행 시 review queue 탭에서 Narrator JSON이 가독성 있게 렌더되고, citation 클릭으로 원본 룰/feature/전표로 점프. session_state hash 기반 캐시 무효화 동작.

### Sprint E2 — 감사인 워크플로우 (실행 트리거 + Review 액션 + 필터) `[M]`
**선행**: Sprint E1
**산출물**:
- **실행 트리거 UX**:
  - "분석 실행" 버튼 + N 후보 수 + 예상 비용/시간 안내 + 진행률 (`st.status` / `st.progress`)
  - 입력 변경 감지(`input_hash` 비교) 시 "재생성" 버튼 노출 + 직전 결과 보존 옵션
  - 에러/부분 성공/budget 초과 알림 (`st.error`, `st.warning`)
- **Review 액션 (감사인 분류 + DB 저장)**:
  - candidate별 분류 라디오: `confirmed_high_risk` / `under_review` / `normal_exception` / `false_positive`
  - 메모 입력 (`audit_note`) + 분류 저장 시 `reviewed_by` / `reviewed_at` 자동 채움
  - DB 마이그레이션: §5 하단 블록을 `src/db/schema.py`에 idempotent ALTER로 추가 (`audit_decision`, `audit_note`, `reviewed_by`, `reviewed_at` + index)
  - `src/llm/review_narrator/cache.py`에 `update_audit_decision(candidate_id, decision, note, user)` 헬퍼 추가
- **필터·검색**:
  - 사이드바: confidence·priority_rank 범위·process·batch_id·audit_decision·인용된 rule_id 필터
  - 본문 상단: candidate_id 검색 박스
- **AuditTrail 이벤트**: `analysis_run`, `review_decision_change` 2종을 `AuditTrail.log()`로 기록
- 단위 테스트 (`tests/modules/test_dashboard/test_tab_review_queue_workflow.py`) — 분류 저장 / 필터 / 재실행 / 에러 표시 케이스
- `tests/modules/test_llm/test_review_narrator/test_cache.py` 확장 — `update_audit_decision` UPSERT 회귀

**완료 조건**:
- 감사인이 candidate를 분류하면 `review_narratives` 테이블에 4컬럼이 저장되고 재진입 시 복원된다.
- "재생성" 버튼이 input_hash 변경에서만 활성화되고, 기존 narrative와 분류는 보존된다.
- 필터·검색이 candidate 목록에 정확히 반영되고 빈 결과/대량 결과 모두 가독성 유지.
- 실행 트리거가 진행률을 표시하고 budget 초과 시 N 자동 축소 (§4 비용 가드 연동).

### Sprint F — 평가 하니스 + 비용 가드 `[M]`
**선행**: Sprint E1 (E2와 병렬 가능)
**산출물**:
- `tests/modules/test_llm/test_review_narrator/test_eval.py` (opt-in, 환경변수 `RUN_LLM_EVAL=1`)
- 비용·토큰 로깅을 `audit_log`에 기록
- 평가 결과를 `test-results/phase3_review_narrator_eval/` 디렉토리에 저장
- **단일 provider 평가** (GPT-5.4 / GPT-5.4-mini). multi-provider A/B는 §4.1 결정에 따라 본 Sprint에서 수행하지 않는다.
- §4.2 schema enum 제약이 strict 단계에서 입력 외 ID를 차단함을 회귀로 확인 (의도적 invalid ID 응답 mock → strict reject).

**완료 조건**: 평가 하니스 실행 시 인용 정합성 ≥99%, Spearman ≥0.6 충족 (실패 시 회귀로 즉시 노출). schema enum 제약 회귀 테스트 통과.

### Sprint G — 문서 정합 + 릴리스 `[S]`
**선행**: Sprint A~F
**작업**:
- `docs/TASKS.md` WU-31 상태 업데이트 (각 Sprint 완료 시 점진적으로)
- `docs/debugging.md`에 Sprint별 트러블슈팅 기록
- `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` 변경 이력 갱신
- CHANGELOG (있다면) 또는 `docs/completed/phase3_review_narrator_completion.md` 작성
- `docs/DECISION.md`에 후속 결정이 있으면 추가

**완료 조건**: 모든 문서가 v2 구현 상태와 일치.

---

## 8. 의존성 그래프

```
Sprint A (DDL + 모델 + Citation)
   ↓
Sprint B (Builder + Sanitizer)
   ↓
Sprint C (Narrator + Cache + 통합 테스트)
   ↓
   ├─────────────────┬─────────────────┐
   ▼                 ▼                 ▼
Sprint D          Sprint E1         Sprint F (E1 이후 즉시 가능)
(흡수)            (렌더링 + citation 점프)
                     │
                     ▼
                  Sprint E2
                  (실행 트리거 + Review 액션 + 필터, DDL ALTER)
   │                 │                 │
   └────────┬────────┴─────────┬───────┘
            ▼                  ▼
                  Sprint G (문서 정합 + 릴리스)
```

C 이후 D / E1 / F는 3개 컨텍스트 병렬 가능 (F는 E1만 있어도 narrator 출력 측정 가능). E2는 E1 완료 후 진입.

---

## 9. 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|-----|------|
| LLM 환각 (존재하지 않는 rule_id 인용) | Citation validator로 즉시 강등 | 강등된 candidate는 후순위로 분리해 감사인 노출 최소화. 통계 모니터링. |
| 비용 폭증 | 후보 N 자동 축소 | budget 초과 시 N=20 → 10 → 5 점진 축소. `audit_log`에 비용 기록. |
| Latency p95 초과 | 사용자 체감 저하 | reasoning 호출 timeout 12s + light fallback. 캐시 우선. |
| 보존 자산 (Text-to-SQL/Export) 회귀 | 기존 테스트 깨짐 | 코드 변경 금지. 의존성(`vanna`, `fpdf2`) 유지. CI에서 회귀 테스트 분리. |
| PII 누락 → API 전송 | 감사 신뢰 손상 | sanitizer 단위 테스트 + 통합 테스트에서 식별자 패턴 모두 점검. 회귀 hardening. |
| RC-4 진행 중 대시보드 통합 충돌 | 작업 중단 | Sprint E는 RC-4 review queue 탭 확정 후 또는 임시 탭으로 우회. |

---

## 10. 진행 추적

진행 상태는 `docs/TASKS.md` Phase 3 섹션의 **WU-31** 행에 Sprint A~G로 분기해 기록한다. 각 Sprint 완료 시:

1. `docs/TASKS.md` WU-31 해당 Sprint 행 ✅ 마킹
2. `docs/debugging.md`에 트러블슈팅 있으면 기록
3. `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` 변경 이력에 한 줄 추가 (스펙 자체가 바뀌었을 때)
4. `documentation-architect` 에이전트로 문서 정합성 검증 (대량 문서 수정 후)

---

## 12. Orchestration — Sprint 발주 명령과 병렬 매트릭스

> 새 대화 세션 또는 서브에이전트에 Sprint를 발주할 때 사용할 명령 프롬프트를 한 곳에 고정한다. 각 프롬프트는 self-contained하게 작성되어 컨텍스트 0인 세션도 작업을 시작할 수 있다.
>
> **서브에이전트 운영 규칙**: 모든 서브에이전트에 한국어 응답 지시 + 작업 종료 시 `documentation-architect` 또는 `code-reviewer` 후속 검증 (CLAUDE.md §7 Workflow Triggers).

### 12.1 의존성 그래프

```
[A] DDL + Pydantic 모델 + Citation Validator     ← 완료
     │
     ▼
[B] Candidate Builder + PII Sanitizer
     │
     ▼
[C] Narrator 본체 + Cache + 통합 테스트
     │
     ├─────────────────┬─────────────────┐
     ▼                 ▼                 ▼
[D] 흡수            [E1] 대시보드        [F] 평가 하니스 + 비용 가드
    insight/            렌더링 + citation
    narrative           점프
                          │
                          ▼
                       [E2] 감사인 워크플로우
                          실행 트리거 + Review 액션 + 필터
                          (DDL ALTER 마이그레이션 포함)
     │                    │                 │
     └────────┬───────────┴─────────┬───────┘
              ▼                     ▼
                   [G] 문서 정합 + 릴리스
```

### 12.2 병렬 매트릭스

| Sprint | 선행 (BLOCKING) | 병렬 가능 대상 | 단일 대화로 완결 가능? |
|--------|----------------|---------------|----------------------|
| A | 없음 | — | ✅ 완료 (2026-05-14) |
| B | A | — | 가능 (M) |
| C | B | — | 가능 (L) — 분할 권장 (C1 Narrator + C2 Cache + C3 통합 테스트) |
| D | C | E1, E2, F | 가능 (M) |
| E1 | C | D, F | 가능 (M) — RC-4 대시보드 진행 상황에 따라 임시 탭 우회 가능 |
| E2 | E1 | D, F | 가능 (M) — DDL ALTER + 감사인 워크플로우 |
| F | C (narrator 측정) | D, E1, E2 | 가능 (M) — E2 결과 평가는 옵션 |
| G | A~F 전체 | — | 가능 (S) |

**병렬 진입 시점**: Sprint C 완료 직후 D / E1 / F 3개 컨텍스트 동시 발주가 가장 효율적. E2는 E1 완료 후 진입 (E1의 카드 렌더링 위에 액션 UI를 얹는 구조).

### 12.3 Sprint별 발주 명령

각 블록은 새 Claude Code 대화 세션 또는 `planner` / `general-purpose` 서브에이전트에 그대로 붙여넣어 사용. 작업 후 본 문서 §10 진행 추적 절차 수행.

---

#### 🚀 Sprint A 발주 (선행: 없음)

```
[Phase 3 v2 Sprint A] DDL + Pydantic 모델 + Citation Validator 구현

작업 범위는 `docs/PHASE3_REWORK_PLAN.md` §7 Sprint A에 정의되어 있다. 단일 출처 spec은 `docs/PHASE3_REVIEW_NARRATOR_SPEC.md`다. 한국어로 응답하라.

산출물:
1. `src/db/schema.py`에 `review_narratives` 테이블 DDL 추가 (스펙 §5 참조: candidate_id PK, narrative_json, citation_valid, input_hash, model_tier, 토큰/비용, batch_id/journal_id/priority 인덱스 2종)
2. `src/llm/review_narrator/__init__.py` + `src/llm/review_narrator/models.py` 신규 생성 — Pydantic 모델 `ReviewNarrative`, `ReasoningEvidence`, `SuggestedAction` 정의 (스펙 §출력 계약 JSON Schema와 1:1 매핑)
3. `src/llm/review_narrator/citation_validator.py` 신규 생성 — `rule_id` / `feature_id` / `journal_id` 존재 검증, 실패 시 `confidence=low` 강등 로직
4. 단위 테스트: `tests/modules/test_llm/test_review_narrator/test_models.py`, `test_citation_validator.py`

완료 기준:
- citation validator 단위 테스트 100% 통과 (스펙 §6.1 표 citation_validator 5개 케이스)
- DDL이 빈 DB에서 마이그레이션 성공 (DuckDB)
- `uv run pytest tests/modules/test_llm/test_review_narrator/ -v` 통과

제약:
- 파일당 100줄 내외, SRP 준수
- 새 패키지 설치 금지 (Pydantic, DuckDB는 이미 의존)
- 코드는 작성 직후 `code-reviewer` 에이전트로 리뷰 트리거

종료 시:
- `docs/TASKS.md` WU-31 Sprint A 행 ✅ 마킹
- `docs/debugging.md`에 트러블슈팅 기록 (있을 경우)
```

---

#### 🚀 Sprint B 발주 (선행: A 완료)

```
[Phase 3 v2 Sprint B] Candidate Builder + PII Sanitizer 구현

선행: Sprint A 완료 (review_narratives DDL + Pydantic 모델 + Citation Validator 존재). 단일 출처: `docs/PHASE3_REVIEW_NARRATOR_SPEC.md`, 계획서: `docs/PHASE3_REWORK_PLAN.md` §3 §7 Sprint B. 한국어로 응답하라.

산출물:
1. `src/llm/review_narrator/candidate_builder.py` 신규 — DuckDB에서 PHASE1 결과(`detection_results`, `phase1_cases`) + PHASE2 결과(`ml_scores`) + 전표 메타(`general_ledger`) + peer_context를 조인해 후보 N건 선정 (기본 N=20, 하드 리밋 100). 우선순위는 PHASE1 case `priority_score` 상위 N개 + PHASE2 percentile ≥0.99 단독 후보 일부 포함.
2. `src/llm/review_narrator/sanitizer.py` 신규 — 거래처명·임직원명·계좌·사업자번호 등 PII 식별자 마스킹. 금액 범위화는 `CONSTRAINTS.md §데이터 비식별화` 표 참조.
3. 단위 테스트: `tests/modules/test_llm/test_review_narrator/test_candidate_builder.py`, `test_sanitizer.py` (스펙 §6.1 표의 Builder 6 + Sanitizer 5 케이스)

완료 기준:
- mock DuckDB fixture로 builder가 candidate dict 생성 (스펙 §입력 계약 형식과 1:1)
- sanitizer가 PII 결측 안전 처리 + 모든 식별자 패턴 마스킹
- `uv run pytest tests/modules/test_llm/test_review_narrator/ -v` 통과

제약:
- LLM 호출 금지 (builder/sanitizer 모두 결정론적, 테스트는 mock 없이 동작)
- DuckDB 변수명/SQL 식별자는 파이썬 로컬 변수와 일치 (memory: feedback_duckdb_variable_scope)
- 코드 작성 직후 `code-reviewer` 에이전트 리뷰

종료 시: `docs/TASKS.md` WU-31 Sprint B ✅, `docs/debugging.md` 갱신.
```

---

#### 🚀 Sprint C 발주 (선행: B 완료) — L 복잡도, 필요 시 C1/C2/C3 분할

```
[Phase 3 v2 Sprint C] Narrator 본체 + Cache + 통합 테스트

선행: Sprint A/B 완료. 단일 출처: `docs/PHASE3_REVIEW_NARRATOR_SPEC.md`, 계획서: `docs/PHASE3_REWORK_PLAN.md` §4 §7 Sprint C. 한국어로 응답하라.

산출물:
1. `src/llm/review_narrator/narrator.py` 신규 — `get_chat_client("reasoning")` 호출 + OpenAI Structured Output(`strict: True`) + JSON 파싱 실패 시 `get_chat_client("light")` 1회 fallback. 2회 실패 시 `confidence=low` 강등.
2. `src/llm/review_narrator/cache.py` 신규 — `review_narratives` 테이블 UPSERT 헬퍼. `input_hash` 동일 시 재사용, 다르면 재호출. SHA-256 기반 hash.
3. 통합 테스트: `tests/modules/test_llm/test_review_narrator/test_integration.py` — review queue N=10 candidate → Builder → Sanitizer → Narrator(mock) → Citation → Cache → DB read 회왕복 + 비식별 누락 케이스 회귀.

완료 기준:
- mock LLM 기반 E2E 회왕복 성공 (DuckDB in-memory fixture)
- citation_validator 통과율 100% (mock 응답)
- 캐시 hit/miss 동작 (input_hash 변경/동일 시나리오)
- latency 측정용 시간 로깅 동작

제약:
- LLM 환각 방지: 응답의 모든 rule_id/feature_id/journal_id를 citation_validator로 검증
- OpenAI 실제 호출은 평가 하니스(Sprint F)에서만. 본 Sprint는 mock ChatClient 사용.
- 코드 작성 직후 `code-reviewer` 에이전트 리뷰

C1/C2/C3 분할 옵션:
- C1: narrator.py + 단위 테스트
- C2: cache.py + 단위 테스트
- C3: test_integration.py + 회귀 hardening

종료 시: `docs/TASKS.md` WU-31 Sprint C ✅, `docs/debugging.md` 갱신.
```

---

#### 🚀 Sprint D 발주 (선행: C 완료, E와 병렬 가능)

```
[Phase 3 v2 Sprint D] insight_generator / narrative_report 흡수 후 폐기

선행: Sprint C 완료 (Narrator 본체 동작). 계획서: `docs/PHASE3_REWORK_PLAN.md` §1 (자산 처리 매트릭스) + §7 Sprint D. 한국어로 응답하라. 본 Sprint는 Sprint E와 병렬 실행 가능.

작업:
1. `src/llm/insight_generator.py`의 배치 인사이트 로직과 `src/llm/narrative_report.py`의 사유서 로직을 Narrator의 `summary` / `reasoning[]` 생성으로 흡수.
2. 호출부 마이그레이션:
   - `dashboard/` 내 호출 경로를 Narrator API로 교체
   - `src/pipeline.py` 내 호출 경로 교체
   - `src/services/phase3_case_narrative_service.py`, `src/llm/phase3_case_prompt.py`, `src/llm/case_narrative_generator.py` 호환성 검토 후 흡수/폐기 결정
3. 흡수 완료 후 `git rm src/llm/insight_generator.py src/llm/narrative_report.py` + 관련 테스트 제거
4. 회귀 테스트: 기존 호출부 테스트가 Narrator API로 통과해야 함

완료 기준:
- `git status`에 두 파일이 deleted로 표시
- `uv run pytest tests/ -v` 전체 통과 (회귀 0건)
- 흡수 전 기능(High 위험 전표 자동 사유서, 배치 인사이트)이 Narrator 출력으로 대체 동작 확인

제약:
- `ripple-search` 스킬 활용: `insight_generator` / `narrative_report` 참조를 코드/문서 전체에서 grep해 누락 없이 교체
- 회귀 위험 큼 → `code-reviewer` 리뷰 필수 + 통합 테스트 우선

종료 시: `docs/TASKS.md` WU-31 Sprint D ✅, `docs/DECISION.md`에 흡수 결정 노트 추가, `docs/debugging.md` 갱신.
```

---

#### 🚀 Sprint E1 발주 (선행: C 완료, D / F와 병렬 가능)

```
[Phase 3 v2 Sprint E1] 대시보드 렌더링 — Narrator 카드 + citation 점프

선행: Sprint C 완료 (Narrator 본체 동작). 계획서: `docs/PHASE3_REWORK_PLAN.md` §7 Sprint E1. 한국어로 응답하라. 본 Sprint는 Sprint D / Sprint F와 병렬 실행 가능.

산출물:
1. RC-4 review queue 탭(또는 임시 `dashboard/tab_review_queue.py`)에 Narrator 출력 표시:
   - candidate 카드 컴포넌트: priority_rank + summary + reasoning(인용 링크) + suggested_actions + confidence 뱃지
   - citation 클릭 핸들러 → 원본 룰 메타데이터 / feature 값 / 전표 라인으로 점프 (explorer 컴포넌트 재사용)
2. Streamlit 캐시 키 + 세션 상태 (`dashboard/_state.py` 확장) — `KEY_REVIEW_QUEUE_CANDIDATES`, `KEY_REVIEW_QUEUE_HASH` 등 신규
3. `dashboard/app.py`에 탭 등록 (RC-4 진행 중이면 임시 탭으로 우회. 추후 RC-4 review queue 탭이 안착되면 본 컴포넌트를 그 안으로 이식)
4. `developing-with-streamlit` 스킬 규칙 준수: st.metric 라벨/value/delta 분리, 수정 후 kill+캐시삭제+재시작 자동 실행 (memory: feedback_streamlit_restart)
5. 단위 테스트: `tests/modules/test_dashboard/test_tab_review_queue_render.py`

완료 기준:
- `uv run streamlit run dashboard/app.py` 실행 시 review queue 탭에서 Narrator JSON이 가독성 있게 렌더
- citation 클릭으로 원본 룰 메타데이터 / feature 값 / 전표 라인이 표시
- session_state hash 기반 캐시 무효화 동작 (mock candidate 변경 시 재렌더)

제약:
- 본 Sprint는 **표시·렌더링만** 다룬다. 실행 트리거·Review 분류·필터·DDL ALTER는 Sprint E2 범위.
- RC-4 review queue 탭이 아직 진행 중이면 임시 탭으로 우회 → RC-4 완료 시 머지
- 작성 직후 `code-reviewer` 리뷰 + UI 변경은 브라우저 실행으로 골든 패스 확인

종료 시: `docs/TASKS.md` WU-31 Sprint E1 ✅, `docs/debugging.md` 갱신.
```

---

#### 🚀 Sprint E2 발주 (선행: E1 완료, D / F와 병렬 가능)

```
[Phase 3 v2 Sprint E2] 감사인 워크플로우 — 실행 트리거 + Review 액션 + 필터

선행: Sprint E1 완료 (Narrator 카드 렌더 + citation 점프 동작). 계획서: `docs/PHASE3_REWORK_PLAN.md` §5 (DDL 하단 ALTER 블록) + §7 Sprint E2. 한국어로 응답하라. 본 Sprint는 Sprint D / Sprint F와 병렬 실행 가능.

산출물:
1. **DDL 마이그레이션** (`src/db/schema.py` 확장):
   - `ALTER TABLE review_narratives ADD COLUMN IF NOT EXISTS audit_decision TEXT` (허용: 'confirmed_high_risk' | 'under_review' | 'normal_exception' | 'false_positive' | NULL)
   - `audit_note TEXT`, `reviewed_by TEXT`, `reviewed_at TIMESTAMP` 추가 + `idx_review_narratives_decision` 인덱스
   - 모든 마이그레이션은 idempotent (`IF NOT EXISTS`)
2. **실행 트리거 UX** (`dashboard/tab_review_queue.py` 또는 RC-4 탭 안에 추가):
   - "분석 실행" 버튼 + N 후보 수 + 예상 비용/시간 안내 + 진행률 (`st.status` / `st.progress`)
   - 입력 변경 감지(`input_hash` 비교) 시 "재생성" 버튼 노출 + 직전 결과 보존 옵션
   - 에러 / 부분 성공 / budget 초과 알림 (`st.error`, `st.warning`)
3. **Review 액션 (감사인 분류 + DB 저장)**:
   - candidate별 분류 라디오 (`st.radio` 또는 `st.segmented_control`)
   - 메모 입력 (`audit_note`) + 분류 저장 시 `reviewed_by` (세션 사용자) / `reviewed_at` (UTC now) 자동 채움
   - `src/llm/review_narrator/cache.py`에 `update_audit_decision(candidate_id, decision, note, user)` 헬퍼 추가 (UPSERT 패턴, 회귀 테스트로 보호)
4. **필터·검색**:
   - 사이드바: confidence·priority_rank 범위·process·batch_id·audit_decision·인용된 rule_id 필터
   - 본문 상단: candidate_id 검색 박스
5. **AuditTrail 이벤트**: `analysis_run`, `review_decision_change` 2종을 `src/export/audit_trail.py::AuditTrail.log()`로 기록
6. 단위 테스트:
   - `tests/modules/test_dashboard/test_tab_review_queue_workflow.py` — 분류 저장 / 필터 / 재실행 / 에러 표시 케이스
   - `tests/modules/test_llm/test_review_narrator/test_cache.py` 확장 — `update_audit_decision` UPSERT 회귀

완료 기준:
- 감사인이 candidate를 분류하면 `review_narratives` 테이블에 4컬럼이 저장되고 재진입 시 복원
- "재생성" 버튼이 input_hash 변경에서만 활성화되고, 기존 narrative와 분류는 보존
- 필터·검색이 candidate 목록에 정확히 반영 (빈 결과 / 대량 결과 모두 가독성)
- 실행 트리거가 진행률 표시 + budget 초과 시 N 자동 축소 (§4 비용 가드 연동)
- `uv run pytest tests/ -v` 통과 + UI 골든 패스 (분류 저장 → 새로고침 → 복원 확인)

제약:
- 본 Sprint는 **워크플로우 액션과 DDL 마이그레이션**을 다룬다. 카드 렌더링·citation 점프는 E1에서 이미 완료된 상태를 가정.
- DDL 변경은 idempotent. 기존 DB에 대해서도 안전 재실행 가능해야 함.
- `developing-with-streamlit` 스킬 규칙 + memory: feedback_streamlit_restart 준수
- 작성 직후 `code-reviewer` 리뷰 + 브라우저 실행으로 골든 패스 확인

종료 시: `docs/TASKS.md` WU-31 Sprint E2 ✅, `docs/debugging.md` 갱신, DDL 마이그레이션 결과를 한 줄 기록.
```

---

#### 🚀 Sprint F 발주 (선행: C+D+E 모두 완료)

```
[Phase 3 v2 Sprint F] 평가 하니스 + 비용 가드 (단일 provider)

선행: Sprint C/D/E 완료. 계획서: `docs/PHASE3_REWORK_PLAN.md` §4.1 §4.2 §6.3 §7 Sprint F. 단일 출처 스펙: `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` §평가 기준. 한국어로 응답하라. **§4.1 결정에 따라 multi-provider A/B는 수행하지 않는다 — GPT-5.4 / GPT-5.4-mini 단일 provider 기준 측정만 한다.**

산출물:
1. `tests/modules/test_llm/test_review_narrator/test_eval.py` 신규 — opt-in (`RUN_LLM_EVAL=1` 환경변수). 실제 OpenAI 호출 사용.
   - 인용 정합성: random 100 candidate × 3회 호출 → citation_validator 통과율 ≥ 99%
   - 우선순위 일치도: 감사인 라벨 N=50 vs LLM `priority_rank` Spearman ρ ≥ 0.6 (`scipy.stats.spearmanr`)
   - Latency p95: reasoning ≤ 8s, light ≤ 2s
2. 비용·토큰 로깅을 `audit_log`에 기록 (`AuditTrail.log` 재사용). `review_narratives.prompt_tokens` / `completion_tokens` / `cost_usd` 채움.
3. budget 초과 감지 시 candidate N 자동 축소 (20 → 10 → 5).
4. 평가 결과를 `test-results/phase3_review_narrator_eval/YYYYMMDD/` 디렉토리에 저장 (정합성 통과율, Spearman, latency 분포, 비용 합계).

완료 기준:
- 평가 하니스 실행 시 모든 기준 충족 (실패 시 회귀로 즉시 노출)
- 비용 로깅이 `audit_log` + `review_narratives`에 양쪽 기록
- budget 시뮬레이션 (소수 candidate)으로 N 축소 동작 확인
- §4.2 schema enum 제약 회귀 — invalid ID 응답을 의도적으로 발생시켜 strict reject 확인

제약:
- 실제 OpenAI 호출은 opt-in. CI 기본 실행은 mock 기반 단위 테스트만.
- 평가 데이터(감사인 라벨 N=50)는 `data/eval/phase3_review_narrator/` 같은 별도 디렉토리 (없으면 신규 생성)
- `code-reviewer` 리뷰 필수

종료 시: `docs/TASKS.md` WU-31 Sprint F ✅, `docs/debugging.md` 갱신, `test-results/` 결과 리포트 작성.
```

---

#### 🚀 Sprint G 발주 (선행: A~F 모두 완료)

```
[Phase 3 v2 Sprint G] 문서 정합 + 릴리스

선행: Sprint A~F 완료. 계획서: `docs/PHASE3_REWORK_PLAN.md` §7 Sprint G + §10 진행 추적. 한국어로 응답하라.

작업:
1. `docs/TASKS.md` WU-31 모든 Sprint ✅ + Phase 3 v2 완료 기준 충족 표시
2. `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` 변경 이력에 구현 완료 한 줄 추가
3. `docs/completed/phase3_review_narrator_completion.md` 신규 작성 — 흡수/폐기 내역, 평가 결과 요약, 운영 가이드
4. `docs/DECISION.md`에 후속 결정이 있으면 D042+ 추가
5. `documentation-architect` 에이전트로 Phase 3 관련 문서 정합성 검증 (CLAUDE.md, README.md, TASKS.md, raw-plan 배너, DECISION.md, 신규 spec/plan, completed 리포트)
6. `git status` 확인 후 Conventional Commits 형식 커밋 (`feat(llm)`, `docs(phase3)`, `refactor(llm)` 등) — 1 커밋 = 1 논리적 변경 원칙

완료 기준:
- 모든 Phase 3 관련 문서가 v2 구현 상태와 일치 (`documentation-architect` 통과)
- 변경 사항 커밋 + main 직접 커밋 금지 (develop → main 흐름)
- `uv run pytest tests/ -v` + UI 골든 패스 확인 후 릴리스 노트 작성

제약:
- 커밋 메시지에 AI/Claude 관련 문구 절대 금지 (CLAUDE.md §5)
- 머지 전 테스트 100% 통과 필수
```

### 12.4 발주 채널 권장

| 작업 단위 | 권장 채널 | 근거 |
|----------|----------|------|
| Sprint A/B/C/D (코드 구현) | 새 Claude Code 대화 세션 (메인 컨텍스트) | 다중 파일 수정 + 테스트 회왕복. 서브에이전트보다 메인 세션이 컨텍스트 보존에 유리. |
| Sprint E (대시보드 통합) | 새 대화 + `developing-with-streamlit` 스킬 활성화 | Streamlit 전용 규칙 자동 적용 필요. |
| Sprint F (평가 하니스) | 새 대화 + 실제 OpenAI 키 환경 | LLM 호출이 실제 발생. 메인 세션 권장. |
| Sprint G (문서 정합 + 검증) | 메인 세션에서 `documentation-architect` 서브에이전트 발주 | 대량 문서 정합 검증은 서브에이전트가 적합. |
| 흡수/폐기 작업 (Sprint D) | 메인 세션 + `ripple-search` 스킬 | 파급 영향 검색 필수. |

서브에이전트(`planner`, `general-purpose`, `Explore`) 발주는 본 §12.3 명령 블록을 그대로 프롬프트에 넣어 사용. 모든 서브에이전트 프롬프트에 "한국어로 응답하라" 명시 유지.

### 12.5 진행 체크리스트

각 Sprint 종료 시 다음 4가지를 확인한다.

- [ ] `docs/TASKS.md` WU-31 해당 Sprint 행 ✅ 마킹
- [ ] `docs/debugging.md` 트러블슈팅 기록 (있을 경우)
- [ ] `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` 변경 이력 갱신 (스펙 자체 변경 시)
- [ ] 다음 Sprint 발주 명령을 §12.3에서 그대로 복사해 새 컨텍스트에 투입

---

## 11. 변경 이력

- 2026-05-14: 최초 작성. Sprint A~G 정의.
- 2026-05-14: §12 Orchestration 추가 — Sprint별 발주 명령, 의존성 그래프, 병렬 매트릭스, 진행 체크리스트 고정.
- 2026-05-14: §4.1 Provider 결정 추가 — GPT-5.4 / GPT-5.4-mini 단일 provider 유지 (multi-provider A/B 미실시). §4.2 Schema enum 제약 절 추가 — strict mode에서 입력 ID 외 인용 차단을 1차 방어선으로 명시. Sprint F / §12.3 Sprint F 발주 명령에 단일 provider 명시 + schema enum 회귀 항목 추가.
- 2026-05-14: **Sprint A 완료** — `review_narratives` DDL + 인덱스 2종, `review_narrator/models.py`, `review_narrator/citation_validator.py` 산출. 단위 테스트 28건 PASS (스펙 §6.1 표의 citation_validator 5 케이스 포함). 다음: Sprint B (Candidate Builder + PII Sanitizer).
- 2026-05-14: **Sprint B 완료** — `review_narrator/sanitizer.py` + `review_narrator/candidate_builder.py` 산출. 결정론적 해시 마스킹(salt 기반), 7단계 금액 범위화, 적요 패턴 마스킹, PHASE1 priority 상위 N + ML percentile 보충 정책 구현. 단위 테스트 51건 추가 (sanitizer 25 + builder 26) → 누적 81 PASS. 다음: Sprint C (Narrator + Cache + 통합 테스트), Sprint D/E는 C 완료 후 병렬 가능.
- 2026-05-14: **Sprint C 완료** — `models.py::build_review_narrative_schema()` (§4.2 strict enum 1차 방어선), `narrator.py` (reasoning→light fallback→failure fallback + citation 2차 강등 결합), `cache.py` (canonical JSON SHA-256 input_hash + UPSERT/UPDATE/reuse 3-state). 단위 테스트 22건 (narrator 12 + cache 10) + E2E 통합 5건 추가 → 누적 108 PASS. mock LLM 기반 회왕복 (Builder→Sanitizer→Narrator→Citation→Cache→DB read) 성공. 다음: Sprint D (insight/narrative 흡수) ↔ Sprint E (대시보드 통합) 병렬 가능.
- 2026-05-15: **Sprint D 완료** — WU-25 자산 흡수 후 폐기. 삭제 파일 5종(`src/llm/insight_generator.py`, `narrative_report.py`, `src/db/batch_insight_store.py`, 관련 테스트 2건). `src/llm/models.py`에서 BatchInsight·SignificantTxOpinion·EntryNarrative·NarrativeBatch 4 모델 제거. `dashboard/tab_overview.py` 배치 인사이트 함수를 Sprint E placeholder로 교체. `src/llm/__init__.py` lazy import 정리. 전체 회귀 **2991 PASS, 0 fail** (env-의존 E2E 2건 제외). schema DDL 27개 (review_narratives 감사인 결정 컬럼 4종 + decision idx 외부 추가 반영).
- 2026-05-15: **Sprint D 흡수 의미 명료화** — "흡수 후 폐기" 매트릭스 §1의 의미는 `InsightGenerator` 배치 단위 요약을 candidate 단위 Narrator로 **재포커싱**한 것이다. 실제 로직 이식 위치: (a) PHASE1 룰 히트 집계 → `review_narrator/candidate_builder.py` (Sprint B에서 완료, priority_score 상위 N 선정), (b) candidate별 reasoning + summary 생성 → `review_narrator/narrator.py` (Sprint C에서 완료, Structured Output). 따라서 Sprint D는 신규 흡수 작업 없이 인터페이스만 제거하면 충분했고, 흡수 자체는 Sprint B+C에서 이미 마쳐졌다. Sprint D 리뷰 반영: `dev_analysis_reset.py` `_BATCH_INSIGHT_KEY` 잔존 키 3건 + 선언 1건 제거, `_render_batch_insight` 시그니처 `# noqa: ARG001` 명시. 다음: Sprint F (평가 하니스) — E는 사용자 측에서 별도 진행 중.
- 2026-05-14: **Sprint E 분할** — E1(렌더링 + citation 점프) + E2(실행 트리거 + Review 액션 + 필터, DDL ALTER 포함)로 나눔. §5 DDL에 idempotent ALTER 블록(`audit_decision`/`audit_note`/`reviewed_by`/`reviewed_at` + `idx_review_narratives_decision`) 추가. §8 / §12.1 의존성 그래프, §12.2 병렬 매트릭스, §12.3 발주 명령(E1/E2 분할), §12.4 발주 채널 정합화. Sprint F 선행을 E1로 완화 → C 완료 직후 D / E1 / F 3개 컨텍스트 병렬 가능. E2는 E1 완료 후 진입.
- 2026-05-15: **Sprint E2 완료** — `src/db/schema.py` idempotent ALTER 4컬럼(`audit_decision`/`audit_note`/`reviewed_by`/`reviewed_at`) + `idx_review_narratives_decision` 인덱스 안착, `AUDIT_DECISION_VALUES` enum 상수 추가. `src/llm/review_narrator/cache.py::update_audit_decision`(decision/note/reviewed_by/reviewed_at UPDATE, invalid decision·빈 user·candidate 미존재 가드) + `read_audit_decision`(분류 복원용 4컬럼 조회) 헬퍼 추가. `src/export/audit_trail.py::EventType` Literal에 `analysis_run` / `review_decision_change` 2종 확장 (`VALID_EVENT_TYPES`는 `get_args()`로 자동 파생 — 기존 회귀 자동 호환). 신규 `dashboard/components/review_queue_workflow.py`에 순수 함수 5종(`apply_filters`/`apply_search`/`compute_run_plan`/`register_review_decision` + `ReviewQueueFilters`/`RunPlan` dataclass). `dashboard/tab_review_queue.py` 확장 — 사이드바 6종 필터 + candidate_id 검색 + 실행 트리거(N·budget·진행률·재생성) + 분류 라디오·메모 + AuditTrail `analysis_run`/`review_decision_change` 이벤트 기록. `dashboard/_state.py`에 E2 6키(`KEY_REVIEW_QUEUE_FILTERS`/`SEARCH`/`LAST_HASH`/`RUN_STATUS`/`RUN_ERROR`/`TARGET_N`) 추가 + `_DEFAULTS` 등록. 단위 테스트 38건 신규(cache 9 — UPSERT/overwrite/none clear/narrative 무영향/invalid·empty user·missing candidate/read_audit_decision · workflow 29 — apply_filters 10/apply_search 5/compute_run_plan 6/register_review_decision 4/AuditTrail event 3/UI 진입점 1) + Sprint E1 회귀 2건 호환 패치(`_stub_streamlit_layout` 도입) → 누적 171 PASS. 다음: Sprint F (평가 하니스 + 비용 가드) → Sprint G (문서 정합 + 릴리스).
- 2026-05-15: **Sprint G 완료 — Phase 3 v2 릴리스 마감**. WU-31 7개 항목 전부 ✅. `docs/completed/phase3_review_narrator_completion.md` 신규(흡수·폐기 매트릭스 결과 / Sprint A~F 산출물 표 / 평가 기준 충족 / DB 스키마 diff / 운영 가이드 / 후속 로드맵). `docs/DECISION.md` D043(Phase 3 v2 안착 — provider 단일화 잠정 유지 + 재평가 트리거 4종 명시: 처리량 1000건/batch, citation pass <99% 3주 연속, OpenAI 가격 50% 인상, Anthropic/Gemini Structured Output strict 동등 보증). `docs/PHASE3_REVIEW_NARRATOR_SPEC.md` §변경 이력 정합화. `documentation-architect` 에이전트 검증으로 11개 문서 정합성 게이트 통과(SPEC Sprint E/F 순서 정정, DECISION D042/D043 순서 정정, completed §8 변경 이력 보강 등 5건 패치).
- 2026-05-15: **Sprint F 완료** — 평가 하니스 + 비용 가드. 신규 모듈 3종: `review_narrator/budget_guard.py` (`BudgetGuard` — `_REDUCTION_STEPS`로 50%→N=10, 80%→N=5, 100%→exhausted=0), `audit_logger.py` (`log_narrate_event` — narrate 결과를 `audit_log.action='analysis_run'`에 토큰·비용·강등 사유 첫 5건 포함 기록, 실패 시 graceful), `eval_harness.py` (`CallSample`/`EvalReport` dataclass + `evaluate_samples`로 citation rate·scipy spearmanr·tier별 latency p50/p95·비용 집계 + `save_eval_report` JSON 저장 `test-results/phase3_review_narrator_eval/YYYYMMDD/`). 단위 테스트 22건(BudgetGuard 8 / AuditLogger 3 / EvaluateSamples 7 / SaveReport 1 / SchemaEnumGuard 2 / opt-in 1) — opt-in은 `RUN_LLM_EVAL=1`에서만 실행. §4.2 schema enum 회귀(mock invalid ID → citation_validator 2차 강등)로 1+2차 방어선 통합 검증. 누적 **139 PASS, 1 skipped** (review_narrator 모듈 전체). 다음: Sprint G (문서 정합 + 릴리스 노트).
