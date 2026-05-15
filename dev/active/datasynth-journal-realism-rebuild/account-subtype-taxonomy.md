# DataSynth Semantic Account Subtype Taxonomy

## Purpose
The current core `AccountSubType::CostOfGoodsSold` and `AccountSubType::OperatingExpenses` are too broad for semantic-clean journal generation. DataSynth must split them into semantic subtypes with allowed business processes and counterparty types. Normal entries may use a subtype only when the selected `AccountingEventScenario` permits the same process and counterparty domain.

This taxonomy is a normal-data contract. Violations are allowed only through explicit `AnomalyMutator` changes with `mutation_type`, `reason`, and `detection_surface_hints`.

## Implementation Rule
- Add semantic account subtypes in Rust DataSynth generation logic before selecting GL accounts, text, or counterparties.
- Do not repair generated CSV rows in Python.
- A broad core `AccountSubType` may remain as the persisted CoA class, but generation must carry the semantic subtype as the validator's source of truth.
- If a GL account cannot be assigned a semantic subtype, it is not eligible for normal scenario generation.

## CostOfGoodsSold Split

| Semantic subtype | Core mapping | Allowed processes | Allowed counterparty types | Forbidden normal combinations |
| --- | --- | --- | --- | --- |
| `COGS_MATERIAL` | `CostOfGoodsSold` | `P2P`, `R2R`, `Mfg` | `VENDOR_RAW_MATERIAL`, `INTERNAL_DEPARTMENT`, `NONE` | payroll text, employee counterparty, payroll provider |
| `COGS_DIRECT_LABOR` | `CostOfGoodsSold` | `H2R`, `R2R`, `Mfg` | `EMPLOYEE`, `PAYROLL_PROVIDER`, `INTERNAL_DEPARTMENT` | P2P external vendor invoice, AP vendor counterparty, office supplier, purchase tax invoice |
| `COGS_OVERHEAD` | `CostOfGoodsSold` | `Mfg`, `R2R`, `P2P` | `INTERNAL_DEPARTMENT`, `VENDOR_SERVICE`, `VENDOR_UTILITIES`, `NONE` | employee payroll register unless scenario is H2R allocation |
| `COGS_SUBCONTRACT` | `CostOfGoodsSold` | `P2P`, `Mfg` | `VENDOR_SERVICE` | employee counterparty, payroll provider, office supplier |
| `COGS_FREIGHT` | `CostOfGoodsSold` | `P2P`, `O2C`, `Mfg` | `VENDOR_SERVICE`, `VENDOR_RAW_MATERIAL`, `CUSTOMER` | payroll text, employee counterparty |
| `COGS_INVENTORY_ADJUSTMENT` | `CostOfGoodsSold` | `R2R`, `Mfg` | `INTERNAL_DEPARTMENT`, `NONE` | AP vendor invoice, customer invoice, payroll register |

## OperatingExpenses Split

| Semantic subtype | Core mapping | Allowed processes | Allowed counterparty types | Forbidden normal combinations |
| --- | --- | --- | --- | --- |
| `OPEX_PAYROLL` | `OperatingExpenses`, `AdministrativeExpenses`, `SellingExpenses` | `H2R`, `R2R` | `EMPLOYEE`, `PAYROLL_PROVIDER`, `INTERNAL_DEPARTMENT` | P2P external vendor invoice, AP vendor counterparty, office supplier, purchase invoice |
| `OPEX_RENT` | `OperatingExpenses`, `AdministrativeExpenses` | `P2P`, `R2R` | `VENDOR_SERVICE`, `INTERNAL_DEPARTMENT` | payroll register, employee counterparty |
| `OPEX_UTILITIES` | `OperatingExpenses` | `P2P`, `R2R` | `VENDOR_UTILITIES`, `INTERNAL_DEPARTMENT` | payroll register, employee counterparty, customer invoice |
| `OPEX_OFFICE_SUPPLIES` | `OperatingExpenses`, `AdministrativeExpenses` | `P2P` | `VENDOR_OFFICE_SUPPLIES` | payroll text, direct labor text, employee counterparty |
| `OPEX_PROFESSIONAL_FEES` | `OperatingExpenses`, `AdministrativeExpenses` | `P2P`, `R2R` | `VENDOR_SERVICE`, `INTERNAL_DEPARTMENT` | payroll register unless explicit H2R service scenario exists |
| `OPEX_TRAVEL` | `OperatingExpenses`, `SellingExpenses`, `AdministrativeExpenses` | `P2P`, `H2R`, `R2R` | `EMPLOYEE`, `VENDOR_SERVICE`, `INTERNAL_DEPARTMENT` | office supplier with payroll/direct labor text |
| `OPEX_MARKETING` | `OperatingExpenses`, `SellingExpenses` | `P2P`, `O2C`, `R2R` | `VENDOR_SERVICE`, `INTERNAL_DEPARTMENT` | payroll register, direct labor text |
| `OPEX_DEPRECIATION` | `OperatingExpenses`, `DepreciationExpense` | `A2R`, `R2R` | `INTERNAL_DEPARTMENT`, `NONE` | AP vendor invoice, purchase tax invoice, office supplier |
| `OPEX_TAX` | `OperatingExpenses`, `TaxExpense` | `Tax`, `R2R`, `H2R` | `TAX_AUTHORITY`, `INTERNAL_DEPARTMENT`, `PAYROLL_PROVIDER` | ordinary office supplier invoice, raw material vendor invoice |

## Required Validator Rules
- `OPEX_PAYROLL` and `COGS_DIRECT_LABOR` are allowed only for `H2R`, `R2R`, or manufacturing allocation scenarios. They are forbidden for `P2P_VENDOR_INVOICE`.
- `OPEX_OFFICE_SUPPLIES` is allowed for `P2P_VENDOR_INVOICE` only with `VENDOR_OFFICE_SUPPLIES` and credit subtype `AP` or `GRIR`.
- `OPEX_UTILITIES` is allowed for `P2P_VENDOR_INVOICE` only with `VENDOR_UTILITIES` and credit subtype `AP` or `GRIR`.
- `OPEX_DEPRECIATION` and `DepreciationExpense` are allowed only for `A2R_DEPRECIATION` or R2R depreciation adjustment scenarios and must not use AP vendor invoice documents.
- `OPEX_TAX` may use `TAX_AUTHORITY` for tax scenarios or `PAYROLL_PROVIDER` for payroll tax scenarios, but must not use ordinary purchase vendor counterparties.
- `COGS_MATERIAL`, `COGS_SUBCONTRACT`, and `COGS_FREIGHT` may use P2P vendor counterparties, but must not emit payroll or direct labor line text families.
- `COGS_INVENTORY_ADJUSTMENT` is an internal adjustment subtype and must not use external AP vendor invoice documents in normal data.

## Rust Work Items
- Add a semantic subtype enum such as `SemanticAccountSubtype` in `tools/datasynth/crates/datasynth-generators/src/process_gl_mapping.rs` or a sibling scenario module.
- Add a mapping from `GLAccount` to `SemanticAccountSubtype` using account number, account name, account description, and scenario context.
- Replace broad `allowed_debit_sub_types()` and `allowed_credit_sub_types()` normal generation paths with semantic subtype filters.
- Extend semantic validator to check `(scenario, semantic_subtype, process, counterparty_type, document_type, line_text_family)`.
