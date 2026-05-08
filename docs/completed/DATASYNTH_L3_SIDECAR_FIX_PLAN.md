# DataSynth L3 Sidecar Fix Plan

Current baseline: `data/journal/primary/datasynth_v106_candidate`.

Note: v119 supersedes the v105 sidecar wording for L3-06 and L3-03 drilldowns. v106 still supersedes v105 for L3-11 cutoff truth.

Production baseline remains unchanged: `data/journal/primary/datasynth/`.

## Fixed Scope

This plan is limited to L3 sidecar consistency and explanatory context. It must not change detector code or redefine Phase 1 rule truth.

## Principles

- `rule_truth_L3_xx.csv` remains the strict Phase 1 rule contract.
- Sidecars explain construction, context, controls, or drill-down. They are not the primary precision/recall truth unless explicitly named as rule truth.
- Files named `normal_*` must not mean "not detected" when the rule is a broad review-population rule.
- When a sidecar is a context inside a review population, name or columns must say so.
- Candidate patches must start from the latest verified candidate only.

## Required Fixes

| Priority | Area | Problem | Required action |
|---:|---|---|---|
| 1 | L3-05 | `normal_weekend_context` can be stale after v104 calendar realism and the name can look like a negative-control file | Rebuild it from current `weekend_review_population`; keep only current weekend/holiday docs with normal context and add explicit `within_l305_review_population=True` |
| 2 | L3-06 | `normal_after_hours_context` overlaps L3-06 rule truth, which is correct but easy to misread | Add clearer alias `afterhours_normal_context_within_review_population*`; keep legacy file for compatibility |
| 3 | L3-04 | Large period-end/start review population lacks explanatory context | Add `period_end_normal_close_context*` and `period_end_priority_context*` |
| 4 | L3-02 | Manual/adjustment population is large and lacks normal/risky context split | Add `manual_entry_normal_context*`, `manual_override_confirmed_anomalies*`, and `manual_sensitive_account_context*` |
| 5 | L3-03 | IC population truth exists, but relation-specific drill-down sidecars are limited | Add `ic_unmatched_cases*`, `ic_amount_mismatch_cases*`, `ic_timing_gap_cases*`, and `transfer_pricing_review_cases*` if reconstructable from current fields |

## v105 Target

`v105_candidate` should be built from `v104_candidate`.

Expected characteristics:

- Journal rows are not mutated.
- Rule truth counts are unchanged.
- Existing required truth gate still returns `failures: []`.
- New sidecars are deterministic and derived only from current journal/truth fields.
- Legacy files may remain, but clearer aliases should be preferred in documentation.

## v105 Result

`v105_candidate` was built from `v104_candidate`.

Changed sidecars:

| Area | Sidecar | Count | Result |
|---|---|---:|---|
| L3-05 | `normal_weekend_context*` | 12,373 | Rebuilt from current `weekend_review_population`; no stale docs outside L3-05 truth |
| L3-05 | `weekend_normal_context_within_review_population*` | 12,373 | Clear alias for normal context inside L3-05 review population |
| L3-05 | `weekend_confirmed_anomalies*` | 29 | Rebuilt from current L3-05 truth plus `WeekendPosting` anomaly label |
| L3-06 | `afterhours_normal_context_within_review_population*` | 6,952 | Clean normal context inside L3-06 review population; anomaly-labeled docs removed in v119 |
| L3-06 | `afterhours_cross_rule_labeled_context*` | 20 | Cross-rule labeled after-hours context split out from normal context |
| L3-04 | `period_end_normal_close_context*` | 3,600 | Representative normal close context sample |
| L3-04 | `period_end_priority_context*` | 3,009 | Representative priority context sample |
| L3-02 | `manual_entry_normal_context*` | 3,600 | Representative normal manual/adjustment context sample |
| L3-02 | `manual_override_confirmed_anomalies*` | 3 | Confirmed `ManualOverride` subset inside L3-02 truth |
| L3-02 | `manual_sensitive_account_context*` | 389 | Manual/adjustment entries also touching L3-10 sensitive/high-risk accounts |
| L3-03 | `ic_unmatched_cases*` | 21 | IC unmatched drill-down subset |
| L3-03 | `ic_amount_mismatch_cases*` | 16 | IC amount mismatch drill-down subset |
| L3-03 | `ic_timing_gap_cases*` | 14 | IC timing gap drill-down subset |
| L3-03 | `transfer_pricing_review_cases*` | 13 | Transfer-pricing review drill-down subset |

Validation:

- Journal rows mutated: 0
- Rule truth mutated: 0
- Required truth gate: `failures: []`
- L3-02/L3-04/L3-05/L3-06/L3-11 document-level context sidecars are subsets of their target rule truth or review population where applicable.
- L3-03 IC exception files are case-level drilldowns linked by `target_document_id` and `counterpart_document_id`; they are not document-level subsets by a `document_id` column.
