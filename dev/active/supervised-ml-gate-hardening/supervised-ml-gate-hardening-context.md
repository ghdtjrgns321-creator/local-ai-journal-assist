# Supervised ML Gate Hardening - Context & Decisions

## Status

- Phase: Sprint A1 완료
- Progress: 11 / 15 tasks complete
- Last Updated: 2026-05-17

## Key Files

**Modified**:
- 없음

**Planned**:
- `config/settings.py` - supervised gate 설정값 추가
- `src/preprocessing/label_strategy.py` - 라벨 메타와 supervised 적합성 판정
- `src/detection/supervised_detector.py` - hard gate enforcement
- `src/preprocessing/model_registry.py` - gate snapshot metadata 저장
- `src/pipeline.py` - supervised skip reason / unsupervised fallback 연결

**New**:
- 필요 시 `src/detection/exceptions.py` 또는 `src/preprocessing/ml_gate.py`
- 필요 시 `tests/modules/test_pipeline/test_ml_gate.py`

## Key Decisions

1. **라벨 출처는 게이트의 1급 입력으로 취급한다 (2026-04-16)**
   - Rationale: 현재 문서 요구사항의 핵심은 "라벨 수 부족"보다 "pseudo label 순환학습 위험" 차단이다. 따라서 positive count보다 먼저 label source를 정책에 넣어야 한다.
   - Alternatives: positive count / positive rate만 강화하는 방법도 있지만, pseudo label이 충분히 많아도 순환 위험은 남는다.
   - Trade-offs: 1차 구현에서 supervised 사용 가능 케이스가 줄어든다. 대신 운영 해석 가능성이 올라간다.

2. **warning이 아니라 hard gate로 승격한다 (2026-04-16)**
   - Rationale: 현재 `_validate_labels()`는 저품질 라벨에도 학습을 계속 진행해 모델이 저장된다. 운영 안전장치라면 학습 자체를 막아야 한다.
   - Alternatives: warnings만 강화하고 UI 표시만 추가. 하지만 이 방식은 잘못된 모델 버전 생성을 막지 못한다.
   - Trade-offs: 일부 기존 실험 흐름이 깨질 수 있다. 테스트와 예외 메시지 정리가 필요하다.

3. **runtime status와 training gate를 같은 reason vocabulary로 맞춘다 (2026-04-16)**
   - Rationale: 학습 단계에서는 `low_positive_rate`, 운영 단계에서는 `missing_trained_model`처럼 단어가 분리되면 UI와 로그가 일관되지 않는다.
   - Alternatives: 각 계층이 자유 문자열 사용. 하지만 유지보수와 테스트가 어려워진다.
   - Trade-offs: 공통 reason set을 합의해야 하지만 이후 확장이 쉬워진다.

4. **1차 범위는 ML01에 한정하고, 다른 supervised ML 계열은 후속으로 확장한다 (2026-04-16)**
   - Rationale: 문서 섹션은 "supervised ML 게이트 강화"지만, 현재 코드베이스에는 `TransformerDetector`, `SequenceDetector`, `EnsembleDetector`까지 연결돼 있다. 한 번에 모두 건드리면 범위가 커지고 회귀 위험이 높다.
   - Alternatives: ML01/ML03/ML04를 동시에 통일. 하지만 테스트 범위가 급격히 커진다.
   - Trade-offs: 1차 정책 일관성은 일부만 확보된다. 대신 ML01에서 정책을 검증한 뒤 확장할 수 있다.

## Known Issues

- `dev/README.md`는 현재 repo에 없다. 이번 계획은 `CLAUDE.md`와 기존 `dev/active/*` 문서 형식을 기준으로 작성했다.
- 현재 코드베이스에서 supervised training orchestration 전용 서비스는 분리돼 있지 않다. 실제 gate enforcement는 `SupervisedDetector.train()` 쪽부터 시작하는 것이 가장 안전하다.
- `TransformerDetector`, `SequenceDetector`도 사실상 supervised label을 사용하지만 이번 문서 범위에는 직접 포함되지 않는다.
- legacy supervised 모델에는 gate metadata가 없으므로, 로드 후 provenance 표시에 `unknown_training_gate` 같은 하위 호환 처리가 필요하다.

## Open Questions

1. supervised gate 실패를 `ValueError`로 둘지, 전용 `SupervisedGateError`로 둘지 구현 시점에 결정해야 한다.
2. runtime에서 legacy supervised 모델을 발견했을 때 바로 차단할지, `unknown` 경고와 함께 실행 허용할지 운영 정책이 필요하다.
3. 이번 턴에서 ML01만 적용한 뒤 ML03/ML04까지 같은 정책을 즉시 확장할지 후속 작업으로 분리할지 결정해야 한다.

## Sprint A1 Results (2026-05-17)

Sprint A1은 label_strategy -> supervised_detector -> Phase2 training report까지 supervised gate를 구조화했다. `LabelResult`는 `quality_grade`, `gate_decision`, `gate_reason`을 노출하며, 기존 `label_quality`, `gate_status`는 하위 호환 별칭으로 유지한다. GateDecision 값은 `eligible`, `low_signal_fallback`, `hard_fail`, `unavailable` 네 가지로 고정했다.

Low-signal 기준은 `positive_count < 50` 또는 `positive_rate < 0.01`이다. trusted ground truth라도 기준 미달이면 `low_signal_fallback`으로 supervised 학습 대상에서 제외된다. pseudo/pseudo_fallback은 `circular_label_risk`, unsupervised/no-label은 `missing_ground_truth_labels`로 구조화된다.

`SupervisedDetector.train()`은 `SupervisedGateError`를 통해 gate 실패를 학습 전에 차단하고, 성공 시 model registry metadata에 gate snapshot을 저장한다. `run_phase2_training()`은 supervised gate 실패 trial을 `skipped`로 기록하고 `trial.metadata.supervised_gate`에 snapshot을 남기며, `training_report.json` 최상위에는 `supervised_gate` 필드를 추가한다.

검증:
- `uv run pytest tests/modules/test_preprocessing/test_label_strategy.py tests/modules/test_detection/test_supervised_detector.py tests/modules/test_services/test_phase2_training_service.py -q` -> 63 passed
- `uv run pytest tests/modules/test_services/test_phase2_layer_a_guards.py tests/modules/test_services/test_phase2_case_contract.py tests/modules/test_detection/test_supervised_detector.py -q` -> 37 passed
- Combined focused regression -> 82 passed
- Touched-file ruff check -> PASS

Git diff 확인은 사용자 hook이 git 명령을 차단하여 수행하지 못했다. 파일 검토는 `rg`와 직접 파일 읽기로 대체했다.
