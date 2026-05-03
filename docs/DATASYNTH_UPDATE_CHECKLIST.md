# DataSynth Update Checklist

Current production baseline: `data/journal/primary/datasynth/` freeze `v126` as of `2026-05-02`.

Latest freeze note: `data/journal/primary/datasynth/FREEZE_V126.md`.

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

Current split derivatives:

- `data/journal/primary/datasynth_contract/`: contract truth and sidecar-context validation split.
- `data/journal/primary/datasynth_manipulation/`: actual manipulation/injected issue truth split.
- Keep `data/journal/primary/datasynth/` as the compatibility production baseline until loaders explicitly support the split datasets.

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
- Keep `journal_entries_YYYY.csv/json` as deterministic partitions of `journal_entries.csv`. If either representation is patched, regenerate and verify the other representation before evaluating rules.

Recommended wording:

`Current production DataSynth baseline is data/journal/primary/datasynth/ freeze v126 as of 2026-05-02. This report targets candidate datasynth_vXX_candidate.`

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
- `L3-01 := valid CoA account flagged by the current configured process/account mismatch detector contract`
- `Manual Entry/L3-02 := manual or adjustment source population`
- `Intercompany/L3-03 := related-party/intercompany transaction population`
- `RushedPeriodEnd/L3-04 := period-end/start posting candidate; high amount, manual source, and injected RushedPeriodEnd scenarios are priority/scenario signals`
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
- `L4-03 := amount_zscore above threshold and global high-amount guard passed`; `UnusuallyHighAmount` / `StatisticalOutlier` are injected anomaly subsets, not the full rule-truth denominator
- `MisclassifiedAccount := injected/account-classification issue label; do not use it alone as L3-01 rule truth`
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

Current v126 high-priority sidecars:

- L1 audit split: `field_contract_truth*`, `l1_audit_issue_truth*`, `l1_field_only_normal_or_review*`
- L1-01: `l101_unbalanced_truth*`
- L2-01: `l201_just_below_threshold_truth*`
- L1-09: `approval_date_missing_cases*`
- L1-09 controls: `approval_date_present_normal_controls*`
- L1-08: `wrong_period_confirmed_anomalies*`, `wrong_period_normal_controls*`
- L1-07 system/control-gap context: `skipped_approval_system_gap_controls*` (`skipped_approval_normal_controls*` remains as a legacy gate-compatible alias, not a true normal control)
- L1-08 non-audit rule-truth context: `wrong_period_non_audit_issue_truth*` (`wrongperiod_negative_controls*` remains as a legacy traceability alias, not a true negative control)
- L1-06 review-only context: `sod_review_population*` with `sod_review_signal=True` and `was_sod_violation=False`
- L2-02: `duplicate_payment_pairs*`, `duplicate_payment_negative_controls*`
- L3-01: `l301_account_process_mismatch_review_population*`; legacy CoA-boundary repair evidence remains in `misclassified_account_coa_fix_cases*`
- L3-06: `afterhours_review_population*`, `normal_after_hours_context*`, `afterhours_negative_controls*`, `afterhours_limitation_controls*`
- D01: `account_activity_variance_truth*`, `account_activity_variance_normal_controls*`, `account_activity_variance_review_population*`, `account_activity_variance_stable_controls*`, `account_activity_variance_near_threshold_controls*`, `account_activity_variance_exclusions*`
- D02: `monthly_pattern_shift_confirmed_anomalies*`, `monthly_pattern_shift_truth*`, `monthly_pattern_shift_normal_controls*`, `monthly_pattern_shift_raw_positive_normal_contexts*`, `monthly_pattern_shift_guardrail_negative_controls*`, `monthly_pattern_shift_review_population*`, `monthly_pattern_shift_exclusions*`
- L4-02: `benford_finding_truth*`, `benford_adversarial_holdout*`
- L4 detector universe aliases: `revenue_outlier_detector_universe*`, `high_amount_detector_universe*`, `rare_account_pair_detector_universe*`, `abnormal_hours_behavior_detector_universe*`, `batch_detector_universe*`
- L4 context aliases: `high_amount_legitimate_contexts*`, `high_amount_boundary_contexts*`, `rare_account_pair_legitimate_contexts*`, `batch_legitimate_contexts*`, `batch_boundary_contexts*`, `revenue_outlier_boundary_contexts*`
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

`Historical report. Current production DataSynth baseline is data/journal/primary/datasynth/ freeze v126 as of 2026-05-02.`

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
- As of v126, production is `datasynth/`; keep only recent candidates needed for rollback/debugging.
- Remove older scratch directories such as old backups, drift checks, coverage checks, and candidates before the retention window after promotion verification.

Never delete production `data/journal/primary/datasynth/` as part of cleanup.

## 10. Current v126 Snapshot

- Production path: `data/journal/primary/datasynth/`
- Freeze: `v126`
- Rows: `1,109,435`
- Documents: `319,193`
- Companies: `3`
- Columns: `52`
- `labels/anomaly_labels.csv`: `3,149`
- Audit issue label documents: `2,992`
- `labels/rule_truth.csv`: `316,839`
- MisclassifiedAccount rows patched to valid CoA accounts: `19`
- MisclassifiedAccount rows still outside CoA: `0`
- Unregistered GL docs without InvalidAccount label: `0`
- L1-09 labels/cases: `26 / 26`
- L2-02 labels/pairs/controls: `33 / 33 / 18`
- D01 truth/control/review: `336 / 504 / 840`
- D02 confirmed/control/review/exclusions: `346 / 194 / 497 / 2,059`
- Benford group truth/holdout: `99 / 176`

## 11. Current Rule-Truth Candidate Snapshot

v126 has been promoted to production. Keep this section as the latest candidate lineage until a newer candidate is built.

- Latest candidate path: `data/journal/primary/datasynth_v126_candidate`
- Lineage: `v74 CoA backfill -> v75 L2 rule truth -> v76 L3/L4 rule truth -> v77 L1 review truth -> v79 safe broad L1 truth -> v80 L1-06/L3-12 split -> v81 realistic approval metadata -> v82 L1 boundary controls -> v83 L1-05 consistency fix -> v84 manipulated-entry truth -> v85 L3-01 detector-contract truth -> v86 L3-01 distribution realism -> v87 L3-03 detector-contract truth -> v88 L3-02 source distribution realism -> v89 L3-05 calendar truth -> v90 L1-06 severity diversity -> v91 L3-06 after-hours truth -> v92 L3-09 stale suspense truth cleanup -> v93 L1-02 missing-field diversity -> v94 L3-04 period-window truth -> v95 L3-12 user-level truth -> v96 L3-12 bucket diversity -> v97 BatchAnomaly confirmed-label diversity -> v98 manipulated-entry company diversity -> v99 DuplicatePayment pair diversity -> v100 minor source realism -> v101 L3-04 detector-window truth -> v102 L1 sidecar semantics cleanup -> v103 L3 stale truth cleanup -> v104 L3-05 calendar realism -> v105 L3 sidecar context cleanup -> v106 L3-11 cutoff truth realignment -> v107 L4-01 revenue z-score truth realignment -> v108 L4-02 Benford group truth realignment -> v109 L3-12 candidate/scored truth split -> v110 L4-04 detector-universe truth realignment -> v111 L4-05 combined-context truth realignment -> v112 L4-06 batch detector-universe truth realignment -> v113 L2-02 duplicate-payment detector-universe truth realignment -> v114 stale detector-contract truth refresh -> v115 L2-03/L2-04/L2-05 stale truth purge and current-detector rebuild -> v116 active truth metadata cleanup -> v117 L2 independent scenario/control sidecars -> v118 sidecar purpose manifest -> v119 L3 sidecar semantics cleanup -> v120 L4 sidecar semantics cleanup -> v121 D01/D02 macro sidecar semantics cleanup -> v122 year journal file consistency cleanup -> v123 L4-06 truth refresh -> v124 L3/D A-axis truth refresh -> v125 L2 pair/reversal truth split -> v126 L2 A-axis contract truth refresh`
- `v78_candidate` is superseded and should not be promoted because journal CSV patching happened on hardlinked candidate files.
- Required truth gate: `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_v126_candidate`
- Required A-axis truth alignment gate: `python tools/scripts/check_datasynth_axis_truth_alignment.py data/journal/primary/datasynth_v126_candidate`
- Required stale scan: verify all active `rule_truth_*` files have `source_candidate=v126`; detector-diff scan remains available for selected expensive rules.
- Required sidecar policy check: independent behavioral evaluation may only use rows in `labels/sidecar_manifest.csv` where `allowed_for_independent_sidecar_eval=True`.
- Last gate result: `failures: []`
- Last L3-01 alignment check: detector docs `2,419`, truth docs `2,419`, detector/truth diff `0`
- Last L3-01 distribution: P2P `1,059`, O2C `520`, H2R `380`, TRE `300`, A2R `160`
- Last L3-03 alignment check: detector docs `30,377`, truth docs `30,377`, population truth docs `30,377`, all diffs `0`
- Last L3-03 distribution: `2022=10,075`, `2023=10,186`, `2024=10,116`
- Last L3-02 alignment check: actual manual/adjustment docs `86,808`, truth docs `86,808`, population truth docs `86,808`, all diffs `0`
- Last L3-02 distribution: `2022=28,947`, `2023=28,687`, `2024=29,174`
- Last L3-05 alignment check: actual weekend/holiday docs `24,318`, truth docs `24,318`, population truth docs `24,318`, all diffs `0`
- Last L3-05 distribution: `2022=6,011`, `2023=9,354`, `2024=8,953`
- Last L1-06 severity check: truth docs `19`, detector hit docs `19`, detector hit rows `64`
- Last L1-06 score distribution: score `0.70=24`, `0.80=33`, `0.95=7`
- Last L1-06 bucket distribution: `direct_medium=7`, `direct_high=9`, `direct_critical=3`
- Last L1-06 conflict distribution: `preparer_approver=11`, `purchase_payment=5`, `cash_disbursement=2`, `treasury_payment=1`
- Last L3-06 alignment check: detector docs `7,507`, truth docs `7,507`, detector/truth diff `0`
- Last L3-06 distribution: `2022=2,622`, `2023=2,444`, `2024=2,441`; automated `3,633`, interface `1,004`, recurring `1,279`, manual `1,524`, adjustment `67`
- Last L3-06 score distribution: score `0.20=4,773`, `0.45=2,734`
- Last L3-09 alignment check: detector docs `1,091`, truth docs `1,091`, review population docs `1,091`, all diffs `0`
- Last L3-09 cleanup: removed stale truth docs `6dded142-3eaa-41dc-a85e-d3bc84b1116f`, `78b6fc4d-2f33-40ac-ab88-88813eab466d`
- Last L3-09 distribution: `2022=356`, `2023=390`, `2024=345`
- Last L1-02 alignment check: detector docs `156`, truth docs `156`, detector/truth diff `0`
- Last L1-02 distribution: `2022=46`, `2023=49`, `2024=61`
- Last L1-02 missing field distribution: `gl_account=96`, `document_date=13`, `document_type=12`, `fiscal_period=12`, `posting_date=11`, `debit_amount=11`, `credit_amount=10`, `company_code=9`
- Last L1-02 score distribution: `0.42=13`, `0.48=12`, `0.56=10`, `0.62=7`, `0.72=14`, `0.74=86`, `0.78=4`, `0.80=6`, `0.86=4`
- Last L1-01 alignment after L1-02 amount omissions: detector docs `316`, truth docs `316`, detector/truth diff `0`
- Last L3-04 alignment check: expected detector-window docs `141,375`, truth docs `141,375`, expected/truth diff `0`
- Last L3-04 distribution follows current v124 year-file journal; count `141,375`, split `2022=46,822`, `2023=46,614`, `2024=47,939`
- Last L3-04 boundary fix: added `10,843` documents that satisfy `posting_date.day <= 5 OR days_to_month_end <= 5` but were missing from the prior last-five-days truth.
- Last L1 sidecar semantics cleanup: `skipped_approval_system_gap_controls*` added with `79` docs; `wrong_period_non_audit_issue_truth*` added with `140` docs; `sod_review_population*` now uses `was_sod_violation=False`, `legacy_was_sod_violation=True`, and `sod_review_signal=True`.
- Last L3 stale truth cleanup: L3-02 added `3` current manual/adjustment documents; L3-03 removed `1` stale document whose GL account is now missing; L3-05 removed `3` stale documents whose posting date is now missing.
- Last L3-05 calendar realism pass: moved `11,547` normal automated/interface/recurring documents (`39,336` journal rows) from weekend/holiday posting dates to nearby same-month business days; protected anomaly-labeled, L1-08, L3-07, L3-11, manual, and adjustment documents; L3-05 ratio is now `4.00%`.
- Last L3 sidecar context cleanup: `normal_weekend_context=12,373`, `period_end_normal_close_context=3,600`, `period_end_priority_context=3,009`, `manual_entry_normal_context=3,600`, `manual_override_confirmed_anomalies=3`, `manual_sensitive_account_context=389`. L3-06 after-hours normal context is refined in v119; L3-03 IC exception sidecars are case-level drilldowns, not document-level subsets.
- Last L3-11 cutoff truth realignment: current journal calculation docs `130`, `rule_truth_L3_11` docs `130`, detector/truth diff `0`; v124 removes 3 stale truth documents whose current `posting_date=2024-01-01` no longer exceeds the configured business-day cutoff threshold.
- Last L3-11 cutoff sidecars: `cutoff_review_population=130`, `cutoff_confirmed_anomalies=107`, `cutoff_normal_controls=276`.
- Last L4-01 revenue z-score truth realignment: feature-backed detector docs `964`, `rule_truth_L4_01` docs `964`, detector/truth diff `0`; removed 3 stale non-revenue-account truth documents and added 2 current revenue z-score hits.
- Last L4-01 sidecars: `revenue_outlier_review_population=964`, `revenue_outlier_boundary_controls=212`.
- Last L4-02 Benford group truth realignment: detector finding groups `99`, `rule_truth_L4_02` groups `99`, detector/truth diff `0`; removed 3 stale groups and added 2 current groups.
- Last L4-02 sidecars: `benford_finding_truth=99`, `benford_drilldown_candidates=24,148`, `benford_normal_groups=318`, `benford_skipped_small_groups=3,267`, `benford_adversarial_holdout=176`.
- Last L4-04 rare account-pair truth realignment: detector docs `4,091`, `rule_truth_L4_04` docs `4,091`, `rare_account_pair_review_population` docs `4,091`, detector/truth diff `0`; added `645` current detector docs and removed `57` stale truth docs.
- Last L4-04 score buckets: `single_rare_pair=3,380`, `multiple_rare_pairs=468`, `large_doc_distinct_pair=243`; confirmed subset `52` docs with `46` currently in detector truth; normal controls `258` docs with `256` currently in detector truth.
- Last L4-05 abnormal-hours truth realignment: three-year combined-context detector docs `4,964`, `rule_truth_L4_05` docs `4,964`, `abnormal_hours_behavior_review_population` docs `4,964`, detector/truth diff `0`; existing confirmed subset `27` docs all remain in truth.
- Last L4-05 score buckets: `system_context_review=3,373`, `high_context_midnight=1,577`, `rapid_approval=14`. Strict L4-05 evaluation must run detector on combined 2022-2024 context and split results by `fiscal_year`; annual single-year runs are robustness checks only.
- Last L4-03 stale refresh: detector docs `4,015`, `rule_truth_L4_03` docs `4,015`, detector/truth diff `0`; added `5` current detector docs and removed `4` stale truth docs.
- Last L4-06 stale refresh: detector docs `686`, `rule_truth_L4_06` docs `686`, `batch_review_population` docs `686`, detector/truth diff `0`; removed `175` stale truth docs.
- Last L4-06 distribution after v114: `batch_review_docs=686`, `amount_outlier_only_docs=517`, `simultaneous_only_docs=140`, `multi_signal_batch_docs=29`.
- Last L4-06 control split after v114: `batch_normal_controls=250` with raw hit overlap `0`; `batch_boundary_controls=128` with raw hit overlap `30`. Both are control sidecars only and are excluded from strict `rule_truth_L4_06`.
- Last L2-02 duplicate-payment pair-key cleanup: v126 keeps `rule_truth_L2_02=384` and `duplicate_payment_review_population=384`, adds stable `pair_key` / `duplicate_pair_key`, and maps `33` confirmed `duplicate_payment_pairs` into `duplicate_group_id`.
- Last L2-02 reason split: `amount_partner_fallback=351`, `reference_match=26`, `mixed_reference_fallback=7`; year split `2022=156`, `2023=116`, `2024=112`; A-axis pair evaluation should use `pair_key`.
- Last L2-02 control split: `duplicate_payment_pairs=33` with truth overlap `33`; `duplicate_payment_negative_controls=18` with truth overlap `0`.
- Last L2 stale truth purge: v115 deletes copied L2-03/L2-04/L2-05 rule-truth families from the active candidate and rebuilds them from current detector output.
- Last L2-03 truth: `rule_truth_L2_03=111`; v126 rebuilds from the active `b05_duplicate_entry()` A-axis evaluator and clarifies reason codes as `exact_duplicate=64`, `near_duplicate=28`, `ic_split_duplicate=12`, `o2c_offset_duplicate=4`, `split_duplicate=3`.
- Last L2-04 truth: detector docs `1,098`, `rule_truth_L2_04` docs `1,098`; queue split `review=529`, `low_review=418`, `immediate=78`, `population=73`.
- Last L2-05 truth split: v126 restores A-axis `rule_truth_L2_05` to the raw current detector universe: `80` documents. The `52` strict documents remain in `reversal_strict_truth`; `28` weak candidates remain in `reversal_weak_review_population` and are still A-axis raw truth.
- Historical v116 active truth metadata cleanup: v116 first removed legacy `source_candidate` values from active `rule_truth_*`; v126 is the current active metadata baseline.
- Historical v116 active candidate artifact cleanup: v116 root kept only `FREEZE_V116_CANDIDATE.md` and `V116_TRUTH_METADATA_CLEANUP.json` among versioned freeze/patch manifests at that time; v126 is the current artifact baseline.
- Last L2 independent sidecars: v117 adds detector-independent behavioral sidecars without changing journal rows or `rule_truth` membership.
- L2 independent confirmed/plausible sidecars: `duplicate_entry_confirmed_scenarios=67`, `expense_capitalization_plausible_cases=33`, `reversal_pattern_plausible_cases=51`.
- L2 independent negative/control sidecars: `duplicate_entry_negative_controls=90`, `expense_capitalization_normal_capex_controls=90`, `reversal_pattern_normal_clearing_controls=90`.
- Important: `*_review_population` files are detector-contract snapshots. They are not independent validation sidecars. Independent behavior checks must use the v117 L2 scenario/control sidecars.
- Last active candidate artifact cleanup: v117 root keeps only `FREEZE_V117_CANDIDATE.md` and `V117_L2_INDEPENDENT_SIDECARS.json` among versioned freeze/patch manifests.
- Last sidecar manifest: v118 adds `labels/sidecar_manifest.csv/json` with `146` classified sidecars. Purpose split is `realism_control=33`, `review_population=20`, `detector_contract_universe=4`, `rule_truth_context=2`, `rule_truth_but_not_audit_issue=1`, `legacy_alias=2`, `contract_manifest=84`.
- Last independent sidecar allowlist: `34` sidecars have `allowed_for_independent_sidecar_eval=True`.
- Last L1 sidecar classification: `delegated_approval_controls`, `late_approval_boundary_controls`, `post_approval_change_controls`, `approver_master_mapping_issues`, and `l1_realism_normal_controls` are realism controls; `sod_review_population` is review population; `wrong_period_non_audit_issue_truth`, `skipped_approval_system_gap_controls`, and `system_control_gap_controls` are not independent realism controls.
- Last active candidate artifact cleanup: v118 root keeps only `FREEZE_V118_CANDIDATE.md` and `V118_SIDECAR_MANIFEST.json` among versioned freeze/patch manifests.
- Last L3-06 sidecar cleanup: v119 removes `20` anomaly-labeled documents from `afterhours_normal_context_within_review_population` and `normal_after_hours_context`; the clean normal context now has `6,952` docs with anomaly-label overlap `0`.
- Last L3-06 cross-rule context: v119 adds `afterhours_cross_rule_labeled_context=20` with `DuplicatePayment=17`, `BatchAnomaly=3`.
- Last L3-03 IC drilldown cleanup: v119 adds L3-03 link columns to `ic_unmatched_cases=21`, `ic_amount_mismatch_cases=16`, `ic_timing_gap_cases=14`, `transfer_pricing_review_cases=13`; all `64` combined IC exception cases have target/counterpart links to L3-03 rule truth.
- Last sidecar manifest after v120: `164` rows; L4 role split is `strict_truth_alias=17`, `normal_context=10`, `boundary_control=8`, `confirmed_subset=5`, `adversarial_holdout=2`, `drilldown_candidate=2`, `contract_manifest=2`.
- Last L4 sidecar semantics cleanup: v120 adds detector-universe aliases `revenue_outlier_detector_universe=964`, `high_amount_detector_universe=4,015`, `rare_account_pair_detector_universe=4,091`, `abnormal_hours_behavior_detector_universe=4,964`, `batch_detector_universe=686`; all have diff `0` against their owner `rule_truth_L4_*`.
- Last L4 context aliases: v120 adds `high_amount_legitimate_contexts=177`, `high_amount_boundary_contexts=116`, `rare_account_pair_legitimate_contexts=258`, `batch_legitimate_contexts=250`, `batch_boundary_contexts=128`, `revenue_outlier_boundary_contexts=212`.
- Last L4 context policy: `normal_controls` and `boundary_controls` are not strict negative controls. They are legitimate/boundary contexts and may overlap raw detector universe; e.g. `rare_account_pair_legitimate_contexts` overlaps L4-04 universe by `256/258`, and `batch_boundary_contexts` overlaps L4-06 universe by `30/128`.
- Last D01/D02 macro sidecar cleanup: v121 keeps D01/D02 rule-truth membership unchanged and adds macro metadata for group-level evaluation. D01 adds `account_activity_variance_stable_controls=240`, `account_activity_variance_near_threshold_controls=120`, and `account_activity_variance_exclusions=96`.
- Last D02 macro sidecar cleanup: v121 keeps confirmed/review counts unchanged and splits `monthly_pattern_shift_normal_controls=194` into `monthly_pattern_shift_raw_positive_normal_contexts=151` and `monthly_pattern_shift_guardrail_negative_controls=43`. `monthly_pattern_shift_truth=346` is a clearer alias for confirmed macro truth.
- Last D01/D02 manifest cleanup: v121 sidecar manifest has `172` rows; macro sidecar roles are `strict_truth_alias=4`, `confirmed_subset=3`, `normal_context=4`, `boundary_control=2`, `contract_manifest=2`.
- Last D01/D02 interpretation policy: D01/D02 are `fiscal_year + company_code + gl_account` macro review signals. Their normal controls may be raw-positive review contexts, not detector false positives. Do not evaluate them with document-level `is_anomaly`.
- Last year-file consistency cleanup: v122 regenerates `journal_entries_2022/2023/2024.csv/json` as direct partitions of `journal_entries.csv`. Before the patch, year files had `posting_date/source` mismatches in all years and `fiscal_period` mismatches in 2023/2024; after the patch, checked mismatches are `0`.
- Last L1-02 year-file fix: v122 aligns the two fiscal-period-missing documents `8c1f9639-51f4-42f0-8280-1b0486b7090b` and `fd85b1ca-3976-4dbb-867d-cd3089257afa` so the year files also have `fiscal_period` blank.
- Last L4-06 truth refresh: v123 rebuilds `rule_truth_L4_06*`, `batch_review_population*`, and `batch_detector_universe*` from the current year-file detector output after v122. L4-06 review docs increased from `686` to `692`; added docs are the six 2023-09-30 23:25:00 automated simultaneous-creation documents.
- Last L4-06 detector-universe alignment: `rule_truth_L4_06`, `batch_review_population`, and `batch_detector_universe` are all `692` documents with diff `0`.
- Last L3/D A-axis truth refresh: v124 rebuilds `rule_truth_L3_02`, `rule_truth_L3_04`, `rule_truth_L3_05`, and `rule_truth_L3_11` from current `journal_entries_YYYY.csv` and pins D01/D02 A-axis to macro `rule_truth_D01/D02` review universes.
- Last D01/D02 A-axis policy: D01 A-axis truth `840` groups, confirmed subset `336`; D02 A-axis truth `497` groups, confirmed subset `346`. Confirmed macro subsets are not the A-axis denominator.
- Last A-axis truth alignment gate: `check_datasynth_axis_truth_alignment.py` returns `failures: []` for L3-02/L3-04/L3-05/L3-11 and D01/D02.
- Historical v124 active truth metadata cleanup: v124 rewrote active `rule_truth_*` source metadata to `source_candidate=v124`; v126 is now the current active metadata baseline.
- Historical v124 active candidate artifact cleanup: v124 root kept only `FREEZE_V124_CANDIDATE.md` and `V124_L3_D_AXIS_TRUTH_REFRESH.json` among versioned freeze/patch manifests at that time.
- Last L2 A-axis contract truth refresh: v126 keeps L2-02 `pair_key`, rebuilds L2-03 from the active A-axis evaluator, and restores L2-05 `rule_truth` to the raw detector universe. Active `rule_truth_*` metadata now uses `source_candidate=v126`.
- Last active candidate artifact cleanup: v126 root keeps only `FREEZE_V126_CANDIDATE.md` and `V126_L2_CONTRACT_TRUTH_REFRESH.json` among versioned freeze/patch manifests.
- Last L3-12 user-level truth check: truth user-years `64`, review population user-years `64`, projection user-years `64`
- Last L3-12 distribution: `2022=21`, `2023=21`, `2024=22`; document projection docs `262,846`, projected rows `883,087`
- Last L3-12 bucket diversity: manual-sensitive `38`, system-mixed `15`, leadership-broad `11`; detector bucket remains preserved as `compound_scope_concentration=64`
- Last L3-12 candidate/scored split: raw candidate user-years `127`, scored user-years `64`; candidate split `2022=43`, `2023=42`, `2024=42`; bucket split `system_scope_observation=63`, `compound_scope_concentration=49`, `system_mixed_scope_review=15`; raw candidate document projection docs `318,993`.
- Last BatchAnomaly confirmed-label diversity: total `175`; v112 confirmed subset is selected only from current L4-06 detector truth and uses source automated `113`, interface `62`; recurring-only source is no longer confirmed L4-06 truth.
- Last manipulated-entry diversity: total `420`; company C001 `147`, C002 `139`, C003 `134`; scenario/year counts preserved; text marker docs `420`, outside truth `0`
- Last DuplicatePayment pair diversity: total `33`; company C001 `11`, C002 `11`, C003 `11`; year 2022 `19`, 2023 `7`, 2024 `7`; variant exact `7`, reference_blank `7`, reference_variant `7`, date_shifted `6`, amount_rounding `6`; v113 keeps these as confirmed pair metadata inside the broader L2-02 rule truth.
- Last minor source realism pass: reclassified documents `6,084`; year 2022 `2,041`, 2023 `2,010`, 2024 `2,033`; L3-02 source manual `76,386`, adjustment `10,422`; L4-05 source manual `18`, adjustment `9`

Promotion checklist additions:

- Confirm evaluation code reads `labels/rule_truth.csv` for Phase 1 contract metrics.
- Confirm evaluation code does not use `anomaly_labels.csv` alone as Phase 1 truth.
- Confirm broad review-population rules such as L1-09 and L3-04 are reported as candidate coverage, not audit issue precision.
- Confirm broad L1 rules are reported correctly:
  - L1-05: `created_by == approved_by`, including automated/system contexts.
  - L1-06: direct SoD marker or direct IT/admin business posting evidence only.
  - L1-07: `approved_by` missing. v81 should not be dominated by automated/recurring routine documents.
  - L1-09: `approval_date` missing. v81 should retain only realistic manual/adjustment gaps plus confirmed cases.
- Confirm approval boundary/control sidecars stay out of injected fraud labels unless they create an actual field-contract gap:
  - `late_approval_boundary_controls.csv`
  - `delegated_approval_controls.csv`
  - `approver_master_mapping_issues.csv`
  - `post_approval_change_controls.csv`
  - `system_control_gap_controls.csv`
- Confirm manipulated-entry truth is evaluated separately from rule truth:
  - `manipulated_entry_truth.csv`
  - `manipulated_entry_scenario_summary.csv`
- Confirm L3-12 is reported as user-level work-scope review population, not as document-level strict truth or confirmed SoD violation.
- Preserve `anomaly_labels.csv` as audit/injection issue labels.
- Do not delete `datasynth_v108_candidate` until production promotion or a later candidate supersedes it.
- Any future builder that modifies journal CSVs must use physical copy, not hardlinks.
