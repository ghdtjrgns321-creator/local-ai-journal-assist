# Phase2 Streamlit Alignment - Context & Decisions

## Status
- Phase: Implementation
- Progress: 24 / 24 tasks complete
- Last Updated: 2026-05-07

## Key Files
**Modified**:
- `dashboard/tab_phase2.py` - Phase2 상태 표시, 학습/추론 버튼 분리, 결과 provenance 표시
- `dashboard/tab_phase1.py` - Phase1에서 Phase2로 넘어가는 action을 새 Phase2 정책과 정렬
- `dashboard/_state.py` - Phase2 training report 관련 session key 추가
- `src/services/phase2_training_service.py` - Streamlit용 training entrypoint 추가
- `src/services/phase2_inference_service.py` - latest training snapshot 조회와 provenance 저장 정리
- `src/pipeline.py` - 회사/engagement별 model registry 경로 사용
- `src/db/batch_reader.py` - 저장된 Phase2 provenance 복원 검증
- `src/export/analysis_status.py` - Phase2 inference mode 표시 검증
- `docs/PHASE_PROVENANCE.md` - Phase2 운영 정의 갱신

**New**:
- `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-plan.md` - 괴리 해소 전략 계획
- `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-context.md` - 결정 및 상태 기록
- `dev/active/phase2-streamlit-alignment/phase2-streamlit-alignment-tasks.md` - 실행 체크리스트

## Key Decisions
1. **Streamlit Phase2는 학습과 추론을 분리해서 노출한다** (2026-05-07)
   - Rationale: 현재 `Phase 2 분석 시작` 버튼은 실제로 inference-only redetect를 실행하므로 사용자 기대와 다르다.
   - Alternatives: 버튼 이름만 `Phase2 추론 실행`으로 바꾸고 학습 UI는 만들지 않는 방법.
   - Trade-offs: 버튼과 상태가 늘어나지만, 실제 동작과 화면 설명이 일치한다.

2. **운영 기본값은 training report 기반 inference로 둔다** (2026-05-07)
   - Rationale: 기존 설계는 `phase2-train`이 reproducible report/contract를 만들고 `phase2-infer`가 이를 사용하는 구조다.
   - Alternatives: Phase2 클릭 시 매번 학습부터 자동 실행.
   - Trade-offs: 사용자가 학습 단계를 한 번 더 이해해야 하지만, 재현성과 provenance가 유지된다.

3. **회사/engagement별 model registry 경로를 기준으로 정렬한다** (2026-05-07)
   - Rationale: `ctx.model_dir / phase2_train`에서 snapshot을 읽으면서 detector load는 기본 `models` 경로를 쓰면 contract와 실제 모델이 어긋날 수 있다.
   - Alternatives: 모든 모델을 global `PROJECT_ROOT/models`에 저장.
   - Trade-offs: context 전달이 필요하지만 RC 구조의 engagement isolation과 맞다.

4. **이번 작업은 AutoML 품질 개선이 아니라 연결 정합성 작업이다** (2026-05-07)
   - Rationale: `phase2-train-automl`과 `phase2-detector-expansion`은 후보 family/metric/search policy를 다룬다.
   - Alternatives: AutoML 개선과 UI alignment를 한 작업으로 합친다.
   - Trade-offs: 범위를 나누면 작업은 하나 늘지만, 변경 위험과 검증 범위가 줄어든다.

## Known Issues
- `dev/README.md`는 현재 repository에 없다. 계획 문서 형식은 기존 `dev/active/*` 작업과 planner skill 규칙을 기준으로 맞춘다.
- 일부 기존 문서/소스 주석은 인코딩이 깨져 보인다. 이번 작업 문서는 UTF-8 Korean으로 새로 작성한다.
- `dashboard/tab_phase1.py`의 기존 Phase2 직접 실행 버튼은 Phase2 탭 이동으로 정렬했다. 학습/추론 선택은 Phase2 탭에서 수행한다.
- 전체 `test_pipeline.py` 실행은 일부 기존 `tmp_path` fixture가 Windows temp 권한 문제로 setup에서 실패한다. 이번 변경 검증은 관련 pipeline 테스트를 직접 지정해 실행했다.
- Streamlit 서버는 기존 프로세스가 `http://localhost:8501`에서 응답 중이며 `Invoke-WebRequest` 기준 HTTP 200을 확인했다.
- `.tmp_streamlit_stderr.log`에는 기존 `use_container_width` deprecation 경고가 남아 있다. 이번 Phase2 alignment 변경 경로의 실패 로그는 확인되지 않았다.

## Rollback Strategy
- Phase2 UI 변경은 `dashboard/tab_phase2.py`와 `dashboard/tab_phase1.py`에 집중한다. 문제가 생기면 기존 inference-only 버튼 경로로 되돌릴 수 있다.
- Registry path 변경은 테스트로 고정한 뒤 진행한다. 회사별 모델 로드가 실패하면 `ModelRegistry` 주입만 되돌리고 UI 상태 표시 변경은 유지할 수 있다.
- DB schema 변경은 계획하지 않는다. 기존 nullable metadata columns만 사용한다.
