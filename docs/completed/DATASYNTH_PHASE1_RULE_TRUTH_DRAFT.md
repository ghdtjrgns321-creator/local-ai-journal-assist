# DataSynth Phase 1 Rule Truth Draft

Status: draft, not final.

Purpose: fix the repeated mismatch between Phase 1 rule hits and DataSynth labels by separating rule-condition truth from injected/audit issue truth.

## Core Decision

Phase 1 rules are candidate-generation rules, not final answer classifiers.

Therefore Phase 1 rule evaluation must answer:

> Does the document actually satisfy this rule's condition?

It must not answer:

> Did the generator intentionally inject this anomaly label?

If a document satisfies a Phase 1 rule condition, it is positive for that rule even when the condition arose naturally, accidentally, or through another injected scenario.

## Truth Layers

### 1. `rule_truth`

Primary truth for Phase 1 rule implementation.

Use for:

- rule recall/precision against rule definitions,
- regression tests,
- detecting field-contract drift,
- avoiding false FP/FN caused by causal labels.

Rule truth is derived from source fields and master data. It includes both immediate
violations and review candidates when the Phase 1 rule is designed to surface both.
The rule truth layer does not decide whether a hit is a final audit issue.

Example:

- L1-01 positive if debit/credit totals are actually imbalanced.
- L2-01 positive if amount is actually just below the approver's limit.
- L1-09 positive if approval date is missing.

### 2. `injected_issue_truth`

Truth for generator-intended scenarios.

Use for:

- scenario coverage,
- Phase 2/3 explanation and classification,
- checking whether generated anomalies were materialized correctly.

Example:

- `DecimalError`
- `RoundingError`
- `JustBelowThreshold`
- `RevenueManipulation`
- `DuplicatePayment`

### 3. `audit_issue_truth`

Truth for cases that should be treated as meaningful audit issues.

Use for:

- portfolio-facing benchmark,
- prioritization quality,
- queue quality,
- severity/triage evaluation.

Not every `rule_truth` item is an audit issue.

### 4. `normal_control`

Normal or acceptable records that look similar to rule hits or audit issues.

Use for:

- realism,
- hard negatives,
- priority/triage checks.

### 5. `review_population`

Broad population that a rule may surface for auditor review.

Use for:

- coverage,
- queue sizing,
- review workflow tests.

For Phase 1 rule implementation tests, review items can also be positive `rule_truth`
when the rule is expected to catch them. The later scoring/case-building layer decides
whether a hit is an immediate violation, review-only, low priority, or normal control.

## File Layout Target

Recommended target structure:

- `labels/rule_truth.csv`
- `labels/rule_truth_L1_01.csv`
- `labels/rule_truth_L1_02.csv`
- `labels/rule_truth_L1_03.csv`
- `labels/rule_truth_L1_04.csv`
- `labels/rule_truth_L1_05.csv`
- `labels/rule_truth_L1_06.csv`
- `labels/rule_truth_L1_07.csv`
- `labels/rule_truth_L1_08.csv`
- `labels/rule_truth_L1_09.csv`
- `labels/injected_issue_truth.csv`
- `labels/audit_issue_truth.csv`
- `labels/normal_controls.csv`
- `labels/review_population.csv`

Existing rule-specific sidecars such as `l101_unbalanced_truth.csv` and `l201_just_below_threshold_truth.csv` should either be retained as rule-specific truth files or folded into `rule_truth.csv`.

## Minimum `rule_truth` Columns

- `rule_id`
- `document_id`
- `fiscal_year`
- `company_code`
- `document_number`
- `document_type`
- `posting_date`
- `business_process`
- `source`
- `expected_hit`
- `truth_basis`
- `evidence_fields`
- `materiality_amount`
- `related_anomaly_types`
- `is_injected_issue`
- `is_audit_issue`
- `truth_layer`

## L1 Draft Truth Criteria

### L1-01: Debit/Credit Imbalance

Rule truth:

- Positive if `abs(sum(debit_amount) - sum(credit_amount)) > tolerance`.
- Suggested tolerance: `1 KRW`.

Important:

- Do not rely only on `UnbalancedEntry`.
- `DecimalError`, `RoundingError`, `TransposedDigits`, `CurrencyError`, and `ReversedAmount` can all create L1-01 positives.
- Keep causal labels separately.

Current v71/v72 sidecar:

- `labels/l101_unbalanced_truth.csv`

### L1-02: Required Field Missing

Rule truth:

- Positive if a field marked `required: true` in `schema.yaml` is empty.
- Do not add extra interpretation in DataSynth truth. Optional-field coverage is a separate quality topic.

### L1-03: Invalid Account

Rule truth:

- Positive if the account used in the journal entry is not present in configured CoA.

Important:

- This is a field/config contract, not just an injected `InvalidAccount` label.
- DataSynth truth does not need to judge intent. If the account is outside CoA, it is L1-03 positive.

Source of truth:

- `config/chart_of_accounts.csv`
- DataSynth CoA master, if used by the active pipeline

### L1-04: Exceeded Approval Limit

Rule truth:

- Positive if `document_amount > approval_limit(approved_by)`.
- `approved_by` must resolve to an employee master record.

Open decision:

- `document_amount` should match implementation. Current contract has used document max of debit/credit totals.
- Need confirm whether L1-04 should use max debit/credit total or debit-side amount only.

Do not split out boundary/review cases in DataSynth truth. If the approver's own limit is exceeded, it is L1-04 rule truth. Later code can decide whether it is immediate, review-only, or low priority.

### L1-05: Self Approval

Rule truth:

- Positive if `created_by == approved_by`.

Important:

- If Phase 1 rule is simple self-approval candidate generation, every real self-approval is rule truth.
- DataSynth should not apply system/automated exceptions in the truth layer. Exception handling is a later detector/scoring concern.
- Whether it is a meaningful audit issue is separate and belongs to `audit_issue_truth`.

### L1-06: Segregation of Duties

Rule truth:

- Positive if the same user or authority holder performs two roles that should be separated within the same transaction flow.

Potential truth inputs:

- `sod_violation == true`
- non-empty `sod_conflict_type`
- same user performing conflicting P2P steps such as request/order/receipt/payment
- same user performing conflicting O2C steps such as sales entry/billing/cash collection/credit memo
- same user creating, approving, modifying, and clearing the same journal flow
- treasury user creating payment and approving or confirming the transfer
- payroll user changing HR master data and approving or paying payroll
- IT/admin user directly creating, modifying, or approving business journal entries

Important:

- L1-06 truth is direct-only. DataSynth must not put role-threshold or process-breadth review candidates into L1-06 rule truth.
- Use `sod_violation == true` together with a non-empty `sod_conflict_type` when both fields exist. If only one direct conflict marker is available, it may seed L1-06 direct truth, but role/process breadth alone must not.
- Do not mark a row positive only because a user appears in multiple processes. The conflict must involve roles that should be separated in the same transaction flow.

### L1-07: Skipped Approval

Rule truth:

- Positive if approval is skipped.

Current strict candidate:

- `approved_by` missing
- source is not system/automated
- amount requires approval

Important:

- Review-required skipped approval cases are also L1-07 rule truth when the rule should surface them.
- DataSynth should not remove recurring/source-ambiguous cases from rule truth just because the UI may later classify them as review.

### L1-08: Fiscal Period Mismatch

Rule truth:

- Positive if `fiscal_period != month(posting_date)` under the current calendar-year fiscal-period contract.

Important:

- If DataSynth supports non-calendar fiscal year in future, this rule truth must use fiscal calendar config.
- `document_date` basis should not override posting-date basis unless rule contract changes.

Current v65+ sidecar:

- `labels/wrong_period_confirmed_anomalies.csv`

### L1-09: Approval Date Missing

Rule truth:

- Positive if `approval_date` is missing.

Important:

- DataSynth truth should not exclude automated/recurring rows at this layer.
- Later code can split missing approval date hits into immediate violation, review-only, or normal workflow cases.

Audit issue:

- Manual/adjustment + material amount + missing approval date may be audit issue.
- Automated/recurring missing date may be normal control or system workflow issue depending on contract.

## L2 Draft Truth Criteria

L2 rules are strong fraud-signal candidate generators. DataSynth rule truth answers:

> Should Phase 1 surface this as an L2 candidate?

It does not answer:

> Is this already a confirmed fraud issue?

Immediate/review/normal-priority handling belongs to detector scoring and case building, not to the DataSynth rule-truth layer.

### L2-01: Just Below Approval Threshold

Rule truth:

- Positive if the document amount is below the approver's approval limit but close enough to that limit.
- Current contract uses the approver-specific limit and the configured near-threshold ratio.
- All proximity bands are rule truth: lower, close, and razor.

Important:

- If the approver limit cannot be resolved, it is a coverage issue, not L2-01 truth.
- DataSynth should not decide whether lower/close/razor is suspicious enough. It only records that the L2-01 condition is present.

### L2-02: Duplicate Payment

Rule truth:

- Positive if a payment looks like the same vendor/payment was paid again.
- Reference-based matches, mixed-reference fallback matches, blank-reference fallback matches, and recurring-looking duplicate-payment candidates are all rule truth when Phase 1 should surface them.
- In v113 candidate, `rule_truth_L2_02.csv` and `duplicate_payment_review_population.csv` are rebuilt from the current `b04_duplicate_payment()` detector output: `384` documents, detector/truth diff `0`.
- In v126 candidate, `rule_truth_L2_02.csv` and `duplicate_payment_review_population.csv` include stable `pair_key` and `duplicate_pair_key`. Pair-level A-axis evaluation should use that key rather than whichever side of the pair happened to be surfaced first.

Important:

- Suppression of monthly recurring payments is a detector-priority decision, not a DataSynth truth exclusion.
- Confirmed duplicate-payment fraud can be stored separately as `audit_issue_truth` or pair metadata.
- Pair metadata is required because the evidence is a payment pair, not just a single document.
- `DuplicatePayment` labels and `duplicate_payment_pairs.csv` remain the confirmed subset: `33` pair documents, all inside the raw rule truth.
- `duplicate_group_id` is populated for the `33` confirmed pair keys; other L2-02 review pairs retain the stable `pair_key` without a confirmed group id.
- `duplicate_payment_negative_controls.csv` remains a control sidecar and must not be merged into `rule_truth_L2_02`.

### L2-03: Duplicate Entry

Rule truth:

- Positive if an entry looks duplicated, re-entered, copied with small changes, near-duplicated, or split into multiple related entries.
- Exact duplicates, document-shape duplicates, reference duplicates, near duplicates, and split duplicates are all rule truth.

Important:

- DataSynth truth does not assign final confidence. Confidence bands are detector/case-builder output.
- Normal recurring, intercompany, or operational lookalikes may still be useful controls, but they should not be removed from rule truth when the L2-03 rule is expected to surface them.
- v126 rebuilds L2-03 rule truth from the active `b05_duplicate_entry()` A-axis evaluator and clarifies reason codes: `exact_duplicate`, `near_duplicate`, `split_duplicate`, `ic_split_duplicate`, and `o2c_offset_duplicate`.

### L2-04: Expense Capitalization

Rule truth:

- Positive if an expense-nature amount appears to be moved into an asset account pattern that Phase 1 should review.
- Both high-priority and review-priority capitalization candidates are rule truth.

Important:

- Normal capitalization context is not removed from rule truth at DataSynth time when the rule should surface it.
- Later code can lower priority or mark normal-control context based on document type, text, process, or policy.

### L2-05: Reversal Pattern

Rule truth:

- Positive for strict reversal evidence: ERP reversal link, one-to-one opposite-sign reversal pair, or line-swap reversal signature.
- Weak clearing/reclass and low-confidence reversal-like candidates are not A-axis `rule_truth_L2_05`; they are raw review universe sidecars.

Important:

- DataSynth truth should not keep only the confirmed `ReversedAmount` subset.
- v126 keeps `rule_truth_L2_05` as the raw A-axis detector universe: `80` documents.
- `reversal_strict_truth` stores the stricter subset: `52` documents.
- `reversal_weak_review_population` stores the `28` weak candidates. They are still A-axis raw truth because the detector is expected to surface them, but B-axis scoring may lower their priority.
- `reversal_entry_review_population` and `reversal_pattern_raw_review_universe` are aliases of the raw A-axis universe.

## L3 Draft Truth Criteria

L3 rules are review-needed anomaly signals. DataSynth rule truth answers:

> Should Phase 1 surface this as an L3 review candidate?

It does not answer whether the candidate is a confirmed audit issue. Normal context,
priority lowering, whitelist handling, and case escalation belong to later detector,
scoring, and case-building logic.

### L3-01: Account/Process Mismatch

Rule truth:

- Positive if the account is valid in CoA but its account nature does not fit the business process.

Important:

- Accounts outside CoA belong to L1-03, not L3-01.
- DataSynth should not keep only injected `MisclassifiedAccount` labels if a real process/account mismatch exists.

### L3-02: Manual Entry Population

Rule truth:

- Positive if the entry is manual or adjustment source.

Important:

- L3-02 rule truth is the full manual/adjustment population, not only `ManualOverride`.
- Whether a manual entry is routine, priority, or control-bypass is decided downstream.

### L3-03: Intercompany Review Signal

Rule truth:

- Positive if the entry belongs to the related-party/intercompany transaction population.

Important:

- L3-03 does not prove circular transactions. GR01/GR03 and IC01/IC02/IC03 provide stronger follow-up signals.
- Normal intercompany entries are still L3-03 rule truth when Phase 1 should surface them.

### L3-04: Period-End/Period-Start Posting

Rule truth:

- Positive if the entry is within the configured period-end/period-start window, currently month-end/month-start +/- 5 days.

Important:

- High amount, manual/adjustment source, sensitive accounts, approval issues, abnormal timing, and weak descriptions are score/priority signals, not rule-truth prerequisites.
- `RushedPeriodEnd` in `anomaly_labels.csv` is an injected manipulation scenario subset. It is not the primary L3-04 Phase 1 rule truth.
- Recurring close entries and normal close workflows are not removed from rule truth at DataSynth time.
- Later code can lower their priority or classify them as normal close context.

### L3-05: Weekend/Holiday Posting

Rule truth:

- Positive if posting happens on weekend or holiday.

Important:

- Normal weekend operations are still L3-05 rule truth.
- Confirmed `WeekendPosting` is an audit issue subset, not the full rule truth.

### L3-06: After-Hours Posting

Rule truth:

- Positive if posting happens during the configured after-hours window.

Important:

- Automated night batches, overseas operations, or shift-work postings are still rule truth.
- Later code decides whether they are normal context or priority review.

### L3-07: Posting/Document Date Gap

Rule truth:

- Positive if the posting date and document date differ beyond the configured threshold.

Important:

- Backdated, late-posted, and forward-date-gap directions are all rule truth.
- Reasonable business delays are handled downstream as normal/review context, not excluded by DataSynth truth.

### L3-08: Missing Or Corrupted Description

Rule truth:

- Positive if the description is missing, blank, corrupted, or legacy poor-quality alias.

Important:

- Vague or semantically weak descriptions belong to Phase 3 NLP/LLM truth, not L3-08 rule truth.

### L3-09: Suspense Aging

Rule truth:

- Positive if a suspense or clearing account remains unresolved beyond the aging threshold.

Important:

- The target is long unresolved/open status, not mere use of a suspense account.
- Normal clearing controls remain useful sidecars, but are not removed when the L3-09 condition is present.

### L3-10: High-Risk Account Use

Rule truth:

- Positive if the entry touches a configured sensitive/high-risk account or prefix.

Important:

- Routine system use of a sensitive account is still L3-10 rule truth.
- Downstream code decides raw signal, priority case, or normal-control context.

### L3-11: Cutoff Mismatch

Rule truth:

- Positive if posting date and the relevant event date exceed the configured cutoff tolerance for revenue or expense accounts.

Important:

- Reasonable-delay controls are not removed from rule truth when the cutoff rule should surface them.
- Missing event dates are coverage gaps, not normal negatives.

## L4 Draft Truth Criteria

L4 rules are statistical or behavioral review anchors. DataSynth rule truth answers:

> Should Phase 1 surface this as an L4 candidate or macro finding?

It does not answer whether the candidate is a confirmed fraud or audit issue.
Normal large transactions, normal batch runs, normal night operations, and business-driven
distribution shifts can still be rule truth when the L4 rule is designed to surface them.

### L4-01: High-Value Revenue Outlier

Rule truth:

- Positive if a revenue account has an amount z-score above the configured threshold.

Important:

- This is not the full `RevenueManipulation` label family.
- If a revenue row is statistically high by the L4-01 contract, it is rule truth even if it is a normal large revenue transaction.
- Cutoff, reversal, manual revenue entry, and process/account mismatch subtypes belong to their own rule truth when they do not satisfy the L4-01 z-score condition.

### L4-02: Benford Finding

Rule truth:

- Positive at `fiscal_year + company_code + gl_account` group level when the first-digit distribution deviates beyond the configured Benford threshold with enough sample size.

Important:

- L4-02 is not a document-level truth label.
- Drill-down rows are evidence candidates inside a flagged group, not independent document truth.
- Legacy document-level `BenfordViolation` labels should not be used as the L4-02 precision/recall denominator.

### L4-03: High Amount Outlier

Rule truth:

- Positive if the row/document amount satisfies the configured high-amount z-score and amount-quantile guard.

Important:

- Normal large financing, land purchase, capex, or treasury transactions can still be L4-03 rule truth.
- Whether the high amount is audit-meaningful is decided by downstream case priority and `audit_issue_truth`.
- v109 rebuilds `high_amount_review_population*` and `rule_truth_L4_03*` from the current detector contract. `UnusuallyHighAmount` / `StatisticalOutlier` remain injected anomaly subsets, not the full L4-03 denominator.

### L4-04: Rare Debit/Credit Account Pair

Rule truth:

- Positive if the journal contains a debit-credit account pair that falls into the configured rare-pair population.

Important:

- Null or missing account pairs are not L4-04 truth. They belong to L1-02/L1-03 field/account integrity truth.
- Normal rare account pairs remain rule truth when Phase 1 should surface them.

### L4-05: Abnormal Hours Concentration

Rule truth:

- Positive if a user-level time behavior pattern satisfies the configured abnormal-time concentration, repeated midnight, or rapid-approval review condition.

Important:

- Normal shift work, overseas support, or night operations can still be L4-05 rule truth when the detector should surface them.
- System or automated sources follow the detector contract. DataSynth truth should not silently override that contract.
- Confirmed account misuse or credential-risk cases belong to `audit_issue_truth`.

### L4-06: Batch Anomaly Review Signal

Rule truth:

- Positive if a batch-like source satisfies period-end concentration, simultaneous-creation, or batch-amount-outlier conditions.
- In v112 candidate, `rule_truth_L4_06.csv` and `batch_review_population.csv` are rebuilt from the current `c13_batch_anomaly()` detector output: `861` documents, detector/truth diff `0`.

Important:

- Normal batch processing can still be L4-06 rule truth.
- L4-06 is a combo/booster signal. Downstream scoring decides whether the batch hit is low priority, normal control, or elevated by other rule hits.
- `BatchAnomaly` labels are a confirmed subset only: v112 keeps `175` confirmed labels and all are inside the raw rule truth.
- `batch_normal_controls.csv` and `batch_boundary_controls.csv` are control sidecars only. They must not be merged into `rule_truth_L4_06`.
- `recurring` is not a detector batch source. Recurring payroll or allocation examples belong to controls unless the journal source is explicitly classified as batch/interface/automated.

## D01/D02 Draft Truth Criteria

D01 and D02 are analytical review macro findings. They are not document-level truth labels.
The evaluation unit is `fiscal_year + company_code + gl_account` when company code is available.

### D01: Account Activity Variance

Rule truth:

- Positive if a company/account group has a configured year-over-year activity change.
- Activity means total debit+credit amount, transaction count, and average amount according to the current D01 implementation.
- A new current-year account with no prior baseline is also rule truth when D01 should surface it.

Important:

- Normal business growth, price increase, capex expansion, working-capital timing, or account mapping changes can still be D01 rule truth.
- These normal explanations belong to `normal_control` or downstream triage, not exclusion from rule truth.
- 2022 is not evaluated by default when there is no 2021 baseline.

### D02: Monthly Pattern Variance

Rule truth:

- Positive if a company/account group has a configured year-over-year monthly distribution shift after D02 guardrails are satisfied.

Important:

- Normal seasonality, project concentration, recurring batch cycles, or business expansion can still be D02 rule truth.
- Groups with insufficient prior/current months, too few documents, missing accounts, or other guardrail failures belong to exclusions, not false negatives.
- 2023 compares against 2022, and 2024 compares against 2023 by default.

## Evaluation Modes

### Contract Mode

Uses `rule_truth`.

Answers:

- Did the rule detect all documents that satisfy its condition?
- Did it flag documents that do not satisfy its condition?

Expected:

- Some integrity rules may score close to 100%.
- That is acceptable because this mode validates implementation, not business severity.

### Audit Benchmark Mode

Uses `audit_issue_truth`, `normal_controls`, and `review_population`.

Answers:

- Did the system prioritize meaningful audit issues?
- Did it avoid over-escalating normal lookalikes?
- Did it keep review-only cases out of confirmed issue metrics?

Expected:

- Precision should not be artificially perfect.
- Review queue quality matters more than strict binary precision.

### Injection Scenario Mode

Uses `injected_issue_truth`.

Answers:

- Did the generated scenario materialize correctly?
- Can Phase 2/3 identify and explain the injected scenario?

## v73 Proposal

Create a unified Phase 1 rule truth manifest:

- build `labels/rule_truth.csv`
- build `labels/rule_truth_L1_01.csv` through `labels/rule_truth_L1_09.csv`
- preserve existing causal labels in `anomaly_labels.csv`
- keep `labels/audit_issue_truth.csv` as audit benchmark truth
- keep `labels/injected_issue_truth.csv` as generator scenario truth

First implementation scope:

1. L1-01 through L1-09 document-level rule truth
2. L2-01 through L2-05 document/pair-level rule truth
3. L3-01 through L3-11 document/account-state rule truth
4. L4-01, L4-03, L4-04, L4-05, L4-06 review-anchor rule truth
5. L4-02 Benford group-level rule truth
6. D01/D02 company-account-year macro finding truth

Do not use `anomaly_labels.csv` alone as Phase 1 rule truth after this split.

## v74-v108 Candidate Patch Status

Current candidate chain is still separate from production DataSynth.

| Candidate | Source | Scope | Main effect |
|-----------|--------|-------|-------------|
| v74 | v73 | CoA backfill from `config/chart_of_accounts.csv` | L1-03 rule truth dropped from thousands of normal-looking accounts to true invalid-account candidates |
| v75 | v74 | L2-03/L2-04/L2-05 rule-truth recomputation | Removed label fallback for duplicate entry, expense capitalization, and reversal pattern |
| v76 | v75 | L3-04/L4-01/L4-03 feature-backed rule-truth recomputation | Replaced approximate/sidecar truth with actual feature + rule function output |
| v77 | v76 | Superseded broad L1-06/L1-07 review candidate expansion | Do not use for v80 L1-06 evaluation; L1-06 review candidates moved to L3-12/work-scope sidecar |
| v78 | v77 | Superseded | Do not use. Journal-row patching on hardlinked candidates could mutate prior candidate CSVs. |
| v79 | v77 metadata + v71 clean journals | Superseded safe broad L1 rebuild | L1-06 role-threshold review candidates are too broad for v80 and must move to L3-12/work-scope sidecar |
| v80 | v79 | L1-06/L3-12 split | L1-06 is direct SoD truth only; work-scope/process-breadth candidates are materialized as L3-12 and `work_scope_excess_review_population` |
| v81 | v80 | Realistic approval metadata coverage | Unlabeled automated/recurring approval metadata gaps are filled with system approval traces; L1-07/L1-09 broad truth remains but no longer dominated by routine documents |
| v82 | v81 | L1 boundary/control cases | Adds late approvals, delegated approvals, approver master mapping gaps, post-approval change controls, and small routine system-control gaps |
| v83 | v82 | L1-05 consistency fix | Restores journal/sidecar consistency for system self-approval controls after v82 system-control gap injection |
| v84 | v83 | Rule-agnostic manipulated-entry truth | Adds 420 manipulated documents from DETECTION_REFERENCE FSS pattern mix without targeting a single rule |
| v85 | v84 | L3-01 rule-truth realignment | Removes old injected-label-based 59-row L3-01 truth and rebuilds L3-01 from the current detector contract |
| v86 | v85 | L3-01 distribution realism | Reduces P2P/revenue concentration and distributes account-process mismatch candidates across O2C, H2R, TRE, and A2R |
| v87 | v86 | L3-03 detector-contract truth | Realigns L3-03 and `intercompany_population_truth` to the current IC GL-prefix detector contract |
| v88 | v87 | L3-02 source distribution realism | Reduces manual/adjustment overrepresentation and rebuilds L3-02/manual population truth |
| v89 | v88 | L3-05 calendar truth realignment | Rebuilds L3-05/weekend review truth from current journal `posting_date` weekend/holiday condition |
| v90 | v89 | L1-06 severity diversity | Keeps L1-06 direct truth count stable and diversifies SoD evidence across direct_medium, direct_high, and direct_critical |
| v91 | v90 | L3-06 after-hours truth realignment | Rebuilds L3-06 and after-hours review population from actual journal `posting_date` after-hours condition |
| v92 | v91 | L3-09 stale suspense truth cleanup | Removes stale suspense-aging truth not supported by current journal rows |
| v93 | v92 | L1-02 missing-field diversity | Adds varied required-field missing cases and recalculates L1-01 imbalance truth where amount fields are missing |
| v94 | v93 | L3-04 period-window truth | Rebuilds L3-04 rule truth as every current-journal document posted within month-end/month-start +/- 5 days |
| v95 | v94 | L3-12 user-level truth | Converts official L3-12 truth to fiscal_year + created_by user-level truth and moves document rows to projection sidecar |
| v96 | v95 | L3-12 bucket diversity | Preserves user-level L3-12 truth and detector evidence while diversifying business-context buckets and score bands |
| v97 | v96 | BatchAnomaly confirmed-label diversity | Rebuilds confirmed BatchAnomaly subset from existing L4-06 truth across process/source/document-type/company contexts |
| v98 | v97 | Manipulated-entry company diversity | Reselects rule-agnostic manipulated-entry truth across C001/C002/C003 while preserving year/scenario counts |
| v99 | v98 | DuplicatePayment pair diversity | Rebuilds L2-02 pair truth from naturally reconstructable P2P payment pairs; balances companies C001/C002/C003 at 11 each and avoids all-year-2022 concentration |
| v100 | v99 | Minor source realism | Reclassifies selected broad manual/adjustment review documents from manual to adjustment to reduce synthetic source concentration without changing rule contracts |
| v101 | v100 | L3-04 detector-window truth | Rebuilds L3-04 truth as posting day <= 5 or days_to_month_end <= 5, matching the current detector period-window interpretation |
| v102 | v101 | L1 sidecar semantics cleanup | Clarifies legacy L1 sidecar names/columns without changing journal rows, anomaly labels, or rule truth |
| v103 | v102 | L3 stale truth cleanup | Rebuilds L3-02, L3-03, and L3-05 truth from current journal fields after later source/date/missing-field patches |
| v104 | v103 | L3-05 calendar realism | Reduces excessive normal weekend/holiday posting volume by moving selected normal automated/interface/recurring postings to nearby same-month business days |
| v105 | v104 | L3 sidecar context cleanup | Rebuilds/adds L3 explanatory sidecars without changing journal rows or rule truth |
| v106 | v105 | L3-11 cutoff truth realignment | Rebuilds L3-11 truth and cutoff sidecars from current journal `posting_date`/`delivery_date` after v104 calendar movement |
| v107 | v106 | L4-01 revenue z-score truth realignment | Rebuilds L4-01 truth from current feature-backed detector contract: revenue account and `amount_zscore > 3.0` |
| v108 | v107 | L4-02 Benford group truth realignment | Rebuilds Benford finding truth from current journal at `fiscal_year + company_code + gl_account` with `n >= 500` and `MAD > 0.012` |
| v109 | v108 | L3-12 candidate/scored truth split | Adds raw candidate user-year truth for L3-12 while keeping scored review truth separate |
| v110 | v109 | L4-04 detector-universe truth realignment | Rebuilds rare account-pair rule truth from current L4-04 detector output |
| v111 | v110 | L4-05 combined-context truth realignment | Rebuilds abnormal-hours behavior review truth from the 2022-2024 combined detector context |
| v112 | v111 | L4-06 batch detector-universe truth realignment | Rebuilds batch review truth from current L4-06 detector output and keeps confirmed BatchAnomaly as subset |
| v113 | v112 | L2-02 duplicate-payment detector-universe truth realignment | Rebuilds duplicate-payment review truth from current L2-02 detector output and keeps duplicate-payment pairs as confirmed metadata |
| v114 | v113 | Stale detector-contract truth refresh | Adds staleness scan workflow and refreshes L4-03/L4-06 current detector-contract truth |
| v115 | v114 | L2 stale truth purge and rebuild | Deletes copied L2-03/L2-04/L2-05 truth families and rebuilds them from current detector output |
| v116 | v115 | Active truth metadata cleanup | Removes legacy `source_candidate` values from active `rule_truth_*` files |
| v117 | v116 | L2 independent scenario/control sidecars | Adds detector-independent L2-03/L2-04/L2-05 behavioral validation sidecars |
| v118 | v117 | Sidecar purpose manifest | Adds `labels/sidecar_manifest.csv/json` to separate realism controls, review populations, detector snapshots, and contract context |
| v119 | v118 | L3 sidecar semantics cleanup | Splits labeled after-hours context and marks IC exception sidecars as case-level drilldowns |
| v120 | v119 | L4 sidecar semantics cleanup | Marks L4 review populations as detector-contract universes and adds clearer legitimate/boundary context aliases |
| v121 | v120 | D01/D02 macro sidecar semantics cleanup | Adds D01 guardrails and splits D02 raw-positive normal context from guardrail negatives |
| v122 | v121 | Year journal file consistency cleanup | Regenerates `journal_entries_YYYY` files as partitions of the combined journal |
| v123 | v122 | L4-06 truth refresh | Rebuilds batch detector universe after year-file consistency cleanup |
| v124 | v123 | L3/D A-axis truth refresh | Rebuilds L3-02/L3-04/L3-05/L3-11 from current year journals and pins D01/D02 A-axis truth to macro review universes |
| v125 | v124 | L2 pair/reversal truth split | Superseded by v126 for A-axis evaluation because it incorrectly narrowed L2-05 rule truth to a strict subset |
| v126 | v125 | L2 A-axis contract truth refresh | Rebuilds L2-02/L2-03/L2-05 from current A-axis detector contracts; keeps strict/weak reversal subsets as sidecars only |

Latest candidate path:

`data/journal/primary/datasynth_v126_candidate`

Latest `rule_truth.csv` counts:

| Rule | Count |
|------|------:|
| L1-01 | 316 |
| L1-02 | 156 |
| L1-03 | 32 |
| L1-04 | 56 |
| L1-05 | 244 |
| L1-06 | 19 |
| L1-07 | 96 |
| L1-08 | 731 |
| L1-09 | 122 |
| L2-01 | 457 |
| L2-02 | 384 |
| L2-03 | 111 |
| L2-04 | 1,098 |
| L2-05 | 80 |
| L3-01 | 2,419 |
| L3-02 | 86,808 |
| L3-03 | 30,377 |
| L3-04 | 141,375 |
| L3-05 | 24,318 |
| L3-06 | 7,507 |
| L3-09 | 1,091 |
| L3-11 | 130 |
| L3-12 | 64 |
| L4-01 | 964 |
| L4-02 | 99 |
| L4-03 | 4,015 |
| L4-04 | 4,091 |
| L4-05 | 4,964 |
| L4-06 | 692 |

Notes:

- L1-09 is intentionally broad under the user's current rule-truth policy: if approval date is missing, it is rule truth. v81 fills unlabeled routine automated/recurring documents with system approval traces, and v82 adds a small number of routine system-control gaps.
- L1-05 is intentionally broad: if `created_by == approved_by`, it is rule truth even for automated/system contexts. v79 adds 27 system self-approval controls across years.
- L1-06 is direct SoD truth only in v80. Direct markers and IT/admin direct business posting evidence stay in L1-06.
- L3-12 is a large work-scope review population, not a confirmed violation label. It must be reported separately from L1-06 precision/recall.
- L1-07 is intentionally broad: if `approved_by` is missing, it is rule truth. v82 keeps this broad rule truth but tracks non-truth approval boundary cases in sidecars.
- v82 boundary/control sidecars: `late_approval_boundary_controls`, `delegated_approval_controls`, `approver_master_mapping_issues`, `post_approval_change_controls`, `system_control_gap_controls`.
- v83 fixes the v82 edge case where two `system_self_approval_controls` documents were also selected as system-control gaps. L1-05 rule truth now matches journal fields exactly.
- v84 adds `labels/manipulated_entry_truth.csv` as separate scenario truth. It is not a replacement for `rule_truth.csv` and is not copied from individual FSS cases; it generalizes the observed manipulation pattern mix.
- v84 manipulated-entry count: 420 total, split by year as 2022=115, 2023=145, 2024=160.
- v115 removes stale L2-03/L2-04/L2-05 rule-truth families inherited from older candidates and rebuilds them from current detector output. New counts are L2-03=105, L2-04=1,098, L2-05=82.
- v116 removes old `source_candidate` values from active rule-truth files. Historical patch lineage remains only in documentation and manifest files.
- v117 keeps v116 rule-truth membership and adds independent L2 behavioral sidecars. `*_review_population` remains detector-contract snapshot; independent validation must use the new scenario/control sidecars.
- v117 L2 independent sidecars: `duplicate_entry_confirmed_scenarios=67`, `duplicate_entry_negative_controls=90`, `expense_capitalization_plausible_cases=33`, `expense_capitalization_normal_capex_controls=90`, `reversal_pattern_plausible_cases=51`, `reversal_pattern_normal_clearing_controls=90`.
- v118 keeps v117 truth membership and adds `labels/sidecar_manifest.csv/json`.
- v118 sidecar manifest classifies `146` sidecars: `realism_control=33`, `review_population=20`, `detector_contract_universe=4`, `rule_truth_context=2`, `rule_truth_but_not_audit_issue=1`, `legacy_alias=2`, `contract_manifest=84`. Only `allowed_for_independent_sidecar_eval=True` rows may be used as independent behavioral validation sets.
- v119 keeps v118 truth membership, rewrites active truth metadata to `source_candidate=v119`, and tightens L3 sidecar semantics.
- v119 L3-06 cleanup: `afterhours_normal_context_within_review_population` and `normal_after_hours_context` now contain only unlabeled normal after-hours context (`6,952` docs, anomaly-label overlap `0`). The `20` labeled documents are moved to `afterhours_cross_rule_labeled_context`.
- v119 L3-03 cleanup: IC exception files are case-level drilldowns, not document-level subsets of `rule_truth_L3_03`. They now include `target_in_l303_rule_truth`, `counterpart_in_l303_rule_truth`, `linked_l303_document_ids`, and `linked_l303_document_count`.
- v120 keeps v119 truth membership, rewrites active truth metadata to `source_candidate=v120`, and tightens L4 sidecar semantics.
- v120 L4 detector-universe aliases: `revenue_outlier_detector_universe=964`, `high_amount_detector_universe=4,015`, `rare_account_pair_detector_universe=4,091`, `abnormal_hours_behavior_detector_universe=4,964`, `batch_detector_universe=686`; each has document diff `0` against the corresponding `rule_truth_L4_*`.
- v120 L4 context aliases: `high_amount_legitimate_contexts=177`, `high_amount_boundary_contexts=116`, `rare_account_pair_legitimate_contexts=258`, `batch_legitimate_contexts=250`, `batch_boundary_contexts=128`, `revenue_outlier_boundary_contexts=212`.
- v120 sidecar policy: `*_review_population` and `*_detector_universe` are contract/universe files, not independent realism samples. `*_legitimate_contexts` and `*_boundary_contexts` may overlap raw detector hits and must not be treated as strict false-positive controls.
- v121 keeps v120 truth membership, rewrites active truth metadata to `source_candidate=v121`, and tightens D01/D02 macro sidecar semantics.
- v121 D01 sidecars: `account_activity_variance_truth=336`, `account_activity_variance_normal_controls=504`, `account_activity_variance_review_population=840`, `account_activity_variance_stable_controls=240`, `account_activity_variance_near_threshold_controls=120`, `account_activity_variance_exclusions=96`.
- v121 D02 sidecars: `monthly_pattern_shift_confirmed_anomalies=346`, `monthly_pattern_shift_truth=346`, `monthly_pattern_shift_review_population=497`, `monthly_pattern_shift_normal_controls=194`, `monthly_pattern_shift_raw_positive_normal_contexts=151`, `monthly_pattern_shift_guardrail_negative_controls=43`, `monthly_pattern_shift_exclusions=2,059`.
- v121 macro policy: D01/D02 sidecars are evaluated at `fiscal_year + company_code + gl_account`. Normal controls can be raw-positive review contexts; row-level `is_anomaly` must not be modified to satisfy D01/D02.
- v122 keeps v121 truth membership and regenerates `journal_entries_2022/2023/2024.csv/json` directly from `journal_entries.csv`.
- v122 year-file consistency fix: pre-patch year files had `posting_date` mismatches (`2022=5,867`, `2023=18,449`, `2024=15,020`), `source` mismatches (`2022=6,002`, `2023=5,978`, `2024=7,116`), and fiscal-period mismatches in `2023=2`, `2024=2`. Post-patch checked mismatches are `0`.
- v122 L1-02 fix: the two fiscal-period-missing truth documents now have blank `fiscal_period` in both combined and year-specific journal files.
- v123 refreshes only L4-06 detector-contract truth after v122. `rule_truth_L4_06`, `batch_review_population`, and `batch_detector_universe` now contain 692 documents with diff `0`.
- v123 adds six 2023-09-30 23:25:00 automated simultaneous-creation documents to L4-06 rule truth; confirmed `BatchAnomaly` labels and normal/boundary controls are unchanged.
- v124 refreshes L3 A-axis rule truth after the v122 year-file sync and v123 L4-06 refresh. `rule_truth_L3_02`, `rule_truth_L3_04`, `rule_truth_L3_05`, and `rule_truth_L3_11` are rebuilt from the current `journal_entries_YYYY.csv` files.
- v124 L3 A-axis counts: L3-02 `86,808`, L3-04 `141,375`, L3-05 `24,318`, L3-11 `130`; each has detector/truth diff `0` in `check_datasynth_axis_truth_alignment.py`.
- v124 D-axis policy: D01/D02 A-axis evaluation uses `rule_truth_D01.csv` and `rule_truth_D02.csv` macro review universes. D01 is `840` groups with `336` confirmed subset groups; D02 is `497` groups with `346` confirmed subset groups.
- v124 active metadata cleanup: all active `rule_truth_*` files use `source_candidate=v124`, and the candidate root keeps only `FREEZE_V124_CANDIDATE.md` and `V124_L3_D_AXIS_TRUTH_REFRESH.json` among versioned manifests.
- v126 L2-02 pair policy: `rule_truth_L2_02=384` keeps document rows but adds stable `pair_key`; A-axis pair evaluation should compare by `pair_key`. Confirmed `duplicate_payment_pairs=33` are mapped via `duplicate_group_id`.
- v126 L2-03 reason policy: `rule_truth_L2_03=111` is rebuilt from the active A-axis evaluator; reason codes are `exact_duplicate=64`, `near_duplicate=28`, `ic_split_duplicate=12`, `o2c_offset_duplicate=4`, `split_duplicate=3`.
- v126 L2-05 raw/strict split: `rule_truth_L2_05=80` is the raw A-axis detector universe; `reversal_strict_truth=52`; `reversal_weak_review_population=28`. Weak reversal candidates remain A-axis truth and are separated only for B-axis scoring.
- v126 active metadata cleanup: all active `rule_truth_*` files use `source_candidate=v126`, and the candidate root keeps only `FREEZE_V126_CANDIDATE.md` and `V126_L2_CONTRACT_TRUTH_REFRESH.json`.
- v85 replaces the old `MisclassifiedAccount`-label-derived L3-01 truth. Official L3-01 truth is now current detector-contract truth: valid CoA account plus configured process/account mismatch review hit.
- v85 L3-01 count: 2,426 documents, split by year as 2022=837, 2023=774, 2024=815.
- v85 removed the previous 59-row L3-01 rule truth from official labels. Only 2 of those rows matched the current detector contract; 57 were not L3-01 truth under the current rule.
- v86 keeps the same L3-01 detector-contract truth policy but makes the source journal distribution less synthetic. L3-01 count is 2,419 documents, split by year as 2022=881, 2023=727, 2024=811.
- v86 L3-01 by process: P2P=1,059, O2C=520, H2R=380, TRE=300, A2R=160.
- v87 realigns L3-03 to the detector contract. Official L3-03 truth is IC GL-prefix population using prefixes 1150, 2050, 4500, and 2700. Count is 30,378 documents, split by year as 2022=10,075, 2023=10,187, 2024=10,116.
- v87 does not use non-empty `trading_partner` alone as L3-03 truth because no separate related-party master is available.
- v88 reduces manual/adjustment documents from about 73.7% to about 27.2% overall. L3-02 count is 86,808 documents, split by year as 2022=28,947, 2023=28,687, 2024=29,174.
- v88 keeps process differences: P2P/O2C around 18%, H2R around 28%, TRE around 30%, A2R around 42%, and R2R around 46%.
- v89 realigns L3-05 to current journal `posting_date`. L3-05 count is 24,321 documents, split by year as 2022=6,011, 2023=9,355, 2024=8,955.
- v89 L3-05 signal split: weekday holiday=14,996, weekend=8,828, weekend holiday=497.
- v90 keeps L1-06 direct truth at 19 documents while diversifying the evidence used by the detector.
- v90 L1-06 detector rows by score: 0.70=24, 0.80=33, 0.95=7.
- v90 L1-06 document buckets: direct_medium=7, direct_high=9, direct_critical=3.
- v90 L1-06 conflict types: preparer_approver=11, purchase_payment=5, cash_disbursement=2, treasury_payment=1.
- v90 adds high-risk conflict, threshold, and IT/admin critical evidence to avoid all SoD hits collapsing into the same medium severity bucket.
- v91 realigns L3-06 to actual after-hours postings. L3-06 count is 7,507 documents, split by year as 2022=2,622, 2023=2,444, 2024=2,441.
- v91 L3-06 source split: automated=3,633, interface=1,004, recurring=1,279, manual=1,524, adjustment=67.
- v91 L3-06 detector score split: low-risk system/batch context score 0.20=4,773 rows, human/unknown context score 0.45=2,734 rows.
- v91 writes `labels/afterhours_review_population*.csv` as the full L3-06 review population and keeps `normal_after_hours_context*.csv` as non-anomaly normal-context evidence.
- v92 removes 2 stale L3-09 truth documents whose sidecar metadata no longer matched the current journal rows. L3-09 count is 1,091 documents, split by year as 2022=356, 2023=390, 2024=345.
- v92 L3-09 detector/truth/review population are aligned at 1,091 documents with no diff.
- v93 diversifies L1-02 required-field omissions without changing detector code. L1-02 count is 156 documents, split by year as 2022=46, 2023=49, 2024=61.
- v93 L1-02 missing field counts: gl_account=96, document_date=13, document_type=12, fiscal_period=12, posting_date=11, debit_amount=11, credit_amount=10, company_code=9.
- v93 L1-02 score split: 0.42=13, 0.48=12, 0.56=10, 0.62=7, 0.72=14, 0.74=86, 0.78=4, 0.80=6, 0.86=4.
- v93 recalculates L1-01 truth after amount-field omissions. L1-01 count is 316 documents, split by year as 2022=99, 2023=85, 2024=132.
- L3-04 is broad because period-start/end itself is a review candidate population. High amount, manual source, and RushedPeriodEnd scenario labels only affect priority or downstream interpretation.
- v101 L3-04 truth count is 141,375 documents, split by year as 2022=46,822, 2023=46,614, 2024=47,939. It matches current detector-window interpretation: `posting_date.day <= 5 OR days_to_month_end <= 5`, with zero missing/extra documents.
- v95 L3-12 official truth is user-level: 64 user-year rows, split by year as 2022=21, 2023=21, 2024=22. Document drill-down projection is stored separately in `work_scope_excess_document_projection.csv` with 262,846 documents.
- v96 keeps L3-12 at 64 user-year truth rows but diversifies truth interpretation buckets: manual-sensitive scope 38, system-mixed scope 15, leadership-broad scope 11. Detector evidence is preserved in `detector_bucket`/`detector_score`.
- v109 splits L3-12 truth layers. `rule_truth_L3_12.csv` remains scored review truth with 64 user-year rows. `work_scope_raw_candidate_population.csv` is raw candidate truth with 127 user-year rows, including 63 zero-score `system_scope_observation` candidates. L3-12 evaluation must report candidate coverage and scored review accuracy separately.
- v110 realigns L4-04 to the Phase1 raw review-anchor policy. `rule_truth_L4_04.csv` and `rare_account_pair_review_population.csv` both contain the current detector universe of 4,091 documents. Confirmed `UnusualAccountPair` remains a 52-document subset, and normal controls remain separate context sidecars rather than precision failures.
- v111 realigns L4-05 to the Phase1 raw behavior-review policy. `rule_truth_L4_05.csv` and `abnormal_hours_behavior_review_population.csv` both contain the 2022-2024 combined-context detector universe of 4,964 documents. Confirmed `AbnormalHoursConcentration` remains a 27-document subset. Annual single-year detector runs are not strict truth evaluation because user behavior statistics depend on the population context.
- v97 keeps L4-06 broad rule truth unchanged and diversifies the confirmed BatchAnomaly subset: H2R=60, R2R=60, O2C=20, P2P=18, TRE=17; source automated=115 and recurring=60; company split C001=61, C002=59, C003=55.
- v98 keeps manipulated-entry scenario and year counts unchanged at 420 total while rebalancing company distribution to C001=147, C002=139, C003=134. Old manipulated text markers are cleaned before reselection; text markers remain only on the new truth documents.
- v99 rebuilds DuplicatePayment pair truth from current journal rows without mutating journal CSVs. L2-02 pair count remains 33; company split is C001=11, C002=11, C003=11; year split is 2022=19, 2023=7, 2024=7; variants are exact=7, reference_blank=7, reference_variant=7, date_shifted=6, amount_rounding=6.
- v99 L2-02 pair/truth/anomaly document sets match exactly, and every selected pair is reconstructable in the current journal as same-company P2P repeated vendor/payment within 45 days.
- v100 performs a source-column realism pass only. It reclassifies 6,084 documents from manual to adjustment across years 2022=2,041, 2023=2,010, 2024=2,033.
- v100 L3-02 source split is manual=76,386 and adjustment=10,422. L4-05 source split is manual=18 and adjustment=9. Rule-truth counts and required truth contracts are unchanged.
- v101 fixes the L3-04 month-end boundary mismatch. The previous truth used the last five calendar days, while the detector treats `days_to_month_end <= 5` as the period-end window. This adds 10,843 boundary-day documents.
- v102 does not change L1 rule truth. It adds semantic aliases for legacy sidecars: `skipped_approval_system_gap_controls*` for old `skipped_approval_normal_controls*`, and `wrong_period_non_audit_issue_truth*` for old `wrongperiod_negative_controls*`. It also changes `sod_review_population*` from `was_sod_violation=True` to `was_sod_violation=False` plus `sod_review_signal=True`.
- v103 does not mutate journal rows. It rebuilds stale L3 truth from current journal fields: L3-02 adds 3 current manual/adjustment documents, L3-03 removes 1 stale document whose GL account is now missing, and L3-05 removes 3 stale documents whose posting date is now missing.
- v103 alignment checks: L3-02 actual/truth diff 0 at 86,811 documents; L3-03 current IC-prefix/truth diff 0 at 30,377 documents; L3-05 truth contains 0 documents with missing posting date and 24,318 current weekend/holiday documents.
- v104 reduces L3-05 from 24,318 documents (7.62%) to 12,771 documents (4.00%) by moving 11,547 normal automated/interface/recurring documents to nearby same-month business days.
- v104 protects anomaly-labeled documents, L1-08/L3-07/L3-11 truth documents, and manual/adjustment postings. Required truth gate remains `failures: []`.
- v105 changes sidecars only. It rebuilds `normal_weekend_context*`, adds clearer L3-06 normal-context alias files, and adds explanatory L3-04/L3-02/L3-03 context sidecars. Rule truth counts are unchanged from v104.
- v105 sidecar validation: every new L3 document-level sidecar is a subset of its target L3 rule truth, and required truth gate remains `failures: []`.
- v106 realigns L3-11 after v104 calendar movement. Current journal calculation and `rule_truth_L3_11.csv` both contain 133 documents with zero diff.
- v106 moves 3 documents from old cutoff normal controls into L3-11 rule truth/review population because their current `posting_date=2024-01-02` and `delivery_date=2023-12-25` produce a 6 business-day revenue cutoff gap.
- v106 keeps confirmed cutoff anomalies separate from rule truth: `cutoff_confirmed_anomalies=110`, `cutoff_reasonable_delay_controls=23`, `cutoff_normal_controls=273`, and representative `cutoff_untestable_controls=720`.
- v107 realigns L4-01 after later journal/account patches. Current feature-backed detector and `rule_truth_L4_01.csv` both contain 964 documents with zero diff.
- v107 removes 3 stale L4-01 truth documents whose current journal rows are no longer revenue-account rows, and adds 2 current revenue z-score hits that were missing from truth.
- v107 adds `revenue_outlier_review_population*` and `revenue_outlier_boundary_controls*` as explanatory sidecars. Boundary controls are near-threshold revenue z-score rows below or equal to the L4-01 threshold, not strict L4-01 truth.
- v108 realigns L4-02 group-level Benford truth from current journal rows. Current detector findings and `rule_truth_L4_02.csv` both contain 99 groups with zero diff.
- v108 removes 3 stale Benford groups and adds 2 current Benford findings. It also regenerates `benford_finding_truth*`, `benford_drilldown_candidates*`, normal/skipped group controls, and Benford holdout sidecars from the refreshed group pool.
- L4-01 and L4-03 are z-score review anchors. Normal large transactions can be rule truth and should be triaged downstream.
- Production `data/journal/primary/datasynth/` has not been overwritten by v108.
