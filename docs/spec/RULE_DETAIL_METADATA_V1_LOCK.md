# Rule Detail Metadata v1 Lock

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.


> **포트폴리오 주장 범위 (2026-05-19)**: 이 프로젝트는 `fraud`를 판정하거나 실제 운영 부정 탐지 성능을 보장하는 모델이 아니다. 전수 모집단에서 감사인이 먼저 볼 review queue를 만들고, 무작위 검토 대비 상위 구간에 review-worthy synthetic anomaly를 강하게 농축하는 로컬 감사 분석 보조 도구다. DataSynth 기반 precision/recall은 개발 검증 보조 지표이며, 실데이터 운영 성능으로 주장하지 않는다.
> **금지 표현**: "부정을 정확히 탐지", "실무 운영 성능 검증 완료", "TOP100 precision 충분", "fraud 확정/자동 적발"처럼 확정적이거나 운영 성능을 보장하는 표현은 사용하지 않는다.

Updated: 2026-05-08
Status: Locked for v1 implementation

Source inputs:

- `docs/archive/completed/tmp_context_a_rule_metadata.md`
- `docs/archive/completed/tmp_context_b_rule_display_guidance.md`
- `docs/archive/completed/tmp_context_c_rule_column_metadata.md`
- `docs/archive/completed/tmp_context_d_rule_metadata_schema.md`
- `docs/archive/completed/tmp_context_e_rule_metadata_integration_review.md`
- `docs/spec/DETECTION_RULES.md`
- `docs/archive/completed/PHASE1_TOPIC_SCORING_V1_LOCK.md` (2026-06-16 archive 이관)

## Final Decisions

This document resolves the `CONDITIONAL GO` items from Context E. Implementers must treat this file as the final v1 contract when A/B/C/D/E or legacy code comments disagree.

Locked decisions:

- L1~L4 canonical transaction/detail rule count is exactly **31** (2026-06-15: was 32; `L4-02` moved to PHASE1-2 family).
- Legacy "32/33 rules" means `31 canonical L1~L4 transaction rows + L4-02/Benford macro (now PHASE1-2 family)`; it never means 33 canonical transaction rules.
- `L2-03a~d` are internal reason codes under `L2-03`.
- `Benford` is a display alias for `L4-02`.
- `D01/D02`, `L4-02/Benford`, `IC01~IC03`, and `GR01/GR03` are not L1~L4 transaction/detail rules (macro/family — PHASE1-2 또는 별도 surface).
- `L4-02` (Benford macro)는 PHASE1-2 family로 이관(2026-06-15) → canonical L1~L4 count 제외. presenter surface는 `account_process_macro` 유지(행 detail 불가).
- Row violation detail is allowed only when both `presenter_surface=transaction_detail` and `allow_row_violation_detail=True`.
- First implementation must use a minimal flat `RuleDetailMetadata` model, not the full nested schema proposed in Context D.

## Rule Count Policy

The v1 canonical L1~L4 transaction/detail rule count is fixed at **31** (2026-06-15: was 32).

The 31 are all `presenter_surface=transaction_detail` 행/review row cards (review-only `L3-12` 포함). `L4-02`(Benford macro)는 2026-06-15 PHASE1-2 family로 이관되어 더 이상 count에 포함되지 않는다(이전엔 "31 row + 1 macro card = 32" 분해였음).

Any external doc may state the total `31`, but must not claim a different split such as `31 + 1 macro`, `32`, `33 rules`, or count `Benford`/`L4-02` in the canonical L1~L4 transaction count.

Included in the 31:

- Canonical `L1-01` through `L4-06` 행 rows as defined by the L1~L4 rule set, **except `L4-02`**.
- `L3-12`, even though it is review/context oriented.

Excluded from the canonical transaction/detail count:

- `L4-02` (Benford macro → PHASE1-2 family, 2026-06-15)
- `Benford` (alias of `L4-02`)
- `L2-03a`, `L2-03b`, `L2-03c`, `L2-03d`
- `D01`, `D02`
- `IC01`, `IC02`, `IC03`
- `GR01`, `GR03`

Display and reporting rules:

- Count, coverage, selectors, export headings, and canonical display titles must use canonical IDs.
- `Benford` may appear as a user-facing alias only when the UI needs to preserve familiar wording.
- Any legacy dashboard or document text saying "32/33 rules" must be interpreted as `31 canonical + L4-02/Benford macro(PHASE1-2)`.
- `D01/D02` belong to account/process analytical review, not the L1~L4 transaction rule count.
- `IC01~IC03` belong to intercompany sidecar details/seeds, not the L1~L4 transaction rule count.
- `GR01/GR03` belong to graph sidecar details, not the L1~L4 transaction rule count.

## Canonicalization Policy

Canonical mappings are locked as follows:

| requested_rule_id | canonical_rule_id | status | presenter_surface |
|---|---|---|---|
| `L2-03a` | `L2-03` | `internal_reason_code` | `drilldown_reason` |
| `L2-03b` | `L2-03` | `internal_reason_code` | `drilldown_reason` |
| `L2-03c` | `L2-03` | `internal_reason_code` | `drilldown_reason` |
| `L2-03d` | `L2-03` | `internal_reason_code` | `drilldown_reason` |
| `Benford` | `L4-02` | `alias` | `account_process_macro` |

Required behavior:

- `requested_rule_id` may be preserved in audit trail, raw hit provenance, debug output, or compatibility payloads.
- Aggregation, count, display title, rule selector, topic routing, and export heading must use `canonical_rule_id`.
- `L2-03a~d` must never create separate user-visible rules, separate counts, separate transaction detail headings, or standalone topic seeds.
- `Benford` must never create a second count beside `L4-02`.
- If a requested ID is unknown but can be mapped by the locked canonicalization table, the request is allowed as a fallback and must emit a validation warning or audit note, not a hard failure.

## Row Detail Eligibility Policy

Row violation detail generation is allowed only when:

```text
presenter_surface == "transaction_detail"
and allow_row_violation_detail == True
```

The following surfaces must not generate row violation detail:

- `context_badge`
- `account_process_macro`
- `intercompany_sidecar`
- `graph_sidecar`
- `drilldown_reason`

Standalone violation copy is forbidden for:

- `L3-05`
- `L3-06`
- `L3-08`
- `L3-10`
- `L3-12`
- `L4-05`
- `L4-06`

Additional row-display prohibitions:

- `L4-02` and `Benford` must not be displayed as transaction row violations.
- `D01/D02` must not be displayed as transaction row violations.
- `GR01/GR03` must not be displayed as transaction row violations.
- `IC01~IC03` may create intercompany sidecar details and intercompany topic seeds, but must not enter L1~L4 transaction detail/count.
- Context/booster/combo-only rules may appear as badges, corroborating context, review rules, or case-level supporting evidence only when attached to an eligible primary case.

Allowed copy style:

- Transaction-detail rules may use direct row-level review wording.
- Context badges must use "검토 신호", "맥락", "보조 근거", or equivalent wording.
- Macro findings must use account/process population wording.
- Sidecar findings must use sidecar/detail wording.
- `drilldown_reason` entries must use reason/badge wording inside the parent canonical detail.

Forbidden copy style for non-row surfaces:

- Do not say standalone "위반", "부정", "조작", "통제 실패 확정", or equivalent conclusive phrasing.
- Direct violation phrasing is allowed only for eligible transaction-detail rules whose metadata explicitly allows standalone violation copy.

## Required Field Policy

Column metadata must separate ledger inputs from generated outputs. Context C column lists are guidance, not automatic row-level required columns.

Locked column source groups:

| group | meaning | may be row-level ledger required? |
|---|---|---|
| `required_ledger_columns` | Columns physically present in `config/schema.yaml` with `required: true`, or a smaller subset that the specific transaction-detail rule cannot run without. | Yes |
| `optional_ledger_columns` | Columns physically present in `config/schema.yaml` with `required: false`. Missing values reduce evidence quality or display richness. | No hard fail by default |
| `derived_columns` | Values computed by feature, detector, aggregator, case builder, or projection logic. | No |
| `sidecar_output_columns` | Columns produced by intercompany or graph sidecar processes, including target/counterpart/path IDs. | No |
| `macro_output_columns` | Columns produced by account/process macro finding logic. | No |

Actual ledger schema baseline:

- Required ledger columns: `document_id`, `company_code`, `fiscal_year`, `fiscal_period`, `posting_date`, `document_date`, `document_type`, `gl_account`, `debit_amount`, `credit_amount`.
- Optional ledger columns include `currency`, `exchange_rate`, `reference`, `header_text`, `created_by`, `user_persona`, `source`, `business_process`, `ledger`, `approved_by`, `approval_date`, `sod_violation`, `sod_conflict_type`, `delivery_date`, `document_number`, `line_number`, `local_amount`, `line_text`, `trading_partner`, `auxiliary_account_number`, `auxiliary_account_label`, `lettrage`, `lettrage_date`, and other `required: false` schema fields.

Examples of fields that must not be declared as required ledger columns:

- Derived: `amount`, `difference_value`, `expected_value`, `actual_value`, `anomaly_score`, `risk_level`, `case_id`, `priority_band`, `evidence_summary`, `violation_details`.
- Macro output: `macro_finding_id`, `macro_priority_score`, `review_score`, `queue_bucket`, `candidate_rows`, `candidate_documents`, `population_key`, `metrics`.
- Sidecar output: `target_document_id`, `counterpart_document_id`, `intercompany_pair`, `match_status`, `paired_amount`, `paired_posting_date`, `graph_finding_id`, `path_nodes`, `path_edges`, `cycle_length`, `graph_score`.
- Legacy/non-schema display names: `approved_at` must map to `approval_date` if available; `reference_number` must map to `reference` if available.

Missing-column handling:

- `missing_column_message` is user guidance for reduced evidence or unavailable detail.
- `missing_column_message` is not an automatic validation hard fail.
- A hard validation failure is allowed only when a rule explicitly requires a physical ledger column to execute and no fallback is defined.
- Macro and sidecar metadata must not require row-level ledger columns merely to render their own detail. They may require macro/sidecar output columns for those surfaces.

## Validation Severity Policy

Validation must distinguish hard errors, warnings, and allowed fallbacks.

Hard errors:

- Unknown `presenter_surface`.
- Unknown `status`.
- Unknown `scoring_role`.
- Canonicalization loop, including `A -> B -> A`.
- `canonical_rule_id` missing for any metadata entry.
- A canonical transaction count other than 31.
- Alias/internal reason code included in the canonical transaction count.
- Duplicate canonical count entries for the same canonical transaction rule.
- `Benford` counted separately from `L4-02`.
- `L2-03a~d` counted separately from `L2-03`.
- `allow_row_violation_detail=True` on any non-`transaction_detail` surface.
- `allow_standalone_violation_copy=True` for locked context/combo/macro/sidecar/reason rules.
- A field absent from `config/schema.yaml` declared as `required_ledger_columns`.
- Macro/sidecar/reason metadata producing transaction row violation detail.

Warnings:

- Optional ledger column missing from runtime input.
- Legacy artifact missing `scoring_role`.
- Legacy artifact has stale `scoring_role` but metadata can correct the final surface.
- `missing_column_message` is used because evidence is incomplete.
- Legacy "33 rules" copy is encountered and normalized to `31 canonical + L4-02/Benford macro(PHASE1-2)`.
- `approved_at` or `reference_number` is encountered and mapped to `approval_date` or `reference`.

Allowed fallbacks:

- `requested_rule_id` is unknown to the canonical display layer but can be mapped by the locked canonicalization table.
- `amount` display is derived from `abs(debit_amount - credit_amount)` or a documented document-level amount formula.
- Counterparty display falls back through `auxiliary_account_number`, `auxiliary_account_label`, `trading_partner`, `reference`, then an explicit unknown label.
- Existing hard-coded display maps may remain as temporary fallback only after the metadata accessor is attempted first.
- Existing raw hit models may preserve old IDs while projection/export attaches canonical metadata.

## Minimal V1 Schema

The first implementation must not attempt the full Context D nested schema. v1 starts with a minimal frozen `RuleDetailMetadata` entry that can gate count, canonicalization, display, columns, and row-detail eligibility.

Required fields:

| field | required meaning |
|---|---|
| `rule_id` | Requested or registry entry ID. |
| `canonical_rule_id` | Canonical ID used for count, aggregation, display, and export. |
| `status` | One of `active`, `macro`, `sidecar`, `alias`, `internal_reason_code`. |
| `presenter_surface` | One of `transaction_detail`, `context_badge`, `account_process_macro`, `intercompany_sidecar`, `graph_sidecar`, `drilldown_reason`. |
| `final_topic` | One of the six locked PHASE1 topics (7→6, intercompany_cycle 삭제→PHASE1-2 family 이관, SoT §7.3), or null only if explicitly non-topic internal metadata. |
| `secondary_topics` | Ordered list of secondary locked topics. Empty list is allowed. |
| `scoring_role` | One of `primary`, `booster`, `combo_only`, `macro_only`. |
| `standalone_rankable` | Whether the rule can seed ranking/case selection by itself. |
| `include_in_l1_l4_transaction_count` | Whether this entry contributes to the canonical 31 count. |
| `allow_row_violation_detail` | Whether row violation detail can be generated. |
| `allow_standalone_violation_copy` | Whether direct standalone violation copy can be generated. |
| `allow_topic_seed` | Whether the entry can seed a topic under its own surface policy. |
| `display_copy` | B-sourced display title/question/review guidance or a compact equivalent object. |
| `column_sources` | Split column groups: `required_ledger_columns`, `optional_ledger_columns`, `derived_columns`, `sidecar_output_columns`, `macro_output_columns`. |
| `conflict_note` | Required when A/B/C/D/legacy behavior needed a lock decision; otherwise empty string. |

Derived or later fields may be added after v1 gates pass, but they must not weaken these required fields.

## Implementation Sequence

Implement in this exact linear order. Do not split this into parallel workstreams.

1. Create the final metadata module and accessor names.
2. Add validation tests for enum values, canonicalization, count policy, and row-detail eligibility before adding the full registry.
3. Define the minimal `RuleDetailMetadata` schema and enums.
4. Add only identity/policy entries from Context A: `rule_id`, `canonical_rule_id`, `status`, `presenter_surface`, `final_topic`, `secondary_topics`, `scoring_role`, `standalone_rankable`, count and eligibility flags.
5. Implement `canonicalize_rule_id()` for `L2-03a~d -> L2-03` and `Benford -> L4-02`.
6. Implement transaction count validation and assert the canonical count is 31.
7. Implement `can_render_row_violation_detail()` and block non-transaction surfaces at the accessor level.
8. Add B-derived `display_copy` for the minimal registry entries, prioritizing non-conclusive wording for context/macro/sidecar/reason entries.
9. Add forbidden-copy validation for standalone-excluded rules and non-row surfaces.
10. Add C-derived `column_sources`, split into the five locked source groups.
11. Validate `required_ledger_columns` against `config/schema.yaml`.
12. Add temporary projection helpers that enrich existing raw hits with `canonical_rule_id`, `presenter_surface`, and eligibility flags without changing stored raw hit models.
13. Apply row-detail gating at the export entry point.
14. Replace dashboard rule count and rule selector logic with metadata count accessors.
15. Replace dashboard labels/detail copy with metadata display accessors, keeping legacy maps only as fallback.
16. Update case builder seed/ranking logic to respect `standalone_rankable`, `allow_topic_seed`, and canonical IDs.
17. Route `L4-02`, `D01`, and `D02` to account/process macro surfaces, not transaction row detail.
18. Route `IC01~IC03` to intercompany sidecar detail/seed only.
19. Route `GR01/GR03` to graph sidecar detail only.
20. Run the full targeted test gate below and fix failures in sequence.

## Test Gate

Implementation is not complete until all gates pass.

Required tests:

- Metadata registry coverage includes every A/B/C/D rule ID and required v1 field.
- Canonicalization returns `L2-03` for `L2-03a~d`.
- Canonicalization returns `L4-02` for `Benford`.
- Canonical transaction/detail count is exactly 31.
- `Benford`, `L2-03a~d`, `D01/D02`, `IC01~IC03`, and `GR01/GR03` do not increase the canonical transaction count.
- `L4-02` is excluded from the canonical count (PHASE1-2 family, 2026-06-15) and cannot render transaction row violation detail.
- Only `presenter_surface=transaction_detail` plus `allow_row_violation_detail=True` can render row violation detail.
- `context_badge`, `account_process_macro`, `intercompany_sidecar`, `graph_sidecar`, and `drilldown_reason` always deny row violation detail.
- `L3-05`, `L3-06`, `L3-08`, `L3-10`, `L3-12`, `L4-05`, `L4-06` cannot generate standalone violation copy.
- `L4-02/Benford`, `D01/D02`, and `GR01/GR03` cannot appear as transaction row violations.
- `IC01~IC03` can seed intercompany sidecar/topic detail but cannot enter L1~L4 transaction detail/count.
- Column validation rejects non-schema fields in `required_ledger_columns`.
- Optional ledger column absence produces warning or missing-column guidance, not default hard fail.
- Legacy artifacts with missing or stale `scoring_role` are corrected by metadata surface and role.
- Legacy "33 rules" display paths normalize to `31 canonical + L4-02/Benford macro(PHASE1-2)`.
- Export headings and dashboard selectors use canonical IDs.

Recommended command groups:

- Metadata unit tests.
- Export row-detail gating tests.
- Dashboard rule count/selector tests.
- Case builder seed/ranking compatibility tests.
- Existing PHASE1 topic scoring tests.

## Open Questions

None for v1 implementation.

Deferred beyond v1:

- Whether to expand from minimal `RuleDetailMetadata` into the full nested Context D registry.
- Whether to persist `canonical_rule_id` and `presenter_surface` directly into raw hit storage instead of enriching at projection time.
- Whether `L4-02` macro context should attach to every eligible transaction case in the same account/process population or only to explicit account/process review queues.

## IC01 Evidence Level Sidecar Policy (2026-05-23, D065)

> 이관 (2026-06-14): intercompany_cycle topic 삭제에 따라 IC01~IC03은 PHASE1-1 점수 topic이 아니라 **PHASE1-2 family(graph/relational)의 정식 대상**으로 이동했다(SoT `docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md` §7.3). canonical 31 transaction/detail rule count와 `intercompany_sidecar` surface 분류(count 외부, row violation detail 금지)는 변경 없이 유지된다. 아래 IC01 evidence level sidecar 정책은 sidecar 산출물 계약으로 유효하나, PHASE1-1 점수경로 연결 부분(score_aggregator floor 차별 등)은 family 이관 시 정합 처리한다.

본 절은 IC01 의 evidence level sidecar 정책을 별도 lock 으로 명시한다. canonical 31 transaction/detail rule count 정책 (§Rule Count Policy) 과 `RULE_DETAIL_METADATA_REGISTRY` 본문은 변경하지 않는다.

Locked decisions:

- 외부 rule id 는 `IC01` 단일을 유지한다. `IC01_A` / `IC01_B` 와 같은 분리는 도입하지 않는다.
- `IC01`, `IC02`, `IC03` 의 canonical excluded 분류는 그대로 유지된다 (`Excluded from the canonical transaction/detail count` §). `intercompany_sidecar` surface 정책 변경 없음.
- `SEVERITY_MAP` 의 IC01/IC02/IC03 점수 (`IC01=3, IC02=2, IC03=2`) 는 변경하지 않는다 (`src/detection/constants.py:195`).

신규 sidecar column 2 종 (canonical 31 count 외부, `intercompany_sidecar` surface 의 일부):

```
column                      값                                             의미
────────────────────────────────────────────────────────────────────────────────────────────────────────
ic01_evidence_level         "high"                                         IC 모집단 + 그룹 매칭 실패 +
                                                                           명시적 회사 상대방 +
                                                                           관계사/그룹 master 대사 실패
ic01_evidence_level         "review"                                       IC 모집단 + 그룹 매칭 실패 +
                                                                           (partner 결측 OR 형식 비표준 OR
                                                                            master mapping 미정)
ic01_evidence_level         ""                                             해당 없음 (IC01 미해당 또는
                                                                           customer/vendor master 제외)
ic01_review_reason          "missing_partner"                              trading_partner 결측
ic01_review_reason          "nonstandard_format"                           trading_partner 형식 비표준
                                                                           (partner_format regex 비매칭)
ic01_review_reason          "mapping_uncertain"                            master mapping 미정 (폴백 적용)
ic01_review_reason          ""                                             evidence_level != "review" 또는
                                                                           IC01 미해당
```

Sidecar 저장 위치 (2026-05-23 보정):

- 두 sidecar column 은 `DetectionResult.metadata["row_sidecar"]: dict[str, pd.Series]` 에 보관한다. `DetectionResult.details` 에는 부착하지 않는다.
- `DetectionResult.details` 는 numeric rule-score (IC01/IC02/IC03 `float64`) matrix 계약을 유지한다. 문자열 sidecar 가 `details` 에 섞이면 `src/metrics/ground_truth_evaluator.py:1152, 1537` 과 `src/detection/score_aggregator.py::_collect_flagged_rules` 의 `details > 0` 비교에서 TypeError 가 발생하므로 분리 필수.
- 런타임 검증: `result.details.columns == ['IC01', 'IC02', 'IC03']`, `result.details.dtypes` 전부 `float64`, `(result.details > 0).any().any()` 정상 동작.

Review-only 신호의 confirmed 격상 방지 (2026-05-23):

- IC01 review-level (`ic01_evidence_level == "review"`) 은 `details["IC01"]` score 가 `0.0` 으로 유지된다. high 만 `score = 1.0` 으로 산출된다.
- 따라서 `flagged_rules` / case seed / ground-truth 평가에서 confirmed violation 으로 격상되지 않는다.
- `score_aggregator._extract_ic01_evidence_level()` 는 `metadata["row_sidecar"]["ic01_evidence_level"]` 에서 evidence level 을 read 하여 row-level `anomaly_score` 의 Low floor (0.20) 만 부여한다.
- 근거: `AGENTS.md` "review-only signals must not become confirmed violations".

Lock 조건:

- 두 sidecar column 은 `intercompany_sidecar` surface 산출물이다. `RULE_DETAIL_METADATA_REGISTRY` 의 rule_id enum 에는 포함하지 않는다.
- `presenter_surface=intercompany_sidecar`, `include_in_l1_l4_transaction_count=False`, `allow_row_violation_detail=False` 정책은 IC01 본 entry 와 동일하게 적용된다.
- 두 sidecar column 의 생성 책임은 `src/detection/intercompany_rules.py::ic01_unmatched_intercompany()` 와 `src/detection/intercompany_matcher.py::_build_result()` 에 있다. 후자는 `DetectionResult.metadata["row_sidecar"]` 에 부착한다. `score_aggregator._apply_intercompany_exception_corroboration()` 는 `metadata["row_sidecar"]` 를 read-only 로 소비한다 (구버전 `details` fallback 도 지원).
- dashboard / export 표시 맵의 외부 rule id 는 `IC01` 단일 유지. evidence level 은 상세 panel 또는 sidecar drill-down 에서만 노출한다.
- review_reason 코드 enum 확장은 별도 결정문 (후속 D-series) 으로만 허용한다. v1 lock 시점에는 `missing_partner`, `nonstandard_format`, `mapping_uncertain`, `""` 4 값만 유효하다.

관련 결정문 / 문서:

- `docs/spec/DECISION.md` D065 (2026-05-23) — IC01 sidecar 직접 의존 제거, evidence level 정책 도입.
- `docs/spec/DETECTION_RULES.md` L3-03 절 evidence level sidecar 정책 표.
- `docs/archive/completed/PHASE1_TOPIC_SCORING_V1_LOCK.md` 관계사·내부거래·순환구조 topic floor 차별 보조 절. 단, 해당 topic은 PHASE1-2 family로 이관됨(SoT `docs/spec/PHASE1_TIER_EVIDENCE_BASIS.md` §7.3, 2026-06-14). IC01~IC03은 PHASE1-1 점수 topic이 아니라 PHASE1-2 family(graph/relational)의 정식 대상이며, 아래 sidecar/evidence level 정책은 family 이관 시 정합 처리한다. canonical 31 transaction/detail rule count 정책은 변경 없음.

## RuleExplanation Extension Area (2026-05-17)

Sprint B3-meta adds a separate explanation extension without changing the locked `RuleDetailMetadata` keys. The v1 lock remains the source of truth for canonical ID, count, presenter surface, row-detail eligibility, scoring role, and column-source policy. `RuleExplanation` is an additive metadata layer consumed through `src/detection/explanation_registry.py`.

Required `RuleExplanation` fields:

| field | meaning |
|---|---|
| `principle` | Audit principle or control expectation behind the rule. |
| `violation_reason` | Why the rule flags or raises review context. |
| `audit_next_action` | Auditor's next review action; must not conclude fraud by itself. |
| `reference` | PCAOB/ISA or analytical-review reference string. |

Extension rules:

- `RuleExplanation` must be frozen and JSON serializable.
- The explanation registry may add coverage for active detector rules, macro rules, or future UI use, but must not mutate `RULE_DETAIL_METADATA_REGISTRY`.
- Non-row and macro rules must retain review-context language. `L4-02`, `D01`, and `D02` remain account/process analytical review signals, not transaction-row violation detail.
- `dashboard/` consumers must call `get_rule_explanation(rule_id)` in a future UI sprint instead of importing detector modules directly.
