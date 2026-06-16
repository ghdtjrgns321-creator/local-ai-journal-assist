# Topic Scoring Antifit Calibration - Strategic Plan

## Executive Summary
PHASE1 topic scoring currently contains several combo floors that were added after profiling `datasynth_manipulation` v134. The risky part is not the presence of datasynth verification, but that weak datasynth-shaped rule sets are allowed to create Medium or High fraud floors without strong audit evidence.

This plan removes or weakens the weak auxiliary floors, keeps FSS/ISA/PCAOB-supported floors intact, and changes verification so datasynth truth recall is a secondary regression metric rather than the optimization target.

## Current State
The main implementation is in `src/detection/topic_scoring.py`, especially `_fraud_combo_floor_results()`. Configured floor values live in `config/phase1_case.yaml`, and contract tests currently assert several combo-floor outcomes in `tests/modules/test_detection/test_rule_scoring.py` and `tests/modules/test_detection/test_phase1_case_builder.py`.

The highest-risk fitting conditions are:
- `L3-02 + L3-04 + L3-12` creates `fictitious_entry_medium`.
- `L3-02 + L3-04 + L3-12` creates `period_end_adjustment_medium`.
- `approval_bypass + L3-02 + L3-12` creates `embezzlement_concealment_medium`.
- `L3-03 + L3-05 + (L3-02 or L3-12)` creates `circular_transaction_high`.
- `approval_bypass + any(L4-03, L3-02, L3-05, L3-06)` creates `approval_bypass_high`, so `approval_bypass + L3-02` is too easily High.

The matching documentation in `docs/spec/PHASE1_TOPIC_SCORING_V1_LOCK.md` and `docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md` explicitly frames these as datasynth calibration allowances. That wording should be revised to an anti-fitting policy.

## Proposed Solution
Keep combo floors only when the rule set has strong primary evidence:
- Revenue or amount outlier, rare or duplicate pattern, sensitive account, weak description, cutoff mismatch, outflow or duplicate, related-party repeat or cycle, or explicit intercompany exception.
- Treat `L3-12` as context or booster only. It must not create a fraud floor together with broad manual, closing, weekend, or approval conditions.
- Split High, Medium, and badge/context behavior. High floors should require literature-backed manipulation patterns. Medium floors should require at least one strong primary signal beyond `L3-12`. Badge/context tags can preserve UI visibility without inflating topic rank.

## Implementation Phases

### Phase 1: Contract Tests First
**Goal**: Lock anti-fitting behavior before changing scoring.
**Tasks**:
- [ ] Add tests in `tests/modules/test_detection/test_rule_scoring.py` for `L3-02 + L3-04 + L3-12`.
  - Acceptance: No `fictitious_entry_risk` or `period_end_adjustment_risk` combo floor is emitted for that rule set alone.
  - Size: S
- [ ] Add tests in `tests/modules/test_detection/test_rule_scoring.py` for `L3-03 + L3-05 + L3-02` and `L3-03 + L3-05 + L3-12`.
  - Acceptance: Neither rule set receives `circular_transaction_high`; if retained, it is Medium at most and clearly not High.
  - Size: S
- [ ] Add tests in `tests/modules/test_detection/test_rule_scoring.py` for `L1-05 + L3-02 + L3-12`.
  - Acceptance: `duplicate_outflow` does not receive `embezzlement_concealment_risk` from this set alone; `approval_control` can keep a Medium/control-context result.
  - Size: S
- [ ] Add tests in `tests/modules/test_detection/test_rule_scoring.py` for `approval_bypass + L3-02` and `approval_bypass + L3-05`.
  - Acceptance: `approval_control` is Medium, not High, unless high amount, cutoff, abnormal time, or manual-plus-closing evidence is also present.
  - Size: S
- [ ] Keep positive tests for strong floors in `tests/modules/test_detection/test_rule_scoring.py`.
  - Acceptance: Existing strong examples for fictitious entry, period-end adjustment, embezzlement concealment, and circular repeat/cycle still pass.
  - Size: S

### Phase 2: Scoring Logic Tightening
**Goal**: Remove datasynth-shaped floors and narrow broad High paths.
**Tasks**:
- [ ] Edit `src/detection/topic_scoring.py` to remove `has_manual_scope_closing` as a direct floor trigger.
  - Acceptance: `has_manual_scope_closing` is either deleted or used only as a local context boolean that never calls `add()` by itself.
  - Size: S
- [ ] Tighten `revenue_statistical` medium floors.
  - Acceptance: `fictitious_entry_medium` requires revenue or amount evidence, rare/duplicate evidence, or other account-substance evidence; `L3-12` does not satisfy this requirement.
  - Size: M
- [ ] Tighten `closing_timing` medium floors.
  - Acceptance: `period_end_adjustment_medium` requires `L3-08`, `L4-03`, `L3-10`, `L4-04`, or `L3-11`; `L3-04 + L3-02 + L3-12` alone does not floor.
  - Size: M
- [ ] Remove `approval_bypass + L3-02 + L3-12` from `duplicate_outflow`.
  - Acceptance: embezzlement concealment floors require outflow/duplicate/reversal evidence plus approval/SOD bypass.
  - Size: S
- [ ] Tighten `intercompany_cycle` High.
  - Acceptance: `circular_transaction_high` requires related-party or IC evidence plus repeat/cycle context and amount/timing/mismatch support; weekend plus manual or scope is not High.
  - Size: M
- [ ] Split approval bypass High and Medium.
  - Acceptance: High requires approval bypass plus `L4-03`, `L3-11`, `L3-04 + L3-02`, or `L3-06 + L3-02`; `approval_bypass + L3-02` and `approval_bypass + L3-05` map to Medium.
  - Size: M

### Phase 3: Documentation and Policy Lock
**Goal**: Replace datasynth calibration wording with FSS/ISA/PCAOB anti-fitting policy.
**Tasks**:
- [ ] Update `docs/spec/PHASE1_TOPIC_SCORING_V1_LOCK.md`.
  - Acceptance: The `datasynth_manipulation` weak-combo allowance table is removed or rewritten as “badge/tie-break only, no floor”; High/Medium criteria match code.
  - Size: M
- [ ] Update `docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md`.
  - Acceptance: The “truth 문서가 약하게 생성되어 보조 조합 허용” statement is removed; `L3-12` is documented as context/booster.
  - Size: M
- [ ] Update `docs/archive/completed/DETECTION_RESULTS_MANIPULATION.md` after rerun.
  - Acceptance: The report explains expected drops in datasynth Top100/High recall and adds anti-fitting metrics.
  - Size: M

### Phase 4: Verification
**Goal**: Prove the change reduces weak-floor inflation without breaking strong audit patterns.
**Tasks**:
- [ ] Run focused tests: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_rule_scoring.py -q`.
  - Acceptance: All topic scoring contract tests pass.
  - Size: S
- [ ] Run case-builder focused tests: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_phase1_case_builder.py -q`.
  - Acceptance: Case-level fraud tags and topic breakdowns are consistent with the tightened rules.
  - Size: S
- [ ] Run detection module tests: `.venv\Scripts\pytest.exe tests\modules\test_detection -q`.
  - Acceptance: No regressions outside topic scoring.
  - Size: M
- [ ] Rerun manipulation profile using the same command documented in `docs/archive/completed/DETECTION_RESULTS_MANIPULATION.md`.
  - Acceptance: `fictitious_entry_risk` and `period_end_adjustment_risk` case counts decrease materially; strong-floor hit counts remain explainable.
  - Size: M

## Risk Assessment
- **High Risk**: Datasynth truth recall and Top100 counts can drop. Mitigation: Treat that drop as acceptable unless strong FSS/ISA/PCAOB floor hits disappear unexpectedly.
- **Medium Risk**: UI badges may lose visibility if all weak fraud tags are removed. Mitigation: Preserve weak combinations as `approval_control` or context-only breakdown evidence where the current model supports it, without score floors.
- **Medium Risk**: Existing tests may encode datasynth-fit behavior. Mitigation: Replace those assertions with anti-fitting contracts rather than only changing expected scores.

## Success Metrics
- `L3-02 + L3-04 + L3-12` alone creates no Medium fraud floor.
- `L3-03 + L3-05 + (L3-02 or L3-12)` creates no High circular floor.
- `approval_bypass + L3-02 + L3-12` creates no duplicate/outflow embezzlement floor.
- `approval_bypass + L3-02` and `approval_bypass + L3-05` are Medium, not High.
- Strong floors remain intact:
  - `(L4-01 or L4-03) + L3-02 + (L4-04 or L2-03)` -> fictitious entry High.
  - `(L3-04 or L3-07 or L3-11 or L1-08) + L4-03 + (L3-08 or L3-10 or L4-04)` -> period-end adjustment High.
  - `(L2-02 or L2-03 or L2-05) + (L1-05 or L1-06 or L1-07 or L1-04)` -> embezzlement concealment High.
  - related-party or IC + amount/timing + repeat/cycle -> circular transaction High.

## Dependencies
- Code: `src/detection/topic_scoring.py`, `config/phase1_case.yaml` if any policy floor values need renaming or lowering.
- Tests: `tests/modules/test_detection/test_rule_scoring.py`, `tests/modules/test_detection/test_phase1_case_builder.py`.
- Docs: `docs/spec/PHASE1_TOPIC_SCORING_V1_LOCK.md`, `docs/spec/PHASE1_RULE_RELATIONSHIP_MAP.md`, `docs/archive/completed/DETECTION_RESULTS_MANIPULATION.md`.
