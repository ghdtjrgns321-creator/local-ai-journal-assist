# DataSynth Duplicate Realism S1 - Context & Decisions

## Status

- Phase: planning only
- Progress: 0 / 4 implementation phases complete
- Last Updated: 2026-06-01
- Checkpoint: S1 implementation must end with baseline remeasurement and supervisor report before S2 starts.

## Key Files

Modified in S0:

- `tools/scripts/measure_phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.py` - adds duplicate S0 operating KPI.
- `artifacts/phase2_family_responsibility_recall_v33d_fixed5_ownermeta_v33d_20260601.json` - stores normal FP and recall band.
- `tests/modules/test_services/test_duplicate_s0_measurement_reframe.py` - locks S0 KPI artifact contract.
- `docs/debugging.md` - records S0 diagnosis and verification.
- `docs/spec/DECISION.md` - records D070 measurement policy decision.

Planned for S1:

- `tools/datasynth/crates/datasynth-generators/src/data_quality/duplicates.rs` - duplicate type/config/variant generation.
- `tools/datasynth/crates/datasynth-generators/src/data_quality/injector.rs` - duplicate config wiring and stats.
- DataSynth manifest/sidecar outputs under the existing generator workflow - label traceability and variant counts.
- S1 tests under the Rust crate's existing test structure.

Non-scope until after S1:

- `src/detection/duplicate_pair_features.py:1398` `_common_features`.
- `src/detection/duplicate_pair_features.py:1441` `same_day_burst_group_size_max`.
- `src/detection/duplicate_pair_features.py:1442` `routine_repeat_candidate`.
- Any S2 tier/ranking linkage for routine-repeat suppression.

## Key Decisions

1. S1 changes DataSynth before detector ranking.
   - Rationale: changing detector ranking first would refit to the current clean synthetic duplicate shape.
   - Alternatives: tune duplicate top_pairs retention or add sidecar probes now.
   - Trade-offs: current 8/19 recall remains unsolved until data realism and baseline are remeasured.

2. Normal FP rate is the first operating KPI.
   - Rationale: S0 measured `normal_sample_300` native duplicate FP as 0/300 and duplicate recall as 8/19 with ±1 document = 5.3%p.
   - Alternatives: optimize TOP500 recall directly.
   - Trade-offs: small-n recall changes are reported as sensitivity, not a product win.

3. Duplicate sidecar traceability is required, but journal-visible shortcut fields are prohibited.
   - Rationale: labels must remain auditable, while detector inputs must stay clean.
   - Alternatives: expose generated variant fields in journal input.
   - Trade-offs: debugging requires sidecar/manifest joins, not direct journal columns.

4. Data-quality noise stays equal-rate across normal and abnormal records.
   - Rationale: CLAUDE.md DataSynth rule forbids MCAR/typo/format variance becoming a label shortcut.
   - Alternatives: add heavier noise only to duplicate anomalies.
   - Trade-offs: duplicate variants must be realistic through business fields, not artificial data-quality artifacts.

## Ripple Impact Summary

S1 implementation requires full downstream remeasurement because it changes generated data semantics, not just detector code.

Affected areas:

- DataSynth Rust generator and tests.
- DataSynth dataset manifest and label sidecars.
- PHASE1 detection baselines, because journal fields and sidecar semantics can alter rule hits.
- PHASE2 family responsibility recall artifact, including duplicate S0 KPI.
- Duplicate native case quality diagnostics and any documentation that cites fixed5/v33d duplicate counts.
- KPI guard/baseline JSON if regenerated data becomes the new candidate baseline.

Ripple-search terms to run after implementation:

- `duplicate_primary_target`
- `duplicate_semantic_group`
- `DuplicateConfig`
- `routine_repeat_candidate`
- `same_day_burst_group_size_max`
- `phase2_family_responsibility_recall_v33d`
- `normal_sample_300`
- `8/19`

## Known Issues

- `docs/TASKS.md` is absent in the current checkout. `docs/archive/completed/NEW_TASKS.MD` exists as historical RC material, so S1 planning used `CLAUDE.md`, `docs/debugging.md`, `docs/spec/DECISION.md`, and active PHASE2/debugging docs.
- `dev/README.md` is absent, so planner template was applied from the skill instructions and existing `dev/active/` convention.
- Existing `docs/spec/DECISION.md` contains older mojibake lines unrelated to this task. This plan does not rewrite them.
