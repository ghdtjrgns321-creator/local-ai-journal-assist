# Supervised ML Gate Hardening - Task Checklist

## Progress Summary

11 / 15 tasks complete (Sprint A1 complete, 2026-05-17)

## Phase 1: Gate Policy와 설정 외부화

- [x] **1-1** supervised gate 설정값 추가
  - File: `config/settings.py`
  - Details: `supervised_min_positive`, `supervised_min_positive_rate`, `supervised_allowed_label_sources`를 추가한다. 기본값은 현재 상수와 동일하게 둔다.
  - Acceptance: `get_settings()` 기본값만으로 기존 테스트가 깨지지 않는다.
  - Size: S

- [x] **1-2** LabelResult 메타 구조 확장
  - File: `src/preprocessing/label_strategy.py`
  - Details: `positive_count`, `label_quality`, `gate_status`, `gate_reason`, `is_supervised_eligible` 필드를 추가한다.
  - Acceptance: `LabelResult(...)` 직접 생성 fixture들이 모두 새 필드를 처리하거나 기본값으로 통과한다.
  - Size: S

- [x] **1-3** label strategy 기본값 테스트 정리
  - File: `tests/modules/test_preprocessing/test_label_strategy.py`
  - Details: 확장된 dataclass 기본값과 기존 API 호환성을 검증한다.
  - Acceptance: `pytest tests/modules/test_preprocessing/test_label_strategy.py -q` 통과.
  - Size: S

## Phase 2: Label Qualification 구현

- [x] **2-1** datasynth label gate 판정 추가
  - File: `src/preprocessing/label_strategy.py`
  - Details: GT 기반 라벨이면 `trusted`, 아니면 `absent`로 평가하고 positive count/rate를 계산한다.
  - Acceptance: GT가 있으면서 기준을 넘으면 `is_supervised_eligible=True`가 된다.
  - Size: M

- [x] **2-2** pseudo / hybrid fallback 차단 판정 추가
  - File: `src/preprocessing/label_strategy.py`
  - Details: `pseudo`, `pseudo_fallback`, `unsupervised` source는 `circular_risk` 또는 `absent`로 표기하고 supervised 부적합 처리한다.
  - Acceptance: hybrid가 pseudo fallback으로 내려간 케이스에서 `is_supervised_eligible=False`가 된다.
  - Size: M

- [x] **2-3** source breakdown 유지 검증
  - File: `tests/modules/test_preprocessing/test_label_strategy.py`
  - Details: 기존 `source_breakdown`과 새 gate metadata가 동시에 유지되는지 확인한다.
  - Acceptance: 기존 breakdown 관련 테스트와 신규 gate 테스트가 함께 통과한다.
  - Size: M

## Phase 3: SupervisedDetector hard gate enforcement

- [x] **3-1** `_validate_labels()` 반환 구조 개편
  - File: `src/detection/supervised_detector.py`
  - Details: 단순 warning 생성이 아니라 gate snapshot을 반환하도록 바꾼다.
  - Acceptance: train 진입 전 reason code와 warning list를 동시에 얻을 수 있다.
  - Size: M

- [x] **3-2** 학습 차단 예외 추가
  - File: `src/detection/supervised_detector.py`
  - Details: `positive_count == 0`, 최소 양성 수 미달, 최소 양성 비율 미달, untrusted label source에서 supervised 학습을 차단한다.
  - Acceptance: pseudo label과 low-positive fixture에서 train이 예외를 발생시킨다.
  - Size: M

- [x] **3-3** train metadata에 gate snapshot 포함
  - File: `src/detection/supervised_detector.py`
  - Details: `train()` 반환값에 `gate_status`, `gate_reason`, `label_source`, `positive_count`, `positive_rate`를 포함한다.
  - Acceptance: 호출부가 추가 계산 없이 학습 판정을 표시할 수 있다.
  - Size: S

- [x] **3-4** model registry 저장 메타 확장
  - File: `src/detection/supervised_detector.py`, `src/preprocessing/model_registry.py`
  - Details: `save_model()`이 gate snapshot을 metadata params 또는 별도 필드로 저장한다.
  - Acceptance: 저장 후 `list_models()`에서 gate 관련 값을 읽을 수 있다.
  - Size: S

- [x] **3-5** supervised detector 테스트 추가
  - File: `tests/modules/test_detection/test_supervised_detector.py`
  - Details: pseudo 차단, low positive 차단, GT 허용, metadata 저장을 검증한다.
  - Acceptance: `pytest tests/modules/test_detection/test_supervised_detector.py -q` 통과.
  - Size: M

## Phase 4: Pipeline fallback과 운영 상태 정리

- [ ] **4-1** detector status reason vocabulary 정리
  - File: `src/pipeline.py`
  - Details: `untrusted_label_source`, `circular_label_risk`, `insufficient_positive_count`, `low_positive_rate`, `unknown_training_gate` 등 reason 코드를 표준화한다.
  - Acceptance: supervised skip 상태가 자유 문자열이 아니라 고정 코드로 기록된다.
  - Size: S

- [ ] **4-2** supervised skip -> unsupervised fallback 연결
  - File: `src/pipeline.py`
  - Details: training 또는 runtime gate 실패 시 `ml_supervised`를 skipped로 기록하고 `ml_unsupervised`만 실행되도록 한다.
  - Acceptance: 같은 배치에서 supervised만 빠지고 unsupervised는 정상 동작한다.
  - Size: M

- [ ] **4-3** legacy model provenance 처리
  - File: `src/pipeline.py`
  - Details: registry metadata에 gate snapshot이 없는 예전 supervised 모델은 `unknown_training_gate`로 표시한다.
  - Acceptance: 예전 모델 로드시 crash 없이 상태가 복원된다.
  - Size: S

- [ ] **4-4** pipeline 테스트 추가
  - File: `tests/modules/test_pipeline/test_pipeline.py` 또는 `tests/modules/test_pipeline/test_ml_gate.py`
  - Details: supervised skip reason, detector status, fallback 유지 여부를 검증한다.
  - Acceptance: pipeline 단에서 supervised gate 동작이 재현된다.
  - Size: M

## Phase 5: 후속 문서와 회귀 방지

- [ ] **5-1** registry 테스트 보강
  - File: `tests/modules/test_preprocessing/test_model_registry.py`
  - Details: gate snapshot 저장/복원과 legacy metadata 하위 호환을 검증한다.
  - Acceptance: 새 metadata가 있어도 옛 registry.json 로딩이 깨지지 않는다.
  - Size: S

- [ ] **5-2** 문서 상태 갱신
  - File: `docs/archive/completed/개선사항.md`
  - Details: 3.4 항목에 구현 결과, gate 정책, 후속 범위(ML03/ML04 확장)를 반영한다.
  - Acceptance: 문서와 코드 기준이 다시 어긋나지 않는다.
  - Size: S

## Deployment Checklist

- [x] pseudo label로 supervised 모델이 저장되지 않는다.
- [x] GT 라벨이어도 최소 양성 수/비율 미달이면 supervised 학습이 차단된다.
- [x] training report에서 supervised skip reason이 바로 보인다.
- [ ] legacy supervised 모델은 `unknown_training_gate`로 안전하게 표시된다.
- [x] 관련 pytest 모듈이 모두 통과한다.

## Sprint A1 Completion Note (2026-05-17)

Sprint A1 범위는 label gate 구조화, supervised detector hard gate, Phase2 `training_report.json.supervised_gate` 노출까지 완료했다. Pipeline runtime legacy model provenance와 model registry 별도 테스트 보강은 후속 Sprint로 남긴다.
