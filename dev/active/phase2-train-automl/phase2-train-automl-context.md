# Phase2 Train AutoML - Context & Decisions

## Status
- Phase: Sprint A2 완료
- Progress: 24 / 31 tasks complete
- Last Updated: 2026-05-17

## Key Files
**Modified**:
- `src/pipeline.py` - 현재 bootstrap 기반 phase2 cold-start 경로
- `src/services/analysis_service.py` - 현재 phase1/phase2 추론 orchestration
- `src/services/session_service.py` - 현재 dashboard 표시 결과 우선순위
- `dashboard/tab_overview.py` - 현재 phase 단계형 UI 진입점
- `dashboard/tab_phase2.py` - 현재 phase2 상태/모델 메타 렌더링

**New**:
- `src/services/phase2_training_service.py` - phase2-train orchestration
- `src/services/phase2_training_models.py` - trial/result/report dataclass
- `tests/modules/test_services/test_phase2_training_service.py` - 학습 서비스 단위 테스트
- `dev/active/phase2-train-automl/phase2-train-automl-plan.md` - 전략 계획
- `dev/active/phase2-train-automl/phase2-train-automl-tasks.md` - 작업 체크리스트

## Key Decisions
1. **phase2-train과 phase2-infer를 분리한다** (2026-04-18)
   - Rationale: 현재 `src/pipeline.py`의 bootstrap 경로는 cold-start 보완용이지 정식 학습 파이프라인이 아니다.
   - Alternatives: `_try_ml_detection()` 내부에서 trial 탐색까지 수행
   - Trade-offs: 서비스 계층 파일이 늘어나지만, 추론 코드가 단순해지고 UI와 결합이 줄어든다.

2. **trial artifact와 promoted model artifact를 분리한다** (2026-04-18)
   - Rationale: `ModelRegistry`는 현재 운영용 best model 저장소 역할이다. trial 전체를 같이 넣으면 버전 의미가 흐려진다.
   - Alternatives: registry에 모든 trial 저장
   - Trade-offs: 별도 training report 저장 포맷이 필요하지만, 운영 추론과 실험 로그의 경계가 명확해진다.

3. **feature family ablation을 AutoML의 1차 탐색 축으로 채택한다** (2026-04-18)
   - Rationale: `src/preprocessing/feature_quality.py`에 이미 `ablation_plan`이 존재하며, 현재는 실제 학습 탐색에 연결되지 않는다.
   - Alternatives: 하이퍼파라미터만 탐색하고 feature variant는 고정
   - Trade-offs: trial 수가 늘어나지만, sparse optional feature 때문에 성능이 흔들리는 문제를 직접 다룰 수 있다.

4. **stacking은 `train_oof()`를 정식 학습 경로로 사용한다** (2026-04-18)
   - Rationale: `train_from_results()`는 leakage가 있고, 이미 `EnsembleDetector.train_oof()`가 GroupKFold 기반 OOF 학습을 지원한다.
   - Alternatives: 간단한 `train_from_results()` 유지
   - Trade-offs: 학습 시간은 늘어나지만, 실제 배포 모델로 쓸 수 있는 품질을 확보할 수 있다.

5. **bootstrap은 제거하지 않고 신규 학습 서비스의 축약 모드로 축소한다** (2026-04-18)
   - Rationale: 첫 실행 UX는 여전히 필요하다.
   - Alternatives: bootstrap 완전 제거
   - Trade-offs: 두 경로가 남지만, 구현체는 하나의 서비스로 합쳐져 중복이 줄어든다.

## Known Issues
- 현재 `dashboard/tab_overview.py`와 `dashboard/tab_phase2.py`는 진행 상태 문구를 UI에서 고정 문자열로 만든다. 실제 AutoML trial 상태를 표시하려면 training report event stream이 필요하다.
- 현재 `src/pipeline.py`의 bootstrap helper는 detector train API를 직접 호출한다. phase2-train 도입 후에는 thin wrapper로 축소해야 한다.
- `docs/pre-plan` 경로는 현재 워크스페이스에 없어서 과거 ML 설계 문서를 직접 참조하지 못했다. 이번 계획은 코드베이스 현재 상태 기준이다.
- `src/__init__.py`에 `src/pipeline.py`의 중복 코드가 남아 있다. 구현 전 ripple search로 실제 import 경로를 재확인해야 한다.

## Sprint A2 Results (2026-05-17)

Sprint A2는 A1 `supervised_gate` 계약을 전제로 PHASE2 학습/추론 산출물 경계를 고정했다. `run_phase2_training()`은 label gate 평가, feature variant 생성, family/preset trial 실행, leaderboard 정렬, promotion policy 적용, inference contract 생성까지 담당한다. `run_phase2_inference()`는 최신 training snapshot의 promoted version contract만 pipeline에 전달하며, cold-start bootstrap 상태를 추론 모드로 승격하지 않는다.

새 산출물:
- `leaderboard.json`: `family`, `trial`, `preset`, `status`, `metric`, `artifact_path`, `model_version`, `schema_hash`를 row 단위로 저장한다.
- `promotion_decision.json`: promotion policy와 family별 승격/탈락 사유, promoted model 목록을 감사 가능한 JSON으로 저장한다.
- `inference_contract.model_versions`: model별 `model_version`, `source_trial_variant`, `schema_hash`, `fixture_contract`를 담는다.

신규 모듈:
- `src/services/phase2_leaderboard.py`
- `src/services/phase2_promotion_policy.py`

경로 계약:
- training run: `{model_dir}/phase2_train/{report_id}/`
- reports: `{model_dir}/phase2_train/{report_id}/reports/{training_report.json,leaderboard.json,promotion_decision.json}`
- trial artifacts: `{model_dir}/phase2_train/{report_id}/trials/*.json`
- promoted family artifact target: `data/companies/{company_id}/engagements/{year}/models/phase2_<family>/vNNNN/`

검증:
- `uv run pytest tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_training_service.py -q` -> 45 passed
- `uv run pytest tests/modules/test_preprocessing/test_label_strategy.py tests/modules/test_detection/test_supervised_detector.py tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_layer_a_guards.py tests/modules/test_services/test_phase2_case_contract.py -q` -> 83 passed
- touched-file ruff check -> PASS
- focused cold-start grep over `src/pipeline.py`, `src/services/phase2_inference_service.py`, and inference tests -> 0 matches
