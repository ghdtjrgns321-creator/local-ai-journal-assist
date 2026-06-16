# L1-06 SoD Scoring - Task Checklist

## Progress Summary
0 / 13 tasks complete (0%)

## Phase 1: Scoring Contract
- [ ] Add L1-06 scoring policy to `config/audit_rules.yaml`
  - File: `config/audit_rules.yaml`
  - Details: Add score bands `direct_low=0.50`, `direct_medium=0.70`, `direct_high=0.80`, `direct_critical=0.95`, high-risk conflict types, protected processes, and amount materiality reuse.
  - Acceptance: YAML loads through existing audit-rule loading path and no existing config keys are renamed.
  - Size: S

- [ ] Update L1-06 scoring docs
  - File: `docs/spec/DETECTION_PARAMETERS.md`
  - Details: Replace binary wording with direct-only graduated scoring; explicitly state L3-12/work-scope signals still do not score L1-06.
  - Acceptance: Document includes the four bands and the L1-06/L3-12 exclusion rule.
  - Size: S

- [ ] Add failing tests for L1-06 band helper
  - File: `tests/modules/test_detection/test_fraud_rules_access.py`
  - Details: Cover direct-low, direct-medium, direct-high, direct-critical, and work-scope excluded cases.
  - Acceptance: Tests fail against current hardcoded 0.80 implementation.
  - Size: M

## Phase 2: Detector Logic
- [ ] Implement `_get_l106_sod_scoring_config()`
  - File: `src/detection/fraud_rules_access.py`
  - Details: Read new YAML keys with defaults matching the proposed four-band policy.
  - Acceptance: Missing config still produces deterministic defaults.
  - Size: S

- [ ] Implement `_score_l106_sod_rows()`
  - File: `src/detection/fraud_rules_access.py`
  - Details: Accept masks for direct marker, conflict type, IT/admin high-risk, amount materiality, protected process, threshold excess, and corroborating control override.
  - Acceptance: Returns a float Series with only immediate rows above zero.
  - Size: M

- [ ] Replace hardcoded immediate score assignment
  - File: `src/detection/fraud_rules_access.py`
  - Details: Change `score_series.loc[immediate_mask] = 0.8` to the helper output.
  - Acceptance: Direct SoD fixtures show distinct scores and non-immediate rows remain 0.00.
  - Size: S

- [ ] Add L1-06 row annotations
  - File: `src/detection/fraud_rules_access.py`
  - Details: Add metadata per immediate row with `bucket`, `score`, `score_reason`, and direct evidence flags.
  - Acceptance: Aggregator can read display labels without relying on raw numeric score only.
  - Size: M

- [ ] Preserve zero L1-06 review score contract
  - File: `src/detection/fraud_rules_access.py`
  - Details: Keep `review_score_series` as all-zero even when work-scope exclusions are counted.
  - Acceptance: Existing exclusion tests pass with updated score-band assertions.
  - Size: S

## Phase 3: Aggregation And Floors
- [ ] Update L1-06 priority floor config
  - File: `config/phase1_case.yaml`
  - Details: Add a Medium floor for `min_raw_score: 0.70`, keep a High floor for `min_raw_score: 0.80`, and add a stronger Critical priority floor for `min_raw_score: 0.95`.
  - Acceptance: 0.50 L1-06 rows do not get a priority floor; 0.70 rows reach Medium priority; 0.80 and 0.95 rows reach distinct High priority floors.
  - Size: S

- [ ] Verify row risk floor gating
  - File: `src/detection/score_aggregator.py`
  - Details: Extend `_apply_policy_risk_floors()` or add a sibling floor function so L1-06 raw 0.70 reaches Medium row risk, raw 0.80 reaches High, and raw 0.95 receives a stronger High score floor.
  - Acceptance: Aggregation test shows 0.50 raw L1-06 is Low, 0.70 is Medium, and 0.80/0.95 are High with distinct floor reasons.
  - Size: M

- [ ] Add aggregation tests for new L1-06 bands
  - File: `tests/modules/test_detection/test_score_aggregator.py`
  - Details: Construct L1-06 details with raw scores 0.50, 0.70, 0.80, 0.95 and assert ordering plus floor behavior.
  - Acceptance: 0.50 is Low, 0.70 is Medium, 0.80 is High, and 0.95 has the strongest score/priority floor.
  - Size: M

## Phase 4: Reporting And Regression
- [ ] Update L1-06 explanation output
  - File: `src/detection/explanations.py`
  - Details: Include conflict type and score reason when available.
  - Acceptance: Existing explanation tests still pass or are updated for the new reason text.
  - Size: S

- [ ] Add L1-06/L3-12 boundary regression tests
  - File: `tests/modules/test_detection/test_fraud_rules_access.py`
  - Details: Assert toxic pair, role threshold, and fallback process breadth do not appear in L1-06 `flagged_rules` or `review_rules`.
  - Acceptance: Work-scope cases only appear through L3-12 paths, not L1-06.
  - Size: S

- [ ] Run targeted verification
  - File: `tests/modules/test_detection/`
  - Details: Run `.venv\Scripts\pytest.exe tests\modules\test_detection\test_fraud_rules_access.py tests\modules\test_detection\test_score_aggregator.py -q`.
  - Acceptance: Targeted tests pass without changing unrelated snapshots.
  - Size: S

## Deployment Checklist
- [ ] Config defaults reviewed against DataSynth L1-06 prevalence.
- [ ] Existing L1-06 direct-only metrics still separate from L3-12 review population.
- [ ] Documentation updated before implementation is marked complete.
- [ ] Targeted tests passing.
