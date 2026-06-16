# L1-06 SoD Scoring - Strategic Plan

## Executive Summary
L1-06 currently preserves the correct boundary between direct SoD violations and L3-12 work-scope review signals, but its direct scoring is almost binary: direct hits receive 0.80 and non-hits receive 0.00. The proposed change keeps L1-06 as a direct-only confirmed rule while introducing evidence-based severity bands so different SoD conflict types produce distinct row scores, case priorities, and review explanations.

## Current State
- `src/detection/fraud_rules_access.py` sets `score_series.loc[immediate_mask] = 0.8` in `b07_segregation_of_duties()`.
- `review_score_series` is intentionally all zero for L1-06, and work-scope candidates are counted only in `breakdown`.
- `src/detection/rule_scoring.py` marks L1-06 as `control_failure` with `strong` evidence and severity 4.
- `src/detection/score_aggregator.py` applies L1 family max scoring and then policy floors for L1-06.
- `config/phase1_case.yaml` floors L1-06 only when raw score is at least 0.80.
- Existing tests assert 0.80 for direct SoD, conflict type, and IT/admin high-risk posting cases.

## Proposed Solution
Keep L1-06 confirmed-only and replace the hardcoded 0.80 with a rule-local scorer that maps direct evidence to four severity bands. These are raw L1-06 evidence bands, not final row `risk_level` bands. Because row scoring multiplies the normalized L1 signal by `RULE_LEVEL_WEIGHTS["L1"] = 0.40`, Medium/High row risk needs explicit policy floors.

| Band | Raw L1-06 score | Intended meaning | Example evidence |
| --- | ---: | --- | --- |
| Direct-Low | 0.50 | Direct marker exists but limited context; should at least reach Low row risk through normal L1 weighting | `sod_conflict_type` present with non-material amount and no approval/cash/process escalation |
| Direct-Medium | 0.70 | Direct conflict with monetary or protected process relevance; should receive a Medium row/case floor | populated `sod_conflict_type` in TRE/P2P/O2C/R2R, or `sod_violation=True` plus conflict type |
| Direct-High | 0.80 | High-risk SoD conflict that should keep the current policy floor | direct conflict plus material amount, protected process, threshold excess, or high-risk conflict type |
| Direct-Critical | 0.95 | Direct SoD with strong circumvention context; should receive a stronger High priority floor than Direct-High | IT/admin business posting above materiality, direct SoD plus self-approval/skipped approval/manual override |

Do not reintroduce L1-06 review scoring. Work-scope, toxic-pair, and role-threshold populations remain L3-12/work-scope only.

Recommended floor alignment:

| Raw L1-06 band | Normal weighted row score before floors | Row risk floor | Case priority floor |
| --- | ---: | ---: | ---: |
| 0.50 Direct-Low | 0.20 | none; natural Low boundary | none |
| 0.70 Direct-Medium | 0.28 | 0.40 Medium | 0.45 Medium |
| 0.80 Direct-High | 0.32 | 0.70 High | 0.75 High |
| 0.95 Direct-Critical | about 0.30 before floor due severity normalization | 0.85 High | 0.85 High |

## Implementation Phases

### Phase 1: Scoring Contract
**Goal**: Define a stable L1-06 scoring policy before touching detector behavior.
**Tasks**:
- [ ] Add `l1_06_sod_scoring` policy to `config/audit_rules.yaml` - Size: S
- [ ] Document band semantics in `docs/spec/DETECTION_PARAMETERS.md` - Size: S
- [ ] Add unit tests for the scoring helper in `tests/modules/test_detection/test_fraud_rules_access.py` - Size: M

### Phase 2: Detector Logic
**Goal**: Make `b07_segregation_of_duties()` output evidence-sensitive scores while preserving direct-only classification.
**Tasks**:
- [ ] Add `_score_l106_sod_rows()` helper in `src/detection/fraud_rules_access.py` - Size: M
- [ ] Replace hardcoded `0.8` assignment with helper output - Size: S
- [ ] Add row annotation fields for `bucket`, `score`, `score_reason`, and direct evidence flags - Size: M
- [ ] Preserve `review_score_series` as all zero for L1-06 - Size: S

### Phase 3: Aggregation And Floors
**Goal**: Ensure new bands affect row/case priority without flattening all direct SoD hits back to High.
**Tasks**:
- [ ] Update L1-06 policy floors in `config/phase1_case.yaml` so score >= 0.70 gets Medium priority, score >= 0.80 gets High priority, and score >= 0.95 gets Critical priority - Size: S
- [ ] Extend `src/detection/score_aggregator.py` so L1-06 supports Medium and Critical row floors in addition to the current High floor - Size: M
- [ ] Add aggregation tests for 0.50, 0.70, 0.80, and 0.95 L1-06 raw scores - Size: M

### Phase 4: Reporting And Regression
**Goal**: Make the new scoring visible and protect the L1-06/L3-12 boundary.
**Tasks**:
- [ ] Update L1-06 explanations in `src/detection/explanations.py` if row annotations expose score reason - Size: S
- [ ] Add regression tests that work-scope review rows still score 0.00 for L1-06 - Size: S
- [ ] Run targeted pytest for fraud access, score aggregation, and case builder - Size: S

## Risk Assessment
- **High Risk**: Accidentally moving L3-12 work-scope signals back into L1-06 scoring. Mitigation: keep `review_score_series` zero and add tests for toxic pair, role threshold, fallback process breadth, and missing `sod_conflict_type`.
- **Medium Risk**: Policy floors may hide lower L1-06 bands. Mitigation: apply distinct floors: no floor for 0.50, Medium floor for 0.70, High floor for 0.80, stronger High/Critical priority floor for 0.95.
- **Medium Risk**: Existing metrics snapshots may change because 0.80-only assumptions become graduated. Mitigation: update expected tests only where direct L1-06 score granularity is the intended behavior.

## Success Metrics
- L1-06 direct hit raw scores are distributed across at least three non-zero bands in synthetic or fixture coverage.
- L1-06 work-scope review exclusions remain zero-scored for `score_series` and `review_score_series`.
- Existing direct-only precision contract remains intact: `flagged_rules` contains L1-06 only for direct confirmed rows.
- Targeted tests pass: `test_fraud_rules_access.py`, `test_score_aggregator.py`, and L1-06 relevant case builder tests.

## Dependencies
- Code: `src/detection/fraud_rules_access.py`, `src/detection/score_aggregator.py`, `src/detection/rule_scoring.py`, `src/detection/phase1_case_builder.py`
- Config: `config/audit_rules.yaml`, `config/phase1_case.yaml`
- Docs: `docs/spec/DETECTION_PARAMETERS.md`, historical `docs/archive/completed/DETECTION_RESULTS_D.md`
