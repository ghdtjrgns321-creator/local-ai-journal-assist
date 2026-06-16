# Performance Evaluation Report - Strategic Plan

## Executive Summary

`## 3.3 성능 평가 리포트 추가`는 단순 Markdown 출력이 아니라, 현재 파이프라인 결과를 재현 가능하게 평가하는 계층을 만드는 작업이다. 구현은 `정답 기반 평가(DataSynth)`와 `운영 지표 기반 평가(whitelist/high-risk/batch 추세)`를 분리하고, DB 저장 구조와 대시보드 표출을 공통 스키마로 묶는 방향이 적합하다.

## Current State

- 배치 실행 결과는 `general_ledger`, `anomaly_flags`, `benford_*`, `upload_batches`, `audit_log`, `whitelist`에 분산 저장된다.
- 정답 기반 성능 평가는 `tests/phase1_rulebase/test_e2e_label_validation.py`에만 존재하며, DataSynth 전용 스크립트와 Markdown 리포트 생성 로직으로 고정돼 있다.
- 운영 지표 중 `high_risk_count`, whitelist 추가/삭제, 감사 로그는 저장되지만 이를 묶어 보여주는 평가 리포트 계층은 없다.
- 현재 대시보드는 탐지기 운영 상태는 보여주지만 `precision/recall`, `false positive ratio`, `whitelist 반영 전후 변화`, `Phase 1 vs Phase 2 비교`는 계산하지 않는다.
- 과거 배치 복원은 가능하지만 detector runtime snapshot의 영속 저장은 아직 없어 일부 고급 비교 지표는 추정 또는 미지원으로 남는다.

## Proposed Solution

### Architecture

성능 평가 리포트를 두 계층으로 나눈다.

1. **Ground Truth Evaluation**
   - DataSynth 라벨 또는 sidecar label CSV가 있는 배치만 대상.
   - 룰별 precision/recall/F1, 문서 단위 precision/recall, Phase 1 only vs Phase 1+2 비교를 계산한다.

2. **Operational Evaluation**
   - 모든 배치를 대상으로 계산 가능.
   - batch별 high-risk 비율, detector별 flagged 문서 수, whitelist 추가 전후 감소량, whitelist 누적 비율, 배치 간 위험 추세를 계산한다.

두 계층의 결과를 하나의 공통 모델로 묶고, DB 저장과 Markdown/Streamlit 렌더러는 그 모델만 본다.

### Data Sources

- **Ground Truth**: `src/ingest/datasynth_labels.py`, `data/journal/primary/datasynth/labels/*.csv`
- **Detection Result**: `general_ledger`, `anomaly_flags`, `upload_batches`
- **Operational Feedback**: `whitelist`, `audit_log`
- **Detector Context**: `PipelineResult.results`, `PipelineResult.detector_statuses`

### Output Targets

- DB 저장용 요약 테이블 2종
- Python 서비스 계층 1개
- Markdown 리포트 생성기 1개
- Streamlit 대시보드 섹션 1개

## Implementation Phases

### Phase 1: 평가 스키마와 공통 모델 정의 (1일)

**Goal**: 성능 평가 결과를 저장/조회할 수 있는 최소 스키마와 Python 모델을 만든다.

- [ ] Task 1-1 - `src/db/schema.py` - 평가 요약 테이블 2종 DDL 추가 - Size: S
- [ ] Task 1-2 - `src/db/queries.py` - 평가 조회 프리셋 추가 - Size: S
- [ ] Task 1-3 - `src/metrics/models.py` - 공통 dataclass 또는 typed dict 정의 - Size: S
- [ ] Task 1-4 - `tests/modules/test_db/test_schema.py` - 신규 테이블/컬럼 검증 추가 - Size: S

### Phase 2: Ground Truth 평가 엔진 추출 (1일)

**Goal**: 기존 `test_e2e_label_validation.py`의 계산 로직을 재사용 가능한 서비스로 추출한다.

- [ ] Task 2-1 - `src/metrics/ground_truth_evaluator.py` - 룰별/전체 precision, recall, F1 계산기 구현 계획 반영 - Size: M
- [ ] Task 2-2 - `src/metrics/rule_mapping.py` - RULE_TO_LABEL, RULE_TO_LAYER를 테스트 파일에서 서비스 모듈로 이동 - Size: S
- [ ] Task 2-3 - `tests/phase1_rulebase/test_e2e_label_validation.py` - 서비스 모듈 사용으로 리포트 스크립트 단순화 - Size: M
- [ ] Task 2-4 - `tests/modules/test_metrics/test_ground_truth_evaluator.py` - 소형 fixture 기반 단위 테스트 추가 - Size: M

### Phase 3: 운영 지표 평가 엔진 추가 (1일)

**Goal**: 정답 라벨이 없어도 운영 품질을 볼 수 있는 배치 평가 지표를 계산한다.

- [ ] Task 3-1 - `src/metrics/operational_evaluator.py` - high-risk 비율, whitelist 전후 변화, detector coverage 계산 - Size: M
- [ ] Task 3-2 - `src/db/performance_store.py` - 평가 결과 upsert/load 헬퍼 추가 - Size: M
- [ ] Task 3-3 - `tests/modules/test_metrics/test_operational_evaluator.py` - whitelist 및 batch fixture 기반 테스트 추가 - Size: M

### Phase 4: 리포트 생성과 대시보드 통합 (1일)

**Goal**: DB/서비스 결과를 Markdown 리포트와 Streamlit UI에서 일관되게 보여준다.

- [ ] Task 4-1 - `src/metrics/report_builder.py` - 성능 평가 Markdown 생성기 추가 - Size: M
- [ ] Task 4-2 - `dashboard/tab_phase2.py` 또는 신규 `dashboard/components/performance_report.py` - 성능 평가 섹션 추가 - Size: M
- [ ] Task 4-3 - `tests/modules/test_dashboard/test_tab_phase2.py` - 리포트 섹션 렌더링 검증 추가 - Size: M
- [ ] Task 4-4 - `docs/spec/metrics.md` - 지표 정의와 해석 기준 문서화 - Size: S

### Phase 5: 파이프라인 연결과 생성 경로 정리 (0.5~1일)

**Goal**: 새 배치 실행 후 평가 리포트를 자동 또는 반자동으로 생성할 수 있게 연결한다.

- [ ] Task 5-1 - `src/pipeline.py` - 평가 입력용 스냅샷 전달 지점 정리 - Size: S
- [ ] Task 5-2 - `tests/modules/test_pipeline/test_detection_parallel.py` 또는 신규 테스트 - 배치 결과와 평가 결과 연동 검증 - Size: M
- [ ] Task 5-3 - `tools/` 또는 `tests/phase1_rulebase/` - CLI/스크립트 엔트리포인트 정리 - Size: S

## Detailed Design

### DB Schema

신규 테이블은 최소 2종이 적합하다.

1. `performance_reports`
   - 배치 단위 요약
   - 컬럼 예시: `report_id`, `upload_batch_id`, `source_kind`, `phase_scope`, `total_docs`, `flagged_docs`, `high_risk_ratio`, `precision`, `recall`, `f1`, `whitelist_removed_docs`, `created_at`

2. `performance_rule_metrics`
   - 룰 단위 세부 지표
   - 컬럼 예시: `report_id`, `track_name`, `rule_code`, `tp_docs`, `fp_docs`, `fn_docs`, `precision`, `recall`, `f1`, `label_docs`, `flagged_docs`

### Service Boundary

- `ground_truth_evaluator.py`
  - 입력: `PipelineResult` 또는 `(df, results, agg_df, labels_df)`
  - 출력: `PerformanceReport`
- `operational_evaluator.py`
  - 입력: DB connection + batch_id 또는 `PipelineResult`
  - 출력: `PerformanceReport`
- `report_builder.py`
  - 입력: `PerformanceReport`
  - 출력: Markdown 문자열

### Phase 1 vs Phase 2 Comparison

Phase 비교는 “탐지기 성숙도”가 아니라 스코프 기준으로 계산한다.

- `phase1_only`: `layer_a`, `layer_b`, `layer_c`, `benford`
- `phase2_included`: 위 + optional/ML/NLP/Graph/TrendBreak/Layer D 중 실제 실행된 트랙

이 비교는 `PipelineResult.detector_statuses`와 `DetectionResult.track_name` 기준으로 산출한다.

### Whitelist Effect

`whitelist 반영 전후 변화`는 두 수준으로 나눈다.

- **Immediate batch effect**: 현재 배치에서 whitelist된 문서 수, 위험도 하향된 문서 수
- **Accumulated operational effect**: 특정 회사/engagement에서 whitelist 누적 건수와 최근 batch별 whitelist 비율

단, whitelist는 “사람이 FP라고 판단한 것”의 근사치이지 precision의 완전한 정답은 아니므로 UI와 문서에 proxy metric임을 명시한다.

## Risk Assessment

- **High Risk**: DataSynth 평가 로직을 테스트 파일에서 그대로 복붙하면 서비스 코드와 테스트 코드가 다시 분기된다.
  - Mitigation: 계산 로직은 `src/metrics/`로 이동하고 테스트와 리포트 스크립트는 그 모듈을 호출만 하게 만든다.

- **High Risk**: whitelist 기반 지표를 precision으로 오해할 수 있다.
  - Mitigation: UI/문서에서 `ground_truth metric`과 `operational proxy metric`을 명시적으로 분리한다.

- **Medium Risk**: historical batch는 detector runtime snapshot이 완전하지 않아 Phase 2 비교가 일부 부정확할 수 있다.
  - Mitigation: 새 지표 스키마에 `metric_confidence` 또는 `data_completeness` 필드를 두고, 과거 배치는 `partial`로 표시한다.

- **Medium Risk**: `Phase 1 vs Phase 2` 비교를 score threshold 없이 하면 단순 실행 여부만 다른 왜곡이 생길 수 있다.
  - Mitigation: 문서 단위 TP/FP/FN 판단 기준과 threshold를 명시하고 설정값을 report metadata에 저장한다.

## Success Metrics

- DataSynth 배치에서 룰별 precision/recall/F1 리포트가 자동 생성된다.
- 운영 배치에서 whitelist 반영 전후 변화와 high-risk 비율이 대시보드에서 조회된다.
- `Phase 1 only`와 `Phase 2 included` 비교가 같은 공통 포맷으로 출력된다.
- 단위 테스트 + 기존 E2E 리포트 스크립트가 같은 evaluator를 재사용한다.

## Dependencies

- Code: `src/pipeline.py`, `src/db/schema.py`, `src/db/queries.py`, `src/ingest/datasynth_labels.py`, `dashboard/tab_phase2.py`
- External: 없음
