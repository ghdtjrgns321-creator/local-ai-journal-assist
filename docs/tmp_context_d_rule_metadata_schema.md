# Context D Rule Metadata Schema

## 목적과 원칙

이 문서는 룰별 위반 상세 화면에서 사용할 구현용 metadata schema 설계안이다. A/B/C 산출물을 다음 우선순위로 병합한다.

- A: `rule_id`, `canonical_rule_id`, `status`, `final_topic`, `secondary_topics`, `scoring_role`, `standalone_rankable`, `presenter_surface`의 원천.
- B: `display_title`, `user_question`, `why_it_matters`, `what_to_check`, `how_to_review`, `guardrail`, `next_action`, `display_tone`의 원천.
- C: `required_columns`, `display_columns`, `comparison_columns`, `drilldown_columns`, `grouping_keys`, `missing_column_message`의 원천.

핵심 제약은 schema 수준에서 표현한다. `context_badge`, `booster`, `combo_only` 룰은 단독 위반 문구를 만들 수 없고, `macro_only` 룰은 row violation detail이 아니라 account/process macro finding으로만 노출한다. `L2-03a~d`는 `L2-03` 내부 reason code이며, `Benford`는 `L4-02` alias다. `IC01~IC03`은 intercompany sidecar로 topic seed는 가능하지만 L1~L4 transaction rule count에는 넣지 않는다. `GR01/GR03`은 graph sidecar이며 v1 transaction detail 필수 범위 밖이다.

## 1. 최종 Schema 설계

### RuleDisplayMetadata

사용자에게 보이는 룰 설명과 노출 정책이다. B를 문구 원천으로 삼고, A의 identity/policy와 충돌하면 A를 우선한다.

```python
class RuleDisplayMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    canonical_rule_id: str
    status: RuleMetadataStatus
    presenter_surface: PresenterSurface
    finding_scope: FindingScope

    display_title: str
    user_question: str
    why_it_matters: str
    what_to_check: tuple[str, ...]
    how_to_review: tuple[str, ...]
    guardrail: str
    next_action: str
    display_tone: DisplayTone

    final_topic: str | None = None
    secondary_topics: tuple[str, ...] = ()
    scoring_role: ScoringRole
    standalone_rankable: bool
    evidence_type: EvidenceType

    canonical_display: bool = True
    user_visible_rule: bool = True
    allow_row_violation_detail: bool = True
    allow_standalone_violation_copy: bool = True
    allow_topic_seed: bool = True
    include_in_l1_l4_transaction_count: bool = True

    fraud_scenario_tags: tuple[str, ...] = ()
    source_context: Literal["A", "B", "C", "merged"] = "merged"
    notes: str = ""
```

필드 해석:

| 필드 | 의미 |
|---|---|
| `canonical_rule_id` | alias/internal reason code를 대표 룰로 해석하기 위한 ID. `Benford -> L4-02`, `L2-03a~d -> L2-03`. |
| `presenter_surface` | 화면 노출 위치. row 상세, context badge, account/process macro, sidecar, drilldown reason을 구분한다. |
| `finding_scope` | finding의 의미 단위. row/document/account/process/intercompany/graph/reason. |
| `allow_row_violation_detail` | row 위반 상세 패널 생성 허용 여부. `context_badge`, `macro`, `sidecar`, `alias`, `internal_reason_code`는 기본 False. |
| `allow_standalone_violation_copy` | “이 룰 위반” 같은 단독 위반 문구 허용 여부. booster/combo/context 계열은 False. |
| `include_in_l1_l4_transaction_count` | 32개 transaction canonical rule count 포함 여부. IC/D/GR/alias/reason code는 False. |

### RuleColumnMetadata

C의 컬럼 계약을 구현 가능한 구조로 정규화한 schema다.

```python
class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    label: str | None = None
    source: ColumnSource
    requirement: ColumnRequirement = ColumnRequirement.OPTIONAL
    dtype: str = "string"
    fallback_columns: tuple[str, ...] = ()
    formatter: ColumnFormatter = ColumnFormatter.TEXT
    display_priority: int = 100
    nullable: bool = True
    sensitive: bool = False
    description: str = ""


class RuleColumnMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    canonical_rule_id: str
    status: RuleMetadataStatus
    presenter_surface: PresenterSurface
    detail_level: str

    required_columns: tuple[ColumnSpec, ...]
    display_columns: tuple[ColumnSpec, ...]
    comparison_columns: tuple[ColumnSpec, ...] = ()
    drilldown_columns: tuple[ColumnSpec, ...] = ()
    grouping_keys: tuple[str, ...] = ()
    derived_columns: tuple[ColumnSpec, ...] = ()
    inherited_from: str | None = None
    missing_column_message: str
```

컬럼 그룹 사용 기준:

- `required_columns`: 해당 surface를 의미 있게 렌더링하는 최소 컬럼. 없으면 `missing_column_message`를 반환한다.
- `display_columns`: 상세 표 기본 컬럼. C의 `ledger_columns`와 공통 표시 컬럼을 합친다.
- `comparison_columns`: pair, duplicate, cutoff, prior/current, matched-counterpart 비교에 필요한 컬럼.
- `drilldown_columns`: evidence builder나 row detail panel이 추가로 쓰는 파생 증거 컬럼.
- `grouping_keys`: duplicate group, macro population, intercompany pair처럼 row보다 큰 단위를 묶는 키.

### RuleInspectionMetadata

case builder, dashboard, export가 룰 상세를 어떤 방식으로 렌더링할지 결정하는 실행 정책이다.

```python
class RuleInspectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    canonical_rule_id: str
    status: RuleMetadataStatus
    presenter_surface: PresenterSurface
    finding_scope: FindingScope

    row_detail_policy: RowDetailPolicy
    standalone_copy_policy: StandaloneCopyPolicy
    canonicalization_policy: CanonicalizationPolicy
    macro_policy: MacroPolicy | None = None
    sidecar_policy: SidecarPolicy | None = None

    reason_code_field: str | None = None
    reason_code_values: tuple[str, ...] = ()
    allowed_parent_rule_id: str | None = None

    case_seed_policy: CaseSeedPolicy
    topic_seed_policy: TopicSeedPolicy
    count_policy: CountPolicy

    validation_tags: tuple[str, ...] = ()
```

핵심 policy enum 값:

- `row_detail_policy`: `allow`, `forbid_context_only`, `forbid_macro_only`, `forbid_sidecar_only`, `forbid_alias`, `forbid_reason_code`.
- `standalone_copy_policy`: `allow_violation_copy`, `context_only_copy`, `macro_review_copy`, `sidecar_review_copy`, `drilldown_reason_copy`.
- `case_seed_policy`: `can_seed_case`, `cannot_seed_case`, `can_seed_only_with_primary`, `sidecar_seed_only`.
- `topic_seed_policy`: `can_seed_topic`, `cannot_seed_topic`, `context_only`, `macro_context_only`, `sidecar_topic_seed`.
- `count_policy`: `l1_l4_transaction_count`, `exclude_alias`, `exclude_reason_code`, `exclude_macro`, `exclude_sidecar`.

### RuleMetadataRegistry 구조

세 schema를 하나의 registry entry로 묶는다. 구현 시 entry 단위로 검증하고, presenter는 직접 dict에 접근하지 않는다.

```python
class RuleMetadataEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    display: RuleDisplayMetadata
    columns: RuleColumnMetadata
    inspection: RuleInspectionMetadata


class RuleMetadataRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0.0"
    entries: dict[str, RuleMetadataEntry]
    canonical_index: dict[str, tuple[str, ...]]
    topic_index: dict[str, tuple[str, ...]]
    surface_index: dict[PresenterSurface, tuple[str, ...]]

    def get(self, rule_id: str, *, resolve_alias: bool = True) -> RuleMetadataEntry: ...
    def canonicalize(self, rule_id: str) -> str: ...
    def get_for_row_detail(self, rule_id: str) -> RuleMetadataEntry | None: ...
    def get_for_macro_finding(self, rule_id: str) -> RuleMetadataEntry | None: ...
    def get_reason_codes(self, canonical_rule_id: str) -> tuple[RuleMetadataEntry, ...]: ...
    def project_columns(self, rule_id: str, row: Mapping[str, Any]) -> dict[str, Any]: ...
    def validate(self) -> list[MetadataValidationIssue]: ...
```

`canonical_index` 예시:

```python
{
    "L2-03": ("L2-03", "L2-03a", "L2-03b", "L2-03c", "L2-03d"),
    "L4-02": ("L4-02", "Benford"),
}
```

## 2. Enum 정의

```python
class RuleMetadataStatus(StrEnum):
    ACTIVE = "active"
    MACRO = "macro"
    SIDECAR = "sidecar"
    ALIAS = "alias"
    INTERNAL_REASON_CODE = "internal_reason_code"
    DEPRECATED = "deprecated"


class PresenterSurface(StrEnum):
    TRANSACTION_DETAIL = "transaction_detail"
    CONTEXT_BADGE = "context_badge"
    ACCOUNT_PROCESS_MACRO = "account_process_macro"
    INTERCOMPANY_SIDECAR = "intercompany_sidecar"
    GRAPH_SIDECAR = "graph_sidecar"
    DRILLDOWN_REASON = "drilldown_reason"


class ScoringRole(StrEnum):
    PRIMARY = "primary"
    BOOSTER = "booster"
    COMBO_ONLY = "combo_only"
    MACRO_ONLY = "macro_only"


class EvidenceType(StrEnum):
    DATA_INTEGRITY_FAILURE = "data_integrity_failure"
    CONTROL_FAILURE = "control_failure"
    ACCESS_SCOPE_REVIEW = "access_scope_review"
    DUPLICATE_OR_OUTFLOW = "duplicate_or_outflow"
    TIMING_ANOMALY = "timing_anomaly"
    LOGIC_MISMATCH = "logic_mismatch"
    STATISTICAL_OUTLIER = "statistical_outlier"
    INTERCOMPANY_STRUCTURE = "intercompany_structure"
    MACRO_FINDING = "macro_finding"


class DisplayTone(StrEnum):
    DIRECT_CONTROL = "direct_control"
    DATA_QUALITY = "data_quality"
    DIRECT_REVIEW = "direct_review"
    CONTROL_EXCEPTION = "control_exception"
    CONTROL_TRACE = "control_trace"
    CUTOFF_REVIEW = "cutoff_review"
    OUTFLOW_REVIEW = "outflow_review"
    SUBSTANCE_REVIEW = "substance_review"
    MANUAL_REVIEW = "manual_review"
    STATISTICAL_REVIEW = "statistical_review"
    CONTEXT_ONLY = "context_only"
    MACRO_REVIEW = "macro_review"
    SIDECAR_SEED = "sidecar_seed"
    GRAPH_CONTEXT = "graph_context"
    DRILLDOWN_ONLY = "drilldown_only"
    ALIAS_ONLY = "alias_only"


class FindingScope(StrEnum):
    ROW = "row"
    DOCUMENT = "document"
    DOCUMENT_GROUP = "document_group"
    ACCOUNT = "account"
    PROCESS = "process"
    ACCOUNT_PROCESS = "account_process"
    INTERCOMPANY_PAIR = "intercompany_pair"
    GRAPH = "graph"
    REASON_CODE = "reason_code"
```

보조 enum:

```python
class ColumnSource(StrEnum):
    LEDGER = "ledger"
    FEATURE = "feature"
    DETECTION_OUTPUT = "detection_output"
    CASE_BUILDER = "case_builder"
    MACRO_FINDING = "macro_finding"
    SIDECAR_OUTPUT = "sidecar_output"
    DERIVED = "derived"
    CONFIG = "config"
    MASTER_DATA = "master_data"


class ColumnRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    DERIVED_IF_MISSING = "derived_if_missing"
    CONTEXT_ONLY = "context_only"


class ColumnFormatter(StrEnum):
    TEXT = "text"
    AMOUNT = "amount"
    DATE = "date"
    DATETIME = "datetime"
    INTEGER = "integer"
    SCORE = "score"
    PERCENT = "percent"
    BADGE = "badge"
    LIST = "list"
    JSON = "json"
```

## 3. Validation Rules

### status별 required/forbidden 필드

| status | Required | Forbidden / must be false |
|---|---|---|
| `active` + `transaction_detail` | `canonical_rule_id == rule_id`, `final_topic`, `display_title`, B 설명 필드, C row columns | 없음. 단, `scoring_role in {booster, combo_only}`이면 row violation detail 금지 |
| `active` + `context_badge` | `canonical_rule_id == rule_id`, `standalone_rankable=False`, `guardrail`, `next_action`, `display_tone=context_only` 또는 유사 tone | `allow_row_violation_detail=True`, `allow_standalone_violation_copy=True` |
| `macro` | `presenter_surface=account_process_macro`, `finding_scope in {account, process, account_process}`, `scoring_role=macro_only`, macro columns | `allow_row_violation_detail=True`, transaction row count 포함 |
| `sidecar` | sidecar surface, sidecar columns, `include_in_l1_l4_transaction_count=False` | L1~L4 transaction count 포함. graph sidecar는 v1 transaction detail 필수 노출 |
| `alias` | `canonical_rule_id != rule_id`, `canonical_display=False`, `canonicalization_policy=alias_to_canonical` | 독립 columns, 독립 case seed, 독립 count |
| `internal_reason_code` | `canonical_rule_id != rule_id`, `presenter_surface=drilldown_reason`, `allowed_parent_rule_id`, `reason_code_field` | 독립 사용자 룰, 독립 topic seed, 독립 row detail |

### standalone_rankable=False일 때 금지 문구/금지 동작

`standalone_rankable=False` 또는 `scoring_role in {booster, combo_only, macro_only}`이면 다음을 금지한다.

- “위반”, “부정”, “오류 확정”, “통제 실패 확정”처럼 단독 결론을 내리는 제목/요약.
- `build_phase1_rule_document_detail()`류 row detail에서 primary violation panel 생성.
- Top N seed 또는 standalone case seed. 단, IC sidecar는 `sidecar_topic_seed` 정책으로 intercompany topic seed만 허용한다.
- `flagged_rules` 기준 확정 위반 집계. context는 `review_rules`, `raw_rule_hits`, sidecar/macro metadata로만 보강한다.

허용 문구는 “맥락”, “검토 신호”, “보조 신호”, “결합 시 우선 검토”, “macro finding”, “sidecar finding” 계열이다.

### alias/internal_reason_code 처리 규칙

- `Benford`는 반드시 `canonical_rule_id="L4-02"`, `status=alias`, `presenter_surface=account_process_macro`다.
- `Benford`로 accessor를 호출하면 기본 응답은 `L4-02` canonical metadata이고, `requested_rule_id="Benford"`만 별도 audit trail에 남긴다.
- `L2-03a~d`는 반드시 `canonical_rule_id="L2-03"`, `status=internal_reason_code`, `presenter_surface=drilldown_reason`이다.
- `L2-03a~d`는 `RuleDisplayMetadata.user_visible_rule=False`, `allow_row_violation_detail=False`, `include_in_l1_l4_transaction_count=False`다.
- L2-03 detail 화면에서는 `internal_reason_code` 또는 `display_label`로 reason badge를 표시할 수 있으나, 별도 룰 탭이나 별도 룰 count를 만들 수 없다.

### macro/sidecar 처리 규칙

- `L4-02`, `D01`, `D02`는 `status=macro`, `presenter_surface=account_process_macro`, `scoring_role=macro_only`, `allow_row_violation_detail=False`.
- macro finding은 `macro_finding_id`, `population_key`, `macro_priority_score`, `review_score`, `queue_bucket`, `candidate_documents` 같은 account/process evidence를 요구한다.
- `IC01~IC03`은 `status=sidecar`, `presenter_surface=intercompany_sidecar`, `finding_scope=intercompany_pair`, `allow_topic_seed=True`, `include_in_l1_l4_transaction_count=False`.
- `GR01/GR03`은 `status=sidecar`, `presenter_surface=graph_sidecar`, `finding_scope=graph`, `scoring_role=macro_only`, v1 transaction detail required set에서 제외한다.
- sidecar는 topic/case에 연결될 수 있지만, row violation detail title을 생성하지 않고 sidecar detail section으로만 렌더링한다.

## 4. 구현 위치 제안

### 신규 파일 vs `rule_scoring.py`

신규 파일을 권장한다.

```text
src/detection/rule_display_metadata.py
```

근거:

- `rule_scoring.py`는 점수 산식과 topic routing의 원천이다. 표시 문구, 컬럼, guardrail까지 넣으면 scoring contract가 UI 변경에 끌려간다.
- A/B/C 병합 metadata는 dashboard/export/case_builder가 함께 쓰는 presenter 계약이다. 점수 계산 모듈보다 export/view 계층에 가까우며, validation surface도 다르다.
- 테스트도 `RULE_SCORING_REGISTRY` 정합성 검증은 필요하지만, 실패 유형은 표시/문구/컬럼 누락이다.

권장 모듈 분리:

```text
src/detection/rule_display_metadata.py
  - enum, Pydantic schema, registry, registry validation

src/detection/rule_metadata_accessors.py
  - get_rule_metadata()
  - canonicalize_rule_id()
  - can_render_row_violation_detail()
  - get_rule_display()
  - get_rule_columns()
  - get_rule_inspection_policy()
  - project_rule_detail_row()
```

### Accessor 사용 제안

`phase1_case_builder.py`:

- `_rule_label()`, `_rule_focus()`, `_rule_actions()`, `_rule_evidence_summary()`는 `get_rule_display()`와 `get_rule_inspection_policy()`로 점진 대체한다.
- `_annotation_can_seed_case()`는 `RULE_SCORING_REGISTRY`의 scoring role과 함께 `get_rule_inspection_policy(rule_id).case_seed_policy`를 확인한다.
- raw hit 저장 시 `rule_id`는 원천 ID를 유지하되, `rule_evidence_summary`에는 `canonical_rule_id`, `presenter_surface`, `finding_scope`를 포함한다.

`src/export/phase1_case_view.py`:

- `build_phase1_rule_documents()`는 `canonicalize_rule_id()` 후 `can_render_row_violation_detail()`이 False면 빈 row detail 대신 context/macro/sidecar용 안내 payload를 반환한다.
- `_EVIDENCE_BUILDERS`는 장기적으로 `RuleColumnMetadata`의 `required_columns`, `comparison_columns`, `drilldown_columns` 기반 projection으로 축소한다.
- `_signal_type()`은 hard-coded `_MACRO_RULES`, `_REVIEW_CONTEXT_RULES` 대신 `presenter_surface`와 `finding_scope`를 사용한다.

`dashboard/tab_phase1.py`:

- `_RULE_DESCRIPTIONS_KR`, `_RULE_NAMES_KR`는 `get_rule_display(rule_id)`로 대체한다.
- 32개 transaction 룰 카운트는 `include_in_l1_l4_transaction_count=True`인 canonical entries만 센다.
- rule selector는 `presenter_surface=transaction_detail`인 canonical 룰만 기본 노출하고, context/macro/sidecar는 별도 필터에서 선택한다.

## 5. 테스트 계획

### metadata completeness

- A의 모든 `rule_id`가 registry에 있어야 한다.
- `status=active`, `presenter_surface=transaction_detail`인 canonical rule은 B 필드와 C 컬럼 필드가 모두 있어야 한다.
- `IC01~IC03`, `D01/D02`, `GR01/GR03`, `Benford`, `L2-03a~d`는 completeness 예외가 아니라 각 status별 필수 필드를 만족해야 한다.

### enum validation

- `status`, `presenter_surface`, `scoring_role`, `evidence_type`, `display_tone`, `finding_scope`는 enum 외 값을 허용하지 않는다.
- `RuleDisplayMetadata.evidence_type`은 `RULE_SCORING_REGISTRY[rule_id].evidence_type`과 일치해야 한다. alias/reason code는 canonical 일치도 허용한다.
- `final_topic`과 `secondary_topics`는 `TOPIC_REGISTRY`에 존재해야 한다.

### macro-only row detail 금지

- `L4-02`, `Benford`, `D01`, `D02`, `GR01`, `GR03`에 대해 `can_render_row_violation_detail()`이 False여야 한다.
- `build_phase1_rule_document_detail(rule_id="L4-02", document_id=...)`류 호출은 row violation payload가 아니라 macro finding 안내 또는 None을 반환하도록 테스트한다.

### booster 단독 위반 문구 금지

- `L3-03`, `L3-05`, `L3-06`, `L3-08`, `L3-10`, `L3-12`, `L4-05`, `L4-06`은 `allow_standalone_violation_copy=False`.
- 해당 룰의 `display_title`, `guardrail`, `next_action`에 단독 확정 위반 표현이 들어가면 validation fail.
- `standalone_rankable=False`인 룰만 있는 evidence set은 Top N seed를 만들 수 없어야 한다.

### L2-03 reason code canonicalization

- `canonicalize_rule_id("L2-03a") == "L2-03"` 등 a~d 모두 검증.
- `get_reason_codes("L2-03")`는 a~d reason entries를 반환한다.
- L2-03a~d는 dashboard rule count, transaction rule selector, topic seed에서 제외된다.
- L2-03 detail projection에는 reason badge와 reason-specific evidence columns가 포함된다.

### Benford alias canonicalization

- `canonicalize_rule_id("Benford") == "L4-02"`.
- `get_rule_metadata("Benford").display.canonical_rule_id == "L4-02"`.
- Benford는 L4-02와 별도 count를 만들지 않는다.
- Benford 요청은 account/process macro surface로만 resolve된다.

## 6. A/B/C 충돌 또는 누락 목록

### 충돌 목록

| rule_id | 항목 | A 기준 | B/C 또는 코드상 관찰 | 설계 처리 |
|---|---|---|---|---|
| L2-01 | topic 의미 | `final_topic=duplicate_outflow`, `secondary=approval_control` | 사용자 설명은 승인한도 우회 질문이 중심 | A 우선. 표시 문구는 승인한도 질문을 유지하되 topic routing은 duplicate/outflow로 고정 |
| L1-08 | final topic | `closing_timing`, secondary `ledger_integrity` | 데이터 정합성/기간 불일치 설명도 강함 | A 우선. row detail은 cutoff/기간귀속 tone, data integrity는 secondary context |
| L3-03 | 노출 범위 | `booster`, `standalone_rankable=False`, `context_badge` | 관계사 topic seed 맥락이 있음 | 단독 row violation 금지. IC sidecar 또는 다른 primary hit와 결합 시 topic context |
| L3-05/L3-06 | 단독 queue | v1 standalone queue 금지 | 캘린더/시간 이상 설명은 존재 | `context_badge`, `context_only` tone, standalone copy 금지 |
| L3-08 | topic/evidence 해석 | final topic은 ledger integrity, scoring role은 booster | 설명 결손은 timing/cutoff 보조 신호로도 쓰임 | A 우선. ledger integrity context badge로 두고 closing timing은 secondary |
| L3-10 | 단독 노출 | booster, standalone false | 민감 계정 접촉은 강한 사용자 질문처럼 보일 수 있음 | context-only tone 강제. 다른 primary hit와 결합 시만 우선순위 보강 |
| L3-12 | SoD와 관계 | combo_only, standalone false | 업무범위 집중은 권한 문제처럼 보임 | L1-06 direct SoD와 분리. access/work-scope context badge만 허용 |
| L4-02/Benford | alias/count | `Benford`는 `L4-02` alias, macro_only | DETECTION_RULES에는 Benford 독립 트랙 표현 | canonical count는 L4-02 하나. Benford는 alias display만 |
| IC01~IC03 | count/topic seed | sidecar, L1~L4 count 제외, topic seed 가능 | `RULE_SCORING_REGISTRY`에는 primary role로 존재 | metadata에서 `status=sidecar`, count 제외를 명시해 transaction rule count와 분리 |
| GR01/GR03 | surface | graph sidecar, v1 transaction detail 밖 | 코드 macro finding 집계 경로에 포함 가능 | `graph_sidecar`로 분리하고 v1 row detail 필수 범위에서 제외 |

### 누락 목록

| 누락 항목 | 영향 | 보완 주체 |
|---|---|---|
| `display_title` 등 B 문구의 UTF-8 정상화 | 현재 일부 문서 출력이 깨져 registry에 그대로 넣기 어렵다 | B 컨텍스트 보완 또는 최종 registry 작성 시 수동 정상화 |
| `comparison_columns`, `grouping_keys`의 명시적 구분 | C는 ledger/evidence 중심이며 일부 룰은 group key가 암묵적이다 | C 컨텍스트 보완. 특히 L2-02/L2-03/L2-05/L4-02/D01/D02/IC01~IC03 |
| macro finding 공통 schema | D01/D02/L4-02의 evidence key가 일부 다르다 | C와 phase1_case_builder macro rows를 기준으로 공통 `MacroFindingRef` 모델 정의 |
| sidecar detail payload schema | IC/graph sidecar의 target/counterpart/path 표현이 통일되지 않았다 | C 컨텍스트 보완 및 intercompany/graph 구현 코드 확인 |
| forbidden-copy validation용 금지어 목록 | booster/context 룰의 단독 위반 문구 차단을 자동화하려면 한국어 금지 표현 목록 필요 | D 구현 단계에서 validator fixture 추가 |
| dashboard 33개 룰 표시 정책 | dashboard 주석에는 33개 룰 표현이 남아 있고 A는 32 canonical + alias 해석을 요구 | dashboard accessor 전환 시 count policy로 정리 |
| `presenter_surface`와 기존 `_signal_type` 매핑 | export는 hard-coded macro/review set을 사용한다 | accessor 도입 후 `finding_scope` 기반으로 대체 |

## 구현 순서 제안

1. `rule_display_metadata.py`에 enum/schema와 최소 registry shell을 추가한다.
2. A의 identity/policy를 먼저 registry에 적재하고 validation을 통과시킨다.
3. B 문구를 `RuleDisplayMetadata`에 병합하되 context/macro/sidecar 금지 문구 validation을 먼저 둔다.
4. C 컬럼을 `RuleColumnMetadata`에 병합하고 `project_columns()`를 만든다.
5. `phase1_case_view.py`의 row detail 진입점에서 `can_render_row_violation_detail()`만 먼저 적용해 금지 동작을 차단한다.
6. dashboard/export/case_builder의 hard-code label/action/description을 accessor로 점진 대체한다.
