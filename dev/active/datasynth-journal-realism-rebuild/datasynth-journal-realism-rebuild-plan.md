# DataSynth Journal Realism Rebuild - Strategic Plan

## Executive Summary
The current DataSynth journal generator creates balanced entries but not reliable accounting scenarios. It selects debit and credit accounts from broad process-level subtype pools, then attaches header text, line text, and counterparties separately. This allows invalid combinations such as direct labor booked as P2P vendor invoices to office-supply vendors and AP control accounts.

## Current State
- `tools/datasynth/crates/datasynth-generators/src/process_gl_mapping.rs` allows broad P2P debit subtypes (`Inventory`, `CostOfGoodsSold`, `OperatingExpenses`, `PrepaidExpenses`) and P2P credit subtypes (`Cash`, `AccountsPayable`, `GoodsReceivedClearing`).
- `tools/datasynth/crates/datasynth-generators/src/je_generator.rs` assigns vendor auxiliary accounts to all P2P entries before the exact line semantics are known.
- `tools/datasynth/crates/datasynth-core/src/templates/descriptions.rs` line text is subtype-based, so `CostOfGoodsSold` can emit `직접노무비` and `OperatingExpenses` can emit `급여 비용` even in P2P vendor scenarios.
- Existing quality gates check broad GL prefixes and keyword-to-GL class consistency, but not scenario-level account-process-counterparty consistency.

## Proposed Solution
Replace broad process-level random account pairing with accounting-event scenarios. `AccountingEventScenario` becomes the single semantic source for business process, account subtype pools, counterparty domain, source document, header family, line text family, and allowed anomaly mutations.

New structures:
- `AccountingEventType`: business event identity such as `P2pVendorInvoice`, `P2pVendorPayment`, `O2cCustomerInvoice`, `O2cCustomerReceipt`, `H2rPayrollAccrual`, `H2rPayrollPayment`, `A2rDepreciationRun`, `A2rAssetAcquisition`, `TreasuryBankTransfer`, `TreasuryInterestAccrual`, `R2rAccrualAdjustment`, `R2rPrepaidAmortization`, `TaxInvoicePosting`, `IntercompanySettlement`.
- `AccountingEventScenario`: immutable scenario definition with `event_type`, `business_process`, `allowed_debit_subtypes`, `allowed_credit_subtypes`, `allowed_counterparty_types`, `allowed_document_types`, `allowed_header_families`, `allowed_line_text_families`, and `allowed_anomaly_mutations`.
- `ScenarioCatalog`: weighted catalog that selects scenarios first and exposes account/counterparty/text validation helpers.
- `CounterpartyType`: `Vendor`, `Customer`, `Employee`, `PayrollClearing`, `Bank`, `TaxAuthority`, `IntercompanyAffiliate`, `None`.
- `DocumentType`: generator-side semantic document kind mapped to SAP document codes and `DocumentRef`, such as `VendorInvoice`, `VendorPayment`, `CustomerInvoice`, `CustomerReceipt`, `PayrollRun`, `AssetPosting`, `DepreciationRun`, `BankStatement`, `ManualAdjustment`, `TaxInvoice`, `IntercompanyDocument`.
- `LineTextFamily`: controlled pools such as `MaterialPurchase`, `OfficeSuppliesPurchase`, `VendorService`, `Utilities`, `PayrollSalary`, `DirectLaborPayroll`, `EmployeeBenefits`, `Depreciation`, `RevenueBilling`, `CustomerReceipt`, `BankTransfer`, `Interest`, `Accrual`, `PrepaidAmortization`, `Tax`, `Intercompany`.
- `AnomalyMutationType`: explicit semantic mutations such as `WrongCounterpartyDomain`, `WrongDocumentType`, `WrongLineTextFamily`, `WrongBusinessProcess`, `WrongAccountSubtype`, `MismatchedReferenceType`.

Normal generation order:
1. Select `AccountingEventScenario`.
2. Select debit and credit accounts from the scenario's allowed account subtypes.
3. Select counterparty from the scenario's allowed counterparty types.
4. Select document, header text, and line text from the scenario's allowed families.
5. Run semantic validator against scenario, accounts, counterparty, document, header, and line texts.
6. If an anomaly is targeted, apply `AnomalyMutator` to the validated normal event.
7. Record required mutation provenance fields after mutation: `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, and `reason`.
8. Optionally record `detection_surface_hints` as evaluation metadata only. It is not a generation objective, answer label, recall basis, rule count target, or VAE training feature.

Independent random assembly paths are removed. Any fallback that combines `process`, account subtypes, counterparty, document, or text outside a scenario must return a generation error in tests rather than silently selecting a broad account or generic text.

Phase1 rule validation remains a separate classification activity. `dev/active/datasynth-journal-realism-rebuild/phase1-rule-testability-matrix.md` defines which rules can be tested with synthetic data and which require semantic-clean generation or real journal data. DataSynth must not be tuned to match Phase1 hit counts, recall, or dashboard totals.

Phase2 VAE validation remains a separate detector-boundary activity. `dev/active/datasynth-journal-realism-rebuild/phase2-vae-testability-matrix.md` defines which anomaly families can be tested with semantic-clean synthetic data, which feature fields are allowed for training, and which provenance fields must remain evaluation metadata only. DataSynth must not be tuned to improve VAE score shape, reconstruction-error separation, or synthetic dashboard claims.

Dataset regeneration writes a new semantic-clean test dataset at `data/journal/primary/datasynth_semantic_v1`. The existing `datasynth_contract` freeze is not treated as semantic-clean baseline and must not be overwritten silently. `dev/active/datasynth-journal-realism-rebuild/dataset-regeneration-contract.md` defines required metadata, validation metrics, Phase1 and Phase2 reports, and manifest language.

## Implementation Phases

### Phase 1: Contract Tests (1 day)
**Goal**: Capture the current failures before changing generation.
**Tasks**:
- Add scenario consistency checks for labor/payroll text under AP/P2P/vendor combinations.
- Add counterparty-domain checks for office/stationery vendors appearing in payroll/direct labor entries.
- Add quality-gate checks for H2R credit account subtype distribution.
- Add fixtures using known failing document `9ddc8ff9-097f-4251-981e-abad8b70519f`.

### Phase 2: Scenario Model (1-2 days)
**Goal**: Introduce an explicit journal scenario abstraction.
**Tasks**:
- Create `AccountingEventType`, `CounterpartyType`, `DocumentType`, `LineTextFamily`, and `AnomalyMutationType` in `tools/datasynth/crates/datasynth-generators/src/process_gl_mapping.rs` or a new sibling module re-exported from it.
- Create `AccountingEventScenario` with the exact fields required by this plan.
- Create `ScenarioCatalog` with weighted baseline scenarios and lookup helpers from `dev/active/datasynth-journal-realism-rebuild/scenario-catalog.md`.
- Create semantic account subtype splitting for broad COGS and OPEX accounts from `dev/active/datasynth-journal-realism-rebuild/account-subtype-taxonomy.md`.
- Add counterparty master `counterparty_type` fields and scenario-filtered counterparty selection from `dev/active/datasynth-journal-realism-rebuild/counterparty-master-design.md`.
- Replace subtype-global text generation with scenario-owned header and line text families from `dev/active/datasynth-journal-realism-rebuild/text-document-family-design.md`.
- Add Rust semantic validation for entry-level and line-level fail rules from `dev/active/datasynth-journal-realism-rebuild/semantic-validator-design.md`.
- Add mutation-only abnormal injection and full mutation records from `dev/active/datasynth-journal-realism-rebuild/abnormal-injection-design.md`.
- Keep existing anomaly strategies separate from normal scenario generation; only `AnomalyMutator` may create semantic contradictions.

### Phase 3: Generator Refactor (2-4 days)
**Goal**: Make `JournalEntryGenerator` generate from scenarios, not independent random fields.
**Tasks**:
- Select `AccountingEventScenario` before `business_process`, reference, counterparty, header, line text, and GL account selection in `tools/datasynth/crates/datasynth-generators/src/je_generator.rs`.
- Replace `document_type_for_process()` usage with scenario document selection.
- Replace `select_debit_account_for_process()` and `select_credit_account_for_process()` normal paths with scenario account selection.
- Assign counterparties only through `CounterpartyType`: P2P vendor invoice uses vendor; O2C invoice uses customer; payroll uses employee or payroll clearing; treasury uses bank; depreciation uses none or asset context.
- Run a semantic validator before anomaly mutation; discard and retry normal events that fail.
- Make broad fallback functions test-only or error-returning for normal generation.

### Phase 4: Description Cleanup (1-2 days)
**Goal**: Stop generic subtype pools from leaking payroll/direct labor text into vendor scenarios.
**Tasks**:
- Add scenario-aware header generation in `tools/datasynth/crates/datasynth-core/src/templates/descriptions.rs` using `LineTextFamily` and header families.
- Split `CostOfGoodsSold` text into material COGS, direct labor payroll, overhead, freight, and subcontracting families.
- Split `OperatingExpenses` text into payroll, rent, utilities, professional services, travel, office supplies, tax, and depreciation-like families.
- Route line text through scenario family first; subtype fallback is allowed only after validator proves the family is compatible with the scenario.
- Remove process-only header fallbacks that permit invalid pairings.

### Phase 5: Regenerate Semantic-Clean Test Data (1 day)
**Goal**: Build `data/journal/primary/datasynth_semantic_v1` from corrected Rust logic without overwriting the older `datasynth_contract` dataset.
**Tasks**:
- Build `datasynth-cli`.
- Generate 2022-2024 data with fixed seed and updated config into `data/journal/primary/datasynth_semantic_v1`.
- Recreate split yearly CSV/JSON files under the new dataset path.
- Run semantic validator and regenerate only after fixing Rust generation causes when fail conditions appear.
- Produce semantic validation, Phase1 rule count diff, and Phase2 feature profile reports.
- Write manifest with synthetic limitations and usage scope after quality gates pass.

### Phase 6: Regression Gates (1-2 days)
**Goal**: Prevent another bad freeze.
**Tasks**:
- Extend `tests/datasynth_quality_gate3/checks/tier3_semantic.py` or add a tier for scenario realism.
- Add threshold checks for labor in P2P, payroll with vendor counterparties, AP used for payroll, and vendor category mismatches.
- Fail the quality gate on scenario contradictions, not just warn.
- Save profile artifacts showing before/after counts.

## Risk Assessment
- **High Risk**: Rewriting account generation can shift downstream rule label counts. Mitigation: compare rule-level counts before/after and explicitly bless expected changes.
- **High Risk**: Existing tests may expect broad GL distributions. Mitigation: update tests to assert realistic scenario distributions instead of permissive prefix matches.
- **Medium Risk**: Scenario templates may reduce data variety. Mitigation: add many scenario variants and keep amount/date/source noise independent.
- **Medium Risk**: Existing contract dataset is used by dashboard demos. Mitigation: create `datasynth_semantic_v1` as a separate dataset and promote it only through an explicit release task.

## Success Metrics
- Labor/payroll/direct labor text in P2P vendor invoice scenarios: 0 for normal entries.
- Payroll/H2R entries crediting generic AP/control AP: 0 for normal entries, unless an explicit error/anomaly label explains it.
- Office/stationery vendors in payroll/direct labor normal entries: 0.
- Purchase tax invoice with payroll/labor text: 0 for normal entries.
- Depreciation with AP vendor invoice: 0 for normal entries.
- Revenue/customer invoice with non-O2C or non-customer counterparty: 0 for normal entries.
- Bank/treasury event with ordinary purchase vendor: 0 for normal entries.
- Account subtype and line text family mismatch: 0 for normal entries.
- Semantic validator rejects invalid normal events before export.
- Phase 2 VAE training input is restricted to semantic-clean normal baseline rows.
- Phase 2 VAE training input excludes `label`, `rule_id`, `mutation_type`, `expected_rule`, `detection_surface_hints`, and rule-hit fields.
- `data/journal/primary/datasynth_semantic_v1` contains required semantic metadata fields and a manifest that marks it as synthetic test data.
- `datasynth_contract` remains untouched unless a separate promotion step is explicitly approved.
- Quality gates pass with scenario realism checks enabled.
- 2022-2024 yearly splits regenerate from a single reproducible seed/config.

## Dependencies
- Rust generator code in `tools/datasynth/crates/datasynth-generators`.
- Description templates in `tools/datasynth/crates/datasynth-core/src/templates/descriptions.rs`.
- Quality gates in `tests/datasynth_quality_gate2` and `tests/datasynth_quality_gate3`.
- Dataset output paths under `data/journal/primary/`.
