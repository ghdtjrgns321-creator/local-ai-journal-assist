# wave4 build log (S4 — phase1↔phase2 cross-reference linker)

## Agent F — Phase1↔Phase2 Linker (2026-05-27)
- 생성 파일:
  - src/services/phase2_case_phase1_linker.py (129 LoC)
  - tests/modules/test_services/test_phase2_case_phase1_linker.py (407 LoC, 테스트 15개)
- 테스트 케이스: 15 (v7-plan S4 명시 테스트명 그대로 사용)
- pytest: PASS (15/15) — `uv run pytest tests/modules/test_services/test_phase2_case_phase1_linker.py -v` 0.67s
- ruff format/check: pass/pass (test 파일 import 순서 1건 --fix 로 자동 정리)
- 주요 결정 / 이슈:
  - Δ19 lazy two-pass inverse index 알고리즘 그대로 구현. PHASE1 hits 1회 순회로 O(H+R).
  - empty short-circuit 시 `case_set is result.case_set` 동일 객체 반환 → `with_phase1_refs` 호출 자체를 생략해 불필요한 Phase2CaseSet 재구성 비용 제거. invariant #35 (linked=True 유지) 는 case_set 이 비어 있을 때 `Phase2CaseSet().linked` 가 default False 라 short-circuit 분기에서는 적용 안 됨 — 단, 비어 있는 case_set 은 어차피 후속 surface 가 무시하므로 안전.
  - DuplicateCase left_ref / right_ref 가 row_refs 와 중복되어도 set 기반 inverse index 라 idempotent 자연 만족 (invariant #38).
  - phase1_case_refs 정렬은 set → `tuple(sorted(...))` 한 곳에서만 수행, with_phase1_refs 헬퍼 내부에서도 재정렬되지만 결과 동일 (invariant #36).
  - Phase2RowRef.__post_init__ canonical prefix 검증 때문에 테스트 fixture 가 raw int 대신 `f"i:{pos}"` 문자열을 직접 구성 — Phase2RowRef 본체에 의존하지 않고 prefix 규약만 따른다.
  - `_FAMILY_FIELD_NAMES` 는 phase2_case.py 의 동명 상수가 private 라 복제. prefix 추가/변경 시 양쪽 동기화 필요 (Phase2RowRef._CANONICAL_PREFIXES 와 동일 패턴).

## Wave 4 Followup — stale phase1_case_refs reset + MVP 범위 lock (2026-05-27)

### Fix A (High) — stale phase1_case_refs 잔존 차단
- 증상: 이전 구현이 매칭된 case 만 `refs_by_case_id` 에 넣었고, `Phase2CaseSet.with_phase1_refs` 는 dict 에 키 없는 case 의 기존 refs 를 보존 → 재호출 시 stale refs 남음.
  예: p1_alpha 로 link 후 phase1 이 비거나 position 이 사라진 상태로 재호출 → 실제 매칭 0 인데 ("p1_alpha",) 가 계속 남아 UI / linked hash / store 에 잘못된 cross-reference.
- 수정: Pass 3 의 `refs_by_case_id` 에 **모든 case 의 phase2_case_id 를 키로 포함**. 매칭 0 case 는 빈 tuple `()` 명시. `with_phase1_refs` 가 모든 case 에 새 refs 적용.
- 회귀 가드 (+3 테스트):
  - `test_linker_resets_stale_refs_when_phase1_becomes_empty` (phase1 empty 재호출)
  - `test_linker_resets_stale_refs_when_phase1_positions_change` (position 모두 이동 → 매칭 0)
  - `test_linker_preserves_match_for_some_resets_others` (mixed transition)

### Fix B (Medium) — MVP 사용 범위 명시 lock
- 증상: position-only matching 이 store load / df.sort_values / reset_index / multi-company concat 후 잘못된 PHASE1 case 와 매칭 가능. 그러나 v7-plan S4 섹션에 "S4 완료" 로 두고 pipeline attach 까지 진행하면 production reload 안전성이 깨짐.
- 수정: 모듈 docstring 에 **MVP 사용 범위 lock** 섹션 추가.
  - 사용 허용: 동일 in-memory df 위에서 PHASE1 / PHASE2 가 같은 batch 안에서 즉시 cross-reference.
  - 사용 금지: store reload, df 변형, partition / filter 입력 차이.
  - **pipeline attach (run_phase2_inference 통합) 는 S4.next 완료 전까지 금지** — position-only linker 가 production 경로에 들어가면 reload 안전성이 깨진다.
- 후속: S4.next 에서 label primary / doc_line fallback + row_ref_map.jsonl 활용으로 reload 안전성 확보.

### 합계 (S1 + S2 + S3 + S4 + 모든 Followup)
- 신규 단위 테스트: 503 (이전 500 + Fix A 회귀 3)
- 전체 services + models suite: 503/503 통과 (회귀 0)
- ruff format / check: pass
- stale refs / pipeline attach 차단 정책 lock

## Wave 4 Followup 2 — store manifest ↔ S4 capability 정합 (2026-05-27)

### 증상
`save_phase2_case_set()` 의 `key_mode` default 가 `"label"` — 그러나 S4 MVP linker
는 position-only. 운영자가 manifest 의 `key_mode: "label"` 을 보고 label 기반
cross-reference 가 가능하다고 오해 가능. 모듈 docstring 도 "S4 linker 가 row_ref_map
에 의존" 으로 잘못 표기 (실제 S4 는 row_ref_map 미사용).

### Fix (Medium)
1. `save_phase2_case_set` 의 `key_mode` default `"label"` → `"position"` 으로 변경.
   docstring 에 허용 값별 의미 명시: position (S4 MVP), doc_line (S4.next), label (S4.next).
   호출자가 명시적으로 `"label"` 로 올리지 않도록 가이드.
2. `CaseStoreStatus.ROW_REF_MAP_*` 주석 정정: "S4.next linker 가 row_ref_map 의 hash
   식별자에 의존할 예정" 으로 시제 정정. S4 MVP 는 row_ref_map 미사용이지만 sidecar
   무결성은 본 단계에서 미리 보장.
3. 기존 manifest 검증 테스트에 `key_mode == "position"` assertion 추가.

### 회귀 가드 +2 (`test_phase2_case_store.py`)
- `test_save_default_key_mode_is_position_for_s4_mvp` — default 가 "position" 인지 강제
- `test_save_explicit_key_mode_preserved_in_manifest` — 호출자가 명시한 "label" / "doc_line" / "position" 모두 그대로 manifest 에 기록 (S4.next 호환성)

### 합계 (S1 + S2 + S3 + S4 + 모든 Followup)
- 신규 단위 테스트: 505 (이전 503 + Followup 2 회귀 2)
- 전체 services + models suite: 505/505 통과 (회귀 0)
- ruff format / check: pass
- store manifest ↔ linker capability 정합 lock

## Agent G — S4.next (doc_id fallback + line_number normalize) (2026-05-27)
- 확장 파일:
  - src/services/phase2_ref_canonical.py (+54 LoC, `normalize_line_number_key` helper)
  - src/services/phase2_case_phase1_linker.py (+128 LoC, `key_mode` dispatching + `_resolve_auto_key_mode` / `_link_via_doc_id` / `_link_via_position` 분리)
  - tests/modules/test_services/test_phase2_ref_canonical.py (+9 테스트: normalize 8개 + idempotency 1개)
  - tests/modules/test_services/test_phase2_case_phase1_linker.py (+10 key_mode 테스트 + 새 doc-aware fixture `_row_ref_doc` / `_duplicate_case_with_docs` / `_phase1_case_with_docs`)
- 기존 테스트 회귀: 0 (기존 18 호출에 `key_mode="position"` 명시 — auto default 가 fixture 의 document_id 가용성 때문에 doc_id 분기로 자연 전환되어 position 매칭 의도가 깨지는 것을 차단)
- 전체 통과: 58/58 (linker 28 + ref_canonical 30) · services+models suite 회귀 524/524
- ruff format/check: pass/pass
- 주요 결정 / 이슈:
  - `normalize_line_number_key` 는 결과 문자열에 canonical prefix 가 남지 않으므로 ":" 분기를 한 번만 타고 idempotency 자연 만족 (#43). 비정수 float "f:1.5" 는 ValueError 방지하면서 원형 보존, 음수 padding 문자열은 도메인 범위 밖이라 단순화.
  - linker `_ALLOWED_KEY_MODES` frozenset 으로 silent fallback 금지 (#44). `auto` resolution 은 `_resolve_auto_key_mode` 가 모든 row_ref + DuplicateCase pair_ref 의 `document_id` truthy 검사 — 하나라도 None/빈 문자열이면 `position` (#42).
  - `_link_via_doc_id` 의 Pass 2 — RawRuleHitRef.document_id 는 schema 상 str 이지만 빈 문자열 가능성 방어로 `hit.document_id and ...` truthy 게이트.
  - DuplicateCase 의 `left_ref` / `right_ref` 가 row_refs 와 중복되어도 set 기반 inverse index 라 idempotent 자연 만족 (#39 회귀 가드).
  - 외부 호출자 0 (`link_phase2_to_phase1` 사용처는 본 테스트뿐) — default 가 `"auto"` 로 변경되어도 production 회귀 영향 없음. pipeline attach 는 본 단계 완료 후 unblock 되지만 S4.next.2 의 multi-company / row_ref_map.jsonl 까지 마무리한 뒤 호출하는 것을 권장.

## Wave 4 Followup 4 — doc_id looser semantic + normalize idempotency + store enum sync (2026-05-27)

### Fix A (High) — doc_id mode 의 looser semantic 명시 + pipeline attach 차단 lock
- 증상: `key_mode="doc_id"` 가 같은 document 의 다른 line 도 link → duplicate pair / VAE row evidence 에서 cross-reference 가 과하게 붙음. row-precise 가 필요한 경우 false positive.
- 수정:
  - 모듈 docstring 에 doc_id 가 **document-level** precision 임을 강하게 명시 — row 단위가 아니라 document 단위 cross-reference.
  - `LinkerResult.diagnostics["match_precision"]` 추가: `"row"` (position) / `"document"` (doc_id). 호출자가 즉시 정밀도 판별 가능.
  - **pipeline attach 차단 정책 lock 유지** — `doc_id` 의 looser semantic 이 row-precise evidence (duplicate pair, VAE outlier) 에 false positive 추가하므로 production 경로 진입 금지. S4.next.2 의 line-level `doc_line` mode + row_ref_map.jsonl 까지 보류.
- 회귀 가드 +3:
  - `test_diagnostics_records_match_precision_row_for_position_mode`
  - `test_diagnostics_records_match_precision_document_for_doc_id_mode`
  - `test_diagnostics_match_precision_follows_auto_resolution` (auto 분기 → 정밀도 일관)

### Fix B (Medium) — `normalize_line_number_key` idempotency 가드 (colon 중첩)
- 증상: raw line_number 가 `"i:1"` 같은 canonical-prefix-like 문자열이면 canonicalize → `"s:i:1"` → normalize 1차 `"i:1"` → 2차 `"1"`. invariant `normalize(normalize(x)) == normalize(x)` (#43) 깨짐.
- 수정: normalize 결과에 `:` 가 남아 있으면 재귀 호출로 cascade — 매번 ":" 하나씩 떨어져 나가므로 finite. result 가 ":" 없는 최종 형태까지 자동 도달.
- 회귀 가드 +3:
  - `test_normalize_line_number_key_raw_canonical_prefix_string_cascades_to_final` (`"s:i:1"` → `"1"`)
  - `test_normalize_line_number_key_double_canonical_prefix_string_cascades` (`"s:s:abc"` → `"abc"`)
  - `test_normalize_line_number_key_idempotent_with_embedded_colons` (4개 colon 포함 입력에 대해 invariant #43 강화)

### Fix C (Medium) — store key_mode enum 을 linker capability 와 sync
- 증상: store docstring 의 허용값 `{"position", "doc_line", "label"}` 와 linker 의 `_ALLOWED_KEY_MODES = {"position", "doc_id", "auto"}` 가 어긋남. manifest 가 linker 가 모르는 capability 를 신호 → 운영자 / orchestrator 오해.
- 수정:
  - `_STORE_ALLOWED_KEY_MODES = frozenset({"position", "doc_id"})` — linker capability 와 sync.
  - `"auto"` 는 runtime resolution 결과로만 의미. manifest 에는 resolved 값 ("position" 또는 "doc_id") 만 기록.
  - `"doc_line"` / `"label"` / `"company_doc"` 는 S4.next.2 까지 deferred — 입력 시 `UNSAFE_KEY_MODE` status 로 거절.
  - `CaseStoreStatus.UNSAFE_KEY_MODE` 신규 status 추가.
  - `save_phase2_case_set` 진입 시 key_mode 검증 (salt 검증 직전).
- 회귀 가드 +3:
  - `test_save_accepts_doc_id_key_mode`
  - `test_save_rejects_deferred_key_modes` (`"doc_line"`, `"label"`, `"company_doc"`, `"bogus"` 모두 UNSAFE_KEY_MODE)
  - `test_save_rejects_auto_key_mode` (manifest 에 resolution 결과만 기록되어야)
- 기존 `test_save_explicit_key_mode_preserved_in_manifest` 의 enum 도 sync (`"position"` / `"doc_id"` 만 통과 검증).

### 합계 (S1 + S2 + S3 + S4 + S4.next + Followup 4)
- 신규 단위 테스트: 533 (S4.next 524 + Followup4 9)
- 전체 services + models suite: 533/533 통과 (회귀 0)
- ruff format / check: pass
- doc_id semantic lock / normalize cascade / store enum sync 완료

## Wave 4 Followup 5 — normalize 재귀 cascade 제거 + 비도메인 prefix 원형 보존 (2026-05-27)

### 증상
이전 followup 4 의 fix B (normalize 재귀 cascade) 가 ``ts:`` / ``t:`` / ``b:`` /
``d:`` 같은 비도메인 prefix 입력에서 의미없게 분해.

- ``normalize("ts:2026-01-01T00:00:00")`` → cascade ``"00"`` 까지 떨어짐.
- ``normalize("t:(i:1|s:2)")`` → ``"(i:1|s:2)"`` → ``"1|s:2)"`` → ``"2)"`` 등 의미 잃음.

docstring 은 "prefix 하나씩 떨어져 finite" 라고 명시했지만 실제 의미는 깨졌음.
line_number 가 timestamp / tuple / bool / Decimal 일 수 없는데 분해해서 무의미한
substring 을 반환하는 것이 잘못된 capability 신호.

### Fix — 재귀 제거 + 비도메인 prefix 원형 보존 + idempotency 약화
- ``_DOMAIN_PREFIXES = frozenset({"n", "i", "f", "s"})`` — line_number 가 실제 가질 수 있는 타입만.
- 비도메인 prefix (``b:`` / ``d:`` / ``ts:`` / ``t:``) 발견 즉시 원본 ``canonical_key`` 그대로 반환. 분해 / cascade 없음.
- ``s:`` prefix 의 colon-string raw 입력 (예: ``"s:i:1"``) 은 prefix 제거 후 value 원형 보존 (``"i:1"``). 두 번째 normalize 호출 시 의미 변형 가능 — invariant #43 을 **약화된 형태로 정정**:
  - 결과 문자열에 ``":"`` 가 남지 않으면 idempotent (도메인 정상 입력).
  - 결과에 ``":"`` 가 남는 경우 (s: prefix 제거 후 raw colon-string, 비도메인 원형 보존) 는 idempotent 비보장 — 호출자는 한 번만 적용한다.
- docstring 에 examples 와 idempotency 범위 명시.

### 회귀 가드 변경
- **신규 +5**:
  - `test_normalize_line_number_key_timestamp_prefix_returns_original` (``"ts:..."`` 원형 보존)
  - `test_normalize_line_number_key_tuple_prefix_returns_original` (``"t:(...)"`` 원형 보존)
  - `test_normalize_line_number_key_bool_prefix_returns_original` (``"b:..."`` 원형 보존)
  - `test_normalize_line_number_key_decimal_prefix_returns_original` (``"d:..."`` 원형 보존)
  - `test_normalize_line_number_key_non_domain_prefix_does_not_cascade` (multiple-colon 비도메인 입력 cascade 차단)
- **갱신 -2 → +1**: 이전 cascade 검증 테스트 3개 (``..._cascades_to_final``, ``..._cascades``, ``..._idempotent_with_embedded_colons``) → ``test_normalize_line_number_key_raw_canonical_prefix_string_preserves_value`` 1개로 통합 (cascade 없이 한 번에 prefix 제거 후 raw 보존 검증).
- idempotency 테스트 갱신: ``test_normalize_line_number_key_is_idempotent_for_colon_free_results`` — colon-free 결과만 idempotency 보장.

### 합계 (S1 + S2 + S3 + S4 + S4.next + Followup 4 + Followup 5)
- 신규 단위 테스트: 536 (이전 533 + 신규 5 - 갱신 통합 -2 = +3, 단 idempotency 테스트 변경 포함 net +3)
- 전체 services + models suite: 536/536 통과 (회귀 0)
- ruff format / check: pass
- 비도메인 prefix cascade 분해 / 무의미 결과 차단 lock

## Agent H — S4.next.2 (doc_line / company_doc / label) (2026-05-27)
- 확장 파일:
  - src/services/phase2_case_phase1_linker.py (276 → 637 LoC, +361)
    - `_ALLOWED_KEY_MODES` 에 `doc_line` / `company_doc` / `label` 추가 (`auto` 포함 6개)
    - `_HASH_MAP_REQUIRED_MODES` / `_MATCH_PRECISION` lookup 도입
    - `_resolve_auto_key_mode` 우선순위 재편 — label > doc_id > position (#48)
    - `_link_via_doc_line` / `_link_via_company_doc` / `_link_via_label` 신규
    - 공통 helper (`_iter_phase2_refs`, `_build_position_to_entry`, `_finalize_linked_result`) 도입으로 중복 패턴 정리
    - 모듈 docstring 의 pipeline attach 정책 정정 — hash 기반 mode 사용 시 unlock
  - src/services/phase2_case_store.py (597 → 600 LoC, +3)
    - `_STORE_ALLOWED_KEY_MODES` 에 `doc_line` / `company_doc` / `label` 추가 (5개)
    - save key_mode docstring 갱신
  - tests/.../test_phase2_case_phase1_linker.py (+15 신규 테스트, 877 → 1492 LoC)
  - tests/.../test_phase2_case_store.py (+3 신규 테스트, 712 → 754 LoC)
    - 기존 `test_save_rejects_deferred_key_modes` 는 `test_save_rejects_unknown_key_modes` 로 갱신 (deferred 3종을 enum 정식 허용으로 전환했기에 거절 대상에서 제거)
- 신규 테스트 (총 18):
  - linker (15): doc_line/company_doc/label 의 validation(#45) 4건, doc_line 매칭/row-precision 2건, company_doc 매칭/disambiguation 2건, label 매칭/row-precision 2건, auto resolution 우선순위 3건, match_precision matrix 2건
  - store (3): `test_save_accepts_doc_line_key_mode`, `test_save_accepts_company_doc_key_mode`, `test_save_accepts_label_key_mode`
- 기존 테스트 회귀: 0 (test_services + test_phase2_row_ref 전체 554/554 통과)
- 전체 통과: 554/554
- ruff format / check: pass / pass
- pipeline attach: `doc_line` / `company_doc` / `label` 사용 시 **unlock** — linker 모듈 docstring 의 정책 정정. `position` / `doc_id` 단독 사용은 여전히 in-memory same-batch 한정.
- 주요 결정 / 이슈:
  - auto resolution 우선순위 lock — label > doc_id > position. row_ref_map + salt 가용성으로 label 분기, 아니면 doc_id 가용성, 아니면 position fallback.
  - `match_precision` lookup table (`_MATCH_PRECISION`) 로 mode-별 정밀도 일관화 — diagnostics 에 동일 단일 소스로 노출.
  - doc_line 의 PHASE1 측 매칭 key 는 row_ref_map entry 의 `doc_id_hash` + `line_number_key` 재사용. store 가 같은 salt 로 hash 했으므로 PHASE2 측의 `hash_ref_key(ref.document_id, salt=salt)` 결과와 동일하게 일치.
  - label 의 PHASE2 측은 `ref.index_label` (이미 canonical) 을 그대로 `hash_ref_key` — invariant상 make_row_ref 가 canonicalize 보장.
  - 모든 hash 기반 mode 는 row_ref_map entry 가 부재한 PHASE1 hit 를 자연 제외 (position_to_entry lookup miss → None key) — needed_keys 와의 교집합으로 false positive 차단.

## Wave 4 Followup 7 — pipeline attach unlock 회수 + empty row_ref_map validation (2026-05-27)

### 증상 (High)
S4.next.2 의 ``doc_line`` / ``company_doc`` / ``label`` 은 "reload-safe / row-precise /
pipeline attach unlock" 으로 표현됐으나, **PHASE1 측 매칭 key 계산이 여전히
``hit.row_index`` 의 row_ref_map[position] 조회에 의존**. 즉:

- row_ref_map 은 PHASE2 case 의 ref position 만 포함 (`_collect_unique_row_refs` 가
  PHASE2 case_set 만 순회).
- PHASE1 hit position 이 row_ref_map 에 없으면 hash 기반 mode 도 PHASE1 key 변환
  실패 → 매칭 0.
- 결국 PHASE1/PHASE2 position 동기 가정에 의존 — 진짜 cross-batch reload-safety 아님.

### Fix A — pipeline attach unlock 회수 + docstring 정정
- 모듈 docstring 의 "pipeline attach unlock" 정책을 **lock 회수** 로 정정.
- 각 hash 기반 mode docstring 에 "PHASE1 측 한계 — position-keyed lookup 의존" 명시.
- 진짜 cross-batch reload-safety 는 S6.next 의 **full-population row_ref_map** 또는
  PHASE1 별도 row_ref_map / RawRuleHitRef schema 확장 까지 보류.
- in-memory same-batch 시나리오에서 row order 변형 (sort) 흡수 정도까지만 보장.

### 증상 (Medium)
``auto`` resolution 의 ``row_ref_map is not None`` 검사가 빈 list ``[]`` 도 통과 → label
분기 → 모든 case silent unmatched. 명시 ``label`` / ``doc_line`` / ``company_doc``
호출도 ``row_ref_map=[]`` 시 ValueError 없이 진행.

### Fix B — empty row_ref_map validation + auto truthy 검사
- ``_HASH_MAP_REQUIRED_MODES`` validation 에 ``if not row_ref_map: raise ValueError(...)``
  추가 — empty list 거절. 명시 호출의 silent unmatched 차단.
- ``_resolve_auto_key_mode`` 의 ``row_ref_map is not None`` → ``row_ref_map`` truthy 검사 (#48
  보강). empty list 는 label 후보가 아니라 doc_id / position 으로 자연 fallback.

### 새 invariant
- **50.** ``key_mode in {"doc_line", "company_doc", "label"}`` 호출 시 ``row_ref_map``
  이 비어 있으면 (``[]`` 또는 ``None``) ValueError 즉시. ``auto`` 의 label 분기도
  truthy 검사로 empty list 거절.

### 회귀 가드 +4 (`test_phase2_case_phase1_linker.py`)
- `test_label_mode_with_empty_row_ref_map_raises`
- `test_doc_line_mode_with_empty_row_ref_map_raises`
- `test_company_doc_mode_with_empty_row_ref_map_raises`
- `test_auto_with_empty_row_ref_map_does_not_choose_label` (auto 가 doc_id / position 으로 fallback)

### Pipeline attach 상태 (재정정)
- ``doc_line`` / ``label`` / ``company_doc`` 도 PHASE1/PHASE2 position 동기 보장 시에만 안전.
- production attach 는 호출자가 동기 batch 임을 보장한 경우에만 허용.
- 진짜 cross-batch reload-safety unlock 은 **S6.next** 까지 보류.

### 합계 (S1 + S2 + S3 + S4 + S4.next + S4.next.2 + Followup 7)
- 신규 단위 테스트: 558 (이전 554 + Followup 7 회귀 4)
- 전체 services + models suite: 558/558 통과 (회귀 0)
- ruff format / check: pass
- pipeline attach 회수 + empty row_ref_map validation lock

## Wave 4 Followup 8 — auto resolution PHASE1 position coverage 검사 (2026-05-27)

### 증상 (Medium)
``_resolve_auto_key_mode`` 가 ``row_ref_map`` truthy + ``salt`` 가용하면 무조건 label
채택. 그러나 row_ref_map 에 PHASE1 hit position 이 부재한 partial coverage 시
label 분기 후 PHASE1 측 key 변환 실패 → 모든 case silent unmatched. docstring 에는
한계 명시했지만 auto 는 "안전한 최선 mode 선택" 의 성격이므로 partial coverage
감지 + fallback 이 필요.

### Fix — PHASE1 position 100% coverage 검사 + fallback
- ``_resolve_auto_key_mode`` signature 에 ``phase1`` 추가.
- ``_has_full_phase1_position_coverage(phase1, row_ref_map)`` 헬퍼 신규 — PHASE1
  raw_rule_hits 의 모든 row_index 가 row_ref_map position set 에 포함되는지 검사.
- coverage 100% 이면 label 채택, partial 이면 doc_id / position 으로 fallback.
- PHASE1 cases 가 빈 경우 (검사할 hit 없음) → coverage True 로 간주, label 자동 채택.
- 명시 ``label`` / ``doc_line`` / ``company_doc`` 호출은 partial coverage 여도 그대로
  진행 — 호출자 의도 존중 (auto fallback 은 protection layer 일 뿐).

### 새 invariant #51
``key_mode="auto"`` 가 label 분기하려면 PHASE1 hit position 의 100% 가
row_ref_map 에 포함되어야 한다. partial coverage → silent unmatched 위험 → label
회피, doc_id 또는 position 으로 fallback.

### 회귀 가드 +4 (`test_phase2_case_phase1_linker.py`)
- `test_auto_with_full_phase1_position_coverage_chooses_label`
- `test_auto_with_partial_phase1_position_coverage_falls_back` (partial → label 회피)
- `test_auto_with_empty_phase1_cases_chooses_label_when_rrm_available` (검사 무의미 → label)
- `test_explicit_label_with_partial_coverage_still_works_but_warns` (명시 호출은 호출자 책임)

### 합계 (S1 + S2 + S3 + S4 + S4.next + S4.next.2 + Followup 7 + Followup 8)
- 신규 단위 테스트: 562 (이전 558 + Followup 8 회귀 4)
- 전체 services + models suite: 562/562 통과 (회귀 0)
- ruff format / check: pass
- auto resolution 의 partial coverage silent failure 차단 lock

## Wave 4 Followup 9 — auto docstring 정합 + coverage helper 정규화 일관성 (2026-05-27)

### Fix A (Low) — 상단 docstring 의 auto 분기 조건이 Followup 8 로직과 어긋남
- 증상: 모듈 docstring 의 ``"auto"`` 설명이 "row_ref_map + salt 가용하면 label" 로
  되어 있어 Followup 8 의 100% coverage 요구 조건이 누락. attach 정책 lock 역할의
  모듈 docstring 이 실제 동작과 불일치.
- 수정: docstring 의 auto 분기 설명에 ``+ PHASE1 hit position 100% coverage`` 조건
  추가. 명시 호출은 coverage 검사 없음을 함께 명시 (invariant #51 인용).

### Fix B (Low) — coverage helper 와 매칭 helper 의 position 정규화 일치
- 증상: ``_has_full_phase1_position_coverage`` 가 ``isinstance(entry.get("position"), int)``
  만 인식. 반면 hash-mode 매칭 인덱스의 ``_build_position_to_entry`` 는
  ``int(entry["position"])`` 으로 문자열 숫자도 정규화. ``{"position": "10"}`` 같은
  entry 에서 explicit label 은 매칭 가능한데 auto coverage 검사가 누락 → 불필요한
  fallback.
- 수정: ``_has_full_phase1_position_coverage`` 가 ``_build_position_to_entry(row_ref_map).keys()``
  를 재사용. 두 helper 의 position 허용 범위 / 정규화 규칙 단일 출처로 통일.

### 회귀 가드 +1 (`test_phase2_case_phase1_linker.py`)
- `test_auto_coverage_check_accepts_string_position_entries` — 문자열 ``"10"`` /
  ``"11"`` position 도 정규화 통과해 coverage 100% → label 채택 검증.

### 합계 (S1 + S2 + S3 + S4 + S4.next + S4.next.2 + Followup 7 + Followup 8 + Followup 9)
- 신규 단위 테스트: 563 (이전 562 + Followup 9 회귀 1)
- 전체 services + models suite: 563/563 통과 (회귀 0)
- ruff format / check: pass
- attach 정책 docstring ↔ runtime 동작 / coverage helper ↔ 매칭 helper 단일 출처 lock
