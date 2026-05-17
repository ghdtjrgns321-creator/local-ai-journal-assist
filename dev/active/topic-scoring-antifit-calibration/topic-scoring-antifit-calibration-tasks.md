# Topic Scoring Antifit Calibration - Task Checklist

## Progress Summary
20 / 20 tasks complete (100%)

## Phase 1: Contract Tests
- [x] Add anti-fitting test for `L3-02 + L3-04 + L3-12`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Build evidences with the three rules and call `compute_topic_scores(..., return_breakdown=True)` plus `compute_fraud_scenario_tags()`.
  - Acceptance: No `fictitious_entry_risk`, no `period_end_adjustment_risk`, and no fraud combo floor reason for those two topics.
  - Size: S
- [x] Add circular anti-fitting test for `L3-03 + L3-05 + L3-02`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Assert no `circular_transaction_high` behavior and no score `0.75` floor for `intercompany_cycle`.
  - Acceptance: `intercompany_cycle.score < 0.75`.
  - Size: S
- [x] Add circular anti-fitting test for `L3-03 + L3-05 + L3-12`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Same as previous task but using `L3-12`.
  - Acceptance: `intercompany_cycle.score < 0.75`.
  - Size: S
- [x] Add embezzlement anti-fitting test for `L1-05 + L3-02 + L3-12`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Use `L1-05` as approval bypass evidence and assert duplicate/outflow is not fraud-floored.
  - Acceptance: `embezzlement_concealment_risk` is absent from duplicate/outflow breakdown and fraud tags.
  - Size: S
- [x] Add approval Medium test for `L1-07 + L3-02`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Assert `approval_control` gets Medium floor but not High.
  - Acceptance: score is at least `0.60` and below `0.75`; reason reflects approval plus manual context.
  - Size: S
- [x] Add approval Medium test for `L1-07 + L3-05`.
  - File: `tests/modules/test_detection/test_rule_scoring.py`
  - Details: Assert weekend/holiday with approval bypass is Medium unless abnormal-time or other stronger condition is present.
  - Acceptance: score is at least `0.60` and below `0.75`.
  - Size: S

## Phase 2: Logic Changes
- [x] Remove direct `has_manual_scope_closing` revenue floor.
  - File: `src/detection/topic_scoring.py`
  - Details: Delete the `elif has_manual_scope_closing` branch under `revenue_statistical`.
  - Acceptance: The Phase 1 anti-fitting test for fictitious entry passes.
  - Size: S
- [x] Remove direct `has_manual_scope_closing` closing floor.
  - File: `src/detection/topic_scoring.py`
  - Details: Delete the `elif has_manual_scope_closing` branch under `closing_timing`.
  - Acceptance: The Phase 1 anti-fitting test for period-end adjustment passes.
  - Size: S
- [x] Tighten fictitious entry Medium criteria if needed.
  - File: `src/detection/topic_scoring.py`
  - Details: Ensure Medium requires revenue/amount or rare/duplicate/account-substance support.
  - Acceptance: Existing strong fictitious tests pass; weak manual/scope/closing tests fail to floor.
  - Size: M
- [x] Tighten period-end Medium criteria if needed.
  - File: `src/detection/topic_scoring.py`
  - Details: Ensure Medium requires weak description, sensitive account, high amount, cutoff, or rare account support beyond manual closing.
  - Acceptance: `L3-04 + L3-02 + L3-08` remains Medium; `L3-04 + L3-02 + L3-12` does not floor.
  - Size: M
- [x] Remove duplicate/outflow floor for `approval_bypass + L3-02 + L3-12`.
  - File: `src/detection/topic_scoring.py`
  - Details: Delete that branch or move its effect to approval-control Medium only.
  - Acceptance: The embezzlement anti-fitting test passes.
  - Size: S
- [x] Remove weak circular High branch.
  - File: `src/detection/topic_scoring.py`
  - Details: Delete `L3-03 + L3-05 + (L3-02 or L3-12)` as `circular_transaction_high`.
  - Acceptance: Circular anti-fitting tests pass; repeat/cycle High test still passes.
  - Size: S
- [x] Split approval High and Medium branches.
  - File: `src/detection/topic_scoring.py`
  - Details: Make High require `L4-03`, `L3-11`, `L3-04 + L3-02`, or `L3-06 + L3-02`; add Medium for `approval_bypass + L3-02` and `approval_bypass + L3-05`.
  - Acceptance: New approval tests pass and prior strong approval tests are updated to the stricter standard.
  - Size: M

## Phase 3: Documentation
- [x] Rewrite datasynth calibration note in topic scoring lock.
  - File: `docs/PHASE1_TOPIC_SCORING_V1_LOCK.md`
  - Details: Replace weak-combo floor allowance with anti-fitting policy and badge/tie-break wording.
  - Acceptance: No sentence says weak datasynth truth combinations are allowed as Medium or High floors.
  - Size: M
- [x] Rewrite datasynth calibration note in relationship map.
  - File: `docs/PHASE1_RULE_RELATIONSHIP_MAP.md`
  - Details: Remove `L3-02 + L3-04 + L3-12` and `L3-03 + L3-05 + (L3-02 or L3-12)` floor allowances.
  - Acceptance: The document states `L3-12` is booster/context only.
  - Size: M
- [x] Update manipulation results after rerun.
  - File: `docs/DETECTION_RESULTS_MANIPULATION.md`
  - Details: Added the 2026-05-17 D1 anti-fitting profile section with post-change case counts and informational truth metrics.
  - Acceptance: Report distinguishes FSS/ISA/PCAOB floor policy from datasynth truth recall; truth recall is not used as justification.
  - Size: M

## Phase 4: Verification
- [x] Run focused rule scoring tests.
  - Command: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_rule_scoring.py -q`
  - Acceptance: Exit code 0.
  - Size: S
- [x] Run focused phase1 case builder tests.
  - Command: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_phase1_case_builder.py -q`
  - Acceptance: Exit code 0.
  - Size: S
- [x] Run full detection test module.
  - Command: `uv run pytest tests/modules/test_detection -q`
  - Acceptance: Exit code 0 (`1099 passed, 3 skipped`).
  - Size: M
- [x] Rerun manipulation topic profile.
  - Command: `uv run python tools/scripts/profile_phase1_v126.py --data-dir data/journal/primary/datasynth_manipulation_v2 --checkpoint artifacts/phase1_manipulation_v2_topic_antifit_profile_20260517.json --cache-path artifacts/phase1_manipulation_v2_topic_antifit_case_input_20260517.pkl`
  - Acceptance: New artifact exists; report records case distribution and truth metrics as informational only.
  - Size: M
