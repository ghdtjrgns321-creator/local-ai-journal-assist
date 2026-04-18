# Supervised ML Gate Hardening - Strategic Plan

## Executive Summary

`## 3.4 supervised ML 게이트 강화`는 지도학습 모델의 성능 개선 작업이 아니라, 불충분하거나 오염된 라벨로 supervised 모델이 학습되거나 운영 추론에 들어가는 것을 막는 안전장치 작업이다. 현재 코드는 양성 수와 양성 비율이 낮을 때 경고만 남기고 계속 학습하므로, pseudo label 순환학습과 저품질 label source가 그대로 모델 버전으로 저장될 수 있다.

이번 작업은 `label_strategy -> supervised_detector -> pipeline/runtime status` 세 구간으로 나눠 구현한다. 라벨 메타를 명시적으로 계산하고, 학습 게이트를 hard fail 또는 fallback 판정으로 승격하고, 파이프라인/UI/로그에 "왜 supervised가 꺼졌는지"를 공통 구조로 남기는 것이 핵심이다.

## Current State

- `src/preprocessing/label_strategy.py`
  - `LabelResult`는 `strategy`, `label_source`, `positive_rate`, `source_breakdown`만 가진다.
  - 라벨 품질이나 운영 적합성 판정은 없다.
  - `hybrid`는 GT가 없으면 pseudo fallback으로 내려가며, 이 정보가 단순 문자열 수준으로만 남는다.

- `src/detection/supervised_detector.py`
  - `_validate_labels()`가 `positive_count == 0`만 예외 처리하고, `positive_count < 50` 또는 `positive_rate < 0.01`은 warning만 남긴다.
  - 결과적으로 low-signal pseudo label도 그대로 supervised 모델 학습과 저장까지 통과한다.
  - 게이트 실패 사유를 구조화해서 반환하지 않는다.

- `src/pipeline.py`
  - 운영 추론 경로에서는 저장된 supervised 모델이 있으면 바로 로드해 실행한다.
  - 현재 detector status는 `executed/skipped/failed/not_in_path` 정도만 가지며, supervised 모델이 어떤 라벨 조건으로 학습된 모델인지 판정하지 않는다.
  - 향후 training path가 연결되더라도, gate decision과 runtime fallback reason을 같은 구조로 보여줄 기반이 약하다.

- `config/settings.py`
  - stacking fallback 설정은 있으나 supervised 전용 gate 설정은 없다.
  - 현재 supervised 최소 조건은 코드 상수(`_MIN_POSITIVE_COUNT`, `_MIN_POSITIVE_RATE`)에 박혀 있다.

## Proposed Solution

### Core Design

supervised 게이트를 다음 2단으로 분리한다.

1. **Label Qualification**
   - `LabelResult`에 라벨 출처, 라벨 품질, 양성 수, 양성 비율, gate 적합성 메타를 추가한다.
   - pseudo / pseudo_fallback / unsupervised label은 기본적으로 supervised 학습 부적합으로 본다.
   - ground truth라도 양성 수 또는 양성 비율이 기준 미만이면 supervised 학습을 막는다.

2. **Training / Runtime Enforcement**
   - `SupervisedDetector.train()`는 warning 기반이 아니라 구조화된 gate decision을 사용한다.
   - gate 실패 시 hard fail을 발생시키고, 상위 호출부는 이를 받아 supervised를 건너뛰고 unsupervised fallback으로 전환한다.
   - pipeline detector status와 모델 메타에 gate reason을 저장해 운영 화면에서 확인 가능하게 한다.

### Gate Policy

1차 구현 기준은 아래처럼 단순하고 보수적으로 잡는다.

- `label_source`
  - `ground_truth`: 통과 후보
  - `pseudo_fallback`, `detection_scores`, `unsupervised`: 차단
- `positive_count`
  - `0`: hard fail
  - `< supervised_min_positive`: hard fail
- `positive_rate`
  - `< supervised_min_positive_rate`: hard fail
- `label_quality`
  - 1차에서는 `ground_truth`이면 `trusted`, pseudo 계열이면 `circular_risk`, no-label이면 `absent`
- `label_origin`
  - DataSynth / embedded GT / pseudo fallback 정도만 구분

### Persistence / Observability

- `ModelRegistry` metadata에 supervised gate snapshot을 남긴다.
  - `label_source`
  - `positive_count`
  - `positive_rate`
  - `gate_status`
  - `gate_reason`
- `PipelineResult.detector_statuses`에도 supervised skip reason을 넣는다.
- 향후 dashboard는 이 reason을 그대로 표기할 수 있게 한다.

## Implementation Phases

### Phase 1: Gate Policy와 설정 외부화 (0.5일)

**Goal**: 하드코딩된 supervised 기준을 설정과 공통 정책으로 끌어올린다.

- [ ] Task 1-1 - `config/settings.py` - `supervised_min_positive`, `supervised_min_positive_rate`, `supervised_allowed_label_sources` 추가 - Size: S
- [ ] Task 1-2 - `src/preprocessing/label_strategy.py` - gate 판정에 필요한 메타 필드 초안 정의 - Size: S
- [ ] Task 1-3 - `tests/modules/test_preprocessing/test_label_strategy.py` - 새 기본값과 메타 필드 기대값 추가 - Size: S

### Phase 2: LabelResult 자격 판정 구조화 (0.5~1일)

**Goal**: create_labels 결과가 supervised 적합성까지 설명하도록 만든다.

- [ ] Task 2-1 - `src/preprocessing/label_strategy.py` - `positive_count`, `label_quality`, `gate_status`, `gate_reason`, `is_supervised_eligible` 필드 추가 - Size: M
- [ ] Task 2-2 - `src/preprocessing/label_strategy.py` - `_from_datasynth`, `_from_pseudo`, `_hybrid`가 각 출처별 gate 판정을 채우도록 수정 - Size: M
- [ ] Task 2-3 - `tests/modules/test_preprocessing/test_label_strategy.py` - datasynth/pseudo/hybrid별 gate 판정 테스트 추가 - Size: M

### Phase 3: SupervisedDetector 학습 게이트 강제 (1일)

**Goal**: 경고 기반 검사를 실제 학습 차단 규칙으로 바꾼다.

- [ ] Task 3-1 - `src/detection/supervised_detector.py` - `_validate_labels()`를 `warnings + gate decision` 구조로 개편 - Size: M
- [ ] Task 3-2 - `src/detection/supervised_detector.py` - gate 실패 시 전용 예외 또는 명시적 ValueError로 학습 차단 - Size: M
- [ ] Task 3-3 - `src/detection/supervised_detector.py` - `train()` 반환 메타에 gate snapshot 포함 - Size: S
- [ ] Task 3-4 - `src/detection/supervised_detector.py` - `save_model()` metadata에 gate snapshot 저장 - Size: S
- [ ] Task 3-5 - `tests/modules/test_detection/test_supervised_detector.py` - pseudo label 차단, low positive 차단, GT 통과 케이스 테스트 추가 - Size: M

### Phase 4: Pipeline fallback과 운영 상태 연결 (1일)

**Goal**: supervised gate 실패가 운영 경로에서 모호한 예외가 아니라 명시적 fallback으로 보이게 만든다.

- [ ] Task 4-1 - `src/pipeline.py` - supervised detector skip reason vocabulary 정의 (`insufficient_positive_count`, `low_positive_rate`, `untrusted_label_source`, `circular_label_risk`) - Size: S
- [ ] Task 4-2 - `src/pipeline.py` - training 또는 runtime gate 불충족 시 `ml_supervised`를 skipped로 기록하고 `ml_unsupervised` 경로를 유지하도록 연결 - Size: M
- [ ] Task 4-3 - `src/pipeline.py` - detector status metadata에 gate reason, training provenance, model evaluation confidence를 실어 나르도록 보강 - Size: M
- [ ] Task 4-4 - `tests/modules/test_pipeline/test_pipeline.py` 또는 신규 `test_ml_gate.py` - supervised skip/fallback 상태 검증 추가 - Size: M

### Phase 5: 모델 메타와 문서 정리 (0.5일)

**Goal**: 저장된 모델과 운영 화면이 같은 언어로 게이트 상태를 설명하게 만든다.

- [ ] Task 5-1 - `src/preprocessing/model_registry.py` - registry metadata 필드 추가 및 하위 호환 유지 - Size: S
- [ ] Task 5-2 - `tests/modules/test_preprocessing/test_model_registry.py` - gate metadata 저장/복원 테스트 추가 - Size: S
- [ ] Task 5-3 - `docs/개선사항.md` - 3.4 구현 반영 또는 후속 상태 갱신 - Size: S

## Detailed Design

### New LabelResult Shape

`LabelResult` 확장 초안:

- `y: np.ndarray`
- `strategy: str`
- `label_source: str`
- `positive_count: int`
- `positive_rate: float`
- `label_quality: str`
- `gate_status: str`
- `gate_reason: str | None`
- `is_supervised_eligible: bool`
- `source_breakdown: dict | None`

### Gate Decision Semantics

- `gate_status="eligible"`
  - supervised 학습 가능
- `gate_status="fallback_to_unsupervised"`
  - supervised 차단, unsupervised만 사용
- `gate_status="blocked"`
  - 학습/저장 모두 금지. 상위 호출부가 명시적으로 처리해야 함

1차에서는 `blocked`와 `fallback_to_unsupervised`를 사실상 같은 의미로 사용해도 되지만, 모델 학습 파이프라인과 운영 추론 파이프라인을 분리하기 위해 값은 분리해 두는 편이 안전하다.

### Exception Strategy

`SupervisedDetector.train()` 내부에서는 전용 예외 클래스를 두는 편이 가장 깔끔하다.

- 예시: `SupervisedGateError(reason: str, snapshot: dict)`
- 장점:
  - pipeline이 문자열 파싱 없이 reason 코드를 읽을 수 있다.
  - 테스트가 메시지 문자열에 덜 민감해진다.
  - 향후 transformer / sequence detector에도 동일 정책을 재사용 가능하다.

1차 구현 범위에 예외 클래스 추가가 과하다고 판단되면 `ValueError` + `code` 속성 부여로 시작해도 된다.

## Risk Assessment

- **High Risk**: pseudo label 차단을 너무 늦게 적용하면 기존 training flow가 이미 저장한 supervised 모델과 의미가 어긋날 수 있다.
  - Mitigation: 새 gate metadata를 저장하고, 로드 시 metadata가 없는 legacy 모델은 `unknown_training_gate`로 표시한다.

- **High Risk**: 학습 차단만 하고 pipeline status를 안 붙이면 운영자는 "모델이 왜 안 도는지" 알 수 없다.
  - Mitigation: pipeline detector status reason vocabulary를 함께 구현한다.

- **Medium Risk**: `SupervisedDetector`만 강화하고 `TransformerDetector`, `SequenceDetector`는 그대로 두면 ML 계열 정책이 일관되지 않는다.
  - Mitigation: 이번 범위는 문서상 `supervised ML`에 맞춰 ML01만 우선 적용하고, 후속 3.4x 작업으로 동일 gate를 ML03/ML04에 확장한다.

- **Medium Risk**: gate 기준을 코드 상수에서 settings로 옮기면 테스트 fixture가 기존 기본값에 의존할 수 있다.
  - Mitigation: 새 설정은 기존 상수와 동일한 기본값으로 시작하고, 테스트는 명시적으로 fixture 값을 세팅한다.

## Success Metrics

- pseudo 또는 pseudo_fallback label로는 supervised 모델이 학습되지 않는다.
- `positive_count < threshold` 또는 `positive_rate < threshold`면 supervised 학습이 실패하고 명시적 reason이 남는다.
- pipeline detector status에서 `ml_supervised` skip reason을 바로 확인할 수 있다.
- ModelRegistry metadata만 읽어도 저장된 supervised 모델의 라벨 출처와 게이트 판정을 알 수 있다.

## Dependencies

- Code: `config/settings.py`, `src/preprocessing/label_strategy.py`, `src/detection/supervised_detector.py`, `src/preprocessing/model_registry.py`, `src/pipeline.py`
- Tests: `tests/modules/test_preprocessing/test_label_strategy.py`, `tests/modules/test_detection/test_supervised_detector.py`, `tests/modules/test_preprocessing/test_model_registry.py`, `tests/modules/test_pipeline/test_pipeline.py`
- External: 없음
