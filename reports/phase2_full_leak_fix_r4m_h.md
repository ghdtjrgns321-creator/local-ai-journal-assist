# PHASE2 Full Leak Fix - v43d / r4m_h

Date: 2026-06-14

## Scope

- NORMAL base: `data/journal/primary/datasynth_semantic_v1_normal_20260614_v43d`
- PHASE2 overlay: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`
- Seed check: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h_seed1`
- Reference for S13 only: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`

## Fixes

- NORMAL L6/J09: added linked normal reversal background so `original_document_id` and `reversal_document_id` non-null surfaces are not PHASE2-only.
- NORMAL E05/I04: normalized direct SoD marker policy to `sod_violation=false` / blank `sod_conflict_type` for normal baseline, and regenerated document numbers as `company-year-document_type-sequence`.
- PHASE2 L4: dispersed trading partners by role-compatible normal partner pools; removed high-concentration `V-000001`-style surface.
- PHASE2 L5: inherited auxiliary invoice fields, supporting document metadata, and source/persona/counterparty surfaces from normal donors; H2R payroll events use payroll-compatible support evidence.
- PHASE2 L7: removed exact repeated amount/time fingerprints by deterministic non-round variation and document/account/role-aware timestamp dispersion.

## NORMAL Verification

`uv run python tools/scripts/normal_data_realism_verifier_20260603.py data/journal/primary/datasynth_semantic_v1_normal_20260614_v43d --json-out reports/normal_realism_v43d_full_leak_fix.json --md-out reports/normal_realism_v43d_full_leak_fix.md`

- Summary: `PASS 33`, `MONITOR 1`, `FAIL 0`, `INFO 3`.
- Documents: `327,767`; rows: `997,980`.
- E05 direct SoD marker: `sod_violation_true_docs=0`, `sod_conflict_type_nonblank_docs=0`.
- I01/I03/I04 document/reference structure: duplicate document numbers `0`, bad number format `0`, same-role duplicate reference groups `0`.
- J04/J07 reversal links: linked reversal docs `1,300`, checked pairs `1,300`, unlinked `0`, bad pair net `0`.

`uv run python tools/scripts/audit_balance_integrity.py data/journal/primary/datasynth_semantic_v1_normal_20260614_v43d`

- TB to JE: PASS, mismatches `0`.
- Balance sheet equation: PASS, bad periods `0`.
- Year carry-forward: PASS, mismatches `0`.
- Subledger reconciliation: PASS, differences `0`.

## PHASE2 Representative Verification

`uv run python tools/scripts/phase2_shortcut_gate.py data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`

- Result: `17/17 PASS`, `FAIL 0`.
- Population: `328,097`; fraud documents: `330`; base rate `0.1006%`.

`uv run python tools/scripts/verify_phase2_regression.py data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h data/journal/primary/datasynth_semantic_v1_normal_20260614_v43d`

- Base unchanged rows: `0`.
- Label consistency: `0 / 0 / 0`.
- Schemes present: `14`.
- Self-cancel: `0`; fraud imbalance: `0`.
- 3+ line fraud docs: `0`; same-account duplicate split: `0`.
- Omission amounts remain distinct: FS10 `184,310,249`, FS12 `106,184,336`, FS13 `76,704,650`.

`uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`

- Findings: `0`.

`uv run python tools/scripts/audit_full_leak_scan.py data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260614_v1_r4m_h`

- NEW leak candidates: `0`.
- Category/value, NULL/populated rule, numeric repeated value, timestamp concentration, and 2-column combination sections are clean.

## PHASE2 Seed Verification

The same four PHASE2 checks were run on `r4m_h_seed1`.

- `phase2_shortcut_gate.py`: `17/17 PASS`, `FAIL 0`.
- `verify_phase2_regression.py`: base unchanged `0`, label consistency `0 / 0 / 0`, schemes `14`, self-cancel `0`, fraud imbalance `0`.
- `scan_overlay_shortcuts.py`: findings `0`.
- `audit_full_leak_scan.py`: NEW leak candidates `0`.

## Known Monitor

- NORMAL `M06` remains `MONITOR`, not FAIL: hard negative balance rate `2.26%` vs threshold `2.0%`. This is carried as a balance-direction diagnostic and did not break TB, BS equation, roll-forward, closing, or subledger gates.

