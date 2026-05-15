# PHASE1 Rule Detail Audit Note

## Observed L1-01 UI Defect

Dataset checked:

- `data/journal/primary/datasynth_contract/journal_entries_2022.csv`

Example:

- `74bda121-4d0c-4389-9433-cd48b238b2ca`
- Fiscal year `2022`, period `4`, company `C002`
- Debit total `35,690,001`
- Credit total `35,690,001`
- Difference `0`

This document is not an L1-01 debit/credit imbalance. It is a data-integrity issue because one `gl_account` value is missing.

## Why The UI Is Wrong

The L1-01 detector itself computes document-level imbalance correctly in `IntegrityDetector._a01_unbalanced_entry()` by grouping on `document_id` and comparing `sum(debit_amount)` vs `sum(credit_amount)`.

The defect is in the PHASE1 rule detail view assembly:

1. Rule hit documents and case member documents are mixed.
   - `build_phase1_rule_case_doc_map()` currently maps a rule-bearing case to all `case.documents`.
   - If one document in a case has L1-01, other documents in the same case can appear under the L1-01 document master.

2. Master table amount columns use a representative row, not document totals.
   - `build_phase1_rule_documents()` stores `debit_amount`, `credit_amount`, and `amount` from the first relevant row selected for the document.
   - For document-level rules such as L1-01, this makes the master table show line-level amounts while the evidence summary is document-level.

3. Cached/stored analysis results can keep stale `flagged_rules`/case membership visible until the analysis is rerun or reset.

## Initial Fix Direction

1. For document-level rule detail views, derive displayed documents from rule-specific raw hits or validated rule-specific predicates, not from all documents in a case.
2. Change `build_phase1_rule_case_doc_map()` so it returns only documents with a raw hit for the requested rule, unless the rule explicitly declares case-level display semantics.
3. For L1-01, compute master-table debit, credit, difference, and evidence amount from full `doc_rows`, not the representative row.
4. Audit other rules for the same two risks:
   - case document leakage into rule-specific document lists
   - row-level representative values shown as document-level evidence
5. After code fixes, reset or rerun existing analysis batches before judging the UI.

## Full Rule Detail Audit Snapshot

### Shared Defect Surfaces

1. `src.export.phase1_case_view.build_phase1_rule_documents()`
   - Selects rows by parsing `featured_data.flagged_rules` and `featured_data.review_rules`.
   - Uses the first relevant row per `document_id` as the master row.
   - This is unsafe for document-level, pair-level, macro-level, and case-level rules unless the rule evidence is recomputed from all document rows or sidecar/raw-hit metadata.

2. `src.export.phase1_case_view.build_phase1_rule_case_doc_map()`
   - Includes all `case.documents` for any case that has the requested rule in `raw_rule_hits`.
   - In the current render path it mostly filters an already-built rule row list, but it can still widen selection semantics and should be restricted to documents with a requested-rule raw hit.

3. `src.db.batch_reader._reconstruct_detection_results()`
   - Reconstructs persisted `anomaly_flags` by mapping each `document_id` to the first row index.
   - It ignores persisted `line_number`, so restored DetectionResult details lose row-level location.
   - This can distort row-level displays and can move line-specific rule evidence to the first line of a document.

4. `src.db.loader._build_anomaly_flags_df()`
   - Persists only positive `DetectionResult.details` values.
   - `review_rules` are not persisted as rule-detail evidence in the same way unless they also produced positive details.

### Highest Risk Rules

These rules need rule-specific document-level or pair-level evidence instead of representative-row values:

- `L1-01`: document-level debit/credit imbalance. Must recompute debit total, credit total, and difference from all document rows.
- `L1-04`: approval limit excess. Needs document economic amount, approval threshold, and approver context, not arbitrary line amount.
- `L2-01`: just-below-threshold. Needs document amount/threshold ratio, not a first line amount.
- `L2-02`: duplicate payment. Needs duplicate-group/pair metadata, counterparty, reference, amount, and matched document.
- `L2-03`: duplicate journal and aliases `L2-03a~d`. Needs duplicate signature/group metadata; aliases should remain drilldown reason codes, not separate row-detail headings.
- `L2-05`: reversal pattern. Needs matched reversal document/pair metadata, not one selected row.
- `IC01`, `IC02`, `IC03`: intercompany sidecars. They are sidecar/pair rules and should not use generic transaction row detail.
- `D01`, `D02`, `L4-02/Benford`: macro rules. They correctly have row detail disabled, but topic/case displays must not imply single-row transaction evidence.

### Medium Risk Rules

These are transaction-detail rules, but master columns can be misleading if the chosen representative row is not the actual violating row or if restored batches moved the flag to the first document row:

- `L1-02`: missing required field. Should display missing fields from row annotations or direct null scan on the displayed row.
- `L1-03`: invalid account. Should display the invalid account row, not first row after DB restore.
- `L1-05`: self approval. Usually document-level; representative row is acceptable only if created/approved fields are document-level stable.
- `L1-06`: SoD. User/process evidence may be case/user-level; document row display should be treated as context.
- `L1-07`: missing approval. Usually document-level; representative row is acceptable if approval fields are stable across document rows.
- `L1-08`: fiscal period mismatch. Usually document-level; expected/actual should be recomputed from posting date and fiscal period.
- `L1-09`: approval date missing. Usually document-level; representative row is acceptable if approval fields are stable.
- `L2-04`: expense capitalization. Needs specific asset/expense account rows in the same document; representative `gl_account` alone is weak.
- `L3-01`: process/account mismatch. Row-specific, but restored batches can move the evidence to first row.
- `L3-04`, `L3-07`, `L3-11`: timing rules. Mostly document-level date fields; representative row is acceptable if dates are document-level stable.
- `L3-09`, `L3-10`: sensitive/unsettled accounts. Row-specific; must keep the actual account row.
- `L4-01`, `L4-03`, `L4-04`: statistical/rare-account transaction details. Need the actual scored row/account or derived score metadata, not a generic first row.

### Lower Risk / Context-Only Rules

These are intentionally not standalone transaction-detail rules in metadata, or should be displayed as context badges:

- `L3-03`, `L3-05`, `L3-06`, `L3-08`, `L3-12`, `L4-05`, `L4-06`
- `GR01`, `GR03`

Risk remains if the topic UI presents them through the generic rule master/detail path despite `allow_row_violation_detail=False`.

### Fix Order

1. Add tests for L1-01 balanced/non-balanced documents:
   - A balanced document with `L1-02` in the same case must not appear in L1-01 document master.
   - L1-01 master columns must show document debit total, credit total, and difference.
2. Fix `build_phase1_rule_case_doc_map()` to map case IDs to raw-hit documents for the requested canonical rule.
3. Add a document evidence aggregation path in `build_phase1_rule_documents()`:
   - For document-level rules, compute display fields from `doc_rows`.
   - For row-level rules, keep the actual hit row.
   - For pair/sidecar/macro rules, use sidecar/raw-hit metadata or keep row detail disabled.
4. Fix DB restored batch reconstruction to use `(document_id, line_number)` when available, falling back to first row only if line number is missing.
5. Re-run/reload batches after the view and restore fixes.
