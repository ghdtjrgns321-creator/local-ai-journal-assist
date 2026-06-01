# Unsupervised Native Case Evidence Quality — 2026-05-30

## Scope

This diagnostic validates PHASE2 unsupervised production evidence quality for fixed5.
It does not change q95 gate, VAE score/threshold, PHASE1 ranking, PHASE2 fusion, or
native row case ordering. Truth labels are used only for aggregate evaluation.

Artifact:

- `artifacts/unsupervised_evidence_quality_fixed5_20260530.json`

Script:

- `tools/scripts/diagnose_unsupervised_evidence_quality_fixed5_20260530.py`

## Top Features

The fixed5 measurement path now builds production-like `ML02_top_feature_*` details
from deterministic VAE reconstruction top-k features instead of the Stage7 dummy
details path.

Aggregate result:

| Metric | Count |
|---|---:|
| top_features_available_case_count | 51,717 |
| top_features_available_truth_docs | 483 |
| top_feature_evidence_added_truth_docs | 483 |
| top_features_available_top100_truth_docs | 5 |
| top_features_available_top500_truth_docs | 39 |

Top feature category distribution is aggregate-only. Raw document IDs, row IDs,
index labels, phase2 case IDs, and raw feature-row identifiers are not emitted.

## Companion Surface

| Surface | TOP100 | TOP500 | TOP10000 | TOP500 repeated-normal pressure |
|---|---:|---:|---:|---:|
| native_row_queue | 5 | 39 | 289 | 0.716 |
| document_score_with_row_count_penalty | 22 | 100 | 408 | 0.462 |
| hybrid_with_soft_repeated_normal_guard | 25 | 151 | 483 | 0.256 |
| soft_guard_with_row_count_context | 32 | 174 | 483 | 0.282 |
| hybrid_row_count_blended_surface_upper_bound | 61 | 263 | 483 | 0.382 |
| soft_guard_pressure_guard_surface | 3 | 22 | 365 | 0.000 |

The pressure guard lowers repeated-normal pressure but loses too much TOP500
coverage, so it is not an adoption candidate.

## q95 Backlog

q95 miss truth docs are not promoted to cases.

| Metric | Count |
|---|---:|
| q95_miss_truth_docs | 137 |
| near_q95_truth_docs | 64 |
| strong_document_context_truth_docs | 25 |
| near_q95_with_top_features_truth_docs | 0 |

The backlog is a future validation candidate list only. It is not a q95 gate
change recommendation.

## Decision

- `production_top_features_connected=true`
- `evidence_quality_improved=true`
- `best_defensive_companion_surface=hybrid_with_soft_repeated_normal_guard`
- `best_upper_bound_surface=hybrid_row_count_blended_surface_upper_bound`
- `production_adoption=false` in this historical Phase 6 slice artifact
- `q95_gate_change_recommended=false`

Reason: top_features improve evidence quality, but document companion adoption
still requires cross-batch pressure and review-burden validation. The aggressive
hybrid surface remains an upper-bound benchmark only.

## Phase 6 Slice Stability

Artifact:

- `artifacts/unsupervised_soft_guard_stability_fixed5_20260530.json`

Validation scope:

- Primary dataset: `fixed5_normalcal5`
- Excluded dataset: `fixed4` because it is known-broken DataSynth for this validation
- Slices: fixed5 year, quarter, month, business-process bucket, GL-account bucket

Surface stability:

| Surface | slices | current-or-better TOP500 | pressure below native | pressure <= 0.30 | best TOP500 | worst pressure |
|---|---:|---:|---:|---:|---:|---:|
| native_row_queue | 74 | 74 | 74 | 2 | 110 | 1.000 |
| hybrid_with_soft_repeated_normal_guard | 74 | 74 | 65 | 3 | 150 | 1.000 |
| soft_guard_with_row_count_context | 74 | 74 | 63 | 3 | 200 | 1.000 |
| hybrid_row_count_blended_surface_upper_bound | 74 | 74 | 48 | 0 | 246 | 1.000 |
| pressure_guard_surface | 74 | 54 | 74 | 31 | 91 | 1.000 |

Interpretation:

- Soft guard is stable on TOP500 uplift against native row queue across fixed5-compatible
  slices.
- Repeated-normal pressure is not stable enough for product default adoption because
  many small/contextual slices exceed the 0.30 pressure ceiling.
- `soft_guard_with_row_count_context` is a secondary surface: better recall, slightly
  weaker pressure profile.
- Upper-bound hybrid remains non-adoptable.
- Pressure guard is rejected as a default candidate because recall drops too far.

q95 backlog slice stability:

- q95 backlog concentration: `0.1314`
- max q95 miss in a slice: `90`
- max near-q95 in a slice: `33`
- max strong-context q95 backlog in a slice: `14`
- `q95_gate_change_recommended=false`

Decision:

- `adoption_candidate=true` for soft guard as a review-surface candidate
- `production_adoption=true` for the VAE family-list display ordering
- q95 gate, VAE score/threshold, case generation, PHASE1 ranking, and PHASE2
  fusion remain unchanged

## V3.1 Owner-Role Surface Diagnostic

Artifact:

- `artifacts/unsupervised_v31_owner_surface_fixed5_20260531.json`

Script:

- `tools/scripts/diagnose_unsupervised_v31_owner_surface_fixed5_20260531.py`

The v3.1 responsibility map historically split unsupervised evaluation into:

- debug statistical denominator: 168 `fictitious_entry` truth documents
- companion: 339 truth documents where VAE supplies anomaly context but is not the primary owner

Surface results:

| Role | Surface | TOP100 | TOP500 | TOP10000 | TOP500 repeated-normal pressure |
|---|---|---:|---:|---:|---:|
| debug statistical denominator | native_row_queue | 12 | 23 | 111 | 0.818 |
| debug statistical denominator | hybrid_with_soft_repeated_normal_guard | 24 | 110 | 140 | 0.336 |
| debug statistical denominator | soft_guard_context_top100_probe | 31 | 110 | 140 | 0.336 |
| debug statistical denominator | soft_guard_with_row_count_context | 31 | 114 | 140 | 0.400 |
| companion | native_row_queue | 0 | 34 | 225 | 0.796 |
| companion | hybrid_with_soft_repeated_normal_guard | 1 | 33 | 275 | 0.478 |
| companion | hybrid_row_count_blended_surface_upper_bound | 1 | 135 | 275 | 0.634 |

TOP500 PHASE1 action-tier outside counts:

| Role | Surface | matched | outside immediate | outside review-or-above | outside candidate-or-above |
|---|---|---:|---:|---:|---:|
| debug statistical denominator | native_row_queue | 23 | 23 | 15 | 15 |
| debug statistical denominator | hybrid_with_soft_repeated_normal_guard | 110 | 110 | 74 | 73 |
| companion | native_row_queue | 34 | 34 | 33 | 28 |
| companion | hybrid_with_soft_repeated_normal_guard | 33 | 33 | 32 | 25 |

Interpretation:

- Soft guard materially improves the historical v3.1 debug-denominator TOP500 coverage: 23 -> 110.
- Debug-denominator TOP100 also improves from 12 -> 24.
- TOP100 residual gap is rank-band separation, not pure candidate absence:
  soft guard has 86 additional primary targets in rank101-500.
- `soft_guard_context_top100_probe` is bounded diagnostic-only: TOP100 24 -> 31,
  TOP500 unchanged at 110, repeated-normal pressure unchanged at 0.336.
- Companion TOP500 does not improve: 34 -> 33. The companion benefit is mainly deeper than TOP500.
- The surface is adopted as the default VAE family-list display ordering because
  it improves broad statistical review contribution and reduces repeated-normal
  pressure while keeping a single UI list. It is not a fraud primary recall
  family target.
- This is an ordering-only change. It does not change q95 gate, VAE
  score/threshold, case generation, PHASE1 ranking, or PHASE2 fusion.
- `top_features` remain explanation evidence and are not ranking inputs.

Monitoring guardrails:

- repeated-normal pressure requires monitoring
- period-end normal background requires monitoring
- account/process concentration requires monitoring
- single-row high amount normal proxy requires monitoring
- companion TOP500 does not improve

## V3.1 Next-Improvement Follow-Up - 2026-05-31

Artifact:

- `artifacts/unsupervised_v31_improvement_options_20260531.json`

The current product default remains `hybrid_with_soft_repeated_normal_guard`. A small non-upper-bound lift exists, but it is not enough to replace the default:

| Surface | Debug denominator TOP100 | Debug denominator TOP500 | TOP500 repeated-normal pressure |
|---|---:|---:|---:|
| adopted soft guard | 24 | 110 | 0.336 |
| soft guard + row-count context | 31 | 114 | 0.400 |
| hybrid upper-bound | 59 | 112 | 0.682 |

Decision: keep the single VAE family list on the adopted soft guard. The row-count context candidate adds only TOP100 +7 and TOP500 +4 while increasing repeated-normal pressure. The upper-bound improves TOP100 but is too pressure-heavy for product default.

Next improvement class: pressure-stable review contribution and explainability. Any next experiment must start from the adopted soft guard and improve broad statistical review contribution without raising TOP500 repeated-normal pressure above 0.336. Do not use PHASE1 prior, truth/owner/scenario metadata, q95 near-miss promotion, top_features, DataSynth score fitting, or threshold/weight recall fitting as ranking inputs.

## V3.2d Exact Owner-Role Surface Diagnostic - 2026-05-31

Artifact:

- `artifacts/unsupervised_v32_exact_owner_surface_fixed5_20260531.json`

Script:

- `tools/scripts/diagnose_unsupervised_v32_exact_owner_surface_fixed5_20260531.py`

The v3.2d responsibility map locks suspense as PHASE1 primary and keeps the
`fictitious_existence_statistical` subset as a VAE debug statistical denominator. This diagnostic uses
exact matched-document joins against the v3.2d owner metadata. Scenario-level
proration is retained only as a historical estimate and is not the official VAE
product recall.

Denominators:

| Role | truth docs | PHASE1 immediate covered | PHASE1 review+ covered | PHASE1 candidate+ covered |
|---|---:|---:|---:|---:|
| debug statistical denominator | 49 | 0 | 9 | 9 |
| companion | 395 | 0 | 41 | 70 |

Debug-denominator exact measurement:

| Surface | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 repeated-normal pressure |
|---|---:|---:|---:|---:|---:|
| native_row_queue | 0 / 49 | 0 / 49 | 0 / 49 | 1 / 49 | 1.000 |
| hybrid_with_soft_repeated_normal_guard | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.244 |
| soft_guard_context_top100_probe | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.244 |
| soft_guard_with_row_count_context | 2 / 49 | 10 / 49 | 13 / 49 | 13 / 49 | 0.284 |
| hybrid_row_count_blended_surface_upper_bound | 7 / 49 | 13 / 49 | 13 / 49 | 13 / 49 | 0.746 |

Companion exact recall:

| Surface | TOP100 | TOP500 | TOP10000 | TOP500 repeated-normal pressure |
|---|---:|---:|---:|---:|
| native_row_queue | 3 / 395 | 4 / 395 | 91 / 395 | 0.992 |
| hybrid_with_soft_repeated_normal_guard | 16 / 395 | 55 / 395 | 277 / 395 | 0.182 |
| soft_guard_context_top100_probe | 16 / 395 | 55 / 395 | 277 / 395 | 0.182 |
| soft_guard_with_row_count_context | 16 / 395 | 65 / 395 | 277 / 395 | 0.202 |
| hybrid_row_count_blended_surface_upper_bound | 43 / 395 | 109 / 395 | 277 / 395 | 0.582 |

Decision:

- Keep the current single VAE family-list default:
  `hybrid_with_soft_repeated_normal_guard`.
- The bounded `soft_guard_context_top100_probe` does not improve exact debug-denominator
  TOP100/TOP500 over the adopted soft guard on the v3.2d journal. It remains
  diagnostic-only.
- `soft_guard_with_row_count_context` keeps debug-denominator TOP500 at 10 and raises
  repeated-normal pressure from 0.244 to 0.284, so it is not a default replacement.
- q95 gate, VAE score/threshold, case generation, PHASE1 ranking, and PHASE2
  fusion remain unchanged.

## V3.3b Exact Owner-Role Surface Diagnostic - 2026-06-01

Artifact:

- `artifacts/unsupervised_v33_exact_owner_surface_fixed5_20260531.json`

Script:

- `tools/scripts/diagnose_unsupervised_v33_exact_owner_surface_fixed5_20260531.py`

The v3.3b responsibility map keeps suspense as PHASE1 primary by evaluator
policy override and evaluates `fictitious_existence_statistical` as a VAE
debug statistical denominator. The diagnostic reads the v3.3b journal directly and uses exact
matched-document joins.

Denominators:

| Role | truth docs | PHASE1 immediate covered | PHASE1 review+ covered | PHASE1 candidate+ covered |
|---|---:|---:|---:|---:|
| debug statistical denominator | 40 | 0 | 10 | 10 |
| companion | 404 | 0 | 40 | 69 |

Debug-denominator exact measurement:

| Surface | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 repeated-normal pressure |
|---|---:|---:|---:|---:|---:|
| native_row_queue | 0 / 40 | 0 / 40 | 0 / 40 | 0 / 40 | 1.000 |
| hybrid_with_soft_repeated_normal_guard | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.242 |
| soft_guard_context_top100_probe | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.242 |
| soft_guard_with_row_count_context | 2 / 40 | 10 / 40 | 16 / 40 | 16 / 40 | 0.280 |
| v33_statistical_signal_probe | 0 / 40 | 0 / 40 | 1 / 40 | 16 / 40 | 0.586 |
| v33_pressure_capped_signal_probe | 0 / 40 | 1 / 40 | 2 / 40 | 16 / 40 | 0.218 |
| hybrid_row_count_blended_surface_upper_bound | 7 / 40 | 16 / 40 | 16 / 40 | 16 / 40 | 0.740 |

Capture-vs-miss split under the adopted soft guard:

- Captured in TOP500: 10 debug-denominator docs
- Missed from TOP500: 30 debug-denominator docs
- Of the missed set, only 6 docs have current VAE case records; 24 are outside
  the current generated case surface. This makes pure ordering changes
  insufficient.
- Captured docs have uniformly high VAE max score and strong amount-tail
  context, but the missed case-record subset has similar amount-tail and score
  levels. The residual gap is therefore not solved by a selector-safe
  amount-tail/account-process/document-shape reorder.

Decision:

- Keep the single VAE family-list default:
  `hybrid_with_soft_repeated_normal_guard`.
- `soft_guard_context_top100_probe`, `soft_guard_with_row_count_context`,
  `v33_statistical_signal_probe`, and `v33_pressure_capped_signal_probe` do not
  improve TOP100/TOP500 without either losing coverage or increasing pressure.
- Upper-bound hybrid remains non-adoptable because pressure is too high.
- q95 gate, VAE score/threshold, case generation, PHASE1 ranking, and PHASE2
  fusion remain unchanged.
- These debug counts do not make VAE/unsupervised a fraud primary recall family.
  Product judgment uses broad statistical review contribution, repeated-normal
  pressure, PHASE1 outside complement, and evidence explainability.

Next improvement class:

- VAE needs feature representation / signal separation work, not another
  ranking reorder. DataSynth follow-up should verify that VAE debug-denominator
  fictitious-existence cases have observable statistical signals beyond
  amount-tail, such as document-shape outlier, rare entity behavior, and
  account/process rarity. These must remain truth/evaluation sidecar metadata,
  not detector input shortcuts. Do not fit DataSynth generation, thresholds, or
  weights to recover these debug-denominator documents.
