# DataSynth Counterparty Master Design

## Purpose
Normal journal generation must select counterparties only from the selected scenario's `allowed_counterparty_types`. Counterparty names and counterparty types must agree. This prevents payroll rows from receiving office suppliers, treasury rows from receiving purchase vendors, and customer invoices from receiving non-customer counterparties.

## Required CounterpartyType Values
- `VENDOR_OFFICE_SUPPLIES`
- `VENDOR_RAW_MATERIAL`
- `VENDOR_SERVICE`
- `VENDOR_LOGISTICS`
- `VENDOR_UTILITIES`
- `EMPLOYEE`
- `PAYROLL_PROVIDER`
- `TAX_AUTHORITY`
- `CUSTOMER`
- `BANK`
- `RELATED_PARTY`
- `INTERNAL_DEPARTMENT`

## Current Code Shape
- `tools/datasynth/crates/datasynth-core/src/models/master_data.rs` has `VendorType` and `CustomerType`, but no cross-entity `counterparty_type`.
- `VendorType::Supplier` currently mixes raw materials, office supplies, equipment, and general suppliers.
- `JournalEntryGenerator` currently selects `vendor_pool.random_vendor()` for both `P2P` and `Treasury`, which lets bank/treasury events receive ordinary vendors.
- `H2R`, `Tax`, bank, and internal department counterparties are not represented as first-class counterparty pools in normal JE selection.

## Data Model Contract
Add a semantic `CounterpartyType` enum in Rust and attach it to every counterparty source used by journal generation.

Recommended placement:
- Primary enum: `tools/datasynth/crates/datasynth-core/src/models/master_data.rs` if exported in CSV/master data outputs.
- Generator-only mirror or re-export: `tools/datasynth/crates/datasynth-generators/src/process_gl_mapping.rs` if the scenario catalog owns semantic rules.

Required fields:
- `Vendor.counterparty_type: CounterpartyType`
- `Customer.counterparty_type: CounterpartyType`
- Employee-derived counterparty record with `counterparty_type = EMPLOYEE`
- Bank-derived counterparty record with `counterparty_type = BANK`
- Tax authority counterparty record with `counterparty_type = TAX_AUTHORITY`
- Internal department counterparty record with `counterparty_type = INTERNAL_DEPARTMENT`
- Intercompany/related-party records with `counterparty_type = RELATED_PARTY`

## Name Classification Rules
These rules are for generation and validation. A normal counterparty name must match its assigned `counterparty_type`.

| Name signal | CounterpartyType |
| --- | --- |
| `기업문구`, `오피스`, `문구`, `제지`, `사무용품`, `Office`, `Stationery`, `Paper` | `VENDOR_OFFICE_SUPPLIES` |
| `소재`, `원재료`, `부품`, `철강`, `화학`, `Raw`, `Material` | `VENDOR_RAW_MATERIAL` |
| `회계법인`, `컨설팅`, `빌딩관리`, `정비`, `용역`, `Service`, `Consulting` | `VENDOR_SERVICE` |
| `물류`, `택배`, `운송`, `Freight`, `Logistics`, `Shipping` | `VENDOR_LOGISTICS` |
| `전력`, `가스`, `상수도`, `통신`, `Electric`, `Gas`, `Water`, `Telecom`, `Utility` | `VENDOR_UTILITIES` |
| Korean person name, employee ID, `사번`, `급여대상자`, `Employee` | `EMPLOYEE` |
| `Payroll`, `급여대행`, `인사급여`, `사회보험`, `Benefit` | `PAYROLL_PROVIDER` |
| `세무서`, `국세`, `지방세`, `Tax`, `Revenue Service`, `NTS` | `TAX_AUTHORITY` |
| customer master record, `고객`, `거래처-매출`, `Customer` | `CUSTOMER` |
| `은행`, `Bank`, `IBK`, `국민`, `신한`, `하나`, `우리`, `KDB` | `BANK` |
| `관계사`, `계열`, `Intercompany`, related company code | `RELATED_PARTY` |
| department code, cost center, `부서`, `팀`, `센터`, `Department` | `INTERNAL_DEPARTMENT` |

## Existing Type Mapping

| Existing type | Default counterparty type | Notes |
| --- | --- | --- |
| `VendorType::Supplier` | split by name into `VENDOR_RAW_MATERIAL` or `VENDOR_OFFICE_SUPPLIES` | Do not leave generic for normal JE selection. |
| `VendorType::ServiceProvider` | `VENDOR_SERVICE` | Building management and repairs stay service. |
| `VendorType::Utility` | `VENDOR_UTILITIES` | Used by P2P utilities invoice scenarios. |
| `VendorType::ProfessionalServices` | `VENDOR_SERVICE` | Tax authority is not a professional-service vendor. |
| `VendorType::Technology` | `VENDOR_SERVICE` | Treat software, cloud, license, and IT support vendors as service vendors for the current catalog. |
| `VendorType::Logistics` | `VENDOR_LOGISTICS` | Used for freight/COGS logistics scenarios. |
| `VendorType::Financial` | `BANK` | Prefer first-class bank pool for treasury events. |
| `VendorType::EmployeeReimbursement` | `EMPLOYEE` | Should not be selected for vendor invoice payroll/direct labor scenarios. |
| `CustomerType::*` except `Intercompany` | `CUSTOMER` | Customer invoices and receipts only. |
| `CustomerType::Intercompany` | `RELATED_PARTY` | Intercompany scenarios only. |
| `Vendor.is_intercompany = true` | `RELATED_PARTY` | Intercompany scenarios only. |

## Scenario Selection Rule
Normal `JournalEntryGenerator` must not call unfiltered `random_vendor()` or `random_customer()` after scenario selection.

Required flow:
1. Select `AccountingEventScenario`.
2. Read `scenario.allowed_counterparty_types`.
3. Select a counterparty from a unified counterparty view or a typed pool filtered by those allowed types.
4. Validate the selected counterparty name and type.
5. Fail, retry, or drop the normal event if no matching counterparty exists.

Allowed examples:
- `P2P_VENDOR_INVOICE` + `OPEX_OFFICE_SUPPLIES` + `AP` may select only `VENDOR_OFFICE_SUPPLIES`.
- `H2R_PAYROLL_ACCRUAL` + `OPEX_PAYROLL` may select `EMPLOYEE`, `PAYROLL_PROVIDER`, `TAX_AUTHORITY`, or `INTERNAL_DEPARTMENT`.
- `TRE_LOAN_DRAWDOWN` may select only `BANK` or lender-like `BANK` records.
- `O2C_CUSTOMER_INVOICE` may select only `CUSTOMER`.

Forbidden normal examples:
- Payroll/labor/direct labor with `VENDOR_OFFICE_SUPPLIES`.
- Payroll/labor/direct labor with generic external AP vendor.
- Treasury bank event with ordinary purchase vendor.
- Customer invoice with vendor, employee, bank, or internal department counterparty.
- Depreciation event with AP vendor invoice counterparty.

## Rust Work Items
- Add `CounterpartyType` enum with the required values.
- Add `counterparty_type` to vendor and customer master structs, with serde default migration for existing data.
- Add first-class pools or generated records for employee, payroll provider, tax authority, bank, related party, and internal department counterparties.
- Add `random_counterparty_of_allowed_types(allowed: &[CounterpartyType])`.
- Replace `JournalEntryGenerator` P2P/Treasury vendor selection with scenario-filtered counterparty selection.
- Add validator checks that counterparty name signals match `counterparty_type`.
- Add tests for office supplier, bank, tax authority, employee, customer, related party, and internal department classification.
