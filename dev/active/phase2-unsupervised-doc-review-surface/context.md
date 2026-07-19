# PHASE2 Unsupervised Document Review Surface - Context & Decisions

## Status

- Phase: BLOCKED — VAE target 재정의 확정, semantic-clean 데이터 대기
- Progress: P1~P5 구현/측정 완료. target 재정의 확정(2026-06-02). feature 재설계는 데이터 대기.
- Last Updated: 2026-06-02
- Current blocker: semantic-clean 정상 모집단(datasynth journal realism, 별도 트랙) 미완.
  그 전까지 VAE는 diagnostic/companion 유지, 입력 feature 재설계 착수 보류.

## CONFIRMED — VAE target 재정의 (2026-06-02)

근거·구현방향·상태는 `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md` §6 단일 출처.
요약:
- 근본 결함: VAE는 target이 미정의(anti-leakage 잔여 컬럼 include-by-default)이고, 해석
  feature 7/7이 PHASE1 룰·타 family와 중첩 → 차별점 0 → PHASE1 밖 ~0. "broad statistical
  review" 프레이밍은 PHASE1 L4 statistical_outlier와 충돌.
- 확정 target: multivariate joint-combination atypicality (account_subtype × business_process
  × counterparty_type × document_type × line_text_family 조합 비정형성). 단일 축은 PHASE1/
  family 소유라 배제. autoencoder의 유일한 비중첩 niche = joint coherence.
- 구현방향: "statistical" 프레이밍 폐기 / 단일축 신호 입력·score 배제 / 입력 feature를
  semantic 구조 범주형 중심으로 재설계(잔여-컬럼 include 폐기) / joint-rarity 기준 score /
  P1~P3 document-case 산출은 evidence carrier로 유지.
- 상태: Class B → semantic-clean 데이터 필요(별도 트랙 생성 중). 도착 전 feature 재설계
  보류. 합성 평가는 mutation-type 분리 mechanism 증거 한정, production recall 주장 금지.
- 기록 위치: 결정서 §6, docs/spec/TROUBLESHOOT.md TS-18,
  docs/guide/users/UNSUPERVISED_DOCUMENT_COMPANION_SURFACE.md.
- **Frozen design spec 작성 완료(결정서 §7, 2026-06-02)**: input feature set(구조 범주형 7개
  전용)·배제 입력·scoring·acceptance criteria(A1~A5, mechanism evidence)를 datasynth realism
  contract 스키마에만 의존해 데이터 내용 안 보고 동결. fitting 차단 근거는 §7-0 표.
- Next: 데이터 트랙(semantic-clean) 완료 시 → 비지도 학습 + §7-4 A1~A5 1회 검증. 그 전 착수 없음.

## PENDING datasynth 요구 (VAE 전용, 아직 family 트랙에 미반영 — 2026-06-03)

datasynth family 트랙(semanticfix8d~8o)은 전부 hard-violation/family 디텍터 현실화다. VAE용
semantic_v1에는 아래가 **추가로** 필요하며 현재 누구의 plan에도 없다. semantic_v1 착수 전 반영 필요.

1. **valid-but-atypical truth class (VAE 고유 평가 대상)**: semantic validator가 만들어지면 hard
   mismatch(불가능 조합)는 validator=rule이 먹는다. 그러면 VAE가 hard mismatch를 겨냥하면 또 중첩
   (이번엔 validator와). 따라서 mutator는 (a) hard semantic violation(validator/rule truth)과
   별개로 (b) **validator가 허용하지만 정상 분포에서 jointly 희소·맥락상 이상한 조합**을 VAE truth로
   분리 주입해야 한다. (b)가 없으면 semantic_v1이 와도 VAE 평가 대상이 0.
2. **§6/§7 refinement 필요**: VAE를 validator 하류로 재포지셔닝(target = allowed-but-rare soft
   atypicality). §7-1 순수 저카디널 구조 categorical만으로는 validator와 중첩 → soft rarity가 의미
   있으려면 higher-card/context dim(counterparty identity 그룹, amount/timing bucket)을 joint에
   포함해야 함(현 §7-1 "v2 후보"가 실은 core). ← 사용자 승인 후 §6/§7 편집.
3. **GL/timestamp 오라클 선결**: 8o 잔존 WARN 중 gl_account fraud-only(8010/2700)는 account_subtype
   파생 시 VAE feature로 전이되므로 semantic_v1 전에 정상 사용 추가로 닫아야 함. posting_date 정확초
   타임스탬프 오라클은 timeseries/결산 realism 결함으로 분산 필요.
4. **owner 재라벨**: `unsupervised=statistical 139` / `broad_statistical_only_owner`는 §6 폐기
   프레이밍. semantic_v1에서 (b) soft-atypical owner로 교체.

## Source Documents Read

- `CLAUDE.md`
- `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`

## Missing Expected Documents

- `docs/TASKS.md` is missing in the current checkout.
- `docs/archive/completed/NEW_TASKS.MD` is missing in the current checkout.
- `dev/README.md` is missing in the current checkout.

These missing files were required or referenced by agent policy, so this P0 plan uses the provided redesign decision document and the inspected source files as the working source of truth.

## Key Files Inspected

**Core model and builder**
- `src/models/phase2_case.py` - frozen PHASE2 case dataclasses and `Phase2CaseSet`.
- `src/services/phase2_unsupervised_case_builder.py` - current row-level VAE case builder with q95 ECDF gate and soft document-priority ordering.
- `src/services/phase2_case_set_orchestrator.py` - routes `ml_unsupervised` detector output into `Phase2CaseSet.unsupervised_cases`.

**Downstream contracts**
- `src/services/phase2_case_family_aggregator.py` - converts row detector scores into PHASE1 case overlay inputs and attaches unsupervised explanation features display-only.
- `src/services/phase2_case_contract.py` - builds family contributions, review bands, and display overlays while preserving PHASE1 priority.
- `src/services/phase2_inference_service.py` - attaches overlays and native case set post-inference.
- `src/pipeline.py` - `PipelineResult` carries `phase2_case_set`, overlays, and policy summaries.

**Dashboard**
- `dashboard/components/phase2_native_case_panel.py` - current unsupervised table is row-like and shows anomaly score plus one top feature.
- `dashboard/components/phase2_native_case_metrics.py` - counts native case totals and exposes unsupervised cases.

**Locks and regressions**
- `tests/modules/test_services/test_unsupervised_companion_readiness.py` - locks companion framing, anti-fitting guardrails, and current downstream helper behavior.

## Existing Invariants to Preserve

1. `Phase2CaseSet` stores family cases as tuples and iterates deterministically.
2. `Phase2RowRef.index_label` must be canonicalized through `make_row_ref`.
3. `UnsupervisedCase` and related case dataclasses are frozen.
4. `build_unsupervised_cases` returns a tuple and gracefully returns `()` on empty/missing scores/details.
5. Zero scores remain ECDF 0; only positive scores receive percentile ranks.
6. q95 gate defaults to `0.95`.
7. `evidence_signature` must only contain model/schema identity, not score, threshold, or ECDF.
8. PHASE1 is not a builder input; PHASE1 references are attached later by linker.
9. `explanation_features` are display-only and must not enter scoring or ranking.
10. Product role remains `broad_statistical_review_companion_evidence_surface`.

## Approval Decisions Required

### Decision A: Data Model Shape

**Option A1 - Extend `UnsupervisedCase`**

Use the existing `UnsupervisedCase` class, change its intended semantics to document-level, set `unit_type="document"`, allow multiple `row_refs`, and add document context fields.

Pros:
- Minimal disruption to `Phase2CaseSet.unsupervised_cases`.
- Existing linker, dashboard metrics, export status, and policy summary can keep their current family slot.
- Lower migration cost for P2/P3.

Cons:
- The class name does not make the document-level semantics explicit.
- Tests and comments must strongly prevent a future row-case regression.
- Existing fixtures with `unit_type="row"` need careful compatibility handling or updates.

**Option A2 - Add `UnsupervisedDocumentCase`**

Create a new frozen dataclass, likely subclassing `UnsupervisedCase` or `Phase2CaseBase`, and store it in `Phase2CaseSet.unsupervised_cases` as the new unsupervised case type.

Pros:
- Document-level semantics are explicit.
- Easier to encode document aggregate fields without overloading row-era fields.
- Reduces ambiguity in dashboard and diagnostics.

Cons:
- More import/type ripple across orchestrator, dashboard, tests, policy summary, and any serialization assumptions.
- If it subclasses `UnsupervisedCase`, the type hierarchy must avoid ambiguous row/document fields.
- If it does not subclass `UnsupervisedCase`, several `isinstance(UnsupervisedCase)` checks and imports must change.

**Recommended default for approval**: Option A1 if the priority is controlled blast radius; Option A2 if explicit semantic separation is more important than migration cost.

### Decision B: Document-Level Score Aggregation

**Option B1 - Max Row Score**

Document `family_score` and `anomaly_score` use the maximum gated row VAE score; document ECDF uses the maximum gated row ECDF.

Pros:
- Closest to current row surface.
- Keeps score semantics simple and auditable.
- Avoids introducing another tunable formula.

Cons:
- One extreme row can dominate a large document.
- Does not reward corroboration from multiple anomalous rows except through evidence count/context.

**Option B2 - Top-K Mean of Gated Row Scores**

Document score uses the mean of top K gated row scores, with K fixed in code and documented.

Pros:
- Reduces single-row dominance.
- Better reflects document evidence bundle when several rows are anomalous.

Cons:
- K becomes a new design parameter.
- May be perceived as a score transformation even if VAE score itself is unchanged.
- Requires clear tests to prove q95 gate and raw VAE score are not tuned.

**Option B3 - Max Score for Ranking, Separate Evidence Context for Corroboration**

Keep `family_score=max(row_score)` and add separate non-scoring fields such as `evidence_row_count`, `top_score_mean`, or `score_spread` for display/diagnostics only.

Pros:
- Preserves current score behavior while surfacing document-level evidence strength.
- Avoids creating a new ranking formula.
- Pairs well with anti-fitting guardrails.

Cons:
- Review order may still be driven by the single strongest row.
- Dashboard must make clear which fields are context-only.

**Recommended default for approval**: Option B3.

### Decision C: Top Features and Reason Tags at Document Level

**Option C1 - Representative Max-Score Row Features**

Use top features from the highest-score evidence row as the document case top features.

Pros:
- Simple and aligned with current aggregator representative-row logic.
- Deterministic.
- Low risk of changing explanation semantics.

Cons:
- May hide secondary reasons from other anomalous rows in the same document.

**Option C2 - Merge Top Features Across Evidence Rows**

Merge top features across all gated evidence rows, sort by absolute contribution, and keep top N.

Pros:
- Better document-level explanation bundle.
- More useful when a document has multiple anomaly modes.

Cons:
- Contribution values may not be directly comparable across rows without careful framing.
- More implementation and test surface.

**Recommended default for approval**: Option C2 for document review usefulness, with representative max-score row retained as a trace field if needed.

### Decision D: Evidence Row Display Policy

**Option D1 - Show All Gated Evidence Rows in Detail**

The master list remains one document per row; detail view lists all gated evidence rows.

Pros:
- Full evidence transparency.
- Natural fit for audit review.

Cons:
- Large documents may create long detail panels.

**Option D2 - Show Top N Evidence Rows with Count and Overflow**

The detail view shows top N evidence rows sorted by score/ecdf and displays total evidence row count.

Pros:
- Controls UI burden.
- Keeps master-detail usable for large documents.

Cons:
- Requires an explicit N.
- Reviewer may need a secondary path to inspect all rows.

**Recommended default for approval**: Option D2 with an overflow count, while raw ledger drilldown remains available for the selected document.

### Decision E: Native Ordering Strategy

**Option E1 - Remove Row-Native Ordering Option for Unsupervised**

Once the builder emits document cases, keep one document-level deterministic ordering and remove the `native` row ordering branch from the active path.

Pros:
- Avoids carrying a row-era concept into the new surface.
- Reduces future confusion.

Cons:
- Existing tests or diagnostic scripts that request `native` need updates.

**Option E2 - Keep `native` as Diagnostic Fallback**

Keep the `ordering_strategy` parameter, but redefine `native` as document max-score order rather than row order.

Pros:
- Backward-compatible function signature.
- Useful for diagnostics comparing document-score order vs context-priority order.

Cons:
- The word `native` may remain ambiguous.
- Requires clear policy summary updates.

**Recommended default for approval**: Option E2 during migration, then document that row-native ordering is retired.

### Decision F: Missing `document_id` Handling

**Option F1 - Singleton Fallback by Canonical Row Identity**

If a gated row has no usable `document_id`, emit a singleton document-case keyed by its canonical row ref and mark the grouping mode in `case_generation_reason`.

Pros:
- Preserves graceful degradation and avoids silently dropping anomalous VAE rows.
- Keeps existing sparse-fixture and partial-data paths closer to current behavior.
- Makes the fallback auditable through explicit metadata.

Cons:
- Some cases remain effectively row-like when source data lacks document identifiers.
- Dashboard copy must avoid implying a true accounting document group exists for fallback cases.

**Option F2 - Exclude Rows Without `document_id`**

Only emit document-cases for rows that have a usable document identifier.

Pros:
- Strictly enforces the document-case concept.
- Avoids mixed true-document and fallback-singleton semantics.

Cons:
- Drops VAE evidence in imperfect source data.
- Makes debugging harder when detector output exists but the review surface is empty.

**Recommended default for approval**: Option F1 with `case_generation_reason["document_grouping"] = "fallback_row_identity"` or equivalent display/debug metadata.

## Proposed Approved Set

Unless you choose otherwise, the lowest-risk implementation set is:

- A1: extend `UnsupervisedCase` with `unit_type="document"`.
- B3: use max score/ecdf for ranking fields and put corroboration fields in display-only context.
- C2: merge top features/reason tags across evidence rows.
- D2: show top N evidence rows plus total evidence count.
- E2: keep ordering strategy signature as diagnostic compatibility, but redefine it for document cases.
- F1: keep singleton fallback for gated rows without `document_id`, with explicit grouping metadata.

## APPROVED Decisions (2026-06-01, locked)

User approved the recommended set with two acknowledged lock-update conditions.

| Decision | Approved | Binding notes |
|----------|----------|---------------|
| A | **A1** extend `UnsupervisedCase`, `unit_type="document"` | MUST add an invariant test asserting newly built unsupervised cases are `unit_type="document"` (prevent row-case regression). |
| B | **B3** `family_score`/`anomaly_score` = max gated row score/ecdf; corroboration fields (`evidence_row_count`, `top_score_mean`, `score_spread`) are display/diagnostic only | family_score stays the raw VAE signal. Pressure/single-row dominance is controlled by the ordering layer (soft-guard hybrid), NOT by transforming family_score. Do not introduce a top-k/K parameter into the ranking score. |
| C | **C2** merge top features/reason tags across gated evidence rows, sort by abs contribution, keep top N | Keep representative max-score row as a trace field. Display-only; never enters scoring/ranking (invariant 9). |
| D | **D2** detail shows top N evidence rows + total evidence count (overflow) | N is a UI micro-value; implementer picks a reasonable default. Raw ledger drilldown stays available for the selected document. |
| E | **E2** keep `ordering_strategy` signature; redefine `native` as document max-score order (row-native retired) | Useful for P5 diagnostic comparison (document-score order vs context-priority order). Document that row-native ordering is retired. |
| F | **F1** missing `document_id` -> singleton document-case keyed by canonical row ref, with `case_generation_reason["document_grouping"]="fallback_row_identity"` | Dashboard copy MUST NOT imply a real accounting document group exists for fallback singletons. |

### Acknowledged lock-update conditions (intended, not silent regression)

1. **`case_generation_changed` flag**: P3 deliberately updated this lock from
   `False` to `True` and added `case_generation_change="row_case_to_document_case"`.
   q95/VAE score/threshold/PHASE1 ranking/PHASE2 fusion guardrails remain unchanged.
2. **Companion readiness fixture migration**: the readiness fixture currently builds
   `unit_type="row"` cases. P1/P2 migrate these fixtures to document-case. The row-shaped
   fixture is repurposed to cover the F1 fallback-singleton path, not kept as a legacy
   default.

### Anti-fitting guardrails reaffirmed (all must stay)

- truth / owner / scenario label, PHASE1 rank, matched result: NOT scoring/ranking/selector inputs.
- q95 gate, VAE score, threshold, weights: unchanged; not tuned to recall.
- DataSynth: not regenerated/altered to match VAE score.
- "이상치 = 부정" language forbidden; product role stays
  `broad_statistical_review_companion_evidence_surface`, `fraud_primary_recall_family=False`.

## P2 Decision — repeated_normal_pressure penalty held at 0.0 (MUST validate in P5)

- Row-era soft guard penalized documents by `case_count` (number of gated anomalous rows
  in a document). At document granularity (1 document = 1 case) that proxy is meaningless,
  so P2 set the pressure penalty to 0.0 rather than inventing an `evidence_row_count`-based
  penalty without justification (avoids unjustified heuristic + fitting surface). Approved.
- **Hypothesis (NOT yet verified)**: document-grouping itself collapses repeated-normal
  documents from many queue slots to one, so TOP500 `repeated_normal_pressure` should land
  near the measured soft-guard range (~0.18-0.24) without any penalty.
- **P5 binding check**: measure TOP500 repeated_normal_pressure on the document-case
  surface. If it stays low -> keep penalty at 0.0 (no new control needed). If it spikes to
  ~0.5+, design a *justified* document-level pressure signal (measurement-first, no recall
  fitting). Do not re-add a row-count penalty without this measurement.

## P5 Data Baseline Decision (2026-06-02) — v33d with A/B/C/D labeling

- P5 measures on the CURRENT dataset `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d`
  (QG3 truth_check = PASS, 0 failures, no leakage columns, full mutation provenance).
- Rationale: this redesign changed the review UNIT (row -> document), not VAE features. The
  current VAE feature basis is mostly Class A (amount_z, round_amount, posting weekend/
  after-hours, posting_lag, manual_entry, partner_frequency), which
  `dev/active/datasynth-journal-realism-rebuild/phase2-vae-testability-matrix.md` classifies
  as testable on current synthetic data.
- KNOWN, ACCEPTED LIMITATION: the `datasynth-journal-realism-rebuild` (semantic validator +
  semantic-clean normal population) is still Planning (0/7). Normal rows may still contain
  semantically impossible combinations. P5 must therefore label axes by testability class:
  - **Class A (trusted)**: amount-tail, period-end, posting time/manual, reversal, related-party rarity.
  - **Class B (low confidence, synthetic-mixing artifact possible)**: account/process rarity,
    document/text mismatch, counterparty-mismatch context. The P3-attached
    `account_process_rarity` context is Class B and MUST be labeled as such.
  - Report all results as "detector behavior on controlled data", NOT production recall/precision
    (matrix lines 14, 106-110). fraud recall stays diagnostic-only.
- T4-14 period-end concentration QG WARNING (2.60x vs >=3x target) is an under-shoot (signal
  conservative, not inflated) -> P5 footnote only, non-blocking.
- Do NOT alter DataSynth to improve VAE metrics. The realism rebuild, if pursued, is a separate
  accounting-correctness project, out of scope for this redesign sprint.

## P5 Diagnostic Result (2026-06-02) — pressure gate failed

- Artifact: `artifacts/unsupervised_document_review_surface_20260601.json`.
- History: `artifacts/unsupervised_document_review_surface_history.json`.
- Dataset remained `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d`.
- Current document-case default emits 51,094 document review cases. It keeps q95/VAE
  score/threshold unchanged and does not use truth/owner/scenario/PHASE1 rank/matched result
  as selector or ordering inputs.
- S1 TOP500 candidate-outside docs: primary 0, companion 3. Against the row soft-guard
  baseline, deltas are primary -5 and companion -28.
- S2 TOP500 repeated_normal_pressure max is 1.00, outside the row soft-guard reference
  range 0.18-0.24. **Conclusion: penalty 0.0 is not confirmed as safe.** Document grouping
  alone did not reduce repeated-normal pressure; next work needs a justified document-level
  pressure signal, measurement-first and without recall fitting.
- S3 top feature / reason tag attach rates are 1.0 / 1.0. S4 document review unit is met.
  S5 guard flags passed. `account_process_rarity` remains Class B (synthetic mixing artifact
  possible), while amount-tail and period-end are Class A on controlled data.
- Current product default ordering is context-free `document_case_max_score_order`; amount-tail,
  period-end, and account/process rarity are display-only context fields.

## P5 Result + Direction (2026-06-02) — rework to genuine usefulness

- P5 measured document_case_default on v33d: 51,094 cases / 51,094 documents (1:1, no
  consolidation, fallback_singleton=0), TOP500 repeated_normal_pressure = 1.0, beyond-PHASE1
  primary 0 / companion 3. This reproduces the native_row_queue failure. S1 and S2 FAILED.
- Root cause: raw VAE max-score ranks GLOBAL statistical extremity, which on this data equals
  period-end large NORMAL entries. "extreme != review-worthy." document-grouping cannot help
  because q95-gated rows are ~1 per document. The row soft-guard's 0.24 pressure came from the
  repeated-normal guard, not grouping; P2 held that guard at 0.0.
- USER DECISION (2026-06-02): do NOT demote (B) or ship-with-limitation (C). Rework from the
  root until the surface is genuinely useful, WITHOUT fitting (truth/owner/scenario/PHASE1 rank
  not used for selection/order; q95/score/threshold/weights not tuned to recall; DataSynth not
  altered).
- Direction: move from GLOBAL anomaly to PEER-RELATIVE (contextual) anomaly. Two build
  destinations, decided by measurement (P5.5 probe) not guess:
  - A. ordering-layer rework (no VAE retrain): keep VAE score, add audit-justified
    repeated-normal suppression + cohort-relative re-rank.
  - B. representation/gate rework (VAE retrain): make features/gate cohort-conditional so the
    VAE itself stops surfacing extreme-but-normal. Higher ceiling, more cost, 8GB VRAM bound.
- P5.5 = measurement-first probe (model untouched) to test whether cohort-relative re-rank +
  repeated-normal suppression separates targets better than raw max-score on v33d. Anti-fitting
  discipline: define a SMALL a-priori set of audit-justified signals, justify each in the script
  before measuring, report ALL, and pick by audit-justification + robustness, NOT by max S1.

## Known Issues and Watchpoints

- `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md` still says “초안”; P6 should update status only after implementation and P5 actuals.
- P3 policy summary now says `case_generation_changed=True` with
  `case_generation_change="row_case_to_document_case"`; this is an intended lock update, not
  a silent regression.
- Readiness fixtures now use document cases; the missing-`document_id` row-shaped fixture is
  retained only as the F1 fallback singleton path test.
- `phase2_case_contract._adjusted_priority` still computes an overlay value from family scores.
  P3 confirmed it remains display overlay only; primary queue order and queue fusion regression
  tests pass.
- Historical soft-guard ordering remains a diagnostic baseline only. P5 did not approve it as
  current product default. Current default ordering uses document max score; context fields are
  display-only until a justified document-level pressure signal is designed and measured.
