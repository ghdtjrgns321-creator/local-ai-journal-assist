# DataSynth Normal Accounting Event Scenario Catalog

## Purpose
This catalog defines the semantic-clean normal baseline for DataSynth journal entries. Normal generation must select one event scenario first, then derive process, debit and credit account subtypes, counterparty, document, header text family, and line text family from that scenario.

Semantic contradictions must not appear naturally in normal data. They may appear only after `AnomalyMutator` mutates a validated normal event and records required mutation provenance: `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`. `detection_surface_hints` is optional evaluation metadata describing which detection surfaces may observe the mutation; it is not a generation target, answer label, recall basis, rule count target, or VAE training feature.

## Shared Types

### CounterpartyType
- `VENDOR_OFFICE_SUPPLIES`
- `VENDOR_RAW_MATERIAL`
- `VENDOR_SERVICE`
- `VENDOR_LOGISTICS`
- `VENDOR_UTILITIES`
- `VENDOR_FIXED_ASSET`
- `CUSTOMER`
- `EMPLOYEE`
- `PAYROLL_PROVIDER`
- `TAX_AUTHORITY`
- `INTERNAL_DEPARTMENT`
- `BANK`
- `LENDER`
- `INTERCOMPANY_AFFILIATE`
- `RELATED_PARTY`
- `NONE`

### DocumentType
- `PURCHASE_INVOICE`
- `TAX_INVOICE`
- `GOODS_RECEIPT`
- `PAYMENT_RUN`
- `BANK_STATEMENT`
- `PAYROLL_REGISTER`
- `PAYROLL_ACCRUAL_BATCH`
- `CUSTOMER_INVOICE`
- `CUSTOMER_RECEIPT`
- `MANUAL_ACCRUAL`
- `REVERSAL_DOCUMENT`
- `ASSET_ACQUISITION`
- `CAPEX_INVOICE`
- `DEPRECIATION_RUN`
- `LOAN_AGREEMENT`
- `INTEREST_NOTICE`
- `INTERCOMPANY_INVOICE`
- `INTERCOMPANY_SETTLEMENT`

### LineTextFamily
- `MATERIAL_PURCHASE`
- `RAW_MATERIAL_PURCHASE`
- `OFFICE_SUPPLIES_PURCHASE`
- `PROFESSIONAL_FEES`
- `UTILITIES`
- `REPAIRS`
- `VENDOR_PAYMENT`
- `PAYROLL_SALARY`
- `DIRECT_LABOR_PAYROLL`
- `PAYROLL_TAX`
- `EMPLOYEE_BENEFITS`
- `CUSTOMER_BILLING`
- `CUSTOMER_RECEIPT`
- `ACCRUAL`
- `REVERSAL`
- `ASSET_ACQUISITION`
- `DEPRECIATION`
- `LOAN_DRAWDOWN`
- `INTEREST_PAYMENT`
- `INTERCOMPANY_SALE`
- `INTERCOMPANY_SETTLEMENT`

### HeaderTextFamily
- `PURCHASE_INVOICE_HEADER`
- `VENDOR_PAYMENT_HEADER`
- `PAYROLL_ACCRUAL_HEADER`
- `PAYROLL_PAYMENT_HEADER`
- `CUSTOMER_INVOICE_HEADER`
- `CUSTOMER_RECEIPT_HEADER`
- `ACCRUAL_HEADER`
- `REVERSAL_HEADER`
- `ASSET_ACQUISITION_HEADER`
- `DEPRECIATION_HEADER`
- `TREASURY_HEADER`
- `INTERCOMPANY_HEADER`

### Semantic Account Subtype Mapping
The catalog uses semantic subtypes that are narrower than the current core `AccountSubType`. The implementation may initially map them to existing `AccountSubType` values plus text-family and account-description filters.

| Semantic subtype | Current core mapping |
| --- | --- |
| `AP` | `AccountsPayable` |
| `AR` | `AccountsReceivable` |
| `CASH` | `Cash` |
| `BANK_CLEARING` | `BankClearing` |
| `GRIR` | `GoodsReceivedClearing` |
| `INVENTORY` | `Inventory` |
| `RAW_MATERIALS` | `Inventory` |
| `FIXED_ASSET` | `FixedAssets` |
| `INTANGIBLE_ASSET` | `IntangibleAssets` |
| `ACCUMULATED_DEPRECIATION` | `AccumulatedDepreciation` |
| `COGS_MATERIAL` | `CostOfGoodsSold` |
| `OPEX_OFFICE_SUPPLIES` | `AdministrativeExpenses`, `OperatingExpenses` |
| `OPEX_PROFESSIONAL_FEES` | `AdministrativeExpenses`, `OperatingExpenses` |
| `OPEX_UTILITIES` | `OperatingExpenses` |
| `OPEX_REPAIRS` | `OperatingExpenses` |
| `OPEX_PAYROLL` | `OperatingExpenses`, `AdministrativeExpenses`, `SellingExpenses` |
| `COGS_DIRECT_LABOR` | `CostOfGoodsSold` |
| `OPEX_TAX` | `TaxExpense`, `OperatingExpenses` |
| `ACCRUED_PAYROLL` | `AccruedLiabilities` |
| `PAYROLL_TAX_PAYABLE` | `TaxLiabilities` |
| `ACCRUED_LIABILITIES` | `AccruedLiabilities` |
| `PRODUCT_REVENUE` | `ProductRevenue` |
| `SERVICE_REVENUE` | `ServiceRevenue` |
| `DEFERRED_REVENUE` | `DeferredRevenue` |
| `PREPAID_EXPENSE` | `PrepaidExpenses` |
| `DEPRECIATION_EXPENSE` | `DepreciationExpense` |
| `AMORTIZATION_EXPENSE` | `AmortizationExpense` |
| `SHORT_TERM_DEBT` | `ShortTermDebt` |
| `LONG_TERM_DEBT` | `LongTermDebt` |
| `INTEREST_EXPENSE` | `InterestExpense` |
| `INTERCOMPANY_CLEARING` | `IntercompanyClearing` |

## Event Catalog

### P2P_VENDOR_INVOICE
- Process: `P2P`
- Debit semantic subtypes: `INVENTORY`, `RAW_MATERIALS`, `COGS_MATERIAL`, `OPEX_OFFICE_SUPPLIES`, `OPEX_PROFESSIONAL_FEES`, `OPEX_UTILITIES`, `OPEX_REPAIRS`
- Credit semantic subtypes: `AP`, `GRIR`
- Counterparty types: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `VENDOR_UTILITIES`
- Document types: `PURCHASE_INVOICE`, `TAX_INVOICE`, `GOODS_RECEIPT`
- Line text families: `MATERIAL_PURCHASE`, `RAW_MATERIAL_PURCHASE`, `OFFICE_SUPPLIES_PURCHASE`, `PROFESSIONAL_FEES`, `UTILITIES`, `REPAIRS`
- Forbidden: `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`, `EMPLOYEE`, `PAYROLL_PROVIDER`, `PAYROLL_REGISTER`, `PAYROLL_ACCRUAL_BATCH`

### P2P_PAYMENT
- Process: `P2P`
- Debit semantic subtypes: `AP`, `GRIR`
- Credit semantic subtypes: `CASH`, `BANK_CLEARING`
- Counterparty types: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `VENDOR_UTILITIES`
- Document types: `PAYMENT_RUN`, `BANK_STATEMENT`
- Line text families: `VENDOR_PAYMENT`
- Forbidden: `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`, `EMPLOYEE`, `PAYROLL_REGISTER`

### H2R_PAYROLL_ACCRUAL
- Process: `H2R`
- Debit semantic subtypes: `OPEX_PAYROLL`, `COGS_DIRECT_LABOR`, `OPEX_TAX`
- Credit semantic subtypes: `ACCRUED_PAYROLL`, `ACCRUED_LIABILITIES`, `PAYROLL_TAX_PAYABLE`
- Counterparty types: `EMPLOYEE`, `PAYROLL_PROVIDER`, `TAX_AUTHORITY`, `INTERNAL_DEPARTMENT`
- Document types: `PAYROLL_REGISTER`, `PAYROLL_ACCRUAL_BATCH`
- Line text families: `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`, `PAYROLL_TAX`, `EMPLOYEE_BENEFITS`
- Forbidden: `AP`, `GRIR`, `PURCHASE_INVOICE`, `TAX_INVOICE`, `GOODS_RECEIPT`, `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `VENDOR_UTILITIES`

### H2R_PAYROLL_PAYMENT
- Process: `H2R`
- Debit semantic subtypes: `ACCRUED_PAYROLL`, `ACCRUED_LIABILITIES`, `PAYROLL_TAX_PAYABLE`
- Credit semantic subtypes: `CASH`, `BANK_CLEARING`
- Counterparty types: `EMPLOYEE`, `PAYROLL_PROVIDER`, `TAX_AUTHORITY`, `BANK`
- Document types: `PAYROLL_REGISTER`, `PAYMENT_RUN`, `BANK_STATEMENT`
- Line text families: `PAYROLL_SALARY`, `PAYROLL_TAX`, `EMPLOYEE_BENEFITS`
- Forbidden: `AP`, `GRIR`, `PURCHASE_INVOICE`, `TAX_INVOICE`, `GOODS_RECEIPT`, `VENDOR_OFFICE_SUPPLIES`

### O2C_CUSTOMER_INVOICE
- Process: `O2C`
- Debit semantic subtypes: `AR`
- Credit semantic subtypes: `PRODUCT_REVENUE`, `SERVICE_REVENUE`, `DEFERRED_REVENUE`
- Counterparty types: `CUSTOMER`
- Document types: `CUSTOMER_INVOICE`
- Line text families: `CUSTOMER_BILLING`
- Forbidden: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `EMPLOYEE`, `PAYROLL_PROVIDER`, `PURCHASE_INVOICE`

### O2C_CASH_RECEIPT
- Process: `O2C`
- Debit semantic subtypes: `CASH`, `BANK_CLEARING`
- Credit semantic subtypes: `AR`
- Counterparty types: `CUSTOMER`, `BANK`
- Document types: `CUSTOMER_RECEIPT`, `BANK_STATEMENT`
- Line text families: `CUSTOMER_RECEIPT`
- Forbidden: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`

### R2R_ACCRUAL
- Process: `R2R`
- Debit semantic subtypes: `OPEX_PROFESSIONAL_FEES`, `OPEX_UTILITIES`, `OPEX_REPAIRS`, `INTEREST_EXPENSE`, `OPEX_TAX`
- Credit semantic subtypes: `ACCRUED_LIABILITIES`
- Counterparty types: `INTERNAL_DEPARTMENT`, `NONE`
- Document types: `MANUAL_ACCRUAL`
- Line text families: `ACCRUAL`
- Forbidden: `PURCHASE_INVOICE`, `GOODS_RECEIPT`, `CUSTOMER_INVOICE`, `PAYROLL_REGISTER`, `VENDOR_OFFICE_SUPPLIES` unless an explicit vendor-accrual scenario is added

### R2R_REVERSAL
- Process: `R2R`
- Debit semantic subtypes: reversed credit semantic subtypes from a validated source event
- Credit semantic subtypes: reversed debit semantic subtypes from a validated source event
- Counterparty types: copied from validated source event, or `NONE` for pure GL reversal
- Document types: `REVERSAL_DOCUMENT`
- Line text families: `REVERSAL`
- Forbidden: independent account, counterparty, or text selection without a validated source event

### A2R_ASSET_ACQUISITION
- Process: `A2R`
- Debit semantic subtypes: `FIXED_ASSET`, `INTANGIBLE_ASSET`
- Credit semantic subtypes: `AP`, `CASH`, `BANK_CLEARING`, `GRIR`
- Counterparty types: `VENDOR_FIXED_ASSET`, `BANK`, `INTERNAL_DEPARTMENT`
- Document types: `ASSET_ACQUISITION`, `CAPEX_INVOICE`, `GOODS_RECEIPT`
- Line text families: `ASSET_ACQUISITION`
- Forbidden: `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`, `CUSTOMER_INVOICE`

### A2R_DEPRECIATION
- Process: `A2R`
- Debit semantic subtypes: `DEPRECIATION_EXPENSE`, `AMORTIZATION_EXPENSE`
- Credit semantic subtypes: `ACCUMULATED_DEPRECIATION`, `INTANGIBLE_ASSET`
- Counterparty types: `INTERNAL_DEPARTMENT`, `NONE`
- Document types: `DEPRECIATION_RUN`
- Line text families: `DEPRECIATION`
- Forbidden: `AP`, `GRIR`, `PURCHASE_INVOICE`, `TAX_INVOICE`, `GOODS_RECEIPT`, `VENDOR_OFFICE_SUPPLIES`, `VENDOR_FIXED_ASSET`

### TRE_LOAN_DRAWDOWN
- Process: `Treasury`
- Debit semantic subtypes: `CASH`, `BANK_CLEARING`
- Credit semantic subtypes: `SHORT_TERM_DEBT`, `LONG_TERM_DEBT`
- Counterparty types: `BANK`, `LENDER`
- Document types: `LOAN_AGREEMENT`, `BANK_STATEMENT`
- Line text families: `LOAN_DRAWDOWN`
- Forbidden: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `PURCHASE_INVOICE`, `PAYROLL_REGISTER`

### TRE_INTEREST_PAYMENT
- Process: `Treasury`
- Debit semantic subtypes: `INTEREST_EXPENSE`, `ACCRUED_LIABILITIES`
- Credit semantic subtypes: `CASH`, `BANK_CLEARING`
- Counterparty types: `BANK`, `LENDER`
- Document types: `INTEREST_NOTICE`, `PAYMENT_RUN`, `BANK_STATEMENT`
- Line text families: `INTEREST_PAYMENT`
- Forbidden: `VENDOR_OFFICE_SUPPLIES`, `VENDOR_RAW_MATERIAL`, `VENDOR_SERVICE`, `PAYROLL_SALARY`, `DIRECT_LABOR_PAYROLL`

### IC_INTERCOMPANY_SALE
- Process: `Intercompany`
- Debit semantic subtypes: `INTERCOMPANY_CLEARING`, `AR`
- Credit semantic subtypes: `PRODUCT_REVENUE`, `SERVICE_REVENUE`, `INTERCOMPANY_CLEARING`
- Counterparty types: `RELATED_PARTY`, `INTERCOMPANY_AFFILIATE`
- Document types: `INTERCOMPANY_INVOICE`
- Line text families: `INTERCOMPANY_SALE`
- Forbidden: external vendor counterparty, external customer counterparty, payroll text family, ordinary purchase invoice

### IC_INTERCOMPANY_SETTLEMENT
- Process: `Intercompany`
- Debit semantic subtypes: `INTERCOMPANY_CLEARING`
- Credit semantic subtypes: `CASH`, `BANK_CLEARING`, `INTERCOMPANY_CLEARING`
- Counterparty types: `RELATED_PARTY`, `INTERCOMPANY_AFFILIATE`, `BANK`
- Document types: `INTERCOMPANY_SETTLEMENT`, `BANK_STATEMENT`
- Line text families: `INTERCOMPANY_SETTLEMENT`
- Forbidden: external vendor counterparty, employee counterparty, payroll text family, customer invoice

## Validator Rules
- `P2P_VENDOR_INVOICE` and `P2P_PAYMENT` must never use payroll or direct labor line text families.
- `H2R_PAYROLL_ACCRUAL` and `H2R_PAYROLL_PAYMENT` must never use AP, GRIR, purchase invoice, tax invoice, goods receipt, or ordinary vendor counterparties.
- `O2C_CUSTOMER_INVOICE` must require `BusinessProcess::O2C` and `CounterpartyType::CUSTOMER`.
- `A2R_DEPRECIATION` must never use AP, vendor invoice documents, or vendor counterparties.
- Treasury events must use bank or lender counterparties, not ordinary purchase vendors.
- `R2R_REVERSAL` must be derived from a validated source event; it cannot independently sample accounts, documents, counterparties, or text families.
- Every line text must belong to one of the scenario's allowed `LineTextFamily` values and be compatible with the selected account semantic subtype.
