# Timeseries Native Case Ranking Diagnostic - 2026-05-29

## Scope

This note records the current iteration result for the Phase2 Timeseries native case ranking surface on `datasynth_manipulation_v7_candidate_fixed5_normalcal5`.

The diagnostic compares alternative TS review candidate ordering surfaces only. It does not change detector thresholds, native case gates, PHASE1 priority/composite ranking, PHASE2 family fusion, Noisy-OR, or RRF.

## Baseline

Current native TS ordering:

| Metric | Value |
|---|---:|
| case_count | 861 |
| TOP100 | 0 / 620 |
| TOP500 | 0 / 620 |
| TOP1000 | 8 / 620 |
| TOP10000 | 8 / 620 |
| first truth-covering rank | 762 |
| TOP500 period_end_context true | 119 |
| TOP500 normal_closing_spike_proxy | 91 |
| TOP500 TS01 / TS02 | 75 / 425 |
| TOP500 subject top1 share | 2.2% |

The primary bottleneck remains ranking placement, not missing TS artifact generation.

## Candidate Results

| Candidate | TOP100 | TOP500 | TOP1000 | TOP10000 | First rank | FP pressure proxy | TOP500 normal closing proxy |
|---|---:|---:|---:|---:|---:|---:|---:|
| current_native_ts_ordering | 0 | 0 | 8 | 8 | 762 | 0.0860 | 91 |
| robust_z_context_composite | 0 | 8 | 8 | 8 | 300 | 0.0331 | 31 |
| period_end_lift_robust_balanced | 0 | 8 | 8 | 8 | 359 | 0.0358 | 34 |
| period_end_normalized_mixed_signal | 0 | 8 | 8 | 8 | 328 | 0.0358 | 34 |
| subject_activity_rank_adjusted | 0 | 8 | 8 | 8 | 323 | 0.0304 | 28 |
| robust_context_baseline_sufficiency | 0 | 8 | 8 | 8 | 295 | 0.0331 | 31 |
| mixed_signal_period_end_demoted | 0 | 8 | 8 | 8 | 381 | 0.0137 | 9 |
| non_period_end_surprise_priority | 0 | 8 | 8 | 8 | 445 | 0.0133 | 9 |
| ts01_ts02_balanced_surface | 0 | 8 | 8 | 8 | 335 | 0.0332 | 32 |
| review_burden_penalized_context | 8 | 8 | 8 | 8 | 76 | 0.0338 | 28 |
| review_burden_closing_demoted_context | 8 | 8 | 8 | 8 | 98 | 0.0233 | 16 |

## Feature Contribution Read

- `robust_z` plus `context_evidence_count` consistently moves the fixed5 truth-covering evidence unit from rank 762 into TOP500.
- Baseline sufficiency helps avoid overvaluing windows with thin history but does not materially change TOP-N coverage in this batch because most TOP500 candidates already have sufficient baseline.
- Demoting `normal_closing_spike_proxy` lowers false-positive pressure proxy but weakens first-rank placement compared with context-first candidates.
- Repeated subject/window_kind mitigation is the strongest fixed5 placement candidate. It lowers subject top1 share from 2.2% to 1.2% and moves the first truth-covering evidence unit to rank 76.
- Weak normal-closing demotion on top of repeated subject/window_kind mitigation keeps TOP100 coverage at 8 while lowering the false-positive pressure proxy from 0.0338 to 0.0233. The first truth-covering evidence unit moves from rank 76 to 98, still inside TOP100.
- TS01/TS02 balancing is useful as a concentration diagnostic, but quota-like ordering is not a production policy.

## Cross-Batch Check

`artifacts/timeseries_ranking_crossbatch_20260529.json` compares fixed3, fixed4, and fixed5_normalcal5 using the same diagnostic candidates.

| Batch | Current TOP100/TOP500 | Best fixed5 candidate TOP100/TOP500 | First rank current -> candidate | Primary gap |
|---|---:|---:|---:|---|
| fixed3 | 0 / 0 | 0 / 0 | none -> none | artifact truth coverage gap |
| fixed4 | 0 / 0 | 0 / 0 | none -> none | artifact truth coverage gap |
| fixed5_normalcal5 | 0 / 0 | 8 / 8 | 762 -> 98 | ranking gap |

Truth coverage flow:

| Batch | flagged truth docs | artifact window truth docs | native case truth docs | ranking can improve |
|---|---:|---:|---:|---|
| fixed3 | 13 | 0 | 0 | false |
| fixed4 | 13 | 0 | 0 | false |
| fixed5_normalcal5 | 13 | 8 | 8 | true |

This separates the current iteration result:

- fixed5 has a ranking placement problem, and diagnostic rankers can improve the review surface.
- fixed3/fixed4 have an artifact truth coverage gap. Since no truth-covering TS native case exists in those batches, ranking-only work cannot improve TOP-N coverage.
- Aggregate artifact retention reconstruction found that fixed3/fixed4 do have TS01 truth candidate windows before the current artifact cap. They are not retained by current original-order cap500.

Artifact retention reconstruction:

| Batch | TS01 candidate windows | TS01 truth candidate windows | current cap500 truth windows | score-desc cap500 truth windows | period-end+score cap500 truth windows |
|---|---:|---:|---:|---:|---:|
| fixed3 | 4,761 | 3 | 0 | 3 | 3 |
| fixed4 | 4,761 | 3 | 0 | 3 | 3 |
| fixed5_normalcal5 | 1,593 | 3 | 1 | 0 | 3 |

Unique truth document count under the same retention surfaces:

| Batch | current cap500 truth docs | score-desc cap500 truth docs | period-end+score cap500 truth docs |
|---|---:|---:|---:|
| fixed3 | 0 | 13 | 13 |
| fixed4 | 0 | 13 | 13 |
| fixed5_normalcal5 | 8 | 0 | 13 |

Review burden proxy:

| Batch | current cap500 | period-end+score cap500 | period-end+score low-support-demoted cap500 | low-support-demoted TOP100/TOP500 truth docs |
|---|---:|---:|---:|---:|
| fixed3 | 0.4379 | 0.4857 | 0.4521 | 0 / 13 |
| fixed4 | 0.4379 | 0.4857 | 0.4521 | 0 / 13 |
| fixed5_normalcal5 | 0.1959 | 0.4949 | 0.4528 | 13 / 13 |

This is the current improvement path:

- Ranking-only work has a hard limit on fixed3/fixed4 because native TS cases currently cover zero truth documents.
- Artifact retention has a diagnostic improvement path: period-end+score cap500 would retain TS01 truth candidate windows in fixed3, fixed4, and fixed5, covering 13 unique truth documents in each batch.
- Simple score-desc cap500 is not stable because it helps fixed3/fixed4 but misses fixed5 TS01 truth candidate windows.
- `period-end+score low-support-demoted` keeps the same TOP500 truth document count while removing one-row support windows from the retained TOP500. It still cannot move fixed3/fixed4 truth docs into TOP100 without score-band or ordinal-shaped keys that look too fitted.
- The named diagnostic retention candidate is `period_end_score_low_support_demoted_cap500`. It uses only period-end context, row support, score, and original grouped order as a stable tie-break.
- Retention no-fitting assertions are locked in the artifact: truth labels are not used for retention order, production artifact retention is unchanged, detector artifact cap is unchanged, and TS01 candidate generation is unchanged.
- Production policy remains unchanged. Readiness status is `production_application_hold` despite cross-batch TOP500 improvement, because fixture/DataSynth validation and UI/report review burden checks are still required.
- Production adoption proposal is recorded in `docs/spec/debugging/TIMESERIES_RETENTION_ADOPTION_PROPOSAL_20260529.md`.

Deterministic fixture validation:

| Check | Result |
|---|---|
| truth label used | false |
| first retained label | `supported_unusual_period_end_window` |
| supported unusual before one-row period-end noise | true |
| period-end context before non-period-end high score | true |

Fixture order under `period_end_score_low_support_demoted_cap500`:

1. `supported_unusual_period_end_window`
2. `normal_supported_period_end_burst`
3. `one_row_period_end_noise_high_score`
4. `non_period_end_high_score_window`

This supports the policy's audit-observable intent: supported period-end windows outrank one-row period-end noise, and period-end context outranks non-period-end high-score windows. It is not a production adoption decision.

## Row-Score Window Surface

The TOP100/TOP500 equality in native TS ranking was a real bottleneck signal. In fixed5, final TS `row_score` covers far more truth documents than TS01/TS02 detail flags:

| Stage | fixed5 truth docs |
|---|---:|
| row_score > 0 | 557 |
| row_score > 0.5 | 502 |
| TS01 detail flag | 13 |
| TS02 detail flag | 0 |
| current native case | 8 |
| retention candidate native surface | 13 |

This means the larger recovery path is not another ranker over current native cases. It is a diagnostic native-like row-score window surface that groups final TS row scores by subject/day.

Diagnostic row-score window results:

| Batch / surface | Policy | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 |
|---|---|---:|---:|---:|---:|---:|
| fixed3 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 43 | 43 | 56 | 109 |
| fixed4 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 43 | 43 | 56 | 109 |
| fixed5 row_score >= 0.5 | period-end+score low-support-demoted | 0 | 0 | 13 | 275 | 373 |
| fixed5 row_score >= 0.8 | period-end+score low-support-demoted | 0 | 8 | 13 | 270 | 290 |
| fixed3 row_score >= 0.5 | period-end support bucket + score | 43 | 51 | 51 | 143 | 363 |
| fixed4 row_score >= 0.5 | period-end support bucket + score | 43 | 51 | 51 | 143 | 363 |
| fixed5 row_score >= 0.5 | period-end support bucket + score | 0 | 264 | 269 | 348 | 376 |
| fixed5 row_score >= 0.8 | period-end support bucket + score | 0 | 191 | 210 | 272 | 290 |

Additional audit-observable context ordering was tested without truth labels in the ordering key. The added fields are window-level amount tail (`amount_log`, `amount_zscore`) and boolean context counts from manual JE, after-hours/weekend, round amount, suspense account, and risk keyword flags.

| Batch / surface | Policy | TOP100 | TOP500 | TOP1000 | TOP2000 | TOP5000 | First rank | TOP500 burden proxy |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| fixed3 row_score >= 0.5 | period-end support + amount | 162 | 300 | 339 | 356 | 429 | 1 | 0.4787 |
| fixed3 row_score >= 0.5 | period-end support + amount z-score | 161 | 258 | 338 | 356 | 429 | 8 | 0.4766 |
| fixed3 row_score >= 0.5 | period-end support + context count | 59 | 234 | 259 | 355 | 425 | 6 | 0.4759 |
| fixed3 row_score >= 0.5 | period-end support hybrid | 158 | 290 | 301 | 323 | 422 | 27 | 0.4801 |
| fixed4 row_score >= 0.5 | period-end support + amount | 162 | 300 | 339 | 356 | 429 | 1 | 0.4787 |
| fixed4 row_score >= 0.5 | period-end support + amount z-score | 161 | 258 | 338 | 356 | 429 | 7 | 0.4766 |
| fixed4 row_score >= 0.5 | period-end support + context count | 59 | 234 | 259 | 355 | 425 | 6 | 0.4759 |
| fixed4 row_score >= 0.5 | period-end support hybrid | 158 | 290 | 301 | 323 | 422 | 27 | 0.4801 |
| fixed5 row_score >= 0.5 | period-end support + amount | 213 | 314 | 361 | 365 | 381 | 1 | 0.4703 |
| fixed5 row_score >= 0.5 | period-end support + amount z-score | 219 | 309 | 358 | 361 | 380 | 1 | 0.4703 |
| fixed5 row_score >= 0.5 | period-end support + context count | 222 | 324 | 355 | 365 | 381 | 3 | 0.4717 |
| fixed5 row_score >= 0.5 | period-end support hybrid | 222 | 340 | 362 | 365 | 381 | 6 | 0.4675 |

Year-split check for `period-end support hybrid`:

| Batch | 2022 TOP100/TOP500 | 2023 TOP100/TOP500 | 2024 TOP100/TOP500 | TOP500 period-end share | TOP500 high amount z-score share |
|---|---:|---:|---:|---:|---:|
| fixed3 | 59 / 68 | 86 / 126 | 107 / 107 | 100.0% | 45.8% |
| fixed4 | 59 / 68 | 86 / 126 | 107 / 107 | 100.0% | 45.8% |
| fixed5_normalcal5 | 58 / 94 | 122 / 135 | 105 / 136 | 100.0% | 10.4% |

Interpretation:

- Bigger recovery exists without using truth labels for ordering.
- fixed3/fixed4 can recover TOP100 158 and TOP500 290 with the row-score context window hybrid.
- fixed5 can recover TOP100 222 and TOP500 340 with the same feature family.
- The improvement is not from TS01/TS02 detail flag retention alone. It comes from surfacing final TS row-score context windows as separate native-like evidence units, then ordering them by period-end context, support buckets, amount tail, and audit context count.
- The false-positive pressure proxy rises versus the conservative support-bucket-only surface but remains in a narrow band: fixed3/fixed4 `0.4801`, fixed5 `0.4675` for the hybrid. This is a review-burden warning, not a reason to discard the recovery path.
- The year-split floor is positive in every batch. The fixed5 TOP100 recovery is not isolated to one year, and fixed3/fixed4 show the same direction.
- The main burden signal is not one-row support; low-row-support share is `0.0`. The main burden signal is period-end concentration, plus high amount z-score concentration in fixed3/fixed4.
- The best current non-fitted larger recovery candidate is a separate TS row-score context window surface ordered by period-end context, support buckets, amount/context features, and score. It needs clear UI language and burden controls because the surface is broader than current native TS cases.

Readiness payload:

| Field | Value |
|---|---|
| candidate | `period_end_support_hybrid` |
| surface | `row_score_ge_0.5` |
| status | `production_application_hold` |
| all_batches_top100_improved | true |
| all_batches_top500_improved | true |
| truth_label_used_for_surface_order | false |
| production_case_generation_changed | false |

## Row-Score Burden Control

The next diagnostic iteration compared burden-control candidates derived from the same `period_end_support_hybrid` ordering. No new truth-fitted scorer was introduced.

| Batch | Policy | TOP100 | TOP500 | TOP1000 | First rank | TOP500 burden | Period-end share | Subject top1 share | High amount z-score share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fixed3 | hybrid baseline | 158 | 290 | 301 | 27 | 0.4801 | 100.0% | 8.6% | 45.8% |
| fixed3 | period-end 80% cap | 158 | 254 | 301 | 27 | 0.3929 | 80.0% | 9.4% | 58.6% |
| fixed3 | subject cap10 | 159 | 245 | 301 | 27 | 0.4570 | 100.0% | 2.0% | 40.6% |
| fixed3 | high amount z-score 25% cap | 158 | 296 | 301 | 27 | 0.4759 | 100.0% | 7.4% | 25.0% |
| fixed3 | UI100 context / export500 hybrid | 59 | 290 | 301 | 6 | 0.4766 | 100.0% | 7.6% | 45.8% |
| fixed4 | hybrid baseline | 158 | 290 | 301 | 27 | 0.4801 | 100.0% | 8.6% | 45.8% |
| fixed4 | period-end 80% cap | 158 | 254 | 301 | 27 | 0.3929 | 80.0% | 9.4% | 58.6% |
| fixed4 | subject cap10 | 159 | 245 | 301 | 27 | 0.4570 | 100.0% | 2.0% | 40.6% |
| fixed4 | high amount z-score 25% cap | 158 | 296 | 301 | 27 | 0.4759 | 100.0% | 7.4% | 25.0% |
| fixed4 | UI100 context / export500 hybrid | 59 | 290 | 301 | 6 | 0.4766 | 100.0% | 7.6% | 45.8% |
| fixed5 | hybrid baseline | 222 | 340 | 362 | 6 | 0.4675 | 100.0% | 5.0% | 10.4% |
| fixed5 | period-end 80% cap | 222 | 264 | 362 | 6 | 0.3796 | 80.0% | 5.6% | 26.4% |
| fixed5 | subject cap10 | 222 | 340 | 362 | 6 | 0.4570 | 100.0% | 2.0% | 10.2% |
| fixed5 | high amount z-score 25% cap | 222 | 340 | 362 | 6 | 0.4675 | 100.0% | 5.0% | 10.4% |
| fixed5 | UI100 context / export500 hybrid | 222 | 340 | 362 | 3 | 0.4675 | 100.0% | 5.0% | 10.4% |

Interpretation:

- Period-end 80% cap materially lowers burden but loses TOP500 coverage: fixed3/fixed4 `290 -> 254`, fixed5 `340 -> 264`.
- Subject cap10 lowers subject concentration with no fixed5 TOP500 loss, but fixed3/fixed4 lose TOP500 coverage `290 -> 245`.
- High amount z-score 25% cap is useful for fixed3/fixed4 because it lowers high amount concentration and slightly improves TOP500 `290 -> 296`. It does not affect fixed5 because fixed5 is already below the cap.
- UI100 context / export500 hybrid is not a universal UI default: it preserves TOP500 but drops fixed3/fixed4 TOP100 `158 -> 59`. It may still be useful as a split export strategy, not as a single review order.
- Current best next product-shaped candidate is not a new ranker. It is `period_end_support_hybrid` plus configurable burden controls, especially subject cap and high amount z-score cap, exposed as diagnostic controls before any production adoption.

## PHASE1 Incremental Alignment

The review direction was corrected after the recall-focused iterations. The main question is not only how many truth-labeled review candidates a TS surface can place in TOP100/TOP500. The PHASE2 TS question is whether the surface adds evidence that PHASE1 TOP100 did not already show, and whether that evidence is aligned with TS-specific timing/period-end behavior.

`row_score_phase1_incremental_alignment_summary` records this as aggregate-only evaluation. PHASE1 ranking is not changed. Truth labels and PHASE1 TOP-N document membership are used only after policy ordering for aggregate evaluation.

| Batch | PHASE1 TOP100 truth docs | PHASE1 TOP500 truth docs | PHASE1 reference |
|---|---:|---:|---|
| fixed3 | n/a | n/a | `phase1_case_result_not_configured` |
| fixed4 | 85 | 273 | available |
| fixed5_normalcal5 | 246 | 330 | available |

Broad TS context surface:

| Batch | Policy | TOP100 truth | TOP100 not in PHASE1 TOP100 | TOP100 TS-aligned not in PHASE1 TOP100 | TOP500 truth | TOP500 not in PHASE1 TOP100 | TOP500 TS-aligned not in PHASE1 TOP100 |
|---|---|---:|---:|---:|---:|---:|---:|
| fixed4 | period-end support hybrid | 158 | 123 | 0 | 290 | 252 | 59 |
| fixed4 | high amount z-score 25% cap | 158 | 123 | 0 | 296 | 258 | 65 |
| fixed5 | period-end support hybrid | 222 | 108 | 2 | 340 | 170 | 32 |
| fixed5 | high amount z-score 25% cap | 222 | 108 | 2 | 340 | 170 | 32 |

Timing-primary diagnostic candidates:

| Batch | Policy | TOP100 truth | TOP100 not in PHASE1 TOP100 | TOP100 TS-aligned not in PHASE1 TOP100 | TOP500 truth | TOP500 TS-aligned not in PHASE1 TOP100 |
|---|---|---:|---:|---:|---:|---:|
| fixed4 | timing primary round amount demoted | 0 | 0 | 0 | 0 | 0 |
| fixed4 | timing primary support + round amount demoted | 0 | 0 | 0 | 5 | 0 |
| fixed5 | timing primary round amount demoted | 7 | 7 | 7 | 14 | 13 |
| fixed5 | timing primary support + round amount demoted | 13 | 13 | 13 | 33 | 32 |

Interpretation:

- The previous `period_end_support_hybrid` result is a strong broad companion/export surface, not a TS primary review surface.
- In fixed4, broad hybrid TOP100 adds 123 truth documents outside PHASE1 TOP100, but zero are TS-aligned. Its TOP500 adds 59 TS-aligned documents outside PHASE1 TOP100.
- In fixed5, broad hybrid TOP100 adds 108 truth documents outside PHASE1 TOP100, but only 2 are TS-aligned.
- The timing-primary candidates are cleaner in fixed5, where TOP100 TS-aligned incremental improves from 2 to 13, but they do not generalize to fixed4.
- Therefore the current direction should split surfaces: broad TS-derived companion/export surface versus TS primary timing/period-end surface. The broad surface must not be described as a family-primary TS ranking candidate.
- Production application remains on hold. The next useful iteration is to design TS primary features that improve PHASE1-incremental TS-aligned TOP100 in both fixed4 and fixed5 without using truth labels in the ordering key.

## No-Fitting Evidence

The artifact records:

- `truth_label_used_for_scoring=false`
- `truth_label_used_only_for_aggregate_evaluation=true`
- `production_ranking_changed=false`
- `threshold_changed=false`
- `phase1_ranking_changed=false`
- `phase2_fusion_changed=false`

Score functions accept candidate name and `TimeseriesCase` only. `truth_docs` and scenario mappings are passed only to aggregate evaluation functions after candidate ordering is computed.

Raw leak self-report:

```json
{
  "doc_like_token_count": 0,
  "forbidden_identifier_key_count": 0,
  "phase2_case_id_like_token_count": 0
}
```

## Production Position

`review_burden_closing_demoted_context` is still the strongest candidate inside the current native TS case set, not an applied ranking policy. The larger recovery path is now the diagnostic TS row-score context window surface. Product use remains on hold because this is a broader evidence-unit surface and requires UI/export burden validation before adoption.

## Next Iteration Prompt

Role: continue as the local-ai-assist Phase2 Timeseries family agent. Keep work diagnostic-only and do not alter PHASE1 ranking, TS detector thresholds, native case gates, PHASE2 fusion, Noisy-OR, or RRF.

Focus:

1. Prepare a second adoption proposal for a TS row-score context window surface. Keep it separate from TS01/TS02 rule detail flags and current native TS case ordering.
2. Define UI language for this surface as "TS context window evidence unit", not a confirmed exception.
3. Add burden controls for period-end concentration, one-row support, subject concentration, and high-amount repeated normal windows.
4. Cross-check whether the amount/context hybrid inflates review burden on another DataSynth batch or year-split fixture.
5. Keep detector thresholds, native case gates, PHASE1 ranking, and PHASE2 fusion unchanged. Only write aggregate artifact outputs.
6. Keep raw identifier leak checks at zero for truth document tokens, forbidden identifier keys, and `p2_timeseries_window_` tokens.
7. Report current iteration result, next validation needed, and production application hold rationale.
