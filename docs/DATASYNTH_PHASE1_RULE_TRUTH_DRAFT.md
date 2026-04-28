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

Important:

- Suppression of monthly recurring payments is a detector-priority decision, not a DataSynth truth exclusion.
- Confirmed duplicate-payment fraud can be stored separately as `audit_issue_truth` or pair metadata.
- Pair metadata is required because the evidence is a payment pair, not just a single document.

### L2-03: Duplicate Entry

Rule truth:

- Positive if an entry looks duplicated, re-entered, copied with small changes, near-duplicated, or split into multiple related entries.
- Exact duplicates, document-shape duplicates, reference duplicates, near duplicates, and split duplicates are all rule truth.

Important:

- DataSynth truth does not assign final confidence. Confidence bands are detector/case-builder output.
- Normal recurring, intercompany, or operational lookalikes may still be useful controls, but they should not be removed from rule truth when the L2-03 rule is expected to surface them.

### L2-04: Expense Capitalization

Rule truth:

- Positive if an expense-nature amount appears to be moved into an asset account pattern that Phase 1 should review.
- Both high-priority and review-priority capitalization candidates are rule truth.

Important:

- Normal capitalization context is not removed from rule truth at DataSynth time when the rule should surface it.
- Later code can lower priority or mark normal-control context based on document type, text, process, or policy.

### L2-05: Reversal Pattern

Rule truth:

- Positive if the entry looks like a reversal, cancellation, correction, clearing, offset, or reclassification pattern that Phase 1 should surface.
- High-confidence reversal and candidate clearing/reclass patterns are both rule truth.

Important:

- DataSynth truth should not keep only the confirmed `ReversedAmount` subset.
- ERP reversal links, opposite-sign same-account matches, line-swap signatures, rolling zero-out patterns, and reversal keywords can all support L2-05 rule truth.

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

### L3-04: Period-End/Period-Start Large Or Manual Posting

Rule truth:

- Positive if the entry is near period end/start and is high amount or manual.

Important:

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

Important:

- Normal batch processing can still be L4-06 rule truth.
- L4-06 is a combo/booster signal. Downstream scoring decides whether the batch hit is low priority, normal control, or elevated by other rule hits.

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

## v74-v81 Candidate Patch Status

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

Latest candidate path:

`data/journal/primary/datasynth_v81_candidate`

Latest `rule_truth.csv` counts:

| Rule | Count |
|------|------:|
| L1-01 | 303 |
| L1-02 | 86 |
| L1-03 | 32 |
| L1-04 | 56 |
| L1-05 | 244 |
| L1-06 | 19 |
| L1-07 | 76 |
| L1-08 | 731 |
| L1-09 | 102 |
| L2-01 | 457 |
| L2-02 | 33 |
| L2-03 | 96 |
| L2-04 | 563 |
| L2-05 | 113 |
| L3-04 | 117,589 |
| L3-12 | 266,863 |
| L4-01 | 965 |
| L4-03 | 4,014 |

Notes:

- L1-09 is intentionally broad under the user's current rule-truth policy: if approval date is missing, it is rule truth. v81 fills unlabeled routine automated/recurring documents with system approval traces, so remaining L1-09 truth is concentrated in manual/adjustment documents.
- L1-05 is intentionally broad: if `created_by == approved_by`, it is rule truth even for automated/system contexts. v79 adds 27 system self-approval controls across years.
- L1-06 is direct SoD truth only in v80. Direct markers and IT/admin direct business posting evidence stay in L1-06.
- L3-12 is a large work-scope review population, not a confirmed violation label. It must be reported separately from L1-06 precision/recall.
- L1-07 is intentionally broad: if `approved_by` is missing, it is rule truth. v81 reduces unrealistic automated/recurring gaps and leaves manual/adjustment missing-approver candidates.
- L3-04 is broad because period-start/end plus high amount or manual source is a review candidate population, not a confirmed fraud label.
- L4-01 and L4-03 are z-score review anchors. Normal large transactions can be rule truth and should be triaged downstream.
- Production `data/journal/primary/datasynth/` has not been overwritten by v81.
