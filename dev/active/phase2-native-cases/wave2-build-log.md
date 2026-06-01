# PHASE2 Native Cases — Wave 2 Build Log

S2 단계 산출물 빌드 로그. agent 별 append-only.

## Agent C — Duplicate Case Builder (2026-05-27)

- 생성 파일:
  - src/services/phase2_duplicate_case_builder.py (161 LoC)
  - tests/modules/test_services/test_phase2_duplicate_case_builder.py (테스트 12개)
- 테스트 케이스: 12
- pytest: PASS (12/12, 0.63s)
- ruff format/check: pass / pass
- 주요 결정 / 이슈:
  - `classify_pair_evidence_tier` (strong/moderate/weak) 결과로 case 화 여부를
    결정. weak / pair_artifact 부재 / top_pairs 빈 list → 빈 tuple graceful
    fallback (invariant #15, #16).
  - `evidence_signature = f"sub_rule={pair['rule_id']}"` — pair_score / amount /
    threshold 일절 미포함 (invariant #13). test_evidence_signature_does_not_include_pair_score
    에서 pair_score 만 다른 두 입력의 case_id 동일성으로 회귀 검증.
  - `df.index.get_loc(label)` 결과가 int / slice / boolean ndarray 어떤 타입으로
    돌아와도 첫 occurrence 의 int row_position 으로 환원 (`_resolve_row_position`).
    duplicate label 발생 시 첫 위치 보존.
  - `_column_value` 가 컬럼 부재 / scalar NaN 을 None 으로 수렴 — line_number 가
    "0001" 문자열이면 `make_row_ref` 가 canonicalize 결과 "s:0001" 로 line_number_key
    보존 (S4 정규화 유예 invariant 와 일관).
  - `canonical_refs = (canonicalize_ref_key(left.index_label), canonicalize_ref_key(right.index_label))`
    로 항상 S1 helper 통과시켜 `make_phase2_case_id` 의 prefix allowlist 검증을
    안전하게 통과 (invariant #12).
  - 반환 타입은 `tuple[DuplicateCase, ...]` — Phase2CaseSet.duplicate_cases tuple 에
    직접 들어갈 수 있도록 list 가 아닌 tuple (invariant #11).
  - `phase1_case_refs` 는 dataclass default `()` 유지 — linker S4 가 부착
    (invariant #17). 빌더는 PHASE1 prior (priority_score / composite_sort_score)
    에 절대 접근하지 않음 (invariant #14).
  - `family_ecdf = 0.0` — S3 store 가 ECDF 결합 / 별도 계산 책임.
  - `pair_id` 기본값은 `case_id` 자체 (artifact 의 pair_id 가 명시되지 않는 경우).

## Agent D — Unsupervised Case Builder (2026-05-27)

- 생성 파일:
  - src/services/phase2_unsupervised_case_builder.py (185 LoC)
  - tests/modules/test_services/test_phase2_unsupervised_case_builder.py (테스트 11개)
- 테스트 케이스: 11
- pytest: PASS (11/11, 0.63s)
- ruff format/check: pass / pass
- 주요 결정 / 이슈:
  - `evidence_signature = f"model={model_id}|schema={schema_hash}"` 만 사용 —
    anomaly_score / ecdf_gate / threshold 일절 미포함 (invariant #13).
    `test_case_id_includes_model_and_schema_in_signature` 가 model/schema 변경에
    case_id 반응성을 회귀 검증.
  - `top_features` 는 `tuple[dict, ...]` 로 동결, 각 dict 키:
    `feature_id / contrib / tag / label_ko / evidence_type`. v7-plan 의
    `feature_id` 키 표기를 따르며 family_aggregator 의 `feature` 키와 의도적으로
    분리 (case 영역은 spec 우선).
  - zero-preserving ECDF 는 builder 내부에 inline 구현 (S2 MVP) — 0 score row 는
    ECDF 0 으로 보존, 양수 score 만 `rank(method="max", pct=True)`. S3 helper
    공용화 여부는 store/manifest 단계에서 재검토.
  - Gate: `family_ecdf >= ecdf_gate` (기본 0.95). 미달 row 는 case 화하지 않음
    (invariant #15). `test_row_at_ecdf_gate_included` 가 동률 양수 score 분포에서
    rank pct=1.0 통과를, `test_row_below_ecdf_gate_excluded` 가 분위 분포에서
    상위 1 row 만 통과함을 회귀.
  - Empty details / empty scores / 미정합 label (`details.index` 부재) 모두 빈
    tuple graceful fallback (invariant #16).
  - `df.index.get_loc(label)` 결과가 int / slice / boolean ndarray 어떤 타입으로
    돌아와도 첫 occurrence 의 int row_position 으로 환원하는 안전 분기 유지
    (duplicate builder 와 패턴 일치).
  - `canonical_refs = (canonicalize_ref_key(label),)` — 단일 row 입력만 통과.
    `make_phase2_case_id` 의 prefix allowlist 검증이 raw 라벨 누설을 차단
    (invariant #12).
  - `phase1_case_refs` 는 default `()` (invariant #17). 빌더는 PHASE1 prior
    (priority_score / composite_sort_score / rule hit) 에 절대 접근하지 않음
    (invariant #14).
  - `family_score == anomaly_score` 로 일치시켜 두었으며, `family_ecdf` 는
    inline ECDF 결과를 그대로 기록. S3 store 가 외부 ECDF 결합으로 덮어쓸 경우
    `case_generation_reason.ecdf` 값과 함께 정합성 확인 필요.
  - 테스트 fixture 에서 float64 컬럼에 빈 문자열을 대입할 때 발생하는 pandas
    FutureWarning 은 해당 컬럼을 object 로 명시 캐스팅해 제거.

## Wave 2 Followup — pyright type narrowing 정리 (2026-05-27)

- `phase2_unsupervised_case_builder._zero_preserving_ecdf`: `scores[scores>0]` →
  `scores.loc[scores>0]` 로 변경 (pyright Series narrowing). 런타임 동일.
- `phase2_unsupervised_case_builder._make_unsupervised_ref`: `hasattr(pos, "__len__")`
  분기 → `isinstance(raw_pos, np.ndarray)` 명시 분기. `np` 모듈 import 추가.
  duplicate builder 의 `_resolve_row_position` 과 동일 패턴.
- `test_phase2_duplicate_case_builder._make_df`: `index=[10, 11, 12]` →
  `index=pd.Index([10, 11, 12])` 로 변경 (pandas-stubs Axes 타입 narrowing).
- `test_phase2_unsupervised_case_builder._make_result`: `flagged_indices` 생성을
  `scores.index[mask].tolist()` 가 아닌 list comprehension + `int()` 캐스팅 +
  `# type: ignore[arg-type]` 로 변경 (Hashable → int narrowing 한계).

### 합계 (S1 + S2 + Pyright Followup)
- 총 테스트 케이스: 104 (S1 81 + S2 23)
- ruff format / check: pass
- pyright runtime-affecting 이슈: 0
- 잔여 pyright import resolution: 프로젝트 전반 config (PR-pre-2 후보)

## Wave 2 Followup 2 — unsupervised 리뷰 반영 (2026-05-27)

### Fix A (High) — label mismatch graceful fallback 실제 동작
- 증상: `details.index` 에는 있지만 `df.index` 에 없는 label 이 들어오면
  `df.index.get_loc(label)` 의 KeyError 가 전파되어 builder 가 깨짐.
  보고는 "graceful fallback" 이지만 실제로는 미동작.
- 수정: `_make_unsupervised_ref` 시그니처를 `Phase2RowRef | None` 으로 변경.
  KeyError / TypeError 잡아 None 반환. 호출자가 None 이면 continue 로 skip.
  duplicate builder 의 `_resolve_row_position` 과 동일 패턴.

### Fix B (Medium) — NaN/NaT/pd.NA 식별자 문자열화 차단
- 증상: `str(df["document_id"].iat[pos])` 에서 NaN → "nan", NaT → "NaT" 같은
  가짜 문자열이 Phase2RowRef 에 저장되어 비식별화 / 매칭 모두 오염.
- 수정: duplicate builder 와 동일한 `_column_value` helper 를 unsupervised 에도
  추가. 컬럼 부재 / scalar NaN / pd.NA 가드 후 None 으로 수렴. `make_row_ref`
  호출 시 None 이 아닐 때만 `str()` 캐스팅.

### Fix C (Low) — case_generation_reason gate 정밀화
- 증상: `case_generation_reason["gate"]` 가 ecdf_gate 와 무관하게 항상
  `"unsupervised_ecdf_q95"`. test fixture 가 `ecdf_gate=0.5` 를 써도 metadata
  는 q95 로 기록 → 부정확.
- 수정: `{"gate": "unsupervised_ecdf", "threshold": ecdf_gate, "ecdf": ecdf_value}`
  로 분리. gate 종류 / 임계 / 실제 ecdf 가 각각 명시.

### 회귀 가드 +4 (`test_phase2_unsupervised_case_builder.py`)
- `test_row_with_label_only_in_details_skipped_when_missing_from_df` (Fix A)
- `test_document_id_nan_collapses_to_none_in_row_ref` (Fix B)
- `test_company_code_pd_na_collapses_to_none_in_row_ref` (Fix B)
- `test_case_generation_reason_records_custom_threshold` (Fix C)

### 합계 (S1 + S2 + 모든 Followup)
- 총 테스트 케이스: 108 (S1 81 + S2 23 + Followup 4)
- ruff format / check: pass
- pyright runtime-affecting 이슈: 0
