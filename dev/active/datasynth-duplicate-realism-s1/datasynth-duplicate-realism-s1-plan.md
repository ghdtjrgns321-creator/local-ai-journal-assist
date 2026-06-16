# DataSynth Duplicate Realism S1 - Strategic Plan

## Executive Summary

S1 updates DataSynth duplicate generation realism before any duplicate detector ranking or routine-repeat suppression work. The goal is to make duplicate labels less aligned with current detector tolerance by adding vendor-code drift, account dispersion, invoice/reference contamination, and period-overrun variants while preserving traceable labels and equal data-quality noise policy across normal and abnormal records.

This is a plan only. Implementation starts after supervisor approval.

## Current State

Duplicate S0 locked the measurement posture: normal false-positive rate first, recall reported as n=19 confidence band. The current v33d duplicate TOP500 primary result is 8/19, but it must not be tuned directly.

Verified Rust locations:

- `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs:40` defines `DuplicateConfig`.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs:156` creates duplicate records.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs:231` applies near-duplicate field variations.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs:282` applies fuzzy variations.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs:24` defines `DataQualityConfig`.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs:88` and `:115` set minimal/high-variation duplicate rates.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs:601` exposes `should_duplicate`.

Current duplicate generation is generic and still too close to detector assumptions: ID changes are guaranteed, near duplicate varying fields are narrow, amount/date variation is bounded near current detection tolerance, and there is no explicit plan-level contract for vendor-code drift, account dispersion, contaminated invoice/reference, or period-overrun duplicates.

## Proposed Solution

Add a Rust-side duplicate realism layer that produces audit-plausible duplicate variants without changing Python detector thresholds.

Required scenario classes:

- Vendor-code drift: same economic counterparty with changed vendor/customer code, alias, or master-data merge/split symptom.
- Account dispersion: duplicate economic event posted across plausible expense/liability/suspense/clearing account variants.
- Invoice/reference contamination: missing prefix/suffix, OCR typo, delimiter changes, partial invoice reuse, blank or noisy payment reference.
- Period overrun: duplicate payment or posting outside current small date windows, including month/period boundary movement.

Required invariants:

- Label traceability remains complete: original/duplicate pair identity, semantic group, injected variant class, changed fields, and intended owner role must be recoverable from sidecar metadata.
- Data-quality noise such as missingness, typos, encoding, and format variation must be applied at equal rates to normal and abnormal records. Do not make noise a shortcut for duplicate labels.
- No truth labels, owner metadata, or sidecar probe fields are used by detector selectors, gates, rankings, thresholds, PHASE1 ranking, or PHASE2 fusion.
- S2 normal-repeat suppression remains blocked until S1 generation and baseline remeasurement are complete.

## Implementation Phases

### Phase 1: Rust Contract Tests (S)

Goal: Lock expected duplicate variant metadata before generator changes.

Tasks:

- Add Rust tests for `DuplicateConfig` variant knobs in `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`.
- Add Rust tests for vendor-code drift preserving economic counterparty traceability.
- Add Rust tests for account dispersion changing account fields without breaking debit/credit balance assumptions of the record type under test.
- Add Rust tests for invoice/reference contamination with original/duplicate pair metadata retained.
- Add Rust tests for period-overrun offsets beyond the current short detector window.

### Phase 2: Generator Realism (M)

Goal: Implement duplicate variants in the Rust generator.

Tasks:

- Extend `DuplicateConfig` with variant rates and max period-overrun days.
- Extend `DuplicateType` or add variant metadata so created duplicates expose semantic class.
- Update `create_duplicate()` to choose realism variants without detector output.
- Extend near/fuzzy variation helpers to support vendor/account/reference/period fields when present.
- Keep existing generic behavior backward compatible for records that do not expose those fields.

### Phase 3: Injector Wiring (S)

Goal: Make the realism knobs available through the data-quality injector.

Tasks:

- Wire new `DuplicateConfig` defaults through `DataQualityConfig::default`, `minimal`, and `high_variation`.
- Preserve current `with_duplicate_rate()` builder behavior.
- Add stats for each variant class or verify sidecar metadata is sufficient for downstream counts.

### Phase 4: DataSynth Regeneration And Baseline Remeasurement (L)

Goal: Produce a new candidate dataset and rerun baseline measurements before any detector change.

Tasks:

- Run relevant Cargo checks/tests in `tools/datasynth/`.
- Regenerate the fixed candidate dataset under the existing DataSynth workflow.
- Rerun PHASE1/PHASE2 baseline measurements, including duplicate S0 KPI.
- Compare normal FP rate, duplicate recall band, and family responsibility recall against v33d.
- Report to supervisor before S2 starts.

## Risk Assessment

- High Risk: New duplicate variants can become label leakage if sidecar fields appear in journal input. Mitigation: sidecar-only metadata, raw journal column leak check, and S0 no-selector-truth contract.
- High Risk: Account dispersion can create accounting-impossible records. Mitigation: Rust tests must check balance and account plausibility for supported record types.
- Medium Risk: Period-overrun duplicates may reduce current detector recall. Mitigation: expected and acceptable for realism; report as baseline drift, not a detector regression to tune immediately.
- Medium Risk: Data-quality noise can accidentally correlate with abnormal records. Mitigation: equal-rate noise policy test and manifest summary comparison.

## Success Metrics

- Rust duplicate generator tests pass.
- New dataset manifest reports duplicate variant counts and sidecar traceability.
- Normal and abnormal data-quality noise rates remain comparable by policy.
- Duplicate S0 KPI is remeasured after regeneration: normal FP rate plus n=19 or updated denominator recall band.
- No detector ranking, gate, threshold, PHASE1 ranking, or PHASE2 fusion changes occur in S1.

## Dependencies

- S0 measurement reframing complete.
- Existing DataSynth Rust generator under `tools/datasynth/`.
- Current duplicate detector artifact path remains read-only for comparison.
- Supervisor approval required before implementation.
