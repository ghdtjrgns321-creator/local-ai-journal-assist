# DataSynth Manipulation V6 Anti-Fitting Contract

## Purpose

V6 repairs the remaining manipulation dataset defects found after V5 fixed9 without fitting synthetic data to Phase2 model scores.

The V6 goal is not to make Phase2 perform poorly. The goal is to produce accounting-plausible normal and manipulated journals where obvious label leakage is absent, accounting substance is coherent, and any remaining Phase2 separation can be classified as either a legitimate scenario signal, a Phase2 feature-policy issue, or a true generator defect.

## Baseline

- Input dataset candidate: `data/journal/primary/datasynth_manipulation_v5_candidate_fixed9`
- Generator baseline: Rust `manipulation-v5` profile in `tools/datasynth/crates/datasynth-cli/src/manipulation_v5.rs`
- New output path: `data/journal/primary/datasynth_manipulation_v6_candidate`
- V5 fixed9 generation PASS checks must be preserved:
  - truth docs = 620
  - O2C customer invoice revenue missing docs = 0
  - P2P vendor invoice credit GR/IR rows = 0
  - self-approval rows with `sod_violation=false` = 0
  - zero amount filler rows = 0
  - CoA `15110` and `8030` present
  - mutation provenance missing counts = 0

## Non-Negotiable Anti-Fitting Rules

The following metrics are measurement-only and must not be used as generation targets:

- single-column AUROC
- two-feature AUROC
- simulated logistic AUROC
- ensemble AUPRC
- scenario recall, top-k capture, or review-queue capture
- exact Phase1 rule hit counts

Do not add, remove, or weaken a mutation solely because a metric is above or below a desired number. A generator change is allowed only when it has an accounting-domain reason:

- a normal population condition is plausible in real operations;
- a manipulated scenario is missing the accounting substance that defines it;
- a line, account, counterparty, document, or approval field contradicts the event it represents;
- a generated field is an obvious label shortcut rather than an operational fact.

If a high AUROC remains after accounting-valid generation, classify the cause instead of forcing the generator to hide it.

## V6 Work Items

### V6-A. Accounting Substance Fixes

These are hard generator requirements.

1. Register CoA `8010` as an expense account.
   - `account_type`: `expense`
   - `sub_type`: `repair_expense` or `maintenance_expense`
   - Scope: expense capitalization source expense account.

2. Preserve P2P vendor invoice AP logic.
   - In `P2P_VENDOR_INVOICE`, credit GR/IR must be 0 rows.
   - GR/IR belongs to goods receipt style events, not vendor invoice posting.

3. Strengthen line text to account/direction consistency.
   - Every generated or mutated line text must match the line's account class and debit/credit direction.
   - Example: a cash credit line should use cash payment/outflow language, not withholding-tax accrual language.
   - Applies to normal and manipulated rows.

4. Recheck manipulation scenario entries for accounting substance.
   - `circular_related_party_transaction`: round-trip pattern and IC GL prefix pairing must be coherent.
   - `expense_capitalization`: expense-to-asset reclassification must use a valid expense account and valid asset account.
   - `period_end_adjustment_manipulation`: accrual/reversal style entries must be directionally coherent.
   - `unusual_timing_manipulation`: abnormal timing may coexist with approval/process issues, but the underlying entry must still be a valid accounting event.

### V6-B. Natural Operational Noise Expansion

Normal population enrichment must be expanded only where operationally plausible. These are hard data-design requirements, but the resulting AUROC is measurement-only.

Add or verify natural normal-population occurrence for:

- approval contract gap
- approval matrix gap
- near-threshold amount
- legitimate backdating
- suspense account lifecycle usage
- intercompany transaction population
- intercompany master-counterparty evidence
- amount magnitude tail
- supply amount / invoice amount tail
- first-digit distribution variety
- approval lag distribution

Rules:

- Do not mark only manipulated truth documents with these enrichment fields.
- Do not create unlabeled confirmed violations in normal data.
- Normal noise must have a domain reason, such as late approval processing, master-data maintenance lag, close-period manual work, normal IC settlement, temporary suspense clearing, or high-value but legitimate transactions.
- Preserve the distinction between natural operational noise and intentional manipulation provenance.

### V6-C. Intentional Anachronism Preservation

Anachronism can be an intended manipulation/control-breakdown signal and must not be erased only to lower a model metric.

Required:

- Preserve approval-before-posting and late-approval manipulation signals where they are part of the scenario design.
- Add a natural normal approval-lag distribution so approval lag is not a trivial label proxy.
- Keep normal approval-before-posting at zero or minimal level unless a documented legitimate backdating case explains it.

Measurement:

- D1/D2 counts are measured against V4/V5 history, but they are not fitted to an exact count target.
- If D1/D2 become too predictive, classify whether the cause is legitimate scenario signal, Phase2 feature-policy issue, or generator leakage.

### V6-D. Phase2 Shortcut Audit Classification

Run the same Phase2 leakage and preflight checks used for V5, but classify every high-separation feature into one of four categories:

1. `GENERATOR_FIX_REQUIRED`
   - The field is an accidental label shortcut or impossible normal/mutated split.
   - Fix in Rust generator.

2. `PHASE2_FEATURE_POLICY`
   - The field is a Phase1/enrichment/review surface that should not be used directly by Phase2 training.
   - Fix by deny-list, feature role separation, or metadata-only routing.

3. `LEGITIMATE_SCENARIO_SIGNAL`
   - The field captures the intended accounting substance of the scenario.
   - Do not weaken the generator to hide the signal.

4. `REAL_DATA_REVALIDATION_REQUIRED`
   - Synthetic data cannot determine the correct production distribution.
   - Keep as a synthetic limitation and revalidate with real journal data.

The audit report must include this classification for high single-column AUROC, high two-feature AUROC, and high simulated logistic separability.

### V6-E. Generation PASS Preservation

V6 must preserve V5 fixed9 generation quality:

- no O2C customer invoice without revenue line;
- no P2P vendor invoice crediting GR/IR;
- no self-approval row with false SOD flag;
- no zero-amount filler line;
- CoA `15110`, `8030`, and `8010` present;
- truth docs = 620;
- 8 scenario truth mapping unchanged;
- mutation provenance complete.

## Acceptance Gates

### Hard Gates

V6 can be promoted only if all hard gates pass:

- generation/truth quality PASS;
- accounting logic audit HARD findings = 0;
- V5 fixed9 generation PASS checks preserved;
- no obvious label/provenance leakage columns in Phase2 training inputs;
- normal operational noise is documented with accounting-domain rationale;
- Phase2 shortcut audit classifies remaining high-separation features.

### Measurement-Only Metrics

The following must be reported but do not by themselves fail DataSynth:

- single-column AUROC counts;
- two-feature AUROC counts;
- simulated logistic AUROC;
- Stage 4 scenario detectability;
- Stage 5 rule-only circular learning;
- Stage 8 stacking ablation;
- top-k truth capture;
- exact D1/D2 counts.

If these metrics are high, the report must classify the cause using V6-D. Do not change generator distributions only to satisfy a numeric model threshold.

## Required Outputs

- `data/journal/primary/datasynth_manipulation_v6_candidate/`
- `MANIPULATION_V6_DATASET_MANIFEST.json`
  - V5 to V6 change summary
  - anti-fitting statement
  - accounting-domain rationale for normal operational noise
  - note that AUROC and AUPRC targets are measurement-only
- `tests/datasynth_quality_gate3/results/manipulation_v6_candidate_truth_check.json`
- `artifacts/datasynth_v6_quality_verification.md`
- `artifacts/datasynth_v6_accounting_logic_audit.md`
- `artifacts/datasynth_v6_phase2_cheat_route_audit.md`
- `artifacts/datasynth_v6_preflight_check.md`
- Optional supporting outputs:
  - `artifacts/S4_v6_scenario_detectability_data.json`
  - `artifacts/S5_v6_circular_learning_overlap.json`
  - `artifacts/S8_v6_stacking_oof_ablation.json`

## Stop Conditions

Stop and report instead of continuing generator fitting when:

- accounting substance is already valid but model separability remains high;
- a feature is inherently part of the manipulation scenario definition;
- lowering AUROC would require weakening a scenario's accounting meaning;
- a fix would create unnatural normal data or unlabeled confirmed violations.

In those cases, recommend a Phase2 feature-policy fix or real-data revalidation, not another DataSynth mutation pass.
