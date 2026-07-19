# Duplicate Native Case Quality Diagnosis - fixed5

> Date: 2026-05-29  
> Dataset: `datasynth_manipulation_v7_candidate_fixed5_normalcal5`  
> Scope: PHASE2 duplicate native pair evidence unit diagnosis. Aggregate only; raw document IDs are not emitted.

## Summary

The previous recovery fixed the artifact creation failure: duplicate row score hits now produce `pair_artifact.top_pairs` and native `DuplicateCase` evidence units.

The remaining TOP-N recall issue was not caused by missing duplicate row scores. In fixed5, many synthetic truth documents entered the duplicate row-score and bounded candidate subset stages, but score-only top-N retention was monopolized by exact duplicate pairs from a small set of nontruth repeated documents.

The implemented change is artifact-only document diversity retention:

- row scores are unchanged;
- PHASE1 `priority_score`, `composite_sort_score`, and ranking are unchanged;
- PHASE2 family ranking combination policy is unchanged;
- thresholds are unchanged;
- row score hits are still not converted to cases without left/right pair evidence.

## Stage Counts

| Metric | Count |
|---|---:|
| duplicate row score hits | 152,043 |
| synthetic truth documents | 620 |
| truth rows | 1,251 |
| truth rows with duplicate score > 0 | 562 |
| truth documents with duplicate score > 0 | 285 |
| bounded candidate subset rows | 50,000 |
| bounded candidate subset documents | 27,924 |
| bounded candidate subset truth documents | 241 |
| top_pairs retained | 500 |
| top_pairs truth documents | 24 |
| DuplicateCase count | 198 |
| DuplicateCase covered documents | 145 |
| DuplicateCase truth documents | 22 |

## Candidate-To-Case Attrition

| Stage | Truth documents | Loss from prior stage | Interpretation |
|---|---:|---:|---|
| Row score hit | 285 | — | Duplicate row score covers part of the synthetic truth set. |
| Bounded candidate subset | 241 | 44 | The 50,000-row artifact subset drops some row-score truth documents, but this is not the dominant loss. |
| Generated/capped pair evidence | 217 | 24 | Pair generation plus the 200,000-pair scalability cap still produce left/right evidence for most candidate-subset truth documents. |
| Retained `top_pairs@500` | 24 | 193 | Main attrition point: metadata retention surface is much smaller than generated/capped pair evidence. |
| Case-grade top pairs | 22 | 2 | Weak pair tier excludes a small number of top-pair truth documents. |
| Native `DuplicateCase` | 22 | 0 | No join/canonical/document-id mapping loss observed after case-grade gate. |

Conclusion: the current bottleneck is top-N pair retention, not weak-tier gating or join/canonical failure.

## Retention Cap Diagnostic

Same detector thresholds and scores were used. Only the diagnostic retention cap changed.

| Retention | Truth documents | Case-grade truth documents | First truth pair rank | Tier distribution |
|---|---:|---:|---:|---|
| `top_pairs@500` | 24 | 22 | 129 | strong 25 / moderate 173 / weak 302 |
| `top_pairs@2k` | 76 | 41 | 129 | strong 58 / moderate 651 / weak 1,291 |
| `top_pairs@10k` | 105 | 60 | 129 | strong 261 / moderate 3,712 / weak 6,027 |
| `top_pairs@50k` | 217 | 94 | 129 | strong 1,787 / moderate 17,257 / weak 30,956 |

Retention expansion increases truth document coverage materially, but most added pairs remain weak or moderate review candidates. This supports further diagnostic work on audit-observable ranking diversity before changing any ranking policy.

## Root Cause

Before diversity retention, the default `top_pairs=500` was filled entirely by `L2-03a` exact duplicate pairs from 54 nontruth documents. Expanded diagnostic retention showed truth-covering pairs existed below the metadata top-500 boundary. The first truth-covering pair appeared below the score-only top-500, so the native recall gap was a retention concentration issue, not a missing row-score issue.

After diversity retention, `top_pairs=500` covers 209 documents and includes 24 truth documents. The resulting 198 case-grade pairs cover 145 documents, including 22 truth documents.

## Current Top Pair Profile

| Attribute | Result |
|---|---:|
| `L2-03a` pairs | 500 |
| strong pairs | 25 |
| moderate pairs | 173 |
| weak pairs | 302 |
| same-account pairs | 500 |
| same-partner pairs | 198 |
| amount similarity p50 | 1.0 |
| date distance p50 | 0 days |
| reference similarity p50 | 0.769 |

Interpretation: current top pairs remain exact same-account, same-date, same-amount review candidates. Case-grade pairs are the subset with sufficient partner/reference/text evidence. Weak pairs are intentionally excluded from `DuplicateCase`.

## Truth Vs Nontruth Pair Profile

Generated truth-covering pairs and nontruth pairs are both dominated by exact/similar same-account amount matches. The strongest differences are evidence mix and document concentration, not score thresholds.

| Profile | Truth-covering generated pairs | Nontruth generated pairs |
|---|---:|---:|
| pair count | 13,687 | 186,313 |
| truth document count | 217 | 0 |
| `L2-03a` pairs | 4,688 | 115,130 |
| `L2-03b` pairs | 8,999 | 71,183 |
| strong pairs | 206 | 24,136 |
| moderate pairs | 3,356 | 38,660 |
| weak pairs | 10,125 | 123,517 |
| same-account rate | 100.0% | 100.0% |
| same-partner rate | 26.0% | 33.7% |
| amount similarity p50 / p90 | 1.0 / 1.0 | 1.0 / 1.0 |
| date distance p50 / p90 | 0 / 730 days | 0 / 468 days |
| reference similarity p50 / p90 | 0.769 / 0.850 | 0.769 / 1.000 |
| text similarity p50 / p90 | 1.0 / 1.0 | 1.0 / 1.0 |
| pair score p50 / p90 | 1.0 / 1.0 | 1.0 / 1.0 |

The score distribution is too tied to explain attrition by score alone. Retention diversity and case-grade evidence tier are the relevant review-surface controls.

## Cap And Gate Diagnosis

| Stage | Diagnosis |
|---|---|
| Row score | Truth rows are present in duplicate row-score hits. |
| Candidate subset | Truth-hit documents are present in the 50,000-row bounded subset. |
| Pair generation | Expanded retention contains truth-covering left/right pair evidence. |
| Top-N retention | Previous score-only retention was the recall-zero cause. |
| Case builder | Current top pairs produce truth-covering `DuplicateCase` evidence units. |

Case-builder gate details:

- weak-pair truth documents in current top_pairs: 12;
- strong/moderate join-failed truth documents: 0;
- cases created with missing `document_id`: 0;
- duplicate case-id collapse count: 0.

The remaining caps are still meaningful:

- `duplicate_pair_artifact_max_rows=50,000` drops 102,043 row-score candidate rows from artifact generation, but it does not eliminate all truth-hit documents.
- `duplicate_pair_artifact_top_n=500` is still a metadata surface cap, but document diversity retention prevents one dense repeated group from consuming it.
- `duplicate_max_total_pairs=200,000` is reached and `truncation_reason=max_group_size` remains; this is a scalability guard, not a truth-tuned gate.

## Implemented Change

`build_duplicate_pair_artifact()` now retains top pairs with document diversity:

- default max pairs per document: 5;
- default max pairs per document pair: 1;
- fill behavior preserves `top_n` if diversity constraints cannot fill the artifact;
- selection diagnostics are recorded under `pair_artifact.coverage["top_pair_selection"]`.

This is an auditor review surface improvement: it reduces repeated evidence units from the same document pair and increases inspectable document coverage without changing detector scores or thresholds.

## Evidence Artifact

Detailed aggregate JSON:

- `artifacts/duplicate_native_case_quality_diagnosis_fixed5_20260529.json`
- `artifacts/duplicate_retention_candidates_fixed5_20260529.json`

The artifacts include `raw_identifier_leak_check.doc_like_token_count = 0` and
`raw_identifier_leak_check.forbidden_identifier_key_count = 0`; tests also assert the checked-in JSON
contains no `DOC-`, `TRUTH-`, truth document ID value, or `p2_duplicate_` case-id-like token.

## Phase 3 Retention Candidate Comparison

The following comparison is diagnostic-only. It uses the same generated/capped pair evidence and does
not change detector thresholds, row scores, PHASE1 priority/ranking, or PHASE2 family fusion.

| Candidate | top pairs | Expected DuplicateCase | Pair docs covered | Pair truth docs | Case truth docs | Weak ratio | Max pairs/doc | First truth pair rank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current document-diversity @500 | 500 | 198 | 209 | 24 | 22 | 60.4% | 5 | 129 |
| current document-diversity @2k | 2,000 | 709 | 842 | 76 | 41 | 64.5% | 5 | 129 |
| current document-diversity @10k | 10,000 | 3,973 | 4,224 | 105 | 60 | 60.3% | 5 | 129 |
| current document-diversity @50k | 50,000 | 19,044 | 9,267 | 217 | 94 | 61.9% | 72 | 129 |
| document-first @500 | 500 | 176 | 1,000 | 74 | 30 | 64.8% | 1 | 28 |
| case-grade-first @500 | 500 | 500 | 783 | 24 | 24 | 0.0% | 3 | 6 |
| pair-diversity-score @500 | 500 | 500 | 1,000 | 36 | 36 | 0.0% | 1 | 2 |
| evidence-diversity @500 | 500 | 500 | 1,000 | 36 | 36 | 0.0% | 1 | 2 |
| evidence-diversity @1k | 1,000 | 1,000 | 2,000 | 46 | 46 | 0.0% | 1 | 1 |
| evidence-diversity @2k | 2,000 | 2,000 | 2,333 | 46 | 46 | 0.0% | 225 | 1 |
| evidence-diversity @5k | 5,000 | 5,000 | 2,347 | 46 | 46 | 0.0% | 1,121 | 1 |
| tier-then-score-then-diversity @500 | 500 | 500 | 597 | 3 | 3 | 0.0% | 3 | 387 |
| two-stage score100/diversity500 | 500 | 455 | 833 | 28 | 28 | 9.0% | 6 | 102 |
| hybrid score-diversity balanced @500 | 500 | 500 | 1,000 | 34 | 34 | 0.0% | 1 | 3 |
| case-grade with score floor @500 | 500 | 500 | 783 | 24 | 24 | 0.0% | 3 | 6 |
| document-pair cap with fill @500 | 500 | 198 | 209 | 24 | 22 | 60.4% | 5 | 129 |
| rule-balanced duplicate surface @500 | 500 | 169 | 288 | 24 | 22 | 66.2% | 5 | 257 |

Diagnostic read:

- top-N expansion improves coverage but creates a much larger review surface; it should remain separate from the UI review cap.
- document-first retention maximizes document coverage, but still admits many weak pairs.
- case-grade-first removes weak-pair attrition but narrows the evidence surface to strong/moderate pairs only.
- evidence-diversity @500 gives the best TOP500 case truth coverage among tested candidates while keeping weak pairs out and document-pair concentration low. It uses pair score, partner/reference/text evidence, and repeated document/document-pair penalties; truth labels and scenarios are not selector inputs.
- expanding the evidence-diversity surface above 1k increases review burden sharply and reintroduces repeated normal document concentration during fill. That is a review burden signal, not a production recommendation.
- tier-first ordering is not a good candidate in fixed5: strong/moderate nontruth evidence dominates early ranks and pushes truth-covering pairs down.
- two-stage score100/diversity500 preserves the first 100 pair order, but the DuplicateCase builder then sorts cases by evidence tier and family score. Therefore pair-level TOP100 preservation does not preserve case-level TOP100.
- document-pair cap with fill and rule-balanced surfaces keep review burden closer to current, but they do not improve total DuplicateCase truth documents.

Current iteration result: the evidence supports further diagnostic-only ranking comparison. It is not yet enough to change production ranking.

## V3.1 Primary Readiness Follow-Up - 2026-05-31

Artifacts:

- `artifacts/duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json`
- `artifacts/duplicate_v31_improvement_next_fixed5_dupmeta_20260531.json`

The v3.1 duplicate primary target has 76 documents in 38 pair groups. Current DuplicateCase primary coverage remains 0 because the documents do not reach pair evidence generation:

| Stage | Primary docs |
|---|---:|
| Duplicate primary target | 76 |
| row score > 0 | 28 |
| candidate subset | 0 |
| generated pair evidence | 0 |
| DuplicateCase | 0 |

This is not a `top_pairs` retention problem. The blocking stage is candidate generation before pair evidence:

- 48 / 76 primary docs receive no duplicate row score. They have same partner/process, near amount, exact reference, 1-3 day shift, but same-account ratio is 0.0.
- 28 / 76 receive only lower-score L2-03d row hits at 0.428571, below the large-input candidate subset floor 0.598986.

Rejected fixes: expanding `top_pairs`, changing pair retention order, promoting weak pairs, using duplicate owner metadata as a selector, or lowering the global row-score threshold.

Next improvement class: row-score feature coverage and observable lower-score pair path. Run diagnostic-only experiments for a bounded L2-03d lower-score band and a same-account relaxation path when same partner/process, exact reference, near amount, and 1-3 day shift are present. Report case-grade primary docs and weak-pair pressure without changing production ranking or thresholds.

## Phase 4 Baseline Status

Duplicate family remains on a diagnostic baseline without changing the production ranker, thresholds,
pair generation, PHASE1 priority/ranking, or PHASE2 family fusion. The confirmed bottleneck is the
generated/capped pair evidence to `top_pairs` retention step. Current DuplicateCase coverage remains
low at 22 / 620 (3.55%) under the production document-diversity surface, while evidence-diversity @500
is a production-safe candidate comparison at 36 / 620 (5.81%) before cross-batch validation.

Production adoption remains pending. `evidence-diversity @500` is the strongest fixed5 total-coverage
candidate, but its case_count is 198 -> 500 and TOP100 case truth documents move from 21 to 14.
The next improvement should test a case-order-aware companion surface or cross-batch validation, not a
default product ranking change.

## Case-Order Companion Surface Iteration

Pair-level retention changes do not directly preserve `DuplicateCase` TOP100 because the builder and
measurement order cases by evidence tier, family score, and stable case id. The following
case-order-aware candidates are diagnostic-only and do not change production ordering.

| Candidate | Case count | TOP100 case truth docs | TOP500 case truth docs | Total case truth docs | Nontruth docs | Review burden vs current |
|---|---:|---:|---:|---:|---:|---:|
| current default | 198 | 21 | 22 | 22 | 123 | baseline |
| evidence-diversity @500 default case order | 500 | 14 | 36 | 36 | 964 | +302 cases |
| current TOP100 anchor + diversity fill | 682 | 21 | 41 | 48 | 1,028 | +484 cases |
| case score tiebreak + diversity | 500 | 10 | 36 | 36 | 964 | +302 cases |
| case-grade density cap | 500 | 10 | 36 | 36 | 964 | +302 cases |
| split UI100 current / export500 evidence | 500 | 21 | 36 | 36 | 964 | +302 cases |

Current iteration read:

- `current TOP100 anchor + diversity fill` preserves current TOP100 and improves TOP500/total coverage,
  but the review surface grows to 682 cases. This is a useful diagnostic, not a default UI policy.
- `case score tiebreak + diversity` and `case-grade density cap` do not recover TOP100; they still let
  strong/moderate nontruth evidence units occupy early case slots.
- `split UI100 current / export500 evidence` keeps the current UI TOP100 while exposing the broader
  evidence-diversity surface for export/sidecar review. This separates early review stability from
  broader diagnostic coverage without changing PHASE1 or PHASE2 family fusion.

Next iteration should validate the split surface and anchor-fill approach across at least one more
fixed batch or fixture. If the direction holds, the next design question is UI review cap versus
diagnostic/export sidecar separation, not threshold tuning.

## Cross-Batch Companion Surface Check

`artifacts/duplicate_case_order_crossbatch_20260529.json` compares fixed4 and fixed5_normalcal5 with
the same diagnostic-only case-order companion surfaces. The script keeps detector thresholds, row
scores, PHASE1 ranking, PHASE2 family fusion, and the production duplicate selector unchanged.

| Batch | Surface | TOP100 case truth docs | TOP500 case truth docs | Total case truth docs | Case count | Nontruth docs |
|---|---|---:|---:|---:|---:|---:|
| fixed4 | current default | 56 | 81 | 81 | 182 | 50 |
| fixed4 | evidence-diversity default | 48 | 100 | 100 | 500 | 894 |
| fixed4 | current TOP100 anchor + diversity fill | 56 | 101 | 101 | 662 | 933 |
| fixed4 | split UI100 current / export500 evidence | 56 | 100 | 100 | 500 | 894 |
| fixed5_normalcal5 | current default | 21 | 22 | 22 | 198 | 123 |
| fixed5_normalcal5 | evidence-diversity default | 14 | 36 | 36 | 500 | 964 |
| fixed5_normalcal5 | current TOP100 anchor + diversity fill | 21 | 45 | 48 | 682 | 1,028 |
| fixed5_normalcal5 | split UI100 current / export500 evidence | 21 | 36 | 36 | 500 | 964 |

Current iteration read:

- The split surface preserves the current UI TOP100 in both fixed4 and fixed5 while improving the
  broader export TOP500 surface.
- The anchor-fill surface gives the largest TOP500/total gain but increases case count and nontruth
  document coverage more than the split surface.
- This supports a UI review cap versus diagnostic/export sidecar design direction. It is still not a
  default production ranking change, and fixed3 remains an optional heavier validation pass.

## Split Surface Schema Candidate

The cross-batch artifact now records a diagnostic schema candidate named
`sidecar_contract_candidate`. It stores only aggregate fields:

- `ui_review_surface`: current duplicate case order capped at 100 review candidates;
- `export_sidecar_surface`: evidence-diversity case-grade evidence units capped at 500;
- evidence tier distribution, rule distribution, document coverage counts, nontruth pressure, and
  repeated-document concentration;
- raw identifier policy flags, all set to false for stored raw document IDs, row IDs, index labels,
  and Phase2 case IDs.

The schema candidate is not connected to PHASE2 family fusion and does not replace the production
default duplicate selector. In fixed4/fixed5, both UI and export surfaces are case-grade only:

| Batch | UI cap / truth docs | UI tier mix | Export cap / truth docs | Export tier mix | Export nontruth docs |
|---|---:|---|---:|---|---:|
| fixed4 | 100 / 56 | strong 65 / moderate 35 | 500 / 100 | strong 95 / moderate 405 | 894 |
| fixed5_normalcal5 | 100 / 21 | strong 25 / moderate 75 | 500 / 36 | strong 350 / moderate 150 | 964 |

Current iteration read: the split schema is a plausible contract for separating the auditor's first
review surface from a broader export sidecar. The remaining issue is review burden: export sidecar
nontruth document coverage is high, so the next iteration should define sidecar filters or grouped
export summaries before any adoption proposal.

## Export Sidecar Burden Iteration

Filtering individual evidence units by document pair, document, rule/tier balance, or high similarity
did not reduce nontruth document coverage because evidence-diversity @500 is already mostly unique by
document pair and case-grade. The useful burden reduction path is therefore a grouped summary sidecar
rather than another individual-case filter.

| Batch | Export sidecar | Underlying pairs | Summary groups | Truth docs covered | Nontruth docs covered |
|---|---|---:|---:|---:|---:|
| fixed4 | evidence-diversity cases | 500 | 500 case units | 100 | 894 |
| fixed4 | rule/tier grouped summary | 500 | 4 groups | 100 | 894 |
| fixed4 | rule/tier/similarity grouped summary | 500 | 5 groups | 100 | 894 |
| fixed5_normalcal5 | evidence-diversity cases | 500 | 500 case units | 36 | 964 |
| fixed5_normalcal5 | rule/tier grouped summary | 500 | 4 groups | 36 | 964 |
| fixed5_normalcal5 | rule/tier/similarity grouped summary | 500 | 4 groups | 36 | 964 |

Current iteration read:

- Individual export filters do not reduce nontruth document coverage without dropping truth coverage
  or becoming too selective.
- Grouped summaries reduce the review unit count from 500 case units to 4-5 aggregate groups while
  preserving the same underlying evidence coverage.
- Bounded representative drilldown is mixed. On fixed4, top20 representatives per rule/tier/similarity
  group cover 70 truth documents with 81 pair units. On fixed5, the same top20 drilldown covers only
  2 truth documents with 53 pair units, so representative ordering is not stable enough for adoption.
- The stronger direction is a two-layer export contract: grouped summary first, with representative
  drilldown clearly marked as partial and not a substitute for the full sidecar evidence population.

## Full-Evidence Manifest And High-Volume Group Policy

The grouped sidecar now includes a diagnostic full-evidence manifest. It does not store raw document
IDs, row IDs, pair IDs, index labels, or Phase2 case IDs. It stores only:

- group ordinal;
- group key (`rule_id`, evidence tier, similarity bucket);
- evidence ordinal start/end;
- evidence unit count and aggregate coverage counts.

The manifest shows where coverage and burden concentrate:

| Batch | Group | Evidence units | Truth docs | Nontruth docs |
|---|---|---:|---:|---:|
| fixed4 | L2-03a moderate partner-one-high | 26 | 48 | 4 |
| fixed4 | L2-03a strong partner-ref-text-high | 30 | 48 | 6 |
| fixed4 | L2-03b moderate partner-one-high | 378 | 2 | 754 |
| fixed5_normalcal5 | L2-03a moderate partner-one-high | 149 | 8 | 290 |
| fixed5_normalcal5 | L2-03a strong partner-ref-text-high | 338 | 28 | 648 |

A truth-blind high-volume policy (`summary_first_for_high_volume_groups`, threshold 100 evidence
units) gives different behavior by batch:

| Batch | Summary groups | Summary truth docs | Full-drilldown pairs | Full-drilldown truth docs | Full-drilldown nontruth docs |
|---|---:|---:|---:|---:|---:|
| fixed4 | 5 | 100 | 122 | 98 | 140 |
| fixed5_normalcal5 | 4 | 36 | 13 | 0 | 26 |

Current iteration read: high-volume summary-first is useful for reducing drilldown burden, but in
fixed5 the truth-covering evidence is inside high-volume groups. Therefore adoption-safe wording is:
summary coverage is complete for the export sidecar, while bounded drilldown is a partial sample and
must not be interpreted as full evidence coverage.

Current diagnostic contract candidate:

- `grouped_summary_primary_with_full_manifest`;
- first-level export review units are 4-5 rule/tier/similarity groups instead of 500 case rows;
- full evidence population remains represented by group ordinal and evidence ordinal ranges, not raw
  identifiers;
- representative drilldown remains partial and should not be used as the coverage denominator.

## PHASE1 Uplift Reframing

The latest diagnostic changes the evaluation question from broad truth recall to PHASE2's product
role: whether Duplicate native cases bring duplicate-specific review candidates into the upper review
surface when PHASE1 did not already place those documents in its TOP100. The new aggregate-only
artifact is `artifacts/duplicate_phase1_uplift_fixed5_20260529.json`.

fixed5 PHASE1 reference, using the stored PHASE1 case order and the minimum case rank per document:

| PHASE1 bucket | Truth documents |
|---|---:|
| TOP100 | 246 |
| 101-500 | 84 |
| 501-1000 | 52 |
| 1001+ | 162 |
| Not in PHASE1 cases | 76 |

Duplicate surface comparison under the PHASE1-uplift lens:

| Surface | Case cap | TOP100 truth docs | TOP100 truth outside PHASE1 TOP100 | TOP500 truth docs | TOP500 truth outside PHASE1 TOP100 | Read |
|---|---:|---:|---:|---:|---:|---|
| current document-diversity | 198 | 22 | 19 | 22 | 19 | Best aligned with early PHASE1 complement role. |
| evidence-diversity | 500 | 8 | 3 | 36 | 8 | Improves total coverage but mostly adds documents already high in PHASE1. |
| current TOP100 anchor + diversity fill | 682 | 22 | 19 | 42 | 19 | Preserves early complement value; extra TOP500 coverage is mostly PHASE1 TOP100 reinforcement. |
| phase1-gap case-grade diagnostic | 500 | 0 | 0 | 2 | 2 | PHASE1-rank gap alone is not a safe selector. |

Interpretation: the previous evidence-diversity direction is useful as an export/sidecar coverage
candidate, but it is not the best first review surface when the goal is PHASE1 TOP100 uplift.
Current duplicate ordering, despite lower total truth coverage, carries more Duplicate-specific
incremental value in TOP100 because 19 of its 22 truth-covering documents were outside PHASE1 TOP100.
The PHASE1-gap diagnostic is a negative control: using PHASE1 rank buckets without enough duplicate
evidence ordering collapses coverage and should not be proposed as a production ranking policy.

Production default remains unchanged. The next iteration should compare PHASE1-uplift metrics
cross-batch and look for duplicate-specific evidence features that preserve the current TOP100
incremental value while reducing weak-pair pressure or improving bounded export coverage.

## Cross-Batch PHASE1 Uplift Check

The cross-batch artifact `artifacts/duplicate_phase1_uplift_crossbatch_20260530.json` compares the
same PHASE1-uplift metrics on fixed4 and fixed5. It keeps raw identifiers out of the stored payload
and records only aggregate bucket counts, tier/rule distributions, and policy flags.

| Batch | Surface | TOP100 truth outside PHASE1 TOP100 | TOP500 truth outside PHASE1 TOP100 | Case-grade pair ratio | Read |
|---|---|---:|---:|---:|---|
| fixed4 | current document-diversity | 56 | 74 | 0.364 | Strong PHASE1 complement, but weak pair pressure exists in artifact top pairs. |
| fixed4 | evidence-diversity | 45 | 90 | 1.000 | Better export coverage and no weak pairs; TOP100 complement lower than current. |
| fixed4 | phase1-gap case-grade | 46 | 88 | 1.000 | Looks viable on fixed4 only. |
| fixed5 | current document-diversity | 19 | 19 | 0.396 | Best first-review complement on fixed5. |
| fixed5 | evidence-diversity | 3 | 8 | 1.000 | Better total coverage but weak PHASE1 TOP100 complement. |
| fixed5 | phase1-gap case-grade | 0 | 2 | 1.000 | Negative control: PHASE1 rank gap alone is unstable. |

Cross-batch read: evidence-diversity and phase1-gap selectors are not stable first-review adoption
candidates. The safer product direction is to keep current document-diversity as the first-review
TOP100 baseline, then expose case-grade evidence-diversity through a grouped export/sidecar surface.
That preserves the fixed5 PHASE1-uplift behavior while avoiding weak-pair case promotion. The next
iteration should focus on reducing sidecar burden and explaining weak artifact pairs, not replacing
the first-review order with a PHASE1-gap selector.

## Phase 5 Remaining Generated Potential

Phase 5 asks a narrower question: the generated/capped pair evidence has 24 fixed5 truth documents
outside PHASE1 TOP100, and current Duplicate TOP100 already captures 19. The remaining headroom is
therefore 5 documents, not a broad ranking-rewrite opportunity. The aggregate-only artifact is
`artifacts/duplicate_remaining_potential_fixed5_20260530.json`.

fixed5 first-review headroom:

| Measure | Count |
|---|---:|
| Generated potential outside PHASE1 TOP100 | 24 |
| Current TOP100 captured outside PHASE1 TOP100 | 19 |
| Current missed outside PHASE1 TOP100 | 5 |
| Generated potential outside PHASE1 TOP500 | 8 |
| Current TOP100 captured outside PHASE1 TOP500 | 5 |
| Current missed outside PHASE1 TOP500 | 3 |

Missed potential classification:

| Reason | fixed5 docs | Read |
|---|---:|---|
| weak_pair_only | 3 | Not suitable for case promotion. |
| artifact_cap_boundary | 2 | Case-grade potential exists, but not enough to justify first-review ranking replacement. |

Feature profile read:

- captured set: 19 truth docs, 661 related pairs, case-grade pair ratio 0.861, same-partner ratio
  0.861;
- missed set: 5 truth docs, 113 related pairs, case-grade pair ratio 0.009, same-partner ratio
  0.009;
- both sets are mostly period-end context, so period-end context alone is not a useful tiebreak.

Candidate comparison:

| Candidate | First-review change | TOP100 truth outside PHASE1 TOP100 | Sidecar TOP500 truth | Weak pair ratio | Decision |
|---|---|---:|---:|---:|---|
| current_plus_case_grade_sidecar | No | 19 | 36 | 0.000 | Keep as sidecar/export candidate. |
| current_with_missed_potential_tiebreak | Yes | 0 | 0 | 0.000 | Reject; loses current first-review complement. |

Cross-batch sanity is consistent with this decision. On fixed4, remaining potential is much larger
(164 generated potential, 53 current captured, 111 missed), but the same tiebreak candidate loses the
current captured set. This means a fixed5-only tiebreak would be fitting-prone, while a sidecar-only
case-grade surface is safer because it does not change first-review ordering.

Current Phase 5 recommendation:

- do not change production first-review ranking;
- keep current document-diversity as the first-review TOP100 baseline;
- use case-grade evidence-diversity as export/sidecar evidence, preferably behind grouped summary
  and full-evidence manifest;
- treat the remaining fixed5 headroom as small and mostly weak/boundary-limited, not as proof that
  ranking weights should be tuned.

## Phase 6 Policy Summary Attachment

Phase 6 records the Duplicate decision as aggregate-only runtime metadata in
`PipelineResult.phase2_family_policy_summary["duplicate"]`. This is descriptor metadata only; it is
not consumed by detectors, PHASE1 priority, PHASE2 fusion, or native case ordering.

Policy summary values:

- `primary_product_role`: `pair_evidence_first_review_with_case_grade_sidecar`;
- `production_first_review_ranking_changed`: `false`;
- `native_ordering_changed`: `false`;
- `production_adoption`: `true`, scoped to retaining the current first-review policy;
- `recommended_first_review_surface`: `current_document_diversity_top_500`;
- `recommended_sidecar_surface`: `current_plus_case_grade_sidecar`;
- `weak_pair_promotion_allowed`: `false`.

Sidecar descriptor values:

| Field | Value |
|---|---:|
| sidecar surface id | duplicate_case_grade_sidecar_v1 |
| case-grade only | true |
| weak pair ratio | 0.0 |
| sidecar TOP500 truth docs | 36 |
| first-review TOP100 captured outside PHASE1 TOP100 | 19 |
| missed potential | 5 |
| weak-pair-only missed | 3 |
| artifact-cap-boundary missed | 2 |
| raw identifier leak check | 0 |

The sidecar descriptor does not replace `case_set.duplicate_cases` order and does not add UI tabs,
columns, or wording. User-facing explanation lives in
`docs/guide/users/DUPLICATE_PAIR_EVIDENCE_SURFACE.md`.

## Phase 7 fixed5_dupmeta Primary Target Attrition

`fixed5_dupmeta` resolves the Duplicate denominator question, so Phase 7 traces the 76 Duplicate
primary target documents / 38 pair groups through the existing detector artifact path without
changing production first-review ordering.

- Script: `tools/scripts/diagnose_duplicate_primary_target_fixed5_dupmeta_20260530.py`
- Artifact: `artifacts/duplicate_primary_target_fixed5_dupmeta_20260530.json`
- Scope: aggregate-only row score -> bounded candidate subset -> generated pair evidence -> retained top_pairs -> DuplicateCase

Stage attrition:

| Stage | Primary docs |
|---|---:|
| Duplicate primary target | 76 |
| duplicate row score > 0 | 28 |
| large-input candidate subset | 0 |
| generated pair evidence | 0 |
| retained top_pairs@500 | 0 |
| case-grade top_pairs | 0 |
| DuplicateCase | 0 |

Reason distribution:

| Reason | Docs |
|---|---:|
| no duplicate row score | 48 |
| candidate subset excluded | 28 |

The 28 row-score-hit primary documents are all `L2-03d` time-shifted-duplicate hits with row score
`0.42857142857142855`. The large-input candidate subset keeps the top 50,000 row-score rows and its
minimum retained score is `0.5989857631894374`, so none of these primary rows reach pair generation.
Expanding retained top_pairs to 50,000 does not recover primary docs because the primary rows are
already absent from the bounded candidate frame.

Interpretation:

- The current primary target miss is not a top_pairs retention or case-builder join issue.
- The first bottleneck is row-score coverage: 48 / 76 primary docs have no duplicate row score.
- The second bottleneck is bounded candidate subset selection: 28 / 76 have row score, but their
  score is below the large-input candidate floor.
- A production ranking change would not address this path. The next candidate should be
  diagnostic-only feature coverage for time-shifted employee-card duplicate-like pairs, or a bounded
  artifact candidate sidecar that samples lower-score `L2-03d` rows without changing row score,
  threshold, PHASE1 ranking, or PHASE2 fusion.
- Raw identifier leak check remains 0.

## Phase 7 Candidate Sidecar Sampling

The follow-up artifact `artifacts/duplicate_candidate_sidecar_fixed5_dupmeta_20260530.json` tests
whether bounded sidecar sampling can route lower-score Duplicate primary evidence into pair
generation without replacing the main 50k candidate subset.

Decision payload:

| Field | Value |
|---|---:|
| primary target docs | 76 |
| row-score coverage docs | 28 |
| main candidate subset coverage docs | 0 |
| row-score coverage gap docs | 48 |
| low-score cap gap docs | 28 |
| bottleneck stage | candidate_subset_prefilter |
| top_pairs cap bottleneck | false |

Primary gap profile:

| Group | Docs | Semantic groups | Similarity source | Date bucket | Amount | Reference | Text | PHASE1 action tier |
|---|---:|---:|---|---|---|---|---|---|
| no row score | 48 | 24 | mixed | 1_3d | near | exact | medium | none 39, medium 4, low 5 |
| low-score L2-03d | 28 | 14 | mixed | 1_3d | near | exact | medium | medium 15, low 13 |
| retained in main candidate subset | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

Sidecar comparison:

| Sidecar | Candidate docs | Primary docs entering | Primary docs with pair evidence | Case-grade primary docs | Weak pair ratio | Read |
|---|---:|---:|---:|---:|---:|---|
| l2_03d_stratified_low_score_sample | 10,000 | 0 | 0 | 0 | 78.18% | Rule-only bounded sample does not reach primary docs. |
| duplicate_primary_metadata_probe_sample | 76 | 76 | 76 | 76 | 97.76% | Oracle feasibility probe only; not a product selector. |
| rule_balanced_duplicate_candidate_sample | 10,000 | 0 | 0 | 0 | 79.50% | Rule-balanced sample still misses primary docs. |

Interpretation:

- Pair feasibility exists only when the DataSynth duplicate primary metadata is used as an oracle
  probe. That confirms the rows can form duplicate-like pair evidence in principle, but it is not a
  production-safe selector.
- Non-oracle sidecars based on current rule/score evidence do not reach the primary target docs.
- The current observable feature path has two gaps: 48 docs have no row score, and 28 docs have
  lower-score `L2-03d` evidence that sits below the main candidate subset floor.
- Main first-review ranking, threshold, PHASE1 ranking, and PHASE2 fusion should remain unchanged.
- Weak pairs remain unsuitable for primary DuplicateCase promotion. The oracle probe's weak-pair
  ratio is 97.76%, so any product sidecar needs stronger observable filtering before adoption.

## Phase 8 Product Policy Metadata

`phase2_family_policy_summary["duplicate"]` now carries the v3.1 duplicate-primary status as
aggregate-only metadata:

| Field | Value |
|---|---:|
| v3.1 primary status | `pending_pair_evidence_validation` |
| v3.1 primary candidate docs | 76 |
| native TOP500 primary docs | 0 |
| no-row-score primary docs | 48 |
| low-score L2-03d primary docs | 28 |
| non-oracle sidecar pair feasibility | false |

This metadata is not consumed by detector scoring, PHASE1 ranking, PHASE2 fusion, or case ordering.
It exists so downstream consumers do not misread the 76 duplicate-like metadata documents as a
validated product primary recall denominator.

## Phase 9 V3.1 Readiness Contract

`artifacts/duplicate_v31_primary_readiness_fixed5_dupmeta_20260531.json` is the current compact
readiness artifact. It reads the Phase 6 and Phase 7 aggregate artifacts and locks the decision that
Duplicate primary recovery is not a `top_pairs` ranking problem.

Readiness lock:

| Metric | Value |
|---|---:|
| duplicate primary candidate docs | 76 |
| duplicate pair groups | 38 |
| row-score primary docs | 28 |
| no-row-score primary docs | 48 |
| primary row-score rows | 54 |
| candidate subset primary docs | 0 |
| generated pair primary docs | 0 |
| top_pairs primary docs | 0 |
| case-grade top_pairs primary docs | 0 |
| DuplicateCase primary docs | 0 |

Score path:

| Field | Value |
|---|---:|
| all duplicate row-score hits | 152,043 |
| primary rule docs: L2-03d | 28 |
| primary L2-03d score | 0.42857142857142855 |
| candidate subset min score | 0.5989857631894374 |
| selected candidate rows | 50,000 |

Gap decomposition added in the readiness artifact:

| Gap | Docs | Pair groups | Profile |
|---|---:|---:|---|
| no row score | 48 | 24 | 1-3 day shift, near amount, exact reference, medium text, partner match 1.0, same account 0.0, P2P |
| low-score L2-03d | 28 | 14 | same aggregate profile; score floor gap 0.17041433461800887, primary/floor ratio 0.7154951835405927 |

The no-row-score group is mostly outside PHASE1 action tiers (`none=39`, `medium=4`, `low=5`).
The low-score group is already PHASE1 low/medium context (`low=13`, `medium=15`) but still below the
large-input candidate floor. This confirms the issue is observable duplicate feature coverage and
lower-score pair path design, not PHASE1 queue placement.

Non-oracle sidecar failure profile:

| Sidecar | Candidate docs | Primary docs entering | Primary pair docs | Weak pair ratio | Read |
|---|---:|---:|---:|---:|---|
| l2_03d_stratified_low_score_sample | 10,000 | 0 | 0 | 78.18% | current observable sample misses primary docs |
| rule_balanced_duplicate_candidate_sample | 10,000 | 0 | 0 | 79.50% | rule-balanced sample still misses primary docs |
| duplicate_primary_metadata_probe_sample | 76 | 76 | 76 | 97.76% | oracle feasibility only, not a selector |

The readiness artifact records `top_pairs_cap_is_bottleneck=false` after checking retention sizes
500, 2,000, 10,000, and 50,000. The next improvement class is
`row_score_feature_coverage_or_observable_lower_score_pair_path`.

Guardrails remain unchanged:

- do not use duplicate primary metadata or pair-group truth metadata as selector input;
- do not lower row-score thresholds to recover fixed5;
- do not expand `top_pairs` as the primary fix;
- do not promote weak pairs into `DuplicateCase`;
- preserve current first-review ordering.

## Phase 10 Observable Feature-Gap Experiment

`artifacts/duplicate_v31_feature_gap_experiment_20260531.json` tests two oracle-free sidecar
directions while leaving the production path unchanged.

| Experiment | Candidate docs | Primary docs entering | Primary pair docs | Case-grade primary docs | Read |
|---|---:|---:|---:|---:|---|
| `l2_03d_lower_score_floor_band_sample` | 10,000 | 0 | 0 | 0 | lower-score L2-03d rows still do not recover primary docs |
| `observable_document_profile_sample` | 10,000 | 76 | 75 | 74 | observable document profile can recover pair evidence, but burden is high |

The observable profile uses non-oracle fields only: P2P process, non-empty reference, non-empty
trading partner, two-to-three-line documents, and amount rank. It does not use truth label,
scenario, owner metadata, PHASE1 rank, or matched result as selector input.

Decision: this is a strong diagnostic direction, not a product default. The candidate admits
9,924 non-primary documents into the sidecar. The next work should reduce burden with audit-stable
guards before any export/sidecar adoption, and still must not alter first-review ordering or weak
pair promotion.

## Phase 11 V3.2d Companion Burden Reduction

`artifacts/duplicate_v32_companion_sidecar_burden_20260531.json` moves the denominator from the
old v3.1 duplicate-primary probe to the v3.2d responsibility map. Duplicate has no primary
denominator in v3.2d; the active lifecycle metric is `duplicate_companion=111`.

This diagnostic is candidate-document burden analysis, not production pair generation. It does not
change row-score thresholds, `top_pairs`, weak-pair gates, PHASE1 ranking, or PHASE2 fusion.

| Candidate | Candidate docs | Companion docs entering | Non-target candidate docs | Companion candidate recall | Read |
|---|---:|---:|---:|---:|---|
| current duplicate path | n/a | 0 | n/a | 0.00% | read from v3.2d responsibility artifact; full detector rerun skipped |
| observable profile top 10k | 10,000 | 76 | 9,924 | 68.47% | high coverage, high burden |
| observable profile top 5k | 5,000 | 76 | 4,924 | 68.47% | same coverage with half the burden |
| observable profile top 2k | 2,000 | 76 | 1,924 | 68.47% | best broad-profile burden reduction so far |
| strict time-shift/reference guard | 2,239 | 28 | 2,211 | 25.23% | stronger audit guard, but loses too much companion coverage |

The strict guard uses only observable GL fields: row count, business process, trading partner,
reference similarity, posting-date distance, and amount proximity. It does not use truth labels,
owner metadata, pair-group truth, PHASE1 rank, or matched results as selector input.

Decision: no product sidecar adoption yet. The broad profile can reduce burden by lowering the
document cap to 2,000 without losing the 76 companion documents it admits, but the diagnostic still
does not prove stable case-grade pair evidence on the regenerated v3.2d data. The next duplicate
iteration should test pair-artifact generation only on the bounded 2k candidate frame and then
compare case-grade ratio before any export/drilldown sidecar is considered.

## Phase 12 V3.3b Primary/Companion Sidecar Burden

`artifacts/duplicate_v33_exact_sidecar_fixed5_20260531.json` measures the regenerated
v3.3b owner map. Duplicate primary is now `time_shifted_duplicate` with 22 documents,
and duplicate companion has 71 documents. The current production path still does not
route target documents into the pair artifact candidate subset.

Current path after the 2026-06-01 bounded supplement follow-up:

| Stage | Primary docs | Companion docs | Notes |
|---|---:|---:|---|
| row score > 0 | 10 / 22 | 8 / 71 | lower-score evidence exists for part of the target set |
| candidate subset | 22 / 22 | 34 / 71 | bounded observable-profile supplement reserves 500 document profiles inside the 50k row budget |
| case-grade pair evidence | 10 / 22 | 4 / 71 | document-profile pair builder recovers the strict observable subset |

Diagnostic sidecar comparison:

| Candidate | Candidate docs | Primary case-grade | Companion case-grade | Non-target docs | Read |
|---|---:|---:|---:|---:|---|
| observable profile top 10k | 10,000 | 22 / 22 | 34 / 71 | 9,944 | full recovery, too broad |
| observable profile top 5k | 5,000 | 22 / 22 | 34 / 71 | 4,944 | same recovery, high burden |
| observable profile top 2k | 2,000 | 22 / 22 | 34 / 71 | 1,944 | prior bounded baseline |
| observable profile top 1k | 1,000 | 22 / 22 | 34 / 71 | 944 | same recovery, lower burden |
| observable profile top 500 | 500 | 22 / 22 | 34 / 71 | 444 | best bounded export/drilldown candidate |
| mid time-shift/reference guard | 38 | 10 / 22 | 4 / 71 | 24 | low burden, loses too much coverage |
| strict time-shift/reference guard | 36 | 10 / 22 | 4 / 71 | 22 | low burden, loses too much coverage |

Selector inputs remain observable GL fields only: document row count, business process,
trading partner presence, reference presence/similarity, posting-date distance, and
amount proximity. Truth labels, owner metadata, pair-group truth, PHASE1 rank, and
matched results are not selector inputs.

Decision: production duplicate path now includes the bounded observable-profile supplement,
rule-balanced pair selection, and a document-profile pair builder. This moves current
case-grade primary evidence from 0 / 22 to 10 / 22 without lowering row-score thresholds,
raising `top_pairs` caps, changing weak-pair gates, or using truth/owner metadata as a
selector. `observable_profile_top_500` still remains an export/drilldown candidate rather
than a full first-review replacement. The remaining 12 primary docs enter the candidate
subset but do not form observable case-grade pair evidence under current GL fields, so
the next step is DataSynth/feature-path review rather than another ranking tweak.

## Phase 13 V3.3d Shortcut-Free Duplicate Follow-Up

`artifacts/duplicate_v33d_exact_sidecar_fixed5_20260601.json` repeats the exact
sidecar measurement on `datasynth_manipulation_v7_candidate_fixed5_ownermeta_v33d`.
The duplicate primary denominator is now 19 shortcut-free `time_shifted_duplicate`
documents. Current production path:

| Stage | Primary docs | Companion docs | Notes |
|---|---:|---:|---|
| row score > 0 | 11 / 19 | 8 / 71 | row signal still covers only part of the primary set |
| candidate subset | 19 / 19 | 34 / 71 | bounded observable-profile supplement admits all primary docs |
| case-grade pair evidence | 8 / 19 | 4 / 71 | retained `top_pairs` contain only the strict pair subset |

Aggregate-only probe on `observable_profile_top_500` pair-artifact generation
(`RUN_DUPLICATE_OBS500_PAIR_ARTIFACT_PROBE=1` path) showed:

| Probe | Primary pair docs | Primary case-grade docs | Remaining primary docs | Read |
|---|---:|---:|---:|---|
| current mixed 50k candidate artifact | 8 / 19 | 8 / 19 | 11 | score-candidate surface dilutes profile evidence inside top 500 |
| observable-profile top 500 artifact only | 19 / 19 | 15 / 19 | 4 | sidecar profile improves pair evidence but is not enough for all docs |

The remaining 4 documents in the profile-only artifact are aggregate-identical:
2-row P2P documents with partner and reference present, expected same partner,
same process, exact reference, near amount, 1-3 day shift, and medium text
similarity. However, their observable document profile has same
`trading_partner + business_process` group size 1 inside the top-500 profile
frame, so L2-03e cannot create a document-profile pair without a non-observable
truth/owner bridge. This is not a row-threshold issue and should not be fixed by
weak-pair promotion.

Decision: keep the production duplicate path unchanged. The safe improvement is
diagnostic/export-sidecar decomposition: profile-only generation can explain
15 / 19 primary docs, while the last 4 require DataSynth or observable feature
path review. Selector inputs remain GL-observable only; truth, owner metadata,
scenario labels, PHASE1 rank, and matched result membership remain evaluation-only.
