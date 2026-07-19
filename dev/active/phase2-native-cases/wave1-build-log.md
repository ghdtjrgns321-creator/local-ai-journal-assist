# PHASE2 Native Cases — Wave 1 Build Log

S1 단계 산출물 빌드 로그. agent 별 append-only.

## Agent A — Services Foundation (2026-05-27 작업)

- 생성 파일:
  - src/services/phase2_ref_canonical.py (76 LoC)
  - src/services/phase2_ref_pseudonymize.py (26 LoC)
  - src/services/artifact_path_safety.py (66 LoC)
  - src/services/phase2_case_id.py (39 LoC)
  - tests/modules/test_services/test_phase2_ref_canonical.py (테스트 20개)
  - tests/modules/test_services/test_phase2_ref_pseudonymize.py (테스트 8개)
  - tests/modules/test_services/test_artifact_path_safety.py (테스트 13개)
  - tests/modules/test_services/test_phase2_case_id.py (테스트 7개)
- 총 테스트 케이스: 48
- ruff format: pass (8 files left unchanged)
- ruff check: pass (All checks passed!)
- 주요 결정 / 이슈 / 주의사항:
  - `canonicalize_ref_key` 의 bool 분기를 int 보다 먼저 배치 — bool 이 int
    subclass 이라 isinstance 순서가 b:0/b:1 코드 보존에 결정적.
  - numpy 는 lazy import. ImportError 가드를 두어 core 외 환경에서도 정상
    동작하도록 함 (실제로는 core group 의존이라 발생하지 않는 분기).
  - `pd.NaT` / `pd.NA` 는 isinstance 체크가 아니라 identity 비교(`is`)로 처리.
    `pd.isna` 가 array-like 입력에 대해 array 를 반환하는 함정을 피함.
  - `artifact_path_safety.safe_batch_artifact_file` 는 S1 미사용. docstring 에
    PR-pre-1 활성화 메모 명시. suffix whitelist `{".json"}` 외 거부.
  - `make_phase2_case_id` payload 의 ref 정렬은 `sorted()` 후 ',' join.
    evidence_signature 에 raw 금액/score/threshold 포함 금지 docstring 강조.
  - pytest 는 Agent B 와 import dependency (case_hash → model) 가 있어 호출자
    통합 실행에 위임. 본 작업 범위에서는 실행하지 않음.

## Agent B — Data Model + Case Hash (2026-05-27 작업)

- 생성 파일:
  - src/models/phase2_case.py (205 LoC)
  - src/services/phase2_case_hash.py (69 LoC)
  - tests/modules/test_models/test_phase2_row_ref.py (테스트 11개)
  - tests/modules/test_services/test_phase2_case_hash.py (테스트 10개)
- 총 테스트 케이스: 21
- ruff format: pass (4 files left unchanged)
- ruff check: pass (All checks passed!)
- 주요 결정 / 이슈 / 주의사항:
  - `make_row_ref` 는 `canonicalize_ref_key` 를 함수 내부 lazy import 로 호출 —
    Agent A 모듈과의 circular dependency 차단 및 import time 안전 확보.
  - `raw_line_number is None` 분기를 canonicalize 호출 앞에 두어 None 입력은
    canonicalize 를 거치지 않고 바로 None 으로 수렴. NaN/NaT/pd.NA 는
    canonicalize 가 "n:" 을 반환하면 None 으로 치환.
  - line_number_key 는 type-tag 접두 그대로 보존 — `"0001"` ("s:0001") 과
    `1` ("i:1") 의 dtype 차이가 S4 까지 살아 있음 (test 로 명시 검증).
  - `Phase2CaseSet.iter_all_cases_sorted` 는 `_FAMILY_FIELD_NAMES` 튜플로 5
    family 를 순회 후 `phase2_case_id` 사전순 정렬 → hash payload 결정성 보장.
  - `with_phase1_refs(refs_by_case_id)` 는 명시되지 않은 case 의 기존 refs 를
    유지하고 set 자체의 `linked` 를 True 로 전환한 새 set 반환 (frozen replace).
  - `compute_raw_case_hash` 와 `compute_linked_case_hash` 는 별도 payload 생성
    경로로 완전 분리. 분리 invariant 는 `inspect.getsource` 로 source-level 에서
    상호 호출 부재를 테스트로 검증.
  - `_case_to_canonical_dict` 는 `dataclasses.asdict` 결과에서 exclude 필드를
    pop 한 뒤, payload 에 `phase1_case_refs` 가 남아 있으면 정렬된 list 로 치환 —
    linked hash 의 입력 순서 무관성 보장.
  - pytest 는 Agent A 와의 import dependency 때문에 본 에이전트 범위에서
    실행하지 않음. 호출자가 통합 실행 (`uv run pytest tests/modules/`) 으로 검증.

## Wave 1 Followup — 사용자 리뷰 반영 (2026-05-27)

### Fix 1 (High) — hash payload index_label canonicalize 누락 보완
- 증상: `_case_to_canonical_dict` 가 `dataclasses.asdict` 결과를 그대로 사용 →
  Phase2RowRef.index_label 의 pd.Timestamp / np.int64 / tuple / pd.NA 가 raw 로
  payload 에 흘러 default=str 환경 의존성 발생.
- 수정: `src/services/phase2_case_hash.py` 에 `_normalize_row_ref_index_labels`
  재귀 walker 추가. dict 의 "index_label" 키를 만나면 `canonicalize_ref_key` 결과로
  치환. row_refs / left_ref / right_ref 어느 위치든 처리.
- 추가 발견: `dataclasses.asdict` 가 tuple 을 tuple 로 보존 (list 변환 안 함).
  walker 의 list 분기에 tuple 도 포함하도록 확장 (`isinstance(obj, (list, tuple))`).
- 회귀 가드 (+6 테스트, `test_phase2_case_hash.py`):
  - `test_canonical_dict_replaces_pd_timestamp_index_label_with_canonical_string`
  - `test_raw_hash_stable_under_pd_timestamp_index_label_instance_difference`
  - `test_raw_hash_stable_under_np_int64_index_label`
  - `test_raw_hash_stable_under_tuple_index_label`
  - `test_raw_hash_differs_for_distinct_index_labels` (식별성 보장)
  - `test_linked_hash_also_canonicalizes_index_labels`

### Fix 2 (Medium) — make_phase2_case_id canonical input 검증 추가
- 증상: `canonical_refs` 가 docstring 으로만 canonical 결과를 요구. raw 값
  ("DOC001" 등) 이 들어와도 silent 통과 → ID 안정성 / 비식별화 계약 위반.
- 수정: `src/services/phase2_case_id.py` 에 `_CANONICAL_PREFIX_ALLOWLIST`
  (`n:`, `b:`, `i:`, `f:`, `d:`, `ts:`, `t:`, `s:`) + `_validate_canonical_ref`
  추가. `make_phase2_case_id` 진입 시 모든 ref 검증, 위반 시 ValueError.
- 회귀 가드 (+6 테스트, `test_phase2_case_id.py`):
  - `test_make_phase2_case_id_rejects_raw_string_ref`
  - `test_make_phase2_case_id_rejects_empty_string_ref`
  - `test_make_phase2_case_id_rejects_unknown_prefix`
  - `test_make_phase2_case_id_rejects_non_string_ref`
  - `test_make_phase2_case_id_accepts_all_canonical_prefixes`
  - `test_make_phase2_case_id_validates_all_refs_in_tuple`

### Fix 3 (Low) — 보고 표 경로 정정
- `test_phase2_row_ref.py` 의 실제 위치는 `tests/modules/test_models/`. 이전
  Wave 1 보고 표가 `tests/modules/test_services/` 로 잘못 기재됨. 실제 파일은
  처음부터 옳은 위치에 작성됨 (보고 표만 정정).

### 추가 invariant (Fix 1/2 반영)
- 9. hash payload 의 모든 `index_label` 은 `canonicalize_ref_key` 통과 결과 문자열
- 10. `make_phase2_case_id.canonical_refs` 는 allowlist prefix 검증 통과만 허용

### 합계 (Wave 1 + Followup)
- 총 테스트 케이스: 81 (Wave 1 69 + Followup 12)
- ruff format/check: pass
- pyright import resolution: 프로젝트 전반 `[tool.pyright].extraPaths` 미설정 이슈 (PR-pre-2 후보, 본 작업 외)
