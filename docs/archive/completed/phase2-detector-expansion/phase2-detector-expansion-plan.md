# Phase2 Detector Expansion - Strategic Plan

## Executive Summary
현재 Phase 2는 `unsupervised / supervised / transformer / sequence / stacking` 중심의 train-infer-provenance 계약은 갖췄지만, 문서상 Phase 2로 분류된 `timeseries / relational / duplicate / intercompany` 계열은 아직 학습 오케스트레이션과 detector 세분화 계약에 완전히 편입되지 않았다. 이번 작업은 기존 Phase 2 기반 위에 시계열·novelty·중복·내부거래 계열을 학습 family와 공용 contract 안으로 묶고, detector 세분화와 AutoML 정책을 포트폴리오 설명 가능한 수준까지 끌어올리는 것이다.

## Current State
- `src/services/phase2_training_service.py`는 `unsupervised`, `supervised`, `transformer`, `sequence`, `stacking` 5개 family만 orchestration한다.
- `src/detection/timeseries_detector.py`, `src/detection/relational_detector.py`, `src/detection/duplicate_detector.py`, `src/detection/intercompany_matcher.py`는 개별 detector로 존재하지만 Phase 2 train leaderboard / promoted model / inference contract에 포함되지 않는다.
- `src/pipeline.py`는 `duplicate`, `intercompany`, `relational`, `timeseries`를 별도 detect track으로 실행할 수 있으나, promoted model 기반의 exact Phase 2 contract에는 아직 느슨하게 연결되어 있다.
- `docs/spec/DETECTION_RULES.md`는 최신화되었지만, DataSynth 16개 유형과 실제 detector family 매핑은 아직 부분적이다.
- 현재 AutoML은 family별 preset 탐색과 승격 정책까지는 구현되었지만, detector 세분화와 track별 선택 정책은 아직 단일 기준에 가깝다.

## Proposed Solution
- Phase 2 train family를 9개 계열로 확장한다.
  - `unsupervised`
  - `supervised`
  - `transformer`
  - `sequence`
  - `timeseries`
  - `relational`
  - `duplicate`
  - `intercompany`
  - `stacking`
- rule-style detector도 Phase 2 train leaderboard에 들어갈 수 있도록 공통 trial/result contract를 확장한다.
- detector 세분화는 “모델 family”와 “canonical model key”를 분리하여 관리한다.
  - 예: `timeseries` family 아래 `transaction_burst`, `unusual_frequency`
  - 예: `relational` family 아래 `new_counterparty`, `dormant_account_activity`
- AutoML 고도화는 exhaustive search가 아니라 family별 탐색 정책과 승격 정책을 정교화하는 방향으로 간다.
  - family별 preset
  - sub-detector 단위 leaderboard
  - selection policy
  - train/infer contract 강화

## Implementation Phases

### Phase 1: Planning Baseline and Contract Audit (0.5 day)
**Goal**: 기존 Phase 2 contract와 새 detector family 확장 범위를 문서와 코드 양쪽에 고정한다.
**Tasks**:
- [ ] 기존 `phase2_training_service.py` family map 현황 정리 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] 기존 detector track 이름과 canonical model key 매핑 정리 - File: `src/pipeline.py` - Size: S
- [ ] 확장 대상 detector별 현재 재사용 가능 API 확인 - File: `src/detection/timeseries_detector.py` - Size: S
- [ ] 확장 대상 detector별 현재 재사용 가능 API 확인 - File: `src/detection/relational_detector.py` - Size: S
- [ ] 확장 대상 detector별 현재 재사용 가능 API 확인 - File: `src/detection/duplicate_detector.py` - Size: S
- [ ] 확장 대상 detector별 현재 재사용 가능 API 확인 - File: `src/detection/intercompany_matcher.py` - Size: S

### Phase 2: Training Family Expansion (1.5 days)
**Goal**: `timeseries`, `relational`, `duplicate`, `intercompany`를 Phase 2 train orchestration에 편입한다.
**Tasks**:
- [ ] `_DEFAULT_MODEL_FAMILIES`에 확장 family 추가 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] detector factory map에 timeseries/relational/duplicate/intercompany 추가 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] family별 canonical model key 추가 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] rule-style detector용 generic trial runner 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] timeseries family queue/preset 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] relational family queue/preset 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] duplicate family queue/preset 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] intercompany family queue/preset 추가 - File: `src/services/phase2_training_service.py` - Size: M

### Phase 3: Detector Granularity and Sub-Track Metadata (1.5 days)
**Goal**: family 내부 sub-detector를 문서와 UI에서 설명 가능한 수준으로 세분화한다.
**Tasks**:
- [ ] `Phase2TrialResult.metadata`에 `sub_detector_keys` 계약 추가 - File: `src/services/phase2_training_models.py` - Size: S
- [ ] timeseries sub-detector metadata 기록 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] relational sub-detector metadata 기록 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] duplicate sub-detector metadata 기록 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] intercompany sub-detector metadata 기록 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] inference contract에 family/sub-detector provenance 확장 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] pipeline detector status에 canonical family / used_version 정합 강화 - File: `src/pipeline.py` - Size: M

### Phase 4: AutoML Policy Hardening (1.5 days)
**Goal**: 확장 family까지 포함하는 family별 탐색·승격 정책을 정교화한다.
**Tasks**:
- [ ] family별 search preset policy 재정의 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] rule-style detector의 metric normalization 정책 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] family별 최소 완료 trial 수 / skip 패널티 정책 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] sub-detector summary를 report metadata에 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] promoted selection tie-break를 family 특성까지 반영하도록 확장 - File: `src/services/phase2_training_service.py` - Size: M

### Phase 5: Contract Propagation and Inference Alignment (1 day)
**Goal**: train 확장 결과가 infer / DB / export / phase3까지 같은 contract로 전파되게 한다.
**Tasks**:
- [ ] inference service가 확장 family promoted version을 읽도록 보강 - File: `src/services/phase2_inference_service.py` - Size: M
- [ ] batch 저장 메타에 확장 family contract 반영 검토 및 보강 - File: `src/db/loader.py` - Size: M
- [ ] batch 복원 시 확장 family contract 복원 검토 및 보강 - File: `src/db/batch_reader.py` - Size: M
- [ ] export provenance에 family 확장 summary 반영 - File: `src/export/analysis_status.py` - Size: M

### Phase 6: Verification and Documentation (1 day)
**Goal**: 확장된 Phase 2가 문서-코드-테스트 기준으로 일치함을 확보한다.
**Tasks**:
- [ ] training service 확장 family 테스트 추가 - File: `tests/modules/test_services/test_phase2_training_service.py` - Size: L
- [ ] pipeline/inference contract 회귀 테스트 추가 - File: `tests/modules/test_pipeline/test_pipeline.py` - Size: M
- [ ] export/provenance 회귀 테스트 추가 - File: `tests/modules/test_export/test_excel_exporter.py` - Size: M
- [ ] `docs/spec/DETECTION_RULES.md`와 `docs/archive/completed/PHASE_PROVENANCE.md` 후속 반영 - File: `docs/spec/DETECTION_RULES.md` - Size: S
- [ ] 작업 완료 후 상태 문서 갱신 - File: `dev/active/phase2-detector-expansion/phase2-detector-expansion-context.md` - Size: S

## Risk Assessment
- **High Risk**: rule-style detector를 train leaderboard에 넣을 때 metric 해석이 ML family와 달라 비교가 왜곡될 수 있다. Mitigation: family별 normalization과 sub-detector summary를 같이 저장한다.
- **High Risk**: duplicate/intercompany는 이미 별도 track과 DB 컬럼이 있어 phase2 contract와 이중 관리될 수 있다. Mitigation: canonical model key와 track map을 먼저 고정한 뒤 infer contract를 그 기준으로만 읽는다.
- **Medium Risk**: timeseries/relational detector는 학습형 모델이 아니라 save/load semantics가 약하다. Mitigation: rule-style family는 artifact-less trial을 허용하고 versioned policy contract로 관리한다.
- **Medium Risk**: detector 세분화가 UI 요구로 다시 번질 수 있다. Mitigation: 이번 단계는 metadata와 contract까지만 우선 고정하고 UI는 후속 최소 반영만 한다.

## Success Metrics
- Phase 2 training report에서 9개 family가 모두 queue 대상이 된다.
- `timeseries`, `relational`, `duplicate`, `intercompany`가 leaderboard / promoted model / inference contract에 나타난다.
- `TransactionBurst`, `UnusualFrequency`, `NewCounterparty`, `DormantAccountActivity`, `ExactDuplicateAmount`, `UnmatchedIntercompany`가 sub-detector metadata로 추적된다.
- phase2 infer 결과가 확장 family provenance를 DB 복원과 export까지 유지한다.
- 관련 테스트가 모두 통과한다.

## Dependencies
- Code:
  - `src/services/phase2_training_service.py`
  - `src/services/phase2_training_models.py`
  - `src/services/phase2_inference_service.py`
  - `src/pipeline.py`
  - `src/detection/timeseries_detector.py`
  - `src/detection/relational_detector.py`
  - `src/detection/duplicate_detector.py`
  - `src/detection/intercompany_matcher.py`
  - `src/db/loader.py`
  - `src/db/batch_reader.py`
  - `src/export/analysis_status.py`
- External:
  - existing ModelRegistry directory
  - current DuckDB batch schema
