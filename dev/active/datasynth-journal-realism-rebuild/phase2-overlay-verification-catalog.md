# PHASE2 Overlay Verification Catalog

## Scope

This file is the PHASE2 fraud overlay realism and anti-shortcut gate catalog.
It is separate from the NORMAL and PHASE1 catalogs.

- NORMAL checks: `normal-data-realism-test-catalog.md`
- PHASE1 overlay checks: `phase1-abnormal-overlay-test-catalog.md`
- PHASE2 overlay checks: this file
- Scheme source of truth: `../phase2-fraud-scheme-catalog.md`
- Implemented shortcut gate: `../../../tools/scripts/phase2_shortcut_gate.py`
- Accounting regression gate: `../../../tools/scripts/verify_phase2_regression.py`
- Surface shortcut scan: `../../../tools/scripts/scan_overlay_shortcuts.py`
- Full-column leak scan: `../../../tools/scripts/audit_full_leak_scan.py`

PHASE2 fraud overlay generation must follow `dev/active/phase2-fraud-scheme-catalog.md`.
Generation must not be tuned from detector performance. Detector output is used only after the dataset is complete.

## Gate Update Rule

Every PHASE2 overlay generator change must run the applicable gates in this catalog.
Any recurring or likely recurring bug found during review must be added here as a regression gate before the run is accepted.

Acceptance for the current PHASE2 fraud overlay requires:

```powershell
uv run python tools/scripts/phase2_shortcut_gate.py <PHASE2_DATASET> <REFERENCE_DATASET>
uv run python tools/scripts/audit_balance_integrity.py <NORMAL_BASE>
uv run python tools/scripts/verify_phase2_regression.py <PHASE2_DATASET> <NORMAL_BASE>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE2_DATASET>
uv run python tools/scripts/audit_full_leak_scan.py <PHASE2_DATASET>
uv run python tools/scripts/verify_phase2_seed_diversity.py <REPRESENTATIVE_DATASET> <SEED1> ... <SEEDN>
```

The reference dataset is required when S13 scale preservation is in scope.
Scale reference for S13 is now `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`
(the scale-correct reference overlay). `r4f_c` is retired and may be deleted; future rounds use
`r4l_b` as the scale reference. `r4l_b` is not a final accepted overlay after the 2026-06-14
full-column leak scan; the next accepted dataset must pass `audit_full_leak_scan.py` with findings 0.
Gate thresholds, whitelists, S11 combination lists, S12 floor, S13
exclusion list, S14 structure floor, and seed-diversity assignment checks are not changed without
explicit user approval.

## Current Baseline (2026-06-13 scale reference; 2026-06-14 full-scan update)

- Normal base: `data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j`
- Scale/accounting reference PHASE2 overlay: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`
- Scale reference for S13: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b` (r4f_c retired)
- Seed rotation outputs: `..._r4l_b_seed1` through `..._r4l_b_seed5`
- Pre-full-scan evidence (PASS before 2026-06-14 full-column scan):
  - `phase2_shortcut_gate.py <r4l_b> <r4l_b>` exits 0 with 15 gates PASS (S15 label-interface included).
    For future rounds: `phase2_shortcut_gate.py <new> <r4l_b>` (r4l_b as scale reference).
  - `audit_balance_integrity.py <v42j>` PASS; NORMAL N10/N11/N12 (TB↔JE, year carry-forward, subledger)
    are hard prerequisites, satisfied in v42j.
  - `verify_phase2_regression.py <r4l_b> <v42j>` exits 0.
  - `verify_phase2_seed_diversity.py <r4l_b> <r4l_b_seed1..5>` exits 0 (content + assignment diversity).
  - `scan_overlay_shortcuts.py <r4l_b>` reports findings 0.
- Full-column scan update:
  - `reports/phase2_full_leak_scan_r4l_b.md` found reproducible leaks in r4l_b and r4l_b_seed1:
    L4 `trading_partner V-000001` concentration, L5 auxiliary-field nullness and fraud-only
    `(event_type, supporting_doc_type)` cells, L6 `original_document_id` non-null boundary due to
    missing normal reversal background, and weak L7 round-amount value leaks.
  - Therefore r4l_b remains only the S13 scale reference. r4m or later is accepted only when F21-F26
    and the NORMAL C06/J09 prerequisite pass.
- Retired/deletable datasets: v41, all r4f~r4l (non-b) including failed/pre_hashfix/seed variants.
  - Every generated seed dataset exits 0 for the 14-gate shortcut gate, regression gate, and surface shortcut scan.
  - `verify_phase2_seed_diversity.py <r4k> <r4k_seed1> ... <r4k_seed5>` exits 0 with every pair at or above 50% fraud-content difference and zero identical scheme-company assignment vectors.
  - `docs/debugging.md` records failed intermediate runs and fixes.

## Required Artifact And Coverage Gates

| ID | Area | Check |
| --- | --- | --- |
| A01 | Artifacts | Journal, scheme sidecars, reports, and flow/member sidecars exist. |
| A02 | Schema | Scheme rows include scheme id, instance id, member docs, component roles, evaluation stratum, and omission amount. |
| A03 | Evidence | Reports contain numeric counts, not only an ACCEPT string. |
| B01 | Coverage | FS01 through FS14 are all present. |
| B02 | Roles | Component role sets exactly match the scheme catalog. |
| B03 | Pairing | Multi-document roles follow catalog timing and pairing. |
| C01 | Base | Base normal documents are unchanged. |
| C02 | Count | Output document count equals base documents plus overlay documents. |
| C03 | Twins | Accounts, document types, and surface formats used by overlay also exist in normal data. |
| C04 | Delivery | `delivery_date` non-null is not overlay-only. |
| C05 | Base financial integrity | The normal base used for overlay passes M08 TB↔JE derivation, M09 yearly carry-forward, and M10 measured subledger reconciliation before fraud rows are added. |
| C06 | Base reversal background | If overlay uses `original_document_id`/`reversal_document_id`, the normal base must already contain linked normal reversals with the same non-null surface. NORMAL J09 must pass before PHASE2 acceptance. |

## Required Accounting Substance Gates

| ID | Area | Check |
| --- | --- | --- |
| D01 | Balance | Overlay documents are balanced by document. |
| D02 | Substance | Same-document same-GL debit/credit self-cancel count is zero. |
| D03 | Direction | FS01/FS05/FS09 revenue effect is positive. |
| D04 | Direction | FS03 cash effect is outflow and concealment accounts carry the offset. |
| D05 | Direction | FS07 inventory or COGS effect is present. |
| D06 | Direction | FS11 intercompany receivable/payable do not fully offset. |
| D07 | Line structure | Same-side split used only to inflate line count is zero. Natural two-line fraud entries are allowed. |
| D08 | Scheme account coherence | Every scheme uses only catalog-valid semantic account subtypes. |
| D09 | Period-end substance | FS02, FS06, FS07, and FS09 include real period-end postings where catalog mechanics require them. |
| D10 | Scale preservation | Scheme cumulative scale is preserved when amount realism is adjusted. FS14 payroll is excluded from r4f reference restoration because normal payroll level is the realism constraint. |
| D11 | Structural signal preservation | Shortcut cleanup must not flatten scheme-defining structure. FS01 must repeat external fictitious customers, FS03 must show progressive cash withdrawals, and FS05 must span a three-company circular chain. |

## Required Flow And Linkage Gates

| ID | Area | Check |
| --- | --- | --- |
| E01 | Flow | Every overlay document appears in a real flow/member sidecar. |
| E02 | Linkage | O2C delivery and customer-invoice sidecars align with delivery dates. |
| E03 | Linkage | Reversal, return, and rebooking documents have source-document links. |
| E04 | Linkage | GL and H2R schemes have batch/run sidecars. |

## Required Leakage And Shortcut Gates

The implemented gate names below map to `tools/scripts/phase2_shortcut_gate.py`.

| ID | Script Gate | Check |
| --- | --- | --- |
| F01 | `scan_overlay_shortcuts.py` | Exact-value, format-signature, and numeric-range findings are zero. |
| F02 | Manual/all-column scan | No non-sidecar surface column perfectly separates overlay documents. |
| F03 | Journal surface | Component-role strings and mutation/provenance strings do not appear in journal feature columns. |
| F04 | `R-COV` | 14 scheme coverage is complete. |
| F05 | `R-SELF` | Same-document same-GL debit/credit self-cancel is zero. |
| F06 | `R-BAL` | Fraud documents are balanced. |
| F07 | `R-DIR` | Direction anti-pattern count is zero. |
| F08 | `S1` | Metadata missingness gap between normal and fraud is within 8 percentage points. |
| F09 | `S2` | No single surface value or null rule is a high-precision/high-recall shortcut. |
| F10 | `S4` | Every extended PHASE2 account has sufficient normal twins. Current minimum is 300 normal documents. |
| F11 | `S8` | Scheme-account semantic subtype whitelist passes. |
| F12 | `S9` | Fraud identifiers and document-number prefixes follow normal format and length. |
| F13 | `S10` | Period-end schemes have actual month-end rows. |
| F14 | `S11` | Multi-column metadata combinations do not create fraud-only cells. |
| F15 | `S12` | Small fraud components exist naturally and amount digit cells are not shortcuts. |
| F16 | `S13` | Scheme scale remains within reference ratio bounds when a reference dataset is supplied. |
| F17 | `S14` | Scheme structural floor passes: FS01 has repeated external-customer concentration with no internal/affiliate fictitious-sale partner, FS03 late cash-withdrawal average exceeds early average, and FS05 has a 3-company cycle. |
| F18 | `verify_phase2_seed_diversity.py` | Seed rotation is real: every pair of representative/seed datasets differs by at least 50% on `(scheme_id, component_role, local_amount, posting_date, gl_account)` and no two datasets share the same scheme-company assignment vector. |
| F19 | `S2` | Overlay rows do not expose NULL/format markers through `is_synthetic`, `is_mutated`, `line_number`, or `ledger`. These fields are included in S2 and any value/null cell above shortcut thresholds is FAIL. |
| F20 | `S15` | Fraud rows with `is_anomaly=true` have `anomaly_type` populated consistently with `fraud_type`; missing `anomaly_type` is not allowed to erase multi-class evaluation labels. |
| F21 | `audit_full_leak_scan.py` | Full-column scan over all journal surface columns exits 0. It must not be replaced by the narrower S2 whitelist or `scan_overlay_shortcuts.py`. Run on the representative dataset and at least one seed dataset. |
| F22 | Full-column L4 | No `trading_partner` value may become a high-precision or high-recall fraud identifier. Vendor/IC scheme counterparties must be dispersed or backed by normal twins; `V-000001`-style concentration is FAIL. |
| F23 | Full-column L5a/L5b | Auxiliary fields such as `invoice_amount`, `supply_amount`, and `auxiliary_account_number` must inherit normal donor nullness/value rules. Fraud documents being all-null or all-populated while normal peers differ is FAIL. |
| F24 | Full-column L5c | Every `(event_type, supporting_doc_type)` combination used by overlay must exist in normal data or be accompanied by normal twins. Fraud-only cells with support above the full-scan threshold are FAIL. H2R payroll events must not inherit tax-invoice support types unless the same H2R payroll support cell exists in normal data; use payroll-supported evidence such as payroll statements or donor-supported blanks. |
| F25 | Full-column L6 | `original_document_id`/`reversal_document_id` non-null values must not be overlay-only. If the normal base has insufficient linked normal reversals, PHASE2 acceptance is blocked until NORMAL J09/C06 is fixed. |
| F26 | Full-column L7 | Exact round amounts and amount digit buckets must not create fraud-only cells under the full-scan precision/recall/lift criteria. Small repeated round amounts need normal support or natural non-round variation; detector-target fitting is forbidden. |

## Low-Trace Omission Gates

| ID | Area | Check |
| --- | --- | --- |
| G01 | Low trace | FS10/FS12/FS13 omission amounts are positive. |
| G02 | Low trace | FS10/FS12/FS13 omission amounts are not copied constants. |
| G03 | Low trace | Omission amount equals the defined component-basis amount. |
| G04 | Low trace | Updating omission metadata does not change posted accounting effects. |

## History And Hollow-Pass Gates

| ID | Area | Check |
| --- | --- | --- |
| H01 | History | Failed intermediate runs and fixes are recorded in `docs/debugging.md`. |
| H02 | Hollow pass | Empty populations are FAIL or BLOCKED, not PASS. |
| H03 | No gate weakening | Gate thresholds, whitelists, and exclusion lists are not relaxed without explicit user approval. |
| H04 | Loop discipline | A dataset is accepted only when shortcut, regression, surface scan, full-column leak scan, and seed diversity gates all pass. |

## Regression-Derived Additions

| Run | Defect Found | Required Gate |
| --- | --- | --- |
| r1e | Same-document same-GL self-cancel made economic substance zero. | D02, F05 |
| r1e | O2C overlay delivery date was missing. | C04, E02 |
| r1e | FS09 had an invented role and wrong timing direction. | B02, B03 |
| r2 | Base normal delivery date was blank, making non-null delivery date an overlay boundary. | C04 |
| v33 | Normal O2C delivery date and flow sidecars were inconsistent. | E02 |
| r3f | GL/H2R scheme documents lacked real flow sidecar membership. | E01, E04 |
| r3f | FS11 intercompany economics netted to zero. | D06 |
| r3f | FS10/FS12/FS13 omission amounts all equalled 148750000. | G01-G04 |
| r3g | Shortcut gate baseline had regression gates PASS but shortcut gates FAIL. | F04-F10 |
| r4b | Shortcut removal used unrelated filler accounts such as loans receivable and contract assets in wrong schemes. | D08, F11 |
| r4d | Line-count fitting used same-side split to inflate 3+ line fraud documents. | D07 |
| r4e | Earlier shortcut checks missed identifier length, system-field nulls, period-end absence, and line-text-family concentration. | F09, F12, F13 |
| r4f_c | Single-column gates passed, but normal-absent metadata combinations remained. | F14 |
| r4f_c | Fraud amounts concentrated in 7-8 digits and lacked small real fraud components. | F15 |
| r4g | Small-fraud repair reduced FS03 cumulative embezzlement scale from r4f_c reference. | D10, F16 |
| r4h | Shortcut cleanup dispersed away scheme substance: FS01 fictitious revenue lost repeated-customer concentration and FS05 circular trading collapsed to one company. | D11, F17 |
| r4i_seed1 first run | Seed rotation fallback generated a truth-only `reference` numeric bucket (`100000-100999`). | F01, H04 |
| r4i_seed1~5 | Seed rotation was fake: all six datasets had 0 fraud-content difference despite passing per-seed gates. | F18 |
| r4j first run | Seed-aware account spread pushed AP `2000` into short-term-debt subtypes in FS05/FS08. | D08, F11 |
| r4i/r4j strengthened S14 | FS01 fictitious-sale counterparties included internal departments or affiliates, and FS03 cash withdrawals were not progressive over time. | D11, F17 |
| r4j diversity-v2 | Content diversity passed, but scheme-company assignment still repeated on seed pairs because the company selection reduced to a mod-3 rotation. | F18 |
| r4k domain audit | Fraud overlay rows exposed `is_synthetic`, `is_mutated`, and `line_number` NULL markers; all three columns must remain in S2. | F19 |
| r4k domain audit | Fraud rows had `anomaly_type` blank even when `is_anomaly=true`, weakening PHASE2 multi-class evaluation. | F20 |
| v42 prompt N10-N12 | Base normal TB, opening balances, and subledger reconciliation can be hollow even when overlay gates pass. Overlay acceptance must require the normal M08-M10 balance gate first. | C05 |
| r4l_b full-column scan | The narrowed shortcut gates passed, but `audit_full_leak_scan.py` found reproducible L4/L5/L6 leaks and a weak L7 leak across r4l_b and r4l_b_seed1. Full-column scan is now mandatory. | C06, F21-F26 |
| r4m_f_seed1 full-column scan | Representative r4m_f passed, but seed1 produced fraud-only H2R payroll `(event_type, supporting_doc_type=tax invoice)` cells. Full-column leak scan must run on at least one seed, and H2R support evidence must be event-compatible. | F21, F24, H04 |
| v43d/r4m_h | NORMAL direct SoD marker policy and document-number gate were reconciled: normal may contain self-approval context but no direct `sod_violation` marker, and document numbers are regenerated as company-year-document_type sequences. r4m_h and seed1 both passed 17 shortcut gates, regression, surface shortcut scan, and full-column leak scan. | C06, F21-F26, H04 |

## Current Command Checklist

For the next PHASE2 fraud overlay candidate, run with these roles:

- `<NORMAL_BASE>`: the current accepted NORMAL base, after NORMAL J09/C06 reversal-background gate passes.
- `<PHASE2_DATASET>`: the candidate overlay dataset, r4m or later.
- `<REFERENCE_DATASET>`: `data/journal/primary/datasynth_semantic_v1_phase2_fraud_20260613_v1_r4l_b`
  for S13 scale preservation only.
- `<SEED1> ... <SEEDN>`: seed-rotation outputs for the same candidate lineage.

```powershell
uv run python tools/scripts/phase2_shortcut_gate.py `
  <PHASE2_DATASET> `
  <REFERENCE_DATASET>

uv run python tools/scripts/audit_balance_integrity.py `
  <NORMAL_BASE>

uv run python tools/scripts/verify_phase2_regression.py `
  <PHASE2_DATASET> `
  <NORMAL_BASE>

uv run python tools/scripts/scan_overlay_shortcuts.py `
  <PHASE2_DATASET>

uv run python tools/scripts/audit_full_leak_scan.py `
  <PHASE2_DATASET>

uv run python tools/scripts/verify_phase2_seed_diversity.py `
  <PHASE2_DATASET> `
  <SEED1> `
  <SEED2> `
  <SEED3> `
  <SEED4> `
  <SEED5>

uv run python tools/scripts/audit_full_leak_scan.py `
  <SEED1>
```

Expected result:

- `phase2_shortcut_gate.py`: v42/r4l and later have at least 15 gates including S15, fail 0.
- `audit_balance_integrity.py`: v42/r4l and later normal base exits 0 before overlay acceptance; M08/M09/M10 failures block the fraud overlay even if shortcut gates pass.
- `verify_phase2_regression.py`: base unchanged 0, label consistency 0/0/0, 14 schemes, self-cancel 0, fraud imbalance 0.
- `scan_overlay_shortcuts.py`: findings 0.
- `audit_full_leak_scan.py`: findings 0 on the representative dataset and at least one seed dataset. Any L4/L5/L6/L7-class finding blocks acceptance even when shortcut gates pass.
- `verify_phase2_seed_diversity.py`: all representative/seed pairs differ by at least 50%, and identical scheme-company assignment pairs are 0.

For seed rotation, run the same per-dataset shortcut, regression, surface shortcut, and full-column leak commands against each seed output. A seed dataset is not accepted if any seed-only identifier, reference range, metadata combination, auxiliary-field nullness rule, reversal-link surface, trading-partner concentration, amount bucket, or normal-absent surface appears. The seed set is not accepted if diversity passes only by changing labels, density, scheme count, accounting mechanics, or a periodic company assignment rotation.

## Implementation Notes

- Metadata shortcut removal must use observed normal combinations, not independent marginal sampling.
- PHASE2 overlay rows must inherit non-substance surface fields from a normal donor document whenever possible. This includes auxiliary invoice fields, supporting-document metadata, counterparty surface, and source/user/persona combinations. Mutate the scheme substance fields; do not independently sample marginal surface columns.
- Full-column leakage is broader than the S2 whitelist. `audit_full_leak_scan.py` must run after every PHASE2 overlay regeneration and must not be bypassed by arguing that `phase2_shortcut_gate.py` or `scan_overlay_shortcuts.py` already passed.
- Reversal-link fields are a cross-track dependency: if PHASE2 uses `original_document_id` or `reversal_document_id`, NORMAL must already provide linked normal reversals through J09. PHASE2 must not be the first dataset where those fields become non-null.
- Trading partners and auxiliary fields are surface features. They may support a scheme only through realistic flow structure, not by concentrating one vendor/customer or by making all fraud rows null in fields that normal peer documents populate.
- Fraud-only `(event_type, supporting_doc_type)` cells are forbidden. Create normal-supported twins or use donor-supported event/supporting combinations while preserving scheme mechanics.
- Round amount values are allowed only when they arise from scheme mechanics and have normal support. Repeated exact amounts such as 25M/40M/2.49M must not become value-level identifiers.
- Small fraud components must arise from scheme mechanics: FS03 progressive embezzlement, FS04 small write-off, FS14 payroll-like amounts.
- Restoring FS03 scale must keep early small transactions and increase later transactions; it must not restore FS14 to the r4f_c level.
- Structural floor cleanup must preserve scheme mechanics. Removing shortcuts cannot erase the repeated external fake-customer pattern in FS01, the progressive early-small/late-large FS03 cash-withdrawal path, or the 3-company circular chain in FS05.
- Seed rotation changes placement, not density. If a seed changes surface identifier distributions, use normal donor/fallback values rather than inventing new ranges.
- Seed rotation must change fraud content, not just document IDs, company labels, or metadata. Seed must affect deterministic amount/date/customer/company/donor placement while preserving scheme prevalence and accounting substance. Company placement must be seed-specific per scheme, not a `seed % company_count` rotation.
- Detector performance is not an input to generation. The only accepted feedback loop is gate failure analysis on data realism, accounting substance, and shortcut leakage.
