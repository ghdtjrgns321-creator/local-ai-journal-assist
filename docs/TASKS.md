# Phase별 태스크

> 각 태스크의 상세 구현 가이드는 `docs/pre-plan/` 참조

## Phase 1: MVP (Python Only 파이프라인 + 기본 UI)

### Phase 1a: 데이터 파이프라인

| #  | 태스크             | 파일                                                          | 가이드                                          | 상태 |
|----|--------------------|---------------------------------------------------------------|------------------------------------------------|------|
| 0  | 데이터셋 수집·선정 | `data/journal/`, 32개 검토                                    | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 0a | DataSynth 빌드    | `tools/datasynth/` (Rust, EY-ASU)                              | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 0b | 메인 데이터 생성  | `data/journal/primary/datasynth/` (1,068K건)                   | [00-dataset](pre-plan/00-dataset.md)           | ✅   |
| 1  | 프로젝트 초기화     | `pyproject.toml`, `.gitignore`, `.env.example`                | [01-project-setup](pre-plan/01-project-setup.md) | ✅   |
| 2  | 설정 레이어         | `config/settings.py`, YAML 3종 + `datasynth.yaml`            | [01-project-setup](pre-plan/01-project-setup.md) | ✅   |
| 3  | 샘플 데이터 생성기  | DataSynth로 대체 (10-sample-data 불필요)                      | -                                              | ✅   |
| 4  | 수동 Excel 템플릿   | DataSynth CSV로 대체                                          | -                                              | ✅   |
| 5  | 파일 검증           | `src/ingest/file_validator.py`                                | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 6  | Excel 읽기          | `src/ingest/excel_reader.py`                                  | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 7  | 헤더 탐지           | `src/ingest/header_detector.py`                               | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 8  | 컬럼 매핑           | `src/ingest/column_mapper.py`                                 | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 9  | 타입 캐스팅         | `src/ingest/type_caster.py`                                   | [02-ingest](pre-plan/02-ingest.md)             | ✅   |
| 10 | 매핑 프로파일       | `src/ingest/mapping_profile.py`                               | [02-ingest](pre-plan/02-ingest.md)             | ⬜   |
| 11 | 피처 엔진           | `src/feature/engine.py` + 4개 서브모듈                        | [03-feature](pre-plan/03-feature.md)           | ⬜   |
| 12 | L1~L2 검증          | `src/validation/schema_validator.py`, `accounting_validator.py` | [04-validation](pre-plan/04-validation.md)     | ⬜   |
| 13 | 전처리 리포트       | `src/validation/report_generator.py`                          | [04-validation](pre-plan/04-validation.md)     | ⬜   |
| 14 | 단위 테스트 (1a)    | `tests/test_ingest/`, `test_feature/`                         | 각 가이드 "테스트 전략" 섹션                    | ⬜   |

**완료 기준**: DataSynth CSV → ingest → feature → validation 파이프라인 통과

### Phase 1b: 이상탐지 + DB

| #  | 태스크            | 파일                                                           | 가이드                                    | 상태 |
|----|-------------------|----------------------------------------------------------------|------------------------------------------|------|
| 15 | BaseDetector      | `src/detection/base.py`                                        | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 16 | Layer A 무결성    | `src/detection/integrity_layer.py` (A01~A03)                   | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 17 | Layer B 부정탐지  | `src/detection/fraud_layer.py` (B01~B10)                       | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 18 | Layer C 이상징후  | `src/detection/anomaly_layer.py` (C01~C09, Benford=C07)        | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 19 | 점수 집계         | `src/detection/score_aggregator.py` (3레이어+Benford)          | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 20 | DuckDB            | `src/db/connection.py`, `schema.py`, `loader.py`, `queries.py` | [06-db](pre-plan/06-db.md)              | ⬜   |
| 21 | 파이프라인        | `src/pipeline.py`                                              | 05-detection + 06-db 통합                | ⬜   |
| 22 | 단위 테스트 (1b)  | `tests/test_detection/`, `test_db/`                            | 각 가이드 "테스트 전략" 섹션              | ⬜   |

**완료 기준**: `AuditPipeline.run("datasynth.csv")` → 22개 룰 3레이어 탐지 → DuckDB 적재 → 프리셋 쿼리 정상

### Phase 1c: 대시보드

| #  | 태스크          | 파일                       | 가이드                                    | 상태 |
|----|-----------------|----------------------------|------------------------------------------|------|
| 23 | UI 컴포넌트     | `dashboard/components/`    | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 24 | Tab 1: Summary  | `dashboard/tab_summary.py` | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 25 | Tab 2: Benford  | `dashboard/tab_benford.py` | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 26 | Tab 3: Explorer | `dashboard/tab_explorer.py`| [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |
| 27 | 메인 앱         | `dashboard/app.py`         | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |

**완료 기준**: `streamlit run dashboard/app.py` → 3탭 정상 렌더링

---

## Phase 2: Core AI (ML 모델 + 16개 추가 유형)

| 태스크                       | 파일                                       | 가이드                                    | 상태 |
|------------------------------|--------------------------------------------|------------------------------------------|------|
| GridSearchCV 지도학습        | `src/detection/supervised_detector.py`     | [05-detection](pre-plan/05-detection.md) | ⬜   |
| VAE + IF 앙상블              | `src/detection/vae_detector.py`            | [05-detection](pre-plan/05-detection.md) | ⬜   |
| DuplicateDetector            | `src/detection/duplicate_detector.py`      | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 시계열 분석                  | `src/detection/timeseries_detector.py`     | [05-detection](pre-plan/05-detection.md) | ⬜   |
| 내부거래 매칭                | `src/detection/intercompany_matcher.py`    | [05-detection](pre-plan/05-detection.md) | ⬜   |
| score_aggregator 5트랙 확장  | `src/detection/score_aggregator.py`        | [05-detection](pre-plan/05-detection.md) | ⬜   |
| L3 통계 검증                 | `src/validation/statistical_validator.py`  | [04-validation](pre-plan/04-validation.md) | ⬜   |
| SHAP 시각화                  | `dashboard/tab_explorer.py`                | [07-dashboard](pre-plan/07-dashboard.md) | ⬜   |

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
