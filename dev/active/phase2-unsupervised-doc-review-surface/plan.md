# PHASE2 Unsupervised Document Review Surface - Strategic Plan

## Executive Summary

PHASE2 VAE/Unsupervised family is being redesigned from a row anomaly queue into a document-level anomaly review surface. The detector score, zero-preserving ECDF, q95 gate, threshold, and model weight stay unchanged; only the review case unit, evidence packaging, dashboard surface, and diagnostic harness change.

P0 design choices are approved in `context.md` as A1/B3/C2/D2/E2/F1. P1 may proceed with model-only TDD; builder, contract, dashboard, evaluation, and documentation phases remain scoped to their later steps.

## Current State

- `src/services/phase2_unsupervised_case_builder.py` emits one `UnsupervisedCase` per anomalous row with `unit_type="row"`.
- The current default ordering (`hybrid_with_soft_repeated_normal_guard`) already uses document-level review priority, but it only reorders row cases and does not make one document equal one review case.
- `src/models/phase2_case.py` has `UnsupervisedCase` as a frozen dataclass that stores a tuple of `Phase2RowRef`, but the builder currently fills exactly one row ref.
- `src/services/phase2_case_set_orchestrator.py` stores unsupervised cases inside `Phase2CaseSet.unsupervised_cases`, so downstream contracts can keep the same family slot if the model remains compatible.
- `src/services/phase2_case_family_aggregator.py` and `src/services/phase2_case_contract.py` currently aggregate row detector scores into PHASE1 case overlays and keep unsupervised explanation features display-only.
- `src/services/phase2_inference_service.py` attaches both PHASE2 overlays and the native `Phase2CaseSet` after standalone inference; PHASE1 is post-inference context only.
- `dashboard/components/phase2_native_case_panel.py` renders unsupervised rows as row-level VAE entries with `anomaly_score` and one top feature.
- `dashboard/components/phase2_native_case_metrics.py` counts `Phase2CaseSet.unsupervised_cases` and currently excludes unsupervised from the “top native family” helper by default.
- `tests/modules/test_services/test_unsupervised_companion_readiness.py` locks the current companion role: `product_role="broad_statistical_review_companion_evidence_surface"`, `fraud_primary_recall_family=False`, q95 no-change, and anti-fitting guard flags false.

## Proposed Direction

Redesign the unsupervised family as:

- one document equals one PHASE2 unsupervised review case;
- anomalous rows inside the document are evidence rows, not separate review cases;
- document-level score/ecdf/context are case metadata for ordering and explanation;
- score remains a raw VAE signal for gate/order, not a fraud conclusion;
- review usefulness and evidence contribution replace fraud recall as the primary evaluation axis.

## Non-Negotiable Guards

- Keep VAE anomaly score unchanged.
- Keep zero-preserving ECDF unchanged.
- Keep q95 gate at `0.95`.
- Do not tune threshold or weight against truth recall.
- Do not use truth, owner, scenario, PHASE1 rank, or matched result as scoring, selector, or ranking input.
- Do not alter DataSynth to match VAE score behavior.
- Do not describe statistical outliers as confirmed fraud, violations, or errors.
- Keep `explanation_features` display-only; do not feed top features or reason tags into scoring.
- Keep primary queue, PHASE1 ranking, and phase2 fusion behavior unchanged unless a regression test explicitly shows a pre-existing lock conflict.

## Implementation Phases

### P0: Planning and Design Approval

**Goal**: Create the implementation plan and collect user approval for design choices.

**Tasks**:
- [x] Read the redesign decision document.
- [x] Read current unsupervised builder, model, aggregator, contract, inference, pipeline, dashboard, and companion readiness lock.
- [x] Create P0 plan/context/tasks documents under `dev/active/phase2-unsupervised-doc-review-surface/`.
- [x] Receive user approval for the choices listed in `context.md`.

**Verification**:
- P0 code changes: none.
- User approved the selected model, scoring aggregation, evidence row display, ordering policy, and missing-document fallback before P1.

### P1: Document-Case Data Model

**Goal**: Define the immutable data representation for document-level unsupervised review cases.

**Files**:
- `src/models/phase2_case.py`
- `tests/modules/test_models/test_phase2_unsupervised_document_case.py` or a nearby existing model test

**Tasks**:
- Add RED tests for frozen dataclass behavior and tuple-based evidence rows.
- Represent multiple anomalous row refs in one document-level review case.
- Include document-level aggregate score, aggregate ECDF, top features, reason tags, and context fields for amount-tail, period-end, account/process rarity, and repeated-normal pressure.
- Preserve existing invariant style and `Phase2CaseSet` tuple semantics.

**Verification**:
- `uv run pytest tests/modules/test_models/test_phase2_unsupervised_document_case.py -q`
- `uv run ruff check src/models/phase2_case.py tests/modules/test_models/test_phase2_unsupervised_document_case.py`

### P2: Case Builder Row-to-Document Aggregation

**Goal**: Emit document-level unsupervised cases from row-level VAE detector output.

**Files**:
- `src/services/phase2_unsupervised_case_builder.py`
- `tests/modules/test_services/test_phase2_unsupervised_case_builder.py` or matching existing service test

**Tasks**:
- Add RED tests proving same-document anomalous rows collapse into one case.
- Keep q95 gate and zero-preserving ECDF exactly as-is.
- Exclude rows below gate before document grouping.
- Preserve graceful empty behavior.
- Preserve evidence signature identity rules by keeping score and threshold out of `evidence_signature`.
- Attach document-level top features and reason tags from evidence rows.
- Remove or neutralize row-native ordering only according to the approved P0 decision.

**Verification**:
- Focused pytest for unsupervised builder tests.
- `uv run ruff check src/services/phase2_unsupervised_case_builder.py <builder-test-path>`

### P3: Aggregator and Contract Wiring

**Goal**: Carry document-level unsupervised evidence/context through family contribution, overlay, review band, inference, and pipeline contracts.

**Files**:
- `src/services/phase2_case_family_aggregator.py`
- `src/services/phase2_case_contract.py`
- `src/services/phase2_inference_service.py`
- `src/pipeline.py` if the result contract or attachment comments need updating
- tests under `tests/modules/test_services/`

**Tasks**:
- Add tests for document-level unsupervised contribution payloads.
- Attach top feature, reason tag, amount-tail, period-end proximity, account/process rarity, and repeated-normal pressure as display context.
- Keep explanation features out of scoring.
- Keep companion readiness lock values unchanged unless the existing lock itself conflicts with the approved redesign.
- Confirm primary queue, PHASE1 ranking, and phase2 fusion regression guards stay green.

**Verification**:
- Focused aggregator/contract tests.
- `uv run pytest tests/modules/test_services/test_unsupervised_companion_readiness.py -q`
- `uv run ruff check src/services/phase2_case_family_aggregator.py src/services/phase2_case_contract.py src/services/phase2_inference_service.py src/pipeline.py`

### P4: Dashboard Document Review List

**Goal**: Replace row-like VAE table with a single document-level VAE review list.

**Files**:
- `dashboard/components/phase2_native_case_panel.py`
- `dashboard/components/phase2_native_case_metrics.py`
- `dashboard/tab_phase2.py` or `dashboard/tab_review_queue.py` if the surrounding view needs copy or layout changes

**Tasks**:
- Render one row per document review case.
- Show reason tag, top feature, amount-tail, period-end proximity, account/process rarity, and evidence-row count.
- Keep language to statistical outlier / anomaly pattern / context only.
- Keep KPI usage aligned with Streamlit metric semantics: `value` for the number, `delta` only for time or true change.
- Do not stop, restart, or clear Streamlit automatically.

**Verification**:
- Import smoke, for example `uv run python -c "import dashboard.components.phase2_native_case_panel; import dashboard.components.phase2_native_case_metrics; import dashboard.tab_phase2"`
- Focused dashboard tests if affected tests already exist.

### P5: Review Usefulness Diagnostic Harness

**Goal**: Measure document-level review usefulness without making fraud recall a product success criterion.

**Files**:
- `tools/scripts/diagnose_unsupervised_document_review_surface.py`
- `artifacts/unsupervised_document_review_surface_<date-or-run-id>.json`
- `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`

**Tasks**:
- Follow the existing `diagnose_unsupervised_*_owner_surface_fixed5` pattern.
- Report new document additions outside PHASE1 immediate/review/candidate tiers for TOP100/500/1000/10000.
- Report repeated-normal pressure, account/process concentration, amount-tail ratio, period-end ratio, top feature coverage, and reason tag coverage.
- Include fraud recall only as diagnostic context.
- Store guard flags proving forbidden selector/order inputs were not used.
- Append each run result without overwriting history.

**Verification**:
- Run the diagnostic script on the agreed fixture/data path.
- Validate generated JSON shape.
- Compare actual values to decision document §4 baselines without tuning to targets.

### P6: Documentation and Final Verification

**Goal**: Update active docs and verify the redesign end to end.

**Files**:
- `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`
- `docs/spec/PHASE2_GOVERNANCE_DESIGN.md`
- `docs/spec/PHASE2_INTERFACE_DESIGN.md`
- `CLAUDE.md`
- `docs/guide/PROJECT_OVERVIEW.md`
- `docs/debugging.md` if troubleshooting occurred

**Tasks**:
- Mark the redesign decision as confirmed/implemented after P5 actuals are known.
- Update row-to-document unsupervised family descriptions.
- Register the decision document in active indexes.
- Record meaningful troubleshooting only if there was a real failure/fix.
- Run final related pytest suites and ruff.

**Verification**:
- Related service, detection, dashboard unsupervised tests.
- Companion readiness lock.
- Primary queue, PHASE1 ranking, and phase2 fusion regression guards.
- `uv run ruff check .`

## Dependencies

P0 approval is required before code. P1, P2, and P3 are sequential because model shape, builder output, and downstream contract wiring depend on each other. P4 and P5 can run in parallel after P3 because dashboard rendering and diagnostic measurement consume the same document-case contract.

```text
P0 -> approval -> P1 -> P2 -> P3 -> P4
                                      -> P5
                                  -> P6
```

## Risk Assessment

- **High Risk**: Treating the new document-case surface as fraud detection.
  - Mitigation: keep companion role locks, UI copy restrictions, and diagnostic-only fraud recall language.
- **High Risk**: Accidentally using PHASE1 rank, owner, scenario, truth, or matched output to improve ordering.
  - Mitigation: builder tests and P5 guard flags must name each forbidden input explicitly.
- **Medium Risk**: Changing case identity by including score, ECDF, or threshold in `evidence_signature`.
  - Mitigation: RED test for identity stability across score changes.
- **Medium Risk**: Existing downstream code expects `unit_type="row"` or one row ref per unsupervised case.
  - Mitigation: P1/P2 ripple tests around `Phase2CaseSet`, linker, dashboard panel, metrics, export status, and companion readiness.
- **Medium Risk**: Dashboard displays score as a conclusion rather than as context.
  - Mitigation: P4 copy and column review against `docs/guide/ux-flow.md`.

## Success Metrics

- Same-document anomalous rows produce exactly one unsupervised document review case.
- q95 gate and zero-preserving ECDF tests pass unchanged.
- Companion readiness keeps `fraud_primary_recall_family=False` and `product_role="broad_statistical_review_companion_evidence_surface"`.
- Review usefulness harness reports S1-S5 from the decision document using observed values.
- Dashboard shows document-level evidence/context without confirmed-fraud wording.
