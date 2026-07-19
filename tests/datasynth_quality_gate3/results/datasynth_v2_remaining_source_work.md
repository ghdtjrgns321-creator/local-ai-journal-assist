# DataSynth V2 Remaining Source Work

Generated: 2026-05-14

## Current Candidate State

- `datasynth_contract_v2` master/document-flow coverage has been repaired at the dataset/materialization layer.
- `datasynth_manipulation_v2` is regenerated from the repaired contract base.
- Contract-only approval fixtures are neutralized in manipulation background unless the document is selected as manipulation truth.
- Manipulation truth documents now include substantive journal mutations for circular IC, fictitious revenue, and embezzlement/cash leakage scenarios.
- Latest full Phase1 runs completed without detector warnings for both contract and manipulation candidates.

## Remaining Source-Level Work

The following should be moved into Rust generation if `*_v2` is promoted from candidate scripts to repeatable generator modes:

1. Document-flow materialization
   - Source area: `tools/datasynth/crates/datasynth-runtime/src/enhanced_orchestrator.rs`
   - Relevant functions: `phase_document_flows`, `generate_document_flows`, `generate_jes_from_document_flows`
   - Required behavior: every generated JE reference with `PO/GR/VI/PAY/SO/CI/DLV-*` must be present in `DocumentFlowSnapshot` or referenced by `document_references`.

2. JE approval routing
   - Source area: `tools/datasynth/crates/datasynth-runtime/src/enhanced_orchestrator.rs`
   - Relevant area: approval/user repair logic near JE post-processing
   - Required behavior: normal entries should use known approvers with `can_approve_je=true`, company authorization, and sufficient approval limit. Contract fixtures must be explicit and bounded.

3. Contract vs manipulation fixture separation
   - Source area: generator mode/output selection rather than detector-side Python.
   - Required behavior: contract-only fixtures must not leak into manipulation background as unlabeled anomalies.

4. Manipulation truth substantive mutations
   - Source area: `tools/datasynth/crates/**` manipulation generation mode.
   - Required behavior: circular truth should emit IC GL/process/counterparty evidence; fictitious truth should emit DR 11xx / CR 4xxx revenue substance; embezzlement truth should emit cash/advance or duplicate-outflow substance with traceable provenance.

## Python Candidate Scripts Covering This Today

- `tools/scripts/repair_contract_v2_master_flow_coverage.py`
- `tools/scripts/refresh_contract_sidecar_truth.py`
- `tools/scripts/materialize_datasynth_manipulation_v2.py`

## Latest Verification

- Contract full Phase1 cache: `artifacts/phase1_contract_v2_final_candidate_20260514.pkl`
- Contract strict A-axis output: `tests/datasynth_quality_gate3/results/contract_v2_a_axis_strict_final_candidate.json`
  - rules checked: 34
  - false positive docs: 0
  - false negative docs: 0
- Manipulation full Phase1 cache: `artifacts/phase1_manipulation_v2_final_candidate_20260514.pkl`
- Manipulation case artifact: `artifacts/phase1_cases/_anonymous/phase1case__anonymous_datasynth_v126_profiled_phase1_20260514T091304Z.json`
- Manipulation topic/ranking report: `artifacts/manipulation_v2_final_label_signal_recovery.md`

The earlier circular expected-topic weakness is resolved in the candidate dataset by adding period-end circular adjustment evidence: L3-03 hits 34 / 34 circular truth documents and expected `intercompany_cycle` topic entry is 34 / 34.
