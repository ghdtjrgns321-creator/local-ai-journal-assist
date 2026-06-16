# 현재 결합 상태

- `dashboard/app.py`가 회사 전환, 저장 배치 자동 복원, 현재 표시 결과 선택을 직접 수행한다.
- `batch_selector.py`가 `load_batch()` 이후 `session_state`를 직접 채운다.
- `analysis_runner.py`와 `_redetect.py`가 각각 `AuditPipeline` 생성 규칙을 중복 보유한다.
- `data_uploader.py`는 별도 `AuditTrail` 생성 헬퍼를 갖고 있다.

이 구조는 Streamlit에서는 동작하지만, API/worker/CLI 같은 다른 진입점을 붙이려면 orchestration 로직을 다시 복제하게 된다.

## 1차 분리 원칙
- UI 파일은 `st.session_state`를 넘기고 결과를 렌더링만 한다.
- DB 복원 규칙과 phase 실행 규칙은 `src/services`가 가진다.
- 후속 API 계층은 같은 서비스를 재사용한다.
