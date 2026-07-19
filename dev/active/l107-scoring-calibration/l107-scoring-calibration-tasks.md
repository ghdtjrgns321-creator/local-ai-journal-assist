# L1-07 Scoring Calibration - Task Checklist

## Progress Summary
0 / 14 tasks complete (0%)

## Phase 1: Rule-Local Score Contract
- [ ] Add `_l107_component_scores()` helper.
  - File: `src/detection/fraud_rules_access.py`
  - Acceptance: helper returns bounded component series for every input row.
  - Size: M

- [ ] Add component values to L1-07 row annotations.
  - File: `src/detection/fraud_rules_access.py`
  - Acceptance: each L1-07 candidate annotation includes `score_components` and `score_reason_summary`.
  - Size: S

- [ ] Add low/review/high/critical L1-07 fixtures.
  - File: `tests/modules/test_detection/test_fraud_rules_access.py`
  - Acceptance: four fixtures produce ordered scores.
  - Size: M

## Phase 2: Replace Fixed Rule Score
- [ ] Replace fixed immediate score with component-based score.
  - File: `src/detection/fraud_rules_access.py`
  - Acceptance: immediate L1-07 rows can score across `0.70-1.00`.
  - Size: S

- [ ] Replace fixed review score with capped component score.
  - File: `src/detection/fraud_rules_access.py`
  - Acceptance: review rows stay below confirmed threshold unless immediate criteria are met.
  - Size: S

- [ ] Update fraud layer exact-score tests.
  - File: `tests/modules/test_detection/test_fraud_layer.py`
  - Acceptance: tests assert bands and ordering rather than fixed `[0.8, 0.4]`.
  - Size: S

## Phase 3: Case Priority Calibration
- [ ] Make L1-07 priority floors score-sensitive.
  - File: `config/phase1_case.yaml`
  - Acceptance: critical L1-07 can floor to high, but ordinary immediate cases do not all become the same priority.
  - Size: S

- [ ] Update `_apply_priority_floors()` if tiered floor syntax is needed.
  - File: `src/detection/phase1_case_builder.py`
  - Acceptance: floor config can match `rule_id`, label, and raw score range.
  - Size: M

- [ ] Add case builder ordering tests.
  - File: `tests/modules/test_detection/test_phase1_case_builder.py`
  - Acceptance: material repeated approval omission ranks above a routine missing approver case.
  - Size: M

## Phase 4: Verification
- [ ] Run focused L1-07 tests.
  - Command: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_fraud_rules_access.py -q`
  - Acceptance: all L1-07 tests pass.
  - Size: S

- [ ] Run fraud layer tests.
  - Command: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_fraud_layer.py -q`
  - Acceptance: fraud layer tests pass.
  - Size: S

- [ ] Run phase1 case builder tests.
  - Command: `.venv\Scripts\pytest.exe tests\modules\test_detection\test_phase1_case_builder.py -q`
  - Acceptance: priority and ordering tests pass.
  - Size: S

- [ ] Produce before/after L1-07 score distribution.
  - File: `tests/phase1_rulebase/test-results/`
  - Acceptance: report contains bucket counts for `<0.45`, `0.45-0.69`, `0.70-0.84`, `>=0.85`.
  - Size: M

- [ ] Update detection rules documentation.
  - File: `docs/spec/DETECTION_RULES.md`
  - Acceptance: L1-07 section documents component scoring and queue bands.
  - Size: S

