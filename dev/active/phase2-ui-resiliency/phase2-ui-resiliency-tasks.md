# Phase2 UI Resiliency Tasks

## Status

Current phase: analysis before patching.

## A. UI Action Matrix

- [x] A1. Inspect `dashboard/tab_phase2.py` render path and sub-tab selectors.
- [x] A2. Map Phase2 inference button handler and expected state.
- [x] A3. Map Phase2 retrain + inference handler and expected state.
- [x] A4. Map Phase2 training-only path.
- [x] A5. Map partition selector and fallback behavior.
- [x] A6. Map saved batch load and autoload path.
- [x] A7. Map Phase1 rerun, mapping finalize, upload-again, and return-to-start invalidation.

### A.1 Phase2 학습 / 추론 버튼

| 액션 | 트리거 | 핸들러 | 호출 chain | session_state write/delete | 영향 산출물 | 사전조건 | invalidation |
|---|---|---|---|---|---|---|---|
| Phase 2 학습 + 추론 (최초) | `tab_phase2.py:48` `st.button("Phase 2 학습 + 추론 실행")` | `_start_phase2_pipeline(partition="2024", train=True)` (`tab_phase2.py:2100`) | `run_phase2_training_analysis(state)` → `run_phase2_inference_analysis(state, partition="2024")` | `KEY_PHASE2_TRAINING_REPORT_ID`, `KEY_PHASE2_RESULT`, `KEY_BATCH_ID`, `KEY_PIPELINE_RESULT`, `KEY_FEATURED_DATA`, `KEY_ACTIVE_RESULT_TAB`, `KEY_PENDING_RESULT_TAB` | `models/phase2_train/{report_id}/...` 신규, `phase2_overlays/{batch_id}.json` 신규, `batch_meta` phase2 컬럼 update | `result is None` && `snapshot is None` (not_trained 분기) | `st.rerun()` |
| 저장된 모델로 Phase 2 추론 | `tab_phase2.py:55` 버튼 | `_start_phase2_pipeline(train=False)` | `run_phase2_inference_analysis` 만 | `KEY_PHASE2_RESULT`, `KEY_BATCH_ID`, `KEY_PIPELINE_RESULT`, `KEY_FEATURED_DATA` | `phase2_overlays/{batch_id}.json` 덮어쓰기, `batch_meta` phase2 컬럼 update | `snapshot` 존재 (training_report_available) | `st.rerun()` |
| Phase 2 재학습 + 추론 | `tab_phase2.py:60` 버튼 | `_start_phase2_pipeline(train=True)` | (위 학습+추론과 동일) | (위와 동일) | training 산출물 신규 `report_id`, overlay 덮어쓰기 — **이전 report_id 와 stale 위험** | `result not None` (inference_complete) | `st.rerun()` |
| Partition selector (UI 미노출, 내부 고정) | `tab_phase2.py:72` `_DEFAULT_PARTITION = "전체"` | — | `_load_phase2_partition_summary("전체")` (3 연도 merge) | (없음, 읽기만) | `artifacts/phase2_inference_v7_fixed3_year_{year}.json` 3개 read | `result not None` | — |

### A.2 Phase2 sub-tab 클릭

| 액션 | 트리거 | 렌더 함수 | 읽는 state | 비고 |
|---|---|---|---|---|
| 전체 요약 | `tab_phase2.py` `st.tabs(["전체 요약", ...])` | `_render_overview_tab` | `KEY_PHASE2_RESULT`, `KEY_PHASE1_RESULT` (overlay/case lookup), partition_summary | KPI 카드 / Phase 1+2 도넛 / family bar |
| Family 신호 | (위 tabs) | `_render_family_signal_tab` | partition_summary | family 카드 + sub-detector 표 + dormant expander |
| 검토 Lane | (위 tabs) | `_render_review_lane_tab` | `KEY_PHASE2_RESULT.phase2_case_overlays`, `KEY_PHASE1_RESULT` (priority lookup) | lane summary + content frame (Phase1 priority 병기) |
| 모델 기준 | (위 tabs) | `_render_model_basis_tab` | snapshot (`models/phase2_train/...`) | training/leaderboard expander |

### A.3 상위 6 탭 라우팅

| 액션 | 트리거 | 렌더 분기 | 사전조건 | invalidation |
|---|---|---|---|---|
| 개요 / 회사별 설정 / Phase1 결과 / Phase2 결과 / 전기 비교 / Review Queue 클릭 | `app.py:314` `st.tabs(RESULT_PAGES, key=KEY_TOP_LEVEL_NAV, on_change="rerun")` | `app.py:323-334` 의 if-elif chain | 각 탭의 result attribute 존재 (없으면 빈 안내) | `KEY_ACTIVE_RESULT_TAB = active_tab` (`app.py:321`) |
| 처음으로 돌아가기 | `app.py:291` `st.button("처음으로 돌아가기")` | `_reset_to_company_select` (`app.py:82`) | — | `clear_company_selection(ss)` (`session_service.py:60`) + `sync_selection_to_query_params` (URL params 비우기) + `st.rerun()` → 회사 선택 화면 |

### A.4 데이터 lifecycle / Phase1 invalidation

| 액션 | 트리거 | 핸들러 | session_state 변경 | Phase2 invalidation |
|---|---|---|---|---|
| 회사 선택 autoload (1회) | `app.py:251` `autoload_flag = f"_batch_autoloaded_for_{ctx.engagement_id}"`, `app.py:263` `load_batch_into_state` | `batch_service.load_batch_into_state` → `_attach_persisted_phase2_overlays` → `restore_loaded_result` | `KEY_PREP_RESULT`, `KEY_PHASE1_RESULT` (if `has_analysis_output`), `KEY_PHASE2_RESULT` (if `_has_phase2_artifacts`), `KEY_PIPELINE_RESULT`, `KEY_BATCH_ID`, `KEY_LOADED_FROM_DB=True`, `KEY_FEATURED_DATA`, autoload_flag=True | `KEY_PHASE2_RESULT = loaded if _has_phase2_artifacts else None` (session_service.py 변경됨) |
| 저장 batch 로드 (수동) | `dashboard/components/batch_selector.py` `st.button("불러오기", key=f"load_{bid}")` | `load_batch_into_state(state, conn, batch_id)` | (autoload와 동일) | (autoload와 동일) |
| 데이터 재업로드 | `data_uploader.py` ingest 흐름 → `mapping_finalize.prepare_mapped_data` | `prepare_mapped_data` | `KEY_PREP_RESULT`, `KEY_PHASE2_RESULT=None` 명시 reset, `KEY_PIPELINE_RESULT=None`, `KEY_BATCH_ID`, `KEY_FEATURED_DATA`, `KEY_LOADED_FROM_DB=False` | ✅ Phase2 명시 reset |
| Phase1 분석 재실행 | `tab_phase1.py:125` `st.button("Phase 1 분석 시작")` 또는 app 측 `run_phase_analysis(phase="phase1")` | `analysis_service.run_phase_analysis` | `KEY_PHASE1_RESULT` 신규, `KEY_PIPELINE_RESULT` 신규, `KEY_BATCH_ID`, `KEY_FEATURED_DATA` | ⚠️ **STALE 위험**: `KEY_PHASE2_RESULT` 미invalidate. 이전 phase1 case_id 기반 overlay 가 새 phase1 cases 와 어긋날 수 있음 (D13 분기 후보) |

### A.5 KEY 변경 흐름 요약

```
[회사선택]
  autoload_flag(engagement_id) 가드
    load_batch_into_state
      _attach_persisted_phase2_overlays (overlay 파일 → loaded.phase2_case_overlays)
      restore_loaded_result
        KEY_PHASE1_RESULT, KEY_PHASE2_RESULT(메타 있을 때), KEY_PIPELINE_RESULT 세팅

[Phase2 학습+추론 버튼]
  run_phase2_training_analysis → KEY_PHASE2_TRAINING_REPORT_ID
  run_phase2_inference_analysis
    _inherit_phase1_case_result(state[KEY_PHASE1_RESULT])  ← canonical 강제
      _attach_phase2_case_overlays(result)                 ← overlay rebuild
    KEY_PHASE2_RESULT = result
    _persist_phase2_overlays_to_disk → engagement_dir/phase2_overlays/{batch_id}.json

[Phase1 재실행]
  run_phase_analysis(phase="phase1")
    KEY_PHASE1_RESULT 신규, KEY_PIPELINE_RESULT 신규
    KEY_PHASE2_RESULT 그대로 (⚠️ stale)

[처음으로 돌아가기]
  _reset_to_company_select
    clear_company_selection → KEY_PHASE1_RESULT/KEY_PHASE2_RESULT/KEY_PIPELINE_RESULT/... 전부 pop
    sync_selection_to_query_params → URL ?company=/?engagement= 제거
    st.rerun()
```

## B. Session State Matrix

- [x] B1. Trace `KEY_PREP_RESULT`.
- [x] B2. Trace `KEY_PHASE1_RESULT`.
- [x] B3. Trace `KEY_PHASE2_RESULT`.
- [x] B4. Trace `KEY_PIPELINE_RESULT`.
- [x] B5. Trace `KEY_BATCH_ID`.
- [x] B6. Trace `KEY_COMPANY_CONTEXT`.
- [x] B7. Trace `KEY_FEATURED_DATA`.
- [x] B8. Trace `KEY_LOADED_FROM_DB`.
- [x] B9. Trace result tab routing keys.
- [x] B10. Trace `KEY_PHASE2_TRAINING_REPORT_ID`.
- [x] B11. Trace autoload guard keys.

### B.1 Key 단일 추적표

라인 번호는 `M-Verify` 시점(2026-05-20) 기준. 함수명/심볼이 권위 기준이며, 라인은 ripple-search 시 재확인 권장.

| Key | 정의 | 주요 write (함수 · 파일) | 주요 read | reset/delete | 동시 set | stale 위험 |
|---|---|---|---|---|---|---|
| `KEY_PREP_RESULT` | `dashboard/_state.py` | `mapping_finalize.prepare_mapped_data`, `session_service.restore_loaded_result` (`session_service.py:110+`) | `app.py` (`prep_result or display_result` 패턴), tab_phase1, tab_phase2 | `session_service.clear_company_selection` (`session_service.py:60`) | prep 분석 시 batch_id/featured_data 동시 | — |
| `KEY_PHASE1_RESULT` | _state.py | `analysis_service.run_phase_analysis`, `restore_loaded_result` (has_analysis_output 통과 시) | `app.py`, `tab_phase1`, `tab_phase2._render_review_lane_tab` 등 | `clear_company_selection`, `mapping_finalize.prepare_mapped_data` | pipeline/batch_id 동시 | Phase2 추론 시 canonical 으로 강제 덮어쓰여야 함 (R-High 적용됨) |
| `KEY_PHASE2_RESULT` | _state.py | `phase2_inference_service.run_phase2_inference_analysis`, `restore_loaded_result` (if `_has_phase2_artifacts(loaded)`), `mapping_finalize.prepare_mapped_data` (None) | `app.py:303`, tab_phase2 전반 | `clear_company_selection`, `mapping_finalize` reset, `dev_analysis_reset` | inference 시 pipeline/batch_id 동시 | ⚠️ **Phase1 재실행 후 stale** — KEY_PHASE2_RESULT 가 자동 invalidate 안 됨 (D13/D14 대상) |
| `KEY_PIPELINE_RESULT` | _state.py | `run_phase_analysis`, `run_phase2_inference_analysis`, `restore_loaded_result` | `app.py`, tab_phase1, tab_overview | `clear_company_selection`, `mapping_finalize`, `dev_analysis_reset` | phase1/phase2 분석 후 함께 | Phase2 가 KEY_PIPELINE_RESULT 도 덮어씀 — 전기 비교 / Review Queue 가 phase1 기준이 아닌 phase2 결과를 보게 됨 |
| `KEY_BATCH_ID` | _state.py | `run_phase_analysis`, `run_phase2_inference_analysis`, `restore_loaded_result`, `mapping_finalize`, `data_uploader` 완료 시점 | `app.py`, `tab_review_queue`, `dev_analysis_reset` | `clear_company_selection` | 분석 후 pipeline/featured_data 동시 | — |
| `KEY_COMPANY_CONTEXT` | _state.py | `app.py` `_needs_ctx_refresh` 시 `ContextFactory.create`, settings 변경 시 `ctx.clone_with_settings` | `app.py`, `restore_loaded_result`, `phase2_inference_service` 다수, `batch_service._attach_persisted_phase2_overlays` | `clear_company_selection` | — | autoload 후 `ctx.clone_with_settings(settings)` 가 매번 새 인스턴스 — 캐시/identity 의존 코드 주의 |
| `KEY_FEATURED_DATA` | _state.py | `run_phase_analysis`, `phase2_inference_service._store_featured_data_best_effort` (`phase2_inference_service.py:139`), `mapping_finalize`, `restore_loaded_result` | `analysis_service.rerun_detection`, phase2 inference 시 fallback | `clear_company_selection`, `mapping_finalize` reset | prep 복원 시 함께 | Phase2 추론이 featured_df 로 덮어씀 — phase1 features 와 schema 다를 위험 |
| `KEY_LOADED_FROM_DB` | _state.py | `restore_loaded_result` (True), `mapping_finalize` (False), `dev_analysis_reset` | `tab_phase2._render_phase2_action_panel`, 액션 panel 분기 | `clear_company_selection`, `dev_analysis_reset` | — | DB 로드 후 재분석 안 하면 True 유지 — "읽기 전용 모드" UI 진입 |
| `KEY_ACTIVE_RESULT_TAB` / `KEY_PENDING_RESULT_TAB` | _state.py | app/tabs 의 on_change rerun, `_consume_pending_page` (`app.py:150`), 각 탭 진입 시 명시 set | `app.py:308`, `_consume_pending_page` | (자동 consume) | active 와 pending 쌍 | rerun race — pending 이 active 보다 우선 적용되는지 흐름 |
| `KEY_PHASE2_TRAINING_REPORT_ID` | _state.py | `phase2_training_service.run_phase2_training_analysis`, `tab_phase2._start_phase2_pipeline` | `phase2_inference_service.load_latest_phase2_training_snapshot` 호출 시 `ctx.model_dir` 기준 | `clear_company_selection` (자동) | training 직후 set | 여러 training 실행 시 마지막만 유지 — 이전 모델 재현 불가 (의도된 단순화) |
| `_batch_autoloaded_for_{engagement_id}` | `app.py:251` 동적 키 | `app.py:268` autoload 성공 후 True | `app.py:252` guard check | (engagement 전환 시 새 key) | — | 같은 engagement 로 재진입 시 guard True 유지 — 수동 batch 재선택 진로 막힘 |

### B.2 Stale 시나리오

1. **Phase1 재실행 후 Phase2 stale (D13 후보)**
   - `run_phase_analysis(phase="phase1")` → `KEY_PHASE1_RESULT` 갱신
   - `KEY_PHASE2_RESULT` 는 그대로 — 이전 phase1 case_id 기반 overlay 가 새 cases 와 어긋남
   - 권장: `run_phase_analysis` 가 phase1 분기일 때 `state[KEY_PHASE2_RESULT] = None` 명시

2. **DB 로드 후 KEY_LOADED_FROM_DB=True 잔존**
   - `restore_loaded_result` → True
   - 사용자가 추론 한 번 더 실행해도 True 유지 — UI 분기에서 "DB에서 불러온 결과입니다" caption 영구
   - 권장: 재추론 성공 후 `KEY_LOADED_FROM_DB = False`

3. **Phase2 추론이 featured_data 덮어쓰기**
   - `_store_featured_data_best_effort` 가 phase2 featured_df 로 덮어씀
   - phase1 feature schema 와 다를 수 있어 후속 rerun_detection 부정확
   - 권장: phase1 featured_data 와 phase2 featured_data 분리 슬롯

4. **autoload guard 사후 재선택 진로**
   - 같은 engagement 진입 시 `_batch_autoloaded_for_*` True 유지
   - 다른 batch 를 자동으로 로드하지 않음 (의도) — 단 UI에 "다른 batch 보기" 진로 명확화 필요

5. **mapping_finalize 후 training_report_id 잔존**
   - `prepare_mapped_data` 가 prep/phase2_result reset 하지만 `KEY_PHASE2_TRAINING_REPORT_ID` 미reset
   - 다음 추론 시 이전 training snapshot 으로 inference 시도 → schema 불일치 위험
   - 권장: `prepare_mapped_data` 가 `KEY_PHASE2_TRAINING_REPORT_ID` 도 reset

## C. Persistence Matrix

- [x] C1. Trace `upload_batches`, `general_ledger`, `anomaly_flags`.
- [x] C2. Trace `batch_meta` Phase2 fields.
- [x] C3. Trace Phase2 training report.
- [x] C4. Trace Phase2 leaderboard and promotion decision.
- [x] C5. Trace Phase1 case artifact path, creation, lazy load, and failure behavior.
- [x] C6. Trace Phase2 overlay JSON path, schema, save/load, and company isolation.
- [x] C7. Trace static Phase2 inference artifacts used by analysis-area cards.

### C.1 DB 테이블

| 산출물 | 저장 함수 | 저장 시점 | 트리거 조건 | 읽기 함수 | 누락 시 결과 | 격리 |
|---|---|---|---|---|---|---|
| `upload_batches` | `db/loader.load_all` (~`db/loader.py:145+`) + `update_upload_batch_meta` (`db/loader.py:196+`) | Phase1/Phase2 파이프라인 완료 후 + inference 후 메타 update | `batch_id` 존재, phase2 메타 컬럼 attach 시 | `db/batch_reader.list_batches`, `batch_reader.load_batch` (`batch_reader.py:54`) | Crash (batch 로드 실패) → autoload 차단 | engagement DB 파일별 |
| `general_ledger` | `db/loader.load_general_ledger` | ingest 직후 | DataFrame 행 > 0 | `execute_preset("batch_ledger")` | Crash (대시보드 렌더 불가) | `company_code` + `upload_batch_id` |
| `anomaly_flags` | `db/loader.load_anomaly_flags` | detection 결과 적재 시 | DetectionResult.details 행 > 0 | `execute_preset("batch_flags")` → `_reconstruct_detection_results` (`batch_reader.py:119`) | Graceful (empty list) | `upload_batch_id` |
| `batch_meta` (phase2 컬럼) | `update_upload_batch_meta` 의 `phase2_training_report_id`, `phase2_inference_contract`, `phase2_promotion_policy`, `phase2_inference_mode`, `detector_statuses_json` | `_persist_phase2_batch_snapshot` (`phase2_inference_service.py:280`) → inference 직후 | `conn` 존재 + `batch_id` 존재 + `load_result` 존재 (best-effort, 실패해도 inference 진행) | `batch_reader._phase1_case_meta_from_row` (`batch_reader.py:332`) 와 같은 row 조회에서 attach | Graceful (phase2 컬럼 NULL → `_has_phase2_artifacts` False → KEY_PHASE2_RESULT 도 None) | engagement DB |
| `performance_reports` | `db/performance_store.save_report` | phase1/phase2 성능 평가 완료 후 | PerformanceReport 객체 + `report_id`/`upload_batch_id` | `db/performance_store.load_latest_report` → `batch_reader.py:70` 에서 fallback `evaluate_operational_report_from_db` | Graceful (재평가) | `upload_batch_id` |

### C.2 파일 산출물

| 산출물 | 저장 함수 | 저장 시점 | 트리거 조건 | 읽기 함수 | 누락 시 결과 | 격리 |
|---|---|---|---|---|---|---|
| `models/phase2_train/{report_id}/training_report.json` | `phase2_training_service.save_phase2_training_report` (`:408+`) | Phase2 AutoML 학습 완료 후 | `report.report_id` 유효 | `phase2_inference_service.load_latest_phase2_training_snapshot` (`:333+`) | Graceful (snapshot=None → `untrained_contract_only` 모드) | `ctx.model_dir / phase2_train/` |
| `models/phase2_train/{report_id}/reports/leaderboard.json` | `phase2_leaderboard.save_leaderboard_json` | training_report 저장 시 동반 호출 | `leaderboard` 행 > 0 | `_read_json_artifact` (`phase2_inference_service.py:365+`) | Graceful (artifact=None, 모델 기준 탭 빈 표) | report_id |
| `models/phase2_train/{report_id}/reports/promotion_decision.json` | `phase2_promotion_policy.save_promotion_decision_json` | training_report 저장 시 동반 호출 | promoted_models 유효 | `_read_json_artifact` | Graceful (기본 정책 유지) | report_id |
| `artifacts/phase1_cases/{company_id}/{run_id}.json` | `phase1_case_builder.save_phase1_case_result` (`:606`) — 경로는 `phase1_case_artifact_path(company_id, run_id)` (`:602`) | Phase1 case 빌드 완료 후 | `Phase1CaseResult.cases` 길이 > 0 | `phase1_case_view.resolve_phase1_case_result(pr)` (`:66`) — `pr.phase1_case_path` 에서 lazy load. `batch_reader._phase1_case_meta_from_row` (`:332`) 가 `phase1_case_path` 를 attach, 없으면 `_recover_phase1_case_meta_from_artifacts` (`batch_reader.py:355`) 가 artifact 디렉토리에서 복구 시도 | Graceful (metadata-only 모드, `phase1_case_count > 0` 이면 메타만 표시) — 단 canonical phase2 overlay 생성 실패 (D2 분기) | `company_id` 폴더 (engagement 격리는 run_id 안에 batch_id 포함으로 간접) |
| `engagement_dir/phase2_overlays/{batch_id}.json` | `phase2_overlay_store.save_phase2_overlays` (`:69`) — `_persist_phase2_overlays_to_disk` 가 호출 (`phase2_inference_service.py:302`) | Phase2 inference 후 (overlay attach 직후) | `ctx` 존재 + `batch_id` 안전 (path traversal 차단) + overlays 리스트 | `phase2_overlay_store.load_phase2_overlays` (`:117`) — schema_version + payload batch_id 검증, `batch_service._attach_persisted_phase2_overlays` (`batch_service.py:36`) 가 호출 | Graceful (None → overlay missing UI) | `engagement_dir = ctx.db_path.parent` |
| `artifacts/phase2_inference_v7_fixed3_year_{year}.json` | `scripts/phase2_inference_v7_fixed3_by_year.py` (정적 smoke artifact) | 수동 smoke 실행 시 | — (런타임 미생성) | `tab_phase2._load_phase2_partition_summary` 가 `artifacts/phase2_inference_v7_fixed3_year_{partition}.json` 직접 read | Graceful (family signal 카드 빈 상태) — 단 **이게 정적 참조 파일이라 회사/engagement 무관**, 모든 회사가 같은 파일을 봄 (회사 격리 위반 가능성) | ⚠️ 글로벌 (회사 격리 없음) |

### C.3 Critical 추적 요약

1. **Phase1 case artifact 경로 lifecycle**
   - 생성: `phase1_case_artifact_path(company_id, run_id) = artifacts/phase1_cases/{company_id}/{run_id}.json` (`phase1_case_builder.py:602-603`)
   - 저장: `save_phase1_case_result(result)` (`:606-610`)
   - DB attach: `batch_meta.phase1_case_path`, `phase1_case_run_id`, `phase1_case_count`, `phase1_macro_finding_count`, `phase1_top_theme_ids`
   - Lazy load: `resolve_phase1_case_result(pr)` (`phase1_case_view.py:66`)
     - `pr.phase1_case_result.cases` 있으면 그대로
     - 없으면 `pr.phase1_case_path` 에서 `load_phase1_case_result` 로 파일 read
     - 파일 실패 시 warning + None → metadata-only 모드
   - Artifact 복구: `_recover_phase1_case_meta_from_artifacts(batch_id)` (`batch_reader.py:355`) 가 phase1_case_path 가 batch_meta 에 없을 때 artifact 디렉토리에서 batch_id 매칭하는 파일을 찾는 fallback

2. **`_persist_phase2_batch_snapshot` 가 update 하는 batch_meta 컬럼**
   - `phase2_training_report_id`, `phase2_inference_contract`, `phase2_promotion_policy`, `phase2_inference_mode`, `detector_statuses_json`
   - 호출 위치: `phase2_inference_service.run_phase2_inference:59` → `_persist_phase2_batch_snapshot(conn=conn, result=result)`
   - 실패 시 result.warnings 에 추가, inference 자체는 성공 처리

3. **Overlay 파일과 batch_meta 의 training_report_id 정합 (D13 stale 위험)**
   - overlay JSON 안의 `phase2_training_report_id` 와 `batch_meta.phase2_training_report_id` 가 같아야 valid
   - 재학습 후 overlay 파일은 새 report_id, batch_meta 도 새 report_id 로 동시 update — but 이전 overlay 파일이 같은 batch_id 면 덮어쓰기 됨 (의도)
   - 다른 batch 에 대한 stale overlay 는 batch_id 검증으로 차단 (R-Med1 적용됨)

4. **`artifacts/phase2_inference_v7_fixed3_year_{year}.json` — 글로벌 정적 파일**
   - 모든 회사가 같은 파일을 read. 회사/engagement 격리 위반 가능성.
   - 현재는 family signal preview 용도이라 큰 위험 아님, 단 회사별 partition_summary 가 필요해지면 분리 필요
   - F 패치 시 회사별 동적 파일 또는 DB 테이블 전환 고려

## D. Failure Classification

- [x] D1. Phase1 cases missing.
- [x] D2. Phase1 artifact missing or unreadable.
- [x] D3. Phase2 inference not run.
- [x] D4. Phase2 DB load failed.
- [x] D5. Phase2 overlay missing.
- [x] D6. Overlay schema mismatch.
- [x] D7. Overlay batch_id mismatch.
- [x] D8. Overlay present but no hit cases.
- [x] D9. Training snapshot missing / cold-start inference.
- [x] D10. Partition zero-row fallback.
- [x] D11. Missing or anonymous company context.
- [x] D12. Old batch without overlay persistence.
- [x] D13. Stale overlay after retraining.
- [x] D14. Cross-company or cross-engagement overlay attach risk.

### D.1 Failure / Message / Action Matrix

| ID | Branch | Detection condition | User-facing message | Diagnostic detail | Next action | Severity | Patch target |
|---|---|---|---|---|---|---|---|
| D1 | Phase1 cases missing | `resolve_phase1_case_result(KEY_PHASE1_RESULT)` is None and `phase1_case_count == 0` | `Phase 1 검토 케이스가 없어 Phase 2를 케이스 기준으로 연결할 수 없습니다.` | Phase2 overlay is case-keyed; no case base exists. | `Phase 1 분석 실행` button / route to Phase1 tab | Blocker | `tab_phase2` empty-state resolver |
| D2 | Phase1 artifact missing or unreadable | `phase1_case_count > 0`, `phase1_case_path` present, lazy load fails | `저장된 Phase 1 케이스 파일을 읽지 못했습니다. 현재는 Phase 2 재생성 케이스 기준으로 표시됩니다.` | Canonical restore failed; fallback must be labeled. | `Phase 1 재실행` or `Phase 2 재추론` after artifact recovery | Warning | `phase2_inference_service`, `tab_phase2` diagnostics |
| D3 | Phase2 inference not run | `KEY_PHASE2_RESULT is None` and no Phase2 meta | `Phase 2 추론 결과가 없습니다.` | Training may exist but no inference result/overlay exists. | `저장된 모델로 Phase 2 추론` or `Phase 2 학습 + 추론` | Normal empty | `tab_phase2` action panel |
| D4 | Phase2 DB load failed | `result.warnings` contains DB load failure or `load_result is None` after inference | `Phase 2 분석은 완료됐지만 DB 저장 일부가 실패했습니다. 현재 화면은 세션 결과 기준입니다.` | Refresh may lose DB-backed reconstruction if overlay/meta also missing. | `결과 확인 후 재추론` / expose warning details | Warning | `phase2_inference_service`, `tab_phase2` warning strip |
| D5 | Phase2 overlay missing | `KEY_PHASE2_RESULT` has Phase2 meta but `phase2_case_overlays` absent/empty and no overlay JSON | `Phase 2 케이스 overlay가 없습니다. 이 batch는 다시 추론해야 케이스별 결과가 저장됩니다.` | Old batch or persistence failure. | `Phase 2 재추론` | Warning | `batch_service`, `tab_phase2` overlay status |
| D6 | Overlay schema mismatch | `load_phase2_overlays` returns schema mismatch diagnostic | `저장된 overlay 형식이 현재 버전과 맞지 않습니다.` | `schema_version != SCHEMA_VERSION`; attach rejected. | `Phase 2 재추론` | Warning | `phase2_overlay_store` return diagnostic |
| D7 | Overlay batch_id mismatch | overlay payload batch_id != requested batch_id | `저장된 overlay가 현재 batch와 일치하지 않아 사용하지 않았습니다.` | Prevents stale/cross-batch attach. | `현재 batch로 Phase 2 재추론` | Warning | `phase2_overlay_store` return diagnostic |
| D8 | Overlay present but no hit cases | overlays exist but no case has Phase2 family contributions / lane membership | `Phase 2가 케이스에 추가 적중 신호를 부여하지 않았습니다.` | This is valid no-hit, not missing overlay. | Show overlay count + allow Review Lane filter reset | Informational | `tab_phase2` chart/data guards |
| D9 | Training snapshot missing / cold-start inference | `load_latest_phase2_training_snapshot(ctx) is None`, inference mode `untrained_contract_only` | `저장된 학습 기준이 없어 기본 추론 기준으로 실행했습니다.` | No training_report/leaderboard/promotion artifacts. | `Phase 2 학습 + 추론` | Warning | `phase2_inference_service`, `tab_phase2` model strip |
| D10 | Partition zero-row fallback | `_apply_partition_filter` falls back because selected year has 0 rows | `선택 연도에 데이터가 없어 전체 데이터로 Phase 2를 실행했습니다.` | Displayed partition differs from executed population. | Show used partition = `전체`; offer partition selector reset | Warning | `phase2_inference_service` result metadata, `tab_phase2` status |
| D11 | Missing or anonymous company context | `KEY_COMPANY_CONTEXT is None` or ctx lacks valid company/engagement/db path | `회사/engagement 컨텍스트가 없어 결과 저장과 재로드가 제한됩니다.` | Overlay/model paths depend on ctx. | `회사 선택으로 돌아가기` | Blocker for persistence | `app`, `tab_phase2`, services guards |
| D12 | Old batch without overlay persistence | loaded batch has Phase2 meta but no overlay file and batch predates overlay store | `이전 batch에는 케이스 overlay 파일이 없습니다. Phase 2를 다시 실행하면 저장됩니다.` | Not a crash; historical compatibility branch. | `Phase 2 재추론` | Informational / warning | `batch_service`, `tab_phase2` status |
| D13 | Stale overlay after retraining or Phase1 rerun | overlay `phase2_training_report_id` differs from current report, or `KEY_PHASE1_RESULT` changed while `KEY_PHASE2_RESULT` remains | `현재 Phase 2 결과가 최신 Phase 1/학습 기준과 다를 수 있어 숨겼습니다.` | Prevents old overlay against new cases/model. | `Phase 2 재추론` | Blocker for display | invalidation in `analysis_service`, `mapping_finalize`, overlay validator |
| D14 | Cross-company or cross-engagement overlay attach risk | ctx path/company differs from overlay path/metadata, or static global artifact used as company-specific data | `현재 회사 기준으로 생성된 Phase 2 근거만 표시합니다.` | Overlay store is engagement-scoped; static artifact is global preview only. | Block attach; show preview label for global artifact | Blocker for attach | `phase2_overlay_store`, `tab_phase2` preview labeling |

### D.2 Derived Patch Groups

| Patch group | Failure IDs | Rule |
|---|---|---|
| P1 State invalidation | D13 | Phase1 rerun / prep change / retrain must invalidate stale Phase2 surfaces. |
| P2 Overlay diagnostics | D5-D7, D12, D14 | Overlay loader should return status diagnostics, not only list/None. |
| P3 Phase1 canonical/fallback labeling | D1-D2 | UI must distinguish no Phase1 cases from missing artifact and fallback cases. |
| P4 Inference status metadata | D4, D9, D10-D11 | Result should carry DB-load status, inference mode, and partition fallback metadata. |
| P5 Empty-state UX | D3, D8 | Valid no-result/no-hit states need different text and action buttons. |
| P6 Static artifact isolation | D14 | Global V7 fixed3 preview must be labeled or replaced by company-scoped data. |

## E. Verification Scenarios

- [x] E1. Fresh Phase1 to Phase2 immediate UI.
- [x] E2. Fresh Phase1 to Phase2 refresh/reload.
- [x] E3. Saved batch load restores overlay.
- [x] E4. Phase1 metadata-only still creates overlay.
- [x] E5. Missing Phase1 artifact uses explicit fallback.
- [x] E6. DB load failure preserves session display.
- [x] E7. Same batch double inference safely overwrites overlay.
- [x] E8. Company A/B overlay isolation.
- [x] E9. Retrain invalidates or flags old overlay.
- [x] E10. Upload/prep change resets Phase1/Phase2 consistently.

### E.1 Verification Matrix

| ID | Scenario | Setup | Action | Expected state | Expected UI | Test target |
|---|---|---|---|---|---|---|
| E1 | Fresh Phase1 -> Phase2 immediate UI | In-memory `KEY_PHASE1_RESULT` has full `phase1_case_result.cases`; ctx valid | Click saved-model inference or train+inference | `KEY_PHASE2_RESULT.phase2_case_overlays` length > 0; `KEY_LOADED_FROM_DB=False` | Overview cards and Review Lane do not show overlay missing | `test_phase2_inference_service`, `test_tab_phase2` |
| E2 | Fresh Phase1 -> Phase2 -> refresh/reload | E1 plus overlay JSON saved | F5 / autoload same batch | `load_batch_into_state` attaches persisted overlays before restore | Same overlay-derived cards/lane visible after reload | `test_dashboard_services`, browser smoke |
| E3 | Saved batch load restores overlay | Existing DB batch meta + overlay JSON | Manual batch load | `KEY_PHASE2_RESULT is loaded`; overlays equal JSON | No "rerun only" empty state | `test_load_batch_into_state_restores_persisted_phase2_overlays` |
| E4 | Phase1 metadata-only still creates overlay | `KEY_PHASE1_RESULT` has `phase1_case_path` + count, no in-memory cases | Phase2 inference | Artifact lazy-loaded; result overlays rebuilt | Canonical case ids appear in lane/overview | `test_run_phase2_inference_analysis_loads_phase1_case_artifact_for_overlay` |
| E5 | Missing Phase1 artifact uses explicit fallback | Metadata-only Phase1 points to missing artifact; redetect creates fallback cases | Phase2 inference | Redetect `phase1_case_result` preserved; diagnostic warning/status present | UI says canonical artifact missing and fallback used | service test + dashboard message test |
| E6 | DB load failure preserves session display | Inference result has overlays but `load_result=None` / DB warning | Phase2 inference | `KEY_PHASE2_RESULT` remains result; overlays remain in session | Warning strip; charts/lane still render from session | `test_run_phase2_inference_analysis_keeps_result_when_db_load_fails`, dashboard test |
| E7 | Same batch double inference overwrites safely | Same batch_id inferred twice with different overlays/report_id | Run inference twice | Overlay file contains latest payload; batch_id/report_id valid | No stale warning after latest inference | `test_phase2_overlay_store`, new overwrite test |
| E8 | Company A/B overlay isolation | Company A and B have same batch_id under different engagement dirs | Load A then B | B does not attach A overlay; A reload still sees A overlay | No cross-company data in UI | `test_phase2_overlay_store` company isolation + batch service test |
| E9 | Retrain invalidates or flags old overlay | Existing overlay has old `phase2_training_report_id`; new training report exists | Retrain or load old batch | Old overlay hidden/flagged unless explicitly historical | UI instructs Phase2 rerun under new training basis | new stale-report test |
| E10 | Upload/prep change resets Phase1/Phase2 consistently | Existing Phase1/Phase2 state and training_report_id | Upload new file / mapping finalize | `KEY_PHASE1_RESULT=None`, `KEY_PHASE2_RESULT=None`, `KEY_PIPELINE_RESULT=None`, training report key reset | Phase2 tab shows no inference result, not old overlay | `test_dashboard_services` / mapping finalize test |

### E.2 Minimal Gate Set Per Patch Group

| Patch group | Required tests |
|---|---|
| P1 State invalidation | `test_dashboard_services`, focused mapping/analysis-service test |
| P2 Overlay diagnostics | `test_phase2_overlay_store`, `test_dashboard_services` |
| P3 Phase1 canonical/fallback labeling | `test_phase2_inference_service`, `test_tab_phase2` |
| P4 Inference status metadata | `test_phase2_inference_service`, import smoke |
| P5 Empty-state UX | `test_tab_phase2`, component snapshot/string tests |
| P6 Static artifact isolation | `test_tab_phase2` plus one company-context smoke |

## F. Patch Queue

Patch queue remains locked until A-E are complete.
