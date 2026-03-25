# Phase별 태스크

> 각 태스크의 상세 구현 가이드는 `docs/pre-plan/` 참조
> pre-plan 번호(00~10)는 **도메인 분류**이며, 구현 순서는 **Phase 번호**를 따른다.
> 예: `05a-detection-ml.md`는 Phase 2b의 설계 레퍼런스이지, 05 다음에 바로 구현하는 것이 아님.

## Phase 1: MVP (Python Only 파이프라인 + 기본 UI)

### Phase 1a: 데이터 파이프라인

| #  | 태스크             | 파일                                                          | 가이드                                          | 상태 |
|----|--------------------|---------------------------------------------------------------|------------------------------------------------|------|
| 0  | 데이터셋 수집·선정 | `data/journal/`, 32개 검토                                    | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 0a | DataSynth 빌드    | `tools/datasynth/` (Rust, EY-ASU)                              | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 0b | 메인 데이터 생성  | `data/journal/primary/datasynth/` (1,106K건)                   | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 1  | 프로젝트 초기화     | `pyproject.toml`, `.gitignore`, `.env.example`                | [01-project-setup](pre-plan/01-project-setup.md) | ✅   |
| 2  | 설정 레이어         | `config/settings.py`, YAML 3종 + `datasynth.yaml`            | [01-project-setup](pre-plan/01-project-setup.md) | ✅   |
| 3  | 샘플 데이터 생성기  | DataSynth로 대체 (10-sample-data 불필요)                      | -                                              | ✅   |
| 4  | 수동 Excel 템플릿   | DataSynth CSV로 대체                                          | -                                              | ✅   |
| 5  | 파일 검증           | `src/ingest/file_validator.py`                                | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 6  | Excel 읽기          | `src/ingest/excel_reader.py`                                  | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 7  | 헤더 탐지           | `src/ingest/header_detector.py`                               | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 8  | 컬럼 매핑           | `src/ingest/column_mapper.py`                                 | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 9  | 타입 캐스팅         | `src/ingest/type_caster.py`                                   | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 10 | 매핑 프로파일       | `src/ingest/mapping_profile.py`                               | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 10a | **UX 1단계**       | 구조적 헤더탐지 + 타입검증 + ReviewItem + Null분기 + latin-1 폴백 | [02-ingest](pre-plan/02-ingest.md)          | ✅   |
| 10b | **피드백 반영**    | 인코딩 오버라이드+confidence, 시트 스코어링, 금액 퀵픽스, Phase 1c UI 스펙 | [02-ingest](pre-plan/02-ingest.md)   | ✅   |
| 11 | 피처 엔진           | `src/feature/engine.py` + 4개 서브모듈 (170 tests passed)     | [03-feature](pre-plan/03-feature.md)           | ✅   |
| 11a | **UX 3단계 — EDA** | `src/eda/` 7개 모듈 (52 tests passed)                         | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ✅   |
| 12 | L1~L2 검증          | `src/validation/schema_validator.py`, `accounting_validator.py` | [04-validation](pre-plan/04-validation.md)     | ✅   |
| 13 | 전처리 리포트       | `src/validation/report_generator.py` (17 tests passed)        | [04-validation](pre-plan/04-validation.md)     | ✅   |
| 14 | 단위 테스트 (1a)    | `tests/test_ingest/`, `test_feature/`                         | 각 가이드 "테스트 전략" 섹션                    | ✅   |

**완료 기준**: DataSynth CSV → ingest → feature → validation 파이프라인 통과

### Phase 1b: 이상탐지 + DB

| #  | 태스크            | 파일                                                           | 가이드                                    | 상태 |
|----|-------------------|----------------------------------------------------------------|------------------------------------------|------|
| 15 | BaseDetector      | `src/detection/base.py`                                        | [05-detection](pre-plan/05-detection.md) | ✅   |
| 16 | Layer A 무결성    | `src/detection/integrity_layer.py` (A01~A03)                   | [05-detection](pre-plan/05-detection.md) | ✅   |
| 17 | Layer B 부정탐지  | `src/detection/fraud_layer.py` (B01~B10, 42 tests)             | [05-detection](pre-plan/05-detection.md) | ✅   |
| 18 | Layer C 이상징후  | `src/detection/anomaly_layer.py` (C01~C09, 41 tests)           | [05-detection](pre-plan/05-detection.md) | ✅   |
| 19 | 점수 집계         | `src/detection/score_aggregator.py` (3레이어+Benford, 12 tests) | [05-detection](pre-plan/05-detection.md) | ✅   |
| 19a | 역분개 패턴 탐지 (1:1 + N:M) | `src/detection/anomaly_layer.py` (확장)              | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 19b | Top-side JE 조합 탐지        | `src/detection/score_aggregator.py` (확장)           | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 19c | 비정상 시간대 입력자 집중     | `src/feature/time_features.py` (확장)                | [03-feature](pre-plan/03-feature.md)     | ⬜   |
| 20 | DuckDB (ML 확장 스키마) | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py` — schema에 supervised/unsupervised_score nullable 예약 | [06-db](pre-plan/06-db.md) | ⬜   |
| 21 | 파이프라인        | `src/pipeline.py`                                              | 05-detection + 06-db 통합                | ⬜   |
| 22 | 단위 테스트 (1b)  | `tests/test_detection/` (120 tests + [E2E](../tests/test_detection/test-results/e2e-detection-datasynth.md)), `test_db/` | 각 가이드 "테스트 전략" 섹션 | ⬜   |

**완료 기준**: `AuditPipeline.run("datasynth.csv")` → 22개 룰 3레이어 탐지 → DuckDB 적재 → 프리셋 쿼리 정상

### Phase 1c: 대시보드

| #  | 태스크                   | 파일                                      | 가이드                                    | 상태 |
|----|--------------------------|-------------------------------------------|------------------------------------------|------|
| 23 | UI 컴포넌트              | `dashboard/components/`                   | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 24 | Tab 1: Summary           | `dashboard/tab_summary.py`                | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 25 | Tab 2: Benford           | `dashboard/tab_benford.py`                | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 26 | Tab 3: Explorer          | `dashboard/tab_explorer.py`               | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 27 | 메인 앱                  | `dashboard/app.py`                        | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 28 | 임계값 튜닝 슬라이더     | `dashboard/components/threshold_sidebar.py`| [ux-flow §4A](pre-plan/ux-flow.md#a-실시간-파라미터-튜닝-dynamic-threshold-tuning--흐름도-⑧) | ⬜   |
| 29 | 프리셋 드롭다운          | `dashboard/components/preset_selector.py` | [ux-flow §4C](pre-plan/ux-flow.md#c-산업별시즌별-프리셋-environment-presets--흐름도-⑩)       | ⬜   |
| 30 | HITL 예외 처리 (whitelist)| `src/db/schema.py` + `tab_explorer.py`   | [ux-flow §4B](pre-plan/ux-flow.md#b-화이트리스트--hitl-피드백-루프-mark-as-false-positive--흐름도-⑨) | ⬜   |

**완료 기준**: `streamlit run dashboard/app.py` → 3탭 정상 렌더링 + 슬라이더 변경 시 탐지 결과 갱신 + 프리셋 전환 + 예외 처리 저장/제외

---

### 문서 보완: AUDIT_DOMAIN_FINAL 기준서 매핑 완성

> `audit_domain_additional.md` §3 "문서 보완 14건" 기반. 코드 변경 없음, 문서만 수정.

| 태스크                                                                 | 파일                          | 가이드                                                          | 상태 |
|------------------------------------------------------------------------|-------------------------------|-----------------------------------------------------------------|------|
| AUDIT_DOMAIN_FINAL 기준서 매핑 추가 (5건) + 참조 출처 (8건) + 범위 섹션 (1건) | `docs/AUDIT_DOMAIN_FINAL.md` | [audit_domain_additional](audit_domain_additional.md) §3        | ⬜   |

---

### Phase 2 준비: DataSynth 확장 (한국 실무 맞춤 컬럼 추가)

> DataSynth Rust 코드 수정 + YAML 설정 추가. Phase 2 탐지 룰의 **선행 의존**.

| 태스크                            | 파일                                                | 가이드                                                              | 상태 |
|-----------------------------------|-----------------------------------------------------|---------------------------------------------------------------------|------|
| approval.rs 한국식 전결규정 적용  | `tools/datasynth/crates/*/approval.rs, je_generator.rs, user.rs` | [audit_domain_additional](audit_domain_additional.md) §4-4          | ⬜   |
| 증빙/컷오프/변경이력 컬럼 추가    | `tools/datasynth/crates/*/journal_entry.rs`          | [audit_domain_additional](audit_domain_additional.md) §2-1,2-4,4-1  | ⬜   |
| 전표번호 순차 생성                | `tools/datasynth/crates/*/je_generator.rs`           | [audit_domain_additional](audit_domain_additional.md) §2-2          | ⬜   |
| IP 주소 생성                      | `tools/datasynth/crates/*/je_generator.rs`           | [audit_domain_additional](audit_domain_additional.md) §4-2          | ⬜   |
| datasynth.yaml approval 섹션     | `config/datasynth.yaml`                              | [audit_domain_additional](audit_domain_additional.md) §4-4          | ⬜   |
| 데이터 재생성 + ingest/feature 검증 | `data/journal/primary/datasynth/`                   | 신규 컬럼 포함 데이터로 기존 파이프라인 호환 확인                    | ⬜   |

---

## Phase 2: Core AI (ML 모델 + 추가 탐지 유형)

### Phase 2a: ML 전처리 파이프라인

| 태스크                       | 파일                                         | 가이드                                              | 상태 |
|------------------------------|----------------------------------------------|-----------------------------------------------------|------|
| 피처 그룹 분류               | `src/preprocessing/feature_groups.py`        | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| 커스텀 트랜스포머            | `src/preprocessing/transformers.py`          | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| 파이프라인 빌더              | `src/preprocessing/pipeline_builder.py`      | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| 라벨 전략 (자동 모드 전환)   | `src/preprocessing/label_strategy.py`        | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| CV 셀렉터                   | `src/preprocessing/cv_selector.py`           | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| VAE 래퍼 + 모델             | `src/preprocessing/vae_wrapper.py`, `vae_model.py` | [03a-preprocessing](pre-plan/03a-preprocessing.md) | ⬜   |
| 모델 레지스트리              | `src/preprocessing/model_registry.py`        | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| 전처리 투명성                | `src/preprocessing/transparency.py`          | [03a-preprocessing](pre-plan/03a-preprocessing.md)  | ⬜   |
| 단위 테스트 (preprocessing)  | `tests/test_preprocessing/`                  | 03a-preprocessing "테스트 전략"                     | ⬜   |

### Phase 2a 확장: 신규 컬럼 탐지 룰 (DataSynth 확장 컬럼 활용)

> [audit_domain_additional.md](audit_domain_additional.md) 기반. DataSynth 확장 완료 후 구현 가능.

| 태스크                             | 파일                                         | 가이드                                                | 상태 |
|------------------------------------|----------------------------------------------|-------------------------------------------------------|------|
| 증빙 존재 확인 + 적격증빙 미수취   | `src/detection/` (신규 또는 fraud_layer 확장) | [audit_domain_additional](audit_domain_additional.md) §2-1 | ⬜   |
| 컷오프 검증 (납품일 vs 전기일)     | `src/detection/` (신규 또는 anomaly_layer 확장) | [audit_domain_additional](audit_domain_additional.md) §2-4 | ⬜   |
| 증빙 금액 불일치 + 부가세 검증     | `src/detection/` (신규 또는 anomaly_layer 확장) | [audit_domain_additional](audit_domain_additional.md) §2-5 | ⬜   |
| 전표 수정 이력 탐지                | `src/detection/` (신규)                       | [audit_domain_additional](audit_domain_additional.md) §4-1 | ⬜   |
| IP 주소 비정상 접근 탐지           | `src/detection/` (신규)                       | [audit_domain_additional](audit_domain_additional.md) §4-2 | ⬜   |
| 전표번호 연속성 갭 탐지            | `src/detection/` (신규)                       | [audit_domain_additional](audit_domain_additional.md) §2-2 | ⬜   |
| 승인 프로세스·TOE 검증             | `src/detection/` (신규)                       | [audit_domain_additional](audit_domain_additional.md) §4-4,3-3 | ⬜   |

### Phase 2b: ML 탐지기

| 태스크                       | 파일                                       | 가이드                                                | 상태 |
|------------------------------|--------------------------------------------|------------------------------------------------------|------|
| SupervisedDetector           | `src/detection/supervised_detector.py`     | [05a-detection-ml](pre-plan/05a-detection-ml.md)     | ⬜   |
| VAEDetector + IF 앙상블      | `src/detection/vae_detector.py`            | [05a-detection-ml](pre-plan/05a-detection-ml.md)     | ⬜   |
| score_aggregator 3→5트랙 확장 | `src/detection/score_aggregator.py` — 기존 A/B/C + supervised + unsupervised | [05-detection](pre-plan/05-detection.md) + 05a | ⬜   |
| L3 통계 검증                 | `src/validation/statistical_validator.py`  | [04-validation](pre-plan/04-validation.md)           | ✅ (Phase 1a 선행 구현) |
| SHAP 시각화                  | `dashboard/tab_explorer.py`                | [07-dashboard](pre-plan/07-dashboard.md)             | ⬜   |
| 단위 테스트 (ML detection)   | `tests/test_detection/test_ml_*.py`        | [05a-detection-ml](pre-plan/05a-detection-ml.md)     | ⬜   |
| TrendBreak (회계추정치 편의) | `src/detection/timeseries_detector.py`     | [05a-detection-ml](pre-plan/05a-detection-ml.md) §TrendBreak | ⬜   |
| 재무제표-장부 대사 (TB 교차검증) | `src/validation/tb_reconciliation.py`  | [04-validation](pre-plan/04-validation.md) §재무제표-장부 대사 | ⬜   |
| 배치 전표 이상 패턴          | `src/detection/` (anomaly_layer 확장)      | [05a-detection-ml](pre-plan/05a-detection-ml.md) §배치 전표 | ⬜   |

### Phase 2c: 추가 탐지기 (별도 계획)

| 태스크                       | 파일                                       | 가이드                                    | 상태 |
|------------------------------|--------------------------------------------|------------------------------------------|------|
| DuplicateDetector            | `src/detection/duplicate_detector.py`      | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 시계열 분석                  | `src/detection/timeseries_detector.py`     | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 내부거래 매칭                | `src/detection/intercompany_matcher.py`    | [05-detection](pre-plan/05-detection.md) | ⬜   |

---

## Phase 3: NLQ + Graph + Polish (NLP·그래프 5개 유형 + LLM + 내보내기)

| 태스크              | 파일                             | 가이드                                    | 상태 |
|---------------------|----------------------------------|------------------------------------------|------|
| Ollama 클라이언트   | `src/llm/ollama_client.py`       | [08-llm](pre-plan/08-llm.md)            | ⬜   |
| Vanna Text-to-SQL   | `src/llm/text_to_sql.py`        | [08-llm](pre-plan/08-llm.md)            | ⬜   |
| SQL 검증            | `src/llm/sql_validator.py`       | [08-llm](pre-plan/08-llm.md)            | ⬜   |
| 감사 프리셋 6종     | `src/llm/prompt_presets.py`      | [08-llm](pre-plan/08-llm.md)            | ⬜   |
| 적요 NLP            | `src/detection/nlp_analyzer.py`  | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 그래프 순환 탐지   | `src/detection/graph_detector.py`    | [05-detection](pre-plan/05-detection.md) | ⬜   |
| Chat UI 탭          | `dashboard/tab_chat.py`          | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| Export 탭           | `dashboard/tab_export.py`        | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 감사조서 Excel/PDF  | `src/export/`                    | [09-export](pre-plan/09-export.md)       | ⬜   |
| Audit Trail         | `src/export/audit_trail.py`      | [09-export](pre-plan/09-export.md)       | ⬜   |
| 인사이트 생성       | `src/llm/insight_generator.py`   | [08-llm](pre-plan/08-llm.md)            | ⬜   |
| 경제적 실질 판단 (NLP)      | `src/detection/nlp_analyzer.py` (확장)  | [08-llm](pre-plan/08-llm.md) §경제적 실질           | ⬜   |
| 유의적 거래 합리성 평가 (LLM) | `src/llm/insight_generator.py` (확장) | [08-llm](pre-plan/08-llm.md) §유의적 거래           | ⬜   |
| TransferPricingAnomaly (이전가격) | `src/detection/graph_detector.py` (확장) | [AUDIT_DOMAIN_FINAL](AUDIT_DOMAIN_FINAL.md) §4.4 | ⬜   |
