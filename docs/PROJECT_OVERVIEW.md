# Project Overview

> PHASE1 operating role: PHASE1 is a rule-based full-population screening layer, not a final fraud classifier. Its first job is to surface all records, groups, and macro signals that violate configured rules or deserve review. The second step classifies those hits into normal exceptions, auditor review queues, and high-risk candidates using materiality, evidence strength, case priority, company exception policy, and rule combinations.

> Current DataSynth baseline: `data/journal/primary/datasynth/` freeze `v59` as of 2026-04-27. Dataset size is `1,109,435` rows / `319,193` documents / `52` columns. Main label sidecar: `labels/anomaly_labels.csv` `2,843` rows.

> PHASE1 scoring baseline: rule results are normalized through `src/detection/rule_scoring.py` before case aggregation. Dashboard/report priority is case-level `priority_score`, not a direct sum of raw rule labels or row-level `anomaly_score`.

> Current PHASE1 rule scope: 32 L1~L4 implemented rules. L3-12 is an `access_scope_review` work-scope review signal, separated from L1-06 direct SoD violations and promoted only through `work_scope_combo_score` when corroborating rule groups are present.

## 프로젝트 정의

Local AI Audit Assistant v2.0 — 감사 실증절차 전표 테스트 자동화 도구.
MindBridge, KPMG Clara의 핵심 로직을 오픈소스(Python)로 재현하는 포트폴리오.

## 기술 스택

| 영역        | 기술                               | 비고                                        |
|-------------|------------------------------------|---------------------------------------------|
| 언어        | Python 3.11+                       |                                             |
| 패키지      | uv + pyproject.toml                | dependency-groups로 core/ml/llm/dashboard 분리 |
| 전처리      | openpyxl, pandas 2.x, pandera      | pandera: 스키마 기반 품질 게이트            |
| 컬럼 매핑   | rapidfuzz                          | fuzzy string matching                       |
| 설정        | pydantic-settings, pyyaml          | 환경변수 + YAML                             |
| 통계        | scipy.stats, numpy                 | Benford, KS 검정, Runs test                |
| 지도학습    | xgboost, lightgbm, scikit-learn, shap | 파이프라인 인프라 (고객사 실데이터 fine-tuning용, Phase 2) |
| 비지도학습  | pytorch (VAE), scikit-learn (IF)   | **핵심 탐지기** — 합성 데이터 적합도 높음 (Phase 2)  |
| 한국어 NLP  | kiwipiepy                          | JVM 의존성 없음 (Phase 3)                  |
| DB          | duckdb                             | OLAP 최적화                                 |
| LLM         | 상용 API (Gemini, Claude 등)       | Phase 3 — 로컬 LLM 대신 상용 API 사용      |
| Text-to-SQL | 상용 LLM API 기반                  | Phase 3                                     |
| 벡터 DB     | ChromaDB                           | RAG 스토리지 (Phase 3)                     |
| 대시보드    | streamlit, plotly, streamlit-aggrid |                                             |
| PDF         | fpdf2                              | Phase 3                                     |

## 디렉토리 구조

> **아키텍처 전환 (2026-04-02)**: Company-Centric 재설계 진행 중. [NEW_TASKS.MD](NEW_TASKS.MD) 참조.

```
local-ai-assist/
├── pyproject.toml
├── CLAUDE.md
├── config/                     # 글로벌 기본 설정 (회사별 오버라이드의 폴백)
│   ├── settings.py             # AuditSettings + ContextFactory
│   ├── datasynth.yaml          # DataSynth 생성 설정
│   ├── schema.yaml             # 표준 46컬럼 스키마 (전사 공통)
│   ├── keywords.yaml           # 기본 ERP별 헤더 키워드
│   ├── audit_rules.yaml        # 기본 감사 룰
│   ├── risk_keywords.yaml      # 기본 위험 적요 키워드
│   ├── cleaning.yaml           # 타입 캐스팅 규칙 (전사 공통)
│   ├── chart_of_accounts.csv   # 범용 CoA (글로벌 폴백)
│   └── presets/                # 산업별 프리셋 (런타임 오버레이)
├── src/
│   ├── context.py              # CompanyContext + ContextFactory (RC-0)
│   ├── pipeline.py             # AuditPipeline(context=) 오케스트레이터
│   ├── company/                # 회사/Engagement CRUD (RC-0)
│   │   ├── models.py           # CompanyProfile, EngagementProfile
│   │   ├── repository.py       # YAML CRUD, 디렉토리 관리
│   │   ├── merger.py           # 3계층 deep_merge
│   │   └── migration.py        # 레거시 DB 마이그레이션
│   ├── ingest/                 # 수집·평탄화
│   ├── feature/                # 감사 파생변수 19개
│   ├── eda/                    # EDA 프로파일링
│   ├── validation/             # 계층적 검증 (L1~L3)
│   ├── preprocessing/          # ML 전처리 파이프라인 (Phase 2)
│   ├── detection/              # PHASE1 L1~L4 32개 룰 + 보조 findings
│   ├── db/                     # DuckDB (ConnectionManager)
│   ├── llm/                    # LLM 연동 (Phase 3)
│   └── export/                 # 내보내기 (Phase 3)
├── dashboard/                  # Streamlit
│   ├── app.py                  # 메인 앱 (회사 선택 → 분석 플로우)
│   ├── page_company.py         # 회사 선택/생성 화면 (RC-4)
│   ├── _state.py               # session_state 키 (company_id, engagement_id 포함)
│   ├── _kpi.py                 # KPI 6개
│   ├── tab_eda.py              # Tab 0: EDA 프로파일
│   ├── tab_summary.py          # Tab 1: Executive Summary
│   ├── tab_benford.py          # Tab 2: Benford Analysis
│   ├── tab_explorer.py         # Tab 3: Anomaly Explorer
│   ├── tab_comparison.py       # Tab 4: 연도 비교 (RC-4)
│   ├── tab_chat.py             # Tab 5: Text-to-SQL (Phase 3)
│   └── components/
│       ├── company_manager.py  # 회사 CRUD 컴포넌트 (RC-4)
│       ├── engagement_selector.py # 연도 선택 (RC-4)
│       ├── data_uploader.py    # 파일 업로드 + 파이프라인 실행
│       ├── filters.py          # 사이드바 필터 12개
│       ├── mapping_review.py   # 매핑 리뷰 3-tier UI
│       ├── preset_selector.py  # 프리셋 + 회사별 설정 통합
│       ├── threshold_sidebar.py # 임계값 튜닝 슬라이더
│       ├── rule_panel.py       # 룰 컨트롤 패널
│       ├── _redetect.py        # 재탐지 헬퍼
│       ├── explorer_*.py       # 탐색기 서브 컴포넌트 3종
│       └── charts/             # Plotly 차트 래퍼 17종
├── data/
│   ├── companies/              # 회사별 데이터 (Company-Centric)
│   │   └── {company_id}/
│   │       ├── company.yaml    # 메타 + settings_overrides
│   │       ├── chart_of_accounts.csv
│   │       ├── keywords.yaml   # ERP 별칭 오버라이드
│   │       ├── audit_rules.yaml
│   │       ├── profiles/       # 매핑 프로파일
│   │       └── engagements/{year}/
│   │           ├── engagement.yaml
│   │           ├── audit.duckdb  # Engagement별 격리 DB
│   │           └── models/       # ML 모델 아티팩트
│   └── journal/                # 전표 원본 (.gitignore)
├── tools/datasynth/            # EY-ASU DataSynth (Rust)
├── tests/
└── docs/
```

## 구현 가이드 (docs/pre-plan/)

개요서를 기능 영역별로 분리한 구현 레퍼런스. 각 파일은 목적/관련 파일/핵심 클래스/데이터 흐름/구현 순서/테스트 전략을 포함.

| #  | 파일                                                     | 내용                                                          | Phase  |
|----|----------------------------------------------------------|---------------------------------------------------------------|--------|
| 0  | [00-dataset.md](pre-plan/00-dataset.md)                  | 데이터셋 수집·선정·적합도·Phase별 활용 전략                   | 사전   |
| 1  | [01-project-setup.md](pre-plan/01-project-setup.md)      | pyproject.toml, uv, AuditSettings, YAML 설정                 | MVP    |
| 2  | [02-ingest.md](pre-plan/02-ingest.md)                    | 파일 검증, Excel 읽기, 헤더 탐지, 컬럼 매핑, 타입 캐스팅     | MVP    |
| 3  | [03-feature.md](pre-plan/03-feature.md)                  | 감사 파생변수 11개 (time/amount/pattern/text)                 | MVP    |
| 3a | [03a-preprocessing.md](pre-plan/03a-preprocessing.md)    | ML 전처리 파이프라인, VAE 래퍼, 라벨 전략                     | P2     |
| 4  | [04-validation.md](pre-plan/04-validation.md)            | L1 Pandera + L2 회계 + L3 통계 검증 + 리포트                 | MVP+P2 |
| 5  | [05-detection.md](pre-plan/05-detection.md)              | 초기 24개 룰 설계 기록. 현행 기준은 L1/L2/L3/L4 32개 룰, Benford(L4-02), L3-12 work-scope review, ML 16개, NLP 5개 | MVP~P3 |
| 6  | [06-db.md](pre-plan/06-db.md)                            | DuckDB 커넥션, 스키마, 로더, 프리셋 쿼리                     | MVP    |
| 7  | [07-dashboard.md](pre-plan/07-dashboard.md)              | Streamlit 5탭, 컴포넌트, 차트, 필터                          | MVP+P3 |
| 8  | [08-llm.md](pre-plan/08-llm.md)                          | Ollama, Vanna AI 2.0, SQL 검증, 프리셋, 인사이트             | P3     |
| 9  | [09-export.md](pre-plan/09-export.md)                    | Excel/PDF 감사조서, Audit Trail                               | P3     |
| 10 | [10-sample-data.md](pre-plan/10-sample-data.md)          | 가상 GL 데이터 생성기 — DataSynth로 대체됨                    | MVP    |
| UX | [ux-flow.md](pre-plan/ux-flow.md)                        | UX 3단계 흐름도, 감사인 심리, 3가지 디자인 원칙               | 전체   |

**구현 의존 그래프:**
```
00-dataset → 01-project-setup → 10-sample-data → 02-ingest → 03-feature → 04-validation
                                                                    ↓
                                                              05-detection → 03a-preprocessing → ML 탐지
                                                                                                    ↓
                                                                                                  06-db
                                                                                                    ↓
                                                                                              07-dashboard
                                                                                                    ↓
                                                                                         08-llm → 09-export
```

## 합성 데이터 (DataSynth)

EY-ASU DataSynth(Rust)로 생성한 K-IFRS 적용 한국 중견 제조 그룹사 시뮬레이션.

| 항목           | 값                                                    |
|----------------|-------------------------------------------------------|
| 법인           | C001 본사(서울), C002 울산공장, C003 천안공장 — 전체 KRW |
| 회계연도       | 2022-01 ~ 2024-12 (3개년)                             |
| 전표 규모      | 319,226건 / 1,109,221 라인아이템 (전표당 약 3.47행)      |
| 금액 분포      | LogNormal(14.0, 2.5) — 라인 중앙값 ~33.6만원, 평균 ~1,706만원 |
| 승인 한도      | 6단계 전결규정 (자동→담당자→팀장→본부장→CFO→이사회)    |
| 사용자 풀      | 직원 마스터 246명(기본 204 + JE actor 42), `created_by 42/42` 및 `approved_by 14/14` 직접 조인 |
| 시간 패턴      | 한국 근무 문화 반영 (심야 1.5%, 오전 피크 29.7%, 야근 13.1%) |
| 이상 주입      | fraud 1.35% (15,008행) + anomaly 0.57% (6,270행) + SoD 2.75% (30,488행) + anomaly_labels.csv 1,912건 (5개 카테고리) |
| Benford        | 첫째 자릿수 적합 (tolerance 5%, payroll/recurring 제외) |

## ML 학습 전략

비지도학습 중심 + 지도학습 파이프라인 인프라 구축.

| 접근법 | 모델 | 역할 | 합성 데이터 적합도 |
|:-------|:-----|:-----|:-----------------:|
| 비지도학습 | VAE + Isolation Forest | **핵심 탐지기** — 정상 분포 이탈 탐지 | 높음 |
| 지도학습 | XGBoost, FT-Transformer, BiLSTM | 파이프라인 인프라 — 고객사 실데이터 유입 시 활성화 | 중간 |
| 앙상블 | Stacking Meta-Learner (LR Ridge) | 6개 모델 출력 결합 | 높음 |

**배경**: DataSynth 합성 데이터의 이상치는 룰 기반으로 주입되므로, 지도학습 시 순환 학습(Circular Learning) 문제 발생.
비지도학습(VAE+IF)은 정상 분포를 학습하므로 합성 데이터에서도 유효.
지도학습 파이프라인(cv_selector, SMOTE-ENN, PR-AUC 평가)은 인프라로 구축하여,
향후 고객사별 실데이터 유입 시 fine-tuning으로 즉시 활성화 가능.

상세: [CONSTRAINTS.md §ML 학습 전략](CONSTRAINTS.md) | [TROUBLESHOOT.md §TS-3](TROUBLESHOOT.md)

## 데이터 흐름

> **Company-Centric 재설계 반영 (2026-04-02)**

```
[대시보드 진입]
  → 회사 선택/생성 → Engagement(연도) 선택 → CompanyContext 생성
  ↓ (ContextFactory: 글로벌 → 회사 → 연도 3계층 설정 해소)

[데이터 업로드]
  Excel/CSV → file_validator → reader → header_detector
  → column_mapper(←ctx.keywords) → type_caster(←cleaning.yaml)
  → 매핑 프로파일 저장 (ctx.profile_dir)
  ↑ UX 1단계: 자동 헤더/매핑 + 사용자 위임 + 판단 근거 투명 노출

[파이프라인 실행] — AuditPipeline(context=ctx).run(path)
  → 표준 DataFrame → feature/engine(←ctx.settings, ctx.audit_rules) — 파생변수 19개
  → validation (L1 구조 + L2 회계 + L3 통계)
  → detection (L1~L4 32개 룰 + 보조 findings, ←ctx.settings, ctx.chart_of_accounts)
  → score_aggregator (가중합 + risk_level + L2-05)
  → DuckDB 적재 (ctx.db_path — Engagement별 격리 DB)
  ↑ UX 2단계: 룰 컨트롤 패널 + 재탐지

[분석]
  → Streamlit 4탭 (EDA / Summary / Benford / Explorer)
  → 연도 비교 탭 (ATTACH 교차 쿼리)
  ↑ UX 3단계: EDA 프로파일링 + 전처리 투명성

[Phase 2: ML/DL — 로컬 실행]
  → preprocessing (pipeline_builder → cv_selector)
  → ML 탐지 (VAE+IF + Stacking) — 모델 저장: ctx.model_dir

[Phase 3: LLM — 상용 API (하이브리드)]
  → 로컬: 위험 스코어·통계 지표 추출
  → API: Text-to-SQL, NLP 의미 분석, 인사이트 생성, Export
  → 비식별화 레이어: 현재 범위 외, 필요성 인지 (CONSTRAINTS.md 참조)
```
> Historical note. Current DataSynth production baseline is `data/journal/primary/datasynth/` freeze `v59` as of 2026-04-27. This section originally referenced `v23` freeze (2026-04-22).
> `B04 DuplicatePayment`는 `P2P + KZ` pair/negative-control 구조로 승격되었고, `v20.4`는 백업본 `datasynth_backup_v20_4_20260422`로 보존된다.
> Historical sub-note. This section originally referenced `v23` as of 2026-04-22; current production is `v59`.
