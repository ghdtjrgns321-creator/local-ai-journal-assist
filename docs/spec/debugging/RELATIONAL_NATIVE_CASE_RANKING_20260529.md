# Relational native case ranking diagnostic - 2026-05-29

## Scope

This note records the fixed5 relational native case ranking diagnostics and the adopted product review-surface policy. The product default relational ordering is `structural_moderate_audit_then_business_lane_split_surface` with policy id `structural_moderate_audit_then_business_lane_split_v1`. PHASE1 priority/composite ordering, PHASE2 fusion, thresholds, and relational case gate were not changed.

## Baseline

- Relational native case count: 57,640
- Sub-rule case count: R05 44,404, R06 11,874, R01 646, R02 5, R03 278, R07 433
- Current TOP100 composition: R03 72, R07 28
- Current TOP500 composition: R03 211, R05 45, R06 160, R07 84
- Current matched truth documents: TOP100 5, TOP500 19, TOP1000 19, TOP10000 35
- First truth rank: 51

## R05/R06 Decomposition

| Rule | case_count | matched truth all cases | matched / 1000 cases | top subject share | top account share | rows p95 | docs p95 | high-volume nontruth share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| R05 | 44,404 | 126 | 2.84 | 0.12% | 1.50% | 2.0 | 2.0 | 32.52% |
| R06 | 11,874 | 70 | 5.90 | 1.89% | 1.36% | 42.0 | 24.0 | 9.90% |

R05 explosion is broad rare partner-account surface rather than repeated identical edge dominance. R06 has larger row/document support per evidence unit, so user-account context needs separate review burden measurement.

## Candidate Results

| Candidate | first truth rank | TOP100 | TOP500 | TOP1000 | TOP10000 | TOP500 R05/R06 share | TOP500 high-volume nontruth share |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | 51 | 5 | 19 | 19 | 35 | 41.0% | 9.8% |
| rare_edge_balanced_sampling_per_sub_rule | 7 | 6 | 27 | 57 | 179 | 39.6% | 10.8% |
| r03_r07_priority_first_surface | 51 | 5 | 33 | 35 | 50 | 0.0% | 10.0% |
| moderate_tail_only_surface_q95 | 2 | 8 | 98 | 143 | 157 | 0.0% | 9.4% |
| structural_moderate_tail_lane_split_surface | 4 | 7 | 41 | 131 | 172 | 0.0% | 10.4% |
| three_lane_structural_moderate_context_surface | 4 | 6 | 38 | 65 | 172 | 20.0% | 11.4% |
| structural_moderate_business_balanced_lane_split_surface | 10 | 12 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_moderate_audit_then_business_lane_split_surface | 2 | 51 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_moderate_capped_context_lane_split_surface | 2 | 51 | 92 | 141 | 172 | 0.0% | 10.2% |
| structural_anchor_moderate_1_to_4_surface | 2 | 59 | 100 | 141 | 172 | 0.0% | 10.0% |
| sub_rule_balanced_review_surface | 32 | 3 | 19 | 36 | 60 | 50.0% | 10.0% |
| account_partner_context_surface | 16 | 2 | 12 | 12 | 37 | 57.8% | 9.8% |

The moderate tail surface has the largest fixed5 aggregate improvement, but it concentrates R01/R02 moderate review candidates at the top. That is not enough for production adoption without cross-batch validation and semantic review of false-positive pressure.

## Moderate Tail Decomposition

- q95 tail case count: 651, split R01 646 and R02 5.
- q99 tail case count: 648, split R01 643 and R02 5.
- q95 TOP500 split: R01 496 and R02 4.
- q95 TOP500 matched truth documents: 98.
- q95 TOP500 review burden: 48 truth-case evidence units and 452 nontruth-case evidence units, or 10.42 cases per matched case.
- q95 TOP500 scenario mix: approval_sod_bypass 6, embezzlement_concealment 43, expense_capitalization 21, fictitious_entry 16, suspense_account_abuse 12.

The lane split surface lowers R01/R02 dominance while keeping a material lift over current. It is a stronger diagnostic surface than moderate-only for audit review ergonomics, and fixed4 below checks whether that direction survives outside fixed5.

The adopted product default is `structural_moderate_audit_then_business_lane_split_surface`: it keeps the R03/R07 structural lane visible, uses audit-context buckets for the top prefix, then balances the R01/R02 moderate tail by `business_process`. This raises fixed5 TOP100 from 5 to 51 and TOP500 from 19 to 92 without passing truth labels into the selector.

The highest aggregate diagnostic candidate is now `structural_anchor_moderate_1_to_4_surface`: it keeps R03/R07 as an anchor rather than a 1:1 lane. Fixed5 TOP100/TOP500 rises to 59/100 and fixed4 TOP100/TOP500 rises to 58/105. R03/R07 drops to about 20% of TOP500, so this is a semantic tradeoff rather than an automatic production policy.

## PHASE1 Incremental Coverage

The latest diagnostic adds PHASE1 incremental coverage. PHASE1 baseline uses the document set referenced by PHASE1 detector flagged rows. PHASE1 TOP-N sets use a read-only detector score proxy and do not change PHASE1 priority/composite ordering.

| Baseline | review docs | matched truth docs |
|---|---:|---:|
| PHASE1 all flagged docs | 124,710 | 620 |
| PHASE1 TOP100 score-proxy docs | 65 | 3 |
| PHASE1 TOP500 score-proxy docs | 325 | 15 |
| PHASE1 TOP1000 score-proxy docs | 639 | 41 |
| PHASE1 TOP10000 score-proxy docs | 5,463 | 429 |

TOP500 incremental snapshot:

| Surface | matched | PHASE1 overlap | PHASE1 missed | incremental vs PHASE1 TOP500 |
|---|---:|---:|---:|---:|
| current | 19 | 19 | 0 | 19 |
| R03/R07 structural-only | 33 | 33 | 0 | 33 |
| R01/R02 moderate-tail | 98 | 98 | 0 | 95 |
| R05/R06 context lane | 2 | 2 | 0 | 2 |
| structural_moderate_audit_then_business_lane_split_surface | 92 | 92 | 0 | 89 |
| structural_anchor_moderate_1_to_4_surface | 100 | 100 | 0 | 97 |

PHASE1 all 620/620 is treated only as broad review-universe inclusion. It is not evidence that PHASE1 supplied the relational evidence unit or the scenario-level explanation.

| Surface | TOP500 matched | not in PHASE1 TOP500 | net uplift vs PHASE1 TOP500 | structural evidence docs | moderate-tail evidence docs |
|---|---:|---:|---:|---:|---:|
| current | 19 | 19 | 4 | 17 | 0 |
| R03/R07 structural-only | 33 | 33 | 18 | 33 | 0 |
| R01/R02 moderate-tail | 98 | 95 | 83 | 0 | 98 |
| R05/R06 context lane | 2 | 2 | -13 | 0 | 0 |
| structural_moderate_audit_then_business_lane_split_surface | 92 | 89 | 77 | 16 | 76 |
| structural_anchor_moderate_1_to_4_surface | 100 | 97 | 85 | 5 | 95 |

Historical v3.1 result: `audit_then_business` had high PHASE1 TOP-N uplift and high relational evidence/explanation incremental. Under that responsibility map, relational primary was the 34 circular related-party documents where IC and relational were co-primary; 9 were matched by native TOP500. This is retained only as history. The current v3.2d map has no relationship-primary denominator, so this v3.1 primary recall is not the current product conclusion.

## Fixed4 Cross-Batch Snapshot

| Candidate | TOP100 | TOP500 | TOP1000 | TOP500 sub_rule 구성 |
|---|---:|---:|---:|---|
| current | 6 | 17 | 17 | R03 310, R06 105, R07 85 |
| r03_r07_priority_first_surface | 6 | 17 | 33 | R03 332, R07 168 |
| moderate_tail_only_surface_q95 | 18 | 107 | 140 | R01 496, R02 4 |
| structural_moderate_tail_lane_split_surface | 11 | 42 | 124 | R01 248, R02 2, R03 197, R07 53 |
| three_lane_structural_moderate_context_surface | 10 | 40 | 116 | R01 198, R02 2, R03 157, R06 100, R07 43 |
| structural_moderate_business_balanced_lane_split_surface | 17 | 90 | 124 | R01 247, R02 3, R03 197, R07 53 |
| structural_moderate_audit_then_business_lane_split_surface | 51 | 89 | 124 | R01 245, R02 5, R03 197, R07 53 |
| structural_anchor_moderate_1_to_4_surface | 58 | 105 | 140 | R01 395, R02 5, R03 78, R07 22 |

Fixed4 preserves the direction: moderate-only produces the largest TOP500 lift but is R01/R02-dominant, and the structural/moderate audit-then-business lane split remains materially above current while retaining R03/R07 structural evidence. The fixed4 q95 moderate TOP500 burden is 50 truth-case evidence units and 450 nontruth-case evidence units.

## Year Split Validation

| Dataset | Year | current TOP100 | candidate TOP100 | current TOP500 | candidate TOP500 |
|---|---:|---:|---:|---:|---:|
| fixed5 | 2022 | 2 | 52 | 2 | 80 |
| fixed5 | 2023 | 2 | 20 | 3 | 29 |
| fixed5 | 2024 | 8 | 18 | 11 | 31 |
| fixed4 | 2022 | 2 | 51 | 2 | 79 |
| fixed4 | 2023 | 2 | 20 | 2 | 29 |
| fixed4 | 2024 | 6 | 16 | 8 | 29 |

The candidate direction survives both fixed5/fixed4 and 2022/2023/2024 splits. This supports the adopted relational review-surface policy while keeping PHASE1 priority/composite ordering, PHASE2 fusion, and relational gate unchanged.

## Review Burden Cap Stress Test

Applied scenario-agnostic caps to the R01/R02 moderate tail before lane splitting:

- max cases per `business_process` bucket: 90
- max cases per `document_count_bucket`: 220

The capped candidate produced the same TOP-N result as audit-then-business:

| Dataset | TOP100 | TOP500 | TOP1000 |
|---|---:|---:|---:|
| fixed5 | 51 | 92 | 141 |
| fixed4 | 51 | 89 | 124 |

This iteration adds stability evidence rather than a better surface. The cap did not expose additional lift, so the product default remains `structural_moderate_audit_then_business_lane_split_surface`.

## Structural Anchor Ratio Stress

Increasing moderate exposure while keeping a structural anchor improved aggregate results:

| Candidate | fixed5 TOP100 | fixed5 TOP500 | fixed4 TOP100 | fixed4 TOP500 | TOP500 semantic note |
|---|---:|---:|---:|---:|---|
| audit-then-business 1:1 | 51 | 92 | 51 | 89 | R03/R07 remains near half until structural lane exhausts |
| anchor 1:2 | 52 | 98 | 58 | 94 | R03/R07 still material |
| anchor 1:3 | 59 | 100 | 58 | 98 | R03/R07 about 25% |
| anchor 1:4 | 59 | 100 | 58 | 105 | R03/R07 about 20% |

The 1:4 anchor candidate is the strongest aggregate diagnostic result so far, but it is not adopted. It remains a diagnostic-only upper-bound because the 1:4 ratio has fixed5 metric-selection smell and reduces the structural-signal share.

## No-Fitting And Leak Guard

- Truth labels are not selector/scoring inputs.
- Truth labels are used only for aggregate evaluation after ordering.
- Diagnostic candidate provenance is fixed5 exploratory diagnostic weights, not calibrated, and not product policy. The adopted product policy is the 1:1 audit-then-business surface above.
- Raw leak self-report for both diagnostic artifacts: `doc_like_token_count=0`, `forbidden_identifier_key_count=0`, `phase2_case_id_like_token_count=0`, `raw_edge_like_token_count=0`.

## Next Iteration Prompt

Next possible check is R05/R06 context rescue as a separate lane, not mixed into the primary product top surface. Keep raw identifiers out of artifacts and keep PHASE1 priority/composite ordering, PHASE2 fusion, and relational gate unchanged.

## V3.1 Owned-Recall Follow-Up - 2026-05-31

Artifact:

- `artifacts/relational_v31_improvement_options_20260531.json`

Under the v3.1 responsibility map, relational primary means the 34 circular related-party documents where IC and relational are co-primary. The adopted relational surface still matches 9 / 34 at TOP500. Existing diagnostic surfaces do not materially improve that primary recall:

| Surface | TOP500 circular primary docs | TOP500 total truth docs | Note |
|---|---:|---:|---|
| current native | 9 | 19 | R03/R05/R06/R07 strong surface |
| adopted audit-then-business | 9 | 92 | best product relationship-evidence surface |
| account-partner context | 10 | 12 | best circular primary count, but low total coverage and high R05/R06 context share |
| structural anchor 1:4 | 4 | 100 | total truth upper-bound, not circular-primary improvement |

Conclusion: relational owned recall is low because the v3.1 primary denominator is circular co-primary, while the adopted relational product surface is a broader relationship-evidence companion. Changing the product default now is not supported; the best observed circular-primary lift is only 9 -> 10 / 34 and comes from a context-heavy surface.

Next improvement class: diagnostic-only IC-relational bridge analysis. For the 34 circular co-primary documents, compare aggregate IC reciprocal evidence presence with relational R03/R07 edge evidence presence, then identify which observable fields are missing from relational edge construction. Do not use owner/truth metadata as a selector.

## V3.2d Companion Contribution - 2026-05-31

Artifact:

- `artifacts/relational_v32_companion_contribution_20260531.json`

Under the v3.2d responsibility map, relational no longer has a primary denominator in fixed5. The lane is measured as `relationship_companion=139`, split into IC circular 34, approval/SOD 29, and embezzlement 76. The adopted product surface remains `structural_moderate_audit_then_business_lane_split_surface`; no production ordering, gate, PHASE1 ranking, or PHASE2 fusion changed in this diagnostic.

Adopted surface companion recall:

| TOP-N | Companion matched / 139 | Approval/SOD | IC circular | Embezzlement | All truth docs on surface |
|---|---:|---:|---:|---:|---:|
| TOP100 | 7 / 139 | 6 | 0 | 1 | 51 |
| TOP500 | 33 / 139 | 7 | 9 | 17 | 92 |
| TOP1000 | 81 / 139 | 7 | 9 | 65 | 141 |

Native/current companion baseline from the older native diagnostic is TOP100 5 / 139 and TOP500 17 / 139; TOP1000 scenario breakdown is not available in that artifact. The adopted surface therefore improves companion evidence placement without reclassifying relational as a primary family.

Rule mix for the adopted surface:

| TOP-N | R03/R07 structural | R01/R02 moderate | R05/R06 context |
|---|---:|---:|---:|
| TOP100 | 50 | 50 | 0 |
| TOP500 | 250 | 250 | 0 |
| TOP1000 | 500 | 500 | 0 |

R05/R06 still dominate raw relational volume (`R05=44,404`, `R06=11,874`, about 97.6% of all relational cases), but the adopted companion surface keeps their TOP500 share at 0.0. They remain context/export burden lanes rather than the primary review surface.

Interpretation: relational remains an active relationship review surface. The v3.2d companion metric is only an interim measurement while relationship-primary/co-primary denominator metadata is unavailable. Primary/co-primary recall tuning resumes once DataSynth provides that denominator.

## V3.3b Exact Primary Measurement - 2026-05-31

Artifact:

- `artifacts/relational_v33_exact_primary_measurement_20260531.json`

Under the v3.3b responsibility map, relational primary is the 20
`employee_vendor_hidden_relationship` documents. The measurement rebuilds
relational cases from the v3.3b journal, then performs an in-memory exact
matched-document join. Owner metadata is used only as the denominator and
evaluation set; detector scoring, case generation, ordering, PHASE1 ranking,
and PHASE2 fusion are unchanged.

| Surface | TOP100 primary / 20 | TOP500 primary / 20 | TOP1000 primary / 20 | TOP500 companion / 119 |
|---|---:|---:|---:|---:|
| current native order | 0 | 0 | 0 | 3 |
| adopted audit-then-business | 0 | 13 | 20 | 21 |

The exact join replaces the earlier scenario-level proration estimate of
2 / 20. It shows that the adopted relational review surface is materially
better for relationship-primary owner docs than native order, but the lift is
rank-band dependent: the primary owner set appears by TOP1000, not TOP100.

Runtime was 42.443 seconds, so no bounded/cached fallback was used. Raw leak
self-report remains 0 / 0 / 0 / 0.

## V3.3b TOP100 Diagnostic Candidate - 2026-06-01

The v3.3b exact artifact now also records a TOP100 diagnostic-only surface:
`employee_vendor_observable_profile_surface`.

| Surface | TOP100 primary / 20 | TOP500 primary / 20 | TOP1000 primary / 20 | TOP500 companion / 119 | TOP500 R05/R06 pressure |
|---|---:|---:|---:|---:|---:|
| current native order | 0 | 0 | 0 | 3 | 421 |
| adopted audit-then-business | 0 | 13 | 20 | 21 | 0 |
| employee-vendor observable profile | 20 | 20 | 20 | 16 | 372 |

Rank-band decomposition explains the problem:

| Surface | TOP100 | Rank 101-500 | Rank 501-1000 | >1000 |
|---|---:|---:|---:|---:|
| current native order | 0 | 0 | 0 | 20 |
| adopted audit-then-business | 0 | 13 | 7 | 0 |
| employee-vendor observable profile | 20 | 0 | 0 | 0 |

The diagnostic candidate uses observable GL case context only:
reference/counterparty employee-vendor token presence, business-process bucket,
account class, document support count, sub-rule, evidence tier, and family score.
It does not use truth label, scenario label, owner metadata, PHASE1 rank, or
matched result as selector inputs.

It is not adopted as the product default. The reason is not recall: TOP100 reaches
20 / 20. The blocker is audit stability. Fixed5 v3.3b encodes employee-vendor
semantics with recognizable synthetic reference/counterparty tokens, and the
candidate brings heavy R05 context pressure into TOP500. Product adoption requires
non-synthetic or regenerated validation showing that the employee-vendor profile
is a stable audit-observable signal rather than a DataSynth token shortcut.
