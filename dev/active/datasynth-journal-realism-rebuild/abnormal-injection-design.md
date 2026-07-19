# DataSynth Abnormal Injection Design

## Purpose
Semantic abnormal data must be created only by mutating a semantic-clean normal accounting event. The generator itself must not accidentally create semantic violations through independent random field selection.

Required sequence:
1. Select `AccountingEventScenario`.
2. Generate a complete normal event.
3. Run semantic validator.
4. If the normal event fails validation, discard and retry.
5. If an abnormal event is requested, apply `AnomalyMutator`.
6. Record mutation provenance.
7. Run semantic validator again and require provenance for every semantic violation.

## Mutation Record
Every semantic mutation must leave these fields:
- `base_event_type`
- `mutation_type`
- `mutated_field`
- `original_value`
- `mutated_value`
- `reason`

`detection_surface_hints` may also be recorded as optional evaluation metadata. It is not required mutation provenance.

Recommended Rust shape:

```rust
pub struct SemanticMutationRecord {
    pub base_event_type: AccountingEventType,
    pub mutation_type: AnomalyMutationType,
    pub mutated_field: String,
    pub original_value: String,
    pub mutated_value: String,
    pub reason: String,
    pub detection_surface_hints: Option<Vec<String>>,
}
```

The record should be serialized into anomaly metadata and, if the journal schema supports it, exported as columns for dataset auditability. `detection_surface_hints` describes detection surfaces where the mutation may be observable. It must not be used as a generation objective, answer label, recall denominator, rule count target, or VAE training feature.

## Minimum Mutation Types
- `ACCOUNT_COUNTERPARTY_MISMATCH`
- `DOCUMENT_TEXT_MISMATCH`
- `PROCESS_TEXT_MISMATCH`
- `ACCOUNT_TEXT_FAMILY_MISMATCH`
- `COUNTERPARTY_DOCUMENT_MISMATCH`
- `REVENUE_COUNTERPARTY_MISMATCH`
- `TREASURY_VENDOR_MISMATCH`
- `DEPRECIATION_VENDOR_INVOICE_MISMATCH`

## Example
```yaml
base_event_type: H2R_PAYROLL_ACCRUAL
mutation_type: ACCOUNT_COUNTERPARTY_MISMATCH
mutated_field: counterparty_type
original_value: EMPLOYEE
mutated_value: VENDOR_OFFICE_SUPPLIES
reason: Payroll accrual was intentionally assigned to an office supplier to test semantic mismatch detection.
detection_surface_hints:
  - L3-01
  - L4-04
```

## Allowed Mutation Targets
The mutator may change only one semantic dimension per mutation unless the selected mutation type explicitly declares a compound mutation.

Allowed fields:
- `business_process`
- `document_type`
- `source_document`
- `counterparty_type`
- `counterparty_id`
- `counterparty_name`
- `semantic_account_subtype`
- `header_family`
- `header_text`
- `line_text_family`
- `line_text`

Amount, date, approval, and timing anomalies remain separate anomaly families and should not be used to create semantic contradictions unless a semantic mutation record is also written.

## Scenario Guard
Each `AccountingEventScenario` owns `allowed_anomaly_mutations`. `AnomalyMutator` must reject a mutation if it is not listed in the scenario.

Examples:
- `H2R_PAYROLL_ACCRUAL` may allow `ACCOUNT_COUNTERPARTY_MISMATCH`, `DOCUMENT_TEXT_MISMATCH`, and `ACCOUNT_TEXT_FAMILY_MISMATCH`.
- `P2P_VENDOR_INVOICE` may allow `PROCESS_TEXT_MISMATCH` and `ACCOUNT_TEXT_FAMILY_MISMATCH`.
- `A2R_DEPRECIATION` may allow `DEPRECIATION_VENDOR_INVOICE_MISMATCH`.
- `TRE_LOAN_DRAWDOWN` may allow `TREASURY_VENDOR_MISMATCH`.
- `O2C_CUSTOMER_INVOICE` may allow `REVENUE_COUNTERPARTY_MISMATCH`.

## Provenance Rules
- `base_event_type` is copied from the validated normal scenario.
- `original_value` must be read from the event before mutation.
- `mutated_value` must be read from the event after mutation.
- Required provenance consists exactly of `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`.
- `detection_surface_hints`, when present, should name one or more semantic validator surfaces, Phase1 rule surfaces, Phase2 feature groups, or dashboard review surfaces that may observe the mutation.
- `detection_surface_hints` is optional evaluation metadata. It is not a correctness oracle for validator rule matching, detector recall, rule-count reporting, generation objectives, answer labels, or VAE training features.
- If semantic validator fails after mutation and required mutation provenance is missing, the abnormal entry fails provenance validation.
- If semantic validator fails before mutation, the event is not eligible for abnormal injection.

## Integration Points
- Existing `AnomalyLabel::metadata` can store mutation record fields.
- `JournalEntryHeader.anomaly_type` can store `mutation_type` for compatibility, but the full mutation record must still be preserved.
- `SemanticValidator` uses the required mutation provenance fields to decide whether an abnormal semantic violation is labelled or unlabelled. It must not require `detection_surface_hints`.

## Rust Work Items
- Add `SemanticMutationRecord`.
- Add or extend `AnomalyMutationType` with semantic mutation variants.
- Add `AnomalyMutator` entry point that accepts a validated normal event and scenario.
- Ensure mutator refuses non-allowed mutation types for the scenario.
- Write mutation fields into anomaly metadata.
- Run semantic validation before and after mutation.
- Add tests proving accidental generator semantic violations are rejected before mutation.
- Add tests proving abnormal semantic violations fail without mutation provenance.
