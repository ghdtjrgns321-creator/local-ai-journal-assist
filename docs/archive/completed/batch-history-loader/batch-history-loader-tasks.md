# Batch History Loader - Task Checklist

## Progress Summary

10 / 10 tasks complete (100%)

## Phase 1: DB 스키마 + 메타 적재

- [x] **1-1** upload_batches DDL 추가
  - File: `src/db/schema.py`
  - Details: `SCHEMA_DDL` dict에 `upload_batches` CREATE TABLE 추가. 컬럼: `upload_batch_id` (PK), `file_name`, `row_count`, `anomaly_count`, `high_risk_count`, `created_at`, `warnings`. `UPLOAD_BATCHES_COLUMNS` 리스트 상수 추가 (created_at 제외, loader reindex용).
  - Acceptance: `initialize_schema()` 실행 후 `conn.execute("SHOW TABLES").fetchdf()`에 upload_batches 포함
  - Size: S

- [x] **1-2** load_all()에 메타 적재 로직 추가
  - File: `src/db/loader.py`, `src/pipeline.py` (PipelineResult)
  - Details: `load_all()` 시그니처에 `file_name: str = ""` 파라미터 추가. 트랜잭션 내 COMMIT 직전에 upload_batches INSERT. `high_risk_count`는 `df["risk_level"].eq("High").sum()` (risk_level 컬럼 없으면 0). **PipelineResult 데이터클래스에 `file_name: str = ""` 필드 추가** (메서드 시그니처 연쇄 오염 방지, 리뷰 피드백 #3).
  - Acceptance: 테스트에서 `load_all()` 호출 후 `SELECT * FROM upload_batches WHERE upload_batch_id = ?` 결과가 1행이고, row_count가 gl_rows와 일치
  - Size: S

- [x] **1-3** 프리셋 쿼리 2종 추가
  - File: `src/db/queries.py`
  - Details: `PRESET_QUERIES`에 `list_batches` (파라미터 없음, ORDER BY created_at DESC), `batch_meta` (WHERE upload_batch_id = ?) 추가. `list_batches`는 `execute_preset(conn, "list_batches", params=())` 형태로 호출 — 빈 튜플이므로 기존 검증 로직에서 ValueError 발생하지 않음 (params가 None이 아니기 때문).
  - Acceptance: `:memory:` DB에서 스키마 초기화 후 두 쿼리 모두 에러 없이 빈 DataFrame 반환
  - Size: S

- [x] **1-4** 파이프라인에서 file_name 전달 (PipelineResult.file_name 방식)
  - File: `src/pipeline.py`, `dashboard/components/data_uploader.py`
  - Details: **PipelineResult.file_name 필드를 통해 전달** (리뷰 피드백 #3 — 메서드 시그니처 연쇄 오염 방지). `_load_db()`에서 `self._result.file_name`을 `load_all()`에 전달. `data_uploader.py`의 `_run_pipeline_from_mapped()`에서 반환된 PipelineResult에 file_name 할당. `run(path)` 메서드에서는 `Path(path).name`을 PipelineResult에 설정.
  - Acceptance: 대시보드에서 파일 업로드 후 `SELECT file_name FROM upload_batches` 결과에 파일명이 저장되어 있음
  - Size: S

- [x] **1-5** 메타 적재 단위 테스트
  - File: `tests/modules/db/test_batch_meta.py` (신규)
  - Details: 테스트 3개 작성. (1) load_all() → upload_batches에 1행 삽입, 필드값 검증. (2) 동일 batch_id 재삽입 시 ConstraintException. (3) file_name 빈 문자열일 때 정상 동작. :memory: DuckDB 사용, 최소 DataFrame(5행) 생성.
  - Acceptance: `uv run pytest tests/modules/db/test_batch_meta.py -v` 3개 테스트 전체 PASS
  - Size: M

## Phase 2: Batch Reader

- [x] **2-1** batch_reader.py 신설
  - File: `src/db/batch_reader.py` (신규, 약 100줄)
  - Details: `list_batches(conn) -> pd.DataFrame` — `execute_preset(conn, "list_batches", params=())` 래핑. `load_batch(conn, batch_id) -> PipelineResult` — (1) general_ledger 조회, (2) **`_reconstruct_detection_results()`로 anomaly_flags에서 Pseudo DetectionResult 역산** (리뷰 피드백 #1 — rule_code별 GROUP BY → DetectionResult 껍데기 생성), (3) benford_summary/digits 조회, (4) risk_summary 계산, (5) PipelineResult(data=data, results=pseudo_results, featured_data=None) 반환. 빈 결과 시 ValueError raise.
  - Acceptance: 파이프라인 실행 → DB 적재 → `load_batch()` → 반환된 PipelineResult.data 행 수가 원본과 일치, **results 리스트가 비어있지 않고 룰별 flagged_count가 anomaly_flags와 일치**
  - Size: M

- [x] **2-2** batch_reader 단위 테스트
  - File: `tests/modules/db/test_batch_reader.py` (신규)
  - Details: 테스트 3개 작성. (1) 적재 후 load_batch() 반환값의 data 행수, risk_summary 키 일치. (2) list_batches() 결과에 적재한 batch_id 포함. (3) 존재하지 않는 batch_id로 load_batch() 호출 시 ValueError. :memory: DuckDB + 최소 파이프라인 실행 (skip_db=False).
  - Acceptance: `uv run pytest tests/modules/db/test_batch_reader.py -v` 3개 테스트 전체 PASS
  - Size: M

## Phase 3: 대시보드 통합

- [x] **3-1** _state.py에 DB 로드 플래그 추가 + 읽기 전용 모드 UI
  - File: `dashboard/_state.py`, `dashboard/app.py`
  - Details: `KEY_LOADED_FROM_DB = "audit_loaded_from_db"` 상수 추가. `_DEFAULTS`에 `KEY_LOADED_FROM_DB: False` 추가. `_reset_to_company_select()`에서 리셋 대상 키 목록에 포함. **읽기 전용 모드 UI (리뷰 피드백 #2)**: `KEY_LOADED_FROM_DB == True`일 때 (1) 대시보드 상단에 `st.info("DB에서 불러온 과거 분석 결과입니다 (읽기 전용 모드)")` 배지 표시, (2) 사이드바 "탐지 설정" Expander를 숨기거나 "설정을 변경하려면 원본 파일을 다시 업로드해주세요" 안내 표시.
  - Acceptance: `init_state()` 호출 후 `st.session_state["audit_loaded_from_db"]`가 False. DB 로드 시 상단 info 배지 표시, 탐지 설정 비활성화 확인.
  - Size: S

- [x] **3-2** batch_selector.py 신설
  - File: `dashboard/components/batch_selector.py` (신규, 약 60줄)
  - Details: `render_batch_selector(conn) -> bool` — list_batches(conn) 호출, 빈 결과면 False 반환(아무것도 렌더링하지 않음). 배치가 있으면 `st.subheader("이전 분석 결과")` + 각 배치를 `st.container(border=True)` 카드로 표시: 파일명, 행수, 이상건수, High건수, 업로드 시각. "불러오기" 버튼 클릭 시 `_load_and_restore(conn, batch_id)` 호출 — load_batch() → session_state 설정(KEY_PIPELINE_RESULT, KEY_BATCH_ID, KEY_UPLOAD_COUNT, KEY_LOADED_FROM_DB=True) → st.rerun().
  - Acceptance: Streamlit 실행 시 배치가 있는 engagement에서 카드가 표시되고, 클릭 시 분석 탭으로 전환
  - Size: M

- [x] **3-3** app.py 분기 로직 수정
  - File: `dashboard/app.py`
  - Details: 162~166행의 `if result is None:` 블록 수정. `render_batch_selector(conn)` 호출을 `render_uploader()` 위에 배치. conn은 `_conn_mgr.get(ctx.db_path)`로 획득. `render_batch_selector`가 True를 반환하면 `st.divider()` 추가하여 배치 목록과 업로더 사이를 구분. `_reset_to_company_select()`의 리셋 키 목록에 KEY_LOADED_FROM_DB 추가. "다른 파일 분석" 버튼(180행)에서도 KEY_LOADED_FROM_DB를 False로 리셋.
  - Acceptance: (1) 배치 있는 engagement: 상단 배치 카드 + 구분선 + 하단 업로더. (2) 배치 없는 engagement: 업로더만 표시. (3) 배치 선택 후 4개 탭 정상 렌더링. (4) "다른 파일 분석" 클릭 시 업로드 화면으로 복귀.
  - Size: M

## Deployment Checklist

- [ ] `initialize_schema()` 실행 시 기존 DB에 upload_batches 테이블 자동 생성 (IF NOT EXISTS)
- [ ] 기존 테이블 스키마 변경 없음 (하위 호환)
- [ ] `load_all()` file_name 파라미터 기본값 "" 설정 (기존 호출부 파급 없음)
- [ ] `uv run pytest tests/ -v` 전체 통과
- [ ] 대시보드 수동 테스트: 업로드 → 재시작 → 배치 선택 → 결과 확인
