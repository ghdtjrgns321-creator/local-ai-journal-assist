# PHASE2 Native Cases — Wave 3 Build Log

S3 단계 산출물 빌드 로그. agent 별 append-only.

## Agent E — Phase2 Case Store (2026-05-27)

- 생성 파일:
  - src/services/phase2_case_store.py (407 LoC)
  - tests/modules/test_services/test_phase2_case_store.py (457 LoC, 테스트 22개)
- save 테스트: 14
- load 테스트: 8
- pytest: PASS (22/22, 0.77s)
- ruff format/check: pass / pass
- 주요 결정 / 이슈:
  - `_collect_unique_row_refs` 가 row_refs + DuplicateCase.left_ref/right_ref 모두
    훑어 unique position 기준 dedup. 같은 position 이 여러 case 에 등장하면 첫
    occurrence 보존 (invariant #28). DuplicateCase 외 family 는 row_refs 만으로
    충분하지만 future-proof 로 left/right 분기를 명시.
  - `row_ref_entry` 의 `doc_id_hash` / `company_code_hash` 는 raw string 을 그대로
    `hash_ref_key` 에 통과 (canonicalize 미적용). 이미 string 타입이라 환경 의존
    없음. `canonical_label_hash` 만 `canonicalize_ref_key` 통과. `line_number_key`
    는 hash 안 함 — Phase2RowRef 가 이미 보유한 canonical string 그대로 (invariant
    #19, S4 정규화 보존).
  - 진입 가드 순서: salt → ctx → batch_id. salt 검증을 가장 먼저 — hash_ref_key
    호출 전에 차단해 SALT_MISSING 을 안정적으로 반환 (invariant #24).
  - 빈 family 는 `_write_family_jsonls` 가 `if not cases: continue` 로 jsonl 자체를
    생성하지 않음 (invariant #23). 디스크 사용량 절감 + load 시 누락 jsonl 은 빈
    list 로 graceful 처리.
  - manifest 의 `linked_case_hash` 는 `case_set.linked == False` 면 null 로 명시
    저장 (invariant #21). load 시 `linked_case_hash is not None` 을 기준으로
    case_set.linked 재구성 — manifest 가 linked 상태의 단일 출처.
  - load 의 `_case_from_dict` 가 dataclass 필드별로 적절한 컨테이너 타입 복원:
    `row_refs` → tuple[Phase2RowRef, ...], `left_ref/right_ref` → Phase2RowRef|None,
    `phase1_case_refs` / `top_features` → tuple, `counterparty_pair` → tuple[str,str].
    원본 list 그대로 두면 dataclass 의 frozen tuple 필드와 타입 mismatch.
  - load 후 `Phase2RowRef.index_label` 은 canonical string 그대로 보존 (invariant
    #27). raw 타입 복원 시도 없음 — S4 linker 가 별도 매핑 책임.
  - `row_ref_map.jsonl` 직렬화는 `_canonical_jsonl_line` (sort_keys + 압축
    separator + default=str) 으로 결정적. manifest 의 `row_ref_map_hash` 는 본
    직렬화 결과의 sha256 — 재현 가능한 무결성 체크.
  - save 가 반환하는 `Phase2CaseStoreResult.raw_case_hash` / `linked_case_hash` 는
    manifest 의 동일 필드와 1:1. 호출자가 manifest 재파싱 없이 즉시 사용 가능.
  - 테스트 fixture 의 expected `doc_id_hash` / `company_code_hash` 계산이 처음에
    `canonicalize_ref_key` 를 거치도록 잘못 작성됐다가 spec 정합으로 정정. invariant
    #18 은 "hash_ref_key 통과 + raw 원문 부재" 가 핵심이며, canonical 변환 강제는
    아님 — 이미 string 인 식별자에는 적용하지 않는 것이 v7-plan 의 row_ref_map
    schema 와 일관.

## Wave 3 Followup — 무결성 검증 + canonicalize idempotency (2026-05-27)

### Fix A (High) — row_ref_map 무결성 검증
- 증상: `save` 가 `row_ref_map_hash` 를 manifest 에 기록하지만 `load` 는 sidecar
  존재 여부 / hash 일치 여부를 검증하지 않음. S4 linker 가 이 sidecar 에 의존할
  예정이라 missing / 변조 상태에서도 LOAD_SUCCESS 가 반환되는 위험.
- 수정: load 단계 7) 에서 row_ref_map.jsonl 존재 + sha256 재계산 + manifest 와 비교.
  새 status 2개: `ROW_REF_MAP_MISSING` / `ROW_REF_MAP_HASH_MISMATCH`.

### Fix B (Medium) — case hash 재계산 검증
- 증상: load 가 manifest 의 raw_case_hash / linked_case_hash 를 그대로 결과에
  실어 줌. family jsonl 이 파싱 가능한 다른 payload 로 변조되어도 감지 불가.
- 수정: load 단계 8) 에서 `compute_raw_case_hash(case_set)` 재계산 → manifest 와
  비교. linked 이면 `compute_linked_case_hash(case_set)` 도 동일 비교.
  새 status 1개: `CASE_HASH_MISMATCH`. diagnostics.kind = "raw" / "linked" 로
  어느 hash 단계에서 깨졌는지 명시.

### Fix C (Medium) — 민감 artifact 정책 명시
- 증상: family jsonl 안의 row_refs / left_ref / right_ref 에 raw document_id /
  company_code 가 그대로 포함됨. row_ref_map 만 비식별인 데 비대칭.
- 결정: 회사별 권한 격리 디렉토리 (`<engagement_dir>`) 자체에 의존하는 민감
  artifact 로 lock. 감사인 UI / 디버깅이 원본 식별자를 필요로 하기 때문.
- 수정: 모듈 docstring 에 정책 명시. row_ref_map 만 비식별화한 이유 (Δ19 lazy
  two-pass inverse index 의 노출 표면 축소) 와 외부 배포 금지 정책 기록.

### Fix D (치명 — 검증 추가 후 발견) — canonicalize_ref_key idempotency
- 증상: Fix B 적용 후 모든 round-trip 테스트 실패. 원인은 load 가 복원한
  `Phase2RowRef.index_label` 이 이미 canonical 문자열 ("i:10") 인데, raw_hash
  재계산 시 `_normalize_row_ref_index_labels` 가 다시 `canonicalize_ref_key`
  호출 → `"s:i:10"` 이중 prefix 가 붙어 hash 불일치.
- 수정: `canonicalize_ref_key` 의 string fallback 분기 직전에 idempotency 가드
  추가. canonical prefix (`n:` / `b:` / `i:` / `f:` / `d:` / `ts:` / `t:` / `s:`)
  로 시작하는 문자열은 그대로 반환. `_CANONICAL_PREFIXES` 상수 모듈 상단에 정의.

### 회귀 가드 +9 (`test_phase2_case_store.py` +4 / `test_phase2_ref_canonical.py` +5)
- `test_load_returns_row_ref_map_missing_when_jsonl_deleted` (Fix A)
- `test_load_returns_row_ref_map_hash_mismatch_when_jsonl_tampered` (Fix A)
- `test_load_returns_case_hash_mismatch_when_family_jsonl_tampered` (Fix B, raw)
- `test_load_returns_case_hash_mismatch_for_linked_when_linked_jsonl_tampered` (Fix B, linked)
- `test_canonicalize_idempotent_on_int_prefix` (Fix D)
- `test_canonicalize_idempotent_on_timestamp_prefix` (Fix D)
- `test_canonicalize_idempotent_on_string_prefix` (Fix D)
- `test_canonicalize_idempotent_on_null_prefix` (Fix D)
- `test_canonicalize_idempotent_on_tuple_prefix` (Fix D)
- `test_canonicalize_non_canonical_string_gets_s_prefix` (Fix D 경계 — canonical prefix 가 아닌 문자열은 여전히 's:' 부착)

### 합계 (S1 + S2 + S3 + 모든 Followup)
- 총 테스트 케이스: 140 (S1 81 + S2 27 + S3 26 + canonical idempotency 6)
- ruff format / check: pass
- pyright runtime-affecting 이슈: 0

## Wave 3 Followup 2 — canonicalize idempotency 근본 해결 (2026-05-27)

### 문제 재정의
이전 followup 의 fix D (canonicalize_ref_key 글로벌 idempotency) 는 raw 문자열
`"i:10"` 의 의미를 잃음 — int 10 과 충돌. S4 linker 가 canonical key 에 강하게
의존하므로 raw string collision 은 디버깅 어려운 버그가 됨.

### 옵션 비교
1. `canonicalize_ref_key(value, assume_canonical=False)` flag — 호출 site 누락 위험.
2. 별도 `canonicalize_loaded_ref_key()` 함수 — `_normalize_row_ref_index_labels`
   호출 site 가 fresh / loaded 데이터 구분 불가 → 동일 collision 잔존.
3. **Phase2RowRef.index_label 항상 canonical 화** — 근본 해결 (선택).

### 선택: 옵션 3 (Phase2RowRef invariant 강화)
- `Phase2RowRef.index_label: Any → str` 으로 타입 좁힘. invariant 명시: 항상
  canonical 문자열.
- `make_row_ref` 가 `canonicalize_ref_key` 통과 후 저장. 모든 builder 가
  make_row_ref 경유 → invariant 보장.
- `_normalize_row_ref_index_labels` 제거. `_case_to_canonical_dict` 가 asdict
  결과를 그대로 사용. row_refs 의 index_label 은 이미 canonical 이므로 별도 walker
  불필요.
- `canonicalize_ref_key` idempotency 가드 제거 — strict 복원. raw "i:10" → "s:i:10"
  (semantic preservation).
- duplicate builder / case store 에서 `canonicalize_ref_key(ref.index_label)` 재호출
  제거 (이미 canonical, 재호출 시 "s:i:10" 이중 prefix).
- load: `_row_ref_from_dict` 는 jsonl 의 canonical string 그대로 보존.

### 변경 파일
- `src/models/phase2_case.py`: Phase2RowRef.index_label 타입 + invariant + make_row_ref canonicalize
- `src/services/phase2_ref_canonical.py`: idempotency 가드 제거 (strict 복원)
- `src/services/phase2_case_hash.py`: `_normalize_row_ref_index_labels` 제거
- `src/services/phase2_case_store.py`: `_row_ref_entry` 의 canonicalize 재호출 제거 + `_row_ref_from_dict` 의 str 보장
- `src/services/phase2_duplicate_case_builder.py`: `canonical_refs` 의 재호출 제거 (이미 canonical)
- `tests/modules/test_models/test_phase2_row_ref.py`: 1 assertion 갱신 (raw 10 → "i:10")
- `tests/modules/test_services/test_phase2_duplicate_case_builder.py`: 2 assertion 갱신
- `tests/modules/test_services/test_phase2_unsupervised_case_builder.py`: 6 assertion 갱신 (by_label dict key)
- `tests/modules/test_services/test_phase2_case_hash.py`: `_make_case_with_label` 가 canonicalize 통과 (fixture 일관)
- `tests/modules/test_services/test_phase2_ref_canonical.py`: 6 idempotency 테스트 제거, strict 1 테스트로 교체

### 새 invariant
- 29. Phase2RowRef.index_label 은 항상 canonical 문자열 (make_row_ref 가 보장).
- 30. raw 문자열 "i:10" 도 strict canonicalize 가 "s:i:10" 으로 prefix 부착 — int 10 ("i:10") 과 의미 보존.
- 31. hash 경로에서 row_ref.index_label 재정규화 금지 — Phase2RowRef invariant 신뢰.

### 합계 (S1 + S2 + S3 + Option 3 refactor)
- 총 테스트 케이스: 135 (140 − idempotency 6 + strict 1 = 135). 전체 services + models suite: 481/481 통과 (회귀 0).
- ruff format / check: pass
- pyright runtime-affecting 이슈: 0
- raw 문자열 vs canonical 충돌: 불가능 (구조적 차단)

## Wave 3 Followup 3 — invariant runtime 강제 + 테스트 fixture 정합 (2026-05-27)

### 문제
이전 Option 3 리팩토는 Phase2RowRef.index_label invariant 를 주석/타입힌트로만
표현. 미래 builder / 수동 fixture 가 `Phase2RowRef(index_label="A")` 또는
`index_label=10` 으로 직접 생성하면 raw hash / row_ref_map hash 가 조용히 깨짐.
실제로 `test_phase2_row_ref.py` 의 frozen / optional 테스트가 raw "A" 를
주입하면서도 통과 — invariant 위반 silent.

추가로 `test_phase2_case_store.py` 의 `_make_duplicate_case` / `_make_unsupervised_case`
fixture 가 `canonicalize_ref_key(left.index_label)` 같이 이미 canonical 인 값을
재호출 → "s:i:10" 이중 prefix → production duplicate builder 와 다른 ID 공간 테스트.

### Fix A — `Phase2RowRef.__post_init__` 런타임 검증
```python
def __post_init__(self):
    if not isinstance(self.index_label, str):
        raise TypeError("...canonical str")
    if not self.index_label.startswith(_CANONICAL_PREFIXES):
        raise ValueError("...canonical prefix")
```
- `_CANONICAL_PREFIXES = ("n:", "b:", "i:", "f:", "d:", "ts:", "t:", "s:")` 를
  `models/phase2_case.py` 모듈 상단에 정의. `canonicalize_ref_key` 의 prefix 와
  동기화 (주석으로 single source 명시).
- frozen dataclass `__post_init__` 는 검증/raise 만 가능 — invariant 강제에 충분.

### Fix B — 테스트 fixture canonicalize 재호출 제거
- `test_phase2_case_store.py:_make_duplicate_case` — `canonicalize_ref_key(left.index_label)` → `left.index_label` 그대로 (production duplicate builder 와 정합).
- `test_phase2_case_store.py:_make_unsupervised_case` — 동일 패턴 정정.
- `test_phase2_row_ref.py:test_phase2_row_ref_frozen` / `test_phase2_row_ref_company_code_optional` — `index_label="A"` → `"s:A"` (canonical 형식).

### 회귀 가드 +4 (`test_phase2_row_ref.py`)
- `test_phase2_row_ref_post_init_rejects_non_string_index_label` — int 등 raw 타입 → TypeError
- `test_phase2_row_ref_post_init_rejects_non_canonical_string_index_label` — `"A"`/`"DOC001"` → ValueError
- `test_phase2_row_ref_post_init_accepts_all_canonical_prefixes` — 8개 prefix 모두 통과
- `test_make_row_ref_output_passes_post_init` — `make_row_ref` 출력은 항상 invariant 통과 (raw int / str / pd.NA / 이미-canonical 모두)

### 변경 파일
- `src/models/phase2_case.py`: `_CANONICAL_PREFIXES` + `Phase2RowRef.__post_init__`
- `tests/modules/test_models/test_phase2_row_ref.py`: fixture canonical 형식 + 4 회귀 가드
- `tests/modules/test_services/test_phase2_case_store.py`: 2개 fixture canonicalize 재호출 제거

### 새 invariant 추가
- 32. Phase2RowRef.__post_init__ 이 index_label 의 canonical str + prefix 형식을 runtime 에서 강제. 위반 시 TypeError / ValueError 즉시.

### 합계 (S1 + S2 + S3 + 모든 Wave 3 Followup)
- 신규 단위 테스트: 135 + 4 = 139 (services + models phase2 native cases 영역)
- 전체 services + models suite: 485/485 통과 (회귀 0)
- ruff format / check: pass
- raw 값 → Phase2RowRef 직접 주입: 구조적 차단 (post_init 강제)
- 테스트 fixture ↔ production builder ID 공간 정합 확보
