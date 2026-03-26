# Phase별 태스크

> 각 태스크의 상세 구현 가이드는 `docs/pre-plan/` 참조
> pre-plan 번호(00~10)는 **도메인 분류**이며, 구현 순서는 **Phase 번호**를 따른다.
> 예: `05a-detection-ml.md`는 Phase 2b의 설계 레퍼런스이지, 05 다음에 바로 구현하는 것이 아님.

## 진행 현황 요약

| Phase              | 완료 | 전체 | 진행률 |
|--------------------|------|------|--------|
| 1a 데이터 파이프라인 | 20   | 20   | 100%   |
| 1b 이상탐지+DB       |  8   | 18   |  44%   |
| 1c 대시보드           |  0   | 12   |   0%   |
| 2a ML 전처리          | 10   | 10   | 100%   |
| 2a-ext 신규탐지       |  0   |  7   |   0%   |
| 2b ML 탐지기          |  1   | 10   |  10%   |
| 2c 추가 탐지기        |  0   |  3   |   0%   |
| 2-ext 확장            |  0   |  6   |   0%   |
| 3 NLQ+Graph+Polish    |  0   | 22   |   0%   |
| **합계**              | 39   | 98   |  40%   |

**상태 범례**: ✅ 완료 / ⬜ 미착수
**블로커**: Phase 섹션 상단 blockquote로 표기 (🚫 BLOCKER)
**번호 미부여**: 문서 보완 (1건) + DataSynth 확장 (8건) = 9건은 Phase 간 보조 작업으로 요약표 집계에서 제외

---

## Phase 1: MVP (Python Only 파이프라인 + 기본 UI)

### Phase 1a: 데이터 파이프라인

| #   | 태스크              | 파일                                                            | 가이드                                             | 상태 |
|-----|---------------------|-----------------------------------------------------------------|---------------------------------------------------|------|
| 0   | 데이터셋 수집·선정  | `data/journal/`, 32개 검토                                      | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 0a  | DataSynth 빌드      | `tools/datasynth/` (Rust, EY-ASU)                               | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 0b  | 메인 데이터 생성    | `data/journal/primary/datasynth/` (1,106K건)                    | [00-dataset](pre-plan/00-dataset.md)              | ✅   |
| 1   | 프로젝트 초기화     | `pyproject.toml`, `.gitignore`, `.env.example`                  | [01-project-setup](pre-plan/01-project-setup.md)  | ✅   |
| 2   | 설정 레이어         | `config/settings.py`, YAML 3종 + `datasynth.yaml`              | [01-project-setup](pre-plan/01-project-setup.md)  | ✅   |
| 3   | 샘플 데이터 생성기  | DataSynth로 대체 (10-sample-data 불필요)                        | -                                                 | ✅   |
| 4   | 수동 Excel 템플릿   | DataSynth CSV로 대체                                            | -                                                 | ✅   |
| 5   | 파일 검증           | `src/ingest/file_validator.py`                                  | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 6   | Excel 읽기          | `src/ingest/excel_reader.py`                                    | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 7   | 헤더 탐지           | `src/ingest/header_detector.py`                                 | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 8   | 컬럼 매핑           | `src/ingest/column_mapper.py`                                   | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 9   | 타입 캐스팅         | `src/ingest/type_caster.py`                                     | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 10  | 매핑 프로파일       | `src/ingest/mapping_profile.py`                                 | [02-ingest](pre-plan/02-ingest.md)                | ✅   |
| 10a | **UX 1단계**        | 구조적 헤더탐지 + 타입검증 + ReviewItem + Null분기 + latin-1 폴백 | [02-ingest](pre-plan/02-ingest.md)               | ✅   |
| 10b | **피드백 반영**     | 인코딩 오버라이드+confidence, 시트 스코어링, 금액 퀵픽스, Phase 1c UI 스펙 | [02-ingest](pre-plan/02-ingest.md)      | ✅   |
| 11  | 피처 엔진           | `src/feature/engine.py` + 4개 서브모듈 (170 tests passed)       | [03-feature](pre-plan/03-feature.md)              | ✅   |
| 11a | **UX 3단계 — EDA**  | `src/eda/` 7개 모듈 (52 tests passed)                           | [03a-preprocessing](pre-plan/03a-preprocessing.md)| ✅   |
| 12  | L1~L2 검증          | `src/validation/schema_validator.py`, `accounting_validator.py`  | [04-validation](pre-plan/04-validation.md)        | ✅   |
| 13  | 전처리 리포트       | `src/validation/report_generator.py` (17 tests passed)          | [04-validation](pre-plan/04-validation.md)        | ✅   |
| 14  | 단위 테스트 (1a)    | `tests/test_ingest/`, `test_feature/`                           | 각 가이드 "테스트 전략" 섹션                       | ✅   |

**완료 기준**: DataSynth CSV → ingest → feature → validation 파이프라인 통과

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
| 19  | 점수 집계                        | `src/detection/score_aggregator.py` (3레이어+Benford, 12 tests)      | [05-detection](pre-plan/05-detection.md)   | ✅   |
| 19a | 역분개 패턴 탐지 (1:1 + N:M)    | `src/detection/anomaly_layer.py` (확장)                              | [05-detection](pre-plan/05-detection.md)   | ⬜   |
| 19b | Top-side JE 조합 탐지            | `src/detection/score_aggregator.py` (확장)                           | [05-detection](pre-plan/05-detection.md)   | ⬜   |
| 19c | 비정상 시간대 입력자 집중         | `src/feature/time_features.py` (확장)                                | [03-feature](pre-plan/03-feature.md)       | ⬜   |
| 19d | IC identifiers 불일치 수정       | `src/feature/pattern_features.py` — `["1150C","2050C"]` → `["1150","2050","4500","2700"]` | [03-feature](pre-plan/03-feature.md) §210 | ⬜   |
| 19e | manual_source_codes 오매칭 수정  | `src/feature/pattern_features.py` — SA는 document_type, source 아님   | [03-feature](pre-plan/03-feature.md) §211 | ⬜   |
| 19f | suspense_keywords 언어 불일치    | `src/feature/text_features.py` — DataSynth 영문 vs 현재 한국어 키워드 | [03-feature](pre-plan/03-feature.md) §212 | ⬜   |
| 20  | DuckDB core                      | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py`       | [06-db](pre-plan/06-db.md)                | ✅   |
| 20a | DuckDB ML 확장 스키마 (Phase 2 대비 예약 선언만) | `src/db/schema.py` — supervised/unsupervised_score nullable 예약 | [06-db](pre-plan/06-db.md) | ⬜ |
| 20b | loader.py approval_level 파생    | `src/db/loader.py` — CASE WHEN 전결규정 6단계                        | [06-db](pre-plan/06-db.md)                | ⬜   |
| 21  | 파이프라인 오케스트레이터        | `src/pipeline.py`                                                    | 05-detection + 06-db 통합                  | ⬜   |
| 22  | detection 단위테스트             | `tests/test_detection/` (120+ tests)                                 | 각 가이드 "테스트 전략" 섹션               | ✅   |
| 22a | DB 단위테스트                    | `tests/test_db/`                                                     | [06-db](pre-plan/06-db.md)                | ✅   |
| 22b | 파이프라인 E2E 통합테스트        | `tests/` — ingest→feature→validation→detection→DB 전체 흐름           | 05-detection + 06-db 통합                  | ⬜   |

**완료 기준**: `AuditPipeline.run("datasynth.csv")` → 24개 룰 3레이어 탐지 → DuckDB 적재 → 프리셋 쿼리 정상

### Phase 1c: 대시보드

> **pre-plan 참조**: Phase 1c 착수 시 아래 문서의 "미해결 이슈" 섹션 반드시 확인
> - `02-ingest.md` §882-896 (ingest 미해결 7건 → dashboard UI로 해결)
> - `07-dashboard.md` §580-599 (dashboard 미해결 15건)
> - `ux-flow.md` UX Stage 2~3 (룰 패널 + EDA 시각화)
> - `02-ingest.md` §36, §41 (인제스트 오케스트레이터 + IngestResult 인터페이스)
> - `02-ingest.md` §271 (3-tier 매핑 확인 UI: auto/review/blocked)

| #   | 태스크                     | 파일                                         | 가이드                                     | 상태 |
|-----|----------------------------|----------------------------------------------|--------------------------------------------|------|
| 23  | UI 컴포넌트                | `dashboard/components/`                      | [07-dashboard](pre-plan/07-dashboard.md)   | ⬜   |
| 24  | Tab 1: Summary             | `dashboard/tab_summary.py`                   | [07-dashboard](pre-plan/07-dashboard.md)   | ⬜   |
| 25  | Tab 2: Benford             | `dashboard/tab_benford.py`                   | [07-dashboard](pre-plan/07-dashboard.md)   | ⬜   |
| 26  | Tab 3: Explorer            | `dashboard/tab_explorer.py`                  | [07-dashboard](pre-plan/07-dashboard.md)   | ⬜   |
| 27  | 메인 앱                    | `dashboard/app.py`                           | [07-dashboard](pre-plan/07-dashboard.md)   | ⬜   |
| 28  | 임계값 튜닝 슬라이더       | `dashboard/components/threshold_sidebar.py`  | [ux-flow §4A](pre-plan/ux-flow.md)        | ⬜   |
| 29  | 프리셋 드롭다운            | `dashboard/components/preset_selector.py`    | [ux-flow §4C](pre-plan/ux-flow.md)        | ⬜   |
| 30  | HITL 예외 처리 (whitelist) | `src/db/schema.py` + `tab_explorer.py`       | [ux-flow §4B](pre-plan/ux-flow.md)        | ⬜   |
| 30a | EDA 시각화 탭              | `dashboard/tab_eda.py` — `src/eda/` 프로파일링 결과 시각화 | [03a-preprocessing](pre-plan/03a-preprocessing.md), [ux-flow](pre-plan/ux-flow.md) UX Stage 3 | ⬜ |
| 30b | 룰 컨트롤 패널 UI         | `dashboard/components/rule_panel.py` — 감사규칙 가중치/임계값 조정 | [ux-flow](pre-plan/ux-flow.md) UX Stage 2 §④ | ⬜ |
| 30c | 인제스트 오케스트레이터    | `src/pipeline.py` 또는 `dashboard/` — `run_ingest_pipeline()` 단일 진입점 + 매핑 확인 UI | [02-ingest](pre-plan/02-ingest.md) §36 | ⬜ |
| 30d | 미해결 이슈 UI 반영       | ReviewItem UI, 매핑 프로파일 학습, multi-sheet 선택 등 15건 | [07-dashboard](pre-plan/07-dashboard.md) §580-599 | ⬜ |

**완료 기준**: `streamlit run dashboard/app.py` → 3탭 정상 렌더링 + 슬라이더 변경 시 탐지 결과 갱신 + 프리셋 전환 + 예외 처리 저장/제외

---

### 문서 보완: AUDIT_DOMAIN_FINAL 기준서 매핑 완성

> `audit_domain_additional.md` §3 "문서 보완 14건" 기반. 코드 변경 없음, 문서만 수정.

| 태스크                                                                  | 파일                          | 가이드                                                   | 상태 |
|-------------------------------------------------------------------------|-------------------------------|----------------------------------------------------------|------|
| AUDIT_DOMAIN_FINAL 기준서 매핑 추가 (5건) + 참조 출처 (8건) + 범위 섹션 (1건) | `docs/AUDIT_DOMAIN_FINAL.md` | [audit_domain_additional](audit_domain_additional.md) §3 | ⬜   |

---

### Phase 2 준비: DataSynth 확장 (한국 실무 맞춤 컬럼 추가)

> DataSynth Rust 코드 수정 + YAML 설정 추가. Phase 2 탐지 룰의 **선행 의존**.

| 태스크                             | 파일                                                              | 가이드                                                               | 상태 |
|------------------------------------|-------------------------------------------------------------------|----------------------------------------------------------------------|------|
| approval.rs 한국식 전결규정 적용   | `tools/datasynth/crates/*/approval.rs, je_generator.rs, user.rs`  | [audit_domain_additional](audit_domain_additional.md) §4-4           | ✅   |
| 증빙/컷오프/변경이력 컬럼 추가     | `tools/datasynth/crates/*/journal_entry.rs`                       | [audit_domain_additional](audit_domain_additional.md) §2-1,2-4,4-1   | ⬜   |
| 전표번호 순차 생성                 | `tools/datasynth/crates/*/je_generator.rs`                        | [audit_domain_additional](audit_domain_additional.md) §2-2           | ⬜   |
| IP 주소 생성                       | `tools/datasynth/crates/*/je_generator.rs`                        | [audit_domain_additional](audit_domain_additional.md) §4-2           | ⬜   |
| datasynth.yaml approval 섹션      | `config/datasynth.yaml`                                           | [audit_domain_additional](audit_domain_additional.md) §4-4           | ✅   |
| SuspenseAccountAbuse keyword 주입 | `tools/datasynth/` — 적요에 ~30% keyword 삽입                     | [03-feature](pre-plan/03-feature.md) §212                            | ⬜   |
| Round number clamping 검증        | `tools/datasynth/` — 라운드 넘버 클램핑 로직 확인                  | [03-feature](pre-plan/03-feature.md) §154                            | ⬜   |
| 데이터 재생성 + 파이프라인 호환 확인 | `data/journal/primary/datasynth/`                                | 신규 컬럼 포함 데이터로 기존 파이프라인 호환 확인                     | ⬜   |

---

## Phase 2: Core AI (ML 모델 + 추가 탐지 유형)

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

### Phase 2a 확장: 신규 컬럼 탐지 룰 (DataSynth 확장 컬럼 활용)

> [audit_domain_additional.md](audit_domain_additional.md) 기반. DataSynth 확장 완료 후 구현 가능.

| #   | 태스크                            | 파일                                          | 가이드                                                     | 상태 |
|-----|-----------------------------------|-----------------------------------------------|------------------------------------------------------------|------|
| 41  | 증빙 존재 확인 + 적격증빙 미수취  | `src/detection/` (신규 또는 fraud_layer 확장)  | [audit_domain_additional](audit_domain_additional.md) §2-1 | ⬜   |
| 42  | 컷오프 검증 (납품일 vs 전기일)    | `src/detection/` (신규 또는 anomaly_layer 확장)| [audit_domain_additional](audit_domain_additional.md) §2-4 | ⬜   |
| 43  | 증빙 금액 불일치 + 부가세 검증    | `src/detection/` (신규 또는 anomaly_layer 확장)| [audit_domain_additional](audit_domain_additional.md) §2-5 | ⬜   |
| 44  | 전표 수정 이력 탐지               | `src/detection/` (신규)                        | [audit_domain_additional](audit_domain_additional.md) §4-1 | ⬜   |
| 45  | IP 주소 비정상 접근 탐지          | `src/detection/` (신규)                        | [audit_domain_additional](audit_domain_additional.md) §4-2 | ⬜   |
| 46  | 전표번호 연속성 갭 탐지           | `src/detection/` (신규)                        | [audit_domain_additional](audit_domain_additional.md) §2-2 | ⬜   |
| 47  | 승인 프로세스·TOE 검증            | `src/detection/` (신규)                        | [audit_domain_additional](audit_domain_additional.md) §4-4,3-3 | ⬜ |

### Phase 2b: ML 탐지기

> 🚫 **BLOCKER**: Phase 2b 착수 전 데이터 분할 전략 결정 필요
> - train/val/test split 비율, holdout 정책, DataSynth vs 실무데이터 분할
> - ref: `03a-preprocessing.md` §57, `05a-detection-ml.md` §12

> **pre-plan 참조**: Phase 2b 착수 시 확인할 교차 참조
> - `05a-detection-ml.md` §654-665 (preprocessing 코드리뷰 미해결 6건: registry path traversal, VAE check_is_fitted, label_strategy hybrid fallback 등)
> - `05-detection.md` §185 (C01 account-group별 Q3 확장)
> - `05-detection.md` §369 (Phase 1 룰 결과 → pseudo-label로 활용)
> - `06-db.md` §580 (ALTER TABLE 마이그레이션 — ML 피처 컬럼 추가)

| #   | 태스크                             | 파일                                        | 가이드                                                         | 상태 |
|-----|------------------------------------|---------------------------------------------|----------------------------------------------------------------|------|
| 48  | SupervisedDetector                 | `src/detection/supervised_detector.py`      | [05a-detection-ml](pre-plan/05a-detection-ml.md)               | ⬜   |
| 49  | VAEDetector + IF 앙상블            | `src/detection/vae_detector.py`             | [05a-detection-ml](pre-plan/05a-detection-ml.md)               | ⬜   |
| 50  | score_aggregator 3→5트랙 확장      | `src/detection/score_aggregator.py` — A/B/C + supervised + unsupervised | [05-detection](pre-plan/05-detection.md) + 05a   | ⬜   |
| 51  | L3 통계 검증                       | `src/validation/statistical_validator.py`   | [04-validation](pre-plan/04-validation.md)                     | ✅ (Phase 1a 선행 구현) |
| 52  | SHAP 시각화                        | `dashboard/tab_explorer.py`                 | [07-dashboard](pre-plan/07-dashboard.md)                       | ⬜   |
| 53  | 단위 테스트 (ML detection)         | `tests/test_detection/test_ml_*.py`         | [05a-detection-ml](pre-plan/05a-detection-ml.md)               | ⬜   |
| 54  | TrendBreak (회계추정치 편의, ML 기반) | `src/detection/timeseries_detector.py`   | [05a-detection-ml](pre-plan/05a-detection-ml.md) §TrendBreak   | ⬜   |
| 55  | 재무제표-장부 대사 (TB 교차검증)   | `src/validation/tb_reconciliation.py`       | [04-validation](pre-plan/04-validation.md) §재무제표-장부 대사 | ⬜   |
| 56  | 배치 전표 이상 패턴                | `src/detection/` (anomaly_layer 확장)       | [05a-detection-ml](pre-plan/05a-detection-ml.md) §배치 전표    | ⬜   |
| 57  | C01 account-group별 Q3 확장        | `src/detection/anomaly_layer.py` — 글로벌 Q3 → 계정그룹별 Q3 | [05-detection](pre-plan/05-detection.md) §185    | ⬜   |

### Phase 2c: 추가 탐지기 (별도 계획)

| #   | 태스크              | 파일                                    | 가이드                                     | 상태 |
|-----|---------------------|-----------------------------------------|--------------------------------------------|------|
| 58  | DuplicateDetector   | `src/detection/duplicate_detector.py`   | [05-detection](pre-plan/05-detection.md)   | ⬜   |
| 59  | 시계열 분석 (Rule 기반) | `src/detection/timeseries_rule.py`  | [05-detection](pre-plan/05-detection.md)   | ⬜   |
| 60  | 내부거래 매칭       | `src/detection/intercompany_matcher.py` | [05-detection](pre-plan/05-detection.md)   | ⬜   |

### Phase 2 확장: 기존 모듈 고도화 (pre-plan 교차 참조)

> Phase 2 범위 내에서 기존 모듈을 확장하는 태스크. Phase 2a/2b 완료 후 순차 진행.

| #   | 태스크                              | 파일                                          | 가이드                                              | 상태 |
|-----|-------------------------------------|-----------------------------------------------|-----------------------------------------------------|------|
| 61  | 유럽 금액 포맷 지원                 | `src/ingest/type_caster.py` — `1.234,56` 스타일 | [02-ingest](pre-plan/02-ingest.md) §374            | ⬜   |
| 62  | 한국 공휴일 연동 (holidays.KR)      | `src/feature/time_features.py`                | [04-validation](pre-plan/04-validation.md) §128     | ⬜   |
| 63  | approval_threshold 다단계 확장      | `src/feature/amount_features.py` — 단일 → 6단계 (10M~50B) | [03-feature](pre-plan/03-feature.md) §154 | ⬜   |
| 64  | DuckDB ALTER TABLE 마이그레이션 (Phase 2 실행) | `src/db/schema.py` — ML 피처 컬럼 실제 추가 | [06-db](pre-plan/06-db.md) §580 | ⬜ |
| 65  | 텍스트 정보량(Entropy) 분석         | `src/feature/text_features.py` — 적요 엔트로피·패턴 수학적 분석 | [03-feature](pre-plan/03-feature.md) §249 | ⬜   |
| 66  | Dashboard ML 지표 설명 (툴팁)       | `dashboard/` — AUPRC, F2-score, DR@FAR=5% 설명 | [07-dashboard](pre-plan/07-dashboard.md) §607      | ⬜   |

---

## Phase 3: NLQ + Graph + Polish (NLP·그래프 5개 유형 + LLM + 내보내기)

> **pre-plan 참조**: Phase 3 착수 시 확인할 교차 참조
> - `08-llm.md` §590-622 (Phase 1a에서 이관된 미해결 이슈 5건: header-account mismatch, process-account mismatch, vague descriptions, IC anomalies, synonym bypass)
> - `08-llm.md` §711-736 (감사기준서 갭 분석 3건: 경제적 실질, 유의적 거래, 이전가격)
> - `03-feature.md` §759 (text_features semantic stub → Ollama 임베딩 연동)
> - `01-project-setup.md` §84 (LLM 설정 필드 활성화: ollama_model, ollama_base_url)
> - `03a-preprocessing.md` §119 (VRAM 순차 실행: LLM + VAE 동시 사용 방지)

| #   | 태스크                              | 파일                                          | 가이드                                                     | 상태 |
|-----|-------------------------------------|-----------------------------------------------|------------------------------------------------------------|------|
| 67  | Ollama 클라이언트                   | `src/llm/ollama_client.py`                    | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 68  | Vanna Text-to-SQL                   | `src/llm/text_to_sql.py`                     | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 69  | SQL 검증                            | `src/llm/sql_validator.py`                    | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 70  | 감사 프리셋 6종                     | `src/llm/prompt_presets.py`                   | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 71  | 적요 NLP                            | `src/detection/nlp_analyzer.py`               | [05-detection](pre-plan/05-detection.md)                   | ⬜   |
| 72  | 그래프 순환 탐지                    | `src/detection/graph_detector.py`             | [05-detection](pre-plan/05-detection.md)                   | ⬜   |
| 73  | Chat UI 탭                          | `dashboard/tab_chat.py`                       | [07-dashboard](pre-plan/07-dashboard.md)                   | ⬜   |
| 74  | Export 탭                           | `dashboard/tab_export.py`                     | [07-dashboard](pre-plan/07-dashboard.md)                   | ⬜   |
| 75  | 감사조서 Excel/PDF                  | `src/export/`                                 | [09-export](pre-plan/09-export.md)                         | ⬜   |
| 76  | audit_trail 테이블 DDL              | `src/db/schema.py` — audit_trail 테이블 추가  | [09-export](pre-plan/09-export.md) §31                     | ⬜   |
| 77  | Audit Trail 기록기                  | `src/export/audit_trail.py`                   | [09-export](pre-plan/09-export.md)                         | ⬜   |
| 78  | 인사이트 생성                       | `src/llm/insight_generator.py`                | [08-llm](pre-plan/08-llm.md)                              | ⬜   |
| 79  | 경제적 실질 판단 (NLP)              | `src/detection/nlp_analyzer.py` (확장)        | [08-llm](pre-plan/08-llm.md) §경제적 실질                  | ⬜   |
| 80  | 유의적 거래 합리성 평가 (LLM)       | `src/llm/insight_generator.py` (확장)         | [08-llm](pre-plan/08-llm.md) §유의적 거래                  | ⬜   |
| 81  | TransferPricingAnomaly (이전가격)    | `src/detection/graph_detector.py` (확장)      | [AUDIT_DOMAIN_FINAL](AUDIT_DOMAIN_FINAL.md) §4.4          | ⬜   |
| 82  | LLM 기반 헤더 탐지 고도화           | `src/ingest/header_detector.py` (확장)        | [02-ingest](pre-plan/02-ingest.md) §848                    | ⬜   |
| 83  | LLM 전처리 제안 모듈                | `src/llm/` — EDAProfile → 전처리 전략 추천    | [03a-preprocessing](pre-plan/03a-preprocessing.md) §47     | ⬜   |
| 84  | kiwipiepy 형태소 분석               | `src/feature/text_features.py` (확장)         | [03-feature](pre-plan/03-feature.md) §287                  | ⬜   |
| 85  | LLM 계정명 의미 분석                | `src/feature/text_features.py` (확장)         | [03-feature](pre-plan/03-feature.md) §423                  | ⬜   |
| 86  | XAI Narrative Report                | `src/llm/` — 위험 설명 자동 생성              | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
| 87  | 감사규칙 피드백 루프                | `src/llm/` — audit_rules.yaml 자동 개선 제안  | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
| 88  | semantic_similarity (임베딩)        | `src/llm/` — Ollama 임베딩 동의어 매칭        | [08-llm](pre-plan/08-llm.md) §626                         | ⬜   |
