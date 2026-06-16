# PHASE2 Unsupervised Explainability Surface — Task Checklist

## Progress Summary
14 / 14 tasks complete ✅ (2026-05-25)

## Lock Conditions (재확인)
- scores / rule_flags / family_score / phase2 queue / PHASE1 priority 변경 금지 ✅
- Top-K / reason tag 는 explanation payload only — score input 진입 금지 ✅
- narrator / dashboard: fraud / violation / confirmed / 위반 확정 금지 ✅
- 미매핑 feature → `feature_pattern_outlier` ✅
- 매칭 순서: 정확 → prefix → contains ✅
- C (stability), E (IF dead path) 본 sprint out of scope ✅

## Phase A: Reason tag config + loader ✅
- [x] `config/unsupervised_reason_tags.yaml` 작성 — 7개 매핑 + fallback
- [x] `src/services/unsupervised_reason_tags.py` 신규 — loader + `resolve_tag()` 매칭
- [x] `tests/modules/test_services/test_unsupervised_reason_tags.py` — 정확/prefix/contains/fallback 회귀 (11 passed)

## Phase B: Aggregator 에 explanation_features 전파 ✅
- [x] `src/services/phase2_case_family_aggregator.py` —
  `_unsupervised_explanation_features_for_case` helper 추가, unsupervised
  result 의 details (ML02_top_feature_*) 를 case row max-contrib 으로 집계
- [x] aggregator `build_phase2_case_family_overlay_inputs` 결과에
  `family_explanation_features_by_case` 추가
- [x] `src/services/phase2_case_contract.py` —
  `build_phase2_case_overlays(family_explanation_features_by_case=…)` 시그니처
  확장, `_attach_explanation_features` 가 unsupervised entry 에
  `evidence_type=statistical_outlier` + `explanation_features` 부착
- [x] call site wiring: `src/pipeline.py::_build_phase2_case_overlays`,
  `src/services/phase2_inference_service.py::_attach_phase2_case_overlays`
- [x] `tests/modules/test_services/test_phase2_case_family_aggregator.py` —
  explanation_features 전파 + 빈 details fallback + unknown feature 회귀 (12 passed, 신규 3건)

## Phase C: Narrator language guard ✅
- [x] `src/llm/phase3_case_prompt.py::phase3_fact_grounding_system_prompt` —
  unsupervised guard 문장 추가 (통계적 이상치 한정, fraud/violation/confirmed
  / 위반 확정 / 부정 확정 / 오류 확정 금지)
- [x] `_case_input` payload 에 `phase2_unsupervised_explanation` 키 추가 —
  family_contributions 의 unsupervised entry 에서 explanation_features 추출
- [x] `tests/modules/test_llm/test_phase3_case_prompt.py` — system prompt 가드
  문장 회귀 + payload 키 회귀 (9 passed, 신규 3건)

## Phase D: 회귀 검증 ✅
- [x] `uv run pytest tests/modules/test_services/test_unsupervised_reason_tags.py -q` → 11 passed
- [x] `uv run pytest tests/modules/test_services/test_phase2_case_family_aggregator.py -q` → 12 passed
- [x] `uv run pytest tests/modules/test_services/test_phase2_case_contract.py -q` → 23 passed
- [x] `uv run pytest tests/modules/test_llm/test_phase3_case_prompt.py -q` → 9 passed
- [x] `uv run pytest tests/modules/test_pipeline/test_phase2_lane_overlay_preservation.py -q` → 3 passed (primary RRF mismatch 0)
- [x] `uv run pytest tests/modules/test_services/test_phase2_inference_service.py -q` → 27 passed
- [x] `uv run ruff check` modified files → All checks passed

**총 합계**: 본 작업 범위 회귀 85 tests passed, mismatch/score 변경 0건.

## 사전 working tree 변경과의 분리 (참고)
- `dashboard/tab_phase2.py` 는 본 세션 시작 시점에 이미 3,526 줄 변경 상태였음.
  관련 `test_tab_phase2.py` 의 reference/source_status 7건 실패는 본 작업과
  무관한 사전 미완성 변경 때문. 본 작업의 lock 조건 (score / 순위 / primary
  queue 무변경) 은 lane_overlay_preservation regression 으로 보장.
