# Phase2 UI Resiliency Plan

## Operating Rule

No further patching until the UI action matrix, state matrix, persistence matrix, failure classification, and verification scenarios are written. Fixes should be small and tied to one failure branch.

## Phase A: Trace UI Actions

- [x] Map every visible Phase2 button, selector, tab, and status message to its handler.
- [x] Include Phase1 rerun, mapping finalize, upload-again, saved batch load, autoload, and return-to-start actions.
- [x] Record each action's expected preconditions and invalidation policy.

Output: UI action matrix in `phase2-ui-resiliency-tasks.md`.

## Phase B: Trace State Mutation

- [x] Track writes, reads, and invalidation for all core keys.
- [x] Separate in-memory full results from metadata-only restored results.
- [x] Identify stale-state risks after Phase1 rerun, prep change, retrain, and company switch.

Output: session-state matrix.

## Phase C: Trace Persistence Contracts

- [x] Trace DB save/read contract for batch, ledger, anomaly flags, and batch metadata.
- [x] Trace Phase1 case artifact lifecycle and lazy-load behavior.
- [x] Trace Phase2 training report, leaderboard, promotion decision, and overlay JSON lifecycle.
- [x] Trace static/reference artifact use for analysis-area cards.

Output: persistence matrix.

## Phase D: Classify Failure Branches

- [x] Derive failure branches from phases A-C.
- [x] Assign each branch a user-facing message, diagnostic detail, and next action.
- [x] Decide which branches are graceful degradation and which block display.

Output: failure/message matrix.

## Phase E: Verification Matrix

Critical scenarios:

- [x] Fresh Phase1 -> Phase2 inference -> immediate UI display.
- [x] Fresh Phase1 -> Phase2 inference -> refresh/reload -> UI display.
- [x] Saved batch load -> persisted overlay attach.
- [x] Phase1 metadata-only -> Phase2 inference.
- [x] Phase1 artifact missing -> Phase2 fallback overlay.
- [x] DB load failure -> session result and overlay remain visible.
- [x] Same batch inferred twice -> overlay overwrite is safe.
- [x] Company A batch -> Company B switch -> overlay isolation.
- [x] Retrain after old overlay -> invalidate or keep policy is explicit.
- [x] Prep result / upload change -> Phase1 and Phase2 reset consistently.

Output: test matrix and minimal pytest/browser targets.

## Phase F: Patch By Branch

- [ ] One failure branch per patch.
- [ ] Each patch must add or update a regression test.
- [ ] Dashboard message changes must include a focused dashboard test or import smoke.
- [ ] DB/file contract changes must include loader/batch-service tests.

## Initial Decision Points

- Stale overlay after retraining: default policy should reject/flag if `phase2_training_report_id` differs, unless user explicitly chooses to view historical overlay.
- Partition 0-row fallback: UI must show "selected year had no rows; full dataset used."
- Canonical Phase1 unavailable: use redetect fallback only with an explicit diagnostic label, not silently.
- Old batches without overlay: show "older batch; rerun Phase2 to create overlay" with a rerun action.
