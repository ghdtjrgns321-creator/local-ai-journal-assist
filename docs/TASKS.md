# Phase별 태스크

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.

> 각 태스크의 상세 구현 가이드는 `docs/pre-plan/` 참조
> pre-plan 번호(00~10)는 **도메인 분류**이며, 구현 순서는 **Phase 번호**를 따른다.
> 예: `05a-detection-ml.md`는 Phase 2b의 설계 레퍼런스이지, 05 다음에 바로 구현하는 것이 아님.

## 진행 현황 요약

| Phase                           | 완료 | 전체 | 진행률 |
|---------------------------------|------|------|--------|
| 1a 데이터 파이프라인             | 20   | 20   | 100%   |
| 1b 이상탐지+DB+Variance           | 21   | 21   | 100%   |
| 1c 대시보드                      | 12   | 12   | 100%   |
| RC 재설계 (Company-Centric)      | 41   | 41   | 100%   |
| 2a ML 전처리                     | 10   | 10   | 100%   |
| 2 WU-00 전처리 수정              |  5   |  5   | 100%   |
| 2 WU-01~04 ML 핵심               |  2   |  6   |  33%   |
| 2 WU-05~08 추가탐지              |  0   |  4   |   0%   |
| 2 WU-09~13 고도화                |  1   |  5   |  20%   |
| 2 WU-14~16 DataSynth             |  1   |  3   |  33%   |
| 2 WU-17 대시보드ML               |  1   |  1   | 100%   |
| 3 WU-18~19 API+NLP기초           |  1   |  2   |  50%   |
| 3 WU-20 Text-to-SQL              |  0   |  1   |   0%   |
| 3 WU-21~22 NLP탐지+그래프        |  2   |  2   | 100%   |
| 3 WU-23~24 Audit+감사조서        |  1   |  2   |  50%   |
| 3 WU-25~27 인사이트+UI           |  2   |  3   |  67%   |
| 3 WU-28~30 고도화                |  2   |  3   |  67%   |
| **합계**                         | 119  | 150  |  79%   |

**상태 범례**: ✅ 완료 / ⬜ 미착수
**블로커**: Phase 섹션 상단 blockquote로 표기 (🚫 BLOCKER)
**번호 미부여**: DataSynth 확장 (8건) = Phase 간 보조 작업으로 요약표 집계에서 제외

---

## Phase 1: MVP (Python Only 파이프라인 + 기본 UI) ✅

### Phase 1a: 데이터 파이프라인

| #   | 태스크              | 파일                                                            | 가이드                                             | 상태 |
|-----|---------------------|-----------------------------------------------------------------|---------------------------------------------------|------|
| 0   | 데이터셋 수집·선정  | `data/journal/`, 32개 검토                                      | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 0a  | DataSynth 빌드      | `tools/datasynth/` (Rust, EY-ASU)                               | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 0b  | 메인 데이터 생성    | `data/journal/primary/datasynth/` (1,109K건, v20.4 운영 기준본) | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 1   | 프로젝트 초기화     | `pyproject.toml`, `.gitignore`, `.env.example`                  | [01-project-setup](pre-plan/01-project-setup.md)  | ✅   |
| 2   | 설정 레이어         | `config/settings.py`, YAML 3종 + `datasynth.yaml`              | [01-project-setup](pre-plan/01-project-setup.md)  | ✅   |
| 3   | 샘플 데이터 생성기  | DataSynth로 대체 (10-sample-data 불필요)                        | -                                                 | ✅   |
| 4   | 수동 Excel 템플릿   | DataSynth CSV로 대체                                            | -                                                 | ✅   |
| 5   | 파일 검증           | `src/ingest/file_validator.py`                                  | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 6   | Excel 읽기          | `src/ingest/excel_reader.py`                                    | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 7   | 헤더 탐지           | `src/ingest/header_detector.py`                                 | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 8   | 컬럼 매핑           | `src/ingest/column_mapper.py`                                   | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 9   | 타입 캐스팅         | `src/ingest/type_caster.py` + `config/cleaning.yaml`            | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 10  | 매핑 프로파일       | `src/ingest/mapping_profile.py`                                 | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 10a | **UX 1단계**        | 구조적 헤더탐지 + 타입검증 + ReviewItem + Null분기 + latin-1 폴백 | [02-ingest](pre-plan/02-ingest.md)               | ✅   |
| 10b | **피드백 반영**     | 인코딩 오버라이드+confidence, 시트 스코어링, 금액 퀵픽스, Phase 1c UI 스펙 | [02-ingest](pre-plan/02-ingest.md)      | ✅   |
| 11  | 피처 엔진           | `src/feature/engine.py` + 4개 서브모듈 (170 tests passed)       | [03-feature](pre-plan/03-feature.md)              | ✅   |
| 11a | **UX 3단계 — EDA**  | `src/eda/` 7개 모듈 (52 tests passed)                           | [03a-preprocessing](pre-plan/03a-preprocessing.md)| ✅   |
| 12  | L1~L2 검증          | `src/validation/schema_validator.py`, `accounting_validator.py`  | [04-validation](pre-plan/04-validation.md)        | ✅   |
| 13  | 전처리 리포트       | `src/validation/report_generator.py` (17 tests passed)          | [04-validation](pre-plan/04-validation.md)        | ✅   |
| 14  | 단위 테스트 (1a)    | `tests/test_ingest/`, `test_feature/`                           | 각 가이드 "테스트 전략" 섹션                       | ✅   |

**완료 기준**: DataSynth CSV → ingest → feature → validation 파이프라인 통과 ✅

### Phase 1b: 이상탐지 + DB

> **pre-plan 참조**: Phase 1b 잔여 작업 시 확인
> - `05-detection.md` §58 (파이프라인 오케스트레이터 `run_detection_pipeline()`)
> - `06-db.md` §1123 (`src/pipeline.py` 미구현 — E2E 조립)

| #   | 태스크                           | 파일                                                                 | 가이드                                     | 상태 |
|-----|----------------------------------|----------------------------------------------------------------------|--------------------------------------------|------|
| 15  | BaseDetector                     | `src/detection/base.py`                                              | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 16  | L1 무결성                   | `src/detection/integrity_layer.py` (L1-01~L1-03)                         | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 17  | L2 부정탐지                 | `src/detection/fraud_layer.py` (L4-01~L2-04, 42 tests)                   | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 18  | L3/L4 이상징후                 | `src/detection/anomaly_layer.py` (L3-04~L3-09, 41 tests)                 | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19  | 점수 집계                        | `src/detection/score_aggregator.py` (L1/L2/L3/L4+Benford+Top-side score, 21 tests)  | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19a | 역분개 패턴 탐지 (1:1 + N:M)    | `src/detection/anomaly_rules_reversal.py` + `anomaly_layer.py`       | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19b | Top-side JE 조합 점수              | `src/detection/score_aggregator.py` (확장, 9 tests)                  | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19c | 비정상 시간대 입력자 집중 (L4-05)   | `src/detection/anomaly_rules_simple.py` + `src/feature/time_features.py` (46 tests) | [03-feature](pre-plan/03-feature.md), [05-detection](pre-plan/05-detection.md) | ✅   |
| 19d | IC identifiers 불일치 수정       | `src/feature/pattern_features.py` — `["1150C","2050C"]` → `["1150","2050","4500","2700"]` | [03-feature](pre-plan/03-feature.md) §210 | ✅   |
| 19e | manual_source_codes 오매칭 수정  | `src/feature/pattern_features.py` — SA는 document_type, source 아님   | [03-feature](pre-plan/03-feature.md) §211 | ✅   |
| 19f | suspense_keywords 언어 불일치    | `src/feature/text_features.py` — DataSynth 영문 vs 현재 한국어 키워드 | [03-feature](pre-plan/03-feature.md) §212 | ✅   |
| 19g | L1-05 자기승인 정밀화             | automated 제외 + 소액(10M) 제외. 111K→1.5K (98.6% 감소)              | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 20  | DuckDB core                      | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py`       | [06-db](pre-plan/06-db.md)                | ✅   |
| 20a | DuckDB ML 확장 스키마 (Phase 2 대비 예약 선언만) | `src/db/schema.py` — 7컬럼 nullable 예약 + ml_model_metadata(PK, JSON) | [06-db](pre-plan/06-db.md) | ✅ |
| 20b | loader.py approval_level 파생    | `src/db/loader.py` — debit SUM + settings 동적 참조 + N level 캡     | [06-db](pre-plan/06-db.md)                | ✅   |
| 21  | 파이프라인 오케스트레이터        | `src/pipeline.py` — AuditPipeline(ingest→validate→feature→detection→db) | 05-detection + 06-db 통합              | ✅   |
| 22  | detection 단위테스트             | `tests/test_detection/` (120+ tests)                                 | 각 가이드 "테스트 전략" 섹션               | ✅   |
| 22a | DB 단위테스트                    | `tests/test_db/`                                                     | [06-db](pre-plan/06-db.md)                | ✅   |
| 22b | 파이프라인 E2E 통합테스트        | `tests/test_pipeline/` — 13개 pytest + DataSynth 1M행 E2E            | 05-detection + 06-db 통합                  | ✅   |
| 22c | Variance 인프라 (Batch 1)         | `constants.py`, `settings.py`, `prior_data_loader.py`                | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |
| 22d | Variance 룰+오케스트레이터 (Batch 2) | `variance_rules.py`, `variance_layer.py`, `__init__.py`           | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |
| 22e | Variance 파이프라인 통합 (Batch 3) | `pipeline.py`, `context.py`, dashboard 호출부, 통합 테스트 8개       | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |

**완료 기준**: `AuditPipeline.run("datasynth.csv")` → 24개 룰 L1/L2/L3/L4 + Variance(기존회사) 탐지 → DuckDB 적재 → 프리셋 쿼리 정상 ✅

### Phase 1c: 대시보드

> **pre-plan 참조**: Phase 1c 착수 시 아래 문서의 "미해결 이슈" 섹션 반드시 확인
> - `02-ingest.md` §882-896 (ingest 미해결 7건 → dashboard UI로 해결)
> - `07-dashboard.md` §580-599 (dashboard 미해결 15건)
> - `ux-flow.md` UX Stage 2~3 (룰 패널 + EDA 시각화)
> - `02-ingest.md` §36, §41 (인제스트 오케스트레이터 + IngestResult 인터페이스)
> - `02-ingest.md` §271 (3-tier 매핑 확인 UI: auto/review/blocked)

**실행 순서 및 의존 관계:**

```
WU1 (기반 컴포넌트) ──── 반드시 최초 실행
 │
 ├── WU2 (Summary)  ──┐
 ├── WU3 (Benford)  ──┼── 4개 병렬 가능 (독립)
 ├── WU4 (Explorer) ──┤
 └── WU5 (설정)     ──┘
                       │
                       ▼
               WU6 (EDA + app.py 통합) ── WU1~5 전부 완료 후
                       │
                       ▼
               WU7 (인제스트 + 미해결) ── 기본 동작 확인 후 고급 기능
```

#### WU1: 기반 컴포넌트 (Foundation) — 1단계

> session_state 키 네이밍, 필터 dict 구조를 한 대화에서 통일

| #   | 태스크             | 파일                                    | 가이드                                   | 상태 |
|-----|--------------------|-----------------------------------------|------------------------------------------|------|
| 23a | 패키지 초기화      | `dashboard/__init__.py`, `dashboard/_state.py`, `dashboard/components/__init__.py`, `dashboard/components/charts/__init__.py` | —                              | ✅   |
| 23b | 파일 업로드 위젯   | `dashboard/components/data_uploader.py` | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |
| 23c | Plotly 차트 래퍼   | `dashboard/components/charts/` — 11종 6모듈 (DataFrame → go.Figure) | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |
| 23d | 사이드바 필터      | `dashboard/components/filters.py` — 기본4 + 차원6 + 개발2 | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |

#### WU2: Tab 1 — Summary — 2단계 (WU1 완료 후, WU3~5와 병렬 가능)

| #   | 태스크             | 파일                         | 가이드                                   | 상태 |
|-----|--------------------|-----------------------------|------------------------------------------|------|
| 24  | Tab 1: Summary     | `dashboard/tab_summary.py` + `_kpi.py` + `charts/rule_charts.py` — KPI 6개 + 차트 7종 + 3-Row 레이아웃 | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |

#### WU3: Tab 2 — Benford — 2단계 (WU1 완료 후, WU2/4/5와 병렬 가능)

| #   | 태스크             | 파일                         | 가이드                                   | 상태 |
|-----|--------------------|-----------------------------|------------------------------------------|------|
| 25  | Tab 2: Benford     | `dashboard/tab_benford.py` — Benford 오버레이 + MAD/KS + 분리 분석 | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |

#### WU4: Tab 3 — Explorer + HITL — 2단계 (WU1 완료 후, WU2/3/5와 병렬 가능)

> AgGrid 체크박스 → whitelist INSERT → 재탐지 ANTI JOIN 흐름을 한 대화에서 end-to-end 구현

| #   | 태스크                     | 파일                                         | 가이드                              | 상태 |
|-----|----------------------------|----------------------------------------------|-------------------------------------|------|
| 26  | Tab 3: Explorer            | `dashboard/tab_explorer.py` — AgGrid 27컬럼 + 조건부 서식 + 행 상세 패널 | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |
| 30  | HITL 예외 처리 (whitelist) | `src/db/schema.py` (DDL 추가) + `tab_explorer.py` (HITL UI) | [ux-flow §4B](pre-plan/ux-flow.md) | ✅   |

#### WU5: 설정 컴포넌트 — 2단계 (WU1 완료 후, WU2/3/4와 병렬 가능)

> 3개 모두 AuditSettings를 조작하며 session_state 갱신 순서 설계 필수

| #   | 태스크                 | 파일                                            | 가이드                              | 상태 |
|-----|------------------------|-------------------------------------------------|-------------------------------------|------|
| 28  | 임계값 튜닝 슬라이더   | `dashboard/components/threshold_sidebar.py` — AuditSettings 23필드 슬라이더 | [ux-flow §4A](pre-plan/ux-flow.md) | ✅   |
| 29  | 프리셋 드롭다운        | `dashboard/components/preset_selector.py` + `config/presets/*.yaml` | [ux-flow §4C](pre-plan/ux-flow.md) | ✅   |
| 30b | 룰 컨트롤 패널 UI     | `dashboard/components/rule_panel.py` — 감사규칙 가중치/임계값 조정 | [ux-flow](pre-plan/ux-flow.md) UX Stage 2 §④ | ✅ |

#### WU6: EDA 탭 + 메인 앱 통합 — 3단계 (WU1~5 전부 완료 후)

> app.py가 모든 탭/컴포넌트를 import하므로 통합 단계

| #   | 태스크             | 파일                         | 가이드                                   | 상태 |
|-----|--------------------|-----------------------------|------------------------------------------|------|
| 30a | EDA 시각화 탭      | `dashboard/tab_eda.py` — `src/eda/` EDAProfile 시각화 | [03a-preprocessing](pre-plan/03a-preprocessing.md), [ux-flow](pre-plan/ux-flow.md) UX Stage 3 | ✅ |
| 27  | 메인 앱            | `dashboard/app.py` — 4탭 통합 + session_state 관리 + 개발 모드 토글 | [07-dashboard](pre-plan/07-dashboard.md) | ✅   |

#### WU7: 인제스트 오케스트레이터 + 미해결 이슈 — 4단계 (WU6 완료 후)

> 기본 동작 확인 후 고급 기능 추가 (수정 위주)

| #   | 태스크                  | 파일                                         | 가이드                              | 상태 |
|-----|-------------------------|----------------------------------------------|-------------------------------------|------|
| 30c | 인제스트 오케스트레이터 | `src/pipeline.py` (수정) — full ingest pipeline (_ingest: read_file → detect_headers → score_sheets → auto_map_columns → cast_dataframe) + file_validator 5단계 검증 + Parquet 헤더 탐지 스킵 | [02-ingest](pre-plan/02-ingest.md) §36 | ✅ |
| 30d | 미해결 이슈 UI 반영     | `data_uploader.py` 3단계 스테이지 머신(UPLOAD→REVIEW→PIPELINE) 재작성 + `mapping_review.py` 신규 — UI-1~4 구현 + 필수/권장 미매핑 사유 안내 | [07-dashboard](pre-plan/07-dashboard.md) §580-599 | ✅ |

**완료 기준**: `streamlit run dashboard/app.py` → 4탭 정상 렌더링 + 슬라이더 변경 시 탐지 결과 갱신 + 프리셋 전환 + 예외 처리 저장/제외 ✅

---

## RC: Company-Centric 아키텍처 재설계 ✅

> **전체 완료** (41/41 태스크). 상세: [NEW_TASKS.MD](NEW_TASKS.MD)
>
> 글로벌 싱글톤 설정 → 회사별 독립 파이프라인(CompanyContext + ContextFactory)으로 전면 전환.
> Phase 2 ML 탐지기는 CompanyContext 기반으로 구현한다.

| Phase                              | 태스크 | 완료 | 상태 |
|------------------------------------|--------|------|------|
| RC-0 Company 인프라                | 7      | 7    | ✅   |
| RC-1 파이프라인 Context 주입       | 7      | 7    | ✅   |
| RC-2 싱글톤 직접 호출 제거         | 8      | 8    | ✅   |
| RC-3 DB 격리 + ConnectionManager   | 6      | 6    | ✅   |
| RC-4 대시보드 재설계               | 8      | 8    | ✅   |
| RC-5 매핑 프로파일 + 고급 기능     | 5      | 5    | ✅   |

**핵심 변경점**:
- `CompanyContext` 불변 객체 + `ContextFactory.create(company_id, engagement_id)`
- Engagement별 독립 DuckDB (`data/companies/{id}/engagements/{year}/audit.duckdb`)
- `ConnectionManager` 경로별 커넥션 관리 (스레드 안전)
- 대시보드: 회사 선택 → Engagement 선택 → 업로드/분석 플로우 + 연도 비교 탭
- 매핑 프로파일 회사별 격리 + 키워드 자동 학습

---

### Phase 2 준비: DataSynth 확장 (한국 실무 맞춤 컬럼 추가)

> 현재 active DataSynth 후보는 `data/journal/primary/datasynth_contract_v2`와 `data/journal/primary/datasynth_manipulation_v2`이다. legacy 비교용 데이터셋은 `data/journal/archive/primary_legacy_20260514/`로 이동했다. 아래는 Phase 2 탐지 룰의 **선행 의존**이다.

| 태스크                             | 파일                                                              | 가이드                                                               | 상태 |
|------------------------------------|-------------------------------------------------------------------|----------------------------------------------------------------------|------|
| approval.rs 한국식 전결규정 적용   | `tools/datasynth/crates/*/approval.rs, je_generator.rs, user.rs`  | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| 증빙/컷오프/변경이력 컬럼 추가     | `tools/datasynth/crates/*/journal_entry.rs`                       | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| 전표번호 순차 생성                 | `tools/datasynth/crates/*/enhanced_orchestrator.rs` Phase 9a      | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| IP 주소 생성                       | `tools/datasynth/crates/*/je_generator.rs`                        | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| datasynth.yaml approval 섹션      | `config/datasynth.yaml`                                           | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| SuspenseAccountAbuse keyword 주입 | GL 코드 탐지 정상 작동. 적요 의미 분석은 키워드 한계로 Phase 3 이관 (#71, #84, #88) | [03-feature](pre-plan/03-feature.md) §212, [DETECTION_RULES](DETECTION_RULES.md) §L3-09 | N/A  |
| Round number clamping 검증        | `tools/datasynth/` — 라운드 넘버 클램핑 로직 확인                  | [03-feature](pre-plan/03-feature.md) §154                            | ✅   |
| 다기간 시계열 데이터 생성 (2~3개년)  | `tools/datasynth/` — 복수 회계연도 생성                          | TrendBreak (#54) 선행 의존                                        | ✅   |
| 데이터 재생성 + 파이프라인 호환 확인 | `data/journal/primary/datasynth/`                                | 신규 컬럼 포함 데이터로 기존 파이프라인 호환 확인                     | ✅   |

---

## Phase 2: Core AI (ML 모델 + 추가 탐지 유형)

> **ML 전략: 비지도학습 중심** (TS-3, 2026-04-01 결정)
> DataSynth 합성 데이터의 지도학습 순환 문제(룰로 주입한 이상치를 ML이 재학습)로 인해,
> **비지도학습(VAE+IF)을 핵심 탐지기**로, **지도학습(XGBoost 등)은 파이프라인 인프라 구축**으로 위치 설정.
> 지도학습 파이프라인은 향후 고객사별 실데이터 유입 시 fine-tuning으로 활성화.
> 상세: [CONSTRAINTS.md §ML 학습 전략](CONSTRAINTS.md) | [TROUBLESHOOT.md §TS-3](TROUBLESHOOT.md)
>
> **전제**: RC 재설계 완료 — 모든 ML 탐지기는 `CompanyContext` 기반으로 구현. 회사별 모델 저장: `ctx.model_dir`
> **실행 순서**: Work Unit(WU) 단위로 관리. 의존 관계는 다이어그램 참조.
> **크리티컬 패스**: WU-00 → WU-01 → WU-02 → WU-01b → WU-01c → WU-03 → WU-04
> **D032~D034 반영**: BiLSTM+Attention(WU-01c), FT-Transformer(WU-01b), Stacking(WU-03) 추가

```
                         ┌──────────────┐
                         │   WU-00 (S)  │  전처리 코드리뷰 수정
                         │     ✅       │  + 데이터 분할 전략
                         └──────┬───────┘
                                │
         ┌──────────────────────┼──────────────────────────────┐
         │                      │                              │
  ┌──────▼──────┐  ┌───────────▼───────────┐    ┌─────────────▼──────────────┐
  │  WU-01 (L)  │  │ WU-05 (M) Duplicate   │    │ WU-06 (S) TimeSeries      │
  │ Supervised  │  │ WU-07 (M) IC Match    │    │ WU-08 (M) Relational      │
  │ Detector    │  │                        │    │ WU-09 (S) L3-04+Batch  ✅   │
  └──────┬──────┘  └───────────┬───────────┘    │ WU-10 (S) EUR+Holiday ✅  │
         │                      │                │ WU-11 (S) Approval+Ent ✅│
  ┌──────▼──────┐              │                │ WU-13 (M) TB 대사         │
  │  WU-02 (M)  │              │                └────────────────────────────┘
  │ VAE+IF      │              │                  (TIER 2/3 병렬)
  └──────┬──────┘              │
         │                      │
  ┌──────▼───────┐             │
  │  WU-01b (M)  │             │
  │ FT-Transform │             │
  └──────┬───────┘             │
         │                      │
  ┌──────▼───────┐             │
  │  WU-01c (M)  │             │
  │ BiLSTM+Attn  │             │
  └──────┬───────┘             │
         │                      │
         ▼                      │
  ┌─────────────┐              │
  │  WU-03 (M)  │◄─────────────┘
  │ Stacking    │
  │ Meta-Learner│
  └──────┬──────┘
         │
  ┌──────▼──────┐   ┌──────────┐
  │  WU-04 (M)  │──►│ WU-12(S) │
  │ Pipeline    │   │ DuckDB   │
  │ Integration │   │ ALTER    │
  └──────┬──────┘   └──────────┘
         │
    ─────┼──── 외부 블로커 ─────
         │
    DataSynth Rust    WU-01 완료
    ┌────▼────┐      ┌────▼────┐
    │WU-14 (M)│      │WU-17 (M)│
    │WU-15 (M)│      │SHAP+    │
    │WU-16 (L)│      │Tooltips │
    └─────────┘      └─────────┘
```

**복잡도**: S = 1대화 소형 / M = 1대화 중형 / L = 1대화 대형

### Phase 2a: ML 전처리 파이프라인

| #   | 태스크                      | 파일                                          | 가이드                                              | 상태 |
|-----|-----------------------------|-----------------------------------------------|-----------------------------------------------------|------|
| 31  | 피처 그룹 분류              | `src/preprocessing/feature_groups.py`         | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 32  | 커스텀 트랜스포머           | `src/preprocessing/transformers.py`           | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 33  | 파이프라인 빌더             | `src/preprocessing/pipeline_builder.py`       | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 34  | 라벨 전략 (자동 모드 전환)  | `src/preprocessing/label_strategy.py`         | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 35  | CV 셀렉터                   | `src/preprocessing/cv_selector.py`            | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 36  | VAE 래퍼 + 모델             | `src/preprocessing/vae_wrapper.py`, `vae_model.py` | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ✅  |
| 37  | 모델 레지스트리             | `src/preprocessing/model_registry.py`         | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 38  | 전처리 투명성               | `src/preprocessing/transparency.py`           | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 39  | 파이프라인 설명기           | `src/preprocessing/explainer.py`              | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ✅   |
| 40  | 단위 테스트 (preprocessing) | `tests/test_preprocessing/` (62 tests passed) | 03a-preprocessing "테스트 전략"                     | ✅   |

### WU-00: 전처리 코드리뷰 수정 + 데이터 분할 전략 `[S]` ✅

> 해소된 블로커: 데이터 분할 전략 결정 (D029), preprocessing 코드리뷰 미해결 5건

| 태스크                               | 파일                                       | 상태 |
|--------------------------------------|--------------------------------------------|------|
| model_registry path traversal 방어   | `src/preprocessing/model_registry.py`      | ✅   |
| model_registry 상대경로 → PROJECT_ROOT | `src/preprocessing/model_registry.py`    | ✅   |
| vae_wrapper check_is_fitted 추가     | `src/preprocessing/vae_wrapper.py`         | ✅   |
| label_strategy hybrid fallback warning | `src/preprocessing/label_strategy.py`    | ✅   |
| cv_selector VAE n_jobs=1 강제        | `src/preprocessing/cv_selector.py`         | ✅   |
| 데이터 분할 전략 문서화 (D029)       | `docs/DECISION.md`                         | ✅   |

### WU-01: SupervisedDetector `[L]` — #48 ✅

> **의존**: WU-00 ✅
> **역할**: 파이프라인 인프라 구축 (합성 데이터 순환 학습 한계로 실탐지 성능은 제한적)
> XGBoost/RF/LR/LGBM GridSearchCV 지도학습 탐지기
> **입력**: 19 피처 + 24 룰 결과 = 43차원. DataSynth GT 또는 pseudo-label 사용
> **불균형 처리**: XGB→scale_pos_weight, RF→class_weight="balanced", LGBM→is_unbalance=True
> **확장 경로**: 고객사별 실데이터 유입 시 fine-tuning으로 활성화 (Semi-supervised 인터페이스 포함)
> **코드리뷰 반영**: preprocessor 공유 버그, threshold hold-out 분리, 양성0건 차단, XGB deprecated 제거

| #   | 태스크                  | 파일                                                               | 가이드                                           | 상태 |
|-----|-------------------------|--------------------------------------------------------------------|--------------------------------------------------|------|
| 48  | SupervisedDetector      | `src/detection/supervised_detector.py`                             | [05a-detection-ml](pre-plan/05a-detection-ml.md) §164 | ✅ |
|     | LightGBM 파이프라인 추가 | `src/preprocessing/pipeline_builder.py` (확장)                    | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ✅ |
|     | SMOTE-ENN 선택적 적용    | imblearn Pipeline 내부 스텝 (CV fold별 train에만 적용)             | [05a-detection-ml](pre-plan/05a-detection-ml.md) §200 | ✅ |
|     | 단위 테스트              | `tests/modules/test_detection/test_supervised_detector.py` (17 tests) | 05a-detection-ml "테스트 전략"                | ✅   |

### WU-02: VAEDetector + IF 앙상블 `[M]` — #49 ✅

> **의존**: WU-00 ✅
> **역할**: 핵심 탐지기 — 비지도학습은 합성 데이터 적합도가 가장 높음 (순환 학습 문제 없음)
> VAE + Isolation Forest 비지도 앙상블 탐지기
> **실증 근거**: L4-04 recall=10% (1,039건 중 105건). 전수조사 결과 라벨 ~56%가 빈도 상위의 흔한 GL 조합.
> 통계 룰(하위 1%)로는 "흔하지만 도메인상 비정상"인 조합을 구조적으로 탐지 불가.
> VAE 잠재공간에서 정상 GL 조합 패턴을 학습하면 빈도와 무관하게 재구성 오차로 탐지 가능.
> **아키텍처**: Basic FC — Input(n)→Hidden(32)→Latent(8)→Hidden(32)→Output(n)
> **학습 데이터**: 순수 비지도 — X 전체 학습 (y 라벨 학습 배제, 평가 전용)
> **앙상블**: ECDF 기반 Percentile Ranking + 균등 가중합 (배치 크기 무관 안정성)
> **참고**: BiLSTM+Attention은 D032에 따라 WU-01c에서 독립 탐지기로 구현 (VAE 교체 아닌 병렬 운용)

| #   | 태스크                    | 파일                                                                    | 가이드                                            | 상태 |
|-----|---------------------------|-------------------------------------------------------------------------|---------------------------------------------------|------|
| 49  | VAEDetector + IF 앙상블    | `src/detection/vae_detector.py`                                         | [05a-detection-ml](pre-plan/05a-detection-ml.md) §236 | ✅ |
|     | t-SNE/UMAP 잠재공간 시각화 | `src/detection/latent_visualizer.py`                                    | [05a-detection-ml](pre-plan/05a-detection-ml.md) §450 | ✅ |
|     | Layer enum + ML 가중치     | `src/detection/constants.py` — `ML_SUPERVISED/ML_UNSUPERVISED` + `LAYER_WEIGHTS_WITH_ML` | score_aggregator 통합                  | ✅ |
|     | Pipeline Cold Start 방어   | `src/pipeline.py` — `_try_ml_detection()` + `_select_weights()`         | Variance 패턴 동일                                 | ✅ |
|     | score_aggregator ML 테스트 | `tests/modules/test_detection/test_score_aggregator.py` (4 tests 추가)  | ML 가중치 합계/반영/무시/Cold Start               | ✅ |
|     | 단위 테스트                | `tests/modules/test_detection/test_vae_detector.py` (23 tests)          | 05a-detection-ml "테스트 전략"                    | ✅   |

### WU-01b: FT-Transformer Tabular 탐지기 `[M]` — D033 ✅

> **의존**: WU-02 (VAE 래퍼 패턴 재사용)
> FT-Transformer: 모든 피처를 토큰화 → self-attention으로 피처 간 상호작용 학습
> **아키텍처**: 42 features → Feature Tokenizer(64-dim) + [CLS] → Transformer Encoder(2L, 4H, d=64, ff=128) → FC(64→2)
> **VRAM**: ~300MB (batch=256). RTX 3070 Ti 8GB 여유 충분
> **핵심 이점**: 룰 결과 간 조합 패턴을 attention이 자동 학습 (Top-side 조합 점수의 학습 버전)

| #    | 태스크                       | 파일                                                          | 가이드                                           | 상태 |
|------|------------------------------|---------------------------------------------------------------|--------------------------------------------------|------|
| 49b  | FT-Transformer PyTorch 모듈  | `src/preprocessing/ft_model.py` (신규)                        | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ✅   |
|      | FT-Transformer sklearn 래퍼  | `src/preprocessing/ft_wrapper.py` (신규)                      | vae_wrapper.py 패턴 동일                         | ✅   |
|      | TransformerDetector          | `src/detection/tabular_transformer.py` (신규)                 | BaseDetector 계약 준수                           | ✅   |
|      | pipeline_builder 확장        | `src/preprocessing/pipeline_builder.py` — build_ft_pipeline() | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ✅ |
|      | 단위 테스트                   | `tests/modules/test_detection/test_tabular_transformer.py` + `tests/modules/test_preprocessing/test_ft_wrapper.py` (신규) | 05a-detection-ml "테스트 전략" | ✅ |

### WU-01c: BiLSTM + Attention 시퀀스 탐지기 `[M]` — D032 ✅

> **의존**: WU-01b (래퍼 패턴 확립 후)
> 사용자-시간 윈도우 기반 시퀀스 탐지. ISA 240 "경영진 override" 반복 패턴 포착
> **시퀀스 구성**: `created_by` 그룹 → `posting_date` 정렬 → seq_len=16 슬라이딩 윈도우(stride=1)
> **아키텍처**: BiLSTM(hidden=64, bidir) → Additive Attention → FC(128→64→2). VRAM ~100MB
> **sklearn 통합**: 외부 2D API 유지, 내부에서 sequence_builder로 3D 변환

| #    | 태스크                       | 파일                                                         | 가이드                                           | 상태 |
|------|------------------------------|--------------------------------------------------------------|--------------------------------------------------|------|
| 49c  | 시퀀스 빌더 (2D→3D 윈도우)   | `src/preprocessing/sequence_builder.py` (신규)               | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ✅   |
|      | BiLSTM+Attention PyTorch 모듈 | `src/preprocessing/bilstm_model.py` (신규)                   | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ✅   |
|      | BiLSTM sklearn 래퍼          | `src/preprocessing/bilstm_wrapper.py` (신규)                 | vae_wrapper.py 패턴 동일                         | ✅   |
|      | SequenceDetector             | `src/detection/sequence_detector.py` (신규)                  | BaseDetector 계약 준수                           | ✅   |
|      | constants/settings 확장      | `src/detection/constants.py` — ML_SEQUENCE, ML04 + `config/settings.py` — bilstm_* | —                                    | ✅   |
|      | 단위 테스트 (27개)           | `tests/modules/test_detection/test_sequence_detector.py` (신규) | 05a-detection-ml "테스트 전략"                | ✅   |

### WU-03: Stacking Meta-Learner 앙상블 `[M]` — #50, D034 ✅

> **의존**: WU-01 + WU-02 + WU-01b + WU-01c + WU-05
> 기존 고정 가중합(D024) → Stacking meta-learner(LR Ridge)로 대체
> **TODO**: `LAYER_WEIGHTS_WITH_ML` 수동 가중치(룰 0.68/ML 0.32)를 데이터 기반 동적 학습으로 대체
> **Level 0**: 6개 base model (룰 24개, XGBoost, VAE, IF, BiLSTM, FT-Transformer)
> **Level 1**: Logistic Regression (L2) — 6개 확률값 → 최종 anomaly_score
> **Leakage 방지**: ✅ `train_oof()` — GroupKFold(n_splits=settings.stacking_cv_folds=3, groups=user_ids) + joblib n_jobs=-1 병렬 OOF 프로토콜. User-Leakage 방어. `train_from_results()`는 라벨 부족 시 fallback 경로로 유지.
> **Fallback**: 라벨 부족 시 기존 Percentile Ranking 가중합으로 폴백

| #   | 태스크                         | 파일                                                          | 가이드                                              | 상태 |
|-----|--------------------------------|---------------------------------------------------------------|-----------------------------------------------------|------|
| 50  | StackingEnsemble sklearn 래퍼  | `src/preprocessing/stacking.py` (신규)                        | [05a-detection-ml](pre-plan/05a-detection-ml.md)    | ✅   |
|     | EnsembleDetector               | `src/detection/ensemble_detector.py` (신규)                   | BaseDetector 계약 준수                              | ✅   |
|     | score_aggregator stacking 확장 | `src/detection/score_aggregator.py`, `constants.py`           | [05-detection](pre-plan/05-detection.md) + 05a      | ✅   |
|     | Percentile Ranking 정규화      | 가중합 전 스케일 통일 (fallback 모드)                          | [05a-detection-ml](pre-plan/05a-detection-ml.md)    | ✅   |
|     | 단위 테스트                     | `tests/modules/test_detection/test_stacking.py`, `test_ensemble_detector.py` (신규) | 05a-detection-ml "테스트 전략"        | ✅   |

### WU-04: Pipeline 통합 + ML 통합 테스트 `[M]` — #53 ✅

> **의존**: WU-03
> pipeline.py에 ML 탐지기 연결 + E2E 테스트

| #   | 태스크                           | 파일                                                                      | 가이드                                                | 상태 |
|-----|----------------------------------|---------------------------------------------------------------------------|-------------------------------------------------------|------|
| 53  | ML Pipeline 통합                 | `src/pipeline.py`, `config/settings.py`                                   | 05-detection + 06-db 통합                             | ✅ (WU-02에서 선행 구현) |
|     | ML 통합 테스트                   | `tests/modules/test_detection/test_ml_integration.py` (신규, 8개 통과)    | 05a-detection-ml "테스트 전략"                        | ✅   |
|     | Hold-out fraud type 검증         | `tests/modules/test_detection/test_holdout_fraud.py` (신규, 5개 통과)     | [05a-detection-ml](pre-plan/05a-detection-ml.md) §615 | ✅   |
|     | Feature perturbation 강건성 테스트 | `tests/modules/test_detection/test_perturbation.py` (신규, 5개 통과)     | [05a-detection-ml](pre-plan/05a-detection-ml.md) §639 | ✅   |
|     | 피처 병렬 실행 옵션              | `src/feature/engine.py`, `tests/modules/test_feature/test_engine_parallel.py` (6개 통과) | [03-feature](pre-plan/03-feature.md) §Engine | ✅   |

### WU-05: DuplicateDetector `[M]` — #58 ✅

> **의존**: WU-00 ✅
> Exact + Fuzzy 중복 전표 탐지
> **실증 근거**: L2-03 recall=9% (134건 중 12건). 샘플 20건 중 18건(90%)이 exact match 쌍 부재.
> 실무에서도 유사 금액 중복(100만→99.8만), 분할 거래(100만→50만+50만), 시차 중복을 잡으려면
> fuzzy matching + 금액 합산 분석 + embedding similarity 필요.

| #   | 태스크           | 파일                                              | 가이드                                   | 상태 |
|-----|------------------|---------------------------------------------------|------------------------------------------|------|
| 58  | DuplicateDetector | `src/detection/duplicate_detector.py`, `duplicate_rules.py` (신규) | [05-detection](pre-plan/05-detection.md) | ✅   |
|     | 단위 테스트       | `tests/modules/test_detection/test_duplicate_detector.py` (신규, 15개 통과) | 05-detection "테스트 전략" | ✅   |

### WU-06: 시계열 Rule-Based `[S]` — #59 ✅

> **의존**: WU-00 ✅
> TransactionBurst + UnusualFrequency

| #   | 태스크                 | 파일                                                                          | 가이드                                   | 상태 |
|-----|------------------------|-------------------------------------------------------------------------------|------------------------------------------|------|
| 59  | 시계열 Rule-Based      | `src/detection/timeseries_rules.py`, `timeseries_detector.py` (신규)          | [05-detection](pre-plan/05-detection.md) | ✅   |
|     | 단위 테스트             | `tests/modules/test_detection/test_timeseries_rule.py` (신규, 15개 통과)      | 05-detection "테스트 전략"               | ✅   |

### WU-07: 내부거래 매칭 `[M]` — #60, #60c ✅

> **의존**: WU-00 ✅
> IC 전표 대응 거래 매칭 + UnmatchedIntercompany

| #   | 태스크                      | 파일                                                                         | 가이드                                   | 상태 |
|-----|-----------------------------|------------------------------------------------------------------------------|------------------------------------------|------|
| 60  | 내부거래 매칭               | `src/detection/intercompany_matcher.py`, `intercompany_rules.py` (신규)      | [05-detection](pre-plan/05-detection.md) | ✅   |
| 60c | UnmatchedIntercompany       | (위 파일 내 IL3-04/IL3-05/IL3-06 서브룰)                                            | [05-detection](pre-plan/05-detection.md) | ✅   |
|     | 단위 테스트                  | `tests/modules/test_detection/test_intercompany_matcher.py` (신규, 22개 통과) | 05-detection "테스트 전략"               | ✅   |

### WU-08: Relational 탐지기 `[M]` — #60a, #60b, #60d, #60e ✅

> **의존**: WU-00 ✅
> NewCounterparty / DormantAccount / TransferPricing / MissingRelationship

| #   | 태스크                     | 파일                                                                                | 가이드                                   | 상태 |
|-----|----------------------------|-------------------------------------------------------------------------------------|------------------------------------------|------|
| 60a | NewCounterparty (R01)      | `src/detection/relational_rules.py`, `relational_detector.py` (신규)                | [05-detection](pre-plan/05-detection.md) | ✅   |
| 60b | DormantAccountActivity (R02) | (위 파일 내 포함, 연좌 플래깅 윈도우 적용)                                          | [05-detection](pre-plan/05-detection.md) | ✅   |
| 60d | TransferPricingAnomaly (R03) | (위 파일 내 포함, IC 거래 통계적 근사)                                              | [05-detection](pre-plan/05-detection.md) | ✅   |
| 60e | MissingRelationship (R04)  | (위 파일 내 포함, document_flows P2P/O2C 체인 검증)                                 | [05-detection](pre-plan/05-detection.md) | ✅   |
|     | 단위 테스트                 | `tests/modules/test_detection/test_relational_rules.py` (23개), `test_relational_detector.py` (15개) | 05-detection "테스트 전략" | ✅   |

### WU-09: L3-04 Q3 확장 + 배치 패턴 + 경고 하드코딩 제거 `[S]` — #56, #57 ✅

> **의존**: 없음 (기존 모듈 개선)

| #   | 태스크                              | 파일                                        | 가이드                                                       | 상태 |
|-----|-------------------------------------|---------------------------------------------|--------------------------------------------------------------|------|
| 57  | L3-04 계정그룹별 Q3 확장              | `src/detection/anomaly_rules_simple.py`     | [05-detection](pre-plan/05-detection.md) §185                | ✅   |
| 56  | 배치 전표 이상 패턴 (L4-06)           | `src/detection/anomaly_rules_batch.py` (신규) | [05a-detection-ml](pre-plan/05a-detection-ml.md) §배치 전표  | ✅   |
|     | 경고 하드코딩 제거 + L4-02 문서단위   | `src/detection/constants.py`, `score_aggregator.py`, `anomaly_rules_statistical.py` | [05-detection](pre-plan/05-detection.md) §1293 | ✅ |

### WU-10: 유럽 금액 포맷 + 한국 공휴일 + 외화 소수점 `[S]` — #61, #62 ✅

> **의존**: 없음. 패키지: `holidays` (이미 등록됨)

| #   | 태스크                          | 파일                                        | 가이드                                                | 상태 |
|-----|---------------------------------|---------------------------------------------|-------------------------------------------------------|------|
| 61  | 유럽 금액 포맷 지원             | `config/cleaning.yaml` + `src/ingest/type_caster.py` | [02-ingest](pre-plan/02-ingest.md) §374      | ✅   |
| 62  | 한국 공휴일 연동                | `src/feature/time_features.py`              | [04-validation](pre-plan/04-validation.md) §128      | ✅   |
|     | 외화 소수점 처리 (is_round_number) | `src/feature/amount_features.py` + `engine.py` | [03-feature](pre-plan/03-feature.md) §537        | ✅   |
|     | currency_decimals YAML 설정     | `config/audit_rules.yaml` — KRW:0, USD:2, EUR:2, JPY:0, GBP:2, CNY:2 | [03-feature](pre-plan/03-feature.md) §537 | ✅ |

### WU-11: 다단계 승인한도 + 피처 고도화 `[M]` — #63, #65 ✅

> **의존**: 없음
> pre-plan 03-feature에서 이관된 Phase 2 피처 개선 항목 포함

| #   | 태스크                             | 파일                                | 가이드                                          | 상태 |
|-----|------------------------------------|-------------------------------------|-------------------------------------------------|------|
| 63  | approval_threshold 6단계           | `src/feature/amount_features.py`    | [03-feature](pre-plan/03-feature.md) §154      | ✅   |
| 65  | description_quality 3단계 고도화   | `src/feature/text_features.py` — regex패턴 + TTR(어휘다양성) + Shannon entropy | [03-feature](pre-plan/03-feature.md) §541-601 | ✅ |
|     | Z-score CoA 상위계정 fallback      | `src/feature/amount_features.py` — n<30 소그룹 → 자산/부채/수익/비용 상위그룹 | [03-feature](pre-plan/03-feature.md) §536 | ✅ |
|     | is_suspense_account 대상 컬럼 확장 | `src/feature/pattern_features.py` — `gl_account_name` 추가 | [03-feature](pre-plan/03-feature.md) §538 | ✅ |

### WU-12: DuckDB ALTER TABLE 마이그레이션 `[S]` — #64 ✅

> **의존**: WU-03 (ML 컬럼 확정 후)

| #   | 태스크                        | 파일                          | 가이드                                 | 상태 |
|-----|-------------------------------|-------------------------------|----------------------------------------|------|
| 64  | DuckDB ALTER TABLE (ML 컬럼)  | `src/db/migration.py`        | [06-db](pre-plan/06-db.md) §580      | ✅   |

### WU-13: 재무제표-장부 대사 `[M]` — #55 ✅

> **의존**: 없음

| #   | 태스크                          | 파일                                                                       | 가이드                                                         | 상태 |
|-----|---------------------------------|----------------------------------------------------------------------------|----------------------------------------------------------------|------|
| 55  | TB 교차검증                     | `src/validation/tb_reconciliation.py` (신규)                               | [04-validation](pre-plan/04-validation.md) §재무제표-장부 대사 | ✅   |
|     | Trial Balance DuckDB 테이블 DDL | `src/db/schema.py` — PK(upload_batch_id, gl_account, fiscal_period)        | [06-db](pre-plan/06-db.md) §1238                              | ✅   |
|     | ReconciliationResult dataclass  | `src/validation/models.py` — ReconciliationItem + ReconciliationResult      |                                                                | ✅   |
|     | CompanyContext materiality 전달 | `src/context.py` — materiality_amount 필드 추가                             |                                                                | ✅   |
|     | TB 적재 함수                    | `src/db/loader.py` — load_trial_balance() + load_all() 통합                |                                                                | ✅   |
|     | 파이프라인 통합                 | `src/pipeline.py` — _validate() + _load_db() 통합                          |                                                                | ✅   |
|     | 계정 접두사 설정                | `config/audit_rules.yaml` — reconciliation_account_prefixes                |                                                                | ✅   |
|     | 단위 테스트                     | `tests/modules/test_validation/test_tb_reconciliation.py` (신규, 16개)     | 04-validation "테스트 전략"                                    | ✅   |

### WU-14: 증빙/컷오프/금액 탐지 `[M]` — #41, #42, #43

| #   | 태스크                          | 파일                                       | 가이드                                     | 상태 |
|-----|---------------------------------|--------------------------------------------|--------------------------------------------|------|
| 41  | 증빙 존재 확인 + 적격증빙       | `src/detection/evidence_rules.py`          | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |
| 42  | 컷오프 검증 (납품일 vs 전기일)  | `src/detection/evidence_rules.py`          | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |
| 43  | 증빙 금액 불일치 + 부가세 검증  | `src/detection/evidence_rules.py`          | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |

### WU-15: 수정이력/IP/전표번호/승인 탐지 `[M]` — #44, #45, #46, #47

> ⚠️ **BLOCKER 부분 해소**: #45(IP)만 ip_address 컬럼 미존재로 스켈레톤. 나머지 구현 완료.

| #   | 태스크                 | 파일                                            | 가이드                                     | 상태 |
|-----|------------------------|-------------------------------------------------|--------------------------------------------|------|
| 44  | 전표 수정 이력 탐지    | `src/detection/access_audit_rules.py` (AL1-01)    | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |
| 45  | IP 비정상 접근 탐지    | `src/detection/access_audit_rules.py` (AL1-02)    | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | 🔲   |
| 46  | 전표번호 연속성 갭     | `src/detection/access_audit_rules.py` (AL1-03)    | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |
| 47  | 승인 프로세스·TOE 검증 | `src/detection/access_audit_rules.py` (AL3-01)    | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ✅   |
|     | 오케스트레이터         | `src/detection/access_audit_layer.py`           |                                            | ✅   |
|     | 파이프라인 통합        | `src/pipeline.py` — `_try_access_audit_detection` |                                          | ✅   |
|     | 단위 테스트 (22건)     | `tests/modules/test_detection/test_access_audit_rules.py` |                                  | ✅   |

### WU-16: TrendBreak ML `[L]` — #54

> ✅ DataSynth 다기간(2~3개년) 데이터 생성 완료

| #   | 태스크                          | 파일                                              | 가이드                                                       | 상태 |
|-----|---------------------------------|---------------------------------------------------|--------------------------------------------------------------|------|
| 54  | TrendBreak (회계추정치 편의)     | `src/detection/trendbreak_detector.py` (신규)     | [05a-detection-ml](pre-plan/05a-detection-ml.md) §TrendBreak | ✅   |
|     | TL4-01 부호 편향 + TL2-01 범위 극단  | `src/detection/trendbreak_rules.py` (신규)        |                                                              | ✅   |
|     | 다기간 로더                     | `src/detection/multi_year_loader.py` (신규)       |                                                              | ✅   |
|     | 파이프라인 통합                  | `src/pipeline.py` — `_try_trendbreak_detection`   |                                                              | ✅   |
|     | 단위 테스트 (35건)               | `tests/modules/test_detection/test_trendbreak_*`  |                                                              | ✅   |

### WU-17: SHAP 시각화 + ML 툴팁 `[M]` — #52, #66

> ✅ **완료**: Phase 2 ML 파이프라인과 대시보드 연결. flagged rows(anomaly_score ≥ shap_threshold)만 SHAP 계산하여 성능 최적화.

| #   | 태스크                    | 파일                                                       | 가이드                                        | 상태 |
|-----|---------------------------|------------------------------------------------------------|-----------------------------------------------|------|
| 52  | SHAP 시각화               | `dashboard/components/shap_waterfall.py` (신규)            | [07-dashboard](pre-plan/07-dashboard.md)      | ✅   |
|     | SHAP 파이프라인 통합      | `src/pipeline.py::_try_shap_explanation`                   |                                               | ✅   |
|     | explainer base_value 반환 | `src/preprocessing/explainer.py`                           |                                               | ✅   |
|     | Explorer 3컬럼 레이아웃   | `dashboard/components/explorer_detail.py`                  |                                               | ✅   |
|     | ML 개별 점수 DB 컬럼 주입 | `src/detection/score_aggregator.py::_inject_ml_track_scores` |                                             | ✅   |
|     | Grid ML 컬럼 추가         | `dashboard/components/explorer_grid.py` (`_ML_SCORE_COLS`) |                                               | ✅   |
| 66  | ML 지표 설명 (툴팁)       | `dashboard/components/ml_tooltips.py` (신규)               | [07-dashboard](pre-plan/07-dashboard.md) §607 | ✅   |
|     | Grid headerTooltip 연결   | `dashboard/components/explorer_grid.py` (ML_TOOLTIPS)      |                                               | ✅   |

### 추천 실행 순서 (Sprint 단위)

| Sprint | Work Unit                              | 복잡도       | 비고                              |
|--------|----------------------------------------|--------------|-----------------------------------|
| **1**  | WU-00                                  | S            | ✅ 완료                           |
| **2**  | WU-01, WU-05, WU-06, WU-09, WU-10     | L+M+S+S+S   | 크리티컬패스 + 병렬 4건 (WU-09✅, WU-10✅) |
| **3**  | WU-02, WU-07, WU-11, WU-13            | M+M+S+M     | 크리티컬패스 + 병렬 3건           |
| **4**  | WU-01b, WU-08                          | M+M         | FT-Transformer + 병렬            |
| **5**  | WU-01c                                 | M           | BiLSTM+Attention 시퀀스 탐지      |
| **6**  | WU-03                                  | M           | Stacking meta-learner 앙상블      |
| **7**  | WU-04, WU-12                           | M+S         | Pipeline 통합 + DB 마이그         |
| **8**  | WU-14, WU-15, WU-16                   | M+M+L       | DataSynth 블로커 해소 후          |
| **9**  | WU-17                                  | M           | Phase 1c 블로커 해소 후           |

**Phase 2 완료 기준**: ML Pipeline E2E 동작 + Stacking 6-model 앙상블 + DuckDB ML 컬럼 적재 + 추가 탐지기 8종 동작

> **DETECTION_RULES §3.2 유형→모듈 매핑** (모듈별 관리, 16개 유형 커버):
>
> | 모듈 (WU)                    | 커버 유형                                                                                       |
> |------------------------------|-------------------------------------------------------------------------------------------------|
> | SupervisedDetector (WU-01)   | ImproperCapitalization, FictitiousVendor, RoundDollarManipulation, MisclassifiedAccount, FutureDatedEntry, CurrencyError (6개) |
> | VAEDetector + IF (WU-02)     | FictitiousEntry, ReversedAmount, TransposedDigits, StatisticalOutlier, **UnusualAccountPair** (5개) |
> | DuplicateDetector (WU-05)    | ExactDuplicateAmount (1개)                                                                      |
> | 시계열 분석 (WU-06)          | TransactionBurst, UnusualFrequency (2개)                                                        |
> | 내부거래 매칭 (WU-07)        | UnmatchedIntercompany (1개)                                                                     |
> | Relational (WU-08)           | NewCounterparty, DormantAccountActivity (2개)                                                   |
>
> **실증 근거 (2026-03-28 E2E 전수조사, v7)**:
>
> | 룰   | Recall | 라벨 | TP  | 룰 한계                                            | ML/DL 보완 전략                    | Phase |
> |------|-------:|-----:|----:|-----------------------------------------------------|-------------------------------------|:------|
> | L2-03  |     9% |  134 |  12 | exact match만 → 유사 금액·분할 거래 미탐            | DuplicateDetector (fuzzy+split+embedding) | 2 (WU-05) |
> | L3-03  |     7% |  643 |  48 | 2-hop만, 640건 trading_partner NULL, cycle 0건      | GraphDetector DFS/BFS N-hop         | 3 (#72) |
> | L4-04  |    10% | 1039 | 105 | 빈도 기반만 → 흔하지만 도메인상 이상한 조합 미탐(~56%) | VAE/GNN 잠재공간 학습               | 2 (WU-02) |
> | L4-02  |    34% |  154 |  53 | 행 단위 탐지 vs 문서 단위 라벨 기준 불일치           | 문서 단위 집계 로직 개선 (Phase 2)  | 2 (WU-09) |
>
> L2-03/L4-04는 "규칙으로 정의할 수 없는 패턴"이므로 ML 필수.
> L3-03은 그래프 알고리즘 필수. L4-02은 집계 단위 통일로 개선 가능.

---

## Phase 3: Review Queue Narrator + 기존 자산 (NLP·그래프 보존)

> **🔄 Rescope 공지 (2026-05-14)**: Phase 3의 단일 목표는 **Review Queue Narrator** — PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타를 LLM이 읽고 감사 후보 Top-N 재정렬 + 의심 근거 서술 + 다음 행동 제안.
> 단일 출처(SoT): [docs/PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md)
>
> **비범위 (구현 보존, 신규 작업 없음)**:
> - **WU-20 Text-to-SQL** ✅ — 코드 유지, Phase 3 완료 기준에서 제외. 대시보드 노출 여부는 별도 결정.
> - **WU-24 데이터분석 보고서 Excel/PDF** ✅ — 코드 유지, Phase 3 완료 기준에서 제외.
> - **WU-26 Chat UI 탭** ✅ — Text-to-SQL UI. 코드 유지, Phase 3 완료 기준에서 제외.
> - **WU-27 Export 탭** ✅ — 코드 유지, Phase 3 완료 기준에서 제외.
> - **WU-30 감사규칙 피드백 루프** ✅ — LLM이 룰 추가/수정 제안. 자유 가설 영역이라 비범위로 분류. 코드 유지.
>
> **신규 WU 슬롯**: WU-31 Review Queue Narrator (Candidate Builder + Citation Validator + Narrator UI).
>
> **Sprint D 흡수 완료 (2026-05-15)**: WU-25 `insight_generator.py` + `narrative_report.py` + `batch_insight_store.py` + 관련 테스트 2건 `git rm`. `BatchInsight` / `SignificantTxOpinion` / `EntryNarrative` / `NarrativeBatch` Pydantic 모델 제거. `dashboard/tab_overview.py::_render_batch_insight()`는 Sprint E placeholder로 임시 교체. 전체 회귀 **2991 PASS**.
>
> **유지 자산 (Narrator 입력에 활용)**:
> - WU-18 API 클라이언트 ✅ / WU-19 kiwipiepy ✅ / WU-21 NLP 탐지 ✅ / WU-22 그래프 탐지 ✅ / WU-23 Audit Trail ✅ / WU-28 헤더 탐지 ✅. (WU-25 자산은 Sprint D에서 흡수 후 폐기 — CaseNarrative/CaseNarrativeGenerator만 PHASE2 overlay용으로 보존)
>
> ---
>
> **기존 아키텍처 변경 이력 (2026-04-09)**: 로컬 LLM(Ollama + Qwen3-8B) → **상용 API(Gemini, Claude 등) 하이브리드**로 전환.
> 로컬 환경(RTX 3070 Ti 8GB)에서 8B 양자화 모델의 한국어 회계 도메인 이해력 부족 + VRAM 병목 문제.
> 원본 데이터는 로컬에서 처리하고, API에는 위험 스코어·통계 지표 등 비식별 정보만 전달.
> 비식별화 모듈은 현재 범위 외 (필요성 인지, [CONSTRAINTS.md §비식별화](CONSTRAINTS.md) 참조).
> 기존 `ollama_client.py`, `preprocessing_advisor.py`는 폴백으로 유지.
>
> **전제**: RC 재설계 완료 — 모든 모듈은 `CompanyContext` 기반으로 구현. `BaseDetector(ABC)` 상속 → `detect()` → `DetectionResult` 패턴 준수.
> **실행 순서**: Work Unit(WU) 단위로 관리. 의존 관계는 다이어그램 참조.
> **크리티컬 패스**: WU-18 → WU-20 → WU-26 → WU-27
>
> **pre-plan 참조**: Phase 3 착수 시 확인할 교차 참조 (아키텍쳐 변경은 적용 안되어있음, 아키텍쳐 변경(04-09 내용이 맞음))
> - `08-llm.md` §590-622 (Phase 1a에서 이관된 미해결 이슈 5건: header-account mismatch, process-account mismatch, vague descriptions, IC anomalies, synonym bypass)
> - `08-llm.md` §711-736 (감사기준서 갭 분석 3건: 경제적 실질, 유의적 거래, 이전가격)
> - `03-feature.md` §759 (text_features semantic stub → 상용 API 임베딩 연동)
> - `01-project-setup.md` §84 (LLM 설정 필드 활성화: api_provider, api_key, api_model)
> - L3-09 SuspenseAccount 적요 탐지: 키워드 매칭 한계(우회 표현·동의어·은어)로 Phase 3 이관 → #71 + #84 + #88로 해결

```
                         ┌──────────────┐
                         │  WU-18 (M)   │  API 클라이언트 Foundation
                         │  #67         │  + settings 확장
                         └──────┬───────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
  ┌──────▼──────┐    ┌─────────▼─────────┐    ┌───────▼───────┐
  │  WU-21 (M)  │    │    WU-20 (L)      │    │  WU-28 (S)    │
  │  NLP 탐지   │    │  Text-to-SQL      │    │  헤더탐지 LLM │
  │  + 임베딩   │    │  + 검증 + 프리셋  │    │  #82          │
  │  #71,79,    │    │  #68, #69, #70    │    ├───────────────┤
  │  85,88      │    └─────────┬─────────┘    │  WU-29 (S)    │
  │  의존:      │              │              │  전처리 확장   │
  │  WU-18+19   │    ┌─────────▼─────────┐    │  #83          │
  └──────┬──────┘    │    WU-26 (M)      │    └───────────────┘
         │           │  Chat UI 탭       │
         │           │  #73              │
  ┌──────▼──────┐    └─────────┬─────────┘
  │  WU-25 (M)  │              │
  │  인사이트   │    ┌─────────▼─────────┐
  │  + XAI      │    │    WU-27 (M)      │
  │  #78,80,86  │    │  Export 탭 통합   │
  └──────┬──────┘    │  #74              │
         │           │  의존: WU-24+26   │
  ┌──────▼──────┐    └───────────────────┘
  │  WU-30 (M)  │
  │  피드백 루프│
  │  #87        │
  └─────────────┘

  ── WU-18과 독립 (Sprint 1에서 병렬 착수) ──

  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
  │  WU-19 (S)   │   │  WU-22 (S)   │   │  WU-23 (S)   │
  │  NLP 기초    │   │  그래프 탐지  │   │  Audit Trail │
  │  kiwipiepy   │   │  #72, #81    │   │  DDL + 기록기│
  │  #84         │   │  (LLM 불필요) │   │  #76, #77    │
  └──────┬───────┘   └──────────────┘   └──────┬───────┘
         │                                      │
         │ WU-21 입력                   ┌───────▼───────┐
         └──────────────────────────►   │  WU-24 (L)    │
                                        │  감사조서      │
                                        │  Excel/PDF    │
                                        │  #75          │
                                        └───────┬───────┘
                                                │
                                                └──► WU-27 입력
```

**복잡도**: S = 1대화 소형 / M = 1대화 중형 / L = 1대화 대형

### WU-18: API 클라이언트 Foundation `[M]` — #67 ✅

> Phase 3 전체의 기초. OpenAI API(gpt-5.4 / gpt-5.4-mini 2티어) 추상화 레이어 + settings.py 교체.
> `ChatClient` / `EmbeddingClient` Protocol(ISP) + `OpenAIClient` 단일 구현체. 팩토리는 `get_chat_client(tier)` / `get_embedding_client()` 2종.
> OllamaClient 및 관련 의존성 완전 제거(WU-29 흡수).
> OpenAI Structured Outputs `strict: True` 호환을 위해 `_enforce_strict_schema()` 헬퍼로 `additionalProperties=False` + `required` 재귀 주입.

| #   | 태스크                                                    | 파일                                                                                                                                                                            | 가이드                                               | 상태 |
|-----|-----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------|------|
| 67  | LLM API 클라이언트 (Protocol + OpenAIClient + 티어 팩토리) | `src/llm/api_client.py` (신규) — `ChatClient`/`EmbeddingClient` Protocol + `OpenAIClient` + `_enforce_strict_schema` 헬퍼 + `get_chat_client(tier)` / `get_embedding_client()`   | [08-llm](pre-plan/08-llm.md)                         | ✅   |
|     | OllamaClient 제거 + preprocessing_advisor 교체 (WU-29 흡수) | `src/llm/ollama_client.py` 삭제 / `src/llm/preprocessing_advisor.py` `OllamaClient` → `get_chat_client("light")` / `src/llm/__init__.py` lazy export 정리                      | —                                                    | ✅   |
|     | settings.py LLM 필드 교체                                  | `config/settings.py` — `ollama_*` 삭제, `openai_api_key`/`openai_light_model`/`openai_reasoning_model`/`openai_embedding_model`/`openai_temperature`/`openai_timeout` 추가 + 빈 키 경고 validator | [01-project-setup](pre-plan/01-project-setup.md) §84 | ✅   |
|     | pyproject.toml + CLAUDE.md 의존성 교체                     | `pyproject.toml` llm 그룹 `openai>=1.50` 추가 + `ollama`/`vanna[…ollama…]` 제거 / `CLAUDE.md` Quick Reference + dependency-groups + Skill 맵 동기화                            | —                                                    | ✅   |
|     | 단위 테스트                                                | `tests/modules/test_llm/test_api_client.py` (신규, 33 케이스) — Protocol/OpenAIClient/strict schema/팩토리/티어 mock 기반 / `test_ollama_client.py` 삭제 / `test_preprocessing_advisor.py` ollama mock 제거 | —                                                    | ✅   |

### WU-19: NLP 기초 (kiwipiepy 형태소 분석) `[S]` — #84 ✅

> WU-18과 독립 (로컬 NLP 라이브러리만 사용). Sprint 1에서 병렬 착수.
> 한국어 텍스트 분석의 기초 인프라. WU-21(NLP 탐지)의 전처리 단계.
> DataSynth 영문 적요에서는 kiwipiepy 불필요 → `_has_korean(text)` 분기로 한국어에만 적용.
> 구현 완료: `morpheme_tokens` (list[str]) 컬럼, Kiwi iterable 배치 호출로 C++ 멀티스레딩 활용.

| #   | 태스크                        | 파일                                                                        | 가이드                                    | 상태 |
|-----|-------------------------------|-----------------------------------------------------------------------------|-------------------------------------------|------|
| 84  | kiwipiepy 형태소 분석기       | `src/feature/text_features.py` (확장) — `_tokenize_kiwi()`, `add_morpheme_features(df)` | [03-feature](pre-plan/03-feature.md) §287 | ✅   |
|     | Kiwi 인스턴스 싱글톤 + 배치   | `src/feature/text_features.py` — `_get_kiwi` lazy 싱글톤 + iterable 배치 토큰화 | —                                     | ✅   |
|     | 단위 테스트                    | `tests/modules/test_feature/test_text_kiwi.py` (신규, 31건 통과)            | —                                         | ✅   |

### WU-20: Text-to-SQL 파이프라인 `[L]` — #68, #69, #70 ✅ 🔄 *비범위(보존)*

> **2026-05-14 rescope**: Phase 3 완료 기준에서 제외. 구현물은 보존하되 신규 작업/확장 없음. 대시보드 노출 여부는 별도 결정.

> **의존**: WU-18 ✅ (API 클라이언트)
> 자연어 → SQL 변환 + 검증 + 감사 프리셋 12종. Chat UI(WU-26)의 백엔드.
> DuckDB `general_ledger` DDL + 도메인 용어를 컨텍스트로 주입.
> SQL 검증 2단계: (1) 프롬프트에 "SELECT만 허용" (2) `sql_validator`로 DML/DDL 차단.
> ChromaDB는 RAG 컨텍스트 저장소로 선택적 활용.

| #   | 태스크                        | 파일                                                                          | 가이드                            | 상태 |
|-----|-------------------------------|-------------------------------------------------------------------------------|-----------------------------------|------|
| 69  | SQL 검증기                    | `src/llm/sql_validator.py` (신규) — DML 차단, 테이블 화이트리스트, 서브쿼리 깊이 제한, 자동 LIMIT | [08-llm](pre-plan/08-llm.md) | ✅   |
| 70  | 감사 프리셋 12종              | `src/llm/prompt_presets.py` (신규) — 기본 6종 + 프로세스별 6종 + 카테고리 분류 | [08-llm](pre-plan/08-llm.md)     | ✅   |
| 68  | Text-to-SQL 엔진              | `src/llm/text_to_sql.py` (신규) — DDL 컨텍스트 주입 + LLM SQL 생성 + sql_validator 연동 + DuckDB 실행 + DataFrame 반환 | [08-llm](pre-plan/08-llm.md)     | ✅   |
|     | ChromaDB 스키마 학습 (선택)   | `src/llm/schema_trainer.py` (신규) — DDL + 도메인 용어 + 샘플 Q&A RAG 저장    | [08-llm](pre-plan/08-llm.md) §697 | ✅  |
|     | 단위 테스트                    | `tests/modules/test_llm/test_text_to_sql.py`, `test_sql_validator.py`, `test_prompt_presets.py` (신규) | — | ✅   |

### WU-21: NLP 탐지 + 임베딩 `[M]` — #71, #79, #85, #88 ✅

> **의존**: WU-18 ✅ (API embed) + WU-19 ✅ (kiwipiepy)
> 적요 NLP 분석기 + 경제적 실질 판단 + 계정명 의미 분석 + 임베딩 동의어 매칭.
> `NLPDetector(BaseDetector)` — 5개 서브룰: NLP01~NLP05.
> Phase 1a 미해결 이슈 5건(08-llm §590-622)을 NLP로 해결.
> 비식별화: morpheme_tokens(한글) join 또는 영문 stopword 제거 결과만 임베딩 API에 전달, 원본 적요 전문 전송 금지.
> **성능**: O(U) 캐시(중복 텍스트 API 1회) + numpy 행렬 곱 코사인(루프 금지). dict 인메모리 캐시(ChromaDB 미사용 — 대상 소규모).
> **graceful**: API 키 미설정/연결 실패 시 NLPDetector 빈 결과 + warning, 파이프라인 중단 없음.

| #   | 태스크                        | 파일                                                                      | 가이드                                                                                 | 상태 |
|-----|-------------------------------|---------------------------------------------------------------------------|----------------------------------------------------------------------------------------|------|
| 71  | 적요 NLP 분석기               | `src/detection/nlp_analyzer.py` + `nlp_rules.py` (신규) — NLP01(header-account 불일치), NLP02(process-account 불일치), NLP03(비정형 적요), NLP04(IC 이상), NLP05(동의어 우회). graph_detector + graph_rules 컨벤션 미러링 | [05-detection](pre-plan/05-detection.md), [08-llm](pre-plan/08-llm.md) §590-622       | ✅   |
| 79  | 경제적 실질 판단              | `src/detection/nlp_rules.py` — NLP01/NLP02에서 임베딩 유사도 + account_category 교차 검증으로 ISA 315/240 로직 반영 | [08-llm](pre-plan/08-llm.md) §715-722                                                 | ✅   |
| 88  | semantic_similarity 구현      | `src/llm/embedding_service.py` (신규) — `EmbeddingService`: O(U) dict 캐시 + L2 정규화 가정 행렬 곱 코사인 + centroid 거리 + find_nearest. `text_features.add_semantic_similarity` stub 교체 | [03-feature](pre-plan/03-feature.md) §759, [08-llm](pre-plan/08-llm.md) §610-622      | ✅   |
| 85  | LLM 계정명 의미 분석          | `src/feature/text_features.py` (확장) — `add_account_semantic(df)`: 고유 gl_account만 LLM 카테고리 분류 + 적요 교차 검증 컬럼 | [03-feature](pre-plan/03-feature.md) §423                                              | ✅   |
|     | constants.py NLP 룰 등록      | `src/detection/constants.py` — `NLP01`~`NLP05` + `Layer.NLP = "nlp"` + SEVERITY_MAP (4/3/2/3/3) | —                                                                                      | ✅   |
|     | settings.py NLP 파라미터       | `config/settings.py` — `nlp_*` 7종(threshold·percentile·batch_size 등)    | —                                                                                      | ✅   |
|     | pipeline.py 통합              | `src/pipeline.py` — `_try_nlp_detection()` 추가, Graph 탐지 직후 호출      | —                                                                                      | ✅   |
|     | 단위 테스트 (29건)             | `tests/modules/test_detection/test_nlp_analyzer.py` (15건), `tests/modules/test_llm/test_embedding_service.py` (14건) — Mock EmbeddingClient + 룰별 단위 + 에러 격리 + graceful skip | —                                                                                      | ✅   |

### WU-22: 그래프 순환 탐지 `[S]` — #72, #81 ✅ (2026-04-11)

> WU-18과 독립 (networkx 기반, LLM 불필요). Sprint 1에서 병렬 착수.
> L3-03 recall=7% (643건 중 48건) 개선 목표. trading_partner NULL 640건 → N-hop DFS/BFS + implicit 엣지 추론.
> `GraphDetector(BaseDetector)` — 2개 서브룰: GR01, GR03.
> R03(relational_rules.py) 통계 기반과 GR03 그래프 토폴로지 기반 차별화.
> CentralityAnomaly(GR02)는 제외 — DataSynth 그래프 규모(회사 3개, 거래처 수십 개)에서 centrality 분석 무의미. 실데이터 유입 후 재검토.
> **OOM 방어 3중 장치**: pandas 사전 필터(is_intercompany + min_amount ≥ 1천만원) → `nx.from_pandas_edgelist` 벡터화 구축(add_edge 루프 금지) → max_edges 자동 상향. 100k 행 벤치마크 1.3초.

| #   | 태스크                           | 파일                                                                                  | 가이드                                         | 상태 |
|-----|----------------------------------|---------------------------------------------------------------------------------------|------------------------------------------------|------|
| 72  | 그래프 순환 탐지                 | `src/detection/graph_rules.py` + `graph_detector.py` (신규) — GR01(DFS N-hop, length_bound=5) | [05-detection](pre-plan/05-detection.md)       | ✅   |
| 81  | TransferPricingAnomaly 그래프    | `src/detection/graph_rules.py` (확장) — GR03: 양방향 IC 엣지 가격 asymmetry (R03과 구조적 차별화) | [DETECTION_RULES](DETECTION_RULES.md) §4.4     | ✅   |
|     | pyproject.toml networkx 추가     | `pyproject.toml` — core 그룹에 `networkx>=3.2` 추가                                   | —                                              | ✅   |
|     | constants.py 그래프 룰 등록      | `src/detection/constants.py` — `GR01`, `GR03` + `Layer.GRAPH = "graph"` + SEVERITY_MAP | —                                             | ✅   |
|     | settings.py 파라미터             | `config/settings.py` — graph_gr01_* 4개 + graph_gr03_* 2개 (OOM 방어 포함)            | —                                              | ✅   |
|     | pipeline.py 통합                 | `src/pipeline.py` — `_try_graph_detection()` 신규 (RelationalDetector 직후 실행)      | —                                              | ✅   |
|     | 단위 테스트 (16건)               | `tests/modules/test_detection/test_graph_detector.py` (신규) — Basic 3 + GR01 6 + GR03 2 + OOM 3 + Edge 2 | —                                              | ✅   |

### WU-23: Audit Trail 인프라 `[S]` — #76, #77 ✅

> WU-18과 독립. Sprint 1에서 병렬 착수.
> Export(WU-24)의 전제 조건. 이벤트 6종: upload, validate, analysis, query, filter, export.
> **구현 결정**: 새 `audit_trail` 테이블 대신 기존 `audit_log` 테이블 재사용. `AuditTrail`은 `src/db/audit_log.py::record_event`의 OOP 래퍼. `user_action`은 `details` JSON에 병합 저장하고 조회 시 DuckDB `->>` 연산자로 독립 컬럼 노출.

| #   | 태스크                        | 파일                                                                             | 가이드                                         | 상태 |
|-----|-------------------------------|----------------------------------------------------------------------------------|------------------------------------------------|------|
| 76  | audit_log action 허용값 확장  | `src/db/schema.py` (주석만) — `action` 컬럼 주석에 user 이벤트 6종 추가. DDL 변경 없음 | [09-export](pre-plan/09-export.md) §31         | ✅   |
| 77  | Audit Trail 기록기            | `src/export/audit_trail.py` (신규) — `AuditEvent` dataclass + `AuditTrail`: `log()`, `export_trail()`, `get_trail()` | [09-export](pre-plan/09-export.md) §371-396    | ✅   |
|     | export 패키지 초기화          | `src/export/__init__.py` (신규)                                                  | —                                              | ✅   |
|     | 단위 테스트                    | `tests/modules/test_export/test_audit_trail.py` (신규) — 14개 테스트 (5 클래스)   | —                                              | ✅   |

### WU-24: 데이터분석 보고서 Excel/PDF `[L]` — #75 ✅ 🔄 *비범위(보존)*

> **2026-05-14 rescope**: Phase 3 완료 기준에서 제외. 구현물은 보존하되 신규 작업/확장 없음.

> **방향 전환**: 원래 "감사조서(Audit Working Paper)" 산출이었으나, 감사조서는 ISA 230에 따라
> 감사인이 직접 작성하는 법적 문서이므로 **데이터분석 보고서(Data Analysis Report)** 로 재정의.
> 감사인이 자신의 감사조서에 첨부/참조할 수 있는 보조 자료를 생성한다.
>
> **의존**: WU-23 (audit_trail 기록기) ✅
> Excel 5~6시트 + PDF 6섹션 데이터분석 보고서.
> 메모리 대응: openpyxl `write_only=True` + `WriteOnlyCell` (사후 셀 접근 불가 회피).
> PII 마스킹: created_by, approved_by SHA-256 해싱 + auxiliary_account 부분 치환 (원본 불변).
> 차트 hang 방지: kaleido `to_image()` ThreadPoolExecutor + timeout(10s) + 표 fallback.
>
> **⚠️ audit_log 조회 시**: `AuditTrail.get_trail()` 사용. `queries.py::audit_log_by_batch` 프리셋은
> 시스템 이벤트가 섞이므로 금지. 상세 비교는 WU-27 주의 블록 참조.

| #   | 태스크                        | 파일                                                                          | 가이드                                         | 상태 |
|-----|-------------------------------|-------------------------------------------------------------------------------|------------------------------------------------|------|
| 75  | ExcelExporter                 | `src/export/excel_exporter.py` (신규) — 5~6시트: 분석 요약, 이상 전표, Benford, 탐지 규칙 통계, 직무분리 분석, 원본 데이터 + ExportFilter + 마스킹 | 계획서: `~/.claude/plans/vectorized-sauteeing-squirrel.md` | ✅ |
|     | PDFExporter                   | `src/export/pdf_exporter.py` (신규) — 6섹션: 표지(면책조항), 요약, 프로세스 분포, Benford, 이상 전표 Top N, 탐지 규칙+SoD. malgun.ttf 우선 한글 폰트 탐색 | 계획서 참조 | ✅ |
|     | ExportFilter + ExportConfig   | `src/export/models.py` (신규) — 필터/설정 dataclass + 컬럼 매핑 상수 + 면책조항 | 계획서 참조 | ✅ |
|     | 마스킹 유틸                    | `src/export/masking.py` (신규) — SHA-256 해싱 + 부분 치환 (원본 불변)         | 계획서 참조 | ✅ |
|     | 단위 테스트                    | `tests/modules/test_export/test_models.py` (10), `test_masking.py` (10), `test_excel_exporter.py` (8), `test_pdf_exporter.py` (5) — 33개 신규 테스트 통과 | — | ✅ |

### WU-25: LLM 인사이트 + XAI `[M]` — #78, #80, #86 ✅

> **의존**: WU-18 (API 클라이언트) ✅ + WU-21 (NLP 결과 활용) ✅
> 배치 인사이트 + L4-03 AND L4-01 유의적 거래 합리성 평가 + 엔트리 XAI Narrative Report.
> 비식별화는 본 프로젝트 범위 외(TS-6). `sanitizer.py` 생성하지 않음.
> XAI 호출 조건: `risk_level IN ('High','Critical') AND anomaly_score > 0`.
> Laziness 방어: `settings.narrative_batch_size=15` + 누락 검증·재귀 재시도.
> 호출 주체: 대시보드 On-Demand. 결과는 `llm_narratives` 테이블에 캐시 (document_id PK).

| #   | 태스크                        | 파일                                                                        | 가이드                                  | 상태 |
|-----|-------------------------------|-----------------------------------------------------------------------------|-----------------------------------------|------|
| 78  | 인사이트 생성기(배치)         | `src/llm/insight_generator.py` (신규) — `generate_batch_insight()` + DuckDB 집계 + reasoning 티어 | [08-llm](raw-plan/08-llm.md) §587-588  | ✅   |
| 80  | 유의적 거래 합리성 평가       | `src/llm/insight_generator.py` — `_query_significant_tx()` L4-03 AND L4-01 → audit_flag 의견 | [08-llm](raw-plan/08-llm.md) §724-738  | ✅   |
| 86  | XAI Narrative Report          | `src/llm/narrative_report.py` (신규) — 파생변수 18종 + 탐지결과 → 1~3문장 사유서. batch=15 + 재귀 재시도 + 캐시 UPSERT | [08-llm](raw-plan/08-llm.md) §630-662  | ✅   |
|     | 응답 스키마                    | `src/llm/models.py` (확장) — BatchInsight, SignificantTxOpinion, EntryNarrative, NarrativeBatch | —                                       | ✅   |
|     | DDL + settings                 | `src/db/schema.py` llm_narratives 테이블/인덱스 + `config/settings.py` WU-25 4개 필드        | —                                       | ✅   |
|     | 단위 테스트                    | `tests/modules/test_llm/test_insight_generator.py` (6), `test_narrative_report.py` (10) — 16건 통과 | —                                       | ✅   |

### WU-26: Chat UI 탭 `[M]` — #73 ✅ 🔄 *비범위(보존)*

> **2026-05-14 rescope**: Text-to-SQL UI. Phase 3 완료 기준에서 제외. 구현물 보존.

> **의존**: WU-20 (Text-to-SQL)
> Streamlit Chat UI + 프리셋 버튼 12종 + 스트리밍 응답.
> `st.chat_input` + `st.chat_message` + SQL 결과 `st.dataframe` + `st.code` 패턴.
> AuditTrail.log(event_type="query") 자동 호출.
> **Streamlit 함정 대응**: `st.write_stream` 반환값 즉시 history append(rerun 유실 방지),
> `df_preview=head(100)`만 session 저장(OOM 방지), `CHAT_HISTORY_MAX=20` FIFO.

| #   | 태스크                        | 파일                                                             | 가이드                                         | 상태 |
|-----|-------------------------------|------------------------------------------------------------------|------------------------------------------------|------|
| 73  | Chat UI 탭                    | `dashboard/tab_chat.py` (신규) — 프리셋 2서브탭(기본/프로세스) × columns(3)×2행 + chat_input + 프리뷰 ≤100행 | [07-dashboard](pre-plan/07-dashboard.md)       | ✅   |
|     | 대화 히스토리 관리            | `dashboard/_state.py` (확장) — `KEY_CHAT_HISTORY`, `KEY_CHAT_LLM_ENABLED` | —                                              | ✅   |
|     | app.py 탭 등록                | `dashboard/app.py` (수정) — 5번째 "Chat" 탭 추가                | —                                              | ✅   |
|     | 단위 테스트                    | `tests/modules/test_dashboard/test_tab_chat.py` (17 tests) — preview 컷/FIFO/audit event/run_query graceful | —                                              | ✅   |

### WU-27: Export 탭 (통합) `[M]` — #74 ✅ 🔄 *비범위(보존)*

> **2026-05-14 rescope**: Phase 3 완료 기준에서 제외. 구현물 보존.

> **의존**: WU-24 (감사조서) + WU-26 (Chat UI, 선택적) + WU-23 (audit_trail)
> 대시보드 Export 탭 — 포맷 선택(Excel/PDF/CSV), ExportFilter UI, 다운로드 버튼.
> pipeline.py 각 단계에 AuditTrail.log() 주입.
>
> **⚠️ audit_log 조회 경로 주의 (WU-23 구현 이후 추가)**:
> `audit_log` 테이블을 조회하는 경로가 두 가지라 **용도가 다르다**. 혼용 금지.
>
> | 경로                                                         | 반환 범위                                       | 정렬                      | 용도                                |
> |--------------------------------------------------------------|-------------------------------------------------|---------------------------|-------------------------------------|
> | `src/db/queries.py::PRESET_QUERIES["audit_log_by_batch"]`    | **모든 action** (시스템 이벤트 포함)            | `created_at DESC`         | 대시보드 감사 로그 뷰어 (최신순)    |
> | `src/export/audit_trail.py::AuditTrail.get_trail(batch_id)`  | **user 이벤트 6종만** (upload/validate/analysis/query/filter/export) | `created_at ASC, id ASC` | Export/CSV 다운로드 (시간순)        |
>
> 차이점:
> 1. **필터링**: 프리셋은 `detection_run`/`whitelist_*`/`pipeline_validate_fail` 같은 시스템 이벤트가 함께 반환됨. `AuditTrail.get_trail()`은 사용자 이벤트만 반환.
> 2. **컬럼**: `AuditTrail.get_trail()`은 `details->>'user_action'`을 독립 컬럼으로 추출. 프리셋은 `details` 원본 JSON만 제공.
> 3. **정렬 방향**: 프리셋 DESC(최신 우선), 트레일 ASC(시간순).
>
> **WU-27 가이드**: Export CSV/감사 증적 다운로드에는 반드시 `AuditTrail.get_trail()`을 사용한다. `audit_log_by_batch` 프리셋을 재사용하면 `detection_run` 같은 시스템 이벤트가 다운로드 파일에 섞여 감사인에게 혼동을 준다. 프리셋은 대시보드 내부 뷰어(최신 로그 조회) 전용.

| #   | 태스크                        | 파일                                                                      | 가이드                                                               | 상태 |
|-----|-------------------------------|---------------------------------------------------------------------------|----------------------------------------------------------------------|------|
| 74  | Export 탭                     | `dashboard/tab_export.py` (신규) — 2-Step 패턴(생성 버튼 → session 캐싱 → download_button), 포맷 radio(Excel/PDF/감사 증적 CSV) + ExportFilter UI(사이드바 FilterState 어댑트) + ExportConfig 폼 + 해시 기반 stale 캐시 무효화 | [07-dashboard](pre-plan/07-dashboard.md), [09-export](pre-plan/09-export.md) §470-476, 계획서: `~/.claude/plans/declarative-finding-toast.md` | ✅   |
|     | pipeline.py audit_trail 주입  | `src/pipeline.py` (수정) — `AuditPipeline.__init__(audit_trail=None)` 선택 주입 + `_NullAuditTrail` no-op 폴백 + upload/validate/analysis(탐지)/analysis(DB 적재)/재탐지 5개 지점 로깅, graceful 래퍼로 로깅 실패가 파이프라인 차단 안 함 | —                                                                    | ✅   |
|     | app.py 탭 등록                | `dashboard/app.py` (수정) — Export 탭 추가                                | —                                                                    | ✅   |
|     | _state.py 세션 키 추가        | `dashboard/_state.py` (수정) — KEY_EXPORT_FORMAT + 2-Step 캐싱용 READY_DATA/NAME/MIME/HASH 5개 | — | ✅ |
|     | 단위 테스트                    | `tests/modules/test_dashboard/test_tab_export.py` (신규, 22 tests) — 헬퍼 단위(`_build_filter` / `_build_config_from_form` / `_settings_hash` / `_sanitize_filename` / `_make_filename` / `_build_audit_event` / `_parse_date`) + 캐시 무효화 + Excel/PDF/CSV bytes 시그니처 검증. `tests/modules/test_pipeline/test_pipeline.py` 확장(+5 tests) — audit_trail 호환성/단계별 로깅(3·4이벤트)/redetect/로깅 실패 격리 | —                                                                    | ✅   |

### WU-28: LLM 헤더 탐지 고도화 `[S]` — #82 ✅

> **의존**: WU-18 (API 클라이언트)
> 기존 5-factor 스코어링(header_detector.py)은 유지. 구조 confidence가 effective_threshold 미만일 때 LLM(gpt-5.4-mini)에 재검증 요청 → max() 합성으로 복원.
> 환각 방지: `_serialize_context()`에서 NaN → "" 치환 + `[Row N]` 라벨 강제. LLM 미가용/JSON 파싱 실패/설정 off 시 기존 동작 폴백.

| #   | 태스크                        | 파일                                                                   | 가이드                                      | 상태 |
|-----|-------------------------------|------------------------------------------------------------------------|---------------------------------------------|------|
| 82  | LLM 헤더 탐지 고도화          | `src/ingest/header_detector.py` (확장) — `_llm_header_check`/`_try_llm_boost`/`_serialize_context` + `HeaderLLMResponse` 스키마 + `enable_llm_header_fallback` 설정 | [02-ingest](pre-plan/02-ingest.md) §848     | ✅   |
|     | 단위 테스트                    | `tests/modules/test_ingest/test_header_llm.py` (신규) — 10 케이스 PASS | —                                           | ✅   |

### WU-29: LLM 전처리 제안 확장 `[S]` — #83 ✅ (WU-18에 흡수)

> WU-18에서 `preprocessing_advisor.py`의 `OllamaClient` → `get_chat_client("light")` 교체를 함께 수행. `rule_based_fallback`은 `RuntimeError` 흡수 + `self.client=None` 패턴으로 유지. 본 태스크는 독립 작업으로 남기지 않는다.

### WU-30: 감사규칙 피드백 루프 `[M]` — #87 ✅ 🔄 *비범위(보존)*

> **2026-05-14 rescope**: LLM이 룰 추가/수정을 제안하는 자유 가설 영역. Phase 3 v2 비범위. 구현물 보존, 신규 작업 없음.

> **의존**: WU-25 (인사이트 생성기)
> LLM이 새 데이터 패턴 분석 → audit_rules.yaml 개선 제안 → 사용자 승인.
> 제안 카테고리: manual_source_codes, suspense_keywords, suspense_account_codes, revenue_account_prefixes, intercompany_identifiers.
> 안전장치: LLM 제안은 항상 사용자 승인 필요 (자동 반영 금지). 회사별 오버라이드에만 저장 (전역 yaml 불변). 감사 로그 `rule_feedback_log.jsonl` append-only.

| #   | 태스크                        | 파일                                                                           | 가이드                                  | 상태 |
|-----|-------------------------------|--------------------------------------------------------------------------------|-----------------------------------------|------|
| 87  | 피드백 루프                   | `src/llm/rule_feedback.py` — 카테고리별 Top-K 집계 + 1회 LLM 호출 + 3-way 중복검사 + 회사 override 저장 | [08-llm](pre-plan/08-llm.md) §664-691  | ✅   |
|     | 대시보드 UI                   | `dashboard/components/rule_feedback_panel.py` + app.py "룰 제안" 탭 — 카테고리별 expander + 근거 전표 + 승인/거부 | —                                       | ✅   |
|     | 단위 테스트                    | `tests/modules/test_llm/test_rule_feedback.py` — 8건 통과 (중복/머지/IC왕복/감사로그/graceful) | —                                       | ✅   |

### 추천 실행 순서 (Sprint 단위)

| Sprint | Work Unit                                          | 복잡도     | 비고                                                  |
|--------|----------------------------------------------------|------------|-------------------------------------------------------|
| **1**  | WU-18, WU-19, WU-22, WU-23                        | M+S+S+S    | 4개 동시 착수. WU-19/22/23은 WU-18과 독립             |
| **2**  | WU-20                                              | L          | 크리티컬 패스. WU-18 완료 필수                        |
| **3**  | WU-21, WU-24                                       | M+L        | WU-21: WU-18+19 완료 후. WU-24: WU-23 완료 후. 병렬  |
| **4**  | WU-25, WU-26                                       | M+M        | WU-25: WU-18+21 후. WU-26: WU-20 후. 병렬            |
| **5**  | WU-27, WU-28, WU-29                               | M+S+S      | WU-27: WU-24+26 후. WU-28/29: WU-18 후 언제든. 병렬  |
| **6**  | WU-30                                              | M          | WU-25 완료 후                                         |

> **DETECTION_RULES Phase 3 유형→모듈 매핑**:
>
> | 모듈 (WU)                       | 커버 유형                                                                                        |
> |---------------------------------|--------------------------------------------------------------------------------------------------|
> | NLPDetector (WU-21)             | NLP01~NLP05: header-account 불일치, process-account 불일치, 비정형 적요, IC 이상, 동의어 우회 (5개) |
> | GraphDetector (WU-22)           | GR01(CircularTransaction), GR03(TransferPricingAnomaly) (2개)                                    |
> | TrendBreak (WU-16, Phase 2)     | 시계열 추세 이탈 — Phase 2 DataSynth 블로커 해소 후 구현 (#54)                                    |

### WU-31: Review Queue Narrator `[L]` — 신규 (v2 핵심)

> **의존**: WU-18 (API 클라이언트) ✅ / WU-25 (insight_generator, narrative_report) ✅ / Phase 2 ML 스코어 산출 + DuckDB review queue 테이블.
> 단일 출처: [docs/PHASE3_REVIEW_NARRATOR_SPEC.md](PHASE3_REVIEW_NARRATOR_SPEC.md).
>
> Candidate Builder는 review queue 1건당 (rule_hits + ml_scores + journal_meta + peer_context)을 PII 비식별 후 LLM에 전달. Structured Output(`strict: True`)으로 우선순위·근거·다음 행동을 JSON으로 받아 Citation Validator가 rule_id/feature_id/journal_id 존재 여부를 검증. 검증 실패 건은 `confidence=low` + 후순위 처리.

| #   | 태스크                          | 파일                                                                                                                  | 가이드                                                  | 상태 |
|-----|---------------------------------|----------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|------|
| 신규 | Candidate Builder              | `src/llm/review_narrator/candidate_builder.py` (신규) — review queue + rule_hits + ml_scores + journal_meta → LLM 입력 dict | [PHASE3_REVIEW_NARRATOR_SPEC](PHASE3_REVIEW_NARRATOR_SPEC.md) | ✅ Sprint B |
| 신규 | PII Sanitizer                  | `src/llm/review_narrator/sanitizer.py` (신규) — 식별자(이름·사업자번호 등) 비식별 처리                                  | 동                                                      | ✅ Sprint B |
| 신규 | Review Narrator                | `src/llm/review_narrator/narrator.py` (신규) — Structured Output 스키마 + reasoning 티어 호출 + light 폴백             | 동                                                      | ✅ Sprint C |
| 신규 | Citation Validator             | `src/llm/review_narrator/citation_validator.py` (신규) — rule_id/feature_id/journal_id 존재 검증 + 실패 시 confidence 강등 | 동                                                      | ✅ Sprint A |
| 신규 | Review Queue 테이블/캐시 DDL    | `src/db/schema.py` (확장) — `review_narratives` 테이블 (candidate_id PK, narrative JSON, citation_valid bool, created_at) | 동                                                      | ✅ Sprint A |
| 신규 | 응답 스키마 (Pydantic)          | `src/llm/review_narrator/models.py` (신규) — `ReviewNarrative`, `ReasoningItem`, `ReasoningEvidence`, `SuggestedAction` | 동                                                      | ✅ Sprint A |
| 신규 | 대시보드 통합 (Sprint E1)        | `dashboard/tab_review_queue.py` + `dashboard/components/review_narrator{,_jump}.py` (신규) — 카드 + citation 점프, `app.py` 탭 등록 + `_state.py` KEY_REVIEW_QUEUE_* | 동                                                      | ✅ Sprint E1 (2026-05-15 — 9개 unit PASS, dashboard 175 regression PASS, streamlit boot 200) |
| 신규 | 대시보드 워크플로우 (Sprint E2)  | `dashboard/components/review_queue_workflow.py` (신규) + `tab_review_queue.py` 확장 — 실행 트리거 + 분류 라디오·메모 + 사이드바 6종 필터·검색. `src/db/schema.py` idempotent ALTER (`audit_decision`/`audit_note`/`reviewed_by`/`reviewed_at` + `idx_review_narratives_decision`). `src/llm/review_narrator/cache.py::update_audit_decision`·`read_audit_decision` 헬퍼. `src/export/audit_trail.py` EventType 2종(`analysis_run`/`review_decision_change`) 확장. | 동                                                      | ✅ Sprint E2 (2026-05-15 — workflow 29 + cache 9 신규 + E1 회귀 호환, 누적 171 PASS) |
| 신규 | 단위 테스트                     | `tests/modules/test_llm/test_review_narrator/*` (신규) — Candidate Builder / Sanitizer / Citation Validator / Narrator / Cache mock + E2E 통합 | —                                                       | ✅ Sprint A+B+C+E2 (138개 PASS — models 18 / citation 11 / sanitizer 26 / builder 26 / narrator 12 / cache 19 / 통합 5 / E1 9 / E2 29 ※ E1·E2는 dashboard 측 카운트) |
| 신규 | 평가 하니스 + 비용 가드          | `src/llm/review_narrator/budget_guard.py` + `audit_logger.py` + `eval_harness.py` (신규) + `tests/modules/test_llm/test_review_narrator/test_eval.py` (신규). `audit_log.analysis_run` 이벤트 기록, citation/Spearman/latency 측정, `test-results/phase3_review_narrator_eval/YYYYMMDD/` JSON 저장. opt-in `RUN_LLM_EVAL=1`. | —                                                       | ✅ Sprint F (2026-05-15 — 22 unit PASS + 1 opt-in skipped. §4.2 schema enum 회귀 2건 포함) |

**Phase 3 v2 완료 기준** (Review Queue Narrator):
1. Candidate Builder: PHASE1 룰 히트 + PHASE2 ML 스코어 + 전표 메타 → LLM 입력 dict 생성. PII 비식별 통과.
2. Review Narrator: Structured Output(`strict: True`)으로 candidate 1건당 (priority_rank, summary, reasoning[], suggested_actions[], confidence) 반환.
3. Citation Validator: `evidence.rule_id` / `feature_id` / `journal_id` 모두 입력에 실존. 검증 통과율 ≥ 99%.
4. Latency: candidate 1건당 p95 ≤ 8s(reasoning) / ≤ 2s(light).
5. 우선순위 일치도: 감사인 라벨 N=50 vs LLM rank Spearman ρ ≥ 0.6.
6. 캐시: `review_narratives` 테이블에 candidate_id 단위 UPSERT.

**유지 자산 정합 기준** (rescope 후에도 통과해야 함):
- WU-18 API 클라이언트 / WU-21 NLP 탐지 / WU-22 그래프 탐지 / WU-25 insight·narrative / WU-23 Audit Trail / WU-28 헤더 LLM 보강: 회귀 테스트 그대로 통과.

**비범위 (테스트만 통과, 신규 기준 없음)**:
- WU-20 Text-to-SQL / WU-24 Export 보고서 / WU-26 Chat UI / WU-27 Export 탭 / WU-30 룰 피드백 루프.
> Current DataSynth production baseline: `data/journal/primary/datasynth/` = `v23` freeze (2026-04-22).  
> `B04 DuplicatePayment`는 `P2P + KZ` 지급쌍과 pair/negative-control sidecar 기준으로 승격되었고, `v20.4`는 백업본 `datasynth_backup_v20_4_20260422`로 보존된다.
> Current production DataSynth baseline: `data/journal/primary/datasynth/` freeze `v23` as of 2026-04-22. Older `v20.x` references below are historical task notes.
