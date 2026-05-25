# Phase2 Family Ranking - Task Checklist

## Progress Summary
31 / 31 sprint scope tasks complete (100%) + 4건 post-review bug fix 적용.
**2026-05-20 follow-up**: production overlay wiring P1-a~d 해결. `DetectionResult`
row score/details 를 Phase1 case 단위로 집계해 `family_contributions`, `top_family`,
`max_evidence_tier`, `lane_membership` 을 production inference 경로에 채운다.

### Post-review bug fix (2026-05-19)
- ✅ #4 sub-detector evidence_tier 저장 + count 정확화
- ✅ #3 coverage_breadth near-dormant 제외 + positive guard
- ✅ #2 lane_membership ECDF ≥ 0.95 명시 조건
- ✅ #1 production wiring 미완료를 코드 docstring + handoff §8.0 에 정직 표시

### P1 follow-up (2026-05-20)
- ✅ row-level family score 집계 helper 추가
  - Evidence: `src/services/phase2_case_family_aggregator.py`
  - 역할: `ml_unsupervised`, `timeseries`, `relational`, `duplicate`, `intercompany`
    score/details 를 case 단위 max score, zero-preserving ECDF, top sub-detector 로 집계.
- ✅ production call site wiring
  - Evidence: `src/pipeline.py::_build_phase2_case_overlays`,
    `src/services/phase2_inference_service.py::_attach_phase2_case_overlays`
  - 영향: placeholder overlay 만 생성되던 상태를 해소. primary PHASE1 priority 및
    PHASE1↔PHASE2 queue ordering 은 변경하지 않음.
- ✅ Streamlit summary placeholder 방어
  - Evidence: `dashboard/tab_phase2.py::_render_phase2_summary_ribbon`
  - 영향: overlay 미생성 상태를 `0건`으로 오해하지 않도록 `- / case-level overlay 미생성`
    으로 표시.
- ✅ 검증
  - `uv run pytest tests/modules/test_services/test_phase2_case_family_aggregator.py -q`
    → 2 passed
  - `uv run pytest tests/modules/test_dashboard/test_tab_phase2.py -q` → 20 passed
  - `uv run pytest tests/modules/test_services/test_phase2_inference_service.py -q`
    → 11 passed
  - `uv run pytest tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py -q`
    → 3 passed
  - `uv run ruff check ...` → All checks passed

**Pivot (2026-05-19)**: Phase C 측정에서 hierarchical RRF -6.45pp 손실 확인 → reject. primary PHASE1+VAE 2-way RRF 유지, family signal 은 lane/overlay/tie-break 으로만 사용. Phase D/E/F 재정의.

## Phase A: L5 evidence_tier YAML + schema test ✅
- [x] `config/phase2_subdetector_tiers.yaml` 작성 (14 sub-detector 모두 cover)
  - Evidence: 14 entries (1 unsupervised + 2 timeseries + 4 relational + 4 duplicate + 3 intercompany). PCAOB AS 2401 §B7, ISA 240 ¶A41, ISA 550 ¶A19~A21 인용 + V7 fixed3 분포 측정값 출처.

- [x] `src/services/subdetector_tiers.py` loader 작성
  - Evidence: `load_subdetector_tiers()` + `SubdetectorTier` dataclass + `max_tier_weight()` 노출. `TIER_ORDER`로 strong=3 > moderate=2 > weak=1 > ml_quantile=0.

- [x] `tests/phase2_rulebase/test_subdetector_tiers_schema.py` schema test
  - Evidence: 14 tests passed (TestCoverage 2, TestTierValues 3, TestSourceFields 4, TestStrongTierStandardBacking 1, TestTierWeightHelper 4).

- [x] D044 PR 템플릿에 tier 변경 fitting-risk check 추가
  - Evidence: docs/DECISION.md D044 fitting-risk check 섹션에 "PHASE2 sub-detector tier 변경" 라인 추가, 출처 기준서/분포 + truth recall 미사용 명시 요구.

## Phase B: L0 분포 진단 metric + training_report pin ✅
- [x] `src/services/phase2_family_diagnostics.py` 신규 — 3 metric 함수
  - Evidence: `compute_row_nonzero_rate`, `compute_rank_resolution`, `compute_top_tail_resolution(scores, q=0.95)` + dataclass `FamilyDiagnostics` 노출. numpy 기반으로 ndarray 타입 안전.

- [x] `Phase2TrainingReport.family_diagnostics` 슬롯 결정 — metadata 사전 활용
  - Evidence: `Phase2TrainingReport.metadata` 는 이미 `inference_contract`/`promotion_policy` 등 dict 슬롯을 보유. `attach_family_diagnostics_to_metadata()` 가 `metadata["family_diagnostics"]` 에 `{schema_version, q, diagnostics, roles}` payload pin. 별도 typed field 추가하지 않음으로 기존 회귀 영향 0.

- [x] training step 측정 hook 분리 — `attach_family_diagnostics_to_metadata` helper
  - Evidence: helper 가 family score Series dict 를 받아 metadata 에 pin. 실제 training service 호출 site 는 Phase E (production cutover) 에서 row-level family score aggregator 와 함께 wire. Phase C dry-run 도 이 helper 를 호출.
  - Deferred 사유: `src/services/phase2_training_service.py` 는 현재 row-level family score 를 단일 dict 로 노출하지 않음 (trial artifact 분산). Phase C/E 에서 aggregator 추가 후 single wiring.

- [x] unit test
  - Evidence: `tests/modules/test_services/test_phase2_family_diagnostics.py` 31 tests passed. metric edge case + V7 fixed3 분포 pattern + metadata round-trip + invalid role 필터링 모두 cover. 누적 Phase A+B 45 tests passed.

## Phase C: hierarchical RRF measurement-only ✅ (reject 결정)
- [x] `compute_phase2_internal_rrf` helper
  - Evidence: `src/services/queue_fusion.py` 에 helper 추가. active-only / booster-only / mixed / phase1 eligibility 4 분기 정상.

- [x] booster eligibility 함수
  - Evidence: `_compute_booster_eligibility` 내부 helper 로 통합. q95 진입 / 미진입 / phase1 q95 진입 분기 정확.

- [x] V7 fixed3 dry-run script
  - Evidence: `tools/scripts/phase2_family_ranking_dry_run.py` — 5-family 점수 계산 후 hierarchical RRF + 2-way baseline 동일 표 비교, 142.5s 실행.

- [x] TOP N 비교 산출물 작성
  - Evidence: `artifacts/phase2_family_ranking_measurement_20260519.md` + `.json`. 측정 결과: TOP 100/500/1000/2000/5000 평균 **-6.45pp** 손실 (baseline 16.61% baseline 사용 시).

- [x] unit test
  - Evidence: `tests/modules/test_services/test_queue_fusion_hierarchical.py` 11 tests passed. 후속 Phase C-격리 단계에서 marker 추가 예정.

**Reject 결정 (2026-05-19)**: RRF 는 ranker 가 동등한 검색기일 때 강함. PHASE2 5 family 는 역할·분포가 본질적으로 다름. voter 형식 통일 시 unsupervised 의 연속 분해능이 희석됨. 측정 -6.45pp 가 정확히 이걸 보여줌. supervised/transformer 활성화 시 재평가.

## Phase C-격리: experimental 표식 ✅
- [x] `compute_phase2_internal_rrf` docstring 갱신
  - Evidence: `src/services/queue_fusion.py` helper 상단 박스에 reject 사유·측정 산출물·거버넌스 출처·재평가 조건 모두 명시. EXPERIMENTAL 표식.

- [x] `pytest.mark.experimental_phase2_internal_rrf` marker 추가
  - Evidence: `tests/modules/test_services/test_queue_fusion_hierarchical.py` 에 `pytestmark = pytest.mark.experimental_phase2_internal_rrf` + 모듈 docstring 갱신. 11 tests 모두 marker 적용.

- [x] `pyproject.toml` marker 등록
  - Evidence: `[tool.pytest.ini_options].markers` 에 `experimental_phase2_internal_rrf` 추가. 검증: `uv run pytest -m "not experimental_phase2_internal_rrf"` → 11 deselected.

- [x] measurement md 상단에 reject 결정 박스 추가
  - Evidence: `artifacts/phase2_family_ranking_measurement_20260519.md` §0 에 reject 결정 박스 + 사용자 승인 문장 + 살린/격리 산출물 표 + 재평가 조건 추가.

## Phase D: overlay + lane membership (재정의) ✅
- [x] `Phase2CaseOverlay` 신규 필드 추가
  - Evidence: `src/services/phase2_case_contract.py` Phase2CaseOverlay 에 7개 필드 (family_contributions, top_family, coverage_breadth_q95, max_family_ecdf, max_evidence_tier, lane_membership, coverage_gap_families) 추가. 기존 `phase2_family_scores`/`phase2_adjusted_priority` 유지(하위 호환).

- [x] 6단 tie-break 함수 — primary RRF 동률 한정
  - Evidence: `apply_phase2_tie_break(primary_scores, overlays_by_case, total_amounts_by_case, strong_subdetector_count_by_case, near_tie_eps=1e-9)` 추가. near-tie 그룹 내부에서만 6단 ladder 적용. 가드 통과: near-tie 외 영역은 primary 순위 보존.

- [x] family score 집계 helper (overlay 부착)
  - Evidence: `build_phase2_case_overlays` 시그니처 확장 — `family_scores_by_case` + `family_ecdf_by_case` + `family_top_subdetectors_by_case` + `family_roles` + `family_q95_thresholds` 입력. evidence_tier YAML 을 통한 contribution 정렬 적용. inference service 의 row→case 집계 wiring 은 Phase E 에서 actual call site 와 함께 통합.

- [x] PHASE3 narrator prompt 가 새 필드 인용
  - Evidence: `src/llm/phase3_case_prompt.py::_case_input` 에 `phase2_family_contributions`, `phase2_top_family`, `phase2_coverage_breadth_q95`, `phase2_max_family_ecdf`, `phase2_max_evidence_tier`, `phase2_lane_membership`, `phase2_coverage_gap_families` 추가. 기존 `phase2_family_scores` 유지.

- [x] unit test — overlay 신규 필드 + tie-break 가드
  - Evidence: `tests/modules/test_services/test_phase2_case_contract.py` 신규 7 테스트 + 기존 8 테스트 모두 통과. `tests/modules/test_llm/test_phase3_case_prompt.py` 6 테스트 통과 (1건 보강 + 1건 신규).
  - 검증: `uv run pytest tests/modules/test_services/ tests/modules/test_llm/ tests/phase2_rulebase/ -q` → 503 passed, 1 skipped.

## Phase E: lane UI + overlay routing (재정의) ✅
- [x] family lane 정렬 helper
  - Evidence: `src/services/phase2_lane_sort.py` 신규 — `sort_lane`, `lane_summary`, `list_active_lanes`, `best_subdetector_tier` 4 helper. evidence_tier desc → ecdf desc → score desc 정렬. 12 unit tests passed.

- [x] dashboard family lane 컴포넌트 (별도 모듈로 분리)
  - Evidence: `dashboard/components/phase2_family_lanes.py` 신규 — `build_lane_summary_frame`, `build_lane_content_frame`, `render_lane_view`. 기존 `phase2_family_matrix.py` 보존 (100줄 모듈 룰 준수). 6 unit tests passed.

- [x] dashboard tab_phase2 lane selector 통합
  - Evidence: `tab_phase2.py::_render_phase2_lane_view` + `_resolve_phase2_overlays_from_state` + `_resolve_family_roles_from_snapshot` 추가. `_render_phase2_contract_views` 가 family_matrix + subdetector_grid + leaderboard + lane_view 순서로 렌더.

- [x] regression test — primary queue 보존
  - Evidence: `tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py` 3 tests — primary 2-way RRF score/rank 가 overlay 호출 / lane sort 호출 후에도 mismatch 0.

- [x] streamlit smoke
  - Evidence: `uv run python -c "import dashboard.app; import dashboard.tab_phase2"` → "import OK". 전체 dashboard regression 통과.

- 검증: `uv run pytest tests/modules/test_dashboard/test_tab_phase2.py tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py tests/modules/test_services/test_phase2_lane_sort.py tests/modules/test_dashboard/test_phase2_family_lanes.py -q` → 34 passed.

## Phase F: 거버넌스 lock + 문서 갱신 (재정의) ✅
- [x] PHASE2_GOVERNANCE_DESIGN.md 결정 8 추가
  - Evidence: `docs/PHASE2_GOVERNANCE_DESIGN.md` 결정 8 (8.0~8.9) — 결정 요지, 사용자 승인 문장, 측정 근거, RRF 범위 제한, family signal 4 경로, tie-break 가드 lock, family role 4 상태 임계, evidence_tier governance, 옵션 R/Z 정합, 산출물 인덱스. 결정 7 다음·부록 A 앞에 배치. 기존 결정 4~7 변경 없음.

- [x] PHASE2_INTERFACE_DESIGN.md §4.3.1/§4.4.1 보강
  - Evidence: §4.3.1 family lane 보조 view (lane × 정렬 기준 × 노출 조건 표) + §4.4.1 narrator family signal citation 8 필드 매핑 표 추가. 결정 3 옵션 Z lock 변경 없음.

- [x] V7_FIXED3_PHASE2 §6 보강
  - Evidence: §6 끝에 "family ranking 정책 (2026-05-19 lock)" subsection 추가 — primary queue / hierarchical RRF reject / family signal 노출 / 격리 산출물 / 측정 근거 / 거버넌스 출처 6행 표 + 양방향 교차 참조.

- [x] kpi_baseline.json Layer C c6 추가
  - Evidence: `tests/phase2_rulebase/kpi_baseline.json` c6_family_diagnostics_stability metric 추가 — SOFT_WARN, min_ratio 0.7, decision_link 인용. baseline 은 첫 production 학습 후 채움.

- [x] handoff 문서 작성
  - Evidence: `artifacts/sprint_phase2_family_ranking_handoff_20260519.md` — 9 절 (요약/승인/Phase 결과/pivot decision/살린 산출물/격리 산출물/governance lock/검증/후속 작업/plan 참조).

## Deployment Checklist (pivot 후 재정의) — 전체 완료
- [x] config/phase2_subdetector_tiers.yaml schema test 통과
- [x] Phase B family_diagnostics 3 metric helper + metadata pin helper 완료
- [x] Phase C measurement-only — hierarchical RRF -6.45pp 손실 측정 + reject 결정
- [x] Phase C-격리 — experimental marker + reject 사유 docstring
- [x] Phase D — Phase2CaseOverlay 신규 필드 (internal RRF 미포함) + 6단 tie-break 가드
- [x] Phase D — PHASE3 narrator prompt 가 family_contributions 인용
- [x] Phase E — dashboard lane UI + tier badge + coverage gap 배지
- [x] Phase E — primary queue mismatch 0 regression test
- [x] Phase F — PHASE2_GOVERNANCE_DESIGN.md 결정 8 lock + tie-break 가드 문구
- [x] Phase F — kpi_baseline.json Layer C family_diagnostics_stability metric
- [x] Phase F — handoff 문서 작성
