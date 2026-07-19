# DataSynth Semantic Validator Design

## Purpose
Semantic validation is the hard gate that prevents invalid accounting meaning from entering the normal baseline. The validator must run inside Rust DataSynth before export, not as a Python CSV repair step.

The validator checks both journal-entry header semantics and individual line semantics. Normal entries fail on any semantic contradiction. Abnormal entries may contain contradictions only when they include required mutation provenance: `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`. `detection_surface_hints` describes detection surfaces that may observe the mutation, but it is optional evaluation metadata and not validator truth.

## Required Inputs
The validator needs these fields or equivalent in-memory context:
- `scenario_id`
- `event_type`
- `business_process`
- `document_type`
- `source_document`
- `counterparty_type`
- `counterparty_id`
- `counterparty_name`
- `header_family`
- `header_text`
- line-level `semantic_account_subtype`
- line-level core `AccountSubType`
- line-level `line_text_family`
- line-level `line_text`
- anomaly fields: `is_anomaly`, `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, `detection_surface_hints`, `reason`

## Validation Scope

### Entry-Level Checks
Entry-level checks inspect the journal header and cross-line context.
- `scenario_id` is present for every generated entry.
- `business_process` matches the selected scenario.
- `document_type` is one of `scenario.allowed_document_types`.
- `counterparty_type` is one of `scenario.allowed_counterparty_types`.
- `header_family` is one of `scenario.allowed_header_families`.
- Abnormal entries with semantic contradictions have required mutation provenance fields: `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`.

### Line-Level Checks
Line-level checks inspect every debit and credit line.
- `semantic_account_subtype` is present for COGS/OPEX broad core account classes.
- `semantic_account_subtype` is allowed by the selected scenario for the line side.
- `line_text_family` is one of `scenario.allowed_line_text_families`.
- `line_text_family` is compatible with `semantic_account_subtype`.
- Line text tokens do not contradict the scenario, document, or counterparty domain.

## Mandatory Fail Conditions
These fail conditions apply to normal entries and to abnormal entries without mutation provenance.

| Rule ID | Scope | Fail condition |
| --- | --- | --- |
| `SEM001_SCENARIO_ID_REQUIRED` | Entry | Normal entry has no `scenario_id`. |
| `SEM002_LABOR_TEXT_P2P` | Entry + Line | Labor, payroll, or direct labor text appears with `P2P`. |
| `SEM003_LABOR_WITH_AP_GRIR` | Line + Cross-line | Labor, payroll, or direct labor appears in an entry that uses `AP` or `GRIR`. |
| `SEM004_LABOR_WITH_OFFICE_SUPPLIER` | Entry + Line | Labor, payroll, or direct labor appears with `VENDOR_OFFICE_SUPPLIES` or office-supplier name signals. |
| `SEM005_PURCHASE_TAX_INVOICE_PAYROLL_TEXT` | Entry + Line | `PURCHASE_INVOICE` or `TAX_INVOICE` carries payroll/labor text. |
| `SEM006_DEPRECIATION_WITH_AP_VENDOR` | Entry + Line | Depreciation text/family/subtype appears with AP vendor invoice, `AP`, or ordinary vendor counterparty. |
| `SEM007_REVENUE_NON_CUSTOMER_COUNTERPARTY` | Entry + Line | Revenue account or customer billing text appears with non-`CUSTOMER` counterparty, excluding explicit intercompany sale scenarios. |
| `SEM008_CUSTOMER_INVOICE_REVENUE_NON_O2C` | Entry | Customer invoice revenue appears outside `O2C`, excluding explicit intercompany sale scenarios. |
| `SEM009_SUBTYPE_TEXT_FAMILY_MISMATCH` | Line | Account semantic subtype and `line_text_family` are incompatible. |
| `SEM010_ABNORMAL_PROVENANCE_REQUIRED` | Entry | Abnormal entry has any semantic violation but lacks one or more required mutation provenance fields: `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, or `reason`. |

## Text Signal Detection
The validator should prefer explicit `line_text_family`, but it must also detect raw text leakage as a defense layer.

Labor/payroll/direct labor signals:
- Korean: `급여`, `상여`, `미지급급여`, `직접노무비`, `생산직 급여`, `인건비`, `원천세`, `4대보험`, `퇴직급여`
- English: `payroll`, `salary`, `wage`, `bonus`, `direct labor`, `labor cost`, `withholding`

Office supplier signals:
- Korean: `기업문구`, `오피스`, `문구`, `제지`, `사무용품`, `복사용지`, `토너`
- English: `office`, `stationery`, `paper`, `copy paper`, `toner`

Depreciation signals:
- Korean: `감가상각`, `상각비`, `감가상각누계액`
- English: `depreciation`, `accumulated depreciation`, `amortization`

Revenue/customer invoice signals:
- Korean: `매출`, `고객 청구`, `세금계산서`, `채권`
- English: `revenue`, `sales invoice`, `customer invoice`, `billing`

## Normal Handling
For `is_anomaly = false`:
- Any mandatory fail condition returns `Err(SemanticValidationError)`.
- `JournalEntryGenerator` must discard and retry the entry.
- A bounded retry failure should fail tests rather than emitting invalid normal data.

## Abnormal Handling
For `is_anomaly = true`:
- Run the same checks and collect violations.
- If no violation exists, pass.
- If violations exist, require `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`.
- `detection_surface_hints` identifies detection surfaces where the mutation may be observed. It is optional evaluation metadata and must not be treated as an answer label, generation target, recall basis, rule-count target, or VAE training feature.
- The validator must not fail an abnormal row solely because `detection_surface_hints` does not match a failed semantic rule.
- `reason` should be present for audit traceability; missing `reason` is a warning unless the implementation chooses to make it hard fail.

## Validator API Direction
Add a Rust validator such as:

```rust
pub struct SemanticValidator;

pub struct SemanticValidationContext<'a> {
    pub scenario: &'a AccountingEventScenario,
    pub base_event_type: Option<&'a str>,
    pub mutation_type: Option<&'a str>,
    pub mutated_field: Option<&'a str>,
    pub original_value: Option<&'a str>,
    pub mutated_value: Option<&'a str>,
    pub reason: Option<&'a str>,
    pub detection_surface_hints: Option<&'a [String]>,
}

impl SemanticValidator {
    pub fn validate_entry(
        entry: &JournalEntry,
        context: &SemanticValidationContext,
    ) -> Result<(), Vec<SemanticValidationError>>;
}
```

`SemanticValidationError` should include:
- `rule_id`
- `scope`
- `document_id`
- optional `line_number`
- `message`
- actual values used in the decision

## Rust Work Items
- Add `scenario_id`, `header_family`, line-level `semantic_account_subtype`, and line-level `line_text_family` to generated JE context or exported fields.
- Implement semantic validator in Rust DataSynth generation code.
- Call validator before anomaly mutation for normal candidate events.
- Call validator after anomaly mutation to enforce required mutation provenance. Keep `detection_surface_hints` optional and excluded from VAE training features.
- Add tests for all mandatory fail rules.
- Add a zero-violation test over a sample of normal scenario-generated entries.
