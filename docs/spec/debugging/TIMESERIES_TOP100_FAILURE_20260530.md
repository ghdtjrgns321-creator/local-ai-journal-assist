# Timeseries TOP100 Failure Diagnostic - 2026-05-30

## Scope

This Phase 6 diagnostic asks why TS-primary truth evidence does not reliably reach TOP100 on `fixed5_normalcal5`. The goal is not to accept TOP500 companion performance as sufficient. The goal is to separate implementation defects, DataSynth label alignment, and TS-primary ranking separation.

Production ranking, detector gates, PHASE1 ranking, and PHASE2 fusion were not changed. Truth/scenario labels are used only after candidate ordering for aggregate evaluation.

## Truth Attribution

| Metric | Count |
|---|---:|
| total truth docs | 620 |
| TS-primary label aligned truth docs | 32 |
| mixed / non-TS truth docs | 588 |
| truth docs in TS candidate pool | 502 |
| truth docs missing from TS candidate pool | 118 |
| candidate-pool truth docs outside TOP100 | 489 |

Alignment classes:

| Class | Count |
|---|---:|
| `ts_primary_label_aligned` | 32 |
| `mixed_but_ts_relevant` | 400 |
| `non_ts_primary_but_ts_context_present` | 144 |
| `not_ts_family_target` | 44 |

Feature buckets:

| Feature | Truth doc count |
|---|---:|
| TS01 match | 13 |
| TS02 match | 0 |
| period-end context | 381 |
| robust_z >= 3 | 347 |
| period_end_lift >= 2 | 464 |
| baseline observations >= 10 | 486 |
| supported window >= 7 rows | 397 |
| matched by other PHASE2 family | 620 |
| PHASE1 TOP100 | 246 |
| PHASE1 TOP500 | 330 |

## TOP100 Miss Reasons

Aggregate miss reasons for candidate-pool truth outside TOP100:

| Reason | Count |
|---|---:|
| mixed_scenario_not_ts_primary | 470 |
| normal_period_end_competition | 368 |
| amount_signal_belongs_to_unsupervised | 304 |
| manual_adjustment_signal_belongs_to_phase1_or_other_family | 298 |
| high_subject_activity_background | 163 |
| low_support_window | 105 |
| weak_ts_signal | 38 |
| ranking_formula_underweights_ts_specific_signal | 19 |
| baseline_unavailable_or_weak | 16 |
| implementation_suspect | 0 |

## Implementation Check

No implementation bug is suspected from this aggregate diagnostic.

| Check | Result |
|---|---|
| implementation_bug_suspected | false |
| artifact window count | 1000 |
| artifact sub_signal_high windows | 861 |
| TS01 truth doc count | 13 |
| TS02 truth doc count | 0 |

`expected_count`, `robust_z`, `period_end_lift`, and baseline support are present in candidate windows. The stronger issue is not missing fields but label alignment and ranking separation.

## Candidate Surfaces

| Surface | TOP100 TS-specific | TOP500 TS-specific | TOP100 mixed TS-relevant | TOP500 mixed TS-relevant | TOP500 low support ratio |
|---|---:|---:|---:|---:|---:|
| current native TS order | 0 | 0 | 0 | 0 | 0.876 |
| TS primary conservative | 13 | 32 | 0 | 0 | 0.000 |
| TS-specific severity | 0 | 32 | 0 | 0 | 0.000 |
| mixed TS-relevant | 2 | 32 | 236 | 275 | 0.000 |

Interpretation:

- `ts_primary_conservative_surface` is still the best TS-primary candidate because it moves 13 TS-specific truth docs into TOP100 without broad mixed inflation.
- `mixed_ts_relevant_surface` brings many mixed/context docs into TOP100, but it is not TS-primary enough.
- `ts_specific_severity_surface` is too strict for TOP100 but recovers TS-specific docs by TOP500.

## Decision

| Field | Value |
|---|---|
| ts_top100_failure_primary_reason | `mixed_scenario_not_ts_primary` |
| implementation_bug_suspected | false |
| datasynth_label_alignment_issue_suspected | true |
| ts_primary_label_aligned_truth_docs | 32 |
| mixed_but_ts_relevant_truth_docs | 400 |
| candidate_pool_missing_truth_docs | 118 |
| candidate_but_ranked_below_top100_truth_docs | 489 |
| best_ts_primary_candidate | `ts_primary_conservative_surface` |
| top100_product_viable | true |
| top500_companion_only_rejected_as_final_goal | true |
| production_adoption | false |

## Current Read

The failure is primarily label alignment plus ranking separation, not an obvious TS implementation bug. Most synthetic truth docs are mixed or non-TS-primary while still carrying TS context. TS-specific truth exists, but it is only 32 documents. Current TS-primary conservative ordering can place 13 of them in TOP100 and all 32 by TOP500.

Next required action: redefine the TS recall target around TS-primary-aligned truth, then continue TS-specific ranking diagnostics without using broad companion recall as the success criterion.

## Phase 7 Rank-Band Gap

`artifacts/timeseries_top100_rankband_gap_fixed5_20260530.json` narrows the target to the 32 TS-primary-aligned truth documents. It compares the 13 documents promoted by `ts_primary_conservative_surface` into TOP100 with the 19 documents that remain in TOP101-500. This is still diagnostic-only; production ranking, gate, PHASE1 ranking, and PHASE2 fusion were not changed.

### 13 vs 19 Feature Comparison

| Feature | Promoted TOP100 13 | Delayed TOP101-500 19 | Read |
|---|---:|---:|---|
| robust_z median | 3.3725 | 1.5738 | delayed group is weaker on median robust_z |
| period_end_lift median | 7.0 | 5.5 | delayed group is weaker on median lift |
| baseline observations median | 243 | 167 | delayed group has lower baseline support |
| context evidence median | 2 | 1 | delayed group has weaker context evidence |
| supported window ratio | 1.000 | 1.000 | support is not the blocker |
| period-end context ratio | 1.000 | 1.000 | period-end context is not differentiating |
| after-hours/weekend ratio | 1.000 | 0.421 | clear timing-context gap |
| amount-tail context ratio | 0.000 | 0.421 | diagnostic only; not used to inflate TS-primary |
| subject activity rank median | 61 | 4 | delayed group includes high-activity background |
| business process | TRE 13 | R2R 11, TRE 8 | R2R high-activity background explains most delayed docs |
| source | manual 13 | manual 15, adjustment 4 | source is aggregate-only, not a selector feature |
| fiscal year | 2022 6, 2023 7 | 2023 11, 2024 8 | 2024 remains weaker in TOP100 placement |

### Delayed 19 Reasons

| Reason | Count |
|---|---:|
| score_tie_or_rank_band_collision | 19 |
| lower_robust_z | 11 |
| low_context_evidence | 11 |
| low_baseline_support | 11 |
| high_subject_activity_background | 11 |
| normal_period_end_competition | 11 |
| weak_after_hours_weekend_signal | 11 |
| one_row_or_low_support_window | 0 |
| no_clear_audit_observable_difference | 0 |

The delayed set has an observable split: 11 R2R/high-activity-background documents are weaker on robust_z/context/baseline/after-hours evidence, while 8 TRE documents have enough timing support but were suppressed by amount-tail demotion before TS-primary evidence ordering.

### Diagnostic Candidate

`ts_specific_top100_stabilized_surface` was created as a diagnostic-only candidate. It keeps the TS-primary sort on timing/window evidence: period-end context, supported window, after-hours/weekend context, context evidence, period-end lift, robust_z, and subject activity background. It does not use truth, scenario, business process, source, fiscal year, PHASE1 rank, raw identifiers, or fixed5 weight sweep as selector inputs.

| Surface | TOP100 TS-specific | TOP500 TS-specific | TOP100 mixed TS-relevant | TOP500 mixed TS-relevant | TOP500 burden |
|---|---:|---:|---:|---:|---:|
| TS primary conservative | 13 | 32 | 0 | 0 | 0.4689 |
| TS-specific TOP100 stabilized | 21 | 32 | 0 | 0 | 0.4689 |

Current read:

- A defensible audit-observable TOP100 feature exists: after-hours/weekend timing priority with subject activity background adjustment.
- The improvement is `13 -> 21` TS-specific TOP100 while keeping TOP500 `32/32`.
- Mixed TS-relevant TOP100 remains `0`, so this is not broad companion inflation.
- DataSynth alignment issue remains because the full fixed5 truth set is still dominated by mixed/non-TS-primary documents.
- Historical note: at this diagnostic step, production adoption was still false
  pending validation. This was later superseded by the Phase 8/9 adoption lock
  below, where the stabilized surface became the product default ordering.

## Phase 8 V3.1 Primary Target Re-read

`artifacts/timeseries_v31_primary_fixed5_ownermeta_ic_20260531.json` re-reads the same TS surfaces with the current v3.1 canonical responsibility denominator. The denominator is no longer the earlier diagnostic `ts_primary_label_aligned=32`; it is the DataSynth owner metadata field `injected_timing_primary=True`, which yields 21 timing-primary truth documents. The owner metadata is used only for denominator selection. Candidate ordering remains truth/scenario/PHASE1-rank blind.

V3.1 target:

| Metric | Count |
|---|---:|
| timeseries primary docs | 21 |
| period-end context docs | 92 |
| PHASE1 immediate-covered TS primary docs | 0 |
| PHASE1 review-or-higher-covered TS primary docs | 2 |
| PHASE1 candidate-or-higher-covered TS primary docs | 21 |

Surface comparison:

| Surface | TOP100 TS primary | TOP500 TS primary | TOP500 low-support ratio | Read |
|---|---:|---:|---:|---|
| current native TS order | 0 / 21 | 0 / 21 | 0.876 | current native ordering misses all v3.1 TS primary targets |
| TS primary conservative | 13 / 21 | 21 / 21 | 0.000 | full TOP500 capture, partial TOP100 placement |
| TS-specific TOP100 stabilized | 21 / 21 | 21 / 21 | 0.000 | product default ordering fully places v3.1 TS primary in TOP100 |

Interpretation:

- The v3.1 denominator changes the read materially: TS is not inherently unable to surface its timing-primary targets.
- The current native ordering is the failing path: it ranks low-support and broad period-end windows ahead of the timing-primary evidence.
- The stabilized surface uses audit-observable timing/window features only and does not use truth labels, scenario labels, owner metadata, PHASE1 ranks, raw identifiers, or matched results as ordering inputs.
- Production adoption is now true for ordering only. Detector gate, threshold, PHASE1 ranking, and PHASE2 fusion remain unchanged. The explicit `native` fallback remains available.

Adoption-readiness guardrails are now part of the artifact:

- `production_default_ordering_strategy = ts_specific_top100_stabilized_surface`
- `candidate_ordering_strategy = ts_specific_top100_stabilized_surface`
- `explicit_flag_required = false`
- `product_default_adoption_allowed = true`
- `native_fallback_strategy = native`
- `period_end_context_primary_denominator = false`
- selector inputs exclude truth, scenario, owner metadata, PHASE1 rank, matched result, and raw identifiers
- post-adoption monitoring: single fixed5 owner-metadata candidate only, regenerated/slice validation still required, and period-end context documents must not inflate the primary denominator

The artifact also stores post-adoption validation requirements as structured data:

- regenerated owner-metadata DataSynth validation remains required after adoption.
- stabilized TOP100 and TOP500 primary capture must remain `21 / 21`.
- period-end context documents must not be counted as the primary denominator.
- fixed5-compatible slice validation remains required; TOP500 capture must not regress within eligible slices, and TOP100 slice regression requires review.
- fixed4 is not product adoption evidence.
- selector contract keeps truth, scenario, owner metadata, PHASE1 rank, matched result, and raw identifier inputs disallowed.

## Phase 9 Default Ordering Wiring

`build_timeseries_cases(...)` now defaults to `ts_specific_top100_stabilized_surface`. Native artifact order remains available as an explicit fallback:

```python
build_timeseries_cases(
    batch_id=batch_id,
    detection_result=timeseries_result,
    df=df,
    ordering_strategy="native",
)
```

`build_phase2_case_set(...)` forwards the same default strategy, and callers can still pass `timeseries_ordering_strategy="native"` when they need artifact order.

Guardrails:

- Production detector gate, threshold, PHASE2 fusion, and PHASE1 ranking are unchanged.
- Default Streamlit/native case order remains the case set order produced by the production attach path, now using the stabilized TS ordering.
- The stabilized key uses only case/artifact timing-window fields: period-end context, row-ref support count, round amount context, after-hours/weekend context, context evidence count, period-end lift, robust_z, and subject activity rank.
- Truth labels, scenario labels, PHASE1 rank, matched results, and raw identifiers are not selector inputs.
