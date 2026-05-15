# Phase1 Rule Testability Matrix

## Scope
Phase1 does not modify DataSynth to fit rule counts, recall, dashboard totals, or demo distributions. This matrix classifies what each Phase1 rule can legitimately prove with synthetic data.

## Classification
- **A. Synthetic-sufficient**: synthetic data can test rule logic and expected edge cases without semantic-clean generator changes.
- **B. Semantic-clean required**: useful synthetic validation requires the accounting-event, semantic subtype, counterparty, document, and text-family fixes described in this planning set.
- **C. Smoke/regression only**: synthetic data can test code paths, stability, and obvious edge cases, but not reliable performance.
- **D. Real-ledger required**: real journal data is needed for reliability or business-validity assessment.

## Guardrails
- Do not modify DataSynth to match rule hit counts, recall, or dashboard numbers.
- Do not over-inject abnormal rows to make a rule look effective.
- Do not fit data specifically for semantic rules such as `L3-01` or `L4-04`.
- Do not use `rule_id`, `expected_rule`, or dashboard desired counts as generation criteria.
- If semantic-clean normal data produces hits, record whether the cause is generator contamination or rule logic.

## Matrix

| Rule | Rule name | Class | Data conditions | Current DataSynth status | Missing conditions recorded as DataSynth requirements | Real JE data needed? |
| --- | --- | --- | --- | --- | --- | --- |
| `L1-01` | Unbalanced Entry | A | `document_id`, `debit_amount`, `credit_amount`, line grouping | Sufficient for structural logic; generator already balances most normal entries | Keep explicit abnormal imbalance labels separate from normal balance guarantee | Not for logic; yes for materiality calibration |
| `L1-02` | Missing Required Field | A | Required column set, null/blank handling | Sufficient for schema/null regression | Maintain stable required-column contract | Not for logic |
| `L1-03` | Invalid Account | A | `gl_account`, CoA master, postable flag | Sufficient for unknown-account regression | CoA coverage by company/country if multi-entity grows | Not for logic |
| `L1-04` | Exceeded Approval Limit | A | amount, `created_by`, user approval limit/level, approval policy | Mostly sufficient; approval threshold fields exist in generator path | Preserve user approval-limit master and amount basis | Real data needed for threshold reasonableness |
| `L1-05` | Self Approval | A | `created_by`, `approved_by`, automated/manual source | Sufficient for control-bypass logic | Keep automated/recurring entries excluded from human approval requirements | Real data needed for frequency expectations |
| `L1-06` | Segregation of Duties Violation | A | user role/persona, allowed process scope, `created_by`, `business_process` | Sufficient for code regression; user-process map exists | Keep SoD policy explicit and independent from target hit counts | Real data needed for role-policy completeness |
| `L1-07` | Skipped Approval | A | amount, approval threshold, `approved_by`, source type | Sufficient for logic regression | Preserve approval-required flag or derivable threshold | Real data needed for policy calibration |
| `L1-08` | Wrong Fiscal Period | A | `posting_date`, `fiscal_period`, fiscal calendar | Sufficient for calendar logic | Add non-calendar-year fiscal profiles only if supported scenarios need them | Real data not required for logic |
| `L1-09` | Approval Date Missing | A | `approved_by`, `approval_date`, source type | Sufficient for missing-date regression | Keep approval workflow fields consistent for manual entries | Real data not required for logic |
| `L2-01` | Just Below Approval Threshold | A | amount, approval threshold, document grouping, source type | Sufficient for boundary logic | Do not tune amount distribution to target hit count | Real data needed for threshold-band prevalence |
| `L2-02` | Duplicate Payment | B | counterparty type/id, amount, reference, payment document type, date window | Partially sufficient; requires scenario-clean counterparty/document semantics | Add scenario-owned payment events and typed counterparties | Real data useful for duplicate-pattern prevalence |
| `L2-03` | Duplicate Entry | A | document signature fields: company, amount, date, account pair, reference, counterparty | Sufficient for duplicate-signature regression | Keep natural batch similarity separate from explicit duplicate mutation | Real data needed for operational false-positive rate |
| `L2-04` | Expense Capitalization Signal | B | semantic account subtype, asset/expense account classes, document type, text family | Current broad OPEX/COGS can contaminate this rule | Add semantic subtypes and scenario text family validation | Real data needed for capitalization policy judgment |
| `L2-05` | Reversal Pattern | A | reversal source, amount, account pair, document date/posting date, reference linkage | Sufficient for reversal matching regression | Add explicit source-event linkage for stronger validation | Real data useful for normal reversal cadence |
| `L3-01` | Misclassified Account | B | business process, semantic account subtype, scenario id, counterparty type, line text family | Current DataSynth has known process/account/text contamination | Complete accounting-event scenario catalog and semantic validator | Real data needed for allowed-process policy completeness |
| `L3-02` | Manual Entry Override | A | `source`, `document_type`, created user, amount, approval context | Sufficient for source/manual regression | Keep source type independent from rule target counts | Real data needed for manual-entry baseline |
| `L3-03` | Related Party Transaction Review Signal | B | related-party counterparty, company code, trading partner, IC document type | Partially present; needs `RELATED_PARTY` counterparty type and IC scenario catalog | Add related-party master and IC scenarios | Real data needed for related-party register completeness |
| `L3-04` | Period-start/end Closing Review Candidate | A | `posting_date`, fiscal period, source type, amount | Sufficient for date-window logic | Do not force month-end concentration for dashboard totals | Real data needed for client close-calendar calibration |
| `L3-05` | Weekend Posting | A | `posting_date`, holiday/weekend calendar, source type | Sufficient for calendar regression | Maintain country holiday calendar metadata | Real data useful for normal weekend operations |
| `L3-06` | After-hours Posting | A | `created_at` or posting timestamp, user/source type, working-hours calendar | Sufficient for time-window logic | Keep timezone and working-hour profile explicit | Real data needed for client work schedule |
| `L3-07` | Posting-Document Date Gap | A | `posting_date`, `document_date`, document type | Sufficient for gap bucket logic | Add scenario-specific expected lag profiles if needed | Real data needed for normal lag distribution |
| `L3-08` | Missing or Corrupted Description | A | `header_text`, `line_text`, encoding/corruption/null detection | Sufficient for missing/corrupt regression | Keep text corruption noise independent from semantic anomalies | Real data not required for logic |
| `L3-09` | Suspense Aging | B | suspense/clearing account subtype, open item age, clearing status/reference | Current JE-only data can smoke-test account flags but not aging reliability | Add open-item lifecycle or clearing status for aging validation | Real data needed for aging reliability |
| `L3-10` | High-risk Account Use | B | sensitive account list, semantic subtype, process, approval/source context | Synthetic can test list matching; semantic-clean needed to avoid generator contamination | Keep sensitive-account list configurable and scenario-clean | Real data needed for client-specific high-risk accounts |
| `L3-11` | Revenue Cutoff Mismatch | B | revenue subtype, customer invoice, shipment/delivery date, posting/document date, customer counterparty | Current fields partly exist; needs O2C customer invoice scenario and clean delivery/source docs | Add scenario-owned O2C invoice/receipt document semantics | Real data needed for cutoff policy and shipping evidence |
| `L3-12` | Work Scope Excess Review | C | user-to-company/process scope, assigned process map, access scope, created_by | Synthetic can regression-test scoring; reliability depends on real access rights | Add explicit user access-role master if not already exported | Real data required for access-scope reliability |
| `L4-01` | Revenue Outlier | C | revenue account/subtype, amount distribution by company/account/period | Synthetic can test outlier math, not true revenue baseline | Semantic-clean revenue scenarios and stable population sizes | Real data required for reliability |
| `L4-02` | Benford Violation | C | amount population size, account scope, positive numeric amounts | Synthetic can smoke/regression-test Benford implementation | Avoid shaping amounts to satisfy Benford dashboards | Real data required for meaningful Benford interpretation |
| `L4-03` | High Amount Outlier | C | amount, company/account/process grouping, materiality or robust distribution | Synthetic can test thresholds and sorting | Materiality profile and distribution profile as config, not target counts | Real data required for reliable thresholding |
| `L4-04` | Rare Debit-Credit Account Pair | B | debit/credit semantic account subtype pair, scenario id, process, counterparty type | Current broad account-pair generation causes false semantic rarity | Complete scenario catalog and semantic subtype validation | Real data needed for client-specific rare-but-valid pairs |
| `L4-05` | Abnormal Hours Cluster | C | timestamp, created_by, source type, user population, clustering window | Synthetic can test clustering code paths | Do not inject night-owl clusters to match desired dashboard totals | Real data required for behavioral reliability |
| `L4-06` | Batch Posting Outlier | C | created_by, posting timestamp, source, batch-like grouping, document sequence | Synthetic can test batch detection mechanics | Keep normal batching realistic but not fitted to hits | Real data required for operational batch baseline |

## Auxiliary Phase1 Surfaces
These are shown with Phase1 results or drill-downs but are not part of the 32 canonical L1-L4 transaction rules.

| Rule | Class | Data conditions | Current DataSynth status | Missing conditions | Real JE data needed? |
| --- | --- | --- | --- | --- | --- |
| `D01` | C | Prior-period account activity by company/account | Synthetic multi-year data can smoke-test; reliability depends on prior actuals | Prior-year comparable ledger summaries | Yes |
| `D02` | C | Prior-period monthly ratio distribution by account/company | Synthetic can regression-test variance code | Stable prior/current periods and comparable business seasonality | Yes |
| `IC01` | B | related-party master, reciprocal company code, IC counterparty matching | Needs `RELATED_PARTY` counterparty and IC scenario cleanup | Intercompany source/target linkage | Real data needed for completeness |
| `IC02` | B | IC reciprocal amount, tolerance, company pair | Needs explicit IC paired events | Reciprocal event id and amount tolerance metadata | Real data needed for completeness |
| `IC03` | B | IC reciprocal timing/date gap, company pair | Needs explicit IC paired events | Reciprocal event id and timing tolerance metadata | Real data needed for completeness |
| `GR01` | C | graph edge data across counterparties/accounts/documents | Synthetic can smoke-test graph algorithms | Entity graph extraction and stable relationship model | Yes |
| `GR03` | C | related-party graph and transfer-pricing edge signals | Synthetic can smoke-test graph algorithms | Related-party graph plus pricing/evidence fields | Yes |

## DataSynth Requirement Backlog Only
These are requirements to make synthetic validation fair. They are not instructions to tune detection counts.

- Scenario metadata: `scenario_id`, `event_type`, `document_type`, `source_document`.
- Semantic account metadata: `semantic_account_subtype`, core `AccountSubType`, debit/credit side.
- Counterparty metadata: `counterparty_type`, id, name, related-party flag.
- Text metadata: `header_family`, `line_text_family`, raw header/line text.
- Approval metadata: approval threshold, approver, approval date, created_by, source type.
- Timing metadata: posting date, document date, created timestamp, timezone, fiscal calendar.
- IC metadata: related-party pair id, reciprocal document id, amount/timing tolerance.
- Prior-period metadata for D01/D02.

## Interpretation Rules
- For A rules, synthetic data can validate deterministic rule logic and edge cases.
- For B rules, do not judge rule performance until semantic-clean generation exists.
- For C rules, use synthetic results only for smoke/regression; do not report synthetic recall as reliability evidence.
- For D-level needs embedded in C rules, real client ledger data is required for performance claims.
- When semantic-clean normal entries trigger B semantic rules, classify the root cause as either generator contamination or detector logic issue before changing any data.
