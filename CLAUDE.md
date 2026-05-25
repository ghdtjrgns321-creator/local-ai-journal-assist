# Local AI Audit Assistant v2.0

> 보조 파일 — 영문 정책 (Stack / Non-negotiables / Common Commands / Testing / Coding / Audit / DataSynth / Skill 활용 / Safety / Secrets / Git) 은 [AGENTS.md](./AGENTS.md) 참조. 본 파일은 한국어 Phase 로드맵 + 문서 인덱스 + Skill/Agent 활용 맵 + gpt-5.4 티어 메모. 양쪽 모두 각 도구가 자동 로드, 중복 룰은 공유 동기화 체크리스트 메모리로 관리.

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

감사 실증절차 전표 테스트를 로컬 환경에서 자동화하는 Python 프로젝트.
PCAOB AS 2401, ISA 240 커버. MindBridge/KPMG Clara 핵심 로직을 오픈소스로 재현.

## Quick Reference

| 항목 | 값 |
|------|---|
| Python | 3.11+ |
| 패키지 관리 | uv + pyproject.toml (dependency-groups) |
| DB | DuckDB (OLAP) |
| 대시보드 | Streamlit + Plotly + AgGrid |
| LLM (Phase 3) | OpenAI (gpt-5.4 / gpt-5.4-mini 2티어) — Review Queue Narrator 한정 |
| 테스트 | pytest (`uv run pytest tests/ -v`) |
| 실행 | `uv run streamlit run dashboard/app.py` |

## Phase 로드맵

- **RC (Restructure)**: Company-Centric 아키텍처 전면 재설계 — 41개 태스크
  - RC-0: Company 인프라 (CompanyContext + ContextFactory + CRUD)
  - RC-1: 파이프라인 Context 주입
  - RC-2: 싱글톤 직접 호출 제거
  - RC-3: DB 격리 (Engagement별 DuckDB) + ConnectionManager
  - RC-4: 대시보드 재설계 (회사 선택 → 분석 플로우)
  - RC-5: 매핑 프로파일 회사 연결 + 고급 기능
- **Phase 1 (MVP)** ✅ 1a/1b 완료, 1c는 RC-4에 통합
  - 1a: ingest + feature + validation + EDA ✅
  - 1b: detection (31개 룰) + db + pipeline ✅
  - 1c: dashboard → RC-4에서 회사 선택 UI와 함께 구현
- **Phase 2**: ML/DL 전처리 + 탐지기 (회사별 모델 저장 구조 활용)
- **Phase 3 (Review Queue Narrator)** ✅ **완료 (v2, Sprint A~G 2026-05-15)**: PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 LLM이 읽고 (a) 후보 Top-N 재정렬 (b) 의심 근거 서술 (c) 감사인 다음 행동 제안. **새 패턴 발견·자유 가설 생성은 비범위**. 상세: [docs/PHASE3_REVIEW_NARRATOR_SPEC.md](docs/PHASE3_REVIEW_NARRATOR_SPEC.md) · 완료 리포트: [docs/completed/phase3_review_narrator_completion.md](docs/completed/phase3_review_narrator_completion.md)
  - 비범위(구현 보존, 신규 작업 없음): Text-to-SQL (WU-20), Export Excel/PDF/감사증적 (WU-24/27)

## 문서 가이드

- 관련있는 작업을 할 때 문서가이드를 참조하여 작업 후 업데이트 할 것
- 활성 문서는 `docs/` 루트, 완료/구버전 산출물은 `docs/completed/`. 단일 인덱스는 [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) §활성 문서 인덱스 참조.

### 메인 참조 (전 Phase 공통)

| 문서 | 경로 | 내용 |
|------|------|------|
| 프로젝트 개요 | [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | 기술 스택, 디렉토리 구조, 데이터 흐름, 활성 문서 인덱스 |
| 프로젝트 설명 | [docs/상세.MD](docs/상세.MD), [docs/핵심기능.MD](docs/핵심기능.MD), [docs/EXPLAIN.md](docs/EXPLAIN.md) | 포트폴리오 포지셔닝·기능 설명·1줄 정의 |
| UX 흐름 | [docs/ux-flow.md](docs/ux-flow.md) | 사용자 흐름·UI 원칙·상태 문구 기준 |
| 설계 결정 로그 | [docs/DECISION.md](docs/DECISION.md) | 기술 선택 이유, 아키텍처 결정 |
| 제약·정책 | [docs/CONSTRAINTS.md](docs/CONSTRAINTS.md) | ML 학습 전략, PHASE1 CI KPI 가드, 비식별화 정책 |
| 트러블슈팅 | [docs/TROUBLESHOOT.md](docs/TROUBLESHOOT.md), [docs/debugging.md](docs/debugging.md) | TS 시리즈 결정 + 디버깅 히스토리 |
| 지표 정의 | [docs/metrics.md](docs/metrics.md) | PHASE1 truth/proxy 구분, 평가 지표 |
| Git | [docs/GIT.md](docs/GIT.md) | 브랜치 구조, CI 워크플로우, 태그 규칙 |

### Detection (운영)

| 문서 | 경로 | 내용 |
|------|------|------|
| 탐지 룰 목록 | [docs/DETECTION_RULES.md](docs/DETECTION_RULES.md) | 전체 탐지 룰 목록, 점수 체계, DataSynth 갭, 컬럼 스키마 |
| 탐지 레퍼런스 | [docs/DETECTION_REFERENCE.md](docs/DETECTION_REFERENCE.md) | 법규 체계, 감사기준서 매핑, 금감원 189건 실증 |
| 파라미터 매핑 | [docs/DETECTION_PARAMETERS.md](docs/DETECTION_PARAMETERS.md) | 룰 정의 ↔ 설정·코드·UX 조정면 연결 |
| 포트폴리오 재해석 | [docs/DETECTION_PORTFOLIO_REFRAME.md](docs/DETECTION_PORTFOLIO_REFRAME.md) | 운영 목적 기준 탐지 포트폴리오 |
| Ranking 기준 | [docs/DETECTION_RANKING_CRITERIA.md](docs/DETECTION_RANKING_CRITERIA.md) | PHASE1 7개 topic ranking 정렬 기준 |

### PHASE1 활성 락 / PHASE2 진행

| 문서 | 경로 | 내용 |
|------|------|------|
| Rule Detail Metadata v1 Lock | [docs/RULE_DETAIL_METADATA_V1_LOCK.md](docs/RULE_DETAIL_METADATA_V1_LOCK.md) | 32 canonical rule count, alias/reason code 정책, surface gating |
| Topic Scoring v1 Lock | [docs/PHASE1_TOPIC_SCORING_V1_LOCK.md](docs/PHASE1_TOPIC_SCORING_V1_LOCK.md) | 7개 topic, locked corrections |
| Rule Relationship Map | [docs/PHASE1_RULE_RELATIONSHIP_MAP.md](docs/PHASE1_RULE_RELATIONSHIP_MAP.md) | 룰 간 증폭 관계, scoring 업데이트 |
| Separate Benchmark | [docs/PHASE1_SEPARATE_BENCHMARK_SPEC.md](docs/PHASE1_SEPARATE_BENCHMARK_SPEC.md) | L4-02/03/04/L3-09/L4-05 별도 검증 단위 |
| PHASE2 Governance | [docs/PHASE2_GOVERNANCE_DESIGN.md](docs/PHASE2_GOVERNANCE_DESIGN.md) | KPI 가드 설계, Layer A/B/C |
| PHASE1↔PHASE2 Interface | [docs/PHASE2_INTERFACE_DESIGN.md](docs/PHASE2_INTERFACE_DESIGN.md) | row feature contract, ml_score 결합 정책 |
| PHASE2 Fitting Audit | [docs/PHASE2_FITTING_AUDIT.md](docs/PHASE2_FITTING_AUDIT.md) | Stage 0~10 종합 entry-point |
| PHASE2 Timeseries Role Lock | [docs/PHASE2_TIMESERIES_ROLE_LOCK.md](docs/PHASE2_TIMESERIES_ROLE_LOCK.md) | TS01/TS02 결산·시점 컨텍스트 lane 역할 고정 (결정 9, 2026-05-25) |

### Phase 3 / 최신 결과

| 문서 | 경로 | 내용 |
|------|------|------|
| Phase 3 spec | [docs/PHASE3_REVIEW_NARRATOR_SPEC.md](docs/PHASE3_REVIEW_NARRATOR_SPEC.md) | Review Queue Narrator 입력/출력 계약, 인용 규칙, 비범위 |
| Contract V3 결과 | [docs/DETECTION_RESULTS_CONTRACT_V3.md](docs/DETECTION_RESULTS_CONTRACT_V3.md) | datasynth_contract_v2 전표 단위 재집계 (TS-12 적용) |
| Manipulation V7 결과 | [docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md](docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md) | V7 fixed3 연도별 PHASE2 추가 분석 |

### 완료 / 구버전 산출물 (`docs/completed/`)

| 영역 | 위치 |
|------|------|
| 원본 계획서 & 구현 가이드 (옛 pre-plan) | [docs/completed/raw-plan/](docs/completed/raw-plan/) — `개요서.md`, `00-dataset.md` ~ `10-sample-data.md`, `03a-preprocessing.md`, `05a-detection-ml.md` (13개 파일) |
| Phase 3 재코딩 계획 (완료) | [docs/completed/PHASE3_REWORK_PLAN.md](docs/completed/PHASE3_REWORK_PLAN.md) |
| Phase 3 완료 리포트 | [docs/completed/phase3_review_narrator_completion.md](docs/completed/phase3_review_narrator_completion.md) |
| PHASE1 Topic Scoring 완료 | [docs/completed/PHASE1_TOPIC_SCORING_V1_COMPLETION.md](docs/completed/PHASE1_TOPIC_SCORING_V1_COMPLETION.md) |
| RC 재설계 태스크 (완료) | [docs/completed/NEW_TASKS.MD](docs/completed/NEW_TASKS.MD) |
| DataSynth 품질·계획·sidecar | [docs/completed/datasynth.md](docs/completed/datasynth.md), `datasynth_*_v126.*`, `DATASYNTH_*.md` |
| PHASE1 Remodeling Plan | [docs/completed/PHASE1_REMODELING_PLAN.md](docs/completed/PHASE1_REMODELING_PLAN.md) |
| Rule Detail Metadata 입력자료 (tmp_context_a~e) | [docs/completed/tmp_context_*.md](docs/completed/) |
| S 시리즈 Stage 산출 | `docs/completed/S3_*.md`, `S8_*.md`, `S9_*.md` |
| 구버전 DETECTION_RESULTS | `docs/completed/DETECTION_RESULTS_CONTRACT.md`/V2, `DETECTION_RESULTS_D/L1/L2/L3/L4.md`, `DETECTION_RESULTS_MANIPULATION.md`/V2/V3/V4/V7_FIXED3 |
| Phase 1/2/3 feasibility | `docs/completed/phase1_feasibility.md`, `phase2_ml_feasibility.md`, `phase3_llm_feasibility.md` |

> 작업 전 관련 docs를 먼저 읽고, 완료 후 변경사항 반영할 것.
> 구현 시 해당 영역의 `completed/raw-plan/0X-*.md` 가이드를 참조할 것 (구 pre-plan).

### ⚠️ 태스크 시작/종료 시 필수 체크리스트
1. **시작 시**: 올바른 브랜치에서 작업 중인지 확인 (`docs/GIT.md` 브랜치 전략 참고)
2. **시작 시**: 활성 plan/context/tasks 위치 — `dev/active/<plan-name>/`
3. **종료 시**: `docs/debugging.md`에 트러블슈팅 기록 (있을 경우) + 관련 docs 문서 최신화
4. **종료 시**: 새로 완료된 산출물은 `docs/completed/`로 이동하고 본 가이드 표 갱신

## 핵심 코딩 규칙

- **모듈**: 파일당 100줄 내외, SRP 준수
- **탐지 트랙 추가**: `BaseDetector(ABC)` 상속 → `detect() -> DetectionResult` 구현
- **DB**: Engagement별 격리 DuckDB (`data/companies/{id}/engagements/{year}/audit.duckdb`)
- **설정**: `CompanyContext` (3계층 해소) → 글로벌 폴백: `config/settings.py` (Pydantic Settings) + YAML
- **데이터 검증**: Pandera 스키마 기반 (L1 구조 → L2 회계 → L3 통계)
- **디버깅**: `systematic-debugging` 스킬의 4단계 프레임워크를 따른다

## DATASYNTH 생성 규칙

- 테스트에 데이터를 끼워 맞추지(fitting) 말고, 데이터 자체를 올바르게 생성하라.
- **정상 데이터**: 회계적으로 정상 (차대변 균형, 양수 금액, 기간 범위 내) + 자연적 노이즈 (MCAR 결측, 오타, 서식 변동)
- **비정상 데이터**: 의도적 이상 패턴 (fraud, error, process issue) + 라벨로 완전 추적
- **데이터 품질 (MCAR, typo, format)**: 정상/비정상 무관하게 **동일 비율** 적용. ML 지름길 학습·일반화 실패·허위 피처 중요도·합성 아티팩트 방지.
- RUST 로 근본부터 제대로 수정, PYTHON으로 덧대기 금지
- datasynth 재생성 작업 후 C:\Users\ghdtj\workspace\portfolio\local-ai-assist\docs\debugging.md 업데이트

## 이슈 추적 & 리포트 규칙

- **교차 참조 필수**: 미해결 이슈는 발견 문서(`completed/raw-plan/0X-*.md` 또는 활성 spec/lock 문서)와 해결 문서 **양쪽 모두** 기록. "해결 위치" 또는 "발견 위치" 컬럼으로 상호 링크.
- **test-results 리포트 3단 분류**: "문제점" 섹션에서 코드 버그 / Graceful Degradation(정상) / 데이터 특성을 구분. 의도된 미생성(필수 컬럼 부재 등)은 "문제점"이 아님.
- **리포트 중복 금지**: 동일 내용을 다른 섹션에 복붙하지 않음. (예: §3과 §5가 동일하면 §5 제거)

## Skill 활용 맵

| Phase | 활용 Skill |
|-------|-----------|
| 전 Phase 공통 | `tdd`, `verification-before-completion`, `systematic-debugging` |
| 파급 변경 시 | `ripple-search` |
| 서브에이전트 | `subagent-orchestration` |
| RC-0~3 (인프라/파이프라인/DB) | `python-code-quality`, `pytest-backend-testing`, `duckdb` |
| RC-4~5 (대시보드/매핑) | `developing-with-streamlit`, `python-code-quality` |
| 1a (ingest/feature) | `data-analysis`, `python-code-quality`, `python-packaging`, `pytest-backend-testing` |
| 1b (detection/db) | `duckdb`, `data-analysis`, `pytest-backend-testing` |
| 1c (dashboard) → RC-4 | `developing-with-streamlit`, `python-code-quality` |
| Phase 2 (ML) | `data-analysis`, `python-code-quality`, `mermaid` (아키텍처 다이어그램) |
| Phase 3 (Review Queue Narrator) | `langgraph-rag-guidelines`, `claude-api` |

## Agent 활용 가이드

| Agent | 용도 | 비고 |
|-------|------|------|
| `planner` | 새 Phase/Sub-phase 시작 시 구현 계획 수립 | 커스텀 에이전트 |
| `code-reviewer` | 주요 모듈 구현 완료 후 코드 리뷰 | 커스텀 에이전트 |
| `error-resolver` | 빌드/런타임 에러 진단 | 커스텀 에이전트 |
| `documentation-architect` | 문서 작성/리뷰/품질 검증 | 커스텀 에이전트 |
| `Explore` | 코드베이스 탐색, 의존성 추적 | 내장 Agent tool |
| `Plan` | 아키텍처 설계, 리팩토링 전략 | 내장 Agent tool |

## dependency-groups

```
core = ["pandas>=2.2", "openpyxl", "pandera", "rapidfuzz", "duckdb", "scipy", "numpy", "pyyaml", "pydantic-settings"]
ml = ["xgboost", "scikit-learn", "shap", "torch"]
nlp = ["kiwipiepy"]
llm = ["vanna[duckdb,chromadb]", "openai"]
dashboard = ["streamlit", "plotly", "streamlit-aggrid"]
export = ["fpdf2"]
dev = ["pytest", "ruff", "mypy"]
```

MVP 설치: `uv sync --group core --group dashboard --group dev`
