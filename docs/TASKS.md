# Phase별 태스크

> 각 태스크의 상세 구현 가이드는 `docs/pre-plan/` 참조
> pre-plan 번호(00~10)는 **도메인 분류**이며, 구현 순서는 **Phase 번호**를 따른다.
> 예: `05a-detection-ml.md`는 Phase 2b의 설계 레퍼런스이지, 05 다음에 바로 구현하는 것이 아님.

## 진행 현황 요약

| Phase                           | 완료 | 전체 | 진행률 |
|---------------------------------|------|------|--------|
| 1a 데이터 파이프라인             | 20   | 20   | 100%   |
| 1b 이상탐지+DB+Layer D           | 21   | 21   | 100%   |
| 1c 대시보드                      | 12   | 12   | 100%   |
| RC 재설계 (Company-Centric)      | 41   | 41   | 100%   |
| 2a ML 전처리                     | 10   | 10   | 100%   |
| 2 WU-00 전처리 수정              |  5   |  5   | 100%   |
| 2 WU-01~04 ML 핵심               |  0   |  6   |   0%   |
| 2 WU-05~08 추가탐지              |  0   |  4   |   0%   |
| 2 WU-09~13 고도화                |  0   |  5   |   0%   |
| 2 WU-14~16 DataSynth             |  0   |  3   |   0%   |
| 2 WU-17 대시보드ML               |  0   |  1   |   0%   |
| 3 NLQ+Graph+Polish               |  0   | 22   |   0%   |
| **합계**                         | 109  | 150  |  73%   |

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
| 0b  | 메인 데이터 생성    | `data/journal/primary/datasynth/` (1,106K건, v21 확정)          | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
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
| 16  | Layer A 무결성                   | `src/detection/integrity_layer.py` (A01~A03)                         | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 17  | Layer B 부정탐지                 | `src/detection/fraud_layer.py` (B01~B11, 42 tests)                   | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 18  | Layer C 이상징후                 | `src/detection/anomaly_layer.py` (C01~C10, 41 tests)                 | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19  | 점수 집계                        | `src/detection/score_aggregator.py` (3레이어+Benford+B19, 21 tests)  | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19a | 역분개 패턴 탐지 (1:1 + N:M)    | `src/detection/anomaly_rules_reversal.py` + `anomaly_layer.py`       | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19b | Top-side JE 조합 탐지 (B19)      | `src/detection/score_aggregator.py` (확장, 9 tests)                  | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19c | 비정상 시간대 입력자 집중 (C12)   | `src/detection/anomaly_rules_simple.py` + `src/feature/time_features.py` (46 tests) | [03-feature](pre-plan/03-feature.md), [05-detection](pre-plan/05-detection.md) | ✅   |
| 19d | IC identifiers 불일치 수정       | `src/feature/pattern_features.py` — `["1150C","2050C"]` → `["1150","2050","4500","2700"]` | [03-feature](pre-plan/03-feature.md) §210 | ✅   |
| 19e | manual_source_codes 오매칭 수정  | `src/feature/pattern_features.py` — SA는 document_type, source 아님   | [03-feature](pre-plan/03-feature.md) §211 | ✅   |
| 19f | suspense_keywords 언어 불일치    | `src/feature/text_features.py` — DataSynth 영문 vs 현재 한국어 키워드 | [03-feature](pre-plan/03-feature.md) §212 | ✅   |
| 19g | B06 자기승인 정밀화             | automated 제외 + 소액(10M) 제외. 111K→1.5K (98.6% 감소)              | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 20  | DuckDB core                      | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py`       | [06-db](pre-plan/06-db.md)                | ✅   |
| 20a | DuckDB ML 확장 스키마 (Phase 2 대비 예약 선언만) | `src/db/schema.py` — 7컬럼 nullable 예약 + ml_model_metadata(PK, JSON) | [06-db](pre-plan/06-db.md) | ✅ |
| 20b | loader.py approval_level 파생    | `src/db/loader.py` — debit SUM + settings 동적 참조 + N level 캡     | [06-db](pre-plan/06-db.md)                | ✅   |
| 21  | 파이프라인 오케스트레이터        | `src/pipeline.py` — AuditPipeline(ingest→validate→feature→detection→db) | 05-detection + 06-db 통합              | ✅   |
| 22  | detection 단위테스트             | `tests/test_detection/` (120+ tests)                                 | 각 가이드 "테스트 전략" 섹션               | ✅   |
| 22a | DB 단위테스트                    | `tests/test_db/`                                                     | [06-db](pre-plan/06-db.md)                | ✅   |
| 22b | 파이프라인 E2E 통합테스트        | `tests/test_pipeline/` — 13개 pytest + DataSynth 1M행 E2E            | 05-detection + 06-db 통합                  | ✅   |
| 22c | Layer D 인프라 (Batch 1)         | `constants.py`, `settings.py`, `prior_data_loader.py`                | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |
| 22d | Layer D 룰+오케스트레이터 (Batch 2) | `variance_rules.py`, `variance_layer.py`, `__init__.py`           | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |
| 22e | Layer D 파이프라인 통합 (Batch 3) | `pipeline.py`, `context.py`, dashboard 호출부, 통합 테스트 8개       | [RULEBASE_UPDATE.md](RULEBASE_UPDATE.md)   | ✅   |

**완료 기준**: `AuditPipeline.run("datasynth.csv")` → 24개 룰 4레이어 + Layer D(기존회사) 탐지 → DuckDB 적재 → 프리셋 쿼리 정상 ✅

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

> DataSynth v21 확정 (Phase 1 Recall 91.4%, Normal 85.2%). 아래는 Phase 2 탐지 룰의 **선행 의존**.

| 태스크                             | 파일                                                              | 가이드                                                               | 상태 |
|------------------------------------|-------------------------------------------------------------------|----------------------------------------------------------------------|------|
| approval.rs 한국식 전결규정 적용   | `tools/datasynth/crates/*/approval.rs, je_generator.rs, user.rs`  | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| 증빙/컷오프/변경이력 컬럼 추가     | `tools/datasynth/crates/*/journal_entry.rs`                       | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| 전표번호 순차 생성                 | `tools/datasynth/crates/*/enhanced_orchestrator.rs` Phase 9a      | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| IP 주소 생성                       | `tools/datasynth/crates/*/je_generator.rs`                        | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| datasynth.yaml approval 섹션      | `config/datasynth.yaml`                                           | [DETECTION_RULES](DETECTION_RULES.md) §3.3                          | ✅   |
| SuspenseAccountAbuse keyword 주입 | GL 코드 탐지 정상 작동. 적요 의미 분석은 키워드 한계로 Phase 3 이관 (#71, #84, #88) | [03-feature](pre-plan/03-feature.md) §212, [DETECTION_RULES](DETECTION_RULES.md) §C10 | N/A  |
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
  │ Detector    │  │                        │    │ WU-09 (S) C01+Batch       │
  └──────┬──────┘  └───────────┬───────────┘    │ WU-10 (S) EUR+Holiday     │
         │                      │                │ WU-11 (S) Approval+Entropy│
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

### WU-01: SupervisedDetector `[L]` — #48

> **의존**: WU-00 ✅
> **역할**: 파이프라인 인프라 구축 (합성 데이터 순환 학습 한계로 실탐지 성능은 제한적)
> XGBoost/RF/LR/LGBM GridSearchCV 지도학습 탐지기
> **입력**: 18 피처 + 24 룰 결과 = 42차원. DataSynth GT 또는 pseudo-label 사용
> **불균형 처리**: XGB→scale_pos_weight, RF→class_weight="balanced", LGBM→is_unbalance=True
> **확장 경로**: 고객사별 실데이터 유입 시 fine-tuning으로 활성화 (Semi-supervised 인터페이스 포함)

| #   | 태스크                  | 파일                                                               | 가이드                                           | 상태 |
|-----|-------------------------|--------------------------------------------------------------------|--------------------------------------------------|------|
| 48  | SupervisedDetector      | `src/detection/supervised_detector.py` (신규)                      | [05a-detection-ml](pre-plan/05a-detection-ml.md) §164 | ⬜ |
|     | LightGBM 파이프라인 추가 | `src/preprocessing/pipeline_builder.py` (확장)                    | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ⬜ |
|     | SMOTE-ENN 선택적 적용    | train set only (data leakage 방지)                                 | [05a-detection-ml](pre-plan/05a-detection-ml.md) §200 | ⬜ |
|     | 단위 테스트              | `tests/test_detection/test_supervised_detector.py` (신규)          | 05a-detection-ml "테스트 전략"                   | ⬜   |

### WU-02: VAEDetector + IF 앙상블 `[M]` — #49

> **의존**: WU-00 ✅
> **역할**: 핵심 탐지기 — 비지도학습은 합성 데이터 적합도가 가장 높음 (순환 학습 문제 없음)
> VAE + Isolation Forest 비지도 앙상블 탐지기
> **실증 근거**: C09 recall=10% (1,039건 중 105건). 전수조사 결과 라벨 ~56%가 빈도 상위의 흔한 GL 조합.
> 통계 룰(하위 1%)로는 "흔하지만 도메인상 비정상"인 조합을 구조적으로 탐지 불가.
> VAE 잠재공간에서 정상 GL 조합 패턴을 학습하면 빈도와 무관하게 재구성 오차로 탐지 가능.
> **아키텍처**: Basic FC — Input(n)→Hidden(64)→Hidden(32)→Latent(8)→Hidden(32)→Hidden(64)→Output(n)
> **학습 데이터**: 검증모드=is_fraud=False only, 실전모드=전체(contamination tolerance <2%)
> **참고**: BiLSTM+Attention은 D032에 따라 WU-01c에서 독립 탐지기로 구현 (VAE 교체 아닌 병렬 운용)

| #   | 태스크                  | 파일                                                               | 가이드                                           | 상태 |
|-----|-------------------------|--------------------------------------------------------------------|--------------------------------------------------|------|
| 49  | VAEDetector + IF 앙상블  | `src/detection/vae_detector.py` (신규)                             | [05a-detection-ml](pre-plan/05a-detection-ml.md) §236 | ⬜ |
|     | t-SNE/UMAP 잠재공간 시각화 | 학습 후 latent space 품질 검증 유틸리티                           | [05a-detection-ml](pre-plan/05a-detection-ml.md) §450 | ⬜ |
|     | 단위 테스트              | `tests/test_detection/test_vae_detector.py` (신규)                 | 05a-detection-ml "테스트 전략"                   | ⬜   |

### WU-01b: FT-Transformer Tabular 탐지기 `[M]` — D033

> **의존**: WU-02 (VAE 래퍼 패턴 재사용)
> FT-Transformer: 모든 피처를 토큰화 → self-attention으로 피처 간 상호작용 학습
> **아키텍처**: 42 features → Feature Tokenizer(64-dim) + [CLS] → Transformer Encoder(2L, 4H, d=64, ff=128) → FC(64→2)
> **VRAM**: ~300MB (batch=256). RTX 3070 Ti 8GB 여유 충분
> **핵심 이점**: 24개 룰 결과 간 조합 패턴을 attention이 자동 학습 (수동 B19 Top-side 룰의 학습 버전)

| #    | 태스크                       | 파일                                                          | 가이드                                           | 상태 |
|------|------------------------------|---------------------------------------------------------------|--------------------------------------------------|------|
| 49b  | FT-Transformer PyTorch 모듈  | `src/preprocessing/ft_model.py` (신규)                        | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ⬜   |
|      | FT-Transformer sklearn 래퍼  | `src/preprocessing/ft_wrapper.py` (신규)                      | vae_wrapper.py 패턴 동일                         | ⬜   |
|      | TransformerDetector          | `src/detection/tabular_transformer.py` (신규)                 | BaseDetector 계약 준수                           | ⬜   |
|      | pipeline_builder 확장        | `src/preprocessing/pipeline_builder.py` — build_ft_pipeline() | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ⬜ |
|      | 단위 테스트                   | `tests/test_detection/test_tabular_transformer.py` (신규)     | 05a-detection-ml "테스트 전략"                   | ⬜   |

### WU-01c: BiLSTM + Attention 시퀀스 탐지기 `[M]` — D032

> **의존**: WU-01b (래퍼 패턴 확립 후)
> 사용자-시간 윈도우 기반 시퀀스 탐지. ISA 240 "경영진 override" 반복 패턴 포착
> **시퀀스 구성**: `created_by` 그룹 → `posting_date` 정렬 → seq_len=16 슬라이딩 윈도우(stride=1)
> **아키텍처**: BiLSTM(hidden=64, bidir) → Additive Attention → FC(128→64→2). VRAM ~100MB
> **sklearn 통합**: 외부 2D API 유지, 내부에서 sequence_builder로 3D 변환

| #    | 태스크                       | 파일                                                         | 가이드                                           | 상태 |
|------|------------------------------|--------------------------------------------------------------|--------------------------------------------------|------|
| 49c  | 시퀀스 빌더 (2D→3D 윈도우)   | `src/preprocessing/sequence_builder.py` (신규)               | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ⬜   |
|      | BiLSTM+Attention PyTorch 모듈 | `src/preprocessing/bilstm_model.py` (신규)                   | [05a-detection-ml](pre-plan/05a-detection-ml.md) | ⬜   |
|      | BiLSTM sklearn 래퍼          | `src/preprocessing/bilstm_wrapper.py` (신규)                 | vae_wrapper.py 패턴 동일                         | ⬜   |
|      | SequenceDetector             | `src/detection/sequence_detector.py` (신규)                  | BaseDetector 계약 준수                           | ⬜   |
|      | 단위 테스트                   | `tests/test_detection/test_sequence_detector.py` (신규)      | 05a-detection-ml "테스트 전략"                   | ⬜   |

### WU-03: Stacking Meta-Learner 앙상블 `[M]` — #50, D034

> **의존**: WU-01 + WU-02 + WU-01b + WU-01c + WU-05
> 기존 고정 가중합(D024) → Stacking meta-learner(LR Ridge)로 대체
> **Level 0**: 6개 base model (룰 24개, XGBoost, VAE, IF, BiLSTM, FT-Transformer)
> **Level 1**: Logistic Regression (L2) — 6개 확률값 → 최종 anomaly_score
> **Leakage 방지**: 5-fold out-of-fold prediction 프로토콜
> **Fallback**: 라벨 부족 시 기존 Percentile Ranking 가중합으로 폴백

| #   | 태스크                         | 파일                                                          | 가이드                                              | 상태 |
|-----|--------------------------------|---------------------------------------------------------------|-----------------------------------------------------|------|
| 50  | StackingEnsemble sklearn 래퍼  | `src/preprocessing/stacking.py` (신규)                        | [05a-detection-ml](pre-plan/05a-detection-ml.md)    | ⬜   |
|     | EnsembleDetector               | `src/detection/ensemble_detector.py` (신규)                   | BaseDetector 계약 준수                              | ⬜   |
|     | score_aggregator stacking 확장 | `src/detection/score_aggregator.py`, `constants.py`           | [05-detection](pre-plan/05-detection.md) + 05a      | ⬜   |
|     | Percentile Ranking 정규화      | 가중합 전 스케일 통일 (fallback 모드)                          | [05a-detection-ml](pre-plan/05a-detection-ml.md)    | ⬜   |
|     | 단위 테스트                     | `tests/test_detection/test_ensemble_detector.py` (신규)       | 05a-detection-ml "테스트 전략"                      | ⬜   |

### WU-04: Pipeline 통합 + ML 통합 테스트 `[M]` — #53

> **의존**: WU-03
> pipeline.py에 ML 탐지기 연결 + E2E 테스트

| #   | 태스크                         | 파일                                                    | 가이드                                | 상태 |
|-----|--------------------------------|---------------------------------------------------------|-----------------------------------------|------|
| 53  | ML Pipeline 통합               | `src/pipeline.py`, `config/settings.py`                 | 05-detection + 06-db 통합              | ⬜   |
|     | ML 통합 테스트                  | `tests/test_detection/test_ml_integration.py` (신규)     | 05a-detection-ml "테스트 전략"        | ⬜   |
|     | Hold-out fraud type 검증        | test set에서 미지 유형 2종 VAE 탐지율 검증               | [05a-detection-ml](pre-plan/05a-detection-ml.md) §450 | ⬜ |
|     | Feature perturbation 강건성 테스트 | 노이즈 주입 후 VAE 반응 검증                           | [05a-detection-ml](pre-plan/05a-detection-ml.md) §450 | ⬜ |
|     | 피처 병렬 실행 옵션             | `src/feature/engine.py` — concurrent.futures 스레드풀    | [03-feature](pre-plan/03-feature.md) §Engine | ⬜ |

### WU-05: DuplicateDetector `[M]` — #58

> **의존**: WU-00 ✅
> Exact + Fuzzy 중복 전표 탐지
> **실증 근거**: B05 recall=9% (134건 중 12건). 샘플 20건 중 18건(90%)이 exact match 쌍 부재.
> 실무에서도 유사 금액 중복(100만→99.8만), 분할 거래(100만→50만+50만), 시차 중복을 잡으려면
> fuzzy matching + 금액 합산 분석 + embedding similarity 필요.

| #   | 태스크           | 파일                                              | 가이드                                   | 상태 |
|-----|------------------|---------------------------------------------------|------------------------------------------|------|
| 58  | DuplicateDetector | `src/detection/duplicate_detector.py` (신규)      | [05-detection](pre-plan/05-detection.md) | ⬜   |
|     | 단위 테스트       | `tests/test_detection/test_duplicate_detector.py` (신규) | 05-detection "테스트 전략"          | ⬜   |

### WU-06: 시계열 Rule-Based `[S]` — #59

> **의존**: WU-00 ✅
> TransactionBurst + UnusualFrequency

| #   | 태스크                 | 파일                                          | 가이드                                   | 상태 |
|-----|------------------------|-----------------------------------------------|------------------------------------------|------|
| 59  | 시계열 Rule-Based      | `src/detection/timeseries_rule.py` (신규)     | [05-detection](pre-plan/05-detection.md) | ⬜   |
|     | 단위 테스트             | `tests/test_detection/test_timeseries_rule.py` (신규) | 05-detection "테스트 전략"          | ⬜   |

### WU-07: 내부거래 매칭 `[M]` — #60, #60c

> **의존**: WU-00 ✅
> IC 전표 대응 거래 매칭 + UnmatchedIntercompany

| #   | 태스크                      | 파일                                                | 가이드                                   | 상태 |
|-----|-----------------------------|-----------------------------------------------------|------------------------------------------|------|
| 60  | 내부거래 매칭               | `src/detection/intercompany_matcher.py` (신규)      | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 60c | UnmatchedIntercompany       | (위 파일 내 포함)                                    | [05-detection](pre-plan/05-detection.md) | ⬜   |
|     | 단위 테스트                  | `tests/test_detection/test_intercompany_matcher.py` (신규) | 05-detection "테스트 전략"          | ⬜   |

### WU-08: Relational 탐지기 `[M]` — #60a, #60b, #60d, #60e

> **의존**: WU-00 ✅
> NewCounterparty / DormantAccount / TransferPricing / MissingRelationship

| #   | 태스크                     | 파일                                             | 가이드                                   | 상태 |
|-----|----------------------------|--------------------------------------------------|------------------------------------------|------|
| 60a | NewCounterparty            | `src/detection/relational_detector.py` (신규)    | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 60b | DormantAccountActivity     | (위 파일 내 포함)                                 | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 60d | TransferPricingAnomaly     | (위 파일 내 포함)                                 | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 60e | MissingRelationship        | (위 파일 내 포함)                                 | [05-detection](pre-plan/05-detection.md) | ⬜   |
|     | 단위 테스트                 | `tests/test_detection/test_relational_detector.py` (신규) | 05-detection "테스트 전략"          | ⬜   |

### WU-09: C01 Q3 확장 + 배치 패턴 + 경고 하드코딩 제거 `[S]` — #56, #57

> **의존**: 없음 (기존 모듈 개선)

| #   | 태스크                              | 파일                                        | 가이드                                                       | 상태 |
|-----|-------------------------------------|---------------------------------------------|--------------------------------------------------------------|------|
| 57  | C01 계정그룹별 Q3 확장              | `src/detection/anomaly_rules_simple.py`     | [05-detection](pre-plan/05-detection.md) §185                | ⬜   |
| 56  | 배치 전표 이상 패턴                 | `src/detection/anomaly_layer.py` (확장)     | [05a-detection-ml](pre-plan/05a-detection-ml.md) §배치 전표  | ⬜   |
|     | `_generate_warnings` 하드코딩 제거  | `src/detection/` — "A02 rule" 문자열 → `constants.py` 참조 | [05-detection](pre-plan/05-detection.md) §1293 | ⬜ |

### WU-10: 유럽 금액 포맷 + 한국 공휴일 + 외화 소수점 `[S]` — #61, #62

> **의존**: 없음. 패키지 추가: `holidays`

| #   | 태스크                          | 파일                                        | 가이드                                                | 상태 |
|-----|---------------------------------|---------------------------------------------|-------------------------------------------------------|------|
| 61  | 유럽 금액 포맷 지원             | `config/cleaning.yaml` + `src/ingest/type_caster.py` | [02-ingest](pre-plan/02-ingest.md) §374      | ⬜   |
| 62  | 한국 공휴일 연동                | `src/feature/time_features.py`              | [04-validation](pre-plan/04-validation.md) §128      | ⬜   |
|     | 외화 소수점 처리 (is_round_number) | `src/feature/amount_features.py`          | [03-feature](pre-plan/03-feature.md) §537            | ⬜   |
|     | currency_decimals YAML 설정     | `config/audit_rules.yaml` — KRW:0, USD:2, EUR:2, JPY:0 | [03-feature](pre-plan/03-feature.md) §537 | ⬜ |

### WU-11: 다단계 승인한도 + 피처 고도화 `[M]` — #63, #65

> **의존**: 없음
> pre-plan 03-feature에서 이관된 Phase 2 피처 개선 항목 포함

| #   | 태스크                             | 파일                                | 가이드                                          | 상태 |
|-----|------------------------------------|-------------------------------------|-------------------------------------------------|------|
| 63  | approval_threshold 6단계           | `src/feature/amount_features.py`    | [03-feature](pre-plan/03-feature.md) §154      | ⬜   |
| 65  | description_quality 3단계 고도화   | `src/feature/text_features.py` — regex패턴 + TTR(어휘다양성) + Shannon entropy | [03-feature](pre-plan/03-feature.md) §541-601 | ⬜ |
|     | Z-score CoA 상위계정 fallback      | `src/feature/amount_features.py` — n<30 소그룹 → 자산/부채/수익/비용 상위그룹 | [03-feature](pre-plan/03-feature.md) §536 | ⬜ |
|     | is_suspense_account 대상 컬럼 확장 | `src/feature/pattern_features.py` — `gl_account_name` 추가 | [03-feature](pre-plan/03-feature.md) §538 | ⬜ |

### WU-12: DuckDB ALTER TABLE 마이그레이션 `[S]` — #64

> **의존**: WU-03 (ML 컬럼 확정 후)

| #   | 태스크                        | 파일                          | 가이드                                 | 상태 |
|-----|-------------------------------|-------------------------------|----------------------------------------|------|
| 64  | DuckDB ALTER TABLE (ML 컬럼)  | `src/db/schema.py`           | [06-db](pre-plan/06-db.md) §580      | ⬜   |

### WU-13: 재무제표-장부 대사 `[M]` — #55

> **의존**: 없음

| #   | 태스크                    | 파일                                                              | 가이드                                                         | 상태 |
|-----|---------------------------|-------------------------------------------------------------------|----------------------------------------------------------------|------|
| 55  | TB 교차검증               | `src/validation/tb_reconciliation.py` (신규)                      | [04-validation](pre-plan/04-validation.md) §재무제표-장부 대사 | ⬜   |
|     | Trial Balance DuckDB 테이블 DDL | `src/db/schema.py` — PK(batch_id, account_code, fiscal_period) | [06-db](pre-plan/06-db.md) §1238                              | ⬜   |
|     | 단위 테스트                | `tests/test_validation/test_tb_reconciliation.py` (신규)          | 04-validation "테스트 전략"                                    | ⬜   |

### WU-14: 증빙/컷오프/금액 탐지 `[M]` — #41, #42, #43

> 🚫 **BLOCKER**: DataSynth Rust 확장 완료 후 (증빙/컷오프 컬럼)

| #   | 태스크                          | 파일                                       | 가이드                                     | 상태 |
|-----|---------------------------------|--------------------------------------------|--------------------------------------------|------|
| 41  | 증빙 존재 확인 + 적격증빙       | `src/detection/evidence_rules.py` (신규)   | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |
| 42  | 컷오프 검증 (납품일 vs 전기일)  | (위 파일 내 포함)                           | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |
| 43  | 증빙 금액 불일치 + 부가세 검증  | (위 파일 내 포함)                           | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |

### WU-15: 수정이력/IP/전표번호/승인 탐지 `[M]` — #44, #45, #46, #47

> 🚫 **BLOCKER**: DataSynth Rust 확장 완료 후 (이력/IP/순번 컬럼)

| #   | 태스크                 | 파일                                            | 가이드                                     | 상태 |
|-----|------------------------|-------------------------------------------------|--------------------------------------------|------|
| 44  | 전표 수정 이력 탐지    | `src/detection/access_audit_rules.py` (신규)    | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |
| 45  | IP 비정상 접근 탐지    | (위 파일 내 포함)                                | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |
| 46  | 전표번호 연속성 갭     | (위 파일 내 포함)                                | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |
| 47  | 승인 프로세스·TOE 검증 | (위 파일 내 포함)                                | [DETECTION_RULES](DETECTION_RULES.md) §3.3 | ⬜   |

### WU-16: TrendBreak ML `[L]` — #54

> 🚫 **BLOCKER**: DataSynth 다기간(2~3개년) 데이터 생성 완료 후

| #   | 태스크                     | 파일                                          | 가이드                                                                              | 상태 |
|-----|----------------------------|-----------------------------------------------|--------------------------------------------------------------------------------------|------|
| 54  | TrendBreak (회계추정치 편의) | `src/detection/timeseries_detector.py` (신규) | [05a-detection-ml](pre-plan/05a-detection-ml.md) §TrendBreak                        | ⬜   |

### WU-17: SHAP 시각화 + ML 툴팁 `[M]` — #52, #66

> 🚫 **BLOCKER**: ~~Phase 1c 대시보드~~ ✅ + WU-01 완료 후

| #   | 태스크                    | 파일                                            | 가이드                                        | 상태 |
|-----|---------------------------|-------------------------------------------------|-----------------------------------------------|------|
| 52  | SHAP 시각화               | `dashboard/tab_explorer.py` (확장)              | [07-dashboard](pre-plan/07-dashboard.md)      | ⬜   |
| 66  | ML 지표 설명 (툴팁)       | `dashboard/components/ml_tooltips.py` (신규)    | [07-dashboard](pre-plan/07-dashboard.md) §607 | ⬜   |

### 추천 실행 순서 (Sprint 단위)

| Sprint | Work Unit                              | 복잡도       | 비고                              |
|--------|----------------------------------------|--------------|-----------------------------------|
| **1**  | WU-00                                  | S            | ✅ 완료                           |
| **2**  | WU-01, WU-05, WU-06, WU-09, WU-10     | L+M+S+S+S   | 크리티컬패스 + 병렬 4건           |
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
> | B05  |     9% |  134 |  12 | exact match만 → 유사 금액·분할 거래 미탐            | DuplicateDetector (fuzzy+split+embedding) | 2 (WU-05) |
> | B10  |     7% |  643 |  48 | 2-hop만, 640건 trading_partner NULL, cycle 0건      | GraphDetector DFS/BFS N-hop         | 3 (#72) |
> | C09  |    10% | 1039 | 105 | 빈도 기반만 → 흔하지만 도메인상 이상한 조합 미탐(~56%) | VAE/GNN 잠재공간 학습               | 2 (WU-02) |
> | C07  |    34% |  154 |  53 | 행 단위 탐지 vs 문서 단위 라벨 기준 불일치           | 문서 단위 집계 로직 개선 (Phase 2)  | 2 (WU-09) |
>
> B05/C09는 "규칙으로 정의할 수 없는 패턴"이므로 ML 필수.
> B10은 그래프 알고리즘 필수. C07은 집계 단위 통일로 개선 가능.

---

## Phase 3: NLQ + Graph + Polish (NLP·그래프 5개 유형 + LLM + 내보내기)

> **pre-plan 참조**: Phase 3 착수 시 확인할 교차 참조
> - `08-llm.md` §590-622 (Phase 1a에서 이관된 미해결 이슈 5건: header-account mismatch, process-account mismatch, vague descriptions, IC anomalies, synonym bypass)
> - `08-llm.md` §711-736 (감사기준서 갭 분석 3건: 경제적 실질, 유의적 거래, 이전가격)
> - `03-feature.md` §759 (text_features semantic stub → Ollama 임베딩 연동)
> - `01-project-setup.md` §84 (LLM 설정 필드 활성화: ollama_model, ollama_base_url)
> - `03a-preprocessing.md` §119 (VRAM 순차 실행: LLM + VAE 동시 사용 방지)
> - C10 SuspenseAccount 적요 탐지: 키워드 매칭 한계(우회 표현·동의어·은어)로 Phase 3 이관 → #71 + #84 + #88로 해결

| #   | 태스크                              | 파일                                          | 가이드                                                     | 상태 |
|-----|-------------------------------------|-----------------------------------------------|------------------------------------------------------------|------|
| 67  | Ollama 클라이언트                   | `src/llm/ollama_client.py`                    | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 68  | Vanna Text-to-SQL                   | `src/llm/text_to_sql.py`                     | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 69  | SQL 검증                            | `src/llm/sql_validator.py`                    | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 70  | 감사 프리셋 6종                     | `src/llm/prompt_presets.py`                   | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 71  | 적요 NLP                            | `src/detection/nlp_analyzer.py`               | [05-detection](pre-plan/05-detection.md)                   | ⬜   |
| 72  | 그래프 순환 탐지                    | `src/detection/graph_detector.py` — CircularTransaction + CentralityAnomaly (Relational 2유형). **실증(v7)**: B10 recall=7% (643건 중 48건), 640건 trading_partner NULL, cycle 0건 → N-hop DFS/BFS 필수 | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 73  | Chat UI 탭                          | `dashboard/tab_chat.py`                       | [07-dashboard](pre-plan/07-dashboard.md)                   | ⬜   |
| 74  | Export 탭                           | `dashboard/tab_export.py`                     | [07-dashboard](pre-plan/07-dashboard.md)                   | ⬜   |
| 75  | 감사조서 Excel/PDF                  | `src/export/`                                 | [09-export](pre-plan/09-export.md)                         | ⬜   |
| 76  | audit_trail 테이블 DDL              | `src/db/schema.py` — audit_trail 테이블 추가  | [09-export](pre-plan/09-export.md) §31                     | ⬜   |
| 77  | Audit Trail 기록기                  | `src/export/audit_trail.py`                   | [09-export](pre-plan/09-export.md)                         | ⬜   |
| 78  | 인사이트 생성                       | `src/llm/insight_generator.py`                | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 79  | 경제적 실질 판단 (NLP)              | `src/detection/nlp_analyzer.py` (확장)        | [08-llm](pre-plan/08-llm.md) §경제적 실질                  | ⬜   |
| 80  | 유의적 거래 합리성 평가 (LLM)       | `src/llm/insight_generator.py` (확장)         | [08-llm](pre-plan/08-llm.md) §유의적 거래                  | ⬜   |
| 81  | TransferPricingAnomaly (이전가격)    | `src/detection/graph_detector.py` (확장)      | [DETECTION_RULES](DETECTION_RULES.md) §4.4                 | ⬜   |
| 82  | LLM 기반 헤더 탐지 고도화           | `src/ingest/header_detector.py` (확장)        | [02-ingest](pre-plan/02-ingest.md) §848                    | ⬜   |
| 83  | LLM 전처리 제안 모듈                | `src/llm/` — EDAProfile → 전처리 전략 추천    | [03a-preprocessing](pre-plan/03a-preprocessing.md) §47     | ⬜   |
| 84  | kiwipiepy 형태소 분석               | `src/feature/text_features.py` (확장)         | [03-feature](pre-plan/03-feature.md) §287                  | ⬜   |
| 85  | LLM 계정명 의미 분석                | `src/feature/text_features.py` (확장)         | [03-feature](pre-plan/03-feature.md) §423                  | ⬜   |
| 86  | XAI Narrative Report                | `src/llm/` — 위험 설명 자동 생성              | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
| 87  | 감사규칙 피드백 루프                | `src/llm/` — audit_rules.yaml 자동 개선 제안  | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
| 88  | semantic_similarity (임베딩)        | `src/llm/` — Ollama 임베딩 동의어 매칭        | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
