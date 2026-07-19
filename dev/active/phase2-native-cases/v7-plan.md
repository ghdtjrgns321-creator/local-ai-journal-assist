# PHASE2 Native Cases — v7 Internal Plan

> Internal spec. 7 review rounds (v1→v7). 단일 출처. Compact.

## Decisions (locked)

- unit: family-native (pair / edge / row / window / no_candidate)
- phase1 relation: independent + cross-reference (ranking 결합 없음)
- generation gate: strong / moderate / ml_quantile only (weak 제외)
- storage scope: gate-passed cases only
- ID format: `p2_{family}_{unit_type}_{sha1_10}`
- raw_hash / linked_hash 완전 분리. phase1_case_refs는 linked 에만 포함.
- created_at은 manifest.json 에만, case record 에는 없음.
- line_number_key dtype 보존 (S1). 정규화 결정은 S4 deferred.
- VAE family_ecdf >= 0.95 gate, UI top 50 cap → S2/S7

## File targets (S1)

```
src/
  models/phase2_case.py                              (Agent B)
  services/
    phase2_ref_canonical.py                          (Agent A)
    phase2_ref_pseudonymize.py                       (Agent A)
    artifact_path_safety.py                          (Agent A)
    phase2_case_id.py                                (Agent A)
    phase2_case_hash.py                              (Agent B)
tests/modules/
  test_models/test_phase2_row_ref.py                 (Agent B)
  test_services/
    test_phase2_ref_canonical.py                     (Agent A)
    test_phase2_ref_pseudonymize.py                  (Agent A)
    test_artifact_path_safety.py                     (Agent A)
    test_phase2_case_id.py                           (Agent A)
    test_phase2_case_hash.py                         (Agent B)
```

## Module signatures

### `phase2_ref_canonical.py`

```python
def canonicalize_ref_key(value: Any) -> str:
    """type-tag prefix + normalized string. 환경 무관."""
    # None / float-NaN / pd.NaT / pd.NA / Decimal-NaN  → "n:"
    # bool / np.bool_                                    → "b:0" or "b:1"
    # int / np.integer                                   → f"i:{int(v)}"
    # float / np.floating:
    #   pd.isna(v)              → "n:"
    #   math.isinf and v>0      → "f:+inf"
    #   math.isinf and v<0      → "f:-inf"
    #   else                    → f"f:{float(v):.10g}"
    # Decimal:
    #   value.is_nan()          → "n:"
    #   else                    → f"d:{value.normalize()}"
    # pd.Timestamp:
    #   pd.isna(v)              → "n:"
    #   else                    → f"ts:{value.isoformat()}"
    # datetime / date           → f"ts:{value.isoformat()}"
    # tuple                     → "t:(" + "|".join(canonicalize_ref_key(x) for x in v) + ")"
    # else                      → "s:" + str(value)
```

### `phase2_ref_pseudonymize.py`

```python
def hash_ref_key(canonical_key: str, *, salt: str) -> str:
    if not salt or not salt.strip():
        raise ValueError("hash_ref_key: salt must be non-empty and non-whitespace")
    return hashlib.sha256(f"{salt}|{canonical_key}".encode()).hexdigest()[:16]
```

### `artifact_path_safety.py`

```python
SAFE_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

def is_safe_batch_id(batch_id: str) -> bool:
    # len ∈ [1, 128], not "." / "..", pattern fullmatch
    ...

def safe_batch_artifact_dir(engagement_dir: Path, batch_id: str) -> Path | None:
    """<engagement_dir>/phase2_cases/<batch_id>/ — case set directory artifact."""
    ...

def safe_batch_artifact_file(
    engagement_dir: Path, batch_id: str, suffix: str = ".json"
) -> Path | None:
    """<engagement_dir>/phase2_overlays/<batch_id>.json — overlay file artifact.

    NOTE: S1 (phase2-native-cases) 범위에서 case store 가 호출하지 않는다.
    overlay store 마이그레이션(PR-pre-1)에서 phase2_overlay_store.py 가
    private _is_safe_batch_id 대신 본 함수를 호출하도록 전환할 때 활성화된다.
    S1 에서는 본 함수의 단위 테스트만 유지하고 사용처는 없다.
    """
    # suffix 화이트리스트: {".json"} 외 → None
    ...
```

### `phase2_case_id.py`

```python
def make_phase2_case_id(
    *,
    batch_id: str,
    family: str,
    unit_type: str,
    canonical_refs: tuple[str, ...],
    evidence_signature: str,
) -> str:
    """
    payload = "{batch_id}|{family}|{unit_type}|{sorted_csv_refs}|{evidence_signature}"
    return f"p2_{family}_{unit_type}_{sha1(payload)[:10]}"

    중요: evidence_signature 에는 raw 금액 / score / threshold 포함 금지.
    case identity 만 (sub_rule, ic_role, edge keys 등).
    """
```

### `models/phase2_case.py`

```python
@dataclass(frozen=True)
class Phase2RowRef:
    row_position: int
    index_label: Any
    document_id: str | None
    line_number_key: str | None     # canonicalize 결과 그대로 (S1, 정규화 없음)
    company_code: str | None


def make_row_ref(
    *,
    row_position: int,
    index_label: Any,
    document_id: str | None,
    raw_line_number: Any,
    company_code: str | None,
) -> Phase2RowRef:
    """raw_line_number 를 canonicalize 통과시켜 line_number_key 채움.
    None/NaN/NaT/pd.NA 는 None 으로 수렴. 그 외는 canonical 결과 그대로 (정규화 안 함).
    """
    # lazy import — circular dependency 방어
    from src.services.phase2_ref_canonical import canonicalize_ref_key

    if raw_line_number is None:
        line_number_key = None
    else:
        ck = canonicalize_ref_key(raw_line_number)
        line_number_key = None if ck == "n:" else ck
    return Phase2RowRef(row_position, index_label, document_id, line_number_key, company_code)


@dataclass(frozen=True)
class Phase2CaseBase:
    phase2_case_id: str
    batch_id: str
    family: str                              # duplicate | intercompany | relational | unsupervised | timeseries
    unit_type: str                           # pair | edge | row | window | no_candidate
    row_refs: tuple[Phase2RowRef, ...]
    evidence_tier: str                       # strong | moderate | weak | ml_quantile
    case_generation_reason: dict[str, Any]
    family_score: float
    family_ecdf: float
    phase1_case_refs: tuple[str, ...] = ()

    def with_phase1_refs(self, refs: tuple[str, ...]) -> "Phase2CaseBase":
        return dataclasses.replace(self, phase1_case_refs=tuple(sorted(refs)))


@dataclass(frozen=True)
class DuplicateCase(Phase2CaseBase):
    pair_id: str = ""
    sub_rule: str = ""                       # L2-03a / L2-03b / L2-03c / L2-03d
    left_ref: Phase2RowRef | None = None
    right_ref: Phase2RowRef | None = None
    pair_evidence_tier: str = ""

@dataclass(frozen=True)
class IntercompanyCase(Phase2CaseBase):
    ic_role: str = ""                        # reciprocal_flow | amount_mismatch | no_candidate | timing_gap
    counterparty_pair: tuple[str, str] | None = None
    amount_a: float | None = None
    amount_b: float | None = None
    amount_symmetry: float | None = None

@dataclass(frozen=True)
class RelationalCase(Phase2CaseBase):
    sub_rule: str = ""                       # R01..R07
    edge_a: str = ""
    edge_b: str = ""
    metric_name: str = ""
    metric_value: float = 0.0

@dataclass(frozen=True)
class UnsupervisedCase(Phase2CaseBase):
    anomaly_score: float = 0.0
    top_features: tuple[dict, ...] = ()      # [{feature_id, contrib, tag, label_ko}, ...]
    model_id: str = ""
    schema_hash: str = ""

@dataclass(frozen=True)
class TimeseriesCase(Phase2CaseBase):
    sub_rule: str = ""                       # TS01 | TS02
    subject: str = ""                        # account or process
    window_start: str = ""
    window_end: str = ""
    daily_count: int = 0
    expected_count: float = 0.0
    z_score: float = 0.0


@dataclass(frozen=True)
class Phase2CaseSet:
    duplicate_cases: tuple[DuplicateCase, ...] = ()
    intercompany_cases: tuple[IntercompanyCase, ...] = ()
    relational_cases: tuple[RelationalCase, ...] = ()
    unsupervised_cases: tuple[UnsupervisedCase, ...] = ()
    timeseries_cases: tuple[TimeseriesCase, ...] = ()
    linked: bool = False

    def iter_all_cases_sorted(self) -> Iterator[Phase2CaseBase]:
        """모든 family case 를 phase2_case_id 사전순으로."""
        ...

    def with_phase1_refs(self, refs_by_case_id: dict[str, tuple[str, ...]]) -> "Phase2CaseSet":
        """각 case 에 phase1_case_refs 부착 후 linked=True 로 새 set 반환."""
        ...
```

### `phase2_case_hash.py`

```python
_RAW_HASH_EXCLUDED_FIELDS = frozenset({"phase1_case_refs"})

def _case_to_canonical_dict(case: Phase2CaseBase, *, exclude: frozenset[str] = frozenset()) -> dict:
    d = dataclasses.asdict(case)
    for f in exclude:
        d.pop(f, None)
    if "phase1_case_refs" in d:
        # linked payload 에서는 정렬된 list 로
        d["phase1_case_refs"] = sorted(d["phase1_case_refs"])
    return d

def _canonical_json(payload: list[dict]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

def compute_raw_case_hash(case_set: Phase2CaseSet) -> str:
    """raw hash — phase1_case_refs 명시 제외 (default () 라도)."""
    payload = [
        _case_to_canonical_dict(c, exclude=_RAW_HASH_EXCLUDED_FIELDS)
        for c in case_set.iter_all_cases_sorted()
    ]
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

def compute_linked_case_hash(case_set: Phase2CaseSet) -> str:
    """linked hash — phase1_case_refs 정렬된 list 로 payload 포함."""
    payload = [_case_to_canonical_dict(c) for c in case_set.iter_all_cases_sorted()]
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
```

## Test names

### `test_phase2_ref_canonical.py`
- test_canonicalize_none_returns_n
- test_canonicalize_float_nan_returns_n
- test_canonicalize_pd_nat_returns_n
- test_canonicalize_pd_na_returns_n
- test_canonicalize_decimal_nan_returns_n
- test_canonicalize_bool_true_returns_b1
- test_canonicalize_bool_false_returns_b0
- test_canonicalize_int_returns_i_prefix
- test_canonicalize_np_int64_returns_i_prefix
- test_canonicalize_float_normal_returns_f_prefix
- test_canonicalize_float_pos_inf_returns_f_plus_inf
- test_canonicalize_float_neg_inf_returns_f_minus_inf
- test_canonicalize_decimal_normal_returns_d_prefix
- test_canonicalize_pd_timestamp_returns_ts_prefix
- test_canonicalize_python_datetime_returns_ts_prefix
- test_canonicalize_python_date_returns_ts_prefix
- test_canonicalize_tuple_returns_t_prefix
- test_canonicalize_nested_tuple
- test_canonicalize_string_returns_s_prefix
- test_canonicalize_unicode_string

### `test_phase2_ref_pseudonymize.py`
- test_salt_empty_raises_value_error
- test_salt_whitespace_only_raises
- test_salt_tab_newline_only_raises
- test_same_input_same_hash
- test_different_salt_different_hash
- test_different_canonical_different_hash
- test_output_length_16
- test_output_is_lowercase_hex

### `test_artifact_path_safety.py`
- test_safe_batch_id_alphanumeric
- test_safe_batch_id_with_dot_dash_underscore
- test_safe_batch_id_rejects_forward_slash
- test_safe_batch_id_rejects_backslash
- test_safe_batch_id_rejects_dot_dot
- test_safe_batch_id_rejects_single_dot
- test_safe_batch_id_rejects_empty
- test_safe_batch_id_rejects_over_128_chars
- test_safe_batch_artifact_dir_correct_path
- test_safe_batch_artifact_dir_returns_none_for_unsafe_batch
- test_safe_batch_artifact_file_default_json_suffix
- test_safe_batch_artifact_file_rejects_other_suffix
- test_safe_batch_artifact_file_returns_none_for_unsafe_batch

### `test_phase2_case_id.py`
- test_id_format_prefix_family_unit
- test_id_stable_under_ref_order_change
- test_id_changes_with_evidence_signature
- test_id_changes_with_batch_id
- test_id_changes_with_family
- test_id_changes_with_unit_type
- test_id_uses_sha1_truncated_10

### `test_phase2_case_hash.py`
- test_raw_hash_excludes_phase1_case_refs_default
- test_raw_hash_invariant_under_with_phase1_refs
- test_linked_hash_payload_contains_sorted_phase1_case_refs
- test_linked_hash_changes_when_phase1_refs_set_changes
- test_linked_hash_invariant_under_input_order
- test_raw_hash_function_separate_from_linked
- test_raw_hash_deterministic_repeat

### `test_phase2_row_ref.py`
- test_phase2_row_ref_frozen
- test_phase2_row_ref_company_code_optional
- test_make_row_ref_helper_basic
- test_line_number_key_preserves_dtype_difference_until_s4
- test_line_number_key_nan_collapses_to_none
- test_line_number_key_none_passthrough
- test_line_number_key_pd_na_collapses_to_none
- test_phase2_case_base_with_phase1_refs_returns_sorted
- test_phase2_case_set_iter_all_cases_sorted
- test_phase2_case_set_with_phase1_refs_sets_linked_true

## Invariants (S1 통과 조건)

1. canonicalize 결과는 환경 무관 (Windows/Linux, pandas/numpy 버전 무관)
2. pseudonymize 는 None / "" / 공백전용 salt 거부
3. raw_hash payload 에 `phase1_case_refs` 키 부재 (default () 라도)
4. linked_hash payload 의 `phase1_case_refs` 는 정렬된 list (입력 순서 무관)
5. line_number_key 정규화 미적용 — "0001" ≠ 1 보존
6. safe_batch_artifact_file 은 S1 테스트만 존재, 호출처 없음
7. case_id 는 ref 순서/임계 변경에 무관, signature/batch_id/family/unit_type 변경에 반응
8. raw/linked hash 함수 완전 분리 (raw 가 linked 의 sub-routine 으로 호출 안 됨)

## S2 — duplicate + unsupervised builders (parallel-ready)

### File targets
```
src/services/phase2_duplicate_case_builder.py        (Agent C)
src/services/phase2_unsupervised_case_builder.py     (Agent D)
tests/modules/test_services/test_phase2_duplicate_case_builder.py
tests/modules/test_services/test_phase2_unsupervised_case_builder.py
```

S1 helper (contract boundary, 모든 builder 공통):
- `make_phase2_case_id` — canonical_refs 검증 통과 필수
- `canonicalize_ref_key` — row_ref index_label / canonical_refs 입력 정규화
- `make_row_ref` — Phase2RowRef 생성 (line_number_key canonicalize 포함)
- `DuplicateCase` / `UnsupervisedCase` — frozen sub-class

### Module signatures

#### `phase2_duplicate_case_builder.py`
```python
def build_duplicate_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,      # track_name == "duplicate"
    df: pd.DataFrame,                       # GL frame, df.index 가 detection 결과 join 키
) -> tuple[DuplicateCase, ...]:
    """detector metadata['pair_artifact']['top_pairs'] 를 DuplicateCase tuple 로 변환.

    Gate: classify_pair_evidence_tier(features) in {strong, moderate}
    Weak / pair_artifact 미존재 → 빈 tuple graceful fallback.

    각 pair 마다:
    - left_ref / right_ref = make_row_ref(...) 로 Phase2RowRef 생성
      (row_position=df.index.get_loc(label), index_label=label,
       document_id=df['document_id'].iloc[pos] or None,
       raw_line_number=df['line_number'].iloc[pos] (있을 시) else None,
       company_code=df['company_code'].iloc[pos] (있을 시) else None)
    - canonical_refs = (canonicalize_ref_key(left.index_label), canonicalize_ref_key(right.index_label))
    - evidence_signature = f"sub_rule={pair['rule_id']}" (raw 금액/score 포함 금지)
    - case_id = make_phase2_case_id(batch_id, "duplicate", "pair", canonical_refs, evidence_signature)
    - family_score = pair['pair_score']
    - family_ecdf = 본 builder 에서는 미산출 (0.0). ECDF 는 S3 store 에서 외부 결합 또는 별도 계산.
    - case_generation_reason = {"gate": "evidence_tier_" + tier, "pair_evidence_tier": tier}
    """
```

#### `phase2_unsupervised_case_builder.py`
```python
def build_unsupervised_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,      # track_name == "ml_unsupervised"
    df: pd.DataFrame,
    model_id: str,                          # training_report 식별자
    schema_hash: str,                       # training_report.schema_hash
    ecdf_gate: float = 0.95,
) -> tuple[UnsupervisedCase, ...]:
    """detector.details (ML02_top_feature_*) + detector.scores 를 UnsupervisedCase 로 변환.

    Gate: family_ecdf >= ecdf_gate (기본 0.95)
    빈 details / scores → 빈 tuple graceful fallback.

    각 통과 row 마다:
    - row_ref = make_row_ref(...) from df row at label
    - canonical_refs = (canonicalize_ref_key(label),)
    - evidence_signature = f"model={model_id}|schema={schema_hash}"
    - case_id = make_phase2_case_id(batch_id, "unsupervised", "row", canonical_refs, evidence_signature)
    - family_score = float(scores[label])
    - family_ecdf = float(computed_ecdf[label])
    - case_generation_reason = {"gate": "unsupervised_ecdf_q95", "ecdf": family_ecdf}
    - evidence: anomaly_score / top_features (최대 3개, resolve_tag 통과) / model_id / schema_hash

    top_features 추출 규칙 (phase2_case_family_aggregator 의 패턴 재사용):
    - 컬럼 `ML02_top_feature_{1..3}` 와 동반 `_contrib` 컬럼
    - resolve_tag(feature_name) → {tag, label_ko, evidence_type}
    - NaN/empty feature_name 은 skip
    """
```

### Test names

#### `test_phase2_duplicate_case_builder.py`
- test_empty_metadata_returns_empty_tuple
- test_pair_artifact_missing_returns_empty_tuple
- test_top_pairs_empty_returns_empty_tuple
- test_weak_tier_pairs_excluded
- test_strong_tier_pair_included
- test_moderate_tier_pair_included
- test_case_id_uses_canonicalized_refs
- test_evidence_signature_contains_only_sub_rule
- test_evidence_signature_does_not_include_pair_score
- test_phase1_case_refs_empty_by_default
- test_row_refs_built_from_df_row_position
- test_id_stable_under_pair_order_in_top_pairs

#### `test_phase2_unsupervised_case_builder.py`
- test_empty_details_returns_empty_tuple
- test_empty_scores_returns_empty_tuple
- test_row_below_ecdf_gate_excluded
- test_row_at_ecdf_gate_included
- test_top_features_extracted_from_ml02_columns
- test_top_features_skips_nan_or_empty_feature_name
- test_top_features_includes_resolve_tag_label_ko
- test_case_id_includes_model_and_schema_in_signature
- test_case_id_uses_canonicalized_row_label
- test_family_ecdf_field_matches_computed_ecdf
- test_phase1_case_refs_empty_by_default

### Invariants (S2 통과 조건)

11. builder 출력은 항상 `tuple[CaseSubclass, ...]` (list 아님). Phase2CaseSet 의 family-typed tuple 에 직접 들어가야 함.
12. canonical_refs 는 항상 `canonicalize_ref_key` 통과 후 `make_phase2_case_id` 에 전달.
13. evidence_signature 에 raw 금액 / pair_score / anomaly_score 포함 금지 — case identity 만.
14. builder 자체에서 PHASE1 입력 (priority_score / composite_sort_score / rule hit) 접근 금지. detection_result + df + (model_id/schema_hash) 만 사용.
15. weak / below-gate evidence 는 case 화하지 않음 (성능·UX). 통계는 lane summary 에서 별도.
16. detector metadata 부재 시 graceful empty tuple (예외 던지지 않음).
17. `phase1_case_refs` 는 default `()` (linker S4 가 부착).

## S3 — phase2_case_store (save / load)

본 단계는 store 만 다룬다. orchestrator (builder 결과 → Phase2CaseSet 조립) 와
`run_phase2_inference` 통합은 S3.next / S4 와 함께 별도 후속 작업.

### File targets
```
src/services/phase2_case_store.py
tests/modules/test_services/test_phase2_case_store.py
```

### 디렉토리 구조 (save 산출)
```
<engagement_dir>/phase2_cases/<batch_id>/
├── manifest.json
├── row_ref_map.jsonl                    # 1 줄 = 1 unique row_position
├── duplicate.jsonl                       # 1 줄 = 1 case (비어있으면 미생성)
├── intercompany.jsonl
├── relational.jsonl
├── unsupervised.jsonl
└── timeseries.jsonl
```

### manifest.json schema
```json
{
  "schema_version": "1.0",
  "batch_id": "<safe>",
  "written_at": "<ISO>",
  "row_count": <int>,                              // row_ref_map 총 entry 수
  "case_counts": {"duplicate": N, ...},
  "row_ref_map_hash": "sha256:<hex>",
  "key_mode": "label" | "doc_line" | "position",   // engagement 별 식별자 신뢰도
  "raw_case_hash": "sha256:<hex>",                 // compute_raw_case_hash(case_set)
  "linked_case_hash": null | "sha256:<hex>",       // case_set.linked == False → null
  "phase2_training_report_id": "<id>|null",
  "phase2_partition": "<partition>|null"
}
```

### row_ref_map.jsonl 각 줄
```json
{
  "position": <int>,                       // unique key per engagement
  "canonical_label_hash": "<hex>",         // hash_ref_key(canonicalize_ref_key(index_label), salt=...)
  "doc_id_hash": "<hex>" | null,           // hash_ref_key(document_id, salt=...) — None 이면 null
  "company_code_hash": "<hex>" | null,
  "line_number_key": "<canonical>" | null  // hash 안 함 (저민감도). canonicalize_ref_key 결과 그대로
}
```

### family.jsonl 각 줄
`_case_to_canonical_dict(case)` 결과를 한 줄로 직렬화. `case_set.linked == False` 면
`_RAW_HASH_EXCLUDED_FIELDS` 제외 (phase1_case_refs 부재). linked 일 때는 정렬된 list 포함.

### Module signatures

```python
class CaseStoreStatus:
    SAVED = "saved"
    LOAD_SUCCESS = "load_success"
    MISSING = "missing"
    SCHEMA_MISMATCH = "schema_mismatch"
    BATCH_ID_MISMATCH = "batch_id_mismatch"
    INVALID_PAYLOAD = "invalid_payload"
    UNSAFE_BATCH_ID = "unsafe_batch_id"
    CTX_MISSING = "ctx_missing"
    SALT_MISSING = "salt_missing"

@dataclass(frozen=True)
class Phase2CaseStoreResult:
    status: str
    manifest_path: Path | None
    case_set: Phase2CaseSet | None = None
    raw_case_hash: str | None = None
    linked_case_hash: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def save_phase2_case_set(
    *,
    ctx: Any,                                       # CompanyContext (db_path attribute)
    batch_id: str,
    case_set: Phase2CaseSet,
    salt: str,                                      # engagement-scoped, 빈/공백 → SALT_MISSING
    key_mode: str = "label",                        # label / doc_line / position
    phase2_training_report_id: str | None = None,
    phase2_partition: str | None = None,
) -> Phase2CaseStoreResult: ...


def load_phase2_case_set(
    *,
    ctx: Any,
    batch_id: str,
) -> Phase2CaseStoreResult: ...
```

### Test names (`test_phase2_case_store.py`)

#### save
- test_save_creates_phase2_cases_directory_under_engagement
- test_save_writes_manifest_with_required_fields
- test_save_writes_family_jsonl_for_each_nonempty_family
- test_save_skips_jsonl_for_empty_family
- test_save_writes_row_ref_map_with_dedup_by_position
- test_save_row_ref_map_pseudonymizes_doc_id_with_salt
- test_save_row_ref_map_pseudonymizes_company_code_with_salt
- test_save_row_ref_map_preserves_line_number_key_unhashed
- test_save_returns_unsafe_batch_id_status_for_path_traversal
- test_save_returns_salt_missing_for_whitespace_salt
- test_save_returns_ctx_missing_when_db_path_absent
- test_save_manifest_raw_case_hash_matches_compute_raw_case_hash
- test_save_manifest_linked_case_hash_null_when_not_linked
- test_save_manifest_linked_case_hash_set_when_linked

#### load
- test_load_returns_missing_for_nonexistent_batch
- test_load_returns_schema_mismatch_for_wrong_schema_version
- test_load_returns_batch_id_mismatch_for_inconsistent_manifest
- test_load_returns_invalid_payload_for_corrupt_jsonl
- test_load_roundtrip_preserves_case_count_per_family
- test_load_roundtrip_preserves_case_ids
- test_load_preserves_phase1_case_refs_when_linked
- test_load_row_refs_have_canonical_string_index_label

### Invariants (S3 통과 조건)

18. row_ref_map.jsonl 의 doc_id / company_code / canonical_label 모두 `hash_ref_key` 통과 — raw 원문 부재.
19. line_number_key 는 hash 안 함 (저민감도, S4 정규화 키 보존 필요).
20. manifest.raw_case_hash == `compute_raw_case_hash(case_set)` (정합).
21. case_set.linked == False → manifest.linked_case_hash is null.
22. case_set.linked == True → manifest.linked_case_hash == `compute_linked_case_hash(case_set)`.
23. 빈 family 는 jsonl 미생성 (디스크 절약).
24. salt 가 None / "" / whitespace-only → status=SALT_MISSING (실제 hash 호출 전 검증).
25. unsafe batch_id → status=UNSAFE_BATCH_ID, manifest_path=None.
26. ctx 가 None 또는 db_path 부재 → status=CTX_MISSING.
27. load 후 `Phase2RowRef.index_label` 은 canonical string (e.g., `"ts:..."`). 원본 raw 타입 복원 안 함.
28. row_ref_map.jsonl 의 entry 는 unique position 기준 dedup (동일 position 여러 case 에 등장해도 1 줄).

### 사용 helper

- `src.services.artifact_path_safety.safe_batch_artifact_dir(engagement_dir, batch_id)` — 디렉토리 경로
- `src.services.phase2_ref_pseudonymize.hash_ref_key(canonical_key, salt=...)` — 식별자 hash
- `src.services.phase2_ref_canonical.canonicalize_ref_key(value)` — 새로 canonicalize 필요 시 (row_ref 의 index_label 은 이미 canonical 화되어 있음)
- `src.services.phase2_case_hash._case_to_canonical_dict / compute_raw_case_hash / compute_linked_case_hash` — case 직렬화 / hash 산출

## S4 — phase2_case_phase1_linker (cross-reference)

### File targets
```
src/services/phase2_case_phase1_linker.py
tests/modules/test_services/test_phase2_case_phase1_linker.py
```

### Scope (S4 MVP)
- **Position equality** primary matching: PHASE1 `RawRuleHitRef.row_index` (positional) ==
  PHASE2 `Phase2RowRef.row_position`. 둘 다 동일 df 에서 산출되므로 직접 비교.
- doc_line / label fallback 은 S4.next 결정 항목 (line_number normalization 포함).
- `Phase2CaseSet.with_phase1_refs(refs_by_case_id)` 헬퍼 재사용 → linked=True 산출.
- PHASE1 `priority_score` / `priority_rank` / `composite_sort_score` 변경 0건 (회귀 가드).
- PHASE2 `family_score` / `family_ecdf` / `case_generation_reason` 변경 0건.

### Module signatures

```python
@dataclass(frozen=True)
class LinkerResult:
    case_set: Phase2CaseSet              # linked=True (or 빈 case_set 경우 그대로)
    diagnostics: dict[str, Any]          # match counts, key_mode_used, ...


def link_phase2_to_phase1(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
) -> LinkerResult:
    """PHASE2 case ↔ PHASE1 case_id cross-reference via row_position 등가.

    Algorithm (Δ19 lazy two-pass inverse index):
    1. Pass 1 — needed_positions 수집:
         PHASE2 case_set.iter_all_cases_sorted() 의 row_refs[*].row_position
         + DuplicateCase.left_ref/right_ref.row_position
       (PHASE1 raw_rule_hits 위치는 phase1 순회에서 직접 사용, dedup 불필요)
    2. Pass 2 — position → set[phase1_case_id] inverse index 구축 (Phase1 순회):
         for each phase1_case:
             for hit in phase1_case.raw_rule_hits:
                 if hit.row_index in needed_positions:
                     index[hit.row_index].add(phase1_case.case_id)
    3. Pass 3 — refs_by_case_id 조립:
         for each phase2 case:
             matched = {pid for ref in case.row_refs for pid in index.get(ref.row_position, set())}
             matched |= (DuplicateCase 의 left/right_ref 도 포함)
             if matched:
                 refs_by_case_id[case.phase2_case_id] = tuple(sorted(matched))
    4. case_set.with_phase1_refs(refs_by_case_id) 반환.

    PHASE1/PHASE2 priority/score 모두 read-only. linker 는 cross-reference 만 부착.
    """
```

### Test names (`test_phase2_case_phase1_linker.py`)

- test_empty_case_set_returns_empty_linked
- test_empty_phase1_returns_case_set_with_no_refs
- test_position_match_creates_phase1_case_refs
- test_no_position_overlap_returns_empty_phase1_refs
- test_multiple_phase1_cases_overlap_returns_sorted_refs
- test_linker_returns_case_set_with_linked_true
- test_linker_preserves_phase1_priority_score (회귀 가드)
- test_linker_preserves_phase2_family_score (회귀 가드)
- test_linker_preserves_phase2_case_generation_reason (회귀 가드)
- test_linker_idempotent_when_case_set_already_linked (재호출 안전성)
- test_linker_diagnostics_includes_match_counts
- test_phase1_case_refs_sorted_alphabetically_in_tuple
- test_duplicate_case_left_ref_position_matches_phase1
- test_duplicate_case_right_ref_position_matches_phase1
- test_phase2_cases_without_phase1_overlap_keep_empty_refs

### Invariants (S4 통과 조건)

33. linker 호출 후 `phase1.cases[*].priority_score` / `priority_rank` / `composite_sort_score` 변경 없음.
34. linker 호출 후 PHASE2 case 의 `family_score` / `family_ecdf` / `case_generation_reason` 변경 없음 (with_phase1_refs 만 적용).
35. position 매칭이 0 인 case 는 `phase1_case_refs = ()` 유지 (linked=True 만 set).
36. `phase1_case_refs` 는 정렬된 tuple — input 순서 무관.
37. linker 는 PHASE2 case_set 의 row_refs / left_ref / right_ref 모두 포함하여 매칭 (DuplicateCase 의 pair 양쪽 모두 cross-reference 대상).
38. linker 는 idempotent — 이미 linked 된 case_set 재호출 시 동일 결과 (refs 동일 set).

### Helpers (re-use)

```python
from src.models.phase1_case import Phase1CaseResult, RawRuleHitRef
from src.models.phase2_case import (
    DuplicateCase, Phase2CaseBase, Phase2CaseSet, Phase2RowRef,
)
```

### Deferred to S4.next

- label primary / doc_line fallback matching (현 MVP 는 position equality 만).
- line_number_key 정규화 결정 (`normalize_line_number_key` 도입 vs 보존).
- row_ref_map.jsonl 활용 (외부 source 의 position → label hash 매핑).
- PHASE1 → PHASE2 역방향 cross-reference index (`build_phase1_phase2_cross_ref_map`).

## S4.next — doc_id fallback + line_number normalize

### 설계 근거
position-only 의 약점은 PHASE1 ↔ PHASE2 가 다른 df frame 일 때 (store reload,
df.sort_values / reset_index, multi-company concat). 가장 robust 한 stable
identifier 는 `document_id`:
- `RawRuleHitRef.document_id` — PHASE1 측 보유 (str)
- `Phase2RowRef.document_id` — PHASE2 측 보유 (str | None, make_row_ref 단계 캐시)
둘을 직접 비교 → row order / position 변형 무관. multi-company 환경에서는
(company_code, document_id) 페어가 필요하지만 본 단계는 single-company 한정,
multi-company 는 S4.next.2 로 유예.

### 매칭 의미 (lock)
- `position`: precise row-level. PHASE1 hit row_index == PHASE2 row_ref row_position.
- `doc_id`: document-level. PHASE1 hit document_id == PHASE2 row_ref document_id.
  같은 document 의 다른 row 도 cross-reference (감사 도메인에서 의도된 looser
  매칭 — 한 document 에 의심 신호와 anomaly 가 함께 있으면 같이 봐야 함).
- `auto`: PHASE2 row_refs 가 모두 document_id 가용하면 `doc_id`, 그렇지 않으면
  `position` fallback. 호출자가 `key_mode` 결정 책임 회피용.

### File targets
```
src/services/phase2_ref_canonical.py                       (normalize_line_number_key 추가)
src/services/phase2_case_phase1_linker.py                  (key_mode dispatching 확장)
tests/modules/test_services/test_phase2_ref_canonical.py   (normalize helper 테스트)
tests/modules/test_services/test_phase2_case_phase1_linker.py (key_mode 테스트)
```

### Module signatures

```python
# phase2_ref_canonical.py — 신규 헬퍼
def normalize_line_number_key(canonical_key: str | None) -> str | None:
    """canonicalize_ref_key 결과를 dtype-agnostic 으로 정규화.

    회계 도메인에서 "0001" 과 1 과 1.0 은 같은 line 의미. dtype 차이를 흡수해
    cross-reference 매칭률 상승. S4.next 이후 doc_line key_mode 에서 사용.

    "s:0001" → "1"
    "s:0010" → "10"
    "i:1"    → "1"
    "f:1.0"  → "1"
    "n:"     → None
    None     → None
    "s:abc"  → "abc"  (숫자 아니면 prefix 만 제거)
    """


# phase2_case_phase1_linker.py — 시그니처 확장
def link_phase2_to_phase1(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    key_mode: str = "auto",   # "position" | "doc_id" | "auto"
) -> LinkerResult:
    """key_mode dispatch:
      - "position": S4 MVP. row_position 등가. fresh in-memory same-batch 한정.
      - "doc_id": document_id 등가. reload / df 변형 후에도 안전.
      - "auto": PHASE2 row_refs 가 모두 document_id 보유하면 "doc_id",
                 아니면 "position" fallback. 호출자 default.

    LinkerResult.diagnostics["key_mode_used"] 에 실제 사용한 mode 기록.
    """
```

### Test names

#### `test_phase2_ref_canonical.py` — `normalize_line_number_key` (+8)
- test_normalize_line_number_key_string_zero_padded → "1"
- test_normalize_line_number_key_string_zero_padded_double_digit → "10"
- test_normalize_line_number_key_int_prefix → "1"
- test_normalize_line_number_key_float_one_point_zero → "1"
- test_normalize_line_number_key_null_canonical_returns_none
- test_normalize_line_number_key_none_passthrough
- test_normalize_line_number_key_non_numeric_string_keeps_value
- test_normalize_line_number_key_empty_canonical_returns_none

#### `test_phase2_case_phase1_linker.py` — key_mode (+10)
- test_doc_id_mode_matches_via_document_id
- test_doc_id_mode_matches_across_different_positions (reload 시나리오 — position 다름, doc_id 같음)
- test_doc_id_mode_excludes_phase2_refs_without_document_id
- test_doc_id_mode_excludes_phase1_hits_without_document_id
- test_doc_id_mode_diagnostics_records_key_mode_used
- test_auto_mode_falls_back_to_position_when_some_phase2_refs_lack_document_id
- test_auto_mode_uses_doc_id_when_all_phase2_refs_have_document_id
- test_auto_mode_diagnostics_records_resolved_key_mode
- test_position_mode_explicit_still_works (회귀)
- test_invalid_key_mode_raises_value_error

### Invariants (S4.next 통과 조건)

39. `key_mode="position"` 동작은 S4 MVP 와 정확히 동일 — 기존 15+3 회귀 테스트 통과 유지.
40. `key_mode="doc_id"` 는 document_id 등가만 사용. row_position / line_number_key 무시.
41. `key_mode="auto"` 는 결정 결과를 `LinkerResult.diagnostics["key_mode_used"]` 에 기록 ("doc_id" 또는 "position").
42. `key_mode="auto"` 가 doc_id 선택하려면 **모든** PHASE2 case 의 row_refs 가 document_id 가용. 하나라도 None 이면 position fallback.
43. `normalize_line_number_key` 는 idempotent: `normalize(normalize(x)) == normalize(x)`.
44. invalid key_mode 입력 → ValueError 즉시 (silent fallback 금지).

### Deferred to S4.next.2

- `company_doc` key_mode (multi-company engagement)
- `label` key_mode + row_ref_map.jsonl hash 비교 (cross-engagement / out-of-process)
- doc_line key_mode (`document_id` + `normalize_line_number_key`) — line-level robust 매칭
- bidirectional cross-ref index (PHASE1 → PHASE2 방향)
- pipeline attach (run_phase2_inference 통합) — 본 S4.next 완료 후 unblock

## S4.next.2 — doc_line / company_doc / label modes + pipeline attach unlock

### 설계 근거
S4.next 의 `doc_id` mode 는 document-level cross-reference 만 가능 (같은 doc 의
다른 line 도 link). row-precise evidence (duplicate pair, VAE outlier) 에 false
positive. 이 단계는 `row_ref_map.jsonl` 의 hash 식별자를 활용해 **line-level /
multi-company / canonical-label** 매칭을 추가, pipeline attach 차단을 해제한다.

### 매칭 의미 (lock)
- `doc_line`: (document_id_hash, normalized line_number_key) — line-level precision.
  multi-line 전표 안에서 정확한 row 매칭. row_ref_map + salt 필요.
- `company_doc`: (company_code_hash, document_id_hash) — multi-company concat
  환경에서 회사 disambiguation. row_ref_map + salt 필요.
- `label`: canonical_label_hash 직접 비교 — 가장 robust. row_ref_map + salt 필요.

`row_ref_map` 은 PHASE2 store 가 저장한 `<engagement_dir>/phase2_cases/<batch_id>/row_ref_map.jsonl`
의 entries (position → hash 식별자) 그대로. salt 는 store 가 사용한 engagement-scoped
salt 와 동일.

### File targets
```
src/services/phase2_case_phase1_linker.py        (3 새 mode 추가)
src/services/phase2_case_store.py                (key_mode enum 확장)
tests/modules/test_services/test_phase2_case_phase1_linker.py
tests/modules/test_services/test_phase2_case_store.py
```

### Module signatures

```python
def link_phase2_to_phase1(
    *,
    case_set: Phase2CaseSet,
    phase1: Phase1CaseResult,
    row_ref_map: list[dict[str, Any]] | None = None,  # row_ref_map.jsonl entries
    salt: str | None = None,                           # engagement-scoped salt
    key_mode: str = "auto",
) -> LinkerResult:
    """key_mode dispatch (S4.next.2 확장):
      - "position": S4 MVP
      - "doc_id":   S4.next (document-level, looser)
      - "doc_line": S4.next.2 (line-level via row_ref_map) — row_ref_map+salt 필수
      - "company_doc": S4.next.2 (multi-company) — row_ref_map+salt 필수
      - "label":    S4.next.2 (canonical hash) — row_ref_map+salt 필수
      - "auto":     row_ref_map+salt 가용하면 label, 아니면 doc_id, 아니면 position
    """
```

### 새 ALLOWED key_mode (linker + store sync)
- linker `_ALLOWED_KEY_MODES`: `{"position", "doc_id", "doc_line", "company_doc", "label", "auto"}`
- store `_STORE_ALLOWED_KEY_MODES`: `{"position", "doc_id", "doc_line", "company_doc", "label"}` ("auto" 는 resolution 결과만 저장)

### Auto resolution 우선순위 (가장 strict → 약한 순)
1. `label` — row_ref_map + salt 가용 (가장 strict, row-precise)
2. `doc_id` — row_ref_map 없지만 PHASE2 ref 들이 모두 document_id 가용
3. `position` — fallback (in-memory same-batch 한정)

### Match precision matrix

| mode | match_precision |
|---|---|
| `position` | `"row"` |
| `label` | `"row"` |
| `doc_line` | `"row"` |
| `company_doc` | `"document"` |
| `doc_id` | `"document"` |

### Validation rules
- `key_mode="doc_line"` / `"company_doc"` / `"label"` 명시 시 `row_ref_map` + `salt` 모두 필수. 누락 시 ValueError.
- `key_mode="auto"` 가 label 분기하려면 `row_ref_map` + `salt` 모두 가용. 아니면 doc_id / position 분기.

### Test names (대표)

#### linker (+15 대표)
- test_doc_line_mode_requires_row_ref_map
- test_doc_line_mode_requires_salt
- test_doc_line_mode_matches_via_doc_and_normalized_line
- test_doc_line_mode_distinguishes_lines_in_same_document  (row-precise 검증)
- test_company_doc_mode_requires_row_ref_map_and_salt
- test_company_doc_mode_matches_via_company_and_doc
- test_company_doc_mode_disambiguates_across_companies
- test_label_mode_requires_row_ref_map_and_salt
- test_label_mode_matches_via_canonical_label_hash
- test_label_mode_returns_row_precision_in_diagnostics
- test_auto_resolves_to_label_when_row_ref_map_and_salt_available
- test_auto_falls_back_to_doc_id_without_row_ref_map_when_doc_ids_present
- test_auto_falls_back_to_position_without_row_ref_map_or_doc_ids
- test_match_precision_row_for_label_doc_line_position
- test_match_precision_document_for_doc_id_company_doc

#### store (+3 대표)
- test_save_accepts_doc_line_key_mode
- test_save_accepts_company_doc_key_mode
- test_save_accepts_label_key_mode

### Invariants (S4.next.2 통과 조건)

45. `doc_line` / `company_doc` / `label` 호출 시 row_ref_map + salt 누락 → ValueError 즉시.
46. `doc_line` / `label` mode 는 같은 document 의 다른 line 을 구별 — row-precise 검증.
47. `company_doc` mode 는 다른 회사 간 같은 document_id 를 다르게 매칭 — multi-company disambiguation.
48. auto resolution 우선순위: label > doc_id > position (row_ref_map + salt 가용성).
49. store `_STORE_ALLOWED_KEY_MODES` 와 linker `_ALLOWED_KEY_MODES` (minus "auto") 동기화.

### Pipeline attach unblock 조건
- linker 가 `doc_line` / `company_doc` / `label` 중 하나로 호출 가능하면 unblock.
- `position` / `doc_id` 단독 사용은 여전히 in-memory same-batch 한정 (docstring 명시).
- 모듈 docstring 의 "pipeline attach 차단" 정책 정정.

## S5 — IC matcher metadata 확장 + IC case builder

### 두 phase

**Phase A — IC matcher metadata 확장** (`src/detection/intercompany_matcher.py`):
- 기존 row 단위 score / details / row_sidecar / probabilistic_reconciliation /
  reciprocal_flow metadata 변경 없음 (회귀 0).
- 새 metadata key `ic_pair_artifact` 추가 (duplicate `pair_artifact` 패턴):
  ```python
  {
      "schema_version": 1,
      "candidate_pairs": [...],   # 매칭된 pair (left_index, right_index, score, components)
      "unmatched_rows": [...],    # IC01 unmatched — row_sidecar sanitized projection
      "mismatch_pairs": [...],    # IC02 amount mismatch (left, right, amount_a, amount_b, ratio, severity)
      "reciprocal_pairs": [...],  # 단일 document 의 receivable+payable reciprocal flow
      "coverage": {...},          # IC row 수 / 매칭 가용성 통계
  }
  ```
- 도메인 정당화 인용 (ISA 550 ¶A20 + PCAOB AS 2401 §B7) — truth recall 조정
  압력 차단 (D044 PR 템플릿).

**Phase B — IC case builder** (`src/services/phase2_intercompany_case_builder.py`):
- 입력: `DetectionResult` (track_name="intercompany") + `df`
- 출력: `tuple[IntercompanyCase, ...]`
- contract boundary: S1 helper (make_phase2_case_id / canonicalize_ref_key / make_row_ref)
- Gate (Δ5): `ic_role ∈ {reciprocal_flow, amount_mismatch}` — weak no_candidate /
  timing_gap 단독은 case 화 안 함 (정상 단방향 거래 / cut-off 차이 구분 어려움).

### File targets
```
src/detection/intercompany_matcher.py                  (Phase A — metadata 확장)
src/services/phase2_intercompany_case_builder.py       (Phase B — 신규)
tests/modules/test_detection/test_intercompany_matcher_pair_artifact.py
tests/modules/test_services/test_phase2_intercompany_case_builder.py
```

기존 IC matcher 테스트 파일이 있으면 그대로 두고 별도 파일로 artifact 검증 분리.

### Module signatures

```python
# Phase A — IC matcher 내부 (intercompany_matcher.py 에 추가)
@dataclass
class IntercompanyPairArtifact:
    schema_version: int = 1
    candidate_pairs: list[dict[str, Any]] = field(default_factory=list)
    unmatched_rows: list[dict[str, Any]] = field(default_factory=list)
    mismatch_pairs: list[dict[str, Any]] = field(default_factory=list)
    reciprocal_pairs: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: ...

def build_intercompany_pair_artifact(
    df: pd.DataFrame,
    pair_map: dict,
    match_df: pd.DataFrame,
    prob_scores: pd.DataFrame,
    prob_summary: dict,
    reciprocal_scores: pd.DataFrame,
    reciprocal_summary: dict,
    rule_results: dict[str, pd.Series],
    sidecar_columns: dict[str, pd.Series],
    settings,
) -> IntercompanyPairArtifact:
    """매칭 / mismatch / reciprocal / unmatched 4종 sanitized artifact 구축.
    각 entry 의 index 는 df.index label (json-safe), 식별자는 raw 값.
    """
```

```python
# Phase B — IC case builder
def build_intercompany_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,  # track_name == "intercompany"
    df: pd.DataFrame,
) -> tuple[IntercompanyCase, ...]:
    """ic_pair_artifact 의 reciprocal_pairs + mismatch_pairs → IntercompanyCase.

    Gate: ic_role ∈ {reciprocal_flow, amount_mismatch}. unmatched_rows / timing
    단독은 case 화하지 않음 (weak evidence).
    각 case:
      - unit_type: "pair" (reciprocal_pairs / mismatch_pairs 둘 다)
      - canonical_refs: row_refs 의 index_label tuple (이미 canonical)
      - evidence_signature: f"ic_role={ic_role}" (raw 금액/score 미포함)
      - row_refs: (left, right) — make_row_ref 통과
    """
```

### Phase A 도메인 정합

각 artifact 의 audit standard 인용 (모듈 docstring + 함수 docstring):
- `reciprocal_pairs` — ISA 550 ¶A20 (양방향 reconciliation), PCAOB AS 2401 §B7
  (intercompany unusual journal entries). 단일 document 내 receivable+payable
  동시 + amount symmetry ≥ 0.95 → strong evidence.
- `mismatch_pairs` — ISA 550 ¶A20 보조 + AS 2401 .A6 (3) (금액 mismatch 는
  의도성 증거 보강).
- `unmatched_rows` — ISA 550 ¶A20 보조 + AS 2401 §B7 (no_candidate 는 weak —
  정상 단방향 거래와 구분 어려움).
- `candidate_pairs` — debugging / 운영 가시화 용도. case generation 직접 사용 안 함.

### Test names

#### Phase A (`test_intercompany_matcher_pair_artifact.py`, +8)
- test_artifact_contains_all_four_artifact_lists_when_ic_rows_present
- test_artifact_empty_when_ic_rows_below_threshold
- test_reciprocal_pairs_extracted_for_single_document_with_receivable_payable
- test_mismatch_pairs_extracted_for_amount_mismatch_with_ratio
- test_unmatched_rows_extracted_from_ic01_evidence_level
- test_candidate_pairs_index_labels_are_json_safe
- test_artifact_schema_version_pinned_to_1
- test_artifact_metadata_does_not_change_row_scores_or_details

#### Phase B (`test_phase2_intercompany_case_builder.py`, +12)
- test_empty_metadata_returns_empty_tuple
- test_ic_pair_artifact_missing_returns_empty_tuple
- test_reciprocal_pairs_emit_ic_role_reciprocal_flow
- test_mismatch_pairs_emit_ic_role_amount_mismatch
- test_unmatched_rows_excluded_from_case_generation (Gate)
- test_timing_only_pairs_excluded_from_case_generation (Gate)
- test_case_id_uses_canonicalized_row_refs
- test_evidence_signature_contains_only_ic_role
- test_evidence_signature_does_not_include_raw_amount
- test_phase1_case_refs_empty_by_default
- test_row_refs_built_from_df_row_position
- test_return_type_is_tuple_of_intercompany_case

### Invariants (S5 통과 조건)

52. Phase A — IC matcher 의 기존 row 단위 score / details / row_sidecar / probabilistic_reconciliation / reciprocal_flow metadata 변경 0건. 새 metadata key `ic_pair_artifact` 만 추가.
53. Phase A — `ic_pair_artifact` 의 식별자 (left_index/right_index) 는 `_json_safe` 통과 (duplicate `pair_artifact` 패턴 정합).
54. Phase B — Gate: `ic_role ∈ {reciprocal_flow, amount_mismatch}`. unmatched / timing 단독은 case 화 안 함.
55. Phase B — evidence_signature 는 case identity 만 (`f"ic_role={role}"`). raw 금액 / score / amount_symmetry / ratio 절대 포함 금지.
56. Phase B — PHASE1 prior (priority_score / composite_sort_score / rule hit) 접근 0건.
57. Phase B — 반환 `tuple[IntercompanyCase, ...]`. 빈 metadata / 빈 artifact → 빈 tuple graceful fallback.

### Deferred to S5.next

- IC family 의 `case_generation_reason` 에 audit standard 인용 metadata 추가 (`{"gate": "ic_strong_evidence", "standard": "ISA 550 ¶A20"}`).
- IC family ECDF 계산 (현재 builder 는 family_ecdf=0.0 — S3 store 가 외부 결합 또는 별도 enrichment).
- multi-currency reciprocal_flow (현재는 same-currency 가정).

## S6 — Relational + Timeseries detector artifact + builders

### 두 family 병렬 진행
Relational (R01~R07) 과 Timeseries (TS01~TS02) 는 detector 독립 → 두 agent 병렬:
- **Agent J — Relational**: detector edge_artifact 확장 + RelationalCase builder
- **Agent K — Timeseries**: detector window_artifact 확장 + TimeseriesCase builder

### File targets
```
src/detection/relational_detector.py            (Agent J — edge_artifact)
src/services/phase2_relational_case_builder.py  (Agent J — 신규)
src/detection/timeseries_detector.py            (Agent K — window_artifact)
src/services/phase2_timeseries_case_builder.py  (Agent K — 신규)
tests/modules/test_detection/test_relational_edge_artifact.py
tests/modules/test_detection/test_timeseries_window_artifact.py
tests/modules/test_services/test_phase2_relational_case_builder.py
tests/modules/test_services/test_phase2_timeseries_case_builder.py
```

### Phase A — Relational edge_artifact

새 metadata key `relational_edge_artifact`:
```python
{
    "schema_version": 1,
    "edges": [
        {
            "rule_id": "R01" | "R02" | "R03" | "R04" | "R05" | "R06" | "R07",
            "row_indices": [<json_safe(label)>, ...],
            "row_positions": [int, ...],          # MultiIndex 안전
            "edge_a": str,                         # user_id / trading_partner / counterparty (rule 별 의미)
            "edge_b": str,                         # gl_account (대부분)
            "metric_name": str,                    # "rarity" / "degree_spike_z" / "transfer_pricing_ratio" 등
            "metric_value": float,                 # rule 별 raw score 또는 핵심 metric
            "evidence_tier": "strong" | "moderate" | "weak",
        },
        ...
    ],
    "coverage": {"R01": int, "R02": int, ...},
}
```

기존 row 단위 출력 (scores / details / rule_flags / graph_entity_summary metadata) 변경 0.

### Phase B — Timeseries window_artifact

새 metadata key `timeseries_window_artifact`:
```python
{
    "schema_version": 1,
    "windows": [
        {
            "rule_id": "TS01" | "TS02",
            "subject": str,                         # gl_account 또는 business_process
            "window_start": "YYYY-MM-DD",
            "window_end": "YYYY-MM-DD",
            "row_indices": [<json_safe>, ...],
            "row_positions": [int, ...],
            "daily_count": int,                     # 윈도우 내 transaction count
            "expected_count": float,                # 통계적 기대값
            "z_score": float,                       # robust z 또는 ECDF 기반
            "sub_signal_high": bool,                # detector 결정 — Δ13 spec
            "evidence_tier": "strong" | "moderate" | "weak",
        },
        ...
    ],
    "coverage": {"TS01": int, "TS02": int},
}
```

`sub_signal_high` 는 detector 가 robust_z / ECDF / period-end context gate 종합 후 산출.

### Phase C — RelationalCase builder

```python
def build_relational_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,  # track_name == "relational"
    df: pd.DataFrame,
) -> tuple[RelationalCase, ...]:
    """relational_edge_artifact.edges → RelationalCase tuple.
    Gate (Δ5): evidence_tier == "strong" OR (moderate AND family_ecdf >= 0.95).
    family_ecdf 는 본 builder 에서 0.0 (S3 store 결합 또는 S6.next 별도 enrichment).
    """
```

evidence_signature: `f"sub_rule={rule_id}|edge_a={edge_a}|edge_b={edge_b}"` — case identity 만. metric_value/raw score 포함 금지.

unit_type: `"edge"`.

### Phase D — TimeseriesCase builder

```python
def build_timeseries_cases(
    *,
    batch_id: str,
    detection_result: DetectionResult,  # track_name == "timeseries"
    df: pd.DataFrame,
) -> tuple[TimeseriesCase, ...]:
    """timeseries_window_artifact.windows → TimeseriesCase tuple.
    Gate (Δ13 final): evidence_tier ∈ {strong, moderate} AND sub_signal_high == True.
    """
```

evidence_signature: `f"sub_rule={rule_id}|subject={subject}|window={window_start}"` — case identity 만. z_score/daily_count 포함 금지.

unit_type: `"window"`.

### Row lookup (S5 invariant #59 + #60 정합)
두 builder 모두 `_make_ref_from_position(df, position=...)` 패턴 사용. `df.index[position]` 을 source of truth — artifact 의 `*_indices` 는 display payload.

### Test names (대표, 각 +8~12)

#### `test_relational_edge_artifact.py` (+8)
- test_artifact_contains_edges_and_coverage
- test_artifact_empty_when_no_relational_rules_fired
- test_r05_edge_extracted_with_edge_a_edge_b_and_metric
- test_r06_user_account_degree_spike_edge
- test_edge_row_positions_match_indices
- test_artifact_schema_version_pinned_to_1
- test_existing_row_scores_and_details_unchanged
- test_edge_evidence_tier_assigned_per_rule_severity

#### `test_timeseries_window_artifact.py` (+8)
- test_artifact_contains_windows_and_coverage
- test_artifact_empty_when_no_timeseries_rules_fired
- test_ts01_window_extracted_with_subject_start_end_z
- test_ts02_window_extracted_with_expected_count
- test_window_row_positions_match_indices
- test_sub_signal_high_set_for_strong_evidence
- test_artifact_schema_version_pinned_to_1
- test_existing_row_scores_and_details_unchanged

#### `test_phase2_relational_case_builder.py` (+10)
- test_empty_metadata_returns_empty_tuple
- test_strong_tier_edge_emits_case
- test_moderate_tier_edge_below_q95_filtered_out
- test_weak_tier_edge_excluded
- test_case_id_uses_canonicalized_row_refs
- test_evidence_signature_contains_sub_rule_and_edge_keys
- test_evidence_signature_does_not_include_metric_value
- test_phase1_case_refs_empty_by_default
- test_row_refs_index_label_uses_df_index_canonical_form
- test_return_type_is_tuple_of_relational_case

#### `test_phase2_timeseries_case_builder.py` (+10)
- test_empty_metadata_returns_empty_tuple
- test_strong_tier_with_sub_signal_high_emits_case
- test_strong_tier_without_sub_signal_high_filtered_out
- test_weak_tier_excluded
- test_case_id_uses_canonicalized_row_refs
- test_evidence_signature_contains_sub_rule_subject_window
- test_evidence_signature_does_not_include_z_score
- test_phase1_case_refs_empty_by_default
- test_row_refs_index_label_uses_df_index_canonical_form
- test_return_type_is_tuple_of_timeseries_case

### Invariants (S6 통과 조건)

61. Phase A — Relational detector 의 기존 row 단위 출력 변경 0건. 새 `relational_edge_artifact` 만 추가.
62. Phase B — Timeseries detector 의 기존 row 단위 출력 변경 0건. 새 `timeseries_window_artifact` 만 추가.
63. 두 artifact 의 식별자 (row_indices) 는 `_json_safe` 통과. row_positions 함께 보유 — MultiIndex 안전.
64. Phase C — RelationalCase Gate: strong OR (moderate AND family_ecdf >= 0.95). evidence_signature 는 sub_rule + edge keys 만.
65. Phase D — TimeseriesCase Gate: evidence_tier ∈ {strong, moderate} AND sub_signal_high. evidence_signature 는 sub_rule + subject + window_start.
66. 두 builder 모두 row_refs[*].index_label 은 `df.index[position]` source of truth (invariant #60 정합).
67. 두 builder 모두 PHASE1 prior 접근 0건. phase1_case_refs default `()`.
68. 빈 metadata / 빈 artifact → 빈 tuple graceful fallback.

### Deferred to S6.next

- full-population row_ref_map / PHASE1 별도 row_ref_map / RawRuleHitRef schema 확장 (진짜 cross-batch reload-safety + pipeline attach unlock).
- family_ecdf 외부 결합 / enrichment 정책.

## S6.next — RawRuleHitRef schema 확장 (옵션 C, 사용자 선택)

### 설계 결정 (사용자 lock)
3가지 path (full-population row_ref_map / PHASE1 별도 sidecar / RawRuleHitRef schema 확장) 중 **옵션 C** 채택. PHASE1 결과 자체에 stable identifier 를 포함시켜 linker 가 sidecar 조회 없이 hash 직접 비교 — 가장 architecturally clean + pipeline attach 시 row_ref_map 의존 제거.

### 3 phase 분할
- **Phase 1** (이번): PHASE1 `RawRuleHitRef` schema + 빌더 hash 산출. 기존 PHASE1 테스트 회귀 0.
- **Phase 2** (다음): linker 가 hash 필드 사용. row_ref_map 조회 path 단순화. auto resolution 갱신.
- **Phase 3** (그 다음): pipeline attach unlock 정책 lock 회수.

### Phase 1 — File targets
```
src/models/phase1_case.py                          (RawRuleHitRef schema 확장)
src/detection/phase1_case_builder.py               (hit 생성 시 hash 산출)
tests/modules/test_models/test_phase1_raw_rule_hit_ref.py  (신규)
tests/modules/test_detection/test_phase1_case_builder_hash_fields.py  (신규)
```

### Phase 1 — schema 변경
```python
class RawRuleHitRef(BaseModel):
    # 기존
    rule_id: str
    severity: int
    document_id: str
    row_index: int       # legacy (position)
    record_id: str | None = None
    score: float = 0.0
    signal_strength: float = 0.0
    normalized_score: float = 0.0
    evidence_strength: str = ""
    scoring_role: str = "primary"
    display_label: str = ""
    signal_status: str = "confirmed"
    detail: str | None = None
    evidence_type: str

    # 신규 (S6.next Phase 1) — engagement-scoped stable identifier
    canonical_label_hash: str = ""        # hash_ref_key(canonicalize(df.index[row_index]), salt)
    doc_id_hash: str = ""                 # hash_ref_key(document_id, salt)
    line_number_key: str | None = None    # canonicalize_ref_key(line_number) — normalize 결과
```

기본값 빈 문자열 / None — backward compat (기존 PHASE1 결과 JSON 로드 시 default 적용).

### Phase 1 — 빌더 변경
```python
# phase1_case_builder.py
# hit 생성 시 (df + engagement salt 필요):
canonical_label_hash = hash_ref_key(
    canonicalize_ref_key(df.index[row_pos]),
    salt=engagement_salt,
)
doc_id_hash = hash_ref_key(document_id, salt=engagement_salt) if document_id else ""
raw_line = df["line_number"].iat[row_pos] if "line_number" in df.columns else None
line_number_key = canonicalize_ref_key(raw_line) if raw_line is not None else None
if line_number_key == "n:":
    line_number_key = None
```

`engagement_salt` 는 PHASE1 builder 시그니처에 새 파라미터로 추가 (default `""` 면 hash 산출 skip → 기존 caller backward compat).

### Phase 1 — backward compatibility
- 기존 PHASE1 결과 (JSON) 로드 시 신규 필드 default — 회귀 없음.
- 기존 PHASE1 빌더 호출자가 salt 안 넘기면 신규 필드 빈 문자열 — `model_config(extra="forbid")` 와 충돌 안 함.
- 신규 caller (S6.next.Phase 2 이후 linker 통합 경로) 만 salt 명시 → hash 산출.

### Phase 1 — 도메인 정당화
- 신규 hash 필드는 stable identifier 보강 — audit standard 변경 아님.
- engagement-scoped salt 로 cross-engagement 식별자 누출 차단 (S3 비식별화 정책 정합).

### Phase 1 — Test names
- test_raw_rule_hit_ref_legacy_fields_unchanged (회귀)
- test_raw_rule_hit_ref_new_hash_fields_default_empty_or_none
- test_raw_rule_hit_ref_extra_forbid_still_enforced
- test_phase1_case_builder_without_salt_keeps_hash_fields_empty (backward compat)
- test_phase1_case_builder_with_salt_populates_canonical_label_hash
- test_phase1_case_builder_with_salt_populates_doc_id_hash
- test_phase1_case_builder_with_salt_populates_line_number_key
- test_phase1_case_builder_hash_uses_engagement_scoped_salt (salt 다르면 hash 다름)
- test_phase1_case_builder_canonical_label_hash_matches_phase2_format (PHASE2 row_ref_map 의 같은 row position 의 canonical_label_hash 와 일치 — invariant #70)
- test_existing_phase1_tests_pass_unchanged (회귀 가드)

### Phase 1 — Invariants

70. PHASE1 `RawRuleHitRef.canonical_label_hash` 는 `hash_ref_key(canonicalize_ref_key(df.index[row_index]), salt=engagement_salt)` 결과. 동일 engagement salt 로 PHASE2 row_ref_map 에 저장된 `canonical_label_hash` 와 일치 → linker 가 두 source 의 hash 직접 비교 가능.
71. PHASE1 builder 가 `engagement_salt` 미수령 시 신규 hash 필드는 빈 문자열 / None (backward compat). 기존 caller 영향 0.
72. 기존 `row_index` / `document_id` / 기타 legacy 필드 동작 변경 0. 신규 hash 필드는 부가 정보로만 사용.
73. `RawRuleHitRef.model_config(extra="forbid")` 유지 — schema migration 시점에 unknown 필드는 여전히 거부.

### Deferred to Phase 2 / Phase 3
- linker 가 hash 필드 사용 (Phase 2)
- auto resolution + match_precision 갱신 (Phase 2)
- pipeline attach unlock 정책 정정 (Phase 3)
- TS detector 의 expected_count 실제 baseline 산출 (S6 followup 별도)
- family_ecdf 외부 결합 / enrichment

## S6.next Phase 2 — linker 가 hash 필드 사용

### 핵심 변경
PHASE1 `RawRuleHitRef` 가 Phase 1 에서 stable identifier hash 필드 직접 보유 →
linker 의 hash 기반 mode (doc_line / company_doc / label) 가 **row_ref_map
sidecar 조회 없이 hit 의 hash 필드 직접 사용** 가능.

### Phase 1 누락 보완 — company_code_hash 추가
Phase 1 spec 이 company_code_hash 누락. Phase 2 에서 함께 추가:
- `RawRuleHitRef.company_code_hash: str = ""` 신규
- PHASE1 builder 가 `engagement_salt` 보유 시 company_code 도 hash 산출

### Hit hash 우선 + row_ref_map fallback 패턴
```python
def _phase1_label_key(hit, position_to_entry):
    # Hit 의 hash 필드 우선 (Phase 1 산출물)
    if hit.canonical_label_hash:
        return hit.canonical_label_hash
    # 빈 문자열 → row_ref_map fallback (구 schema PHASE1 결과)
    entry = position_to_entry.get(hit.row_index)
    if entry is None:
        return None
    return entry.get("canonical_label_hash") or None
```

doc_line / company_doc 도 동일 패턴 — hit 의 hash 우선, 빈 값 면 row_ref_map fallback.

### Auto resolution 갱신
`_has_full_phase1_position_coverage` 가 hash 필드 우선 검사:
- 모든 PHASE1 hit 가 `canonical_label_hash` 가용 → label 자동 채택 (row_ref_map 부재해도 OK)
- 일부 hit 만 hash 가용 → row_ref_map 보완 필요 (기존 partial coverage 검사)
- 둘 다 없으면 doc_id / position fallback

### File targets
```
src/models/phase1_case.py                          (company_code_hash 추가)
src/detection/phase1_case_builder.py               (company_code_hash 산출)
src/services/phase2_case_phase1_linker.py          (hit hash 우선 + fallback)
tests/modules/test_models/test_phase1_raw_rule_hit_ref.py  (company_code_hash 검증)
tests/modules/test_detection/test_phase1_case_builder_hash_fields.py  (company_code_hash 산출)
tests/modules/test_services/test_phase2_case_phase1_linker.py  (hit hash 우선 + fallback)
```

### Invariants (S6.next Phase 2 통과 조건)

74. RawRuleHitRef 가 `company_code_hash: str = ""` 추가. engagement_salt 가용 시 산출. default 빈 문자열 — backward compat.
75. linker 의 hash 기반 mode (`doc_line` / `company_doc` / `label`) 는 hit 의 hash 필드 우선 사용. 빈 값이면 row_ref_map fallback.
76. `_has_full_phase1_position_coverage` 가 hash 필드 우선 검사 — PHASE1 hit 가 모두 hash 가용하면 row_ref_map 부재해도 label 채택.
77. hit hash 와 row_ref_map hash 는 동일 engagement_salt 산출이어야 매칭. 다른 salt 사용 시 hash 다름 → 매칭 0 (silent). 호출자가 salt 정합 보장.

### Deferred to Phase 3
- pipeline attach unlock 정책 정정
- row_ref_map deprecation 검토 (Phase 1 schema 전면 보급 후)

## S3.next — Orchestrator + run_phase2_inference attach

S6.next Phase 2 unlock 활용 — engagement_salt 기반 hash mode 로 production 경로 진입.

### 2 phase 분할
- **Phase A** (이번): orchestrator (`build_phase2_case_set`) 단일 모듈 — detection_results 5 family 라우팅 후 Phase2CaseSet 조립.
- **Phase B** (다음): `run_phase2_inference` attach — 기존 inference service 흐름에 orchestrator + store + linker 통합.

### Phase A — File targets
```
src/services/phase2_case_set_orchestrator.py
tests/modules/test_services/test_phase2_case_set_orchestrator.py
```

### Phase A — Module signature

```python
def build_phase2_case_set(
    *,
    batch_id: str,
    detection_results: list[DetectionResult],
    df: pd.DataFrame,
    unsupervised_model_id: str = "",
    unsupervised_schema_hash: str = "",
    unsupervised_ecdf_gate: float = 0.95,
) -> Phase2CaseSet:
    """5 family builder 호출 후 Phase2CaseSet 조립.

    detection_results 에서 track_name 별 라우팅:
    - "duplicate"      → build_duplicate_cases(batch_id, detection_result, df)
    - "ml_unsupervised" → build_unsupervised_cases(... + model_id, schema_hash, ecdf_gate)
    - "intercompany"   → build_intercompany_cases(...)
    - "relational"     → build_relational_cases(...)
    - "timeseries"     → build_timeseries_cases(...)

    각 family detection_result 부재 시 해당 cases tuple 은 빈 ().
    detection_results 가 빈 list 면 모든 family 빈 Phase2CaseSet 반환.
    detection_results 에 중복 track_name 이 있으면 마지막 결과 사용 (호출자 책임).
    """
```

### Phase A — Test names (+10)
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

### Phase A — Invariants

80. orchestrator 는 detection_results 의 track_name 만 라우팅 — 모르는 track_name 은 silent skip. ValueError 던지지 않음.
81. unsupervised builder 만 추가 인자 (model_id / schema_hash / ecdf_gate) 필요. 다른 family builder 는 (batch_id, detection_result, df) 만 받음.
82. orchestrator 출력 Phase2CaseSet 의 `linked` 는 default False — linker 가 후속 단계에서 부착.
83. orchestrator 는 PHASE1 prior (priority_score / composite_sort_score / rule hit) 접근 0건. 5 builder 의 invariant (#14, #56, #67) 인계.

### Phase B — run_phase2_inference attach

#### File targets
```
src/services/phase2_inference_service.py   (attach hook 추가)
src/pipeline.py                             (PipelineResult 신규 필드)
tests/modules/test_services/test_phase2_inference_service_case_set_attach.py
```

#### PipelineResult 확장
```python
@dataclass
class PipelineResult:
    # ... 기존 ...
    phase2_case_set: Phase2CaseSet | None = field(default=None, repr=False)
    phase2_linker_diagnostics: dict[str, Any] | None = field(default=None, repr=False)
```

#### Attach hook
```python
def _attach_phase2_case_set(result, *, ctx=None, snapshot=None) -> None:
    """orchestrator + linker hook (S3.next Phase B, invariant #84~87).

    1. result.results / data / batch_id 가용성 검증 — 부재 시 graceful skip.
    2. engagement_salt 도출: ctx.engagement_id + batch_id (없으면 빈 문자열 — position fallback).
    3. orchestrator 호출 → case_set.
    4. PHASE1 가용 시 linker 호출 (key_mode="auto") → linked case_set + diagnostics.
    5. result.phase2_case_set / phase2_linker_diagnostics 부착.

    호출자 책임 (attach 정책 lock):
    - engagement_salt 명시 + PHASE1 builder 가 동일 salt 사용 → reload-safe (invariant #79)
    - salt 부재 / PHASE1 builder 미 hash → position fallback (in-memory same-batch 한정)
    """
```

#### 통합 위치
`run_phase2_inference` 의 `_attach_phase2_case_overlays(result)` 호출 직후, `_persist_phase2_batch_snapshot` 호출 직전.

#### Invariants (S3.next Phase B)

84. `_attach_phase2_case_set` 는 result.results / data / batch_id 부재 시 graceful skip — ValueError 던지지 않음.
85. engagement_salt 도출 실패 시 (ctx 부재 / engagement_id 부재) salt="" — linker 가 hash mode skip 하고 position / doc_id 로 auto fallback (invariant #79 정합).
86. PHASE1 부재 시 linker 호출 skip — case_set 만 부착 (linked=False).
87. unsupervised model_id / schema_hash 는 snapshot 에서 도출 — 부재 시 빈 문자열 (orchestrator 가 default 값 사용).

#### Test names (대표)
- test_attach_skips_when_results_empty
- test_attach_skips_when_data_none
- test_attach_skips_when_batch_id_empty
- test_attach_attaches_case_set_to_result
- test_attach_with_phase1_invokes_linker_and_records_diagnostics
- test_attach_without_phase1_skips_linker_keeps_linked_false
- test_attach_with_engagement_salt_auto_resolves_to_hash_mode
- test_attach_without_engagement_salt_falls_back_to_position

## Deferred (S3.next Phase A 이후)

- S3.next Phase B: run_phase2_inference attach
- S7: dashboard drill-down
- S6.next.next: row_ref_map deprecation 검토
- PR-pre-1: phase2_overlay_store → artifact_path_safety 마이그레이션
- PR-pre-2: pyproject.toml `[tool.pyright]` 에 `extraPaths = ["."]` 추가
