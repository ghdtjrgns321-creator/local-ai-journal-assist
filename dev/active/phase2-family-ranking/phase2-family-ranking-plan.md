# Phase2 Family Ranking - Strategic Plan

## Executive Summary
PHASE2 5-family score 결합 ranking 정책을 lock한다.

**핵심 결정 (2026-05-19, Phase C 측정 후 pivot)**:
- RRF는 폐기하지 않는다. 다만 적용 범위를 **PHASE1 ↔ VAE 같은 전역 연속 ranker 결합**으로 제한한다.
- **PHASE2 내부 family 간 hierarchical RRF는 V7 fixed3 Phase C 측정에서 ranking 희석(-6.45pp 평균)이 확인되어 production 도입을 중단한다.**
- family signal은 **lane, tie-break, evidence overlay, narrator citation**으로 사용한다.

본 작업은 위 결정을 lock하고, evidence_tier governance·family diagnostics·explainable contribution overlay·lane UI를 도입한다. primary global queue는 현 운영(PHASE1 composite ↔ VAE ECDF 2-way RRF k=60)을 그대로 유지하며 변경 0이다.

## Current State
- `src/services/queue_fusion.py`: RRF k=60 N-way dict-API 지원, 호출처는 2-way (phase1_composite + phase2_unsupervised) 한정
- `src/services/phase2_case_contract.py`: `Phase2CaseOverlay.phase2_family_scores` dict 노출, `_adjusted_priority`는 mean 단순 결합
- `src/services/phase2_inference_service.py`: family score를 case_id 단위로 집계하는 코드 없음 → overlay는 항상 빈 dict
- `dashboard/components/phase2_family_matrix.py`: family별 고유 metric(`ECDF q95 count`, `burst_detection_rate` …) 표시, 비교 가능 ranking dimension 부재
- `dashboard/components/phase2_subdetector_grid.py`: 13 sub-detector hit count 표시
- `artifacts/phase2_family_correlation_matrix_20260519.md`: Spearman max\|ρ\|=0.21 측정, "5-way RRF as-is" 권고하나 hit density·score granularity 변수 미반영
- `docs/PHASE2_GOVERNANCE_DESIGN.md`: 결정 4~7 lock 완료, family ranking 결합 정책은 미정의
- `docs/PHASE2_INTERFACE_DESIGN.md`: 결정 3 옵션 Z (independent queue) lock, PHASE2 internal ranking은 별도 결정 필요
- `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` §6: scenario × family 보완성 표는 있으나 결합식 부재

## Proposed Solution
**RRF는 적용 범위를 PHASE1 ↔ VAE 전역 결합으로 제한, PHASE2 family는 lane + overlay + tie-break으로 표현한다.**

| Layer | 정의 | 상태 |
|---|---|---|
| L0 분포 진단 | family별 `row_nonzero_rate`, `rank_resolution`, `top_tail_resolution` 3 metric 측정 → `training_report.json` pin | 살림 (Phase B 완료) |
| L1 family role 자동 판정 | near-dormant / active / coarse / tail-only 4 상태. role은 **lane visibility 결정** 용도 (ranking voter 아님) | 살림, 의미만 전환 |
| L2 PHASE2 internal hierarchical RRF | active-ranker voter + coarse-booster conditional 가산 | **❌ V7 fixed3 -6.45pp 측정으로 reject, experimental 격리** |
| L3 PHASE1 ↔ PHASE2 final RRF | 기존 2-way k=60 (`phase1_composite` ↔ `phase2_unsupervised`) 그대로 | **변경 0** (현 운영 유지) |
| L4 tie-break 6단 | rrf_score → coverage_breadth_q95 → strong_subdetector_count → max_family_ecdf → max_subdetector_evidence_tier → \|total_amount\| | 살림, **primary RRF 동률 한정** |
| L5 evidence_tier lock | `config/phase2_subdetector_tiers.yaml`, 기준서 또는 분포 metric 출처 필수 | 살림 (Phase A 완료) |
| L6 explainable output | `Phase2CaseOverlay`에 `family_contributions`, `top_family`, `coverage_breadth`, `lane_membership`, `coverage_gap_families` 부착 | 신규 (Phase D 재정의) |
| L7 family lanes | dashboard에 family별 보조 큐, 각 lane은 해당 family score로 정렬. near-dormant는 "데이터 미보유" 배지 | 신규 (Phase E 재정의) |

ECDF는 RRF 입력이 아니라 confidence·tie-break·dashboard·LLM citation 표준화 보조 점수.

### Tie-break 가드 (governance lock 필수)

> **Tie-break ladder는 primary RRF의 동률 또는 near-tie 보조 정렬에만 사용하며, primary queue의 기본 순위를 뒤집는 별도 weighted score로 사용하지 않는다.**

이 가드가 없으면 6단 ladder가 새 ranking model로 변질될 수 있다. 구체적으로:
- tie-break는 동률 doc 그룹 내부에서만 적용.
- "near-tie" 정의: primary RRF score 차이 ≤ 1e-9 (float 정밀도) — 그 외는 primary score 그대로.
- ladder는 weight 가중합이 아니라 lexicographic 비교만 사용.

### Lane 구조

| Lane | 정렬 기준 | 노출 조건 |
|---|---|---|
| primary | PHASE1+VAE 2-way RRF score | 항상 노출 (감사 main queue) |
| duplicate | evidence_tier desc → family ECDF desc | duplicate family active 시 |
| relational | evidence_tier desc → family ECDF desc | relational family active 시 |
| timing | family ECDF desc | timeseries family active 시 (coarse-booster여도 lane으로는 의미) |
| intercompany | family ECDF desc | active 시 / near-dormant면 "데이터 미보유 배지" |

lane 내부 정렬에는 RRF를 쓰지 않는다 — 동일 family 내 sub-detector는 evidence_tier YAML이 출처 lock된 분류를 제공하므로 categorical sort가 자연스럽다.

## Implementation Phases

### Phase A: L5 evidence_tier YAML + schema test (0.5 day)
**Goal**: 14 sub-detector(unsupervised VAE 1 + timeseries 2 + relational 4 + duplicate 4 + intercompany 3) 각각의 evidence_tier를 기준서·분포 metric 근거와 함께 단일 출처 파일에 lock.

**Tasks**:
- [ ] `config/phase2_subdetector_tiers.yaml` 작성 - File: `config/phase2_subdetector_tiers.yaml` - Size: M
- [ ] tier 부여 근거(PCAOB AS 2401·ISA 240·V7 분포 측정값) 출처 컬럼 강제 - File: `config/phase2_subdetector_tiers.yaml` - Size: S
- [ ] `tests/phase2_rulebase/test_subdetector_tiers_schema.py` schema test 작성 - File: `tests/phase2_rulebase/test_subdetector_tiers_schema.py` - Size: M
- [ ] `src/services/subdetector_tiers.py` loader + 13 sub-detector 누락 검증 - File: `src/services/subdetector_tiers.py` - Size: S
- [ ] D044 PR 템플릿에 tier 변경 fitting-risk check 추가 - File: `docs/DECISION.md` - Size: S

### Phase B: L0 분포 진단 metric + training_report pin (0.5 day)
**Goal**: family score 분포 진단 3 metric을 training 시점 계산 후 `training_report.json` metadata에 pin.

**Tasks**:
- [ ] `src/services/phase2_family_diagnostics.py` 신규 - 3 metric 계산 함수 - File: `src/services/phase2_family_diagnostics.py` - Size: M
- [ ] `phase2_training_service` training step 종료 직전에 metric 측정 + report metadata 추가 - File: `src/services/phase2_training_service.py` - Size: M
- [ ] `Phase2TrainingReport` schema에 `family_diagnostics` 필드 추가 - File: `src/services/phase2_training_models.py` - Size: S
- [ ] unit test - File: `tests/modules/test_services/test_phase2_family_diagnostics.py` - Size: M

### Phase C: hierarchical RRF measurement (완료, reject 결정)
**Goal**: hierarchical RRF helper + V7 fixed3 measurement-only 비교 산출. **결과: reject.**

**산출물**:
- `src/services/queue_fusion.py::compute_phase2_internal_rrf` (helper)
- `tests/modules/test_services/test_queue_fusion_hierarchical.py` (11 tests passed)
- `tools/scripts/phase2_family_ranking_dry_run.py` (measurement script)
- `artifacts/phase2_family_ranking_measurement_20260519.md` — TOP 100~5000 평균 -6.45pp 손실 측정

**결정**: V7 fixed3 측정에서 hierarchical RRF 가 2-way baseline 보다 평균 -6.45pp 손실. 원인은 unsupervised 의 연속 분포 변별력이 duplicate(binary cap) / timeseries(2값 이산) / intercompany(99.997% 0) 와 같은 voter 형식으로 묶이면서 희석됨. supervised/transformer 등 연속·전역 ranker 가 추가 활성화될 때 재평가.

### Phase C-격리: experimental 표식 (0.25 day)
**Goal**: Phase C 산출물 삭제 대신 experimental 격리 + reject 사유 명시. 미래 재평가 근거 보존.

**Tasks**:
- [ ] `compute_phase2_internal_rrf` docstring 에 V7 fixed3 reject 사유 + 재평가 조건 명시 - File: `src/services/queue_fusion.py` - Size: S
- [ ] `test_queue_fusion_hierarchical.py` 모듈에 `pytest.mark.experimental_phase2_internal_rrf` marker - File: `tests/modules/test_services/test_queue_fusion_hierarchical.py` - Size: S
- [ ] `pyproject.toml` marker 등록 (warning 차단) - File: `pyproject.toml` - Size: S
- [ ] measurement md 상단에 "reject 결정" 박스 추가 - File: `artifacts/phase2_family_ranking_measurement_20260519.md` - Size: S

### Phase D: overlay + lane membership (1 day) — 재정의
**Goal**: `Phase2CaseOverlay` 에 family_contributions + lane_membership 부착, primary RRF 동률 한정 6단 tie-break 적용. **internal RRF 필드 미포함.**

**Tasks**:
- [ ] `Phase2CaseOverlay` 에 `family_contributions: list[dict]`, `top_family: str`, `coverage_breadth: int`, `lane_membership: list[str]`, `coverage_gap_families: list[str]` 부착 - File: `src/services/phase2_case_contract.py` - Size: M
- [ ] 6단 tie-break 함수 `apply_phase2_tie_break(primary_scores, overlays, near_tie_eps=1e-9)` 동률·near-tie 한정 동작 - File: `src/services/phase2_case_contract.py` - Size: M
- [ ] family score 를 case_id 단위로 집계 (family score Series → case overlay) - File: `src/services/phase2_inference_service.py` - Size: M
- [ ] PHASE3 narrator prompt 가 family_contributions + top_family + coverage_breadth + lane_membership 인용 - File: `src/llm/phase3_case_prompt.py` - Size: S
- [ ] unit test (overlay 신규 필드 + tie-break 가드 + family score 집계) - File: `tests/modules/test_services/test_phase2_case_contract.py` - Size: M

### Phase E: lane UI + overlay routing (1 day) — 재정의
**Goal**: dashboard 에 family lane 분리 + tier badge 노출, near-dormant 는 coverage gap 배지. **primary queue 변경 0.**

**Tasks**:
- [ ] `phase2_family_matrix.py` 에 lane 표시 컴포넌트 추가, family별 active/coarse/near-dormant 배지 + evidence_tier 카운트 - File: `dashboard/components/phase2_family_matrix.py` - Size: M
- [ ] family lane 내부 정렬 (`evidence_tier desc → family ECDF desc`) helper - File: `src/services/phase2_case_contract.py` 또는 신규 `phase2_lane_sort.py` - Size: M
- [ ] dashboard tab_phase2 에 lane selector + lane content - File: `dashboard/tab_phase2.py` - Size: M
- [ ] regression test — primary queue 순위가 lane 도입 후에도 보존되는지 - File: `tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py` - Size: M
- [ ] streamlit smoke import 통과 - File: `dashboard/tab_phase2.py` - Size: S

### Phase F: 거버넌스 lock + 문서 갱신 (0.5 day) — 재정의
**Goal**: PHASE2_GOVERNANCE_DESIGN.md 결정 8 = "PHASE2 internal RRF reject + family signal lane/overlay/tie-break 한정", tie-break 가드 문구 lock.

**Tasks**:
- [ ] 결정 8 추가 — RRF 적용 범위 제한 + Phase C 측정 인용 + tie-break 가드 + lane 정책 - File: `docs/PHASE2_GOVERNANCE_DESIGN.md` - Size: M
- [ ] PHASE2_INTERFACE_DESIGN.md §4.3/§4.4 보강 — lane 추가, family_contributions citation - File: `docs/PHASE2_INTERFACE_DESIGN.md` - Size: S
- [ ] V7_FIXED3_PHASE2 §6 끝에 family ranking 정책 + Phase C measurement 인용 - File: `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md` - Size: S
- [ ] kpi_baseline.json Layer C 에 family_diagnostics 안정성 metric 추가 (baseline = Phase B 측정값) - File: `tests/phase2_rulebase/kpi_baseline.json` - Size: S
- [ ] handoff 문서 작성 (Phase C reject 결정 + 살린 산출물 명시) - File: `artifacts/sprint_phase2_family_ranking_handoff_20260519.md` - Size: S

## Risk Assessment
- **High → 현실화 후 mitigation 적용**: ~~V7 fixed3 측정에서 hierarchical RRF가 baseline 보다 낮을 수 있다~~ → **실제로 -6.45pp 측정**. Mitigation: hierarchical RRF reject + lane/overlay pivot. 미래 supervised/transformer 활성화 시 재평가.
- **High**: evidence_tier 부여가 사후에 truth recall 손잡이로 변질될 수 있다. Mitigation: Phase A에서 출처 컬럼 강제 + schema test, D044 PR 템플릿에 fitting-risk check 추가.
- **Medium**: family role classification이 inference 간 진동할 수 있다. Mitigation: classification은 training 시점에 pin, inference는 그대로 사용. 재분류는 재학습 trigger로만. Pivot 후 role은 ranking voter가 아니라 lane visibility 결정에만 영향 → 영향 범위 축소.
- **Medium**: tie-break ladder 가 새 ranking model 로 변질될 수 있다. Mitigation: governance lock 문구로 primary RRF 동률·near-tie 한정 적용 명시 + `apply_phase2_tie_break` unit test 가 `near_tie_eps=1e-9` 외 영역에서 primary 순위를 변경하지 않음을 검증.
- **Medium**: PHASE3 narrator citation 계약 변경이 LLM 출력에 영향을 줄 수 있다. Mitigation: Phase D는 신규 필드 추가만 하고 기존 `phase2_family_scores` dict는 그대로 유지(하위 호환).
- **Low**: dashboard family lane UI 가 너무 복잡해질 수 있다. Mitigation: 기본 화면은 primary queue, lane은 expander 또는 별도 tab.

## Success Metrics
- `config/phase2_subdetector_tiers.yaml`이 14 sub-detector 모두 cover하고 schema test 통과 ✅
- `family_diagnostics` 3 metric helper + metadata pin helper 완료, unit test 통과 ✅
- V7 fixed3 hierarchical RRF measurement-only 산출 + reject 결정 lock ✅
- Phase D 완료 후 `Phase2CaseOverlay`에 family_contributions + lane_membership 부착, PHASE3 narrator citation 가능
- Phase E 완료 후 dashboard 에 family lane + tier badge + coverage gap 배지 노출
- Phase F 완료 후 PHASE2_GOVERNANCE_DESIGN.md 결정 8 lock + tie-break 가드 문구 lock
- primary PHASE1+VAE 2-way RRF queue 의 순위가 lane/overlay 도입 후에도 mismatch 0 (regression test)

## Dependencies
- Code:
  - `src/services/queue_fusion.py`
  - `src/services/phase2_case_contract.py`
  - `src/services/phase2_training_service.py`
  - `src/services/phase2_training_models.py`
  - `src/services/phase2_inference_service.py`
  - `src/pipeline.py`
  - `src/llm/phase3_case_prompt.py`
  - `dashboard/components/phase2_family_matrix.py`
- Docs:
  - `docs/PHASE2_GOVERNANCE_DESIGN.md`
  - `docs/PHASE2_INTERFACE_DESIGN.md`
  - `docs/DETECTION_RESULTS_MANIPULATION_V7_FIXED3_PHASE2.md`
  - `docs/DECISION.md`
- External:
  - `artifacts/phase1_manipulation_v7_fixed3_case_input.pkl` (Phase C dry-run input)
  - `data/companies/_ci_baseline/engagements/2026/models/phase2_unsupervised/v1/model_bundle.pt`
  - `tests/phase2_rulebase/kpi_baseline.json` (Phase F Layer C 갱신)
