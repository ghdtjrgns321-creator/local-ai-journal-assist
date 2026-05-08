# DataSynth Patch Workflow

> **PHASE1 역할 원칙**: PHASE1은 `fraud`를 확정하거나 정답 라벨을 맞히는 단계가 아니다. PHASE1의 목적은 전수 모집단에서 규칙 위반, 정책 위반, 이상 징후, 분석적 검토 신호를 넓게 올려 **감사인이 봐야 할 항목과 우선순위**를 만드는 것이다. DataSynth의 `is_fraud`/`is_anomaly`와 precision/recall은 개발 검증 보조 지표이며, 운영 해석은 예외 처리 대상, 감사인 리뷰 대상, 고위험 후보를 구분하는 review queue 기준으로 한다.
Current production baseline: `data/journal/primary/datasynth/` freeze `v126` as of `2026-05-02`.

This document defines the required workflow for future DataSynth patches. The goal is to avoid slow, risky full rewrites for every small fix.

## Principle

Do not rewrite 1.1M-row journal CSVs at every analysis step.

Use this order instead:

1. Diagnose.
2. Build a patch manifest.
3. Validate the manifest against the current production baseline.
4. Materialize a candidate once.
5. Validate the materialized candidate.
6. Promote only by explicit instruction.

Do not start a new patch from an unvalidated or interrupted candidate.

## Why

The production DataSynth files are large:

- `journal_entries.csv`: combined 1.1M-row file.
- `journal_entries_2022.csv`, `journal_entries_2023.csv`, `journal_entries_2024.csv`: year splits.
- `labels/anomaly_labels.csv/json/jsonl`: label sidecars.

Rewriting these files repeatedly causes:

- long runtime for small patches,
- partially written candidates if interrupted,
- higher risk of mismatch between combined and year files,
- unnecessary churn in generated files,
- harder debugging because the actual intended change is buried in full-file rewrites.

## Required Patch Flow

### 0. Choose The Source Baseline

Every patch must explicitly declare its source baseline.

Allowed source baselines:

- current production freeze, for example `data/journal/primary/datasynth/` freeze `v126`,
- a validated candidate with passing validation JSON,
- a manifest chain that has been explicitly declared as cumulative.

Not allowed:

- interrupted candidate directories,
- partially materialized candidates,
- scratch copies,
- old candidates whose validation contract is weaker than the current production contract,
- candidates that were built by fitting directly to detector outputs without an independent generation rationale.

Rule for sequential patch numbers:

- `vXX_candidate` should normally be based on the current production freeze unless the previous candidate has passed all required gates.
- `v61_candidate` may be based on `v60_candidate` only if `v60_candidate` is validated and explicitly marked as the source baseline.
- If a candidate is not validated, the next candidate must restart from the current production freeze plus only validated patch manifests.
- Never assume `v61` automatically includes `v60` just because the version number is higher.

Every `FREEZE_VXX_CANDIDATE.md` must include:

- `Source baseline`
- `Included prior manifests`
- `Excluded prior candidates`
- `Validation status`
- `Promotion status`

### 1. Audit First

Create or run a small audit script that reads only required columns with `usecols`.

The audit output must answer:

- which rule or label contract is affected,
- which files are affected,
- which `document_id` or row keys are affected,
- whether this is a generator/config issue, label issue, or materialized data issue,
- whether production data must be rewritten or a sidecar/config patch is enough.

Audit output should be written as:

- `data/journal/primary/datasynth_vXX_patch_manifest/audit.json`, or
- `data/journal/primary/datasynth_vXX_candidate/VXX_AUDIT.json` if the candidate already exists.

### 2. Patch Manifest Before Data Rewrite

Before touching large CSVs, create a manifest file that contains the exact intended changes.

Recommended files:

- `patch_manifest.csv`
- `patch_manifest.json`
- `PATCH_PLAN.md`

Minimum manifest columns:

- `patch_id`
- `rule_id`
- `anomaly_type`
- `document_id`
- `line_number` if row-level
- `field_name`
- `old_value`
- `new_value`
- `reason`
- `source_file`
- `expected_validation`

For sidecar-only patches, the manifest must still describe why the source journal does not need to change.

For cumulative patches, create a manifest chain file:

- `included_manifests.json`
- `manifest_chain.md`

It must list every prior manifest that is intentionally included. This prevents the common failure mode where a later candidate silently drops an earlier hotfix.

### 3. Validate Manifest Against Source

Before materializing:

- Every `document_id` in the manifest must exist in the current source baseline.
- Every `old_value` must match the current source value.
- Row-level patches must identify rows deterministically with `document_id + line_number` or another stable key.
- The patch must not modify label columns inside ML input features unless the patch explicitly targets source truth fields.
- For label contract fixes, confirm the target rule owns the label meaning.

If any old value does not match, stop. Do not guess.

For cumulative patches:

- validate each included manifest in order,
- verify that no later manifest overwrites an earlier manifest unintentionally,
- record intentional overrides explicitly with `override_reason`.

### 4. Materialize Once

Only after the manifest is stable, materialize a candidate:

- Copy production baseline to `data/journal/primary/datasynth_vXX_candidate/`.
- Apply the manifest once.
- Rewrite only files that actually changed.
- If journal rows change, update both combined and affected year files in the same run.
- If labels change, update `anomaly_labels.csv/json/jsonl/summary` in the same run.
- Write `FREEZE_VXX_CANDIDATE.md`.

Do not promote to `data/journal/primary/datasynth/` during candidate materialization.

### 5. Validate Candidate

Candidate validation must run after materialization.

Required checks:

- row counts match expected values,
- year split row counts sum to combined row count,
- `document_id + line_number` uniqueness is preserved,
- debit/credit balance is not accidentally changed except for explicit `UnbalancedEntry` truth,
- label counts match expected values,
- new sidecar counts match the manifest,
- rule-specific contract check passes,
- `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_vXX_candidate` passes when applicable.
- if the candidate is based on a prior candidate, run the regression form:
  `python tools/scripts/check_datasynth_required_truth.py data/journal/primary/datasynth_vXX_candidate --previous data/journal/primary/datasynth_vYY_candidate`

The validation output must be written to a JSON file in the candidate directory.

Candidate validation status must be binary:

- `valid_candidate=true`: all required validation checks passed.
- `valid_candidate=false`: interrupted, failed, or unverified.

Do not use ambiguous wording such as "probably OK" or "partially passed" for candidate lineage.

### 6. Promote Separately

Promotion is a separate step.

Only promote after:

- the user explicitly requests promotion,
- candidate validation passes,
- required docs are updated,
- storage cleanup policy is checked.

Promotion updates:

- `data/journal/primary/datasynth/`
- `data/journal/primary/datasynth/PREVIEW.md`
- `data/journal/primary/datasynth/FREEZE_VXX.md`
- `data/journal/OVERVIEW.md`
- project docs listed in `docs/DATASYNTH_UPDATE_CHECKLIST.md`

## Safe Cases For Manifest-First Patching

This workflow is safe for:

- label metadata fixes,
- sidecar additions,
- small document-level field patches,
- CoA boundary fixes,
- approval master backfills,
- row-level label contract repairs,
- quality gate metadata updates.

It is also safer than full regeneration when preserving previously accumulated patches matters.

## Anti-Fitting Rules

DataSynth patches must not simply make a detector produce perfect TP/FP/FN numbers.

Allowed:

- fixing label-field contradictions,
- adding missing truth coverage for a rule that had no evaluable examples,
- adding normal controls and review populations,
- aligning a label contract with a business definition,
- preserving realistic ambiguity where a rule should produce review candidates.

Not allowed:

- changing synthetic data only so one detector gets FP=0/FN=0,
- deriving labels directly from the detector output and calling them ground truth,
- removing all hard negative controls because they lower precision,
- making every anomaly case satisfy one clean obvious pattern,
- making all annual counts identical for convenience,
- adding sidecar flags that would not exist in real company data and then using them as model features.

When a detector result motivates a patch, the patch must be restated as a business/data-generation issue.

Example:

- Bad: "L3-07 has FP, remove those rows."
- Good: "Add normal long-delay posting controls with documented business reasons so L3-07 precision can be interpreted separately from confirmed late-posting truth."

## Realism Rules

Synthetic data should be testable but not too clean.

Required realism principles:

- Yearly counts should vary unless the count is a fixed structural fixture.
- Ratios should be sampled from ranges, not copied exactly across 2022/2023/2024.
- Company/year profiles should affect missingness, process mix, approval behavior, source distribution, and anomaly mix.
- Confirmed anomalies, review populations, and normal controls must be separated.
- Boundary cases must exist near rule thresholds.
- Hard negatives must exist when the real world has plausible normal lookalikes.
- Metadata should explain generation rationale, but Phase 2 input features must not include answer leakage.

Examples of acceptable variation:

- `ApprovalDateMissing`: `7 / 9 / 10` is better than `8 / 8 / 8`.
- `DuplicatePayment`: different yearly counts and variants are better than equal counts per year.
- Fraud/anomaly rates should vary by company-year profile.
- Text templates should vary by process and year.

Fixed equal counts are allowed only when:

- the sidecar is a tiny smoke-test fixture,
- the file clearly says it is a contract test, not a realism benchmark,
- it is excluded from model generalization claims.

## Truth Layer Rules

Keep these concepts separate:

- `rule_truth`: all records a Phase 1 rule should catch, including review candidates when the rule is designed to surface them.
- `audit_issue_truth`: subset that should be treated as meaningful audit issues for portfolio/priority benchmarks.
- `field_contract_truth`: exact field-condition truth used to verify rule implementation contracts.
- `confirmed_anomaly`: intended positive truth.
- `review_population`: broad queue a rule should surface for auditor review.
- `normal_control`: plausible normal lookalike.
- `boundary_control`: near-threshold normal or ambiguous case.
- `contract_fixture`: small deterministic fixture for implementation checks.

Do not evaluate every `rule_truth`, `field_contract_truth`, or `review_population` item as a confirmed audit issue. But for Phase 1 contract testing, review candidates are still positives when the rule is expected to catch them.

Do not train Phase 2 on sidecar-only truth fields as input features.

Document-level labels are not always valid for group-level rules. For group-level rules such as Benford, D01, and D02, truth must be stored at the correct group level.

Starting with v70-style candidates, `labels/anomaly_labels.csv` may represent `audit_issue_truth`.
In that mode exact L1 field contracts must be preserved separately in `labels/field_contract_truth.csv`.

## Patch Numbering And Lineage

Patch numbers are not enough to prove lineage.

Each candidate must include a lineage block:

```yaml
candidate_version: vXX
source_baseline: data/journal/primary/datasynth@vYY
included_manifests:
  - vAA_patch_manifest/name.json
  - vBB_patch_manifest/name.json
excluded_candidates:
  - datasynth_vZZ_candidate
validation_status: pass|fail|not_run
promotion_status: candidate_only|promoted
```

If a patch is abandoned:

- mark its candidate as invalid or remove it,
- keep the manifest only if it is useful,
- state that the next patch restarts from the last valid baseline.

This avoids the failure mode where `v61` accidentally drops `v60` or inherits a broken partial `v60`.

## Risks And Controls

| Risk | Control |
|---|---|
| Manifest says one thing but CSV has another | Validate `old_value` before applying |
| Combined file and year files diverge | Materialize both in one script and compare row counts |
| Partial candidate after interruption | Treat candidate as invalid until validation JSON exists and passes |
| Sidecar and labels diverge | Validate sidecar document IDs against `anomaly_labels.csv` and journal files |
| Patch overfits detector output | Record business rule contract and generation rationale in `PATCH_PLAN.md` |
| Huge rewrite hides actual change | Keep `patch_manifest.csv/json` as the audit trail |
| Later patch drops earlier fix | Maintain `included_manifests.json` and validate manifest chain |
| Equal yearly counts look synthetic | Use year/company range sampling unless fixture-only |
| Ground truth leaks into ML features | Keep sidecars physically separate from model input features |

## Required Truth Gate

`tools/scripts/check_datasynth_required_truth.py` is the promotion gate for accumulated DataSynth truth.

It must fail on more than simple missing labels:

- required label/sidecar minimums,
- v70-style audit issue mode, where `anomaly_labels.csv` is audit issue truth and L1 contract checks use `field_contract_truth.csv`,
- L1-01 debit/credit arithmetic truth via `labels/l101_unbalanced_truth.csv`,
- L2-01 approver-limit near-threshold truth via `labels/l201_just_below_threshold_truth.csv`,
- L2 rule truth uses the full candidate population that Phase 1 should surface, not only confirmed anomaly subsets,
- combined vs yearly journal row-count divergence,
- duplicate `document_id + line_number`,
- L1-03/L3-01 CoA boundary contradictions,
- L1-05 `SelfApproval` rule truth:
  `created_by == approved_by`; system/automated exceptions are handled later by detector/scoring logic,
- `SelfApproval` sidecar mismatch against the same field contract,
- L1-04 `ExceededApprovalLimit` rule truth:
  `document_amount > approved_by.approval_limit`,
- `ExceededApprovalLimit` sidecar mismatch against the same approval-limit contract,
- L1-06 `SegregationOfDutiesViolation` rule truth:
  direct SoD conflict evidence only, such as a populated `sod_conflict_type` or `sod_violation=True` with conflict type. Role-threshold and process-breadth review candidates belong to L3-12/work-scope sidecar truth,
- L1-07 `SkippedApproval` rule truth:
  skipped approval, including review-required candidates,
- skipped-approval normal controls must not overlap confirmed labels,
- L1-09 `ApprovalDateMissing` rule truth:
  missing `approval_date`,
- automated/recurring missing approval-date cases are not removed from rule truth; later code decides review/normal handling,
- L1-08 `WrongPeriod` exact field contract:
  `fiscal_period != posting_date.month` under the current calendar-year fiscal-period contract,
- wrong-period confirmed sidecar must match the same field contract and normal controls must not overlap labels,
- L2-02 `DuplicatePayment` rule truth:
  duplicate-payment candidates including reference matches, fallback matches, and recurring-looking candidates that Phase 1 should surface,
- L2-03 `DuplicateEntry` rule truth:
  exact, document-shape, reference, near, and split duplicate-entry candidates,
- L2-04 `ExpenseCapitalization` rule truth:
  expense-to-asset capitalization candidates, including review-priority candidates,
- L2-05 `ReversalEntry` rule truth:
  reversal, cancellation, correction, clearing, offset, and reclassification candidates,
- optional previous-candidate truth count regression.

Use it this way before promotion:

```powershell
.venv\Scripts\python.exe tools\scripts\check_datasynth_required_truth.py data\journal\primary\datasynth_vXX_candidate --previous data\journal\primary\datasynth_vYY_candidate
```

If a label or sidecar count intentionally decreases, the patch must document the reason and pass an explicit allow-list:

```powershell
.venv\Scripts\python.exe tools\scripts\check_datasynth_required_truth.py data\journal\primary\datasynth_vXX_candidate --previous data\journal\primary\datasynth_vYY_candidate --allow-decrease SomeLabel
```

## Interrupted Runs

If a materialization run is interrupted:

- Do not use the candidate as a benchmark.
- Do not promote it.
- Re-run from the manifest after deleting or replacing the candidate directory.
- If deletion is needed, confirm the target path is exactly `data/journal/primary/datasynth_vXX_candidate/`.

An interrupted candidate is not a valid candidate even if some files exist.

## v60 Lesson

The v60 approval patch attempt showed that rewriting all journal and label outputs during each iteration is too slow.

Future v60 work should restart as:

1. `v60_patch_manifest/approval_master_audit.json`
2. `v60_patch_manifest/approval_master_patch_manifest.csv`
3. manifest validation
4. one candidate materialization
5. candidate validation

The partially materialized `datasynth_v60_candidate` must not be treated as trusted until it is rebuilt from a validated manifest.


