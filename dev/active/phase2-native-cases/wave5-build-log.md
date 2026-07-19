# PHASE2 Native Cases — Wave 5 Build Log

S5 단계 산출물 — IC matcher metadata 확장 + IC case builder.

## Agent I — Phase A (IC matcher pair_artifact) (2026-05-27)

- 확장 파일:
  - src/detection/intercompany_matcher.py
    - IntercompanyPairArtifact dataclass + build_intercompany_pair_artifact + 4종 추출 헬퍼
      (_extract_reciprocal_pairs / _extract_mismatch_pairs / _extract_unmatched_rows /
      _extract_candidate_pairs) 신규 (약 +280 LoC, 기존 도메인 정당화 docstring 보강 포함)
    - _build_result 에 keyword-only ``match_df`` 추가 + metadata key ``ic_pair_artifact`` 부착
    - _empty_result 에도 빈 artifact dict 부착 (builder graceful fallback 호환)
  - tests/modules/test_detection/test_intercompany_matcher_pair_artifact.py (+8 테스트, +231 LoC)
- 신규 helper:
  - `_ic_json_safe` (duplicate `_json_safe` 패턴 정합)
  - `_ic_safe_str` / `_ic_safe_float` (NaN/inf 방어)
  - `_empty_ic_pair_artifact` (`_empty_result` 경로용)
  - `IntercompanyMatcher._safe_match_df` (Exception graceful fallback)
- 기존 IC matcher 출력 회귀: 0건 (`tests/modules/test_detection/` 1313 통과 + 3 skipped, 약 2분 16초)
- pytest Phase A: 8/8 통과
- 도메인 정당화: ISA 550 ¶A20 + PCAOB AS 2401 §B7 / .A6 (3) 모듈 docstring 인용
- 주요 결정 / 이슈:
  - reciprocal_pairs 추출 시 `ic_reciprocal_flow_prob > 0` 만 필터 (structural pass 가
    이미 score > 0 조건). 추가 임계는 surface 단에 가하지 않고 Phase B Gate 가
    ic_role 별로 판단 — invariant #54 의 책임 분리.
  - mismatch_pairs 의 right_index 는 counterpart row 식별이 불가하므로 left_index 와
    동일하게 self 표기 (IC02 row-level score 가 group-level mismatch 의 row 투영이라
    counterpart row 가 명시되어 있지 않은 도메인 한계). Phase B 빌더가 동일 label
    중복 detect 후 row_refs 를 단일 ref tuple 로 강등 처리.
  - candidate_pairs 는 운영 가시화 / debug 용 — Phase B Gate 가 차단 (timing-only weak).
  - artifact entry 의 모든 index 는 `_ic_json_safe` 통과 (invariant #53).
  - `_build_result` 시그니처에 keyword-only `match_df=None` 추가 — 외부 API 가 아니라
    내부 detect → _build_result 호출 한 곳만 영향. 인자 미전달 시 `_safe_match_df` 가
    한번 더 재계산 (방어용, 실제 detect 경로는 항상 전달).

## Agent I — Phase B (IC case builder) (2026-05-27)

- 신규 파일:
  - src/services/phase2_intercompany_case_builder.py (약 230 LoC)
  - tests/modules/test_services/test_phase2_intercompany_case_builder.py (+12 테스트, 약 290 LoC)
- pytest Phase B: 12/12 통과 (`uv run pytest tests/modules/test_services/test_phase2_intercompany_case_builder.py -v` 0.67s)
- Gate: reciprocal_flow + amount_mismatch only — unmatched_rows / candidate_pairs (timing-only) 단독은 차단 (invariant #54)
- evidence_tier 매핑: reciprocal_flow → strong / amount_mismatch → moderate
- evidence_signature: `f"ic_role={role}"` 만 — raw 금액 / symmetry / ratio 절대 미포함 (invariant #55)
- ruff format/check: pass/pass (test 파일 import 순서 1건 --fix 로 자동 정리)
- 주요 결정 / 이슈:
  - reciprocal_flow case 의 unit_type 도 "pair" 유지 (invariant #54 와 일관). artifact entry
    가 단일 row_index 이므로 row_refs 는 단일 ref tuple — Phase2CaseSet.iter_all_cases_sorted
    가 case_id 기반 정렬이라 unit_type 표기 통일이 더 중요.
  - mismatch_pairs 의 left/right index 가 같으면 row_refs duplicate 제거 → 단일 ref tuple 로
    강등 (Phase2RowRef contract 정합).
  - PHASE1 prior 접근 0건 (invariant #56) — detection_result + df + batch_id 만 사용.
  - phase1_case_refs = () default (invariant #57, linker S4 가 부착).
  - amount_symmetry 필드는 reciprocal_flow 에 직접 사용 (artifact symmetry 그대로),
    amount_mismatch 에는 ratio (작은쪽/큰쪽) 를 amount_symmetry 필드에 매핑 — 도메인적으로
    "양 금액 일치 정도" 의미 통일.
  - counterparty_pair 는 trading_partner 우선, fallback 으로 company_code 사용. 두 컬럼
    모두 부재면 None.

## 전체 통합 확인

- `uv run pytest tests/modules/test_services/ tests/modules/test_detection/ tests/modules/test_models/test_phase2_row_ref.py`
  → **1888 passed, 3 skipped** in 146.85s
- 신규 테스트: Phase A 8 + Phase B 12 = **20개 추가**
- 회귀: 0건 (S1~S4.next.2 산출물 / 기존 IC matcher / 다른 detector 모두 무변경)

## Wave 5 Followup — reciprocal 양쪽 row + MultiIndex 안전 lookup (2026-05-27)

reviewer 지적 (High #1 + Medium #2) 대응. invariant #58 / #59 신규 lock.

### Fix High — reciprocal case 가 receivable + payable 양쪽 row 보존 (invariant #58)

- `src/detection/intercompany_matcher.py::_extract_reciprocal_pairs`
  - entry schema 확장: `receivable_indices` / `receivable_positions` / `payable_indices` /
    `payable_positions` 4종 list 추가. doc 안 rec/pay 양쪽 모두의 label + 0-based row
    position 보존 (np.flatnonzero(mask.to_numpy())).
  - `row_index` / `row_position` 도 legacy compat 으로 유지 (rec 우선, 없으면 pay 의 첫 row).
  - 한쪽이라도 row 가 없으면 `continue` (structural pass 가 mask 단위라 양쪽 필수).
- `src/services/phase2_intercompany_case_builder.py::_build_reciprocal_case`
  - rec_indices + pay_indices 양쪽 모두를 `row_refs` 로 채움 (rec 먼저, pay 나중).
  - counterparty_pair 는 receivable 첫 row + payable 첫 row 기준.
  - 구 schema (`row_index` 만 보유) 는 legacy fallback — `_make_ref_from_position`
    (`row_position` 있으면) 또는 `_make_ref` (label-only).
- 도메인 효과: "무엇과 무엇이 reciprocal" 답 가능 + PHASE1 cross-ref (S4 linker) 가
  반대쪽 row 의 hit 도 회수 가능.

### Fix Medium — MultiIndex/tuple label 환경에서 position 직접 사용 (invariant #59)

- `src/detection/intercompany_matcher.py` 4종 추출 함수에 position 필드 추가:
  - `_extract_reciprocal_pairs` → `receivable_positions` / `payable_positions` / `row_position`
  - `_extract_mismatch_pairs` → `left_position` / `right_position`
  - `_extract_unmatched_rows` → `row_position`
  - `_extract_candidate_pairs` → `left_position` / `right_position`
  - position 산출은 모두 `np.flatnonzero(mask.to_numpy())` — boolean mask 의 안전 변환.
- `src/services/phase2_intercompany_case_builder.py`
  - 신규 helper `_make_ref_from_position(df, *, position, index_label)` — 기존
    `_make_ref(df, label)` 는 legacy fallback 으로 유지.
  - `_build_reciprocal_case`: 새 schema (양쪽 row position list) 우선, 구 schema 는
    `row_position` 있으면 position-based / 없으면 label-based graceful fallback.
  - `_build_mismatch_case`: `left_position` + `right_position` 있으면 position 기반,
    없으면 `_make_ref(df, label)` legacy fallback (test_evidence_signature_*
    inline artifact 회귀 보장).
- 도메인 효과: `_ic_json_safe` 가 tuple → str 평탄화하는 환경에서도 builder 가
  `df.iloc[position]` 으로 안전 lookup → IC case 가 조용히 0건 되는 회귀 차단.

### 회귀 가드 +6 (Phase A 3 + Phase B 3)

Phase A (`tests/modules/test_detection/test_intercompany_matcher_pair_artifact.py`):
- `test_reciprocal_pairs_include_both_receivable_and_payable_row_lists`
  — entry 가 receivable_indices/positions + payable_indices/positions + legacy compat 동시 보유 검증.
- `test_each_artifact_entry_includes_row_position`
  — reciprocal/mismatch/candidate/unmatched 4종 모두에 row_position 또는 left/right_position 검증.
- `test_reciprocal_extraction_works_with_multiindex_df`
  — MultiIndex (doc, line) df 에서도 reciprocal entry 가 정상 추출 + position 정보 유효.

Phase B (`tests/modules/test_services/test_phase2_intercompany_case_builder.py`):
- `test_reciprocal_case_includes_both_receivable_and_payable_row_refs`
  — single-line rec + single-line pay doc 에서 row_refs 길이 2 + 양쪽 position 모두 포함.
- `test_reciprocal_case_with_multiline_doc_includes_all_rows`
  — rec 2 line + pay 2 line doc 에서 row_refs 길이 4 + rec→pay 순서.
- `test_intercompany_case_resolves_multiindex_label_via_position`
  — MultiIndex df + str 평탄화된 index_label 에서 reciprocal + mismatch 양쪽 case 정상 생성.

기존 fixture 갱신: `_reciprocal_artifact` / `_mismatch_artifact` 가 새 schema 사용,
`_legacy_reciprocal_artifact` helper 추가 (구 schema graceful fallback 검증 보조).

### 합계

- 수정 파일 4개 — 회귀 가드 +6 (총 Phase A 11 + Phase B 15 = 26 테스트)
- `uv run pytest tests/modules/test_services/ tests/modules/test_detection/ tests/modules/test_models/test_phase2_row_ref.py`
  → **1894 passed, 3 skipped** in 142.06s (이전 baseline 1888 → +6 정확히 신규 회귀 가드만).
- ruff format/check: 4 files unchanged / all checks passed.
- 신규 invariant: #58 (reciprocal 양쪽 row 보존), #59 (artifact position 필드 + builder 안전 lookup).
- IC matcher row 단위 score / details / row_sidecar / probabilistic_reconciliation /
  reciprocal_flow metadata 변경 0건 (invariant #52 회귀 보장).
- 주요 결정 / 이슈:
  - 양쪽 row 있는 entry 의 `row_refs` 순서는 `(*rec_refs, *pay_refs)` 로 고정 — 후속
    linker / family overlay 가 rec/pay 분리하지 않으므로 순서 invariant 가 case_id
    canonical_refs 의 hash 일관성에 직접 영향 (변경 시 case_id 변동).
  - mismatch_pair 의 `right_position` 은 left 와 동일 (counterpart row 식별 불가) —
    Phase A 의 self-pair 표기 정합 유지. row_refs duplicate 검출 시 단일 ref tuple
    강등 로직은 그대로.
  - `_make_ref` 는 deprecated 가 아니라 legacy fallback 으로 명시 유지 — 구 호출자
    (artifact entry 에 position 없음) 보호.
  - MultiIndex test 는 `_ic_json_safe` 가 tuple → str 평탄화하는 실제 시나리오를 직접
    재현 (label 은 "('DOC100', 0)" str, position 은 정수). builder 가 position 만
    사용하므로 label 매칭은 불필요.
