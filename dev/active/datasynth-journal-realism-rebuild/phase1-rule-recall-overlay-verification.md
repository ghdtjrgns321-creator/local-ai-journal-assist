# PHASE1 Rule Recall Overlay Verification

## Purpose

Recall dataset verification contract.
PHASE1 rule-recall overlay 수정 중 새 버그가 발견되거나 재발 가능성이 있는 결함이 확인되면, 해당 검사는
본 문서 또는 [phase1-abnormal-overlay-test-catalog.md](./phase1-abnormal-overlay-test-catalog.md)에
regression gate로 추가하고 이후 PHASE1 recall overlay 재생성의 자동 실행 대상에 포함한다.

## Hard Invariants

- Output dataset is separate from p3_2_overlay.
- Base normal v29 is reused and not regenerated.
- Output distinct document_id count must equal v29 distinct document_id count.
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

Use dev/active/phase1-rule-recall-checklist.md only. Locked corrections: L2-01 near approval limit; L2-04 asset debit plus expense credit in one document; L4-01 revenue zscore population rule.

## Required Truth Fields

rule_id, case_kind, case_index, natural_unit_type, natural_unit_id, member_document_ids, base_document_ids, variant_id, is_boundary_control, expected_detector_outcome, expected_measurement_unit, raw_trigger_summary.

## Acceptance

1. 39 of 39 rules in truth.
2. Boundary controls are labelled normal and expected no_fire.
3. scan_overlay_shortcuts.py findings zero.
4. measure_phase1_detector_catch.py runs with expected truth unit count.
5. Reports include per-rule recall numerator denominator and control false positives.
6. `audit_overlay_injection.py` CoA coverage gate passes: journal accounts are covered by
   dataset CoA and global config CoA, with only L1-03 standard invalid-account docs allowed
   to be absent.
7. pytest tests -q --continue-on-collection-errors has no new failure or exact blocker is recorded.

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
