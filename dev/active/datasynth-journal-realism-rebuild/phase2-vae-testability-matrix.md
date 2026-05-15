# Phase2 VAE Testability Matrix

## Purpose
Phase2 VAE evaluation uses semantic-clean synthetic normal entries to test whether unsupervised feature reconstruction can surface selected anomaly patterns. Phase2 does not modify DataSynth for VAE score, reconstruction-error shape, rule hit count, or dashboard metric targets.

The VAE training baseline must contain only normal rows that pass the Rust semantic validator. Semantic contradictions may appear in evaluation only when an explicit `AnomalyMutator` record explains the mutated field and advisory detection surface hints.

## Guardrails
- Do not tune normal DataSynth distributions after reading VAE scores.
- Do not make abnormal examples visually or statistically easy only to improve VAE metrics.
- Do not simplify normal distributions to make reconstruction error cleaner.
- Do not include `label`, `rule_id`, `mutation_type`, `expected_rule`, `detection_surface_hints`, or rule-hit columns in training features.
- Use `mutation_type` only as evaluation metadata for slicing errors by injected anomaly family.
- Treat synthetic results as detector-behavior evidence on controlled data, not as a claim about production journal-entry performance.

## Training Feature Candidates
These fields are allowed only after the row is confirmed semantic-clean when used for normal training:

| Feature | Type | Purpose | Required DataSynth Condition |
|---|---|---|---|
| `event_type` | categorical | Captures accounting-event identity | Scenario catalog assigns every row |
| `business_process` | categorical | Captures P2P, O2C, H2R, R2R, A2R, Treasury, Intercompany domain | Copied from scenario |
| `debit_account_subtype` | categorical | Captures debit semantic account meaning | Semantic subtype resolver populated |
| `credit_account_subtype` | categorical | Captures credit semantic account meaning | Semantic subtype resolver populated |
| `counterparty_type` | categorical | Captures counterparty domain | Counterparty master typed |
| `document_type` | categorical | Captures source-document semantics | Scenario document selection populated |
| `source_type` | categorical | Captures interface, manual, batch, and recurring source | Existing source metadata normalized |
| `line_text_family` | categorical | Captures text family without raw free-text leakage | Scenario text-family generation populated |
| `amount_bucket` | ordinal or categorical | Captures amount scale without memorizing exact value | Stable bucket policy defined before evaluation |
| `posting_month` | ordinal or categorical | Captures monthly seasonality | Posting date available |
| `posting_day_of_week` | categorical | Captures weekday pattern | Posting date available |
| `posting_hour` | ordinal or categorical | Captures time-of-day pattern | Posting timestamp available |
| `manual_or_batch` | categorical | Captures manual versus system pattern | Source metadata mapped |
| `reversal_flag` | boolean | Captures reversal behavior | Reversal metadata populated |
| `related_party_flag` | boolean | Captures related-party involvement | Counterparty type or master flag populated |

## Excluded Features
These fields are never training inputs:

| Excluded Field | Reason |
|---|---|
| `label` | Direct anomaly target leakage |
| `is_anomaly` | Direct anomaly target leakage |
| `rule_id` | Rule-output leakage |
| `rule_hit` | Rule-output leakage |
| `mutation_type` | Injected anomaly provenance, evaluation metadata only |
| `expected_rule` | Legacy expected-rule field; excluded to prevent target leakage |
| `detection_surface_hints` | Advisory detection-surface metadata; excluded to prevent target and analysis leakage |
| `reason` | Human-readable anomaly explanation leakage |
| `base_event_type` | Mutation provenance; use `event_type` from the row instead |
| `mutated_field` | Injected anomaly provenance leakage |
| `original_value` | Injected anomaly provenance leakage |
| `mutated_value` | Injected anomaly provenance leakage |

## Testability Classes
| Class | Meaning | Phase2 Interpretation |
|---|---|---|
| A | Synthetic data is sufficient for controlled detector testing | VAE behavior can be tested with current or planned non-label features |
| B | Testable after semantic-clean features exist | Requires scenario metadata and semantic validator output from the DataSynth rebuild |
| C | Synthetic testing is limited | Use only for smoke and regression checks on feature plumbing |
| D | Real journal data is required for trustworthy evaluation | Re-train and revalidate after real data is available |

## VAE Testability Matrix
| Anomaly or Behavior | Class | Candidate Features | Synthetic Evaluation Scope | Limit and Real-Data Need |
|---|---|---|---|---|
| Amount outlier | A | `amount_bucket`, account subtypes, `event_type` | Confirm high or rare amount buckets increase anomaly score compared with clean peer events | Real materiality thresholds and vendor-specific ranges require real journals |
| Unusual posting hour | A | `posting_hour`, `manual_or_batch`, `source_type` | Confirm after-hours or rare-hour postings are scored higher within comparable event groups | Real user working hours require production timestamps |
| Rare posting weekday | A | `posting_day_of_week`, `source_type`, `business_process` | Test weekend or holiday-like pattern sensitivity in controlled samples | Local holiday calendars and close schedules require company data |
| Month-end concentration | A | `posting_month`, posting day features, `event_type` | Test whether unusual month or period concentration changes score | Real close calendar, cut-off practice, and seasonality require real history |
| Manual versus batch rarity | A | `manual_or_batch`, `source_type`, `event_type` | Verify rare manual postings inside normally batched events are visible | Real source-system mix and user practice require real logs |
| Reversal pattern anomaly | A | `reversal_flag`, `event_type`, amount features | Test rare reversals and unusual reversal amount buckets | Real reversal policy and correction workflow require real data |
| Related-party flag rarity | A | `related_party_flag`, `business_process`, `counterparty_type` | Test whether rare related-party usage is separable from normal peers | Real related-party population and disclosure policy require master data |
| Account-process-counterparty mismatch | B | `event_type`, `business_process`, account subtypes, `counterparty_type` | Evaluate injected semantic mutations after normal rows pass validator | VAE may flag rarity but cannot prove accounting invalidity without validator or rule layer |
| Document-account mismatch | B | `document_type`, account subtypes, `line_text_family`, `event_type` | Evaluate explicit document mutation such as payroll text under purchase invoice | VAE detects feature inconsistency only if semantic families are encoded cleanly |
| Text-family and account subtype mismatch | B | `line_text_family`, account subtypes, `event_type` | Test injected family swaps after scenario text generation is implemented | Raw line text meaning remains outside VAE unless converted into governed families |
| Revenue with non-customer counterparty | B | `event_type`, `business_process`, account subtypes, `counterparty_type`, `document_type` | Test controlled mutation from customer to vendor, bank, or internal department | VAE can rank rarity; semantic invalidity remains validator responsibility |
| Payroll with office supplier or AP vendor | B | `event_type`, account subtypes, `counterparty_type`, `document_type`, `line_text_family` | Test mutation from employee or payroll provider to office supplier | VAE score should be analyzed beside semantic validator outcome |
| Treasury event with ordinary purchase vendor | B | `business_process`, `event_type`, `counterparty_type`, `document_type` | Test mutation from bank to vendor category | Real bank account and lender master semantics require production master data |
| Industry-specific accounting practice | C | `event_type`, account subtypes, `document_type` | Smoke-test feature availability only | Industry norms require sector-specific historical entries |
| Company policy violation | C | `source_type`, `manual_or_batch`, account subtypes, approval-related features when present | Verify the pipeline can carry policy-relevant features | Policy thresholds and exceptions require company policy data |
| Counterparty real-world meaning | C | `counterparty_type`, `related_party_flag`, master-data-derived features | Verify typed counterparties are carried into matrix building | External entity meaning, ownership links, and sanctions context require real enrichment |
| Real user behavior anomaly | D | user, approver, timestamp, source, override features | Synthetic data can only test column handling when available | Production user behavior requires real audit logs and re-training |
| Real approval practice anomaly | D | approver, approval limit, amount, override flags | Synthetic data can only test schema compatibility | Approval norms require workflow history and approval authority tables |
| Real counterparty network anomaly | D | counterparty graph, bank account, related-party links | Synthetic data can only test engineered feature ingestion | Network shape and entity relationships require real master data and payments |

## Detectable Versus Undetectable Semantics
Detectable with semantic-clean features:
- Rare or inconsistent combinations across `event_type`, account subtype, `counterparty_type`, `document_type`, `source_type`, and `line_text_family`.
- Numeric or temporal deviations represented by stable feature buckets.
- Manual/batch, reversal, and related-party rarity when those fields are populated.

Not reliably detectable by VAE alone:
- Whether a journal entry violates accounting rules when the violation is common in synthetic data.
- Whether a counterparty is truly a bank, employee, customer, related party, or tax authority without typed master data.
- Whether a posting violates company policy, approval authority, close calendar, or industry practice.
- Whether a semantic contradiction is abnormal when `label`, `mutation_type`, or detection-surface hint metadata is needed to know the injected cause.

## Synthetic Evaluation Scope
Synthetic evaluation can report:
- Score distribution for semantic-clean normal baseline rows.
- Score distribution for explicit abnormal mutations, grouped by `mutation_type` as metadata after scoring.
- Feature-group reconstruction contribution for amount, time, source, event, account, counterparty, document, and text-family groups.
- Regression evidence that excluded leakage fields are absent from the training matrix.
- Regression evidence that normal training rows passed semantic validation before VAE fitting.

Synthetic evaluation must not report:
- Production recall, precision, or alert volume expectations.
- Rule-level recall optimized by abnormal injection volume.
- Dashboard target counts as quality evidence.
- VAE superiority for semantic rules that require validator logic.

## Real Journal Data Re-Training and Re-Validation Needs
When real journal data is available, Phase2 must re-train and revalidate:
- Amount buckets and materiality behavior by company, account, counterparty, and period.
- Posting hour, weekday, and close-calendar behavior.
- Manual, batch, recurring, reversal, and interface-source behavior.
- User, preparer, approver, and approval-limit behavior.
- Counterparty network, bank-account, related-party, employee, and tax-authority semantics.
- Industry-specific and company-policy patterns.
- Feature drift between synthetic scenario catalog distributions and real journal distributions.

## Acceptance Criteria
- VAE training feature preparation drops all excluded fields listed in this document.
- Training baseline filter requires normal label and semantic validator pass.
- Evaluation analysis may group by `mutation_type` only after model scoring.
- Synthetic Phase2 report separates A, B, C, and D claims.
- Any Phase2 finding on semantic contradictions is cross-referenced with semantic validator or Phase1 rule output before interpretation.
