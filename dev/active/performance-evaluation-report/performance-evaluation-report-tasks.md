# Performance Evaluation Report - Task Checklist

## Progress Summary

0 / 15 tasks complete (0%)

## Phase 1: 평가 스키마와 공통 모델

- [ ] **1-1** 평가 요약 테이블 DDL 추가
  - File: `src/db/schema.py`
  - Details: `performance_reports`, `performance_rule_metrics` 테이블을 추가한다. `source_kind`(`ground_truth`/`operational_proxy`), `phase_scope`, `metric_confidence` 컬럼을 포함한다.
  - Acceptance: `initialize_schema()` 후 `SHOW TABLES`에 두 테이블이 존재한다.
  - Size: S

- [ ] **1-2** 평가 조회 프리셋 추가
  - File: `src/db/queries.py`
  - Details: `latest_performance_report`, `performance_rule_metrics_by_report`, `performance_reports_by_batch` 프리셋을 추가한다.
  - Acceptance: 빈 DB에서도 세 프리셋이 예외 없이 빈 DataFrame을 반환한다.
  - Size: S

- [ ] **1-3** 공통 모델 정의
  - File: `src/metrics/models.py`
  - Details: `PerformanceReport`, `RuleMetric`, `PhaseComparisonMetric` 모델을 정의한다. Markdown/UI/DB 저장이 모두 이 모델을 사용하게 한다.
  - Acceptance: evaluator가 반환하는 타입이 테스트와 렌더러에서 재사용 가능하다.
  - Size: S

- [ ] **1-4** DB 스키마 테스트 추가
  - File: `tests/modules/test_db/test_schema.py`
  - Details: 신규 테이블 2종과 핵심 컬럼 존재 여부를 검증한다.
  - Acceptance: `pytest tests/modules/test_db/test_schema.py -q` 통과.
  - Size: S

## Phase 2: Ground Truth 평가 엔진

- [ ] **2-1** 룰-라벨 매핑 모듈 추출
  - File: `src/metrics/rule_mapping.py`
  - Details: `tests/phase1_rulebase/test_e2e_label_validation.py`의 `RULE_TO_LABEL`, `RULE_TO_LAYER`를 옮기고 문서화한다.
  - Acceptance: 기존 E2E 스크립트가 새 모듈 import로 동작한다.
  - Size: S

- [ ] **2-2** Ground Truth evaluator 구현
  - File: `src/metrics/ground_truth_evaluator.py`
  - Details: 룰별 TP/FP/FN, precision/recall/F1, 전체 문서 단위 precision/recall, Phase 1 only vs Phase 2 included 비교를 계산한다.
  - Acceptance: 소형 fixture에서 계산값이 수기 기대값과 일치한다.
  - Size: M

- [ ] **2-3** DataSynth label 로더 연결
  - File: `src/ingest/datasynth_labels.py`, `src/metrics/ground_truth_evaluator.py`
  - Details: sidecar label CSV 또는 embedded label을 evaluator 입력으로 안정적으로 불러오도록 연결한다.
  - Acceptance: DataSynth source path만 알면 labels_df를 읽어 평가 가능하다.
  - Size: S

- [ ] **2-4** 기존 E2E label validation 스크립트 단순화
  - File: `tests/phase1_rulebase/test_e2e_label_validation.py`
  - Details: 계산 로직은 evaluator 호출로 대체하고, 스크립트는 데이터 로드 및 report write만 담당하게 줄인다.
  - Acceptance: 기존 Markdown 리포트 형식이 크게 깨지지 않고 스크립트가 동작한다.
  - Size: M

- [ ] **2-5** Ground Truth evaluator 단위 테스트 추가
  - File: `tests/modules/test_metrics/test_ground_truth_evaluator.py`
  - Details: precision/recall/F1, no-label rule, skipped rule, phase comparison 케이스를 검증한다.
  - Acceptance: evaluator 핵심 branch가 모두 테스트된다.
  - Size: M

## Phase 3: 운영 지표 평가 엔진

- [ ] **3-1** Operational evaluator 구현
  - File: `src/metrics/operational_evaluator.py`
  - Details: 배치별 high-risk 비율, detector별 flagged 문서 수, whitelist 추가 전후 감소량, 누적 whitelist 비율을 계산한다.
  - Acceptance: DB fixture에서 지표 계산값이 예상과 일치한다.
  - Size: M

- [ ] **3-2** 평가 결과 저장 계층 추가
  - File: `src/db/performance_store.py`
  - Details: `save_report()`, `load_latest_report()`, `list_reports_by_batch()`를 구현한다.
  - Acceptance: report 저장 후 재조회 시 summary와 rule metrics가 보존된다.
  - Size: M

- [ ] **3-3** 운영 지표 evaluator 테스트 추가
  - File: `tests/modules/test_metrics/test_operational_evaluator.py`
  - Details: whitelist 없는 배치, whitelist 반영 배치, partial confidence historical batch 케이스를 검증한다.
  - Acceptance: `pytest tests/modules/test_metrics/test_operational_evaluator.py -q` 통과.
  - Size: M

## Phase 4: 리포트 생성과 UI 통합

- [ ] **4-1** Markdown report builder 추가
  - File: `src/metrics/report_builder.py`
  - Details: `PerformanceReport`를 받아 요약, phase comparison, rule metrics, whitelist effect를 포함한 Markdown 문자열을 만든다.
  - Acceptance: ground truth report와 operational report 모두 같은 builder로 출력된다.
  - Size: M

- [ ] **4-2** 대시보드 성능 평가 섹션 추가
  - File: `dashboard/tab_phase2.py` 또는 `dashboard/components/performance_report.py`
  - Details: 현재 detector 운영 상태 아래에 성능 평가 요약 카드와 표를 추가하고, ground truth/proxy 여부를 배지로 구분한다.
  - Acceptance: 평가 결과가 없으면 graceful empty state를 보여주고, 있으면 summary/rule table이 렌더링된다.
  - Size: M

- [ ] **4-3** 대시보드 테스트 추가
  - File: `tests/modules/test_dashboard/test_tab_phase2.py`
  - Details: 성능 평가 데이터가 있을 때와 없을 때 렌더링 분기를 검증한다.
  - Acceptance: UI 분기 관련 회귀가 테스트로 보호된다.
  - Size: M

- [ ] **4-4** 지표 문서화
  - File: `docs/spec/metrics.md`
  - Details: precision/recall/F1 정의, whitelist proxy metric 해석, synthetic bias 한계를 문서화한다.
  - Acceptance: 문서만 읽어도 각 지표의 의미와 제한을 설명할 수 있다.
  - Size: S

## Phase 5: 파이프라인 연결

- [ ] **5-1** 배치 실행 후 평가 생성 지점 연결
  - File: `src/pipeline.py`
  - Details: 새 배치 실행 후 ground truth 가능 여부를 판별하고, 가능하면 평가 엔진 호출 지점을 추가한다. 자동 생성이 부담되면 명시적 메서드 진입점만 추가한다.
  - Acceptance: 신규 배치에서 평가 호출 경로가 한 곳으로 고정된다.
  - Size: S

- [ ] **5-2** 통합 검증
  - File: `tests/modules/test_pipeline/` 또는 `tests/phase1_rulebase/`
  - Details: 파이프라인 결과에서 evaluator로 이어지는 end-to-end 경로를 최소 1건 검증한다.
  - Acceptance: 저장/조회/UI 중 최소 한 경로가 통합 테스트로 보호된다.
  - Size: M

## Deployment Checklist

- [ ] 신규 DB 테이블 2종이 멱등 초기화된다.
- [ ] 기존 `test_e2e_label_validation.py` 리포트가 evaluator 재사용 구조로 바뀐다.
- [ ] ground truth metric과 operational proxy metric이 UI에서 명시적으로 구분된다.
- [ ] 과거 배치의 partial confidence 표시가 문서와 UI에 반영된다.
- [ ] 관련 pytest 모듈이 모두 통과한다.
