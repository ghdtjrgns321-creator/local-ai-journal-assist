# Phase2 Train AutoML - Strategic Plan

## Executive Summary
현재 `phase2`는 저장된 모델 추론과 bootstrap 학습이 섞여 있어, 첫 실행 UX와 학습 재현성이 모두 불안정하다. 이를 해결하기 위해 `phase2-train`을 별도 서비스 계층으로 분리하고, 전처리 후보 비교, 모델 후보 비교, 하이퍼파라미터 탐색, stacking 학습, registry 승격을 하나의 학습 파이프라인으로 묶는다.

## Current State
- `src/services/analysis_service.py`는 `phase1`/`phase2` 추론 실행만 담당하고 학습 단계는 없다.
- `src/pipeline.py`의 `_try_ml_detection()`과 `_try_stacking_ensemble()`는 모델이 없을 때 bootstrap 학습을 시도하지만, 이는 cold-start 보완용이며 AutoML이 아니다.
- `src/detection/supervised_detector.py`는 `compare_pipelines()`를 통해 LR/RF/XGB/LGBM 비교를 수행하지만, 탐색 결과를 별도 leaderboard로 저장하지 않는다.
- `src/detection/tabular_transformer.py`, `src/detection/sequence_detector.py`, `src/detection/vae_detector.py`는 개별 train/save/load API가 있으나, 공통 trial orchestration이 없다.
- `src/preprocessing/feature_quality.py`는 family ablation plan을 제공하지만 실제 학습 탐색 루프에서 사용되지 않는다.
- `src/detection/ensemble_detector.py`는 `train_oof()`를 갖고 있으나 추론 파이프라인에서는 단순 bootstrap 경로만 사용한다.

## Proposed Solution
- `phase2`를 두 경로로 분리한다.
  - `phase2-train`: 학습 전용 AutoML 파이프라인
  - `phase2-infer`: 저장된 best model만 사용하는 추론 파이프라인
- 학습 파이프라인은 다음 단계를 고정 순서로 수행한다.
  - 라벨 소스 평가
  - feature group 생성
  - feature family ablation variant 생성
  - 모델 family별 candidate train/evaluate
  - best trial 선택
  - stacking OOF 학습 여부 판정 및 학습
  - registry 저장
  - training report 저장
- UI는 이 서비스가 반환한 training report를 그대로 표시하는 thin layer로 유지한다.

## Implementation Phases

### Phase 1: Training Domain Foundation (1 day)
**Goal**: 학습 파이프라인의 입출력 타입과 저장 포맷을 먼저 고정한다.
**Tasks**:
- [ ] `src/services/phase2_training_service.py` 생성 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `src/services/phase2_training_models.py` 생성 - File: `src/services/phase2_training_models.py` - Size: M
- [ ] 학습 상태 enum, trial result, leaderboard row, training report dataclass 정의 - File: `src/services/phase2_training_models.py` - Size: M
- [ ] company/engagement 모델 디렉토리 기준 training artifact 경로 정책 정의 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] 저장 파일 스키마 문서화 - File: `dev/active/phase2-train-automl/phase2-train-automl-context.md` - Size: S

### Phase 2: Label and Feature Search Preparation (1 day)
**Goal**: 학습 가능한 입력과 탐색 variant를 공통 루틴으로 만들고 bootstrap 코드와 분리한다.
**Tasks**:
- [ ] `create_labels()` 기반 trusted label 판정 래퍼 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `profile_dataframe()` + `classify_features()` 기반 공통 feature prep 함수 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `feature_quality.ablation_plan`을 실제 variant 입력으로 변환하는 helper 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] variant별 사용 컬럼 집합과 FeatureGroups 재구성 로직 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] 라벨 부족 시 `unsupervised-only` fallback 정책 명시 - File: `src/services/phase2_training_service.py` - Size: S

### Phase 3: Model Candidate Orchestration (2 days)
**Goal**: supervised / transformer / sequence / unsupervised를 동일한 trial 구조로 실행한다.
**Tasks**:
- [ ] supervised candidate runner 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] transformer candidate runner 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] sequence candidate runner 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] unsupervised candidate runner 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] candidate별 metric, gate reason, feature quality, elapsed 수집 로직 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] 실패 trial도 leaderboard에 남기는 에러 수집 정책 추가 - File: `src/services/phase2_training_service.py` - Size: S

### Phase 4: Hyperparameter Search and Budget Policy (2 days)
**Goal**: 모델별 탐색 범위를 하드코딩된 bootstrap이 아니라 반복 가능한 search policy로 바꾼다.
**Tasks**:
- [ ] `config/settings.py`에 phase2-train budget 설정 추가 - File: `config/settings.py` - Size: M
- [ ] supervised pipeline tuning entrypoint를 `compare_pipelines()` + `tune_best_pipeline()`로 확장 - File: `src/services/phase2_training_service.py` - Size: L
- [ ] transformer search grid 정의 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] sequence search grid 정의 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] unsupervised search space 정의 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] search budget 초과 시 조기 종료 정책 추가 - File: `src/services/phase2_training_service.py` - Size: M

### Phase 5: Stacking and Registry Promotion (1 day)
**Goal**: base model best trial 선정 후 stacking OOF를 정식 학습 단계로 넣는다.
**Tasks**:
- [ ] best base models만 registry에 승격 저장하는 promotion 함수 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `EnsembleDetector.train_oof()` 연동 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] stacking 학습 성공/실패를 training report에 반영 - File: `src/services/phase2_training_service.py` - Size: S
- [ ] bootstrap용 `_maybe_bootstrap_phase2_models()`가 신규 학습 서비스의 경량 모드만 호출하도록 리다이렉션 계획 수립 - File: `src/pipeline.py` - Size: M

### Phase 6: Inference Separation and UI Hand-off (1 day)
**Goal**: 추론 경로를 학습 경로와 분리하고, UI가 training report만 소비하도록 만든다.
**Tasks**:
- [ ] `src/services/analysis_service.py`에 `run_phase2_training()` 추가 - File: `src/services/analysis_service.py` - Size: M
- [ ] `src/pipeline.py`에서 `phase2-infer`는 registry 로드 전용으로 단순화 - File: `src/pipeline.py` - Size: L
- [ ] `dashboard/tab_overview.py`에서 phase2 실행 버튼을 학습/추론 분기로 바꾸는 지점 명시 - File: `dashboard/tab_overview.py` - Size: M
- [ ] `dashboard/tab_phase2.py`가 training report leaderboard를 렌더하도록 변경 계획 반영 - File: `dashboard/tab_phase2.py` - Size: M

### Phase 7: Test and Verification (1 day)
**Goal**: 학습 파이프라인이 실제로 재현 가능하고 회귀 없이 동작하는지 검증한다.
**Tasks**:
- [ ] 학습 서비스 단위 테스트 추가 - File: `tests/modules/test_services/test_phase2_training_service.py` - Size: L
- [ ] registry 승격/재로딩 테스트 추가 - File: `tests/modules/test_preprocessing/test_model_registry.py` - Size: M
- [ ] stacking OOF 통합 테스트 추가 - File: `tests/modules/test_detection/test_ensemble_detector.py` - Size: M
- [ ] dashboard service 레벨 phase2-train 테스트 추가 - File: `tests/modules/test_services/test_dashboard_services.py` - Size: M
- [ ] 최소 e2e smoke 테스트 추가 - File: `tests/modules/test_pipeline/test_pipeline.py` - Size: M

## Risk Assessment
- **High Risk**: Sequence/Transformer 탐색이 너무 느릴 수 있다. Mitigation: search budget, candidate cap, feature family ablation 수 제한.
- **High Risk**: trusted label 부족 시 supervised leaderboard가 의미 없어진다. Mitigation: label gate를 report 최상단에 노출하고 unsupervised-only mode를 공식 지원.
- **Medium Risk**: bootstrap 경로와 정식 AutoML 경로가 중복될 수 있다. Mitigation: bootstrap은 신규 학습 서비스의 `mode="bootstrap"` thin wrapper만 사용.
- **Medium Risk**: registry에 trial 전체를 저장하면 모델 버전 오염이 생긴다. Mitigation: trial artifact와 promoted model artifact를 분리한다.

## Success Metrics
- Test coverage: 신규 학습 서비스 85% 이상
- Reproducibility: 동일 seed에서 best model 이름과 핵심 metric이 재현 가능
- Separation: `phase2-infer` 실행 중 추가 학습 코드 경로 진입 0회
- UX readiness: UI는 training report JSON만 읽어도 leaderboard와 진행 상태를 렌더 가능

## Dependencies
- Code:
  - `src/preprocessing/label_strategy.py`
  - `src/preprocessing/feature_groups.py`
  - `src/preprocessing/feature_quality.py`
  - `src/preprocessing/cv_selector.py`
  - `src/detection/supervised_detector.py`
  - `src/detection/tabular_transformer.py`
  - `src/detection/sequence_detector.py`
  - `src/detection/vae_detector.py`
  - `src/detection/ensemble_detector.py`
  - `src/preprocessing/model_registry.py`
- External:
  - `torch`
  - `xgboost`
  - `lightgbm`
  - company/engagement writable model directory
