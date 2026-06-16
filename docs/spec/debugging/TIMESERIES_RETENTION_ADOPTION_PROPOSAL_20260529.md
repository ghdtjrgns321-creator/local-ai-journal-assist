# Timeseries Retention Adoption Proposal - 2026-05-29

## Status

Proposal only. Production detector output, artifact retention, detector cap, native case gate, PHASE1 ranking, and PHASE2 fusion are not changed.

Candidate policy:

`period_end_score_low_support_demoted_cap500`

Policy order:

1. Period-end context windows first.
2. Within period-end context, demote one-row support windows.
3. Then order by TS window score descending.
4. Use original grouped order only as a stable tie-break.

This policy uses only audit-observable window fields: `period_end_context`, `row_count`, `score`, and grouped-order tie-break. It does not use truth labels, scenario labels, raw document identifiers, row identifiers, or case identifiers.

## Why This Candidate Exists

Current TS artifact retention keeps the first 500 grouped TS01 windows in source order. Cross-batch diagnostics showed that this original-order cap can drop period-end TS01 candidate windows even when those windows exist before native case construction.

The candidate is intended to make the TS01 artifact surface more audit-relevant without changing row scoring, thresholds, or native case gates.

## Cross-Batch Evidence

Unique truth document count under TS01 cap500 retention surfaces:

| Batch | Current cap500 | Score-desc cap500 | Period-end+score cap500 | Proposed policy cap500 |
|---|---:|---:|---:|---:|
| fixed3 | 0 | 13 | 13 | 13 |
| fixed4 | 0 | 13 | 13 | 13 |
| fixed5_normalcal5 | 8 | 0 | 13 | 13 |

TOP100/TOP500 under proposed retention:

| Batch | TOP100 truth docs | TOP500 truth docs |
|---|---:|---:|
| fixed3 | 0 | 13 |
| fixed4 | 0 | 13 |
| fixed5_normalcal5 | 13 | 13 |

Review burden proxy:

| Batch | Current cap500 | Period-end+score cap500 | Proposed policy cap500 |
|---|---:|---:|---:|
| fixed3 | 0.4379 | 0.4857 | 0.4521 |
| fixed4 | 0.4379 | 0.4857 | 0.4521 |
| fixed5_normalcal5 | 0.1959 | 0.4949 | 0.4528 |

Interpretation:

- The proposed policy improves TOP500 coverage in all three batches.
- It avoids the fixed5 failure of simple score-desc ordering.
- It lowers low-row-support burden versus period-end+score by demoting one-row windows.
- It still increases period-end concentration versus current retention, so UI/report review burden must be checked before adoption.

## Fixture Evidence

Deterministic fixture order under the proposed policy:

1. `supported_unusual_period_end_window`
2. `normal_supported_period_end_burst`
3. `one_row_period_end_noise_high_score`
4. `non_period_end_high_score_window`

Fixture assertions:

- Truth labels are not used.
- Supported period-end windows outrank one-row period-end noise.
- Period-end context outranks non-period-end high-score windows.

## No-Fitting Assertions

Locked in `artifacts/timeseries_ranking_crossbatch_20260529.json`:

- `truth_label_used_for_retention_order=false`
- `truth_label_used_only_for_aggregate_evaluation=true`
- `production_artifact_retention_changed=false`
- `detector_artifact_cap_changed=false`
- `ts01_candidate_generation_changed=false`

The policy deliberately rejects score-band or ordinal-nearby candidates, even though those could move fixed3/fixed4 truth windows into TOP100, because they are not audit-observable in a defensible way.

## Production Change Scope If Approved

Expected implementation target:

- `src/detection/timeseries_detector.py`
- TS01 artifact retention only.
- Keep `_WINDOW_ARTIFACT_CAP=500` unless separately approved.
- Keep TS01/TS02 detector thresholds unchanged.
- Keep native case builder gate unchanged.
- Keep PHASE1 priority/composite ranking unchanged.
- Keep PHASE2 family fusion unchanged.

Implementation shape:

- Build all grouped TS01 candidate windows in memory.
- Sort TS01 candidate windows by the proposed policy.
- Retain first 500 windows.
- Preserve existing window payload schema.
- TS02 retention remains unchanged unless a separate TS02 diagnostic supports a change.

## Required Tests Before Approval

Add or update tests to lock:

- TS01 retention policy orders period-end supported windows ahead of one-row period-end noise.
- Truth inputs are not accepted by the retention ordering helper.
- Artifact schema remains compatible.
- Raw identifier leak guard remains zero for diagnostic artifacts.
- Fixed3/fixed4/fixed5 diagnostic snapshots preserve expected aggregate direction.
- Existing `timeseries_window_artifact` and `phase2_timeseries_case_builder` tests pass.

Suggested commands:

```powershell
uv run pytest tests/modules/test_detection/test_timeseries_window_artifact.py tests/modules/test_services/test_phase2_timeseries_case_builder.py tests/modules/test_services/test_timeseries_ranking_crossbatch_diagnostic.py -q
uv run ruff check src/detection/timeseries_detector.py tools/scripts/diagnose_timeseries_ranking_crossbatch_20260529.py tests/modules/test_services/test_timeseries_ranking_crossbatch_diagnostic.py
```

## UI And Report Burden Check

Before adoption, inspect the retained TS01 period-end surface for:

- Excessive normal closing spike concentration.
- Excessive one subject or account concentration.
- Too many one-row support windows.
- Loss of TS02 visibility in the Timeseries family view.
- Misleading language that implies confirmed exceptions.

Allowed language:

- review candidate
- evidence unit
- period-end timing review item
- supported period-end window

Disallowed language:

- fraud detected
- confirmed detection
- final fraud finding

## Rollback Criteria

Rollback or keep on hold if any of the following occurs:

- Cross-batch TOP500 direction no longer improves after remeasurement.
- UI/report burden shows normal period-end closing candidates dominate the review surface.
- One subject/account/process concentration materially worsens.
- Raw identifier leak guard fails.
- Any production ranking, threshold, PHASE1 ranking, or PHASE2 fusion change is required to make the policy look good.
- Additional fixture/DataSynth validation shows one-row noise outranking supported windows.

## Current Recommendation

Keep as production adoption candidate, not applied.

Next action after approval:

Implement the policy behind a narrow TS01 artifact retention helper and re-run the fixed3/fixed4/fixed5 diagnostic suite plus focused detector/builder tests.
