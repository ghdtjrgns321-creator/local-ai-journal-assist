# PHASE2 Unsupervised Document Review Surface - Task Checklist

## Progress Summary

35 / 49 tasks complete. P3 complete; P4 and P5 can proceed in parallel.

## P0: Planning and Design Approval

- [x] Read `CLAUDE.md`.
  - Acceptance: project roadmap, document index, and phase guidance are reflected in `plan.md`.
  - Size: S

- [x] Read `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`.
  - Acceptance: row-case to document-case redesign, companion framing, and anti-fitting guards are reflected in `plan.md`.
  - Size: S

- [x] Inspect current source and lock tests named by the user.
  - Acceptance: `context.md` lists the inspected files and current invariants.
  - Size: S

- [x] Receive approval for data model, score aggregation, feature merge, evidence row display, and ordering compatibility.
  - File: `dev/active/phase2-unsupervised-doc-review-surface/context.md`
  - Acceptance: user selects options A/B/C/D/E/F before P1 starts.
  - Size: S

## P1: Document-Case Data Model

- [x] Read `docs/spec/GIT.md` and confirm the working branch is a feature branch based on `develop`.
  - File: `docs/spec/GIT.md`
  - Acceptance: branch status is reported before edits. `git` command was blocked by user hook; `.git/HEAD` shows `refs/heads/develop`, matching the repo's direct-develop workflow.
  - Size: S

- [x] Read the approved P0 plan and decision document.
  - Files: `plan.md`, `context.md`, `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`
  - Acceptance: implementation follows the approved options.
  - Size: S

- [x] Write RED model test for document-case unit type and multiple evidence row refs.
  - File: `tests/modules/test_models/test_phase2_unsupervised_document_case.py`
  - Acceptance: test fails before model implementation.
  - Size: S

- [x] Write RED model test for frozen dataclass immutability and tuple freezing.
  - File: `tests/modules/test_models/test_phase2_unsupervised_document_case.py`
  - Acceptance: mutable list-style evidence cannot satisfy the expected contract.
  - Size: S

- [x] Write RED model test for document context fields.
  - File: `tests/modules/test_models/test_phase2_unsupervised_document_case.py`
  - Acceptance: amount-tail, period-end, account/process rarity, repeated-normal pressure, and evidence count are asserted.
  - Size: S

- [x] Implement the approved document-case model shape.
  - File: `src/models/phase2_case.py`
  - Acceptance: model tests pass without score/threshold builder logic.
  - Size: M

- [x] Run focused P1 tests.
  - Command: `uv run pytest tests/modules/test_models/test_phase2_unsupervised_document_case.py -q`
  - Acceptance: tests pass and output is reported.
  - Size: S

- [x] Run P1 ruff check.
  - Command: `uv run ruff check src/models/phase2_case.py tests/modules/test_models/test_phase2_unsupervised_document_case.py`
  - Acceptance: ruff passes or any failure is fixed in scope.
  - Size: S

## P2: Case Builder Row-to-Document Aggregation

- [x] Confirm branch and reread approved P0/P1 outputs.
  - Files: `docs/spec/GIT.md`, `plan.md`, `context.md`, `src/models/phase2_case.py`
  - Acceptance: branch and approved choices are stated before edits.
  - Size: S

- [x] Read imbalanced-ml ECDF guidance.
  - File: `C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.agents/skills/imbalanced-ml/SKILL.md`
  - Acceptance: zero-preserving ECDF guard is considered before tests.
  - Size: S

- [x] Write RED builder test for same-document multi-row grouping.
  - File: `tests/modules/test_services/test_phase2_unsupervised_case_builder.py`
  - Acceptance: two gated rows with the same `document_id` are expected to produce one case.
  - Size: S

- [x] Write RED builder test for gate-miss exclusion before grouping.
  - File: `tests/modules/test_services/test_phase2_unsupervised_case_builder.py`
  - Acceptance: below-q95 rows do not appear in evidence rows.
  - Size: S

- [x] Write RED builder test for graceful empty output.
  - File: `tests/modules/test_services/test_phase2_unsupervised_case_builder.py`
  - Acceptance: missing/empty scores or details return `()`.
  - Size: S

- [x] Write RED builder test for evidence signature identity stability.
  - File: `tests/modules/test_services/test_phase2_unsupervised_case_builder.py`
  - Acceptance: score/threshold changes do not enter `evidence_signature` or case identity.
  - Size: S

- [x] Implement document grouping in the builder.
  - File: `src/services/phase2_unsupervised_case_builder.py`
  - Acceptance: one case per document with gated evidence rows only.
  - Size: M

- [x] Implement approved missing `document_id` fallback or exclusion behavior.
  - File: `src/services/phase2_unsupervised_case_builder.py`
  - Acceptance: gated rows without document identifiers follow the approved F option and expose explicit metadata when fallback is used.
  - Size: S

- [x] Implement approved document score aggregation.
  - File: `src/services/phase2_unsupervised_case_builder.py`
  - Acceptance: tests prove VAE score and q95 gate are not changed.
  - Size: M

- [x] Implement document-level top feature and reason tag policy.
  - File: `src/services/phase2_unsupervised_case_builder.py`
  - Acceptance: top features and tags attach at document case level.
  - Size: M

- [x] Implement approved ordering compatibility behavior.
  - File: `src/services/phase2_unsupervised_case_builder.py`
  - Acceptance: tests cover the approved native/diagnostic/default ordering semantics.
  - Size: S

- [x] Run focused P2 tests.
  - Command: `uv run pytest tests/modules/test_services/test_phase2_unsupervised_case_builder.py -q`
  - Acceptance: tests pass and output is reported.
  - Size: S

- [x] Run P2 ruff check.
  - Command: `uv run ruff check src/services/phase2_unsupervised_case_builder.py tests/modules/test_services/test_phase2_unsupervised_case_builder.py`
  - Acceptance: ruff passes or any failure is fixed in scope.
  - Size: S

- [x] Run Korean code-reviewer agent review.
  - Scope: P2 builder and tests
  - Acceptance: findings are addressed or explicitly deferred with rationale.
  - Size: S

## P3: Aggregator and Contract Wiring

- [x] Confirm branch and reread P2 output.
  - Files: `docs/spec/GIT.md`, `src/services/phase2_unsupervised_case_builder.py`, `src/models/phase2_case.py`
  - Acceptance: branch and builder contract are stated before edits.
  - Size: S

- [x] Read local audit review checklist.
  - File: `C:/Users/ghdtj/workspace/portfolio/local-ai-assist/.agents/skills/local-ai-assist-review/SKILL.md`
  - Acceptance: PHASE1 ranking, review-only language, and evidence grounding risks are checked.
  - Size: S

- [x] Write RED aggregator test for document-level context payload.
  - File: service test under `tests/modules/test_services/`
  - Acceptance: top feature, reason tag, amount-tail, period-end, rarity, and pressure context are expected.
  - Size: S

- [x] Write RED contract test proving explanation features are not score inputs.
  - File: service test under `tests/modules/test_services/`
  - Acceptance: changing explanation features does not change family scores or review band inputs.
  - Size: S

- [x] Wire document context into aggregator output.
  - File: `src/services/phase2_case_family_aggregator.py`
  - Acceptance: document-level unsupervised context is available to overlay builders.
  - Size: M

- [x] Wire document context into family contribution payload.
  - File: `src/services/phase2_case_contract.py`
  - Acceptance: contribution entries include display context without scoring side effects.
  - Size: M

- [x] Update inference/pipeline attachment comments or fields only where the contract requires it.
  - Files: `src/services/phase2_inference_service.py`, `src/pipeline.py`
  - Acceptance: post-inference PHASE1 overlay contract remains explicit.
  - Size: S

- [x] Run companion readiness regression.
  - Command: `uv run pytest tests/modules/test_services/test_unsupervised_companion_readiness.py -q`
  - Acceptance: product role and anti-fitting locks pass, or a lock conflict is reported for user decision before changing expectations.
  - Size: S

- [x] Run focused P3 pytest.
  - Command: focused service tests selected during implementation
  - Acceptance: all touched service tests pass.
  - Size: S

- [x] Run P3 ruff check.
  - Command: `uv run ruff check src/services/phase2_case_family_aggregator.py src/services/phase2_case_contract.py src/services/phase2_inference_service.py src/pipeline.py`
  - Acceptance: ruff passes or any failure is fixed in scope.
  - Size: S

## P4: Dashboard Document Review List

- [ ] Confirm branch and reread P3 contract.
  - Files: `docs/spec/GIT.md`, `src/services/phase2_case_contract.py`, `dashboard/components/phase2_native_case_panel.py`
  - Acceptance: dashboard edits follow the document-case payload.
  - Size: S

- [ ] Read Streamlit guidance skill relevant to dashboard layout and metrics.
  - Files: Streamlit dashboard/layout/metric skills as needed
  - Acceptance: KPI and layout decisions follow Streamlit guidance.
  - Size: S

- [ ] Update unsupervised master table to one row per document review case.
  - File: `dashboard/components/phase2_native_case_panel.py`
  - Acceptance: visible columns include document id, evidence row count, reason tag, top feature, and context fields.
  - Size: M

- [ ] Update unsupervised detail view to show approved evidence row policy.
  - File: `dashboard/components/phase2_native_case_panel.py`
  - Acceptance: detail view exposes row evidence without claiming fraud/violation/error.
  - Size: M

- [ ] Update native case metrics if document-case counts change KPI meaning.
  - File: `dashboard/components/phase2_native_case_metrics.py`
  - Acceptance: counts describe document review cases, not row anomalies.
  - Size: S

- [ ] Update surrounding Phase 2 tab copy if needed.
  - File: `dashboard/tab_phase2.py` or `dashboard/tab_review_queue.py`
  - Acceptance: UI wording says statistical outlier/anomaly/context only.
  - Size: S

- [ ] Run dashboard import smoke.
  - Command: `uv run python -c "import dashboard.components.phase2_native_case_panel; import dashboard.components.phase2_native_case_metrics; import dashboard.tab_phase2"`
  - Acceptance: import completes without starting Streamlit.
  - Size: S

## P5: Review Usefulness Diagnostic Harness

- [ ] Confirm branch and read decision document §4.
  - Files: `docs/spec/GIT.md`, `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`
  - Acceptance: S1-S5 are mapped to script outputs.
  - Size: S

- [ ] Inspect existing diagnostic script patterns.
  - Files: `tools/scripts/diagnose_unsupervised_*`
  - Acceptance: new script naming, artifact shape, and accumulation pattern follow existing practice.
  - Size: S

- [ ] Implement document review usefulness diagnostic script.
  - File: `tools/scripts/diagnose_unsupervised_document_review_surface.py`
  - Acceptance: script emits TOP100/500/1000/10000 usefulness metrics.
  - Size: L

- [ ] Include anti-fitting guard flags in result JSON.
  - File: `tools/scripts/diagnose_unsupervised_document_review_surface.py`
  - Acceptance: truth/owner/scenario/PHASE1 rank selector flags and q95/score/DataSynth flags are explicit.
  - Size: S

- [ ] Run diagnostic and save artifact.
  - File: `artifacts/unsupervised_document_review_surface_<run-id>.json`
  - Acceptance: artifact is written with observed values and no target fitting.
  - Size: S

- [ ] Compare actuals against decision document §4 baselines.
  - File: `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`
  - Acceptance: comparison is factual and marks fraud recall as diagnostic only.
  - Size: S

## P6: Documentation and Final Verification

- [ ] Read documentation-architect guidance before doc updates.
  - File: `C:/Users/ghdtj/.agents/skills/claude-agent-documentation-architect/SKILL.md`
  - Acceptance: doc updates are structured and avoid duplicate long explanations.
  - Size: S

- [ ] Update redesign decision status and P5 actuals.
  - File: `docs/spec/PHASE2_UNSUPERVISED_ROLE_REDESIGN_DECISION.md`
  - Acceptance: status moves from draft to confirmed/implemented only after P5 actuals.
  - Size: M

- [ ] Update governance and interface docs from row to document semantics.
  - Files: `docs/spec/PHASE2_GOVERNANCE_DESIGN.md`, `docs/spec/PHASE2_INTERFACE_DESIGN.md`
  - Acceptance: unsupervised family unit is documented as document-level review surface.
  - Size: M

- [ ] Register the active decision document in project indexes.
  - Files: `CLAUDE.md`, `docs/guide/PROJECT_OVERVIEW.md`
  - Acceptance: active document index includes the redesign decision.
  - Size: S

- [ ] Record troubleshooting if real failures occurred.
  - File: `docs/debugging.md`
  - Acceptance: only meaningful failures/fixes are recorded.
  - Size: S

- [ ] Read verification-before-completion and local testing skills.
  - Files: verification and `local-ai-assist-testing` skill docs
  - Acceptance: final test scope follows project guidance.
  - Size: S

- [ ] Run related service/detection/dashboard unsupervised tests.
  - Command: selected focused pytest commands
  - Acceptance: tests pass and output is reported.
  - Size: M

- [ ] Run companion and primary/fusion regression guards.
  - Command: selected regression pytest commands
  - Acceptance: primary queue, PHASE1 ranking, and phase2 fusion guards pass.
  - Size: M

- [ ] Run final ruff.
  - Command: `uv run ruff check .`
  - Acceptance: ruff passes or in-scope failures are fixed.
  - Size: M
