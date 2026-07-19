# L1-07 Scoring Calibration - Context & Decisions

## Status
- Phase: Planning
- Progress: 0 / 4 phases complete
- Last Updated: 2026-04-29

## Key Files
**Modified later**:
- `src/detection/fraud_rules_access.py` - L1-07 queue split, row annotations, and fixed score constants.
- `config/phase1_case.yaml` - case-level priority floors and adjustments.
- `tests/modules/test_detection/test_fraud_rules_access.py` - focused L1-07 scoring examples.
- `tests/modules/test_detection/test_fraud_layer.py` - layer-level score expectations.
- `tests/modules/test_detection/test_phase1_case_builder.py` - case priority ordering and floor behavior.

## Current Findings
1. L1-07 immediate score is fixed.
   - `score_series.loc[immediate] = 0.8`
   - Review and low-priority scores are fixed at `0.4` and `0.1`.

2. Current immediate qualification already has useful evidence.
   - Positive evidence: manual source, missing approval date, manual JE, abnormal time, high-risk process, high approval level.
   - Immediate requires approval-required, non-system source, manual source, and minimum evidence count.

3. Case priority floors flatten differences.
   - L1-07 immediate has `min_priority_score: 0.75`.
   - Separate context floors can push cases to `0.80`, `0.90`, or `0.95`.

## Key Decisions
1. **Keep queue labels, change score calculation** (2026-04-29)
   - Rationale: immediate/review/low labels are useful for workflow routing.
   - Trade-off: tests must stop asserting a single exact L1-07 immediate score.

2. **Use component scoring instead of another flat severity constant** (2026-04-29)
   - Rationale: auditors need to see why one approval omission outranks another.
   - Alternatives: percentile ranking or severity-only remapping.
   - Trade-off: component scores require calibration and documentation.

3. **Treat mitigation as a negative factor, not an exclusion by default** (2026-04-29)
   - Rationale: recurring/interface entries may still be risky if material or repeated.
   - Trade-off: some review candidates remain visible, but lower-ranked.

## Practical Component Definitions
- `approval_requirement_confidence`: `exceeds_threshold`, `approval_level >= 1`, document amount above company approval threshold.
- `amount_materiality`: document amount relative to materiality, approval threshold, or population percentile.
- `control_bypass_context`: manual/adjustment source, missing approval date, sensitive process/account, creator role risk.
- `timing_and_manual_context`: manual JE, period-end, after-hours, backdated, weekend.
- `repeat_or_concentration`: repeated missing approvals by same creator/process/account/month.
- `data_trace_quality`: approval date absent, workflow trace absent, approver field blank across all lines.
- `mitigation_likelihood`: automated/interface/batch/recurring source, standing approval candidate, master-data-driven approval.

## Known Issues
- Current code uses line-level amount in several places; practical L1-07 severity should use document-level amount where possible.
- `materiality_amount` defaults to zero in `config/phase1_case.yaml`, so amount scoring can become relative to the current batch rather than audit materiality.
- `approved_by` missingness can be a data extraction issue, not a control failure; the model must keep column absence and field null separate.

