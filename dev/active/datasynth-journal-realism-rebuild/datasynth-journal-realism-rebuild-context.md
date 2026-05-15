# DataSynth Journal Realism Rebuild - Context & Decisions

## Status
- Phase: Planning
- Progress: 0 / 7 phases complete
- Last Updated: 2026-05-10

## Worker Brief
목표는 DataSynth 정상 전표의 회계 의미 정합성을 회복하는 것이다.

현재 문제는 차대변 균형 문제가 아니라, process/account/counterparty/document/text가 독립적으로 선택되어 정상 데이터에 의미론적으로 불가능한 전표가 섞이는 것이다.

정상 데이터에서는 다음이 금지된다.
- payroll/labor/direct labor + P2P vendor invoice
- payroll/labor/direct labor + external AP vendor
- payroll/labor/direct labor + office/stationery supplier
- purchase tax invoice + payroll/labor text
- depreciation + AP vendor invoice
- revenue/customer invoice + non-O2C/non-customer counterparty
- bank/treasury event + ordinary purchase vendor
- account subtype과 line text family 불일치

비정상 케이스는 생성기 오류로 자연 발생하면 안 된다. 반드시 `AnomalyMutator`가 정상 이벤트를 기반으로 특정 필드를 변형하고, `base_event_type`, `mutation_type`, `mutated_field`, `original_value`, `mutated_value`, `reason`, `detection_surface_hints`를 남겨야 한다.

수정 위치는 주로 Rust DataSynth다. Python으로 CSV를 사후 보정하지 않는다.

## Key Files
**Existing**:
- `tools/datasynth/crates/datasynth-generators/src/process_gl_mapping.rs` - broad process-to-subtype mappings that currently allow invalid scenarios.
- `tools/datasynth/crates/datasynth-generators/src/je_generator.rs` - current journal generation flow and counterparty assignment.
- `tools/datasynth/crates/datasynth-core/src/templates/descriptions.rs` - header and line text pools.
- `tools/datasynth/crates/datasynth-generators/src/anomaly/injector.rs` - existing anomaly injection and `AnomalyLabel` metadata path.
- `tools/datasynth/crates/datasynth-core/src/models/anomaly.rs` - existing `AnomalyLabel::with_metadata` support for mutation provenance.
- `tests/datasynth_quality_gate3/checks/tier3_semantic.py` - current semantic checks.
- `tests/datasynth_quality_gate3/checks/tier4_crossfield.py` - current cross-field checks.

**New**:
- `dev/active/datasynth-journal-realism-rebuild/datasynth-journal-realism-rebuild-plan.md` - strategic plan.
- `dev/active/datasynth-journal-realism-rebuild/datasynth-journal-realism-rebuild-context.md` - context and decisions.
- `dev/active/datasynth-journal-realism-rebuild/datasynth-journal-realism-rebuild-tasks.md` - executable checklist.
- `dev/active/datasynth-journal-realism-rebuild/scenario-catalog.md` - normal accounting event catalog for `ScenarioCatalog` implementation.
- `dev/active/datasynth-journal-realism-rebuild/account-subtype-taxonomy.md` - semantic split of broad COGS and OPEX account subtypes.
- `dev/active/datasynth-journal-realism-rebuild/counterparty-master-design.md` - counterparty type taxonomy and master-data selection rules.
- `dev/active/datasynth-journal-realism-rebuild/text-document-family-design.md` - scenario-owned header and line text family rules.
- `dev/active/datasynth-journal-realism-rebuild/semantic-validator-design.md` - Rust semantic validator rules for normal and abnormal entries.
- `dev/active/datasynth-journal-realism-rebuild/abnormal-injection-design.md` - mutation-only abnormal semantic injection contract.
- `dev/active/datasynth-journal-realism-rebuild/phase1-rule-testability-matrix.md` - Phase1 rule synthetic testability classification.
- `dev/active/datasynth-journal-realism-rebuild/phase2-vae-testability-matrix.md` - Phase2 VAE feature boundary, synthetic testability, and real-data revalidation scope.
- `dev/active/datasynth-journal-realism-rebuild/dataset-regeneration-contract.md` - semantic-clean dataset output path, metadata, reports, manifest, and quality metrics.

## Observed Failure
Known failing document:
- `9ddc8ff9-097f-4251-981e-abad8b70519f`
- Debit `500040` / `COGS 5` with line text `직접노무비`
- Credit `205002` / `IC Payable - C002` with subtype `accounts_payable`
- Business process `P2P`
- Counterparty `기업문구 홀딩스`

Measured on `data/journal/primary/datasynth_contract/journal_entries.csv`:
- Labor/payroll/direct labor context: `61,005` lines, `28,168` documents.
- Labor context under `P2P`: `10,854` lines.
- Labor documents containing AP/payable: `7,583 / 28,168` documents, about `26.9%`.
- Office/stationery/paper counterparties in labor rows: `505` lines, `434` documents.

## Key Decisions
1. **Regenerate instead of patching individual CSV rows** (2026-05-10)
   - Rationale: The defect is structural in the generator. CSV repair would hide the current sample but leave future runs broken.
   - Alternatives: one-off Pandas cleanup of all 3 years.
   - Trade-offs: Regeneration is more invasive but reproducible and testable.

2. **Use scenario-level generation** (2026-05-10)
   - Rationale: Account, text, process, counterparty, and support document must be selected together.
   - Alternatives: Narrow existing process subtype mappings only.
   - Trade-offs: Scenario model is more code, but it prevents impossible combinations by construction.

3. **Make semantic contradictions fail quality gates** (2026-05-10)
   - Rationale: Existing gates allowed the bad freeze because they checked broad prefixes and keywords, not business meaning.
   - Alternatives: Dashboard-side warnings.
   - Trade-offs: Hard gates may require test updates, but bad datasets should not be accepted.

4. **Use accounting-event scenarios as the generation root** (2026-05-10)
   - Rationale: `je_generator.rs` currently selects process, document type, counterparty, header text, and line text in separate blocks. A scenario catalog makes the intended accounting event explicit before any field is sampled.
   - Alternatives: continue narrowing `allowed_debit_sub_types()` and `allowed_credit_sub_types()` by process.
   - Trade-offs: Scenario catalog introduces more Rust types but removes broad fallback paths that reintroduce contradictions.

5. **Make normal validation precede anomaly mutation** (2026-05-10)
   - Rationale: Phase2 VAE must learn from semantic-clean normal baseline data. Any semantic violation must be a labelled mutation from a validated normal event.
   - Alternatives: validate only final CSV rows in Python.
   - Trade-offs: Rust generation may retry entries more often, but exported normal rows become trustworthy.

6. **Treat process-only document mapping as deprecated** (2026-05-10)
   - Rationale: `document_type_for_process()` maps H2R and A2R to one process-level document code, but the user requirement needs document semantics tied to event type and counterparty domain.
   - Alternatives: expand `document_type_for_process()` with subtype checks.
   - Trade-offs: Scenario document selection is more explicit and easier to validate.

7. **Use the scenario catalog as a normal-only contract** (2026-05-10)
   - Rationale: `scenario-catalog.md` lists the minimum normal accounting events and their allowed debit subtypes, credit subtypes, counterparties, documents, and line text families.
   - Alternatives: infer allowed combinations from existing process mappings and text pools.
   - Trade-offs: The catalog is stricter than the current generator, so implementation must add semantic subtype filtering instead of relying only on broad `AccountSubType` values.

8. **Split broad COGS and OPEX types before normal account selection** (2026-05-10)
   - Rationale: `CostOfGoodsSold` and `OperatingExpenses` contain incompatible meanings such as direct labor, office supplies, utilities, professional fees, and depreciation. Scenario validation needs the narrower semantic subtype before text and counterparty selection.
   - Alternatives: keep broad core `AccountSubType` and infer meaning from line text after generation.
   - Trade-offs: Semantic subtype assignment adds a mapping layer, but prevents P2P vendor invoices from naturally receiving payroll or direct labor meaning.

9. **Add counterparty_type as the scenario selection gate** (2026-05-10)
   - Rationale: Existing `VendorType` and `CustomerType` do not cover employee, payroll provider, tax authority, bank, related party, or internal department counterparties, and `JournalEntryGenerator` currently reuses vendor selection for Treasury.
   - Alternatives: infer counterparty domain from names at validation time only.
   - Trade-offs: Adding `counterparty_type` changes master data schemas, but it lets normal generation filter counterparties before invalid entries are created.

10. **Generate header and line text from scenario families** (2026-05-10)
   - Rationale: `DescriptionGenerator::generate_line_text()` currently selects from `sub_type_line_pool(AccountSubType)`, which makes broad COGS/OPEX accounts leak payroll or direct labor text into unrelated scenarios.
   - Alternatives: keep global subtype pools and add keyword cleanup after generation.
   - Trade-offs: Family-specific pools require more templates, but normal entries become semantically valid by construction.

11. **Make semantic validation a Rust hard gate** (2026-05-10)
   - Rationale: The VAE normal baseline must never include unlabelled semantic contradictions. Python checks can report bad exports, but Rust generation must reject them before output.
   - Alternatives: rely on downstream quality gates only.
   - Trade-offs: Generation may retry more often and requires extra metadata fields, but invalid normal rows stop at the source.

12. **Create semantic abnormal rows only by mutation** (2026-05-10)
   - Rationale: Abnormal cases are useful for detector validation only when their causal field change is known. Accidental semantic violations from normal generation pollute both normal baseline and anomaly labels.
   - Alternatives: allow rare generator mistakes and label them after export.
   - Trade-offs: Mutation records add metadata volume, but they make every semantic violation traceable to a deliberate injection.

13. **Keep Phase1 evaluation separate from DataSynth fitting** (2026-05-10)
   - Rationale: Phase1's role is to classify what synthetic data can validate, not to tune DataSynth until rule counts or dashboard metrics look good.
   - Alternatives: generate targeted anomalies for every Phase1 rule and optimize recall.
   - Trade-offs: The matrix may show limited synthetic testability for statistical and semantic rules, but it protects Phase1 from synthetic-data overclaiming.

14. **Keep Phase2 VAE evaluation separate from DataSynth fitting** (2026-05-10)
   - Rationale: Phase2 must train on semantic-clean normal rows and evaluate controlled anomaly families without using labels, rule ids, mutation provenance, or detection-surface hint fields as model inputs.
   - Alternatives: tune normal and abnormal synthetic distributions until reconstruction error separates cleanly.
   - Trade-offs: Synthetic VAE results become more modest, but the evaluation avoids leakage and avoids overclaiming production performance.

15. **Create `datasynth_semantic_v1` as a separate dataset** (2026-05-10)
   - Rationale: Existing `datasynth_contract` is not semantic-clean baseline data and should remain available for historical comparison until an explicit promotion task replaces it.
   - Alternatives: overwrite `datasynth_contract` after generator fixes.
   - Trade-offs: Consumers must opt into the new path, but the semantic-clean dataset has a clear manifest and does not hide the old freeze's limitations.

## Known Issues
- `CLAUDE.md` appears partially mojibake in terminal output, but the DataSynth rule is clear: fix Rust generator root cause, not Python post-hoc fitting.
- `dev/README.md` is not present in this checkout.
- Existing `datasynth_contract` is marked source freeze `v126`; corrected output should use a new freeze/version marker.
