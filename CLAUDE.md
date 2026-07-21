# Local AI Audit Assistant v2.0

> 보조 파일 — 영문 정책 (Stack / Non-negotiables / Common Commands / Testing / Coding / Audit / DataSynth / Skill 활용 / Safety / Secrets / Git) 은 [AGENTS.md](./AGENTS.md) 참조. 본 파일은 한국어 Phase 로드맵 + 문서 인덱스 + Skill/Agent 활용 맵 + gpt-5.4 티어 메모. 양쪽 모두 각 도구가 자동 로드, 중복 룰은 공유 동기화 체크리스트 메모리로 관리.

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

감사 실증절차 전표 테스트를 로컬 환경에서 자동화하는 Python 프로젝트.
PCAOB AS 2401, ISA 240 커버. MindBridge/KPMG Clara 핵심 로직을 오픈소스로 재현.

## Quick Reference

| 항목          | 값                                                           |
| ------------- | ------------------------------------------------------------ |
| Python        | 3.11+                                                        |
| 패키지 관리   | uv + pyproject.toml (dependency-groups)                      |
| DB            | DuckDB (OLAP)                                                |
| 대시보드      | Streamlit + Plotly + AgGrid                                  |
| LLM (Phase 3) | Removed from active product path — Local Evidence Brief only |
| 테스트        | pytest (`uv run pytest tests/ -v`)                           |
| 실행          | `uv run streamlit run dashboard/app.py`                      |

## Phase 로드맵

- **RC (Restructure)**: Company-Centric 아키텍처 전면 재설계 — 41개 태스크
  - RC-0: Company 인프라 (CompanyContext + ContextFactory + CRUD)
  - RC-1: 파이프라인 Context 주입
  - RC-2: 싱글톤 직접 호출 제거
  - RC-3: DB 격리 (Engagement별 DuckDB) + ConnectionManager
  - RC-4: 대시보드 재설계 (회사 선택 → 분석 플로우)
  - RC-5: 매핑 프로파일 회사 연결 + 고급 기능
- **Phase 1 (MVP)** ✅ 1a/1b 완료, 1c는 RC-4에 통합 — C안 3-surface 구조로 PHASE1-1/PHASE1-2 분리 (PHASE1-1 검토표면 SoT: [docs/spec/PHASE1_COMBO_BUILDER_SPEC.md](docs/spec/PHASE1_COMBO_BUILDER_SPEC.md))
  - 1a: ingest + feature + validation + EDA ✅
  - 1b: detection (29개 룰) + db + pipeline ✅
  - **PHASE1-1 (룰)**: 전표/행 단위 결정론 룰 → 명명된 위반. **tier 자동 등급(HIGH/MEDIUM/LOW/CONTEXT) 전면 폐지(2026-07-17)** → **조합 빌더 + 프리셋**으로 대체 (SoT: [docs/spec/PHASE1_COMBO_BUILDER_SPEC.md](docs/spec/PHASE1_COMBO_BUILDER_SPEC.md)). 어휘 = 몸통 10(금감원 v3 확정 빈도) × 특징 10(감사기준서 240 부정 분개 특징), 조합 선택 = 감사인 판단(시스템은 등급 비선언). 커버리지 큐(룰별 전수)와 데이터정합성 패널(L1-01~03)은 별도 표면.
  - **PHASE1-2 (분석적 검토 신호)**: "전표 한 장으론 안 보이고 계정·거래처를 모아야 보이는" 모집단 단위 신호(ISA 520). **자기 큐 5종**(Benford L4-02·D01·D02·라운드넘버 밀집도·첫등장/희소 거래처) + **배지**(L4-05·L4-06·L3-12·라운드넘버 단건·첫등장/희소 전표, 점수 비병합). 신호만 생성하고 검토 목록은 소유하지 않는다(절단 없음). 구 family(graph GR01/03·relational R01~R09·IC01~03)는 **단일 법인 확정으로 완전 삭제**(2026-06-30, L3-03 관계사 꼬리표만 PHASE1-1 조합용 잔존), 시계열은 **PHASE2 lane 잔류**(2026-07-15 — 당기내 집중 자기 큐는 실측 후 폐기, D02 드릴다운으로 재정의).
  - 1c: dashboard → RC-4에서 회사 선택 UI와 함께 구현
- **Phase 2 (VAE companion surface)**: 정상 분포 비지도 학습(VAE) 단독 surface. 학습된 정상 밖 비정형을 추가 검토 후보로 surface(부정 확정 아님).
  - **3-surface 불변식**: PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE 세 surface는 절대 비병합(독립 탭/뷰/큐, 단일 점수 미병합).
- **Phase 3**: Removed from active product path (2026-05-26). 선택된 PHASE1 case 설명은 외부 API 호출 없이 Local Evidence Brief가 기존 룰/문서/family 신호를 deterministic summary로 표시한다. 상세: [docs/spec/LOCAL_EVIDENCE_BRIEF_SPEC.md](docs/spec/LOCAL_EVIDENCE_BRIEF_SPEC.md)
  - historical only: PHASE3 Review Narrator, Text-to-SQL, LLM rule feedback

## 문서 가이드

- 관련있는 작업을 할 때 문서가이드를 참조하여 작업 후 업데이트 할 것
- 사용자/포트폴리오 문서는 `docs/guide/`, 권위 기준 문서는 `docs/spec/`, 완료 산출물은 `docs/archive/completed/`, 폐기/구버전 결정은 `docs/archive/abandoned/`. 예외적으로 [docs/debugging.md](docs/debugging.md)는 전역 훅 호환을 위해 루트에 유지한다. 단일 인덱스는 [docs/guide/PROJECT_OVERVIEW.md](docs/guide/PROJECT_OVERVIEW.md) §활성 문서 인덱스 참조.

### 메인 참조 (전 Phase 공통)

| 문서           | 경로                                                                                                                                       | 내용                                                             |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| 프로젝트 개요  | [docs/guide/PROJECT_OVERVIEW.md](docs/guide/PROJECT_OVERVIEW.md)                                                                           | 기술 스택, 디렉토리 구조, 데이터 흐름, 활성 문서 인덱스          |
| 프로젝트 설명  | [docs/guide/상세.MD](docs/guide/상세.MD), [docs/guide/핵심기능.MD](docs/guide/핵심기능.MD), [docs/guide/EXPLAIN.md](docs/guide/EXPLAIN.md) | 포트폴리오 포지셔닝·기능 설명·1줄 정의                           |
| 개발 방법론    | [docs/guide/개발방법론.md](docs/guide/개발방법론.md)                                                                                       | 데이터-우선·검증중심 탐지 개발 순서(6단계)와 원칙 (포트폴리오용) |
| UX 흐름        | [docs/guide/ux-flow.md](docs/guide/ux-flow.md)                                                                                             | 사용자 흐름·UI 원칙·상태 문구 기준                               |
| 설계 결정 로그 | [docs/spec/DECISION.md](docs/spec/DECISION.md)                                                                                             | 기술 선택 이유, 아키텍처 결정                                    |
| 제약·정책      | [docs/spec/CONSTRAINTS.md](docs/spec/CONSTRAINTS.md)                                                                                       | ML 학습 전략, PHASE1 CI KPI 가드, 비식별화 정책                  |
| 트러블슈팅     | [docs/spec/TROUBLESHOOT.md](docs/spec/TROUBLESHOOT.md), [docs/debugging.md](docs/debugging.md)                                             | TS 시리즈 결정 + 디버깅 히스토리                                 |
| 지표 정의      | [docs/spec/metrics.md](docs/spec/metrics.md)                                                                                               | PHASE1 truth/proxy 구분, 평가 지표                               |
| Git            | [docs/spec/GIT.md](docs/spec/GIT.md)                                                                                                       | 브랜치 구조, CI 워크플로우, 태그 규칙                            |

### Detection (운영)

| 문서                      | 경로                                                                                           | 내용                                                                                                                          |
| ------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 탐지 룰 목록 (PHASE1-1)   | [docs/spec/DETECTION_RULES.md](docs/spec/DETECTION_RULES.md)                                   | PHASE1-1 L1~L4 행 단위 룰 SoT, 점수 체계, DataSynth 갭, 컬럼 스키마                                                           |
| L1-06 SoD toxic 조합 근거 | [docs/spec/SOD_TOXIC_COMBINATIONS_GROUNDING.md](docs/spec/SOD_TOXIC_COMBINATIONS_GROUNDING.md) | 직무분리 toxic 업무조합(7프로세스→4기능, 12조합) 3축 근거 해설. 데이터 SoT는 config/sod_toxic_combinations.yaml               |
| PHASE1-2 룰 (분석적 검토) | [docs/spec/DETECTION_RULES_PHASE1-2.MD](docs/spec/DETECTION_RULES_PHASE1-2.MD)                 | 자기 큐 5종(L4-02·D01·D02·라운드넘버 밀집도·첫등장/희소) + 배지(L4-05·L4-06·L3-12). GR/IC/relational 삭제, 시계열 PHASE2 잔류 |
| Phase 2 ML 룰             | [docs/spec/DETECTION_RULES_PHASE2_ML.md](docs/spec/DETECTION_RULES_PHASE2_ML.md)               | Phase 2 ML/DL 보조 분석 (VAE 등 model family)                                                                                 |
| 룰 원칙 해설 (사용자용)   | [docs/guide/룰원칙해설.md](docs/guide/룰원칙해설.md)                                           | 비회계 사용자용 — 룰별 "왜 신호인가·숨은 도메인 가정" 전수 해설 (canonical 29 + macro/보조 L4-02/IC/GR/D)                     |
| 단위 측정 정책            | [docs/spec/UNIT_MEASUREMENT_POLICY.md](docs/spec/UNIT_MEASUREMENT_POLICY.md)                   | PHASE1·PHASE2 탐지 단위와 분모/분자 측정 기준 SoT                                                                             |
| 탐지 레퍼런스             | [docs/spec/DETECTION_REFERENCE.md](docs/spec/DETECTION_REFERENCE.md)                           | 법규 체계, 감사기준서 매핑, 금감원 189건 실증                                                                                 |
| 파라미터 매핑             | [docs/spec/DETECTION_PARAMETERS.md](docs/spec/DETECTION_PARAMETERS.md)                         | 룰 정의 ↔ 설정·코드·UX 조정면 연결                                                                                            |
| 포트폴리오 재해석         | [docs/spec/DETECTION_PORTFOLIO_REFRAME.md](docs/spec/DETECTION_PORTFOLIO_REFRAME.md)           | 운영 목적 기준 탐지 포트폴리오                                                                                                |
| Ranking 기준              | [docs/spec/DETECTION_RANKING_CRITERIA.md](docs/spec/DETECTION_RANKING_CRITERIA.md)             | (SUPERSEDED 2026-07-17) 구 tier ranking — 정렬 원칙만 빌더 sort_key 로 승계                                                   |

### PHASE1 활성 락 / PHASE2 진행

| 문서                              | 경로                                                                                                             | 내용                                                                                                                                                 |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Combo Builder Spec (현행 SoT)** | [docs/spec/PHASE1_COMBO_BUILDER_SPEC.md](docs/spec/PHASE1_COMBO_BUILDER_SPEC.md)                                 | PHASE1-1 조합 빌더 — 몸통10(금감원)×특징10(기준서240)·프리셋4·tier 폐지(2026-07-17)                                                                  |
| PHASE1 Tier Evidence Basis        | [docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md](docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md)                               | (SUPERSEDED 2026-07-17 — tier 폐지, 현행 SoT는 PHASE1_COMBO_BUILDER_SPEC) 구 tier 근거 이력                                                          |
| Rule Detail Metadata v1 Lock      | [docs/archive/completed/RULE_DETAIL_METADATA_V1_LOCK.md](docs/archive/completed/RULE_DETAIL_METADATA_V1_LOCK.md) | 29 canonical rule count (L4-02 PHASE1-2 이관), alias/reason code 정책, surface gating. 현행 SoT는 `src/detection/rule_detail_metadata.py`(assert 29) |
| Topic Scoring v1 Lock             | [docs/archive/completed/PHASE1_TOPIC_SCORING_V1_LOCK.md](docs/archive/completed/PHASE1_TOPIC_SCORING_V1_LOCK.md) | **[2026-06-16 archive 이관]** 구 가중합/floor/band컷 v1 lock 역사 기록. 현행 SoT는 PHASE1_COMBO_BUILDER_SPEC (tier 폐지 2026-07-17)                  |
| Rule Relationship Map             | [docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md](docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md)                           | 룰 간 증폭 관계, scoring 업데이트                                                                                                                    |
| Separate Benchmark                | [docs/spec/PHASE1_SEPARATE_BENCHMARK_SPEC.md](docs/spec/PHASE1_SEPARATE_BENCHMARK_SPEC.md)                       | L4-02/03/04/L3-09/L4-05 별도 검증 단위                                                                                                               |
| PHASE2 Governance                 | [docs/spec/PHASE2_GOVERNANCE_DESIGN.md](docs/spec/PHASE2_GOVERNANCE_DESIGN.md)                                   | KPI 가드 설계, Layer A/B/C                                                                                                                           |
| PHASE1↔PHASE2 Interface           | [docs/spec/PHASE2_INTERFACE_DESIGN.md](docs/spec/PHASE2_INTERFACE_DESIGN.md)                                     | row feature contract, ml_score 결합 정책                                                                                                             |
| PHASE2 Fitting Audit              | [docs/spec/PHASE2_FITTING_AUDIT.md](docs/spec/PHASE2_FITTING_AUDIT.md)                                           | Stage 0~10 종합 entry-point                                                                                                                          |
| PHASE2 Timeseries Role Lock       | [docs/spec/PHASE2_TIMESERIES_ROLE_LOCK.md](docs/spec/PHASE2_TIMESERIES_ROLE_LOCK.md)                             | TS01/TS02 결산·시점 컨텍스트 lane 역할 고정 (결정 9, 2026-05-25)                                                                                     |

### Phase 3 / 최신 결과

| 문서                                    | 경로                                                                                                                           | 내용                                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| Local Evidence Brief                    | [docs/spec/LOCAL_EVIDENCE_BRIEF_SPEC.md](docs/spec/LOCAL_EVIDENCE_BRIEF_SPEC.md)                                               | Local-only selected case evidence summary contract                                    |
| Contract V3 결과                        | [docs/guide/DETECTION_RESULTS_CONTRACT_V3.md](docs/guide/DETECTION_RESULTS_CONTRACT_V3.md)                                     | datasynth_contract_v2 전표 단위 재집계 (TS-12 적용)                                   |
| Manipulation V7 결과                    | [docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md](docs/guide/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md) | V7 fixed3 연도별 PHASE2 추가 분석                                                     |
| **2026-07 검증 종합 (포트폴리오 본문)** | [docs/guide/VALIDATION_RESULTS_2026-07.md](docs/guide/VALIDATION_RESULTS_2026-07.md)                                           | S1~S5 검증 라운드 종합 — 룰 표면 성공·행 단위 VAE 실패 기록·원리적 한계·빅4 실무 정합 |

### 완료 / 구버전 산출물 (`docs/archive/`)

| 영역                                            | 위치                                                                                                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 원본 계획서 & 구현 가이드 (옛 pre-plan)         | [docs/archive/completed/raw-plan/](docs/archive/completed/raw-plan/) — `개요서.md`, `00-dataset.md` ~ `10-sample-data.md`, `03a-preprocessing.md`, `05a-detection-ml.md` (13개 파일) |
| Phase 3 재코딩 계획 (폐기)                      | [docs/archive/abandoned/PHASE3_REWORK_PLAN.md](docs/archive/abandoned/PHASE3_REWORK_PLAN.md)                                                                                         |
| Phase 3 완료 리포트 (폐기)                      | [docs/archive/abandoned/phase3_review_narrator_completion.md](docs/archive/abandoned/phase3_review_narrator_completion.md)                                                           |
| PHASE1 Topic Scoring 완료                       | [docs/archive/completed/PHASE1_TOPIC_SCORING_V1_COMPLETION.md](docs/archive/completed/PHASE1_TOPIC_SCORING_V1_COMPLETION.md)                                                         |
| RC 재설계 태스크 (완료)                         | [docs/archive/completed/NEW_TASKS.MD](docs/archive/completed/NEW_TASKS.MD)                                                                                                           |
| DataSynth 품질·계획·sidecar                     | [docs/archive/completed/datasynth.md](docs/archive/completed/datasynth.md), `datasynth_*_v126.*`, `DATASYNTH_*.md`                                                                   |
| PHASE1 Remodeling Plan                          | [docs/archive/completed/PHASE1_REMODELING_PLAN.md](docs/archive/completed/PHASE1_REMODELING_PLAN.md)                                                                                 |
| Rule Detail Metadata 입력자료 (tmp_context_a~e) | [docs/archive/completed/tmp_context_*.md](docs/archive/completed/)                                                                                                                   |
| S 시리즈 Stage 산출                             | `docs/archive/completed/S3_*.md`, `S8_*.md`, `S9_*.md`                                                                                                                               |
| 구버전 DETECTION_RESULTS                        | `docs/archive/completed/DETECTION_RESULTS_CONTRACT.md`/V2, `DETECTION_RESULTS_D/L1/L2/L3/L4.md`, `DETECTION_RESULTS_MANIPULATION.md`/V2/V3/V4/V7_FIXED3                              |
| Phase 1/2/3 feasibility                         | `docs/archive/completed/phase1_feasibility.md`, `phase2_ml_feasibility.md`, `docs/archive/abandoned/phase3_llm_feasibility.md`                                                       |

> 작업 전 관련 docs를 먼저 읽고, 완료 후 변경사항 반영할 것.
> 구현 시 해당 영역의 `completed/raw-plan/0X-*.md` 가이드를 참조할 것 (구 pre-plan).

### ⚠️ 태스크 시작/종료 시 필수 체크리스트
1. **시작 시**: 올바른 브랜치에서 작업 중인지 확인 (`docs/spec/GIT.md` 브랜치 전략 참고)
2. **시작 시**: 활성 plan/context/tasks 위치 — `dev/active/<plan-name>/`
3. **종료 시**: `docs/debugging.md`에 트러블슈팅 기록 (있을 경우) + 관련 docs 문서 최신화
4. **종료 시**: 새로 완료된 산출물은 `docs/archive/completed/`로 이동하고 본 가이드 표 갱신

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

| Phase                                  | 활용 Skill                                                                           |
| -------------------------------------- | ------------------------------------------------------------------------------------ |
| 전 Phase 공통                          | `superpowers` 플러그인 (TDD·완료검증·디버깅)                                         |
| 파급 변경 시                           | `ripple-search`                                                                      |
| 서브에이전트                           | `subagent-orchestration`                                                             |
| RC-0~3 (인프라/파이프라인/DB)          | `python-code-quality`, `pytest-backend-testing`, `duckdb`                            |
| RC-4~5 (대시보드/매핑)                 | `developing-with-streamlit`, `python-code-quality`                                   |
| 1a (ingest/feature)                    | `data-analysis`, `python-code-quality`, `python-packaging`, `pytest-backend-testing` |
| 1b (detection/db)                      | `duckdb`, `data-analysis`, `pytest-backend-testing`                                  |
| 1c (dashboard) → RC-4                  | `developing-with-streamlit`, `python-code-quality`                                   |
| Phase 2 (ML)                           | `data-analysis`, `python-code-quality`, `mermaid` (아키텍처 다이어그램)              |
| Local Evidence Brief / Phase 3 removal | `python-code-quality`, `pytest-backend-testing`                                      |

## Agent 활용 가이드

| Agent                              | 용도                                      | 비고            |
| ---------------------------------- | ----------------------------------------- | --------------- |
| `Plan` (빌트인)                    | 새 Phase/Sub-phase 시작 시 구현 계획 수립 | 내장 Agent tool |
| `code-reviewer`                    | 주요 모듈 구현 완료 후 코드 리뷰          | 커스텀 에이전트 |
| `superpowers:systematic-debugging` | 빌드/런타임 에러 진단·근본원인            | 플러그인        |
| `documentation-architect`          | 문서 작성/리뷰/품질 검증                  | 커스텀 에이전트 |
| `Explore`                          | 코드베이스 탐색, 의존성 추적              | 내장 Agent tool |
| `Plan`                             | 아키텍처 설계, 리팩토링 전략              | 내장 Agent tool |

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

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `ghdtjrgns321-creator/local-ai-journal-assist` (uses the `gh` CLI). External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles use their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
