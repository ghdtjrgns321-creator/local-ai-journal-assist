# Timeseries Phase 5 Primary Surface Diagnostic - 2026-05-30

## Scope

This note records the current iteration result for TS family Phase 5. `fixed4` is treated as a known-broken DataSynth baseline and is excluded from product adoption decisions. The primary validation source is `fixed5_normalcal5`.

Production gates, detector thresholds, PHASE1 ranking, PHASE2 family fusion, Noisy-OR, and RRF were not changed. Truth labels and scenario labels are used only after policy ordering for aggregate evaluation.

## Validation Source

| Field | Value |
|---|---|
| primary_validation_dataset | `fixed5_normalcal5` |
| excluded_validation_datasets | `["fixed4"]` |
| exclusion_reason | `known-broken DataSynth baseline; not used for product adoption` |

The fixed5-compatible stability checks are year, quarter, and business_process slices.

## Surfaces

The diagnostic separates broad companion/export from TS-primary candidates.

| Surface | Role |
|---|---|
| `current_native_ts_order` | Current native TS order reference |
| `broad_companion_reference_surface` | Broad TS-derived export/companion reference, not TS-primary |
| `timing_primary_context_surface` | TS-primary candidate using period-end context, support, robust_z, context evidence, lift, and round/extreme amount demotion |
| `supported_period_end_anomaly_surface` | TS-primary candidate that keeps supported period-end anomaly windows |
| `ts_primary_conservative_surface` | Lower-burden TS-primary candidate prioritizing support and non-round timing context |

## Fixed5 Results

TS-aligned scenarios are `period_end_adjustment_manipulation` and `unusual_timing_manipulation`.

| Surface | TOP100 TS-aligned outside PHASE1 TOP100 | TOP500 TS-aligned outside PHASE1 TOP100 | TOP100 truth outside PHASE1 TOP100 | TOP500 truth outside PHASE1 TOP100 | TOP500 burden | low support ratio |
|---|---:|---:|---:|---:|---:|---:|
| current native TS order | 0 | 0 | 0 | 0 | 0.2584 | 0.876 |
| broad companion reference | 2 | 32 | 108 | 170 | 0.4675 | 0.118 |
| timing primary context | 0 | 32 | 0 | 32 | 0.4689 | 0.000 |
| supported period-end anomaly | 0 | 32 | 0 | 32 | 0.4689 | 0.000 |
| TS primary conservative | 13 | 32 | 13 | 32 | 0.4689 | 0.000 |

## Slice Stability

Year split for `ts_primary_conservative_surface`:

| Year | TOP100 TS-aligned outside PHASE1 TOP100 | TOP500 TS-aligned outside PHASE1 TOP100 |
|---|---:|---:|
| 2022 | 6 | 9 |
| 2023 | 18 | 18 |
| 2024 | 0 | 8 |

Decision-level stability:

| Surface | eligible slices | TOP100 eligible nonempty rate | TOP500 eligible nonempty rate | year TOP100 eligible nonempty rate |
|---|---:|---:|---:|---:|
| current native TS order | 8 | 0.00 | 0.00 | 0.00 |
| timing primary context | 8 | 0.75 | 1.00 | 0.67 |
| supported period-end anomaly | 8 | 0.75 | 1.00 | 0.67 |
| TS primary conservative | 8 | 0.75 | 1.00 | 0.67 |
| broad companion reference | 8 | 0.75 | 1.00 | 0.33 |

Interpretation:

- Fixed4 no longer blocks or supports product adoption.
- Fixed5 current native TS order contributes zero PHASE1-incremental TS-aligned evidence at TOP100/TOP500.
- TS-primary candidates provide stable TOP500 signal across eligible fixed5 slices.
- TOP100 remains slice-unstable because 2024 has zero TOP100 TS-aligned incremental evidence under the conservative candidate.
- Therefore TOP100 product default adoption is not allowed. TOP500 diagnostic companion role is allowed.
- Broad companion remains separate and must not be used as TS-primary default.

## Decision Payload

| Field | Value |
|---|---|
| best_ts_primary_candidate | `ts_primary_conservative_surface` |
| best_broad_companion_candidate | `broad_companion_reference_surface` |
| top100_adoption_allowed | false |
| top500_companion_allowed | true |
| production_adoption | false |
| recommended_product_role | diagnostic TOP500 companion candidate only |

Production adoption remains on hold because defaults require UI/export burden review and non-broken external fixture validation.
