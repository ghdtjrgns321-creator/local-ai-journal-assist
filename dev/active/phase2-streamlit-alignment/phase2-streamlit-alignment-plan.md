# Phase2 Streamlit Alignment - Strategic Plan

## Executive Summary
현재 Phase2는 설계상 `phase2-train`과 `phase2-infer`가 분리되어 있지만, Streamlit은 `phase2-infer`만 실행하는 화면으로 남아 있다. 이 작업은 Phase2의 운영 정의를 "학습 리포트 기반 추론"으로 고정하고, Streamlit이 학습 상태, 추론 모드, 모델/contract provenance를 정확히 보여주도록 맞춘다.

## Current State
- `src/services/phase2_training_service.py`에는 AutoML 학습 orchestration, leaderboard, promotion policy, inference contract 생성 로직이 있다.
- `src/services/phase2_inference_service.py`는 최신 `training_report.json`을 읽고 `AuditPipeline.redetect(..., detection_scope="phase2_only")`를 실행한다.
- `dashboard/tab_phase2.py`의 primary button은 학습을 실행하지 않고 `run_phase2_inference_analysis()`만 호출한다.
- `src/pipeline.py`의 ML detector load는 `ModelRegistry()` 기본 경로를 사용하므로 회사/engagement별 `ctx.model_dir`와 불일치할 가능성이 있다.
- Streamlit UI는 Phase2를 "분석 시작"으로 표현하지만, 실제로는 저장된 모델 contract가 있으면 contract 기반 추론, 없으면 untrained/cold-start 상태를 표시하는 과도기 구조다.

## Proposed Solution
- Phase2의 사용자-facing 구조를 세 단계로 명확히 분리한다.
  - `Not trained`: 학습 리포트 없음. 사용자는 학습 실행 또는 추론-only 실행 여부를 명확히 선택한다.
  - `Training report available`: 최신 report, promoted models, inference contract, promotion policy를 표시한다.
  - `Inference complete`: 어떤 report/contract/mode로 추론했는지 Phase2 결과에 고정 표시한다.
- Streamlit은 학습과 추론을 같은 버튼으로 숨기지 않는다.
  - `Phase 2 학습 실행`: `run_phase2_training()`을 호출하고 report를 저장한다.
  - `저장된 모델로 Phase 2 추론`: `run_phase2_inference_analysis()`를 호출한다.
- `ModelRegistry` 경로를 회사/engagement별 `ctx.model_dir`로 정렬한다.
- DB restore/export/Phase3에서 동일한 `phase2_training_report_id`, `phase2_inference_contract`, `phase2_inference_mode`, `phase2_promotion_policy`를 사용하게 한다.

## Implementation Phases

### Phase 1: Contract and Path Baseline (0.5 day) - Complete
**Goal**: 현재 괴리의 기준점을 테스트로 고정하고 모델 저장/로드 경로 결정을 확정한다.
**Tasks**:
- [ ] Streamlit Phase2 버튼이 inference만 실행하는 현재 동작을 테스트로 기록 - File: `tests/modules/test_dashboard/test_tab_phase2.py` - Size: S
- [ ] `load_latest_phase2_training_snapshot()`의 report 선택 규칙을 테스트로 고정 - File: `tests/modules/test_services/test_phase2_inference_service.py` - Size: S
- [ ] `ModelRegistry`가 회사/engagement별 `ctx.model_dir`를 사용해야 한다는 결정을 context 문서에 기록 - File: `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-context.md` - Size: S
- [ ] `src/pipeline.py`의 `ModelRegistry()` 기본 경로 사용 지점을 목록화 - File: `src/pipeline.py` - Size: S

### Phase 2: Service API Alignment (1 day) - Complete
**Goal**: Dashboard가 학습과 추론을 명확히 호출할 수 있는 service entrypoint를 제공한다.
**Tasks**:
- [ ] `run_phase2_training_analysis(state)` entrypoint 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `run_phase2_training_analysis()`가 `KEY_PREP_RESULT`, `KEY_COMPANY_CONTEXT`, `KEY_SETTINGS`를 사용하도록 구현 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] 학습 완료 후 `phase2_training_report_id`를 session_state에 저장할 key 추가 - File: `dashboard/_state.py` - Size: S
- [ ] 학습 report 조회 helper를 inference service에서 재사용 가능하게 정리 - File: `src/services/phase2_inference_service.py` - Size: M
- [ ] 회사 context가 있을 때 pipeline ML detector에 `ctx.model_dir` registry를 전달하는 경로 추가 - File: `src/pipeline.py` - Size: L

### Phase 3: Streamlit UX Alignment (1 day) - Complete
**Goal**: Phase2 탭이 현재 상태와 가능한 행동을 정확히 보여주게 한다.
**Tasks**:
- [ ] Phase2 탭 상단에 inference mode/report id/contract 유무 상태 배지 추가 - File: `dashboard/tab_phase2.py` - Size: M
- [ ] 학습 리포트가 없을 때 `Phase 2 학습 실행`과 `추론-only 실행`을 별도 버튼으로 분리 - File: `dashboard/tab_phase2.py` - Size: M
- [ ] 학습 리포트가 있을 때 promoted model과 promotion policy 요약 표시 - File: `dashboard/tab_phase2.py` - Size: M
- [ ] 추론 실행 버튼 문구를 `저장된 모델로 Phase 2 추론`으로 변경 - File: `dashboard/tab_phase2.py` - Size: S
- [ ] Phase1 결과 화면의 `Phase2로 이동/실행` 버튼이 새 Phase2 entrypoint와 같은 상태 전이를 사용하게 변경 - File: `dashboard/tab_phase1.py` - Size: M

### Phase 4: Persistence and Restore Consistency (0.5 day) - Complete
**Goal**: 실행 후 저장, DB reload, export에서 같은 Phase2 provenance가 복원되게 한다.
**Tasks**:
- [ ] `update_upload_batch_meta()` 호출 시 training report id와 inference contract 저장 검증 강화 - File: `src/services/phase2_inference_service.py` - Size: S
- [ ] DB batch reader가 Phase2 provenance를 `PipelineResult`에 복원하는 테스트 추가 - File: `tests/modules/test_db/test_batch_reader.py` - Size: M
- [ ] read-only DB 로드 결과에서 Phase2 재학습/재추론 버튼 정책을 명시 - File: `dashboard/tab_phase2.py` - Size: M
- [ ] export provenance formatter가 `training_contract`, `untrained_contract_only`, `cold_start_bootstrap`을 구분 표시하도록 검증 - File: `tests/modules/test_export/test_analysis_status.py` - Size: M

### Phase 5: Verification and Documentation (0.5 day) - Complete
**Goal**: 설계 문서, Streamlit 동작, 테스트가 같은 Phase2 정의를 말하게 한다.
**Tasks**:
- [ ] Phase2 운영 정의를 `docs/PHASE_PROVENANCE.md`에 갱신 - File: `docs/PHASE_PROVENANCE.md` - Size: S
- [ ] 기존 `phase2-train-automl` 문서와 이번 alignment 문서의 책임 경계를 명시 - File: `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-context.md` - Size: S
- [ ] Phase2 dashboard 테스트 추가/갱신 - File: `tests/modules/test_dashboard/test_tab_phase2.py` - Size: M
- [ ] Phase2 service 테스트 추가/갱신 - File: `tests/modules/test_services/test_phase2_training_service.py` - Size: M
- [ ] smoke 검증 명령 실행: `.venv\Scripts\pytest.exe tests\modules\test_dashboard\test_tab_phase2.py tests\modules\test_services\test_phase2_inference_service.py -q` - File: `tests/modules/test_dashboard/test_tab_phase2.py` - Size: S

## Risk Assessment
- **High Risk**: Streamlit에서 학습까지 직접 실행하면 큰 데이터에서 응답 시간이 길어질 수 있다. Mitigation: 학습 버튼은 명시적으로 분리하고, report 저장 후 rerun하는 동기식 MVP로 시작한 뒤 필요하면 background job으로 분리한다.
- **High Risk**: `ModelRegistry` 경로 불일치로 contract는 존재하지만 detector가 모델을 못 읽을 수 있다. Mitigation: `ctx.model_dir` 기반 registry 주입을 먼저 고정하고, missing model 상태를 UI에 노출한다.
- **Medium Risk**: 기존 Phase2 결과를 DB에서 불러온 읽기 전용 모드와 새 학습/추론 버튼 정책이 충돌할 수 있다. Mitigation: DB 로드 결과는 provenance 표시를 우선하고 재실행은 원본 업로드/현재 세션 데이터가 있을 때만 허용한다.
- **Medium Risk**: `phase2-train-automl`과 이번 alignment 작업의 범위가 겹칠 수 있다. Mitigation: AutoML 후보/metric 개선은 기존 작업에 남기고, 이번 작업은 Dashboard/service/path/provenance 연결만 다룬다.

## Success Metrics
- Phase2 탭에서 사용자가 현재 상태를 `not trained`, `training report available`, `inference complete` 중 하나로 즉시 구분할 수 있다.
- 학습 버튼과 추론 버튼이 분리되어, 버튼 이름과 실제 호출 service가 일치한다.
- 회사/engagement별 모델 registry에서 저장된 promoted model을 inference가 로드한다.
- Phase2 결과에는 `phase2_training_report_id`, `phase2_inference_mode`, `phase2_inference_contract`가 일관되게 표시/저장/복원된다.
- 관련 dashboard/service/db/export 테스트가 통과한다.

## Dependencies
- Code:
  - `dashboard/tab_phase2.py`
  - `dashboard/tab_phase1.py`
  - `dashboard/_state.py`
  - `src/services/phase2_training_service.py`
  - `src/services/phase2_inference_service.py`
  - `src/pipeline.py`
  - `src/preprocessing/model_registry.py`
  - `src/db/batch_reader.py`
  - `src/export/analysis_status.py`
- External:
  - existing company/engagement model directory
  - existing DuckDB `upload_batches` metadata columns
  - existing Streamlit synchronous execution model
