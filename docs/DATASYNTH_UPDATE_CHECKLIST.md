# DataSynth Update Checklist

Current production baseline: `data/journal/primary/datasynth/` freeze `v59` as of `2026-04-27`.

Latest freeze note: `data/journal/primary/datasynth/FREEZE_V59.md`.

This checklist is the required update path whenever DataSynth is regenerated, patched, promoted, or cleaned up.

Patch execution workflow is defined in [DATASYNTH_PATCH_WORKFLOW.md](DATASYNTH_PATCH_WORKFLOW.md). For non-trivial changes, follow the manifest-first workflow there before materializing a candidate.

## 1. Production Promotion

When a candidate becomes the production baseline, update or verify:

- `data/journal/primary/datasynth/journal_entries.csv`
- `data/journal/primary/datasynth/journal_entries_2022.csv`
- `data/journal/primary/datasynth/journal_entries_2023.csv`
- `data/journal/primary/datasynth/journal_entries_2024.csv`
- `data/journal/primary/datasynth/labels/anomaly_labels.csv`
- `data/journal/primary/datasynth/labels/anomaly_labels.json`
- `data/journal/primary/datasynth/labels/anomaly_labels.jsonl`
- `data/journal/primary/datasynth/labels/anomaly_labels_summary.json`
- `data/journal/primary/datasynth/generation_statistics.json`
- `data/journal/primary/datasynth/data_quality_stats.json`
- `data/journal/primary/datasynth/run_manifest.json`
- `data/journal/primary/datasynth/balance_validation.json`

Required production docs:

- `data/journal/primary/datasynth/FREEZE_VXX.md`
- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/OVERVIEW.md`

Required project docs:

- `docs/DECISION.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/DETECTION_RULES.md`
- `docs/핵심기능.MD`

## 2. Candidate-Only Patch

If only `data/journal/primary/datasynth_vXX_candidate/` is created:

- Add or update `data/journal/primary/datasynth_vXX_candidate/FREEZE_VXX_CANDIDATE.md`.
- Declare the exact source baseline and included prior manifests.
- Do not base a new candidate on an interrupted or unvalidated candidate.
- Do not update `data/journal/primary/datasynth/PREVIEW.md`.
- Do not update `data/journal/OVERVIEW.md`.
- Mention the current production baseline in any candidate test result.

Recommended wording:

`Current production DataSynth baseline is data/journal/primary/datasynth/ freeze v59 as of 2026-04-27. This report targets candidate datasynth_vXX_candidate.`

## 3. Label Contract Changes

When label meaning changes, update:

- `data/journal/primary/datasynth/labels/*`
- `docs/DETECTION_RULES.md`
- `docs/completed/DATASYNTH_INJECTION_SPEC.md` if the generator/injection contract changed
- relevant `tests/phase1_rulebase/test-results/*.md`
- validation/audit scripts that consume labels

Examples:

- v70-style truth split: `anomaly_labels.csv` may be audit issue truth, while exact L1 field contracts live in `labels/field_contract_truth.csv`
- `L1-01 := abs(sum(debit_amount)-sum(credit_amount)) > tolerance`, evaluated via `labels/l101_unbalanced_truth.csv`
- `L2-01 := approval_limit * 0.9 <= max(sum(debit_amount),sum(credit_amount)) < approval_limit`, evaluated via `labels/l201_just_below_threshold_truth.csv`
- L2 rule truth means the full candidate population that Phase 1 should surface, not only confirmed anomaly subsets
- `ExceededApprovalLimit := document_amount > approved_by.approval_limit`
- `SelfApproval := created_by == approved_by`; system/automated exceptions are handled later by detector/scoring logic
- `SegregationOfDutiesViolation := the same user or authority holder performs two roles that should be separated within the same transaction flow`
- `SkippedApproval := approval-required document with approved_by missing, including review-required candidates`
- `DuplicatePayment := duplicate-payment candidate, including reference, fallback, and recurring-looking candidates that Phase 1 should surface`
- `DuplicateEntry := exact, document-shape, reference, near, or split duplicate-entry candidate`
- `ExpenseCapitalization := expense-to-asset capitalization candidate`
- `ReversalEntry := reversal, cancellation, correction, clearing, offset, or reclassification candidate`
- L3 rule truth means the full review-candidate population that Phase 1 should surface, not only confirmed anomaly labels
- `MisclassifiedAccount/L3-01 := valid CoA account used in a mismatched business-process context`
- `Manual Entry/L3-02 := manual or adjustment source population`
- `Intercompany/L3-03 := related-party/intercompany transaction population`
- `RushedPeriodEnd/L3-04 := period-end/start and high-amount or manual posting candidate`
- `WeekendPosting/L3-05 := weekend or holiday posting candidate`
- `AfterHoursPosting/L3-06 := configured after-hours posting candidate`
- `BackdatedEntry/LatePosting/L3-07 := posting/document date gap above threshold`
- `MissingOrCorruptedDescription/L3-08 := missing, blank, corrupted, or legacy poor description`
- `SuspenseAccountAbuse/L3-09 := unresolved suspense/clearing account above aging threshold`
- `HighRiskAccountUse/L3-10 := configured sensitive/high-risk account touch`
- `RevenueCutoffMismatch/L3-11 := posting date and event date exceed cutoff tolerance`
- `ApprovalDateMissing := approval_date missing`
- automated/recurring missing approval-date cases are still rule truth; later code decides review/normal handling
- `WrongPeriod := fiscal_period does not match posting_date.month`
- `BenfordViolation` should not be used as document-level L4-02 truth
- `MisclassifiedAccount := valid CoA account used in an unusual business_process context; it must not use unregistered GL codes`
- `InvalidAccount := GL account outside the configured CoA`
- D01/D02 should not be evaluated by document-level `is_anomaly`

## 4. Sidecar Changes

When sidecars are added, removed, or structurally changed, update:

- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/OVERVIEW.md`
- `docs/DETECTION_RULES.md`
- `docs/핵심기능.MD`
- relevant test-result markdown under `tests/phase1_rulebase/test-results/`
- scripts that read the sidecar files

Current v59 high-priority sidecars:

- L1 audit split: `field_contract_truth*`, `l1_audit_issue_truth*`, `l1_field_only_normal_or_review*`
- L1-01: `l101_unbalanced_truth*`
- L2-01: `l201_just_below_threshold_truth*`
- L1-09: `approval_date_missing_cases*`
- L1-09 controls: `approval_date_present_normal_controls*`
- L1-08: `wrong_period_confirmed_anomalies*`, `wrong_period_normal_controls*`
- L2-02: `duplicate_payment_pairs*`, `duplicate_payment_negative_controls*`
- L3-01: `misclassified_account_coa_fix_cases*`
- D01: `account_activity_variance_truth*`, `account_activity_variance_normal_controls*`, `account_activity_variance_review_population*`
- D02: `monthly_pattern_shift_confirmed_anomalies*`, `monthly_pattern_shift_normal_controls*`, `monthly_pattern_shift_review_population*`, `monthly_pattern_shift_exclusions*`
- L4-02: `benford_finding_truth*`, `benford_adversarial_holdout*`
- L4-04: `rare_account_pair_confirmed_anomalies*`, `rare_account_pair_normal_controls*`, `rare_account_pair_review_population*`
- L3-10: `high_risk_account_confirmed_anomalies*`, `high_risk_account_normal_controls*`, `high_risk_account_review_population*`

## 5. Hotfix-Only Patch

If the patch is a small data hotfix:

- Create a patch manifest first unless the change is documentation-only.
- Record the hotfix in `FREEZE_VXX.md` or `FREEZE_VXX_CANDIDATE.md`.
- Update `PREVIEW.md` if production data changed.
- Update affected rule docs if label meaning changed.
- Verify row counts and relevant sidecar counts.

## 6. Numeric Snapshot Changes

When row counts, document counts, label counts, or key sidecar counts change, update:

- `data/journal/primary/datasynth/FREEZE_VXX.md`
- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/OVERVIEW.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/핵심기능.MD`

Minimum snapshot:

- combined rows/documents
- year-level rows/documents
- `anomaly_labels.csv` rows
- main sidecar rows
- column count
- company count

## 7. Historical Reports

Historical reports do not need to be rewritten fully. Add or preserve a note that the report is historical when it references old candidate paths or old freeze versions.

Recommended wording:

`Historical report. Current production DataSynth baseline is data/journal/primary/datasynth/ freeze v59 as of 2026-04-27.`

## 8. Promotion Verification

Before saying a promotion is complete, verify:

1. `journal_entries.csv` row count.
2. Year file row counts.
3. `labels/anomaly_labels.csv` row count.
4. New sidecar counts.
5. Candidate lineage block declares source baseline and included manifests.
6. Anti-fitting check is documented when the patch changes labels or truth sidecars.
7. Year/company counts are intentionally varied or explicitly marked as fixture-only.
8. `PREVIEW.md`, `FREEZE_VXX.md`, and `OVERVIEW.md` reflect the promoted version.
9. `DETECTION_RULES.md` contains the current evaluation contract.
10. Candidate cleanup did not remove the promoted `data/journal/primary/datasynth/` directory.
11. `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth` passes.
12. For candidate-to-candidate promotion, the previous baseline regression gate passes:
    `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_vXX_candidate --previous data/journal/primary/datasynth_vYY_candidate`.
13. Field-contract labels such as L1-05 `SelfApproval`, L1-04 `ExceededApprovalLimit`, L1-06 `SegregationOfDutiesViolation`, and L1-07 `SkippedApproval` match their source journal fields exactly, not just minimum label counts.

## 9. Storage Cleanup Policy

To control local data size:

- Keep production: `data/journal/primary/datasynth/`
- Keep recent candidates needed for rollback/debugging.
- As of v59, candidates `datasynth_v50_candidate` through `datasynth_v59_candidate` are retained.
- Remove older scratch directories such as old backups, drift checks, coverage checks, and candidates before the retention window after promotion verification.

Never delete production `data/journal/primary/datasynth/` as part of cleanup.

## 10. Current v59 Snapshot

- Production path: `data/journal/primary/datasynth/`
- Freeze: `v59`
- Rows: `1,109,435`
- Documents: `319,193`
- Companies: `3`
- Columns: `52`
- `labels/anomaly_labels.csv`: `2,843`
- MisclassifiedAccount rows patched to valid CoA accounts: `19`
- MisclassifiedAccount rows still outside CoA: `0`
- Unregistered GL docs without InvalidAccount label: `0`
- L1-09 labels/cases: `26 / 26`
- L2-02 labels/pairs/controls: `33 / 33 / 18`
- D01 truth/control/review: `336 / 504 / 840`
- D02 confirmed/control/review/exclusions: `346 / 194 / 497 / 2,059`
- Benford group truth/holdout: `100 / 176`

## 11. Current Rule-Truth Candidate Snapshot

This is not production until explicitly promoted.

- Latest candidate path: `data/journal/primary/datasynth_v81_candidate`
- Lineage: `v74 CoA backfill -> v75 L2 rule truth -> v76 L3/L4 rule truth -> v77 L1 review truth -> v79 safe broad L1 truth -> v80 L1-06/L3-12 split -> v81 realistic approval metadata`
- `v78_candidate` is superseded and should not be promoted because journal CSV patching happened on hardlinked candidate files.
- Required truth gate: `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v81_candidate`
- Last gate result: `failures: []`

Promotion checklist additions:

- Confirm evaluation code reads `labels/rule_truth.csv` for Phase 1 contract metrics.
- Confirm evaluation code does not use `anomaly_labels.csv` alone as Phase 1 truth.
- Confirm broad review-population rules such as L1-09 and L3-04 are reported as candidate coverage, not audit issue precision.
- Confirm broad L1 rules are reported correctly:
  - L1-05: `created_by == approved_by`, including automated/system contexts.
  - L1-06: direct SoD marker or direct IT/admin business posting evidence only.
  - L1-07: `approved_by` missing. v81 should not be dominated by automated/recurring routine documents.
  - L1-09: `approval_date` missing. v81 should retain only realistic manual/adjustment gaps plus confirmed cases.
- Confirm L3-12 is reported as work-scope review population, not as confirmed SoD violation.
- Preserve `anomaly_labels.csv` as audit/injection issue labels.
- Do not delete `datasynth_v81_candidate` until production promotion or a later candidate supersedes it.
- Any future builder that modifies journal CSVs must use physical copy, not hardlinks.
