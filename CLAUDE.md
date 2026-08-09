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
  - **PHASE1-1 (룰)**: 전표/행 단위 결정론 룰 → 명명된 위반. **tier 자동 등급(HIGH/MEDIUM/LOW/CONTEXT) 전면 폐지(2026-07-17)** → **조합 빌더 + 프리셋**으로 대체 (SoT: [docs/spec/PHASE1_COMBO_BUILDER_SPEC.md](docs/spec/PHASE1_COMBO_BUILDER_SPEC.md)). 어휘 = 몸통 9(금감원 v3 확정 빈도) × 특징 10(감사기준서 240 부정 분개 특징), 조합 선택 = 감사인 판단(시스템은 등급 비선언). 커버리지 큐(룰별 전수)와 데이터정합성 패널(L1-01~03 + L1-08)은 별도 표면. **L1-08 기간귀속은 몸통에서 제거(2026-07-27)** — 원장 fiscal_period 는 ERP 가 posting_date 로 정하므로 둘의 비교가 동어반복(실측 전건 불일치 0), 데이터정합성 패널 전용으로 되돌림.
  - **PHASE1-2 (분석적 검토 신호)**: "전표 한 장으론 안 보이고 계정·거래처를 모아야 보이는" 모집단 단위 신호(ISA 520). **자기 큐 5종**(Benford L4-02·D01·D02·라운드넘버 밀집도·첫등장/희소 거래처) + **배지**(L4-05·L4-06·L3-12·라운드넘버 단건·첫등장/희소 전표, 점수 비병합). 신호만 생성하고 검토 목록은 소유하지 않는다(절단 없음). 구 family(graph GR01/03·relational R01~R09·IC01~03)는 **단일 법인 확정으로 완전 삭제**(2026-06-30, L3-03 관계사 꼬리표만 PHASE1-1 조합용 잔존), 시계열은 **PHASE2 lane 잔류**(2026-07-15 — 당기내 집중 자기 큐는 실측 후 폐기, D02 드릴다운으로 재정의).
  - 1c: dashboard → RC-4에서 회사 선택 UI와 함께 구현
- **Phase 2 (VAE companion surface)**: 정상 분포 비지도 학습(VAE) 단독 surface. 학습된 정상 밖 비정형을 추가 검토 후보로 surface(부정 확정 아님).
  - **3-surface 불변식**: PHASE1-1 룰 / PHASE1-2 family / PHASE2 VAE 세 surface는 절대 비병합(독립 탭/뷰/큐, 단일 점수 미병합).
- **Phase 3**: Removed from active product path (2026-05-26). 선택된 PHASE1 case 설명은 외부 API 호출 없이 Local Evidence Brief가 기존 룰/문서/family 신호를 deterministic summary로 표시한다. (구 상세 스펙 `docs/spec/LOCAL_EVIDENCE_BRIEF_SPEC.md` 는 삭제됨)
  - historical only: PHASE3 Review Narrator, Text-to-SQL, LLM rule feedback

## 문서 가이드

> 아래는 **실제 존재하는 파일만** 적는다. 없는 문서를 표에 되살리지 말 것 — 죽은 링크를 쫓다
> 폐기된 문서로 떨어지는 사고가 반복됐다.

- 작업 관련 문서를 먼저 읽고, 완료 후 변경사항을 반영한다.
- 문서 본체 = `FINAL-REPORT/`. `docs/` 에는 SoT 몇 건과 작업 기록만 남아 있다.

### FINAL-REPORT — 문서 본체 (17개)

| 파일                                               | 내용                                        |
| -------------------------------------------------- | ------------------------------------------- |
| `0_README.md` · `1_OVERVIEW.md`                    | 진입점, 프로젝트 개요                       |
| `2_PIPELINE.md`                                    | 데이터 흐름                                 |
| `3_DATASYNTH-ENGINE.md` · `4_DATASYNTH-QUALITY.md` | 합성 생성기 · 품질 게이트                   |
| `5_INGEST-FEATURE.md`                              | 적재 · 피처                                 |
| `6_PHASE1-1_RULES.md`                              | **룰 SoT** — 룰 정의, §6.6 발화율 대역 판정 |
| `7_PHASE1-1_COMBO-BUILDER.md`                      | 조합 빌더                                   |
| `8_PHASE1-2_ANALYTICAL.md`                         | 분석적 검토 신호                            |
| `9_PHASE2_VAE.md`                                  | 비지도 VAE                                  |
| `10_PLATFORM.md` · `11_DASHBOARD.md`               | 플랫폼 · 대시보드                           |
| `12_DIFFERENTIATION.md` · `13_TEST-DECISIONS.md`   | 차별점 · 테스트 결정                        |
| `14_JOURNEY.md` · `15_TROUBLESHOOTING.md`          | 개발 여정 · 트러블슈팅                      |
| `16_COVERAGE.md`                                   | 커버리지                                    |

### docs/ — 살아있는 것 전부

| 경로                                       | 역할                                                                             |
| ------------------------------------------ | -------------------------------------------------------------------------------- |
| `docs/spec/PHASE1_COMBO_BUILDER_SPEC.md`   | **PHASE1-1 현행 SoT** — tier 폐지(2026-07-18) 후 조합 빌더+프리셋                |
| `docs/spec/results/normal/`                | 정상 데이터 실측 결과 기록                                                       |
| `docs/0716/S1_RULE_BANDS.md`               | **룰 발화율 대역 SoT** — 실측 전 선언, 3분류(①생성기 결함 ②룰 과탐 ③대역 오선언) |
| `docs/0716/PLAN.md`                        | S 시리즈 검증 라운드 계획                                                        |
| `docs/guide/VALIDATION_RESULTS_2026-07.md` | S1~S5 검증 종합                                                                  |
| `docs/guide/users/`                        | 사용자·포트폴리오 서술 (00_INDEX.md 부터)                                        |
| `docs/methodology/`                        | CARDS · FACTCHECK · GAPS · GLOSSARY · QBANK                                      |
| `docs/phase1-1/fsscombo.md`                | 금감원 조합 검증                                                                 |
| `docs/archive/completed/`                  | 완료 산출물 3건                                                                  |

> ⚠️ `docs/` 는 `dd02727` 로 git 추적에서 제외됐다 — 로컬에만 있고 이력이 남지 않는다.
> 삭제·덮어쓰기 전 반드시 내용을 확인할 것.

### 폐지된 개념 — 문서에서 보이면 무시할 것

| 개념                                    | 상태                                                                           |
| --------------------------------------- | ------------------------------------------------------------------------------ |
| tier 자동등급 (HIGH/MEDIUM/LOW/CONTEXT) | **2026-07-18 `87d97e0` 전면 폐지.** "단독 발화는 LOW 흡수" 류 근거는 전부 무효 |
| `priority_band`                         | 폐지된 tier 의 잔재 필드 — 코드가 항상 `"low"` 를 넣는다. 지표로 쓰지 말 것    |
| combo floor 12종                        | tier 와 함께 폐지                                                              |
| `docs/spec/DETECTION_RULES.md`          | 삭제됨. 룰 SoT 는 `FINAL-REPORT/6_PHASE1-1_RULES.md`                           |

### ⚠️ 태스크 시작/종료 시 필수 체크리스트
1. **시작 시**: 올바른 브랜치에서 작업 중인지 확인. main 직접 커밋 금지
2. **시작 시**: 다단계 작업이면 `dev/<작업명>/` 에 context.md·tasks.md 를 판다 (전역 룰)
3. **종료 시**: 트러블슈팅은 `FINAL-REPORT/15_TROUBLESHOOTING.md` 에 기록 + 관련 문서 최신화
4. **종료 시**: 수치를 바꿨으면 그 수치를 인용한 문서를 전부 찾아 갱신 (README·FINAL-REPORT 교차 인용 잦음)

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

Issues live in GitHub Issues for `ghdtjrgns321-creator/local-ai-journal-assist` (uses the `gh` CLI). External PRs are not a triage surface.

### Triage labels

Five canonical roles use their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).

### Domain docs

Single-context — the project brief lives in `CLAUDE.md` / `AGENTS.md`; there is no separate `docs/adr/`.
