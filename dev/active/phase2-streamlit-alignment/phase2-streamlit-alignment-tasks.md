# Phase2 Streamlit Alignment - Task Checklist

## Progress Summary
24 / 24 tasks complete (100%)

## Phase 1: Contract and Path Baseline
- [x] 현재 Phase2 버튼의 inference-only 동작을 테스트로 기록
  - File: `tests/modules/test_dashboard/test_tab_phase2.py`
  - Details: `_start_phase2_analysis()`가 training service가 아니라 `run_phase2_inference_analysis()`를 호출하는 기대를 명시한다.
  - Acceptance: 테스트가 현재 동작을 설명하는 이름으로 존재하고 통과한다.
  - Size: S

- [x] 최신 training snapshot 선택 규칙을 테스트로 고정
  - File: `tests/modules/test_services/test_phase2_inference_service.py`
  - Details: 여러 `training_report.json`이 있을 때 수정 시간이 가장 최신인 report를 선택하는지 검증한다.
  - Acceptance: 최신 report id와 contract가 result에 붙는다.
  - Size: S

- [x] 회사/engagement별 model registry 결정을 context에 기록
  - File: `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-context.md`
  - Details: `ctx.model_dir`를 기준으로 training snapshot과 detector model load를 정렬한다고 기록한다.
  - Acceptance: Key Decisions에 registry path 결정이 있다.
  - Size: S

- [x] pipeline의 기본 `ModelRegistry()` 사용 지점을 목록화
  - File: `src/pipeline.py`
  - Details: `_try_ml_detection()`과 `_try_stacking_ensemble()`의 registry 생성 지점을 확인한다.
  - Acceptance: 변경 대상 함수와 필요한 주입 방식이 구현 메모에 기록된다.
  - Size: S

## Phase 2: Service API Alignment
- [x] Streamlit용 `run_phase2_training_analysis(state)` 추가
  - File: `src/services/phase2_training_service.py`
  - Details: session_state 기반으로 prep data, context, settings를 꺼내 `run_phase2_training()`을 호출한다.
  - Acceptance: fake state로 training report를 반환하는 단위 테스트가 통과한다.
  - Size: M

- [x] training entrypoint의 입력 DataFrame 선택 규칙 구현
  - File: `src/services/phase2_training_service.py`
  - Details: `prep_result.featured_data`가 있으면 우선 사용하고 없으면 `prep_result.data`를 사용한다.
  - Acceptance: 두 입력 케이스가 각각 테스트된다.
  - Size: M

- [x] Phase2 training report session key 추가
  - File: `dashboard/_state.py`
  - Details: `KEY_PHASE2_TRAINING_REPORT_ID` 또는 동등한 이름을 추가하고 `_DEFAULTS`에 `None`을 넣는다.
  - Acceptance: `init_state()` 후 key가 존재한다.
  - Size: S

- [x] training snapshot 조회 helper 정리
  - File: `src/services/phase2_inference_service.py`
  - Details: UI가 latest report summary를 읽을 수 있도록 report id, contract, policy를 반환하는 public helper를 유지한다.
  - Acceptance: helper 단위 테스트가 snapshot payload를 반환한다.
  - Size: M

- [x] pipeline ML detector registry 경로를 context 기반으로 변경
  - File: `src/pipeline.py`
  - Details: context가 있고 anonymous가 아니면 `ModelRegistry(registry_dir=self._ctx.model_dir)`를 사용한다.
  - Acceptance: fake context model_dir로 registry가 생성되는 테스트가 통과한다.
  - Size: L

## Phase 3: Streamlit UX Alignment
- [x] Phase2 상태 배지 렌더링 함수 추가
  - File: `dashboard/tab_phase2.py`
  - Details: `phase2_inference_mode`, `phase2_training_report_id`, contract 유무를 표시하는 helper를 만든다.
  - Acceptance: helper가 mode별 label을 반환하는 테스트가 통과한다.
  - Size: M

- [x] 학습 리포트 없음 상태에서 버튼 분리
  - File: `dashboard/tab_phase2.py`
  - Details: `Phase 2 학습 실행`과 `추론-only 실행`을 별도 버튼으로 표시한다.
  - Acceptance: result가 없고 snapshot도 없을 때 두 action이 구분된다.
  - Size: M

- [x] 학습 리포트 있음 상태에서 promoted model 요약 표시
  - File: `dashboard/tab_phase2.py`
  - Details: `required_models`, `promoted_versions`, `selection_mode`를 작은 table 또는 dataframe으로 표시한다.
  - Acceptance: snapshot fixture로 model/version summary dataframe이 생성된다.
  - Size: M

- [x] 추론 버튼 문구 변경
  - File: `dashboard/tab_phase2.py`
  - Details: 기존 `Phase 2 분석 시작` 문구를 실제 동작에 맞게 `저장된 모델로 Phase 2 추론`으로 바꾼다.
  - Acceptance: 버튼 label 테스트 또는 snapshot test가 새 문구를 기대한다.
  - Size: S

- [x] Phase1 화면의 Phase2 이동 action 정렬
  - File: `dashboard/tab_phase1.py`
  - Details: Phase1에서 직접 `_start_phase2_analysis()`를 호출하는 위치가 새 action 정책을 사용하도록 바꾼다.
  - Acceptance: Phase1 action이 Phase2 tab 전환 상태 key를 유지한다.
  - Size: M

## Phase 4: Persistence and Restore Consistency
- [x] inference provenance 저장 검증 강화
  - File: `src/services/phase2_inference_service.py`
  - Details: `_persist_phase2_batch_snapshot()`이 report id, contract, policy, mode를 모두 전달하는지 테스트한다.
  - Acceptance: fake `update_upload_batch_meta` 호출 인자가 모두 검증된다.
  - Size: S

- [x] DB batch reader provenance 복원 테스트 추가
  - File: `tests/modules/test_db/test_batch_reader.py`
  - Details: `phase2_training_report_id`, `phase2_inference_contract`, `phase2_promotion_policy`, `phase2_inference_mode` 복원을 검증한다.
  - Acceptance: `load_batch()` 결과 attribute가 저장값과 일치한다.
  - Size: M

- [x] 읽기 전용 DB 로드 결과의 Phase2 action 정책 명시
  - File: `dashboard/tab_phase2.py`
  - Details: `KEY_LOADED_FROM_DB`가 true이면 provenance 표시를 우선하고 재실행 버튼을 숨기거나 안내한다.
  - Acceptance: read-only state에서 실행 버튼이 표시되지 않는다.
  - Size: M

- [x] export provenance formatter 테스트 추가
  - File: `tests/modules/test_export/test_analysis_status.py`
  - Details: 세 mode `training_contract`, `untrained_contract_only`, `cold_start_bootstrap` 표시를 검증한다.
  - Acceptance: 각 mode가 구분 가능한 문자열로 export status에 포함된다.
  - Size: M

## Phase 5: Verification and Documentation
- [x] Phase2 운영 정의 문서 갱신
  - File: `docs/PHASE_PROVENANCE.md`
  - Details: Streamlit에서는 학습과 추론이 분리되어 표시된다는 내용을 반영한다.
  - Acceptance: 문서에 train/infer/UI state 정의가 모두 있다.
  - Size: S

- [x] 기존 Phase2 작업과 이번 작업의 책임 경계 문서화
  - File: `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-context.md`
  - Details: AutoML 품질 개선은 기존 `phase2-train-automl`, UI/service alignment는 이번 작업이라고 명시한다.
  - Acceptance: Known Issues 또는 Key Decisions에 책임 경계가 있다.
  - Size: S

- [x] Phase2 dashboard 테스트 갱신
  - File: `tests/modules/test_dashboard/test_tab_phase2.py`
  - Details: 상태 badge, button label, promoted model summary helper를 검증한다.
  - Acceptance: phase2 dashboard 테스트가 통과한다.
  - Size: M

- [x] Phase2 service 테스트 갱신
  - File: `tests/modules/test_services/test_phase2_training_service.py`
  - Details: `run_phase2_training_analysis()`의 state 입력과 report 반환을 검증한다.
  - Acceptance: phase2 training service 테스트가 통과한다.
  - Size: M

- [x] Phase2 alignment smoke 테스트 실행
  - File: `tests/modules/test_dashboard/test_tab_phase2.py`
  - Details: `.venv\Scripts\pytest.exe tests\modules\test_dashboard\test_tab_phase2.py tests\modules\test_services\test_phase2_inference_service.py -q`를 실행한다.
  - Acceptance: 두 테스트 파일이 통과하거나 실패 원인이 문서화된다.
  - Size: S

## Deployment Checklist
- [x] Streamlit에서 Phase2 학습/추론 버튼이 분리되어 보인다.
  - Evidence: `dashboard/tab_phase2.py` renders `Phase 2 학습 실행` and `저장된 모델로 Phase 2 추론`; `dashboard.app` import passed; `http://localhost:8501` returned 200.
- [x] 학습 리포트가 없을 때 UI가 contract 없음 상태를 명확히 표시한다.
  - Evidence: `_render_training_snapshot_summary()` displays `저장된 Phase 2 학습 리포트가 없습니다.` when no snapshot exists.
- [x] 학습 리포트가 있을 때 promoted model summary가 표시된다.
  - Evidence: `test_build_promoted_model_frame_summarizes_contract` passed.
- [x] Phase2 추론 후 DB reload에서 같은 provenance가 복원된다.
  - Evidence: `TestLoadBatch::test_restore_phase2_contract_snapshot` passed.
- [x] Export/analysis status에서 inference mode가 구분된다.
  - Evidence: `test_build_phase_provenance_lines_distinguishes_phase2_inference_modes` passed.
- [x] 관련 pytest smoke가 통과한다.
  - Evidence: Phase2 alignment smoke passed: `36 passed`.

## Sprint UI-A4 Checklist (2026-05-18)

- [x] Phase A handoff 7개와 active plan 3개 정독.
- [x] Diag-1 GO-WITH-CAVEAT와 Diag-2 GO 진입 조건 확인.
- [x] Phase2 사용자-facing 3 상태 UI 분기 구현.
- [x] 학습/추론 버튼 분리 유지.
- [x] 9 family matrix 컴포넌트 추가.
- [x] 13 sub-detector grid 컴포넌트 추가.
- [x] 2022/2023/2024/전체 partition selector 추가 및 inference filter 전달.
- [x] leaderboard/promotion_decision sidecar 표시 컴포넌트 추가.
- [x] ECDF q95 high count와 `rule_proxy_score` 라벨 표시. truth recall 라벨 미사용.
- [x] PHASE1 result UI 파일 변경 금지 준수.
- [x] duplicate performance guard 재실행.
- [x] 완료 handoff 작성.
