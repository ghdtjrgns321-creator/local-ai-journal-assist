# DataSynth Duplicate Realism S1 - Task Checklist

## Progress Summary

0 / 22 implementation tasks complete (0%)

## Phase 1: Rust Contract Tests

- [ ] Add a test that `DuplicateConfig::default()` exposes explicit rates for vendor drift, account dispersion, reference contamination, and period overrun.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: `cargo test` fails before config fields exist and passes after implementation.
  - Size: S

- [ ] Add a test for vendor-code drift preserving pair traceability.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: original and duplicate share traceable economic counterparty metadata while journal-visible vendor code can differ.
  - Size: S

- [ ] Add a test for account dispersion.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: duplicate can move across configured account fields without losing original/duplicate pair metadata.
  - Size: S

- [ ] Add a test for invoice/reference contamination.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: duplicate reference can be blank/noisy/partial while sidecar metadata records original reference relationship.
  - Size: S

- [ ] Add a test for period-overrun duplicate date offsets.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: at least one duplicate variant can move beyond current short detector windows.
  - Size: S

## Phase 2: Generator Implementation

- [ ] Extend `DuplicateConfig` with realism variant knobs.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: default/minimal/high-variation constructors compile with explicit values.
  - Size: S

- [ ] Extend duplicate variant metadata.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: `DuplicateRecord` or equivalent metadata identifies variant class and changed fields.
  - Size: S

- [ ] Implement vendor-code drift mutation.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: test fixture shows changed vendor/customer code without detector-output input.
  - Size: M

- [ ] Implement account-dispersion mutation.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: test fixture shows changed account field with traceability preserved.
  - Size: M

- [ ] Implement invoice/reference contamination mutation.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: test fixture covers prefix/suffix/noisy/blank reference cases.
  - Size: M

- [ ] Implement period-overrun mutation.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: generated date offset can exceed current detector tolerance and remains plausible.
  - Size: M

- [ ] Preserve backward compatibility for records without the target fields.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs`
  - Acceptance: existing generic duplicate tests still pass.
  - Size: S

## Phase 3: Injector Wiring

- [ ] Wire new duplicate config defaults through `DataQualityConfig::default()`.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs`
  - Acceptance: default config compiles and tests can inspect new duplicate realism fields.
  - Size: S

- [ ] Wire minimal duplicate realism rates.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs`
  - Acceptance: `DataQualityConfig::minimal()` keeps low issue pressure while preserving non-zero realism coverage if policy requires it.
  - Size: S

- [ ] Wire high-variation duplicate realism rates.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs`
  - Acceptance: `DataQualityConfig::high_variation()` increases realism variant pressure without changing unrelated noise policy.
  - Size: S

- [ ] Add or verify stats/manifest support for duplicate variant counts.
  - File: `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs`
  - Acceptance: downstream manifest can report variant counts without journal-visible shortcut columns.
  - Size: M

## Phase 4: Regeneration And Remeasurement

- [ ] Run Rust formatting and tests.
  - File: `tools/datasynth/`
  - Acceptance: `cargo fmt`, `cargo test`, and targeted crate checks pass.
  - Size: M

- [ ] Regenerate the candidate DataSynth dataset through the existing workflow.
  - File: existing DataSynth generation scripts/configs
  - Acceptance: manifest and sidecars include duplicate variant traceability.
  - Size: L

- [ ] Rerun PHASE1 baselines.
  - File: existing PHASE1 measurement artifacts
  - Acceptance: rule hit and review queue deltas are summarized, not silently accepted.
  - Size: M

- [ ] Rerun PHASE2 family responsibility recall.
  - File: `tools/scripts/measure_phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.py` or successor
  - Acceptance: duplicate S0 KPI reports normal FP and recall band on the regenerated candidate.
  - Size: M

- [ ] Run ripple-search across old duplicate terms.
  - File: repository-wide docs/code/artifacts references
  - Acceptance: project docs/source/test-result references are classified as update, code change, or remeasurement-only.
  - Size: S

- [ ] Report S1 completion to supervisor and stop before S2.
  - File: `docs/debugging.md` and supervisor report
  - Acceptance: report includes regenerated baseline numbers, normal FP, recall band, and whether S2 may start.
  - Size: S

## Deployment Checklist

- [ ] No Python detector threshold/ranking/gate changes in S1.
- [ ] No Streamlit restart, cache cleanup, or server kill.
- [ ] No new package installation.
- [ ] No git write commands unless explicitly requested by the user.
- [ ] Korean docs remain UTF-8 and are not round-tripped through PowerShell output writers.
