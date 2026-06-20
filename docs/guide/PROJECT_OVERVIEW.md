# Project Overview

> **Local-first product boundary (2026-05-26)**: local-ai-assist is a local ledger analysis assistant. PHASE1 is the base review queue, PHASE2 is family-specific lane support, and PHASE3 LLM Narrator is a removed/deprecated historical asset. Active product paths do not call external LLM/API services. 단일 출처: [LOCAL_FIRST_EVIDENCE_POLICY.md](../spec/LOCAL_FIRST_EVIDENCE_POLICY.md), [DECISION.md §D068](../spec/DECISION.md), deprecated spec [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md).

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> PHASE1 operating role: PHASE1 is a rule-based full-population screening layer, not a final fraud classifier. Its first job is to surface all records, groups, and macro signals that violate configured rules or deserve review. The second step classifies those hits into normal exceptions, auditor review queues, and high-risk candidates using materiality, evidence strength, case priority, company exception policy, and rule combinations.

> Current DataSynth baseline: `data/journal/primary/datasynth/` freeze `v126` as of 2026-05-02. Dataset size is `1,109,435` rows / `319,193` documents / `52` columns. Main label sidecar: `labels/anomaly_labels.csv` `3,149` rows.

> PHASE1 scoring baseline: rule results are normalized through `src/detection/rule_scoring.py` before case aggregation. Dashboard/report priority is case-level `priority_score`, not a direct sum of raw rule labels or row-level `anomaly_score`. Case priority uses control, amount, logic, timing, and behavior axes; timing keeps closing/cutoff signals such as L3-11 visible in the review queue.

> Current PHASE1-1 rule scope: 31 L1~L4 canonical transaction rules. `L4-02`/`Benford`, `D01/D02`, `IC01~IC03`, `GR01/GR03` are PHASE1-2 macro/family findings outside the canonical count (이관 2026-06-15). `L3-12` is an `access_scope_review` review signal under `L1-06`. 단일 출처: [RULE_DETAIL_METADATA_V1_LOCK.md](../spec/RULE_DETAIL_METADATA_V1_LOCK.md), [PHASE1_TIER_EVIDENCE_BASIS.md](../spec/PHASE1_TIER_EVIDENCE_BASIS.md).


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

## 프로젝트 정의

Local AI Audit Assistant v2.0 — 감사 실증절차 전표 테스트 자동화 도구.
MindBridge, KPMG Clara의 핵심 로직을 오픈소스(Python)로 재현하는 포트폴리오.

## 기술 스택

| 영역        | 기술                               | 비고                                        |
|-------------|------------------------------------|---------------------------------------------|
| 언어        | Python 3.11+                       |                                             |
| 패키지      | uv + pyproject.toml                | dependency-groups로 core/ml/dashboard 분리; llm group은 legacy/historical |
| 전처리      | openpyxl, pandas 2.x, pandera      | pandera: 스키마 기반 품질 게이트            |
| 컬럼 매핑   | rapidfuzz                          | fuzzy string matching                       |
| 설정        | pydantic-settings, pyyaml          | 환경변수 + YAML                             |
| 통계        | scipy.stats, numpy                 | Benford, KS 검정, Runs test                 |
| 지도학습    | xgboost, lightgbm, scikit-learn, shap | 파이프라인 인프라 (고객사 실데이터 fine-tuning용, Phase 2 dormant) |
| 비지도학습  | pytorch (VAE), scikit-learn (IF)   | **핵심 탐지기** — Phase 2 MVP 단일 promoted model |
| 한국어 NLP  | kiwipiepy                          | JVM 의존성 없음. future local-only NLP 후보 |
| DB          | duckdb                             | OLAP 최적화, Engagement별 격리              |
| LLM         | OpenAI/API integrations (historical) | Active product path에서 제거 |
| 벡터 DB     | ChromaDB (historical v1)           | Active product path에서 제거               |
| Text-to-SQL | (historical v1, Vanna)             | Active product path에서 제거               |
| 대시보드    | streamlit, plotly, streamlit-aggrid |                                             |
| PDF/Export  | local export/report modules         | 로컬 렌더링만 허용                          |

## 디렉토리 구조

> **아키텍처**: Company-Centric — `data/companies/{id}/engagements/{year}/audit.duckdb` 격리.

```
local-ai-assist/
├── pyproject.toml
├── CLAUDE.md
├── config/                     # 글로벌 기본 설정 (회사별 오버라이드의 폴백)
│   ├── settings.py             # AuditSettings + ContextFactory
│   ├── datasynth.yaml          # DataSynth 생성 설정
│   ├── schema.yaml             # 표준 스키마 (전사 공통)
│   ├── keywords.yaml           # 기본 ERP별 헤더 키워드
│   ├── audit_rules.yaml        # 기본 감사 룰
│   ├── risk_keywords.yaml      # 기본 위험 적요 키워드
│   ├── cleaning.yaml           # 타입 캐스팅 규칙 (전사 공통)
│   ├── chart_of_accounts.csv   # 범용 CoA (글로벌 폴백)
│   ├── coa_categories.yaml     # 계정군 정의 (YAML, 코드 상수 금지)
│   ├── phase1_case.yaml        # PHASE1 case priority/floor 정책
│   └── presets/                # 산업별 프리셋 (런타임 오버레이)
├── src/
│   ├── context.py              # CompanyContext + ContextFactory (RC-0)
│   ├── pipeline.py             # AuditPipeline(context=) 오케스트레이터
│   ├── company/                # 회사/Engagement CRUD
│   │   ├── models.py           # CompanyProfile, EngagementProfile
│   │   ├── repository.py       # YAML CRUD, 디렉토리 관리
│   │   ├── merger.py           # 3계층 deep_merge
│   │   └── migration.py        # 레거시 DB 마이그레이션
│   ├── ingest/                 # 수집·평탄화·헤더 탐지·컬럼 매핑
│   ├── feature/                # 감사 파생변수 19개
│   ├── eda/                    # EDA 프로파일링
│   ├── validation/             # 계층적 검증 (L1 Pandera / L2 회계 / L3 통계)
│   ├── preprocessing/          # ML 전처리 파이프라인 (Phase 2)
│   ├── detection/              # PHASE1 L1~L4 31개 룰 + macro/보조 findings
│   │   ├── rule_scoring.py     # 룰 normalized score (PHASE1 운영 단일 출처)
│   │   ├── topic_scoring.py    # 6개 topic queue (intercompany_cycle → PHASE1-2 family 이관)
│   │   ├── score_aggregator.py # row anomaly_score 가중합
│   │   ├── phase1_case_builder.py
│   │   └── ...                 # L1~L4, evidence, benford, variance, IC, graph
│   ├── models/                 # phase1_case 등 Pydantic 모델
│   ├── services/               # phase2 inference/training service
│   ├── db/                     # DuckDB (ConnectionManager)
│   ├── llm/                    # historical/disabled LLM assets
│   └── export/                 # local export/report helpers
├── dashboard/                  # Streamlit
│   ├── app.py                  # 메인 앱 (회사 선택 → 분석 플로우)
│   ├── page_company.py         # 회사 선택/생성 화면
│   ├── _state.py / _kpi.py
│   ├── tab_overview.py / tab_phase1.py / tab_phase2.py
│   ├── tab_review_queue.py     # PHASE1/PHASE2 local review queue
│   ├── tab_explorer.py / tab_comparison.py
│   └── components/             # data_uploader, filters, mapping_review,
│                               # rule_panel, scroll_anchor, charts/, ...
├── data/
│   ├── companies/              # 회사별 데이터 (Company-Centric)
│   │   └── {company_id}/
│   │       ├── company.yaml    # 메타 + settings_overrides
│   │       ├── chart_of_accounts.csv
│   │       ├── keywords.yaml
│   │       ├── audit_rules.yaml
│   │       ├── profiles/       # 매핑 프로파일
│   │       └── engagements/{year}/
│   │           ├── engagement.yaml
│   │           ├── audit.duckdb  # Engagement별 격리 DB
│   │           └── models/       # ML 모델 아티팩트
│   └── journal/                # 전표 원본 (.gitignore)
├── tools/datasynth/            # EY-ASU DataSynth (Rust, .gitignore)
├── tools/scripts/              # 진단/베이스라인/감사 스크립트
├── tests/
├── dev/active/                 # 진행 중 plan/context/tasks
└── docs/
```

## 활성 문서 인덱스

| 영역 | 문서 |
|------|------|
| 프로젝트 정의 | 본 문서, [상세.MD](상세.MD), [핵심기능.MD](핵심기능.MD), [EXPLAIN.md](EXPLAIN.md), [ux-flow.md](ux-flow.md) |
| 설계 결정/제약 | [DECISION.md](../spec/DECISION.md), [CONSTRAINTS.md](../spec/CONSTRAINTS.md), [TROUBLESHOOT.md](../spec/TROUBLESHOOT.md), [debugging.md](../debugging.md) |
| Detection 운영 | [DETECTION_RULES.md](../spec/DETECTION_RULES.md) (PHASE1-1), [DETECTION_RULES_PHASE1-2.MD](../spec/DETECTION_RULES_PHASE1-2.MD) (PHASE1-2 family·macro), [DETECTION_RULES_PHASE2_ML.md](../spec/DETECTION_RULES_PHASE2_ML.md) (Phase2 ML), [UNIT_MEASUREMENT_POLICY.md](../spec/UNIT_MEASUREMENT_POLICY.md), [DETECTION_REFERENCE.md](../spec/DETECTION_REFERENCE.md), [DETECTION_PARAMETERS.md](../spec/DETECTION_PARAMETERS.md), [DETECTION_PORTFOLIO_REFRAME.md](../spec/DETECTION_PORTFOLIO_REFRAME.md), [DETECTION_RANKING_CRITERIA.md](../spec/DETECTION_RANKING_CRITERIA.md) |
| Detection 사용자 해설 | [룰원칙해설.md](룰원칙해설.md) — 룰별 "왜 신호인가·숨은 가정" 전수 해설 |
| PHASE1 활성 락 | [PHASE1_TIER_EVIDENCE_BASIS.md](../spec/PHASE1_TIER_EVIDENCE_BASIS.md), [PHASE1_TIER_SCORING_SPEC.md](../spec/PHASE1_TIER_SCORING_SPEC.md), [HIGH_COMBO_GROUNDING.md](../spec/HIGH_COMBO_GROUNDING.md), [RULE_DETAIL_METADATA_V1_LOCK.md](../spec/RULE_DETAIL_METADATA_V1_LOCK.md), [PHASE1_RULE_RELATIONSHIP_MAP.md](../spec/PHASE1_RULE_RELATIONSHIP_MAP.md), [PHASE1_SEPARATE_BENCHMARK_SPEC.md](../spec/PHASE1_SEPARATE_BENCHMARK_SPEC.md) |
| PHASE2 진행 | [PHASE2_GOVERNANCE_DESIGN.md](../spec/PHASE2_GOVERNANCE_DESIGN.md), [PHASE2_INTERFACE_DESIGN.md](../spec/PHASE2_INTERFACE_DESIGN.md), [PHASE2_FITTING_AUDIT.md](../spec/PHASE2_FITTING_AUDIT.md) |
| Local-first / deprecated PHASE3 | [LOCAL_FIRST_EVIDENCE_POLICY.md](../spec/LOCAL_FIRST_EVIDENCE_POLICY.md), [PHASE3_REVIEW_NARRATOR_SPEC.md](../archive/abandoned/PHASE3_REVIEW_NARRATOR_SPEC.md) |
| 최신 검증 결과 | [DETECTION_RESULTS_CONTRACT_V3.md](DETECTION_RESULTS_CONTRACT_V3.md), [DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md](DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md) |
| 지표 정의 | [metrics.md](../spec/metrics.md) |
| Git 운영 | [GIT.md](../spec/GIT.md) |
| 사용자 시나리오 | [users/00_INDEX.md](users/00_INDEX.md) ~ `10_PORTFOLIO_POSITIONING.md` |
| 템플릿 | [templates/phase2_evaluation_report_template.md](../spec/templates/phase2_evaluation_report_template.md) |
| 완료 산출물 (구현 가이드 포함) | [archive/completed/](../archive/completed/) — `raw-plan/` (구 pre-plan 13개), S 시리즈, DataSynth contract v126 sidecar, 구버전 DETECTION_RESULTS 등 |

## 합성 데이터 (DataSynth)

EY-ASU DataSynth(Rust)로 생성한 K-IFRS 적용 한국 중견 제조 그룹사 시뮬레이션. 현재 baseline freeze `v126` (2026-05-02).

| 항목           | 값                                                    |
|----------------|-------------------------------------------------------|
| 법인           | C001 본사(서울), C002 울산공장, C003 천안공장 — 전체 KRW |
| 회계연도       | 2022-01 ~ 2024-12 (3개년)                             |
| 전표 규모      | `319,193` 문서 / `1,109,435` 라인아이템 (52 컬럼) |
| 금액 분포      | LogNormal(14.0, 2.5) — 라인 중앙값 ~33.6만원, 평균 ~1,706만원 |
| 승인 한도      | 6단계 전결규정 (자동→담당자→팀장→본부장→CFO→이사회)    |
| 사용자 풀      | 직원 마스터 246명 (기본 204 + JE actor 42), `created_by 42/42` 및 `approved_by 14/14` 직접 조인 |
| 시간 패턴      | 한국 근무 문화 반영 (심야 1.5%, 오전 피크 29.7%, 야근 13.1%) |
| 이상 주입      | sidecar `labels/anomaly_labels.csv` `3,149` 건 (manipulation v4~v7 시리즈로 fitting 위험 제거 후 확장 중) |
| Benford        | 첫째 자릿수 적합 (tolerance 5%, payroll/recurring 제외) |
| 외부 검증      | OpenDataPhilly / Tritscher portability·shadow 검증 (보조) |

상세: [datasynth.md](../archive/completed/datasynth.md), [DATASYNTH_INJECTION_SPEC.md](../archive/completed/DATASYNTH_INJECTION_SPEC.md), DataSynth contract sidecar/taxonomy v126 (`docs/archive/completed/datasynth_contract_*_v126.*`).

## ML 학습 전략

비지도학습 중심 + 지도학습 dormant + local evidence summaries.

| 접근법 | 모델 | 역할 | 합성 데이터 적합도 |
|:-------|:-----|:-----|:-----------------:|
| 비지도학습 | VAE (1개 promoted) + Isolation Forest | **Phase 2 MVP 핵심 탐지기** — 정상 분포 이탈 evidence | 높음 |
| 지도학습 | XGBoost, LightGBM, FT-Transformer, BiLSTM | Dormant. 라벨 누수 가드(Supervised Gate) 통과 후만 활성화 | 낮음 (생성기 shortcut 위험) |
| 앙상블 | Stacking Meta-Learner (LR Ridge, OOF) | Experimental — 지도학습 활성화 시 결합 | 중간 |
| Local Evidence Brief | deterministic template | PHASE1/PHASE2 로컬 근거 요약 | 외부 API 없음 |

**배경**: DataSynth 합성 데이터의 이상치는 룰 기반으로 주입되므로, 지도학습 시 순환 학습(Circular Learning) 문제 발생.
비지도학습(VAE+IF)은 정상 분포를 학습하므로 합성 데이터에서도 유효.
지도학습 파이프라인(cv_selector, SMOTE-ENN, PR-AUC 평가, threshold 동적 최적화)은 인프라로만 구축, 고객사별 실데이터 유입·HITL 라벨 축적 이후 fine-tuning으로 활성화.

상세: [CONSTRAINTS.md](../spec/CONSTRAINTS.md), [TROUBLESHOOT.md §TS-3](../spec/TROUBLESHOOT.md), [PHASE2_FITTING_AUDIT.md](../spec/PHASE2_FITTING_AUDIT.md).

## 데이터 흐름

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
  → validation (L1 Pandera + L2 회계 + L3 통계)
  → detection (PHASE1-1 룰 = L1~L4 전표 단위 + PHASE1-2 family = graph/relational/시계열 구조 단위 + 보조 findings)
  → rule_scoring (normalized_score + scoring_role + evidence_strength)
  → topic_scoring (6개 topic queue — intercompany_cycle는 PHASE1-2 family로 이관)
  → phase1_case_builder (case 명명 tier = HIGH/MEDIUM/LOW/CONTEXT, 순서형)
  → score_aggregator (row anomaly_score 가중합 L1=0.40 / L2=0.25 / L3=0.20 / L4=0.15)
  → DuckDB 적재 (ctx.db_path — Engagement별 격리 DB)
  ↑ UX 2단계: 룰 컨트롤 패널 + 재탐지

[분석]
  → Streamlit (overview / phase1 / phase2 / review_queue / explorer / comparison)
  ↑ UX 3단계: review queue 우선순위 + 의심 근거 + 다음 행동

[Phase 2: ML/DL — 로컬 실행]
  → preprocessing (pipeline_builder → cv_selector, document_id GroupKFold)
  → 비지도 학습: VAE (train split에서만 fit, ECDF 분포 저장)
  → unsupervised_selection_score (score_tail_gap / topk_stability / capacity / degeneracy)
  → 모델 저장: ctx.model_dir/phase2_unsupervised/v1/
  → Layer A KPI guard (audit-testing nightly CI)

[Local Evidence Brief]
  → PHASE1 rule evidence + PHASE2 family lane signal + case metadata
  → deterministic local template summary
  → dashboard selected-case/detail panels and local export views
  ↑ 외부 LLM/API 호출 없음. 요약은 fraud 확정이나 새 패턴 발견을 하지 않는다.
```

## CI 워크플로우

| 워크플로우 | 트리거 | 역할 |
|-----------|--------|------|
| `phase1-kpi-guard` | PR (main/develop), main push, weekly schedule, manual | PHASE1 Layer A/B hard guard + Layer C soft warn |
| `audit-testing` | manual + nightly `0 18 * * *` UTC (KST 03:00) | PHASE2 Stage 5 baseline `training_report.json` Layer A + case contract 회귀 차단 |

상세: [GIT.md](../spec/GIT.md).
