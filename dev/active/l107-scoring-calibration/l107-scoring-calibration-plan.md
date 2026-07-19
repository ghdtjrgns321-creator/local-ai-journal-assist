# L1-07 Scoring Calibration - Strategic Plan

## Executive Summary
L1-07 currently separates approval omission into immediate/review/low queues, but immediate rows receive a mostly fixed rule score. This makes serious and routine approval gaps cluster around the same score band, so the review queue is hard to use in practice.

The proposed solution keeps the existing queue split, but replaces the fixed immediate score with a transparent subscore model: approval requirement confidence, amount/materiality, control bypass context, timing/manual evidence, repeat pattern, and mitigation/standing-approval possibility.

## Current State
- `src/detection/fraud_rules_access.py` sets L1-07 immediate score to `0.8`, review score to `0.4`, and low-priority review score to `0.1`.
- `config/phase1_case.yaml` applies a L1-07 immediate priority floor of `0.75`.
- Case-level adjustments can apply additional floors such as `amount_or_period_floor: 0.80`, `strong_context_floor: 0.90`, and `critical_context_floor: 0.95`.
- `src/detection/rule_scoring.py` treats L1-07 as strong control-failure evidence, so severity weighting is already high before business context is considered.

## Proposed Solution
Introduce `l107_score` as a rule-local score with five positive dimensions and one mitigation dimension:

```text
l107_raw_score =
  0.25 * approval_requirement_confidence
+ 0.25 * amount_materiality
+ 0.20 * control_bypass_context
+ 0.15 * timing_and_manual_context
+ 0.10 * repeat_or_concentration
+ 0.05 * data_trace_quality
- 0.15 * mitigation_likelihood
```

Clamp the final score to these bands:
- `0.85-1.00`: confirmed critical, e.g. material amount, manual/adjustment source, no approval date, sensitive account/process, repeated by same creator.
- `0.70-0.84`: confirmed high, e.g. approval-required manual entry with enough corroboration but limited materiality or no repeat pattern.
- `0.45-0.69`: review required, e.g. missing approver with approval level evidence but recurring/interface or possible standing approval context.
- `0.10-0.44`: low-priority completeness issue, e.g. missing approver where approval requirement is weak or system source likely explains it.
- `0.00`: excluded, e.g. `approved_by` column absent or known system-approved source with no approval-required evidence.

## Implementation Phases

### Phase 1: Add Rule-Local Score Contract
**Goal**: Make L1-07 score components explicit without changing external outputs.

Tasks:
- Add `_l107_component_scores()` in `src/detection/fraud_rules_access.py`.
- Store component fields in `row_annotations["L1-07"]`.
- Keep the existing `score_series`, `review_score_series`, and labels for compatibility.
- Add tests in `tests/modules/test_detection/test_fraud_rules_access.py` for low/review/high/critical examples.

### Phase 2: Replace Fixed Immediate Score
**Goal**: Use `l107_raw_score` for L1-07 detail score while preserving immediate/review queue labels.

Tasks:
- Change `score_series.loc[immediate] = 0.8` to component-based scores.
- Set review scores from the same model, capped below the confirmed threshold unless immediate criteria are met.
- Update `tests/modules/test_detection/test_fraud_layer.py` expectations that currently assume `[0.8, 0.4]`.

### Phase 3: Calibrate Case Floors
**Goal**: Prevent floors from flattening meaningful differences.

Tasks:
- Change L1-07 `priority_floors` from a hard `0.75` for all immediate cases to score-sensitive floors.
- Use floor tiers: `0.70` for confirmed high, `0.80` for material/sensitive, `0.90` only for multi-evidence critical cases.
- Ensure `priority_score` can still rise through amount, behavior, repeat, and combo evidence.

### Phase 4: Validate With Synthetic and Realistic Profiles
**Goal**: Verify that the queue becomes useful for auditors.

Tasks:
- Run focused L1-07 unit tests.
- Run phase1 case builder tests.
- Compare score distribution before/after using bucket counts: `<0.45`, `0.45-0.69`, `0.70-0.84`, `>=0.85`.
- Confirm top cases include material and repeated approval omissions before routine missing approver cases.

## Risk Assessment
- **High Risk**: Overfitting to synthetic labels. Mitigation: use interpretable components and keep config thresholds company-overridable.
- **Medium Risk**: Existing tests expect fixed values. Mitigation: update assertions to verify bands and component ordering instead of exact constants.
- **Medium Risk**: Too many dimensions may hide the reason for ranking. Mitigation: expose component scores and top reasons in row annotations/export.

## Success Metrics
- Immediate L1-07 rows no longer cluster at one value; at least three populated score bands appear on representative data.
- Material manual approval omissions rank above recurring/interface review candidates.
- Every high L1-07 case exposes at least two human-readable reasons in row annotations.
- Existing aggregate score range remains `0.0-1.0`.

