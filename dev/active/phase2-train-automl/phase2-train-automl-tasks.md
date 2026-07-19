# Phase2 Train AutoML - Task Checklist

## Progress Summary
24 / 31 tasks complete (Sprint A2 complete, 2026-05-17)

## Phase 1: Training Domain Foundation
- [x] `Phase2TrainingStatus` enum 정의
  - File: `src/services/phase2_training_models.py`
  - Details: `pending`, `running`, `completed`, `failed`, `skipped` 상태를 정의한다.
  - Acceptance: enum import 시 학습 단계 상태 문자열이 고정된다.
  - Size: S
- [x] `Phase2TrialResult` dataclass 정의
  - File: `src/services/phase2_training_models.py`
  - Details: model family, variant, params, metric, elapsed, gate reason, artifact path를 담는다.
  - Acceptance: trial 한 건을 dict로 직렬화할 수 있다.
  - Size: S
- [x] `Phase2TrainingReport` dataclass 정의
  - File: `src/services/phase2_training_models.py`
  - Details: label summary, leaderboard, promoted models, stacking summary, warnings를 담는다.
  - Acceptance: report에 UI가 필요한 핵심 필드가 모두 포함된다.
  - Size: S
- [x] artifact 경로 규칙 정의
  - File: `src/services/phase2_training_service.py`
  - Details: engagement `model_dir` 아래 `trials/`, `reports/`, `promoted/` 역할을 분리한다.
  - Acceptance: path helper가 문자열 빌드 없이 `Path` 객체를 반환한다.
  - Size: S

## Phase 2: Label and Feature Search Preparation
- [x] trusted label 생성 helper 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `create_labels(..., strategy="hybrid")` 호출 후 gate와 source를 요약한다.
  - Acceptance: 라벨 없음, pseudo fallback, trusted label 세 경우가 모두 구분된다.
  - Size: S
- [x] feature group 생성 helper 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `profile_dataframe()` + `classify_features()`를 한 번만 수행한다.
  - Acceptance: 여러 candidate가 같은 base feature groups를 공유한다.
  - Size: S
- [x] ablation variant 변환 helper 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `feature_quality.ablation_plan`을 실제 include/drop 컬럼 규칙으로 바꾼다.
  - Acceptance: `baseline_core`, `plus_*`, `full_active` variant 목록이 생성된다.
  - Size: M
- [x] variant별 FeatureGroups 재구성 helper 추가
  - File: `src/services/phase2_training_service.py`
  - Details: variant에서 제외된 컬럼을 group에서 제거한다.
  - Acceptance: detector train 호출 시 variant에 맞는 groups만 전달된다.
  - Size: M

## Phase 3: Model Candidate Orchestration
- [x] supervised trial runner 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `SupervisedDetector.train()` 호출과 결과 수집을 감싼다.
  - Acceptance: 성공 시 trial result가 생성되고 실패 시 failed trial이 기록된다.
  - Size: M
- [x] transformer trial runner 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `TransformerDetector.train()` 호출과 결과 수집을 감싼다.
  - Acceptance: trial result가 model family `ft_transformer`로 기록된다.
  - Size: M
- [x] sequence trial runner 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `SequenceDetector.train()` 호출과 결과 수집을 감싼다.
  - Acceptance: sequence 필수 컬럼 부족 시 skipped reason이 남는다.
  - Size: M
- [x] unsupervised trial runner 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `UnsupervisedDetector.train()` 호출과 결과 수집을 감싼다.
  - Acceptance: 라벨 없이도 valid trial이 생성된다.
  - Size: M
- [x] failed trial normalization 추가
  - File: `src/services/phase2_training_service.py`
  - Details: 예외를 `status`, `reason`, `elapsed`로 표준화한다.
  - Acceptance: trial 실패가 보고서에서 누락되지 않는다.
  - Size: S

## Phase 4: Hyperparameter Search and Budget Policy
- [ ] phase2-train 설정 필드 추가
  - File: `config/settings.py`
  - Details: `phase2_train_budget_minutes`, `phase2_train_max_trials_per_family`, `phase2_train_seed`를 추가한다.
  - Acceptance: `AuditSettings`에서 기본값과 validator가 동작한다.
  - Size: M
- [ ] supervised tuning wrapper 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `compare_pipelines()` 이후 best estimator에 `tune_best_pipeline()`를 선택적으로 적용한다.
  - Acceptance: tuning on/off에 따라 trial params가 달라진다.
  - Size: L
- [ ] transformer search grid 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `ft_d_token`, `ft_n_layers`, `ft_dropout`, `ft_lr` 탐색 조합을 정의한다.
  - Acceptance: 최소 2개 이상의 transformer trial이 생성된다.
  - Size: M
- [ ] sequence search grid 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `bilstm_seq_len`, `bilstm_hidden_size`, `bilstm_dropout`, `bilstm_lr` 조합을 정의한다.
  - Acceptance: 최소 2개 이상의 sequence trial이 생성된다.
  - Size: M
- [x] unsupervised search grid 추가
  - File: `src/services/phase2_training_service.py`
  - Details: `vae_latent_dim`, `vae_epochs`, `if_contamination` 조합을 정의한다.
  - Acceptance: unsupervised leaderboard가 단일 bootstrap이 아닌 multi-trial을 갖는다.
  - Size: M
- [ ] budget cutoff 추가
  - File: `src/services/phase2_training_service.py`
  - Details: 누적 elapsed가 예산을 넘으면 남은 후보를 skipped 처리한다.
  - Acceptance: report warnings에 budget cutoff가 기록된다.
  - Size: M

## Phase 5: Stacking and Registry Promotion
- [x] family별 best trial 선택 함수 추가
  - File: `src/services/phase2_training_service.py`
  - Details: completed trial만 대상으로 metric 우선순위로 1개를 고른다.
  - Acceptance: family당 promoted model이 최대 1개만 선택된다.
  - Size: S
- [x] promoted model save 함수 추가
  - File: `src/services/phase2_training_service.py`
  - Details: best detector만 `save_model()`로 registry에 올린다.
  - Acceptance: registry에 trial 전체가 아니라 best artifact만 저장된다.
  - Size: M
- [ ] stacking OOF 학습 추가
  - File: `src/services/phase2_training_service.py`
  - Details: trusted label이 충분하면 `EnsembleDetector.train_oof()`를 호출한다.
  - Acceptance: report에 `mode=oof_stacking|fallback`가 저장된다.
  - Size: M
- [ ] stacking promotion 추가
  - File: `src/services/phase2_training_service.py`
  - Details: OOF 학습 성공 시 `stacking_meta`를 registry에 저장한다.
  - Acceptance: `stacking_meta`가 promoted models 목록에 포함된다.
  - Size: S

## Phase 6: Inference Separation and UI Hand-off
- [ ] `run_phase2_training()` 서비스 함수 추가
  - File: `src/services/analysis_service.py`
  - Details: dashboard state를 받아 training report를 생성하고 저장한다.
  - Acceptance: phase2-train이 pipeline redetect와 별도 API를 가진다.
  - Size: M
- [ ] bootstrap helper thin wrapper화
  - File: `src/pipeline.py`
  - Details: `_maybe_bootstrap_phase2_models()`가 신규 서비스의 `mode="bootstrap"`만 호출하도록 변경한다.
  - Acceptance: 직접 detector train 호출 코드가 pipeline에서 제거된다.
  - Size: L
- [x] `phase2-infer` 경로 단순화
  - File: `src/pipeline.py`
  - Details: `_try_ml_detection()`는 registry load + detect만 담당하게 줄인다.
  - Acceptance: 모델 탐색/선택 로직이 pipeline에 남지 않는다.
  - Size: L
- [ ] dashboard phase2 training report 연결 지점 명세
  - File: `dashboard/tab_phase2.py`
  - Details: leaderboard, best params, promoted model 목록 렌더 위치를 정의한다.
  - Acceptance: training report를 입력으로 한 렌더 함수 시그니처가 확정된다.
  - Size: M

## Phase 7: Test and Verification
- [x] label fallback 테스트 추가
  - File: `tests/modules/test_services/test_phase2_training_service.py`
  - Details: trusted label 없음 시 supervised families가 skipped 되는지 검증한다.
  - Acceptance: reason이 `missing_ground_truth_labels` 또는 gate reason으로 고정된다.
  - Size: M
- [x] unsupervised-only mode 테스트 추가
  - File: `tests/modules/test_services/test_phase2_training_service.py`
  - Details: 라벨 부족이어도 unsupervised leaderboard가 생성되는지 검증한다.
  - Acceptance: completed unsupervised trial이 1건 이상 남는다.
  - Size: M
- [x] family ablation leaderboard 테스트 추가
  - File: `tests/modules/test_services/test_phase2_training_service.py`
  - Details: `baseline_core`와 `plus_persona` variant가 trial 목록에 모두 포함되는지 검증한다.
  - Acceptance: report trial variants 집합이 예상값과 일치한다.
  - Size: M
- [ ] stacking OOF path 테스트 추가
  - File: `tests/modules/test_detection/test_ensemble_detector.py`
  - Details: promoted base models가 있을 때 OOF stacking이 호출되는지 검증한다.
  - Acceptance: report mode가 `oof_stacking`이 된다.
  - Size: M
- [ ] dashboard service integration 테스트 추가
  - File: `tests/modules/test_services/test_dashboard_services.py`
  - Details: `run_phase2_training()`이 state에 report를 저장하는지 검증한다.
  - Acceptance: state에서 report와 batch metadata를 읽을 수 있다.
  - Size: M
- [ ] regression smoke 테스트 추가
  - File: `tests/modules/test_pipeline/test_pipeline.py`
  - Details: 기존 `phase2-infer`가 학습 없이 registry load만 수행하는지 검증한다.
  - Acceptance: infer path에서 training service 호출이 0회다.
  - Size: M

## Deployment Checklist
- [ ] `config/settings.py` 신규 학습 예산 필드 테스트 완료
- [ ] company/engagement model 디렉토리 쓰기 권한 확인
- [x] 신규 training report 직렬화 포맷 문서화
- [x] phase2-infer 회귀 테스트 통과
- [x] dashboard가 training report 없을 때 graceful fallback 유지

## Sprint A2 Completion Note (2026-05-17)

완료: 학습/추론 서비스 경계, leaderboard/promotion decision JSON 산출, inference contract model version/schema hash 확장, cold-start bootstrap mode 제거. 남김: budget settings/tuning wrapper, OOF stacking promotion 전면화, dashboard 렌더 연결, pipeline bootstrap helper thin-wrapper 명시 작업.
