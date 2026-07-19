# PHASE2 Native Cases — Wave 7 Build Log

S6.next 단계 산출물 — RawRuleHitRef schema 확장 (옵션 C). PHASE1 결과 자체에
engagement-scoped stable identifier (canonical_label_hash / doc_id_hash /
line_number_key) 를 직접 포함시켜 S4.next.2 linker 가 row_ref_map sidecar
조회 없이 두 source 의 hash 직접 비교만으로 cross-batch reload-safe 매칭을
수행할 수 있도록 한다.

## Agent L — S6.next Phase 1 (PHASE1 schema + 빌더 hash) (2026-05-28)

- 확장 파일:
  - src/models/phase1_case.py (+11 LoC, RawRuleHitRef +3 신규 필드)
    - canonical_label_hash: str = ""
    - doc_id_hash: str = ""
    - line_number_key: str | None = None
    - 기존 legacy 필드 / model_config(extra="forbid") 변경 0 (invariant #72, #73)
  - src/detection/phase1_case_builder.py (+약 40 LoC)
    - import: canonicalize_ref_key, hash_ref_key (services.phase2_ref_*)
    - build_phase1_case_result(..., engagement_salt: str = "") 파라미터 추가
    - _build_cases(..., *, engagement_salt: str = "") 파라미터 추가
    - _raw_rule_hit_refs(..., *, df, engagement_salt) — hash 산출 + 빈 값 fallback
    - has_salt 가드로 salt 미수령 시 hash 산출 skip → 기존 caller 영향 0
  - tests/modules/test_models/test_phase1_raw_rule_hit_ref.py (+5 테스트, 신규)
    - legacy fields unchanged / new defaults / explicit assignment /
      extra forbid / JSON round-trip
  - tests/modules/test_detection/test_phase1_case_builder_hash_fields.py (+7 테스트, 신규)
    - without salt empty / canonical hash / doc_id hash / line_number_key /
      line_number 컬럼 부재 / engagement-scoped salt 분리 /
      PHASE2 row_ref_map 공식 일치

- 신규 테스트: 12 PASS (model 5 + 빌더 7)
- 기존 PHASE1 회귀: 0
  - `uv run pytest tests/modules/test_detection/ tests/modules/test_models/ -q`
  - 1361 passed, 3 skipped (사전 skip 와 동일)
- engagement_salt 파라미터 추가 위치:
  - public entry: `build_phase1_case_result(..., engagement_salt="")`
  - internal: `_build_cases(..., *, engagement_salt="")`
  - internal: `_raw_rule_hit_refs(..., *, df, engagement_salt="")`
- backward compat:
  - salt 미수령 → canonical_label_hash="" / doc_id_hash="" / line_number_key=None
  - tools/scripts/profile_phase1_v126.py 의 `_build_cases(...)` 호출은 salt 안
    넘기므로 무영향
  - 기존 PHASE1 산출물 JSON 로드 시 신규 필드 default 적용 → 회귀 없음
- ruff format / check: pass / pass (4 files left unchanged · All checks passed)

### 주요 결정 / 이슈

- helper import 위치: PHASE1 (model layer) 가 `src.services.phase2_ref_*` 를
  직접 import 하는 것은 layer 위반 소지가 있으나, v7-plan §S6.next Phase 1
  의 명시적 위임 사항이라 본 단계는 그대로 진행. 후속 refactor 에서 phase-
  neutral identifier 모듈로 분리 가능.
- hash 산출 위치: `_raw_rule_hit_refs` 의 ref cache miss 분기에서 단일화. cache
  hit 시 재산출 비용 0. salt 가 빌더 한 번 호출 전체에서 단일이므로 cache key
  (rule_id, row_index) 에 salt 를 포함시키지 않아도 안전.
- has_salt 가드 우선: `hash_ref_key` 가 빈 salt 를 `ValueError` 로 거부하므로,
  빈 salt 케이스는 산출 자체를 skip 하고 default 값을 그대로 둠.
- line_number_key 정규화: `canonicalize_ref_key(raw_line)` 결과가 `"n:"` (None
  계열) 이면 None 으로 수렴 — None / NaN / NaT / pd.NA 입력을 일관 처리.
- PHASE2 row_ref_map 과 공식 일치 검증: `canonicalize_ref_key(df.index[row_index])`
  + `hash_ref_key(canonical, salt=engagement_salt)` 의 합성이 PHASE2 store 의
  `_serialize_row_ref` (index_label 이 이미 canonicalize 결과) 와 동일 결과를
  내는지 신규 테스트 `test_phase1_case_builder_canonical_label_hash_matches_phase2_format`
  에서 직접 비교 — invariant #70 보장.
- Phase 2 / Phase 3 (linker hash 비교 / pipeline attach unlock) 은 본 PR 범위 밖.

## Agent M — S6.next Phase 2 (linker hit hash 직접 사용) (2026-05-28)

- 확장 파일:
  - src/models/phase1_case.py (+5 LoC, RawRuleHitRef + company_code_hash)
    - company_code_hash: str = "" 추가 — engagement_salt 가용 시 산출
    - default 빈 문자열 — backward compat (invariant #74)
  - src/detection/phase1_case_builder.py (+약 12 LoC)
    - _raw_rule_hit_refs: has_company_code 가드 + company_code 컬럼 hash 산출
    - NaN/None/빈 문자열 graceful skip — PHASE2 store _serialize_row_ref 와 동일 정책
    - 동일 engagement_salt + str(company_code) input → PHASE2 row_ref_map 와 동일 hash
  - src/services/phase2_case_phase1_linker.py (+약 35 LoC)
    - _phase1_label_key — hit.canonical_label_hash 우선, 빈 값이면 row_ref_map fallback
    - _phase1_doc_line_key — hit.doc_id_hash + hit.line_number_key 우선, fallback
    - _phase1_company_doc_key — hit.company_code_hash + hit.doc_id_hash 우선, fallback
    - _has_full_phase1_position_coverage — hit hash 가용 hit 은 row_ref_map 검사 skip
      (invariant #76)
  - tests/modules/test_models/test_phase1_raw_rule_hit_ref.py (+1 신규, +기존 2건 갱신)
    - default 검증에 company_code_hash 추가
    - explicit assignment 에 company_code_hash 추가
    - round-trip JSON 에 company_code_hash 추가
    - 신규 test_raw_rule_hit_ref_company_code_hash_default_when_legacy_payload_loaded
  - tests/modules/test_detection/test_phase1_case_builder_hash_fields.py (+3 신규)
    - test_phase1_case_builder_with_salt_populates_company_code_hash
    - test_phase1_case_builder_company_code_hash_empty_when_column_absent
    - test_phase1_case_builder_company_code_hash_matches_phase2_row_ref_map_format
    - 기존 without_salt 테스트에 company_code_hash="" 검증 추가
  - tests/modules/test_services/test_phase2_case_phase1_linker.py (+12 신규)
    - test_label_mode_uses_hit_canonical_label_hash_when_present
    - test_label_mode_falls_back_to_row_ref_map_when_hit_hash_empty
    - test_doc_line_mode_uses_hit_doc_and_line_hash_when_present
    - test_doc_line_mode_falls_back_to_row_ref_map_when_hit_hash_empty
    - test_company_doc_mode_uses_hit_hashes_when_present
    - test_company_doc_mode_falls_back_to_row_ref_map_when_hit_hash_empty
    - test_auto_coverage_passes_when_all_hits_have_canonical_label_hash
    - test_auto_coverage_mixed_hits_uses_row_ref_map_fallback_for_legacy_hits
    - test_auto_coverage_fails_when_hit_lacks_hash_and_row_ref_map
    - test_label_mode_different_salt_yields_zero_match (invariant #77)
    - + 신규 _phase1_case_with_hit_hashes helper

- 신규 테스트: 16 PASS (model 1 + builder 3 + linker 12)
- 기존 회귀: 0 (전체 1966 passed, 3 skipped — 사전 skip 와 동일)
  - `uv run pytest tests/modules/test_services/ tests/modules/test_detection/ tests/modules/test_models/`
- ruff format / check: pass / pass (6 files left unchanged · All checks passed)

### 주요 결정 / 이슈

- hit hash 우선 패턴: 세 helper (`_phase1_label_key` / `_phase1_doc_line_key` /
  `_phase1_company_doc_key`) 가 동일 패턴 — `getattr(hit, "...", "") or ""` 로
  truthy 검사 후, 빈 값이면 `position_to_entry` lookup. 한 군데서 라도 hit hash 가
  truthy 면 row_ref_map 부재해도 매칭 가능 (invariant #75).
- coverage helper invariant #76 — `canonical_label_hash` 만 검사. doc_id_hash /
  company_code_hash 는 mode 별 helper 내부 fallback 으로 처리되므로 coverage
  레벨에서 검사하지 않는다. coverage 의 목적은 auto resolution 의 label 분기
  안전성 (silent unmatched 위험) 차단이므로 label key 인 canonical_label_hash 만 본다.
- company_code 정책 정합: PHASE2 store 의 `_serialize_row_ref` 가 `str(company_code)`
  으로 hash 하므로 builder 도 동일하게 `str(company_code_value)` 변환 후 hash —
  invariant #77 (같은 salt + 같은 input → 같은 hash) 보장. 신규 builder 테스트
  `test_phase1_case_builder_company_code_hash_matches_phase2_row_ref_map_format`
  으로 직접 검증.
- silent zero-match 정책: salt 정합 책임은 호출자에게 위임 (invariant #77). 다른
  salt 로 산출된 hash 가 만나면 단순히 매칭 0 — ValueError 던지지 않는다. 신규
  테스트 `test_label_mode_different_salt_yields_zero_match` 가 의도된 silent
  동작을 회귀 가드로 고정.
- backward compat: 구 schema PHASE1 결과 (hash 필드 빈 값) 가 들어와도 row_ref_map
  fallback 으로 매칭 가능. 신규 테스트 6건 (각 mode 당 2건: hit hash 우선 / fallback)
  으로 양방향 동작 고정.
- Phase 3 (pipeline attach unlock / row_ref_map deprecation) 은 본 PR 범위 밖.

## Agent N — S3.next Phase A (Orchestrator) (2026-05-28)

- 신규 파일:
  - src/services/phase2_case_set_orchestrator.py (142 LoC)
    - `build_phase2_case_set(*, batch_id, detection_results, df,
      unsupervised_model_id="", unsupervised_schema_hash="",
      unsupervised_ecdf_gate=0.95) -> Phase2CaseSet`
    - `_TRACK_NAME_TO_FAMILY` dict 로 5 track 라우팅, 모르는 track 은 silent skip
    - 중복 track_name 은 마지막 결과로 덮어쓰기 (호출자 책임 docstring 명시)
  - tests/modules/test_services/test_phase2_case_set_orchestrator.py (475 LoC, +10 테스트)
    - test_empty_detection_results_returns_empty_case_set
    - test_unknown_track_name_ignored
    - test_duplicate_detection_result_routes_to_duplicate_builder
    - test_unsupervised_detection_result_routes_with_model_and_schema_params
    - test_intercompany_detection_result_routes_to_intercompany_builder
    - test_relational_detection_result_routes_to_relational_builder
    - test_timeseries_detection_result_routes_to_timeseries_builder
    - test_multiple_families_combine_into_single_case_set
    - test_returns_phase2_case_set_with_linked_false_default
    - test_orchestrator_does_not_touch_phase1_prior

- 신규 테스트: 10 PASS (0.65s)
- 기존 회귀: 0
  - `uv run pytest tests/modules/test_services/ tests/modules/test_models/
    tests/modules/test_detection/ -q`
  - 1978 passed, 3 skipped (사전 skip 동일)
- 5 builder 시그니처 호환: 모두 `(*, batch_id, detection_result, df)` —
  unsupervised 만 `+ model_id, schema_hash, ecdf_gate=0.95` 추가. orchestrator
  가 정확히 매칭하여 kwarg 전달.
- ruff format / check: pass / pass (2 files left unchanged · All checks passed)

### 주요 결정 / 이슈

- builder mock 전략: monkeypatch 로 5 builder 를 capture-stub (`_StubRecorder`)
  으로 대체. 실제 builder 비즈니스 로직 (artifact 파싱, tier gate 등) 은 본
  테스트 범위 밖이며, orchestrator 의 책임 (track_name 라우팅 / 인자 전달 /
  Phase2CaseSet 조립) 만 검증한다. recorder.calls 로 kwarg set 까지 확인하여
  invariant #81 (unsupervised 만 추가 인자) 회귀 가드 강화.
- silent skip 검증: `test_unknown_track_name_ignored` + multi-family 테스트의
  noisy_unknown_track 둘 다 ValueError 미발생 + builder 호출 0건을 동시에
  검증해 invariant #80 양면 (예외 미발생 / 무호출) 고정.
- invariant #83 검증: orchestrator 는 시그니처에 PHASE1 prior 인자가 노출되지
  않는 점만으로도 정적 보장. 추가로 `test_orchestrator_does_not_touch_phase1_prior`
  에서 builder stub 호출 kwarg 에 `phase1_cases / priority_score /
  composite_sort_score / row_ref_map / phase1_case_refs` 가 0건임을 직접
  확인해 runtime 회귀 가드까지 부착.
- linked=False default: dataclass field default 이지만 orchestrator 가
  명시적으로 `linked=False` 를 넘겨 의도 명시 — invariant #82 가 코드 의도로
  표현되도록 함. `test_returns_phase2_case_set_with_linked_false_default` 가
  case 있는 경우 / 없는 경우 양쪽 다 False 임을 검증.
- 사전 회귀 (orchestrator 무관): 전체 회귀에서 4건 사전 실패 — header_llm
  ImportError / detection rule_count / dashboard tab_review_queue
  render_candidate_card / yaml priority_band 0.75 → 0.9. 본 작업 변경과
  무관 (orchestrator 모듈 import 0건).
- Phase B (run_phase2_inference attach) 는 다음 단계 — orchestrator 호출 hook,
  engagement_salt 도출, store/linker 통합은 본 PR 범위 밖 (v7-plan §S3.next
  Phase B deferred).

## Agent O — S3.next Phase B (run_phase2_inference attach) (2026-05-28)

- 확장 파일:
  - src/pipeline.py (+8 LoC, PipelineResult +2 필드 + Phase2CaseSet import)
    - `phase2_case_set: Phase2CaseSet | None = field(default=None, repr=False)`
    - `phase2_linker_diagnostics: dict[str, Any] | None = field(default=None, repr=False)`
  - src/services/phase2_inference_service.py (+82 LoC)
    - `_attach_phase2_case_set(result, *, ctx, snapshot)` helper 신규
    - `run_phase2_inference` 의 `_attach_phase2_case_overlays` 직후 +
      `_persist_phase2_batch_snapshot` 직전 위치에 hook 호출 추가
    - log_timing key: `phase2.inference.attach_phase2_case_set`
  - tests/modules/test_services/test_phase2_inference_service_case_set_attach.py
    (273 LoC, +8 테스트, 신규)
    - test_attach_skips_when_results_empty
    - test_attach_skips_when_data_none
    - test_attach_skips_when_batch_id_empty
    - test_attach_attaches_case_set_to_result
    - test_attach_with_phase1_invokes_linker_and_records_diagnostics
    - test_attach_without_phase1_skips_linker_keeps_linked_false
    - test_attach_with_engagement_salt_auto_resolves_to_hash_mode
    - test_attach_without_engagement_salt_falls_back_to_position

- 신규 테스트: 8 PASS (0.64s)
- 기존 회귀: 0
  - `uv run pytest tests/modules/test_services/
    tests/modules/test_detection/ tests/modules/test_models/ -q`
  - 1987 passed, 3 skipped (Phase B 직전 baseline 1979 + 신규 8 → 1987 정합)
  - `tests/modules/test_services/test_phase2_inference_service.py` 27 tests
    포함 전 구간 회귀 0 — 기존 `_FakePipeline` (results 필드 부재) 가
    invariant #84 graceful skip 으로 자연 흡수.
- ruff format / check: pass / pass (3 files left unchanged · All checks passed)

### 주요 결정 / 이슈

- circular import 처리: `_attach_phase2_case_set` 내부에서 orchestrator /
  linker 모듈을 function-level lazy import 로 호출. PipelineResult 의
  `Phase2CaseSet | None` 타입 힌트만 module-level import (`src.models.phase2_case`)
  — 모델은 dataclass 정의 외부 의존이 없어 순환 위험 0.
- snapshot 도출 경로: `model_id = snapshot["report_id"]`, `schema_hash =
  snapshot["inference_contract"]["schema_hash"]` 로 정확히 invariant #87 정합.
  snapshot 부재 / dict 아님 / 키 부재 모두 빈 문자열 fallback —
  test_attach_attaches_case_set_to_result 가 default 동작 잠금.
- engagement_salt 정책: `f"{engagement_id}|{batch_id}"` 포맷 — engagement_id
  부재 시 `salt=None` 전달하여 linker auto resolve 가 position fallback.
  PHASE1 builder 가 동일 포맷으로 salt 사용 시 hit hash direct path 활성
  (S6.next Phase 2 invariant #79 정합).
- linker ValueError 안전 가드: `key_mode="auto"` 는 salt 부재 시 position 으로
  fallback 하므로 실제로는 ValueError 가 거의 발생하지 않지만, 예기치 못한
  실패가 inference 전체를 막지 않도록 try/except 로 감싸고 warning 누적.
- backward compat: `run_phase2_inference` 시그니처 변경 0건. 기존 fake pipeline
  test 27 건이 graceful skip 만으로 통과 — invariant #84 가 인터페이스 호환을
  보장.
- pipeline attach 진짜 unlock: S6.next Phase 1+2 가 PHASE1 hit hash 보유 +
  linker hit hash direct path 를 production 으로 만들었고, 본 Phase B 가
  orchestrator + linker 를 inference 흐름에 정식 통합. PHASE1 builder 가
  engagement_salt 를 받기만 하면 row_ref_map sidecar 없이 cross-batch
  reload-safe 매칭이 가능하다.
