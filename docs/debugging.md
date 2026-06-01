# Debugging Log

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

트러블슈팅 히스토리. 발생한 문제와 해결 과정을 기록하여 같은 실수를 반복하지 않기 위한 문서.

> 이 문서는 시점별 디버깅 기록이다. 현재 실사용 DataSynth 기준본은 `data/journal/primary/datasynth/`의 `v126` freeze (2026-05-02) + `datasynth_manipulation_v4_candidate` (manipulation v4, 2026-05-16 active) 이며, 과거 DataSynth 수치와 핫픽스 설명은 기록 시점 기준일 수 있다. 최신 baseline 출처: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) §활성 문서 인덱스.

## 2026-05-26: PHASE3 LLM removal / local-first boundary

PHASE3 LLM narrator and selected-case AI memo were removed from active product path. The feature duplicated existing PHASE1 case evidence and required sending case metadata/rule evidence to an external LLM, which conflicted with the local ledger analysis product boundary.

Replacement: deterministic Local Evidence Brief from existing PHASE1/PHASE2 evidence only.

Historical logs below may still mention LLM/PHASE3 work. Those entries are retained as time-stamped historical records, not active implementation guidance.

---

## 2026-05-17: Sprint A3 — PHASE2 rule-based detector family registration

### 상황

A2에서 고정한 `leaderboard.json` / `promotion_decision.json` / `inference_contract` schema v1 위에 `timeseries`, `relational`, `duplicate`, `intercompany` rule-based detector를 PHASE2 family로 통합했다. 기존 detector의 `detect()` 로직과 V7 fixed3 데이터, dashboard 파일은 변경하지 않았다.

### 해결

- `_DEFAULT_DETECTOR_FACTORIES`, `_DEFAULT_SEARCH_PRESETS`, `_FAMILY_TO_CANONICAL_MODEL`, `_PROMOTED_TRACK_MAP`에 4개 family 등록을 고정했다.
- 기본 active family를 `unsupervised` 1개에서 `unsupervised + timeseries + relational + duplicate + intercompany` 5개로 확장했다.
- rule-style family는 `model_bundle.pt` 대신 `phase2_<family>/vNNNN/calibration_metadata.json`을 저장한다.
- leaderboard metric은 family별 이름(`burst_detection_rate`, `new_counterparty_precision`, `fuzzy_match_f1`, `ic_match_completeness`)으로 저장하고 `metric_interpretation=rule_proxy_score`를 붙였다.
- promotion policy는 artifact-less family를 허용하면서 최소 completed trial, metric threshold, search diversity, failure ratio를 유지한다.
- `sequence` D047 guard는 BiLSTM/user-temporal family 전용이며 신규 `timeseries` burst/frequency rule family에는 적용하지 않는 정책을 문서화했다.

### 회귀 가드

- `uv run pytest tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_detector_expansion.py -q` -> 47 passed.
- `uv run pytest tests/modules/test_preprocessing/test_label_strategy.py tests/modules/test_detection/test_supervised_detector.py tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_layer_a_guards.py tests/modules/test_services/test_phase2_case_contract.py tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_detector_expansion.py -q` -> 96 passed.

---

## 2026-05-18: Sprint UI-A4 Phase2 Streamlit alignment

### 문제

Phase A에서 PHASE2 train/infer contract와 9 family registry가 준비됐지만 Streamlit은 기존 Phase2 result/provenance 중심 화면에 머물렀다. 사용자에게 `Not trained`, `Training report available`, `Inference complete` 상태가 분리되어 보이지 않았고, 9 family matrix, 13 sub-detector hit, year partition, `leaderboard.json`/`promotion_decision.json` sidecar가 한 화면에서 소비되지 않았다.

### 해결

`dashboard/tab_phase2.py`에 3-state header와 2022/2023/2024/전체 partition selector를 추가했다. 신규 컴포넌트 3종을 추가해 family matrix, sub-detector hit grid, leaderboard/promotion decision table을 분리했다. `load_latest_phase2_training_snapshot()`은 latest `training_report.json` 옆의 `leaderboard.json`과 `promotion_decision.json`을 함께 읽도록 확장했고, `run_phase2_inference_analysis()`는 선택된 `fiscal_year` partition으로 입력 DataFrame을 필터링할 수 있게 했다.

Intercompany는 Diag-1 UI Meta Contract를 반영해 active family로 표시하고 IC01-only / IC02·IC03 carry-over를 명시한다. Duplicate detector 코드는 변경하지 않았고, Diag-2 성능 계약은 `tests/modules/test_detection/test_duplicate_performance.py`로 재검증했다.

### 검증

- `uv run pytest tests/modules/test_dashboard/test_tab_phase2.py tests/modules/test_dashboard/test_phase2_family_matrix.py tests/modules/test_dashboard/test_phase2_subdetector_grid.py tests/modules/test_dashboard/test_phase2_leaderboard_view.py tests/modules/test_services/test_phase2_inference_service.py -q` -> 27 passed.
- `uv run ruff check dashboard/tab_phase2.py dashboard/components/phase2_family_matrix.py dashboard/components/phase2_subdetector_grid.py dashboard/components/phase2_leaderboard_view.py src/services/phase2_inference_service.py tests/modules/test_dashboard/test_tab_phase2.py tests/modules/test_dashboard/test_phase2_family_matrix.py tests/modules/test_dashboard/test_phase2_subdetector_grid.py tests/modules/test_dashboard/test_phase2_leaderboard_view.py tests/modules/test_services/test_phase2_inference_service.py` -> PASS.
- `uv run python -c "import dashboard.app"` -> PASS with expected bare Streamlit `ScriptRunContext` warnings.
- `uv run pytest tests/modules/test_detection/test_duplicate_performance.py -q` -> 2 passed.
- `uv run pytest tests/modules/test_dashboard -q` -> 213 passed, 1 existing failure in `test_tab_phase1.py::test_phase1_render_uses_compact_four_tab_layout` because `_render_year_over_year` is absent in current `dashboard/tab_phase1.py`; forbidden PHASE1 UI files were not edited.

### Notes

`git diff -- dashboard/components/rule_panel.py dashboard/tab_phase1.py dashboard/tab_overview.py` was blocked by the user's PreToolUse hook. Fallback inspection found the new PHASE2 component imports only in `dashboard/tab_phase2.py`, and no `priority_score`, `composite_sort`, or `queue.parquet` references in the touched PHASE2 UI/service files.

---

## 2026-05-17: Stage 5~7 — PHASE2 첫 학습 + Layer A/B/C 가드 + Review Queue 통합

### 상황

`datasynth_manipulation_v7_candidate_fixed3` 기준으로 PHASE2 unsupervised autoencoder MVP의 첫 학습을 수행하고 (Stage 5), 학습 결과를 Layer A(학습 누설)/B(모델 품질)/C(PHASE1 정합) 3트랙으로 검증한 뒤 (Stage 6), Phase2CaseOverlay로 PHASE1 case와 결합하여 Review Queue + Phase 3 Narrator 입력 계약을 산출했다 (Stage 7).

### Stage 5 산출

- 모델 번들: `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/model_bundle.pt`
- 학습 리포트: `.../v1/training_report.json`
- ECDF 학습 분포: `.../v1/ecdf_train_distribution.npz`
- 핵심 메타: dataset=`datasynth_manipulation_v7_candidate_fixed3`, training_mode=`unsupervised_autoencoder_mvp`, loss=`reconstruction_only_mse_plus_kl`, target_used=false, fit_split=train, split_strategy=`group_by_document_id`, epochs=40, train_rows=80,000, val=19,999, test=50,000.

### Stage 6 — Layer A/B/C 검증

| 트랙   | 정책        | 결과         | 산출물                                              |
|--------|-------------|--------------|-----------------------------------------------------|
| A      | HARD        | GO (8/8)     | `artifacts/phase2_layer_a_audit_2026-05-17.{md,json}` |
| B      | HARD        | GO (5/5)     | `artifacts/phase2_layer_b_audit_2026-05-17.{md,json}` |
| C      | SOFT WARN   | SOFT-INFO    | `artifacts/phase2_layer_c_audit_2026-05-17.{md,json}` |

- A1~A8 모두 PASS: dataset_version 고정, deny-list 76+ 제외 (row-level 53 + raw header 36), document_id group split + 누수 cross-check, fit→transform 순서, target_used=false, reconstruction loss only.
- B1~B5 모두 PASS: val/train recon ratio 1.0809 (overfit 아님), test↔val drift 0.1577 (≤0.5), KS=0.7224 (강한 분리), ECDF 일관성, top-1% scenario entropy 0.8393 (truth 시나리오 다양성 기준).
- C1 PASS (PHASE1 priority_score 비파괴), C2~C4 INFO. top-500 overlap=0.03은 보완성 기준의 하한이지만 PHASE2가 PHASE1 누락 신호를 신규 발굴하는 구성으로 해석한다. truth recall 수치(C3/C4)는 `feedback_phase1_truth_recall_guard`에 따라 informational only.

### Stage 7 — Review Queue + Narrator 입력 계약

- 산출물: `data/companies/_ci_baseline/engagements/2026/review_queue/v1/queue.parquet` (41,129 rows × 24 cols), `queue_top500.parquet`, `queue_top100.parquet`.
- HARD checks: `priority_score_preserved=True` (mismatch 0/41,129), `narrator_required_fields_present=True` (6 필드 결측 0), `composite_sort_v1_lock_compliant=True`.
- sort keys: `phase1_composite_sort_score`, `phase1_triage_rank_score`, `total_amount`, `rule_count`. `phase2_score`는 보조 컬럼이며 sort key가 아니다 (V1 lock 유지).
- 통합 리포트: `artifacts/phase1_phase2_integration_report_2026-05-17.{md,json}` → **GO**.

### 교훈

1. PHASE2 학습 누설 가드는 단일 메타 키(dataset_version, fit_split, target_used)만 검사하지 않고 `epoch_history` 키 집합까지 검사해야 한다. label-based loss 키(`bce_loss`, `cross_entropy_loss` 등)가 부재한지 확인하면 reconstruction-only 정책의 자동 회귀 가드가 된다.
2. PHASE1↔PHASE2 overlay는 sort key를 보존해야 한다. `phase2_score`를 정렬 키로 끼우는 순간 V1 lock이 깨지므로 보조 컬럼으로만 노출한다.
3. Synthetic truth metrics are informational. PHASE1/PHASE2 changes must rest on domain policy and leakage/noise controls.

### 교차 참조

- DataSynth V7 fixed3 patched 품질 게이트: [completed/datasynth.md](completed/datasynth.md) §해당 항목.
- DataSynth fixed3 승격 결정 기록: [DECISION.md](DECISION.md) D050.
- Layer A/B/C 가드 체계 및 A3/A4 운영 임계 결정 기록: [DECISION.md](DECISION.md) D051.
- PHASE1 rule detail audit note의 PHASE2 overlay 메모: [dev/active/phase1-rule-detail-audit-note.md](../dev/active/phase1-rule-detail-audit-note.md) §PHASE2 overlay 반영 노트.

---

## 2026-05-17: detection explanation metadata-only sprint

Sprint B3-meta added a frozen `RuleExplanation` schema and a registry entry point for future UI/export explanation work without changing PHASE1 dashboard files or detector `detect()` behavior. Active coverage is canonical L1-L4 32 rules plus `D01`/`D02`, with metadata stored as detector-owned constants and aggregated by `src/detection/explanation_registry.py`.

Verification passed with `uv run pytest tests/modules/test_detection/test_explanation_schema.py tests/modules/test_detection/test_explanation_registry.py tests/modules/test_detection/test_rule_detail_metadata.py tests/modules/test_detection/test_rule_scoring.py -q` and targeted ruff. Handoff: `artifacts/sprint_phaseA_B3_handoff_2026-05-17.md`.

---

## 2026-05-15: Stage 2 split leakage guard 적용

### 상황

S2 fitting audit에서 row-level random KFold가 document/user leakage를 만들 수 있음이 확인되어 Phase 2 CV 선택 정책을 코드 경로에 고정해야 했다.

### 해결

- `cv_selector.build_user_group_kfold()` 추가: `created_by` 기준 GroupKFold를 만들고, unique user 수가 `n_splits`보다 작으면 경고 후 `document_id` GroupKFold로 폴백한다.
- `cv_selector.select_split_strategy()` 추가: user feature 사용 시 user GroupKFold, temporal holdout 필요 시 `split_user_year_holdout`, 기본은 document GroupKFold를 선택한다.
- row-level `KFold`가 `_ensure_group_kfold()`로 들어오면 `ValueError`를 발생시켜 Phase 2 평가에서 임의 row split을 차단한다.
- `ensemble_detector.train_oof()`가 받은 `user_ids`가 실제 `X["created_by"]`와 일치하는지 검증하고, 각 fold의 user overlap도 재확인한다.

### 회귀 가드

`test_groupkfold_zero_user_overlap`, `test_random_split_rejects_row_level`, `test_stage2_thresholds_holds`로 S2 split 정책과 AUC gap 임계값을 고정했다.

---

## 2026-05-15: Stage 8 — Stacking OOF protocol 재검증

### 상황

`phase2_ml_feasibility.md §3` 의 OOF Stacking 구현 (`ensemble_detector.train_oof`) 이 "룰/VAE 1회 학습 + supervised/transformer/sequence OOF 재학습" 정책을 사용한다. v3 dataset (manipulation_v3) 에서 4개 ablation 으로 누수 효과와 룰 트랙 메타 가중치 비중을 정량 측정.

### 결과

| 지표 | 값 | 임계 | 판정 |
|---|---|---|---|
| AUPRC(A) − AUPRC(B) | +0.0009 | > +0.02 | 정책 유지 |
| 룰 4트랙 가중치 비중 (A) | 2.2% | > 50% | 균형 유지 |

전체 AUPRC: A=0.9988, B=0.9979, C=0.9964, D=0.1302. ml_supervised 가중치 0.8987 로 절대 우세.

### 관찰

`approval_sod_bypass` 시나리오만 단일 +0.1461 gap 발생 (layer_b 룰의 fold-wise refit 노이즈). 다른 5개 시나리오는 |Δ| < 0.003. 전체 영향이 미미한 이유: ml_supervised 가 동일 시나리오를 동급 이상으로 잡음.

### 결정

현 정책 (`_LEAKAGE_PRONE_TRACKS = (ML_SUPERVISED, ML_TRANSFORMER, ML_SEQUENCE)`) 유지. 룰/VAE 의 1회 학습 정책은 본 dataset 에서 누수 효과를 만들지 않는다. `S8_stacking_policy_patch.md` 미생성.

### 산출물

- `tools/analysis/s8_stacking_oof_ablation.py`
- `artifacts/S8_stacking_oof_ablation.json`
- `docs/completed/S8_stacking_oof_audit.md`

### 교훈

1. 룰 detector 가 stateless API 라 명시적 train/apply 분리가 없어도, fold-wise 호출에서 통계 임계값 (z-score, Benford expected, 분포 quantile) 이 fold 분포로 재계산되어 fold-sensitive 효과는 측정 가능하다.
2. Ridge(positive=True) 의 자동 sparsification 으로 본 dataset 에서 layer_a/layer_c/benford weight = 0. 4 트랙 max-aggregation 이 ml_supervised 와 강한 공선성 → 룰 트랙 단독 부가가치 제한적.
3. 시나리오별 분해는 전체 평균이 안정적이어도 개별 시나리오 영향 (approval_sod_bypass +0.1461) 을 드러내며 PHASE2 회귀 KPI 의 시나리오별 추적 필요성을 시사한다.

---

## 2026-05-15: Phase 3 v2 Sprint E2 — 감사인 워크플로우 (실행 트리거 + 분류 + 필터)

### 상황

Sprint E1 완료(카드 렌더 + citation 점프) 위에 감사인 워크플로우를 얹어야 한다. 요구사항: `review_narratives`에 분류·메모 4컬럼 idempotent 추가, `update_audit_decision` UPSERT 헬퍼, AuditTrail EventType 확장(`analysis_run` / `review_decision_change`), 사이드바 6종 필터·검색, 분석 실행 트리거(N·예산·진행률), 분류 라디오·메모 + DB 저장. Sprint E1 회귀를 깨지 않은 채 통합.

### 해결

- `src/db/schema.py` SCHEMA_DDL에 idempotent ALTER 4컬럼(`audit_decision`/`audit_note`/`reviewed_by`/`reviewed_at`) + `idx_review_narratives_decision` 인덱스, `AUDIT_DECISION_VALUES` frozenset 상수 노출.
- `src/llm/review_narrator/cache.py::update_audit_decision`(invalid decision·빈 user·candidate 미존재 가드 3중 검증, `reviewed_at`은 `datetime.now(UTC).replace(tzinfo=None)`) + `read_audit_decision`(라디오·메모 위젯 기본값 복원용 4컬럼 SELECT).
- `src/export/audit_trail.py` EventType Literal에 `analysis_run` / `review_decision_change` 2종 추가. `VALID_EVENT_TYPES`는 `get_args()`로 자동 파생 → 기존 audit_trail 회귀 자동 호환.
- `dashboard/components/review_queue_workflow.py` 신규 — 순수 함수 5개 (`ReviewQueueFilters` dataclass, `apply_filters`(6차원: confidence/priority_rank/process/batch_id/audit_decision[unassigned sentinel 포함]/rule_ids 교집합), `apply_search`(candidate_id 부분일치·대소문자 무시), `compute_run_plan`(N ladder 20→10→5 + 비용 추정), `register_review_decision`(UPDATE + AuditTrail.log 묶음, trail 실패는 흡수)).
- `dashboard/tab_review_queue.py` 확장 — 기존 E1 카드/citation 흐름 유지 위 + 사이드바 필터 + 검색 박스 + 실행 트리거 섹션(N number_input·예산·진행률·재생성[input_hash 비교]) + candidate별 분류 라디오·메모 위젯 + `AuditTrail.log` `analysis_run`/`review_decision_change`.
- `dashboard/_state.py`에 E2 6키(`KEY_REVIEW_QUEUE_FILTERS`/`SEARCH`/`LAST_HASH`/`RUN_STATUS`/`RUN_ERROR`/`TARGET_N`) + `_DEFAULTS` 등록.
- 테스트 38건 신규 — cache(`update_audit_decision` UPSERT/overwrite/none clear/narrative 무영향/invalid·empty user·missing candidate/read 헬퍼) 9, workflow(`apply_filters` 10/`apply_search` 5/`compute_run_plan` 6/`register_review_decision` 4/AuditTrail EventType 3/UI 진입점 1) 29. Sprint E1 회귀 2건은 E2 통합으로 추가 위젯이 그려지면서 columns 단언이 의미를 잃어 `_stub_streamlit_layout` 공용 stub으로 패치.

### 결과

| 항목 | 결과 |
|---|---:|
| 단위 테스트 (cache 신규) | 9 / 9 PASS |
| 단위 테스트 (workflow 신규) | 29 / 29 PASS |
| Sprint E1 회귀 (호환 패치) | 9 / 9 PASS |
| review_narrator 누적 | 117 / 117 PASS |
| audit_trail 회귀 | 15 / 15 PASS |
| 통합 누적(E1+E2+cache+audit_trail) | 171 / 171 PASS |
| dashboard import smoke | OK |

### 교훈

1. Streamlit 함수에 import 추가만 한 edit는 ruff(hook)가 미사용으로 즉시 제거한다. 동일 edit에서 사용 코드까지 함께 넣거나, 함수 스코프 inline import로 회피해야 한다.
2. `EventType = Literal[...]`과 `VALID_EVENT_TYPES = frozenset(get_args(EventType))` 패턴을 유지하면 새 이벤트 타입 추가 시 회귀 테스트가 자동으로 6→8종을 검증한다. 단일 진실 공급원 효과 확인.
3. pyright는 `iterrows()` row의 컬럼 접근을 Series로 추론한다. `row.to_dict()`로 우회하거나 `isinstance(value, str)` 가드를 함께 두면 narrowing이 안정적.
4. UI 통합 테스트의 stub은 위젯 컨텍스트 매니저(`with st.expander(...)`)까지 받아야 하므로 `_DummyCtx`의 `__getattr__`이 다음 호출에서 다시 `_DummyCtx`를 반환하도록 자기참조해야 한다. 단순 lambda → None 반환은 컨텍스트 매니저 프로토콜 실패.
5. Sprint E1 회귀가 빈 narratives 시 `columns 호출 금지`를 단언했다면, E2 통합으로 사이드바·트리거·검색이 추가되는 순간 단언이 깨진다. 회귀 의도(빈 안내 메시지 발생)만 유지하고 columns 단언은 완화해야 진화 가능.

---

## 2026-05-15: Phase 3 v2 Sprint E1 — Review Queue Narrator 대시보드 렌더링

### 상황

Sprint C 완료(Narrator + Cache + 통합 테스트)에 이어 RC-4 미진입 상태에서 Narrator 출력을 표시할 임시 탭을 새로 만든다. 입력은 세션에 적재된 `KEY_REVIEW_QUEUE_NARRATIVES`(list[dict]) + `KEY_REVIEW_QUEUE_CANDIDATE_INDEX`(citation 점프용)이며, 본 Sprint는 표시·렌더링만 다루고 실행 트리거·재생성·필터·분류는 Sprint E2 범위로 분리.

### 해결

- `dashboard/_state.py`에 `KEY_REVIEW_QUEUE_NARRATIVES / SELECTED_CANDIDATE / CITATION_TARGET / INPUT_HASH / CANDIDATE_INDEX` 5개 키 + `PAGE_REVIEW_QUEUE` 추가, 기본값 dict까지 등록.
- `dashboard/components/review_narrator.py`에 카드 컴포넌트(`render_candidate_card`)를 분리. priority_rank + confidence chip(green/amber/red) + summary + reasoning(인용 버튼) + suggested_actions 구조.
- `dashboard/components/review_narrator_jump.py`에 citation 점프 패널 분리. rule_hit은 `rule_detail_metadata.asdict()` 평탄화 후 핵심 필드 + 전체 JSON expander, ml_feature는 `candidate.ml_scores` 매칭, row는 `result.data`에서 journal_id/document_id + line_no 필터.
- `dashboard/tab_review_queue.py`에 좌측 카드 + 우측 jump 2열 레이아웃, priority_rank 오름차순 정렬, `KEY_REVIEW_QUEUE_INPUT_HASH` 변경 시 직전 점프 표적 자동 무효화.
- `app.py`에 5번째 탭으로 등록(`PAGE_REVIEW_QUEUE`).
- 테스트 9건 추가: 정렬 / 빈 입력 / 카드 호출 / citation 클릭 → 세션 상태 / 해시 변경 무효화 / 해시 동일 유지 / citation label 포맷 3종 parametrize.

### 결과

| 항목 | 결과 |
|---|---:|
| 단위 테스트 (신규) | 9 / 9 PASS |
| dashboard 회귀 테스트 | 175 / 175 PASS |
| review_narrator 회귀 테스트 | 118 / 118 PASS |
| Streamlit boot (`/`) | HTTP 200 |
| Streamlit boot (`/healthz`) | `ok` |

### 교훈

1. PHASE3 v2 대시보드는 입력(candidate dict)이 변경되면 직전 citation 표적이 유효하지 않을 수 있다. Sprint E1은 `_invalidate_jump_on_hash_change`에서 해시 변경 시 표적과 선택 candidate를 함께 비워 stale 상태를 차단.
2. `RuleDetailMetadata`는 pydantic이 아닌 frozen dataclass라 `model_dump`가 없다. `dataclasses.asdict`로 평탄화해 dict 접근 패턴을 유지.
3. `data[mask]`는 pyright가 ndarray로 해석하는 케이스가 있어 `data.loc[mask]`로 명시 캐스팅이 더 안전.
4. Sprint E1은 표시 전용이며, citation 표적 적재/해시 무효화는 작은 헬퍼(`_set_citation_target`, `_invalidate_jump_on_hash_change`)로 분리해 E2의 트리거·분류 UI가 동일 키를 재사용하도록 한다.

---

## 2026-04-18: Streamlit UI 리팩터링 중 반복 실수 정리

대시보드 개요 탭 Before/After 재구성 + KPI 카드·차트 레이아웃 작업 중 여러 차례 시행착오. 같은 실수를 반복하지 않기 위한 기록.

### 1. `position: sticky` 불안정 — Streamlit DOM에서 시행착오 반복

**상황**: 원본 데이터 미리보기 테이블을 컬럼 매핑 스크롤 시 상단에 고정하려 `position: sticky` 여러 번 시도.

**실패 원인**:
- Streamlit `stMain`, `stMainBlockContainer`, `stVerticalBlockBorderWrapper` 등 scroll container 체인이 복잡해 sticky가 안정적으로 작동하지 않음.
- `:has()` selector로 marker 기반 scope를 시도했으나 DOM 구조가 버전마다 달라 예측 불가.

**치명 실수**: sticky를 억지로 작동시키려 `html, body, stMain, stMainBlockContainer` 전체에 `overflow: visible !important`를 강제 → **페이지 스크롤 자체가 막힘**.

**교훈**:
- Streamlit 전역 컨테이너의 `overflow`를 건드리지 말 것. Streamlit의 스크롤 메커니즘은 이들 컨테이너에 의존.
- 단일 컬럼 내 sticky는 포기. `st.columns` 레이아웃에서 **좌우 분할 + `stColumn` 자체를 sticky로**가 유일하게 안정적.
- 근본적으로 안 되는 패턴은 대체 UX(접을 수 있는 expander, inline 샘플값)로 전환하는 판단이 필요.

### 2. Streamlit `container(border=True)` 내부 flex center가 안 먹는 원인

**상황**: KPI 카드 내부에 `display:flex; justify-content:center`로 content를 중앙 정렬했는데 **항상 상단으로 치우침**.

**근본 원인**:
```
stVerticalBlock[data-has-border="true"]  ← flex column
  └ stElementContainer                     ← flex item, 기본은 flex:0 (content 크기)
     └ stMarkdown / stMarkdownContainer   ← 상하 비대칭 padding 기본값
        └ 내 HTML div (height:100% flex center)
```

- `stElementContainer`에 `flex: 1`이 없으면 **content 크기**로만 계산됨. 내 `height:100%`는 content 크기 안에서만 작동.
- `stMarkdown` 계열 wrapper가 숨겨진 상하 비대칭 padding을 추가해 시각적으로 상단에 쏠림.

**해결**:
```css
[data-has-border="true"] {
    display: flex !important;
    flex-direction: column !important;
}
[data-has-border="true"] > [data-testid="stElementContainer"] {
    padding: 0 !important;
    margin: 0 !important;
}
[data-has-border="true"] > [data-testid="stElementContainer"]:only-child {
    flex: 1 !important;
    height: 100% !important;
}
[data-has-border="true"] [data-testid="stMarkdown"],
[data-has-border="true"] [data-testid="stMarkdownContainer"] {
    padding: 0 !important;
    margin: 0 !important;
    height: 100% !important;
}
```

자식이 여러 개(헤더+차트)면 `:only-child` 대신 명시적 height로 관리. `:last-child` 만 flex:1로 하면 마지막 요소(footer)가 엄청 늘어나므로 주의.

**교훈**:
- `height: 100%`는 **부모가 확정 높이**일 때만 작동. flex 체인을 완전히 연결해야 함.
- Streamlit wrapper(`stElementContainer`, `stMarkdown`, `stMarkdownContainer`)의 숨겨진 기본 padding을 명시적으로 리셋해야 함.

### 3. 전역 CSS scope 미적용 — 다른 페이지 레이아웃까지 망가뜨림

**상황**: KPI 카드 flex center를 위해 `[data-has-border="true"]`에 전역 CSS 규칙(`padding:0`, `overflow:hidden`, `display:flex`)을 강제 → **engagement selector**, **기타 모든 `container(border=True)` 페이지** 레이아웃 붕괴.

**해결**: marker class 기반 scope 제한.
- tab_overview의 모든 카드 내부 HTML에 `<div class="tab-overview-scoped">` 삽입.
- CSS selector를 `:has(.tab-overview-scoped)`로 한정.

```css
[data-has-border="true"]:has(.tab-overview-scoped) {
    padding: 0 !important;
    ...
}
```

**교훈**:
- Streamlit 전역 CSS는 **처음부터 scope를 제한**할 것. 추상적 testid(`data-has-border`)는 모든 페이지에 공통이라 전역 적용 = 모든 페이지 영향.
- 특정 탭/페이지 전용 스타일은 marker class로 감싸고 `:has()` / descendant selector로 한정.

### 4. Plotly chart 이중 border

**상황**: `st.container(border=True)` 안에 Plotly chart를 넣으면 **카드 border + Plotly 자체 border**로 이중 테두리.

**원인**: `styles.py`에 `[data-testid="stPlotlyChart"] { border: 1px solid; padding: 0.5rem; background: var(--c-bg); }` 전역 카드 스타일이 있었음.

**해결**: Plotly 자체 카드 스타일을 전역 제거. 필요한 곳만 `container(border=True)`로 감쌈.
```css
[data-testid="stPlotlyChart"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
}
```

**교훈**: Plotly/다른 위젯에 "카드 효과"를 전역으로 주면 container와 겹침. UI 일관성은 **container 래핑**으로 통일하고 위젯 자체 스타일은 투명하게 두는 것이 안전.

### 5. `st.markdown` triple-quoted HTML이 코드블록으로 렌더됨

**상황**: `st.markdown("""<div>...</div>""", unsafe_allow_html=True)`에서 들여쓰기 4칸 + 빈 줄 조합이 있으면 **HTML이 그대로 문자열로 노출**.

**원인**: Streamlit markdown은 들여쓰기 4칸+빈 줄을 **코드블록 시작 신호**로 오인.

**해결**: HTML을 단일 라인 concat으로 작성.
```python
html = (
    "<div style='...'>"
    f"<div>{label}</div>"
    f"<div>{value}</div>"
    "</div>"
)
st.markdown(html, unsafe_allow_html=True)
```

**교훈**: `st.markdown` + triple-quoted HTML은 **들여쓰기 없이** 또는 **textwrap.dedent()** 로 정규화할 것. 빈 줄은 절대 섞지 말 것.

### 6. 파일명 추출 `rsplit('_', 1)` 버그

**상황**: `journal_entries_2022.csv` 같은 파일명이 **`journal_entries`**로 잘려 표시됨.

**원인**: `upload_key.rsplit("_", 1)[0]`로 size를 제거하려 했으나 파일명 자체에 `_`가 있으면 잘못 잘림. DB 재로드 경로에선 size 없이 절대경로만 저장되어 더 심각.

**해결**: 정규식으로 **뒤에 붙은 `_숫자`만** 선택 제거.
```python
def _extract_file_name(upload_key: str) -> str:
    if not upload_key:
        return "데이터"
    name = Path(upload_key).name or upload_key
    m = re.match(r"^(.+)_(\d+)$", name)
    return m.group(1) if m else name
```

**교훈**: 문자열 파싱 시 **delimiter가 content에 포함될 가능성**을 반드시 고려. 가능하면 정규식으로 제약.

### 7. Round 반올림으로 "불일치 있는데 100% 일치" 표시

**상황**: 불일치 2건 / 106,163건 → `rate = 99.998%`를 `f"{rate:.2f}%"`로 포맷 → **"100.00% 일치 · 불일치 2건"** 모순 메시지.

**해결**: `math.floor`로 내림.
```python
rate = math.floor((total - mismatches) / total * 10000) / 100
```

**교훈**: 부정합 감지 메시지에서 **100% 표기는 0건 일치 때만 허용**. 표시 목적의 rate 계산은 항상 **round보다 floor**가 의미 보존 측면에서 안전.

### 8. `st.columns` 내부에서 `st.spinner` + `st.progress` 실행 시 텍스트 두 줄 잘림

**상황**: 매핑 확인 버튼을 `st.columns([1, 1, 6])`의 첫 column에 두고 그 안에서 spinner/progress 실행 → **1/8 폭에 갇혀 텍스트 두 줄**.

**해결**: `st.empty()` placeholder를 column **바깥 풀 폭**에 생성, 버튼 클릭 시 placeholder에 렌더.
```python
progress_area = st.empty()        # 풀 폭
btn_col, _, _ = st.columns([1,1,6])
with btn_col:
    clicked = st.button("실행")
if clicked:
    with progress_area.container():
        with st.spinner("..."): ...
```

**교훈**: Streamlit에서 **진행률/스피너는 폭이 좁은 column 안에서 실행하지 말 것**. placeholder는 column 바깥에서 선언하고 나중에 채움.

### 9. `st.container(border=True)` 내부 다중 자식일 때 `:last-child`에 `flex:1` 주면 footer가 늘어남

**상황**: 차트 카드에 헤더 + 차트 + footer 3자식 구조. `:last-child` (footer)에 `flex:1`이 적용되어 **footer가 거대하게 늘어나고 차트가 찌그러짐**.

**해결**: `:only-child`만 `flex:1` 적용. 자식 여럿이면 각 자식은 content 크기, 차트는 명시적 height.

**교훈**: CSS `:last-child`는 자식 수 조건을 검증하지 않음. **자식 1개**만 flex stretch하려면 `:only-child` 사용.

### 10. 공통 교훈 — Streamlit 레이아웃 작업 체크리스트

| 항목 | 확인 |
|------|------|
| 전역 CSS를 추상적 testid에 적용 | 절대 금지. 반드시 marker scope. |
| Plotly 차트에 전역 border/padding | 금지. container 래핑으로 통일. |
| `position: sticky` | 단일 컬럼 내는 불안정. 좌우 분할 + `stColumn` sticky만 사용. |
| `overflow: visible` 전역 강제 | 페이지 스크롤 파괴. 절대 금지. |
| `st.markdown` + triple-quoted HTML | 들여쓰기/빈 줄 금지. 한 줄 concat. |
| `st.columns` 내부 spinner/progress | 금지. 풀 폭 `st.empty()` placeholder 사용. |
| 파일명 파싱 | delimiter를 content에 포함 가능성 고려. regex 우선. |
| 불일치 rate 계산 | `round` 대신 `floor`로 100% 표기 회피. |
| `container(border=True)` flex center | `display:flex + flex-direction:column` 전파 + `:only-child`에 `flex:1` 필수. |

---

## 2026-04-14: DataSynth 두 핵심 버그 근본 수정 (Rust)

**배경**: 전수조사에서 ML 학습 불가 수준의 두 버그 발견.
1. **라벨-entry 동기화 실패**: `anomaly_labels.csv` 8,337건 vs `journal_entries.csv` `is_fraud=true` 339건 (1/18 미달)
2. **reference 컬럼 MCAR 위반**: 정상 2.40% vs 비정상 10.55% NULL (차이 8.15%p) → ML 지름길 학습 위험

### 근본 원인

**버그 1 — T5-31 / T5-27 역방향 라벨 entry 마킹 누락**
(`crates/datasynth-runtime/src/enhanced_orchestrator.rs` 2585-2666)
- SelfApproval 패턴(`created_by == approved_by`) 발견 시 라벨만 `anomaly_labels.labels.push()`
- entry의 `is_fraud`/`is_anomaly`/`fraud_type`/`anomaly_type` 마킹 **누락**
- Fraud 라벨 5,968건 중 **5,931건이 REV-SA prefix** (역방향 라벨) → CSV 미반영
- UnbalancedEntry도 동일한 구조적 누락 (T5-27)

**버그 2 — DocumentationStrategy의 reference NULL화**
(`crates/datasynth-generators/src/anomaly/strategies.rs` 1884-1891)
- `MissingDocumentation` anomaly가 `entry.header.reference = None` 설정
- `reference`는 문서 체인 FK인데 비정상에서만 NULL화 → MCAR 규칙 위반
- 이후 data_quality MCAR(전역 2%)이 추가로 적용되어 비정상 10.55% vs 정상 2.40%

### 수정 내용

**Fix 1: T5-31 SelfApproval 역방향 라벨 + entry 마킹**
- `entries.iter()` → `entries.iter_mut()` 변경
- 라벨 push와 동시에 entry.header에 is_fraud=true, is_anomaly=true, fraud_type=SelfApproval, anomaly_type="SelfApproval", anomaly_id 마킹

**Fix 2: T5-27 UnbalancedEntry 역방향 라벨 + entry 마킹**
- target_docs HashSet 먼저 추출 → entries.iter_mut() 별도 루프에서 is_anomaly/anomaly_type 마킹
- 중복 라벨 방지 (doc_id 기준 dedupe)

**Fix 3: DocumentationStrategy 근본 변경**
- `reference = None` 제거 (FK 보호)
- `header_text = None` 제거 (MCAR 편향 방지)
- `has_attachment = false` + `supporting_doc_type = None`만 유지 (도메인 의미상 정확)

### 검증 결과 (재생성 후)

| 항목 | 이전 | 이후 | 판정 |
|------|------|------|:----:|
| Fraud 라벨 → is_fraud=true | 0.7% | **100.0%** | PASS |
| Fraud 라벨 → is_anomaly=true | 1.1% | **100.0%** | PASS |
| Relational/Statistical/Error/ProcessIssue → is_anomaly=true | ~100% | **100%** | PASS |
| is_fraud 전체 비율 | 0.11% | **1.96%** (설정 2% 근접) | PASS |
| reference MCAR 차이 | 8.15%p | **1.97%p** (<2%p) | PASS |
| header_text MCAR 차이 | 0.23%p | **0.25%p** | PASS |
| SelfApproval: created=approved vs fraud_type=SelfApproval | 5,932 vs 1 | **5,932 vs 5,932** | PASS |

### 잔여 이슈 (부차)
- `tax_code` MCAR 차이 4.32%p: 도메인 특성(비정상 데이터의 과세 대상 거래 비율이 낮음)으로 해석. MCAR 대상이 아닌 결정론적 필드이므로 ML 지름길 학습 유발 가능성 낮음.

### 파일
- `tools/datasynth/crates/datasynth-runtime/src/enhanced_orchestrator.rs` (T5-27, T5-31 수정)
- `tools/datasynth/crates/datasynth-generators/src/anomaly/strategies.rs` (DocumentationStrategy 수정)
- 빌드: `cd tools/datasynth && cargo build --release -p datasynth-cli` (13분)
- 재생성: `./target/release/datasynth-data.exe generate -c ../../config/datasynth.yaml -o ../../data/journal/primary/datasynth --seed 2024`

---

## 2026-04-11 (오후): Phase 2 잔여 과제 4묶음 해결 (코드 독립 작업)

**배경**: 오전 세션에서 4대 결함(P0-1 / P0-2 / P1-1 / P1-2)을 해결한 뒤, 남은 14개
항목을 **데이터 재생성 없이 해결 가능한 묶음 4개**로 분할하여 처리. 재생성은 마지막
세션으로 분리 예정.

### 묶음 1 — 설명력 기반 (4개 / 35 tests 신규)

- **BiLSTM `get_attention_weights()` 노출** (`bilstm_wrapper.py`)
  - `AuditBiLSTM.forward()`가 이미 계산·저장하던 `_attn_weights`를 public API로 노출
  - `(n_windows, seq_len)` 반환, 소프트맥스 후 각 행 합 ≈ 1, 마스킹 위치는 0
- **FT-Transformer attention 추출** (`ft_model.py`, `ft_wrapper.py`)
  - `AuditFTTransformer.forward_with_attention()` 신규 — `nn.TransformerEncoder`의
    fast-path 최적화 우회하기 위해 각 layer의 `self_attn`을 수동 실행하여 weights 추출
  - `FTTransformerClassifier.get_attention_weights()` 신규 — `[CLS] → 피처` 토큰
    attention을 `(n_samples, n_features)` 로 반환
- **`drift_detector.py` + PSI 함수** (신규 파일)
  - `compute_psi_numeric` (가우시안 bin 기반, baseline_mean/std만으로 작동)
  - `compute_psi_categorical` (baseline top-N + `_OTHER_` 버킷)
  - `compute_drift_report` (`ModelMetadata` + `current_df` → `DriftReport`)
  - 임계값: `DRIFT_THRESHOLD_WARN=0.1`, `DRIFT_THRESHOLD_CRITICAL=0.25`
- **risk_level 분위수 전환** (`score_aggregator.py`, `config/settings.py`)
  - `classify_risk_level(mode="absolute"|"quantile", quantiles=...)` 모드 분기
  - `settings.risk_classification_mode` + `risk_quantile_high/medium/low`
  - score=0인 행은 rank가 높아도 NORMAL 보존 (실제 위험 없음)

### 묶음 2 — 파이프라인 관측성 (3개 / 11 tests)

- **탐지기 병렬 실행 헬퍼** (`pipeline.py`)
  - `_run_detectors_parallel(detectors, df, max_workers, progress_callback)`
  - ThreadPoolExecutor (pandas/numpy GIL 해제 활용 — ProcessPool은 DataFrame
    pickle 비용 과다)
  - `max_workers=None|1`이면 순차 (테스트/디버깅)
  - 결과 순서는 입력 detector 순서로 정렬 (병렬 완료 순 아님)
  - progress_callback 예외는 격리 — UI 오류가 탐지 막지 않음
- **탐지기별 프로파일링** (`pipeline.py`)
  - `collect_detection_profile(results)` — `metadata["elapsed"]` 수집
  - `format_detection_profile(profile)` — 마크다운 표 + `share%` 포맷
- **진행률 상세도** — 병렬 헬퍼의 `progress_callback`으로 자연스럽게 지원.
  Streamlit 측에서 `pipeline._detection_progress_callback = lambda c, t, n: ...` 주입
- 검증: 3개 × 0.1초 sleep 탐지기 → 순차 0.3초 vs 병렬 ≤ 0.15초 (2배 단축)

### 묶음 3 — 감사 증거 + 대시보드 UI (3개 / 23 tests)

- **`src/export/audit_evidence.py`** 신규
  - `RULE_LEGAL_BASIS` dict — 주요 룰 ID → 감사기준서/ISA/PCAOB 근거 매핑
  - `AuditEvidence` dataclass — document_id / score / risk / rules / top_features / narrative
  - `format_narrative(...)` — "전표 D001은 위험도 'High' (anomaly_score=0.850)로 분류...
    위반 룰: L3-04(기말/기초 결산 검토 후보군) [ISA 240 §32]... VAE 재구성 오차 주요 기여 피처: amount(0.430)..."
  - `build_evidence_report(df, min_score)` — 파이프라인 결과 DataFrame 일괄 변환
- **`dashboard/components/shap_waterfall.py`** 확장
  - `render_vae_waterfall(row, top_k=3)` 신규 — P0-1의 `ML02_top_feature_{1..3}`
    컬럼 소비. SHAP과 달리 양수(MSE) 전용 Waterfall
- **`dashboard/components/drift_banner.py`** 신규
  - `render_drift_banner(current_df, model_metadatas, max_show=5)` — 상단 고정 배너
  - 4단계 상태 분류: critical(🚨) / warn(⚠️) / stable(✅) / skip(메타 없음)
  - 드리프트 상세 expander — DataFrame 표로 모델·PSI·스키마 불일치 목록

### 묶음 4 — 문서·선택 작업 (2개 / 5 tests)

- **FT-T Ablation Study 스크립트** (`tools/scripts/ft_ablation_study.py`)
  - `classify_conclusion(f1_with, f1_without, threshold=0.005)` → "keep"/"remove"/"inconclusive"
  - `write_report(result)` → 마크다운 리포트 (`tests/datasynth_quality_gate/results/`)
  - `--dry-run` 모드로 리포트 포맷 검증 가능. 실제 학습은 데이터 재생성 이후 단계
- **`docs/DECISION.md`에 D037·D038 추가**
  - D037: 모델 드리프트 재학습 정책 (PSI ≥ 0.25 자동 트리거 + 분기별 주기 재학습)
  - D038: FT-T 유지 + ablation 기반 판정 정책

### 종합

- 전체 스코프 내 누적 **234/234 테스트 통과** (오전 139개 + 오후 95개 신규)
- 14개 잔여 항목 중 13개 코드 완료. 나머지 1개는 "데이터 재생성 후 실제 FT-T ablation 실행"
- 묶음 간 파일 중복 없음 — 각 묶음 완료 시점에서 회귀 테스트 실행으로 원인 범위 최소화
- 다음 세션: DataSynth 재빌드 + 데이터 재생성 + 모델 재학습 1회 → §2 BiLSTM 효과 + ablation 실측

---

## 2026-04-11: Phase 2 ML 4대 결함 해결 (P0-1 / P0-2 / P1-1 / P1-2)

**배경**: `docs/phase2_ml_feasibility.md` 검토에서 Phase 2 ML 파이프라인의 4가지 구조적 결함이 확정됨.
감사 산업 납품 가능 상태 진입을 위한 선결 조건.

### P0-1: VAE 피처별 재구성 오차 분해

**증상**: `_score_vae`가 전체 MSE 스칼라만 반환 → 감사조서에 "왜 이상인지" 정량 증거 제시 불가.
주력 비지도 탐지기(VAE+IF)가 감사 실무에서 채택 불가능한 상태.

**해결**:
- `src/preprocessing/vae_wrapper.py`: `_compute_errors_per_feature(X) → (N, D)` 추가. 기존 `_compute_errors`는 행 평균으로 위임. public API `score_samples_per_feature` 추가.
- `src/detection/vae_detector.py`: `_score_vae_per_feature()` + `_build_topk_columns()` 추가. `detect()`가 `details`에 `ML02_top_feature_1~3` + `_contrib` 6개 컬럼을 첨부.
- Top-K 선택은 `np.argpartition`으로 O(N·D) (정렬 비용 없음).

**검증**: `test_vae_wrapper` 11개, `test_vae_detector` 28개 통과. `per_feature.mean(axis=1) ≈ score_samples` rtol 1e-5 일치.

### P0-2: GroupKFold 기반 OOF Stacking (User-Leakage 방어)

**증상**: `train_from_results`가 이미 학습된 base 모델의 predict 결과를 그대로 meta-learner에 주입 → ML_SUPERVISED/TRANSFORMER/SEQUENCE 3개 모델에 data leakage. 검증 F1이 허위 상승.

**핵심 결정**:
- **GroupKFold(n_splits=3, groups=user_ids)**: 단순 random split은 "User A는 일단 이상치"라는 사용자 ID memorization 과적합을 유발 → 한 사용자 전표는 한 fold에만 속하도록 보장. BiLSTM의 `GroupShuffleSplit` 패턴과 일관성 유지.
- **3-fold (MVP)**: 파이프라인에 무거운 딥러닝 모델(FT-T, BiLSTM) 포함. `settings.stacking_cv_folds`로 노출하여 안정화 후 5로 승격 가능.
- **joblib.Parallel(n_jobs=-1, backend="loky")**: fold 학습은 독립적 → 프로세스 격리 병렬 학습으로 wall-clock 1× 학습 시간에 근접.

**해결**:
- `src/detection/ensemble_detector.py`: `train_oof()` 신규 진입점. `_train_fold_worker()` 모듈 최상위 함수로 분리(loky pickle 호환). `_build_score_matrix_from_oof()` 헬퍼.
- leakage-prone 트랙만 fold마다 재학습. 룰 4개 + VAE는 `non_leakage_results`로 한 번만 실행.
- 기존 `train_from_results()`는 라벨 부족/리소스 부족 시 fallback 경로로 유지.
- `config/settings.py`: `stacking_cv_folds=3`, `stacking_oof_n_jobs=-1` 기본값 추가.

**검증**: `test_ensemble_detector` 24개 통과 (OOF 5개 신규). User-leakage 차단은 `set(users[train]) ∩ set(users[val]) == ∅` 직접 검증.

### P1-1: BiLSTM 시퀀스에 시간(시:분:초) 도입

**증상**: `posting_date`만으로 시퀀스 정렬 → 같은 날 수백 건 배치에서 ERP 입력 순서가 뒤섞여 "30분 내 3건 연속 입력" 같은 ISA 240 패턴 포착 불가.

**원인**:
- DataSynth `je_generator.rs`가 `created_at = posting_date.and_time(time).and_utc()`로 시간을 **이미 생성** 중이나, `csv_sink.rs` 헤더에 `posting_date`만 출력 → **시간 정보가 CSV에 미노출**.

**해결**:
- **Rust**: `tools/datasynth/crates/datasynth-output/src/csv_sink.rs` 헤더에 `posting_time` 컬럼 추가. `item.header.created_at.format("%H:%M:%S")`로 시:분:초만 출력 (하위호환: `posting_date`는 그대로 date).
- **Python**:
  - `src/db/schema.py`: `general_ledger`에 `posting_time TIME` + `GENERAL_LEDGER_COLUMNS` 추가.
  - `src/detection/sequence_detector.py`: `_build_timestamps()` 헬퍼 — `posting_date + to_timedelta(posting_time)` 조합으로 완전한 타임스탬프. 부재 시 기존 동작(date only) fallback.

**결정사항 (플랜 승인 시)**:
- stride 학습-추론 일치는 **채택 안 함** — stride는 윈도우 샘플링 간격일 뿐 입력 텐서 분포와 무관. 학습 stride=4(메모리·속도) / 추론 stride=1(전수 커버리지)는 의도된 설계.

**검증**: `cargo test -p datasynth-output --test csv_output_integration` 4/4 통과. `test_sequence_detector` 31개 통과 (TestPostingTime 4개 신규).

### P1-2: 모델 드리프트 메타데이터

**증상**: `ModelMetadata`에 학습 시점의 데이터 분포(mean/std/nunique)가 없음 → PSI 계산·재학습 트리거 불가. SOC 2 "AI 모델 거버넌스" 부적합.

**해결**:
- `src/preprocessing/model_registry.py`: `ModelMetadata`에 `training_data_stats`, `feature_schema_version`, `class_imbalance_ratio`, `n_train_samples` 4개 필드 추가. `list_models()`는 구버전 `registry.json`도 로드 가능 (default 값 채움).
- `src/preprocessing/data_stats.py` (신규): `compute_training_stats`, `compute_class_imbalance`, `compute_feature_schema_version` 유틸.
- 모든 detector (`supervised/transformer/sequence/vae/ensemble`)의 `train()`이 `self._train_stats` 보존 → `save_model()`이 registry에 전달.
- **버그 수정**: `ensemble_detector.save_model()`이 `feature_count`를 누락하던 이슈 수정 (`feature_count=len(STACKING_BASE_MODELS)`).

**본 작업 범위 외(다음 스프린트)**: `drift_detector.py` (PSI 계산), 대시보드 드리프트 배너, 재학습 정책 문서화.

**검증**: `test_model_registry` 14개 (DriftMetadata 4개 신규), `test_data_stats` 14개 (신규 모듈) 통과. 구버전 registry.json 하위호환 로드 검증 포함.

### 종합

- 본 스프린트로 Phase 2 완료 선언의 가장 큰 장애물 4개가 제거됨.
- 스코프 내 단위 테스트 139개(신규 27개) 모두 통과.
- 본 브랜치(feature/wu14)의 기존 선행 실패(pipeline test_results_count stale, schema_yaml_sync, test_feature/e2e_datasynth)는 내 변경 스코프 밖 — `git stash` 검증으로 사전 존재 확인.

---

## 2026-04-10: DataSynth 한국 부가세(Tax) 전면 구현 + QG3 품질 개선

**증상**:
1. `journal_entries.csv`의 `tax_code`/`tax_amount` 컬럼이 전부 NaN (Phase 20 스킵)
2. QG3 전수검사 후 LLM 판정: 12월 34.9% 편중, 주말 10.1%, 월요일 27%, 세금계산서 매칭 81.3%, VAT-ZERO-KR 0건, R2R 프로세스에 tax_code 편중

**원인**:
- `config/datasynth.yaml`에 `tax:` 섹션 없음 → `TaxConfig.enabled` 기본값 `false` → Phase 20 전체 스킵
- `tax_code_generator.rs` `COUNTRY_RATES`에 KR 미포함 (DE/GB/FR 등 12개국만)
- Phase 20의 `TaxLine`이 `JournalEntryLine`에 **역매핑되는 코드가 전혀 없음** (document_id 매칭만으로 하면 1:N 중복 함정)
- `je_generator.rs`의 `supporting_doc_type` 로직이 O2C → "세금계산서"를 하드코딩해서, 매출채권 회수/선수금 전표(Revenue 라인 없음)에도 세금계산서 부착
- `period_end.year_end.peak_multiplier: 18.0` 과도 설정 → 12월 전표 폭증
- `seasonality.weekend_activity: 1.0` (평일과 동등) → 주말 10% 초과

**해결**:

### Rust 코드 수정
1. **`tax_code_generator.rs` COUNTRY_RATES에 KR 추가**: `("KR", "South Korea", "vat", "0.10", None)`
2. **`enhanced_orchestrator.rs` Phase 20b `backfill_je_tax_codes` 신규 함수** (핵심):
   - **1:N 중복 방지**: 전표당 첫 번째 Revenue/Expense base line에만 `tax_code`/`tax_amount` 부여 (AR/AP/부가세예수금 라인 NaN)
   - **business_process 필터**: O2C/P2P + `supporting_doc_type='세금계산서'` 전표만 대상 (R2R/H2R/A2R/TRE 제외)
   - **면세 판정**: `AccountSubType::InterestIncome/InterestExpense/DividendIncome/Investments` → VAT-EX-KR
   - **영세율**: O2C 매출 전표 중 `document_id` FNV 해시 기반 deterministic 15%를 VAT-ZERO-KR로 분류 (수출 모사)
3. **`je_generator.rs` `supporting_doc_type` 로직 수정** (근본 해결):
   - O2C 전표는 **실제 Revenue(4xxx) 라인이 있을 때만** "세금계산서"
   - P2P 전표는 Expense(5xxx/6xxx) 라인이 있을 때만 "세금계산서"
   - 매출채권 회수/선수금 전표는 "기타증빙"으로 분기
4. **`csv_sink.rs`**: tax_code/tax_amount 컬럼 헤더/행 추가 (CLI는 output_writer 경로라 실효는 없지만 일관성 유지)

### YAML 설정 수정 (`config/datasynth.yaml`)
- `tax:` 섹션 신규 추가: KR VAT 10%, 면세 4개 카테고리(financial_services/insurance/healthcare/education), 법인세 실효세율 24.2%
- `period_end.year_end.peak_multiplier: 18.0 → 4.0`, `start_day: -25 → -15`
- `seasonality.weekend_activity: 1.0 → 0.2`, `year_end_multiplier: 6.0 → 3.0`
- `seasonality.monday_multiplier: 1.3 → 1.1`
- `temporal_patterns.intraday`에 `deep_night(00-03) 0.005` 세그먼트 추가, `late_night 0.02 → 0.005`

**검증 (1,192,404 라인 / 319,061 전표 기준)**:

| 지표 | 수정 전 | 수정 후 |
|------|--------|--------|
| tax_code 채움(Revenue/Expense base line) | 0 | 109,078 |
| 과세 10% 정확도 | — | 99,697/99,697 = 100.00% |
| 1:N 중복 (전표당 최대 tax_code 수) | — | 1 |
| VAT-STD-KR / VAT-EX-KR / VAT-ZERO-KR | 0/0/0 | 99,697 / 612 / 8,769 |
| 세금계산서 전표 tax_code 매칭률 | 81.3% | 96.48% |
| R2R 프로세스 tax_code 부여 | 75,276건 | 0건 |
| 12월 전표 비중 | 34.9% | 12.4% |
| 주말 전표 비중 | 10.1% | 2.7% |
| 월요일 전표 비중 | 27.0% | 24.0% |
| 심야(22~06) 비중 | 2.1% | 1.01% |
| 03시 단독 피크 | 1,475건 | 190건 |
| 차대변 불균형 | 0.125% | 0.085% |

**교훈**:
1. **1:N 역매핑 함정**: 한 전표(document_id)에 여러 라인이 있을 때, `document_id`만 키로 데이터를 복사하면 `groupby.sum()` 시 N배 중복 계산된다. 반드시 **base line(Revenue/Expense)에만 단일 부여**하고 나머지는 NaN 유지. `COA.get_account(gl).account_type`으로 필터.
2. **VAT 대상 판별은 계정만으로 부족**: `AccountType::Revenue/Expense`는 필요조건이지만 충분조건 아님. R2R(결산조정), H2R(급여), A2R(자산취득), TRE(차입금이자)에도 Revenue/Expense 라인이 있지만 부가세와 무관. `business_process` + `supporting_doc_type` 필터 필수.
3. **"데이터에 맞추지 말고 데이터를 올바르게 생성"**: 세금계산서 매칭 81% 문제는 backfill 로직이 아니라 je_generator가 회수 전표에도 "세금계산서"를 붙이는 하드코딩 때문. 탐지 쪽을 고치면 fitting, 생성 쪽을 고치면 근본 해결.
4. **config 중복 설정 주의**: `seasonality.year_end_multiplier: 6.0`과 `temporal_patterns.period_end.year_end.peak_multiplier: 18.0`이 동시에 존재. 실제 효력은 후자. 분포 편중 디버깅 시 두 경로 모두 확인.
5. **QG3 extract_profile 활용**: 규칙/임계값 없이 전수 집계 → LLM 정성/정량 판정 흐름이 현실성 검증에 효과적. 고정된 체크리스트로 못 잡는 distribution skew를 사람이 읽으면 한 번에 보임.

---

## 작성 가이드

```
## YYYY-MM-DD: 문제 제목

**증상**: 무엇이 잘못되었는지
**원인**: 왜 발생했는지
**해결**: 어떻게 고쳤는지
**교훈**: 다음에 주의할 점
```

---

## 2026-03-20: charset_normalizer가 latin-1을 ascii로 오탐

**증상**: bpi2019(527MB, latin-1) 파일 읽기 시 `'ascii' codec can't decode byte 0x96 in position 249785`

**원인**: `text_reader._detect_encoding()`이 64KB만 샘플링. bpi2019의 latin-1 특수문자(0x96)가 249KB 지점에 첫 등장 → 샘플 범위 밖 → charset_normalizer가 ascii로 오탐 → `pd.read_csv(encoding="ascii")`에서 에러

**해결**: `_detect_encoding()`에서 ascii 감지 시 latin-1로 폴백 (1줄 추가). ascii ⊂ latin-1 이므로 부작용 없음.

**교훈**: 샘플 기반 감지는 대용량 파일에서 오탐 가능. "샘플 크기 확대"는 땜질 — 타입 시스템의 포함관계(ascii ⊂ latin-1)를 활용하는 것이 근본 해결.

---

## 2026-03-20: 헤더 탐지 키워드 80% 의존 → 구조적 신호로 전환

**증상**: financial-anomaly(Amount, Timestamp), general-ledger(Date, EntryNo)에서 헤더 탐지 실패 (confidence=0.20). keywords.yaml에 미등록된 범용 영문 컬럼명.

**원인**: 스코어 공식이 `KeywordScore × 0.80 + StringRatio × 0.20` — 키워드 없으면 최대 0.20

**해결**: 5개 구조 신호 가중합으로 전환. TypeDiversity(0.35) + Uniqueness(0.25) + NullDensity(0.15) + Keyword(0.15) + StringRatio(0.10). 키워드 없어도 구조적으로 헤더/데이터 행을 구분.

**교훈**: "키워드를 더 등록"하는 땜질 대신 "데이터 자체의 구조적 신호"를 활용하면 미지의 데이터셋에도 범용 동작.

---

## 2026-03-20: fuzzy 매핑 타입 비호환 오매핑 (drcrk→debit_amount)

**증상**: sap-merged에서 drcrk(차대변 indicator, 'S'/'H' 문자열)가 debit_amount(float)에 매핑 → 캐스팅 100% NaN

**원인**: rapidfuzz가 'drcrk'와 'debit' 문자열 유사도만 비교. 실제 데이터 타입(str vs float)을 무시.

**해결**: 이중 방어 — (1) dc_indicator 표준 컬럼 등록으로 정확 매칭 우선 (2) `_type_compat.py`에서 fuzzy 후보의 소스 타입↔스키마 타입 비교, 비호환 시 스코어 0

**교훈**: 문자열 유사도 매칭은 반드시 타입 검증과 병행해야 한다. "이름이 비슷해도 타입이 다르면 틀린 매핑".

---

## 2026-03-22: engine.py rules 전달 형식 불일치 → pattern 피처 전부 False

### 증상

Detection E2E 테스트(DataSynth 1M행)에서 L4-01(매출 이상 변동), L3-02(수기 전표) 등이 0건.
`is_revenue_account`, `is_manual_je`, `is_intercompany`, `is_suspense_account` 피처가 전부 False.

### 원인

`audit_rules.yaml`의 YAML 구조와 피처 엔진 내부의 기대 형식 간 **깊이(depth) 불일치**.

```
audit_rules.yaml:              get_audit_rules() 반환값:
──────────────                 ────────────────────────
patterns:                      {"patterns": {
  revenue_account_prefixes:        "revenue_account_prefixes": ["4"],
    - "4"                          "manual_source_codes": ["SA", ...],
  manual_source_codes:             ...
    - "SA"                     }}
```

호출 체인에서 문제 발생 지점:

```
경로 A — pattern_features.py 직접 호출 (정상):
  add_all_pattern_features(df, rules=None)
  → rules = get_audit_rules()["patterns"]     ← 자동으로 ["patterns"] 접근
  → rules.get("revenue_account_prefixes")     ← ["4"] 반환

경로 B — engine.py 경유 (버그):
  generate_all_features(df, rules=get_audit_rules())
  → engine.py가 {"patterns": {...}} 을 그대로 pattern_features에 전달
  → rules.get("revenue_account_prefixes")     ← 최상위에 해당 키 없음
  → 빈 리스트 [] fallback → 피처 전부 False → 에러 없이 조용히 실패
```

`pattern_features.py`는 `rules=None`일 때만 자동으로 `["patterns"]`를 꺼낸다.
`engine.py`의 docstring에 "patterns 수준 dict를 넘기세요"라고 적혀있지만,
중첩 dict가 들어와도 **에러 없이 빈 리스트로 fallback**하여 버그를 감춘다.

### 영향 범위

`generate_all_features(df, rules=get_audit_rules())` 형태로 호출하는 코드에서
pattern 피처 4개가 전부 False (first_digit은 rules 미사용이라 영향 없음):

```
is_revenue_account  → L4-01 매출 이상 변동 미탐지
is_manual_je        → L3-02 수기 전표 미탐지
is_intercompany     → L3-03 관계사 순환거래 미탐지
is_suspense_account → L3-08 가계정 키워드 미탐지
```

기존 feature 단위 테스트는 `rules=None` 또는 평탄 dict로 호출하여 이 버그를 미포착.

### 해결

**`engine.py`에서 방어 처리** — 중첩 dict가 들어오면 자동으로 `["patterns"]`를 꺼냄:

```python
# src/feature/engine.py generate_all_features() 시작 부분 (L116~119)
if rules is not None and "patterns" in rules:
    rules = rules["patterns"]
```

적용 후 E2E 재실행 결과: L4-01 0→1,069건, L3-02 0→2건 정상 탐지.

### 회귀 테스트

```bash
uv run pytest tests/test_feature/ tests/test_detection/ -v
```

### 교훈

함수가 dict를 받을 때 **키 부재를 빈 리스트로 fallback하면 버그가 숨는다**.
"조용한 실패(silent failure)"는 즉시 에러보다 디버깅이 훨씬 어렵다.
방어 방법: (1) 공개 API에서 입력 형식 정규화 (2) fallback 시 warning 로그 추가.

---

## 2026-03-26: 브랜치 전략 단순화 시 벌크 커밋 발생

**증상**: `60b9603` 커밋에 116파일(11,198줄 추가)이 단일 커밋으로 들어감. "1커밋 = 1논리적 변경" 원칙 위배.

**원인**: Phase별 feature 브랜치 5개(feat/1a-ingest, 1b-detection, 2-ml, 3-llm, backup) 운용 중 작업이 브랜치 간 왔다갔다하면서 feat/1a-ingest에 미커밋 변경 91파일이 누적. develop+main 2-branch 체제로 전환하기 위해 브랜치 머지 전 안전 확보 목적으로 일괄 커밋.

**해결**: 벌크 커밋 그대로 유지. 머지 시 충돌은 ours(최신본) 기준으로 해결. 파일 손실 없음 확인 완료. 이후 feature 브랜치 전부 삭제하고 develop+main 2-branch 체제로 전환.

**교훈**: 1인 프로젝트에서 phase별 feature 브랜치는 오버엔지니어링. 작업이 phase 간 교차되면 브랜치 전환 시 미커밋 변경 분실 위험이 높아진다. 단순한 브랜치 전략(develop+main)이 안전하다.

---

### Phase 1c WU1: 대시보드 기반 컴포넌트 구현 시 교훈 (2026-03-27)

**1. tempfile 디스크 I/O 불필요**
- 증상: `st.file_uploader` → tempfile 저장 → `pipeline.run(path)` 방식은 디스크 I/O + 임시 파일 관리 부담
- 해결: UploadedFile은 file-like object이므로 `pd.read_csv(uploaded)` 직접 읽기 + `run_from_dataframe()` 호출
- 교훈: Streamlit UploadedFile의 인터페이스를 먼저 확인할 것

**2. flagged_rules CSV 필터 성능**
- 증상: `.apply(lambda s: set(s.split(",")) & target)` 방식은 1M행에서 Python 루프 오버헤드
- 해결: `str.contains("|".join(codes), regex=True)` 벡터화 매칭으로 ~10× 성능 개선
- 교훈: pandas에서 행 단위 `.apply()`는 최후 수단. 벡터화 연산 우선 검토

**3. 산점도 이상치 탈락**
- 증상: `df.sample(5000)` 단순 랜덤 샘플링 시 High/Medium 이상치가 무작위 탈락
- 해결: `_priority_sample()` — High/Medium 전수 보존, Normal 위주 다운샘플링
- 교훈: 감사 데이터 시각화에서 이상치는 핵심 관심 대상. 샘플링 시 도메인 우선순위 반영 필수

---

### Phase 1c WU7: 인제스트 오케스트레이터 + 미해결 이슈 UI 반영 (2026-03-28)

**1. ModuleNotFoundError: No module named 'dashboard'**
- 증상: `streamlit run dashboard/app.py` 실행 시 dashboard 패키지 import 실패
- 원인: Streamlit이 실행 파일의 상위 디렉토리를 sys.path에 자동 추가하지 않음
- 해결: `sys.path` 에 프로젝트 루트 경로 명시 추가
- 교훈: Streamlit 앱을 서브디렉토리에 배치할 경우 sys.path 설정 필수

**2. AxiosError: Network Error (Streamlit 대용량 업로드)**
- 증상: 50MB 이상 파일 업로드 시 브라우저에서 AxiosError 발생, 서버 응답 없음
- 원인: Streamlit 기본 `maxMessageSize`(200MB)가 server↔browser 통신 제한. 대용량 DataFrame 직렬화 시 초과
- 해결: `.streamlit/config.toml`에 `maxUploadSize=1024`, `maxMessageSize=1024` 설정
- 교훈: `maxUploadSize`만으로는 부족. `maxMessageSize`도 함께 올려야 대용량 파일 파이프라인이 정상 동작

**3. utf-8 codec error (인코딩 폴백)**
- 증상: CP949/EUC-KR 인코딩 파일 업로드 시 `UnicodeDecodeError: 'utf-8' codec can't decode`
- 원인: 인코딩 자동 감지 실패 시 기본 utf-8로 읽기 시도
- 해결: UI-1 인코딩 드롭다운 구현 — confidence < 0.7 시 사용자에게 인코딩 선택 selectbox 노출 + 선택 값으로 파일 재읽기
- 교훈: 한국 ERP 덤프는 CP949/EUC-KR 비율이 높으므로 인코딩 수동 오버라이드는 필수 UI

**4. 탐색기 탭 브라우저 멈춤 (대용량 DataFrame)**
- 증상: 1M행 DataFrame을 AgGrid에 직접 전달 시 브라우저 탭 무응답
- 원인: AgGrid가 전체 행을 브라우저 메모리에 로드 시도
- 해결: `explorer_grid.py`에서 10K행 제한 적용 (필터 후 상위 10,000건만 표시)
- 교훈: 브라우저 기반 그리드 컴포넌트는 10K행 이하로 제한해야 안정적 렌더링 가능

---

## 2026-04-02: DataSynth 재구성 — 5회 연속 빌드 미반영 사고

### 증상

Run#8~12 (5회) 품질 게이트에서 동일 FAIL 7건이 반복. Rust 코드를 수정해도 결과가 변하지 않음.

### 원인 (2계층)

**1계층 — 바이너리 미갱신 (핵심)**

`datasynth-runtime` 크레이트에 기존 컴파일 에러(immutable borrow) 2건이 존재.
- `enhanced_orchestrator.rs:1780` — `let anomaly_labels` (mut 필요)
- `enhanced_orchestrator.rs:1679` — `let intercompany` (mut 필요)

`cargo check -p datasynth-generators`는 generators 크레이트만 체크하여 PASS.
하지만 `cargo build --release`는 전체 워크스페이스를 빌드하는데, runtime 크레이트 에러로 **바이너리 생성 실패**. cargo가 "Finished" 메시지를 출력하지만 실제로는 워크스페이스 root만 빌드하고 cli 바이너리는 건너뜀. 결과적으로 **2026-03-31 18:33의 old 바이너리**로 5회 재생성.

`cargo build --release -p datasynth-cli`를 명시적으로 호출해야 에러가 노출됨.

**2계층 — 코드 결함 (빌드 미반영으로 검증 불가능)**

| FAIL | 근본 원인 | 수정 |
|------|----------|------|
| T3-04/05/12/13 | `Employee::new()` 기본 persona=JuniorAccountant, EmployeeGenerator가 job_level→persona 매핑 안 함 | `employee_generator.rs`에 persona 매핑 추가 |
| T3-10 | `with_employee_pool()` 후 `user_process_map` 미갱신 (old generic IDs) | `rebuild_user_process_map()` 메서드 추가 |
| T2-02 | anomaly injection 후 debit/credit 동시 양수 라인 발생 | netoff 로직 추가 |

### 해결

1. `enhanced_orchestrator.rs`: `let` → `let mut` 2건
2. `cargo clean --release` + `cargo build --release -p datasynth-cli` (전체 리빌드)
3. 바이너리 타임스탬프 **4월 2일 09:17** 확인 후 재생성

### 교훈

1. **`cargo build --release`만으로는 바이너리 갱신을 보장할 수 없다.** 워크스페이스에서 특정 크레이트가 에러면 해당 바이너리만 skip되고 "Finished" 출력. `-p datasynth-cli`를 명시하면 에러가 즉시 드러남.
2. **재생성 전 반드시 `ls -la target/release/datasynth-data*` 타임스탬프 확인.** 현재 시각과 일치하지 않으면 빌드 실패.
3. **`cargo check -p <crate>`는 의존 크레이트를 검증하지 않는다.** full rebuild로만 전체 의존성 에러를 잡을 수 있다.
4. **RNG fitting 금지.** RNG 시퀀스를 맞추기 위해 dummy 호출을 소비하는 것은 test-fitting과 같다. 근본 원인(employee persona 미설정)을 고쳐야 한다.
5. **gl_rng 분리 시도는 실패.** 별도 RNG 스트림을 추가해도 메인 rng에서 제거된 호출만큼 시퀀스가 밀린다. 근본 해결은 employee assignment 자체의 견고성.

---

## 2026-04-02: Employee.persona 미설정 — 전체 Employee가 JuniorAccountant

### 증상

품질 게이트 T3-05 (employee company 불일치 729K건), T3-13 (무권한 승인 7,123건) 등 5건 FAIL.

### 원인

`Employee::new()` (user.rs:775)에서 `persona: UserPersona::JuniorAccountant`로 기본값 설정.
`EmployeeGenerator.generate_employee()` (employee_generator.rs:263)에서 `employee.job_level = job_level`은 설정하지만 `employee.persona`는 갱신하지 않음.

결과: 204명 전원이 JuniorAccountant persona → `select_user()`가 Manager/Controller 검색 시 매칭 실패 → generic fallback ID 생성 → employees.json과 불일치.

### 해결

`employee_generator.rs`에서 `job_level` 설정 직후 persona 동기화:
```rust
employee.persona = match job_level {
    JobLevel::Staff => UserPersona::JuniorAccountant,
    JobLevel::Senior | JobLevel::Lead | JobLevel::Supervisor => UserPersona::SeniorAccountant,
    JobLevel::Manager | JobLevel::Director => UserPersona::Manager,
    JobLevel::VicePresident | JobLevel::Executive => UserPersona::Controller,
};
```

### 교훈

모델 기본값이 "안전한 기본값"이 아닐 수 있다. `Employee::new()`의 `JuniorAccountant` 기본값은 명시적 설정 없이 사용하면 전체 데이터를 오염시킨다.

---

## 2026-03-03 ~ 04-02: DataSynth T3 교차검증 1달 디버깅 전체 기록 (Run#1→#20)

### 문제 정의

DataSynth가 생성하는 journal_entries.csv의 `created_by`/`approved_by`가 employees.json의 직원 데이터와 불일치. T3 교차검증 6개 항목이 FAIL 상태로 20회 재생성에도 해결되지 않음.

### 왜 1달간 실패했는가 — 실패 패턴 분석

**Phase 1 (Run#1~#7): 증상 수준 패치 반복**

Employee와 User가 별도 경로로 생성되는 구조적 문제를 인식하지 못하고, 개별 FAIL 항목에 대한 증상 수준 패치를 반복.

- `gl_rng` 분리 → RNG 시퀀스 변경 → 다른 FAIL 항목 발생
- `type_roll` dummy consumption → 기존 RNG 시퀀스 보존 시도 → test fitting으로 판정, 롤백
- 부분 수정 5회 연속 동일 결과 → 바이너리 미갱신 발견 (아래 참조)

**Phase 2 (Run#8~#12): 바이너리 미갱신 5회 낭비**

`cargo build --release`가 workspace 루트에서 성공 메시지를 출력했지만, `datasynth-runtime` crate에 컴파일 에러(`let` vs `let mut`)가 있어 CLI 바이너리가 재생성되지 않음. 3월 31일 빌드의 구 바이너리가 계속 사용됨.

```
발견 방법: ls -la target/release/datasynth-data.exe → 타임스탬프가 3일 전
해결 방법: cargo clean --release && cargo build --release -p datasynth-cli
교훈:      빌드 후 반드시 바이너리 타임스탬프 확인
```

**Phase 3 (Run#13~#14): Employee/User 이원화 인식, 부분 통합 시도**

Employee와 User가 별도 생성되는 구조를 인식하고 EmployeeGenerator에 AutomatedSystem 생성을 추가. T3-03 (FK orphan) 33→0건으로 개선되었으나 T3-04/05는 악화.

악화 원인을 특정하지 못한 채 부분 패치 반복.

**Phase 4 (Run#15): 통합 재설계 완료, 그러나 숨은 파괴 코드 미발견**

UserGenerator를 JE 생성 경로에서 완전 제거. EmployeeGenerator가 유일한 사용자 소스. T3-03 해소(0건). 그러나 T3-04/05는 오히려 악화 (826K→1,075K).

이 시점에서 `select_user()`, `UserPool::from_employees()`, `to_user()` 코드를 모두 검증했고 전부 정상이었음. **문제는 생성 로직이 아니라 생성 후 후처리에 있었음.**

### 왜 Run#20에서 성공했는가 — 근본 원인 3개

**근본 원인 1: employee user_id 파괴적 덮어쓰기 (T3-04/05의 97% 원인)**

`enhanced_orchestrator.rs:1728-1746`에서 JE 생성 후 모든 employee의 user_id를 JE의 created_by 값으로 라운드 로빈 덮어쓰기. 이전 UserGenerator 시절 T3-03 해결을 위한 덧대기 패치. 통합 재설계 후에는 불필요하면서 persona/company/approval 정합성을 전면 파괴.

```rust
// 삭제된 코드 — 268명의 employee user_id를 JE created_by의 알파벳 순으로 강제 매핑
let mut je_user_vec: Vec<String> = je_users.into_iter().collect();
je_user_vec.sort();
for (i, emp) in self.master_data.employees.iter_mut().enumerate() {
    emp.user_id = je_user_vec[i % je_user_vec.len()].clone();
    // persona, company_code, approval_limit는 그대로 → 전면 불일치
}
```

왜 발견이 늦었는가: `select_user()` → `header.user_persona` 경로만 추적. employee가 employees.json에 직렬화되기 전에 user_id가 변경되는 후처리 경로는 검색 범위 밖.

**근본 원인 2: T3-12 post-processing의 user_persona 미갱신 (637K건)**

approval_limit 초과 시 `created_by`를 한도 충분한 직원으로 교체하면서 `user_persona`는 업데이트하지 않음. automated 직원(limit=0)의 모든 전표가 manager로 교체되면서 persona 불일치.

연쇄 구조: automated employee의 `approval_limit=0` (Employee::new 기본값) → 금액 1원 이상이면 전부 한도 초과 → manager로 교체 → persona는 여전히 `automated_system`.

**근본 원인 3: 다수의 부수 버그**

| 버그                                        | 영향 범위       | FAIL 항목     |
|---------------------------------------------|-----------------|---------------|
| `generate_employee_with_level()` persona 미갱신 | 부서장 15명      | T3-04         |
| `generate_automated_employee()` limit=0     | automated 64명   | T3-12         |
| IC/subledger 생성기 `created_by` 하드코딩   | 1,003건          | T3-03         |
| SoD 주입 시 can_approve_je 미검증           | 6건              | T3-13         |

### 수정 내역

**근본 수정 (데이터 생성 자체를 올바르게):**

| 파일                       | 수정                                             |
|----------------------------|--------------------------------------------------|
| `enhanced_orchestrator.rs` | user_id 덮어쓰기 코드 전면 삭제                  |
| `employee_generator.rs`    | `generate_employee_with_level()` persona 재매핑   |
| `employee_generator.rs`    | automated employee `approval_limit = ~1T`         |
| `je_generator.rs`          | SoD PreparerApprover: `can_approve_je` 검증 추가  |

**후처리 보정 (fitting — RC 재설계 시 근본 수정 예정):**

| 파일                       | 수정                                             | 근본 수정 방안                           |
|----------------------------|--------------------------------------------------|------------------------------------------|
| `enhanced_orchestrator.rs` | orphan created_by → employee 교체                 | IC/subledger 생성기에 employee pool 전달 |
| `enhanced_orchestrator.rs` | T3-12 limit 초과 시 created_by+persona 동시 교체  | `select_user()`에서 금액 기반 직원 선택  |
| `enhanced_orchestrator.rs` | T3-13 무권한 approved_by 교체                     | anomaly injector SoD 검증 강화           |

### Run별 추이

```
Run  T3-03  T3-04      T3-05     T3-10  T3-12   T3-13   총 FAIL
#8   33     826K       563K      3      1,670   18,730  6
#14  33     826K       563K      3      1,670   18,730  6
#15  0      1,075K     814K      3      25,649  28,070  5 (T3-03 해결)
#17  2      0          0         0      72,511  2,433   3 (user_id 덮어쓰기 삭제)
#18  0      0          0         0      483     3       2 (automated limit, orphan 교체)
#19  0      0          0         0      1       0       1 (anomaly 스킵 조건 수정)
#20  0      0          0         0      0       0       0 (automated limit 상향)
```

### 교훈

1. **생성 후 후처리를 반드시 검색하라.** 생성 로직이 정상이어도 orchestrator의 post-processing이 데이터를 변형할 수 있다. `grep "iter_mut\|created_by\s*="` 같은 전체 검색이 필요.
2. **덧대기 패치는 다음 수정의 근본 원인이 된다.** user_id 강제 동기화(T3-03 해결)가 T3-04/05/12/13의 근본 원인으로 전이. 일시적 해결이 구조적 문제를 은폐.
3. **필드 A 변경 시 연관 필드 B를 반드시 갱신하라.** `created_by` 교체 시 `user_persona`를 누락하면 교차검증 전면 FAIL.
4. **바이너리 타임스탬프를 확인하라.** Rust workspace에서 의존 crate의 컴파일 에러가 있어도 `cargo build`가 성공 메시지를 출력할 수 있다. 5회 낭비의 원인.
5. **anomaly/fraud 제외 조건은 품질 게이트 기준과 일치시켜라.** `is_anomaly` 일괄 스킵이 아니라 `ExceededApprovalLimit` 등 특정 타입만 스킵.

---

## 2026-04-02: DataSynth v21 확정 — E2E 라벨 검증 21회 반복 수렴

### 결과

| 항목 | 값 |
|------|---|
| DataSynth 행수 | 1,106,056 |
| 라벨 건수 | 7,827 |
| Phase 1 Recall | 91.4% (2,408 / 2,636) |
| 전체 Recall | 92.0% (7,197 / 7,827) |
| 100% Recall 룰 | 10개 |
| L1-06 flagged | 1.9% |
| Normal 등급 | 85.2% |
## 2026-05-14: DataSynth manipulation v2 substantive mutation repair

### 문제

`datasynth_manipulation_v2`의 일부 manipulation truth가 표면 메타데이터만 바뀌고 회계 실체가 충분히 바뀌지 않았다.

- `circular_related_party_transaction`: `business_process=Intercompany` 표지는 있으나 IC GL prefix(`1150/2050/4500/2700`)가 0건이라 L3-03 신호가 죽음.
- `fictitious_entry`: fictitious revenue truth인데 4xxx 매출 계정과 11xx 매출채권/현금 계정 조합이 전 문서에 보장되지 않음.
- `embezzlement_concealment`: employee/cash leakage truth인데 가지급금/대여금(`1200/1250`)과 현금(`1000`) 조합, duplicate/near-limit 표면이 약함.

### 해결

`tools/scripts/materialize_datasynth_manipulation_v2.py`에 실체 mutation 단계를 추가했다.

- circular 34개 truth doc 전부에 IC GL prefix를 강제.
- fictitious 168개 truth doc 전부에 DR 11xx / CR 4xxx revenue pattern을 강제하고 일부는 batch-like period-end posting으로 묶음.
- embezzlement 76개 truth doc 전부에 DR 1200/1250 / CR 1000 pattern을 강제하고 duplicate card reference 및 near approval limit 문서를 생성.
- manifest에 operational noise floor 지표(`approved_by_null_pct`, `manual_entry_pct`, `approval_matrix_gap_pct`, `weekend_posting_pct`)를 추가.

### 검증

- `uv run ruff check tools/scripts/materialize_datasynth_manipulation_v2.py`
- `uv run python -m py_compile tools/scripts/materialize_datasynth_manipulation_v2.py`
- `uv run python tools/scripts/check_datasynth_manipulation_truth.py data/journal/primary/datasynth_manipulation_v2 --out tests/datasynth_quality_gate3/results/manipulation_v2_truth_check_after_substantive_mutation.json`
- 컬럼 검증 산출물: `artifacts/manipulation_v2_substantive_mutation_column_check.json`
- 요약 리포트: `artifacts/manipulation_v2_substantive_mutation_repair.md`
- full Phase1 cache: `artifacts/phase1_manipulation_v2_final_candidate_20260514.pkl`
- case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T091304Z.json`
- topic/ranking 리포트: `artifacts/manipulation_v2_final_label_signal_recovery.md`

### 최신 Phase1 확인

2026-05-14 최신 full Phase1 실행은 detector warning 없이 완료됐다.

- manipulation truth 420건 전부 `score > 0` 및 `rule_or_review_hit`에 진입
- top-500 case truth capture: 305 / 420
- high priority truth capture: 276 / 420
- fictitious expected topic 진입: 144 / 168
- embezzlement expected topic 진입: 76 / 76
- circular L3-03 hit: 34 / 34
- circular expected topic 진입: 34 / 34

circular truth는 IC GL prefix와 결산 표면을 함께 갖도록 보강했다. 이로써 L3-03 단독 context badge에 머무르지 않고 `intercompany_cycle` case topic에 전건 진입한다.

### PHASE1 보조 보강

B1 데이터 보강 후에도 IC 신호 강건성을 높이기 위해 두 가지 보조 보강을 적용했다.

- `src/feature/pattern_features.py:add_is_intercompany`
  - 기존 GL prefix 기준에 `business_process == Intercompany`, `counterparty_type == IntercompanyAffiliate`를 OR 조건으로 추가.
  - 최신 `datasynth_contract_v2` 기준 row/doc 증가분은 0으로 확인.
- `tools/scripts/profile_phase1_v126.py:_load_partner_master`
  - `vendor_id/customer_id` 외에 `intercompany_code`도 `ids` 및 `intercompany` set에 적재.
  - `IC-C00x` 형태 trading partner가 master evidence에서 intercompany로 인식될 수 있게 보강.

---

| 코드 버그 의심 | 0건 |

### 확정 사유

- v13~v21 (9회) Phase 1 Recall 91~100% 범위에서 안정 수렴
- 잔여 FN 19건은 DataSynth 난수 시드에 따라 진동하는 소수 라벨 룰 (L1-05 1건, L1-06 3건 등)
- 구조적 한계 4룰(L2-03/L3-03/L4-04/L4-02)의 FN ~1,822건은 Phase 2 ML 영역
- L1-06 과탐 해소(99.91% → 1.9%), 위험등급 정상화(Normal 0.1% → 85.2%) 달성
- 추가 DataSynth 수정의 비용 대비 효익이 미미 (Recall +0.7%p 상한)

### 상세 리포트

- [tests/phase1_rulebase/test-results/e2e-label-validation.md](../tests/phase1_rulebase/test-results/e2e-label-validation.md)
- [tests/phase1_rulebase/test-results/rule-label-gap-analysis.md](../tests/phase1_rulebase/test-results/rule-label-gap-analysis.md)

---

## 2026-04-03: DataSynth Stage 2-3 다기간 전환 (12개월 → 36개월)

### 변경 내용

`period_months: 12` → `36`으로 확장하여 2022~2024년 3개년 데이터 생성.

### 치명적 장벽: Rust CLI Safety Limit

**증상**: `config/datasynth.yaml`에 `period_months: 36`을 설정해도 1년 데이터만 생성됨.

**원인**: `tools/datasynth/crates/datasynth-cli/src/main.rs:2219-2227`의 `apply_safety_limits` 함수가 `period_months > 12`이면 12로 강제 절삭. `cargo build --release`의 "Finished" 메시지만 보고 빌드 성공으로 판단하면, 이 safety limit에 의해 YAML 변경이 무시됨.

**해결**: `apply_safety_limits`에서 period_months 절삭 코드를 제거. `validation.rs`의 `MAX_PERIOD_MONTHS = 120`이 이미 상한을 보장하므로 CLI의 12개월 제한은 중복 안전장치.

### T3-12 FAIL 1건: BenfordViolation 금액 극단값

**증상**: 품질 게이트 T3-12 `approval_limit` FAIL 1건.

**원인**: BenfordViolation anomaly가 첫째 자릿수 9를 만들기 위해 `9.1×10^18` 극단값을 주입. 이 금액이 automated_system의 approval_limit(1조원)을 초과하지만, `ExceededApprovalLimit` 라벨이 없어 T3-12에서 미제외.

**해결**: T3-12 제외 목록에 `BenfordViolation`을 추가 (금액 변형 anomaly).

### 결과

| 항목            | 12개월 (이전) | 36개월 (이후) |
|-----------------|---------------|---------------|
| 총 행수         | 1,105,174     | 3,241,675     |
| fiscal_year     | 2022          | 2022~2024     |
| posting_date    | 01-01~12-31   | 2022-01-01~2024-12-31 |
| 라벨            | 7,827         | 23,067        |
| 품질 게이트     | WARNING       | WARNING       |
| FAIL            | 0             | 0             |

### 교훈

1. **Rust CLI의 safety limit은 config validation과 별개로 존재할 수 있다.** `validation.rs`의 MAX=120과 CLI의 MAX=12가 이중으로 존재. config만 변경해도 안 되는 경우 CLI 코드를 확인.
2. **anomaly injection이 금액을 극단값으로 변형하면 교차검증 체크에 부수 효과가 생긴다.** 금액 변형 anomaly(BenfordViolation)는 approval_limit 체크에서도 제외해야 함.
3. **품질 게이트의 하드코딩된 연도/날짜를 config 기반 동적 계산으로 전환하면 다기간 확장에 자동 대응.** expectations.py에 파생 필드(valid_fiscal_years, end_date 등)를 추가하여 모든 체크가 동적으로 기간을 참조.

---

## 2026-04-04: document_number 순차 채번 구현

### 문제

`document_number` 필드가 항상 None으로 출력됨. Phase 2 전표번호 갭 탐지(§3.3.10)의 선행 의존.

### 해결

`enhanced_orchestrator.rs`에 Phase 9a를 추가하여 모든 전표 생성/수정 완료 후 `(company_code, fiscal_year, document_type)`별 순차 채번 + 확률적 갭 삽입 구현.

### 삽질 과정

1. **기존 "Stage 2-2" 코드가 덮어쓰기**: 라인 2714-2727에 `(company, year)`만으로 단순 순차 할당하는 기존 코드가 존재. Phase 9a에서 정상 채번해도 마지막에 덮어써서 document_type별 분리가 무효화됨. → 기존 코드 제거.
2. **기말 갭 비율이 비기말보다 낮은 버그**: year_end에서 `year_end_rate`만 적용하고 `base_rate`를 누락. → `base_rate + year_end_rate`로 수정.
3. **Quality gate T2-35 오판**: 기존 체크가 `(company, year)`만으로 중복 검사하여 document_type별 독립 채번을 중복으로 잡음. → `document_type` 추가.

### 교훈

1. **`document_number =`로 grep하여 덮어쓰기 코드를 반드시 검색할 것.** 같은 필드를 여러 곳에서 할당하면 마지막 할당이 이김.
2. **갭 비율 설계 시 기본률과 추가률을 합산할 것.** exclusive가 아닌 additive로 설계해야 "기말 > 비기말" 보장.
3. **Quality gate 체크를 데이터 스키마 변경에 맞춰 업데이트할 것.** 채번 기준이 바뀌면 검증 쿼리도 같이 바꿔야 함.
> Historical debugging log. Current production DataSynth baseline is `data/journal/primary/datasynth/` freeze `v23` as of 2026-04-22. Older `v20.x` references below are point-in-time notes.
## 2026-05-14: DataSynth manipulation v3 fitting guard 적용

### 문제

T1/T6 분석 후 `unusual_timing_manipulation`과 `fictitious_entry`를 함께 DataSynth에서 보강하자는 제안이 있었지만, 그대로 진행하면 PHASE1 expected-topic 진입률에 데이터를 맞추는 fitting 위험이 있었다.

### 판단

- `unusual_timing_manipulation`은 raw data 기준 21개 문서가 이미 야간/주말/manual posting 실체를 충족했다. DataSynth에서 period-end 근처로 더 밀면 `period_end_adjustment_manipulation`과 taxonomy가 섞인다.
- `circular_related_party_transaction`은 v2에서 이미 IC GL/관계사 cycle 실체와 expected topic 진입이 회복되어, high-cash 동시 hit 유도 mutation을 추가하지 않았다.
- `fictitious_entry`는 일부 문서가 DR 11xx / CR 4xxx 구조는 갖췄지만 금액·batch 실체가 약해 허위 매출 데이터로서의 회계 실체 보강 여지가 있었다.

### 해결

- 신규 후보 `data/journal/primary/datasynth_manipulation_v3/` 생성. v2는 덮어쓰지 않음.
- `tools/scripts/materialize_datasynth_manipulation_v3.py` 추가.
- fictitious revenue만 회사별 매출계정 상위 분위수 기반 금액 floor(`p99.95 * 1.5`)와 deterministic batch cluster로 보강.
- `tools/scripts/audit_manipulation_v3_mutation_guards.py`로 raw-data guard를 분리.
- `tools/scripts/analyze_contract_v2_master_flow_gap.py`로 contract_v2 approval gap을 원인분리.

### 결과

| 항목 | 결과 |
|---|---:|
| manipulation truth docs | 420 |
| truth gate failures | 0 |
| Guard 1 회계 실체 | PASS |
| Guard 2 정상 배경 fitting 차단 | PASS |
| Guard 3 다른 시나리오 회귀 차단 | PASS |
| Phase1 score/rule/review hit docs | 420 / 420 |
| Top500 truth capture | 309 / 420 |
| fictitious expected topic docs | 151 / 168 |
| unusual_timing expected topic docs | 11 / 21 |

### 교훈

1. DataSynth mutation은 "룰 진입률을 올리기 위해"가 아니라 "회계 실체를 데이터에 새기기 위해"만 추가한다.
2. raw-data guard와 Phase1 measure-only 지표를 분리하면 fitting 위험을 낮출 수 있다.
3. unusual timing처럼 원시 실체는 맞지만 topic 진입이 약한 경우는 DataSynth가 아니라 PHASE1 topic/case 또는 PHASE3 의미해석 과제로 분리한다.

---

## 2026-05-17: Sprint A1 supervised ML gate hardening

### 문제

PHASE2 supervised track이 DataSynth/feedback/pseudo label을 같은 방식으로 취급하면서, 양성 수가 부족하거나 pseudo fallback으로 생성된 라벨도 supervised 학습과 모델 저장 경로에 들어갈 수 있었다. 운영자는 supervised가 꺼진 이유도 `training_report.json`에서 구조적으로 확인하기 어려웠다.

### 해결

`LabelResult`에 `quality_grade`, `gate_decision`, `gate_reason`을 추가하고, `positive_count < 50` 또는 `positive_rate < 0.01`이면 `low_signal_fallback`으로 판정하도록 했다. `SupervisedDetector.train()`은 `SupervisedGateError`로 학습 전에 차단하며, Phase2 training service는 supervised gate 실패 trial을 `skipped`로 기록하고 `training_report.json.supervised_gate`를 추가한다.

검증은 focused 63건, 요청된 Phase2 guard/supervised 회귀 37건, combined focused regression 82건을 통과했다. 변경 파일 ruff check도 통과했다. Handoff: `artifacts/sprint_phaseA_A1_handoff_2026-05-17.md`.

---

## 2026-05-17: Sprint A2 phase2 train AutoML separation

### 문제

A1에서 supervised gate는 구조화됐지만, PHASE2 학습 산출물과 추론 계약은 여전히 `training_report.json` 내부 metadata에 많이 의존했다. Leaderboard와 promotion 사유를 별도 감사 산출물로 검토하기 어렵고, inference service는 detector status의 bootstrap reason을 cold-start mode로 해석할 수 있었다.

### 해결

`leaderboard.json`과 `promotion_decision.json` 산출 모듈을 추가하고 `save_phase2_training_report()`에서 함께 저장하도록 했다. Inference contract에는 `model_versions`를 추가해 model version, source trial, schema hash, fixture contract를 명시했다. `run_phase2_inference()`는 최신 training snapshot이 있으면 `training_contract`, 없으면 `untrained_contract_only`만 반환하도록 단순화해 A1 → A2 흐름에서 supervised gate와 promotion contract가 추론의 유일한 진입 계약이 되도록 했다.

검증은 A2 서비스 focused 45건, A1/Phase2 guard combined 83건, 변경 파일 ruff check를 통과했다. Cold-start bootstrap 관련 focused grep도 0건이다. Handoff: `artifacts/sprint_phaseA_A2_handoff_2026-05-17.md`.

---

## 2026-05-15: manipulation v3 Rust 후보 승격

### 문제

T9에서 Python materialize 후처리를 Rust CLI 단일 명령으로 이관했다. 후보 데이터셋은 생성과 truth/raw-data guard를 통과했지만, Phase1 topic regression guard에서 `circular_related_party_transaction`, `embezzlement_concealment` expected-topic 진입이 활성 Python v3 후보보다 낮았다. 원인은 Rust 후보가 `posting_date` 변경 시 `fiscal_period`도 정합화한 반면, 기존 Python 후보는 일부 기간 불일치를 남겼기 때문이다.

### 확인

- 활성 데이터셋: `data/journal/primary/datasynth_manipulation_v3/`
- 생성 명령: `cargo run -p datasynth-cli --bin datasynth-data -- generate --profile manipulation-v3 ...`
- truth gate: pass, manipulation truth 420건
- Guard 1 회계 실체: pass
- Guard 2 정상 배경 fitting 차단: pass
- Phase1 score/rule/review hit docs: 420 / 420
- Guard 3 topic regression: 기존 Python 후보 대비 기준 재설정
  - circular expected topic: 34 -> 22
  - embezzlement expected topic: 76 -> 42

### 원인

Rust 후보는 `posting_date`를 변경할 때 `fiscal_period`도 같이 정합화한다. 기존 Python materialize 후보는 일부 scenario에서 `posting_date`를 6월/12월로 바꾼 뒤 `fiscal_period`가 1월 값으로 남는 케이스가 있었다. Rust가 이 불일치를 재현하지 않으면서 current Phase1 case/topic baseline과 달라졌다.

### 결정

Rust에서 stale `fiscal_period`를 일부러 재현하는 것은 회계 정합성을 악화시키는 fitting 위험이므로, 회계기간 정합성을 우선하는 1번 안을 채택했다. `datasynth_manipulation_v3_rust_candidate_fixed`를 활성 `datasynth_manipulation_v3`로 승격했고, 기존 Python 후보는 archive로 보존했다.

### 산출물

- `tools/datasynth/crates/datasynth-cli/src/manipulation_v3.rs`
- `artifacts/manipulation_v3_rust_migration_report.md`
- `artifacts/manipulation_v3_final_mutation_recovery.json`
- `artifacts/manipulation_v3_rust_fixed_topic_analysis.json`
- `data/journal/primary/DATASET_VARIANTS.md`
- `data/journal/archive/primary_legacy_20260515/datasynth_manipulation_v3_python_candidate/`

### 교훈

1. Python 후처리와 byte/behavior compatible하게 이관하는 것과 synthetic accounting consistency를 개선하는 것은 별도 의사결정이다.
2. topic 진입률 회귀를 맞추기 위해 period 불일치를 재현하면 DataSynth fitting이 된다.
3. promotion 기준은 Phase1 topic 수치 일치가 아니라 raw-data 회계 정합성과 truth/provenance 계약 통과여야 한다.

---

## 2026-05-16: manipulation v4 후보 생성 및 shortcut 완화 검증

### 문제

PHASE2 fitting audit에서 `manipulation_v3`가 테스트용으로는 유효하지만, 일부 shortcut 위험을 가진다는 분석이 나왔다. 특히 manipulated source/manual 분포, unusual timing feature 동시 점등, deterministic fictitious amount, hold-out scenario 부재가 Phase2 모델의 일반화 검증을 약하게 만들 수 있었다.

### 판단

- v4는 필요하지만 바로 active 승격하지 않는다.
- AUPRC 0.6~0.8 같은 모델 점수는 DataSynth 생성 gate로 쓰지 않는다.
- DataSynth에서 할 일은 회계 실체와 자연 노이즈를 만드는 것이고, 모델 점수는 measure-only로 둔다.
- `datasynth_contract_v2`와 활성 `datasynth_manipulation_v3`는 유지한다.

### 해결

- Rust CLI에 `manipulation-v4` profile을 추가했다.
- 출력 후보: `data/journal/primary/datasynth_manipulation_v4_candidate/`
- 기존 6개 scenario에 hold-out 2개를 추가했다.
  - `suspense_account_abuse`: 100 docs
  - `expense_capitalization`: 100 docs
- 총 truth docs는 420이 아니라 620으로 고정했다.
- `tools/scripts/audit_manipulation_v4_candidate.py`를 추가해 raw-data guard와 Phase2 measure-only 지표를 분리했다.
- S4/S5/S8 분석 스크립트는 v3 하드코딩 대신 환경변수로 v4 후보를 받을 수 있게 보강했다.

### 결과

| 항목 | 결과 |
|---|---:|
| manipulation truth docs | 620 |
| truth/provenance gate failures | 0 |
| normal manual source rate | 0.4144 |
| unusual timing all-four shortcut share | 0.0 |
| unusual timing pattern count | 4 |
| expense capitalization asset+expense pair share | 1.0 |
| suspense aging >= 90 days share | 1.0 |
| fictitious rounded amount unique count | 101 |
| Phase1 score/rule/review hit docs | 620 / 620 |
| Top500 truth capture | 376 / 620 |
| S5 rule-only AUPRC | 0.3971 |
| S8 current-policy AUPRC | 0.9901 |
| S8 full-OOF AUPRC | 0.9860 |
| S8 rules-only AUPRC | 0.2069 |

### 교훈

1. synthetic shortcut 완화는 DataSynth에서 처리할 수 있지만, supervised raw feature가 높은 AUPRC를 내는 문제는 Phase2 모델 설계 문제다.
2. hold-out scenario를 추가하면 truth taxonomy가 바뀌므로 기존 v3와 단순 점수 비교하면 안 된다.
3. v4 promotion은 raw-data guard 통과만으로 충분하지 않고, Phase2가 새 taxonomy와 supervised feature 강도를 받아들일지 결정해야 한다.

---

## 2026-05-17: Sprint D1 topic scoring anti-fitting calibration

### 문제

PHASE1 topic scoring의 일부 auxiliary floor가 synthetic truth scenario에 맞춰진 것처럼 동작할 수 있었다. 특히 `approval_bypass + L3-02/L3-05/L3-06` 같은 약한 승인 context가 High floor로 승격되면 정상 실무 noise까지 상단으로 끌어올릴 위험이 있었다. 이번 점검 기준은 도메인 근거와 정상군 noise 차단이다.

### 해결

`src/detection/topic_scoring.py`에서 약한 approval context는 Medium으로만 유지하고, High는 고액·cutoff·manual closing·manual after-hours 등 강한 근거가 붙은 경우로 제한했다. `config/phase1_case.yaml`에는 `anti_fitting_policy`를 추가했고, topic scoring lock 문서와 relationship map은 FSS/ISA/PCAOB-supported floor와 weak auxiliary floor를 분리하도록 갱신했다.

검증은 `test_rule_scoring.py` 60건, rule scoring + case builder 128건, 전체 detection 1099건 통과와 composite sort focused 4건 통과로 확인했다. Manipulation v2 profile 산출물은 `artifacts/phase1_manipulation_v2_topic_antifit_profile_20260517.json`이며, 해당 truth capture 수치는 informational only로 기록했다.

---

## 2026-05-18: V7 fixed3 by-year PHASE2 smoke validation

### 문제

Streamlit UI sprint 진입 전 V7 fixed3 데이터셋의 2022/2023/2024 연도 partition에서 PHASE2 active 5 family가 실제로 score와 sub-detector hit를 산출하는지 확인해야 했다.

### 해결

`tools/scripts/phase2_inference_v7_fixed3_by_year.py`를 재현 스크립트로 정리하고, PHASE1 case input cache를 연도별로 분리해 동일 `schema_hash=1468611365` model bundle과 4개 rule-style detector를 적용했다. 산출물은 `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md`와 `artifacts/phase2_inference_v7_fixed3_year_*.json`에 저장했다.

### 결과

| Family | 2022 | 2023 | 2024 | Metric |
|---|---:|---:|---:|---|
| `unsupervised` | 22,689 | 26,172 | 30,374 | ECDF q95 high count |
| `timeseries` | 299,127 | 296,765 | 295,572 | score>0 nonzero count |
| `relational` | 15,718 | 15,324 | 15,752 | score>0 nonzero count |
| `duplicate` | 77,115 | 74,367 | 70,918 | score>0 nonzero count |
| `intercompany` | 0 | 0 | 0 | score>0 nonzero count |

### 교훈

1. PHASE2 smoke 결과의 truth join은 informational only로 유지하고 family ranking/preset 조정 근거로 쓰지 않는다.
2. rule-style family는 hit 0 sub-detector도 UI에서 숨기지 않아야 detector coverage를 오해하지 않는다.
3. model bundle과 dashboard 변경 없이 분석 산출물만 생성하는 smoke 경로를 유지한다.

---

## 2026-05-18: Diag-1 intercompany family 0건 root cause

### 문제

V7 fixed3 by-year PHASE2 smoke에서 `intercompany` family가 2022/2023/2024 모두 `score>0` 0건이었다. 반면 같은 partition에서 `relational` R03 transfer pricing은 7K~8K hit가 있어 IC 거래 자체가 없는 상태는 아니었다.

### 가설 검증

| 가설 | 결과 | 근거 |
|---|---|---|
| A. V7 fixed3에 IC 거래 자체가 없음 | 기각 | 2024 기준 `counterparty_type=IntercompanyAffiliate` 15,709행, `is_intercompany=True` 17,813행, C001/C002/C003 거래처 조합 존재 |
| B. IC 매칭 필수 컬럼 부재 | 부분 확정 | `intercompany_id`/`intercompany_code`는 없고, PHASE2 matcher가 pair reference로 기대한 `reference`는 matched-pair reference가 아님 |
| C. detector 입력 형식 불일치 | 확정 | V7은 `IC-C001` 형식 trading partner와 `ic_unmatched_reference` sidecar evidence를 갖지만, IC01은 기존 그룹 대사 결과만 사용 |
| D. preset tolerance 부적합 | 기각 | `amount_tolerance=0/0.03/0.10`, `max_day_diff` 완화 실험 모두 기존 입력에서는 0건 유지 |

### 근본 원인

`IntercompanyMatcher`의 IC01은 `match_ic_groups()`가 만든 `has_counterpart=False`만 unmatched evidence로 해석했다. V7 fixed3 PHASE1 case input은 matched-pair source documents를 직접 포함하지 않고 `ic_unmatched_reference` sidecar 컬럼으로 unmatched reference를 보존하므로, IC01 입력 계약이 V7 fixed3 case input 형식을 반영하지 못했다.

### 해결

`src/detection/intercompany_rules.py::ic01_unmatched_intercompany()`에서 `is_intercompany=True AND ic_unmatched_reference=True`를 IC01 evidence로 합산했다. IC02/IC03은 matched-pair amount/date 대사에 필요한 pair reference가 없으면 계속 0으로 남긴다. 이 변경은 V7 fixed3 source, dashboard, model bundle을 수정하지 않는다.

### 결과

| 연도 | 항목 | 수정 전 | 수정 후 |
|---:|---|---:|---:|
| 2022 | intercompany nonzero | 0 | 12 |
| 2022 | IC01 unmatched_intercompany | 0 | 12 |
| 2022 | IC02 amount_mismatch | 0 | 0 |
| 2022 | IC03 timing_gap | 0 | 0 |
| 2023 | intercompany nonzero | 0 | 6 |
| 2023 | IC01 unmatched_intercompany | 0 | 6 |
| 2023 | IC02 amount_mismatch | 0 | 0 |
| 2023 | IC03 timing_gap | 0 | 0 |
| 2024 | intercompany nonzero | 0 | 16 |
| 2024 | IC01 unmatched_intercompany | 0 | 16 |
| 2024 | IC02 amount_mismatch | 0 | 0 |
| 2024 | IC03 timing_gap | 0 | 0 |

UI meta는 `skipped=false`, `metric_confidence=sidecar_unmatched_reference_only`, `active_sub_detectors=["IC01"]`, `zero_hit_sub_detectors=["IC02","IC03"]`로 기록한다.

### 검증

- `uv run pytest tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py tests/modules/test_detection/test_intercompany_matcher.py -q` -> 25 passed.
- `uv run pytest tests/modules/test_preprocessing/test_label_strategy.py tests/modules/test_detection/test_supervised_detector.py tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py tests/modules/test_services/test_phase2_training_service.py tests/modules/test_services/test_phase2_layer_a_guards.py tests/modules/test_services/test_phase2_case_contract.py tests/modules/test_services/test_phase2_leaderboard.py tests/modules/test_services/test_phase2_promotion_policy.py tests/modules/test_services/test_phase2_inference_service.py tests/modules/test_services/test_phase2_detector_expansion.py -q` -> 98 passed.
- `uv run ruff check src/detection/intercompany_rules.py tests/modules/test_detection/test_intercompany_v7_fixed3_smoke.py` -> PASS.
- `artifacts/phase2_inference_v7_fixed3_year_2024_intercompany_rerun.json` 생성.

---

## 2026-05-23: R03/TS01 calibration trial rollback

### 문제

fixed4 PHASE2 합산에서 `R03_transfer_pricing_anomaly`와
`TS01_transaction_burst`가 noise-dominant sub-detector로 진단됐다.
계획서 `dev/active/r03-ts01-calibration/r03-ts01-calibration-plan.md`는
recall grid search 없이 정상(truth-negative) 분포 q95/q99와 도메인 근거로만
calibration 값을 정하도록 했다.

### 조치

`tools/scripts/r03_ts01_natural_distribution_audit.py`를 추가해 fixed4 자연 분포를
측정했다.

| 항목 | decision basis | q95 | q99 |
|---|---|---:|---:|
| R03 IC pair deviation | truth-negative rows | 0.999517 | 4.659168 |
| TS01 daily z-score | truth-negative dates | 2.048298 | 3.299160 |

trial 변경:

- R03 `deviation_threshold=1.0`, `min_ic_pairs=5`
- TS01 detector 기본 dormant, 함수 sigma 참고값 `3.30`

### 결과

| 항목 | BEFORE | AFTER trial |
|---|---:|---:|
| R03 row hit | 23,389 | 1,248 |
| R03 row truth ratio | 0.28% | 0.88% |
| TS01 row hit | 52,787 | 34,628 |
| UTRDI PHASE2 T100 recall | 6.94% | 19.68% |
| UTRDI integrated T100 recall | 20.16% | 18.87% |

통합 T100 recall 이 `-1.29pp` 하락해 사전 rollback 조건(`-1pp 이상`)을 충족했다.
코드와 active 캐시는 BEFORE 상태로 복원했고, trial 산출물은
`*_AFTER_R03_TS01_FIX_ROLLED_BACK.*`로 보존했다.

### 교훈

1. R03 noise 감소는 성공했지만, 통합 RRF T100에서는 PHASE1과 family rank의 상호작용이
   우선 rollback 조건을 만들 수 있다.
2. rollback 조건은 recall을 튜닝 근거로 쓰는 것이 아니라 사전에 정한 운영 안전장치다.
3. 같은 값 주변을 추가 탐색하지 않는다. 다음 조치는 별도 RFC인 family weight 또는
   R03/TS01의 도메인 정의 재검토로 분리한다.

상세 보고서: `artifacts/phase2_r03_ts01_fix_before_after_fixed4_20260523.md`.

---

## 2026-05-23: R03/TS01 split trial

### 문제

직전 R03+TS01 동시 trial은 PHASE2 T100을 크게 회복했지만 통합 T100이
`20.16% → 18.87%`로 `-1.29pp` 하락해 rollback 됐다. 손실 원인이 R03 calibration인지
TS01 dormant인지 분리할 필요가 있었다.

### 조치

직전 trial 값만 재사용하고 새 값을 탐색하지 않았다.

- Phase A: R03만 `deviation_threshold=1.0`, `min_ic_pairs=5`
- Phase B: TS01만 dormant + function default sigma `3.30`

각 phase마다 측정 후 산출물을 `AFTER_R03_ONLY` / `AFTER_TS01_ONLY`로 보존하고,
코드와 active artifacts를 `BEFORE_SPLIT_TRIAL` 상태로 복원했다. SHA256 일치도 확인했다.

### 결과

| 지표 | BEFORE | R03 alone | TS01 alone | 동시 trial |
|---|---:|---:|---:|---:|
| PHASE2 T100 | 6.94% | 15.32% | 8.71% | 19.68% |
| PHASE2 T500 | 34.68% | 37.26% | 25.97% | 25.97% |
| 통합 T100 | 20.16% | 19.84% | 19.19% | 18.87% |
| 통합 T500 | 42.10% | 42.10% | 41.94% | 45.00% |

둘 다 사전 rollback 조건은 통과했다. 다만 TS01 alone은 통합 T100이 rollback 임계
`19.16%`보다 `0.03pp`만 높고 PHASE2 T500 손실이 커서 운영 여유가 작다.

### 교훈

1. 동시 trial의 통합 T100 손실은 단일 변경 하나만의 즉시 rollback 실패라기보다
   두 변경의 ranking 재배치가 겹친 결과다.
2. R03 alone은 noise 감소와 PHASE2 T100 회복이 크고 통합 T100 손실이 rollback 조건 밖이다.
3. TS01 dormant는 단독으로도 매우 근소하게만 통과하므로 별도 RFC 없이 동시 적용하지 않는다.

권장: R03 단독 적용 PR 우선. 상세 보고서:
`artifacts/phase2_r03_ts01_split_trial_fixed4_20260523.md`.

---


## 2026-05-18: Diag-2 duplicate inference optimization

### 문제

V7 fixed3 Phase A smoke에서 `duplicate` family가 2024 partition 340,764 rows 기준 83.66s가 걸렸다. 다른 active family는 초 단위였기 때문에 Streamlit UI 진입 시 duplicate inference가 직접적인 대기 병목이었다.

### 원인

기존 L2-03b/L2-03c/L2-03d는 `gl_account` 단위 pair scan에 가깝게 동작했다. 2024 partition의 `gl_account` 단독 후보 pair 상한은 약 1.1B였고, pre-optimization legacy 50k cProfile에서도 L2-03d, L2-03c, L2-03b가 누적 시간 상위였다.

### 해결

`src/detection/duplicate_rules.py`에서 amount/date/gl-account blocking을 도입했다. Fuzzy duplicate는 amount tolerance 후보에만 RapidFuzz를 적용하고, split transaction은 date window와 two-sum range로 줄였으며, time-shifted duplicate는 amount bucket과 date sliding window로 변경했다. 반복 line_text 정규화는 cache로 대체했다. Sampling은 사용하지 않았다.

### 결과

| Scope | Before | After avg | Status |
|---|---:|---:|---|
| 2024 partition | 83.66s | 2.744s | PASS |
| Full V7 fixed3 | ~5min cumulative smoke baseline | 4.533s | PASS |

| Sub-detector | Before 2024 | After 2024 | Diff |
|---|---:|---:|---:|
| `L2-03a` exact_duplicate_amount | 2,964 | 2,964 | 0.000% |
| `L2-03b` fuzzy_duplicate | 34,655 | 34,655 | 0.000% |
| `L2-03c` split_transaction | 16,784 | 16,784 | 0.000% |
| `L2-03d` time_shifted_duplicate | 28,590 | 28,590 | 0.000% |

### 검증

- `uv run pytest tests/modules/test_detection/test_duplicate_detector.py tests/modules/test_detection/test_duplicate_performance.py tests/modules/test_detection/test_audit_coverage_contract.py -q` -> 22 passed.
- `uv run ruff check src/detection/duplicate_rules.py src/detection/duplicate_detector.py tests/modules/test_detection/test_duplicate_performance.py` -> PASS.
- Phase A focused regression suite -> 96 passed.
- `uv run pytest tests/modules/test_detection -q` -> 1103 passed, 3 skipped, 4 warnings.
- 상세 측정 JSON: `artifacts/phase2_duplicate_perf_before_after_20260518.json`.

---

## 2026-05-24: Phase 2 timeseries family — statistical anomaly 보강

### 상황

`timeseries` family 가 burst/frequency rule-style boolean (0/0.4/0.8 3 값 이산)
에 머물러 statistical anomaly family 로 설명하기 어려웠다. row score 분해능이
없어 PHASE2 family aggregation (Noisy-OR/lane/tie-break) 에서 ranking 정보를
못 제공했다.

### 해결

`src/detection/timeseries_rules.py` 에 3 sub-signal continuous score 함수를
추가했다.

- `daily_burst_positive_robust_z_score` — 일별 거래 건수 → 14일 rolling
  median + MAD baseline → modified z-score (MAD=0 시 IQR → Poisson std fallback)
  → noise floor 1.5 차감 → [0, 30] clip.
- `group_frequency_positive_robust_z_score` — vendor/account/user 그룹별
  일자 단위 7일 trailing sum → 그룹 자체 시계열 robust z.
- `period_end_concentration_score` — `1 - distance/(window+1)` × 일자 모집단
  거래량 percentile top tail. D-window 이내 모두 양수 가중치 보장
  (review 반영, 이전 식 `1 - distance/window` 는 D-window 일자 score 가 0
  으로 떨어졌다).

`TimeseriesDetector._build_result` 는 `ts01_signal = max(s1_ecdf, s3_raw)`,
`ts02_signal = s2_ecdf`, `row_score = max(ts01, ts02)` 결합 후 ECDF percentile
임계 (`ts_burst_high_pctile`, `ts_freq_high_pctile`) + period_end raw 임계
(`ts_period_end_high`) 로 TS01/TS02 boolean 을 재계산한다. zero-preserving
ECDF (`rank(method="max", pct=True)`) 로 0 점 행은 0 보존.

`config/settings.py` 에 ts_* 파라미터 7 개 (`ts_burst_window_days`,
`ts_group_window_days`, `ts_group_min_support`, `ts_burst_high_pctile`,
`ts_freq_high_pctile`, `ts_period_end_window_days`, `ts_period_end_high`)
추가. legacy `burst_*`/`frequency_*` 는 deprecated 주석.

Phase 1 rule hit / `flagged_rules` / DataSynth 라벨 입력 없음 (독립 score).

### 검증

- `uv run pytest tests/modules/test_detection/test_timeseries_rule.py -v`
  → **37 passed** (legacy boolean 19 + sub-signal/detector contract 18 신규).
- `uv run pytest tests/phase2_rulebase/test_subdetector_tiers_schema.py -v`
  → **14 passed** (tier YAML lock 유지).
- `uv run ruff check src/detection/timeseries_rules.py
  src/detection/timeseries_detector.py
  tests/modules/test_detection/test_timeseries_rule.py config/settings.py`
  → **All checks passed**.
- import smoke (TimeseriesDetector + phase2_case_family_aggregator) → ok.
- `uv run pytest tests/modules/test_detection -q` → **1210 passed, 4 failed,
  3 skipped**.

### 사전 실패 4건 (timeseries 변경과 무관)

`tests/modules/test_detection/test_intercompany_matcher.py::TestProbabilisticReconciliation`
4 개 실패는 본 작업 이전부터 존재한 상태 (`src/detection/intercompany_matcher.py`
와 `src/services/phase2_case_contract.py` 가 본 세션 시작 시점에 미커밋
working tree 변경 상태였으며 본 작업은 두 파일을 일절 수정하지 않았다).
intercompany 디버깅은 별도 작업으로 분리.

| 실패 케이스 | 본 작업 관련성 |
|---|---|
| `test_amount_mismatch_prob_monotonic` | 무관. `ic_amount_prob`는 IntercompanyMatcher 내부. |
| `test_timing_gap_prob_monotonic` | 무관. |
| `test_cross_currency_amount_term_zero` | 무관. |
| `test_scores_combine_with_prob` | 무관. |

### 거버넌스

- `config/phase2_subdetector_tiers.yaml` TS01/TS02 의 `distribution_metric`/
  `source_citation` 에 "PRE-MIGRATION measurement; POST-MIGRATION REMEASUREMENT
  PENDING" 명시 (lock 파일과 실제 detector 분포 정합 보존).
- 본 작업은 TS01/TS02 rule_id 와 tier lock (TS01=moderate, TS02=weak) 을 그대로
  유지. TS03 같은 신규 sub-detector 추가하지 않음 — schema test 통과.

### UI

dashboard/ 변경 없음. Phase 2 lane/overlay/tie-break 컴포넌트는 기존
`result.scores` (row max) 와 `details[TS01/TS02]` 인터페이스만 사용하므로
detector 내부 변경은 투명.

---

## 2026-06-01 — v33d IC native case 0/34 회귀 원인 및 수정

### 상황

v33d responsibility full run에서 `injected_intercompany_primary` denominator는
34였지만 native intercompany case가 0건이었다. v33d DataSynth는 journal-visible
shortcut token을 제거했지만, 34개 primary 문서는 여전히 1150/2050 IC GL,
동일 문서 내 receivable/payable 대칭 금액, 관련회사 counterparty context를
보유했다.

### 원인

`IntercompanyMatcher.detect()`가 `is_intercompany`를 필수 입력으로 요구해,
v33d journal처럼 해당 shortcut 컬럼이 제거된 입력에서는 GL/account evidence를
보기 전에 empty result를 반환했다. GL prefix로 `is_intercompany`를 임시
복구해 확인하면 두 번째 문제가 드러났다. `match_ic_groups()`가 문자열
`posting_date`를 groupby median으로 직접 집계해 pandas가 object median
예외를 냈다.

### 해결

- matcher 입력을 변경하지 않고, configured IC GL prefix에서 내부용
  `is_intercompany`를 추론하도록 변경했다.
- `match_ic_groups()`의 posting date 집계는 `pd.to_datetime(..., errors="coerce")`
  결과를 median 대상으로 사용하도록 바꿨다.
- partner matching key를 `trading_partner` 단일 컬럼에서 `affiliate`,
  `counterparty`, `counterparty_code`, `counterparty_id` 대체 컬럼까지 확장했다.
  DataSynth shortcut token은 재도입하지 않았다.

### 검증

- `uv run pytest tests/modules/test_detection/test_intercompany_matcher.py tests/modules/test_detection/test_intercompany_reciprocal_flow.py tests/modules/test_detection/test_intercompany_matcher_pair_artifact.py -q`
  → **79 passed**.
- `uv run pytest tests/modules/test_detection -q -k intercompany`
  → **109 passed, 1259 deselected**.
- v33d IC-only diagnostic:
  - reciprocal artifact count: 34
  - primary denominator: 34
  - primary docs covered by reciprocal artifact: 34
  - TOP500 recall proxy from native IC artifact: **34/34**
- `uv run ruff check src/detection/intercompany_matcher.py src/detection/intercompany_rules.py tests/modules/test_detection/test_intercompany_matcher.py tests/modules/test_detection/test_intercompany_reciprocal_flow.py`
  → **All checks passed**.

---

## 2026-05-26 — DataSynth 2022 적요 한글 깨짐 원인 및 수정

### 상황

`data/journal/primary/datasynth_manipulation_v7_candidate_fixed5_normalcal5`
의 `journal_entries_2022.csv`를 대시보드 결과 그리드에서 볼 때 `line_text`
적요가 `л`, `δ`, `Θ` 등으로 깨져 표시됐다. CSV 헤더와 2023/2024 데이터는
정상이라 생성물 전체 인코딩 문제와 표시 컴포넌트 문제를 분리해 확인했다.

### 원인

원본 `journal_entries_2022.csv`는 UTF-8로 정상 디코딩되지만,
`src.ingest.text_reader._detect_encoding()`이 64KB 샘플을
`charset_normalizer`에 바로 맡기면서 `ptcp154`로 오탐했다. `ptcp154`는
한글 UTF-8 바이트를 키릴/기호 문자로 조용히 디코딩하므로 ingest 이후
적요 값 자체가 깨진 문자열이 됐다.

### 해결

`_detect_encoding()`에서 BOM을 먼저 확인하고, 그 외 파일은 UTF-8 incremental
strict decode가 성공하면 `utf-8`을 우선 채택하도록 변경했다. 샘플 끝이
멀티바이트 문자 중간에서 잘리는 경우를 허용하기 위해 `final=False`를
사용했다. CP949처럼 UTF-8 strict decode가 실패하는 파일은 기존
`charset_normalizer` 경로를 그대로 사용한다.

### 검증

- `uv run pytest tests/modules/test_ingest/test_text_reader.py -q` → **15 passed**.
- 실제 DataSynth 파일 감지 확인:
  - `journal_entries_2022.csv` → `utf-8`, confidence `1.0`
  - `journal_entries_2023.csv` → `utf-8`, confidence `1.0`
  - `journal_entries_2024.csv` → `utf-8`, confidence `1.0`
  - `journal_entries.csv` → `utf-8`, confidence `1.0`

### 후속 수정

대시보드 PHASE1 결과에서 적요가 계속 깨져 보이는 추가 원인은 수정 전 ingest
결과가 `artifacts/ingest_cache/*.parquet`에 남아 있었기 때문이다. 파이프라인은
원본 CSV보다 ingest cache를 먼저 사용하므로, 인코딩 감지 로직을 고쳐도 기존
`ingest-cache-v1` parquet를 재사용하면 깨진 문자열이 그대로 표시된다.

`src/pipeline.py`의 ingest cache schema를 `ingest-cache-v2`로 올려 기존 v1 캐시를
자동 무효화했다. 사용자는 기존 PHASE1 세션/DB 결과를 삭제하거나 CSV를 다시
읽어 PHASE1을 재실행해야 정상 적요가 반영된다.

추가 확인 결과, Streamlit에서 PHASE1만 재실행하면 CSV를 다시 읽지 않고 기존
`KEY_PREP_RESULT.data` 또는 DB에서 복원된 `general_ledger` DataFrame을 입력으로
사용할 수 있다. 이 경우 ingest cache를 무효화해도 이미 세션/DB에 들어간 깨진
문자열이 계속 전달된다. 또한 feature cache도 별도 `feature-cache-v1` 키를 쓰고
있어 과거 feature parquet가 재사용될 수 있었다.

후속 보완:

- `src/feature/cache.py` schema를 `feature-cache-v2`로 올려 기존 feature cache를
  자동 무효화.
- `src/ingest/text_mojibake.py`를 추가해 UTF-8 한글이 `ptcp154`로 오디코딩된
  문자열만 보수적으로 복구.
- `src/services/analysis_service.py`의 PHASE1 feature 입력과
  `src/db/batch_reader.py`의 DB batch 복원 경로에서 해당 복구를 적용.

검증:

- `uv run pytest tests/modules/test_ingest/test_text_reader.py tests/modules/test_pipeline/test_pipeline.py::TestRunFromDataframe::test_ignores_v1_ingest_cache_after_encoding_detector_change -q`
  → **16 passed**.
- `uv run ruff check src/pipeline.py tests/modules/test_pipeline/test_pipeline.py`
  → **All checks passed**.
- `uv run pytest tests/modules/test_ingest/test_text_mojibake.py tests/modules/test_ingest/test_text_reader.py tests/modules/test_pipeline/test_pipeline.py::TestRunFromDataframe::test_ignores_v1_ingest_cache_after_encoding_detector_change tests/modules/test_feature/test_feature_cache.py -q`
  → **21 passed**.
- `uv run ruff check src/ingest/text_mojibake.py src/feature/cache.py src/services/analysis_service.py src/db/batch_reader.py tests/modules/test_ingest/test_text_mojibake.py tests/modules/test_pipeline/test_pipeline.py`
  → **All checks passed**.

---
