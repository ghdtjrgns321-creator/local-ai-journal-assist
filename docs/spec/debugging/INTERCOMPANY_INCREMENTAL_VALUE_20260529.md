# Intercompany Incremental Value Diagnostic - 2026-05-29

## Scope

This note records the fixed5 IC incremental-value diagnostic. It did not change IC detector thresholds, native case gates, PHASE1 ranking, PHASE2 fusion, Streamlit layout, or dashboard columns.

## Result

| Metric | Value |
|---|---:|
| Native case count | 246 |
| TOP100 circular truth documents | 34 |
| Circular scenario coverage | 34/34 |
| TOP100 net uplift vs PHASE1 | +34 |
| TOP500 net uplift vs PHASE1 | -16 |
| TOP1000 net uplift vs PHASE1 | -53 |
| Reciprocal evidence truth docs | 34 |
| Paired row_refs truth docs | 34 |
| Counterparty pair truth docs | 34 |
| Amount symmetry truth docs | 34 |
| Amount mismatch truth docs | 0 |

## Interpretation

IC is locked as `ic_specific_evidence_strengthening`. It is not a broad recall expansion family. The strong result is PHASE1 TOP100 uplift for circular/reciprocal IC review candidates plus IC-specific reciprocal/pair evidence. TOP500/TOP1000 net uplift is negative versus the PHASE1 broad TOP-N baseline, so IC should not be described as a global recall engine.

`production_adoption=false`, `production_ranking_changed=false`, and `new_policy_adopted=false` mean no new production ranking or gate policy was adopted. They do not mean the existing IC family is disabled.

## Data Path

`run_phase2_inference` attaches `PipelineResult.phase2_case_set`; `IntercompanyCase` remains in the existing native case set and is consumed by the current PHASE2 native case surface. The result also carries optional aggregate-only `phase2_family_policy_summary["intercompany"]` role metadata. That metadata is not a detector input and is not used for ranking or fusion.

## Guardrails

- Truth/scenario labels are used only after ordering for aggregate evaluation.
- Raw document id, row id, phase2 case id, and counterparty raw id are not emitted by the diagnostic artifact.
- Unmatched and timing-only IC signals remain excluded from native case promotion.
- Reports and UI language should say review candidate or evidence strengthening, not confirmed fraud.
