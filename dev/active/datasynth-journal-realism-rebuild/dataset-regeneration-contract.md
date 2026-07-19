# DataSynth Semantic V1 Regeneration Contract

## Purpose
The regeneration owner creates a new semantic-clean test dataset at `data/journal/primary/datasynth_semantic_v1`. The existing `data/journal/primary/datasynth_contract` dataset is not semantic-clean baseline data and must not be overwritten silently.

The regenerated dataset is synthetic test data. Its manifest must state that it is suitable for DataSynth, Phase1, and Phase2 regression testing under the documented semantic assumptions, but it is not evidence of production journal-entry detector performance.

## Output Artifacts
| Artifact | Required Path | Purpose |
|---|---|---|
| Dataset | `data/journal/primary/datasynth_semantic_v1` | New semantic-clean synthetic journal dataset |
| Semantic validation report | `data/journal/primary/datasynth_semantic_v1/reports/semantic_validation_report.*` | Validator pass/fail counts and required quality metrics |
| Phase1 rule count diff report | `data/journal/primary/datasynth_semantic_v1/reports/phase1_rule_count_diff.*` | Difference versus previous dataset without fitting the new data to counts |
| Phase2 feature profile report | `data/journal/primary/datasynth_semantic_v1/reports/phase2_feature_profile.*` | Feature availability, cardinality, missingness, and leakage-field exclusion checks |
| Dataset manifest | `data/journal/primary/datasynth_semantic_v1/manifest.*` | Generation config, semantic-clean status, synthetic limitations, allowed usage, and report links |

## Required Metadata Columns
Every generated entry or line-level export must carry these fields where the schema stores the corresponding semantic unit:

| Field | Requirement |
|---|---|
| `event_type` | Populated from `AccountingEventScenario.event_type` |
| `scenario_id` | Populated for every normal row and every mutated row |
| `business_process` | Copied from the scenario |
| `debit_account_subtype` | Populated with semantic debit subtype |
| `credit_account_subtype` | Populated with semantic credit subtype |
| `counterparty_type` | Populated from typed counterparty master selection |
| `document_type` | Populated from scenario document selection |
| `line_text_family` | Populated from scenario text-family selection |
| `is_synthetic` | `true` for every row in this dataset |
| `is_mutated` | `false` for validated normal rows, `true` for explicit mutation rows |
| `mutation_type` | Empty for normal rows, populated for mutated rows |
| `mutation_reason` | Empty for normal rows, populated for mutated rows |

Optional evaluation metadata such as `detection_surface_hints` may be exported for audit and analysis. It is not required mutation provenance, not a generation target, not an answer label, not a recall criterion, not a rule count target, and not a VAE training feature.

## Required Quality Metrics
The semantic validation report must include these metrics:

| Metric | Required Value |
|---|---|
| Normal labor/payroll plus P2P count | `0` |
| Normal labor/payroll plus AP or GRIR count | `0` |
| Normal labor/payroll plus office supplier count | `0` |
| Normal purchase invoice plus payroll text count | `0` |
| Normal depreciation plus AP vendor count | `0` |
| Normal revenue plus non-customer counterparty count | `0` |
| Abnormal semantic violations with all required mutation provenance fields | `100%` |
| Normal rows missing `scenario_id` | `0` |
| Normal rows missing `counterparty_type` | `0` |

## Regeneration Flow
1. Build the corrected Rust `datasynth-cli`.
2. Generate the dataset into `data/journal/primary/datasynth_semantic_v1`.
3. Refuse to write to `data/journal/primary/datasynth_contract` unless a separate release task explicitly requests a contract promotion.
4. Run the Rust semantic validator over generated output.
5. If validator fail conditions appear, fix the Rust generation cause and regenerate the dataset.
6. Produce the Phase1 rule count diff report without changing data to match rule counts.
7. Produce the Phase2 feature profile report without changing data to improve VAE scores.
8. Write the manifest with synthetic limitations, allowed usage, generation config, validator results, Phase1 diff summary, and Phase2 feature summary.

## Manifest Requirements
The manifest must record:
- Dataset name `datasynth_semantic_v1`.
- Generation timestamp, git commit, generator version, config path, seed, and row counts.
- Statement that the dataset is synthetic and not production performance evidence.
- Statement that normal rows passed `AccountingEventScenario` selection and `SemanticValidator`.
- Statement that semantic violations exist only through explicit `AnomalyMutator` rows.
- List of required metadata columns and missing-count summary.
- Required quality metrics table and pass/fail status.
- Phase1 count diff report path and warning that count differences must not drive data fitting.
- Phase2 feature profile report path and warning that VAE score results must not drive distribution tuning.
- Statement that `detection_surface_hints`, if present, is optional evaluation metadata and is excluded from VAE training features.
- Statement that `datasynth_contract` remains an older dataset and is not treated as semantic-clean baseline.

## Forbidden Actions
- Do not use Python CSV post-processing to force normal rows into semantic compliance.
- Do not overwrite `datasynth_contract` silently.
- Do not inject abnormal rows to hit rule-specific detection count targets.
- Do not tune normal distributions based on VAE evaluation results.
- Do not leave semantic violations without required mutation provenance in normal or abnormal output.
- Do not use `detection_surface_hints` as a generation objective, answer label, recall criterion, rule count target, or VAE training feature.

## Acceptance Criteria
- `data/journal/primary/datasynth_semantic_v1` exists as a separate dataset path.
- The semantic validation report shows every required zero-count metric at the required value.
- The semantic validation report shows abnormal semantic violations with all required mutation provenance fields at `100%`.
- Normal rows missing `scenario_id` and `counterparty_type` are both `0`.
- Phase1 rule count diff report exists and contains no instruction to tune generated data to counts.
- Phase2 feature profile report exists and contains no instruction to tune generated data to VAE performance.
- Manifest explicitly documents synthetic limits and allowed use scope.
