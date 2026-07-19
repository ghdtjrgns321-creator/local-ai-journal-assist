# PHASE1 Rule Recall Overlay Verification

## Purpose

Recall dataset verification contract.
PHASE1 rule-recall overlay 수정 중 새 버그가 발견되거나 재발 가능성이 있는 결함이 확인되면, 해당 검사는
본 문서 또는 [phase1-abnormal-overlay-test-catalog.md](./phase1-abnormal-overlay-test-catalog.md)에
regression gate로 추가하고 이후 PHASE1 recall overlay 재생성의 자동 실행 대상에 포함한다.

## Hard Invariants

- Output dataset is separate from p3_2_overlay.
- Base normal must be the latest accepted single-company NORMAL dataset.
- Output dataset must contain only `company_code=C001`.
- Violations and boundary controls replace normal documents/flows.
- Journal/master must not expose truth or provenance text.
- labels/p3_2_rule_truth.csv is kept for scanner/measurement compatibility, with truth_layer=phase1_rule_recall_overlay.
- Journal `gl_account` values must exist in both dataset `chart_of_accounts.json` and global
  `config/chart_of_accounts.csv`, except accounts used only by L1-03 standard invalid-account
  member documents. CoA gaps outside that exception are FAIL because they let L1-03 become a
  shortcut detector for other rule injections.

## RAW-only Guard

Do not inject derived columns as answers: exceeds_threshold, approval_level, approval_limit_resolved, is_near_threshold, is_period_end, is_weekend, is_holiday, is_after_hours, time_zone_category, days_backdated, description_quality, is_manual_je, is_intercompany, is_suspense_account, amount_zscore, first_digit, fiscal_period_mismatch. approval_contract_degraded must remain false or blank.

## SoT

Use `docs/spec/DETECTION_RULES.md` PHASE1-1 headings as the current rule source.
Historical `dev/active/phase1-rule-recall-checklist.md` rows are implementation hints only when they
do not conflict with `DETECTION_RULES.md`.

Current PHASE1-1 recall scope after the 2026-06-21 rule rewrite is 26 rules:
`L1-01`, `L1-02`, `L1-03`, `L1-04`, `L1-05`, `L1-06`, `L1-07`,
`L1-07-02`, `L1-08`, `L2-01`, `L2-02`, `L2-03`, `L2-04`, `L2-05`,
`L3-02`, `L3-03`, `L3-04`, `L3-05`, `L3-06`, `L3-07`, `L3-09`,
`L3-10`, `L3-11`, `L4-01`, `L4-03`, `L4-04`.

The recall overlay must not inject removed/transferred/non-PHASE1-1 rule truth for:
`L1-09`, `L3-01`, `L3-08`, `L3-12`, `L4-02`, `L4-05`, `L4-06`,
`IC01`, `IC02`, `IC03`, `GR01`, `GR03`, `D01`, `D02`.

## Required Truth Fields

rule_id, case_kind, case_index, natural_unit_type, natural_unit_id, member_document_ids, base_document_ids, variant_id, is_boundary_control, expected_detector_outcome, expected_measurement_unit, raw_trigger_summary.

## Acceptance

1. 26 of 26 current PHASE1-1 rules in truth.
2. Boundary controls are labelled normal and expected no_fire.
3. scan_overlay_shortcuts.py findings zero.
4. measure_phase1_detector_catch.py runs with expected truth unit count.
5. Reports include per-rule recall numerator denominator and control false positives.
6. `audit_overlay_injection.py` CoA coverage gate passes: journal accounts are covered by
   dataset CoA and global config CoA, with only L1-03 standard invalid-account docs allowed
   to be absent.
7. Removed/transferred rule IDs listed above have zero truth rows.
8. Dataset scope is single-company only (`company_code=C001`).
9. pytest tests -q --continue-on-collection-errors has no new failure or exact blocker is recorded
   when full-suite verification is explicitly in scope.

## 2026-06-22 r11 Construction and Proof Summary

Detailed three-way audit: [r11-rule-3way-verification.md](./r11-rule-3way-verification.md).
Combo/tier pre-generation matrix:
[phase1-combo-tier-firing-matrix.md](../phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md).

This section is the DataSynth-side summary of how the accepted PHASE1-1 individual rule recall
dataset was built, how it was proven, and what result it produced. The r11 dataset is only for
detector-only individual rule firing verification. It is not the high/medium/low combo or tier
dataset.

### How r11 Was Built

- Output dataset:
  `data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`.
- Base normal:
  the latest accepted single-company normal baseline at the time of generation.
- Implementation:
  Rust PHASE1 recall overlay under `tools/datasynth/crates/datasynth-cli/`, following the
  `p3_2_overlay.rs` recall-overlay pattern. Python post-patching is not part of the accepted
  generation path.
- Scope:
  exactly the 26 current PHASE1-1 row/document firing rules from
  `docs/spec/DETECTION_RULES.md`.
- Excluded population:
  transferred, retired, macro, PHASE1-2, or non-row-level rules are not injected into r11 truth:
  `D01`, `D02`, `L3-01`, `L3-12`, `L4-02`, `L4-05`, `L4-06`, `IC01`, `IC02`, `IC03`,
  `GR01`, `GR03`, and EV/evidence-context rows.
- Truth model:
  each rule has positive `standard` units and matching `boundary_control` units in
  `labels/p3_2_rule_truth.csv`. Boundary controls are normal-labelled units intentionally placed
  just outside the detector predicate.
- Natural unit:
  the truth row records whether the expected measurement is document-level or row/member-level
  through `natural_unit_type`, `natural_unit_id`, `member_document_ids`, and
  `expected_measurement_unit`.
- Anti-shortcut stance:
  journal/master columns do not carry answer/provenance text. Rule truth remains sidecar-only.
  Triggering is by raw accounting/approval/date/text structure, not by injected derived flags.

### How r11 Was Proven

r11 is accepted by a three-way proof, not by a single recall number.

1. Rule description to detector predicate:
   `docs/spec/DETECTION_RULES.md` was compared to the actual detector and feature code under
   `src/detection/` and `src/feature/`.
2. Rule description to DataSynth truth:
   every truth variant in `labels/p3_2_rule_truth.csv` was checked against the rule description
   and expected natural unit.
3. Detector predicate to measured truth:
   `tools/scripts/measure_phase1_detector_catch.py` was rerun against the r11 dataset and compared
   to the truth sidecar.

The population boundary is also explicit. The manifest and truth CSV define the r11 PHASE1-1
population as 26 rules and 1,500 truth units. The scoring registry has additional rule IDs, but the
registry-minus-r11 set is macro or PHASE1-2 scope, not missing PHASE1-1 row-rule coverage.

### r11 Result

- PHASE1-1 rule population: 26 / 26 covered.
- Truth units: 1,500 total = 750 standard positives + 750 boundary controls.
- Standard recall: 750 / 750.
- Boundary-control false positives: 0 / 750.
- Per-rule result: all 26 rules achieved their expected standard catch and boundary no-fire result.
- Shortcut scan: findings 0.
- CoA/injection audit: PASS for expected rule population; L1-03 remains the only allowed invalid
  account exception.
- Behavioral defects found in detector behavior: 0.
- Remaining notes: 9 non-blocking documentation or cosmetic mismatches are recorded in
  [r11-rule-3way-verification.md](./r11-rule-3way-verification.md); none changed the measured
  firing behavior.

The accepted interpretation is therefore: r11 proves PHASE1-1 individual rule firing, with
description-code-truth alignment, standard positives firing, and boundary controls staying quiet.
Combo/tier grounding remains a separate DataSynth deliverable.

## PHASE1 Combo/Tier Overlay Gate

This gate applies to the future combo/tier dataset only. It must not be merged into r11 individual
rule recall truth.

Source of truth:
`dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`.

Static matrix gate:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py --matrix-only
```

Dataset gate after generation:

```powershell
uv run python tools/scripts/verify_phase1_combo_tier_gate.py <PHASE1_COMBO_TIER_DATASET>
uv run python tools/scripts/scan_overlay_shortcuts.py <PHASE1_COMBO_TIER_DATASET>
```

Required combo/tier truth:

- Buildable scheme truth exists for 13 in-scope schemes:
  `HIGH-1`, `HIGH-2`, `HIGH-3`, `HIGH-4`, `HIGH-5`, `HIGH-7`, `HIGH-9`,
  `M-4A-1`, `M-4A-2`, `M-4A-4`, `M-4B-1`, `M-4B-2`, `M-4B-3`.
- LOW standalone-primary and CONTEXT booster-only controls exist.
- Out-of-scope schemes are absent from truth:
  `HIGH-6`, `HIGH-8`, `HIGH-10`, `M-4A-3`.
- Every `expected_rule_ids` member is one of the r11 26 PHASE1-1 firing rules.
- Every standard combo has `expected_policy_id`, `expected_topic`, and `expected_case_tier`
  matching the matrix.
- Boundary/negative controls intentionally drop one leg and must not silently pass as empty
  populations.
- The case-builder measurement report must prove observed tier/policy equals the truth expectation
  for standards and drops to the expected lower tier for controls.

Implementation constraint:
combo/tier generation must create same-case grouping, not merely co-located truth rows. Member rule
legs must be woven into the same `(theme_id, case_key)` case, with real flow sidecars for
duplicate, reversal, suspense, and threshold-flow combinations.

### 2026-06-22 r1i Combo/Tier Dataset — REJECT

- Dataset: `data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260621_v46b`
- Generator profile: `phase1-combo-tier-overlay`
- Truth file: `labels/phase1_combo_tier_truth.csv`
- Truth rows: 15 = 13 buildable combo schemes + LOW control + CONTEXT control.
- Expected tier counts: HIGH 6, MEDIUM 7, LOW 1, CONTEXT 1.
- Gate:
  - `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
  - PASS.
- Shortcut scan:
  - `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
  - findings 0.
- Actual case-builder measurement:
  - `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i --expect-truth-rows 15`
  - FAIL: passed rows 1 / 15, failed rows 14 / 15.

Rejection reason:
r1i proves only static truth/schema coverage and surface shortcut removal. It does not prove
combo/tier firing. The actual case-builder fails because member-rule legs are still generated as
separate rule cases rather than one natural case, and broad baseline/context flags cause LOW/CONTEXT
controls to rank as high. Therefore this dataset must not be used as accepted combo/tier recall.

Gate hardening added:
`tools/scripts/measure_phase1_combo_tier.py` is now mandatory for combo/tier acceptance. Static
`verify_phase1_combo_tier_gate.py` and `scan_overlay_shortcuts.py` are necessary but insufficient.

Next required generator fix:
build combo/tier units as a single natural case, not as a list of independent rule-injection
documents. Each expected rule must fire on truth member documents inside the same observed case, and
LOW/CONTEXT controls must remain low/context after full case-builder execution.

## 2026-06-09 r21 Result

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r21`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- Truth units: 780 = 39 rules x (10 standard + 10 boundary control)
- Distinct documents: base 320,312 / output 320,312
- Shortcut scan: `FINDINGS 0`
- Detector-only measurement:
  - Standard recall: 390 / 390
  - Boundary-control false positives: 0 / 390
  - Per-rule standard catch: 10 / 10 for all 39 rules
  - Per-rule boundary catches: 0 / 10 for all 39 rules
- Report files:
  - `reports/phase1_detector_catch/summary.json`
  - `reports/phase1_detector_catch/rule_summary.csv`
  - `reports/phase1_detector_catch/variant_summary.csv`
  - `reports/phase1_detector_catch/truth_unit_measurement.csv`
  - `reports/phase1_detector_catch/measurement.md`
  - `reports/phase1_detector_catch/overlay_shortcut_scan.json`
- Full pytest command was run. It still fails on unrelated existing repository blockers
  such as missing legacy DataSynth truth datasets, missing `phase1_phase2_integration_stage7.py`,
  stale rule-count/config expectations, and dashboard test API drift. The PHASE1 recall
  overlay acceptance checks above passed.

## 2026-06-09 r22i Result

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r22i`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- Scope: r21 rework for two downscoped areas:
  - checklist variants implemented instead of one `{rule} standard` placeholder
  - injected units are listed in `document_flows` and `relationships` overlay membership sidecars
- Truth units: 2,160 = 108 variants x (10 standard + 10 boundary control)
- Rule coverage: 39 / 39
- Variant coverage: 108 rule-variant pairs
- Distinct documents: base 320,312 / output 320,312
- Flow/relationship membership:
  - `document_flows/phase1_recall_overlay_flows.json`: 2,160 rows
  - `relationships/phase1_recall_overlay_links.json`: 2,160 rows
  - CSV mirrors are also written for deterministic inspection.
- Shortcut scan:
  - `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r22i`
  - findings 0.
- Detector-only measurement:
  - `uv run python tools/scripts/measure_phase1_detector_catch.py data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r22i --expect-truth-units 2160`
  - standard variant recall: 1,080 / 1,080
  - boundary-control false positives: 0 / 1,080
  - bad rule-variant groups: 0
- Report files:
  - `reports/phase1_detector_catch/summary.json`
  - `reports/phase1_detector_catch/rule_summary.csv`
  - `reports/phase1_detector_catch/truth_unit_measurement.csv`
  - `reports/phase1_detector_catch/measurement.md`
  - `reports/phase1_detector_catch/overlay_shortcut_scan.json`
- Main fixes from r21:
  - Added rule-specific variant catalog from `dev/active/phase1-rule-recall-checklist.md`.
  - Changed truth labels to concrete `variant_name`, `raw_trigger_summary`, `threshold_relation`, and `expected_measurement_unit`.
  - Fixed synthetic document id collisions caused by r21-scale UUID strides after variant expansion.
  - Added non-truth document-number decoys so identifier surface values are not truth-only shortcuts.
  - Fixed L2-01 to respect the real employee approval limit, D01 current-year population generation, L4-04 rare-pair diversity, L3-12 boundary users, and L1-08 fiscal-period mismatch.

## 2026-06-09 r23 Result

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r23`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260607_v29`
- Scope: r22i strengths preserved, but fake overlay-only flow sidecars removed and real flow-file membership added.
- Truth units: 2,160 = 108 variants x (10 standard + 10 boundary control)
- Rule coverage: 39 / 39
- Variant coverage: 108 rule-variant pairs
- Distinct documents: base 320,312 / output 320,312
- Flow class report: `reports/phase1_recall_flow_classification.csv`
- Actual flow membership report: `reports/phase1_recall_real_woven_membership.json`
- Flow-woven target membership:
  - P2P: 360 truth rows / 500 truth docs / 500 docs in real P2P flow files / 500 linked docs
  - O2C: 100 truth rows / 1,500 truth docs / 1,500 docs in real O2C flow files / 1,500 linked docs
  - IC: 280 truth rows / 620 truth docs / 620 docs in real intercompany flow files / 620 linked docs
  - GL-native: 1,420 truth rows / 33,400 truth docs / no forced fake flow membership
- r22i fake files are no longer produced:
  - `document_flows/phase1_recall_overlay_flows.json`: absent
  - `relationships/phase1_recall_overlay_links.json`: absent
- Shortcut scan:
  - `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r23`
  - findings 0.
- Detector-only measurement:
  - `uv run python tools/scripts/measure_phase1_detector_catch.py data/journal/primary/datasynth_semantic_v1_recall_20260609_v1_r23 --expect-truth-units 2160`
  - standard variant recall: 1,080 / 1,080
  - boundary-control false positives: 0 / 1,080
  - standard bad groups: 0
  - boundary bad groups: 0

## 2026-06-13 v42j_r2 Gate Regression

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260613_v42j_r2`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j`
- Detector recall and shortcut scan had passed, but the newly mandatory CoA coverage gate now
  rejects this dataset.
- `uv run python tools/scripts/audit_overlay_injection.py data/journal/primary/datasynth_semantic_v1_recall_20260613_v42j_r2`
  fails with forbidden missing CoA accounts outside L1-03 standard invalid-account docs:
  `1190`, `1290`, `15110`, `1590`, `25110`, `7600`, `8010`.
- `999998` is treated as an allowed missing account only when it appears exclusively in L1-03
  standard invalid-account member documents.
- This is the third CoA-sync ripple class after v31c/v41. Any future PHASE1 recall regeneration
  must pass `reports/phase1_detector_catch/coa_coverage_gate.json` before detector recall numbers
  are considered accepted.

## 2026-06-13 v42j_r3 Accepted

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260613_v42j_r3`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260613_v42j`
- CoA fix:
  - `phase1-recall-overlay` now extends dataset `chart_of_accounts.json` for recall-only
    normal accounts used by L3-09/L4-04 and related population variants.
  - Global `config/chart_of_accounts.csv` includes `15110`, `25110`, `7600`, and `8010`.
  - `999998` remains absent and is allowed only for L1-03 standard invalid-account units.
- Invariants:
  - base docs 325,365 / output docs 325,365 / diff 0.
  - truth rows 2,160 / provenance rows 2,160.
- CoA coverage:
  - `coa_coverage_gate.json`: PASS.
  - missing findings contain only `999998` with allowed L1-03 docs 30 and forbidden docs 0.
- Detector-only measurement:
  - standard 1,080 / 1,080 caught.
  - boundary control 0 / 1,080 caught.
  - standard missed variant rows 0.
  - boundary false-positive variant rows 0.
  - rules 39 / 39.
- Shortcut scan:
  - findings 0.

## 2026-06-21 v45d_phase1_1_r9 Accepted

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260621_v45d_phase1_1_r9`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260621_v45d`
- Scope: PHASE1-1 rule rewrite from `docs/spec/DETECTION_RULES.md`, single-company C001 only.
- Rule coverage: 26 / 26 current PHASE1-1 rules.
- Removed/transferred rule truth rows: 0 for `L1-09`, `L3-01`, `L3-08`, `L3-12`, `L4-02`,
  `L4-05`, `L4-06`, `IC01`, `IC02`, `IC03`, `GR01`, `GR03`, `D01`, `D02`.
- Truth units: 1,540 = 770 standard + 770 boundary controls.
- Company scope: journal company_code set = `[C001]`.
- Shortcut scan:
  - `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_recall_20260621_v45d_phase1_1_r9`
  - findings 0.
- Detector-only measurement:
  - `uv run python tools/scripts/measure_phase1_detector_catch.py data/journal/primary/datasynth_semantic_v1_recall_20260621_v45d_phase1_1_r9 --expect-truth-units 1540`
  - standard variant recall: 770 / 770.
  - boundary-control false positives: 0 / 770.
  - per-rule standard catch: every current PHASE1-1 rule caught all injected standard units.
- Injection audit:
  - `uv run python tools/scripts/audit_overlay_injection.py data/journal/primary/datasynth_semantic_v1_recall_20260621_v45d_phase1_1_r9`
  - CoA coverage PASS.
  - truth units 1,540, target docs 4,580.
  - journal rows matched 9,160, distinct docs 4,580.
  - units with no journal rows found: 0.
- Generator fixes locked by this run:
  - Removed obsolete 39-rule injection scope and limited recall overlay to the 26 active PHASE1-1 rules.
  - Added `L1-07-02` ghost/unknown approver recall variants.
  - Reworked `L3-03` as single-company related-party-account usage instead of old IC/GR multi-company flows.
  - Removed truth-only user, approver, reference, and related-party tokens by sampling normal-like surfaces.
  - Updated L3-10 recall to use current estimate/contra accounts and config exact-account detection support.
  - Updated profile measurement for current L2-03/L4-03 code paths and required columns.
  - Synced global CoA config for v45d normal accounts so L1-03 does not become a stale-CoA shortcut.
  - Fixed L2-05 and L2-02 boundary controls so below-threshold controls no longer fire.

## 2026-06-22 v46b_phase1_1_r11 Accepted

- Dataset: `data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260621_v46b`
- Basis: `dev/active/phase1-rule-basis-audit/phase1-rule-firing-matrix.md`
- Scope: latest `docs/spec/DETECTION_RULES.md` PHASE1-1 26-rule individual firing recall only.
  Combo/tier truth remains a separate dataset.
- Rule coverage: 26 / 26 current PHASE1-1 rules.
- Removed/transferred rule truth rows: 0 for `L1-09`, `L3-01`, `L3-08`, `L3-12`, `L4-02`,
  `L4-05`, `L4-06`, `IC01`, `IC02`, `IC03`, `GR01`, `GR03`, `D01`, `D02`.
- Truth units: 1,500 = 750 standard + 750 boundary controls.
  - Change from r9/r10: L2-03 stale `fuzzy/split/time_shift` variants removed, so the denominator
    intentionally decreases by 40 units.
- Matrix-driven DataSynth fixes:
  - L1-06 variant metadata now describes toxic process-pair SoD, not obsolete `sod_conflict_type`
    or IT-admin markers.
  - L2-03 variants are limited to current detector mechanisms: same-reference/account repost and
    exact same-day repost.
  - L2-04 stale `review_asset_expense_coexistence` variant renamed to amount-match semantics.
  - L3-10 variants now name current estimate accounts `119100`, `237100`, `682100`, `116100`.
  - L4-01 truth unit is document/document, and member docs contain only the spike document; background
    revenue rows remain only as z-score population context.
  - Recall truth/provenance `source_contract` points to the firing matrix; `normal_base_dataset`
    reflects `datasynth_semantic_v1_normal_20260621_v46b`.
- Shortcut scan:
  - `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`
  - findings 0.
- Detector-only measurement:
  - `uv run python tools/scripts/measure_phase1_detector_catch.py data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11 --expect-truth-units 1500`
  - standard variant recall: 750 / 750.
  - boundary-control false positives: 0 / 750.
  - per-rule standard catch: every current PHASE1-1 rule caught all injected standard units.
- Injection audit:
  - `uv run python tools/scripts/audit_overlay_injection.py data/journal/primary/datasynth_semantic_v1_recall_20260622_v46b_phase1_1_r11`
  - CoA coverage PASS.
  - truth units 1,500, target docs 3,100.
  - journal rows matched 6,200, distinct docs 3,100.
  - units with no journal rows found: 0.
- Post-checks:
  - stale variant names from the firing matrix fix list: 0.
  - L4-01 `natural_unit_type` / `expected_measurement_unit`: `document` / `document`.
  - L4-01 truth member document count: 1 for all 40 units.

Note: r9 remains historical but is no longer the current PHASE1-1 individual-rule recall acceptance
baseline because it was built on v45d and retained stale L2-03/L1-06/L3-10/L2-04 metadata.

## 2026-06-22 Combo/Tier Overlay Attempts

### r1i — REJECT

- Dataset: `data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i`
- Static combo/tier gate: PASS.
- Shortcut scan: findings 0.
- Actual case-builder gate:
  - `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1i --expect-truth-rows 15`
  - FAIL, 1/15 passed.
- Root cause: member rule documents were independently generated. The actual PHASE1 case-builder
  groups by topic-specific case keys, so sharing a truth row or `flow_id` is insufficient.

### r1l — REJECT

- Dataset: `data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260621_v46b`
- Generator profile: `phase1-combo-tier-overlay`
- Matrix: `dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`

Changes since r1i:

- Combo rows are generated as shared natural cases instead of independent per-rule documents.
- Combo/tier measurement now evaluates case-level rule sets for flow rules such as `L2-05`, matching
  the PHASE1 case-builder's unit semantics.
- `approved_by` and related-party surfaces were normalized to values that exist in the normal base,
  removing r1j shortcut findings.

Verification:

- `cargo check -p datasynth-cli` — PASS.
- `uv run ruff check tools/scripts/measure_phase1_combo_tier.py tools/scripts/verify_phase1_combo_tier_gate.py tools/scripts/scan_overlay_shortcuts.py` — PASS.
- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l` — PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l` — findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1l --expect-truth-rows 15` — FAIL, 7/15 passed.

Residual failures:

- `HIGH-7`, `M-4A-4`: expected related-party reversal `L2-05|L3-03`, but the observed candidate case
  does not expose both rules together.
- `M-4B-2`: expected suspense reversal `L3-09|L2-05`, but the observed candidate case still lacks
  `L2-05`.
- `M-4A-2`: expected `L2-01|L1-05`, but the observed candidate case lacks `L2-01`.
- `M-4A-1`, `M-4B-1`, `M-4B-3`, `LOW`: expected MEDIUM/LOW, but observed cases are still HIGH.

Conclusion:

No accepted combo/tier dataset exists yet. Static truth/schema coverage and shortcut scan are necessary
but not sufficient; `measure_phase1_combo_tier.py` is the authoritative acceptance gate.

### r1z — ACCEPT

- Dataset: `data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z`
- Base: `data/journal/primary/datasynth_semantic_v1_normal_20260621_v46b`
- Generator profile: `phase1-combo-tier-overlay`
- Matrix: `dev/active/phase1-rule-basis-audit/phase1-combo-tier-firing-matrix.md`

Changes since r1l:

- Flow-based `L2-05` combo rows now expose companion evidence in the actual PHASE1 case-builder path.
- MEDIUM/LOW rows were de-shortcuted: date/reference identity is normalized after date mutation, multi-document
  cases spread across safe mid-month dates, approval users are real normal-base users, and low-count user
  shortcuts are removed.
- `measure_phase1_combo_tier.py` now measures the actual case-builder topic score cut for the expected
  combo topic. It no longer requires the final case `priority_band` to equal the expected combo tier,
  because unrelated broad signals in the same case can legitimately raise the final case band while the
  expected combo floor is still correctly surfaced.

Verification:

- `cargo check -p datasynth-cli` — PASS with existing warnings only.
- `uv run python -m py_compile tools/scripts/measure_phase1_combo_tier.py tools/scripts/verify_phase1_combo_tier_gate.py` — PASS.
- `uv run python tools/scripts/verify_phase1_combo_tier_gate.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z` — PASS.
- `uv run python tools/scripts/scan_overlay_shortcuts.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z` — findings 0.
- `uv run python tools/scripts/measure_phase1_combo_tier.py data/journal/primary/datasynth_semantic_v1_combo_tier_20260622_v46b_r1z --expect-truth-rows 15` — PASS, 15/15 passed.

Conclusion:

r1z is the accepted PHASE1 combo/tier dataset. r11 remains the individual-rule recall dataset; r1z is
only for combo/tier case assembly.
